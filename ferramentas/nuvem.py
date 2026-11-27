"""
Acesso remoto pela VPS (app 1.1.0 / firmware 3.0).

Quem faz o que:
  - O NOTEBOOK continua sendo o fornecedor principal na rede da empresa: le
    o ESP32 como sempre e e onde a configuracao (maquinas, metas, turnos...)
    e editada. Quando ligado, envia essa configuracao para a VPS
    (EnviadorConfig, abaixo).
  - O ESP32 (firmware 3.0) envia, por HTTPS, os ciclos e o estado das
    maquinas DIRETO para a VPS - sem depender do notebook ligado.
  - A VPS roda este mesmo servidor com PAINEL_MODO=nuvem: guarda uma copia e
    serve o painel SOMENTE LEITURA, com login, para quem esta fora da rede.

Notebook como segunda fonte (1.7.0): junto do historico, o notebook manda o
ESTADO AO VIVO das maquinas que ele le do ESP32 pela rede local ("ao_vivo":
maquinas + ha quantos segundos falou com o ESP32). A VPS so aplica se for mais
novo que o ultimo envio direto do ESP32 - o ESP32 continua a fonte principal.
Quando a VPS responde que o ESP32 esta sem enviar direto, o notebook passa a
mandar a cada 5 s (estado e ciclos novos). O status diz a fonte: "esp",
"notebook" ou nenhuma.

Historico: o notebook tambem envia para a VPS TODOS os ciclos que ela ainda
nao tem (em lotes, depois os novos a cada 30 s) - a VPS fica com o mesmo
historico do notebook, alem do que o ESP32 manda direto. Deduplicacao pela
serie do ESP32 + id do ciclo: o que chega pelos dois caminhos nao repete.

Rotas da VPS (POST, com o cabecalho X-Chave-Nuvem = NUVEM_CHAVE do .env):
  /api/nuvem/enviar  <- ESP32: {"dispositivo", "firmware", "hora", "hora_valida",
                       "ultimo_id", "lido_ate", "perdidos", "maquinas": [...],
                       "ciclos": "id,maquina,ciclo,inicio,fim,duracao_s,obs\\n..."}
  /api/nuvem/config  <- notebook: o mesmo formato de GET /config
  /api/nuvem/historico <- notebook: {"setor", "ciclos": [[id, maquina, ciclo,
                       inicio, fim, duracao_s, obs, gravado_em, dispositivo,
                       origem_id], ...]} -> {"ok", "gravados", "total"}

Pessoas (1.2.0): o NOTEBOOK e o mestre - nunca pede senha e pode tudo. Quem
entra pela VPS usa uma de duas senhas: VISUALIZACAO (so ve) ou EDICAO (ve e
altera a configuracao: maquinas, metas, turnos, pausas, calendario,
vigencias, cores, e as proprias senhas redigitando a de edicao atual). As
senhas ficam so como hash (PBKDF2); a sessao dura 30 dias (cookie assinado com
o papel). O notebook pode desligar a edicao remota a qualquer momento.

Configuracao nas duas maos (1.2.0): cada item (maquina:N, meta_pct, turnos,
extras:*, senhas, edicao_remota) tem revisao (tabela config_rev). A VPS e o hub
e da a ordem global; o notebook troca com ela a cada 15 s
(POST /api/nuvem/config, "versao": 2): manda o que mudou aqui, recebe o que
mudou la. Mesmo item alterado nos dois lados = vale o mais recente (UTC).
Tudo vai para a auditoria (tabela alteracoes).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import setores as cadastro_setores
from banco_dados import normalizar_extras, normalizar_turnos
from monitor_serial import SETOR_PADRAO
from monitor_wifi import ARQUIVO_CHAVE_APP, _gravar_json, gravar_linhas_ciclos, registrar_multi_seguro

ARQUIVO_STATUS_NUVEM = "nuvem_status.json"
ARQUIVO_CHAVE_SESSAO = "sessao.key"  # VPS: assina os cookies de sessao (gerado uma vez)
SEGREDO_SENHA_REMOTA = "acesso_remoto"  # senha de VISUALIZACAO: {"hash", "alterado_em"}
SEGREDO_SENHA_EDICAO = "acesso_edicao"  # senha de EDICAO: {"hash", "alterado_em"}
SEGREDO_EDICAO_REMOTA = "edicao_remota"  # {"ativa": bool} - so o notebook muda
SEGREDO_SYNC_CONFIG = "sync_config_nuvem"  # notebook: {"url", "rev"} ultima revisao conhecida da VPS
SEGREDO_AUDITORIA_NUVEM = "auditoria_nuvem"  # notebook: copia das ultimas alteracoes da VPS
SEGREDO_AVISOS_SYNC = "avisos_sync_config"  # notebook: avisos de mudancas recebidas/conflitos
SEGREDO_SENHAS_TEXTO = "senhas_remotas_texto"  # SO notebook (1.7.2): texto das senhas remotas - nunca sincronizado
SENHA_EDICAO_MIN = 10
SEMENTE_EM = "1970-01-01T00:00:00.000+00:00"  # data das sementes (perdem para qualquer edicao real)
COOKIE_SESSAO = "painel_sessao"
DIAS_SESSAO = 30
SENHA_MIN, SENHA_MAX = 8, 128
ARQUIVO_CONFIG_NUVEM = "nuvem.json"  # no notebook: {"url": "...", "chave": "..."} (opcional)
ESP_SEM_ENVIAR_S = 60  # sem envio do ESP32 ha mais que isso = "controlador sem enviar"
AO_VIVO_MAX_IDADE_S = 60  # estado vindo do notebook mais velho que isso nao vale
MAX_CICLOS_POR_ENVIO = 500
MAX_HISTORICO_POR_ENVIO = 500
DISPOSITIVO_SERIAL = "NOTEBOOK-SERIAL"  # ciclos lidos pela USB (sem serie do ESP32)
CURSOR_HISTORICO = "cursor_historico_nuvem"  # notebook: ate qual id local a VPS confirmou
# 1.7.1: reenvio unico do historico inteiro para a VPS completar a hora dos
# ciclos que o ESP32 mandou sem hora (a VPS nao duplica nada). Guarda a URL ja
# reenviada; trocar o valor faz um novo reenvio unico.
REENVIO_HORA = "reenvio_hora_nuvem_1_7_2"  # 1.7.2: nome novo - o reenvio da 1.7.1 pode ter ido para uma VPS antiga


def _agora_iso():
    return datetime.now().isoformat(timespec="seconds")


def chave_confere(esperada, enviada):
    """Comparacao em tempo constante; chave vazia nunca confere."""
    esperada, enviada = str(esperada or ""), str(enviada or "")
    return bool(esperada) and bool(enviada) and hmac.compare_digest(esperada.encode(), enviada.encode())


# ---------------------------------------------------------------------
# Configuracao do setor (painel local, notebook -> VPS)
# ---------------------------------------------------------------------
def config_do_setor(banco, setor):
    """O que GET /config devolve - e o que o notebook envia para a VPS."""
    return {
        "maquinas": banco.obter_maquinas(setor),
        "metaHorasDia": banco.obter_meta_horas_dia(setor),
        "metaPctDia": banco.obter_meta_pct_dia(setor),
        "turnos": banco.obter_turnos(setor),
        "extras": banco.obter_extras(setor),
    }


_trava_config = threading.RLock()  # revisoes em ordem: uma gravacao de configuracao por vez


def _em_ordem(funcao):
    def envolvida(*args, **kwargs):
        with _trava_config:
            return funcao(*args, **kwargs)
    envolvida.__name__, envolvida.__doc__ = funcao.__name__, funcao.__doc__
    return envolvida


@_em_ordem
def aplicar_config(banco, corpo, setor_padrao, origem=None, autor=""):
    """Grava no banco a configuracao recebida (POST /config do painel),
    validando cada campo. Com origem ("notebook" ou "nuvem"), marca a revisao
    dos itens que mudaram e registra a auditoria. Devolve os itens alterados."""
    setor = str(corpo.get("setor", setor_padrao))[:40]
    antes = itens_atuais(banco, setor) if origem else None
    _aplicar_campos(banco, corpo, setor)
    if origem:
        return registrar_mudancas(banco, antes, itens_atuais(banco, setor), origem, autor)
    _tocar_config()
    return []


def _aplicar_campos(banco, corpo, setor):
    maquinas = corpo.get("maquinas")
    for maquina_id, item in (maquinas.items() if isinstance(maquinas, dict) else []):
        if not isinstance(item, dict):
            continue
        try:
            numero = int(maquina_id)
        except (TypeError, ValueError):
            continue
        if not 1 <= numero <= 64:
            continue
        nome = str(item.get("nome", "")).strip()[:40] or f"Máquina {numero}"
        try:
            taxa = float(item.get("metrosPorMin", 0))
        except (TypeError, ValueError):
            taxa = 0
        banco.salvar_maquina(setor, numero, nome, max(0.0, min(taxa, 100000.0)))

    if "metaHorasDia" in corpo:
        try:
            meta = float(corpo["metaHorasDia"])
            if 0 < meta <= 24:
                banco.salvar_meta_horas_dia(setor, meta)
        except (TypeError, ValueError):
            pass

    if "metaPctDia" in corpo and corpo["metaPctDia"] is not None:
        try:
            meta_pct = float(corpo["metaPctDia"])
            if 0 < meta_pct <= 100:
                banco.salvar_meta_pct_dia(setor, round(meta_pct, 1))
        except (TypeError, ValueError):
            pass

    if "turnos" in corpo:
        turnos = normalizar_turnos(corpo["turnos"])
        if turnos:
            banco.salvar_turnos(setor, turnos)

    if "extras" in corpo:
        banco.salvar_extras(setor, normalizar_extras(corpo["extras"]))


# ---------------------------------------------------------------------
# Itens versionados da configuracao (sincronizacao nas duas maos, 1.2.0)
# ---------------------------------------------------------------------
EXTRAS_SINCRONIZADOS = ("pausas", "calendario", "historico", "avisos", "visual", "motivos", "logo", "semProducao")
EXTRAS_DO_SETOR = ("pausas", "calendario", "historico", "avisos", "motivos", "semProducao")
EXTRAS_GLOBAIS = ("visual", "logo")
# 2.0: itens de configuracao por setor. Os do setor que ja existia na 1.x
# continuam SEM prefixo ("maquina:1", "turnos" - o formato que a VPS 1.x
# conhece); os dos outros setores levam o slug: "costura/maquina:1".
# Itens globais (identidade visual, logo, senhas, edicao remota, cadastro de
# setores) nunca tem prefixo.
SETOR_LEGADO = SETOR_PADRAO
_RE_ITEM_SETOR = re.compile(r"^(?:([a-z][a-z0-9-]{0,39})/)?"
                            r"(maquina:\d{1,2}|meta_pct|turnos|extras:(?:pausas|calendario|historico|avisos|motivos|semProducao))$")
_RE_ITEM_GLOBAL = re.compile(r"^(?:extras:(?:visual|logo)|senha_leitura|senha_edicao|edicao_remota|setores)$")
_NOMES_ITEM = {
    "meta_pct": "Meta", "turnos": "Turnos", "extras:pausas": "Intervalos de refeição",
    "extras:calendario": "Calendário", "extras:historico": "Histórico de configurações",
    "extras:avisos": "Avisos", "extras:visual": "Identidade visual", "extras:motivos": "Motivos de parada", "extras:logo": "Logo da empresa", "extras:semProducao": "Máquinas sem produção",
    "senha_leitura": "Senha de visualização", "senha_edicao": "Senha de edição", "edicao_remota": "Edição remota",
    "setores": "Setores",
}
_versao_config = {"v": time.time_ns()}


def versao_config():
    """Muda a cada gravacao de configuracao: os paineis comparam em /status e
    recarregam sozinhos quando outra pessoa (ou o outro lado) alterou."""
    return str(_versao_config["v"])


def _tocar_config():
    _versao_config["v"] = time.time_ns()


def _agora_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def separar_chave(chave):
    """"costura/maquina:3" -> ("costura", "maquina:3"); "turnos" -> (setor
    legado, "turnos"); item global -> (None, chave); invalida -> (None, None)."""
    chave = str(chave or "")
    if _RE_ITEM_GLOBAL.match(chave):
        return None, chave
    m = _RE_ITEM_SETOR.match(chave)
    if not m or m.group(1) == SETOR_LEGADO:  # o setor legado nunca leva prefixo
        return None, None
    return m.group(1) or SETOR_LEGADO, m.group(2)


def chave_do_setor(setor, base):
    return base if setor == SETOR_LEGADO else f"{setor}/{base}"


def chave_item_valida(chave):
    return separar_chave(chave)[1] is not None


def _ordem_sync(itens):
    """O cadastro de setores primeiro: os itens de um setor novo chegam
    junto com ele."""
    return sorted(itens.items(), key=lambda kv: kv[0] != "setores")


def nome_item(chave):
    setor, base = separar_chave(chave)
    base = base or chave
    texto = f"Máquina {base.split(':', 1)[1]}" if base.startswith("maquina:") else _NOMES_ITEM.get(base, base)
    return f"{setor} · {texto}" if setor and setor != SETOR_LEGADO else texto


def _segredo_json(banco, chave):
    try:
        dados = json.loads(banco.obter_segredo(chave) or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _dados_hash(banco, chave):
    dados = _segredo_json(banco, chave)
    return dados if _hash_valido(dados.get("hash")) else {}


def itens_atuais(banco, setor=None):
    """{chave: valor} de toda a configuracao versionada - de TODOS os setores
    do cadastro (2.0) mais os itens globais. ("setor" ficou so por
    compatibilidade com quem chama.)"""
    itens = {}
    slugs = [s["setor"] for s in banco.listar_setores()]
    for slug in slugs:
        for n, m in banco.obter_maquinas(slug).items():
            itens[chave_do_setor(slug, f"maquina:{n}")] = {"nome": m["nome"], "metrosPorMin": m["metrosPorMin"]}
        meta = banco.obter_meta_pct_dia(slug)
        if meta is not None:
            itens[chave_do_setor(slug, "meta_pct")] = meta
        turnos = banco.obter_turnos(slug)
        if turnos:
            itens[chave_do_setor(slug, "turnos")] = turnos
        extras = banco.obter_extras(slug)
        for k in EXTRAS_DO_SETOR:
            if k in extras:
                itens[chave_do_setor(slug, f"extras:{k}")] = extras[k]
    globais = banco.obter_extras(slugs[0] if slugs else SETOR_LEGADO)
    for k in EXTRAS_GLOBAIS:
        if k in globais:
            itens[f"extras:{k}"] = globais[k]
    for chave, segredo in (("senha_leitura", SEGREDO_SENHA_REMOTA), ("senha_edicao", SEGREDO_SENHA_EDICAO)):
        dados = _dados_hash(banco, segredo)
        if dados:
            itens[chave] = {"hash": dados["hash"], "alterado_em": dados.get("alterado_em", "")}
    er = _segredo_json(banco, SEGREDO_EDICAO_REMOTA)
    if er:
        itens["edicao_remota"] = {"ativa": bool(er.get("ativa", True))}
    itens["setores"] = cadastro_setores.lista_para_sync(banco)  # 2.0: cadastro de setores (global)
    return itens


def ler_item(banco, setor, chave):
    return itens_atuais(banco, setor).get(chave)


def gravar_item(banco, setor, chave, valor):
    """Grava um item vindo da sincronizacao nas tabelas de sempre. O setor
    vem da propria chave ("costura/turnos"); sem prefixo = setor legado."""
    alvo, chave = separar_chave(chave)
    if chave is None:
        raise ValueError("chave de configuracao invalida")
    setor = alvo or setor
    if chave.startswith("maquina:") and isinstance(valor, dict):
        n = int(chave.split(":", 1)[1])
        try:
            taxa = max(0.0, min(float(valor.get("metrosPorMin", 0)), 100000.0))
        except (TypeError, ValueError):
            taxa = 0.0
        banco.salvar_maquina(setor, n, str(valor.get("nome", "")).strip()[:40] or f"Máquina {n}", taxa)
    elif chave == "meta_pct":
        meta = float(valor)
        if 0 < meta <= 100:
            banco.salvar_meta_pct_dia(setor, round(meta, 1))
    elif chave == "turnos":
        turnos = normalizar_turnos(valor)
        if turnos:
            banco.salvar_turnos(setor, turnos)
    elif chave.startswith("extras:"):
        banco.salvar_extras(setor, normalizar_extras({chave.split(":", 1)[1]: valor}))
    elif chave in ("senha_leitura", "senha_edicao") and isinstance(valor, dict) and _hash_valido(valor.get("hash")):
        segredo = SEGREDO_SENHA_REMOTA if chave == "senha_leitura" else SEGREDO_SENHA_EDICAO
        banco.salvar_segredo(segredo, json.dumps({"hash": valor["hash"], "alterado_em": str(valor.get("alterado_em", ""))[:40]}))
    elif chave == "edicao_remota":
        ativa = bool(valor.get("ativa", True)) if isinstance(valor, dict) else bool(valor)
        banco.salvar_segredo(SEGREDO_EDICAO_REMOTA, json.dumps({"ativa": ativa}))
    elif chave == "setores":
        cadastro_setores.aplicar_lista(banco, valor)
    _tocar_config()


def _igual(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def resumo_item(chave, valor):
    chave = separar_chave(chave)[1] or chave
    try:
        if chave.startswith("maquina:"):
            return f"{valor['nome']} · {round(float(valor['metrosPorMin']) * 60, 1):g} m/h"
        if chave == "meta_pct":
            return f"{float(valor):g}%"
        if chave == "turnos":
            return ", ".join(f"{t['nome']} {t['inicio']}–{t['fim']}" for t in valor)
        if chave in ("senha_leitura", "senha_edicao"):
            return "alterada"
        if chave == "edicao_remota":
            return "ligada" if valor.get("ativa", True) else "desligada"
        if chave == "setores":
            return ", ".join(s["nome"] + ("" if s.get("ativo", True) else " (desativado)") for s in valor)
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return "alterado"


@_em_ordem
def registrar_mudancas(banco, antes, depois, origem, autor):
    """Marca a revisao dos itens que mudaram e registra a auditoria. No
    notebook o item fica pendente (base = revisao conhecida) ate a VPS
    confirmar; na VPS recebe a proxima revisao global na hora."""
    mudou = sorted(c for c in depois if not _igual(antes.get(c), depois.get(c)))
    agora = _agora_utc()
    for c in mudou:
        if origem == "nuvem":
            banco.marcar_rev(c, banco.max_rev() + 1, agora, "nuvem", autor, False)
        else:
            atual = banco.obter_rev(c)
            banco.marcar_rev(c, atual["rev"] if atual else 0, agora, "notebook", autor, True)
        banco.registrar_alteracao(agora, origem, autor, c, f"{nome_item(c)}: {resumo_item(c, depois[c])}")
    _tocar_config()
    return mudou


@_em_ordem
def alterar_setores(banco, acao, dados, origem, autor):
    """2.0: criar/editar/apagar um setor pelo painel (aqui ou na VPS), com
    revisao e auditoria do item global "setores" - assim a mudanca chega ao
    outro lado. ErroSetor (ValueError) se o pedido for invalido."""
    antes = itens_atuais(banco, SETOR_PADRAO)
    if acao == "criar":
        resultado = cadastro_setores.criar(banco, dados)
    elif acao == "editar":
        resultado = cadastro_setores.editar(banco, dados)
    elif acao == "apagar":
        resultado = cadastro_setores.apagar(banco, dados.get("setor"))
    else:
        raise cadastro_setores.ErroSetor("Ação inválida.")
    registrar_mudancas(banco, antes, itens_atuais(banco, SETOR_PADRAO), origem, autor)
    return resultado


def itens_de_corpo_legado(corpo):
    """Formato antigo (app 1.1.0) -> itens."""
    itens = {}
    maquinas = corpo.get("maquinas")
    for n, m in (maquinas.items() if isinstance(maquinas, dict) else []):
        if isinstance(m, dict) and str(n).isdigit():
            itens[f"maquina:{int(n)}"] = {"nome": m.get("nome", ""), "metrosPorMin": m.get("metrosPorMin", 0)}
    if corpo.get("metaPctDia") is not None:
        itens["meta_pct"] = corpo["metaPctDia"]
    turnos = normalizar_turnos(corpo.get("turnos"))
    if turnos:
        itens["turnos"] = turnos
    for k, texto in normalizar_extras(corpo.get("extras")).items():
        if k in EXTRAS_SINCRONIZADOS:
            itens[f"extras:{k}"] = json.loads(texto)
    acesso = corpo.get("acessoRemoto") if isinstance(corpo.get("acessoRemoto"), dict) else {}
    if _hash_valido(acesso.get("hash")):
        itens["senha_leitura"] = {"hash": acesso["hash"], "alterado_em": str(acesso.get("alteradoEm", ""))[:25]}
    return itens


# ---------------------------------------------------------------------
# VPS: o que chega do ESP32 e do notebook
# ---------------------------------------------------------------------
_trava_status = threading.Lock()


def _ler_status(dir_dados):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_STATUS_NUVEM), "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _atualizar_status(dir_dados, **campos):
    with _trava_status:
        status = _ler_status(dir_dados)
        status.update(campos)
        _gravar_json(os.path.join(dir_dados, ARQUIVO_STATUS_NUVEM), status)


def receber_do_esp(banco, dir_dados, setor, corpo, ip=""):
    """Grava o lote enviado pelo ESP32 (ciclos + estado ao vivo). Levanta
    ValueError se o corpo nao tiver o minimo (o ESP32 tenta de novo)."""
    dispositivo = str(corpo.get("dispositivo", "")).strip()[:64]
    if not dispositivo:
        raise ValueError("dispositivo ausente")
    linhas = [l for l in str(corpo.get("ciclos", "")).splitlines() if l.strip() and not l.startswith("id,")]
    if len(linhas) > MAX_CICLOS_POR_ENVIO:
        raise ValueError("lote grande demais")
    novos = gravar_linhas_ciclos(banco, setor, dispositivo, linhas, log=lambda *_: None)
    registrar_multi_seguro(banco, dispositivo, setor, corpo.get("firmware"), ip)  # 2.0: cadastro de dispositivos

    agora = datetime.now()
    for m in corpo.get("maquinas") or []:
        try:
            desde = agora - timedelta(seconds=max(0, int(m["segundos"])))
            banco.atualizar_estado_ao_vivo(setor, int(m["maquina"]), bool(m["ligado"]), desde.isoformat(timespec="seconds"))
        except (KeyError, TypeError, ValueError):
            continue

    def inteiro(chave):
        try:
            return int(corpo.get(chave) or 0)
        except (TypeError, ValueError):
            return 0

    campos = {
        "ultimo_contato": _agora_iso(),
        "dispositivo": dispositivo,
        "firmware": str(corpo.get("firmware", ""))[:16],
        "hora_esp": str(corpo.get("hora", ""))[:20],
        "hora_esp_valida": bool(corpo.get("hora_valida")),
        "ip_esp": str(ip)[:64],
        "pendentes_esp": max(0, inteiro("ultimo_id") - inteiro("lido_ate")),
    }
    if novos:
        campos.update({"ultima_extracao": _agora_iso(), "ciclos_ultima_extracao": novos})
    if inteiro("perdidos"):
        campos.update({"ciclos_perdidos": inteiro("perdidos"), "perdidos_em": _agora_iso()})
    _atualizar_status(dir_dados, **campos)
    return {"ok": True, "gravados": novos}


@_em_ordem
def receber_config(banco, dir_dados, corpo, setor_padrao):
    """VPS: POST /api/nuvem/config. "versao": 2 = sincronizacao nas duas
    maos; sem versao = app 1.1.0 (envia a configuracao inteira) - aplica so o
    que nunca foi editado pela VPS, para nao desfazer edicoes remotas."""
    if corpo.get("versao") == 2:
        return sincronizar_config(banco, dir_dados, corpo, setor_padrao)
    setor = str(corpo.get("setor", setor_padrao))[:40]
    antes = itens_atuais(banco, setor)
    for chave, valor in itens_de_corpo_legado(corpo).items():
        rev = banco.obter_rev(chave)
        if (rev and rev["origem"] == "nuvem") or _igual(antes.get(chave), valor):
            continue
        gravar_item(banco, setor, chave, valor)
        agora = _agora_utc()
        banco.marcar_rev(chave, banco.max_rev() + 1, agora, "notebook", "notebook (1.1.0)", False)
        banco.registrar_alteracao(agora, "notebook", "notebook (1.1.0)", chave, f"{nome_item(chave)}: {resumo_item(chave, valor)}")
    try:
        meta_h = float(corpo.get("metaHorasDia") or 0)
        if 0 < meta_h <= 24:
            banco.salvar_meta_horas_dia(setor, meta_h)  # campo antigo, sem versao
    except (TypeError, ValueError):
        pass
    _atualizar_status(dir_dados, config_recebida_em=_agora_iso())
    return {"ok": True}


def sincronizar_config(banco, dir_dados, corpo, setor_padrao):
    """VPS (hub): aplica os itens alterados no notebook - aceita se a base
    for a revisao atual ou, em conflito, se for o mais recente (UTC) - e
    devolve tudo o que mudou aqui desde a ultima revisao que o notebook conhece."""
    setor = str(corpo.get("setor", setor_padrao))[:40]
    try:
        rev_conhecida = int(corpo.get("rev_conhecida") or 0)
    except (TypeError, ValueError):
        rev_conhecida = 0
    itens = corpo.get("itens") if isinstance(corpo.get("itens"), dict) else {}
    aceitos, rejeitados = [], []
    for chave, info in _ordem_sync(itens):
        if not chave_item_valida(chave) or not isinstance(info, dict):
            continue
        atual = banco.obter_rev(chave)
        editado = str(info.get("editado_em") or "")[:40] or _agora_utc()
        try:
            base = int(info.get("base_rev") or 0)
        except (TypeError, ValueError):
            base = -1
        if atual is None or base == atual["rev"] or editado > atual["editado_em"]:
            valor_antes = ler_item(banco, setor, chave)
            try:
                gravar_item(banco, setor, chave, info.get("valor"))
            except (TypeError, ValueError, KeyError):
                continue
            banco.marcar_rev(chave, banco.max_rev() + 1, editado, "notebook", "notebook", False)
            valor_depois = ler_item(banco, setor, chave)
            if not _igual(valor_antes, valor_depois):
                # auditoria com a hora real (a da semente e "muito antiga" de proposito)
                quando = editado if editado != SEMENTE_EM else _agora_utc()
                banco.registrar_alteracao(quando, "notebook", "notebook", chave, f"{nome_item(chave)}: {resumo_item(chave, valor_depois)}")
            aceitos.append(chave)
        else:
            rejeitados.append({"chave": chave, "venceu_em": atual["editado_em"],
                               "venceu_origem": atual["origem"], "venceu_autor": atual["autor"]})
    atuais = itens_atuais(banco, setor)
    revs = banco.listar_revs()
    novos = {c: {"valor": atuais[c], "rev": r["rev"], "editado_em": r["editado_em"], "origem": r["origem"], "autor": r["autor"]}
             for c, r in revs.items() if r["rev"] > rev_conhecida and c in atuais}
    _atualizar_status(dir_dados, config_recebida_em=_agora_iso())
    return {"ok": True, "versao": 2, "rev_atual": banco.max_rev(), "itens": novos,
            "aceitos": aceitos, "rejeitados": rejeitados, "auditoria": banco.ultimas_alteracoes(50)}


def _idade_s(iso):
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def aplicar_ao_vivo_notebook(banco, dir_dados, setor, ao_vivo):
    """VPS: estado ao vivo que o notebook leu do ESP32 pela rede local.
    So vale se for mais novo que o ultimo envio direto do ESP32 (que continua
    a fonte principal). Devolve True se aplicou."""
    if not isinstance(ao_vivo, dict):
        return False
    try:
        contato_s = max(0.0, float(ao_vivo.get("contato_s")))
    except (TypeError, ValueError):
        return False
    agora = datetime.now()
    campos = {"notebook_visto_em": _agora_iso()}
    aplicou = False
    if contato_s <= AO_VIVO_MAX_IDADE_S:
        # o ESP32 multi (firmware 3.x) so envia direto o setor legado; nos
        # outros setores o notebook e a unica fonte do estado ao vivo
        idade_esp = _idade_s(_ler_status(dir_dados).get("ultimo_contato", "")) if setor == SETOR_LEGADO else None
        if idade_esp is None or idade_esp > contato_s + 2:
            for m in ao_vivo.get("maquinas") or []:
                try:
                    desde = agora - timedelta(seconds=max(0, int(m["segundos"])))
                    banco.atualizar_estado_ao_vivo(setor, int(m["maquina"]), bool(m["ligado"]), desde.isoformat(timespec="seconds"))
                    aplicou = True
                except (KeyError, TypeError, ValueError):
                    continue
        campos["ultimo_contato_notebook"] = (agora - timedelta(seconds=contato_s)).isoformat(timespec="seconds")
    _atualizar_status(dir_dados, **campos)
    return aplicou


def receber_historico(banco, dir_dados, corpo, setor_padrao):
    """VPS: grava um lote do historico enviado pelo notebook. Lote vazio so
    devolve o total (o notebook usa para conferir se falta algo)."""
    setor = str(corpo.get("setor") or setor_padrao)[:40]
    if not cadastro_setores.slug_valido(setor):
        raise ValueError("setor invalido")
    linhas = corpo.get("ciclos") or []
    if not isinstance(linhas, list) or len(linhas) > MAX_HISTORICO_POR_ENVIO:
        raise ValueError("lote invalido ou grande demais")
    gravados = 0
    for item in linhas:
        try:
            id_local, maquina, ciclo, inicio, fim, duracao_s, obs, gravado_em, dispositivo, origem_id = item
            if not dispositivo or origem_id is None:  # lido pela USB: o id local do notebook identifica
                dispositivo, origem_id = DISPOSITIVO_SERIAL, id_local
            if banco.gravar_ciclo_remoto(
                setor, str(dispositivo)[:64], int(origem_id), int(maquina), int(ciclo),
                str(inicio)[:25], str(fim)[:25], float(duracao_s), str(obs or "")[:80],
                str(gravado_em)[:19] if gravado_em else None,
            ):
                gravados += 1
        except (TypeError, ValueError):
            continue
    total = banco.total_ciclos(setor)
    if linhas:
        _atualizar_status(dir_dados, historico_recebido_em=_agora_iso(), ciclos_total=total)
    resposta = {"ok": True, "gravados": gravados, "total": total}
    if "ao_vivo" in corpo:  # 1.7.0: notebook como segunda fonte
        resposta["ao_vivo_aplicado"] = aplicar_ao_vivo_notebook(banco, dir_dados, setor, corpo.get("ao_vivo"))
        idade_esp = _idade_s(_ler_status(dir_dados).get("ultimo_contato", ""))
        resposta["esp_direto_s"] = None if idade_esp is None else int(idade_esp)
    return resposta


def status_nuvem(dir_dados):
    """GET /sincronizacao na VPS: o ESP32 esta enviando? quando a
    configuracao chegou do notebook?"""
    s = _ler_status(dir_dados)
    idade_esp = _idade_s(s.get("ultimo_contato", ""))
    idade_nb = _idade_s(s.get("ultimo_contato_notebook", ""))
    if idade_esp is not None and idade_esp <= ESP_SEM_ENVIAR_S:
        fonte = "esp"
    elif idade_nb is not None and idade_nb <= ESP_SEM_ENVIAR_S:
        fonte = "notebook"  # o ESP32 nao envia direto, mas o notebook repassa o que le dele
    else:
        fonte = ""
    idades = [i for i in (idade_esp, idade_nb) if i is not None]
    idade = min(idades) if idades else None
    enviando = bool(fonte)
    estado = "conectado" if enviando else ("sem_resposta" if idade is not None else "procurando")
    ultima = s.get("ultimo_contato", "") if idade == idade_esp else s.get("ultimo_contato_notebook", "")
    return {**s, "modo": "nuvem", "rodando": enviando, "estado": estado, "fonte": fonte,
            "ultima_sincronizacao": ultima, "segundos_sem_envio": idade,
            "segundos_sem_envio_esp": idade_esp, "segundos_sem_envio_notebook": idade_nb}


# ---------------------------------------------------------------------
# Senha unica do acesso remoto (definida no notebook, conferida na VPS)
# ---------------------------------------------------------------------
ITERACOES_SENHA = 200_000


def hash_senha(senha, iteracoes=ITERACOES_SENHA):
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes)
    return f"pbkdf2_sha256${iteracoes}${base64.b64encode(sal).decode()}${base64.b64encode(dk).decode()}"


def verificar_senha(senha, guardado):
    try:
        algoritmo, iteracoes, sal, dk = str(guardado).split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), base64.b64decode(sal), int(iteracoes))
        return hmac.compare_digest(calculado, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def _hash_valido(texto):
    partes = str(texto or "").split("$")
    return len(partes) == 4 and partes[0] == "pbkdf2_sha256" and partes[1].isdigit()


def dados_senha_remota(banco):
    """{"hash", "alterado_em"} ou {} (senha ainda nao definida)."""
    try:
        dados = json.loads(banco.obter_segredo(SEGREDO_SENHA_REMOTA) or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) and _hash_valido(dados.get("hash")) else {}


def dados_senha_edicao(banco):
    return _dados_hash(banco, SEGREDO_SENHA_EDICAO)


def edicao_remota_ativa(banco):
    """Interruptor do notebook (padrao: ligada - vale se houver senha de edicao)."""
    return bool(_segredo_json(banco, SEGREDO_EDICAO_REMOTA).get("ativa", True))


def status_senha_remota(banco):
    """Para os paineis - nunca inclui hash."""
    leitura, edicao = dados_senha_remota(banco), dados_senha_edicao(banco)
    return {"definida": bool(leitura), "alteradaEm": leitura.get("alterado_em", ""),
            "edicaoDefinida": bool(edicao), "edicaoAlteradaEm": edicao.get("alterado_em", ""),
            "edicaoRemotaAtiva": edicao_remota_ativa(banco)}


def guardar_senha_texto(banco, papel, senha):
    """1.7.2 - SO NO NOTEBOOK: guarda o texto da senha de acesso remoto
    ("leitura" ou "edicao") para ser consultada depois (esquecimento, Claude
    Code). So guarda se a senha confere com o hash em vigor; junto vai o hash,
    para saber se ela foi trocada depois (pela internet). Nunca vai para a VPS
    (nao esta em itens_atuais) e a VPS nunca chama isto. Devolve True/False."""
    dados = dados_senha_edicao(banco) if papel == "edicao" else dados_senha_remota(banco)
    senha = str(senha or "")
    if not dados or not verificar_senha(senha, dados["hash"]):
        return False
    guardadas = _segredo_json(banco, SEGREDO_SENHAS_TEXTO)
    guardadas[papel] = {"senha": senha, "hash": dados["hash"], "guardada_em": _agora_utc()}
    banco.salvar_segredo(SEGREDO_SENHAS_TEXTO, json.dumps(guardadas, ensure_ascii=False))
    return True


def senhas_guardadas(banco):
    """{papel: {"definida", "conhecida", "senha", "alteradaEm"}} - "senha" so
    quando a guardada ainda e a que vale (o hash nao mudou)."""
    guardadas = _segredo_json(banco, SEGREDO_SENHAS_TEXTO)
    saida = {}
    for papel, dados in (("leitura", dados_senha_remota(banco)), ("edicao", dados_senha_edicao(banco))):
        g = guardadas.get(papel) if isinstance(guardadas.get(papel), dict) else {}
        vale = bool(dados) and g.get("hash") == dados.get("hash") and bool(g.get("senha"))
        saida[papel] = {"definida": bool(dados), "conhecida": vale, "senha": g["senha"] if vale else "",
                        "alteradaEm": dados.get("alterado_em", "")}
    return saida


@_em_ordem
def definir_senha(banco, papel, senha, origem="notebook", autor="notebook", setor=SETOR_PADRAO):
    """Grava o hash da senha de "leitura" (visualizacao) ou "edicao".
    ValueError se for invalida ou igual a do outro papel."""
    senha = str(senha or "")
    minimo = SENHA_EDICAO_MIN if papel == "edicao" else SENHA_MIN
    if not minimo <= len(senha) <= SENHA_MAX:
        raise ValueError(f"A senha de {'edição' if papel == 'edicao' else 'visualização'} precisa ter de {minimo} a {SENHA_MAX} caracteres.")
    outra = dados_senha_remota(banco) if papel == "edicao" else dados_senha_edicao(banco)
    if outra and verificar_senha(senha, outra["hash"]):
        raise ValueError("As senhas de visualização e de edição precisam ser diferentes.")
    antes = itens_atuais(banco, setor)
    banco.salvar_segredo(SEGREDO_SENHA_EDICAO if papel == "edicao" else SEGREDO_SENHA_REMOTA,
                         json.dumps({"hash": hash_senha(senha), "alterado_em": _agora_utc()}))
    registrar_mudancas(banco, antes, itens_atuais(banco, setor), origem, autor)


def definir_senha_remota(banco, senha, origem="notebook", autor="notebook"):
    """Senha de visualizacao (compatibilidade com a 1.1.0)."""
    definir_senha(banco, "leitura", senha, origem, autor)


@_em_ordem
def definir_edicao_remota(banco, ativa, autor="notebook", setor=SETOR_PADRAO):
    """Notebook (mestre): liga/desliga a edicao pela VPS."""
    antes = itens_atuais(banco, setor)
    banco.salvar_segredo(SEGREDO_EDICAO_REMOTA, json.dumps({"ativa": bool(ativa)}))
    registrar_mudancas(banco, antes, itens_atuais(banco, setor), "notebook", autor)


class LimiteTentativas:
    """10 senhas ou chaves erradas em 10 min bloqueiam aquele IP."""

    MAX_FALHAS, JANELA_S = 10, 600

    def __init__(self):
        self._falhas = {}
        self._trava = threading.Lock()

    def bloqueado(self, ip):
        agora = time.monotonic()
        with self._trava:
            recentes = [t for t in self._falhas.get(ip, []) if agora - t < self.JANELA_S]
            self._falhas[ip] = recentes
            return len(recentes) >= self.MAX_FALHAS

    def falhou(self, ip):
        agora = time.monotonic()
        with self._trava:
            self._falhas.setdefault(ip, []).append(agora)
            if len(self._falhas) > 5000:  # robos de varredura: esquece os IPs sem erro recente
                self._falhas = {k: v for k, v in self._falhas.items() if v and agora - v[-1] < self.JANELA_S}


class Sessoes:
    """Cookie de sessao assinado (HMAC) - nao guarda nada em memoria, vale
    depois de reiniciar o servidor e deixa de valer sozinho quando a senha
    muda (a assinatura inclui o hash da senha atual)."""

    def __init__(self, dir_dados):
        caminho = os.path.join(dir_dados, ARQUIVO_CHAVE_SESSAO)
        try:
            with open(caminho, "r", encoding="utf-8") as arquivo:
                self._segredo = bytes.fromhex(arquivo.read().strip())
        except (OSError, ValueError):
            self._segredo = secrets.token_bytes(32)
            with open(caminho, "w", encoding="utf-8") as arquivo:
                arquivo.write(self._segredo.hex())
            try:
                os.chmod(caminho, 0o600)
            except OSError:
                pass

    def _assinar(self, expira, papel, hash_senha_atual):
        return hmac.new(self._segredo, f"{expira}|{papel}|{hash_senha_atual}".encode("utf-8"), hashlib.sha256).hexdigest()

    def criar(self, hash_senha_atual, papel="leitura"):
        expira = int(time.time()) + DIAS_SESSAO * 86400
        return f"{expira}.{papel}.{self._assinar(expira, papel, hash_senha_atual)}"

    def papel(self, token, hashes):
        """"leitura"/"edicao" se o token for valido para a senha ATUAL daquele
        papel (hashes = {papel: hash ou None}), senao None."""
        try:
            expira, papel, assinatura = str(token or "").split(".", 2)
            if int(expira) < time.time() or not hashes.get(papel):
                return None
        except ValueError:
            return None
        return papel if hmac.compare_digest(assinatura, self._assinar(expira, papel, hashes[papel])) else None


def pagina_login(erro="", senha_definida=True, app_remoto=None):
    """Tela de login da VPS: so o campo de senha (+ link do programa para
    Windows, mostrado so em computador com Windows e fora do proprio programa)."""
    from html import escape

    app = ""
    if app_remoto and app_remoto.get("disponivel"):
        mb = max(1, round(int(app_remoto.get("tamanho", 0)) / 1_048_576))
        icone = (f'<img src="{escape(app_remoto["icone"])}" alt="">' if app_remoto.get("icone") else
                 '<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="12" rx="2" '
                 'stroke="currentColor" stroke-width="1.8"/><path d="M8 20h8M12 16v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>')
        app = (f'<a class="app" id="app-remoto" href="{escape(app_remoto["url"])}" '
               f'download="{escape(app_remoto.get("nome") or "")}" hidden>'
               f'<span class="ico">{icone}</span>'
               f'<span><b>Aplicativo para Windows</b><small>Abre direto no painel, sem navegador · {mb} MB</small></span>'
               '<span class="seta">↓</span></a>'
               '<script>(function(){var ua=navigator.userAgent;'
               'if(/Windows/.test(ua)&&!/Mobile|Android/.test(ua)&&!/PainelSantexRemoto/.test(ua)&&!window.pywebview)'
               'document.getElementById("app-remoto").hidden=false;})();</script>')

    aviso = ""
    if not senha_definida:
        aviso = ('<p class="aviso">A senha do acesso remoto ainda não foi definida. No computador do painel, '
                 'na empresa: <b>⚙ Configurações → Acesso remoto</b>.</p>')
    elif erro:
        aviso = f'<p class="erro">{escape(erro)}</p>'
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Produção · acesso remoto</title>
<link rel="icon" href="/assets/icone-empresa.png">
<style>
:root{{color-scheme:light dark;--fundo:#f3f4f6;--cartao:#fff;--texto:#111827;--suave:#6b7280;--borda:#d1d5db;--acento:#c2410c;--erro:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--fundo:#0f172a;--cartao:#1e293b;--texto:#f1f5f9;--suave:#94a3b8;--borda:#334155;--acento:#fb923c;--erro:#f87171}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--fundo);color:var(--texto);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}}
main{{width:100%;max-width:380px;background:var(--cartao);border:1px solid var(--borda);border-radius:14px;padding:28px 24px;box-shadow:0 10px 30px rgba(0,0,0,.08)}}
img{{display:block;height:44px;margin:0 auto 14px;background:#fff;border-radius:8px;padding:4px 8px}}
h1{{font-size:19px;margin:0 0 4px;text-align:center}}.sub{{color:var(--suave);font-size:14px;text-align:center;margin:0 0 20px}}
label{{display:block;font-size:14px;font-weight:600;margin-bottom:6px}}
input{{width:100%;font:inherit;padding:11px 12px;border:1px solid var(--borda);border-radius:9px;background:transparent;color:var(--texto)}}
input:focus{{outline:2px solid var(--acento);outline-offset:1px}}
button{{width:100%;margin-top:14px;font:inherit;font-weight:600;padding:11px;border:0;border-radius:9px;background:var(--acento);color:#fff;cursor:pointer}}
.erro{{color:var(--erro);font-size:14px;margin:0 0 12px}}.aviso{{font-size:14px;margin:0 0 12px;color:var(--suave)}}
.app{{display:flex;align-items:center;gap:12px;margin-top:20px;padding:12px 14px;border:1px solid var(--borda);border-radius:11px;color:var(--texto);text-decoration:none;transition:border-color .15s,background .15s}}
.app[hidden]{{display:none}}.app:hover{{border-color:var(--acento);background:color-mix(in srgb,var(--acento) 6%,transparent)}}
.app .ico{{flex:none;width:40px;height:40px;border-radius:10px;display:grid;place-items:center;color:var(--acento);background:color-mix(in srgb,var(--acento) 12%,transparent)}}
.app .ico img{{width:40px;height:40px;margin:0;padding:0;background:none;border-radius:10px}}
.app b{{display:block;font-size:14px}}.app small{{display:block;font-size:12.5px;color:var(--suave)}}.app .seta{{margin-left:auto;color:var(--acento);font-weight:700}}
</style></head><body><main>
<img src="/assets/logo.png" alt="">
<h1>Painel de Produção</h1><p class="sub">Acesso remoto</p>
{aviso}
<form method="post" action="/login">
<label for="senha">Senha de acesso</label>
<input id="senha" name="senha" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrar</button>
</form>{app}</main></body></html>"""


