"""
Busca pela rede Wi-Fi os ciclos que o ESP32 guarda na propria flash
(LittleFS, com data/hora do RTC) e grava no banco de dados
(banco_dados.py) - o mesmo papel do monitor_serial.py, mas sem cabo e sem
precisar do PC ligado o tempo todo: o ESP32 vai acumulando os ciclos e,
quando o PC conecta (ex. a cada 3 dias), tudo o que falta e baixado.

Cada ciclo tem um id sequencial no ESP32. Aqui so se pede o que veio
depois do ultimo id ja gravado, e o banco ignora ids repetidos - buscar de
novo nunca duplica nada. Depois que os ciclos estao gravados no banco, o
armazenamento do ESP32 e zerado (POST /limpar) para liberar espaco.

Tambem acerta o relogio (RTC DS3231M) do ESP32 com a hora do PC sempre que
a diferenca passar de TOLERANCIA_RELOGIO_S.

Uso:
    python monitor_wifi.py [ENDERECO ...]

O ESP32 pode estar na rede da empresa, na propria rede (HORIMETRO_SANTEX,
sempre 192.168.4.1) ou nas duas. A cada consulta os enderecos sao tentados
em ordem - primeiro o que funcionou por ultimo - e o primeiro que responder
e usado. Alem dos informados (linha de comando ou dados/conexao.json),
sempre entram 192.168.4.1, horimetro.local e o IP que o proprio ESP32
informou ter na rede da empresa (guardado em dados/esp32_ip_empresa.txt):
    {"modo": "wifi"}
    {"modo": "wifi", "endereco": "192.168.15.50"}
    {"modo": "wifi", "endereco": ["192.168.15.50", "192.168.4.1"]}

A situacao da sincronizacao (ESP32 encontrado ou nao, em qual rede, hora
da ultima extracao...) e gravada em dados/sincronizacao.json a cada
consulta - o painel mostra isso via GET /sincronizacao dos servidores
locais, inclusive depois de reabrir o app ("ultima sincronizacao ha 3 dias").

A funcao monitorar() tambem e importada diretamente pelo aplicativo
desktop (app/servidor.py), rodando numa thread - mesmo esquema do
monitor_serial.monitorar().
"""

import http.client
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from banco_dados import BancoDados, NOME_ARQUIVO
from monitor_serial import SETOR_PADRAO, _log_seguro

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_DADOS_PADRAO = os.path.join(DIR_BASE, "..", "dados")
ARQUIVO_CONEXAO = "conexao.json"

INTERVALO_S = 5            # de quanto em quanto tempo consulta o ESP32
TIMEOUT_S = 8
TIMEOUT_PROCURA_S = 2      # para descobrir rapido qual endereco responde
ENDERECOS_PADRAO = ("192.168.4.1", "horimetro.local")  # rede propria do ESP32 / mDNS
ARQUIVO_IP_APRENDIDO = "esp32_ip_empresa.txt"
ARQUIVO_STATUS = "sincronizacao.json"
PREFIXO_REDE_PROPRIA = "192.168.4."  # AP_IP do firmware
TOLERANCIA_RELOGIO_S = 3
MAX_POR_PAGINA = 200       # mesmo limite do firmware (MAX_CICLOS_POR_RESPOSTA)
LIMPAR_APOS_EXTRAIR = True # zera o armazenamento do ESP32 depois de gravar no banco

_ERROS_DE_REDE = (OSError, http.client.HTTPException, ValueError, KeyError, TypeError)

# Chave que o firmware exige nas acoes que alteram o ESP32 (/limpar, /hora,
# /acao) - gerada por gerar_segredos.py em app/segredos_app.json (embutido
# no .exe). Pode ser trocada em dados/conexao.json: {"chave": "..."}.
ARQUIVO_CHAVE_APP = os.path.join(DIR_BASE, "..", "app", "segredos_app.json")
_chave_api = {"valor": None}


