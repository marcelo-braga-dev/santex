"""
Gera um CSV de historico grande e realista para testar o painel
(painel/index.html) com dados ricos: 4 maquinas, perfis de
rendimento e dias de trabalho diferentes, cobrindo pouco mais de 1 ano -
o suficiente para exercitar os filtros de periodo (Dia/Semana/Mes/Ano).

Usa data/hora real (formato que o RTC vai produzir quando entrar em
producao), diferente do firmware atual (que so tem millis() desde o boot).

Uso:
    python gerar_dados_historico.py

Gera: exemplo_historico_completo.csv
"""

import os
import random
from datetime import date, timedelta

random.seed(42)

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SAIDA = os.path.join(DIR_BASE, "..", "dados", "exemplo_historico_completo.csv")

DIAS_HISTORICO = 400  # um pouco mais de 1 ano

# Perfis propositalmente diferentes para o comparativo entre maquinas ficar
# interessante: M1 roda quase todo dia util (alto rendimento), M2 so dia
# util comum, M3 so alguns dias por semana (baixo rendimento, muita
# manutencao/espera), M4 roda todo santo dia com ciclos curtos e rapidos e
# mais anomalias (sensor mais sensivel a ruido).
# dias_ativos: 0=segunda ... 6=domingo (igual ao Python date.weekday())
PERFIS = {
    1: {"dias_ativos": {0, 1, 2, 3, 4, 5}, "ciclos_dia": (5, 9), "duracao_min": (30, 120), "chance_curto": 0.03},
    2: {"dias_ativos": {0, 1, 2, 3, 4}, "ciclos_dia": (4, 7), "duracao_min": (15, 90), "chance_curto": 0.05},
    3: {"dias_ativos": {1, 3, 5}, "ciclos_dia": (2, 5), "duracao_min": (20, 150), "chance_curto": 0.06},
    4: {"dias_ativos": {0, 1, 2, 3, 4, 5, 6}, "ciclos_dia": (6, 10), "duracao_min": (5, 40), "chance_curto": 0.12},
}


def minutos_para_hora(total_min):
    total_seg = round(total_min * 60)
    h = (total_seg // 3600) % 24
    m = (total_seg % 3600) // 60
    s = total_seg % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


linhas = ["maquina,ciclo,data,hora_inicio,hora_fim,duracao_min,obs"]
total_ciclos = 0
hoje = date.today()

for maquina, cfg in PERFIS.items():
    ciclo = 0

    for dias_atras in range(DIAS_HISTORICO, -1, -1):
        dia = hoje - timedelta(days=dias_atras)
        if dia.weekday() not in cfg["dias_ativos"]:
            continue

        data_str = dia.isoformat()
        minuto_atual = 6 * 60 + random.randint(0, 90)  # comeca entre 06:00 e 07:30
        num_ciclos = random.randint(*cfg["ciclos_dia"])

        for _ in range(num_ciclos):
            if minuto_atual > 20 * 60:
                break
            ciclo += 1

            curto = random.random() < cfg["chance_curto"]
            if curto:
                duracao_min = round(random.uniform(0.1, 1.5), 1)
            else:
                duracao_min = float(random.randint(*cfg["duracao_min"]))

            inicio_min = minuto_atual
            fim_min = inicio_min + duracao_min
            obs = "CICLO_CURTO" if curto else ""

            linhas.append(
                f"{maquina},{ciclo},{data_str},{minutos_para_hora(inicio_min)},"
                f"{minutos_para_hora(fim_min)},{duracao_min},{obs}"
            )
            total_ciclos += 1

            minuto_atual = fim_min + random.randint(8, 45)

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas) + "\n")

print(f"Gerados {total_ciclos} ciclos em {CAMINHO_SAIDA}, cobrindo {DIAS_HISTORICO} dias")
