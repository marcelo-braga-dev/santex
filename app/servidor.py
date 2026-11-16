"""
Servidor HTTP embutido do aplicativo desktop: no MESMO processo, serve o
painel (arquivos estaticos de painel/) em "/" e a API de controle da
leitura (/status, /iniciar, /parar, /dados, /sincronizacao, /conexao) que
o painel ja conhece (mesmos endpoints de ferramentas/controle_leitura_server.py).

Dentro do .exe gerado pelo PyInstaller nao ha um "python.exe" separado para
rodar monitor_serial.py como subprocesso (sys.executable aponta para o
proprio aplicativo) - por isso aqui a leitura roda como uma THREAD no mesmo
processo, chamando monitor_serial.monitorar() diretamente - ou
monitor_wifi.monitorar(), quando dados/conexao.json pede leitura pelo Wi-Fi
(ESP32 guardando os ciclos na propria flash).
"""

import json
import mimetypes
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from anuncio_rede import AnuncioRede
from caminhos import dir_base_bundle, dir_dados_usuario

PORTA_SERVIDOR = 80  # porta padrao da web: http://painel.local (sem ":porta")
ENDERECO_ESCUTA = "::"  # todas as placas de rede, IPv6 e IPv4 (acesso por outros PCs)

_BASE = dir_base_bundle()
PAINEL_DIR = os.path.normpath(os.path.join(_BASE, "painel"))
FERRAMENTAS_DIR = os.path.join(_BASE, "ferramentas")

sys.path.insert(0, FERRAMENTAS_DIR)
import monitor_serial  # noqa: E402 (precisa do sys.path.insert acima)
import monitor_wifi  # noqa: E402
from banco_dados import BancoDados, NOME_ARQUIVO, normalizar_turnos, normalizar_extras  # noqa: E402
from monitor_serial import SETOR_PADRAO  # noqa: E402

banco = BancoDados(os.path.join(dir_dados_usuario(), NOME_ARQUIVO))

_thread_leitura = None
_evento_parar = threading.Event()

_TIPOS_EXTRAS = {".ico": "image/x-icon"}


def esta_rodando():
    return _thread_leitura is not None and _thread_leitura.is_alive()


def iniciar():
    """Comeca a gravar ciclos reais no banco de dados persistente: pelo
    Wi-Fi se conexao.json tiver o endereco do ESP32, senao pela porta serial
    detectada automaticamente. Silenciosamente nao faz nada se ja estiver
    rodando ou se nenhuma porta serial for encontrada (o painel reflete
    isso pelo /status continuar "rodando": false)."""
    global _thread_leitura, _evento_parar
    if esta_rodando():
        return
    enderecos = monitor_wifi.endereco_configurado(dir_dados_usuario())
    if enderecos is not None:  # lista vazia = so os enderecos padrao do ESP32
        alvo, origem = monitor_wifi.monitorar, enderecos
    else:
        alvo, origem = monitor_serial.monitorar, monitor_serial.encontrar_porta()
        if not origem:
            return
    _evento_parar = threading.Event()
    _thread_leitura = threading.Thread(
        target=alvo,
        args=(origem,),
        kwargs={"banco": banco, "parar_evento": _evento_parar, "log": lambda *_: None},
        daemon=True,
    )
    _thread_leitura.start()


def status_sincronizacao():
    """O que o painel mostra na barra de sincronizacao: origem dos dados,
    leitura rodando ou nao e, no Wi-Fi, a situacao gravada pelo monitor."""
    modo = monitor_wifi.modo_conexao(dir_dados_usuario())
    status = monitor_wifi.ler_status_sincronizacao(dir_dados_usuario()) if modo == "wifi" else {}
    return {**status, "modo": modo, "rodando": esta_rodando()}


def parar():
    global _thread_leitura
    if not esta_rodando():
        return
    _evento_parar.set()
    _thread_leitura.join(timeout=3)
    _thread_leitura = None