def definir_chave_api(dir_dados):
    """Carrega a chave (conexao.json tem prioridade sobre a embutida)."""
    chave = str(_ler_config_conexao(dir_dados).get("chave") or "").strip()
    if not chave:
        try:
            with open(ARQUIVO_CHAVE_APP, "r", encoding="utf-8") as arquivo:
                chave = str(json.load(arquivo).get("api_chave") or "").strip()
        except (OSError, ValueError, AttributeError):
            chave = ""
    _chave_api["valor"] = chave
    return chave


def _cabecalhos():
    chave = _chave_api["valor"]
    return {"X-Chave": chave} if chave else {}


class ChaveRecusada(Exception):
    """O ESP32 respondeu 403: a chave do app nao confere com a do firmware."""


MSG_CHAVE_RECUSADA = ("O controlador recusou a chave do aplicativo (API_CHAVE): os ciclos continuam sendo "
                      "baixados, mas a limpeza da memória do controlador e o acerto do relógio ficam parados. "
                      "Gere o firmware e o aplicativo com o mesmo .env (python ferramentas/gerar_segredos.py).")


def _ler_config_conexao(dir_dados):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_CONEXAO), "r", encoding="utf-8") as arquivo:
            config = json.load(arquivo)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def modo_conexao(dir_dados=DIR_DADOS_PADRAO):
    """"wifi" (padrao - inclusive sem conexao.json) ou "serial" (cabo USB)."""
    return "serial" if str(_ler_config_conexao(dir_dados).get("modo", "")).lower() == "serial" else "wifi"


def salvar_modo_conexao(dir_dados, modo):
    """Grava o modo escolhido no painel, preservando o resto do conexao.json."""
    config = _ler_config_conexao(dir_dados)
    config["modo"] = "serial" if modo == "serial" else "wifi"
    _gravar_json(os.path.join(dir_dados, ARQUIVO_CONEXAO), config)


def endereco_configurado(dir_dados=DIR_DADOS_PADRAO):
    """Lista de enderecos do ESP32 em dir_dados/conexao.json (pode ser
    vazia - ai valem so os padroes), ou None se o modo for "serial" (ai o
    app usa a porta USB). Sem conexao.json, vale o Wi-Fi."""
    if modo_conexao(dir_dados) != "wifi":
        return None
    enderecos = _ler_config_conexao(dir_dados).get("endereco") or []
    if isinstance(enderecos, str):
        enderecos = [enderecos]
    return [str(e).strip() for e in enderecos if str(e).strip()]


def _gravar_json(caminho, dados):
    """Grava atomicamente (arquivo temporario + rename) - quem le nunca ve
    um JSON pela metade."""
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=pasta, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    except OSError:
        try:
            os.remove(temporario)
        except OSError:
            pass


def ler_status_sincronizacao(dir_dados=DIR_DADOS_PADRAO):
    """Ultima situacao gravada por monitorar() ({} se nunca sincronizou)."""
    try:
        with open(os.path.join(dir_dados, ARQUIVO_STATUS), "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _agora_iso():
    return datetime.now().isoformat(timespec="seconds")


def _ler_ip_aprendido(dir_dados):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_IP_APRENDIDO), "r", encoding="utf-8") as arquivo:
            return arquivo.read().strip() or None
    except OSError:
        return None


def _salvar_ip_aprendido(dir_dados, ip):
    try:
        with open(os.path.join(dir_dados, ARQUIVO_IP_APRENDIDO), "w", encoding="utf-8") as arquivo:
            arquivo.write(ip)
    except OSError:
        pass


def _epoch_local(momento):
    """Segundos desde 1970 na hora LOCAL, sem fuso - o mesmo "relogio de
    parede" que o RTC do ESP32 guarda."""
    return int((momento - datetime(1970, 1, 1)).total_seconds())


