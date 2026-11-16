# Controle de Produção — Horímetro Multi-Setor

Monitoramento de horímetro (tempo ligado/parado, rendimento e produção) de
máquinas a partir de um ESP32 lendo os contatos secos dos relés de
sinalização de cada uma, com persistência local, leitura em tempo real via
Serial e um painel web de produção.

O painel web já foi pensado para múltiplos **setores** da empresa (cada um
com seu proprio conjunto de máquinas e dados isolados), mas por enquanto só
o firmware/ferramentas do setor **Enfestadeiras** (4 máquinas) foi
construído — ver `docs/painel.md`, seção "Múltiplos setores".

## Estrutura do projeto

```
controle_producao_horimetro/
├── README.md
├── docs/                                 # Documentação completa (ver abaixo)
├── firmware/
│   └── controle_producao_horimetro/
│       └── controle_producao_horimetro.ino   # Firmware ESP32 (abrir na Arduino IDE)
├── ferramentas/
│   ├── monitor_serial.py            # Lê a Serial e grava no banco (dados/painel.db)
│   ├── banco_dados.py               # Banco SQLite persistente (ciclos, máquinas, metas)
│   ├── controle_leitura_server.py   # Servidor local (porta 8787) usado pelo painel
│   ├── controlar_porta_serial.ps1   # Libera/retoma a porta COM antes de regravar o firmware
│   └── gerar_dados_historico.py     # Gera dados de exemplo com +1 ano de histórico
├── painel/
│   ├── index.html                       # Dashboard web (abrir local ou publicar)
│   └── assets/                          # Imagens/ícones do painel (logo da empresa)
├── app/
│   ├── main.py                          # Ponto de entrada do aplicativo desktop (janela nativa)
│   ├── servidor.py                      # Servidor embutido: serve o painel + API de leitura
│   ├── caminhos.py                      # Resolução de caminhos (fonte vs. .exe empacotado)
│   ├── build_exe.py                     # Gera o instalável PainelProducaoSantex.exe
│   ├── gerar_executavel.bat             # Atalho: instala dependências + roda build_exe.py
│   ├── requirements.txt                 # pywebview, pyinstaller, pyserial
│   ├── assets/icone.ico                 # Ícone do aplicativo/instalador
│   └── dist/PainelProducaoSantex.exe    # Gerado por build_exe.py (não versionar)
└── dados/
    ├── painel.db                         # Banco "vivo" (SQLite) - nunca apagado/reescrito
    └── exemplo_historico_completo.csv    # Dados de exemplo gerados
```

## Documentação completa

| Documento | Conteúdo |
|---|---|
| [`docs/instalacao.md`](docs/instalacao.md) | Instalar Arduino IDE + núcleo ESP32, driver USB (CP210x/CH340), dependências Python — passo a passo do zero |
| [`docs/firmware.md`](docs/firmware.md) | Pinagem completa, lógica de funcionamento, persistência na flash (NVS), estado ao vivo, formato do CSV, comandos manuais via Serial, histórico de decisões |
| [`docs/ferramentas.md`](docs/ferramentas.md) | Uso detalhado de cada script (`monitor_serial.py`, `controle_leitura_server.py`, `controlar_porta_serial.ps1`, `gerar_dados_historico.py`) |
| [`docs/painel.md`](docs/painel.md) | Todas as seções e funcionalidades do dashboard: setores, filtros de período, configuração de máquinas, exportação Excel, backup |
| [`docs/aplicativo-desktop.md`](docs/aplicativo-desktop.md) | Como rodar e gerar o `.exe` do painel como aplicativo desktop (sem navegador) |
| [`docs/solucao-de-problemas.md`](docs/solucao-de-problemas.md) | Problemas reais já enfrentados (driver, watchdog, portas ocupadas, etc.) com causa e correção |

## Como usar

### 1. Firmware (ESP32)

Abra `firmware/controle_producao_horimetro/controle_producao_horimetro.ino`
na Arduino IDE. Placa: **ESP32 Dev Module**. Pinagem, instalação do núcleo
ESP32 e demais detalhes estão comentados no topo do próprio arquivo.

### 2. Ler os dados em tempo real

```
cd ferramentas
python controle_leitura_server.py
```

Deixe essa janela aberta — ela serve `http://localhost:8787` para o botão
"Atualização automática" e o auto-refresh do painel, e grava os ciclos reais
em `dados/painel.db` (SQLite - nunca é apagado/reescrito entre execuções).

Antes de regravar o firmware pela Arduino IDE, libere a porta COM:

```
cd ferramentas
.\controlar_porta_serial.ps1 parar
# ... grave o firmware na Arduino IDE ...
.\controlar_porta_serial.ps1 iniciar
```

### 3. Painel web

Abra `painel/index.html` direto no navegador (duplo
clique). Com o servidor de controle do passo 2 rodando, os dados atualizam
automaticamente a cada poucos segundos.

### 4. Dados de exemplo

Pelo próprio painel (menu **⚙ Configurações → Dados de exemplo**), ou gerando um histórico
maior em arquivo:

```
cd ferramentas
python gerar_dados_historico.py
```

Gera `dados/exemplo_historico_completo.csv` (~400 dias, um perfil de uso
diferente por máquina).

### 5. (Opcional) Rodar como aplicativo desktop, sem navegador

```
cd app
pip install -r requirements.txt
python main.py
```

Abre uma janela nativa com o mesmo painel — a leitura serial e a API rodam
embutidas no mesmo processo, sem precisar do passo 2 separado. Para gerar
um `.exe` único, que roda em outro PC sem Python instalado, dê duplo
clique em `app/gerar_executavel.bat` (ou rode `python build_exe.py` na
pasta `app`).

Gera `app/dist/PainelProducaoSantex.exe`. Detalhes completos em
[`docs/aplicativo-desktop.md`](docs/aplicativo-desktop.md).

## Requisitos

- Arduino IDE com o núcleo ESP32 instalado.
- Python 3 com `pyserial`: `pip install pyserial`.

Passo a passo completo de instalação (núcleo ESP32, driver USB, etc.) em
[`docs/instalacao.md`](docs/instalacao.md).
