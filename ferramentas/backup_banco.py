"""
Backup automatico do banco (painel.db) - uma copia por dia, sem ninguem
precisar lembrar.

  - Pasta: backup/ na raiz do projeto (fora do git e do .exe), como
    backup/painel-AAAA-MM-DD.db - copia consistente feita pela API de backup
    do SQLite, segura com o app gravando ao mesmo tempo. Quem escolhe a pasta
    e app/caminhos.py (dir_backup); sem a pasta do projeto no PC, vale
    dados/backups. Para outra pasta: "pasta" no dados/backup.json.
  - Rotacao: ficam os 14 backups diarios mais recentes e, alem deles, o
    primeiro backup de cada mes dos ultimos 12 meses.
  - Copia extra (recomendado - protege contra perda/defeito do notebook):
    crie dados/backup.json com a pasta de destino, por exemplo uma pasta do
    OneDrive ou da rede:
        {"pasta_extra": "C:\\\\Users\\\\voce\\\\OneDrive\\\\Backup Painel"}
    A mesma rotacao vale para essa pasta.

O app (app/servidor.py) chama iniciar() ao abrir: faz o backup do dia logo
na abertura (se ainda nao houver) e confere de hora em hora.
"""

import json
import os
import re
import shutil
import threading
from datetime import date, datetime

PASTA_BACKUPS = "backups"
ARQUIVO_CONFIG = "backup.json"
MANTER_DIARIOS = 14
MANTER_MENSAIS = 12
INTERVALO_VERIFICACAO_S = 3600
_NOME = re.compile(r"^painel-(\d{4})-(\d{2})-(\d{2})\.db$")

_estado = {"ultimo_backup": "", "arquivo": "", "erro": "", "pasta_extra": "", "erro_extra": ""}
_trava = threading.Lock()


def status():
    """Situacao do backup para o painel (GET /sincronizacao -> "backup")."""
    with _trava:
        return dict(_estado)


def _config(dir_dados, chave):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_CONFIG), "r", encoding="utf-8") as arquivo:
            config = json.load(arquivo)
    except (OSError, ValueError):
        return ""
    valor = config.get(chave) if isinstance(config, dict) else ""
    return os.path.expandvars(str(valor).strip()) if valor else ""


def _pasta_extra(dir_dados):
    return _config(dir_dados, "pasta_extra")


def _backups_em(pasta):
    """[(data, nome)] dos backups da pasta, do mais novo para o mais antigo."""
    try:
        nomes = os.listdir(pasta)
    except OSError:
        return []
    saida = []
    for nome in nomes:
        m = _NOME.match(nome)
        if m:
            try:
                saida.append((date(int(m.group(1)), int(m.group(2)), int(m.group(3))), nome))
            except ValueError:
                continue
    return sorted(saida, reverse=True)


def _rotacionar(pasta):
    backups = _backups_em(pasta)
    manter = {nome for _, nome in backups[:MANTER_DIARIOS]}
    primeiro_do_mes = {}
    for dia, nome in backups:  # do mais novo ao mais antigo: o ultimo visto e o primeiro do mes
        primeiro_do_mes[(dia.year, dia.month)] = nome
    for mes in sorted(primeiro_do_mes, reverse=True)[:MANTER_MENSAIS]:
        manter.add(primeiro_do_mes[mes])
    for _, nome in backups:
        if nome not in manter:
            try:
                os.remove(os.path.join(pasta, nome))
            except OSError:
                pass


def fazer_backup_do_dia(banco, dir_dados, forcar=False, pasta=None):
    """Faz o backup de hoje se ainda nao existir (ou sempre, com forcar).
    pasta: onde gravar (padrao dados/backups; "pasta" no backup.json tem
    prioridade). Nunca levanta excecao - o erro fica em status()."""
    hoje = date.today()
    nome = f"painel-{hoje.isoformat()}.db"
    pasta = _config(dir_dados, "pasta") or pasta or os.path.join(dir_dados, PASTA_BACKUPS)
    destino = os.path.join(pasta, nome)
    try:
        if forcar or not os.path.isfile(destino):
            banco.fazer_backup(destino)
        _rotacionar(pasta)
        with _trava:
            _estado.update({"ultimo_backup": datetime.fromtimestamp(os.path.getmtime(destino)).isoformat(timespec="seconds"),
                            "arquivo": destino, "erro": ""})
    except Exception as erro:  # noqa: BLE001 - disco cheio, sem permissao...
        with _trava:
            _estado["erro"] = f"{type(erro).__name__}: {erro}"
        return

    extra = _pasta_extra(dir_dados)
    with _trava:
        _estado["pasta_extra"] = extra
    if not extra:
        return
    try:
        os.makedirs(extra, exist_ok=True)
        alvo = os.path.join(extra, nome)
        if forcar or not os.path.isfile(alvo):
            shutil.copy2(destino, alvo + ".tmp")
            os.replace(alvo + ".tmp", alvo)
        _rotacionar(extra)
        with _trava:
            _estado["erro_extra"] = ""
    except Exception as erro:  # noqa: BLE001 - pasta de rede fora do ar, etc.
        with _trava:
            _estado["erro_extra"] = f"{type(erro).__name__}: {erro}"


def iniciar(banco, dir_dados, pasta=None, parar_evento=None):
    """Thread que faz o backup do dia na abertura e confere de hora em hora."""
    parar_evento = parar_evento or threading.Event()

    def laco():
        while not parar_evento.is_set():
            fazer_backup_do_dia(banco, dir_dados, pasta=pasta)
            parar_evento.wait(INTERVALO_VERIFICACAO_S)

    thread = threading.Thread(target=laco, name="backup-banco", daemon=True)
    thread.start()
    return parar_evento
