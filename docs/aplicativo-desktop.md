# Aplicativo desktop (`app/`)

O mesmo painel web, empacotado como um aplicativo Windows normal — abre numa
janela própria (sem barra de endereço, sem navegador), com a leitura
serial e a API já embutidas no mesmo processo. Pensado para quem só quer
dar duplo clique num ícone e ver o painel funcionando, sem saber o que é
Python, terminal ou `localhost`.

## Como funciona

```
app/
├── main.py           # Ponto de entrada: abre a janela (tela de carregando), sobe o servidor e carrega o painel
├── tela_inicial.py    # Tela "Carregando… / Falha / Já aberto" mostrada antes do painel
├── servidor.py        # Servidor HTTP: serve o painel (painel/) + API de leitura
├── caminhos.py         # Resolve caminhos (fonte vs. .exe empacotado, pasta de dados do usuário)
├── requirements.txt     # pywebview, pyinstaller, pyserial
├── assets/icone.ico     # Ícone do aplicativo (gerado a partir do logo da empresa)
└── assets/splash.png    # Imagem de abertura do .exe (enquanto ele se descompacta)

gerar/                  # Geradores (na raiz do projeto) - saída em distribuir/
├── gerar.bat           # Duplo clique: menu (fábrica / remoto / VPS / tudo)
├── exe_fabrica.py      # PyInstaller do PainelProducaoSantex-<versão>.exe (este aplicativo)
├── exe_remoto.py       # PainelSantexRemoto.exe (computadores de fora - ver docs/nuvem-vps.md)
└── pacote_vps.ps1      # Pacote da VPS (alternativa ao git pull)
```

### Abertura sem "tela branca"

A abertura passa por etapas visíveis — nunca fica uma janela branca sem
explicação:

1. **Imagem de abertura** (`assets/splash.png`, opção `--splash` do
   PyInstaller): aparece no instante do duplo clique, enquanto o `.exe`
   (arquivo único) se descompacta. Fechada quando a janela aparece.
2. **Tela de carregamento** — uma tela só, com a lista de etapas
   **Servidor interno → Interface → Conexão com o aplicativo → Dados de
   produção** (a etapa atual gira, as concluídas ganham ✓):
   - a janela já abre nela (`tela_inicial.py`, HTML autocontido, sem rede;
     fundo da janela na mesma cor, `background_color`, sem "flash" branco);
   - numa thread, `main.py` sobe o servidor interno, espera `GET /status`
     responder (até 20 s) e carrega o painel (`load_url`);
   - o painel abre com uma cópia **idêntica** dessa tela (`#app-splash` no
     `index.html` — mesmo cartão, mesma posição, cores fixas) que continua
     a lista de onde parou e some sozinha quando os dados chegam (no máximo
     10 s). Para o usuário, a troca é invisível.
   - **Ao mudar o visual de uma, mude a outra** (comentário nos dois
     arquivos).

Se algo falhar, a mesma tela mostra o motivo, com **Tentar novamente**,
**Abrir registro de erros** e detalhes técnicos:

| Situação | O que aparece |
|---|---|
| Outra janela do Painel já aberta (porta 80 em uso **pelo próprio Painel**) | "O Painel já está aberto em outra janela" + "Usar esta janela mesmo assim" |
| Porta 80 ocupada por outro programa | "A porta 80 está ocupada por outro programa" |
| Servidor não respondeu em 20 s | "O servidor interno não respondeu" (antivírus/firewall bloqueando localhost?) |
| Arquivo faltando no `.exe` / erro inesperado | Mensagem + detalhes técnicos |
| Erro de script no painel durante a abertura | "Falha ao carregar o painel" + Recarregar |

**Porta exclusiva:** o servidor interno abre a porta 80 com
`SO_EXCLUSIVEADDRUSE` (`_ServidorExclusivo` em `servidor.py`). Antes, o
`HTTPServer` padrão (com `SO_REUSEADDR`) deixava **duas** instâncias do app
escutarem a mesma porta no Windows — as requisições caíam ora numa, ora
noutra, e o painel ficava instável ("só funciona fechando e abrindo").
Agora a segunda instância é recusada na hora e mostra o aviso de janela
duplicada. Ao fechar, a porta é liberada imediatamente (`server_close`).

