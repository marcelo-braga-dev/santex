"""
Testes do recebimento dos coletores por push - POST /api/v2/coletor (2.0,
fase 2, etapa 2.3): assinatura por aparelho, anti-replay, aparelho nao
adotado, gravacao com setor/maquina do cadastro, ack e idempotencia.
Pasta temporaria (preparacao do test_backend); chave-mestra de teste.

    python -m unittest discover -s testes -v
"""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_backend import novo_banco, servidor  # noqa: E402

import dispositivos  # noqa: E402
import receptor_push as rp  # noqa: E402
import setores  # noqa: E402

MESTRA = "mestra-de-teste-0123456789abcdef"
ID = "esp-24A1B2C3D4E5"


class Cab(dict):
    def get(self, k, padrao=None):
        return super().get(k, padrao)


def pedido(dispositivo=ID, ciclos=None, estado=None, ts=None, mestra=MESTRA, **extra):
    corpo = json.dumps({"v": 2, "dispositivo": dispositivo, "firmware": "4.0.0", "perfil": "unitario", "seq": 1,
                        "ciclos": ciclos or [], "estado": estado or [], "saude": {"rssi": -60}, **extra}).encode()
    ts = int(time.time()) if ts is None else ts
    cab = Cab({"X-Ts": str(ts), "X-Assinatura": rp.assinar(rp.chave_do_aparelho(mestra, dispositivo.upper().replace("ESP-", "esp-")), ts, corpo)})
    return cab, corpo


class TesteAssinatura(unittest.TestCase):
    def test_chave_por_aparelho(self):
        a, b = rp.chave_do_aparelho(MESTRA, ID), rp.chave_do_aparelho(MESTRA, "esp-24A1B2C3D4E6")
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, b)  # a chave de um aparelho nao serve para outro
        self.assertEqual(a, rp.chave_do_aparelho(MESTRA, ID))

    def test_autenticar(self):
        cab, corpo = pedido()
        dados, disp = rp.autenticar(cab, corpo, MESTRA)
        self.assertEqual((disp, dados["firmware"]), (ID, "4.0.0"))
        casos = [
            ("sem mestra", lambda: rp.autenticar(cab, corpo, ""), 503),
            ("corpo alterado", lambda: rp.autenticar(cab, corpo.replace(b"4.0.0", b"4.0.1"), MESTRA), 401),
            ("outra mestra", lambda: rp.autenticar(*pedido(mestra="outra"), MESTRA), 401),
            ("JSON", lambda: rp.autenticar(cab, b"{x", MESTRA), 400),
            ("versao", lambda: rp.autenticar(*pedido(v=1), MESTRA), 400),
            ("id", lambda: rp.autenticar(*pedido(dispositivo="AA-1"), MESTRA), 400),
            ("sem ts", lambda: rp.autenticar(Cab({"X-Assinatura": cab["X-Assinatura"]}), corpo, MESTRA), 401),
        ]
        for nome, f, status in casos:
            with self.subTest(nome), self.assertRaises(rp.ErroColetor) as e:
                f()
            self.assertEqual(e.exception.status, status)

    def test_relogio_fora_da_janela_devolve_a_hora(self):
        cab, corpo = pedido(ts=int(time.time()) - 600)
        with self.assertRaises(rp.ErroColetor) as e:
            rp.autenticar(cab, corpo, MESTRA)
        self.assertEqual((e.exception.status, e.exception.erro), (401, "relogio"))
        self.assertAlmostEqual(e.exception.resposta()["hora"], time.time(), delta=5)


