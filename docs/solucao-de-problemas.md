# Solução de problemas

Problemas reais já enfrentados neste projeto, com a causa e a correção
aplicada — pra não precisar redescobrir tudo de novo.

## O aplicativo abre com tela branca / demora / às vezes só funciona fechando e abrindo

A partir desta versão a abertura mostra sempre o que está acontecendo
(imagem de abertura → "Carregando…" → painel). Se parar numa tela de
**falha**, ela diz o motivo:

- **"O Painel já está aberto em outra janela"**: havia outra janela (ou um
  processo que não fechou direito) usando a porta 8787. Feche a outra e
  clique em *Tentar novamente* — se não houver janela visível, finalize
  `PainelProducaoSantex.exe` no Gerenciador de Tarefas.
- **"A porta 8787 está ocupada por outro programa"**: por exemplo o
  `controle_leitura_server.py` rodando junto. Feche-o.
- **"O servidor interno não respondeu"**: antivírus/firewall bloqueando o
  acesso local (`localhost`). Libere o aplicativo.

Detalhes de cada abertura ficam em
`%APPDATA%\PainelProducaoSantex\dados\app.log` (botão *Abrir registro de
erros* na própria tela). A primeira abertura do dia é naturalmente mais
lenta (o Windows inicia o WebView2 e o `.exe` se descompacta).

## A porta COM não aparece / aparece "Não conectado"

**Causa mais comum**: driver USB-serial não instalado. No Gerenciador de
Dispositivos, o dispositivo aparece com um ícone de alerta (ex.:
"CP2102 USB to UART Bridge Controller" com status de erro, código 28 —
"os drivers para este dispositivo não estão instalados").

**Correção**: instalar o driver CP210x (Silicon Labs) ou CH340, conforme o
chip da placa. Passo a passo completo em `docs/instalacao.md`.

Outras causas possíveis, em ordem de frequência:
- Cabo USB só de carga (sem linhas de dado) — troque o cabo.
- Outro programa com a porta aberta (Serial Monitor da IDE, ou um dos
  scripts Python deste projeto) — ver próximo item.

## "Acesso negado" / `PermissionError(13, 'Acesso negado')` ao abrir a porta

A porta COM só pode estar aberta por **um programa de cada vez**. Esse
erro aparece quando:
- O Serial Monitor da Arduino IDE está aberto ao mesmo tempo que
  `monitor_serial.py` ou `controle_leitura_server.py`.
- Um processo anterior do `monitor_serial.py` ficou rodando em segundo
  plano sem você perceber.

**Correção**: feche o Serial Monitor da IDE, e/ou rode
`.\controlar_porta_serial.ps1 parar` (mata qualquer `monitor_serial.py`
pendurado). Depois retome com `iniciar`.

## Erro de compilação no watchdog (`esp_task_wdt_init`)

A API `esp_task_wdt` mudou de assinatura entre versões do núcleo
Arduino-ESP32:

- **Núcleos antigos (2.x)**: `esp_task_wdt_init(timeout_segundos, panic_bool)`.
- **Núcleos novos (3.x, baseados em ESP-IDF 5.x)**: `esp_task_wdt_init(const esp_task_wdt_config_t *config)` — recebe uma struct.

**Isso já causou dois problemas em sequência** neste projeto (núcleo
3.3.12):

1. Com a API antiga, erro de compilação (assinatura incompatível).
2. Depois de corrigir pra API nova: erro em tempo de execução
   `E (347) task_wdt: esp_task_wdt_init(517): TWDT already initialized` —
   o próprio framework Arduino-ESP32 3.x já inicializa o watchdog antes do
   `setup()` rodar.
3. Tentando `esp_task_wdt_reconfigure()` em vez de `init()`: novo erro,
   `E (780) task_wdt: esp_task_wdt_reset(707): task not found` — a task
   não ficou corretamente inscrita.

**Decisão final**: removido o watchdog customizado deste firmware (ver
`docs/firmware.md`, seção "Watchdog: removido de propósito"). Um watchdog
mal configurado com `trigger_panic` ligado é pior que não ter nenhum —
arrisca reiniciar o ESP32 sem motivo.

Se quiser revisitar isso no futuro, confirme antes a versão exata do
núcleo instalado (`Arduino15/packages/esp32/hardware/esp32/<versão>`) e
leia o `esp_task_wdt.h` correspondente antes de escrever o código — não
adianta confiar em exemplos genéricos da internet, a API realmente mudou
entre versões.

## A IDE abre uma tela de depuração (GDB/OpenOCD) em vez de gravar

Mensagem típica: `Error: unable to open ftdi device with description '*'`.

**Causa**: foi clicado o botão de **Debug** (ícone de inseto) em vez de
**Carregar/Upload**. O Debug tenta abrir uma sessão JTAG via um
depurador FTDI embutido — que só existe em placas específicas (como a
ESP32-WROVER-KIT), não na DevKit V1/NodeMCU-32S genérica usada aqui.

**Correção**: não é um erro de verdade — só clique no botão de Upload (→)
em vez do de Debug.

## O dashboard não atualiza sozinho / chip fica "Atualização automática indisponível"

O auto-refresh e o botão de atualização automática dependem do
`controle_leitura_server.py` rodando em `localhost:8787` (internamente isso
ainda é a "leitura serial" — só o texto exibido ao usuário na página foi
simplificado, ver `docs/painel.md`). Se ele não estiver rodando (ou tiver
caído — processos em segundo plano iniciados por automação têm um limite de
tempo e são encerrados ao atingi-lo), o painel mostra "Atualização
automática indisponível".

**Correção**: suba de novo —
```
cd ferramentas
python controle_leitura_server.py
```
Isso é **esperado e não funciona** na versão hospedada (link claude.ai) —
aquela página roda numa sandbox sem acesso à rede local. Só funciona
abrindo o arquivo `.html` localmente.