Tudo é registrado em **`dados/app.log`** (no `.exe`:
`%APPDATA%\PainelProducaoSantex\dados\app.log`; recomeça ao passar de
~1 MB).

O painel também deixou de carregar a biblioteca de Excel (SheetJS) da
internet **antes** do próprio código — sem internet ou com rede lenta,
isso travava a abertura inteira. Agora ela é baixada em segundo plano
depois que o painel abre, ou na hora de exportar.

- **`main.py`** abre uma janela com [pywebview](https://pywebview.flowrl.com/)
  apontando para `http://localhost/` — o mesmo endereço que o painel já
  usa quando aberto localmente, só que agora é o próprio aplicativo que serve
  essa página, em vez de o usuário abrir o arquivo `.html` direto.
- **`servidor.py`** é uma versão do `ferramentas/controle_leitura_server.py`
  com uma diferença importante: a leitura serial roda como **thread**, não
  como um processo `monitor_serial.py` separado. Isso é necessário porque,
  dentro do `.exe` gerado pelo PyInstaller, não existe um `python.exe`
  avulso para rodar um script — `sys.executable` aponta para o próprio
  aplicativo. A lógica de leitura em si (`monitor_serial.monitorar()`) e o
  banco de dados (`banco_dados.py`) são os mesmos de
  `ferramentas/`, importados diretamente — nada foi duplicado.
- **`caminhos.py`** decide onde ler o painel/ferramentas empacotados
  (`sys._MEIPASS`, pasta temporária criada pelo PyInstaller) e onde gravar
  dados persistentes do usuário — sempre numa pasta gravável
  (`%APPDATA%\PainelProducaoSantex\`), nunca dentro de "Arquivos de
  Programas" (que normalmente só é gravável com privilégio de
  administrador). Duas sub-pastas: `dados\` (o banco `painel.db`) e
  `perfil_webview\` (ver "Perfil persistente do WebView2" abaixo).

## Rodar sem gerar o `.exe` (desenvolvimento)

```
cd app
pip install -r requirements.txt
python main.py
```

Abre a janela já lendo `painel/` e `ferramentas/monitor_serial.py` direto do
código-fonte (sem build), e grava no banco `dados/painel.db` (igual ao
script `controle_leitura_server.py`).

## Gerar o `.exe`

Mais simples: duplo clique em **`gerar/gerar.bat`** e escolha a opção 1 —
instala as dependências, atualiza as chaves a partir do `.env` e gera o
executável em `distribuir\`.

Ou manualmente (na raiz do projeto):

```
pip install -r app/requirements.txt
python ferramentas/gerar_segredos.py
python gerar/exe_fabrica.py
```

**Este `.exe` leva a chave da fábrica: nunca o copie para computadores de
fora da empresa** — para eles existe o `PainelSantexRemoto.exe` (opção 2 do
`gerar.bat`), que só abre o painel da VPS e não leva segredo nenhum.

Gera **`distribuir/PainelProducaoSantex-<versão>.exe`** — um único arquivo, com
Python, `pywebview`, `pyserial`, `sqlite3` e o painel inteiro embutidos.
Quem for instalar não precisa ter Python nem rodar `pip install` — só esse
`.exe`.

`monitor_serial.py` e `banco_dados.py` entram via `--add-data` (copiados
como arquivos, carregados em tempo de execução por `sys.path` — ver
`servidor.py`), então o PyInstaller nunca analisa os `import` que eles
fazem. Por isso `gerar/exe_fabrica.py` declara manualmente
`--hidden-import=serial.tools.list_ports` e `--hidden-import=sqlite3`;
sem o segundo, o `.exe` compila sem erro mas quebra ao abrir com
`ModuleNotFoundError: No module named 'sqlite3'` (só aparece rodando o
`.exe` de verdade, não no build) — se um novo `import` for adicionado
dentro de `banco_dados.py` ou `monitor_serial.py` no futuro, confira se
ele também precisa entrar aqui.

Sempre teste o `.exe` gerado (rodando-o, não só confiando no build sem
erros) antes de distribuir — é a forma de pegar qualquer caminho relativo
que tenha escapado do empacotamento.

### Requisito em quem for *usar* o `.exe`

O **Microsoft Edge WebView2 Runtime**, que renderiza a janela. Já vem
instalado por padrão em qualquer Windows 10/11 atualizado (é o mesmo motor
do navegador Edge). Se faltar — só em instalações bem desatualizadas — o
Windows baixa e instala sozinho na primeira vez que um app baseado nele é
aberto; não é algo que o instalador deste projeto precisa empacotar junto.

## Onde ficam os dados quando o app está instalado

| Rodando como... | Painel/ferramentas | Banco de dados |
|---|---|---|
| `python main.py` (código-fonte) | `painel/`, `ferramentas/` do projeto | `dados/painel.db` do projeto |
| `.exe` empacotado | pasta temporária criada pelo Windows ao abrir o app (apagada ao fechar) | `%APPDATA%\PainelProducaoSantex\dados\painel.db` |

Isso significa que trocar a versão do `.exe` (reinstalar/substituir o
arquivo) **não apaga os dados já gravados** — eles vivem na pasta do
usuário, não dentro do próprio `.exe`.

### Leitura pelo Wi-Fi

Para o app buscar os ciclos do ESP32 pela rede, em vez da porta USB, crie
`conexao.json` na pasta de dados acima (`%APPDATA%\PainelProducaoSantex\dados\`):

```json
{"modo": "wifi"}
```

O app acha o ESP32 sozinho, esteja o notebook na rede da empresa ou na
rede `HORIMETRO_SANTEX` criada pelo ESP32. Ao clicar em iniciar a leitura no painel, o app baixa tudo o que o ESP32
acumulou, grava no banco, acerta o relógio dele e zera o armazenamento
(ver `monitor_wifi.py` em [ferramentas.md](ferramentas.md)). Apague o
arquivo para voltar à leitura pela USB.

## Perfil persistente do WebView2 (nomes de máquina não somem mais)

`main.py` chama `webview.start(private_mode=False,
storage_path=dir_perfil_webview())`. Isso é **essencial**: por padrão o
`pywebview` abre a janela em modo privado (`private_mode=True`), e nesse
modo o WebView2 não grava **nada** em disco entre execuções — incluindo o
`localStorage` do painel, onde nome/taxa de máquina e meta ficavam
guardados. Sem esse parâmetro, editar uma máquina, fechar o aplicativo e
abrir de novo faz a edição desaparecer (o problema real que motivou essa
correção).

Com `storage_path` apontando para uma pasta fixa do usuário
(`%APPDATA%\PainelProducaoSantex\perfil_webview\`), o WebView2 grava ali um
perfil completo (cookies, cache, `Local Storage`) que é **reaberto**, não
recriado, a cada execução. Confirmado na prática: valor gravado no
`localStorage` por uma execução apareceu fisicamente no arquivo
`perfil_webview/EBWebView/Default/Local Storage/leveldb/*.log` e foi lido
de volta por uma execução seguinte, em outro processo.

Isso é uma camada a mais de segurança além do banco de dados
(`painel.db`) — a configuração de máquina já é persistida nos dois lugares
(ver `docs/painel.md`, seção "Configurar máquinas").

## Diferenças em relação ao painel aberto no navegador

- **Backup/Excel**: continuam usando o download direto do navegador
  (`salvarArquivoParaUsuario`), já que o WebView2 por trás do pywebview se
  comporta como um navegador normal nesse ponto — nenhuma mudança foi
  necessária no painel em si.
- **Atualização automática**: sempre disponível (nunca aparece
  "indisponível"), porque o servidor embutido roda garantidamente junto com
  o app — diferente do painel aberto como arquivo `.html` solto, que depende
  de alguém ter aberto `controle_leitura_server.py` à parte.
- **Múltiplos setores**: funciona igual ao painel web — o registro
  `SETORES` dentro do `index.html` não muda entre as duas formas de abrir.
- **Configuração de máquina mais robusta**: além do `localStorage` (que no
  app desktop só sobrevive por causa do perfil persistente do WebView2,
  ver acima), o nome/taxa de cada máquina e a meta diária também ficam no
  banco de dados (`painel.db`) — o painel web aberto sem servidor local
  (ex.: hospedado) não tem esse reforço, só o `localStorage`.

## Ícone do aplicativo

`app/assets/icone.ico` foi gerado a partir do logo da empresa
(`painel/assets/logo.png`), centralizado num canvas quadrado transparente
(para não esticar/distorcer um logo retangular) e exportado em vários
tamanhos (16 a 256px), como o Windows espera de um `.ico`. Para trocar o
ícone, gere um novo `.ico` a partir da imagem desejada e substitua o
arquivo — `gerar/exe_fabrica.py` já aponta para ele.

## Acessar o painel de outro computador (navegador)

O servidor interno escuta na porta padrão da web (80), em todas as placas
de rede (IPv4 e IPv6), e se anuncia na rede local com o nome
**`painel.local`** (mDNS - `app/anuncio_rede.py`, biblioteca `zeroconf`).
Em qualquer computador ou celular da **mesma rede**, basta abrir:

```
http://painel.local
```

- Também funcionam `http://<IP-do-PC>` e `http://<nome-do-PC>` (sem porta).
- Se o IP do PC mudar, o anúncio se atualiza sozinho em até 1 minuto.
- `painel.local` funciona no Windows 10/11, iPhone/Mac e na maioria dos
  Android recentes; num aparelho que não resolva `.local`, use o IP.
- O PC do painel precisa estar ligado, sem suspensão e com o app aberto.
- **Firewall do Windows** (PowerShell como administrador, uma vez). Só nas
  redes **Privada/Domínio** — nunca em rede Pública (Wi-Fi de hotel,
  aeroporto...), onde estranhos veriam o painel:
  ```powershell
  New-NetFirewallRule -DisplayName "Painel Producao HTTP 80" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Private,Domain
  New-NetFirewallRule -DisplayName "Painel Producao mDNS 5353" -Direction Inbound -Protocol UDP -LocalPort 5353 -Action Allow -Profile Private,Domain
  ```
  Se as regras já foram criadas antes com `Public`, corrija com:
  ```powershell
  Set-NetFirewallRule -DisplayName "Painel Producao HTTP 80" -Profile Private,Domain
  Set-NetFirewallRule -DisplayName "Painel Producao mDNS 5353" -Profile Private,Domain
  ```
  E marque a rede da empresa como **Privada** no Windows (Configurações →
  Rede → propriedades da rede → Perfil de rede: Privado).

### Quem pode alterar (somente leitura + PIN)

- **O computador do painel** (onde o app está aberto) altera tudo, sem senha.
- **Outros computadores e celulares** abrem o painel em **somente leitura**:
  veem tudo, mas turnos, metas, taxas, nomes, iniciar/pausar a leitura,
  origem dos dados e ações do controlador são recusados. Na barra inferior
  aparece **🔒 Somente leitura**; uma alteração feita ali é desfeita na hora
  (a tela volta ao que está salvo).
- **Liberar outros aparelhos com PIN** (opcional): crie
  `%APPDATA%\PainelProducaoSantex\dados\seguranca.json`:
  ```json
  {"pin_remoto": "4821"}
  ```
  No outro aparelho, clique em **🔒 Somente leitura** e digite o PIN — vale
  até fechar a aba. Para trocar o PIN, edite o arquivo (não precisa
  reiniciar o app).

### Acesso de fora da rede (VPS)

Para quem não está na rede da empresa: **https://santex.rexar.com.br**, com
login, somente leitura. O ESP32 (firmware 3.0) envia os dados direto para lá
e o app envia a configuração editada aqui sempre que ela muda (status em
**Controlador**, na barra inferior). A **senha** de quem acessa de fora é
definida e trocada aqui, em **⚙ Configurações → Acesso remoto**. Instalação:
[nuvem-vps.md](nuvem-vps.md).

## Backup automático do banco

O app faz **uma cópia por dia** do `painel.db`, sozinho, ao abrir e depois
conferindo de hora em hora (`ferramentas/backup_banco.py`):

- Pasta: **`backup\` na raiz do projeto**
  (`controle_producao_horimetro\backup\painel-AAAA-MM-DD.db`) — cada arquivo
  é um banco completo, abre com qualquer visualizador SQLite. A pasta está
  no `.gitignore` (nunca vai para o git) e não entra no `.exe`.
  - O `.exe` grava, no momento do build, o caminho da raiz do projeto
    (`app/build_info.json`). Se rodar num PC onde essa pasta não existe, os
    backups vão para `%APPDATA%\PainelProducaoSantex\dados\backups\`.
  - Como o projeto fica dentro do OneDrive, os backups também vão para a
    nuvem sozinhos (cópia fora do notebook).
  - Outra pasta: `"pasta"` no `backup.json` (abaixo).
- Ficam os **14 últimos dias** + o **primeiro backup de cada mês** dos
  últimos 12 meses. Os mais antigos são apagados — só arquivos de backup;
  o banco principal **nunca** é apagado nem reescrito.
- **Configuração opcional** em `%APPDATA%\PainelProducaoSantex\dados\backup.json`
  (a mesma rotação vale nas duas pastas):
  ```json
  {"pasta": "D:\\Backups\\Painel", "pasta_extra": "\\\\servidor\\compartilhado\\Painel"}
  ```
  `pasta` troca o local principal; `pasta_extra` grava uma segunda cópia.
- A situação aparece no painel, em **Controlador** (barra inferior):
  "Backup automático do banco: hoje às 08:00" — ou um aviso ⚠ se falhar.
- **Restaurar**: feche o app, copie o backup desejado por cima de
  `dados\painel.db` (apague `painel.db-wal` e `painel.db-shm` antes) e
  abra o app.

## Deixar em produção permanente

1. **Abrir com o Windows** (no notebook que serve o painel):
   ```powershell
   cd ferramentas
   .\instalar_inicio_automatico.ps1 "C:\Programas\PainelProducaoSantex-<versão>.exe"
   ```
   (`-Remover` desfaz.)
2. **Energia**: na tomada, "Suspender" = Nunca — com o notebook suspenso o
   painel some da rede e a sincronização para (o ESP32 continua guardando
   os ciclos, até ~20.000 = cerca de 40 dias no ritmo atual).
3. **Hora do Windows** com "Acertar a hora automaticamente" ligado — é o PC
   que acerta o relógio do controlador.
4. Firewall e perfil de rede como na seção acima.

## Atualizar para uma versão nova

O `.exe` carrega uma cópia própria do painel: mudar `painel/index.html` não
altera o app instalado até gerar o `.exe` de novo. A versão em uso aparece
no rodapé do painel ("· v1.0.0" — `APP_VERSAO` em `app/servidor.py`).

1. Suba o número em `APP_VERSAO` (`app/servidor.py`).
2. Rode os testes: `python -m unittest discover -s testes -v`.
3. Duplo clique em `gerar/gerar.bat` (ele também roda
   `gerar_segredos.py`, que leva a `API_CHAVE` do `.env` para o app).
4. Feche o app, troque o `.exe` e abra de novo. Os dados ficam onde estão.
5. Se mudou o firmware: grave pela Arduino IDE **com o mesmo `.env`** (o
   firmware e o app precisam da mesma `API_CHAVE` — ver
   [firmware.md](firmware.md)).
