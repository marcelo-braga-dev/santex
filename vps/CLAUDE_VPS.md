# Instruções para o Claude Code na VPS — Painel de Produção (acesso remoto)

Você está numa **VPS de produção** que pode hospedar outros sites. Sua tarefa
é instalar e manter o servidor do **acesso remoto do Painel de Produção**
(app 1.2.0) em **https://santex.rexar.com.br**. Responda sempre em
**português do Brasil**, com comandos e resultados claros.

O código chega à VPS de dois jeitos: **clone do repositório**
(`https://github.com/marcelo-braga-dev/santex`, atualizado com `git pull` —
o caminho usado hoje; este arquivo é `vps/CLAUDE_VPS.md`, e o `CLAUDE.md`
da raiz aponta para cá) ou o pacote `painel-nuvem-<versão>.tar.gz` (este
arquivo vira o `CLAUDE.md` dele). Guia humano equivalente: `docs/nuvem-vps.md`.

**Pedido mais comum: "faça o deploy" depois de um `git pull`** → vá direto
para a seção **"Deploy de uma atualização (git pull)"**, logo abaixo das regras.

## O que é o sistema (para entender antes de mexer)

- Na fábrica, um **ESP32 (firmware 3.0)** lê 4 máquinas e **envia** ciclos e
  estado por HTTPS para `POST https://santex.rexar.com.br/api/nuvem/enviar`.
- O **notebook da fábrica** (app 1.2.0) é a fonte principal e o **mestre**:
  a cada 15 s troca a configuração com a VPS nas duas mãos
  (`POST /api/nuvem/config`, `"versao": 2` — manda o que mudou lá, recebe o
  que foi editado aqui) e envia **todo o histórico de ciclos** que a VPS
  ainda não tem para `POST /api/nuvem/historico` (lotes de 500, sem duplicar).
- Os dois enviam o cabeçalho `X-Chave-Nuvem` com a **NUVEM_CHAVE**.
- Nesta VPS roda o **mesmo servidor Python do app** em `PAINEL_MODO=nuvem`
  (`ferramentas/controle_leitura_server.py` → `app/servidor.py` +
  `ferramentas/nuvem.py`): guarda uma cópia em SQLite e serve o painel com
  **duas senhas** (tela de login só com senha, sessão de 30 dias em cookie
  assinado com o papel): **visualização** (só vê) e **edição** (altera
  máquinas, metas, turnos, calendário… e essas edições vão para o notebook).
  As senhas são definidas no notebook (⚙ Configurações → Acesso remoto) e
  chegam só como hash; quem tem a de edição também pode trocá-las aqui,
  redigitando a atual. O notebook pode desligar a edição remota. Leitura do
  ESP32 e conexão **nunca** são controláveis pela VPS. Auditoria de toda
  alteração na tabela `alteracoes`. **Não existe cadastro de usuários na
  VPS.** Só biblioteca padrão do Python + `pyserial`.

