"""
Servidor local do painel SEM a janela do aplicativo - para desenvolvimento
ou para um PC que so precisa servir o painel na rede.

E exatamente o mesmo servidor do aplicativo desktop (app/servidor.py:
mesma API, mesma leitura serial/Wi-Fi em thread, mesmo backup automatico e
mesma regra de "somente leitura" para outros PCs) - nao ha mais uma copia
separada do codigo aqui. Os dados ficam em dados/painel.db do projeto.

Uso:
    python controle_leitura_server.py

Nao rode junto com o aplicativo desktop: os dois usam a porta 80.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import servidor  # noqa: E402 (app/servidor.py)


def main():
    try:
        srv = servidor.iniciar_servidor_em_thread()
    except OSError as erro:
        print(f"Nao foi possivel abrir a porta {servidor.PORTA_SERVIDOR}: {erro}")
        print("O aplicativo do painel (ou outro servidor) ja esta aberto neste computador?")
        return 1  # falha: o systemd registra o erro (antes saia com 0)
    print(f"Painel em http://localhost (versao {servidor.APP_VERSAO})")
    print(f"Banco de dados: {servidor.banco.caminho}")
    print("Deixe esta janela aberta. Ctrl+C para encerrar.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.parar()
        srv.shutdown()
        srv.server_close()
        print("\nEncerrado.")


if __name__ == "__main__":
    sys.exit(main())
