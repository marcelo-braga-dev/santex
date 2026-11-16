"""
Resolucao de caminhos compartilhada entre main.py e servidor.py - a mesma
logica precisa funcionar tanto rodando direto do codigo-fonte (python
app/main.py) quanto de dentro do .exe gerado pelo PyInstaller, onde os
arquivos empacotados ficam numa pasta temporaria (sys._MEIPASS) e o disco
onde o aplicativo foi instalado pode nao ser gravavel sem admin.
"""

import os
import sys


def rodando_empacotado():
    """True quando este codigo esta rodando dentro do .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def dir_base_bundle():
    """Pasta onde estao painel/ e ferramentas/ - a pasta temporaria do
    PyInstaller quando empacotado, ou a raiz do projeto em desenvolvimento."""
    if rodando_empacotado():
        return sys._MEIPASS  # criado pelo PyInstaller, apagado ao fechar o app
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dir_usuario_app():
    """Pasta raiz gravavel do usuario para este app - nunca dentro de
    'Arquivos de Programas' (so gravavel com privilegio de administrador)."""
    if rodando_empacotado():
        return os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "PainelProducaoSantex",
        )
    return dir_base_bundle()


def dir_dados_usuario():
    """Onde o banco de dados (painel.db) e lido/gravado - sempre uma pasta
    do usuario, nunca apagada entre execucoes."""
    caminho = os.path.join(_dir_usuario_app(), "dados")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def dir_perfil_webview():
    """Pasta onde o WebView2 guarda seu perfil (cookies, localStorage,
    cache) entre execucoes. Sem isso, main.py abriria a janela em modo
    privado (padrao do pywebview) e qualquer coisa salva no localStorage
    do painel - por exemplo os nomes de maquina - desapareceria toda vez
    que o aplicativo fosse fechado e reaberto."""
    caminho = os.path.join(_dir_usuario_app(), "perfil_webview")
    os.makedirs(caminho, exist_ok=True)
    return caminho
