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
login por SENHA UNICA (definida no notebook, chega aqui como hash junto com
a configuracao) e SEMPRE somente leitura - atras do proxy toda visita chega
de 127.0.0.1, que no modo local seria "este computador".
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
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlparse

from caminhos import dir_backup, dir_base_bundle, dir_dados_usuario

APP_VERSAO = "1.7.5"
MODO_NUVEM = os.environ.get("PAINEL_MODO", "").strip().lower() == "nuvem"
# porta padrao da web: http://painel.local (sem ":porta"); na VPS fica atras do Caddy
PORTA_SERVIDOR = int(os.environ.get("PAINEL_PORTA") or (8080 if MODO_NUVEM else 80))
# todas as placas de rede (acesso por outros PCs); na VPS so o Caddy, na mesma maquina
ENDERECO_ESCUTA = os.environ.get("PAINEL_ESCUTA") or ("127.0.0.1" if MODO_NUVEM else "::")
NUVEM_CHAVE = os.environ.get("NUVEM_CHAVE", "").strip()  # VPS: a mesma do .env da fabrica
TIMEOUT_CONEXAO_S = 30  # cliente parado no meio da requisicao nao prende uma thread para sempre
MAX_CORPO_BYTES = 1_000_000
ARQUIVO_SEGURANCA = "seguranca.json"
ROTAS_HARDWARE = ("/iniciar", "/parar", "/esp/acao", "/conexao")  # nunca pela VPS

_BASE = dir_base_bundle()
PAINEL_DIR = os.path.normpath(os.path.join(_BASE, "painel"))
FERRAMENTAS_DIR = os.path.join(_BASE, "ferramentas")

sys.path.insert(0, FERRAMENTAS_DIR)
import backup_banco  # noqa: E402 (precisa do sys.path.insert acima)
import monitor_serial  # noqa: E402
import monitor_wifi  # noqa: E402
import nuvem  # noqa: E402
from banco_dados import BancoDados, NOME_ARQUIVO, imagem_do_logo  # noqa: E402
from monitor_serial import SETOR_PADRAO  # noqa: E402

banco = BancoDados(os.path.join(dir_dados_usuario(), NOME_ARQUIVO))
limite = nuvem.LimiteTentativas() if MODO_NUVEM else None
sessoes = nuvem.Sessoes(dir_dados_usuario()) if MODO_NUVEM else None
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


# ---------------------------------------------------------------------
# Programa remoto para download na VPS (PainelSantexRemoto.exe)
# ---------------------------------------------------------------------
ARQUIVO_APP_REMOTO = "PainelSantexRemoto.exe"  # nome interno (ASCII)
NOME_DOWNLOAD_APP_REMOTO = "Painel de Produção.exe"  # nome com que o arquivo chega ao usuario
_cache_app_remoto = {"chave": None, "info": None}


def _caminho_app_remoto():
    """Onde esta o .exe para download, em ordem: enviado a mao para a pasta
    de dados (/var/lib/painel-nuvem/app-remoto), instalado pelo
    vps/instalar.sh (/opt/painel-nuvem/app-remoto) ou o do repositorio
    (vps/app-remoto, rodando do clone). None = nao disponivel."""
    for pasta in (os.path.join(dir_dados_usuario(), "app-remoto"), os.path.join(_BASE, "app-remoto"),
                  os.path.join(_BASE, "vps", "app-remoto")):
        caminho = os.path.join(pasta, ARQUIVO_APP_REMOTO)
        if os.path.isfile(caminho):
            return caminho
    return None


