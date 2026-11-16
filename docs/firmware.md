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

## Senhas do firmware (`segredos.h`)

Nomes de rede e senhas (`EMPRESA_SSID_PADRAO`, `EMPRESA_SENHA_PADRAO`,
`AP_SSID`, `AP_SENHA`) ficam em
`firmware/controle_producao_horimetro/segredos.h`, que **não vai para o git**
(`.gitignore`). Num computador novo (ou depois de clonar o repositório):

1. Copie `segredos.exemplo.h` para `segredos.h` na mesma pasta.
2. Preencha com os dados reais e grave o firmware normalmente pelo Arduino IDE.

Sem o `segredos.h`, a compilação para com `segredos.h: No such file or directory`.
