# Ferramentas (pasta `ferramentas/`)

Scripts Python e PowerShell que fazem a ponte entre o ESP32 (via Serial) e
o painel web (via HTTP local).

## `banco_dados.py`

Banco de dados SQLite persistente (`dados/painel.db`) — **nunca é apagado
ou reescrito do zero** entre execuções, ao contrário do antigo
`banco_de_dados.csv` (que o `monitor_serial.py` recriava vazio toda vez que
era iniciado). Guarda, isolado por setor:

- **ciclos** — cada ciclo real gravado pela leitura serial (só cresce, via
  `INSERT`, nunca `TRUNCATE`);
- **maquinas** — nome e produção/min de cada máquina (antes só existia no
  `localStorage` do navegador);
- **config_setor** — outras configurações por setor (hoje só a meta diária
  de horas ligado).

Usa `PRAGMA journal_mode=WAL` (mais resistente a fechamento abrupto do
programa) e é seguro de acessar de múltiplos processos/threads ao mesmo
tempo — é exatamente assim que `controle_leitura_server.py` e
`app/servidor.py` (thread, dentro do aplicativo desktop) o usam.

Se encontrar um `banco_de_dados.csv` antigo (do formato pré-SQLite) na
mesma pasta, importa os ciclos dele automaticamente na primeira execução e
renomeia o arquivo para `.migrado`, pra não reimportar de novo.

## `monitor_serial.py`

Lê a porta Serial em tempo real e grava cada ciclo real no banco de dados
(`banco_dados.py`), nunca apagando o que já foi gravado antes.

```
python monitor_serial.py [PORTA]
```

- Se a porta não for informada, tenta detectar automaticamente a placa
  conectada via USB — reconhece descrições contendo `arduino`, `ch340`,
  `usb-serial`, `cp210`, `silicon labs` ou `esp32`.
- Ignora linhas de log (começam com `#`) e a linha de cabeçalho vinda do
  firmware — só grava linhas de dado real (6 campos, `maquina`/`ciclo`
  numéricos).
- Cada linha grava é um **novo registro** no banco — reiniciar o script
  (ou o aplicativo desktop) nunca apaga os ciclos já gravados.
- Qualquer linha com `duracao_s` não-numérica é logada como aviso e
  ignorada, sem derrubar a leitura.
- O log de cada linha lida é protegido contra `UnicodeEncodeError` (bytes
  de lixo do boot da placa, que o console do Windows às vezes não consegue
  imprimir) — um erro de log nunca derruba a gravação do ciclo.
- Requer `pip install pyserial`.

Pare com `Ctrl+C`.

A leitura em si vive na função `monitorar(porta, banco, setor,
parar_evento, log)`, separada de `main()` (que só cuida da linha de
comando) — isso permite que o aplicativo desktop (`app/servidor.py`, ver
`docs/aplicativo-desktop.md`) importe e rode a mesma lógica numa thread, em
vez de um processo `monitor_serial.py` separado (que não existiria dentro
de um `.exe` empacotado).

## `monitor_wifi.py`

Busca pela rede os ciclos que o ESP32 guardou na flash e grava no banco.
É o substituto do `monitor_serial.py` quando o ESP32 fica só na fonte, sem
cabo USB.

```
python monitor_wifi.py [ENDERECO ...]
```

- Procura o ESP32 sozinho, nos dois tipos de rede. A cada consulta tenta,
  em ordem: o último endereço que funcionou, os informados (linha de
  comando ou `dados/conexao.json`), o IP que o ESP32 informou ter na rede
  da empresa (aprendido automaticamente e guardado em
  `dados/esp32_ip_empresa.txt`), `192.168.4.1` (rede própria do ESP32) e
  `horimetro.local`. Na prática, basta `dados/conexao.json` com:
  ```json
  {"modo": "wifi"}
  ```
  Se quiser fixar um endereço: `{"modo": "wifi", "endereco": "192.168.15.50"}`
  (também aceita lista).
- A cada 5 s consulta `GET /info`. Se houver ciclos novos, baixa todos (em
  páginas de 200), grava com `INSERT OR IGNORE` (dispositivo + id do ESP32
  formam a chave única, então buscar de novo nunca duplica nada) e **só
  depois** zera o armazenamento do ESP32 (`POST /limpar`).
  `LIMPAR_APOS_EXTRAIR = False` desliga essa limpeza.
- Acerta o RTC do ESP32 com a hora do PC se a diferença passar de 3 s.
- Atualiza o estado ao vivo (`estado_ao_vivo`) com o que vem em `/info`.
- Sem resposta do ESP32 (fora da rede, desligado), só avisa uma vez e
  continua tentando. Nunca derruba a leitura.

Com `conexao.json` em modo `wifi`, tanto o `controle_leitura_server.py`
quanto o aplicativo desktop usam este monitor no lugar da Serial. Sem o
arquivo (ou com `"modo": "serial"`), tudo continua pela USB como antes.

## `controle_leitura_server.py`

