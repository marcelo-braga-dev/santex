"""
Gera firmware/controle_producao_horimetro/segredos.h a partir do .env da
raiz do projeto - o .env e o lugar unico das senhas (fora do git).

O firmware do ESP32 e compilado pelo Arduino IDE e nao le o .env sozinho:
rode este script sempre que mudar uma senha no .env e grave o firmware
de novo.

Tambem gera app/segredos_app.json (fora do git, embutido no .exe) com a
API_CHAVE - a mesma chave que o firmware exige nas acoes que alteram o
ESP32 (/limpar, /hora, /acao). Sem API_CHAVE no .env, uma chave aleatoria
e criada e acrescentada ao .env automaticamente.

Depois de rodar: grave o firmware E gere o .exe de novo (os dois precisam
da mesma chave).

Uso (na raiz do projeto):
    python ferramentas/gerar_segredos.py
"""

import json
import os
import secrets
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_ENV = os.path.join(RAIZ, ".env")
ARQ_SAIDA = os.path.join(RAIZ, "firmware", "controle_producao_horimetro", "segredos.h")
ARQ_SAIDA_APP = os.path.join(RAIZ, "app", "segredos_app.json")

# chave do .env -> comentario no segredos.h
CHAVES = {
    "EMPRESA_SSID_PADRAO": "Rede da empresa (o ESP32 entra nela como mais um aparelho)",
    "EMPRESA_SENHA_PADRAO": "Senha da rede da empresa",
    "AP_SSID": "Rede propria criada pelo ESP32",
    "AP_SENHA": "Senha da rede propria e da pagina de configuracao (minimo 8 caracteres)",
    "API_CHAVE": "Chave exigida pelo ESP32 em /limpar, /hora e /acao (o app envia no cabecalho X-Chave)",
}

# Acesso remoto (firmware 3.0 / app 1.1.0) - opcionais: NUVEM_URL vazia =
# ESP32 e notebook nao enviam nada para a VPS.
CHAVES_NUVEM = {
    "NUVEM_URL": "Endereco da VPS (acesso de fora da rede), ex. https://santex.rexar.com.br - vazio = desligado",
    "NUVEM_CHAVE": "Chave que o ESP32 e o notebook enviam para a VPS (cabecalho X-Chave-Nuvem)",
}


def ler_env(caminho):
    valores = {}
    with open(caminho, encoding="utf-8") as arquivo:
        for n, linha in enumerate(arquivo, 1):
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            if "=" not in linha:
                sys.exit(f"ERRO: .env linha {n} sem '=': {linha}")
            chave, valor = linha.split("=", 1)
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]  # aceita VALOR="com aspas"
            valores[chave.strip()] = valor
    return valores


def literal_c(texto):
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    if not os.path.isfile(ARQ_ENV):
        sys.exit("ERRO: .env nao encontrado na raiz do projeto - copie .env.exemplo para .env e preencha.")
    valores = ler_env(ARQ_ENV)
    if not valores.get("API_CHAVE"):
        valores["API_CHAVE"] = secrets.token_hex(12)
        with open(ARQ_ENV, "a", encoding="utf-8") as arquivo:
            arquivo.write("\n# Chave das acoes que alteram o ESP32 (limpar, acertar hora, reiniciar).\n"
                          "# Gerada automaticamente - o firmware e o .exe precisam da mesma.\n"
                          f"API_CHAVE={valores['API_CHAVE']}\n")
        print("API_CHAVE criada e acrescentada ao .env.")
    if not valores.get("NUVEM_CHAVE"):
        valores["NUVEM_CHAVE"] = secrets.token_hex(24)
        with open(ARQ_ENV, "a", encoding="utf-8") as arquivo:
            arquivo.write("\n# Chave do acesso remoto: ESP32 e notebook -> VPS. Gerada automaticamente;\n"
                          "# a VPS precisa da mesma (NUVEM_CHAVE em /etc/painel-nuvem.env).\n"
                          f"NUVEM_CHAVE={valores['NUVEM_CHAVE']}\n")
        print("NUVEM_CHAVE criada e acrescentada ao .env.")
    url = valores.get("NUVEM_URL", "").strip().rstrip("/")
    if url and not url.startswith("https://"):
        sys.exit("ERRO: NUVEM_URL precisa comecar com https:// (o ESP32 so envia por HTTPS).")
    valores["NUVEM_URL"] = url
    faltando = [c for c in CHAVES if not valores.get(c)]
    if faltando:
        sys.exit("ERRO: faltam no .env: " + ", ".join(faltando))
    if len(valores["AP_SENHA"]) < 8:
        sys.exit("ERRO: AP_SENHA precisa ter pelo menos 8 caracteres (exigencia do Wi-Fi do ESP32).")

    linhas = [
        "// GERADO por ferramentas/gerar_segredos.py a partir do .env - NAO EDITE",
        "// (altere o .env e rode o script de novo). Fora do git (.gitignore).",
        "",
    ]
    for chave, comentario in {**CHAVES, **CHAVES_NUVEM}.items():
        linhas += [f"// {comentario}", f"const char *{chave} = {literal_c(valores[chave])};", ""]
    with open(ARQ_SAIDA, "w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write("\n".join(linhas))
    with open(ARQ_SAIDA_APP, "w", encoding="utf-8") as arquivo:
        json.dump({"api_chave": valores["API_CHAVE"], "nuvem_url": valores["NUVEM_URL"],
                   "nuvem_chave": valores["NUVEM_CHAVE"]}, arquivo)
    print(f"OK: {os.path.relpath(ARQ_SAIDA, RAIZ)} e {os.path.relpath(ARQ_SAIDA_APP, RAIZ)} atualizados a partir do .env.")
    print("Grave o firmware E gere o .exe de novo (gerar/gerar.bat) - os dois usam as mesmas chaves.")
    print(f"Acesso remoto: {'ligado -> ' + valores['NUVEM_URL'] if valores['NUVEM_URL'] else 'desligado (NUVEM_URL vazia)'}")


if __name__ == "__main__":
    main()
