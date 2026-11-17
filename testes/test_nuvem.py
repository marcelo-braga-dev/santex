"""
Testes do modo nuvem (VPS): sobe o servidor de verdade num processo
separado, com PAINEL_MODO=nuvem e uma pasta temporaria - nunca toca no banco
real nem em nenhuma VPS.

    python -m unittest discover -s testes -v
"""

import http.client
import json
import os
import socket
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

import nuvem  # noqa: E402
from banco_dados import BancoDados  # noqa: E402

CHAVE = "chave-de-teste-0123456789"
SENHA_INICIAL = "senha-da-fabrica"


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def lote_do_firmware(lido_ate=2):
    """Exatamente o JSON que o firmware 3.0 monta em montarEnvioNuvem()."""
    return {
        "dispositivo": "403F07000000-01FCB9D1",
        "firmware": "3.0",
        "hora": "2026-11-17T10:00:00",
        "hora_valida": True,
        "ultimo_id": 5,
        "lido_ate": lido_ate,
        "perdidos": 0,
        "maquinas": [{"maquina": 1, "ligado": True, "segundos": 42}, {"maquina": 2, "ligado": False, "segundos": 600}],
        "ciclos": "id,maquina,ciclo,inicio,fim,duracao_s,obs\n"
                  "1,1,10,2026-11-17T09:00:00,2026-11-17T09:01:00,60.0,\n"
                  "2,2,7,2026-11-17T09:02:00,2026-11-17T09:02:30,30.5,\n",
    }