def info_app_remoto():
    """{"disponivel", "versao", "tamanho", "atualizado_em"} - lido do .json ao
    lado do .exe (gerar/exe_remoto.py), com cache pela data do arquivo."""
    caminho = _caminho_app_remoto()
    if not caminho:
        return {"disponivel": False}
    estado = os.stat(caminho)
    chave = (caminho, estado.st_mtime_ns, estado.st_size)
    if _cache_app_remoto["chave"] != chave:
        try:
            with open(os.path.splitext(caminho)[0] + ".json", "r", encoding="utf-8") as arquivo:
                meta = json.load(arquivo)
        except (OSError, ValueError):
            meta = {}
        _cache_app_remoto.update(chave=chave, info={
            "disponivel": True, "tamanho": estado.st_size, "versao": str(meta.get("versao", ""))[:20],
            "atualizado_em": str(meta.get("gerado_em", ""))[:25], "url": "/app-remoto/" + ARQUIVO_APP_REMOTO,
            "nome": NOME_DOWNLOAD_APP_REMOTO,
            "icone": "/app-remoto/icone.png" if os.path.isfile(os.path.join(os.path.dirname(caminho), "icone.png")) else ""})
    return dict(_cache_app_remoto["info"])


class _SemCorpo:
    """Saida que descarta o corpo da resposta (requisicoes HEAD)."""

    closed = False

    def write(self, dados):
        return len(dados)

    def flush(self):
        pass

    def close(self):
        pass


