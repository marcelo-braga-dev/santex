# Firmware (ESP32)

Arquivo: `firmware/controle_producao_horimetro/controle_producao_horimetro.ino`

## Visão geral

Monitora até **4 máquinas** simultaneamente a partir dos contatos secos de
relés de sinalização (um contato por máquina), medindo quanto tempo cada
uma fica ligada e contando ciclos. **Funciona sozinho, só com a fonte**:
cada ciclo é gravado na flash do próprio ESP32 com data/hora real (RTC
DS3231M), e o PC extrai os dados pelo **Wi-Fi** quando for conectado (por
exemplo, a cada 3 dias), conectando na **rede Wi-Fi criada pelo próprio
ESP32** — depois de gravar no banco, ele zera o armazenamento do ESP32. Não tem display nem botões.

## Hardware

- **Placa**: ESP32 DevKit V1 / NodeMCU-32S (módulo WROOM-32).
- **Alimentação**: fonte 5 V (pino VIN/5V e GND) ou cabo USB.
- **RTC**: DS3231M (I²C) — guarda a data/hora mesmo sem energia (bateria
  CR2032 no módulo).
- **Sem display/LCD/botões** — removidos do projeto; o controle manual é
  feito por comando de texto via Serial (ver abaixo).

### Recomendações para a instalação definitiva

- **Bateria do RTC**: troque a CR2032 na instalação e a cada ~2 anos. Com o
  RTC sem hora e sem PC/internet por perto, os ciclos ficam "sem data/hora"
  (aconteceu: 849 ciclos entre 05/11 e 13/11/2026). O firmware 2.2 recupera
  a hora desses ciclos quando o relógio é acertado no mesmo boot, mas não
  depois de um reinício.
- **Entradas dos relés**: os contatos usam o pull-up **interno** do ESP32
  (~45 kΩ), fraco para cabos longos perto de motores e inversores. Para a
  instalação definitiva, use pull-up externo de 4,7 kΩ para 3,3 V em cada
  entrada (GPIO 16–19) + capacitor de 100 nF para o GND junto ao ESP32 — ou,
  melhor, optoacoplador (ex.: PC817) entre o contato e o ESP32. O debounce
  de 1 s já filtra a maior parte dos ruídos, mas não pulsos longos.
- **Alimentação**: fonte 5 V de boa qualidade (não carregador de celular),
  dentro do painel elétrico, longe dos contatores; se possível num circuito
  com nobreak, já que cada queda gera um "ciclo recuperado".

### Pinagem

| Função | Pino | Observação |
|---|---|---|
| Contato Máquina 1 | GPIO 16 | `INPUT_PULLUP`, fecha para GND quando liga |
| Contato Máquina 2 | GPIO 17 | idem |
| Contato Máquina 3 | GPIO 18 | idem |
| Contato Máquina 4 | GPIO 19 | idem |
| LED de status | GPIO 2 | onboard na maioria das placas DevKit; acende se **qualquer** máquina estiver ligada |
| RTC SDA | GPIO 21 | DS3231M, endereço I²C 0x68 |
| RTC SCL | GPIO 22 | |
| RTC VCC / GND | 3V3 / GND | **3,3 V**, não 5 V |

> Muitos módulos DS3231 (tipo ZS-042) têm um circuito que **carrega** a
> bateria. Com bateria CR2032 (não recarregável), remova o diodo/resistor
> de carga do módulo ou use uma LIR2032.

Se algum relé fizer o contrário (contato **abre** quando a máquina liga, em
vez de fechar), inverta a lógica na função `lerContatoLigado()`.

### Pinos evitados de propósito

Esses pinos **não devem ser usados** para nada neste projeto:

| Pinos | Motivo |
|---|---|
| GPIO 0, 2, 5, 12, 15 | Pinos de *strapping* — afetam o modo de boot do ESP32 (GPIO 2 é usado aqui, mas só como **saída**, o que é seguro) |
| GPIO 1, 3 | UART0 — é o Serial/USB; usar pra outra coisa quebra a comunicação |
| GPIO 6–11 | Ligados à flash SPI interna — nunca usar, trava o boot |
| GPIO 34–39 | Só entrada, sem pull-up interno — não servem para os contatos (que dependem de `INPUT_PULLUP`) |

