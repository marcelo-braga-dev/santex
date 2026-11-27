"""
Recebimento dos coletores por push - POST /api/v2/coletor (2.0, fase 2,
plano secao 8). So no servidor local (mini-PC); os coletores nao falam com
a VPS.

Autenticacao, por aparelho:
    chave do aparelho = HMAC-SHA256(COLETOR_CHAVE_MESTRA, id)  (em hex)
    X-Ts           = hora do aparelho (epoch, segundos)
    X-Assinatura   = HMAC-SHA256(chave do aparelho, X-Ts + "." + corpo)  (hex)
A chave do aparelho e gravada nele no provisionamento e nunca trafega; a
mestra fica so aqui (.env -> app/segredos_app.json). X-Ts com mais de
JANELA_TS_S de diferenca e recusado (anti-replay) - a recusa devolve a hora
do servidor, para um aparelho com o relogio errado conseguir se acertar.

Depois de autenticado:
- o aparelho entra/atualiza no cadastro (ferramentas/dispositivos.py);
- bloqueado -> 403;
- nao adotado -> {"adotado": false, "ack_ate": 0}: NADA e gravado, os
  ciclos ficam guardados no ESP32 ate a adocao;
- adotado -> grava cada ciclo com o setor e a maquina DO CADASTRO (gravados
  no ciclo, na chegada), atualiza o estado ao vivo e devolve "ack_ate": o
  ESP32 so apaga da flash ate ele. A resposta so sai depois do COMMIT de
  cada ciclo (gravar_ciclo_remoto grava numa transacao propria). Reenviar o
  mesmo lote nao duplica nada (dispositivo + origem_id).

Formato do corpo (v2):
    {"v": 2, "dispositivo": "esp-24A1B2C3D4E5", "firmware": "4.0.0",
     "perfil": "unitario", "seq": 18233, "hora": 1795700000, "hora_valida": true,
     "estado": [{"canal": 1, "ligado": true, "segundos": 312}],
     "ciclos": [[1501, 1, 88, "2026-12-01 07:02:10", "2026-12-01 07:09:44", 454.0, ""]],
     "saude": {"rssi": -63, "bssid": "...", "heap": 142000, ...}}
ciclo = [id no ESP32, canal, numero do ciclo, inicio, fim, duracao_s, obs].
"""

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta

import dispositivos
from monitor_wifi import ARQUIVO_CHAVE_APP

VERSAO_PROTOCOLO = 2
JANELA_TS_S = 120
MAX_CORPO = 64 * 1024
MAX_CICLOS = 200
CONFIG_PADRAO = {"debounce_ms": 1000, "intervalo_s": 10}


class ErroColetor(Exception):
    def __init__(self, status, erro, **extra):
        super().__init__(erro)
        self.status, self.erro, self.extra = status, erro, extra

    def resposta(self):
        return {"ok": False, "erro": self.erro, **self.extra}


def chave_mestra():
    """COLETOR_CHAVE_MESTRA: variavel de ambiente (testes, VPS nunca) ou a
    gerada por gerar_segredos.py em app/segredos_app.json. Vazia = coletores
    desligados."""
    valor = os.environ.get("COLETOR_CHAVE_MESTRA", "").strip()
    if valor:
        return valor
    try:
        with open(ARQUIVO_CHAVE_APP, "r", encoding="utf-8") as arquivo:
            return str(json.load(arquivo).get("coletor_chave_mestra", "")).strip()
    except (OSError, ValueError, AttributeError):
        return ""


def chave_do_aparelho(mestra, dispositivo):
    """A chave gravada no aparelho no provisionamento (hex)."""
    return hmac.new(mestra.encode("utf-8"), dispositivo.encode("utf-8"), hashlib.sha256).hexdigest()


def assinar(chave, ts, corpo):
    """X-Assinatura de um pedido (o que o firmware calcula)."""
    return hmac.new(chave.encode("utf-8"), str(ts).encode("utf-8") + b"." + corpo, hashlib.sha256).hexdigest()