def _hora_para_banco(texto):
    """"2026-10-30T14:05:00" (do ESP32) -> "2026-10-30 14:05:00"; "?" -> None."""
    try:
        return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class ClienteEsp32:
    def __init__(self, endereco):
        base = endereco if endereco.startswith("http") else f"http://{endereco}"
        self.base = base.rstrip("/")

    def _requisitar(self, caminho, metodo="GET", timeout=TIMEOUT_S):
        req = Request(self.base + caminho, data=b"" if metodo == "POST" else None, method=metodo,
                      headers=_cabecalhos() if metodo == "POST" else {})
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8"), resp.headers
        except HTTPError as erro:
            if erro.code == 403:
                raise ChaveRecusada(MSG_CHAVE_RECUSADA) from erro
            raise

    def info(self, timeout=TIMEOUT_S):
        return json.loads(self._requisitar("/info", timeout=timeout)[0])

    def ciclos(self, desde):
        """(linhas CSV sem cabecalho, ultimo id examinado pelo ESP32)."""
        texto, headers = self._requisitar(f"/ciclos?desde={desde}&max={MAX_POR_PAGINA}")
        linhas = [l for l in texto.splitlines()[1:] if l.strip()]
        return linhas, int(headers.get("X-Lido-Ate", desde))

    def acertar_hora(self, epoch):
        return json.loads(self._requisitar(f"/hora?epoch={epoch}", "POST")[0])

    def limpar(self, ate):
        return json.loads(self._requisitar(f"/limpar?ate={ate}", "POST")[0])


def _sincronizar_relogio(cliente, info, log):
    """Acerta o RTC do ESP32 se preciso. Devolve True se acertou."""
    agora = _epoch_local(datetime.now())
    if info.get("hora_valida") and abs(int(info.get("epoch", 0)) - agora) <= TOLERANCIA_RELOGIO_S:
        return False
    cliente.acertar_hora(agora)
    _log_seguro(log, f"Relogio do ESP32 acertado (estava: {info.get('hora')}).")
    return True


def _gravar_estado_ao_vivo(banco, setor, info):
    agora = datetime.now()
    for m in info.get("maquinas", []):
        desde = agora - timedelta(seconds=int(m["segundos"]))
        banco.atualizar_estado_ao_vivo(setor, int(m["maquina"]), bool(m["ligado"]), desde.isoformat(timespec="seconds"))


def gravar_linhas_ciclos(banco, setor, dispositivo, linhas, log=print):
    """Grava linhas "id,maquina,ciclo,inicio,fim,duracao_s,obs" vindas do
    ESP32 - as de GET /ciclos (notebook) e as que o firmware 3.0 envia para
    a VPS (POST /api/nuvem/enviar): o MESMO formato, gravado do mesmo jeito,
    com a mesma deduplicacao (serie do ESP32 + id). Devolve quantos eram
    novos."""
    novos = 0
    for linha in linhas:
        partes = linha.strip().split(",")
        if len(partes) != 7 or not partes[0].isdigit():
            _log_seguro(log, f"[aviso] linha ignorada: {linha}")
            continue
        origem_id, maquina, ciclo, inicio, fim, duracao_s, obs = partes
        try:
            if banco.gravar_ciclo_remoto(
                setor, dispositivo, int(origem_id), int(maquina), int(ciclo),
                inicio, fim, float(duracao_s), obs, _hora_para_banco(fim),
            ):
                novos += 1
        except ValueError:
            _log_seguro(log, f"[aviso] linha ignorada (campo invalido): {linha}")
    return novos


def registrar_multi_seguro(banco, dispositivo, setor, firmware=None, ip=None):
    """2.0 (fase 2): o ESP32 multi entra no cadastro de dispositivos (ativo,
    no setor dele) a cada contato. Nada aqui pode parar a leitura: ate um
    erro de importacao e engolido."""
    try:
        import dispositivos
        dispositivos.registrar_multi(banco, dispositivo, setor, firmware=firmware, ip=ip)
    except Exception:  # noqa: BLE001
        pass


