"""
Testes do cadastro de setores (2.0): regras, banco, rotas HTTP e
sincronizacao com a VPS. Tudo em pasta temporaria (reaproveita a preparacao
do test_backend: nunca abre o banco real nem inicia a leitura do ESP32).

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

from test_backend import TMP, novo_banco, servidor  # noqa: E402  (pasta temporaria + servidor de teste)

import nuvem  # noqa: E402
import setores  # noqa: E402
from setores import ErroSetor  # noqa: E402


class TesteRegrasSetores(unittest.TestCase):
    def test_slug_sem_acento_e_comecando_por_letra(self):
        self.assertEqual(setores.gerar_slug("Costura Reta 2"), "costura-reta-2")
        self.assertEqual(setores.gerar_slug("  Ação & Corte!! "), "acao-corte")
        self.assertEqual(setores.gerar_slug("2 Galpão"), "galpao")
        self.assertEqual(setores.gerar_slug("!!!"), "")

    def test_banco_novo_ou_vindo_da_1x_ja_tem_o_setor_inicial(self):
        b = novo_banco()
        lista = b.listar_setores()
        self.assertEqual([s["setor"] for s in lista], ["enfestadeiras"])
        self.assertEqual(lista[0]["tipoColeta"], "multi")
        self.assertTrue(lista[0]["ativo"])
        # reabrir nao duplica nem recria
        setores.editar(b, {"setor": "enfestadeiras", "nome": "Enfesto"})
        b2 = type(b)(b.caminho)
        self.assertEqual([s["nome"] for s in b2.listar_setores()], ["Enfesto"])

    def test_criar_editar_e_slug_que_nunca_muda(self):
        b = novo_banco()
        s = setores.criar(b, {"nome": "Costura", "tipoColeta": "unitario"})
        self.assertEqual((s["setor"], s["tipoColeta"], s["ordem"]), ("costura", "unitario", 1))
        s = setores.editar(b, {"setor": "costura", "nome": "Costura Reta"})
        self.assertEqual((s["setor"], s["nome"]), ("costura", "Costura Reta"))
        # nome que gera o mesmo slug de um existente ganha sufixo
        self.assertEqual(setores.criar(b, {"nome": "Costura!"})["setor"], "costura-2")

    def test_pedidos_invalidos(self):
        b = novo_banco()
        for dados in ({"nome": ""}, {"nome": "   "}, {"nome": "!!!"}, {"nome": "X", "tipoColeta": "outro"},
                      {"nome": "enfestadeiras"}):  # mesmo nome (sem diferenciar maiusculas)
            with self.subTest(dados=dados), self.assertRaises(ErroSetor):
                setores.criar(b, dados)
        with self.assertRaises(ErroSetor):
            setores.editar(b, {"setor": "nao-existe", "nome": "X"})

    def test_sempre_fica_um_setor_ativo(self):
        b = novo_banco()
        with self.assertRaises(ErroSetor):
            setores.editar(b, {"setor": "enfestadeiras", "ativo": False})
        setores.criar(b, {"nome": "Costura"})
        setores.editar(b, {"setor": "enfestadeiras", "ativo": False})
        self.assertEqual(setores.setor_padrao(b), "costura")
        self.assertEqual([s["setor"] for s in b.listar_setores(incluir_inativos=False)], ["costura"])

    def test_setor_com_dados_so_pode_ser_desativado(self):
        b = novo_banco()
        setores.criar(b, {"nome": "Costura"})
        b.gravar_ciclo("enfestadeiras", 1, 1, "?", "?", 5.0, "")
        with self.assertRaises(ErroSetor):
            setores.apagar(b, "enfestadeiras")
        self.assertEqual(b.total_ciclos("enfestadeiras"), 1)  # nada foi apagado
        b.salvar_turnos("costura", [{"nome": "T1", "inicio": "06:00", "fim": "14:00"}])
        setores.apagar(b, "costura")  # sem ciclos nem maquinas: pode
        self.assertIsNone(b.obter_setor("costura"))
        self.assertEqual(b.obter_turnos("costura"), [])
        with self.assertRaises(ErroSetor):  # o ultimo nunca
            setores.apagar(b, "enfestadeiras")

    def test_resolver_setor_pedido(self):
        b = novo_banco()
        self.assertEqual(setores.resolver(b, ""), "enfestadeiras")
        self.assertEqual(setores.resolver(b, "enfestadeiras"), "enfestadeiras")
        self.assertIsNone(setores.resolver(b, "nao-existe"))

    def test_lista_recebida_nao_apaga_setor_com_dados(self):
        b = novo_banco()
        setores.criar(b, {"nome": "Costura"})
        setores.criar(b, {"nome": "Corte"})
        b.salvar_maquina("costura", 1, "Reta 1", 0)
        setores.aplicar_lista(b, [{"setor": "enfestadeiras", "nome": "Enfestadeiras", "tipoColeta": "multi",
                                   "ordem": 0, "ativo": True},
                                  {"setor": "nova", "nome": "Nova", "tipoColeta": "unitario", "ordem": 3, "ativo": True},
                                  {"setor": "_geral", "nome": "invalido"}])
        nomes = {s["setor"] for s in b.listar_setores()}
        self.assertEqual(nomes, {"enfestadeiras", "costura", "nova"})  # corte (vazio) saiu; costura (com maquina) ficou


class TesteSincronizacaoSetores(unittest.TestCase):
    def test_setor_criado_no_notebook_chega_a_vps_e_volta(self):
        nb, vps = novo_banco(), novo_banco()
        dir_vps = tempfile.mkdtemp(dir=TMP)
        nuvem.alterar_setores(nb, "criar", {"nome": "Costura", "tipoColeta": "unitario"}, "notebook", "notebook")
        pend = {p["chave"]: p for p in nb.pendentes()}
        self.assertIn("setores", pend)
        corpo = {"versao": 2, "rev_conhecida": 0, "itens": {"setores": {
            "valor": nuvem.itens_atuais(nb, "enfestadeiras")["setores"], "base_rev": pend["setores"]["rev"],
            "editado_em": pend["setores"]["editado_em"]}}}
        r = nuvem.sincronizar_config(vps, dir_vps, corpo, "enfestadeiras")
        self.assertIn("setores", r["aceitos"])
        self.assertEqual(vps.obter_setor("costura")["tipoColeta"], "unitario")
        self.assertTrue(any(a["chave"] == "setores" for a in vps.ultimas_alteracoes()))
        # editado na VPS (senha de edicao): o notebook recebe na proxima troca
        rev = r["rev_atual"]
        nuvem.alterar_setores(vps, "editar", {"setor": "costura", "nome": "Costura Reta"}, "nuvem", "edição remota")
        r = nuvem.sincronizar_config(vps, dir_vps, {"versao": 2, "rev_conhecida": rev, "itens": {}}, "enfestadeiras")
        self.assertEqual(next(s for s in r["itens"]["setores"]["valor"] if s["setor"] == "costura")["nome"], "Costura Reta")
        nuvem.gravar_item(nb, "enfestadeiras", "setores", r["itens"]["setores"]["valor"])
        self.assertEqual(nb.obter_setor("costura")["nome"], "Costura Reta")


class TesteConfigPorSetor(unittest.TestCase):
    def test_chaves_com_setor(self):
        self.assertEqual(nuvem.separar_chave("costura/maquina:3"), ("costura", "maquina:3"))
        self.assertEqual(nuvem.separar_chave("turnos"), ("enfestadeiras", "turnos"))
        self.assertEqual(nuvem.separar_chave("setores"), (None, "setores"))
        for invalida in ("enfestadeiras/turnos", "costura/setores", "costura/extras:visual", "Costura/turnos",
                         "costura/maquina:100", "x/y/turnos", ""):
            with self.subTest(chave=invalida):
                self.assertFalse(nuvem.chave_item_valida(invalida))
        self.assertEqual(nuvem.nome_item("costura/maquina:3"), "costura · Máquina 3")
        self.assertEqual(nuvem.nome_item("maquina:3"), "Máquina 3")

    def test_itens_de_todos_os_setores(self):
        b = novo_banco()
        setores.criar(b, {"nome": "Costura", "tipoColeta": "unitario"})
        b.salvar_maquina("enfestadeiras", 1, "E1", 10)
        b.salvar_maquina("costura", 1, "Reta 1", 2)
        b.salvar_turnos("costura", [{"nome": "T1", "inicio": "06:00", "fim": "14:00"}])
        from banco_dados import normalizar_extras
        b.salvar_extras("costura", normalizar_extras({"visual": {"empresa": "X"}, "motivos": {"catalogo": []}}))
        itens = nuvem.itens_atuais(b)
        self.assertEqual(itens["maquina:1"]["nome"], "E1")
        self.assertEqual(itens["costura/maquina:1"]["nome"], "Reta 1")
        self.assertIn("costura/turnos", itens)
        self.assertIn("costura/extras:motivos", itens)
        self.assertEqual(itens["extras:visual"], {"empresa": "X"})  # global: sem prefixo e uma vez so
        self.assertNotIn("costura/extras:visual", itens)

    def test_maquina_de_outro_setor_sincroniza_com_a_vps(self):
        nb, vps = novo_banco(), novo_banco()
        dir_vps = tempfile.mkdtemp(dir=TMP)
        nuvem.alterar_setores(nb, "criar", {"nome": "Costura", "tipoColeta": "unitario"}, "notebook", "notebook")
        nuvem.aplicar_config(nb, {"setor": "costura", "maquinas": {"12": {"nome": "Reta 12", "metrosPorMin": 1.5}}},
                             "enfestadeiras", origem="notebook", autor="notebook")
        atuais = nuvem.itens_atuais(nb)
        itens = {p["chave"]: {"valor": atuais[p["chave"]], "base_rev": p["rev"], "editado_em": p["editado_em"]}
                 for p in nb.pendentes()}
        self.assertEqual(set(itens), {"setores", "costura/maquina:12"})
        r = nuvem.sincronizar_config(vps, dir_vps, {"versao": 2, "rev_conhecida": 0, "itens": itens}, "enfestadeiras")
        self.assertEqual(set(r["aceitos"]), {"setores", "costura/maquina:12"})
        self.assertEqual(vps.obter_maquinas("costura")["12"]["nome"], "Reta 12")
        self.assertEqual(vps.obter_maquinas("enfestadeiras"), {})
        # editada na VPS: volta ao notebook pela chave com setor
        nuvem.aplicar_config(vps, {"setor": "costura", "maquinas": {"12": {"nome": "Reta Doze", "metrosPorMin": 1.5}}},
                             "enfestadeiras", origem="nuvem", autor="edição remota")
        r = nuvem.sincronizar_config(vps, dir_vps, {"versao": 2, "rev_conhecida": r["rev_atual"], "itens": {}},
                                     "enfestadeiras")
        self.assertEqual(list(r["itens"]), ["costura/maquina:12"])
        nuvem.gravar_item(nb, "enfestadeiras", "costura/maquina:12", r["itens"]["costura/maquina:12"]["valor"])
        self.assertEqual(nb.obter_maquinas("costura")["12"]["nome"], "Reta Doze")


class TesteHistoricoPorSetor(unittest.TestCase):
    """Historico e estado ao vivo de todos os setores chegam a uma VPS de
    verdade (processo separado, pasta temporaria)."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        import time
        from test_nuvem import CHAVE, RAIZ, porta_livre
        cls.chave = CHAVE
        cls.dados_vps = tempfile.mkdtemp(prefix="painel_vps_setores_", dir=TMP)
        porta = porta_livre()
        env = {**os.environ, "PAINEL_MODO": "nuvem", "PAINEL_DADOS": cls.dados_vps,
               "PAINEL_PORTA": str(porta), "NUVEM_CHAVE": CHAVE, "PYTHONIOENCODING": "utf-8"}
        cls.proc = subprocess.Popen([sys.executable, os.path.join(RAIZ, "ferramentas", "controle_leitura_server.py")],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{porta}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/assets/logo.png", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def total_na_vps(self, setor):
        req = urllib.request.Request(self.base + "/api/nuvem/historico", method="POST",
                                     data=json.dumps({"setor": setor, "ciclos": []}).encode(),
                                     headers={"Content-Type": "application/json", "X-Chave-Nuvem": self.chave})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["total"]

    def test_historico_e_ao_vivo_de_cada_setor(self):
        local = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(local, "nuvem.json"), "w", encoding="utf-8") as f:
            json.dump({"url": self.base, "chave": self.chave}, f)
        b = type(novo_banco())(os.path.join(local, "painel.db"))
        setores.criar(b, {"nome": "Costura", "tipoColeta": "unitario"})
        for i in range(1, 8):
            b.gravar_ciclo_remoto("enfestadeiras", "AA-11111111", i, 1, i, "?", "?", 10.0, "", "2026-12-01 08:00:00")
        for i in range(1, 6):
            b.gravar_ciclo_remoto("costura", f"ESP{i:02d}-SERIE{i:03d}", 1, 1, 1, "?", "?", 20.0, "", "2026-12-01 09:00:00")
        enviador = nuvem.EnviadorConfig(b, local, "enfestadeiras")
        self.assertEqual(enviador.enviar_historico(conferir=False), 12)
        self.assertEqual((self.total_na_vps("enfestadeiras"), self.total_na_vps("costura")), (7, 5))
        self.assertEqual(enviador.status()["historico"]["pendentes"], 0)
        # novo ciclo so na costura: so ele vai (cursor proprio por setor)
        b.gravar_ciclo_remoto("costura", "ESP09-SERIE009", 1, 1, 1, "?", "?", 20.0, "", "2026-12-01 10:00:00")
        self.assertEqual(enviador.enviar_historico(conferir=False), 1)
        self.assertEqual(self.total_na_vps("costura"), 6)
        # VPS "perdeu" a costura: a conferencia percebe e reenvia so o que falta
        import sqlite3
        con = sqlite3.connect(os.path.join(self.dados_vps, "painel.db"))
        con.execute("DELETE FROM ciclos WHERE setor = 'costura'")
        con.commit()
        con.close()
        enviador.enviar_historico(conferir=True)
        self.assertEqual((self.total_na_vps("enfestadeiras"), self.total_na_vps("costura")), (7, 6))
        # estado ao vivo da costura: o notebook e a unica fonte (laco rapido)
        from datetime import datetime
        b.atualizar_estado_ao_vivo("costura", 3, True, datetime.now().isoformat(timespec="seconds"))
        self.assertTrue(enviador.enviar_ao_vivo())
        vps = type(b)(os.path.join(self.dados_vps, "painel.db"))
        self.assertTrue(vps.obter_estado_ao_vivo("costura")["3"]["ligado"])
        # setor com nome invalido e recusado pela VPS
        req = urllib.request.Request(self.base + "/api/nuvem/historico", method="POST",
                                     data=json.dumps({"setor": "../x", "ciclos": []}).encode(),
                                     headers={"Content-Type": "application/json", "X-Chave-Nuvem": self.chave})
        with self.assertRaises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(erro.exception.code, 400)