class TesteProcessar(unittest.TestCase):
    def setUp(self):
        self.b = novo_banco()
        setores.criar(self.b, {"nome": "Costura", "tipoColeta": "unitario"})

    def enviar(self, **kw):
        dados, disp = rp.autenticar(*pedido(**kw), MESTRA)
        return rp.processar(self.b, dados, disp, "10.20.0.41")

    def test_nao_adotado_nao_grava_nada(self):
        st, r = self.enviar(ciclos=[[1, 1, 1, "2026-12-01 07:00:00", "2026-12-01 07:05:00", 300.0, ""]])
        self.assertEqual((st, r["adotado"], r["ack_ate"]), (200, False, 0))  # o ESP32 guarda os ciclos
        self.assertEqual(self.b.total_ciclos("costura"), 0)
        d = self.b.obter_dispositivo(ID)
        self.assertEqual((d["situacao"], d["ip"], d["rssi"]), ("novo", "10.20.0.41", -60))

    def test_adotado_grava_com_a_maquina_do_cadastro(self):
        self.enviar()
        dispositivos.adotar(self.b, ID, "costura", 12)
        ciclos = [[1501, 1, 88, "2026-12-01 07:02:10", "2026-12-01 07:09:44", 454.0, ""],
                  [1502, 1, 89, "2026-12-01 07:10:00", "2026-12-01 07:11:00", 60.0, "CURTO"]]
        st, r = self.enviar(ciclos=ciclos, estado=[{"canal": 1, "ligado": True, "segundos": 30}])
        self.assertEqual((st, r["adotado"], r["ack_ate"], r["gravados"]), (200, True, 1502, 2))
        self.assertAlmostEqual(r["hora"], time.time(), delta=5)
        csv = self.b.csv_do_setor("costura").splitlines()
        self.assertEqual(len(csv), 3)
        self.assertTrue(all(l.startswith("12,") for l in csv[1:]))  # maquina 12 (do cadastro), nao o canal 1
        self.assertIn("2026-12-01T07:09:44", csv[1])
        self.assertTrue(self.b.obter_estado_ao_vivo("costura")["12"]["ligado"])
        self.assertEqual(self.b.resumo("costura", "2026-12-01", "2026-12-01")[0]["ciclos"], 2)
        # reenviar o mesmo lote (resposta perdida): nada duplica, mesmo ack
        st, r = self.enviar(ciclos=ciclos)
        self.assertEqual((r["gravados"], r["ack_ate"], self.b.total_ciclos("costura")), (0, 1502, 2))
        # batimento sem ciclos: ack = o que ja esta guardado
        self.assertEqual(self.enviar()[1]["ack_ate"], 1502)

    def test_ciclo_invalido_e_confirmado_e_sem_hora_fica_sem_data(self):
        self.enviar()
        dispositivos.adotar(self.b, ID, "costura", 1)
        st, r = self.enviar(ciclos=[[7, 1, "x", "?", "?", 1.0, ""],
                                    [8, 1, 3, "1000", "61000", 60.0, "SEM_HORA"]])
        self.assertEqual((r["ignorados"], r["gravados"], r["ack_ate"]), (1, 1, 8))
        linha = self.b.csv_do_setor("costura").splitlines()[1]
        self.assertTrue(linha.endswith(","))  # sem hora real: registrado_em vazio
        self.assertEqual(self.b.resumo("costura", "2000-01-01", "2100-01-01"), [])  # fora do resumo

    def test_bloqueado_e_recusado(self):
        self.enviar()
        dispositivos.bloquear(self.b, ID)
        self.assertEqual(self.enviar()[0], 403)

    def test_lote_grande_demais(self):
        self.enviar()
        dispositivos.adotar(self.b, ID, "costura", 1)
        muitos = [[i, 1, i, "?", "?", 1.0, ""] for i in range(1, rp.MAX_CICLOS + 2)]
        self.assertEqual(self.enviar(ciclos=muitos)[0], 400)


class TesteRotaColetor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["COLETOR_CHAVE_MESTRA"] = MESTRA
        cls.srv = servidor._ServidorExclusivo(("::1", 0), servidor.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://[::1]:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.pop("COLETOR_CHAVE_MESTRA", None)

    def post(self, cab, corpo):
        req = urllib.request.Request(self.base + "/api/v2/coletor", data=corpo, method="POST",
                                     headers={"Content-Type": "application/json", **cab})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_fluxo_completo_pela_rede(self):
        b = servidor.banco
        disp = "esp-AABBCCDDEE77"
        if not b.obter_setor("malharia"):
            setores.criar(b, {"nome": "Malharia", "tipoColeta": "unitario"})
        st, r = self.post(*pedido(dispositivo=disp))
        self.assertEqual((st, r["adotado"]), (200, False))
        dispositivos.adotar(b, disp, "malharia", 3)
        st, r = self.post(*pedido(dispositivo=disp, ciclos=[[1, 1, 1, "2026-12-02 08:00:00", "2026-12-02 08:01:00", 60.0, ""]]))
        self.assertEqual((st, r["ack_ate"], r["gravados"]), (200, 1, 1))
        self.assertEqual(b.total_ciclos("malharia"), 1)
        # assinatura errada: 401, e muitas seguidas do mesmo IP bloqueiam
        cab, corpo = pedido(dispositivo=disp, mestra="errada")
        self.assertEqual(self.post(cab, corpo)[0], 401)
        servidor.limite_coletor._falhas.clear()

    def test_simulador_curto_sem_perda_nem_duplicacao(self):
        # versao curta de ferramentas/simulador_coletores.py: 6 aparelhos,
        # metade sem rede no meio, um com o relogio errado
        import simulador_coletores
        b = servidor.banco
        if not b.obter_setor("simulado-teste"):
            setores.criar(b, {"nome": "Simulado Teste", "tipoColeta": "unitario"})
        r = simulador_coletores.simular(self.base + "/api/v2/coletor", MESTRA, b, ["simulado-teste"], aparelhos=6,
                                        segundos=12, intervalo_s=1, queda=(0.3, 0.6), log=lambda *_: None, troca=(0.5, 2))
        self.assertGreater(r["ciclos_gerados"], 10)
        self.assertEqual((r["faltando"], r["duplicados"], r["na_flash_no_fim"]), (0, 0, 0), r)
        self.assertGreater(r["erros_rede"], 0)  # a queda aconteceu
        self.assertEqual(r["recusas_relogio"], 1)  # e o relogio errado foi acertado


if __name__ == "__main__":
    unittest.main()
