"""
Cadastro de dispositivos (coletores ESP32) - 2.0, fase 2.

Ciclo de vida de um aparelho:

    novo  --adotar(setor, maquina)-->  ativo  --liberar-->  reserva
      |                                  |                     |
      +--------- bloquear -------------> bloqueado <-----------+
                                         (desbloquear -> novo)

- Um aparelho NOVO aparece sozinho no primeiro contato (o servidor so o
  registra depois de conferir a assinatura - ver /api/v2/coletor, 2.3). Ele
  nao grava ciclos ate ser adotado: os ciclos ficam guardados no ESP32.
- ADOTAR liga o aparelho a uma maquina de um setor. Uma maquina tem no
  maximo um aparelho ativo.
- TROCAR (aparelho queimado): o reserva assume a maquina do antigo, que
  vira reserva. Tudo fica em dispositivo_atribuicoes.
- Setor e maquina sao gravados em cada ciclo NA CHEGADA: trocar ou mudar um
  aparelho de lugar nunca altera o historico.

Perfis: "multi" (o ESP32 das Enfestadeiras, firmware 3.x, 4 maquinas - o
setor vem do aparelho, nao de uma maquina) e "unitario" (firmware 4.0, uma
maquina por aparelho).
"""

import re
from datetime import datetime

PERFIS = ("multi", "unitario")
SITUACOES = ("novo", "ativo", "reserva", "bloqueado")
SEM_SINAL_S = 30  # sem contato ha mais que isso: "sem sinal" (nao "parada")
MAX_NOVOS = 200  # protecao: aparelhos novos (nao adotados) guardados de uma vez
# unitario: "esp-" + MAC (12 hex); multi (firmware 3.x): "<MAC>-<serie>"
_RE_UNITARIO = re.compile(r"^esp-[0-9A-F]{12}$")
_RE_MULTI = re.compile(r"^[0-9A-F]{12}-[0-9A-F]{8}$")


class ErroDispositivo(ValueError):
    """Pedido invalido - a mensagem vai para o painel como esta."""


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def normalizar_id(dispositivo):
    """Id em maiusculas (o prefixo "esp-" fica minusculo); None se invalido."""
    texto = str(dispositivo or "").strip()
    if texto[:4].lower() == "esp-":
        texto = "esp-" + texto[4:].upper()
        return texto if _RE_UNITARIO.match(texto) else None
    texto = texto.upper()
    return texto if _RE_MULTI.match(texto) else None


def _serie(dispositivo):
    return dispositivo.rsplit("-", 1)[-1] if _RE_MULTI.match(dispositivo or "") else None


def _exigir(banco, dispositivo):
    d = banco.obter_dispositivo(normalizar_id(dispositivo) or "")
    if d is None:
        raise ErroDispositivo("Aparelho não encontrado.")
    return d


def sem_sinal(d, agora=None):
    """True se o aparelho nao fala ha mais de SEM_SINAL_S (ou nunca falou)."""
    try:
        visto = datetime.fromisoformat(d.get("ultimo_contato") or "")
    except ValueError:
        return True
    return ((agora or datetime.now()) - visto).total_seconds() > SEM_SINAL_S


