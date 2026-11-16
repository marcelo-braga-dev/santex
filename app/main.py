"""
Ponto de entrada do aplicativo desktop "Painel de Producao".

Abre uma janela nativa (sem navegador, sem barra de endereco) mostrando o
mesmo painel web do projeto, com o servidor de leitura/API rodando
embutido no mesmo processo - o usuario so da duplo clique no .exe gerado
e tudo funciona, sem instalar Python/bibliotecas separadamente.

Sequencia de abertura (para nunca ficar uma "tela branca" sem explicacao):
  1. (so no .exe) imagem de abertura do PyInstaller enquanto o arquivo
     unico se descompacta - fechada assim que a janela aparece;
  2. a janela abre JA mostrando a tela "Carregando..." (tela_inicial.py,
     HTML autocontido, nao depende do servidor);
  3. numa thread: sobe o servidor interno, espera ele responder e so entao
     carrega o painel (load_url);
  4. se algo falhar (porta ocupada, painel ja aberto em outra janela,
     servidor sem resposta, erro inesperado), a mesma tela mostra o motivo
     com "Tentar novamente" - e o erro vai para dados/app.log.

Uso em desenvolvimento:
    cd app
    pip install -r requirements.txt
    python main.py

Gerar o .exe: ver build_exe.py.
"""

import json
import logging
import os
import sys
import threading
import time
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webview  # noqa: E402 (pywebview)

from caminhos import dir_dados_usuario, dir_perfil_webview  # noqa: E402
from tela_inicial import COR_FUNDO, html_tela_inicial  # noqa: E402

TITULO_JANELA = "Painel de Produção"
TEMPO_MAX_SERVIDOR_S = 20  # espera maxima pela primeira resposta do servidor interno

ARQUIVO_LOG = os.path.join(dir_dados_usuario(), "app.log")