O **mesmo servidor do aplicativo desktop** (`app/servidor.py`), só que sem
a janela — para desenvolvimento ou para um PC que só serve o painel. Não há
mais uma cópia separada do código: API, leitura (thread), backup e regra de
somente leitura são exatamente os do app. Dados em `dados/painel.db`.

```
python controle_leitura_server.py
```

Não rode junto com o app (os dois usam a porta 80). Endpoints principais:

| Rota | Método | Retorno |
|---|---|---|
| `/status` | GET | `{"rodando", "modo", "versao", "podeEditar", "pinConfigurado"}` |
| `/dados` | GET | ciclos do setor em CSV. Envia `ETag`; com `If-None-Match` igual responde **304** sem corpo. Comprimido com gzip quando aceito |
| `/sincronizacao` | GET | situação da leitura Wi-Fi + `backup` (último backup / erro) |
| `/ao-vivo?setor=<id>` | GET | estado atual (ligada/desligada) de cada máquina |
| `/config?setor=<id>` | GET | máquinas, meta, turnos e configurações extras |
| `/config`, `/iniciar`, `/parar`, `/conexao`, `/esp/acao` | POST | alterações — aceitas só **deste PC** ou com o cabeçalho `X-Pin` correto (`dados/seguranca.json`); senão `403 {"erro": "somente_leitura"}` |

O servidor atende várias requisições ao mesmo tempo (`ThreadingHTTPServer`)
e manda o painel com `Cache-Control: no-cache` (atualizou o app, todos os
aparelhos pegam a versão nova).

## `nuvem.py` e `usuarios_nuvem.py` (acesso remoto)

`nuvem.py` reúne o acesso remoto: na VPS (`PAINEL_MODO=nuvem`) recebe os
envios do ESP32 (`POST /api/nuvem/enviar`) e a configuração do notebook
(`POST /api/nuvem/config`), ambos com a `NUVEM_CHAVE`, e confere o login das
pessoas; no notebook, `EnviadorConfig` manda a configuração para a VPS
quando ela muda. `usuarios_nuvem.py` cria e remove os logins, na VPS. Ver
[nuvem-vps.md](nuvem-vps.md).

## `backup_banco.py`

Backup diário do `painel.db` pela API de backup do SQLite (seguro com o app
gravando). Usado pelo app — ver
[aplicativo-desktop.md](aplicativo-desktop.md#backup-automático-do-banco).

## `instalar_inicio_automatico.ps1`

Cria (ou remove, com `-Remover`) o atalho do `.exe` na pasta "Inicializar"
do Windows, para o painel abrir sozinho com o notebook.

## `controlar_porta_serial.ps1`

Atalho para parar a leitura antes de regravar o firmware (a porta COM só
pode estar aberta por um programa de cada vez) e retomar depois.

```powershell
.\controlar_porta_serial.ps1 parar       # libera a porta antes do upload
.\controlar_porta_serial.ps1 iniciar     # retoma a leitura depois do upload
.\controlar_porta_serial.ps1 reiniciar   # para e inicia de novo
.\controlar_porta_serial.ps1 status      # mostra se esta rodando
```

Primeiro pede ao app/servidor aberto neste PC para pausar/retomar a leitura
(`POST http://localhost/parar` e `/iniciar`). Se nenhum estiver aberto, age
sobre um `monitor_serial.py` avulso (encerra o processo / inicia oculto,
com saída em `monitor_serial.log`).

Se o PowerShell bloquear a execução por política de segurança:

```powershell
powershell -ExecutionPolicy Bypass -File .\controlar_porta_serial.ps1 parar
```

## `gerar_dados_historico.py`

Gera um CSV de histórico sintético, grande e realista, para testar o
painel (filtros de período, comparativos, exportação) sem precisar de
semanas de operação real.

```
python gerar_dados_historico.py
```

Gera `dados/exemplo_historico_completo.csv` cobrindo **~400 dias** (pouco
mais de um ano — o suficiente pros filtros Dia/Semana/Mês/Ano), com data e
hora reais (formato `maquina,ciclo,data,hora_inicio,hora_fim,duracao_min,obs`
— o formato que o firmware vai produzir quando o RTC entrar em produção,
diferente do formato atual baseado em `millis()`).

Quatro perfis de uso bem diferentes, de propósito, para o comparativo
entre máquinas ficar interessante:

| Máquina | Perfil |
|---|---|
| 1 | Roda quase todo dia útil, ciclos longos (30–120 min) — alto rendimento |
| 2 | Só dia útil comum, ciclos médios (15–90 min) |
| 3 | Só 3 dias por semana, ciclos longos (20–150 min) — baixo rendimento |
| 4 | Roda todo santo dia, ciclos curtos e rápidos (5–40 min), mais anomalias `CICLO_CURTO` |

A semente aleatória é fixa (`random.seed(42)`), então rodar de novo sempre
gera os mesmos dados — útil para comparar antes/depois de uma mudança no
painel.