def registrar_contato(banco, dispositivo, perfil, firmware=None, ip=None, saude=None):
    """Chamado a cada contato de um aparelho JA AUTENTICADO. Cria o registro
    "novo" se ele nao existir; atualiza ultimo contato e saude. Devolve o
    registro, ou None se o id for invalido ou o limite de novos estourar.

    multi (firmware 3.x): o mesmo controlador ja apareceu com a parte do MAC
    diferente (mesma serie) - o registro existente com a mesma serie e
    reaproveitado, nunca duplicado."""
    dispositivo = normalizar_id(dispositivo)
    if dispositivo is None or perfil not in PERFIS:
        return None
    d = banco.obter_dispositivo(dispositivo)
    if d is None and perfil == "multi":
        serie = _serie(dispositivo)
        d = next((x for x in banco.listar_dispositivos() if x["perfil"] == "multi" and _serie(x["dispositivo"]) == serie), None)
    if d is None:
        if sum(1 for x in banco.listar_dispositivos() if x["situacao"] == "novo") >= MAX_NOVOS:
            return None
        d = {"dispositivo": dispositivo, "perfil": perfil, "situacao": "novo", "apelido": "", "config_rev": 0}
    saude = saude if isinstance(saude, dict) else {}
    d.update(perfil=perfil, ultimo_contato=_agora(),
             firmware=str(firmware)[:20] if firmware else d.get("firmware"),
             ip=str(ip)[:45] if ip else d.get("ip"),
             rssi=saude.get("rssi") if isinstance(saude.get("rssi"), int) else d.get("rssi"),
             bssid=str(saude["bssid"])[:17] if saude.get("bssid") else d.get("bssid"),
             saude={k: v for k, v in saude.items() if isinstance(v, (int, float, str, bool))} or d.get("saude") or {})
    banco.salvar_dispositivo(d)
    return banco.obter_dispositivo(d["dispositivo"])


def registrar_multi(banco, dispositivo, setor, firmware=None, ip=None):
    """O ESP32 multi das Enfestadeiras (firmware 3.x): na primeira vez entra
    ja como ativo no setor dele (era assim antes da 2.0 - nao precisa de
    adocao). Nunca levanta excecao: e chamado no caminho da leitura de
    producao, que nao pode parar por causa do cadastro."""
    try:
        d = registrar_contato(banco, dispositivo, "multi", firmware=firmware, ip=ip)
        if d and d["situacao"] == "novo":
            quando = _agora()
            d.update(situacao="ativo", setor=setor, maquina=None, adotado_em=quando)
            banco.salvar_dispositivo(d)
        return d
    except Exception:  # noqa: BLE001 - cadastro nunca derruba a leitura
        return None


def adotar(banco, dispositivo, setor, maquina, autor=""):
    """Liga um aparelho unitario (novo ou reserva) a uma maquina do setor."""
    d = _exigir(banco, dispositivo)
    if d["perfil"] != "unitario":
        raise ErroDispositivo("Só aparelhos de uma máquina (unitário) são adotados por máquina.")
    if d["situacao"] == "bloqueado":
        raise ErroDispositivo("Aparelho bloqueado: desbloqueie antes.")
    if d["situacao"] == "ativo":
        raise ErroDispositivo("Aparelho já adotado: use trocar ou liberar.")
    s = banco.obter_setor(str(setor or ""))
    if s is None:
        raise ErroDispositivo("Setor não encontrado.")
    try:
        maquina = int(maquina)
    except (TypeError, ValueError):
        raise ErroDispositivo("Máquina inválida.") from None
    if not 1 <= maquina <= 64:
        raise ErroDispositivo("Máquina de 1 a 64.")
    ocupante = banco.dispositivo_da_maquina(s["setor"], maquina)
    if ocupante is not None:
        raise ErroDispositivo(f"A máquina {maquina} já tem o aparelho {ocupante['dispositivo']}: use trocar.")
    quando = _agora()
    d.update(situacao="ativo", setor=s["setor"], maquina=maquina, adotado_em=quando)
    banco.salvar_dispositivo(d)
    banco.abrir_atribuicao(d["dispositivo"], s["setor"], maquina, quando, autor)
    return banco.obter_dispositivo(d["dispositivo"])


def liberar(banco, dispositivo, autor=""):
    """Tira o aparelho da maquina (vira reserva). O historico fica."""
    d = _exigir(banco, dispositivo)
    if d["situacao"] != "ativo" or d["perfil"] != "unitario":
        raise ErroDispositivo("Só um aparelho adotado (unitário) pode ser liberado.")
    banco.fechar_atribuicao(d["dispositivo"], _agora())
    d.update(situacao="reserva", setor=None, maquina=None)
    banco.salvar_dispositivo(d)
    return banco.obter_dispositivo(d["dispositivo"])


