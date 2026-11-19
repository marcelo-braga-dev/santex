"""
Testes do backend (banco, backup e servidor HTTP do app).

Rodam inteiramente numa pasta temporaria: nunca abrem o banco real
(%APPDATA%/PainelProducaoSantex/dados/painel.db nem dados/painel.db) e nunca
iniciam a leitura do ESP32 (que poderia baixar e LIMPAR ciclos do
controlador de verdade).

Uso (na raiz do projeto):
    python -m unittest discover -s testes -v
"""

import gzip
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "ferramentas"))
sys.path.insert(0, os.path.join(RAIZ, "app"))

TMP = tempfile.mkdtemp(prefix="painel_teste_")
DADOS = os.path.join(TMP, "dados")
os.makedirs(DADOS)
# leitura pela USB e sem placa: o servidor nunca procura o ESP32 nos testes
with open(os.path.join(DADOS, "conexao.json"), "w", encoding="utf-8") as _f:
    json.dump({"modo": "serial"}, _f)

import caminhos  # noqa: E402

caminhos.dir_dados_usuario = lambda: DADOS  # antes de importar o servidor

import backup_banco  # noqa: E402
import servidor  # noqa: E402
from banco_dados import BancoDados  # noqa: E402

assert servidor.banco.caminho.startswith(TMP), "teste abriria um banco fora da pasta temporaria"


def novo_banco():
    return BancoDados(os.path.join(tempfile.mkdtemp(dir=TMP), "painel.db"))


