# Instruções para o Claude Code na VPS — Painel de Produção (acesso remoto)

Você está numa **VPS de produção** que pode hospedar outros sites. Sua tarefa
é instalar e manter o servidor do **acesso remoto do Painel de Produção**
(app 1.1.0) em **https://santex.rexar.com.br**. Responda sempre em
**português do Brasil**, com comandos e resultados claros.

Este arquivo vem como `CLAUDE.md` na raiz do pacote `painel-nuvem-<versão>.tar.gz`,
gerado no notebook da fábrica por `deploy/empacotar_vps.ps1` (no repositório ele
se chama `deploy/CLAUDE_VPS.md`). Guia humano equivalente:
`docs/nuvem-vps.md`.

## O que é o sistema (para entender antes de mexer)

- Na fábrica, um **ESP32 (firmware 3.0)** lê 4 máquinas e **envia** ciclos e
  estado por HTTPS para `POST https://santex.rexar.com.br/api/nuvem/enviar`.
- O **notebook da fábrica** (app 1.1.0) é a fonte principal e envia a
  configuração (máquinas, metas, turnos) para `POST /api/nuvem/config`.
- Os dois enviam o cabeçalho `X-Chave-Nuvem` com a **NUVEM_CHAVE**.
- Nesta VPS roda o **mesmo servidor Python do app** em `PAINEL_MODO=nuvem`
  (`ferramentas/controle_leitura_server.py` → `app/servidor.py` +
  `ferramentas/nuvem.py`): guarda uma cópia em SQLite e serve o painel
  **somente leitura**, com **uma senha única** (tela de login só com senha,
  sessão de 30 dias em cookie assinado), atrás do servidor web com HTTPS.
  A senha é definida **no notebook** (⚙ Configurações → Acesso remoto) e
  chega aqui só como hash, junto com a configuração — **não existe cadastro
  de usuários na VPS**. Só biblioteca padrão do Python + `pyserial`.

| Item | Valor |
|---|---|
| Código | `/opt/painel-nuvem` (dono root) |
| Dados (banco, hash da senha, backups) | `/var/lib/painel-nuvem` (dono `painel`) — **nunca apagar** |
| Chave | `/etc/painel-nuvem.env` (`NUVEM_CHAVE=...`, root, 600) |
| Serviço | `painel-nuvem` (systemd), escuta só em `127.0.0.1:8080` |
| HTTPS | Caddy → `127.0.0.1:8080` (`deploy/Caddyfile`) |
| Logs | `journalctl -u painel-nuvem` |

## Regras que você NUNCA quebra

1. **Nunca mostre, imprima, registre nem copie a NUVEM_CHAVE** (nem em
   comandos com `echo`, nem em respostas). Para usá-la num teste, leia do
   arquivo dentro de um `sudo bash -c '. /etc/painel-nuvem.env; ...'` sem exibi-la.
2. **Senhas e a chave são digitadas pelo usuário, não por você.** Os comandos
   interativos (`instalar_vps.sh` na primeira vez) pedem entrada oculta:
   peça ao usuário para rodá-los ele mesmo digitando `! <comando>` no prompt
   do Claude Code. A senha do painel nem passa pela VPS em texto: é definida
   no notebook.
3. **Não quebre outros sites.** Antes de qualquer mudança em servidor web
   (nginx, Apache, Caddy existente), mostre o que existe, faça cópia
   (`sudo cp arquivo arquivo.bak-$(date +%F)`) e **peça confirmação**. Nunca
   pare, desinstale ou substitua um servidor web que já atende outros domínios.
4. **Firewall: nunca se tranque para fora.** Antes de habilitar o `ufw`,
   libere o SSH (`sudo ufw allow OpenSSH`, ou a porta SSH em uso). Nunca rode
   `ufw reset`, nunca feche a porta do SSH.
5. **Nunca apague** `/var/lib/painel-nuvem` (é a cópia dos dados de produção)
   nem `/etc/painel-nuvem.env`.
6. Peça confirmação antes de: reiniciar serviços que não sejam `painel-nuvem`
   e `caddy`, mexer em DNS/Cloudflare (isso é com o usuário), instalar
   repositórios externos de pacotes.
7. Não rode o servidor fora do systemd sem `PAINEL_MODO=nuvem` — sem ele o
   código tenta o modo da fábrica (porta 80, rede local).

## Passo 0 — Levantamento (só leitura, sempre primeiro)

```bash
cat /etc/os-release | head -3
python3 --version                      # precisa de 3.10 ou mais novo
sudo ss -ltnp | grep -E ':(80|443|8080)\b' || echo "80/443/8080 livres"
systemctl is-active nginx apache2 caddy lsws lshttpd 2>/dev/null
ls -d /usr/local/lsws /usr/local/CyberCP 2>/dev/null    # OpenLiteSpeed / CyberPanel
sudo ufw status verbose 2>/dev/null | head -20
getent hosts santex.rexar.com.br; curl -s -4 ifconfig.me; echo
```