## Lógica de funcionamento

Cada máquina tem sua própria máquina de estados independente
(`EstadoEquipamento::LIGADO` / `DESLIGADO`), com debounce de **1 segundo**
(`DEBOUNCE_MS`) antes de confirmar uma transição — filtra ruído/oscilação
do contato.

Quando uma máquina desliga, o ciclo é fechado e uma linha é impressa no
Serial (ver formato CSV abaixo). Ciclos com duração menor que
`DURACAO_MINIMA_VALIDA_S` (0.5s) ainda são gravados, só marcados como
suspeitos (`CICLO_CURTO`) — nada é descartado silenciosamente.

## Persistência (NVS via `Preferences`)

O estado de cada máquina fica num registro pequeno (16 bytes: ciclos,
total ligado, progresso do ciclo atual, ligada/desligada) na NVS do ESP32,
pela biblioteca `Preferences` — namespace `horimetro`, chaves `m1`..`m4`.
A NVS já faz wear leveling e confere CRC sozinha. Se uma gravação falhar,
o firmware avisa com `# [Mx] ERRO: falha ao gravar estado na flash (NVS)`.

> **Histórico (26/10/2026):** a versão anterior usava a biblioteca
> `EEPROM.h` (emulada) com rodízio de slots e checksum próprios. No ESP32
> cada `EEPROM.commit()` regravava o bloco inteiro de 4 KB na NVS; na
> prática **nada era recuperado após um reset** (contadores voltavam a 0 e
> o ciclo em andamento se perdia) e o desgaste da flash era alto. Trocado
> por `Preferences` e validado com resets forçados com as máquinas ligadas.

### Recuperação após queda de energia

- Se a máquina **continuou ligada** durante o reset → a contagem do ciclo
  retoma de onde parou (aproximado, baseado no último checkpoint salvo).
- Se a máquina **desligou durante a queda** → o ciclo pendente é fechado
  com os dados que deu para salvar, marcado como
  `CICLO_RECUPERADO_APOS_QUEDA` no log (início/fim aparecem como `?`,
  porque realmente não dá pra saber).

O progresso é salvo a cada **30 segundos** (`INTERVALO_SALVAMENTO_MS`)
enquanto a máquina está ligada, e imediatamente em toda transição de
estado — num reset com a máquina ligada, perdem-se no máximo ~30 s.

## Histórico de ciclos na flash (LittleFS)

Cada ciclo fechado vira um registro de 24 bytes em `/ciclos.bin`
(LittleFS), com **id sequencial que nunca reinicia**, máquina, número do
ciclo, início, fim, duração e observações. Cabem **20.000 ciclos**
(`CAPACIDADE_REGISTROS`, ~480 KB), semanas de produção para 4 máquinas.
Só se esse limite estourar antes de uma extração é que os mais antigos são
sobrescritos (o PC avisa quantos se perderam).

"Zerar o armazenamento" (`POST /limpar` ou comando `X`) só marca até qual
id já foi extraído (chave `apagado` na NVS) e libera esse espaço. Os ids
continuam crescendo, e é por isso que o PC nunca confunde um ciclo novo
com um antigo nem grava o mesmo ciclo duas vezes.

Requer um esquema de partição com área SPIFFS/LittleFS. O padrão da placa
"ESP32 Dev Module" (*Default 4MB with spiffs*) serve. A primeira montagem
formata a área sozinha.

## Relógio (RTC DS3231M)

O RTC guarda a **hora local** (a do PC). Ela é acertada:

- **automaticamente pelo PC**, a cada conexão Wi-Fi, se a diferença passar
  de 3 s (`monitor_wifi.py`);
- ou à mão pela Serial: `T2026-10-30 14:05:00`.

