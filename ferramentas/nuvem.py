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

Rotas da VPS (POST, com o cabecalho X-Chave-Nuvem = NUVEM_CHAVE do .env):
  /api/nuvem/enviar  <- ESP32: {"dispositivo", "firmware", "hora", "hora_valida",
                       "ultimo_id", "lido_ate", "perdidos", "maquinas": [...],
                       "ciclos": "id,maquina,ciclo,inicio,fim,duracao_s,obs\\n..."}
  /api/nuvem/config  <- notebook: o mesmo formato de GET /config

Pessoas: login HTTP Basic (sempre atras do HTTPS do Caddy) com usuarios em
dados/usuarios.json - criados com ferramentas/usuarios_nuvem.py.
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
ARQUIVO_USUARIOS = "usuarios.json"
ARQUIVO_CONFIG_NUVEM = "nuvem.json"  # no notebook: {"url": "...", "chave": "..."} (opcional)
ESP_SEM_ENVIAR_S = 60  # sem envio do ESP32 ha mais que isso = "controlador sem enviar"
MAX_CICLOS_POR_ENVIO = 500


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
    _atualizar_status(dir_dados, config_recebida_em=_agora_iso())
    return {"ok": True}


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
# VPS: login das pessoas (HTTP Basic, sempre atras do HTTPS)
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


def carregar_usuarios(dir_dados):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_USUARIOS), "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}


def salvar_usuarios(dir_dados, usuarios):
    _gravar_json(os.path.join(dir_dados, ARQUIVO_USUARIOS), usuarios)


class Autenticador:
    """Confere o cabecalho Authorization: Basic. O PBKDF2 e lento de
    proposito (protege as senhas), entao um login que ja deu certo fica
    lembrado por 10 min - o painel faz varias consultas por minuto."""

    LEMBRAR_S = 600
    MAX_FALHAS, JANELA_FALHAS_S = 10, 600

    def __init__(self, dir_dados):
        self.dir_dados = dir_dados
        self._ok = {}      # sha256(cabecalho) -> (usuario, valido_ate)
        self._falhas = {}  # ip -> [instantes]
        self._trava = threading.Lock()

    def bloqueado(self, ip):
        agora = time.monotonic()
        with self._trava:
            recentes = [t for t in self._falhas.get(ip, []) if agora - t < self.JANELA_FALHAS_S]
            self._falhas[ip] = recentes
            return len(recentes) >= self.MAX_FALHAS

    def usuario(self, cabecalho, ip):
        """Nome do usuario autenticado, ou None."""
        if not cabecalho or not cabecalho.startswith("Basic "):
            return None
        chave = hashlib.sha256(cabecalho.encode("utf-8")).hexdigest()
        agora = time.monotonic()
        with self._trava:
            lembrado = self._ok.get(chave)
            if lembrado and lembrado[1] > agora:
                return lembrado[0]
        try:
            nome, senha = base64.b64decode(cabecalho[6:].strip()).decode("utf-8").split(":", 1)
        except (ValueError, UnicodeDecodeError):
            nome, senha = "", ""
        guardado = carregar_usuarios(self.dir_dados).get(nome)
        if guardado and verificar_senha(senha, guardado):
            with self._trava:
                self._ok[chave] = (nome, agora + self.LEMBRAR_S)
            return nome
        with self._trava:
            self._falhas.setdefault(ip, []).append(agora)
        return None


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
    """Thread do notebook: manda a configuracao para a VPS quando ela muda
    (conferido a cada 30 s) e, mesmo sem mudanca, a cada 30 min. Sem
    internet, so tenta de novo depois - nunca atrapalha o painel local."""

    VERIFICAR_S = 30
    REENVIAR_S = 1800
    TIMEOUT_S = 10

    def __init__(self, banco, dir_dados, setor):
        self.banco, self.dir_dados, self.setor = banco, dir_dados, setor
        self.parar_evento = threading.Event()
        self._status = {"ativo": False, "url": "", "ultimo_envio": "", "erro": ""}
        self._ultimo_hash, self._ultimo_ok = None, 0.0
        self._trava = threading.Lock()

    def status(self):
        with self._trava:
            return dict(self._status)

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
                self.parar_evento.wait(self.VERIFICAR_S)

        threading.Thread(target=laco, name="nuvem-config", daemon=True).start()
        return self.parar_evento
