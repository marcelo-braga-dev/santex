"""
Simulador de coletores (2.0, fase 2) - N ESP32 virtuais falando o protocolo
real do POST /api/v2/coletor contra um servidor com banco TEMPORARIO.
Nunca abre o banco de producao nem le o ESP32 de verdade.

    python ferramentas/simulador_coletores.py                  # 50 aparelhos, 5 min
    python ferramentas/simulador_coletores.py --aparelhos 200 --minutos 30

Cada aparelho virtual:
- liga e desliga a "maquina" (tempos aleatorios curtos, acelerados);
- guarda cada ciclo numa "flash" e so apaga ate o ack_ate do servidor;
- manda batimento a cada --intervalo s e envia na hora quando o estado muda
  (com 0-2 s de atraso aleatorio, como o firmware);
- falha de rede -> espera dobrando (2 s -> 60 s);
- caos: reinicia de vez em quando (reenvia o que nao foi confirmado), metade
  dos aparelhos "cai" junta por um tempo (repetidor fora), um comeca com o
  relogio 10 min errado (o servidor recusa e devolve a hora certa).

No fim confere: todo ciclo gerado esta no banco UMA vez, e mostra tempos
de resposta (mediana, p95, maximo), pedidos, recusas e erros.
"""

import argparse
import json
import os
import random
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import receptor_push  # noqa: E402


class AparelhoVirtual(threading.Thread):
    def __init__(self, url, mestra, numero, fim_em, intervalo_s, rede_fora, sorteio, relogio_errado_s=0, troca=(2, 15)):
        super().__init__(daemon=True)
        self.troca = troca  # segundos entre ligar e desligar (min, max)
        self.url, self.numero, self.fim_em, self.intervalo_s = url, numero, fim_em, intervalo_s
        self.id = f"esp-5150{numero:08X}"
        self.chave = receptor_push.chave_do_aparelho(mestra, self.id)
        self.rede_fora, self.sorteio = rede_fora, sorteio
        self.offset_relogio = relogio_errado_s
        self.flash = []  # ciclos ainda nao confirmados
        self.gerados = []  # todos os ids gerados (para a conferencia)
        self.proximo_id, self.ciclo = 1, 0
        self.ligado, self.desde = False, time.time()
        self.proxima_troca = time.time() + sorteio.uniform(1, 6)
        self.tempos, self.recusas_relogio, self.erros, self.pedidos, self.reinicios = [], 0, 0, 0, 0
        self.adotado = False

    def _agora_txt(self, t):
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")

    def _maquina(self, agora):
        if agora < self.proxima_troca:
            return False
        if self.ligado:  # desligou: fecha um ciclo
            self.ciclo += 1
            self.flash.append([self.proximo_id, 1, self.ciclo, self._agora_txt(self.desde), self._agora_txt(agora),
                               round(agora - self.desde, 1), ""])
            self.gerados.append(self.proximo_id)
            self.proximo_id += 1
        self.ligado, self.desde = not self.ligado, agora
        self.proxima_troca = agora + self.sorteio.uniform(*self.troca)
        return True

    def _enviar(self):
        if self.rede_fora.is_set() and self.numero % 2 == 0:  # metade cai junto (repetidor fora)
            raise OSError("sem rede")
        corpo = json.dumps({"v": 2, "dispositivo": self.id, "firmware": "4.0.0-sim", "perfil": "unitario",
                            "seq": self.pedidos, "hora": int(time.time() + self.offset_relogio), "hora_valida": True,
                            "estado": [{"canal": 1, "ligado": self.ligado, "segundos": int(time.time() - self.desde)}],
                            "ciclos": self.flash[:50], "saude": {"rssi": -60 - self.numero % 20, "heap": 140000}}).encode()
        ts = int(time.time() + self.offset_relogio)
        req = urllib.request.Request(self.url, data=corpo, method="POST", headers={
            "Content-Type": "application/json", "X-Ts": str(ts), "X-Assinatura": receptor_push.assinar(self.chave, ts, corpo)})
        self.pedidos += 1
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                resposta = json.loads(r.read())
        except urllib.error.HTTPError as e:
            resposta = json.loads(e.read() or b"{}")
            if e.code == 401 and resposta.get("erro") == "relogio":  # acerta o RTC com a hora do servidor
                self.recusas_relogio += 1
                self.offset_relogio = resposta["hora"] - time.time()
                return
            raise
        finally:
            self.tempos.append(time.perf_counter() - t0)
        self.adotado = bool(resposta.get("adotado"))
        ack = int(resposta.get("ack_ate") or 0)
        if ack:
            self.flash = [c for c in self.flash if c[0] > ack]  # apaga da flash so o confirmado

    def run(self):
        espera_falha, proximo_envio = 2.0, time.time() + self.sorteio.uniform(0, 2)
        while time.time() < self.fim_em:
            agora = time.time()
            if self._maquina(agora):  # mudou o estado: envia logo (atraso aleatorio 0-2 s)
                proximo_envio = min(proximo_envio, agora + self.sorteio.uniform(0, 2))
            if self.sorteio.random() < 0.0005:  # reinicio: no boot reenvia na hora tudo o que esta na flash
                self.reinicios += 1
                proximo_envio = agora
            if agora >= proximo_envio:
                try:
                    self._enviar()
                    espera_falha = 2.0
                    proximo_envio = agora + (self.intervalo_s if not self.flash else 1)
                except (OSError, ValueError, urllib.error.URLError):
                    self.erros += 1
                    proximo_envio = agora + espera_falha * self.sorteio.uniform(0.8, 1.2)
                    espera_falha = min(60.0, espera_falha * 2)
            time.sleep(0.2)
        # fim: a maquina para e o aparelho esvazia a flash (sem caos)
        self.proxima_troca = 0
        if self.ligado:
            self._maquina(time.time())
        for _ in range(40):
            if not self.flash:
                break
            try:
                self._enviar()
            except (OSError, ValueError, urllib.error.URLError):
                time.sleep(0.5)


