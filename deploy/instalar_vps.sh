#!/usr/bin/env bash
# Instala/atualiza o servidor do acesso remoto na VPS (Ubuntu/Debian).
#
# Uso, NA VPS, de dentro do clone do repositorio (ou do pacote extraido):
#     git pull --ff-only && sudo bash deploy/instalar_vps.sh
# Na primeira instalacao o script pede a NUVEM_CHAVE (sem mostrar na tela).
#
# Pode rodar de novo para atualizar: copia o codigo novo para /opt, mantem
# dados, senha e chave, e reinicia o servico. Nunca apaga /var/lib/painel-nuvem.
set -euo pipefail

ORIGEM="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO=/opt/painel-nuvem
DADOS=/var/lib/painel-nuvem

if [ "$(id -u)" -ne 0 ]; then echo "Rode com sudo."; exit 1; fi

echo "== Dependencias (python3 + pyserial)"
apt-get update -qq
apt-get install -y -qq python3 python3-serial

echo "== Usuario de sistema 'painel' (sem login)"
id painel >/dev/null 2>&1 || useradd --system --home-dir "$DADOS" --shell /usr/sbin/nologin painel

echo "== Codigo em $DESTINO"
mkdir -p "$DESTINO"
for pasta in app ferramentas painel; do
  rm -rf "${DESTINO:?}/$pasta"
  cp -r "$ORIGEM/$pasta" "$DESTINO/$pasta"
done
# segredos da fabrica nunca vao para a VPS
rm -f "$DESTINO/app/segredos_app.json" "$DESTINO/app/build_info.json"
rm -rf "$DESTINO/painel/_backup"
chown -R root:root "$DESTINO"
chmod -R a+rX "$DESTINO"

echo "== Dados em $DADOS (mantidos entre atualizacoes)"
mkdir -p "$DADOS"
chown painel:painel "$DADOS"
chmod 750 "$DADOS"

echo "== Chave (/etc/painel-nuvem.env)"
CHAVE="${1:-}"
if [ -z "$CHAVE" ] && [ ! -f /etc/painel-nuvem.env ]; then
  # pedida sem aparecer na tela nem ficar no historico do terminal
  read -rsp "Cole a NUVEM_CHAVE do .env da fabrica: " CHAVE; echo
  [ -n "$CHAVE" ] || { echo "Chave vazia."; exit 1; }
fi
if [ -n "$CHAVE" ]; then
  umask 077
  printf 'NUVEM_CHAVE=%s\n' "$CHAVE" > /etc/painel-nuvem.env
fi
chmod 600 /etc/painel-nuvem.env

echo "== Servico systemd"
cp "$ORIGEM/deploy/painel-nuvem.service" /etc/systemd/system/painel-nuvem.service
systemctl daemon-reload
systemctl enable painel-nuvem >/dev/null
systemctl restart painel-nuvem
sleep 2
systemctl --no-pager --lines=5 status painel-nuvem || true

echo
echo "Pronto. Proximos passos (uma vez):"
echo "  1) Caddy com HTTPS: deploy/Caddyfile  ->  /etc/caddy/Caddyfile ; sudo systemctl reload caddy"
echo "  2) Senha de acesso: definida no NOTEBOOK da fabrica (Configuracoes -> Acesso remoto); chega aqui sozinha"
echo "  3) Teste: https://santex.rexar.com.br  (tela de login com a senha)"