def _baixar_ciclos(cliente, banco, setor, info, log):
    """Baixa tudo o que o banco ainda nao tem. Devolve (ultimo id examinado
    - tudo ate ele esta seguro no banco -, ciclos novos, ciclos perdidos)."""
    dispositivo = info["dispositivo"]
    registrar_multi_seguro(banco, dispositivo, setor, info.get("firmware"), getattr(cliente, "ip", None))
    desde = banco.ultimo_id_origem(dispositivo)
    # Ciclos entre o que ja temos e o mais antigo que o ESP32 ainda guarda:
    # o buffer circular encheu e eles foram sobrescritos antes de extraidos.
    perdidos = int(info["primeiro_id"]) - (max(desde, int(info.get("apagado_ate", 0))) + 1)
    if perdidos > 0:
        _log_seguro(log, f"[aviso] {perdidos} ciclo(s) foram sobrescritos no ESP32 antes de serem extraidos.")

    novos = 0
    while True:
        linhas, lido_ate = cliente.ciclos(desde)
        novos += gravar_linhas_ciclos(banco, setor, dispositivo, linhas, log)
        if lido_ate <= desde:
            break
        desde = lido_ate
    if novos:
        _log_seguro(log, f"{novos} ciclo(s) novo(s) gravado(s) no banco.")
    return desde, novos, max(0, perdidos)


class _Enderecos:
    """Enderecos candidatos do ESP32, com o ultimo que funcionou na frente."""

    def __init__(self, informados, dir_dados):
        self.dir_dados = dir_dados
        self.lista = []
        for e in list(informados) + [_ler_ip_aprendido(dir_dados)] + list(ENDERECOS_PADRAO):
            self.adicionar(e)

    def adicionar(self, endereco, na_frente=False):
        if not endereco:
            return
        if endereco in self.lista:
            if not na_frente:
                return
            self.lista.remove(endereco)
        if na_frente:
            self.lista.insert(0, endereco)
        else:
            self.lista.append(endereco)

    def procurar(self, parar_evento=None):
        """(cliente, info) do primeiro endereco que responder, ou None."""
        for endereco in list(self.lista):
            if parar_evento is not None and parar_evento.is_set():
                return None
            cliente = ClienteEsp32(endereco)
            try:
                return cliente, cliente.info(timeout=TIMEOUT_PROCURA_S)
            except _ERROS_DE_REDE:
                continue
        return None

    def aprender_ip_empresa(self, info):
        """O ESP32 informa o IP que tem na rede da empresa - guardado para
        acha-lo direto quando o notebook estiver nessa rede."""
        ip = str(info.get("ip_empresa") or "").strip()
        if ip and ip != _ler_ip_aprendido(self.dir_dados):
            _salvar_ip_aprendido(self.dir_dados, ip)
        self.adicionar(ip)