class TesteBanco(unittest.TestCase):
    def test_nao_duplica_quando_o_mac_do_id_muda(self):
        b = novo_banco()
        self.assertTrue(b.gravar_ciclo_remoto("s", "403FA83CFC3F-01FCB9D1", 10, 1, 1, "?", "?", 5.0, ""))
        # mesmo controlador (mesma serie), parte do MAC diferente: nao grava de novo
        self.assertFalse(b.gravar_ciclo_remoto("s", "403F07000000-01FCB9D1", 10, 1, 1, "?", "?", 5.0, ""))
        self.assertTrue(b.gravar_ciclo_remoto("s", "403F07000000-01FCB9D1", 11, 1, 2, "?", "?", 5.0, ""))
        # serie diferente (NVS apagada) e outro controlador: ids recomecam
        self.assertTrue(b.gravar_ciclo_remoto("s", "403F07000000-AAAAAAAA", 10, 1, 1, "?", "?", 5.0, ""))
        self.assertEqual(b.ultimo_id_origem("NOVOMAC00000-01FCB9D1"), 11)
        self.assertEqual(b.ultimo_id_origem("403F07000000-AAAAAAAA"), 10)
        self.assertEqual(b.ultimo_id_origem("403F07000000-BBBBBBBB"), 0)

    def test_motivos_de_parada_sao_salvos_e_sincronizados(self):
        # 1.3.0: motivos de parada = chave nova em config_extra, versionada como as outras
        import nuvem
        from banco_dados import normalizar_extras
        b = novo_banco()
        motivos = {"catalogo": [{"id": "material", "nome": "Falta de material", "cor": "#d0453a"}],
                   "marcas": {"2|1763546400": {"m": "material", "obs": "rolo"}}}
        b.salvar_extras("s", normalizar_extras({"motivos": motivos, "desconhecida": {"x": 1}}))
        self.assertEqual(b.obter_extras("s"), {"motivos": motivos})
        self.assertTrue(nuvem.chave_item_valida("extras:motivos"))
        self.assertEqual(nuvem.itens_atuais(b, "s")["extras:motivos"], motivos)
        self.assertEqual(nuvem.nome_item("extras:motivos"), "Motivos de parada")
        # taxa na auditoria em metros por hora (guardada em m/min)
        self.assertIn("2000 m/h", nuvem.resumo_item("maquina:1", {"nome": "E1", "metrosPorMin": 2000 / 60}))

    def test_logo_da_empresa_validado_e_sincronizado(self):
        # 1.4.0: logo/icone so PNG/JPEG/WebP (SVG pode rodar script); chave geral e sincronizada
        import nuvem
        from banco_dados import imagem_do_logo, normalizar_extras
        png = "data:image/png;base64,iVBORw0KGgo="
        b = novo_banco()
        b.salvar_extras("s", normalizar_extras({"logo": {"logo": png, "icone": "data:image/svg+xml;base64,PHN2Zz4=",
                                                          "atualizadoEm": "2026-11-19T10:00:00Z", "extra": 1}}))
        ex = b.obter_extras("outro_setor")  # vale para o painel inteiro (todos os setores)
        self.assertEqual(ex["logo"], {"logo": png, "atualizadoEm": "2026-11-19T10:00:00Z"})
        self.assertEqual(imagem_do_logo(ex, "logo"), (b"\x89PNG\r\n\x1a\n", "image/png"))
        self.assertIsNone(imagem_do_logo(ex, "icone"))
        self.assertTrue(nuvem.chave_item_valida("extras:logo"))
        self.assertEqual(nuvem.itens_atuais(b, "s")["extras:logo"]["logo"], png)
        b.salvar_extras("s", normalizar_extras({"logo": {}}))  # voltar ao padrao
        self.assertIsNone(imagem_do_logo(b.obter_extras("s"), "logo"))

    def test_ciclo_wifi_sem_hora_sai_sem_horario(self):
        b = novo_banco()
        b.gravar_ciclo_remoto("s", "AA-01", 1, 1, 1, "?", "?", 5.0, "SEM_HORA")  # hora = download
        b.gravar_ciclo_remoto("s", "AA-01", 2, 2, 1, "2026-11-10T07:00:00", "2026-11-10T07:00:05", 5.0, "",
                              "2026-11-10 07:00:05")
        b.gravar_ciclo("s", 3, 1, "?", "?", 5.0, "SEM_HORA")  # pela Serial: hora de chegada e real
        linhas = b.csv_do_setor("s").strip().split("\n")[1:]
        self.assertTrue(linhas[0].endswith("SEM_HORA,"))
        self.assertTrue(linhas[1].endswith(",2026-11-10T07:00:05"))
        self.assertRegex(linhas[2], r"SEM_HORA,\d{4}-\d\d-\d\dT")

    def test_meta_em_porcentagem_preserva_a_meta_em_horas(self):
        b = novo_banco()
        b.salvar_meta_horas_dia("s", 8)
        self.assertIsNone(b.obter_meta_pct_dia("s"))
        b.salvar_meta_pct_dia("s", 88.9)
        self.assertEqual(b.obter_meta_pct_dia("s"), 88.9)
        self.assertEqual(b.obter_meta_horas_dia("s"), 8)  # a antiga fica como estava

    def test_versao_muda_a_cada_ciclo(self):
        b = novo_banco()
        v0 = b.versao_ciclos("s")
        b.gravar_ciclo("s", 1, 1, "?", "?", 3.0, "")
        v1 = b.versao_ciclos("s")
        self.assertNotEqual(v0, v1)
        self.assertEqual(v1, b.versao_ciclos("s"))
        self.assertEqual(v1, b.versao_ciclos("s"))

    def test_backup_e_um_banco_valido_e_completo(self):
        b = novo_banco()
        for i in range(50):
            b.gravar_ciclo("s", 1, i, "?", "?", 1.0, "")
        destino = os.path.join(TMP, "copia", "painel-2026-01-01.db")
        b.fazer_backup(destino)
        con = sqlite3.connect(destino)
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM ciclos").fetchone()[0], 50)
        con.close()
        self.assertFalse(os.path.exists(destino + ".tmp"))