Se o RTC perdeu a hora (bateria fraca ou ausente, flag OSF), o firmware
avisa no boot e grava os ciclos com `SEM_HORA` até a hora ser acertada.
Nesses ciclos, o PC usa a hora em que os recebeu.

Com hora válida, a recuperação após queda de energia também melhora: se a
máquina **seguiu ligada** durante o reset, a duração do ciclo é calculada
pelo RTC, incluindo o tempo em que o ESP32 ficou sem energia. Se o ESP32
ficou desligado mais de 10 min (`LIMITE_QUEDA_CONTINUA_S`), não dá para
saber se a máquina parou no meio. Nesse caso o ciclo antigo é fechado como
`CICLO_RECUPERADO_APOS_QUEDA` e um novo começa.

## Wi-Fi e API HTTP

O ESP32 tem **3 modos de rede**, escolhidos numa página no navegador, sem
regravar o firmware:

| Modo | O que acontece |
|---|---|
| **Ambas** (padrão) | Entra na rede da empresa **e** cria a rede `HORIMETRO_SANTEX` ao mesmo tempo. O notebook acha o ESP32 de qualquer um dos dois jeitos. |
| **Só rede da empresa** | Só fica na rede da empresa. Se ela ficar 2 min fora (senha trocada, roteador desligado), a rede própria liga sozinha, para você nunca perder o acesso. |
| **Só rede própria** | Só cria a rede `HORIMETRO_SANTEX` (sem roteador). |

Valores de fábrica (topo do `.ino`): rede da empresa `VIVOFIBRA-1D51`, rede
própria `HORIMETRO_SANTEX` com senha `AP_SENHA` (**troque antes de gravar**,
mínimo 8 caracteres). Depois da primeira configuração pela página, o que
vale é o que estiver salvo na NVS.

### Página de configuração

Conecte o notebook na rede `HORIMETRO_SANTEX` e abra **http://192.168.4.1**
(ou, na rede da empresa, o IP do ESP32). A página mostra:

- **Atenção** (no topo, em vermelho): só aparece quando algo precisa de
  ação — RTC não responde, RTC estava sem hora ao ligar (bateria CR2032
  fraca/ausente), relógio não acertado (ciclos `SEM_HORA`), armazenamento
  com falha ou quase cheio, sem rede da empresa (com o motivo: rede não
  encontrada, senha errada...), sinal fraco, **conectado ao Wi-Fi mas o
  PC não acessa há mais de 15 min** (repetidor religado sem repassar a
  rede — aperte EN/RESET) e reinício por brownout/watchdog/erro. Sem
  problemas, mostra "Tudo funcionando normalmente";
- **Relógio (RTC DS3231)**: hora atual, se o chip responde no I2C, a hora
  lida do chip agora (e a diferença para a hora interna), temperatura do
  chip (prova de que ele funciona), flag OSF, situação da bateria (se a
  hora foi mantida no último desligamento), último acerto (quando, por
  quem — PC ou Serial — e quantos segundos corrigiu);
- **Rede**: rede da empresa (IP, gateway, sinal em dBm, BSSID/canal do
  ponto de acesso — mostra se está no repetidor ou no roteador —, há
  quanto tempo conectado, quedas desde que ligou), **último acesso do
  painel (PC)**, rede própria e aparelhos conectados, MAC;
- **Máquinas**: ligada/parada e há quanto tempo, modo manual, ciclos e
  tempo total ligado de cada uma;
- **Sistema**: ciclos guardados/capacidade, último id, uso do LittleFS,
  tempo ligado, motivo do último reinício (o botão EN aparece como
  "ligado na energia"), total de reinícios, memória livre, data de
  compilação do firmware e id do dispositivo;
- o link **Atualizar** recarrega a situação (a página não se atualiza
  sozinha para não apagar o que estiver sendo digitado no formulário);
- o formulário: modo, nome e senha da rede da empresa e IP fixo (opcional).
  Quando o ESP32 está conectado, há um link **"usar este IP como fixo"**,
  que preenche o IP atual para o notebook sempre achá-lo no mesmo endereço.