def monitorar(enderecos=(), banco=None, setor=SETOR_PADRAO, parar_evento=None, log=print):
    """Consulta o ESP32 a cada INTERVALO_S ate parar_evento ser sinalizado
    (ou para sempre - Ctrl+C - se for None). Nunca morre por falta de
    rede: so avisa e tenta de novo. enderecos: str ou lista (os padroes
    sempre entram no fim)."""
    if parar_evento is None:
        parar_evento = threading.Event()
    if banco is None:
        banco = BancoDados(os.path.join(DIR_DADOS_PADRAO, NOME_ARQUIVO))
    if isinstance(enderecos, str):
        enderecos = [enderecos]

    dir_dados = os.path.dirname(banco.caminho)
    definir_chave_api(dir_dados)
    candidatos = _Enderecos(enderecos, dir_dados)
    _log_seguro(log, f"Procurando o ESP32 em: {', '.join(candidatos.lista)} (setor: {setor}). Ctrl+C para parar.")
    caminho_status = os.path.join(dir_dados, ARQUIVO_STATUS)
    # Mantem o historico (ultima sincronizacao, ultima extracao...) de
    # execucoes anteriores - o painel mostra "ha 3 dias" mesmo apos reabrir.
    status = ler_status_sincronizacao(dir_dados)
    status.update({"estado": "procurando", "enderecos": list(candidatos.lista), "erro": ""})
    _gravar_json(caminho_status, status)

    conectado = None
    base_atual = None
    limpeza = {"alvo": 0, "em": 0.0}  # ultima limpeza pedida ao ESP32
    while not parar_evento.is_set():
        try:
            achado = candidatos.procurar(parar_evento)
            if parar_evento.is_set():
                break
            if not achado:
                raise OSError("nenhum endereco respondeu")
            cliente, info = achado
            endereco = cliente.base.replace("http://", "")
            candidatos.adicionar(endereco, na_frente=True)
            candidatos.aprender_ip_empresa(info)
            if conectado is not True or cliente.base != base_atual:
                _log_seguro(log, f"Conectado ao ESP32 {info['dispositivo']} em {cliente.base} - {info.get('pendentes', '?')} ciclo(s) guardado(s) nele.")
                conectado = True
                base_atual = cliente.base
            status.update({
                "estado": "conectado",
                "endereco": endereco,
                "rede": "propria" if endereco.startswith(PREFIXO_REDE_PROPRIA) else "empresa",
                "dispositivo": info.get("dispositivo", ""),
                "rede_empresa": info.get("rede_empresa", ""),
                "ip_empresa": info.get("ip_empresa", ""),
                "modo_wifi": info.get("modo_wifi"),
                "ultimo_contato": _agora_iso(),
                "erro": "",
            })
            # Chave recusada (firmware e app com API_CHAVE diferentes) NUNCA
            # impede o download: so o acerto de hora e a limpeza ficam parados
            # (antes, a recusa no /hora abortava a rodada antes de baixar - e a
            # memoria do ESP32 acabaria sobrescrevendo ciclos nao baixados).
            chave_recusada = False
            try:
                if _sincronizar_relogio(cliente, info, log):
                    status["relogio_acertado_em"] = _agora_iso()
                    status["relogio_estava"] = info.get("hora", "")
            except ChaveRecusada:
                chave_recusada = True
            status["hora_esp_valida"] = True
            _gravar_estado_ao_vivo(banco, setor, info)

            ultimo_id = int(info["ultimo_id"])
            apagado_ate = int(info.get("apagado_ate", 0))
            ja_tem = banco.ultimo_id_origem(info["dispositivo"])
            if ultimo_id > ja_tem:
                status["estado"] = "baixando"
                status["pendentes_esp"] = ultimo_id - ja_tem
                _gravar_json(caminho_status, status)
                extraido_ate, novos, perdidos = _baixar_ciclos(cliente, banco, setor, info, log)
                if novos:
                    status["ultima_extracao"] = _agora_iso()
                    status["ciclos_ultima_extracao"] = novos
                if perdidos:
                    status["perdidos_em"] = _agora_iso()
                    status["ciclos_perdidos"] = perdidos
                status["estado"] = "conectado"
            else:
                extraido_ate = ja_tem
            status["pendentes_esp"] = max(0, ultimo_id - extraido_ate)
            # Tudo ate extraido_ate ja esta no banco - so entao o armazenamento
            # do ESP32 e liberado. No firmware 3.0 ele so libera ate o que a VPS
            # tambem ja recebeu: a limpeza e repetida no maximo a cada 60 s
            # enquanto a VPS nao alcanca.
            alvo_limpeza = min(extraido_ate, ultimo_id)
            if LIMPAR_APOS_EXTRAIR and alvo_limpeza > apagado_ate and (
                    alvo_limpeza != limpeza["alvo"] or time.monotonic() - limpeza["em"] > 60):
                limpeza.update({"alvo": alvo_limpeza, "em": time.monotonic()})
                try:
                    restante = cliente.limpar(alvo_limpeza)
                    _log_seguro(log, f"Armazenamento do ESP32 liberado - guardados nele: {restante.get('pendentes', '?')}.")
                except ChaveRecusada:
                    chave_recusada = True
            # firmware 3.0: situacao do envio do ESP32 para a VPS (acesso remoto)
            if "nuvem_ativa" in info:
                status["nuvem_esp"] = {
                    "ativa": bool(info.get("nuvem_ativa")),
                    "ate": int(info.get("nuvem_ate", 0)),
                    "pendentes": max(0, ultimo_id - int(info.get("nuvem_ate", 0))),
                    "ultimo_envio_s": info.get("nuvem_ultimo_envio_s"),
                    "erro": str(info.get("nuvem_erro", "")),
                }
            status["ultima_sincronizacao"] = _agora_iso()
            if chave_recusada and not status.get("aviso_chave"):
                _log_seguro(log, f"[aviso] {MSG_CHAVE_RECUSADA}")
            status["aviso_chave"] = MSG_CHAVE_RECUSADA if chave_recusada else ""
        except ChaveRecusada as erro:
            # Nada foi apagado do ESP32 (o /limpar foi recusado) - os ciclos
            # baixados ja estao no banco e o resto continua guardado nele.
            _log_seguro(log, f"[erro] {erro}")
            conectado = None
            status.update({"estado": "erro", "erro": str(erro)})
        except _ERROS_DE_REDE as erro:
            if conectado is not False:
                _log_seguro(log, f"Sem resposta do ESP32 ({erro}) - tentando de novo a cada {INTERVALO_S}s em: {', '.join(candidatos.lista)}.")
                conectado = False
            status.update({"estado": "sem_resposta", "erro": str(erro), "enderecos": list(candidatos.lista)})
        except Exception as erro:  # noqa: BLE001
            # Banco travado/disco cheio (sqlite3.Error) ou qualquer outra
            # falha: a thread NUNCA pode morrer, senao a sincronizacao para
            # em silencio ate reabrir o app. Como a excecao acontece antes do
            # POST /limpar, nada e apagado do ESP32 - tenta de novo depois.
            tipo = "banco de dados" if isinstance(erro, sqlite3.Error) else type(erro).__name__
            _log_seguro(log, f"[erro] {tipo}: {erro} - tentando de novo em {INTERVALO_S}s.")
            conectado = None
            status.update({"estado": "erro", "erro": f"{tipo}: {erro}"})
        status["verificado_em"] = _agora_iso()
        _gravar_json(caminho_status, status)
        parar_evento.wait(INTERVALO_S)

    status["estado"] = "parado"
    _gravar_json(caminho_status, status)


