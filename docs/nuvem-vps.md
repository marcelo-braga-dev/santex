# Acesso remoto pela VPS (app 1.2.0 + firmware 3.0)

Quem está **fora da rede da empresa** abre o painel em
**https://santex.rexar.com.br** — no navegador ou pelo programa
**`PainelSantexRemoto.exe`** — e entra com uma de duas senhas:

| Senha | Quem entra com ela pode |
|---|---|
| **Visualização** (mín. 8 caracteres) | só ver o painel |
| **Edição** (mín. 10, diferente da outra) | ver **e alterar** máquinas, metas, turnos, intervalos, calendário, vigências e cores — de forma permanente: a alteração chega ao computador da fábrica em até 15 s |

O **computador da fábrica é o mestre**: nunca pede senha, pode tudo, define
as duas senhas e **liga/desliga a edição remota** em
**⚙ Configurações → Acesso remoto**. Nada muda para quem está na empresa.
Detalhes em [Edição remota](#edição-remota-120).

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
| **Notebook (app)** | Continua sendo o **fornecedor principal** e o **mestre** na empresa (lê o ESP32 pela rede local, painel completo, edição sem senha). Quando ligado com internet, **troca a configuração com a VPS a cada 15 s** (manda o que mudou aqui, recebe o que foi editado lá) e envia **todo o histórico de ciclos** que ela ainda não tem. |
| **VPS** | Tem **banco próprio** com o histórico completo (o que o notebook enviou + o que o ESP32 manda direto, sem duplicar) e serve o painel para quem está fora: visualização ou edição, conforme a senha. Leitura do ESP32 e conexão **nunca** são controladas pela VPS. |

**Notebook como segunda fonte (1.7.0):** se o ESP32 não conseguir enviar
direto para a VPS, o app da fábrica (aberto) repassa o que lê dele pela rede
local — estado ao vivo das máquinas e ciclos novos, a cada 5 s enquanto durar a
falha. A VPS só usa o dado do notebook quando ele é mais novo que o último
envio direto do ESP32, e o painel remoto mostra **"Via computador da
fábrica"**. Com o ESP32 e o notebook sem enviar, aparece "Controlador sem
enviar".

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
   .\gerar\pacote_vps.ps1                       # gera distribuir\painel-nuvem-1.1.0.tar.gz (sem segredos)
   scp distribuir\painel-nuvem-1.1.0.tar.gz usuario@IP:~
   ssh usuario@IP "tar -xzf painel-nuvem-1.1.0.tar.gz"   # cria ~/painel-nuvem
   ```
   **Com o Claude Code na VPS**: `cd ~/painel-nuvem && claude` — o `CLAUDE.md`
   do pacote (no repositório: `vps/CLAUDE_VPS.md`) traz o levantamento, a
   instalação, as verificações e as regras de segurança (não mexer em outros
   sites, não mostrar a chave, não se trancar no firewall). Os passos abaixo
   são o mesmo roteiro feito à mão.
3. **Instalar o servidor** (na VPS):
   ```bash
   cd ~/painel-nuvem
   sudo bash vps/instalar.sh        # pede a NUVEM_CHAVE sem mostrar na tela
   ```
   Cria o usuário de sistema `painel`, o código em `/opt/painel-nuvem`, os
   dados em `/var/lib/painel-nuvem` e o serviço `painel-nuvem` (reinicia
   sozinho, fuso `America/Sao_Paulo`, escuta só em `127.0.0.1:8080`).
4. **HTTPS com o Caddy**:
   ```bash
   sudo apt install -y caddy          # Ubuntu 24.04 / Debian 12; em versões antigas, ver caddyserver.com/docs/install
   sudo cp vps/Caddyfile /etc/caddy/Caddyfile
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

## 3. Gravar o firmware 3.0 e gerar o `.exe`

**Ordem: VPS no ar primeiro (seção 2), firmware depois.** Com o 3.0 e a VPS
fora do ar, o ESP32 não libera a memória (guarda para a VPS): o notebook
continua recebendo tudo normalmente, mas se a VPS demorar mais de ~40 dias
para entrar no ar, ela só recebe os ciclos mais recentes.

1. **Antes de gravar**: deixe o app baixar tudo do ESP32 (painel sem "ciclos a
   baixar").
2. Grave o firmware pela Arduino IDE (o firmware 3.0 usa 93% da área de
   programa; esquema de partição padrão).
3. Rode `gerar\gerar.bat` (opção 1) e troque o `.exe` do computador da
   fábrica pelo `distribuir\PainelProducaoSantex-<versão>.exe`.

Na primeira vez com o 3.0, o ESP32 começa a enviar a partir do que ainda
está na memória dele; o histórico antigo continua só no notebook.

## 4. Conferir

| Onde | O que deve aparecer |
|---|---|
| Página do ESP32 (`http://<IP do ESP32>`) | "Acesso remoto (nuvem): enviando — último envio há X s" |
| Painel no notebook → **Controlador** | "Controlador → nuvem: em dia" e "Acesso remoto: configuração enviada para a nuvem hoje às …" |
| https://santex.rexar.com.br | pede login; barra inferior "Controlador enviando"; "🔒 Acesso remoto · somente leitura" |

## Edição remota (1.2.0)

**Definir as senhas** (no computador da fábrica): ⚙ Configurações → Acesso
remoto → preencha a senha de **visualização** e/ou a de **edição** → Salvar.
Elas chegam à VPS em segundos. Preencha só a que quiser trocar.

**Quem edita pela VPS** entra com a senha de edição: o painel mostra
"✏ Edição remota" e libera os mesmos popups do computador da fábrica, menos
a leitura do controlador e a conexão. O que for salvo:

1. grava na VPS na hora (com auditoria: quando, de onde, o quê);
2. os outros painéis abertos (na VPS e na fábrica) se atualizam sozinhos e
   avisam "Configuração atualizada por outro usuário";
3. o computador da fábrica recebe em até 15 s (sem internet, recebe quando voltar).

**Mesma coisa alterada nos dois lados ao mesmo tempo:** vale a alteração
**mais recente**; a outra pessoa vê um aviso no popup Acesso remoto
("Sua alteração em Turnos foi substituída por uma mais recente"). Itens
diferentes (ex.: uma máquina lá, a meta aqui) nunca se perdem.

**Trocar senhas pela VPS:** só quem entrou com a senha de edição, e
**redigitando a senha de edição atual** (uma sessão esquecida aberta não
basta). Trocar uma senha desconecta quem entrou com ela.

**Desligar a edição remota:** no computador da fábrica, desmarque "Permitir
que quem tem a senha de edição altere a configuração". Quem estava editando
é desconectado; a senha de visualização continua valendo. Nada do que se
faz pela VPS restringe o computador da fábrica.

**Últimas alterações:** o popup Acesso remoto lista quem/onde/quando/o quê
(computador da fábrica ou internet, com o IP).

Segurança: HTTPS; senhas só como hash (PBKDF2); papel (visualização/edição)
no cookie assinado; bloqueio após 10 senhas erradas em 10 min; edição exige
o cabeçalho `X-Painel-Edicao` e origem do próprio site (contra CSRF); a VPS
não aceita chamadas de outros sites (sem CORS).

## Programa para os computadores de fora (`Painel de Produção.exe`)

É só uma janela que abre https://santex.rexar.com.br — **não leva chave,
banco nem segredo**. O login fica guardado por 30 dias (perfil em
`%APPDATA%\PainelSantexRemoto`); sem internet mostra "Sem conexão com o
painel — Tentar de novo". Ícone com a marca da Santex (o "S" na elipse
vermelha do logo), gerado por `gerar/icone_remoto.py` em `remoto/icone.ico`.

**Download pelo próprio painel da VPS** — quem abre o painel no navegador de
um computador com Windows vê:
- na tela de login, o link "Aplicativo para Windows";
- no painel, um cartão "Painel no seu computador" (Baixar / Agora não — some
  por 30 dias) e o item fixo ⚙ Configurações → **Aplicativo para Windows**;
- ao baixar, uma janela com os 3 passos de instalação, incluindo o aviso do
  Windows SmartScreen ("Mais informações → Executar assim mesmo" — o programa
  não tem assinatura digital paga).

Nada disso aparece no celular, dentro do próprio programa nem no computador
da fábrica. Rotas públicas: `GET /app-remoto` (informações) e
`GET /app-remoto/PainelSantexRemoto.exe` (chega como "Painel de Produção.exe").

**Como o arquivo chega à VPS:** `gerar\gerar.bat` (opção 2) gera
`distribuir\Painel de Produção.exe` e, **só quando o código ou o ícone do
programa mudou**, publica a cópia em `vps/app-remoto/` (versionada no git).
Commit + push + deploy da VPS e pronto — o `vps/instalar.sh` instala em
`/opt/painel-nuvem/app-remoto/`. Para subir à mão (sem git), coloque
`PainelSantexRemoto.exe` (+ `PainelSantexRemoto.json` e `icone.png`) em
`/var/lib/painel-nuvem/app-remoto/` — essa pasta tem prioridade.

**Nunca copie o `PainelProducaoSantex-<versão>.exe` (o da fábrica) para fora:** ele
leva a chave da fábrica e tentaria ler o controlador.

## Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| ESP32: "a VPS recusou a chave" / notebook: "chave recusada pela VPS" | `NUVEM_CHAVE` diferente na VPS | `sudo nano /etc/painel-nuvem.env` com a chave do `.env` e `sudo systemctl restart painel-nuvem` |
| ESP32: "sem conexao com a VPS (connection refused / SSL)" | DNS, Caddy fora do ar, proxy da Cloudflare ligado ou relógio do ESP32 sem hora | conferir `https://santex.rexar.com.br` num navegador; nuvem cinza na Cloudflare; hora do controlador |
| Painel remoto: "A configuração ainda não chegou" | o notebook não abriu o app com internet desde a instalação | abrir o app no notebook uma vez |
| Painel remoto: "Via computador da fábrica" | o ESP32 não está conseguindo enviar direto; o notebook está repassando | nada urgente — os dados seguem ao vivo; ver o erro do ESP32 em Sincronização no notebook |
| Painel remoto: "Controlador sem enviar" | ESP32 sem enviar direto **e** app da fábrica fechado (ou sem internet) | abrir o app no notebook; os ciclos ficam guardados no ESP32 e chegam quando voltar |
| Senha de edição: "A edição remota está desligada no computador da fábrica" | interruptor desligado no Acesso remoto da fábrica | ligar lá, ou usar a senha de visualização |
| Alteração feita pela VPS não aparece na fábrica | app da fábrica fechado, sem internet ou ainda na 1.1.0 | abrir o app 1.2.0 com internet (a sincronização é a cada 15 s) |

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
sudo bash vps/instalar.sh      # mantém dados, senhas e chave; reinicia o serviço
```

Ou peça ao Claude Code, na pasta do clone: *"faça o deploy"* — o `CLAUDE.md`
da raiz manda seguir `vps/CLAUDE_VPS.md`, seção "Deploy de uma
atualização (git pull)", que inclui as verificações.

**Pelo pacote:** gere e copie de novo (passo 2.2), extraia por cima e rode
`sudo bash vps/instalar.sh` — mantém dados, senha e chave. Para
conferir a chave sem gravar nada: `POST /api/nuvem/ping` com o cabeçalho
`X-Chave-Nuvem` (responde `{"ok": true}` ou 403).
