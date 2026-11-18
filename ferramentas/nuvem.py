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

Pessoas: UMA senha de acesso, definida e trocada no painel do NOTEBOOK
(menu Configuracoes -> Acesso remoto). O notebook guarda so o hash (PBKDF2) e
o envia para a VPS junto com a configuracao; a VPS mostra uma tela de login
so com senha e mantem a pessoa conectada por 30 dias naquele navegador.
Trocar a senha no notebook desconecta todo mundo.
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
from datetime import datetime, timedelta
from urllib.error import HTTPError

from banco_dados import normalizar_extras, normalizar_turnos
from monitor_wifi import ARQUIVO_CHAVE_APP, _gravar_json, gravar_linhas_ciclos

ARQUIVO_STATUS_NUVEM = "nuvem_status.json"
ARQUIVO_CHAVE_SESSAO = "sessao.key"  # VPS: assina os cookies de sessao (gerado uma vez)
SEGREDO_SENHA_REMOTA = "acesso_remoto"  # tabela segredos: {"hash", "alterado_em"}
COOKIE_SESSAO = "painel_sessao"
DIAS_SESSAO = 30
SENHA_MIN, SENHA_MAX = 8, 128
ARQUIVO_CONFIG_NUVEM = "nuvem.json"  # no notebook: {"url": "...", "chave": "..."} (opcional)
ESP_SEM_ENVIAR_S = 60  # sem envio do ESP32 ha mais que isso = "controlador sem enviar"
MAX_CICLOS_POR_ENVIO = 500
MAX_HISTORICO_POR_ENVIO = 500
DISPOSITIVO_SERIAL = "NOTEBOOK-SERIAL"  # ciclos lidos pela USB (sem serie do ESP32)
CURSOR_HISTORICO = "cursor_historico_nuvem"  # notebook: ate qual id local a VPS confirmou


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


def aplicar_config(banco, corpo, setor_padrao):
    """Grava no banco a configuracao recebida (POST /config do painel ou
    POST /api/nuvem/config do notebook), validando cada campo."""
    setor = str(corpo.get("setor", setor_padrao))[:40]
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


def receber_config(banco, dir_dados, corpo, setor_padrao):
    aplicar_config(banco, corpo, setor_padrao)
    acesso = corpo.get("acessoRemoto") if isinstance(corpo.get("acessoRemoto"), dict) else {}
    if _hash_valido(acesso.get("hash")):  # a senha unica, definida no notebook (so o hash)
        banco.salvar_segredo(SEGREDO_SENHA_REMOTA, json.dumps(
            {"hash": acesso["hash"], "alterado_em": str(acesso.get("alteradoEm", ""))[:25]}))
    _atualizar_status(dir_dados, config_recebida_em=_agora_iso())
    return {"ok": True}


def receber_historico(banco, dir_dados, corpo, setor_padrao):
    """VPS: grava um lote do historico enviado pelo notebook. Lote vazio so
    devolve o total (o notebook usa para conferir se falta algo)."""
    setor = str(corpo.get("setor", setor_padrao))[:40]
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
    return {"ok": True, "gravados": gravados, "total": total}


def status_nuvem(dir_dados):
    """GET /sincronizacao na VPS: o ESP32 esta enviando? quando a
    configuracao chegou do notebook?"""
    s = _ler_status(dir_dados)
    try:
        idade = (datetime.now() - datetime.fromisoformat(s.get("ultimo_contato", ""))).total_seconds()
    except (TypeError, ValueError):
        idade = None
    enviando = idade is not None and idade <= ESP_SEM_ENVIAR_S
    estado = "conectado" if enviando else ("sem_resposta" if idade is not None else "procurando")
    return {**s, "modo": "nuvem", "rodando": enviando, "estado": estado,
            "ultima_sincronizacao": s.get("ultimo_contato", ""), "segundos_sem_envio": idade}


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


def status_senha_remota(banco):
    """Para o painel do notebook - nunca inclui o hash."""
    dados = dados_senha_remota(banco)
    return {"definida": bool(dados), "alteradaEm": dados.get("alterado_em", "")}


def definir_senha_remota(banco, senha):
    """Notebook: grava o hash da nova senha. ValueError se for invalida."""
    senha = str(senha or "")
    if not SENHA_MIN <= len(senha) <= SENHA_MAX:
        raise ValueError(f"A senha precisa ter de {SENHA_MIN} a {SENHA_MAX} caracteres.")
    banco.salvar_segredo(SEGREDO_SENHA_REMOTA, json.dumps({"hash": hash_senha(senha), "alterado_em": _agora_iso()}))


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
        with self._trava:
            self._falhas.setdefault(ip, []).append(time.monotonic())


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

    def _assinar(self, expira, hash_senha_atual):
        return hmac.new(self._segredo, f"{expira}|{hash_senha_atual}".encode("utf-8"), hashlib.sha256).hexdigest()

    def criar(self, hash_senha_atual):
        expira = int(time.time()) + DIAS_SESSAO * 86400
        return f"{expira}.{self._assinar(expira, hash_senha_atual)}"

    def valida(self, token, hash_senha_atual):
        if not token or not hash_senha_atual:
            return False
        try:
            expira, assinatura = str(token).split(".", 1)
            if int(expira) < time.time():
                return False
        except ValueError:
            return False
        return hmac.compare_digest(assinatura, self._assinar(expira, hash_senha_atual))