def _configurar_log():
    try:  # mantem o registro pequeno: recomeca quando passa de ~1 MB
        if os.path.getsize(ARQUIVO_LOG) > 1_000_000:
            os.remove(ARQUIVO_LOG)
    except OSError:
        pass
    logging.basicConfig(
        filename=ARQUIVO_LOG,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


_configurar_log()
log = logging.getLogger("painel")

# O servidor e importado depois do log, para registrar tambem erro de import
# (ex.: arquivo faltando dentro do .exe).
try:
    from servidor import PORTA_SERVIDOR, iniciar_servidor_em_thread, parar  # noqa: E402
    ERRO_IMPORT = None
except Exception:  # noqa: BLE001 - qualquer falha aqui vira a tela de erro
    log.exception("Falha ao importar o servidor interno")
    PORTA_SERVIDOR, iniciar_servidor_em_thread, parar = 80, None, (lambda: None)
    ERRO_IMPORT = traceback.format_exc(limit=4)

URL_PAINEL = "http://localhost/" if PORTA_SERVIDOR == 80 else f"http://localhost:{PORTA_SERVIDOR}/"


def _fechar_imagem_abertura():
    """Fecha a imagem de abertura do PyInstaller (--splash), se houver."""
    try:
        import pyi_splash  # existe so dentro do .exe gerado com --splash

        pyi_splash.close()
    except Exception:  # noqa: BLE001 - sem splash (dev ou build sem Tk)
        pass


def servidor_responde(timeout=1.5):
    """True se ha um Painel de Producao respondendo em URL_PAINEL (este ou
    outra janela do app ja aberta)."""
    try:
        with urllib.request.urlopen(URL_PAINEL + "status", timeout=timeout) as resposta:
            return "rodando" in json.loads(resposta.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


class Inicializacao:
    """Sobe o servidor e leva a janela da tela de carregando ate o painel."""

    def __init__(self):
        self.janela = None
        self.servidor = None
        self._executando = threading.Lock()

    def _estado(self, estado, mensagem, etapa="", detalhe="", passo=None):
        """passo = etapa em andamento na lista da tela (0 = Servidor
        interno, 1 = Interface); o painel continua a mesma lista."""
        if self.janela is None:
            return
        dados = json.dumps({"estado": estado, "mensagem": mensagem, "etapa": etapa, "detalhe": detalhe, "passo": passo})
        try:
            self.janela.evaluate_js(f"window.definirEstado && definirEstado({dados})")
        except Exception:  # noqa: BLE001 - janela fechando, ou tela ainda carregando
            pass

    def _falha(self, mensagem, detalhe="", passo=0):
        log.error("%s %s", mensagem, detalhe)
        self._estado("falha", mensagem, "Nada foi perdido: os dados ficam guardados no banco do aplicativo.", detalhe, passo)

    def executar(self):
        if not self._executando.acquire(blocking=False):
            return  # ja tem uma tentativa em andamento
        try:
            self._executar()
        except Exception:  # noqa: BLE001
            self._falha("Erro inesperado ao abrir o painel.", traceback.format_exc(limit=4))
        finally:
            self._executando.release()

    def _executar(self):
        if ERRO_IMPORT:
            self._falha("Arquivos do aplicativo incompletos ou corrompidos.", ERRO_IMPORT)
            return

        self._estado("carregando", "Abrindo o painel…", passo=0)
        if self.servidor is None:
            try:
                self.servidor = iniciar_servidor_em_thread()
                log.info("Servidor interno iniciado na porta %s", PORTA_SERVIDOR)
            except OSError as erro:
                log.warning("Porta %s indisponivel: %s", PORTA_SERVIDOR, erro)
                if servidor_responde():
                    self._estado(
                        "duplicado",
                        "O Painel já está aberto em outra janela.",
                        "Feche a outra janela e clique em “Tentar novamente” — ou use esta mesmo assim.",
                    )
                else:
                    self._falha(
                        f"A porta {PORTA_SERVIDOR} está ocupada por outro programa.",
                        f"{erro}\n\nFeche outros programas do Painel (por exemplo o "
                        "controle_leitura_server.py) ou reinicie o computador.",
                    )
                return

        self._estado("carregando", "Abrindo o painel…", passo=0)
        limite = time.time() + TEMPO_MAX_SERVIDOR_S
        while not servidor_responde():
            if time.time() > limite:
                self._falha(
                    "O servidor interno não respondeu.",
                    f"Sem resposta em {URL_PAINEL}status após {TEMPO_MAX_SERVIDOR_S} s. "
                    "Um antivírus ou firewall pode estar bloqueando o acesso local (localhost).",
                )
                return
            time.sleep(0.25)

        self._estado("carregando", "Abrindo o painel…", passo=1)  # o painel continua daqui
        log.info("Servidor respondendo - carregando o painel")
        self.janela.load_url(URL_PAINEL)

    def encerrar(self):
        try:
            parar()
        finally:
            if self.servidor is not None:
                self.servidor.shutdown()
                self.servidor.server_close()  # libera a porta na hora
                self.servidor = None


class Api:
    """Funcoes chamadas pelos botoes da tela inicial (window.pywebview.api).
    Atributos com "_" na frente nao sao expostos ao JavaScript."""

    def __init__(self, inicializacao):
        self._ini = inicializacao

    def tentar_novamente(self):
        threading.Thread(target=self._ini.executar, daemon=True).start()

    def abrir_assim_mesmo(self):
        log.info("Usuario abriu o painel usando o servidor de outra janela")
        self._ini.janela.load_url(URL_PAINEL)

    def abrir_log(self):
        try:
            os.startfile(ARQUIVO_LOG)  # noqa: S606 - abre no Bloco de Notas
        except OSError:
            os.startfile(os.path.dirname(ARQUIVO_LOG))  # noqa: S606


def main():
    log.info("Abrindo o aplicativo")
    inicializacao = Inicializacao()

    janela = webview.create_window(
        TITULO_JANELA,
        html=html_tela_inicial(),
        js_api=Api(inicializacao),
        width=1440,
        height=900,
        min_size=(1100, 700),
        maximized=True,  # sempre abre preenchendo a tela (mantem a barra de titulo)
        text_select=True,
        background_color=COR_FUNDO,  # fundo da janela antes do HTML: sem "flash" branco
    )
    inicializacao.janela = janela
    janela.events.shown += _fechar_imagem_abertura
    janela.events.closed += lambda: parar()

    try:
        # private_mode=False + storage_path: sem isso o pywebview abre em
        # modo privado por padrao e tudo salvo no localStorage do painel
        # (nomes de maquina, meta, etc.) some ao fechar o aplicativo.
        webview.start(inicializacao.executar, private_mode=False, storage_path=dir_perfil_webview())
    except Exception:  # noqa: BLE001
        log.exception("Falha ao abrir a janela (WebView2)")
        raise
    finally:
        _fechar_imagem_abertura()
        inicializacao.encerrar()
        log.info("Aplicativo fechado")


if __name__ == "__main__":
    main()
