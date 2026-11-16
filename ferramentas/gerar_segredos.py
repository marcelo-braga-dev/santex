"""
Gera firmware/controle_producao_horimetro/segredos.h a partir do .env da
raiz do projeto - o .env e o lugar unico das senhas (fora do git).

O firmware do ESP32 e compilado pelo Arduino IDE e nao le o .env sozinho:
rode este script sempre que mudar uma senha no .env e grave o firmware
de novo.

Uso (na raiz do projeto):
    python ferramentas/gerar_segredos.py
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_ENV = os.path.join(RAIZ, ".env")
ARQ_SAIDA = os.path.join(RAIZ, "firmware", "controle_producao_horimetro", "segredos.h")

# chave do .env -> comentario no segredos.h
CHAVES = {
    "EMPRESA_SSID_PADRAO": "Rede da empresa (o ESP32 entra nela como mais um aparelho)",
    "EMPRESA_SENHA_PADRAO": "Senha da rede da empresa",
    "AP_SSID": "Rede propria criada pelo ESP32",
    "AP_SENHA": "Senha da rede propria e da pagina de configuracao (minimo 8 caracteres)",
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
    for chave, comentario in CHAVES.items():
        linhas += [f"// {comentario}", f"const char *{chave} = {literal_c(valores[chave])};", ""]
    with open(ARQ_SAIDA, "w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write("\n".join(linhas))
    print(f"OK: {os.path.relpath(ARQ_SAIDA, RAIZ)} atualizado a partir do .env - grave o firmware de novo.")


if __name__ == "__main__":
    main()