def trocar(banco, antigo, novo, autor=""):
    """O aparelho "novo" (novo ou reserva) assume a maquina do "antigo"."""
    a = _exigir(banco, antigo)
    if a["situacao"] != "ativo" or a["perfil"] != "unitario":
        raise ErroDispositivo("O aparelho a substituir precisa estar adotado numa máquina.")
    n = _exigir(banco, novo)
    if n["dispositivo"] == a["dispositivo"]:
        raise ErroDispositivo("Escolha outro aparelho.")
    if n["perfil"] != "unitario" or n["situacao"] not in ("novo", "reserva"):
        raise ErroDispositivo("O aparelho que assume precisa ser novo ou reserva.")
    setor, maquina = a["setor"], a["maquina"]
    liberar(banco, a["dispositivo"], autor)
    return adotar(banco, n["dispositivo"], setor, maquina, autor)


def bloquear(banco, dispositivo, autor=""):
    """Bloqueado: o servidor recusa tudo dele (aparelho perdido ou roubado).
    Se estava numa maquina, ela fica livre."""
    d = _exigir(banco, dispositivo)
    if d["situacao"] == "ativo" and d["perfil"] == "unitario":
        banco.fechar_atribuicao(d["dispositivo"], _agora())
    d.update(situacao="bloqueado", setor=None if d["perfil"] == "unitario" else d["setor"],
             maquina=None)
    banco.salvar_dispositivo(d)
    return banco.obter_dispositivo(d["dispositivo"])


def desbloquear(banco, dispositivo, autor=""):
    d = _exigir(banco, dispositivo)
    if d["situacao"] != "bloqueado":
        raise ErroDispositivo("O aparelho não está bloqueado.")
    d.update(situacao="ativo" if d["perfil"] == "multi" and d["setor"] else "novo")
    banco.salvar_dispositivo(d)
    return banco.obter_dispositivo(d["dispositivo"])


def renomear(banco, dispositivo, apelido, autor=""):
    d = _exigir(banco, dispositivo)
    d["apelido"] = " ".join(str(apelido or "").split())[:40]
    banco.salvar_dispositivo(d)
    return banco.obter_dispositivo(d["dispositivo"])


ACOES = {"adotar", "liberar", "trocar", "bloquear", "desbloquear", "renomear"}


def executar(banco, acao, dados, autor=""):
    """POST /dispositivos {"acao": ..., ...} -> registro do aparelho."""
    if acao == "adotar":
        return adotar(banco, dados.get("dispositivo"), dados.get("setor"), dados.get("maquina"), autor)
    if acao == "trocar":
        return trocar(banco, dados.get("antigo"), dados.get("novo"), autor)
    if acao in ("liberar", "bloquear", "desbloquear"):
        return {"liberar": liberar, "bloquear": bloquear, "desbloquear": desbloquear}[acao](banco, dados.get("dispositivo"), autor)
    if acao == "renomear":
        return renomear(banco, dados.get("dispositivo"), dados.get("apelido"), autor)
    raise ErroDispositivo("Ação inválida.")


def lista_para_painel(banco):
    """GET /dispositivos: cada aparelho com "semSinal" calculado agora."""
    agora = datetime.now()
    return [{**d, "semSinal": sem_sinal(d, agora)} for d in banco.listar_dispositivos()]


# -- alertas de comunicacao (plano secao 9.4) ---------------------------------
RSSI_FRACO = -75  # dBm
FLASH_ALTA_PCT = 50  # a flash enchendo = o servidor nao esta recebendo
NIVEL = {"repetidor": "critico", "sem_sinal": "atencao", "flash": "atencao", "relogio": "atencao",
         "sinal_fraco": "info", "reinicios": "atencao", "novo": "info"}


