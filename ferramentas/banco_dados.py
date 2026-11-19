"""
Banco de dados SQLite persistente do projeto - um unico arquivo
(painel.db) que nunca e apagado nem reescrito do zero, ao contrario do
antigo banco_de_dados.csv (que o monitor_serial.py recriava vazio toda vez
que era iniciado, perdendo o historico a cada reinicio).

Guarda cinco coisas, isoladas por setor:
  - ciclos:       cada ciclo real gravado pela leitura serial ou buscado
                  pelo Wi-Fi (so cresce, nunca e truncado). Os vindos pelo
                  Wi-Fi guardam dispositivo + origem_id (id sequencial do
                  ESP32), que impede gravar o mesmo ciclo duas vezes.
  - maquinas:     nome e producao por minuto configurados para cada
                  maquina (antes só no localStorage do navegador).
  - config_setor: outras configuracoes por setor: meta de rendimento em %
                  do tempo disponivel (meta_pct_dia) e a meta antiga em
                  horas ligado (meta_horas_dia, so mantida - nao e mais usada).
  - estado_ao_vivo: ultimo estado (ligada/desligada) de cada maquina e
                  desde quando, informado pelo firmware a cada 10s - nao e
                  historico, so a "foto" atual para o painel.
  - turnos:       turnos de trabalho do setor (nome, hora inicial e final),
                  usados pelo painel para agrupar os ciclos por turno.
  - config_extra: configuracoes do painel guardadas como JSON por chave
                  (ver CHAVES_EXTRA): pausas programadas de cada turno,
                  calendario do setor (dias trabalhados e excecoes) e o
                  historico de configuracao (taxa, meta e turnos com data
                  de inicio de vigencia).

Usado tanto por ferramentas/controle_leitura_server.py (processo separado)
quanto por app/servidor.py (mesmo processo, thread) - SQLite ja suporta
multiplos processos/threads acessando o mesmo arquivo com seguranca,
inclusive com o modo WAL ligado abaixo (mais resistente a fechamento
abrupto do programa).
"""

import json
import os
import re
import sqlite3
import threading

NOME_ARQUIVO = "painel.db"

_HORA_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Chaves aceitas em config_extra e o tamanho maximo do JSON de cada uma
# (protecao contra lixo - o painel nunca chega perto disso).
# "motivos" (1.3.0) = catalogo de motivos de parada + parada -> motivo marcado.
CHAVES_EXTRA = {"pausas": 20000, "calendario": 50000, "historico": 200000, "visual": 2000, "avisos": 2000,
                "motivos": 600000}
# Chaves que valem para o painel inteiro (nao por setor): "visual" = paleta
# de cores (Identidade visual) e nome da empresa - iguais em todo aparelho
# que abrir o painel. Ficam gravadas sob este "setor" fixo.
CHAVES_GERAIS = {"visual"}
SETOR_GERAL = "_geral"


def normalizar_extras(extras):
    """Filtra o dicionario "extras" vindo do painel (POST /config): so
    chaves conhecidas, valores que viram JSON dentro do limite de tamanho.
    Devolve {chave: texto_json}."""
    if not isinstance(extras, dict):
        return {}
    saida = {}
    for chave, valor in extras.items():
        limite = CHAVES_EXTRA.get(chave)
        if not limite or not isinstance(valor, (dict, list)):
            continue
        texto = json.dumps(valor, ensure_ascii=False, separators=(",", ":"))
        if len(texto) <= limite:
            saida[chave] = texto
    return saida


def normalizar_turnos(lista):
    """Valida a lista de turnos vinda do painel (POST /config) e devolve so
    os itens validos: hora "HH:MM" de 00:00 a 23:59, inicio diferente do fim
    (um turno que cruza a meia-noite, ex. 22:00-06:00, e valido). Devolve
    None se a lista nao for uma lista - o chamador entao nao mexe no banco."""
    if not isinstance(lista, list):
        return None
    turnos = []
    for i, item in enumerate(lista):
        if not isinstance(item, dict):
            continue
        inicio = str(item.get("inicio", "")).strip()
        fim = str(item.get("fim", "")).strip()
        if not _HORA_HHMM.match(inicio) or not _HORA_HHMM.match(fim) or inicio == fim:
            continue
        nome = str(item.get("nome", "")).strip()[:28] or f"Turno {i + 1}"
        turno = {"nome": nome, "inicio": inicio, "fim": fim}
        dias = _normalizar_dias_turno(item.get("dias"), inicio, fim)
        if dias:
            turno["dias"] = dias
        turnos.append(turno)
    return turnos