# ---------------------------------------------------------------------
# Ponte para a pagina "Diagnostico do ESP32" do painel: o servidor local
# repassa /info, /eventos e /acao do ESP32 (o painel nao fala direto com
# ele - o endereco certo so o monitor conhece).
# ---------------------------------------------------------------------
ACOES_ESP = ("redetectar_rtc", "varrer_i2c", "reconectar_wifi", "reiniciar")
TIMEOUT_DIAGNOSTICO_S = 5


def _candidatos_esp(status):
    lista = [status.get("endereco") or ""] + list(status.get("enderecos") or [])
    vistos = []
    for e in lista:
        if e and e not in vistos:
            vistos.append(e)
    return vistos


def _json_do_esp(endereco, caminho, metodo="GET"):
    req = Request(f"http://{endereco}{caminho}", method=metodo, data=b"" if metodo == "POST" else None,
                  headers=_cabecalhos() if metodo == "POST" else {})
    with urlopen(req, timeout=TIMEOUT_DIAGNOSTICO_S) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def diagnostico_esp(status):
    """{"ok", "endereco", "info", "eventos", "status"} - eventos = None em
    firmware antigo (sem a rota /eventos)."""
    if status.get("modo") != "wifi":
        return {"ok": False, "status": status,
                "erro": "O diagnóstico detalhado só está disponível com a leitura pelo Wi-Fi (a origem atual é o cabo USB)."}
    ultimo_erro = "nenhum endereço configurado"
    for endereco in _candidatos_esp(status):
        try:
            info = _json_do_esp(endereco, "/info")
        except Exception as erro:  # noqa: BLE001 - qualquer falha de rede = tenta o proximo
            ultimo_erro = f"{endereco}: {erro}"
            continue
        try:
            eventos = _json_do_esp(endereco, "/eventos")
        except Exception:  # noqa: BLE001 - firmware antigo nao tem /eventos
            eventos = None
        return {"ok": True, "endereco": endereco, "info": info, "eventos": eventos, "status": status}
    return {"ok": False, "status": status, "erro": f"O controlador não respondeu ({ultimo_erro})."}


