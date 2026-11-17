"""
Logins de quem acessa o painel pela VPS (fora da rede da empresa).

Roda NA VPS, com a mesma pasta de dados do servidor:
    sudo -u painel PAINEL_DADOS=/var/lib/painel-nuvem python3 ferramentas/usuarios_nuvem.py adicionar maria
    ... listar | remover maria | senha maria

A senha e pedida sem aparecer na tela e guardada so como hash (PBKDF2), em
<PAINEL_DADOS>/usuarios.json. Vale na hora - nao precisa reiniciar o servidor
(um login ja aberto continua valendo por ate 10 min).
"""

import getpass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nuvem import carregar_usuarios, hash_senha, salvar_usuarios  # noqa: E402

NOME_VALIDO = re.compile(r"^[A-Za-z0-9._-]{2,32}$")


def pasta_dados():
    pasta = os.environ.get("PAINEL_DADOS")
    if not pasta:
        sys.exit("Defina PAINEL_DADOS (a pasta de dados do servidor na VPS), ex.: PAINEL_DADOS=/var/lib/painel-nuvem")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def pedir_senha():
    senha = getpass.getpass("Senha (minimo 8 caracteres): ")
    if len(senha) < 8:
        sys.exit("Senha curta demais.")
    if getpass.getpass("Repita a senha: ") != senha:
        sys.exit("As senhas nao conferem.")
    return senha


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("adicionar", "remover", "senha", "listar"):
        sys.exit(__doc__)
    acao, pasta = sys.argv[1], pasta_dados()
    usuarios = carregar_usuarios(pasta)
    if acao == "listar":
        print("\n".join(sorted(usuarios)) or "(nenhum usuario)")
        return
    if len(sys.argv) < 3 or not NOME_VALIDO.match(sys.argv[2]):
        sys.exit("Informe o usuario: 2 a 32 caracteres, letras, numeros, ponto, _ ou -")
    nome = sys.argv[2]
    if acao == "remover":
        if usuarios.pop(nome, None) is None:
            sys.exit(f"Usuario {nome} nao existe.")
        salvar_usuarios(pasta, usuarios)
        print(f"Usuario {nome} removido.")
        return
    if acao == "adicionar" and nome in usuarios:
        sys.exit(f"Usuario {nome} ja existe - use 'senha {nome}' para trocar a senha.")
    if acao == "senha" and nome not in usuarios:
        sys.exit(f"Usuario {nome} nao existe.")
    usuarios[nome] = hash_senha(pedir_senha())
    salvar_usuarios(pasta, usuarios)
    print(f"Usuario {nome} {'criado' if acao == 'adicionar' else 'com senha nova'}.")


if __name__ == "__main__":
    main()