Relate ao usuário: sistema, Python, quem usa 80/443, firewall e **se o DNS
aponta para o IP desta VPS**.

### Verificação obrigatória da Cloudflare

Se `santex.rexar.com.br` resolver para IPs da Cloudflare (`104.16.0.0/13`,
`104.24.0.0/14`, `172.64.0.0/13`, `188.114.96.0/20`, `162.158.0.0/15`…) em vez
do IP da VPS, **pare e avise o usuário**: o registro `santex` precisa ficar
**"Somente DNS" (nuvem cinza)** no painel da Cloudflare. Motivo (verificado
em 17/11/2026): com o proxy ligado a Cloudflare entrega certificado do Google
Trust Services (WE1 ← GTS Root R4), mas o ESP32 só confia na raiz da Let's
Encrypt (ISRG Root X1), e a proteção anti-robô da Cloudflare devolve
"error code: 1010" para clientes que não são navegador — o ESP32 nunca
conseguiria enviar. Sem isso resolvido, o resto funciona para navegadores,
mas não para o controlador.

## Passo 1 — Instalar/atualizar o servidor

O pacote já deve estar descompactado (ex.: `~/painel-nuvem`, com `app/`,
`ferramentas/`, `painel/`, `deploy/`). Na **primeira instalação** a chave
ainda não existe — peça ao usuário:

```
! cd ~/painel-nuvem && sudo bash deploy/instalar_vps.sh
```

(o script pede a NUVEM_CHAVE sem mostrar; ela está no `.env` do notebook da
fábrica). Nas **atualizações** você mesmo pode rodar
`sudo bash deploy/instalar_vps.sh` — ele mantém chave, dados e senha.

Confira:

```bash
systemctl is-active painel-nuvem
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/status   # esperado: 401 (pede login)
sudo journalctl -u painel-nuvem -n 20 --no-pager
```

## Passo 2 — HTTPS

**Situação verificada em 17/11/2026 (de fora):** `santex.rexar.com.br` →
`212.85.17.175`, sem proxy da Cloudflare; quem atende 80/443 é um
**LiteSpeed**, que já tem certificado Let's Encrypt válido para
`santex.rexar.com.br` (cadeia `YR1 ← Root YR ← ISRG Root X1`, enviada
completa — validada como o ESP32 faria, em TLS 1.2 e 1.3). Hoje ele responde
404 (vhost sem o painel). Portanto, **o caminho esperado é o do LiteSpeed**:
não instale o Caddy (brigaria pelas portas 80/443 com o LiteSpeed). Confirme
no Passo 0 antes.

Escolha conforme o levantamento (e confirme com o usuário):

