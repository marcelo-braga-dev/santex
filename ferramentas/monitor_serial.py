"""
Le a saida Serial do Arduino/ESP32 em tempo real e grava cada ciclo real no
banco de dados (ferramentas/banco_dados.py - SQLite, dados/painel.db),
simulando (no PC) o que o cartao SD ou a flash vao gravar.

Uso:
    python monitor_serial.py [PORTA]

Se a porta nao for informada, tenta detectar automaticamente a placa
conectada via USB (Arduino, ESP32 com CP210x/CH340, etc). Requer:
pip install pyserial

A funcao monitorar() tambem e importada diretamente pelo aplicativo
desktop (app/servidor.py), rodando numa thread em vez de um processo
separado - por isso o loop de leitura aceita um parar_evento e uma funcao
de log em vez de usar print()/while True fixo.
"""

import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta

import serial
import serial.tools.list_ports

from banco_dados import BancoDados, NOME_ARQUIVO

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_DADOS_PADRAO = os.path.join(DIR_BASE, "..", "dados")
BAUDRATE = 9600

# Unico setor com hardware/ferramentas montados ate agora (ver
# docs/painel.md, secao "Multiplos setores", para o que falta pra um setor
# novo ter leitura real propria).
SETOR_PADRAO = "enfestadeiras"


def encontrar_porta():
    portas = list(serial.tools.list_ports.comports())
    palavras_chave = ("arduino", "ch340", "usb-serial", "cp210", "silicon labs", "esp32")
    for p in portas:
        desc = (p.description or "").lower()
        if any(k in desc for k in palavras_chave):
            return p.device
    return portas[0].device if portas else None


def eh_linha_de_dados(linha):
    # Formato atual: maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs (6 campos).
    # "maquina" e "ciclo" sao sempre numericos numa linha de dado real.
    partes = linha.split(",")
    return len(partes) == 6 and partes[0].strip().isdigit() and partes[1].strip().isdigit()


# Estado ao vivo: "# ESTADO,<maquina>,<1|0>,<segundos no estado>" (a cada 10s)
# e "# [M<n>] LIGOU" / "# [M<n>] DESLIGOU" (na hora da transicao).
_RE_ESTADO = re.compile(r"^# ESTADO,(\d+),([01]),(\d+)$")
_RE_TRANSICAO = re.compile(r"^# \[M(\d+)\] (?:\[SIM\] )?(LIGOU|DESLIGOU)$")


def interpretar_estado(linha, agora=None):
    """Devolve (maquina, ligado, desde) para uma linha de estado/transicao do
    firmware, ou None se a linha nao for desse tipo. "desde" e a data/hora
    (do PC) em que a maquina entrou no estado atual."""
    agora = agora or datetime.now()
    m = _RE_ESTADO.match(linha)
    if m:
        return int(m.group(1)), m.group(2) == "1", agora - timedelta(seconds=int(m.group(3)))
    m = _RE_TRANSICAO.match(linha)
    if m:
        return int(m.group(1)), m.group(2) == "LIGOU", agora
    return None


