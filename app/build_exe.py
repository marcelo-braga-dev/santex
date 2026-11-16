"""
Gera o instalavel standalone (.exe) do Painel de Producao - um unico
arquivo, sem precisar de Python nem bibliotecas instaladas na maquina de
destino (tudo embutido pelo PyInstaller).

Uso:
    cd app
    pip install -r requirements.txt
    python build_exe.py

Gera app/dist/PainelProducaoSantex.exe. Teste SEMPRE rodando esse .exe
numa pasta fora do projeto (ou em outra maquina) antes de distribuir - pra
garantir que nenhum caminho relativo escapou do empacotamento.

Requisito do lado de quem for USAR o .exe (nao de quem gera): o Microsoft
Edge WebView2 Runtime, que ja vem instalado por padrao no Windows 10/11
atualizados. Se faltar, o Windows oferece a instalacao automaticamente na
primeira vez que um app baseado nele e aberto.
"""

import os

import PyInstaller.__main__

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ_PROJETO = os.path.dirname(DIR_BASE)

PAINEL_SRC = os.path.join(RAIZ_PROJETO, "painel")
MONITOR_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "monitor_serial.py")
MONITOR_WIFI_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "monitor_wifi.py")
BANCO_DADOS_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "banco_dados.py")
ICONE = os.path.join(DIR_BASE, "assets", "icone.ico")
# Imagem mostrada no instante do duplo clique, enquanto o .exe (arquivo
# unico) se descompacta - main.py fecha quando a janela aparece.
SPLASH = os.path.join(DIR_BASE, "assets", "splash.png")

# Pastas de saida (podem ser trocadas por variavel de ambiente, ex. para
# testar um build sem sobrescrever o .exe em uso).
DIST = os.environ.get("BUILD_DIST", os.path.join(DIR_BASE, "dist"))
WORK = os.environ.get("BUILD_WORK", os.path.join(DIR_BASE, "build"))

# --add-data usa ";" no Windows e ":" no Linux/macOS - os.pathsep ja acerta
# isso automaticamente conforme o SO onde o build estiver rodando.
SEP = os.pathsep

ARGS = [
    os.path.join(DIR_BASE, "main.py"),
    "--name=PainelProducaoSantex",
    "--onefile",
    "--windowed",
    f"--icon={ICONE}",
    f"--add-data={PAINEL_SRC}{SEP}painel",
    f"--add-data={MONITOR_SRC}{SEP}ferramentas",
    f"--add-data={MONITOR_WIFI_SRC}{SEP}ferramentas",
    f"--add-data={BANCO_DADOS_SRC}{SEP}ferramentas",
    "--hidden-import=serial.tools.list_ports",
    # monitor_serial.py e banco_dados.py entram como --add-data (arquivos de
    # dados, carregados via sys.path em tempo de execucao) - o PyInstaller
    # nunca analisa o "import sqlite3" la dentro, entao sem isso a extensao
    # _sqlite3 nao e empacotada e o .exe quebra com ModuleNotFoundError.
    "--hidden-import=sqlite3",
    # idem para o monitor_wifi.py (urllib/http.client)
    "--hidden-import=urllib.request",
    # anuncio http://painel.local (anuncio_rede.py): o zeroconf tem modulos
    # compilados carregados dinamicamente - inclui todos para nao faltar nada
    "--collect-submodules=zeroconf",
    "--distpath=" + DIST,
    "--workpath=" + WORK,
    "--specpath=" + DIR_BASE,
    "--noconfirm",
]

# A imagem de abertura (--splash) precisa do Tcl/Tk no Python que gera o
# .exe. Se o PyInstaller recusar (Tk ausente/incompativel), gera sem ela -
# o app continua mostrando a propria tela "Carregando..." assim que a
# janela abre (tela_inicial.py).
try:
    PyInstaller.__main__.run(ARGS + [f"--splash={SPLASH}"])
    print("\n(com imagem de abertura)")
except BaseException as erro:  # noqa: BLE001 - o PyInstaller pode chamar sys.exit
    print(f"\nAviso: imagem de abertura indisponivel ({erro!r}) - gerando sem ela.")
    PyInstaller.__main__.run(ARGS)

print(f"\nPronto: {os.path.join(DIST, 'PainelProducaoSantex.exe')}")