class Handler(BaseHTTPRequestHandler):
    def _responder_json(self, corpo):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(200)
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
            self._responder_json({"rodando": esta_rodando(), "modo": monitor_wifi.modo_conexao(dir_dados_usuario())})
        elif url.path == "/sincronizacao":
            self._responder_json(status_sincronizacao())
        elif url.path == "/dados":
            self._responder_csv()
        elif url.path == "/ao-vivo":
            setor = parse_qs(url.query).get("setor", [SETOR_PADRAO])[0]
            self._responder_json({"rodando": esta_rodando(), "maquinas": banco.obter_estado_ao_vivo(setor)})
        elif url.path == "/esp/diagnostico":
            self._responder_json(monitor_wifi.diagnostico_esp(status_sincronizacao()))
        elif url.path == "/config":
            setor = parse_qs(url.query).get("setor", [SETOR_PADRAO])[0]
            self._responder_json({
                "maquinas": banco.obter_maquinas(setor),
                "metaHorasDia": banco.obter_meta_horas_dia(setor),
                "turnos": banco.obter_turnos(setor),
                "extras": banco.obter_extras(setor),
            })
        else:
            self._responder_estatico(url.path)

    def _responder_csv(self):
        dados = banco.csv_do_setor(SETOR_PADRAO).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _responder_estatico(self, caminho_url):
        """Serve o painel (index.html, assets/logo.png, ...) direto da
        pasta painel/ - e como o painel passa a ser aberto, em vez de
        file://, pra evitar qualquer restricao de fetch/XHR que alguns
        webviews impoem a paginas abertas como arquivo local."""
        if caminho_url == "/":
            caminho_url = "/index.html"

        alvo = os.path.normpath(os.path.join(PAINEL_DIR, unquote(caminho_url).lstrip("/")))
        if not (alvo == PAINEL_DIR or alvo.startswith(PAINEL_DIR + os.sep)) or not os.path.isfile(alvo):
            self.send_response(404)
            self.end_headers()
            return

        tipo, _ = mimetypes.guess_type(alvo)
        tipo = tipo or _TIPOS_EXTRAS.get(os.path.splitext(alvo)[1], "application/octet-stream")
        # Sem "charset=utf-8" o WebView2 adivinha a codificacao sozinho e
        # corrompe os acentos (o HTML e sempre salvo em UTF-8 neste projeto).
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        with open(alvo, "rb") as arquivo:
            dados = arquivo.read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
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
            self._responder_json(monitor_wifi.acao_esp(status_sincronizacao(), str(corpo.get("acao", ""))))
        elif self.path == "/conexao":
            self._salvar_conexao()
        else:
            self.send_response(404)
            self.end_headers()

    def _salvar_config(self):
        try:
            corpo = self._corpo_json()
        except (ValueError, UnicodeDecodeError):
            self._responder_json({"ok": False, "erro": "JSON invalido"})
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
        """Troca a origem dos dados (Wi-Fi do ESP32 ou cabo USB) pelo
        painel - grava no conexao.json e reinicia a leitura na origem nova."""
        try:
            modo = self._corpo_json().get("modo")
        except (ValueError, UnicodeDecodeError):
            modo = None
        if modo not in ("wifi", "serial"):
            self._responder_json({"ok": False, "erro": "modo deve ser wifi ou serial"})
            return
        monitor_wifi.salvar_modo_conexao(dir_dados_usuario(), modo)
        parar()
        iniciar()
        self._responder_json({"ok": True, **status_sincronizacao()})

    def log_message(self, format, *args):
        pass  # silencia o log padrao (GET /status a cada poucos segundos)


class _ServidorExclusivo(HTTPServer):
    """HTTPServer que NAO divide a porta com outro processo.

    O HTTPServer padrao liga SO_REUSEADDR - no Windows isso deixa DOIS
    processos escutando a mesma porta ao mesmo tempo (ex.: uma segunda
    janela do app, ou uma que nao fechou direito), e as requisicoes caem
    ora num, ora no outro: painel instavel, "so funciona fechando e
    abrindo". Com SO_EXCLUSIVEADDRUSE a segunda tentativa falha na hora
    (OSError) e o main.py mostra "O Painel ja esta aberto em outra janela".
    """

    allow_reuse_address = False
    allow_reuse_port = False
    # IPv6 + IPv4 no mesmo socket ("dual-stack"): o Windows traduz nomes
    # (painel.local, nome do PC) primeiro para IPv6 - so IPv4 dava timeout.
    address_family = socket.AF_INET6
    anuncio = None  # AnuncioRede (painel.local), encerrado junto com o servidor

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # so existe no Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

    def server_close(self):
        if self.anuncio is not None:
            self.anuncio.parar()
            self.anuncio = None
        super().server_close()


def iniciar_servidor_em_thread():
    """Sobe o HTTPServer numa thread daemon e devolve a instancia, para o
    chamador poder encerra-lo (shutdown()) ao fechar a janela."""
    # Aceita conexoes de qualquer placa de rede: o painel abre neste PC
    # (http://localhost) e em outros computadores/celulares da mesma rede
    # (http://painel.local ou http://<IP-deste-PC>). Sem senha - qualquer
    # um na rede pode ver e alterar as configuracoes.
    servidor = _ServidorExclusivo((ENDERECO_ESCUTA, PORTA_SERVIDOR), Handler)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    servidor.anuncio = AnuncioRede(PORTA_SERVIDOR)
    servidor.anuncio.iniciar()
    # No Wi-Fi a sincronizacao comeca sozinha ao abrir o app - e so conectar
    # o notebook na rede do ESP32 (ou da empresa). Pela USB continua manual.
    if monitor_wifi.modo_conexao(dir_dados_usuario()) == "wifi":
        iniciar()
    return servidor