def simular(url, mestra, banco, setores, aparelhos=50, segundos=300, intervalo_s=10, queda=(0.4, 0.6), semente=2026,
            log=print, troca=(2, 15)):
    """Roda a simulacao contra url (servidor ja no ar, com a mestra) e confere
    no banco. setores: slugs ja cadastrados; os aparelhos sao adotados 50 por
    setor (maquinas 1..50 - o limite e 64 por setor). Devolve um dict com os
    numeros."""
    if isinstance(setores, str):
        setores = [setores]
    import dispositivos
    sorteio = random.Random(semente)
    rede_fora = threading.Event()
    fim = time.time() + segundos
    lista = [AparelhoVirtual(url, mestra, n, fim, intervalo_s, rede_fora, random.Random(sorteio.random()),
                             relogio_errado_s=600 if n == 1 else 0, troca=troca) for n in range(1, aparelhos + 1)]
    for a in lista:  # 1o contato (registra como novo) e adocao
        dispositivos.registrar_contato(banco, a.id, "unitario")
        dispositivos.adotar(banco, a.id, setores[(a.numero - 1) // 50], (a.numero - 1) % 50 + 1, "simulador")
    for a in lista:
        a.start()
    inicio = time.time()
    if queda:
        time.sleep(max(0, segundos * queda[0]))
        log(f"  [caos] metade dos aparelhos sem rede (repetidor fora) aos {time.time() - inicio:.0f} s")
        rede_fora.set()
        time.sleep(max(0, segundos * (queda[1] - queda[0])))
        rede_fora.clear()
        log(f"  [caos] rede de volta aos {time.time() - inicio:.0f} s")
    for a in lista:
        a.join()
    tempos = sorted(t for a in lista for t in a.tempos)
    faltando = duplicados = 0
    for a in lista:
        no_banco = banco.ciclos_por_origem(a.id)
        gerados = set(a.gerados)
        faltando += len(gerados - set(no_banco))
        duplicados += sum(1 for _, n in no_banco.items() if n > 1)
    r = {
        "aparelhos": aparelhos, "segundos": round(time.time() - inicio),
        "ciclos_gerados": sum(len(a.gerados) for a in lista), "ciclos_no_banco": sum(banco.total_ciclos(s) for s in setores),
        "faltando": faltando, "duplicados": duplicados, "na_flash_no_fim": sum(len(a.flash) for a in lista),
        "pedidos": sum(a.pedidos for a in lista), "erros_rede": sum(a.erros for a in lista),
        "recusas_relogio": sum(a.recusas_relogio for a in lista),
        "resposta_mediana_ms": round(1000 * tempos[len(tempos) // 2], 1) if tempos else None,
        "resposta_p95_ms": round(1000 * tempos[int(len(tempos) * 0.95)], 1) if tempos else None,
        "resposta_max_ms": round(1000 * tempos[-1], 1) if tempos else None,
    }
    r["pedidos_por_s"] = round(r["pedidos"] / max(1, r["segundos"]), 1)
    return r


def main():
    p = argparse.ArgumentParser(description="Simulador de coletores (banco temporario).")
    p.add_argument("--aparelhos", type=int, default=50)
    p.add_argument("--minutos", type=float, default=5)
    p.add_argument("--intervalo", type=float, default=10, help="batimento em segundos (padrao 10)")
    a = p.parse_args()

    raiz = os.path.dirname(DIR)
    sys.path.insert(0, os.path.join(raiz, "app"))
    tmp = tempfile.mkdtemp(prefix="painel_simulador_")
    dados = os.path.join(tmp, "dados")
    os.makedirs(dados)
    with open(os.path.join(dados, "conexao.json"), "w", encoding="utf-8") as f:
        json.dump({"modo": "serial"}, f)  # o servidor nunca procura o ESP32 de verdade
    mestra = "simulador-" + os.urandom(8).hex()
    os.environ["COLETOR_CHAVE_MESTRA"] = mestra
    import caminhos
    caminhos.dir_dados_usuario = lambda: dados
    import servidor  # noqa: E402 (depois de apontar os dados para a pasta temporaria)
    import setores
    assert servidor.banco.caminho.startswith(tmp), "o simulador so roda com banco temporario"
    slugs = [setores.criar(servidor.banco, {"nome": f"Simulado {i + 1}", "tipoColeta": "unitario"})["setor"]
             for i in range((a.aparelhos + 49) // 50)]
    srv = servidor._ServidorExclusivo(("::1", 0), servidor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://[::1]:{srv.server_address[1]}/api/v2/coletor"
    print(f"Banco temporario: {servidor.banco.caminho}")
    print(f"{a.aparelhos} aparelhos por {a.minutos:g} min (batimento {a.intervalo:g} s)...")
    r = simular(url, mestra, servidor.banco, slugs, a.aparelhos, int(a.minutos * 60), a.intervalo)
    srv.shutdown()
    for k, v in r.items():
        print(f"  {k:<22} {v}")
    ok = r["faltando"] == 0 and r["duplicados"] == 0 and r["na_flash_no_fim"] == 0
    print("RESULTADO:", "OK - nenhum ciclo perdido nem duplicado" if ok else "FALHOU")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