## `monitor_serial.py` não grava nenhum ciclo no banco de dados

Se `/dados` continua retornando só o cabeçalho, mesmo com ciclos
acontecendo de verdade: confira se `eh_linha_de_dados()` está checando o
número certo de campos. Isso já quebrou uma vez neste projeto quando o
firmware passou a ter múltiplas máquinas (coluna `maquina` nova) e o script
continuou esperando o formato antigo de 5 campos em vez de 6 —
silenciosamente descartava toda linha de dado real. Corrigido, mas é o
tipo de coisa que volta a quebrar se o formato da linha Serial mudar de
novo sem atualizar o parser do script junto.

## Erro `Acesso negado` ao renomear/mover arquivos do projeto

Se um `mv`/renomeação falhar com "Device or resource busy" ou similar,
algum processo Python ainda está com o arquivo aberto (o
`monitor_serial.py` mantém o CSV aberto o tempo todo que está rodando).
Pare os processos (`Get-CimInstance Win32_Process -Filter "Name =
'python.exe'"` + `Stop-Process`) antes de mover/renomear.

## No aplicativo desktop, acentos aparecem corrompidos ("ProduÃ§Ã£o")

**Causa**: o servidor embutido (`app/servidor.py`) servia o `index.html` com
`Content-Type: text/html`, sem `charset=utf-8`. Sem isso, o WebView2 (motor
por trás do `pywebview` no Windows) adivinha a codificação sozinho e erra,
corrompendo todo acento/cedilha/travessão — mesmo com o arquivo gravado em
UTF-8 de verdade.

**Correção**: `_responder_estatico()` agora acrescenta `; charset=utf-8` ao
`Content-Type` de qualquer arquivo de texto (`text/*`, JS, JSON) antes de
enviar. Confirmado rodando o `.exe` de verdade (não só revisando o código) —
sem esse detalhe o problema não aparece ao simplesmente abrir o `index.html`
direto no navegador, só dentro do WebView2 embutido.

## Depois de adicionar um setor novo, a configuração de máquinas "sumiu"

Não sumiu — cada setor grava nome/taxa de máquina e meta diária numa chave
de `localStorage` própria (sufixo `__<id-do-setor>`, ver `docs/painel.md`,
seção "Múltiplos setores") e, quando há servidor local, também no banco de
dados (`dados/painel.db`). Trocar de setor no seletor do topo troca também
qual chave/linha é lida; a configuração do setor anterior continua salva,
só não aparece enquanto outro setor está selecionado.

## No aplicativo desktop: editei o nome de uma máquina, fechei e abri de novo, e a edição sumiu

**Causa**: `webview.start()` do `pywebview` abre a janela em **modo
privado por padrão** (`private_mode=True`) — nesse modo o WebView2 não
grava nada em disco entre execuções, então qualquer coisa salva só no
`localStorage` do painel (que era o único lugar guardando nome/taxa de
máquina antes do banco de dados existir) desaparecia a cada vez que o
aplicativo era fechado.

**Correção**: `app/main.py` agora chama `webview.start(private_mode=False,
storage_path=dir_perfil_webview())`, apontando para uma pasta fixa do
usuário (`%APPDATA%\PainelProducaoSantex\perfil_webview\`) — o WebView2
passa a reabrir esse perfil, não recriar um novo, a cada execução. Em
paralelo, nome/taxa de máquina e meta diária também passaram a ser
gravados no banco de dados (`dados/painel.db`), uma segunda camada de
persistência que nem depende do perfil do navegador embutido — ver
`docs/aplicativo-desktop.md`, seção "Perfil persistente do WebView2".
Confirmado gravando um valor numa execução e lendo de volta numa segunda
execução (processo novo).

## No `.exe` empacotado: `ModuleNotFoundError: No module named 'sqlite3'`

**Causa**: `monitor_serial.py` e `banco_dados.py` são incluídos no build
via `--add-data` (copiados como arquivo, carregados em tempo de execução
por `sys.path.insert`, não por um `import` normal) — o PyInstaller nunca
analisa estaticamente o código deles, então não percebe que `banco_dados.py`
faz `import sqlite3` e não empacota a extensão `_sqlite3`. O build termina
sem erro; o `.exe` só quebra ao **abrir**, com essa mensagem.

**Correção**: `build_exe.py` declara `--hidden-import=sqlite3`
explicitamente (mesma razão pela qual `--hidden-import=serial.tools.list_ports`
já existia ali). Isso só aparece rodando o `.exe` de verdade — testar
apenas se o build "passou sem erro" não pega esse tipo de problema.

## `monitor_serial.py` trava (ou para de logar) com bytes de boot da placa

**Causa**: logo depois de abrir a porta Serial, a placa às vezes envia
alguns bytes de lixo/reinicialização antes do primeiro texto válido. Esses
bytes, decodificados com `errors="replace"`, viram o caractere `�` —
que o `print()` padrão não consegue escrever em consoles Windows com
codepage `cp1252`, lançando `UnicodeEncodeError` e derrubando a thread/
processo de leitura silenciosamente (o `controle_leitura_server.py` inicia
o subprocesso com `stderr=DEVNULL`, então o erro não aparecia em lugar
nenhum).

**Correção**: toda chamada de log dentro de `monitorar()` passa agora por
`_log_seguro()`, que tenta `log(msg)` e, se estourar `UnicodeEncodeError`,
tenta de novo com o texto reduzido a ASCII — nunca deixando um problema de
*log* derrubar a gravação do ciclo. Reproduzido rodando
`python monitor_serial.py` direto no terminal (sem o servidor engolindo o
erro).