Para salvar, é pedida a **senha do equipamento** (a mesma da rede
`HORIMETRO_SANTEX`). O ESP32 reinicia em ~10 s para aplicar, e nenhum ciclo
se perde: os que estão em andamento são salvos antes e continuam no boot.

Se algo der errado (ex. senha da empresa digitada errada no modo "Só rede
da empresa"), espere 2 min e a rede própria volta. Ou, pela Serial, envie
`W` para voltar o Wi-Fi à configuração de fábrica.

### Observações

- O ESP32 só conecta em Wi-Fi **2,4 GHz**.
- No modo **Ambas**, quando o ESP32 entra na rede da empresa, a rede
  própria passa a usar o mesmo canal do roteador. Quem estiver conectado
  nela pode cair por 1 ou 2 segundos e reconecta sozinho.
- Sem ninguém conectado, o ESP32 **continua contando e gravando os ciclos
  normalmente** em qualquer modo.

| Rota | O que faz |
|---|---|
| `GET /` | Página de situação e configuração do Wi-Fi |
| `POST /config` | Salva a configuração do Wi-Fi (pede a senha do equipamento) e reinicia |
| `GET /info` | JSON: dispositivo, hora, `hora_valida`, `ultimo_id`, `pendentes`, `ip_empresa`, estado de cada máquina; diagnóstico: `rtc_sem_hora_no_boot`, `rssi`, `canal`, `bssid`, `quedas_wifi`, `ligado_ha_s`, `motivo_reset`, `boots`, `firmware` |
| `GET /ciclos?desde=N` | CSV `id,maquina,ciclo,inicio,fim,duracao_s,obs` dos ciclos com id > N (até 200 por vez; cabeçalho `X-Lido-Ate`) |
| `POST /hora?epoch=N` | Acerta o RTC (segundos desde 1970 na hora local) |
| `POST /limpar?ate=N` | Zera o armazenamento até o id N |

Para testar no navegador: `http://192.168.4.1/info` (rede própria) ou `http://<ip-na-empresa>/info`.

## Autodiagnóstico e autocorreção (firmware 2.0)

Objetivo: precisar de menos intervenção manual no ESP32. Tudo aparece no painel em
**⚙ → Diagnóstico do controlador** (na interface o ESP32 é chamado de "controlador") (e na página `http://<ip do ESP32>`).

| Recurso | Como funciona |
|---|---|
| **Redetecção do RTC** | A cada 30 s: se o RTC não estava em uso e passou a responder, passa a usá-lo **sem reiniciar** (grava nele a hora atual do ESP32, ou lê a hora dele se o ESP32 estiver sem hora) e desliga o EOSC (oscilador parando na bateria). Se o RTC parar de responder 3 vezes seguidas, volta para o relógio interno e continua tentando. |
| **Destravamento do I2C** | Antes de cada tentativa: até 9 pulsos de clock + STOP (libera um escravo que ficou segurando SDA). |
| **Varredura I2C + teste de pull-up** | Lista os endereços que respondem (ex.: `0x57,0x68`) e testa se SDA/SCL têm resistor de pull-up (sem pull-up = módulo desligado/desconectado). O painel usa isso para dizer a causa provável quando o RTC não é encontrado. |
| **Hora pela internet (NTP)** | Sem hora válida (sem RTC e sem o PC), acerta pela internet (`a.st1.ntp.br`, `pool.ntp.org`), horário de Brasília (UTC−3). |
| **Motivo das quedas de Wi-Fi** | Cada queda registra o motivo (sinal perdido, rede não encontrada, senha recusada…) e quanto tempo durou. |
| **Reinício do rádio Wi-Fi** | Se não reconectar em ~5 min (5 tentativas), desliga e religa o rádio Wi-Fi (sem reiniciar o ESP32). |
| **Reconexão preventiva** | Conectado, mas o PC não alcança o ESP32 há 15 min (associação "presa" no repetidor): reconecta. Se o PC continuar sem contato (ex.: desligado à noite), repete com intervalo crescente (15 min, 30, 60, até 2 h). Só a primeira de cada período vira evento. |
| **Proteção de memória** | Memória livre abaixo de 16 KB: reinicia de forma segura (salva o estado das máquinas antes). |
| **Registro de eventos** | Últimos 30 eventos em `/eventos.bin` na flash (sobrevive a reinícios): boot e motivo, quedas/voltas de rede, RTC encontrado/perdido, acertos de hora, autocorreções, ações pedidas pelo painel. |

**2.1:** comando serial **`S`** (diagnóstico completo pela USB, sem depender do Wi-Fi e sem
reiniciar: firmware, RTC com teste ao vivo, varredura I2C, pull-ups e causa provável, hora,
Wi-Fi, memória e últimos eventos); identificador do aparelho estável (MAC de fábrica do chip — antes
mudava a cada boot e o PC tratava o controlador como um aparelho novo); reconexão preventiva também
logo após ligar (antes só depois do primeiro acesso do PC).

Novas rotas HTTP: `GET /eventos` e `POST /acao?acao=redetectar_rtc|varrer_i2c|reconectar_wifi|reiniciar`.
O `GET /info` ganhou campos de diagnóstico (`versao`, `rtc_responde`, `i2c`, `i2c_pullup_sda/scl`,
`rtc_temperatura`, `motivo_ultima_queda`, `heap_livre`, `radio_reiniciado`, …) — o PC ignora os que
não conhece, então o app antigo continua funcionando com o firmware novo.

Gravação: Arduino IDE, placa **ESP32 Dev Module**, esquema de partição padrão (o firmware usa
~84% da área de programa). A versão anterior fica em `firmware/_backup/controle_producao_horimetro_v1.ino`.

## Firmware 3.2: atualização pelo Wi-Fi e VPS sem ciclos "sem hora"

**Atualizar o firmware pelo Wi-Fi (OTA)** — a partir do 3.2 (o 3.2 em si
ainda é gravado pela USB):

1. Arduino IDE → **Sketch → Exportar binário compilado**. Na pasta
   `build/esp32.esp32.esp32/` do sketch sai o
   `controle_producao_horimetro.ino.bin` (use esse, **não** o `.merged.bin`).
2. No notebook (ou celular) conectado à rede da empresa/repetidor, abra
   `http://192.168.15.200/atualizar` — ou, perto da máquina, conecte na rede
   `HORIMETRO_SANTEX` e abra `http://192.168.4.1/atualizar`. Há um link no
   fim da página do controlador.
3. Escolha o `.bin`, digite a senha do equipamento (`AP_SENHA`) e clique em
   **Enviar e atualizar**. Leva ~30 s; o controlador reinicia sozinho na
   versão nova (confira o "Firmware" na página).

Detalhes: a senha é conferida antes de gravar qualquer byte; arquivo que não
começa com o byte de firmware do ESP32 (0xE9) é recusado; o firmware novo vai
para a outra partição de aplicativo (esquema de partição padrão, 2 slots) e
só é ativado se chegar inteiro e válido — se o envio cair, o atual continua.
Ciclos (LittleFS) e configuração (NVS) não são tocados. **Não troque o
esquema de partição** no Arduino IDE: um esquema diferente muda a área do
LittleFS e apaga os ciclos guardados. Durante o envio a leitura dos contatos
pausa (o laço principal fica ocupado) — prefira atualizar com as máquinas
paradas. Bluetooth foi descartado: a pilha não cabe na memória e divide o
rádio com o Wi-Fi.

**RTC DS1302 como alternativa ao DS3231** — o firmware detecta sozinho
qual está ligado (DS3231 no I2C tem preferência; depois procura o DS1302) e
redetecta a cada 30 s, então trocar de módulo não exige regravar:

| DS1302 | ESP32 |
|---|---|
| VCC | 3V3 (não 5 V) |
| GND | GND |
| CLK | GPIO 25 |
| DAT | GPIO 26 |
| RST (CE) | GPIO 27 |

O DS1302 não é I2C: o protocolo de 3 fios está no próprio firmware (sem
biblioteca). A presença é confirmada gravando e relendo um byte da RAM do
chip; o bit CH (relógio parado: sem bateria ou nunca acertado) faz o papel do
OSF do DS3231. É menos preciso (~1–2 min/mês) — o PC corrige pelo Wi-Fi
quando passa de 3 s; o que importa é guardar a hora quando o ESP32 reinicia.
Fios curtos (< 20 cm). A página do controlador, o `/info` (`rtc_modelo`) e o
diagnóstico do painel mostram qual modelo está em uso.

**Envio para a VPS só com hora**: ciclo gravado sem hora neste boot (sem RTC,
antes de o PC ou a internet acertarem o relógio) fica na fila até o acerto e
vai depois com a hora real. Antes ele ia como `?`/`SEM_HORA` e a VPS recusava
a versão certa que o notebook mandava (23/11/2026). Ciclo sem hora de boot
anterior segue como `?`, para não travar a fila.

## Firmware 3.1: envio para a VPS mais estável

Diagnóstico (19/11/2026): o ESP32 falhava por períodos de 1 a 6 min ao enviar
para a VPS ("connection refused") enquanto o notebook, na mesma internet,
alcançava a VPS em 100% das tentativas; sinal Wi-Fi −48 dBm e nenhuma queda.
O ponto fraco era abrir uma conexão HTTPS nova (handshake TLS) a cada 10 s.

- **Conexão reaproveitada (keep-alive)**: a conexão HTTPS com a VPS fica
  aberta entre os envios (`HTTPClient::setReuse`); o handshake TLS só
  acontece ao abrir de novo. Se a conexão guardada tiver caído, abre outra na
  hora, no mesmo envio.
- **Erro real**: em vez do genérico "connection refused", `nuvem_erro` traz o
  erro do TLS (`TLS -0x…`) ou se o Wi-Fi estava conectado.
- **Espera máxima de 1 min** entre tentativas (era 5 min): uma falha curta não
  vira vários minutos sem dados na VPS.
- **Reconexão "PC sem contato" só quando a internet também falha**: com o
  envio para a VPS em dia, o Wi-Fi está bom (o PC só está desligado ou com o
  app fechado) — não derruba mais a conexão a cada 15 min.
- `/info` ganhou `nuvem_envios_ok`, `nuvem_falhas` e `nuvem_conexoes_novas`
  (handshakes feitos — com o keep-alive deve crescer bem devagar).
- Nada muda para o notebook nem para a VPS (mesmo formato de envio).

## Firmware 3.0: envio para a VPS (acesso remoto)

O ESP32 continua igual para o notebook (rede local) e **também envia** os
ciclos e o estado das máquinas para a VPS — guia completo em
[nuvem-vps.md](nuvem-vps.md).

- **Tarefa própria** (`tarefaNuvem`, núcleo 0): o envio HTTPS nunca atrasa a
  leitura dos relés, que roda no `loop()` (núcleo 1). A cada ~10 s manda o
  estado das 4 máquinas e até 50 ciclos novos para `NUVEM_URL/api/nuvem/enviar`,
  com a `NUVEM_CHAVE` no cabeçalho `X-Chave-Nuvem`. Com fila, manda o próximo
  lote logo em seguida; com a VPS fora do ar, espera 10 s, 20 s, 40 s… até 5 min.
- **Cursor `nuvemAte`** (NVS): último ciclo confirmado pela VPS. Um ciclo só
  sai da memória quando a VPS **e** o notebook o têm (`apagarCiclosAte` nunca
  passa de `nuvemAte`). Se a memória circular encher antes do envio, os
  sobrescritos viram um evento e um aviso no painel remoto.
- **HTTPS conferido**: certificado raiz em `certificados.h` (ISRG Root X1,
  Let's Encrypt, válido até 2035) — nunca modo inseguro. O relógio do
  sistema passa a seguir a hora do controlador (RTC, PC ou NTP), que o HTTPS
  usa para validar o certificado.
- **Só pela rede da empresa**: a rede própria `HORIMETRO_SANTEX` não tem
  internet; no modo "só rede própria" o envio fica parado (os ciclos esperam).
- **Situação**: `/info` ganhou `nuvem_ativa`, `nuvem_ate`,
  `nuvem_ultimo_envio_s` e `nuvem_erro`; a página do ESP32 mostra a linha
  "Acesso remoto (nuvem)".
- `NUVEM_URL` vazia no `.env` = envio desligado (o firmware se comporta como o 2.2).
- Na primeira gravação do 3.0, o envio começa do que ainda está na memória;
  o histórico antigo fica só no notebook.

## Firmware 2.2: chave da API e hora recuperada

- **Chave nas ações que alteram o ESP32**: `POST /limpar`, `POST /hora` e
  `POST /acao` exigem o cabeçalho `X-Chave` igual à `API_CHAVE` do `.env`
  (gerada sozinha por `gerar_segredos.py` se faltar). Sem a chave certa:
  `403 {"ok":false,"mensagem":"chave invalida"}`. Antes, qualquer aparelho
  na rede podia mandar `POST /limpar?ate=999999` e apagar ciclos ainda não
  baixados. As leituras (`/info`, `/ciclos`, `/eventos`) continuam abertas.
  - O app envia a chave sozinho (vem embutida no `.exe`, gerado com o mesmo
    `.env`). Para trocar sem gerar o `.exe`: `"chave"` no `conexao.json`.
  - Se o firmware e o app estiverem com chaves diferentes, o painel mostra
    "O controlador recusou a chave do aplicativo". Nada se perde: os ciclos
    continuam sendo baixados (a leitura é aberta) — só a limpeza da memória
    e o acerto de hora ficam parados até alinhar as chaves.
- **Ciclos sem hora recebem a hora real**: sem relógio válido, o ciclo é
  gravado com o "tempo desde que ligou" (`FLAG_HORA_RELATIVA`). Quando a
  hora é acertada (PC, internet ou RTC redetectado) **no mesmo boot**, o
  firmware calcula a data real de cada um e tira a marca `SEM_HORA`. O PC
  acerta a hora antes de baixar os ciclos, então eles já chegam com data.
- Formato do registro na flash inalterado (24 bytes; usa o campo reservado).

## Watchdog: removido de propósito

Diferente da versão original (Arduino UNO, que tinha um watchdog AVR
simples e estável), **este firmware não usa watchdog customizado**. Nos
testes com o núcleo Arduino-ESP32 3.3.12, a API `esp_task_wdt` se
comportou de forma instável (erros "already initialized" e depois "task
not found" ao resetar — ver `docs/solucao-de-problemas.md` para o
histórico completo). Um watchdog mal inscrito com `trigger_panic` ligado
arrisca reiniciar o ESP32 sem motivo real, o que é pior do que não ter
watchdog nenhum. O `loop()` é simples e não-bloqueante, então o risco real
de travamento é baixo.

## Saída Serial (formato CSV)

Baud rate: **9600**.

```
maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs
```

| Coluna | Significado |
|---|---|
| `maquina` | 1 a 4 |
| `ciclo` | número sequencial do ciclo **daquela máquina** |
| `inicio_ms` / `fim_ms` | `millis()` do ESP32 no início/fim do ciclo (ou `?` se desconhecido, em ciclo recuperado) |
| `duracao_s` | duração do ciclo em segundos |
| `obs` | vazio (normal), `CICLO_CURTO`, `CICLO_RECUPERADO_APOS_QUEDA`, `SIMULADO`, ou combinações (`CICLO_CURTO+SIMULADO`) |

Linhas que começam com `#` são mensagens de log/diagnóstico (boot,
transições, recuperação da flash) — não são dados de ciclo, e as
ferramentas (`monitor_serial.py`) e o painel já sabem ignorá-las.

### Estado ao vivo

A cada **10 s** (e logo após o boot) o firmware emite, por máquina:

```
# ESTADO,<maquina>,<1=ligada|0=desligada>,<segundos no estado atual>
```

O `monitor_serial.py` grava isso (e as linhas `# [Mx] LIGOU/DESLIGOU`) na
tabela `estado_ao_vivo` do banco; o painel mostra "Ligada agora · há X min"
em cada cartão via `GET /ao-vivo`.

### Abrir a porta não reinicia mais a placa

Na ESP32 DevKit, DTR/RTS comandam o auto-reset (EN/BOOT). O
`monitor_serial.py` abre a porta com os dois **desligados**
(`abrir_porta()`), então pausar/retomar a leitura, reiniciar o servidor ou
o PC não reinicia mais o ESP32 nem corta o ciclo em andamento. A Arduino
IDE continua conseguindo gravar normalmente (ela própria comanda o reset).

> Com o RTC, as colunas passaram a ser `maquina,ciclo,inicio,fim,duracao_s,obs`,
> com `inicio`/`fim` em data/hora real (`2026-10-30T14:05:00`), ou `?` se o
> relógio ainda não foi acertado (o ciclo também recebe `SEM_HORA` em `obs`).

## Controle manual via Serial

Como não há mais display/botões, o controle manual é por comando de texto
no Serial Monitor (com "Nova linha" habilitado):

| Comando | Ação |
|---|---|
| `L1` .. `L4` | Liga manualmente a máquina 1–4 (entra em modo manual) |
| `D1` .. `D4` | Desliga manualmente a máquina 1–4 |
| `R1` .. `R4` | Devolve o controle ao contato real daquela máquina |
| `T2026-10-30 14:05:00` | Acerta o relógio (RTC) |
| `I` | Mostra hora, IP do Wi-Fi e quantos ciclos estão guardados |
| `X` | Apaga todos os ciclos guardados (use só se já extraiu tudo) |
| `W` | Volta o Wi-Fi para a configuração de fábrica (modo Ambas) e reinicia |

Em modo manual, o contato real daquela máquina é **ignorado** até o `R`
correspondente. Os ciclos gerados assim são marcados `SIMULADO` no log,
para nunca serem confundidos com produção real.

## Histórico de decisões relevantes

- O projeto começou num **Arduino UNO R3** com um **LCD Keypad Shield**
  (display + 5 botões). Foi migrado para **ESP32** sem display — o shield
  não encaixa fisicamente na placa e o circuito de botões dele é de 5V
  (risco real para a entrada analógica do ESP32, que é de 3.3V).
- O controle manual que antes era pelos botões (UP/DOWN/SELECT) virou os
  comandos Serial `L`/`D`/`R` descritos acima.
- Multi-máquina (4 entradas) foi adicionado depois da versão single-máquina
  original — por isso a coluna `maquina` é a primeira do CSV.

## Senhas do firmware (`.env` → `segredos.h`)

Nomes de rede e senhas (`EMPRESA_SSID_PADRAO`, `EMPRESA_SENHA_PADRAO`,
`AP_SSID`, `AP_SENHA`, `API_CHAVE`, `NUVEM_URL`, `NUVEM_CHAVE`) ficam no arquivo **`.env`** da raiz do projeto, que
**não vai para o git** (`.gitignore`). O Arduino IDE não lê o `.env`; o
script abaixo gera `firmware/controle_producao_horimetro/segredos.h` (também
fora do git) a partir dele:

```
python ferramentas/gerar_segredos.py
```

- **Trocou uma senha?** Edite o `.env`, rode o script e grave o firmware de novo.
- **Computador novo / repositório clonado?** Copie `.env.exemplo` para `.env`,
  preencha, rode o script e grave o firmware.
- Sem o `segredos.h`, a compilação para com `segredos.h: No such file or directory`.
- `AP_SENHA` precisa ter pelo menos 8 caracteres (o script confere).
- O script também gera `app/segredos_app.json` (fora do git) com a
  `API_CHAVE` para o `.exe`. **Firmware e `.exe` precisam ser gerados com o
  mesmo `.env`** — `gerar/gerar.bat` já roda o script antes do build.