def alertas(banco, agora=None):
    """[{tipo, nivel, dispositivo?, setor?, maquina?, texto}] do estado atual
    dos aparelhos. So os ativos contam para comunicacao (novo/reserva/
    bloqueado nao tem maquina para mostrar como "sem sinal").

    - repetidor: todos os aparelhos ativos de um mesmo AP (bssid, 2 ou mais)
      sem sinal ao mesmo tempo -> um alerta so, no lugar dos "sem sinal";
    - sem_sinal: sem contato ha mais de SEM_SINAL_S;
    - sinal_fraco: ultimo RSSI pior que RSSI_FRACO (o plano pede a media de
      10 min - fica para quando houver historico de saude);
    - flash: uso da flash acima de FLASH_ALTA_PCT;
    - relogio: o aparelho disse hora_valida = false (bateria do RTC);
    - reinicios: o firmware informa "resets_1h" > 3 (campo da saude);
    - novo: aparelho esperando adocao."""
    agora = agora or datetime.now()
    lista = banco.listar_dispositivos()
    ativos = [d for d in lista if d["situacao"] == "ativo"]
    saida = []

    def onde(d):
        if d["perfil"] == "unitario" and d["maquina"]:
            return f"{d['setor']} · máquina {d['maquina']}"
        return d["setor"] or "sem setor"

    por_ap = {}
    for d in ativos:
        if d.get("bssid"):
            por_ap.setdefault(d["bssid"], []).append(d)
    aps_fora = {ap for ap, ds in por_ap.items() if len(ds) >= 2 and all(sem_sinal(d, agora) for d in ds)}
    for ap in sorted(aps_fora):
        saida.append({"tipo": "repetidor", "nivel": NIVEL["repetidor"], "bssid": ap,
                      "texto": f"AP {ap} sem contato: {len(por_ap[ap])} aparelhos sem sinal ao mesmo tempo"})
    for d in ativos:
        base = {"dispositivo": d["dispositivo"], "setor": d["setor"], "maquina": d["maquina"]}
        s = d.get("saude") or {}
        if sem_sinal(d, agora) and d.get("bssid") not in aps_fora:
            saida.append({"tipo": "sem_sinal", "nivel": NIVEL["sem_sinal"], **base,
                          "texto": f"Sem sinal: {d['apelido'] or d['dispositivo']} ({onde(d)})"})
        if isinstance(d.get("rssi"), int) and d["rssi"] < RSSI_FRACO:
            saida.append({"tipo": "sinal_fraco", "nivel": NIVEL["sinal_fraco"], **base,
                          "texto": f"Sinal fraco ({d['rssi']} dBm): {onde(d)}"})
        if isinstance(s.get("flash_uso_pct"), (int, float)) and s["flash_uso_pct"] > FLASH_ALTA_PCT:
            saida.append({"tipo": "flash", "nivel": NIVEL["flash"], **base,
                          "texto": f"Memória do coletor {s['flash_uso_pct']:g}% cheia (o servidor não está recebendo?): {onde(d)}"})
        if s.get("hora_valida") is False:
            saida.append({"tipo": "relogio", "nivel": NIVEL["relogio"], **base,
                          "texto": f"Relógio inválido (trocar a bateria do RTC): {onde(d)}"})
        if isinstance(s.get("resets_1h"), int) and s["resets_1h"] > 3:
            saida.append({"tipo": "reinicios", "nivel": NIVEL["reinicios"], **base,
                          "texto": f"{s['resets_1h']} reinícios na última hora (alimentação ou ruído?): {onde(d)}"})
    novos = [d for d in lista if d["situacao"] == "novo"]
    if novos:
        saida.append({"tipo": "novo", "nivel": NIVEL["novo"], "quantos": len(novos),
                      "texto": f"{len(novos)} aparelho(s) novo(s) esperando adoção"})
    return saida
