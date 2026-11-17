"""
Servidor HTTP embutido do aplicativo desktop: no MESMO processo, serve o
painel (arquivos estaticos de painel/) em "/" e a API de controle da
leitura (/status, /iniciar, /parar, /dados, /sincronizacao, /conexao...).
ferramentas/controle_leitura_server.py usa este mesmo modulo (sem janela).

Dentro do .exe gerado pelo PyInstaller nao ha um "python.exe" separado para
rodar monitor_serial.py como subprocesso (sys.executable aponta para o
proprio aplicativo) - por isso aqui a leitura roda como uma THREAD no mesmo
processo, chamando monitor_serial.monitorar() diretamente - ou
monitor_wifi.monitorar(), quando dados/conexao.json pede leitura pelo Wi-Fi
(ESP32 guardando os ciclos na propria flash).

Seguranca na rede: o painel abre em outros PCs/celulares (painel.local),
mas so ESTE computador altera configuracoes sem senha. Os outros so podem
alterar com o PIN definido em dados/seguranca.json:
    {"pin_remoto": "4821"}
Sem esse arquivo, os outros aparelhos ficam somente leitura.

Modo nuvem (VPS, acesso de fora da rede - ver ferramentas/nuvem.py e
docs/nuvem-vps.md): PAINEL_MODO=nuvem. Sem leitura do ESP32 (ele envia
sozinho para /api/nuvem/enviar), sem anuncio na rede local, painel com
login (dados/usuarios.json) e SEMPRE somente leitura - atras do Caddy toda
visita chega de 127.0.0.1, que no modo local seria "este computador".
Variaveis: PAINEL_PORTA, PAINEL_ESCUTA, PAINEL_DADOS, NUVEM_CHAVE.
"""

import gzip
import hmac
import json
import mimetypes
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from caminhos import dir_backup, dir_base_bundle, dir_dados_usuario

APP_VERSAO = "1.1.0"
MODO_NUVEM = os.environ.get("PAINEL_MODO", "").strip().lower() == "nuvem"
# porta padrao da web: http://painel.local (sem ":porta"); na VPS fica atras do Caddy
PORTA_SERVIDOR = int(os.environ.get("PAINEL_PORTA") or (8080 if MODO_NUVEM else 80))
# todas as placas de rede (acesso por outros PCs); na VPS so o Caddy, na mesma maquina
ENDERECO_ESCUTA = os.environ.get("PAINEL_ESCUTA") or ("127.0.0.1" if MODO_NUVEM else "::")
NUVEM_CHAVE = os.environ.get("NUVEM_CHAVE", "").strip()  # VPS: a mesma do .env da fabrica
TIMEOUT_CONEXAO_S = 30  # cliente parado no meio da requisicao nao prende uma thread para sempre
MAX_CORPO_BYTES = 1_000_000
ARQUIVO_SEGURANCA = "seguranca.json"

_BASE = dir_base_bundle()
PAINEL_DIR = os.path.normpath(os.path.join(_BASE, "painel"))
FERRAMENTAS_DIR = os.path.join(_BASE, "ferramentas")

sys.path.insert(0, FERRAMENTAS_DIR)
import backup_banco  # noqa: E402 (precisa do sys.path.insert acima)
import monitor_serial  # noqa: E402
import monitor_wifi  # noqa: E402
import nuvem  # noqa: E402
from banco_dados import BancoDados, NOME_ARQUIVO  # noqa: E402
from monitor_serial import SETOR_PADRAO  # noqa: E402

banco = BancoDados(os.path.join(dir_dados_usuario(), NOME_ARQUIVO))
autenticador = nuvem.Autenticador(dir_dados_usuario()) if MODO_NUVEM else None
enviador_nuvem = None  # notebook: EnviadorConfig (configuracao -> VPS)

_thread_leitura = None
_evento_parar = threading.Event()
_trava_leitura = threading.Lock()

_TIPOS_EXTRAS = {".ico": "image/x-icon"}

# CSV de /dados ja montado (e comprimido) para a versao atual dos ciclos -
# varios aparelhos consultando a cada 5 s nao remontam o historico inteiro.
_cache_csv = {"versao": None, "bruto": b"", "gzip": b""}
_trava_cache = threading.Lock()


def esta_rodando():
    return _thread_leitura is not None and _thread_leitura.is_alive()


