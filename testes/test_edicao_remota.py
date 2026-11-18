"""
Testes da edicao remota (app 1.2.0): VPS de verdade num processo separado
(PAINEL_MODO=nuvem, pasta temporaria) + um "notebook" simulado com banco
temporario. Nunca toca no banco real, no ESP32 nem em nenhuma VPS.

    python -m unittest discover -s testes -v
"""

import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "ferramentas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nuvem  # noqa: E402
from banco_dados import BancoDados  # noqa: E402
from test_nuvem import CHAVE, porta_livre  # noqa: E402

SETOR = "enfestadeiras"
SENHA_VER = "so-olhar-2026"
SENHA_EDITAR = "pode-editar-2026"


class TesteEdicaoRemota(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados_vps = tempfile.mkdtemp(prefix="painel_vps_edicao_")
        cls.porta = porta_livre()
        env = {**os.environ, "PAINEL_MODO": "nuvem", "PAINEL_DADOS": cls.dados_vps,
               "PAINEL_PORTA": str(cls.porta), "NUVEM_CHAVE": CHAVE, "PYTHONIOENCODING": "utf-8"}
        cls.proc = subprocess.Popen([sys.executable, os.path.join(RAIZ, "ferramentas", "controle_leitura_server.py")],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.porta}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/assets/logo.png", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        # o notebook (mestre): configura tudo e define as duas senhas, sem login
        cls.dir_nb = tempfile.mkdtemp(prefix="painel_nb_edicao_")
        with open(os.path.join(cls.dir_nb, "nuvem.json"), "w", encoding="utf-8") as f:
            json.dump({"url": cls.base, "chave": CHAVE}, f)
        cls.nb = BancoDados(os.path.join(cls.dir_nb, "painel.db"))
        nuvem.aplicar_config(cls.nb, {"maquinas": {"1": {"nome": "Norte", "metrosPorMin": 5},
                                                   "2": {"nome": "Sul", "metrosPorMin": 6}},
                                      "metaPctDia": 80}, SETOR, origem="notebook", autor="notebook")
        nuvem.definir_senha(cls.nb, "leitura", SENHA_VER)
        nuvem.definir_senha(cls.nb, "edicao", SENHA_EDITAR)
        cls.enviador = nuvem.EnviadorConfig(cls.nb, cls.dir_nb, SETOR)
        assert cls.enviador.enviar_agora(), cls.enviador.status()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.nb._conn.close()

    # -- ajudantes ---------------------------------------------------------
    def entrar(self, senha):
        con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        con.request("POST", "/login", urllib.parse.urlencode({"senha": senha}),
                    {"Content-Type": "application/x-www-form-urlencoded"})
        r = con.getresponse()
        r.read()
        con.close()
        return r.status, {"Cookie": (r.getheader("Set-Cookie") or "").split(";")[0]}

    def pedir(self, caminho, metodo="GET", corpo=None, cab=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json", **(cab or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}"), e.headers

    def editor(self):
        st, cab = self.entrar(SENHA_EDITAR)
        self.assertEqual(st, 303)
        return {**cab, "X-Painel-Edicao": "1"}

    def config_vps(self, cab):
        return self.pedir("/config", cab=cab)[1]

    # -- testes ----------------------------------------------------------------
    def test_1_papeis_pela_senha(self):
        st, leitor = self.entrar(SENHA_VER)
        self.assertEqual(st, 303)
        status = self.pedir("/status", cab=leitor)[1]
        self.assertEqual((status["papel"], status["podeEditar"]), ("leitura", False))
        st, corpo, _ = self.pedir("/config", "POST", {"metaPctDia": 50}, {**leitor, "X-Painel-Edicao": "1"})
        self.assertEqual((st, corpo["erro"]), (403, "somente_leitura"))
        self.assertNotIn("acessoRemoto", self.config_vps(leitor))
        ed = self.editor()
        status = self.pedir("/status", cab=ed)[1]
        self.assertEqual((status["papel"], status["podeEditar"]), ("edicao", True))
        cfg = self.config_vps(ed)
        self.assertTrue(cfg["acessoRemoto"]["edicaoDefinida"])
        self.assertNotIn("pbkdf2", json.dumps(cfg))  # hash nunca sai
        self.assertEqual(self.entrar("chute-errado")[0], 401)

    def test_2_csrf_sem_cabecalho_ou_de_outro_site(self):
        ed = self.editor()
        sem = {k: v for k, v in ed.items() if k != "X-Painel-Edicao"}
        self.assertEqual(self.pedir("/config", "POST", {"metaPctDia": 51}, sem)[0], 403)
        self.assertEqual(self.pedir("/config", "POST", {"metaPctDia": 51}, {**ed, "Origin": "https://malicioso.example"})[0], 403)
        self.assertEqual(self.pedir("/config", "POST", {"metaPctDia": 81}, {**ed, "Origin": self.base})[0], 200)
        st, _, cab = self.pedir("/status", cab=ed)
        self.assertIsNone(cab.get("Access-Control-Allow-Origin"))  # nada de CORS na VPS
        for rota in ("/iniciar", "/parar", "/conexao", "/esp/acao"):
            self.assertEqual(self.pedir(rota, "POST", {}, ed)[0], 403, rota)

    def test_3_edicao_na_vps_chega_ao_notebook_e_vice_versa(self):
        ed = self.editor()
        rev_antes = self.pedir("/status", cab=ed)[1]["configRev"]
        self.assertEqual(self.pedir("/config", "POST", {"maquinas": {"2": {"nome": "Sul editada", "metrosPorMin": 7}},
                                                        "turnos": [{"nome": "Manhã", "inicio": "06:00", "fim": "14:00"}]},
                                    ed)[0], 200)
        self.assertNotEqual(self.pedir("/status", cab=ed)[1]["configRev"], rev_antes)  # paineis recarregam
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.nb.obter_maquinas(SETOR)["2"]["nome"], "Sul editada")
        self.assertEqual(self.nb.obter_turnos(SETOR)[0]["inicio"], "06:00")
        self.assertTrue(any(a["chave"] == "maquina:2" and "recebido da nuvem" in a["resumo"]
                            for a in self.nb.ultimas_alteracoes()))
        # notebook (mestre) edita sem senha nenhuma -> chega a VPS
        nuvem.aplicar_config(self.nb, {"maquinas": {"1": {"nome": "Norte nova", "metrosPorMin": 5}}}, SETOR,
                             origem="notebook", autor="notebook")
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.config_vps(ed)["maquinas"]["1"]["nome"], "Norte nova")
        self.assertEqual(self.nb.pendentes(), [])
        auditoria = self.pedir("/alteracoes", cab=ed)[1]["alteracoes"]
        self.assertTrue(any(a["chave"] == "maquina:2" and a["origem"] == "nuvem" for a in auditoria))
        self.assertTrue(any(a["chave"] == "maquina:1" and a["origem"] == "notebook" for a in auditoria))

    def test_4_conflito_vale_o_mais_recente_e_itens_diferentes_nao_se_perdem(self):
        ed = self.editor()
        # notebook edita offline (antes) a meta e a maquina 1; a VPS edita a meta depois
        nuvem.aplicar_config(self.nb, {"metaPctDia": 70, "maquinas": {"1": {"nome": "Norte offline", "metrosPorMin": 5}}},
                             SETOR, origem="notebook", autor="notebook")
        time.sleep(0.01)
        self.assertEqual(self.pedir("/config", "POST", {"metaPctDia": 90}, ed)[0], 200)
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.nb.obter_meta_pct_dia(SETOR), 90)  # a VPS foi depois: venceu
        self.assertEqual(self.config_vps(ed)["metaPctDia"], 90)
        self.assertEqual(self.config_vps(ed)["maquinas"]["1"]["nome"], "Norte offline")  # o outro item subiu
        self.assertTrue(any("substituída" in a["texto"] and "Meta" in a["texto"] for a in self.enviador.avisos()))
        # agora o contrario: VPS edita antes, notebook depois -> notebook vence
        self.assertEqual(self.pedir("/config", "POST", {"metaPctDia": 60}, ed)[0], 200)
        time.sleep(0.01)
        nuvem.aplicar_config(self.nb, {"metaPctDia": 75}, SETOR, origem="notebook", autor="notebook")
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual((self.nb.obter_meta_pct_dia(SETOR), self.config_vps(ed)["metaPctDia"]), (75, 75))

    def test_5_troca_de_senha_pela_vps_exige_a_senha_atual(self):
        global SENHA_EDITAR
        ed = self.editor()
        st, corpo, _ = self.pedir("/config", "POST", {"senhaEdicao": "nova-edicao-2026"}, ed)
        self.assertEqual(st, 403)  # sem a senha atual (sessao roubada nao basta)
        st, corpo, _ = self.pedir("/config", "POST", {"senhaEdicao": "nova-edicao-2026", "senhaAtual": "errada"}, ed)
        self.assertEqual(st, 403)
        st, corpo, _ = self.pedir("/config", "POST", {"senhaEdicao": SENHA_VER, "senhaAtual": SENHA_EDITAR}, ed)
        self.assertEqual(st, 400)  # igual a de visualizacao
        st, corpo, cab = self.pedir("/config", "POST", {"senhaEdicao": "nova-edicao-2026", "senhaAtual": SENHA_EDITAR}, ed)
        self.assertEqual(st, 200)
        nova_sessao = {"Cookie": cab["Set-Cookie"].split(";")[0], "X-Painel-Edicao": "1"}
        self.assertEqual(self.pedir("/status", cab=ed)[0], 401)  # sessoes de edicao antigas cairam
        self.assertEqual(self.pedir("/status", cab=nova_sessao)[1]["papel"], "edicao")  # quem trocou segue
        self.assertEqual(self.entrar(SENHA_EDITAR)[0], 401)
        SENHA_EDITAR = "nova-edicao-2026"
        # chega ao notebook; o notebook segue podendo tudo e redefinir sem senha
        self.assertTrue(self.enviador.enviar_agora())
        self.assertTrue(nuvem.verificar_senha(SENHA_EDITAR, nuvem.dados_senha_edicao(self.nb)["hash"]))
        # a VPS nao liga/desliga a edicao remota
        self.assertEqual(self.pedir("/config", "POST", {"edicaoRemota": False}, nova_sessao)[0], 403)

    def test_6_notebook_desliga_a_edicao_remota(self):
        ed = self.editor()
        st, leitor = self.entrar(SENHA_VER)
        nuvem.definir_edicao_remota(self.nb, False)
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.pedir("/status", cab=ed)[0], 401)  # sessao de edicao derrubada
        self.assertEqual(self.entrar(SENHA_EDITAR)[0], 403)  # avisa que esta desligada
        self.assertEqual(self.pedir("/status", cab=leitor)[1]["papel"], "leitura")  # visualizacao segue
        # e o notebook continua editando normalmente
        nuvem.aplicar_config(self.nb, {"metaPctDia": 77}, SETOR, origem="notebook", autor="notebook")
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.config_vps(leitor)["metaPctDia"], 77)
        nuvem.definir_edicao_remota(self.nb, True)
        self.assertTrue(self.enviador.enviar_agora())
        self.assertEqual(self.entrar(SENHA_EDITAR)[0], 303)

    def test_7_formato_antigo_nao_desfaz_edicao_remota(self):
        ed = self.editor()
        self.assertEqual(self.pedir("/config", "POST", {"maquinas": {"3": {"nome": "Leste remota", "metrosPorMin": 4}}}, ed)[0], 200)
        # um notebook 1.1.0 manda a configuracao inteira (com a maquina 3 antiga)
        legado = {"setor": SETOR, "maquinas": {"3": {"nome": "Leste velha", "metrosPorMin": 4},
                                               "9": {"nome": "Nova do 1.1.0", "metrosPorMin": 1}}}
        st, _, _ = self.pedir("/api/nuvem/config", "POST", legado, {"X-Chave-Nuvem": CHAVE})
        self.assertEqual(st, 200)
        maquinas = self.config_vps(ed)["maquinas"]
        self.assertEqual(maquinas["3"]["nome"], "Leste remota")
        self.assertEqual(maquinas["9"]["nome"], "Nova do 1.1.0")

    def test_8_bloqueio_nao_burlavel_e_cabecalhos_de_protecao(self):
        # o atacante inventa o 1o item do X-Forwarded-For a cada tentativa; o
        # proxy acrescenta o IP real no fim - e esse que conta
        codigos = []
        for i in range(12):
            con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
            con.request("POST", "/login", urllib.parse.urlencode({"senha": "chute"}),
                        {"Content-Type": "application/x-www-form-urlencoded",
                         "X-Forwarded-For": f"10.0.0.{i}, 198.51.100.77"})
            r = con.getresponse()
            r.read()
            con.close()
            codigos.append(r.status)
        self.assertEqual(codigos[-1], 429)
        st, _, cab = self.pedir("/status", cab=self.editor())
        self.assertEqual(cab.get("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", cab.get("Content-Security-Policy", ""))
        self.assertEqual(cab.get("X-Content-Type-Options"), "nosniff")

    def test_9_vps_reinstalada_recebe_a_configuracao_de_novo(self):
        dados = tempfile.mkdtemp(prefix="painel_vps_reset_")
        porta = porta_livre()
        env = {**os.environ, "PAINEL_MODO": "nuvem", "PAINEL_DADOS": dados, "PAINEL_PORTA": str(porta),
               "NUVEM_CHAVE": CHAVE, "PYTHONIOENCODING": "utf-8"}
        script = os.path.join(RAIZ, "ferramentas", "controle_leitura_server.py")

        def subir():
            proc = subprocess.Popen([sys.executable, script], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{porta}/assets/logo.png", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            return proc

        dir_nb = tempfile.mkdtemp(prefix="painel_nb_reset_")
        with open(os.path.join(dir_nb, "nuvem.json"), "w", encoding="utf-8") as f:
            json.dump({"url": f"http://127.0.0.1:{porta}", "chave": CHAVE}, f)
        nb = BancoDados(os.path.join(dir_nb, "painel.db"))
        nuvem.aplicar_config(nb, {"metaPctDia": 66, "maquinas": {"1": {"nome": "Antes", "metrosPorMin": 2}}},
                             SETOR, origem="notebook", autor="notebook")
        enviador = nuvem.EnviadorConfig(nb, dir_nb, SETOR)
        proc = subir()
        try:
            self.assertTrue(enviador.enviar_agora())
            proc.terminate()
            proc.wait(timeout=10)
            for nome in os.listdir(dados):  # "reinstalada": banco da VPS perdido (pasta temporaria do teste)
                if nome.startswith("painel.db"):
                    os.remove(os.path.join(dados, nome))
            proc = subir()
            self.assertTrue(enviador.enviar_agora())  # percebe que a VPS voltou no tempo
            self.assertTrue(enviador.enviar_agora())  # e reenvia tudo
            vps = BancoDados(os.path.join(dados, "painel.db"))
            self.assertEqual(vps.obter_meta_pct_dia(SETOR), 66)
            self.assertEqual(vps.obter_maquinas(SETOR)["1"]["nome"], "Antes")
            vps._conn.close()
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            nb._conn.close()


if __name__ == "__main__":
    unittest.main()
