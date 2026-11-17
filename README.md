# Controle de Produção — Horímetro Multi-Setor

Monitoramento de horímetro (tempo ligado/parado, rendimento e produção) de
máquinas a partir de um ESP32 lendo os contatos secos dos relés de
sinalização de cada uma. O ESP32 guarda os ciclos na própria flash (com
data/hora do RTC) e o **aplicativo desktop** busca tudo pelo Wi-Fi, grava
num banco SQLite e mostra o **painel de produção** — no próprio notebook e
em qualquer computador/celular da rede (`http://painel.local`).

O painel já foi pensado para múltiplos **setores** (cada um com suas
máquinas e dados isolados); por enquanto só o setor **Enfestadeiras**
(4 máquinas) tem hardware — ver `docs/painel.md`, seção "Múltiplos setores".

## Estrutura do projeto

```
controle_producao_horimetro/
├── README.md
├── .env.exemplo                          # Modelo das senhas/chave (copiar para .env - fora do git)
├── docs/                                 # Documentação completa (ver abaixo)
├── firmware/
│   └── controle_producao_horimetro/
│       ├── controle_producao_horimetro.ino   # Firmware ESP32 3.0 (Arduino IDE)
│       └── certificados.h                    # Certificado raiz da VPS (público)
├── app/                                  # Aplicativo desktop (forma de uso em produção)
│   ├── main.py                          # Janela nativa (WebView2) + tela de carregando
│   ├── servidor.py                      # Servidor embutido: painel + API + leitura + backup
│   ├── anuncio_rede.py                  # Anuncia http://painel.local na rede (mDNS)
│   ├── build_exe.py / gerar_executavel.bat  # Gera o PainelProducaoSantex.exe
│   └── dist/PainelProducaoSantex.exe    # Gerado (não versionado)
├── ferramentas/
│   ├── banco_dados.py               # Banco SQLite (ciclos, máquinas, turnos, metas)
│   ├── backup_banco.py              # Backup diário automático do banco
│   ├── nuvem.py                     # Acesso remoto: VPS (modo nuvem) + envio da configuração
│   ├── usuarios_nuvem.py            # Logins de quem acessa pela VPS
│   ├── monitor_wifi.py              # Busca os ciclos do ESP32 pelo Wi-Fi
│   ├── monitor_serial.py            # Leitura pelo cabo USB (alternativa)
│   ├── gerar_segredos.py            # .env -> segredos.h (firmware) + segredos_app.json (app)
│   ├── instalar_inicio_automatico.ps1  # Abre o app junto com o Windows
│   ├── controle_leitura_server.py   # O mesmo servidor do app, sem janela (desenvolvimento)
│   ├── controlar_porta_serial.ps1   # Libera/retoma a porta COM para regravar o firmware
│   └── gerar_dados_historico.py     # Dados de exemplo (+1 ano)
├── painel/
│   ├── index.html                   # Painel web (servido pelo app)
│   └── assets/                      # Logo da empresa
├── deploy/                          # VPS: systemd, Caddy, instalar_vps.sh, empacotar_vps.ps1, CLAUDE_VPS.md
├── testes/
│   └── test_backend.py              # python -m unittest discover -s testes -v
├── dados/                           # Banco/configuração em desenvolvimento (fora do git)
└── backup/                          # Backups automáticos diários do banco (fora do git e do .exe)
```

No `.exe`, os dados ficam em `%APPDATA%\PainelProducaoSantex\dados\`
(`painel.db`, `conexao.json`...) — trocar o `.exe` nunca apaga nada. Os
**backups automáticos** (um por dia) ficam em `backup\` na raiz do projeto,
fora do git e do `.exe`.

## Documentação completa

| Documento | Conteúdo |
|---|---|
| [`docs/nuvem-vps.md`](docs/nuvem-vps.md) | **Acesso remoto** pela VPS (https://santex.rexar.com.br): instalação, logins, firmware 3.0 |
| [`docs/aplicativo-desktop.md`](docs/aplicativo-desktop.md) | Gerar e instalar o `.exe`, acesso pela rede, **somente leitura/PIN**, **backup automático**, **produção permanente**, como atualizar |
| [`docs/firmware.md`](docs/firmware.md) | Pinagem, lógica, flash/NVS, RTC, Wi-Fi e API, **chave da API**, recomendações de hardware |
| [`docs/painel.md`](docs/painel.md) | Todas as seções e funcionalidades do painel |
| [`docs/ferramentas.md`](docs/ferramentas.md) | Uso de cada script de `ferramentas/` |
| [`docs/instalacao.md`](docs/instalacao.md) | Arduino IDE + núcleo ESP32, driver USB, Python — do zero |
| [`docs/solucao-de-problemas.md`](docs/solucao-de-problemas.md) | Problemas reais já enfrentados, com causa e correção |

## Colocar em produção (resumo)

1. **Senhas**: copie `.env.exemplo` para `.env` e preencha. Rode
   `python ferramentas/gerar_segredos.py` (cria a `API_CHAVE` se faltar).
2. **Firmware**: abra o `.ino` na Arduino IDE (placa **ESP32 Dev Module**) e
   grave. Detalhes em [`docs/firmware.md`](docs/firmware.md).
3. **Aplicativo**: duplo clique em `app/gerar_executavel.bat` → copie
   `app/dist/PainelProducaoSantex.exe` para o notebook do painel. Firmware
   e `.exe` precisam vir do **mesmo `.env`** (mesma `API_CHAVE`).
4. **Notebook do painel**: firewall só em rede Privada/Domínio, abrir com o
   Windows (`ferramentas/instalar_inicio_automatico.ps1`), sem suspensão na
   tomada, hora automática do Windows ligada, e de preferência uma cópia
   extra do backup no OneDrive/rede — tudo em
   [`docs/aplicativo-desktop.md`](docs/aplicativo-desktop.md#deixar-em-produção-permanente).

## Desenvolvimento

```
cd app
pip install -r requirements.txt
python main.py                      # app com janela, lendo painel/ e ferramentas/ do código-fonte
python ../ferramentas/controle_leitura_server.py   # ou: só o servidor, painel em http://localhost
python -m unittest discover -s ../testes -v        # testes do backend (pasta temporária)
```

Em desenvolvimento os dados ficam em `dados/painel.db` do projeto. Dados de
exemplo: menu **⚙ Configurações → Dados de exemplo**, ou
`python ferramentas/gerar_dados_historico.py`.

Antes de regravar o firmware pela USB com o app aberto lendo a porta:
`ferramentas\controlar_porta_serial.ps1 parar` (e `iniciar` depois).

## Requisitos

- Arduino IDE com o núcleo ESP32 (3.3.x).
- Python 3 com `app/requirements.txt` (só para gerar o `.exe` ou desenvolver;
  quem usa o `.exe` não precisa de Python).
- No PC que usa o `.exe`: Windows 10/11 com WebView2 (já vem instalado).
