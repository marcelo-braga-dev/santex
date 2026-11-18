# Acesso remoto pela VPS (app 1.1.0 + firmware 3.0)

Quem está **fora da rede da empresa** abre o painel em
**https://santex.rexar.com.br** com **uma senha única**, somente para
visualizar. A senha é definida e trocada no notebook da fábrica, em
**⚙ Configurações → Acesso remoto** (o notebook guarda e envia só o hash). Nada muda para quem está na empresa.

```
                 rede da empresa                              internet
  ┌──────────────────────────────────────────┐
  │ ESP32 (firmware 3.0) ──rede local──► Notebook (app)        │
  │   │  lê os relés, guarda os ciclos       fornecedor principal│
  │   │                                      edita a configuração│
  └───┼──────────────────────────────────────┼─────────────────┘
      │ HTTPS: ciclos + estado (a cada 10 s)  │ HTTPS: configuração
      ▼                                       ▼
  ┌────────────────── VPS santex.rexar.com.br ──────────────────┐
  │ Caddy (HTTPS) ─► servidor em modo nuvem ─► banco (cópia)    │
  └──────────────────────────────┬──────────────────────────────┘
                                 ▼ login, somente leitura
                      computadores e celulares de fora
```

| Quem | Faz o quê |
|---|---|
| **ESP32** | Continua respondendo ao notebook na rede local e **também envia** os ciclos e o estado das máquinas para a VPS, sozinho, a cada ~10 s. Funciona com o notebook desligado. |
| **Notebook (app)** | Continua sendo o **fornecedor principal** na empresa (lê o ESP32 pela rede local, painel completo, edição). Quando ligado com internet, envia para a VPS a **configuração** (máquinas, metas, turnos, cores, hash da senha) e **todo o histórico de ciclos** que ela ainda não tem — a VPS fica com o mesmo histórico do notebook. |
| **VPS** | Tem **banco próprio** com o histórico completo (o que o notebook enviou + o que o ESP32 manda direto, sem duplicar) e serve o painel para quem está fora, **sempre somente leitura**, com a senha. |

Se a internet da empresa ou a VPS cair, o ESP32 guarda os ciclos (até ~20.000)
e envia o que faltou quando a conexão voltar. Ele só libera um ciclo da
memória depois que a VPS **e** o notebook o receberam.

## 1. Preparar a fábrica (`.env`)

No `.env` da raiz do projeto (já preenchido nesta máquina):

```
NUVEM_URL=https://santex.rexar.com.br
NUVEM_CHAVE=<gerada sozinha por gerar_segredos.py>
```

Depois: `python ferramentas/gerar_segredos.py` — atualiza o `segredos.h` do
firmware e o `app/segredos_app.json` do `.exe`. **Firmware, `.exe` e VPS usam
a mesma `NUVEM_CHAVE`.**

## 2. Preparar a VPS (uma vez)

Requisitos: Ubuntu 22.04/24.04 ou Debian 12, acesso SSH com `sudo`, portas
80 e 443 livres (ou um servidor web já existente — ver "Se a VPS já tem nginx").

1. **DNS — obrigatório: "Somente DNS" (nuvem cinza) na Cloudflare.** ✅ Feito
   em 17/11/2026 (agora resolve para 212.85.17.175). Antes, `santex.rexar.com.br`
   estava com o **proxy da Cloudflare ligado**
   (resolve para 104.21.7.220 / 172.67.156.123). Assim o ESP32 **nunca**
   conseguiria enviar: a Cloudflare entrega certificado do Google Trust
   Services (WE1 ← GTS Root R4), mas o ESP32 só confia na Let's Encrypt
   (`firmware/controle_producao_horimetro/certificados.h`), e a proteção
   anti-robô dela responde `error code: 1010` a quem não é navegador. No
   painel da Cloudflare: registro **A** `santex` → **IP da VPS**, proxy
   **desligado** (nuvem cinza).
2. **Montar e copiar o pacote** (PowerShell, na raiz do projeto, no notebook;
   troque `usuario@IP`):
   ```powershell
   .\deploy\empacotar_vps.ps1                       # gera dist-vps\painel-nuvem-1.1.0.tar.gz (sem segredos)
   scp dist-vps\painel-nuvem-1.1.0.tar.gz usuario@IP:~
   ssh usuario@IP "tar -xzf painel-nuvem-1.1.0.tar.gz"   # cria ~/painel-nuvem
   ```
   **Com o Claude Code na VPS**: `cd ~/painel-nuvem && claude` — o `CLAUDE.md`
   do pacote (no repositório: `deploy/CLAUDE_VPS.md`) traz o levantamento, a
   instalação, as verificações e as regras de segurança (não mexer em outros
   sites, não mostrar a chave, não se trancar no firewall). Os passos abaixo
   são o mesmo roteiro feito à mão.
3. **Instalar o servidor** (na VPS):
   ```bash
   cd ~/painel-nuvem
   sudo bash deploy/instalar_vps.sh        # pede a NUVEM_CHAVE sem mostrar na tela
   ```
   Cria o usuário de sistema `painel`, o código em `/opt/painel-nuvem`, os
   dados em `/var/lib/painel-nuvem` e o serviço `painel-nuvem` (reinicia
   sozinho, fuso `America/Sao_Paulo`, escuta só em `127.0.0.1:8080`).
