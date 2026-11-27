"""
Gera o PainelProducaoSantex-<versao>.exe - o aplicativo do COMPUTADOR DA FABRICA
(le o ESP32, guarda o banco, sincroniza com a VPS). Um unico arquivo, sem
precisar de Python nem bibliotecas na maquina de destino (PyInstaller).
Leva a chave da fabrica: NUNCA distribua este .exe para fora da empresa -
fora usa-se o PainelSantexRemoto.exe (gerar/exe_remoto.py).

Uso (ou gerar/gerar.bat):
    pip install -r app/requirements.txt
    python gerar/exe_fabrica.py

Gera distribuir/PainelProducaoSantex-<versao>.exe (ex.: -1.7.2). Teste SEMPRE rodando esse .exe
numa pasta fora do projeto (ou em outra maquina) antes de distribuir - pra
garantir que nenhum caminho relativo escapou do empacotamento.

Requisito do lado de quem for USAR o .exe (nao de quem gera): o Microsoft
Edge WebView2 Runtime, que ja vem instalado por padrao no Windows 10/11
atualizados. Se faltar, o Windows oferece a instalacao automaticamente na
primeira vez que um app baseado nele e aberto.
"""

import json
import os
import re

import PyInstaller.__main__

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_BASE = os.path.join(RAIZ_PROJETO, "app")

# 1.7.2: a versao vai no nome do arquivo (PainelProducaoSantex-1.7.2.exe) -
# lida do APP_VERSAO de app/servidor.py, a mesma que o painel mostra.
with open(os.path.join(DIR_BASE, "servidor.py"), "r", encoding="utf-8") as _arq:
    _achou = re.search(r'^APP_VERSAO = "([0-9][0-9A-Za-z.\-]*)"', _arq.read(), re.M)  # 2.0: aceita "-alfa.1"
if not _achou:
    raise SystemExit("ERRO: APP_VERSAO nao encontrado em app/servidor.py")
VERSAO = _achou.group(1)
NOME_EXE = f"PainelProducaoSantex-{VERSAO}"

PAINEL_SRC = os.path.join(RAIZ_PROJETO, "painel")
MONITOR_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "monitor_serial.py")
MONITOR_WIFI_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "monitor_wifi.py")
BANCO_DADOS_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "banco_dados.py")
BACKUP_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "backup_banco.py")
NUVEM_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "nuvem.py")
SETORES_SRC = os.path.join(RAIZ_PROJETO, "ferramentas", "setores.py")  # 2.0: cadastro de setores
# Chave das acoes no ESP32 (gerada por ferramentas/gerar_segredos.py a partir
# do .env) - o firmware gravado precisa ter a mesma.
SEGREDOS_APP = os.path.join(DIR_BASE, "segredos_app.json")
# Raiz do projeto gravada no .exe: os backups automaticos vao para
# <raiz>/backup (caminhos.dir_backup) - a pasta em si nunca entra no .exe.
BUILD_INFO = os.path.join(DIR_BASE, "build_info.json")
with open(BUILD_INFO, "w", encoding="utf-8") as _arq:
    json.dump({"raiz_projeto": RAIZ_PROJETO}, _arq, ensure_ascii=False)
if not os.path.isfile(SEGREDOS_APP):
    raise SystemExit("ERRO: falta app/segredos_app.json - rode antes: python ferramentas/gerar_segredos.py")
ICONE = os.path.join(DIR_BASE, "assets", "icone.ico")
# Imagem mostrada no instante do duplo clique, enquanto o .exe (arquivo
# unico) se descompacta - main.py fecha quando a janela aparece.
SPLASH = os.path.join(DIR_BASE, "assets", "splash.png")

# Pastas de saida (podem ser trocadas por variavel de ambiente, ex. para
# testar um build sem sobrescrever o .exe em uso).
DIST = os.environ.get("BUILD_DIST", os.path.join(RAIZ_PROJETO, "distribuir"))
WORK = os.environ.get("BUILD_WORK", os.path.join(RAIZ_PROJETO, "gerar", "_trabalho", "fabrica"))

# --add-data usa ";" no Windows e ":" no Linux/macOS - os.pathsep ja acerta
# isso automaticamente conforme o SO onde o build estiver rodando.
SEP = os.pathsep

ARGS = [
    os.path.join(DIR_BASE, "main.py"),
    f"--name={NOME_EXE}",
    "--onefile",
    "--windowed",
    f"--icon={ICONE}",
    # so o painel em uso (index.html + assets + js) - copias antigas em
    # painel/_backup/ nao entram no .exe nem ficam acessiveis pela rede
    f"--add-data={os.path.join(PAINEL_SRC, 'index.html')}{SEP}painel",
    f"--add-data={os.path.join(PAINEL_SRC, 'assets')}{SEP}painel/assets",
    f"--add-data={os.path.join(PAINEL_SRC, 'js')}{SEP}painel/js",  # 2.0: modulos novos do painel
    f"--add-data={MONITOR_SRC}{SEP}ferramentas",
    f"--add-data={MONITOR_WIFI_SRC}{SEP}ferramentas",
    f"--add-data={BANCO_DADOS_SRC}{SEP}ferramentas",
    f"--add-data={BACKUP_SRC}{SEP}ferramentas",
    f"--add-data={NUVEM_SRC}{SEP}ferramentas",
    f"--add-data={SETORES_SRC}{SEP}ferramentas",
    f"--add-data={SEGREDOS_APP}{SEP}app",
    f"--add-data={BUILD_INFO}{SEP}app",
    "--hidden-import=serial.tools.list_ports",
    # monitor_serial.py e banco_dados.py entram como --add-data (arquivos de
    # dados, carregados via sys.path em tempo de execucao) - o PyInstaller
    # nunca analisa o "import sqlite3" la dentro, entao sem isso a extensao
    # _sqlite3 nao e empacotada e o .exe quebra com ModuleNotFoundError.
    "--hidden-import=sqlite3",
    # idem para o monitor_wifi.py (urllib/http.client)
    "--hidden-import=urllib.request",
    "--hidden-import=urllib.error",
    "--hidden-import=gzip",
    "--hidden-import=hmac",
    "--hidden-import=secrets",
    # nuvem.py (acesso remoto): login e envio da configuracao para a VPS
    "--hidden-import=base64",
    "--hidden-import=hashlib",
    # setores.py (2.0): nome do setor -> identificador sem acento
    "--hidden-import=unicodedata",
    # anuncio http://painel.local (anuncio_rede.py): o zeroconf tem modulos
    # compilados carregados dinamicamente - inclui todos para nao faltar nada
    "--collect-submodules=zeroconf",
    "--distpath=" + DIST,
    "--workpath=" + WORK,
    "--specpath=" + WORK,
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

print(f"\nPronto: {os.path.join(DIST, NOME_EXE + '.exe')}")
