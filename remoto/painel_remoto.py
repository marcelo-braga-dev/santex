"""
Painel Santex Remoto - o programa para os computadores FORA da empresa.

E so uma janela (WebView2) que abre o painel da VPS (ex.:
https://santex.rexar.com.br) - sem servidor, sem banco, sem chave e sem
segredo nenhum embutido. Quem usa entra com a senha de visualizacao ou de
edicao (definidas no computador da fabrica, menu Configuracoes -> Acesso
remoto); a sessao dura 30 dias, porque o perfil da janela fica guardado em
%APPDATA%\\PainelSantexRemoto.

Endereco: o gerador (gerar/exe_remoto.py) grava o NUVEM_URL do .env dentro
do .exe. Para testar contra outro servidor: variavel PAINEL_REMOTO_URL.

Uso em desenvolvimento:
    pip install pywebview
    python remoto/painel_remoto.py
"""

import json
import os
import sys
import threading
import urllib.request

import webview  # pywebview

TITULO = "Painel de Produção — Acesso remoto"
URL_PADRAO = "https://santex.rexar.com.br"
COR_FUNDO = "#F4F1EC"


def _dir_base():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def endereco():
    url = os.environ.get("PAINEL_REMOTO_URL", "").strip()
    if not url:
        try:
            with open(os.path.join(_dir_base(), "endereco.json"), encoding="utf-8") as arquivo:
                url = str(json.load(arquivo).get("url", "")).strip()
        except (OSError, ValueError):
            url = ""
    return (url or URL_PADRAO).rstrip("/") + "/"


def dir_perfil():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    caminho = os.path.join(base, "PainelSantexRemoto", "perfil")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def _tela(titulo, texto, botao=False, carregando=False):
    detalhe = f'<button onclick="window.pywebview.api.tentar()">Tentar de novo</button>' if botao else ""
    girando = '<div class="giro"></div>' if carregando else ""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:{COR_FUNDO};
font-family:"Segoe UI",system-ui,sans-serif;color:#2B2622}}
.caixa{{text-align:center;max-width:460px;padding:32px}}
h1{{font-size:20px;margin:0 0 10px}} p{{font-size:14px;line-height:1.5;color:#5E554D;margin:0 0 18px}}
button{{background:#C2410C;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-size:14px;cursor:pointer}}
.giro{{width:34px;height:34px;margin:0 auto 18px;border:3px solid #E4DCD2;border-top-color:#C2410C;border-radius:50%;
animation:g 0.9s linear infinite}} @keyframes g{{to{{transform:rotate(360deg)}}}}
</style></head><body><div class="caixa">{girando}<h1>{titulo}</h1><p>{texto}</p>{detalhe}</div></body></html>"""


class Abertura:
    def __init__(self, url):
        self.url, self.janela = url, None
        self._trava = threading.Lock()

    def _servidor_responde(self):
        try:
            with urllib.request.urlopen(self.url + "assets/logo.png", timeout=10) as resposta:
                return resposta.status == 200
        except Exception:  # noqa: BLE001 - sem internet, DNS, certificado...
            return False

    def abrir(self):
        if not self._trava.acquire(blocking=False):
            return
        try:
            self.janela.load_html(_tela("Conectando…", f"Abrindo {self.url.rstrip('/')}", carregando=True))
            if self._servidor_responde():
                self.janela.load_url(self.url)
            else:
                self.janela.load_html(_tela(
                    "Sem conexão com o painel",
                    "Verifique a internet deste computador. Se a internet estiver funcionando, "
                    "o servidor pode estar em manutenção — tente de novo em alguns minutos.",
                    botao=True))
        finally:
            self._trava.release()


class Api:
    def __init__(self, abertura):
        self._abertura = abertura

    def tentar(self):
        threading.Thread(target=self._abertura.abrir, daemon=True).start()


def main():
    abertura = Abertura(endereco())
    abertura.janela = webview.create_window(
        TITULO, html=_tela("Conectando…", "", carregando=True), js_api=Api(abertura),
        width=1440, height=900, min_size=(1000, 650), maximized=True, text_select=True, background_color=COR_FUNDO,
    )
    # perfil guardado: o login (cookie de 30 dias) e as preferencias sobrevivem ao fechar
    webview.start(abertura.abrir, private_mode=False, storage_path=dir_perfil())


if __name__ == "__main__":
    main()