def _normalizar_dias_turno(dias, inicio_padrao, fim_padrao):
    """Horarios proprios do turno em certos dias da semana (ex.: sexta sai
    as 16:00 em vez das 17:00): {"0".."6" (0 = domingo): {"inicio", "fim"}}.
    Dia invalido ou igual ao horario padrao do turno e descartado."""
    if not isinstance(dias, dict):
        return {}
    saida = {}
    for d in range(7):
        item = dias.get(str(d))
        if not isinstance(item, dict):
            continue
        inicio = str(item.get("inicio", "")).strip()
        fim = str(item.get("fim", "")).strip()
        if not _HORA_HHMM.match(inicio) or not _HORA_HHMM.match(fim) or inicio == fim:
            continue
        if inicio == inicio_padrao and fim == fim_padrao:
            continue
        saida[str(d)] = {"inicio": inicio, "fim": fim}
    return saida

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ciclos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setor TEXT NOT NULL,
    maquina INTEGER NOT NULL,
    ciclo INTEGER NOT NULL,
    inicio_ms TEXT,
    fim_ms TEXT,
    duracao_s REAL NOT NULL,
    obs TEXT NOT NULL DEFAULT '',
    gravado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    dispositivo TEXT,
    origem_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ciclos_setor ON ciclos(setor, id);

CREATE TABLE IF NOT EXISTS maquinas (
    setor TEXT NOT NULL,
    maquina INTEGER NOT NULL,
    nome TEXT NOT NULL,
    metros_por_min REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (setor, maquina)
);

CREATE TABLE IF NOT EXISTS config_setor (
    setor TEXT PRIMARY KEY,
    meta_horas_dia REAL NOT NULL DEFAULT 8
);

CREATE TABLE IF NOT EXISTS estado_ao_vivo (
    setor TEXT NOT NULL,
    maquina INTEGER NOT NULL,
    ligado INTEGER NOT NULL,
    desde TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (setor, maquina)
);

CREATE TABLE IF NOT EXISTS config_extra (
    setor TEXT NOT NULL,
    chave TEXT NOT NULL,
    valor TEXT NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (setor, chave)
);