class TesteBackup(unittest.TestCase):
    def test_rotacao_mantem_14_diarios_e_12_mensais(self):
        pasta = tempfile.mkdtemp(dir=TMP)
        hoje = date(2026, 11, 17)
        dias = [hoje - timedelta(days=i) for i in range(500)]
        for d in dias:
            open(os.path.join(pasta, f"painel-{d.isoformat()}.db"), "w").close()
        open(os.path.join(pasta, "outro-arquivo.txt"), "w").close()
        backup_banco._rotacionar(pasta)
        restantes = sorted(os.listdir(pasta))
        self.assertIn("outro-arquivo.txt", restantes)  # nunca apaga o que nao e backup
        backups = [n for n in restantes if n.startswith("painel-")]
        for d in dias[:14]:
            self.assertIn(f"painel-{d.isoformat()}.db", backups)
        mensais = set(backups) - {f"painel-{d.isoformat()}.db" for d in dias[:14]}
        self.assertLessEqual(len(mensais), 12)
        self.assertTrue(all(n.endswith("-01.db") or n == f"painel-{dias[-1].isoformat()}.db" for n in mensais), mensais)

    def test_pasta_do_backup(self):
        # codigo-fonte: backup/ na raiz do projeto (fora do git)
        self.assertEqual(os.path.normcase(caminhos.dir_backup()), os.path.normcase(os.path.join(RAIZ, "backup")))
        # .exe sem a pasta do projeto neste PC: reserva na pasta de dados
        original = caminhos._raiz_projeto
        caminhos._raiz_projeto = lambda: None
        try:
            self.assertEqual(caminhos.dir_backup(), os.path.join(DADOS, "backups"))
        finally:
            caminhos._raiz_projeto = original
        # "pasta" no backup.json tem prioridade
        dados = tempfile.mkdtemp(dir=TMP)
        outra = os.path.join(TMP, "outra-pasta")
        with open(os.path.join(dados, "backup.json"), "w", encoding="utf-8") as f:
            json.dump({"pasta": outra}, f)
        b = novo_banco()
        backup_banco.fazer_backup_do_dia(b, dados, pasta=os.path.join(TMP, "ignorada"))
        self.assertTrue(os.path.isfile(os.path.join(outra, f"painel-{date.today().isoformat()}.db")))
        self.assertFalse(os.path.exists(os.path.join(TMP, "ignorada")))

    def test_backup_do_dia_e_copia_extra(self):
        dados = tempfile.mkdtemp(dir=TMP)
        extra = os.path.join(TMP, "nuvem")
        with open(os.path.join(dados, "backup.json"), "w", encoding="utf-8") as f:
            json.dump({"pasta_extra": extra}, f)
        b = novo_banco()
        b.gravar_ciclo("s", 1, 1, "?", "?", 1.0, "")
        backup_banco.fazer_backup_do_dia(b, dados)
        nome = f"painel-{date.today().isoformat()}.db"
        self.assertTrue(os.path.isfile(os.path.join(dados, "backups", nome)))
        self.assertTrue(os.path.isfile(os.path.join(extra, nome)))
        st = backup_banco.status()
        self.assertEqual(st["erro"], "")
        self.assertEqual(st["erro_extra"], "")


