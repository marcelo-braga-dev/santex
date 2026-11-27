"""
Teste de volume da 2.0 (etapa 1.4): 1 ano sintetico de 50 maquinas (~1,8
milhao de ciclos) num banco TEMPORARIO, medindo o que o servidor faz com
esse volume. Nunca abre o banco de producao.

    python ferramentas/teste_volume.py                 # 50 maquinas x 365 dias
    python ferramentas/teste_volume.py --maquinas 10 --dias 30

Mede: carga em lote + calculo do resumo_dia, gravacao ciclo a ciclo (com o
resumo mantido junto), consultas do resumo (ano por dia / por maquina),
CSV de 1 dia e da janela de 35 dias do painel, CSV do historico inteiro (o
/dados antigo) e o tamanho do banco.
"""

import argparse
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from banco_dados import BancoDados  # noqa: E402


def medir(rotulo, funcao, *args, **kwargs):
    t = time.perf_counter()
    r = funcao(*args, **kwargs)
    print(f"  {rotulo:<52} {time.perf_counter() - t:8.3f} s")
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--maquinas", type=int, default=50)
    p.add_argument("--dias", type=int, default=365)
    p.add_argument("--ciclos-dia", type=int, default=100, help="ciclos por maquina por dia (padrao 100)")
    p.add_argument("--manter", action="store_true", help="nao apaga a pasta temporaria no fim")
    a = p.parse_args()

    pasta = tempfile.mkdtemp(prefix="painel_volume_")
    caminho = os.path.join(pasta, "painel.db")
    assert caminho.startswith(tempfile.gettempdir()), "o teste so roda em pasta temporaria"
    print(f"Banco temporario: {caminho}")
    b = BancoDados(caminho)
    import setores
    setores.criar(b, {"nome": "Volume", "tipoColeta": "unitario"})
    setor = "volume"

    sorteio = random.Random(2026)
    fim_periodo = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = fim_periodo - timedelta(days=a.dias)
    linhas, origem = [], 0
    for m in range(1, a.maquinas + 1):
        disp = f"ESP{m:02d}000000-{m:08X}"
        for d in range(a.dias):
            t = inicio + timedelta(days=d, hours=6)
            for c in range(a.ciclos_dia):
                dur = sorteio.uniform(60, 420)
                t += timedelta(seconds=dur + sorteio.uniform(20, 120))
                origem += 1
                linhas.append((setor, m, c + 1, "?", "?", round(dur, 1), "", t.strftime("%Y-%m-%d %H:%M:%S"), disp, origem))
    print(f"{len(linhas):,} ciclos sinteticos ({a.maquinas} maquinas x {a.dias} dias x {a.ciclos_dia})".replace(",", "."))

    print("Carga")
    def carregar():
        with b._lock, b._conn:
            b._conn.executemany(
                "INSERT INTO ciclos (setor, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs, gravado_em, dispositivo, origem_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", linhas)
    medir("insercao em lote (sem resumo)", carregar)
    n = medir("calculo do resumo_dia (recalcular_resumo)", b.recalcular_resumo, setor)
    print(f"  -> {n:,} linhas no resumo".replace(",", "."))

    print("Gravacao ciclo a ciclo (como chegam dos coletores)")
    t = fim_periodo + timedelta(hours=7)
    qtd = 2000
    t0 = time.perf_counter()
    for i in range(qtd):
        t += timedelta(seconds=30)
        b.gravar_ciclo_remoto(setor, "ESPNOVO00000-0000ABCD", i + 1, (i % a.maquinas) + 1, i + 1, "?", "?", 25.0, "",
                              t.strftime("%Y-%m-%d %H:%M:%S"))
    dt = time.perf_counter() - t0
    print(f"  {qtd} ciclos, {dt:.2f} s -> {dt / qtd * 1000:.2f} ms por ciclo (com o resumo)")

    print("Consultas")
    de, ate = inicio.strftime("%Y-%m-%d"), fim_periodo.strftime("%Y-%m-%d")
    r = medir("resumo do periodo inteiro por dia", b.resumo, setor, de, ate, "dia")
    print(f"  -> {len(r)} linhas")
    medir("resumo do periodo inteiro por maquina", b.resumo, setor, de, ate, "maquina")
    medir("resumo de 30 dias por dia e maquina", b.resumo, setor,
          (fim_periodo - timedelta(days=30)).strftime("%Y-%m-%d"), ate, "dia_maquina")
    um_dia = (fim_periodo - timedelta(days=1)).strftime("%Y-%m-%d")
    csv = medir("CSV de 1 dia (/api/v2/ciclos)", b.csv_do_setor, setor, desde=um_dia, ate=um_dia)
    print(f"  -> {len(csv) / 1024:.0f} KB")
    for dias in (16, 35):  # janela padrao do painel (14 dias + 2 de folga) e uma maior
        janela = (fim_periodo - timedelta(days=dias)).strftime("%Y-%m-%d")
        csv = medir(f"CSV da janela de {dias} dias (/dados?desde=)", b.csv_do_setor, setor, desde=janela)
        print(f"  -> {len(csv) / 1024 / 1024:.1f} MB")
    medir("versao dos ciclos (ETag do /dados)", b.versao_ciclos, setor)
    csv = medir("CSV do historico inteiro (/dados antigo)", b.csv_do_setor, setor)
    print(f"  -> {len(csv) / 1024 / 1024:.1f} MB")

    b._conn.close()
    print(f"Tamanho do banco: {os.path.getsize(caminho) / 1024 / 1024:.0f} MB")
    if a.manter:
        print(f"(pasta mantida: {pasta})")
    else:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