# ---------------------------------------------------------------------
# Notebook: envia a configuracao para a VPS
# ---------------------------------------------------------------------
def config_nuvem_app(dir_dados):
    """{"url", "chave"} da VPS para o notebook: dados/nuvem.json tem
    prioridade; senao, o que gerar_segredos.py embutiu (NUVEM_URL e
    NUVEM_CHAVE do .env, em app/segredos_app.json). url vazia = desligado."""
    cfg = {}
    try:
        with open(ARQUIVO_CHAVE_APP, "r", encoding="utf-8") as arquivo:
            app = json.load(arquivo)
        cfg = {"url": app.get("nuvem_url", ""), "chave": app.get("nuvem_chave", "")}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(dir_dados, ARQUIVO_CONFIG_NUVEM), "r", encoding="utf-8") as arquivo:
            local = json.load(arquivo)
        if isinstance(local, dict):
            cfg.update({k: local[k] for k in ("url", "chave") if local.get(k)})
    except (OSError, ValueError):
        pass
    return {"url": str(cfg.get("url") or "").strip().rstrip("/"), "chave": str(cfg.get("chave") or "").strip()}


class EnviadorConfig:
    """Thread do notebook (a cada 30 s): manda para a VPS a configuracao
    quando ela muda (e a cada 30 min) e o HISTORICO de ciclos que ela ainda
    nao tem - primeiro tudo, em lotes, depois so os novos. De hora em hora
    confere os totais: se a VPS tiver menos ciclos (reinstalada, banco
    perdido), reenvia tudo - sem duplicar. Sem internet, so tenta de novo
    depois - nunca atrapalha o painel local."""

    VERIFICAR_S = 15
    AO_VIVO_RAPIDO_S = 5  # ESP32 sem enviar direto para a VPS: o notebook repassa a cada 5 s
    REENVIAR_S = 1800
    CONFERIR_TOTAIS_S = 3600
    LOTES_POR_RODADA = 20  # ate 10.000 ciclos por rodada (o resto na proxima)
    TIMEOUT_S = 20

    def __init__(self, banco, dir_dados, setor):
        self.banco, self.dir_dados, self.setor = banco, dir_dados, setor
        self.parar_evento = threading.Event()
        self._status = {"ativo": False, "url": "", "ultimo_envio": "", "erro": "",
                        "historico": {"ate": 0, "pendentes": None, "total_nuvem": None, "ultimo_envio": "", "erro": ""}}
        self._ultimo_hash, self._ultimo_ok = None, 0.0
        self._ultima_conferencia = 0.0
        self._proximo_teste_reenvio = 0.0
        self._trava = threading.Lock()
        self._status["ao_vivo"] = {"ultimo_envio": "", "esp_direto_s": None, "repassando": False, "erro": ""}

    def status(self):
        with self._trava:
            return {**self._status, "historico": dict(self._status["historico"]), "ao_vivo": dict(self._status["ao_vivo"])}

    # -- estado ao vivo -> VPS (1.7.0: notebook como segunda fonte) ---------
    def _setores_envio(self):
        """Setores do cadastro (2.0) - o legado sempre primeiro."""
        slugs = [s["setor"] for s in self.banco.listar_setores()]
        return sorted(slugs, key=lambda s: s != self.setor)

    def corpo_ao_vivo(self, setor=None):
        """{"contato_s", "maquinas": [{maquina, ligado, segundos}]} com o que o
        notebook leu do ESP32 (ou None se nao tiver leitura recente)."""
        estado = self.banco.obter_estado_ao_vivo(setor or self.setor)
        agora = datetime.now()
        maquinas, idades = [], []
        for num, m in estado.items():
            sem_sinal = m.get("segundosSemSinal")
            if sem_sinal is None or sem_sinal > AO_VIVO_MAX_IDADE_S:
                continue
            try:
                segundos = max(0, int((agora - datetime.fromisoformat(m["desde"])).total_seconds()))
            except (TypeError, ValueError):
                continue
            maquinas.append({"maquina": int(num), "ligado": bool(m["ligado"]), "segundos": segundos})
            idades.append(sem_sinal)
        if not maquinas:
            return None
        return {"contato_s": max(0, min(idades)), "maquinas": maquinas}

    def enviar_ao_vivo(self):
        """Manda o estado ao vivo de cada setor com leitura recente. Devolve
        True se o laco deve rodar a cada 5 s: a VPS disse que o ESP32 do setor
        legado esta sem enviar direto, ou ha outro setor com estado ao vivo (2.0:
        nesses o notebook e a unica fonte da VPS)."""
        cfg = config_nuvem_app(self.dir_dados)
        if not cfg["url"]:
            return False
        rapido = False
        for setor in self._setores_envio():
            corpo = self.corpo_ao_vivo(setor)
            if corpo is None:
                continue
            try:
                req = urllib.request.Request(
                    cfg["url"] + "/api/nuvem/historico", method="POST",
                    data=json.dumps({"setor": setor, "ciclos": [], "ao_vivo": corpo}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Chave-Nuvem": cfg["chave"]})
                with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
                    r = json.loads(resp.read().decode("utf-8"))
            except (OSError, ValueError, HTTPError) as erro:
                with self._trava:
                    self._status["ao_vivo"].update(erro=f"{type(erro).__name__}: {erro}")
                return rapido
            if setor != self.setor:
                rapido = True
                continue
            esp_s = r.get("esp_direto_s") if "esp_direto_s" in r else 0  # VPS antiga: nao sabe -> ritmo normal
            rapido = rapido or esp_s is None or esp_s > ESP_SEM_ENVIAR_S
            with self._trava:
                self._status["ao_vivo"].update(ultimo_envio=_agora_iso(), esp_direto_s=esp_s,
                                               repassando=bool(r.get("ao_vivo_aplicado")), erro="")
        return rapido

    def _atualizar_historico(self, **campos):
        with self._trava:
            self._status["historico"].update(campos)

    # -- historico de ciclos -> VPS ---------------------------------------
    def _dados_cursor(self, url):
        try:
            dados = json.loads(self.banco.obter_segredo(CURSOR_HISTORICO) or "{}")
        except ValueError:
            dados = {}
        if not isinstance(dados, dict) or dados.get("url") != url:
            return {"url": url, "ate": 0, "setores": {}}
        return dados

    def _cursor(self, url, setor=None):
        """Ate qual id local a VPS confirmou, por setor (por URL: trocar a VPS
        recomeca). O setor legado fica em "ate" (formato da 1.x); os outros
        (2.0) em "setores"."""
        dados = self._dados_cursor(url)
        if (setor or self.setor) == self.setor:
            return int(dados.get("ate", 0))
        return int((dados.get("setores") or {}).get(setor, 0))

    def _salvar_cursor(self, url, ate, setor=None):
        dados = self._dados_cursor(url)
        if (setor or self.setor) == self.setor:
            dados["ate"] = int(ate)
        else:
            dados.setdefault("setores", {})[setor] = int(ate)
        self.banco.salvar_segredo(CURSOR_HISTORICO, json.dumps(dados))

    def _vps_completa_hora(self, cfg):
        """True se a VPS responde ao ping com versao >= 1.7.1 (a que completa
        a hora dos ciclos SEM_HORA). Falha de rede = False (tenta depois)."""
        try:
            req = urllib.request.Request(cfg["url"] + "/api/nuvem/ping", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "X-Chave-Nuvem": cfg["chave"]})
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
                versao = str(json.loads(resp.read().decode("utf-8")).get("versao", ""))
            numeros = re.match(r"\d+(?:\.\d+)*", versao)  # 2.0: aceita sufixo ("2.0.0-alfa.1")
            return bool(numeros) and tuple(int(p) for p in numeros.group(0).split(".")[:3]) >= (1, 7, 1)
        except (OSError, ValueError, HTTPError):
            return False

    def _post_historico(self, cfg, linhas, setor=None):
        corpo = json.dumps({"setor": setor or self.setor, "ciclos": linhas}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(cfg["url"] + "/api/nuvem/historico", data=corpo, method="POST",
                                     headers={"Content-Type": "application/json", "X-Chave-Nuvem": cfg["chave"]})
        with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def enviar_historico(self, conferir=None):
        """Envia o que falta do historico. Devolve quantos ciclos foram
        gravados na VPS nesta rodada (None = nada a fazer / falhou)."""
        cfg = config_nuvem_app(self.dir_dados)
        if not cfg["url"]:
            return None
        url = cfg["url"]
        try:
            ate = self._cursor(url)
            if self.banco.obter_segredo(REENVIO_HORA) != url and time.monotonic() >= self._proximo_teste_reenvio:
                # 1.7.1: uma vez por VPS, reenvia tudo - a VPS completa a hora
                # dos ciclos que chegaram do ESP32 sem hora (SEM_HORA). 1.7.2:
                # so quando a VPS ja sabe completar (1.7.1 ou mais nova) - VPS
                # antiga aceitaria o reenvio sem corrigir nada; tenta a cada 10 min
                if self._vps_completa_hora(cfg):
                    if ate > 0:
                        ate = 0
                        self._salvar_cursor(url, 0)
                    self.banco.salvar_segredo(REENVIO_HORA, url)
                else:
                    self._proximo_teste_reenvio = time.monotonic() + 600
            if conferir is None:
                conferir = time.monotonic() - self._ultima_conferencia > self.CONFERIR_TOTAIS_S
            gravados, pendentes = 0, 0
            for setor in self._setores_envio():
                g, ate_setor = self._enviar_historico_setor(cfg, url, setor, ate if setor == self.setor else None, conferir)
                gravados += g
                pendentes += self.banco.total_ciclos(setor, ate_setor)
                if setor == self.setor:
                    ate = ate_setor
                if self.parar_evento.is_set():
                    break
            if conferir:
                self._ultima_conferencia = time.monotonic()
            self._atualizar_historico(ate=ate, pendentes=pendentes, erro="")
            return gravados
        except HTTPError as erro:
            if erro.code == 404:
                motivo = "a VPS ainda não recebe o histórico — atualize o servidor da VPS (pacote mais novo)"
            elif erro.code == 403:
                motivo = "chave recusada pela VPS (NUVEM_CHAVE diferente)"
            else:
                motivo = f"HTTP {erro.code}"
        except (OSError, ValueError, KeyError) as erro:
            motivo = f"sem conexão com a VPS ({erro})"
        self._atualizar_historico(erro=motivo, pendentes=sum(
            self.banco.total_ciclos(st, self._cursor(url, st)) for st in self._setores_envio()))
        return None

    def _enviar_historico_setor(self, cfg, url, setor, ate=None, conferir=False):
        """Envia o que falta do historico de um setor. Devolve (ciclos
        gravados na VPS, ate qual id local ela confirmou)."""
        if ate is None:
            ate = self._cursor(url, setor)
        if conferir and ate > 0:
            # a VPS ainda tem tudo o que ja foi enviado? (lote vazio = so o total)
            total_nuvem = self._post_historico(cfg, [], setor)["total"]
            if setor == self.setor:
                self._atualizar_historico(total_nuvem=total_nuvem)
            if total_nuvem < self.banco.total_ciclos(setor) - self.banco.total_ciclos(setor, ate):
                ate = 0  # faltam ciclos que ja tinham ido: reenvia tudo (a VPS nao duplica)
                self._salvar_cursor(url, 0, setor)
        gravados = 0
        for _ in range(self.LOTES_POR_RODADA):
            lote = self.banco.ciclos_para_nuvem(setor, ate, MAX_HISTORICO_POR_ENVIO)
            if not lote:
                break
            linhas = [[c["id"], c["maquina"], c["ciclo"], c["inicio_ms"], c["fim_ms"], c["duracao_s"],
                       c["obs"], c["gravado_em"], c["dispositivo"], c["origem_id"]] for c in lote]
            resposta = self._post_historico(cfg, linhas, setor)
            gravados += int(resposta.get("gravados", 0))
            ate = lote[-1]["id"]
            self._salvar_cursor(url, ate, setor)
            if setor == self.setor:
                self._atualizar_historico(total_nuvem=resposta.get("total"), ultimo_envio=_agora_iso())
            else:
                self._atualizar_historico(ultimo_envio=_agora_iso())
            if self.parar_evento.is_set():
                break
        return gravados, ate

    def _atualizar(self, **campos):
        with self._trava:
            self._status.update(campos)

    # -- configuracao nas duas maos (1.2.0) ---------------------------------
    def _rev_conhecida(self, url):
        dados = _segredo_json(self.banco, SEGREDO_SYNC_CONFIG)
        return int(dados.get("rev", 0)) if dados.get("url") == url else 0

    def _avisar(self, texto):
        avisos = _segredo_json(self.banco, SEGREDO_AVISOS_SYNC).get("lista", [])
        avisos = ([{"quando": _agora_iso(), "texto": texto}] + avisos)[:20]
        self.banco.salvar_segredo(SEGREDO_AVISOS_SYNC, json.dumps({"lista": avisos}, ensure_ascii=False))

    def enviar_agora(self):
        """Uma rodada da sincronizacao: manda os itens alterados aqui e aplica
        os alterados na VPS. Devolve True se a troca aconteceu."""
        cfg = config_nuvem_app(self.dir_dados)
        self._atualizar(ativo=bool(cfg["url"]), url=cfg["url"])
        if not cfg["url"]:
            return False
        url = cfg["url"]
        atuais = itens_atuais(self.banco, self.setor)
        if self._rev_conhecida(url) == 0:
            # primeira troca com esta VPS (ou ela foi reinstalada/restaurada): a
            # configuracao daqui e a semente, cada item com a data da sua ultima
            # alteracao conhecida (sem data = muito antiga). VPS vazia aceita
            # tudo; VPS restaurada de backup fica com o que for mais recente.
            revs = self.banco.listar_revs()
            for chave in atuais:
                r = revs.get(chave)
                if not (r and r["pendente"]):
                    self.banco.marcar_rev(chave, 0, (r or {}).get("editado_em") or SEMENTE_EM,
                                          (r or {}).get("origem") or "notebook", (r or {}).get("autor") or "notebook", True)
        enviados = {}
        for p in self.banco.pendentes():
            if p["chave"] in atuais:
                enviados[p["chave"]] = {"valor": atuais[p["chave"]], "base_rev": p["rev"], "editado_em": p["editado_em"]}
        corpo = {"versao": 2, "setor": self.setor, "rev_conhecida": self._rev_conhecida(url), "itens": enviados}
        req = urllib.request.Request(url + "/api/nuvem/config", method="POST",
                                     data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Chave-Nuvem": cfg["chave"]})
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
                resposta = json.loads(resp.read().decode("utf-8"))
        except HTTPError as erro:
            self._atualizar(erro="chave recusada pela VPS (NUVEM_CHAVE diferente)" if erro.code == 403 else f"HTTP {erro.code}")
            return False
        except (OSError, ValueError) as erro:
            self._atualizar(erro=f"sem conexão com a VPS ({erro})")
            return False
        if resposta.get("versao") != 2:  # VPS ainda na 1.1.0: so o envio antigo funciona
            return self._enviar_legado(cfg)
        self._aplicar_resposta(url, enviados, resposta)
        if int(resposta.get("rev_atual") or 0) < corpo["rev_conhecida"]:
            # a VPS "voltou no tempo" (reinstalada ou restaurada de backup):
            # na proxima rodada reenvia toda a configuracao como semente
            self.banco.salvar_segredo(SEGREDO_SYNC_CONFIG, json.dumps({"url": url, "rev": 0}))
        self._atualizar(ultimo_envio=_agora_iso(), erro="", modo="duas-maos")
        return True

    @_em_ordem
    def _aplicar_resposta(self, url, enviados, resposta):
        itens = resposta.get("itens") or {}
        aceitos = set(resposta.get("aceitos") or [])
        rejeitados = {r["chave"]: r for r in (resposta.get("rejeitados") or []) if isinstance(r, dict)}
        for chave in aceitos:  # confirmado pela VPS (se nao mudou de novo aqui durante o envio)
            r = itens.get(chave)
            if not r:
                continue
            if _igual(ler_item(self.banco, self.setor, chave), enviados.get(chave, {}).get("valor")):
                if chave == "setores" and r.get("valor") is not None and not _igual(r["valor"], enviados[chave]["valor"]):
                    # a VPS aceitou, mas manteve um setor com dados que faltava na
                    # lista enviada: junta aqui tambem (os dois lados ficam iguais)
                    gravar_item(self.banco, self.setor, chave, r["valor"])
                    if self._setores_divergem(r["valor"], r["rev"]):
                        continue
                self.banco.marcar_rev(chave, r["rev"], r["editado_em"], "notebook", "notebook", False)
            else:  # mudou de novo aqui: continua pendente, agora sobre a revisao nova
                local = self.banco.obter_rev(chave) or {}
                self.banco.marcar_rev(chave, r["rev"], local.get("editado_em", _agora_utc()), "notebook", "notebook", True)
        for chave, r in _ordem_sync(itens):
            if chave in aceitos or not chave_item_valida(chave) or r.get("valor") is None:
                continue
            local = self.banco.obter_rev(chave)
            if local and local["pendente"] and chave not in rejeitados:
                continue  # alterado aqui de novo: decide na proxima rodada
            if not _igual(ler_item(self.banco, self.setor, chave), r["valor"]):
                gravar_item(self.banco, self.setor, chave, r["valor"])
                quem = "nuvem" if r.get("origem") == "nuvem" else r.get("origem", "")
                quando = r.get("editado_em", "") if r.get("editado_em") != SEMENTE_EM else _agora_utc()
                self.banco.registrar_alteracao(quando, quem, r.get("autor", ""), chave,
                                               f"{nome_item(chave)}: {resumo_item(chave, r['valor'])} (recebido da nuvem)")
                if chave in rejeitados and (local or {}).get("editado_em") != SEMENTE_EM:
                    self._avisar(f"Sua alteração em {nome_item(chave)} foi substituída por uma mais recente "
                                 f"({r.get('autor') or r.get('origem')}).")
                if chave == "setores" and self._setores_divergem(r["valor"], r["rev"]):
                    continue
            self.banco.marcar_rev(chave, r["rev"], r["editado_em"], r.get("origem", ""), r.get("autor", ""), False)

    def _setores_divergem(self, recebido, rev):
        """Depois de aplicar o cadastro de setores vindo da VPS: se aqui ficou
        diferente (um setor com dados nunca some, mesmo fora da lista
        recebida), o item fica pendente sobre a revisao recebida - a lista
        daqui volta para a VPS na proxima troca e os dois lados convergem."""
        if _igual(ler_item(self.banco, self.setor, "setores"), recebido):
            return False
        agora = _agora_utc()
        self.banco.marcar_rev("setores", rev, agora, "notebook", "notebook", True)
        self.banco.registrar_alteracao(agora, "notebook", "notebook", "setores",
                                       "Setores: mantido aqui um setor com dados que faltava na lista da nuvem")
        return True
        self.banco.salvar_segredo(SEGREDO_SYNC_CONFIG, json.dumps({"url": url, "rev": int(resposta.get("rev_atual", 0))}))
        self.banco.salvar_segredo(SEGREDO_AUDITORIA_NUVEM, json.dumps(resposta.get("auditoria") or [], ensure_ascii=False))

    def avisos(self):
        return _segredo_json(self.banco, SEGREDO_AVISOS_SYNC).get("lista", [])

    def auditoria(self):
        """Ultimas alteracoes: a lista da VPS (completa) + o que esta pendente aqui."""
        try:
            nuvem = json.loads(self.banco.obter_segredo(SEGREDO_AUDITORIA_NUVEM) or "[]")
        except ValueError:
            nuvem = []
        return nuvem if nuvem else self.banco.ultimas_alteracoes(50)

    def _enviar_legado(self, cfg):
        """Envio da 1.1.0 (configuracao inteira) - so para VPS desatualizada."""
        corpo = {"setor": self.setor, **config_do_setor(self.banco, self.setor)}
        senha = dados_senha_remota(self.banco)
        if senha:  # so o hash - a senha em si nunca sai do notebook
            corpo["acessoRemoto"] = {"hash": senha["hash"], "alteradoEm": senha.get("alterado_em", "")}
        texto = json.dumps(corpo, sort_keys=True, ensure_ascii=False)
        resumo = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if resumo == self._ultimo_hash and time.monotonic() - self._ultimo_ok < self.REENVIAR_S:
            return False
        req = urllib.request.Request(
            cfg["url"] + "/api/nuvem/config", data=texto.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Chave-Nuvem": cfg["chave"]},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
                resp.read()
        except HTTPError as erro:
            motivo = "chave recusada pela VPS (NUVEM_CHAVE diferente)" if erro.code == 403 else f"HTTP {erro.code}"
            self._atualizar(erro=motivo)
            return False
        except (OSError, ValueError) as erro:
            self._atualizar(erro=f"sem conexão com a VPS ({erro})")
            return False
        self._ultimo_hash, self._ultimo_ok = resumo, time.monotonic()
        self._atualizar(ultimo_envio=_agora_iso(), erro="")
        return True

    def iniciar(self):
        def laco():
            proxima_config = 0.0
            esp_atrasado = False
            while not self.parar_evento.is_set():
                if time.monotonic() >= proxima_config:
                    try:
                        self.enviar_agora()
                    except Exception as erro:  # noqa: BLE001 - nunca derruba o app
                        self._atualizar(erro=f"{type(erro).__name__}: {erro}")
                    proxima_config = time.monotonic() + self.VERIFICAR_S
                    rodar_historico = True
                else:
                    rodar_historico = esp_atrasado  # ESP32 sem enviar direto: ciclos novos a cada 5 s
                if rodar_historico:
                    try:
                        self.enviar_historico()
                    except Exception as erro:  # noqa: BLE001
                        self._atualizar_historico(erro=f"{type(erro).__name__}: {erro}")
                try:
                    esp_atrasado = self.enviar_ao_vivo()
                except Exception as erro:  # noqa: BLE001
                    esp_atrasado = False
                    with self._trava:
                        self._status["ao_vivo"].update(erro=f"{type(erro).__name__}: {erro}")
                self.parar_evento.wait(self.AO_VIVO_RAPIDO_S if esp_atrasado else self.VERIFICAR_S)

        threading.Thread(target=laco, name="nuvem-config", daemon=True).start()
        return self.parar_evento