class TesteModoNuvem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = tempfile.mkdtemp(prefix="painel_nuvem_teste_")
        # a VPS ja recebeu (como se viesse do notebook) o hash da senha unica
        banco_vps = BancoDados(os.path.join(cls.dados, "painel.db"))
        banco_vps.salvar_segredo(nuvem.SEGREDO_SENHA_REMOTA, json.dumps(
            {"hash": nuvem.hash_senha(SENHA_INICIAL, iteracoes=1000), "alterado_em": "2026-11-17T08:00:00"}))
        banco_vps._conn.close()
        cls.senha = SENHA_INICIAL
        cls.porta = porta_livre()
        env = {**os.environ, "PAINEL_MODO": "nuvem", "PAINEL_DADOS": cls.dados,
               "PAINEL_PORTA": str(cls.porta), "NUVEM_CHAVE": CHAVE, "PYTHONIOENCODING": "utf-8"}
        cls.proc = subprocess.Popen([sys.executable, os.path.join(RAIZ, "ferramentas", "controle_leitura_server.py")],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.base = f"http://127.0.0.1:{cls.porta}"
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
        cls.proc.stderr.close()

    # -- ajudantes ---------------------------------------------------------
    def entrar(self, senha=None, ip=None):
        """POST /login como o navegador (formulario). Devolve (status, cookie)."""
        con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        corpo = urllib.parse.urlencode({"senha": senha if senha is not None else self.senha})
        cab = {"Content-Type": "application/x-www-form-urlencoded"}
        if ip:
            cab["X-Forwarded-For"] = ip
        con.request("POST", "/login", corpo, cab)
        r = con.getresponse()
        r.read()
        cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
        con.close()
        return r.status, cookie

    def sessao(self):
        st, cookie = self.entrar()
        self.assertEqual(st, 303)
        return {"Cookie": cookie}

    def pedir(self, caminho, metodo="GET", corpo=None, cabecalhos=None):
        dados = json.dumps(corpo).encode() if corpo is not None else (b"" if metodo == "POST" else None)
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    # -- testes --------------------------------------------------------------
    def test_1_login_por_senha_unica(self):
        st, pagina = self.pedir("/")  # sem sessao: a pagina inicial e a tela de login
        self.assertEqual(st, 200)
        self.assertIn("Senha de acesso", pagina.decode())
        self.assertNotIn("machine-grid", pagina.decode())
        self.assertEqual(self.pedir("/status")[0], 401)
        self.assertEqual(self.pedir("/dados")[0], 401)
        self.assertEqual(self.pedir("/assets/logo.png")[0], 200)  # logo da tela de login
        st, cookie = self.entrar("senha-errada")
        self.assertEqual((st, cookie), (401, ""))
        cab = self.sessao()
        self.assertIn("HttpOnly", self._set_cookie_completo())
        st, corpo = self.pedir("/status", cabecalhos=cab)
        dados = json.loads(corpo)
        self.assertEqual((st, dados["modo"], dados["podeEditar"]), (200, "nuvem", False))
        st, pagina = self.pedir("/", cabecalhos=cab)
        self.assertIn("machine-grid", pagina.decode())  # agora o painel de verdade

    def _set_cookie_completo(self):
        con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        con.request("POST", "/login", urllib.parse.urlencode({"senha": self.senha}),
                    {"Content-Type": "application/x-www-form-urlencoded"})
        r = con.getresponse()
        r.read()
        con.close()
        return r.getheader("Set-Cookie") or ""

    def test_2_esp32_envia_ciclos_e_estado(self):
        self.assertEqual(self.pedir("/api/nuvem/enviar", "POST", lote_do_firmware())[0], 403)
        self.assertEqual(self.pedir("/api/nuvem/enviar", "POST", lote_do_firmware(),
                                    {"X-Chave-Nuvem": "outra", "Content-Type": "application/json"})[0], 403)
        cab = {"X-Chave-Nuvem": CHAVE, "Content-Type": "application/json"}
        st, corpo = self.pedir("/api/nuvem/enviar", "POST", lote_do_firmware(), cab)
        self.assertEqual((st, json.loads(corpo)["gravados"]), (200, 2))
        st, corpo = self.pedir("/api/nuvem/enviar", "POST", lote_do_firmware(), cab)  # reenvio: nada duplica
        self.assertEqual(json.loads(corpo)["gravados"], 0)
        sessao = self.sessao()
        st, csv = self.pedir("/dados", cabecalhos=sessao)
        linhas = csv.decode().strip().split("\n")
        self.assertEqual(len(linhas), 3)
        self.assertTrue(linhas[1].endswith(",2026-11-17T09:01:00"))
        vivo = json.loads(self.pedir("/ao-vivo", cabecalhos=sessao)[1])
        self.assertTrue(vivo["rodando"])
        self.assertTrue(vivo["maquinas"]["1"]["ligado"])
        sinc = json.loads(self.pedir("/sincronizacao", cabecalhos=sessao)[1])
        self.assertEqual((sinc["modo"], sinc["estado"], sinc["firmware"], sinc["pendentes_esp"]), ("nuvem", "conectado", "3.0", 3))

    def test_2b_ping_confere_a_chave_sem_gravar(self):
        self.assertEqual(self.pedir("/api/nuvem/ping", "POST", {}, {"X-Chave-Nuvem": "errada"})[0], 403)
        st, corpo = self.pedir("/api/nuvem/ping", "POST", {}, {"X-Chave-Nuvem": CHAVE})
        self.assertEqual((st, json.loads(corpo)["ok"]), (200, True))
        sinc = json.loads(self.pedir("/sincronizacao", cabecalhos=self.sessao())[1])
        self.assertNotIn("config_recebida_em", sinc)  # o ping nao finge que a configuracao chegou

    def test_3_nuvem_nunca_edita_nem_mostra_o_hash(self):
        # atras do proxy toda visita vem de 127.0.0.1 - mesmo assim, somente leitura
        cab = {**self.sessao(), "Content-Type": "application/json"}
        for rota in ("/config", "/iniciar", "/parar", "/conexao", "/esp/acao"):
            st, corpo = self.pedir(rota, "POST", {"metaPctDia": 10, "senhaRemota": "trocada-na-vps"}, cab)
            self.assertEqual((st, json.loads(corpo)["erro"]), (403, "somente_leitura"), rota)
        st, corpo = self.pedir("/config", cabecalhos=cab)
        self.assertNotIn("pbkdf2", corpo.decode())
        self.assertNotIn("acessoRemoto", json.loads(corpo))
        st, corpo = self.pedir("/esp/diagnostico", cabecalhos=cab)
        self.assertFalse(json.loads(corpo)["ok"])

    def test_4_senha_trocada_no_notebook_chega_e_derruba_sessoes(self):
        sessao_antiga = self.sessao()
        local = tempfile.mkdtemp(prefix="painel_notebook_teste_")
        with open(os.path.join(local, "nuvem.json"), "w", encoding="utf-8") as f:
            json.dump({"url": self.base, "chave": CHAVE}, f)
        b = BancoDados(os.path.join(local, "painel.db"))
        b.salvar_maquina("enfestadeiras", 1, "Enfestadeira Norte", 5)
        b.salvar_meta_pct_dia("enfestadeiras", 80)
        nuvem.definir_senha_remota(b, "nova-senha-2026")
        enviador = nuvem.EnviadorConfig(b, local, "enfestadeiras")
        self.assertTrue(enviador.enviar_agora())
        self.assertFalse(enviador.enviar_agora())  # sem mudanca: nao reenvia
        self.assertEqual(enviador.status()["erro"], "")
        # a sessao aberta com a senha antiga caiu; a antiga nao entra mais
        self.assertEqual(self.pedir("/status", cabecalhos=sessao_antiga)[0], 401)
        self.assertEqual(self.entrar(SENHA_INICIAL)[0], 401)
        type(self).senha = "nova-senha-2026"
        cfg = json.loads(self.pedir("/config", cabecalhos=self.sessao())[1])
        self.assertEqual((cfg["maquinas"]["1"]["nome"], cfg["metaPctDia"]), ("Enfestadeira Norte", 80))
        # chave errada: o notebook mostra o motivo
        with open(os.path.join(local, "nuvem.json"), "w", encoding="utf-8") as f:
            json.dump({"url": self.base, "chave": "errada"}, f)
        b.salvar_meta_pct_dia("enfestadeiras", 81)
        self.assertFalse(enviador.enviar_agora())
        self.assertIn("chave recusada", enviador.status()["erro"])

    def test_5_sair_e_bloqueio_por_tentativas(self):
        con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        con.request("POST", "/logout", "", self.sessao())
        r = con.getresponse()
        r.read()
        con.close()
        self.assertEqual(r.status, 303)
        self.assertIn("Max-Age=0", r.getheader("Set-Cookie"))
        codigos = [self.entrar("chute", ip="203.0.113.9")[0] for _ in range(12)]
        self.assertEqual(codigos[-1], 429)
        self.assertEqual(self.entrar(ip="203.0.113.9")[0], 429)  # bloqueado mesmo com a senha certa
        self.assertEqual(self.entrar(ip="198.51.100.7")[0], 303)  # outro IP segue normal


if __name__ == "__main__":
    unittest.main()
