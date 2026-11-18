"""
Gera o PainelSantexRemoto.exe - o programa para os computadores FORA da
empresa: so uma janela que abre o painel da VPS (remoto/painel_remoto.py).
Nao leva chave, banco nem segredo: pode ser copiado para quem precisar.
O endereco vem do NUVEM_URL do .env (e publico).

Uso (ou gerar/gerar.bat):
    pip install -r app/requirements.txt
    python gerar/exe_remoto.py

Gera "distribuir/Painel de Produção.exe" (icone: remoto/icone.ico, desenhado
por gerar/icone_remoto.py) e, quando o codigo do programa
mudou, publica a copia em vps/app-remoto/ (versionada no git): o git pull
da VPS leva o arquivo e o painel da VPS oferece o download a quem usa o
navegador num computador com Windows. Sem mudanca no codigo, a copia
publicada fica como esta (o repositorio nao cresce a cada build).
Forcar a publicacao: python gerar/exe_remoto.py --publicar
"""

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime

import PyInstaller.__main__

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.environ.get("BUILD_DIST", os.path.join(RAIZ, "distribuir"))
WORK = os.environ.get("BUILD_WORK", os.path.join(RAIZ, "gerar", "_trabalho", "remoto"))
os.makedirs(WORK, exist_ok=True)
NOME = "Painel de Produção"  # nome do arquivo que o usuario ve
ICONE = os.path.join(RAIZ, "remoto", "icone.ico")
if not os.path.isfile(ICONE):
    sys.exit("ERRO: falta remoto/icone.ico - rode: python gerar/icone_remoto.py")


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
    f"--name={NOME}",
    "--onefile",
    "--windowed",
    f"--icon={ICONE}",
    f"--add-data={ENDERECO}{os.pathsep}.",
    "--distpath=" + DIST,
    "--workpath=" + WORK,
    "--specpath=" + WORK,
    "--noconfirm",
])

# conferencia: nada da fabrica pode ter entrado
toc = open(os.path.join(WORK, NOME, "PKG-00.toc"), encoding="utf-8", errors="replace").read()
for proibido in ("segredos_app", "build_info", ".env", "painel.db", "nuvem.py", "servidor.py"):
    if proibido in toc:
        sys.exit(f"ERRO: {proibido} entrou no {NOME}.exe - nao distribua.")
print(f"\nPronto: {os.path.join(DIST, NOME + '.exe')}  (abre {url})")

# --- publica para a VPS (vps/app-remoto) so se o programa mudou -----------
FONTE = os.path.join(RAIZ, "remoto", "painel_remoto.py")
PUBLICADO = os.path.join(RAIZ, "vps", "app-remoto")
with open(FONTE, "rb") as arquivo:
    fonte = arquivo.read()
with open(ICONE, "rb") as arquivo:
    icone_bytes = arquivo.read()
impressao = hashlib.sha256(fonte + icone_bytes + NOME.encode("utf-8") + url.encode("utf-8")).hexdigest()
versao = re.search(rb'^VERSAO = "([^"]+)"', fonte, re.M).group(1).decode()
meta_caminho = os.path.join(PUBLICADO, "PainelSantexRemoto.json")
try:
    with open(meta_caminho, encoding="utf-8") as arquivo:
        anterior = json.load(arquivo).get("fonte_sha256")
except (OSError, ValueError):
    anterior = None
if anterior == impressao and "--publicar" not in sys.argv:
    print("Copia da VPS (vps/app-remoto) ja e deste codigo - nada a publicar.")
else:
    os.makedirs(PUBLICADO, exist_ok=True)
    exe = os.path.join(DIST, NOME + ".exe")
    # na VPS/git o nome interno e so ASCII; o download chega como "Painel de Producao.exe"
    shutil.copy2(exe, os.path.join(PUBLICADO, "PainelSantexRemoto.exe"))
    shutil.copy2(os.path.join(RAIZ, "remoto", "icone.png"), os.path.join(PUBLICADO, "icone.png"))
    with open(exe, "rb") as arquivo:
        sha_exe = hashlib.sha256(arquivo.read()).hexdigest()
    with open(meta_caminho, "w", encoding="utf-8") as arquivo:
        json.dump({"versao": versao, "nome": NOME + ".exe", "gerado_em": datetime.now().isoformat(timespec="seconds"),
                   "sha256": sha_exe, "fonte_sha256": impressao, "url": url}, arquivo, indent=2)
    print(f"Publicado para a VPS: vps/app-remoto/ (versao {versao}) - faca commit e push; o deploy da VPS instala.")
