"""
Testes do cadastro de dispositivos (2.0, fase 2, etapa 2.2): registro no
contato, adocao, troca, liberar, bloquear, o ESP32 multi das Enfestadeiras
e as rotas /dispositivos. Pasta temporaria (preparacao do test_backend).

    python -m unittest discover -s testes -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_backend import TMP, novo_banco, servidor  # noqa: E402

import dispositivos  # noqa: E402
import nuvem  # noqa: E402
import setores  # noqa: E402
from dispositivos import ErroDispositivo  # noqa: E402

A, B, C = "esp-24A1B2C3D4E5", "esp-24A1B2C3D4E6", "esp-24A1B2C3D4E7"


def banco_com_setor():
    b = novo_banco()
    setores.criar(b, {"nome": "Costura", "tipoColeta": "unitario"})
    return b


class TesteRegistro(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(dispositivos.normalizar_id("ESP-24a1b2c3d4e5"), A)
        self.assertEqual(dispositivos.normalizar_id("403fa83cfc3f-01fcb9d1"), "403FA83CFC3F-01FCB9D1")
        for ruim in ("", "esp-123", "esp-24A1B2C3D4EZ", "AA-S1", "../x", None):
            with self.subTest(ruim=ruim):
                self.assertIsNone(dispositivos.normalizar_id(ruim))

    def test_primeiro_contato_cria_novo_e_atualiza_saude(self):
        b = banco_com_setor()
        d = dispositivos.registrar_contato(b, A.lower(), "unitario", "4.0.0", "10.20.0.41",
                                           {"rssi": -63, "bssid": "A8:42:A1:00:00:02", "heap": 142000, "lixo": [1]})
        self.assertEqual((d["dispositivo"], d["situacao"], d["rssi"], d["firmware"]), (A, "novo", -63, "4.0.0"))
        self.assertEqual(d["saude"], {"rssi": -63, "bssid": "A8:42:A1:00:00:02", "heap": 142000})  # so valores simples
        self.assertFalse(dispositivos.sem_sinal(d))
        self.assertIsNone(dispositivos.registrar_contato(b, "invalido", "unitario"))
        self.assertIsNone(dispositivos.registrar_contato(b, B, "outro-perfil"))

    def test_limite_de_aparelhos_novos(self):
        b = banco_com_setor()
        antes = dispositivos.MAX_NOVOS
        dispositivos.MAX_NOVOS = 2
        try:
            self.assertIsNotNone(dispositivos.registrar_contato(b, A, "unitario"))
            self.assertIsNotNone(dispositivos.registrar_contato(b, B, "unitario"))
            self.assertIsNone(dispositivos.registrar_contato(b, C, "unitario"))
            self.assertIsNotNone(dispositivos.registrar_contato(b, A, "unitario"))  # ja conhecido: sempre atualiza
        finally:
            dispositivos.MAX_NOVOS = antes

    def test_esp32_multi_entra_ativo_e_nao_duplica_pela_serie(self):
        b = novo_banco()
        d = dispositivos.registrar_multi(b, "403FA83CFC3F-01FCB9D1", "enfestadeiras", firmware="3.2")
        self.assertEqual((d["situacao"], d["setor"], d["perfil"]), ("ativo", "enfestadeiras", "multi"))
        # mesmo controlador com a parte do MAC diferente (ja aconteceu): mesmo registro
        dispositivos.registrar_multi(b, "403F07000000-01FCB9D1", "enfestadeiras", firmware="3.2")
        self.assertEqual([x["dispositivo"] for x in b.listar_dispositivos()], ["403FA83CFC3F-01FCB9D1"])
        # nunca levanta excecao (caminho da leitura de producao)
        self.assertIsNone(dispositivos.registrar_multi(object(), "403FA83CFC3F-01FCB9D1", "enfestadeiras"))

    def test_vps_registra_o_esp32_que_envia_direto(self):
        b = novo_banco()
        pasta = tempfile.mkdtemp(dir=TMP)
        nuvem.receber_do_esp(b, pasta, "enfestadeiras", {"dispositivo": "403FA83CFC3F-01FCB9D1", "firmware": "3.2",
                                                         "ciclos": "1,1,1,?,?,5.0,", "maquinas": []}, ip="1.2.3.4")
        d = b.obter_dispositivo("403FA83CFC3F-01FCB9D1")
        self.assertEqual((d["situacao"], d["setor"], d["firmware"]), ("ativo", "enfestadeiras", "3.2"))


class TesteAdocao(unittest.TestCase):
    def setUp(self):
        self.b = banco_com_setor()
        for d in (A, B, C):
            dispositivos.registrar_contato(self.b, d, "unitario")

    def test_adotar_trocar_liberar(self):
        b = self.b
        d = dispositivos.adotar(b, A, "costura", 7, "notebook")
        self.assertEqual((d["situacao"], d["setor"], d["maquina"]), ("ativo", "costura", 7))
        self.assertEqual(b.dispositivo_da_maquina("costura", 7)["dispositivo"], A)
        with self.assertRaises(ErroDispositivo):  # maquina ocupada
            dispositivos.adotar(b, B, "costura", 7)
        with self.assertRaises(ErroDispositivo):  # ja adotado
            dispositivos.adotar(b, A, "costura", 8)
        # aparelho queimado: B assume a maquina 7, A vira reserva
        d = dispositivos.trocar(b, A, B, "notebook")
        self.assertEqual((d["dispositivo"], d["maquina"]), (B, 7))
        self.assertEqual(b.obter_dispositivo(A)["situacao"], "reserva")
        hist = b.atribuicoes(setor="costura", maquina=7)
        self.assertEqual([h["dispositivo"] for h in hist], [A, B])
        self.assertIsNotNone(hist[0]["ate"])
        self.assertIsNone(hist[1]["ate"])
        # reserva pode ser adotado em outra maquina
        self.assertEqual(dispositivos.adotar(b, A, "costura", 9)["maquina"], 9)
        d = dispositivos.liberar(b, B)
        self.assertEqual((d["situacao"], d["maquina"]), ("reserva", None))
        self.assertIsNone(b.dispositivo_da_maquina("costura", 7))

    def test_pedidos_invalidos(self):
        b = self.b
        for args in ((A, "nao-existe", 1), (A, "costura", 0), (A, "costura", 65), (A, "costura", "x"),
                     ("esp-000000000000", "costura", 1)):
            with self.subTest(args=args), self.assertRaises(ErroDispositivo):
                dispositivos.adotar(b, *args)
        dispositivos.registrar_multi(b, "403FA83CFC3F-01FCB9D1", "enfestadeiras")
        with self.assertRaises(ErroDispositivo):  # multi nao e adotado por maquina
            dispositivos.adotar(b, "403FA83CFC3F-01FCB9D1", "costura", 1)
        with self.assertRaises(ErroDispositivo):
            dispositivos.executar(b, "voar", {})

    def test_bloquear_libera_a_maquina(self):
        b = self.b
        dispositivos.adotar(b, A, "costura", 3)
        d = dispositivos.bloquear(b, A)
        self.assertEqual((d["situacao"], d["maquina"]), ("bloqueado", None))
        self.assertIsNone(b.dispositivo_da_maquina("costura", 3))
        with self.assertRaises(ErroDispositivo):
            dispositivos.adotar(b, A, "costura", 3)
        self.assertEqual(dispositivos.desbloquear(b, A)["situacao"], "novo")
        self.assertEqual(dispositivos.renomear(b, A, "  Reta   3  ")["apelido"], "Reta 3")

    def test_setor_com_aparelho_nao_pode_ser_apagado(self):
        b = self.b
        dispositivos.adotar(b, A, "costura", 1)
        dispositivos.liberar(b, A)  # mesmo liberado, o historico de atribuicoes fica
        with self.assertRaises(setores.ErroSetor):
            setores.apagar(b, "costura")


class TesteAlertas(unittest.TestCase):
    def test_alertas_de_comunicacao(self):
        from datetime import datetime, timedelta
        b = banco_com_setor()
        ap1, ap2 = "A8:42:A1:00:00:01", "A8:42:A1:00:00:02"
        aparelhos = [(A, ap1, -60, {}), (B, ap1, -62, {}), (C, ap2, -80, {"flash_uso_pct": 70, "hora_valida": False})]
        for n, (d, ap, rssi, extra) in enumerate(aparelhos, start=1):
            dispositivos.registrar_contato(b, d, "unitario", saude={"bssid": ap, "rssi": rssi, **extra})
            dispositivos.adotar(b, d, "costura", n)
        dispositivos.registrar_contato(b, "esp-0000000000AA", "unitario")  # novo, esperando adocao
        tipos = lambda lista: sorted(a["tipo"] for a in lista)  # noqa: E731
        agora = datetime.now()
        self.assertEqual(tipos(dispositivos.alertas(b, agora)), ["flash", "novo", "relogio", "sinal_fraco"])
        # 2 min depois sem contato de ninguem: o AP1 (2 aparelhos) vira UM alerta de repetidor; C fica "sem sinal"
        depois = agora + timedelta(minutes=2)
        lista = dispositivos.alertas(b, depois)
        self.assertEqual(tipos(lista), ["flash", "novo", "relogio", "repetidor", "sem_sinal", "sinal_fraco"])
        self.assertEqual(next(a for a in lista if a["tipo"] == "sem_sinal")["dispositivo"], C)
        self.assertIn(ap1, next(a for a in lista if a["tipo"] == "repetidor")["texto"])
        # so B volta a falar: o AP1 nao esta mais todo fora -> A aparece sozinho como sem sinal
        d = b.obter_dispositivo(B)
        d["ultimo_contato"] = depois.isoformat(timespec="seconds")
        b.salvar_dispositivo(d)
        lista = dispositivos.alertas(b, depois)
        self.assertEqual(sorted(a["dispositivo"] for a in lista if a["tipo"] == "sem_sinal"), [A, C])
        self.assertNotIn("repetidor", tipos(lista))


class TesteRotasDispositivos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor._ServidorExclusivo(("::1", 0), servidor.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://[::1]:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pedir(self, caminho, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + caminho, data=dados, method="POST" if dados else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_adotar_pelo_painel_cadastra_a_maquina(self):
        b = servidor.banco
        if not b.obter_setor("bordado"):
            setores.criar(b, {"nome": "Bordado", "tipoColeta": "unitario"})
        dispositivos.registrar_contato(b, "esp-AABBCCDDEE01", "unitario", "4.0.0")
        st, r = self.pedir("/dispositivos")
        self.assertEqual(st, 200)
        self.assertTrue(r["podeAlterar"])
        self.assertIn("esp-AABBCCDDEE01", [d["dispositivo"] for d in r["dispositivos"]])
        st, r = self.pedir("/dispositivos", {"acao": "renomear", "dispositivo": "esp-AABBCCDDEE01", "apelido": "Bordadeira 5"})
        self.assertEqual(st, 200)
        st, r = self.pedir("/dispositivos", {"acao": "adotar", "dispositivo": "esp-AABBCCDDEE01", "setor": "bordado", "maquina": 5})
        self.assertEqual((st, r["dispositivo"]["maquina"]), (200, 5))
        # a maquina 5 passou a existir no setor (com o apelido), pela configuracao (sincroniza com a VPS)
        self.assertEqual(b.obter_maquinas("bordado")["5"]["nome"], "Bordadeira 5")
        self.assertIn("bordado/maquina:5", {p["chave"] for p in b.pendentes()})
        st, r = self.pedir("/dispositivos", {"acao": "adotar", "dispositivo": "esp-AABBCCDDEE01", "setor": "bordado", "maquina": 6})
        self.assertEqual(st, 400)
        self.assertIn("adotado", r["erro"])


if __name__ == "__main__":
    unittest.main()