class Handler(BaseHTTPRequestHandler):
    timeout = TIMEOUT_CONEXAO_S
    protocol_version = "HTTP/1.0"

    # -- autorizacao -----------------------------------------------------

    def _ip_cliente(self):
        """IP de quem pediu: atras do proxy da VPS (LiteSpeed/Caddy) vem no
        X-Forwarded-For. Vale o ULTIMO item - o que o proxy acrescentou; os
        anteriores vem do proprio cliente e podem ser inventados (trocar de
        "IP" a cada tentativa burlaria o bloqueio por senhas erradas)."""
        ip = self.client_address[0]
        encaminhado = self.headers.get("X-Forwarded-For", "")
        if encaminhado and _eh_loopback(ip):
            return encaminhado.split(",")[-1].strip() or ip
        return ip

    def end_headers(self):
        if MODO_NUVEM:  # painel publico na internet: protecoes do navegador
            self.send_header("X-Frame-Options", "DENY")  # nenhum site embute o painel (clickjacking)
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()
        if self.command == "HEAD" and not hasattr(self, "_wfile_real"):
            # HEAD: mesmos cabecalhos do GET, corpo descartado
            self._wfile_real, self.wfile = self.wfile, _SemCorpo()

    def finish(self):
        if hasattr(self, "_wfile_real"):
            self.wfile = self._wfile_real
        super().finish()

    @staticmethod
    def _hashes_papeis():
        """Senha atual de cada papel; edicao so vale se o notebook deixar."""
        edicao = nuvem.dados_senha_edicao(banco).get("hash") if nuvem.edicao_remota_ativa(banco) else None
        return {"leitura": nuvem.dados_senha_remota(banco).get("hash"), "edicao": edicao}

    def _papel(self):
        """"local" fora da VPS; na VPS "leitura"/"edicao" pela sessao, ou None."""
        if not MODO_NUVEM:
            return "local"
        if hasattr(self, "_papel_cache"):
            return self._papel_cache
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001 - cookie malformado = sem sessao
            cookie = SimpleCookie()
        token = cookie[nuvem.COOKIE_SESSAO].value if nuvem.COOKIE_SESSAO in cookie else ""
        self._papel_cache = sessoes.papel(token, self._hashes_papeis())
        return self._papel_cache

    def _sessao_valida(self):
        return self._papel() is not None

    @staticmethod
    def _cookie_sessao(token):
        return (f"{nuvem.COOKIE_SESSAO}={token}; Path=/; Max-Age={nuvem.DIAS_SESSAO * 86400}; "
                "HttpOnly; Secure; SameSite=Lax")

    def _autorizar_visitante(self):
        """Modo nuvem: o painel e os dados so depois do login (senha unica).
        Sem sessao: a pagina inicial vira a tela de login e o resto responde
        401 (o painel recarrega e cai na tela de login). Devolve True se pode
        seguir; senao ja respondeu."""
        if not MODO_NUVEM:
            return True
        caminho = urlparse(self.path).path
        if self.command in ("GET", "HEAD") and caminho in ("/assets/logo.png", "/assets/icone-empresa.png"):
            return True  # o logo e o icone aparecem na propria tela de login
        if self._sessao_valida():
            return True
        if self.command in ("GET", "HEAD") and caminho in ("/", "/index.html"):
            self._responder_html(nuvem.pagina_login(senha_definida=any(self._hashes_papeis().values()),
                                                    app_remoto=info_app_remoto()))
        else:
            self._responder_json({"ok": False, "erro": "login"}, status=401)
        return False

    def _responder_html(self, html, status=200, cabecalhos=None):
        dados = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for nome, valor in (cabecalhos or {}).items():
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _redirecionar(self, destino, cookie=None):
        self.send_response(303)
        self.send_header("Location", destino)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login(self):
        """POST /login (VPS): confere a senha unica e abre a sessao (30 dias)."""
        ip = self._ip_cliente()
        if limite.bloqueado(ip):
            self._responder_html(nuvem.pagina_login("Muitas tentativas erradas. Aguarde 10 minutos."), status=429)
            return
        tamanho = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
        bruto = self.rfile.read(tamanho).decode("utf-8", errors="replace") if tamanho else ""
        if "json" in self.headers.get("Content-Type", ""):
            try:
                senha = str(json.loads(bruto).get("senha", ""))
            except (ValueError, AttributeError):
                senha = ""
        else:
            senha = parse_qs(bruto).get("senha", [""])[0]
        hashes = self._hashes_papeis()
        for papel in ("edicao", "leitura"):  # edicao primeiro: as duas senhas sao diferentes
            if hashes[papel] and nuvem.verificar_senha(senha, hashes[papel]):
                self._redirecionar("/", self._cookie_sessao(sessoes.criar(hashes[papel], papel)))
                return
        edicao = nuvem.dados_senha_edicao(banco).get("hash")
        if not hashes["edicao"] and edicao and nuvem.verificar_senha(senha, edicao):
            self._responder_html(nuvem.pagina_login(
                "A edição remota está desligada no computador da fábrica. Use a senha de visualização."), status=403)
            return
        limite.falhou(ip)
        self._responder_html(nuvem.pagina_login("Senha incorreta.", senha_definida=any(hashes.values())), status=401)

    def _pode_editar(self):
        """Este computador (o mestre) sempre pode; os outros da rede local so
        com o PIN correto. Na VPS, so quem entrou com a senha de edicao."""
        if MODO_NUVEM:
            return self._papel() == "edicao"
        if _eh_este_computador(self.client_address[0]):
            return True
        pin = _pin_remoto()
        enviado = self.headers.get("X-Pin", "")
        return bool(pin) and hmac.compare_digest(pin.encode("utf-8"), enviado.encode("utf-8"))

    def _origem_confere(self):
        """Contra CSRF na VPS: edicao exige o cabecalho X-Painel-Edicao (um
        formulario de outro site nao consegue enviar) e, se o navegador mandar
        Origin, ele precisa ser este mesmo site."""
        if self.headers.get("X-Painel-Edicao", "") != "1":
            return False
        origem = self.headers.get("Origin", "")
        if not origem:
            return True
        hosts = {self.headers.get("Host", "")}
        if _eh_loopback(self.client_address[0]):  # atras do proxy
            hosts.add(self.headers.get("X-Forwarded-Host", "").split(",")[0].strip())
        return urlparse(origem).netloc in {h for h in hosts if h}

    def _negar_edicao(self):
        if MODO_NUVEM:
            self._responder_json({
                "ok": False, "erro": "somente_leitura", "pinConfigurado": False,
                "mensagem": "Seu acesso é só de visualização. Entre com a senha de edição para alterar.",
            }, status=403)
            return
        self._responder_json({
            "ok": False,
            "erro": "somente_leitura",
            "pinConfigurado": bool(_pin_remoto()),
            "mensagem": "Este aparelho está em modo somente leitura. Altere pelo computador do painel ou informe o PIN.",
        }, status=403)

    # -- respostas -------------------------------------------------------

    def _responder_json(self, corpo, status=200, cabecalhos=None, cors=True):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if not MODO_NUVEM and cors:  # na VPS o painel e do mesmo site: nada de CORS
            self.send_header("Access-Control-Allow-Origin", "*")
        for nome, valor in (cabecalhos or {}).items():
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_OPTIONS(self):
        self.send_response(204)
        if MODO_NUVEM:  # outro site nunca e liberado a chamar a VPS
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pin, X-Painel-Edicao, If-None-Match, Authorization")
        self.send_header("Access-Control-Expose-Headers", "ETag")
        self.end_headers()

    def do_GET(self):
        try:
            self._get()
        except (ConnectionError, socket.timeout):
            pass  # cliente desistiu no meio - nada a fazer
        except Exception as erro:  # noqa: BLE001 - nunca derruba o servidor
            self._erro_interno(erro)

    def do_HEAD(self):
        """Monitores de disponibilidade (UptimeRobot etc.) usam HEAD - antes
        respondia 501 e o site parecia fora do ar."""
        self.do_GET()

    def do_POST(self):
        try:
            self._post()
        except (ConnectionError, socket.timeout):
            pass
        except Exception as erro:  # noqa: BLE001
            self._erro_interno(erro)

    def _erro_interno(self, erro):
        # detalhe completo no log - no notebook o app.log (main.py), na VPS o
        # journalctl -u painel-nuvem; na internet o visitante so ve "erro interno"
        logging.getLogger("painel").error("Erro interno em %s %s", self.command, urlparse(self.path).path,
                                          exc_info=(type(erro), erro, erro.__traceback__))
        mensagem = "erro interno" if MODO_NUVEM else f"{type(erro).__name__}: {erro}"
        try:
            self._responder_json({"ok": False, "erro": mensagem}, status=500)
        except Exception:  # noqa: BLE001 - conexao ja fechada
            pass

    def _get(self):
        if MODO_NUVEM and urlparse(self.path).path.startswith("/app-remoto"):
            self._responder_app_remoto()  # publico: o programa nao tem segredo nenhum (e pede a senha)
            return
        if not self._autorizar_visitante():
            return
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        setor = consulta.get("setor", [SETOR_PADRAO])[0]
        if url.path == "/status":
            if MODO_NUVEM:
                s = nuvem.status_nuvem(dir_dados_usuario())
                self._responder_json({"rodando": s["rodando"], "modo": "nuvem", "modoServidor": "nuvem",
                                      "versao": APP_VERSAO, "podeEditar": self._pode_editar(), "pinConfigurado": False,
                                      "papel": self._papel(), "configRev": nuvem.versao_config()})
                return
            self._responder_json({
                "rodando": esta_rodando(),
                "modo": monitor_wifi.modo_conexao(dir_dados_usuario()),
                "modoServidor": "local",
                "versao": APP_VERSAO,
                "podeEditar": self._pode_editar(),
                "pinConfigurado": bool(_pin_remoto()),
                "papel": "local" if _eh_este_computador(self.client_address[0]) else "rede",
                "configRev": nuvem.versao_config(),
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
            config = nuvem.config_do_setor(banco, setor)
            if not MODO_NUVEM and self._pode_editar():  # notebook: situacao das senhas remotas (nunca o hash)
                config["acessoRemoto"] = {**nuvem.status_senha_remota(banco),
                                          "url": nuvem.config_nuvem_app(dir_dados_usuario())["url"]}
            elif MODO_NUVEM and self._papel() == "edicao":
                config["acessoRemoto"] = {**nuvem.status_senha_remota(banco), "url": ""}
            config["configRev"] = nuvem.versao_config()
            self._responder_json(config)
        elif url.path == "/alteracoes":
            if not self._pode_editar():
                self._negar_edicao()
                return
            avisos = enviador_nuvem.avisos() if enviador_nuvem is not None else []
            self._responder_json({"alteracoes": banco.ultimas_alteracoes(50), "avisos": avisos})
        elif url.path == "/acesso-remoto/senhas":
            if not self._so_este_computador():
                return
            self._responder_json({"ok": True, "senhas": nuvem.senhas_guardadas(banco)}, cors=False)
        else:
            self._responder_estatico(url.path)

    def _so_este_computador(self):
        """1.7.2: o texto das senhas remotas so aparece no proprio painel do
        computador da fabrica - nunca na VPS, num aparelho da rede (nem com o
        PIN) ou num site aberto no navegador deste PC: exige localhost no Host
        (contra DNS rebinding), nenhuma Origin de fora e o cabecalho do painel;
        a resposta sai sem CORS."""
        host = (self.headers.get("Host") or "").lower()
        nome_host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        origem = self.headers.get("Origin")
        origem_ok = origem is None or urlparse(origem).hostname in ("localhost", "127.0.0.1", "::1")
        if (MODO_NUVEM or not _eh_este_computador(self.client_address[0])
                or nome_host not in ("localhost", "127.0.0.1", "[::1]")
                or not origem_ok or self.headers.get("X-Painel-Edicao") != "1"):
            self._responder_json({"ok": False, "erro": "Só no painel do computador da fábrica."}, status=403, cors=False)
            return False
        return True

    def _responder_app_remoto(self):
        """VPS: GET /app-remoto (informacoes) e /app-remoto/PainelSantexRemoto.exe."""
        caminho_url = urlparse(self.path).path.rstrip("/")
        info = info_app_remoto()
        if caminho_url == "/app-remoto":
            self._responder_json(info)
            return
        caminho = _caminho_app_remoto()
        icone = os.path.join(os.path.dirname(caminho), "icone.png") if caminho else ""
        if caminho_url == "/app-remoto/icone.png" and os.path.isfile(icone):
            with open(icone, "rb") as arquivo:
                dados = arquivo.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
            return
        if caminho_url != "/app-remoto/" + ARQUIVO_APP_REMOTO or not caminho:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.microsoft.portable-executable")
        # nome com acento: filename* (RFC 6266) + alternativa ASCII para navegadores antigos
        self.send_header("Content-Disposition", 'attachment; filename="Painel de Producao.exe"; '
                         f"filename*=UTF-8''{quote(NOME_DOWNLOAD_APP_REMOTO)}")
        self.send_header("Content-Length", str(info["tamanho"]))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(caminho, "rb") as arquivo:
            while True:
                bloco = arquivo.read(256 * 1024)
                if not bloco:
                    break
                self.wfile.write(bloco)

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

    def _responder_logo_empresa(self, caminho_url):
        """Logo enviado em Identidade visual (config_extra "logo"): substitui o
        assets/logo.png em todo lugar (painel, PDF, login da VPS, programa
        remoto). O icone do navegador e o enviado ou, sem ele, o proprio logo.
        Devolve False quando nao ha logo guardado (serve o arquivo padrao)."""
        try:
            extras = banco.obter_extras(SETOR_PADRAO)
        except Exception:  # noqa: BLE001 - banco indisponivel: arquivo padrao
            return False
        img = None
        if caminho_url == "/assets/icone-empresa.png":
            img = imagem_do_logo(extras, "icone")
        if img is None:
            img = imagem_do_logo(extras, "logo")
        if img is None:
            if caminho_url != "/assets/icone-empresa.png":
                return False
            caminho_padrao = os.path.join(PAINEL_DIR, "assets", "logo.png")
            if not os.path.isfile(caminho_padrao):
                return False
            with open(caminho_padrao, "rb") as arquivo:
                img = (arquivo.read(), "image/png")
        dados, tipo = img
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)
        return True

    def _responder_estatico(self, caminho_url):
        """Serve o painel (index.html, assets/logo.png, ...) direto da
        pasta painel/ - e como o painel passa a ser aberto, em vez de
        file://, pra evitar qualquer restricao de fetch/XHR que alguns
        webviews impoem a paginas abertas como arquivo local."""
        if caminho_url == "/":
            caminho_url = "/index.html"
        if caminho_url in ("/assets/logo.png", "/assets/icone-empresa.png") and self._responder_logo_empresa(caminho_url):
            return

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
        if MODO_NUVEM and rota == "/login":
            self._login()
            return
        if MODO_NUVEM and rota == "/logout":
            self._redirecionar("/", f"{nuvem.COOKIE_SESSAO}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
            return
        if not self._autorizar_visitante():
            return
        if rota == "/esp/firmware":  # 1.7.4: atualizar o firmware do ESP32 pelo painel deste computador
            if not self._so_este_computador():
                return
            try:
                tamanho = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                tamanho = 0
            if not 0 < tamanho <= monitor_wifi.TAMANHO_MAX_FIRMWARE:
                mensagem = (monitor_wifi.validar_firmware(b"") if tamanho <= 0 else
                            "Arquivo grande demais para o controlador — use o controle_producao_horimetro.ino.bin "
                            "(não o .merged.bin).")
                self._responder_json({"ok": False, "mensagem": mensagem}, status=400, cors=False)
                return
            self.connection.settimeout(120)  # 1,3 MB pela rede local
            dados = self.rfile.read(tamanho)
            nome = unquote(self.headers.get("X-Arquivo", "") or "firmware.bin")
            r = monitor_wifi.atualizar_firmware_esp(status_sincronizacao(), dados, nome, dir_dados_usuario())
            self._responder_json(r, status=200 if r.get("ok") else 400, cors=False)
            return
        if rota == "/acesso-remoto/guardar":  # 1.7.2: guarda o texto de uma senha remota que ja vale
            if not self._so_este_computador():
                return
            try:
                corpo = self._corpo_json()
            except (ValueError, UnicodeDecodeError):
                corpo = {}
            papel = corpo.get("papel")
            if papel not in ("leitura", "edicao"):
                self._responder_json({"ok": False, "erro": "papel inválido"}, status=400, cors=False)
                return
            if not nuvem.guardar_senha_texto(banco, papel, corpo.get("senha", "")):
                self._responder_json({"ok": False, "erro": "Essa não é a senha em vigor — nada foi guardado. "
                                      "Se ninguém lembra, defina uma nova acima."}, status=400, cors=False)
                return
            self._responder_json({"ok": True, "senhas": nuvem.senhas_guardadas(banco)}, cors=False)
            return
        if rota not in ("/iniciar", "/parar", "/config", "/esp/acao", "/conexao"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if MODO_NUVEM and rota in ROTAS_HARDWARE:
            self._responder_json({"ok": False, "erro": "so_no_computador_do_painel",
                                  "mensagem": "Leitura e controlador só pelo computador da fábrica."}, status=403)
            return
        if not self._pode_editar():
            self._negar_edicao()
            return
        if MODO_NUVEM and not self._origem_confere():
            self._responder_json({"ok": False, "erro": "origem"}, status=403)
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
        if rota not in ("/api/nuvem/enviar", "/api/nuvem/config", "/api/nuvem/historico", "/api/nuvem/ping"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ip = self._ip_cliente()
        # Chave certa passa sempre: tentativas erradas de terceiros (no mesmo
        # IP ou com o IP mascarado pelo proxy) nunca travam o ESP32/notebook.
        if not nuvem.chave_confere(NUVEM_CHAVE, self.headers.get("X-Chave-Nuvem", "")):
            if limite.bloqueado(ip):
                self._responder_json({"ok": False, "erro": "muitas tentativas"}, status=429)
                return
            limite.falhou(ip)
            self._responder_json({"ok": False, "erro": "chave invalida"}, status=403)
            return
        if rota == "/api/nuvem/ping":  # so confere a chave (teste da instalacao), nao grava nada
            self._responder_json({"ok": True, "versao": APP_VERSAO})
            return
        try:
            corpo = self._corpo_json()
            if rota == "/api/nuvem/enviar":
                resposta = nuvem.receber_do_esp(banco, dir_dados_usuario(), SETOR_PADRAO, corpo, ip)
            elif rota == "/api/nuvem/historico":
                resposta = nuvem.receber_historico(banco, dir_dados_usuario(), corpo, SETOR_PADRAO)
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
        origem = "nuvem" if MODO_NUVEM else "notebook"
        if MODO_NUVEM:
            autor = f"edição remota ({self._ip_cliente()})"
        else:  # o proprio computador da fabrica, ou um aparelho da rede com o PIN
            autor = "notebook" if _eh_este_computador(self.client_address[0]) else f"rede local ({self.client_address[0]})"
        senhas = {papel: corpo[campo] for campo, papel in (("senhaRemota", "leitura"), ("senhaEdicao", "edicao"))
                  if campo in corpo}
        cabecalhos = {}
        if senhas:  # so o hash e guardado
            if MODO_NUVEM:  # pela VPS: so redigitando a senha de edicao atual (sessao roubada nao basta)
                atual = nuvem.dados_senha_edicao(banco).get("hash")
                ip = self._ip_cliente()
                if limite.bloqueado(ip):
                    self._responder_json({"ok": False, "erro": "Muitas tentativas erradas. Aguarde 10 minutos."}, status=429)
                    return
                if not (atual and nuvem.verificar_senha(str(corpo.get("senhaAtual", "")), atual)):
                    limite.falhou(ip)
                    self._responder_json({"ok": False, "erro": "Senha de edição atual incorreta."}, status=403)
                    return
            try:
                for papel, senha in senhas.items():
                    nuvem.definir_senha(banco, papel, senha, origem, autor)
                    if not MODO_NUVEM:  # 1.7.2: o notebook guarda o texto para consulta (a VPS nunca)
                        nuvem.guardar_senha_texto(banco, papel, senha)
            except ValueError as erro:
                self._responder_json({"ok": False, "erro": str(erro)}, status=400)
                return
            if MODO_NUVEM and "edicao" in senhas:  # quem trocou continua conectado com a senha nova
                cabecalhos["Set-Cookie"] = self._cookie_sessao(
                    sessoes.criar(nuvem.dados_senha_edicao(banco)["hash"], "edicao"))
        if "edicaoRemota" in corpo:
            if MODO_NUVEM:  # so o notebook (mestre) liga/desliga
                self._responder_json({"ok": False, "erro": "Só o computador da fábrica liga ou desliga a edição remota."}, status=403)
                return
            nuvem.definir_edicao_remota(banco, bool(corpo["edicaoRemota"]))
        nuvem.aplicar_config(banco, corpo, SETOR_PADRAO, origem=origem, autor=autor)
        if enviador_nuvem is not None:  # chega a VPS sem esperar a proxima troca
            threading.Thread(target=enviador_nuvem.enviar_agora, daemon=True).start()
        self._responder_json({"ok": True, "acessoRemoto": nuvem.status_senha_remota(banco),
                              "configRev": nuvem.versao_config()}, cabecalhos=cabecalhos)

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
    # Linux: SO_REUSEADDR NAO deixa dois processos escutarem a mesma porta
    # (o segundo bind falha do mesmo jeito); so permite reabrir a porta logo
    # apos um reinicio. Sem ele, as conexoes em TIME-WAIT bloqueiam a porta
    # por ~60 s e o painel da VPS fica fora do ar a cada deploy/reinicio.
    # No Windows continua desligado (la ele divide a porta; vale o
    # SO_EXCLUSIVEADDRUSE de server_bind).
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")
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