def autenticar(cabecalhos, corpo, mestra, agora=None):
    """(dados, id do aparelho) de um pedido valido; ErroColetor senao.
    cabecalhos: algo com .get(nome) (os cabecalhos HTTP)."""
    agora = time.time() if agora is None else agora
    if not mestra:
        raise ErroColetor(503, "coletores desligados (sem COLETOR_CHAVE_MESTRA)")
    if len(corpo) > MAX_CORPO:
        raise ErroColetor(413, "corpo grande demais")
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ErroColetor(400, "JSON invalido") from None
    if not isinstance(dados, dict) or dados.get("v") != VERSAO_PROTOCOLO:
        raise ErroColetor(400, "versao do protocolo")
    dispositivo = dispositivos.normalizar_id(dados.get("dispositivo"))
    if dispositivo is None:
        raise ErroColetor(400, "dispositivo invalido")
    try:
        ts = int(str(cabecalhos.get("X-Ts") or ""))
    except ValueError:
        raise ErroColetor(401, "assinatura") from None
    esperada = assinar(chave_do_aparelho(mestra, dispositivo), ts, corpo)
    if not hmac.compare_digest(esperada, str(cabecalhos.get("X-Assinatura") or "").strip().lower()):
        raise ErroColetor(401, "assinatura")
    if abs(agora - ts) > JANELA_TS_S:  # assinado, mas velho/adiantado: devolve a hora certa
        raise ErroColetor(401, "relogio", hora=int(agora))
    return dados, dispositivo


def _texto_hora(valor):
    """"2026-12-01 07:09:44" ou "2026-12-01T07:09:44" -> "2026-12-01 07:09:44"; senao None."""
    try:
        return datetime.strptime(str(valor).strip().replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def processar(banco, dados, dispositivo, ip=""):
    """Aplica um pedido ja autenticado. Devolve (status HTTP, resposta)."""
    perfil = dados.get("perfil") if dados.get("perfil") in dispositivos.PERFIS else (
        "unitario" if dispositivo.startswith("esp-") else "multi")
    saude = dict(dados["saude"]) if isinstance(dados.get("saude"), dict) else {}
    if "hora_valida" in dados:  # alerta "relogio invalido" (bateria do RTC)
        saude["hora_valida"] = bool(dados["hora_valida"])
    d = dispositivos.registrar_contato(banco, dispositivo, perfil, dados.get("firmware"), ip, saude)
    if d is None:
        return 429, {"ok": False, "erro": "limite de aparelhos novos"}
    if d["situacao"] == "bloqueado":
        return 403, {"ok": False, "erro": "bloqueado"}
    base = {"ok": True, "hora": int(time.time()), "config": {"rev": d["config_rev"], **CONFIG_PADRAO}, "comando": None}
    if d["situacao"] != "ativo" or not d["setor"] or (d["perfil"] == "unitario" and not d["maquina"]):
        return 200, {**base, "adotado": False, "ack_ate": 0}

    def maquina_de(canal):
        if d["perfil"] == "unitario":
            return d["maquina"]  # quem diz qual maquina e qual e o servidor
        return canal if isinstance(canal, int) and 1 <= canal <= 64 else None

    ciclos = dados.get("ciclos") or []
    if not isinstance(ciclos, list) or len(ciclos) > MAX_CICLOS:
        return 400, {"ok": False, "erro": f"ciclos: lista de no maximo {MAX_CICLOS}"}
    gravados = ignorados = maior = 0
    for c in ciclos:
        try:
            origem_id, canal, ciclo, inicio, fim, duracao, obs = c
            origem_id, ciclo, duracao = int(origem_id), int(ciclo), float(duracao)
            maquina = maquina_de(int(canal))
            if origem_id <= 0 or maquina is None or not 0 <= duracao <= 31 * 86400:
                raise ValueError
        except (TypeError, ValueError):
            ignorados += 1  # nunca vai ficar valido: confirma assim mesmo (senao trava a flash do ESP32)
            try:
                maior = max(maior, int(c[0]))
            except (TypeError, ValueError, IndexError, KeyError):
                pass
            continue
        obs = str(obs or "")[:40].replace(",", ";")
        gravado_em = None if "SEM_HORA" in obs else _texto_hora(fim)
        if banco.gravar_ciclo_remoto(d["setor"], d["dispositivo"], origem_id, maquina, ciclo,
                                     str(inicio)[:25], str(fim)[:25], duracao, obs, gravado_em):
            gravados += 1
        maior = max(maior, origem_id)

    agora = datetime.now()
    for e in dados.get("estado") or []:
        try:
            maquina = maquina_de(int(e["canal"]))
            if maquina is not None:
                desde = agora - timedelta(seconds=max(0, int(e["segundos"])))
                banco.atualizar_estado_ao_vivo(d["setor"], maquina, bool(e["ligado"]), desde.isoformat(timespec="seconds"))
        except (KeyError, TypeError, ValueError):
            continue
    # ack: o maior id deste lote ou o maior ja guardado (batimento sem ciclos
    # tambem libera a flash do que ja estava no banco)
    ack = max(maior, banco.ultimo_id_origem(d["dispositivo"]))
    return 200, {**base, "adotado": True, "ack_ate": ack, "gravados": gravados, "ignorados": ignorados}