def acao_esp(status, acao):
    if acao not in ACOES_ESP:
        return {"ok": False, "mensagem": "Ação inválida."}
    if status.get("modo") != "wifi":
        return {"ok": False, "mensagem": "Disponível só com a leitura pelo Wi-Fi."}
    ultimo_erro = "nenhum endereço configurado"
    for endereco in _candidatos_esp(status):
        try:
            resposta = _json_do_esp(endereco, f"/acao?acao={acao}", metodo="POST")
            return {**resposta, "endereco": endereco}
        except Exception as erro:  # noqa: BLE001
            if getattr(erro, "code", None) == 403:
                return {"ok": False, "mensagem": MSG_CHAVE_RECUSADA}
            if getattr(erro, "code", None) == 404:
                return {"ok": False, "mensagem": "O firmware deste controlador é antigo e não tem esta função — grave o firmware 2.0."}
            ultimo_erro = f"{endereco}: {erro}"
    return {"ok": False, "mensagem": f"O controlador não respondeu ({ultimo_erro})."}


# ---------------------------------------------------------------------
# 1.7.4: atualizacao do firmware pelo painel do notebook. O ESP32 (firmware
# 3.2+) recebe o .bin em POST /atualizar com a senha do equipamento no
# cabecalho X-Senha - o notebook usa a AP_SENHA embutida no app
# (segredos_app.json, gerado do .env). Grava na outra particao e reinicia;
# se algo falhar no meio, o firmware atual continua.
# ---------------------------------------------------------------------
TAMANHO_MAX_FIRMWARE = 1_310_720  # particao de aplicativo do esquema padrao (2 slots OTA)
TIMEOUT_ENVIO_FIRMWARE_S = 150
ESPERA_VOLTA_FIRMWARE_S = 90
_trava_firmware = threading.Lock()


