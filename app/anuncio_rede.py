"""
Anuncia o painel na rede local com um nome fixo - http://painel.local -
para os outros computadores e celulares abrirem sem digitar IP nem porta.

Usa mDNS (o mesmo mecanismo com que impressoras e TVs aparecem sozinhas
na rede): responde "painel.local = <IP deste PC>" a quem perguntar.
Funciona no Windows 10/11, iPhone/Mac e na maioria dos Android recentes,
sem configurar nada no roteador. Se o IP do PC mudar (roteador reiniciou,
trocou de rede), o anuncio e atualizado sozinho em ate 1 minuto.

Falha aqui nunca derruba o painel: sem o anuncio, o acesso pelo IP
(http://<IP-do-PC>/) continua funcionando.
"""

import logging
import socket
import threading

NOME_REDE = "painel"  # -> http://painel.local
INTERVALO_VERIFICA_IP_S = 60

log = logging.getLogger("painel")


def _ips_locais():
    """IPv4 deste PC nas redes locais (sem loopback nem 169.254.x.x)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # IP da rota padrao (o que os outros PCs enxergam), mesmo sem DNS do nome
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # nao envia nada, so escolhe a interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.", "0.")))


class AnuncioRede:
    def __init__(self, porta):
        self.porta = porta
        self._zc = None
        self._info = None
        self._ips = []
        self._parar = threading.Event()
        self._thread = None

    def iniciar(self):
        try:
            from zeroconf import IPVersion, Zeroconf  # noqa: F401 (falha cedo se faltar)
        except ImportError:
            log.warning("Anuncio painel.local indisponivel: biblioteca zeroconf ausente")
            return
        self._thread = threading.Thread(target=self._rodar, name="anuncio-rede", daemon=True)
        self._thread.start()

    def _montar_info(self, ips):
        from zeroconf import ServiceInfo
        return ServiceInfo(
            "_http._tcp.local.",
            f"Painel de Producao ({socket.gethostname()})._http._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in ips],
            port=self.porta,
            properties={"path": "/"},
            server=f"{NOME_REDE}.local.",
        )

    def _rodar(self):
        from zeroconf import IPVersion, Zeroconf
        try:
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
        except Exception:  # noqa: BLE001
            log.exception("Anuncio painel.local: nao foi possivel abrir o mDNS")
            return
        if self._parar.is_set():  # o app fechou enquanto abria
            self._zc.close()
            return
        while not self._parar.is_set():
            try:
                ips = _ips_locais()
                if ips and ips != self._ips:
                    novo = self._montar_info(ips)
                    if self._info is None:
                        # allow_name_change: se outro PC ja usa o mesmo nome de servico, nao falha
                        self._zc.register_service(novo, allow_name_change=True)
                    else:
                        novo = self._montar_info(ips)
                        novo.name = self._info.name
                        self._zc.update_service(novo)
                    self._info, self._ips = novo, ips
                    log.info("Painel anunciado na rede: http://%s.local (IP %s)", NOME_REDE, ", ".join(ips))
            except Exception:  # noqa: BLE001 - tenta de novo na proxima volta
                log.exception("Anuncio painel.local: falha ao anunciar")
            self._parar.wait(INTERVALO_VERIFICA_IP_S)

    def parar(self):
        self._parar.set()
        zc, self._zc = self._zc, None
        if zc is None:
            return
        try:
            if self._info is not None:
                zc.unregister_service(self._info)
            zc.close()
        except Exception:  # noqa: BLE001
            pass