-- segredos do painel (ex.: hash da senha do acesso remoto) - separados da
-- configuracao para NUNCA sairem pelo GET /config
CREATE TABLE IF NOT EXISTS segredos (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- revisao de cada item de configuracao (sincronizacao notebook <-> VPS, 1.2.0):
-- rev = ordem global dada pela VPS; pendente = alterado aqui e ainda nao
-- confirmado pela VPS (so no notebook)
CREATE TABLE IF NOT EXISTS config_rev (
    chave TEXT PRIMARY KEY,
    rev INTEGER NOT NULL DEFAULT 0,
    editado_em TEXT NOT NULL DEFAULT '',
    origem TEXT NOT NULL DEFAULT '',
    autor TEXT NOT NULL DEFAULT '',
    pendente INTEGER NOT NULL DEFAULT 0
);

-- auditoria: quem alterou o que, quando e de onde
CREATE TABLE IF NOT EXISTS alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    origem TEXT NOT NULL,
    autor TEXT NOT NULL DEFAULT '',
    chave TEXT NOT NULL,
    resumo TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS turnos (
    setor TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    nome TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fim TEXT NOT NULL,
    dias TEXT,
    PRIMARY KEY (setor, ordem)
);
"""


def _padrao_serie(dispositivo):
    """"403F07000000-01FCB9D1" -> "%-01FCB9D1" (LIKE): a serie aleatoria que
    o ESP32 guarda na NVS identifica o controlador; a parte do MAC antes do
    "-" se mostrou instavel entre versoes do firmware."""
    serie = str(dispositivo).rsplit("-", 1)[-1]
    return "%-" + serie.replace("%", "").replace("_", "")


class BancoDados:
    def __init__(self, caminho_db):
        self.caminho = caminho_db
        os.makedirs(os.path.dirname(caminho_db), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(caminho_db, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_ESQUEMA)
        self._migrar_colunas_origem()
        self._migrar_csv_antigo_se_existir()

    # -- ciclos ---------------------------------------------------------

    def gravar_ciclo(self, setor, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO ciclos (setor, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (setor, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs),
            )

    def gravar_ciclo_remoto(self, setor, dispositivo, origem_id, maquina, ciclo, inicio, fim, duracao_s, obs, gravado_em=None):
        """Grava um ciclo buscado do ESP32 pelo Wi-Fi. gravado_em e o fim do
        ciclo pelo RTC ("AAAA-MM-DD HH:MM:SS"); None = ESP32 sem hora valida,
        usa a hora do PC. Devolve False se o ciclo ja estava no banco (mesma
        serie do ESP32 + origem_id) - buscar de novo nunca duplica nada,
        mesmo que a parte do MAC no id do dispositivo mude (ja aconteceu:
        3 ids diferentes para o mesmo controlador, todos com a mesma serie)."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO ciclos "
                "(setor, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs, gravado_em, dispositivo, origem_id) "
                "SELECT ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now', 'localtime')), ?, ? "
                "WHERE NOT EXISTS (SELECT 1 FROM ciclos WHERE origem_id = ? AND (dispositivo = ? OR dispositivo LIKE ?))",
                (setor, maquina, ciclo, inicio, fim, duracao_s, obs, gravado_em, dispositivo, origem_id,
                 origem_id, dispositivo, _padrao_serie(dispositivo)),
            )
        return cursor.rowcount == 1

    def ultimo_id_origem(self, dispositivo):
        """Maior id de ciclo deste ESP32 ja gravado aqui (0 = nenhum) -
        reconhecido pela serie (parte depois do "-"), que so muda se a
        memoria NVS do ESP32 for apagada (ai os ids recomecam do 1)."""
        with self._lock:
            linha = self._conn.execute(
                "SELECT MAX(origem_id) AS ultimo FROM ciclos WHERE dispositivo = ? OR dispositivo LIKE ?",
                (dispositivo, _padrao_serie(dispositivo)),
            ).fetchone()
        return linha["ultimo"] or 0

    def ciclos_para_nuvem(self, setor, apos_id, limite):
        """Ciclos com id local > apos_id, em ordem - o historico que o
        notebook envia para a VPS (nuvem.EnviadorConfig)."""
        with self._lock:
            return [dict(l) for l in self._conn.execute(
                "SELECT id, maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs, gravado_em, dispositivo, origem_id "
                "FROM ciclos WHERE setor = ? AND id > ? ORDER BY id LIMIT ?",
                (setor, apos_id, limite),
            )]

    def total_ciclos(self, setor, apos_id=0):
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM ciclos WHERE setor = ? AND id > ?", (setor, apos_id)
            ).fetchone()[0]

    def versao_ciclos(self, setor):
        """Identifica o conteudo atual dos ciclos do setor (muda a cada ciclo
        gravado) - usado pelo servidor para responder "nada mudou" (304) sem
        montar o CSV inteiro."""
        with self._lock:
            linha = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS ultimo FROM ciclos WHERE setor = ?", (setor,)
            ).fetchone()
        return f"{linha['n']}-{linha['ultimo']}"

    def fazer_backup(self, destino):
        """Copia consistente do banco inteiro para o arquivo destino (API de
        backup do SQLite: segura com o banco em uso, inclusive no modo WAL).
        Grava num temporario e renomeia - nunca deixa um backup pela metade."""
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        temporario = destino + ".tmp"
        copia = sqlite3.connect(temporario)
        try:
            with self._lock:
                self._conn.backup(copia)
            copia.close()
            os.replace(temporario, destino)
        finally:
            try:
                copia.close()
            except sqlite3.Error:
                pass
            if os.path.exists(temporario):
                os.remove(temporario)

    def csv_do_setor(self, setor):
        """Reconstroi o CSV no mesmo formato que o painel web ja sabe ler
        (maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs) - assim o painel nao
        precisa saber que a fonte agora e um banco SQLite, nao um arquivo.

        A coluna extra "registrado_em" e o horario real do fim do ciclo: o
        do RTC do ESP32 nos ciclos buscados pelo Wi-Fi, ou a hora do PC no
        momento em que o ciclo chegou pela Serial. E ela que da ao painel o
        horario de cada ciclo - necessario para os filtros de periodo e o
        agrupamento por turno.

        Excecao: ciclo baixado pelo Wi-Fi com SEM_HORA (o ESP32 estava sem
        relogio) sai com registrado_em VAZIO - o gravado_em dele e so a hora
        do download, e usa-la empilhava dias de producao no momento da
        sincronizacao (ja aconteceu: 834 ciclos "as 07h de 10/11"). O painel
        conta esses ciclos a parte ("sem data/hora"). O banco nao muda.
        Pela Serial o gravado_em e a hora real de chegada, entao vale."""
        with self._lock:
            linhas = self._conn.execute(
                "SELECT maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs, gravado_em, dispositivo "
                "FROM ciclos WHERE setor = ? ORDER BY id",
                (setor,),
            ).fetchall()
        saida = ["maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs,registrado_em"]
        for l in linhas:
            # (ciclos da Serial enviados pelo notebook a VPS ficam com dispositivo
            # "NOTEBOOK-SERIAL": a hora de chegada deles e real, como no notebook)
            sem_hora_real = (l["dispositivo"] is not None and not l["dispositivo"].startswith("NOTEBOOK-SERIAL")
                             and "SEM_HORA" in (l["obs"] or ""))
            registrado_em = "" if sem_hora_real else (l["gravado_em"] or "").replace(" ", "T")
            saida.append(
                f"{l['maquina']},{l['ciclo']},{l['inicio_ms']},{l['fim_ms']},{l['duracao_s']},{l['obs']},{registrado_em}"
            )
        return "\n".join(saida) + "\n"

    # -- configuracao de maquinas ----------------------------------------

    def obter_maquinas(self, setor):
        with self._lock:
            linhas = self._conn.execute(
                "SELECT maquina, nome, metros_por_min FROM maquinas WHERE setor = ?",
                (setor,),
            ).fetchall()
        return {
            str(l["maquina"]): {"nome": l["nome"], "metrosPorMin": l["metros_por_min"]}
            for l in linhas
        }

    def salvar_maquina(self, setor, maquina, nome, metros_por_min):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO maquinas (setor, maquina, nome, metros_por_min) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(setor, maquina) DO UPDATE SET "
                "nome = excluded.nome, metros_por_min = excluded.metros_por_min",
                (setor, maquina, nome, metros_por_min),
            )

    # -- config geral do setor -------------------------------------------

    def obter_meta_horas_dia(self, setor, padrao=8):
        with self._lock:
            linha = self._conn.execute(
                "SELECT meta_horas_dia FROM config_setor WHERE setor = ?", (setor,)
            ).fetchone()
        return linha["meta_horas_dia"] if linha else padrao

    def salvar_meta_horas_dia(self, setor, meta_horas_dia):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO config_setor (setor, meta_horas_dia) VALUES (?, ?) "
                "ON CONFLICT(setor) DO UPDATE SET meta_horas_dia = excluded.meta_horas_dia",
                (setor, meta_horas_dia),
            )

    def obter_meta_pct_dia(self, setor):
        """Meta de rendimento em % do tempo disponivel do turno (substitui a
        meta em horas). None = ainda nao definida neste banco (o painel
        converte a meta antiga em horas e grava)."""
        with self._lock:
            linha = self._conn.execute(
                "SELECT meta_pct_dia FROM config_setor WHERE setor = ?", (setor,)
            ).fetchone()
        return linha["meta_pct_dia"] if linha else None

    def salvar_meta_pct_dia(self, setor, meta_pct):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO config_setor (setor, meta_pct_dia) VALUES (?, ?) "
                "ON CONFLICT(setor) DO UPDATE SET meta_pct_dia = excluded.meta_pct_dia",
                (setor, meta_pct),
            )

    # -- estado ao vivo ----------------------------------------------------

    def atualizar_estado_ao_vivo(self, setor, maquina, ligado, desde):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO estado_ao_vivo (setor, maquina, ligado, desde, atualizado_em) "
                "VALUES (?, ?, ?, ?, datetime('now', 'localtime')) "
                "ON CONFLICT(setor, maquina) DO UPDATE SET ligado = excluded.ligado, "
                "desde = excluded.desde, atualizado_em = excluded.atualizado_em",
                (setor, maquina, 1 if ligado else 0, desde),
            )

    def obter_estado_ao_vivo(self, setor):
        """{"1": {"ligado": true, "desde": "...", "segundosSemSinal": 4}, ...}
        - segundosSemSinal = ha quanto tempo o firmware nao confirma o estado
        (acima de ~30s o painel trata como "sem sinal")."""
        with self._lock:
            linhas = self._conn.execute(
                "SELECT maquina, ligado, desde, "
                "CAST(strftime('%s', datetime('now', 'localtime')) - strftime('%s', atualizado_em) AS INTEGER) AS sem_sinal "
                "FROM estado_ao_vivo WHERE setor = ?",
                (setor,),
            ).fetchall()
        return {
            str(l["maquina"]): {"ligado": bool(l["ligado"]), "desde": l["desde"], "segundosSemSinal": l["sem_sinal"]}
            for l in linhas
        }

    # -- turnos ------------------------------------------------------------

    def obter_turnos(self, setor):
        """Lista de turnos do setor, na ordem configurada:
        [{"nome": "Turno 1", "inicio": "06:00", "fim": "14:00"}, ...].
        Turno com horario diferente em alguns dias da semana traz tambem
        "dias": {"5": {"inicio": "06:00", "fim": "16:00"}} (0 = domingo).
        Lista vazia = setor ainda sem turnos salvos (o painel usa o padrao)."""
        with self._lock:
            linhas = self._conn.execute(
                "SELECT nome, inicio, fim, dias FROM turnos WHERE setor = ? ORDER BY ordem",
                (setor,),
            ).fetchall()
        saida = []
        for l in linhas:
            turno = {"nome": l["nome"], "inicio": l["inicio"], "fim": l["fim"]}
            try:
                dias = _normalizar_dias_turno(json.loads(l["dias"] or "{}"), l["inicio"], l["fim"])
            except ValueError:
                dias = {}
            if dias:
                turno["dias"] = dias
            saida.append(turno)
        return saida

    def salvar_turnos(self, setor, turnos):
        """Substitui todos os turnos do setor pela lista recebida."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM turnos WHERE setor = ?", (setor,))
            self._conn.executemany(
                "INSERT INTO turnos (setor, ordem, nome, inicio, fim, dias) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (setor, i, t["nome"], t["inicio"], t["fim"],
                     json.dumps(t["dias"], separators=(",", ":")) if t.get("dias") else None)
                    for i, t in enumerate(turnos)
                ],
            )

    # -- configuracoes extras (JSON) -----------------------------------------

    def obter_extras(self, setor):
        """{chave: valor} com as configuracoes extras do setor (ja como
        objetos Python). Chave ausente = nunca foi salva."""
        with self._lock:
            linhas = self._conn.execute(
                "SELECT chave, valor FROM config_extra WHERE (setor = ? AND chave NOT IN ({0})) "
                "OR (setor = ? AND chave IN ({0}))".format(",".join("?" * len(CHAVES_GERAIS))),
                (setor, *CHAVES_GERAIS, SETOR_GERAL, *CHAVES_GERAIS),
            ).fetchall()
        extras = {}
        for l in linhas:
            try:
                extras[l["chave"]] = json.loads(l["valor"])
            except ValueError:
                pass
        return extras

    def salvar_extras(self, setor, extras_json):
        """Grava {chave: texto_json} (ja validado por normalizar_extras)."""
        if not extras_json:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO config_extra (setor, chave, valor, atualizado_em) VALUES (?, ?, ?, datetime('now', 'localtime')) "
                "ON CONFLICT(setor, chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em",
                [(SETOR_GERAL if k in CHAVES_GERAIS else setor, k, v) for k, v in extras_json.items()],
            )

    # -- segredos (nunca expostos pela API) ------------------------------------

    def obter_segredo(self, chave):
        with self._lock:
            linha = self._conn.execute("SELECT valor FROM segredos WHERE chave = ?", (chave,)).fetchone()
        return linha["valor"] if linha else None

    def salvar_segredo(self, chave, valor):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO segredos (chave, valor, atualizado_em) VALUES (?, ?, datetime('now', 'localtime')) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em",
                (chave, valor),
            )

    # -- revisoes da configuracao e auditoria (1.2.0) --------------------------

    def listar_revs(self):
        with self._lock:
            return {l["chave"]: dict(l) for l in self._conn.execute("SELECT * FROM config_rev")}

    def obter_rev(self, chave):
        with self._lock:
            linha = self._conn.execute("SELECT * FROM config_rev WHERE chave = ?", (chave,)).fetchone()
        return dict(linha) if linha else None

    def marcar_rev(self, chave, rev, editado_em, origem, autor, pendente):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO config_rev (chave, rev, editado_em, origem, autor, pendente) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET rev = excluded.rev, editado_em = excluded.editado_em, "
                "origem = excluded.origem, autor = excluded.autor, pendente = excluded.pendente",
                (chave, int(rev), editado_em, origem, autor[:80], 1 if pendente else 0),
            )

    def max_rev(self):
        with self._lock:
            return self._conn.execute("SELECT COALESCE(MAX(rev), 0) FROM config_rev").fetchone()[0]

    def pendentes(self):
        with self._lock:
            return [dict(l) for l in self._conn.execute("SELECT * FROM config_rev WHERE pendente = 1 ORDER BY chave")]

    def registrar_alteracao(self, quando, origem, autor, chave, resumo):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO alteracoes (quando, origem, autor, chave, resumo) VALUES (?, ?, ?, ?, ?)",
                (quando, origem, autor[:80], chave[:60], resumo[:200]),
            )
            # mantem so as 2000 mais recentes
            self._conn.execute("DELETE FROM alteracoes WHERE id <= (SELECT MAX(id) FROM alteracoes) - 2000")

    def ultimas_alteracoes(self, limite=50):
        with self._lock:
            return [dict(l) for l in self._conn.execute(
                "SELECT quando, origem, autor, chave, resumo FROM alteracoes ORDER BY id DESC LIMIT ?", (limite,))]

    # -- migracao do formato antigo ---------------------------------------

    def _migrar_colunas_origem(self):
        """Bancos criados antes da leitura por Wi-Fi nao tem as colunas
        dispositivo/origem_id - acrescenta sem mexer nos ciclos existentes
        (que ficam com NULL, e NULLs nunca colidem no indice unico)."""
        with self._lock, self._conn:
            colunas = {l["name"] for l in self._conn.execute("PRAGMA table_info(ciclos)")}
            if "dispositivo" not in colunas:
                self._conn.execute("ALTER TABLE ciclos ADD COLUMN dispositivo TEXT")
            if "origem_id" not in colunas:
                self._conn.execute("ALTER TABLE ciclos ADD COLUMN origem_id INTEGER")
            # horarios por dia da semana dos turnos (bancos antigos nao tem)
            # meta de rendimento em % (bancos antigos so tem a meta em horas,
            # que fica preservada como estava)
            colunas_setor = {l["name"] for l in self._conn.execute("PRAGMA table_info(config_setor)")}
            if "meta_pct_dia" not in colunas_setor:
                self._conn.execute("ALTER TABLE config_setor ADD COLUMN meta_pct_dia REAL")
            colunas_turnos = {l["name"] for l in self._conn.execute("PRAGMA table_info(turnos)")}
            if "dias" not in colunas_turnos:
                self._conn.execute("ALTER TABLE turnos ADD COLUMN dias TEXT")
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ciclos_origem ON ciclos(dispositivo, origem_id)"
            )
            # busca por origem_id sozinho (deduplicacao pela serie do ESP32)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ciclos_origem_id ON ciclos(origem_id)")

    def _migrar_csv_antigo_se_existir(self):
        """Antes do banco.db existir, os dados viviam em banco_de_dados.csv
        (reescrito do zero a cada execucao - por isso normalmente so tem o
        cabecalho). Se alguem tiver um CSV antigo com ciclos reais parado
        ali, importa pra dentro do banco (setor "enfestadeiras", unico que
        existia nesse formato) uma unica vez, e renomeia o CSV pra nao
        importar de novo."""
        csv_antigo = os.path.join(os.path.dirname(self.caminho), "banco_de_dados.csv")
        if not os.path.isfile(csv_antigo):
            return
        with self._lock:
            ja_tem_dado = self._conn.execute("SELECT 1 FROM ciclos LIMIT 1").fetchone()
        if ja_tem_dado:
            os.replace(csv_antigo, csv_antigo + ".migrado")
            return

        importados = 0
        with open(csv_antigo, "r", encoding="utf-8") as arquivo:
            linhas = [l.strip() for l in arquivo if l.strip()]
        for linha in linhas[1:]:  # pula o cabecalho
            partes = linha.split(",")
            if len(partes) != 6 or not partes[0].strip().isdigit() or not partes[1].strip().isdigit():
                continue
            maquina, ciclo, inicio_ms, fim_ms, duracao_s, obs = partes
            try:
                duracao_s = float(duracao_s)
            except ValueError:
                continue
            self.gravar_ciclo("enfestadeiras", int(maquina), int(ciclo), inicio_ms, fim_ms, duracao_s, obs)
            importados += 1

        os.replace(csv_antigo, csv_antigo + ".migrado")
        if importados:
            print(f"[banco_dados] {importados} ciclo(s) migrado(s) de banco_de_dados.csv para {NOME_ARQUIVO}.")