def _senha_equipamento(dir_dados=DIR_DADOS_PADRAO):
    """conexao.json ("senha_equipamento") tem prioridade sobre a embutida."""
    senha = str(_ler_config_conexao(dir_dados).get("senha_equipamento") or "").strip()
    if senha:
        return senha
    try:
        with open(ARQUIVO_CHAVE_APP, "r", encoding="utf-8") as arquivo:
            return str(json.load(arquivo).get("ap_senha") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def validar_firmware(dados):
    """Mensagem de erro ou "" se o arquivo parece um .ino.bin do ESP32."""
    if not dados:
        return "Nenhum arquivo recebido."
    if len(dados) > TAMANHO_MAX_FIRMWARE:
        return ("Arquivo grande demais para o controlador — use o controle_producao_horimetro.ino.bin "
                "(não o .merged.bin nem o .bootloader.bin).")
    if dados[0] != 0xE9 or len(dados) < 64 * 1024:
        return ("Este arquivo não é um firmware do ESP32. Use o controle_producao_horimetro.ino.bin "
                "(Arduino IDE → Sketch → Exportar binário compilado), não o .merged.bin.")
    return ""


def _multipart(nome_arquivo, dados):
    limite = "----painelsantex" + os.urandom(8).hex()
    nome = re.sub(r'[^A-Za-z0-9._-]', "_", nome_arquivo or "firmware.bin")[:80]
    inicio = (f"--{limite}\r\nContent-Disposition: form-data; name=\"firmware\"; filename=\"{nome}\"\r\n"
              "Content-Type: application/octet-stream\r\n\r\n").encode("ascii")
    return limite, inicio + dados + f"\r\n--{limite}--\r\n".encode("ascii")


def _resumo_versao(info):
    return {"versao": str(info.get("versao") or "?"), "compilado": str(info.get("firmware") or "")}


def atualizar_firmware_esp(status, dados, nome_arquivo="firmware.bin", dir_dados=DIR_DADOS_PADRAO,
                           espera_s=ESPERA_VOLTA_FIRMWARE_S):
    """Envia o firmware ao ESP32 e espera ele voltar. Devolve {"ok",
    "mensagem", "antes", "depois", "endereco"}. Uma atualizacao por vez."""
    erro = validar_firmware(dados)
    if erro:
        return {"ok": False, "mensagem": erro}
    if status.get("modo") != "wifi":
        return {"ok": False, "mensagem": "Disponível só com a leitura pelo Wi-Fi."}
    senha = _senha_equipamento(dir_dados)
    if not senha:
        return {"ok": False, "mensagem": "A senha do equipamento não está no aplicativo — rode "
                "python ferramentas/gerar_segredos.py e gere o .exe de novo."}
    if not _trava_firmware.acquire(blocking=False):
        return {"ok": False, "mensagem": "Já há uma atualização de firmware em andamento."}
    try:
        endereco, antes, ultimo_erro = None, None, "nenhum endereço configurado"
        for candidato in _candidatos_esp(status):
            try:
                antes = _json_do_esp(candidato, "/info")
                endereco = candidato
                break
            except Exception as e:  # noqa: BLE001 - tenta o proximo endereco
                ultimo_erro = f"{candidato}: {e}"
        if not endereco:
            return {"ok": False, "mensagem": f"O controlador não respondeu ({ultimo_erro})."}
        limite, corpo = _multipart(nome_arquivo, dados)
        req = Request(f"http://{endereco}/atualizar", data=corpo, method="POST",
                      headers={"Content-Type": f"multipart/form-data; boundary={limite}", "X-Senha": senha})
        try:
            with urlopen(req, timeout=TIMEOUT_ENVIO_FIRMWARE_S) as resp:
                resposta = resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            texto = e.read().decode("utf-8", errors="replace").strip()
            if e.code == 404:
                return {"ok": False, "mensagem": "O firmware deste controlador não aceita atualização pelo Wi-Fi "
                        "(precisa do 3.2 ou mais novo, gravado uma vez pela USB)."}
            if e.code == 403:
                return {"ok": False, "mensagem": "O controlador recusou a senha do equipamento (AP_SENHA do .env "
                        "diferente da gravada no firmware). Nada foi alterado."}
            return {"ok": False, "mensagem": texto or f"O controlador respondeu HTTP {e.code}. O firmware atual continua."}
        except _ERROS_DE_REDE as e:
            return {"ok": False, "mensagem": f"A conexão com o controlador caiu durante o envio ({e}). "
                    "O firmware atual continua; tente de novo."}
        # o ESP32 reinicia ~1,5 s depois de responder: espera ele voltar
        fim = time.monotonic() + espera_s
        time.sleep(4)
        depois = None
        while time.monotonic() < fim:
            try:
                depois = _json_do_esp(endereco, "/info")
                break
            except Exception:  # noqa: BLE001 - ainda reiniciando
                time.sleep(2)
        r = {"endereco": endereco, "antes": _resumo_versao(antes), "resposta": resposta}
        if depois is None:
            return {**r, "ok": True, "mensagem": "Firmware enviado, mas o controlador ainda não voltou a responder. "
                    "Aguarde um minuto e atualize o diagnóstico."}
        r["depois"] = _resumo_versao(depois)
        mudou = r["depois"] != r["antes"]
        return {**r, "ok": True, "mensagem": (
            f"Firmware atualizado: {r['antes']['versao']} → {r['depois']['versao']} "
            f"(compilado em {r['depois']['compilado']})." if mudou else
            f"O controlador voltou com o mesmo firmware ({r['depois']['versao']}, compilado em "
            f"{r['depois']['compilado']}) — o arquivo enviado era o mesmo já gravado?")}
    finally:
        _trava_firmware.release()


def main():
    monitorar(sys.argv[1:] or endereco_configurado() or [])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuario.")