4. **HTTPS com o Caddy**:
   ```bash
   sudo apt install -y caddy          # Ubuntu 24.04 / Debian 12; em versões antigas, ver caddyserver.com/docs/install
   sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```
5. **Senha de acesso**: não é criada na VPS. No notebook da fábrica, em
   **⚙ Configurações → Acesso remoto**, defina a senha; ela chega à VPS em
   segundos (junto com a configuração). Para trocar, é só definir outra —
   quem estiver conectado na VPS precisa entrar de novo.
6. **Firewall**: `sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`.

### Se a VPS já tem LiteSpeed (OpenLiteSpeed / CyberPanel) — o caso desta VPS

Verificado de fora em 17/11/2026: `santex.rexar.com.br` → `212.85.17.175`
(Cloudflare em "Somente DNS" ✅), atendido por **LiteSpeed** com certificado
Let's Encrypt já válido (cadeia completa até a ISRG Root X1, aceita pelo
ESP32 em TLS 1.2 e 1.3). **Não instale o Caddy** (as portas 80/443 são do
LiteSpeed). No vhost de `santex.rexar.com.br` (CyberPanel:
`/usr/local/lsws/conf/vhosts/santex.rexar.com.br/vhost.conf`; faça cópia antes):

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

Depois `sudo /usr/local/lsws/bin/lswsctrl restart` e confira:
`https://santex.rexar.com.br/status` deve responder **401** (pede login).

### Se a VPS já tem nginx

Em vez do Caddy, um `server` para `santex.rexar.com.br` com certificado da
Let's Encrypt (certbot) e:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Host $host;
}
```

## 3. Gravar o firmware 3.0 e gerar o `.exe` 1.1.0

**Ordem: VPS no ar primeiro (seção 2), firmware depois.** Com o 3.0 e a VPS
fora do ar, o ESP32 não libera a memória (guarda para a VPS): o notebook
continua recebendo tudo normalmente, mas se a VPS demorar mais de ~40 dias
para entrar no ar, ela só recebe os ciclos mais recentes.

1. **Antes de gravar**: deixe o app baixar tudo do ESP32 (painel sem "ciclos a
   baixar").
2. Grave o firmware pela Arduino IDE (o firmware 3.0 usa 93% da área de
   programa; esquema de partição padrão).
3. Rode `app\gerar_executavel.bat` e troque o `.exe`.

Na primeira vez com o 3.0, o ESP32 começa a enviar a partir do que ainda
está na memória dele; o histórico antigo continua só no notebook.

## 4. Conferir

| Onde | O que deve aparecer |
|---|---|
| Página do ESP32 (`http://<IP do ESP32>`) | "Acesso remoto (nuvem): enviando — último envio há X s" |
| Painel no notebook → **Controlador** | "Controlador → nuvem: em dia" e "Acesso remoto: configuração enviada para a nuvem hoje às …" |
| https://santex.rexar.com.br | pede login; barra inferior "Controlador enviando"; "🔒 Acesso remoto · somente leitura" |

## Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| ESP32: "a VPS recusou a chave" / notebook: "chave recusada pela VPS" | `NUVEM_CHAVE` diferente na VPS | `sudo nano /etc/painel-nuvem.env` com a chave do `.env` e `sudo systemctl restart painel-nuvem` |
| ESP32: "sem conexao com a VPS (connection refused / SSL)" | DNS, Caddy fora do ar, proxy da Cloudflare ligado ou relógio do ESP32 sem hora | conferir `https://santex.rexar.com.br` num navegador; nuvem cinza na Cloudflare; hora do controlador |
| Painel remoto: "A configuração ainda não chegou" | o notebook não abriu o app com internet desde a instalação | abrir o app no notebook uma vez |
| Painel remoto: "Controlador sem enviar" | ESP32 desligado ou sem internet | os ciclos ficam guardados nele e chegam quando voltar |

Logs na VPS: `journalctl -u painel-nuvem -f`. Backups diários do banco da
VPS: `/var/lib/painel-nuvem/backups/` (o notebook continua sendo a cópia
principal).

## Atualizar a VPS depois (deploy)

**Pelo git (caminho usado hoje):** na VPS, dentro do clone do repositório
(`git clone https://github.com/marcelo-braga-dev/santex.git ~/santex` na
primeira vez — o repositório é público, não pede login):

```bash
cd ~/santex
git pull --ff-only
sudo bash deploy/instalar_vps.sh      # mantém dados, senha e chave; reinicia o serviço
```

Ou peça ao Claude Code, na pasta do clone: *"faça o deploy"* — o `CLAUDE.md`
da raiz manda seguir `deploy/CLAUDE_VPS.md`, seção "Deploy de uma
atualização (git pull)", que inclui as verificações.

**Pelo pacote:** gere e copie de novo (passo 2.2), extraia por cima e rode
`sudo bash deploy/instalar_vps.sh` — mantém dados, senha e chave. Para
conferir a chave sem gravar nada: `POST /api/nuvem/ping` com o cabeçalho
`X-Chave-Nuvem` (responde `{"ok": true}` ou 403).