class TesteRotasSetores(unittest.TestCase):
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

    def test_cadastro_pelo_painel_e_setor_por_pedido(self):
        st, r = self.pedir("/setores")
        self.assertEqual(st, 200)
        self.assertIn("enfestadeiras", [s["setor"] for s in r["setores"]])
        st, r = self.pedir("/setores", {"acao": "criar", "nome": "Tecelagem", "tipoColeta": "unitario"})
        self.assertEqual((st, r["setor"]["setor"]), (200, "tecelagem"))
        st, r = self.pedir("/setores", {"acao": "criar", "nome": "Tecelagem"})
        self.assertEqual(st, 400)
        self.assertIn("nome", r["erro"])
        # configuracao e ao vivo por setor; setor desconhecido = 404
        st, r = self.pedir("/config", {"setor": "tecelagem", "maquinas": {"7": {"nome": "Tear 7", "metrosPorMin": 1}}})
        self.assertEqual(st, 200)
        st, r = self.pedir("/config?setor=tecelagem")
        self.assertEqual((r["setor"], r["maquinas"]["7"]["nome"]), ("tecelagem", "Tear 7"))
        self.assertNotIn("7", self.pedir("/config?setor=enfestadeiras")[1]["maquinas"])
        self.assertEqual(self.pedir("/ao-vivo?setor=nao-existe")[0], 404)
        self.assertEqual(self.pedir("/config", {"setor": "nao-existe", "maquinas": {}})[0], 404)
        # com maquina cadastrada, so desativar
        self.assertEqual(self.pedir("/setores", {"acao": "apagar", "setor": "tecelagem"})[0], 400)
        st, r = self.pedir("/setores", {"acao": "editar", "setor": "tecelagem", "ativo": False})
        self.assertEqual((st, r["setor"]["ativo"]), (200, False))
        servidor.banco.apagar_setor("tecelagem")  # sem efeito: tem maquina
        self.assertIsNotNone(servidor.banco.obter_setor("tecelagem"))


if __name__ == "__main__":
    unittest.main()