def iniciar():
    """Comeca a gravar ciclos reais no banco de dados persistente: pelo
    Wi-Fi se conexao.json tiver o endereco do ESP32, senao pela porta serial
    detectada automaticamente. Silenciosamente nao faz nada se ja estiver
    rodando ou se nenhuma porta serial for encontrada (o painel reflete
    isso pelo /status continuar "rodando": false)."""
    global _thread_leitura, _evento_parar
    with _trava_leitura:
        if esta_rodando():
            if not _evento_parar.is_set():
                return
            # leitura anterior ainda encerrando (ex.: troca de origem) - espera
            # ela terminar para nunca haver duas lendo ao mesmo tempo
            _thread_leitura.join(timeout=15)
            if _thread_leitura.is_alive():
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
            name="leitura",
            daemon=True,
        )
        _thread_leitura.start()


def status_sincronizacao():
    """O que o painel mostra na barra de sincronizacao: origem dos dados,
    leitura rodando ou nao e, no Wi-Fi, a situacao gravada pelo monitor."""
    if MODO_NUVEM:
        return {**nuvem.status_nuvem(dir_dados_usuario()), "backup": backup_banco.status()}
    modo = monitor_wifi.modo_conexao(dir_dados_usuario())
    status = monitor_wifi.ler_status_sincronizacao(dir_dados_usuario()) if modo == "wifi" else {}
    extra = {"nuvem": enviador_nuvem.status()} if enviador_nuvem is not None else {}
    return {**status, **extra, "modo": modo, "rodando": esta_rodando(), "backup": backup_banco.status()}


def parar():
    """Pede para a leitura parar e espera ate 12 s (uma consulta ao ESP32
    pode estar no meio, com timeout de 8 s). Se ainda nao terminou, a
    thread fica registrada - iniciar() espera por ela antes de abrir outra."""
    global _thread_leitura
    with _trava_leitura:
        if not esta_rodando():
            return
        _evento_parar.set()
        _thread_leitura.join(timeout=12)
        if not _thread_leitura.is_alive():
            _thread_leitura = None


