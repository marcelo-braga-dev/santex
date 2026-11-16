"""
Servidor local que liga/desliga o monitor_serial.py sob demanda, para o
botao "Atualizacao automatica" do painel/index.html poder controlar a
porta COM direto pela pagina, sem precisar de terminal.

Uso:
    python controle_leitura_server.py

Deixe esta janela aberta em segundo plano (minimizada, por exemplo).
O dashboard (aberto localmente, como arquivo) conversa com ele em
http://localhost. Sem esse servidor rodando, o botao na pagina mostra
"Atualizacao automatica indisponivel" - o navegador nao tem como
iniciar/parar processos sozinho.

Tambem serve os ciclos gravados no banco de dados (SQLite, ver
banco_dados.py) em GET /dados, no mesmo formato CSV que o dashboard ja
sabe ler, e a configuracao de maquinas/meta em GET e POST /config - tudo
persistente entre execucoes (nada aqui e apagado ao reiniciar o servidor).
"""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from banco_dados import BancoDados, NOME_ARQUIVO, normalizar_turnos, normalizar_extras
from monitor_serial import SETOR_PADRAO
from monitor_wifi import (acao_esp, diagnostico_esp, endereco_configurado, ler_status_sincronizacao, modo_conexao,
                          salvar_modo_conexao)

PORTA_SERVIDOR = 80
DIR_BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_MONITOR = "monitor_serial.py"
SCRIPT_MONITOR_WIFI = "monitor_wifi.py"
DIR_DADOS = os.path.join(DIR_BASE, "..", "dados")
CAMINHO_DB = os.path.join(DIR_DADOS, NOME_ARQUIVO)

banco = BancoDados(CAMINHO_DB)
processo_monitor = None


def esta_rodando():
    return processo_monitor is not None and processo_monitor.poll() is None


def iniciar():
    global processo_monitor
    if esta_rodando():
        return
    # dados/conexao.json com {"modo": "wifi", ...} -> busca os ciclos do ESP32 pela rede
    script = SCRIPT_MONITOR_WIFI if endereco_configurado(DIR_DADOS) is not None else SCRIPT_MONITOR
    processo_monitor = subprocess.Popen(
        [sys.executable, script],
        cwd=DIR_BASE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parar():
    global processo_monitor
    if not esta_rodando():
        return
    processo_monitor.terminate()
    try:
        processo_monitor.wait(timeout=3)
    except subprocess.TimeoutExpired:
        processo_monitor.kill()
    processo_monitor = None


def status_sincronizacao():
    modo = modo_conexao(DIR_DADOS)
    status = ler_status_sincronizacao(DIR_DADOS) if modo == "wifi" else {}
    return {**status, "modo": modo, "rodando": esta_rodando()}


class Handler(BaseHTTPRequestHandler):
    def _responder_json(self, corpo, status=200):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/status":
            self._responder_json({"rodando": esta_rodando(), "modo": modo_conexao(DIR_DADOS)})
        elif url.path == "/sincronizacao":
            self._responder_json(status_sincronizacao())
        elif url.path == "/dados":
            self._responder_csv()
        elif url.path == "/ao-vivo":
            setor = parse_qs(url.query).get("setor", [SETOR_PADRAO])[0]
            self._responder_json({"rodando": esta_rodando(), "maquinas": banco.obter_estado_ao_vivo(setor)})
        elif url.path == "/esp/diagnostico":
            self._responder_json(diagnostico_esp(status_sincronizacao()))
        elif url.path == "/config":
            setor = parse_qs(url.query).get("setor", [SETOR_PADRAO])[0]
            self._responder_json({
                "maquinas": banco.obter_maquinas(setor),
                "metaHorasDia": banco.obter_meta_horas_dia(setor),
                "turnos": banco.obter_turnos(setor),
                "extras": banco.obter_extras(setor),
            })
        else:
            self.send_response(404)
            self.end_headers()

    def _responder_csv(self):
        dados = banco.csv_do_setor(SETOR_PADRAO).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _corpo_json(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        if not tamanho:
            return {}
        return json.loads(self.rfile.read(tamanho).decode("utf-8"))

    def do_POST(self):
        if self.path == "/iniciar":
            iniciar()
            self._responder_json({"rodando": esta_rodando()})
        elif self.path == "/parar":
            parar()
            self._responder_json({"rodando": esta_rodando()})
        elif self.path == "/config":
            self._salvar_config()
        elif self.path == "/esp/acao":
            try:
                corpo = self._corpo_json()
            except (ValueError, UnicodeDecodeError):
                corpo = {}
            self._responder_json(acao_esp(status_sincronizacao(), str(corpo.get("acao", ""))))
        elif self.path == "/conexao":
            self._salvar_conexao()
        else:
            self.send_response(404)
            self.end_headers()

    def _salvar_config(self):
        try:
            corpo = self._corpo_json()
        except (ValueError, UnicodeDecodeError):
            self._responder_json({"ok": False, "erro": "JSON invalido"}, status=400)
            return

        setor = corpo.get("setor", SETOR_PADRAO)
        for maquina_id, item in (corpo.get("maquinas") or {}).items():
            nome = str(item.get("nome", f"Máquina {maquina_id}")).strip() or f"Máquina {maquina_id}"
            try:
                taxa = float(item.get("metrosPorMin", 0))
            except (TypeError, ValueError):
                taxa = 0
            banco.salvar_maquina(setor, int(maquina_id), nome, max(0, taxa))

        if "metaHorasDia" in corpo:
            try:
                meta = float(corpo["metaHorasDia"])
                if meta > 0:
                    banco.salvar_meta_horas_dia(setor, meta)
            except (TypeError, ValueError):
                pass

        if "turnos" in corpo:
            turnos = normalizar_turnos(corpo["turnos"])
            if turnos:
                banco.salvar_turnos(setor, turnos)

        if "extras" in corpo:
            banco.salvar_extras(setor, normalizar_extras(corpo["extras"]))

        self._responder_json({"ok": True})

    def _salvar_conexao(self):
        try:
            modo = self._corpo_json().get("modo")
        except (ValueError, UnicodeDecodeError):
            modo = None
        if modo not in ("wifi", "serial"):
            self._responder_json({"ok": False, "erro": "modo deve ser wifi ou serial"}, status=400)
            return
        salvar_modo_conexao(DIR_DADOS, modo)
        parar()
        iniciar()
        self._responder_json({"ok": True, **status_sincronizacao()})

    def log_message(self, format, *args):
        pass  # silencia o log padrao (cada GET /status a cada poucos segundos)


if __name__ == "__main__":
    print("Servidor de controle da leitura em http://localhost")
    print(f"Banco de dados: {banco.caminho}")
    print("Deixe esta janela aberta. Use o botao no painel/index.html.")
    if modo_conexao(DIR_DADOS) == "wifi":
        iniciar()  # no Wi-Fi a sincronizacao comeca sozinha
    try:
        HTTPServer(("0.0.0.0", PORTA_SERVIDOR), Handler).serve_forever()  # aceita outros PCs da rede
    except KeyboardInterrupt:
        parar()
        print("\nEncerrado pelo usuario.")
