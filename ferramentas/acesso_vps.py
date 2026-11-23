"""
Consulta o painel da VPS com a senha de acesso remoto guardada no notebook
(1.7.2) - feito para o Claude Code (e para conferencias rapidas) conseguir
ver o que a VPS mostra sem que ninguem digite ou exponha a senha.

    python ferramentas/acesso_vps.py /status
    python ferramentas/acesso_vps.py "/dados?setor=enfestadeiras" --saida C:/caminho/dados.csv
    python ferramentas/acesso_vps.py /config --edicao      # entra com a senha de edicao

So faz GET (nunca altera nada na VPS). A senha e lida do banco do notebook
(aberto SO para leitura: ?mode=ro), usada so no corpo do POST /login e
NUNCA impressa. Senha nao guardada (definida antes da 1.7.2 ou trocada pela
internet): guarde-a no painel do notebook, Configuracoes -> Acesso remoto ->
"Senhas guardadas neste computador".
"""

import argparse
import http.cookiejar
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO_PADRAO = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PainelProducaoSantex", "dados", "painel.db")
SEGREDO_SENHAS_TEXTO = "senhas_remotas_texto"
SEGREDO_PAPEL = {"leitura": "acesso_remoto", "edicao": "acesso_edicao"}


def _segredo(con, chave):
    linha = con.execute("SELECT valor FROM segredos WHERE chave = ?", (chave,)).fetchone()
    try:
        return json.loads(linha[0]) if linha else {}
    except ValueError:
        return {}


def ler_senha(caminho_banco, papel):
    """Texto da senha guardada que ainda vale (o hash em vigor confere)."""
    uri = "file:" + urllib.parse.quote(os.path.abspath(caminho_banco).replace("\\", "/")) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        guardada = _segredo(con, SEGREDO_SENHAS_TEXTO).get(papel) or {}
        vigente = _segredo(con, SEGREDO_PAPEL[papel])
    finally:
        con.close()
    if not vigente.get("hash"):
        sys.exit(f"Nenhuma senha de {papel} definida.")
    if not guardada.get("senha") or guardada.get("hash") != vigente["hash"]:
        sys.exit(f"A senha de {papel} em vigor nao esta guardada neste computador: guarde-a no painel "
                 "(Configuracoes -> Acesso remoto -> Senhas guardadas neste computador).")
    return guardada["senha"]


def url_vps():
    for caminho, campo in ((os.path.join(os.path.dirname(BANCO_PADRAO), "nuvem.json"), "url"),
                           (os.path.join(RAIZ, "app", "segredos_app.json"), "nuvem_url")):
        try:
            with open(caminho, "r", encoding="utf-8") as arquivo:
                url = str(json.load(arquivo).get(campo) or "").strip().rstrip("/")
            if url:
                return url
        except (OSError, ValueError, AttributeError):
            continue
    sys.exit("Endereco da VPS nao encontrado (nuvem.json / app/segredos_app.json).")


def main():
    p = argparse.ArgumentParser(description="GET no painel da VPS com a senha guardada no notebook.")
    p.add_argument("caminho", help='ex.: /status, /config, "/dados?setor=enfestadeiras"')
    p.add_argument("--edicao", action="store_true", help="entra com a senha de edicao (padrao: visualizacao)")
    p.add_argument("--banco", default=BANCO_PADRAO, help="banco do notebook (aberto so para leitura)")
    p.add_argument("--url", help="endereco da VPS (padrao: o configurado no app)")
    p.add_argument("--saida", help="grava a resposta neste arquivo em vez de imprimir")
    args = p.parse_args()

    base = (args.url or url_vps()).rstrip("/")
    senha = ler_senha(args.banco, "edicao" if args.edicao else "leitura")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "painel-santex-ferramenta"), ("X-Painel-Edicao", "1")]
    try:
        opener.open(urllib.request.Request(base + "/login", data=urllib.parse.urlencode({"senha": senha}).encode(),
                                           method="POST"), timeout=20).close()
    except urllib.error.HTTPError as erro:
        sys.exit(f"Login recusado pela VPS (HTTP {erro.code}).")
    finally:
        senha = None
    if not any(c.name for c in jar):
        sys.exit("A VPS nao abriu a sessao (senha recusada?).")
    caminho = args.caminho if args.caminho.startswith("/") else "/" + args.caminho
    try:
        with opener.open(base + caminho, timeout=30) as resp:
            corpo = resp.read()
    except urllib.error.HTTPError as erro:
        sys.exit(f"GET {caminho}: HTTP {erro.code}")
    if args.saida:
        with open(args.saida, "wb") as arquivo:
            arquivo.write(corpo)
        print(f"{len(corpo)} bytes gravados em {args.saida}")
    else:
        sys.stdout.buffer.write(corpo)
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