class TesteMonitorWifi(unittest.TestCase):
    """ESP32 FALSO em 127.0.0.1 - o monitor e proibido de procurar o
    controlador de verdade (sem enderecos padrao), para nunca baixar nem
    limpar ciclos do ESP32 de producao."""

    def test_chave_recusada_nao_impede_o_download(self):
        import http.server
        import monitor_wifi

        pedidos = []

        class EspFalso(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def responder(self, codigo, corpo, cabecalhos=None):
                dados = corpo.encode()
                self.send_response(codigo)
                for k, v in (cabecalhos or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def do_GET(self):
                pedidos.append(("GET", self.path))
                if self.path.startswith("/info"):
                    self.responder(200, json.dumps({
                        "dispositivo": "AAAAAAAAAAAA-0BADF00D", "primeiro_id": 1, "ultimo_id": 2, "apagado_ate": 0,
                        "hora_valida": False, "epoch": 0, "hora": "?", "maquinas": []}))
                elif self.path.startswith("/ciclos"):
                    desde = int(self.path.split("desde=")[1].split("&")[0])
                    linhas = ["id,maquina,ciclo,inicio,fim,duracao_s,obs"]
                    if desde < 2:
                        linhas += ["1,1,1,2026-11-17T08:00:00,2026-11-17T08:01:00,60.0,",
                                   "2,2,1,2026-11-17T08:02:00,2026-11-17T08:03:00,60.0,"]
                    self.responder(200, "\n".join(linhas) + "\n", {"X-Lido-Ate": "2"})
                else:
                    self.responder(404, "")

            def do_POST(self):
                pedidos.append(("POST", self.path))
                self.responder(403, '{"ok":false,"mensagem":"chave invalida"}')

        esp = http.server.ThreadingHTTPServer(("127.0.0.1", 0), EspFalso)
        threading.Thread(target=esp.serve_forever, daemon=True).start()
        padrao_antigo = monitor_wifi.ENDERECOS_PADRAO
        monitor_wifi.ENDERECOS_PADRAO = ()  # nunca procura o ESP32 real
        b = novo_banco()
        parar = threading.Event()
        t = threading.Thread(target=monitor_wifi.monitorar,
                             kwargs={"enderecos": [f"127.0.0.1:{esp.server_address[1]}"], "banco": b,
                                     "parar_evento": parar, "log": lambda *_: None}, daemon=True)
        try:
            t.start()
            for _ in range(50):
                if b.versao_ciclos("enfestadeiras").startswith("2-"):
                    break
                threading.Event().wait(0.1)
            threading.Event().wait(0.5)
        finally:
            parar.set()
            t.join(timeout=10)
            monitor_wifi.ENDERECOS_PADRAO = padrao_antigo
            esp.shutdown()
        self.assertTrue(b.versao_ciclos("enfestadeiras").startswith("2-"), "os ciclos deviam ter sido baixados")
        self.assertIn(("POST", "/hora"), [(m, p.split("?")[0]) for m, p in pedidos])
        status = monitor_wifi.ler_status_sincronizacao(os.path.dirname(b.caminho))
        self.assertIn("recusou a chave", status.get("aviso_chave", ""))


class TesteServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        servidor.banco.gravar_ciclo(servidor.SETOR_PADRAO, 1, 1, "?", "?", 12.5, "")
        cls.srv = servidor._ServidorExclusivo(("::1", 0), servidor.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://[::1]:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pedir(self, caminho, metodo="GET", corpo=None, cabecalhos=None):
        dados = json.dumps(corpo).encode() if corpo is not None else (b"" if metodo == "POST" else None)
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_head_igual_ao_get_sem_corpo(self):
        """Monitores de disponibilidade usam HEAD (antes: 501)."""
        st_get, cab_get, corpo_get = self.pedir("/index.html")
        st, cab, corpo = self.pedir("/index.html", metodo="HEAD")
        self.assertEqual((st, corpo), (st_get, b""))
        self.assertEqual(cab["Content-Length"], str(len(corpo_get)))
        self.assertEqual(cab["Content-Type"], cab_get["Content-Type"])

    def test_dados_responde_304_sem_mudanca(self):
        st, cab, corpo = self.pedir("/dados")
        self.assertEqual(st, 200)
        self.assertIn("maquina,ciclo", corpo.decode())
        etag = cab["ETag"]
        st, _, corpo = self.pedir("/dados", cabecalhos={"If-None-Match": etag})
        self.assertEqual((st, corpo), (304, b""))
        servidor.banco.gravar_ciclo(servidor.SETOR_PADRAO, 1, 2, "?", "?", 3.0, "")
        st, cab2, _ = self.pedir("/dados", cabecalhos={"If-None-Match": etag})
        self.assertEqual(st, 200)
        self.assertNotEqual(cab2["ETag"], etag)

    def test_dados_comprimidos(self):
        st, cab, corpo = self.pedir("/dados", cabecalhos={"Accept-Encoding": "gzip"})
        self.assertEqual((st, cab["Content-Encoding"]), (200, "gzip"))
        self.assertIn("maquina,ciclo", gzip.decompress(corpo).decode())

    def test_status_informa_versao_e_permissao(self):
        st, _, corpo = self.pedir("/status")
        dados = json.loads(corpo)
        self.assertEqual(dados["versao"], servidor.APP_VERSAO)
        self.assertTrue(dados["podeEditar"])  # localhost

    def test_painel_sem_cache_e_404(self):
        st, cab, _ = self.pedir("/")
        self.assertEqual((st, cab["Cache-Control"]), (200, "no-cache"))
        self.assertEqual(self.pedir("/../ferramentas/banco_dados.py")[0], 404)
        self.assertEqual(self.pedir("/nao-existe.js")[0], 404)
        self.assertEqual(self.pedir("/_backup/index_v1_antes_redesign.html")[0], 404)

    def test_config_valida_entrada(self):
        st, _, corpo = self.pedir("/config", "POST", {
            "setor": servidor.SETOR_PADRAO,
            "maquinas": {"1": {"nome": "<b>x</b>" + "y" * 100, "metrosPorMin": "abc"}, "zz": {"nome": "ignorar"}, "2": "lixo"},
            "metaHorasDia": 99,
            "metaPctDia": 150,
        })
        self.assertEqual((st, json.loads(corpo)["ok"]), (200, True))
        maq = servidor.banco.obter_maquinas(servidor.SETOR_PADRAO)
        self.assertEqual(len(maq["1"]["nome"]), 40)
        self.assertEqual(maq["1"]["metrosPorMin"], 0)
        self.assertNotIn("zz", maq)
        self.assertNotEqual(servidor.banco.obter_meta_horas_dia(servidor.SETOR_PADRAO), 99)
        self.assertIsNone(servidor.banco.obter_meta_pct_dia(servidor.SETOR_PADRAO))  # 150% recusado
        self.pedir("/config", "POST", {"setor": servidor.SETOR_PADRAO, "metaPctDia": 85})
        self.assertEqual(json.loads(self.pedir("/config")[2])["metaPctDia"], 85)
        st, _, _ = self.pedir("/config", "POST", cabecalhos={"Content-Type": "application/json"}, corpo=[1, 2])
        self.assertEqual(st, 200)

    def test_outro_computador_somente_leitura_ou_pin(self):
        self.assertFalse(servidor._eh_este_computador("192.0.2.77"))
        self.assertTrue(servidor._eh_este_computador("::ffff:127.0.0.1"))
        for ip in servidor._enderecos_deste_pc():  # o proprio PC por qualquer IP dele (IPv4 ou IPv6)
            self.assertTrue(servidor._eh_este_computador(ip), ip)
        def handler(ip, pin=None):
            h = servidor.Handler.__new__(servidor.Handler)  # sem socket: so a regra de permissao
            h.client_address = (ip, 0)
            h.headers = {"X-Pin": pin} if pin is not None else {}
            return h

        caminho = os.path.join(DADOS, "seguranca.json")
        self.assertEqual(servidor._pin_remoto(), "")
        self.assertTrue(handler("127.0.0.1")._pode_editar())
        self.assertFalse(handler("192.0.2.77")._pode_editar())  # sem PIN configurado: so leitura
        self.assertFalse(handler("192.0.2.77", "")._pode_editar())
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"pin_remoto": "4821"}, f)
        try:
            self.assertFalse(handler("192.0.2.77")._pode_editar())
            self.assertFalse(handler("192.0.2.77", "0000")._pode_editar())
            self.assertTrue(handler("192.0.2.77", "4821")._pode_editar())
        finally:
            os.remove(caminho)

    def test_senha_do_acesso_remoto_definida_no_notebook(self):
        cab = {"Content-Type": "application/json"}
        st, _, corpo = self.pedir("/config", "POST", {"senhaRemota": "curta"}, cab)
        self.assertEqual(st, 400)
        self.assertIn("8 a 128", json.loads(corpo)["erro"])
        st, _, corpo = self.pedir("/config", "POST", {"senhaRemota": "senha-da-fabrica-1"}, cab)
        self.assertEqual((st, json.loads(corpo)["acessoRemoto"]["definida"]), (200, True))
        cfg = self.pedir("/config")[2].decode()
        self.assertNotIn("pbkdf2", cfg)            # o hash nunca sai pela API
        self.assertNotIn("senha-da-fabrica-1", cfg)
        self.assertTrue(json.loads(cfg)["acessoRemoto"]["definida"])
        guardado = servidor.nuvem.dados_senha_remota(servidor.banco)["hash"]
        self.assertTrue(servidor.nuvem.verificar_senha("senha-da-fabrica-1", guardado))

    def test_post_desconhecido_404(self):
        self.assertEqual(self.pedir("/apagar-tudo", "POST")[0], 404)


if __name__ == "__main__":
    unittest.main()