| Item | Valor |
|---|---|
| Código | `/opt/painel-nuvem` (dono root) |
| Dados (banco, hash da senha, backups) | `/var/lib/painel-nuvem` (dono `painel`) — **nunca apagar** |
| Chave | `/etc/painel-nuvem.env` (`NUVEM_CHAVE=...`, root, 600) |
| Serviço | `painel-nuvem` (systemd), escuta só em `127.0.0.1:8080` |
| HTTPS | **LiteSpeed** desta VPS (proxy no vhost de `santex.rexar.com.br`, certificado Let's Encrypt dele) → `127.0.0.1:8080`. Caddy/nginx só numa VPS sem LiteSpeed |
| Logs | `journalctl -u painel-nuvem` |

## Regras que você NUNCA quebra

1. **Nunca mostre, imprima, registre nem copie a NUVEM_CHAVE** (nem em
   comandos com `echo`, nem em respostas). Para usá-la num teste, leia do
   arquivo dentro de um `sudo bash -c '. /etc/painel-nuvem.env; ...'` sem exibi-la.
2. **Senhas e a chave são digitadas pelo usuário, não por você.** Os comandos
   interativos (`instalar.sh` na primeira vez) pedem entrada oculta:
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

## Deploy de uma atualização (git pull) — o caso mais comum

**Estado em 18/11/2026:** **1.2.0 instalada e funcionando** — serviço
`painel-nuvem` ativo, LiteSpeed fazendo o proxy de `santex.rexar.com.br`
para `127.0.0.1:8080`, `NUVEM_CHAVE` em `/etc/painel-nuvem.env`, ESP32
(firmware 3.0) e notebook 1.2.0 sincronizando, senhas de visualização e de
edição já recebidas, edição remota testada em produção.
**Não refaça os Passos 0–3 nem mexa no LiteSpeed** num deploy comum: só
atualize o código e verifique.

**Proxy do LiteSpeed (aaPanel, ajustado em 18/11/2026)** — as regras ficam em
`/www/server/panel/vhost/openlitespeed/proxy/santex.rexar.com.br/urlrewrite/*.conf`
(a pasta do site no aaPanel é `/www/wwwroot/santex/painel`):
```
RewriteCond %{SERVER_PORT} !^443$
RewriteCond %{REQUEST_URI} !^/\.well-known/acme-challenge/
RewriteRule ^/(.*)$ https://santex.rexar.com.br/$1 [R=301,L]
RewriteCond %{REQUEST_URI} !^/\.well-known/acme-challenge/
RewriteRule ^/(.*)$ http://proxy_42fc7/$1 [P,E=Proxy-Host:$host]
```
Sem a exceção do `acme-challenge`, a renovação automática do certificado
Let's Encrypt (cron do aaPanel, 16:11, a partir de 31 dias do vencimento)
cai no Python e falha — o certificado vence e o **ESP32 para de enviar**.
O "Force HTTPS" do aaPanel sozinho não funciona aqui (a regra do proxy roda
antes dele). **Se alguém editar o proxy pela tela do aaPanel, ele regrava esse
arquivo: confira e reponha as regras.** Teste rápido:
`curl -s -o /dev/null -w '%{http_code}\n' http://santex.rexar.com.br/` → `301`;
um arquivo em `/www/wwwroot/santex/painel/.well-known/acme-challenge/` precisa
abrir por `http://` (200). Recarregar: `/usr/local/lsws/bin/lswsctrl restart`
(suave, não derruba os outros sites).

**1.7.5** (deploy seguinte ao 1.7.4): só o painel (Configurações em abas e
histórico de notificações enxuto). Deploy comum; o `ping` responde `"versao": "1.7.5"`.

**1.7.4** (deploy seguinte ao 1.7.3): só o notebook muda (atualizar o firmware
do ESP32 pelo painel; na VPS o painel fica escondido). Deploy comum; o `ping`
responde `"versao": "1.7.4"`.

**1.7.3** (deploy seguinte ao 1.7.2): só o painel (diagnóstico mostra o modelo
do RTC, DS3231 ou DS1302, do firmware 3.2). Deploy comum; o `ping` responde
`"versao": "1.7.3"`.

**1.7.2** (deploy seguinte ao 1.7.1): só o notebook muda (guarda o texto das
senhas de acesso remoto para consulta; a VPS continua só com o hash). Deploy
comum; o `ping` responde `"versao": "1.7.2"`.

**1.7.1** (deploy seguinte ao `181bf94`): a VPS completa a hora dos ciclos que
o ESP32 enviou sem hora (`SEM_HORA`) quando o notebook manda o mesmo ciclo
com hora - `UPDATE` só nesses ciclos (data/hora e obs; máquina, ciclo e
duração precisam bater). O notebook 1.7.1 reenvia o histórico uma vez
(sem duplicar). Corrige os 55 ciclos de 23/11/2026 07:06-08:11. Deploy comum;
o `ping` responde `"versao": "1.7.1"`.

**1.7.0** (deploy seguinte ao `1b68143`): o notebook vira segunda fonte do
estado ao vivo (campo `ao_vivo` em `/api/nuvem/historico`; `/sincronizacao`
ganha `fonte`). Deploy comum; o `ping` responde `"versao": "1.7.0"`.

**1.6.0** (deploy seguinte ao `b92ed2d`): só o painel — histórico de paradas
e parada registrada (retroativa). Deploy comum; o `ping` responde
`"versao": "1.6.0"`.

**1.5.2** (deploy seguinte ao `8816ecc`): só o painel — filtros fixos e aviso
no rodapé. Deploy comum; o `ping` responde `"versao": "1.5.2"`.

**1.5.1** (deploy seguinte ao `24aceb3`): só o painel — alerta de máquina
parada mais discreto na Visão geral. Deploy comum; o `ping` responde `"versao": "1.5.1"`.

**1.5.0** (deploy seguinte ao `9be70b5`): painel com máquinas Com/Sem
produção e a chave nova `extras:semProducao` na sincronização (sem tabela nova).
Deploy comum (passos 1–3); o `ping` responde `"versao": "1.5.0"`.

**1.4.0** (deploy seguinte ao `eccb2ca`): só o painel — aba **Relatórios**
(Excel e PDF) e menu ⚙ com rolagem. Três bibliotecas novas em `painel/assets`
(`exceljs.min.js`, `jspdf.umd.min.js`, `jspdf.plugin.autotable.min.js`) — o
`vps/instalar.sh` já copia a pasta inteira. Deploy comum (passos 1–3); o `ping`
responde `"versao": "1.4.0"`. O **logo da empresa** (Identidade visual) passa a
sincronizar (`extras:logo`) e a VPS o entrega em `/assets/logo.png` e
`/assets/icone-empresa.png` (liberados sem login, como antes o logo). Conferir: `curl -sI https://santex.rexar.com.br/assets/exceljs.min.js`
→ `401` sem login (o painel e os arquivos só depois do login) — é o esperado.

**1.3.1** (deploy seguinte ao `128b67c`): só o painel — saem o mapa de calor e o
Pareto de motivos do Desempenho. Deploy comum (passos 1–3); o `ping` responde `"versao": "1.3.1"`.

**1.3.0** (deploy seguinte ao `d516dcf`): painel novo (motivos de parada,
evolução, disciplina de turno, alerta, modo TV, relatório, taxa em m/h) e a
chave nova `extras:motivos` na sincronização. **Sem tabela nova** (os motivos
ficam em `config_extra`). Deploy comum (passos 1–3); o `ping` responde
`"versao": "1.3.0"`. Enquanto a VPS estiver na 1.2.x, os motivos marcados
no notebook não sobem (o resto sincroniza normalmente).

**1.2.1** (deploy seguinte ao `74602d6`): só o painel (`painel/index.html`)
mudou — tooltips de tempo parado e horário dos turnos na linha do tempo. Sem
mudança no banco nem no `vps/app-remoto/`. Deploy comum (passos 1–3); o
`ping` passa a responder `"versao": "1.2.1"`.

**Aplicativo para Windows no painel** (deploy seguinte ao `e31fc87`): o
`vps/instalar.sh` passa a copiar `vps/app-remoto/` (o `PainelSantexRemoto.exe`
— programa sem segredos — + `.json` + `icone.png`) para
`/opt/painel-nuvem/app-remoto/`; o painel oferece o download em
`/app-remoto/PainelSantexRemoto.exe`. Verificação:
`curl -s https://santex.rexar.com.br/app-remoto` → `{"disponivel": true, ...}` e
`curl -sI https://santex.rexar.com.br/app-remoto/PainelSantexRemoto.exe` → `200`
com `Content-Disposition: attachment`. Arquivo enviado à mão em
`/var/lib/painel-nuvem/app-remoto/` tem prioridade.

**Revisão final da 1.2.0** (deploy seguinte ao `3d3166f`): a VPS passa a
enviar cabeçalhos de proteção (`X-Frame-Options: DENY`, `nosniff`,
`Referrer-Policy`, HSTS) e o bloqueio por senhas erradas usa o **último**
IP do `X-Forwarded-For` (o que o LiteSpeed acrescenta). Verificação extra:
`curl -sI https://santex.rexar.com.br/ | grep -i x-frame-options` →
`X-Frame-Options: DENY`. Se o LiteSpeed já mandar algum desses cabeçalhos,
pode aparecer duplicado — inofensivo.

**Mudanças da 1.2.0** (este deploy):
- A pasta de instalação mudou: **`deploy/` virou `vps/`** e o instalador é
  **`vps/instalar.sh`** (antes `deploy/instalar_vps.sh`). O serviço, os dados
  e a chave continuam onde estavam.
- Edição remota (senha de edição), sincronização da configuração nas duas
  mãos, auditoria. O banco ganha as tabelas `config_rev` e `alteracoes`
  sozinho ao iniciar (mudança só aditiva — nada é apagado).
- Os logins abertos na 1.1.0 caem uma vez (o cookie agora leva o papel):
  as pessoas entram de novo com a mesma senha.
- Pode ser instalada antes ou depois do `.exe` 1.2.0 no notebook: a VPS
  aceita o formato antigo sem desfazer edições feitas aqui.

1. **Conferir o clone** (na pasta do repositório, ex. `~/santex`):
   ```bash
   git status --short            # precisa estar vazio; se não, MOSTRE e pergunte antes de seguir
   git log --oneline -1          # anote o commit atual (para desfazer, se preciso)
   git pull --ff-only
   git log --oneline -5
   grep -m1 '^APP_VERSAO' app/servidor.py
   ```
   `git pull` recusado (histórico divergente)? Pare e pergunte — nunca use `--force` nem `reset --hard` sem confirmação.
2. **Instalar o código novo** (mantém `/etc/painel-nuvem.env`, `/var/lib/painel-nuvem` e a senha; reinicia o serviço):
   ```bash
   sudo bash vps/instalar.sh
   ```
3. **Verificar** (todos precisam bater):
   ```bash
   systemctl is-active painel-nuvem                                                       # active
   sudo journalctl -u painel-nuvem -n 20 --no-pager                                       # sem Traceback
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/status                  # 401
   curl -s -o /dev/null -w '%{http_code}\n' https://santex.rexar.com.br/status             # 401
   curl -s https://santex.rexar.com.br/ | grep -c 'Senha de acesso'                         # 1
   sudo bash -c '. /etc/painel-nuvem.env; curl -s -X POST https://santex.rexar.com.br/api/nuvem/ping -H "X-Chave-Nuvem: $NUVEM_CHAVE"'
   #   -> {"ok": true, "versao": "1.7.5"}
   sudo bash -c '. /etc/painel-nuvem.env; curl -s -X POST https://santex.rexar.com.br/api/nuvem/historico -H "Content-Type: application/json" -H "X-Chave-Nuvem: $NUVEM_CHAVE" -d "{\"ciclos\": []}"'
   #   -> {"ok": true, "gravados": 0, "total": N}   (N = ciclos que a VPS tem; a rota nova existe)
   ```
   A chave não aparece na tela em nenhum desses comandos — mantenha assim.
4. **Histórico e configuração chegando** (depois que o notebook estiver com
   o `.exe` 1.2.0): repita o último comando do passo 3 — o `total` acompanha
   o do notebook (≈ 4.200+ ciclos em 18/11/2026). Para acompanhar sem expor nada:
   ```bash
   sudo python3 -c "import sqlite3; c=sqlite3.connect('file:/var/lib/painel-nuvem/painel.db?mode=ro', uri=True); print('ciclos:', c.execute('select count(*) from ciclos').fetchone()[0]); print('revisoes da configuracao:', c.execute('select count(*), coalesce(max(rev),0) from config_rev').fetchone()); print('ultimas alteracoes:', c.execute('select quando, origem, chave from alteracoes order by id desc limit 5').fetchall())"
   ```
   `config_rev` com linhas = o notebook 1.2.0 já sincronizou a configuração.
5. **Se algo falhar**: veja `journalctl -u painel-nuvem -n 50`. Para voltar
   ao código anterior: `git checkout <commit anotado no passo 1>` e
   `sudo bash vps/instalar.sh` (os dados não são afetados); depois
   `git checkout main` quando corrigido.
6. **Relate ao usuário**: commit instalado, resultado de cada verificação e
   o `total` de ciclos na VPS.

## Passo 0 — Levantamento (só leitura, sempre primeiro)

Para uma **instalação do zero** (os Passos 0–4). Num deploy comum, use a
seção acima.

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
`ferramentas/`, `painel/`, `vps/`). Na **primeira instalação** a chave
ainda não existe — peça ao usuário:

```
! cd ~/painel-nuvem && sudo bash vps/instalar.sh
```

(o script pede a NUVEM_CHAVE sem mostrar; ela está no `.env` do notebook da
fábrica). Nas **atualizações** você mesmo pode rodar
`sudo bash vps/instalar.sh` — ele mantém chave, dados e senha.

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
  sudo cp vps/Caddyfile /etc/caddy/Caddyfile
  sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
  ```
- **Caddy já serve outros sites** → acrescente o bloco `santex.rexar.com.br { ... }`
  de `vps/Caddyfile` ao Caddyfile existente (com cópia antes), `caddy validate`, `reload`.
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