def pagina_login(erro="", senha_definida=True):
    """Tela de login da VPS: so o campo de senha."""
    from html import escape

    aviso = ""
    if not senha_definida:
        aviso = ('<p class="aviso">A senha do acesso remoto ainda não foi definida. No computador do painel, '
                 'na empresa: <b>⚙ Configurações → Acesso remoto</b>.</p>')
    elif erro:
        aviso = f'<p class="erro">{escape(erro)}</p>'
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Produção · acesso remoto</title>
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
</style></head><body><main>
<img src="/assets/logo.png" alt="">
<h1>Painel de Produção</h1><p class="sub">Acesso remoto · somente visualização</p>
{aviso}
<form method="post" action="/login">
<label for="senha">Senha de acesso</label>
<input id="senha" name="senha" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrar</button>
</form></main></body></html>"""


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

    VERIFICAR_S = 30
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
        self._trava = threading.Lock()

    def status(self):
        with self._trava:
            return {**self._status, "historico": dict(self._status["historico"])}

    def _atualizar_historico(self, **campos):
        with self._trava:
            self._status["historico"].update(campos)

    # -- historico de ciclos -> VPS ---------------------------------------
    def _cursor(self, url):
        """Ate qual id local a VPS confirmou (por URL: trocar a VPS recomeca)."""
        try:
            dados = json.loads(self.banco.obter_segredo(CURSOR_HISTORICO) or "{}")
        except ValueError:
            dados = {}
        return int(dados.get("ate", 0)) if dados.get("url") == url else 0

    def _salvar_cursor(self, url, ate):
        self.banco.salvar_segredo(CURSOR_HISTORICO, json.dumps({"url": url, "ate": int(ate)}))

    def _post_historico(self, cfg, linhas):
        corpo = json.dumps({"setor": self.setor, "ciclos": linhas}, ensure_ascii=False).encode("utf-8")
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
            total_local = self.banco.total_ciclos(self.setor)
            if conferir is None:
                conferir = time.monotonic() - self._ultima_conferencia > self.CONFERIR_TOTAIS_S
            if conferir and ate > 0:
                # a VPS ainda tem tudo o que ja foi enviado? (lote vazio = so o total)
                total_nuvem = self._post_historico(cfg, [])["total"]
                self._ultima_conferencia = time.monotonic()
                self._atualizar_historico(total_nuvem=total_nuvem)
                if total_nuvem < self.banco.total_ciclos(self.setor) - self.banco.total_ciclos(self.setor, ate):
                    ate = 0  # faltam ciclos que ja tinham ido: reenvia tudo (a VPS nao duplica)
                    self._salvar_cursor(url, 0)
            gravados = 0
            for _ in range(self.LOTES_POR_RODADA):
                lote = self.banco.ciclos_para_nuvem(self.setor, ate, MAX_HISTORICO_POR_ENVIO)
                if not lote:
                    break
                linhas = [[c["id"], c["maquina"], c["ciclo"], c["inicio_ms"], c["fim_ms"], c["duracao_s"],
                           c["obs"], c["gravado_em"], c["dispositivo"], c["origem_id"]] for c in lote]
                resposta = self._post_historico(cfg, linhas)
                gravados += int(resposta.get("gravados", 0))
                ate = lote[-1]["id"]
                self._salvar_cursor(url, ate)
                self._atualizar_historico(total_nuvem=resposta.get("total"), ultimo_envio=_agora_iso())
                if self.parar_evento.is_set():
                    break
            self._atualizar_historico(ate=ate, pendentes=self.banco.total_ciclos(self.setor, ate), erro="")
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
        self._atualizar_historico(erro=motivo, pendentes=self.banco.total_ciclos(self.setor, self._cursor(url)))
        return None

    def _atualizar(self, **campos):
        with self._trava:
            self._status.update(campos)

    def enviar_agora(self):
        """Uma rodada: envia se mudou ou se passou o tempo. Devolve True se enviou."""
        cfg = config_nuvem_app(self.dir_dados)
        self._atualizar(ativo=bool(cfg["url"]), url=cfg["url"])
        if not cfg["url"]:
            return False
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
            while not self.parar_evento.is_set():
                try:
                    self.enviar_agora()
                except Exception as erro:  # noqa: BLE001 - nunca derruba o app
                    self._atualizar(erro=f"{type(erro).__name__}: {erro}")
                try:
                    self.enviar_historico()
                except Exception as erro:  # noqa: BLE001
                    self._atualizar_historico(erro=f"{type(erro).__name__}: {erro}")
                self.parar_evento.wait(self.VERIFICAR_S)

        threading.Thread(target=laco, name="nuvem-config", daemon=True).start()
        return self.parar_evento