- **LiteSpeed (OpenLiteSpeed / CyberPanel) já nas portas** → proxy reverso no
  vhost de `santex.rexar.com.br`, mantendo o certificado que ele já usa:
  1. Ache o arquivo do vhost: `sudo grep -ril 'santex.rexar.com.br' /usr/local/lsws/conf/vhosts/ /usr/local/lsws/conf/httpd_config.conf`
     (no CyberPanel costuma ser `/usr/local/lsws/conf/vhosts/santex.rexar.com.br/vhost.conf`).
  2. Faça cópia (`sudo cp vhost.conf vhost.conf.bak-$(date +%F)`), mostre ao
     usuário e, com a confirmação, acrescente ao vhost:
     ```
     extprocessor painel_nuvem {
       type                    proxy
       address                 127.0.0.1:8080
       maxConns                100
       initTimeout             60
       retryTimeout            0
       respBuffer              0
     }

     context / {
       type                    proxy
       handler                 painel_nuvem
       addDefaultCharset       off
     }
     ```
     Se o vhost já tiver um `context /` (site antigo no mesmo domínio), **pare
     e pergunte** — não substitua sem confirmação.
  3. Reinicie de forma suave: `sudo /usr/local/lsws/bin/lswsctrl restart`
     (ou pelo painel do CyberPanel/OpenLiteSpeed WebAdmin, em `:7080`).
  4. Confira: `curl -s -o /dev/null -w '%{http_code}\n' https://santex.rexar.com.br/status` → **401**
     (o painel pedindo login). Ainda 404 = o proxy não pegou; veja
     `/usr/local/lsws/logs/error.log`.
  5. Renovação do certificado: continua com o LiteSpeed/CyberPanel (Let's Encrypt). Não mexa.

- **80/443 livres** → Caddy:
  ```bash
  sudo apt install -y caddy     # Ubuntu 24.04 / Debian 12; mais antigos: caddyserver.com/docs/install
  sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
  sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
  ```
- **Caddy já serve outros sites** → acrescente o bloco `santex.rexar.com.br { ... }`
  de `deploy/Caddyfile` ao Caddyfile existente (com cópia antes), `caddy validate`, `reload`.
- **nginx já está nas portas** → crie um `server` só para `santex.rexar.com.br`
  com `proxy_pass http://127.0.0.1:8080;` e `proxy_set_header X-Forwarded-For $remote_addr;`
  (exemplo em `docs/nuvem-vps.md`), certificado Let's Encrypt com `certbot --nginx -d santex.rexar.com.br`,
  `nginx -t` antes de `reload`. O certificado **tem** que ser da Let's Encrypt.

Firewall (se o `ufw` estiver em uso): `sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp`.

## Passo 3 — Senha de acesso (é definida no notebook, não aqui)

Não há usuários para criar. Peça ao usuário para, **no notebook da fábrica**
(app 1.1.0), abrir **⚙ Configurações → Acesso remoto** e definir a senha. O
app envia o hash para cá em segundos. Confira sem ver a senha nem o hash:

```bash
sudo python3 -c "import sqlite3,json; r=sqlite3.connect('/var/lib/painel-nuvem/painel.db').execute(\"select valor from segredos where chave='acesso_remoto'\").fetchone(); print('senha definida:', bool(r), json.loads(r[0]).get('alterado_em') if r else '')"
```

Enquanto não chegar, a tela de login avisa "A senha do acesso remoto ainda
não foi definida". Nunca grave um hash na VPS por conta própria.

## Passo 4 — Conferir de ponta a ponta

```bash
# certificado: a cadeia precisa terminar na ISRG Root X1 (Let's Encrypt)
echo | openssl s_client -connect santex.rexar.com.br:443 -servername santex.rexar.com.br 2>/dev/null | grep -E '^ *[0-9] s:| i:'
# painel pede login pela internet (sem sessao: /status = 401; / = tela de login)
curl -s -o /dev/null -w '%{http_code}\n' https://santex.rexar.com.br/status          # esperado: 401
curl -s https://santex.rexar.com.br/ | grep -c 'Senha de acesso'                         # esperado: 1
# chave errada e recusada
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'X-Chave-Nuvem: errada' https://santex.rexar.com.br/api/nuvem/ping   # esperado: 403
# chave certa e aceita - /api/nuvem/ping nao grava nada; a chave nao aparece
sudo bash -c '. /etc/painel-nuvem.env; curl -s -X POST https://santex.rexar.com.br/api/nuvem/ping -H "X-Chave-Nuvem: $NUVEM_CHAVE"'   # esperado: {"ok": true, "versao": "1.1.0"}
```

Depois que o usuário gravar o firmware 3.0 e abrir o app 1.1.0 na fábrica:

```bash
sudo cat /var/lib/painel-nuvem/nuvem_status.json   # ultimo_contato recente, firmware 3.0, config_recebida_em
```

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `curl https://...` dá `error code: 1010` ou o certificado é "WE1 / GTS" | Proxy da Cloudflare ligado | Usuário deixa o registro em "Somente DNS" |
| Caddy não emite certificado | DNS ainda não aponta para a VPS, ou 80/443 bloqueadas | `getent hosts`, `ufw status`, `journalctl -u caddy` |
| ESP32/notebook: "chave recusada" | `NUVEM_CHAVE` diferente | Usuário roda `! sudo nano /etc/painel-nuvem.env` com a do `.env`; `sudo systemctl restart painel-nuvem` |
| `painel-nuvem` reiniciando | erro no código ou permissão | `journalctl -u painel-nuvem -n 50`; dono de `/var/lib/painel-nuvem` deve ser `painel` |
| Horários errados no painel | fuso | o serviço define `TZ=America/Sao_Paulo`; confira `systemctl show painel-nuvem -p Environment` |
| 429 no painel | 10 senhas/chaves erradas em 10 min daquele IP | esperar 10 min ou `sudo systemctl restart painel-nuvem` |
| Login: "senha ainda não foi definida" | o notebook não enviou a senha (sem internet, app antigo ou senha não definida) | no notebook: ⚙ Configurações → Acesso remoto; conferir "Enviada para a nuvem" |
| Todos foram desconectados | a senha foi trocada no notebook | entrar com a senha nova (comportamento esperado) |

## Desfazer (sem perder dados)

```bash
sudo systemctl disable --now painel-nuvem
# remover o bloco santex.rexar.com.br do Caddy/nginx (restaurar o .bak) e recarregar
```

`/var/lib/painel-nuvem` fica intacto para uma reinstalação.

## Ao terminar

Resuma para o usuário: o que foi instalado, o resultado de cada verificação do
Passo 4, se a senha de acesso já chegou do notebook e o que falta do lado da fábrica
(gravar o firmware 3.0 **depois** da VPS no ar e instalar o app 1.1.0).
