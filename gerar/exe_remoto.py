"""
Gera o PainelSantexRemoto.exe - o programa para os computadores FORA da
empresa: so uma janela que abre o painel da VPS (remoto/painel_remoto.py).
Nao leva chave, banco nem segredo: pode ser copiado para quem precisar.
O endereco vem do NUVEM_URL do .env (e publico).

Uso (ou gerar/gerar.bat):
    pip install -r app/requirements.txt
    python gerar/exe_remoto.py

Gera distribuir/PainelSantexRemoto.exe.
"""

import json
import os
import sys

import PyInstaller.__main__

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.environ.get("BUILD_DIST", os.path.join(RAIZ, "distribuir"))
WORK = os.environ.get("BUILD_WORK", os.path.join(RAIZ, "gerar", "_trabalho", "remoto"))
os.makedirs(WORK, exist_ok=True)


def nuvem_url():
    """So o NUVEM_URL do .env - nenhum outro valor e lido."""
    try:
        with open(os.path.join(RAIZ, ".env"), encoding="utf-8") as arquivo:
            for linha in arquivo:
                nome, _, valor = linha.strip().partition("=")
                if nome.strip() == "NUVEM_URL":
                    return valor.strip().strip('"').strip("'").rstrip("/")
    except OSError:
        pass
    return ""


url = nuvem_url()
if not url.startswith("https://"):
    sys.exit("ERRO: NUVEM_URL (https://...) nao esta no .env - e o endereco que o programa remoto abre.")
ENDERECO = os.path.join(WORK, "endereco.json")
with open(ENDERECO, "w", encoding="utf-8") as arquivo:
    json.dump({"url": url}, arquivo)

PyInstaller.__main__.run([
    os.path.join(RAIZ, "remoto", "painel_remoto.py"),
    "--name=PainelSantexRemoto",
    "--onefile",
    "--windowed",
    f"--icon={os.path.join(RAIZ, 'app', 'assets', 'icone.ico')}",
    f"--add-data={ENDERECO}{os.pathsep}.",
    "--distpath=" + DIST,
    "--workpath=" + WORK,
    "--specpath=" + WORK,
    "--noconfirm",
])

# conferencia: nada da fabrica pode ter entrado
toc = open(os.path.join(WORK, "PainelSantexRemoto", "PKG-00.toc"), encoding="utf-8", errors="replace").read()
for proibido in ("segredos_app", "build_info", ".env", "painel.db", "nuvem.py", "servidor.py"):
    if proibido in toc:
        sys.exit(f"ERRO: {proibido} entrou no PainelSantexRemoto.exe - nao distribua.")
print(f"\nPronto: {os.path.join(DIST, 'PainelSantexRemoto.exe')}  (abre {url})")