def abrir_porta(porta):
    """Abre a Serial SEM acionar DTR/RTS. Na ESP32 DevKit esses dois sinais
    comandam o circuito de auto-reset (EN/BOOT): com o padrao do pyserial
    (ambos ligados), fechar a porta - ao pausar a leitura, reiniciar o
    servidor ou o PC - derrubava os dois sinais fora de sincronia e
    reiniciava a placa, cortando o ciclo em andamento. Mantidos desligados
    o tempo todo, abrir e fechar a porta nao reinicia mais o ESP32."""
    ser = serial.Serial()
    ser.port = porta
    ser.baudrate = BAUDRATE
    ser.timeout = 1
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def _log_seguro(log, msg):
    """Chama log(msg) sem nunca deixar um erro de LOG derrubar a leitura.
    Em alguns consoles do Windows (codepage cp1252), um byte de lixo vindo
    do boot da placa (decodificado com errors="replace" vira "\\ufffd") faz
    o print() padrao estourar UnicodeEncodeError - sem essa protecao, a
    thread/processo de leitura morria no meio e ninguem percebia (o
    subprocess e iniciado com stderr descartado)."""
    try:
        log(msg)
    except UnicodeEncodeError:
        try:
            log(msg.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass
    except Exception:
        pass


ESPERA_RECONEXAO_S = 5


def monitorar(porta, banco=None, setor=SETOR_PADRAO, parar_evento=None, log=print):
    """Conecta na porta serial e grava cada ciclo real no banco de dados
    (nunca apaga nada do que ja foi gravado - so insere linhas novas) ate
    parar_evento ser sinalizado (ou para sempre - Ctrl+C/KeyboardInterrupt -
    se parar_evento for None, que e o uso via linha de comando).

    Cabo desconectado, placa reiniciando ou porta sumindo NAO encerram a
    leitura: espera ESPERA_RECONEXAO_S e tenta de novo (na mesma porta ou,
    se ela sumiu, na que for detectada) - antes, a thread morria em silencio
    e o painel so voltava a receber dados reabrindo o app."""
    if parar_evento is None:
        parar_evento = threading.Event()
    if banco is None:
        banco = BancoDados(os.path.join(DIR_DADOS_PADRAO, NOME_ARQUIVO))

    avisado = False
    while not parar_evento.is_set():
        try:
            _ler_porta(porta, banco, setor, parar_evento, log)
            avisado = False
        except (serial.SerialException, OSError) as erro:
            if not avisado:
                _log_seguro(log, f"[aviso] porta {porta} indisponivel ({erro}) - tentando de novo a cada {ESPERA_RECONEXAO_S}s.")
                avisado = True
        except Exception as erro:  # noqa: BLE001 - banco travado etc.: nunca morre
            _log_seguro(log, f"[erro] {type(erro).__name__}: {erro} - tentando de novo em {ESPERA_RECONEXAO_S}s.")
        if parar_evento.wait(ESPERA_RECONEXAO_S):
            break
        portas = [p.device for p in serial.tools.list_ports.comports()]
        if porta not in portas:
            porta = encontrar_porta() or porta


def _ler_porta(porta, banco, setor, parar_evento, log):
    _log_seguro(log, f"Conectando em {porta} @ {BAUDRATE} bps...")
    with abrir_porta(porta) as ser:
        time.sleep(0.5)

        _log_seguro(log, f"Gravando ciclos reais em {banco.caminho} (setor: {setor}). Ctrl+C para parar.")
        while not parar_evento.is_set():
            bruta = ser.readline().decode("utf-8", errors="replace").strip()
            if not bruta:
                continue  # readline() so retorna vazio apos o timeout de 1s - reavalia parar_evento

            _log_seguro(log, bruta)

            estado = interpretar_estado(bruta)
            if estado:
                maquina, ligado, desde = estado
                banco.atualizar_estado_ao_vivo(setor, maquina, ligado, desde.isoformat(timespec="seconds"))
                continue

            if eh_linha_de_dados(bruta):
                maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs = bruta.split(",")
                try:
                    banco.gravar_ciclo(
                        setor, int(maquina), int(ciclo), inicio_ms, fim_ms, float(duracao_s), obs
                    )
                except (ValueError, TypeError):
                    # duracao_s inesperada (nao numerica) - loga e segue, sem
                    # derrubar a leitura por causa de uma linha so
                    _log_seguro(log, f"[aviso] linha ignorada (duracao_s invalida): {bruta}")


def main():
    porta = sys.argv[1] if len(sys.argv) > 1 else encontrar_porta()
    if not porta:
        print("Nenhuma porta serial encontrada. Informe manualmente: python monitor_serial.py COM3")
        return
    monitorar(porta)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuario.")