def _pin_remoto():
    try:
        with open(os.path.join(dir_dados_usuario(), ARQUIVO_SEGURANCA), "r", encoding="utf-8") as arquivo:
            pin = json.load(arquivo).get("pin_remoto", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return str(pin).strip()


_ENDERECOS_LOCAIS = {"127.0.0.1", "::1"}
_cache_ips = {"ips": (), "em": 0.0}


def _enderecos_deste_pc():
    """IPv4 E IPv6 deste PC: o Windows abre http://painel.local preferindo
    IPv6, entao o painel aberto assim no proprio PC chega por um endereco
    IPv6 dele - sem isso, cairia em "somente leitura"."""
    from anuncio_rede import _ips_locais  # so no modo local (zeroconf nao e preciso na VPS)

    ips = set(_ips_locais())
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(str(info[4][0]).split("%", 1)[0])
    except OSError:
        pass
    return tuple(ips)


def _eh_este_computador(ip):
    """True para acessos deste mesmo PC - por localhost ou pelo proprio IP
    na rede (ex.: abrindo http://painel.local aqui mesmo)."""
    ip = ip.split("%", 1)[0]
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    if ip in _ENDERECOS_LOCAIS or ip.startswith("127."):
        return True
    agora = time.monotonic()
    if agora - _cache_ips["em"] > 60:  # o IP pode mudar (troca de rede)
        _cache_ips.update({"ips": _enderecos_deste_pc(), "em": agora})
    return ip in _cache_ips["ips"]


def _eh_loopback(ip):
    ip = ip.split("%", 1)[0]
    return ip in _ENDERECOS_LOCAIS or ip.startswith("127.") or ip.startswith("::ffff:127.")


def _csv_atual():
    versao = banco.versao_ciclos(SETOR_PADRAO)
    with _trava_cache:
        if _cache_csv["versao"] != versao:
            bruto = banco.csv_do_setor(SETOR_PADRAO).encode("utf-8")
            _cache_csv.update({"versao": versao, "bruto": bruto, "gzip": gzip.compress(bruto, 6)})
        return dict(_cache_csv)


class Handler(BaseHTTPRequestHandler):
    timeout = TIMEOUT_CONEXAO_S
    protocol_version = "HTTP/1.0"

    # -- autorizacao -----------------------------------------------------

    def _ip_cliente(self):
        """IP de quem pediu: atras do Caddy (VPS) vem no X-Forwarded-For."""
        ip = self.client_address[0]
        encaminhado = self.headers.get("X-Forwarded-For", "")
        if encaminhado and _eh_loopback(ip):
            return encaminhado.split(",")[0].strip()
        return ip

    def _autorizar_visitante(self):
        """Modo nuvem: o painel e os dados so com login (HTTP Basic). Devolve
        True se pode seguir; senao ja respondeu 401/429."""
        if not MODO_NUVEM:
            return True
        ip = self._ip_cliente()
        if autenticador.bloqueado(ip):
            self._responder_json({"ok": False, "erro": "muitas tentativas - aguarde alguns minutos"}, status=429)
            return False
        if autenticador.usuario(self.headers.get("Authorization", ""), ip):
            return True
        dados = "Login necessario.".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Painel de Producao", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)
        return False

    def _pode_editar(self):
        """Este computador sempre pode; os outros so com o PIN correto. Na
        VPS ninguem edita: a configuracao vem do notebook."""
        if MODO_NUVEM:
            return False
        if _eh_este_computador(self.client_address[0]):
            return True
        pin = _pin_remoto()
        enviado = self.headers.get("X-Pin", "")
        return bool(pin) and hmac.compare_digest(pin.encode("utf-8"), enviado.encode("utf-8"))

    def _negar_edicao(self):
        self._responder_json({
            "ok": False,
            "erro": "somente_leitura",
            "pinConfigurado": bool(_pin_remoto()),
            "mensagem": "Este aparelho está em modo somente leitura. Altere pelo computador do painel ou informe o PIN.",
        }, status=403)

    # -- respostas -------------------------------------------------------

    def _responder_json(self, corpo, status=200):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pin, If-None-Match, Authorization")
        self.send_header("Access-Control-Expose-Headers", "ETag")
        self.end_headers()

    def do_GET(self):
        try:
            self._get()
        except (ConnectionError, socket.timeout):
            pass  # cliente desistiu no meio - nada a fazer
        except Exception as erro:  # noqa: BLE001 - nunca derruba o servidor
            self._erro_interno(erro)

    def do_POST(self):
        try:
            self._post()
        except (ConnectionError, socket.timeout):
            pass
        except Exception as erro:  # noqa: BLE001
            self._erro_interno(erro)

    def _erro_interno(self, erro):
        try:
            self._responder_json({"ok": False, "erro": f"{type(erro).__name__}: {erro}"}, status=500)
        except Exception:  # noqa: BLE001 - conexao ja fechada
            pass

    def _get(self):
        if not self._autorizar_visitante():
            return
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        setor = consulta.get("setor", [SETOR_PADRAO])[0]
        if url.path == "/status":
            if MODO_NUVEM:
                s = nuvem.status_nuvem(dir_dados_usuario())
                self._responder_json({"rodando": s["rodando"], "modo": "nuvem", "modoServidor": "nuvem",
                                      "versao": APP_VERSAO, "podeEditar": False, "pinConfigurado": False})
                return
            self._responder_json({
                "rodando": esta_rodando(),
                "modo": monitor_wifi.modo_conexao(dir_dados_usuario()),
                "modoServidor": "local",
                "versao": APP_VERSAO,
                "podeEditar": self._pode_editar(),
                "pinConfigurado": bool(_pin_remoto()),
            })
        elif url.path == "/sincronizacao":
            self._responder_json(status_sincronizacao())
        elif url.path == "/dados":
            self._responder_csv()
        elif url.path == "/ao-vivo":
            rodando = nuvem.status_nuvem(dir_dados_usuario())["rodando"] if MODO_NUVEM else esta_rodando()
            self._responder_json({"rodando": rodando, "maquinas": banco.obter_estado_ao_vivo(setor)})
        elif url.path == "/esp/diagnostico":
            if MODO_NUVEM:
                self._responder_json({"ok": False, "status": status_sincronizacao(),
                                      "erro": "O diagnóstico do controlador só está disponível no computador do painel, na rede da empresa."})
            else:
                self._responder_json(monitor_wifi.diagnostico_esp(status_sincronizacao()))
        elif url.path == "/config":
            self._responder_json(nuvem.config_do_setor(banco, setor))
        else:
            self._responder_estatico(url.path)

    def _responder_csv(self):
        """Historico completo em CSV. Com If-None-Match igual a versao atual
        responde 304 (sem corpo) - o painel consulta a cada 5 s, mas o
        historico so muda quando chega um ciclo novo. Comprimido com gzip
        quando o navegador aceita (CSV encolhe ~6x)."""
        atual = _csv_atual()
        etag = f'"{atual["versao"]}"'
        if self.headers.get("If-None-Match", "") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", "ETag")
            self.end_headers()
            return
        usar_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        dados = atual["gzip"] if usar_gzip else atual["bruto"]
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        if usar_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "ETag")
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
        partes = os.path.relpath(alvo, PAINEL_DIR).split(os.sep)
        oculto = any(p.startswith(("_", ".")) for p in partes)  # painel/_backup/ etc. nunca sao servidos
        if not (alvo == PAINEL_DIR or alvo.startswith(PAINEL_DIR + os.sep)) or oculto or not os.path.isfile(alvo):
            self.send_response(404)
            self.send_header("Content-Length", "0")
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
        # no-cache: o navegador sempre confere - depois de atualizar o app,
        # nenhum aparelho fica preso na versao antiga do painel.
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _corpo_json(self):
        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        if not tamanho:
            return {}
        if tamanho > MAX_CORPO_BYTES:
            raise ValueError("corpo grande demais")
        corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        return corpo if isinstance(corpo, dict) else {}

    def _post(self):
        rota = urlparse(self.path).path
        if MODO_NUVEM and rota.startswith("/api/nuvem/"):
            self._post_nuvem(rota)
            return
        if not self._autorizar_visitante():
            return
        if rota not in ("/iniciar", "/parar", "/config", "/esp/acao", "/conexao"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._pode_editar():
            self._negar_edicao()
            return
        if rota == "/iniciar":
            iniciar()
            self._responder_json({"rodando": esta_rodando()})
        elif rota == "/parar":
            parar()
            self._responder_json({"rodando": esta_rodando()})
        elif rota == "/config":
            self._salvar_config()
        elif rota == "/esp/acao":
            try:
                corpo = self._corpo_json()
            except (ValueError, UnicodeDecodeError):
                corpo = {}
            self._responder_json(monitor_wifi.acao_esp(status_sincronizacao(), str(corpo.get("acao", ""))))
        elif rota == "/conexao":
            self._salvar_conexao()

    def _post_nuvem(self, rota):
        """VPS: recebe do ESP32 (/api/nuvem/enviar) e do notebook
        (/api/nuvem/config). Chave errada -> 403 (o ESP32 e o notebook
        mostram "chave recusada")."""
        if rota not in ("/api/nuvem/enviar", "/api/nuvem/config", "/api/nuvem/ping"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ip = self._ip_cliente()
        if autenticador.bloqueado(ip):
            self._responder_json({"ok": False, "erro": "muitas tentativas"}, status=429)
            return
        if not nuvem.chave_confere(NUVEM_CHAVE, self.headers.get("X-Chave-Nuvem", "")):
            with autenticador._trava:
                autenticador._falhas.setdefault(ip, []).append(time.monotonic())
            self._responder_json({"ok": False, "erro": "chave invalida"}, status=403)
            return
        if rota == "/api/nuvem/ping":  # so confere a chave (teste da instalacao), nao grava nada
            self._responder_json({"ok": True, "versao": APP_VERSAO})
            return
        try:
            corpo = self._corpo_json()
            if rota == "/api/nuvem/enviar":
                resposta = nuvem.receber_do_esp(banco, dir_dados_usuario(), SETOR_PADRAO, corpo, ip)
            else:
                resposta = nuvem.receber_config(banco, dir_dados_usuario(), corpo, SETOR_PADRAO)
        except (ValueError, UnicodeDecodeError) as erro:
            self._responder_json({"ok": False, "erro": str(erro)}, status=400)
            return
        self._responder_json(resposta)

    def _salvar_config(self):
        try:
            corpo = self._corpo_json()
        except (ValueError, UnicodeDecodeError):
            self._responder_json({"ok": False, "erro": "JSON invalido"}, status=400)
            return
        nuvem.aplicar_config(banco, corpo, SETOR_PADRAO)
        self._responder_json({"ok": True})

    def _salvar_conexao(self):
        """Troca a origem dos dados (Wi-Fi do ESP32 ou cabo USB) pelo
        painel - grava no conexao.json e reinicia a leitura na origem nova."""
        try:
            modo = self._corpo_json().get("modo")
        except (ValueError, UnicodeDecodeError):
            modo = None
        if modo not in ("wifi", "serial"):
            self._responder_json({"ok": False, "erro": "modo deve ser wifi ou serial"}, status=400)
            return
        monitor_wifi.salvar_modo_conexao(dir_dados_usuario(), modo)
        parar()
        iniciar()
        self._responder_json({"ok": True, **status_sincronizacao()})

    def log_message(self, format, *args):
        pass  # silencia o log padrao (GET /status a cada poucos segundos)


class _ServidorExclusivo(ThreadingHTTPServer):
    """Servidor que atende varias requisicoes ao mesmo tempo (uma consulta
    lenta ao ESP32 nao trava o painel dos outros) e NAO divide a porta com
    outro processo.

    O HTTPServer padrao liga SO_REUSEADDR - no Windows isso deixa DOIS
    processos escutando a mesma porta ao mesmo tempo (ex.: uma segunda
    janela do app, ou uma que nao fechou direito), e as requisicoes caem
    ora num, ora no outro: painel instavel, "so funciona fechando e
    abrindo". Com SO_EXCLUSIVEADDRUSE a segunda tentativa falha na hora
    (OSError) e o main.py mostra "O Painel ja esta aberto em outra janela".
    """

    daemon_threads = True
    allow_reuse_address = False
    allow_reuse_port = False
    # IPv6 + IPv4 no mesmo socket ("dual-stack"): o Windows traduz nomes
    # (painel.local, nome do PC) primeiro para IPv6 - so IPv4 dava timeout.
    address_family = socket.AF_INET6 if ":" in ENDERECO_ESCUTA else socket.AF_INET
    anuncio = None  # AnuncioRede (painel.local), encerrado junto com o servidor
    parar_backup = None
    parar_nuvem = None

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # so existe no Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

    def server_close(self):
        if self.anuncio is not None:
            self.anuncio.parar()
            self.anuncio = None
        if self.parar_backup is not None:
            self.parar_backup.set()
            self.parar_backup = None
        if self.parar_nuvem is not None:
            self.parar_nuvem.set()
            self.parar_nuvem = None
        super().server_close()


def iniciar_servidor_em_thread():
    """Sobe o servidor numa thread daemon e devolve a instancia, para o
    chamador poder encerra-lo (shutdown()) ao fechar a janela."""
    # Aceita conexoes de qualquer placa de rede: o painel abre neste PC
    # (http://localhost) e em outros computadores/celulares da mesma rede
    # (http://painel.local ou http://<IP-deste-PC>) - somente leitura para
    # eles, a menos que informem o PIN (ver docstring do modulo).
    global enviador_nuvem
    if not MODO_NUVEM:
        monitor_wifi.definir_chave_api(dir_dados_usuario())  # acoes do diagnostico mesmo com a leitura pausada
    servidor = _ServidorExclusivo((ENDERECO_ESCUTA, PORTA_SERVIDOR), Handler)
    thread = threading.Thread(target=servidor.serve_forever, name="servidor-http", daemon=True)
    thread.start()
    servidor.parar_backup = backup_banco.iniciar(banco, dir_dados_usuario(), pasta=dir_backup())
    if MODO_NUVEM:
        return servidor  # VPS: o ESP32 envia sozinho; nada de leitura nem anuncio local
    from anuncio_rede import AnuncioRede

    servidor.anuncio = AnuncioRede(PORTA_SERVIDOR)
    servidor.anuncio.iniciar()
    # acesso remoto: a configuracao editada aqui vai para a VPS
    enviador_nuvem = nuvem.EnviadorConfig(banco, dir_dados_usuario(), SETOR_PADRAO)
    servidor.parar_nuvem = enviador_nuvem.iniciar()
    # No Wi-Fi a sincronizacao comeca sozinha ao abrir o app - e so conectar
    # o notebook na rede do ESP32 (ou da empresa). Pela USB continua manual.
    if monitor_wifi.modo_conexao(dir_dados_usuario()) == "wifi":
        iniciar()
    return servidor
