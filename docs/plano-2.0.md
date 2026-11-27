# Plano da versão 2.0 — vários setores e um ESP32 por máquina

> Documento de planejamento, revisado em 26/11/2026 com todas as decisões
> tomadas até aqui. Base: tag `v1.7.5` (app 1.7.5, firmware 3.2, programa
> remoto 1.2.0). Os demais documentos (`README.md`, `docs/firmware.md`,
> `docs/painel.md`, `docs/nuvem-vps.md`…) descrevem o sistema em produção e
> serão atualizados a cada fase entregue.

## 1. Objetivo

A 2.0 transforma o painel, que hoje atende **um setor com um ESP32 de 4
máquinas**, numa plataforma de **vários setores** com **dois tipos de
coletor**:

| Coletor | Setor | Quantidade | Comunicação |
|---|---|---|---|
| **Multi** (o atual, firmware 3.2) | Enfestadeiras | 1 ESP32 → 4 máquinas | Como hoje: o servidor **busca** os dados (pull) e o ESP32 também envia para a VPS |
| **Unitário** (novo, firmware 4.0) | Novo setor (e outros no futuro) | ~50 ESP32, **1 por máquina** | Rede Wi-Fi dedicada; cada ESP32 **envia** os dados ao servidor local (push) |

Requisitos permanentes:
- **Nenhum ciclo perdido.** O ESP32 guarda tudo na flash e só apaga depois
  de o servidor confirmar que gravou.
- O banco de produção **nunca é apagado nem reescrito**, e as mudanças nele
  são só aditivas.
- As Enfestadeiras **continuam funcionando** com o firmware 3.2, sem
  regravar o ESP32.
- O repositório é público: nenhum segredo vai para o código.

## 2. Decisões tomadas

| Tema | Decisão |
|---|---|
| Sinal das máquinas | **Contato seco de relé**: relé acionado = máquina ligada |
| Dado coletado | **Só ligada/desligada** (sem contagem de peças) |
| Setores | **Cadastrados no banco**, criados e editados pelo painel; nenhum setor fixo no código |
| Servidor local | **Mini-PC dedicado**, sempre ligado |
| Rede | **Rede Wi-Fi dedicada só a este projeto**: **1 AP principal** (no cabo, junto ao mini-PC) + **1 AP repetidor em malha** (sem fio, só tomada) |
| Relógio | **RTC DS3231 em cada ESP32** |
| Destino dos ESP32 unitários | **Só o servidor local**; o servidor repassa à VPS |
| Senhas da VPS | **As mesmas duas senhas para tudo** (visualização e edição), sem permissão por setor |

## 3. Situação atual (análise da 1.7.5)

O que **já ajuda**:
- O banco já separa por setor: `ciclos`, `maquinas`, `turnos`,
  `config_setor`, `estado_ao_vivo` e `config_extra` têm a coluna `setor`.
- A deduplicação por `dispositivo + origem_id` já existe
  (`gravar_ciclo_remoto`).
- O firmware 3.x já sabe **enviar** ciclos com confirmação e só apagar o
  que foi confirmado (envio à VPS). O push da 2.0 parte desse código, já
  testado em produção.
- SQLite em WAL com uma trava única de escrita; servidor
  `ThreadingHTTPServer`.

O que **precisa mudar**:

| Ponto | Onde | Problema com 50 máquinas e vários setores |
|---|---|---|
| `SETOR_PADRAO = "enfestadeiras"` fixo | `app/servidor.py` (≈10 usos), `ferramentas/monitor_serial.py` | Servidor, recebimento do ESP32, histórico, configuração e `EnviadorConfig` atendem um setor só |
| `/dados` devolve **o histórico inteiro em CSV** e o navegador calcula tudo | `_csv_atual()` → `csv_do_setor()` | ~1,8 milhão de ciclos/ano (≈100 MB de CSV). O painel ficaria inviável em poucos meses |
| Um único leitor pull e um único `sincronizacao.json` | `ferramentas/monitor_wifi.py` | Não serve para 50 aparelhos |
| Chave única compartilhada no firmware | `segredos.h` | Um ESP32 perdido expõe a chave de todos |
| Rede própria (AP) do ESP32 ligada por padrão | firmware (`MODO_AMBAS`) | 50 pontos de acesso extras poluiriam o rádio 2,4 GHz |
| Chaves de configuração sem setor (`maquina:1`, `turnos`…) | `config_rev`, `ferramentas/nuvem.py` | A sincronização com a VPS misturaria setores |
| Painel com um setor e cartões grandes | `painel/index.html` (11,6 mil linhas) | Não comporta 50 cartões nem a troca de setor |

## 4. Arquitetura

```
                       REDE WI-FI DEDICADA (2,4 GHz, SSID próprio)

  Máquinas mais distantes                         Máquinas mais próximas
  ┌────────┐ ┌────────┐                           ┌────────┐ ┌────────┐
  │ ESP32  │ │ ESP32  │  ...                      │ ESP32  │ │ ESP32  │  ...
  └───┬────┘ └───┬────┘                           └───┬────┘ └───┬────┘
      │ Wi-Fi    │                                    │ Wi-Fi    │
      ▼          ▼                                    ▼          ▼
  ┌──────────────────────┐   malha sem fio    ┌──────────────────────┐
  │ AP REPETIDOR (mesh)  │ ─────────────────► │ AP PRINCIPAL (raiz)  │
  │ só tomada, no alto   │                    │                      │
  └──────────────────────┘                    └──────────┬───────────┘
                                                         │ cabo (porta 2)
                                              ┌──────────▼───────────┐
                                              │ MINI-PC (app 2.0)    │
                                              │ servidor local       │
                                              └──────────┬───────────┘
                                                         │ cabo (porta 1): rede da empresa / internet
                                                         ▼
  ESP32 multi das Enfestadeiras (3.2) ◄─ pull ─  (como hoje)
                                                         │ HTTPS
                                              ┌──────────▼───────────┐
                                              │ VPS                  │ ◄── ESP32 multi 3.2 também envia direto
                                              │ santex.rexar.com.br  │
                                              └──────────────────────┘
```

### 4.1 Por que push (o ESP32 envia) no coletor unitário

| Critério | Pull (servidor busca, como hoje) | **Push (ESP32 envia)** |
|---|---|---|
| Descobrir 50 IPs | O servidor precisa achar cada IP (DHCP muda) | Não precisa: o ESP32 conhece o servidor |
| Estado ao vivo | Uma volta por 50 aparelhos | Imediato na mudança |
| Carga | 50 conexões a cada 5 s, mesmo sem novidade | Batimento a cada 10 s + envio na mudança |
| Servidor desligado | Nada acontece | O ESP32 acumula na flash e envia tudo quando ele volta |

O pull continua só para o ESP32 multi das Enfestadeiras, como um
adaptador dentro do novo gerenciador de coletores.

### 4.2 Por que os ESP32 unitários não falam com a VPS
- Não abrem 50 conexões TLS para a internet, e não é preciso manter
  certificado e raiz confiável em 50 aparelhos.
- A rede dedicada não precisa de internet.
- A redundância vem da flash de cada ESP32 (20.000 ciclos, várias semanas
  de uma máquina).
- O servidor local repassa à VPS pelo caminho que já existe
  (`/api/nuvem/historico` + `ao_vivo`).

## 5. Rede dedicada

### 5.1 Topologia: 1 AP principal + 1 repetidor
- **AP principal (raiz)**: ligado por cabo à 2ª porta de rede do mini-PC,
  na parte do setor mais próxima do servidor. Atende as máquinas do seu
  lado.
- **AP repetidor**: ligado ao principal **sem fio**, pela malha (mesh) do
  próprio sistema. Precisa só de **tomada**. Fica entre o principal e as
  máquinas mais distantes, que se conectam a ele.
- **Mesmo SSID, mesmo canal**, os dois gerenciados pela mesma
  controladora.
- **Só 2,4 GHz** para os ESP32 (eles não usam 5 GHz), WPA2-PSK, sem
  internet. Na rede ficam só os ESP32, os dois APs e o mini-PC.
- Um salto sem fio só: com 1 repetidor, a malha é a mais simples possível.

### 5.2 Regras de instalação
1. **Prova de alcance antes da instalação definitiva**: com os 2 APs e 2 ESP32 de
   teste nas máquinas mais distantes, medir o sinal por 3 dias. Metas:
   - ESP32 → AP: melhor que **−70 dBm**;
   - repetidor → principal: melhor que **−65 dBm** (é o enlace de todas as
     máquinas distantes).
2. **Instalar alto**, acima das máquinas e com o mínimo de obstáculos
   metálicos entre o repetidor e o principal (de preferência com visada
   direta).
3. **Capacidade**: um AP profissional atende 50 ESP32 com folga (o tráfego
   é mínimo, poucos bytes a cada 10 s). Com 2 APs, a carga se divide.
4. **Canal fixo** (1, 6 ou 11), diferente do canal da rede da empresa;
   potência fixa (sem ajuste automático, que muda a cobertura sozinho).
5. Desligar recursos que atrapalham aparelhos simples: *band steering*
   (a rede é só 2,4 GHz), *airtime fairness* agressivo e desconexão por
   sinal mínimo muito alto.
6. **DHCP com concessão longa** (7 dias) servido pelo mini-PC ou pelo AP
   principal. Os ESP32 não precisam de IP fixo (eles é que procuram o
   servidor); o **mini-PC tem IP fixo** nessa rede (ex.: `10.20.0.1`).
7. ESP32 dentro de painel metálico perde muito sinal: nesses pontos, usar
   um ESP32 com **antena externa** para fora do painel.
8. **Rede própria do ESP32 desligada por padrão**: ela só liga para
   instalação ou socorro (botão BOOT por 5 s, ou mais de 10 min sem
   conseguir entrar na rede dedicada) e desliga sozinha depois de 15 min.

### 5.3 Ponto único de falha
O repetidor concentra as máquinas distantes. Se ele cair:
- **nenhum ciclo se perde**: os ESP32 guardam tudo e enviam quando a
  rede voltar;
- o painel mostra essas máquinas como **"sem sinal"** (não como paradas), e
  o alerta "repetidor sem contato" aparece em segundos;
- solução: religar ou substituir o AP; os ESP32 voltam a enviar sozinhos.

## 6. Servidor local (mini-PC)

O mini-PC substitui o "notebook que lê a cada 3 dias" e passa a ser o
**mestre** (edita sem senha). O notebook continua podendo abrir o painel
pela rede da empresa.

| Item | Especificação | Por quê |
|---|---|---|
| Processador | 4 núcleos de baixo consumo | Folga grande; consumo baixo ligado 24 h |
| Memória | 16 GB | SQLite com cache, controladora dos APs, navegador em modo TV |
| Disco | SSD NVMe 512 GB | ~2 milhões de ciclos/ano + backups diários |
| Rede | **Duas portas Ethernet** | Porta 1: rede da empresa (internet → VPS). Porta 2: AP principal da rede dedicada |
| Sistema | Windows | O app da fábrica é `.exe` |
| BIOS | "Restore on AC power loss" = **Power On** | Volta sozinho depois de uma queda de energia |
| Energia | Protegida contra queda (mini-PC + AP principal) | Evita desligamento brusco do banco e mantém a rede |

Configuração: app 2.0 e controladora dos APs iniciando com o Windows,
atualizações automáticas do Windows fora do horário de produção, backup
diário do banco (já existe) com uma cópia fora do mini-PC.

## 7. Firmware 4.0

### 7.1 Base de código
- **Uma base só para os dois perfis**, escolhido em tempo de execução
  (NVS): `multi` (4 entradas, compatível com o 3.2, pull) ou `unitario`
  (1 entrada, push). **O mesmo `.bin` para todos os coletores
  unitários**: nada é compilado por máquina.
- O `.ino` de 2.746 linhas vira **módulos** na pasta do sketch:
  `relogio.*` (DS3231/DS1302, hora do servidor), `armazenamento.*`
  (LittleFS circular, mesmo formato), `entradas.*` (debounce e estados),
  `rede.*` (Wi-Fi, escolha de AP, reconexão, AP de socorro), `envio.*`
  (push, confirmação, espera progressiva), `http_local.*` (página de
  situação), `ota.*`, `seguranca.*` (HMAC).
- O 3.2 continua congelado nas Enfestadeiras. Migrar esse ESP32 para o
  4.0 (perfil `multi`) fica para depois e é opcional.

### 7.2 Ligação em cada máquina
| Item | Escolha |
|---|---|
| Entrada | 1 contato seco do relé da máquina (GPIO 16) com isolamento (optoacoplador) ou pull-up externo de 4,7 kΩ + 100 nF, ver `docs/firmware.md` |
| Relógio | RTC DS3231 no barramento I²C (GPIO 21/22), como no firmware 3.x |
| Alimentação | 5 V dentro do painel elétrico, longe dos contatores |

### 7.3 Comportamento do perfil unitário
- **Entrada**: relé acionado = ligada; debounce de 1 s (a lógica atual de
  `lerContatoLigado()`).
- **Ciclo**: o mesmo registro de 24 bytes e as mesmas flags (curto,
  recuperado, sem hora…), sempre com máquina = 1. **Quem diz qual máquina é
  qual é o servidor** (§9.2).
- **Relógio**: o RTC é a referência no boot e sem rede. A cada envio, o
  servidor devolve a hora oficial (a do mini-PC) e o ESP32 acerta o RTC se
  a diferença passar de 3 s. A lógica de `SEM_HORA` continua para o caso de
  bateria do RTC esgotada.
- **Envio**:
  - batimento a cada **10 s** com o estado e a saúde do aparelho;
  - envio **imediato** quando o estado muda, mais os ciclos pendentes, em
    lotes de no máximo 50;
  - **atraso aleatório** (0 a 2 s), para os 50 não chegarem juntos depois
    de uma queda de energia;
  - falha → espera dobrando (2 s → 60 s), também com atraso aleatório;
  - apaga da flash **só até o `ack_ate`** devolvido pelo servidor.
- **Escolha do AP**: o ESP32 não troca de AP sozinho. O firmware varre a
  rede ao conectar e entra no AP (BSSID) de **melhor sinal** do SSID. Ele
  varre de novo se o sinal ficar pior que −75 dBm por 2 min ou depois de 3
  envios seguidos com falha. O AP em uso vai na saúde, e o painel mostra
  quem está no principal e quem está no repetidor.
- **Robustez**: watchdog, reinício seguro com pouco heap (já existe),
  reinício do rádio depois de N falhas (já existe), motivo do último reset
  e quedas de Wi-Fi enviados ao servidor.
- **Identificar**: um comando do painel faz o LED piscar por 30 s, para
  achar o aparelho na máquina.

### 7.4 Provisionamento (50 aparelhos sem compilar 50 vezes)
1. Grava-se o **mesmo firmware** em todos (USB, uma vez).
2. A ferramenta **`ferramentas/provisionar_coletor.py`** (e um botão no
   painel do mini-PC), pela USB:
   - lê o ID do chip (MAC);
   - grava na NVS o SSID e a senha da rede dedicada, o endereço do servidor
     (`10.20.0.1`) e a **chave própria do aparelho**;
   - acerta o RTC;
   - imprime uma etiqueta (ID + QR) para o aparelho e a máquina.
3. Alternativa sem PC: o AP de socorro com a página de configuração (já
   existe no 3.x).

### 7.5 Atualização de firmware (OTA) em campanha
1. Envio do `.bin` ao servidor local (SHA-256 calculado).
2. O servidor manda o comando `ota` na resposta. O ESP32 baixa o arquivo
   **do mini-PC** pela rede dedicada.
3. **Canário**: 2 aparelhos. Esperar voltarem com a versão nova e 10 min
   de envios normais.
4. Ondas de 10, com a mesma verificação; **parada automática** se algum
   aparelho não voltar.
5. O firmware novo só se marca como válido
   (`esp_ota_mark_app_valid_cancel_rollback`) **depois do primeiro envio
   aceito pelo servidor**. Senão, volta sozinho à versão anterior.
6. Não atualizar com a máquina ligada (adia até ela parar, com limite de 1 h).

## 8. Protocolo do coletor (v2)

`POST http://10.20.0.1/api/v2/coletor`

Pedido:
```json
{
  "v": 2,
  "dispositivo": "esp-24A1B2C3D4E5",
  "firmware": "4.0.0", "perfil": "unitario",
  "seq": 18233,
  "hora": 1795700000, "hora_valida": true,
  "estado": [{"canal": 1, "ligado": true, "segundos": 312}],
  "ciclos": [[1501, 1, 88, "2026-12-01 07:02:10", "2026-12-01 07:09:44", 454.0, ""]],
  "ultimo_id": 1501, "primeiro_id": 1, "apagado_ate": 1450,
  "saude": {"rssi": -63, "bssid": "A8:42:A1:00:00:02", "heap": 142000,
            "uptime_s": 86400, "reset": "power_on", "flash_uso_pct": 3,
            "quedas_wifi": 2, "ip": "10.20.0.41", "rtc": "DS3231"}
}
```

Resposta:
```json
{
  "ok": true,
  "adotado": true,
  "ack_ate": 1501,
  "hora": 1795700001,
  "config": {"rev": 7, "debounce_ms": 1000, "intervalo_s": 10},
  "comando": null
}
```
Valores de `comando`: `identificar`, `reiniciar`,
`ota {url, sha256, versao}`.

Regras:
- **Autenticação**: `X-Ts` + `X-Assinatura: HMAC-SHA256(chave_do_aparelho,
  ts + "." + corpo)`. A chave nunca trafega, e o servidor recusa `ts` com
  mais de 120 s de diferença (anti-replay).
- **Chave por aparelho**: `chave = HMAC(CHAVE_MESTRA, id_do_aparelho)`. O
  servidor guarda só a mestra (no `.env` / `segredos_app.json`, fora do
  git). Para revogar um aparelho, basta marcá-lo como bloqueado; a chave
  dos outros não muda.
- **Idempotência**: a chave do ciclo é `dispositivo + origem_id`. Reenviar
  o mesmo lote não duplica nada.
- **Confirmação só depois do COMMIT** no SQLite.
- **Relógio fora da janela** (feito na 2.3): a assinatura confere mas o
  `ts` está fora de ±120 s → 401 `{"erro": "relogio", "hora": <epoch do
  servidor>}`. O aparelho acerta o RTC com essa hora e tenta de novo (sem
  isso, um RTC com bateria esgotada nunca mais conseguiria enviar).
- **Chave do aparelho** = `HMAC-SHA256(mestra, id)` em **texto hex** (64
  caracteres); o firmware usa esse texto como chave do HMAC da assinatura.
- **Aparelho não adotado**: o servidor responde `adotado: false, ack_ate: 0`.
  Ele aparece em "Novos aparelhos", e os ciclos **ficam guardados no
  ESP32** até a adoção. Não existem ciclos órfãos no banco.

## 9. Servidor (app 2.0)

### 9.1 Módulos
| Módulo | Função |
|---|---|
| `ferramentas/setores.py` | Cadastro de setores; fim do `SETOR_PADRAO` (vira só o setor inicial da migração) |
| `ferramentas/dispositivos.py` | Registro, adoção, troca, bloqueio, saúde, alertas de comunicação |
| `ferramentas/receptor_push.py` | `/api/v2/coletor`: valida a assinatura, fila em memória e um gravador único em lote (uma transação a cada ~1 s) |
| `ferramentas/coletor_pull.py` | O `monitor_wifi.monitorar()` atual como adaptador: um por ESP32 multi, cada um com seu setor e seu arquivo de status |
| `ferramentas/consultas.py` | API por período e agregados (substitui o CSV inteiro) |
| `ferramentas/ota_campanha.py` | OTA em ondas |

### 9.2 Adoção e troca de aparelhos
- Um aparelho novo aparece em **Dispositivos → Novos**, com o sinal e o AP
  por onde chegou. Você escolhe **setor + máquina** e confirma.
- **Setor e máquina são gravados em cada ciclo na chegada.** Trocar ou
  remanejar um aparelho depois não altera o histórico.
- **Troca de aparelho queimado**: escolher o reserva e "assumir a máquina
  X". O antigo fica como inativo, e tudo vai para o histórico de
  atribuições.

### 9.3 Desempenho
- **Estado ao vivo em memória**: os batimentos (~5/s) atualizam um
  dicionário. A tabela `estado_ao_vivo` só é gravada quando algo muda ou a
  cada 60 s.
- **Gravador único com fila**: sem disputa pela trava do SQLite.
- **`/ao-vivo?setor=`** com ETag/`304`.
- **Consultas por período**: `/api/v2/ciclos?setor=&de=&ate=&maquinas=` e
  `/api/v2/resumo?setor=&de=&ate=&agrupar=dia|turno|maquina`, sobre a tabela
  `resumo_dia` (atualizada a cada ciclo e recalculável). O `/dados` antigo
  continua durante a transição, por compatibilidade.

### 9.4 Saúde e alertas
| Situação | Regra | Mostra |
|---|---|---|
| Sem comunicação | Sem batimento há mais de 30 s | Cartão cinza "sem sinal" (diferente de "parada") |
| Repetidor fora | Todos os aparelhos daquele AP sem sinal ao mesmo tempo | Alerta "AP repetidor sem contato" |
| Sinal fraco | RSSI médio pior que −75 dBm por 10 min | Ícone de sinal; lista em Dispositivos |
| Memória do ESP32 enchendo | Flash > 50 % | Aviso: o servidor não está recebendo |
| Relógio inválido | `hora_valida = false` | Aviso (trocar bateria do RTC) |
| Reinícios demais | Mais de 3 resets em 1 h | Aviso (alimentação ou ruído) |
| Aparelho novo | Não adotado | Selo em Dispositivos |

## 10. Banco de dados (só aditivo)

```sql
CREATE TABLE IF NOT EXISTS setores (
    setor TEXT PRIMARY KEY,               -- slug, gerado do nome na criação; não muda
    nome TEXT NOT NULL,
    tipo_coleta TEXT NOT NULL DEFAULT 'multi',   -- 'multi' | 'unitario' | 'misto'
    ordem INTEGER NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS dispositivos (
    dispositivo TEXT PRIMARY KEY,         -- 'esp-<MAC>' (o mesmo 'dispositivo' de ciclos)
    perfil TEXT NOT NULL,                 -- 'multi' | 'unitario'
    setor TEXT,                           -- NULL = ainda não adotado
    maquina INTEGER,                      -- unitário: máquina do setor; multi: NULL
    apelido TEXT NOT NULL DEFAULT '',
    situacao TEXT NOT NULL DEFAULT 'novo',-- 'novo' | 'ativo' | 'bloqueado' | 'reserva'
    firmware TEXT, ip TEXT, rssi INTEGER, bssid TEXT, saude TEXT,  -- saude = JSON
    ultimo_contato TEXT, adotado_em TEXT, config_rev INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dispositivo_atribuicoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispositivo TEXT NOT NULL, setor TEXT NOT NULL, maquina INTEGER NOT NULL,
    de TEXT NOT NULL, ate TEXT, autor TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS resumo_dia (
    setor TEXT NOT NULL, maquina INTEGER NOT NULL, dia TEXT NOT NULL,
    ciclos INTEGER NOT NULL, segundos_ligada REAL NOT NULL,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (setor, maquina, dia)
);

ALTER TABLE maquinas ADD COLUMN grupo TEXT;      -- linha/célula, para agrupar 50 cartões
ALTER TABLE maquinas ADD COLUMN ordem INTEGER;
ALTER TABLE maquinas ADD COLUMN ativa INTEGER NOT NULL DEFAULT 1;
ALTER TABLE estado_ao_vivo ADD COLUMN dispositivo TEXT;

-- (o indice unico idx_ciclos_origem em (dispositivo, origem_id) ja existe desde a 1.x)
CREATE INDEX IF NOT EXISTS idx_ciclos_setor_gravado ON ciclos(setor, gravado_em);
```

> **Corrigido na etapa 1.4**: o índice previsto era `(setor, maquina,
> inicio_ms)`, mas `inicio_ms`/`fim_ms` são texto e muitas vezes não têm hora
> real. A hora real de cada ciclo é o `gravado_em` (fim do ciclo, pelo RTC),
> então o índice e as consultas por período usam `(setor, gravado_em)`. O
> `resumo_dia` divide o tempo ligado de um ciclo que passa da meia-noite
> entre os dois dias, e o ciclo conta no dia em que terminou.

- Migração ao abrir a 2.0: cria `setores` com `enfestadeiras`
  (Enfestadeiras, tipo `multi`) e registra o ESP32 atual em `dispositivos`
  como `multi`/ativo. Nada existente é alterado.
- Volume: ~2 milhões de ciclos por ano. Com os índices e o `resumo_dia`, o
  SQLite atende com folga. Testar com 1 ano de dados sintéticos (§13).

## 11. Sincronização com a VPS (configuração v3)

- O histórico (`/api/nuvem/historico`) já leva `setor`. O enviador passa a
  percorrer **todos os setores**, cada um com seu cursor.
- **Chaves com setor**: `enfestadeiras/maquina:1`, `<setor>/turnos`… Itens
  globais continuam como hoje (`visual`, senhas, `edicao_remota`). Nova
  chave global `setores` (o cadastro).
- Protocolo `"versao": 3`. A VPS 2.0 aceita v2 (chave sem setor =
  `enfestadeiras`) e v3. **Ordem de implantação: VPS primeiro, depois o
  mini-PC.**
- `ao_vivo` por setor, mais o estado de comunicação dos aparelhos (a VPS
  também mostra "sem sinal").
- O cadastro de dispositivos sobe para a VPS só para leitura. Adoção e OTA
  são feitas só no mini-PC.
- **Senhas**: as duas atuais (visualização e edição) valem para todos os
  setores. Quem tem a de edição pode criar e editar setores pela VPS.
- O ESP32 multi 3.2 continua enviando direto à VPS, como hoje.

## 12. Painel

1. **Seletor de setor** no cabeçalho (lembrado por aparelho, `?setor=` na
   URL) e uma visão **"Fábrica"** com o resumo de todos os setores.
2. **Cadastro de setores** (Configurações → Produção → Setores):
   - **criar**: nome, tipo de coleta (multi/unitário), ordem. O slug é
     gerado do nome e **não muda depois**, porque é a chave gravada nos
     ciclos;
   - **editar**: nome, ordem, tipo de coleta;
   - **desativar** em vez de apagar: some do seletor, o histórico continua
     nos relatórios. Apagar só é permitido para setor sem ciclos nem
     aparelhos;
   - cada setor tem seus turnos, calendário, metas e máquinas;
   - tudo entra na auditoria (`alteracoes`) e sincroniza com a VPS.
3. **Visão geral para 50 máquinas**: cartões compactos (nome, estado, tempo
   no estado, rendimento do turno), **agrupados por linha/célula**, filtros
   (rodando, parada, sem sinal) e ordenação (pior rendimento primeiro).
   Clicar abre o detalhe, que é o cartão atual com "Configurar máquina".
4. **Modo TV** paginado com rotação automática e uma faixa de resumo fixa.
5. **Dispositivos** (Configurações → Sistema): ID, setor/máquina, firmware,
   IP, **AP em uso (principal/repetidor)**, sinal, último contato, uso da
   flash, resets. Ações: adotar, trocar, identificar (LED), reiniciar,
   bloquear, OTA.
6. **Desempenho e Relatórios por setor** e consolidado, sobre a API por
   período.
7. Atualização **incremental** do DOM (só os cartões que mudaram). As
   partes novas vão em módulos JS em `painel/js/`, sem reescrever o que já
   funciona no `index.html`.

## 13. Testes e qualidade

| Nível | O quê |
|---|---|
| Unitários (`testes/`, pasta temporária) | Cadastro de setores, HMAC e anti-replay, adoção e troca, idempotência do push, `ack` só depois do commit, aparelho não adotado, `resumo_dia`, migração (em cópia), configuração v3 ↔ v2 |
| **Simulador** `ferramentas/simulador_coletores.py` | 50 (ou 200) ESP32 virtuais com o protocolo v2: ligam e desligam, perdem rede, reiniciam, repetem lotes, relógio errado, queda de "um AP" (metade some de uma vez). Roda contra o servidor com banco **temporário** |
| Carga e duração | 50 aparelhos por 24 h: zero ciclos perdidos ou duplicados, CPU, tamanho do banco, tempo de resposta do painel com 1 ano de dados |
| Firmware | `arduino-cli compile` nos dois perfis; bancada com 3 a 5 ESP32 acionados por relé temporizado (nunca o ESP32 de produção) |
| Caos | Mini-PC desligado por 2 h; repetidor desligado; energia de todos cortada ao mesmo tempo |
| Rede (fase 0) | Prova com os 2 APs + 2 ESP32 nas máquinas mais distantes, 3 dias |
| VPS | Configuração v3 contra uma VPS de teste (cópia do banco); v2 ainda aceito |

As regras de sempre continuam: nunca abrir o banco de produção para
escrita nem ler o ESP32 real em testes.

## 14. Fases

| Fase | Entrega | Critério de pronto |
|---|---|---|
| **0. Rede e hardware** (1–2 sem.) | Instalação do mini-PC e dos 2 APs; prova de alcance; protótipo da caixa (ESP32 + opto + RTC + fonte) | Sinais dentro das metas (§5.2) por 3 dias |
| **1. Fundação multi-setor** (2–3 sem.) | Tabela e cadastro de setores, fim do `SETOR_PADRAO`, API por período + `resumo_dia`, configuração v3, seletor de setor. **App 2.0.0-alfa.1** (VPS primeiro) | Testes atuais + novos verdes; Enfestadeiras idênticas para o usuário |
| **2. Protocolo e servidor** (2 sem.) | `/api/v2/coletor`, dispositivos, adoção, fila/gravador, simulador, alertas | Simulador: 50 aparelhos por 24 h sem perda nem duplicação |
| **3. Firmware 4.0** (3 sem.) | Modularização, perfil unitário, push, HMAC, escolha de AP, AP de socorro, OTA, provisionamento | Bancada de 5 ESP32 por 7 dias sem perda; OTA com rollback testado |
| **4. Painel 50 máquinas** (2 sem.) | Visão compacta, grupos, filtros, modo TV, Dispositivos, relatórios por setor | Fluido com 50 máquinas e 1 ano de dados sintéticos |
| **5. Piloto** (2 sem.) | 5 máquinas reais (parte no AP principal, parte no repetidor) | Ciclos conferidos à mão; comunicação disponível > 99 % |
| **6. Implantação** (2–3 sem.) | 3 ondas de ~15 máquinas; `docs/coletores.md`, `docs/rede.md`; atualização dos demais documentos | Todas adotadas; **app 2.0.0 e firmware 4.0.0** com tag |

**Total estimado: 12 a 16 semanas.** As fases 2 e 3 andam em paralelo
depois que o protocolo (§8) estiver fechado. A fase 1 não depende da rede
nem do hardware e pode começar já.

## 15. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Enlace repetidor → principal fraco | Máquinas distantes sem sinal | Prova de alcance na fase 0, instalação alta com visada, modelo Outdoor; contingência no Apêndice A |
| Repetidor queima ou fica sem energia | Metade do setor "sem sinal" (sem perda) | Alerta imediato; flash de cada ESP32 segura semanas; repetidor em tomada com energia protegida, se possível |
| Ruído elétrico nas entradas | Ciclos falsos | Optoacoplador, debounce, flag de ciclo curto; validar no piloto |
| Mini-PC desligado | Painel parado (sem perda) | Energia protegida, início automático, BIOS Power On; alerta na VPS "servidor local sem contato" |
| Aparelho trocado sem registro | Ciclos na máquina errada | Adoção obrigatória; aparelho não adotado não grava |
| Histórico grande deixa o painel lento | Painel inutilizável | API por período + `resumo_dia` na fase 1 (feito). Setor novo carrega só uma janela de dias. Atualização incremental (só os ciclos novos, `apos=`) feita na 2.1. **Falta na fase 4**: séries do Desempenho (6 meses / 4 anos para trás) e relatórios longos sobre o `resumo_dia`, e acrescentar no navegador sem reprocessar o texto todo |
| Configuração v3 quebra a VPS 1.7.x | Sincronização parada | VPS primeiro; v2 aceito; teste em cópia (`TesteCompatibilidadeVps175` roda o notebook 2.0 contra a VPS da tag `v1.7.5`) |
| Setores criados ao mesmo tempo no notebook e na VPS | O cadastro sincroniza como lista inteira: o setor **sem dados** do lado que perdeu some | Raro (janela de 15 s). Setor com dados nunca some e a lista converge sozinha. Se incomodar: um item por setor com exclusão explícita (ver `docs/progresso-2.0.md`, revisão da fase 1) |
| Arquivo novo fora dos geradores | `.exe` ou VPS sem o módulo: não abre | `TesteGeradoresLevamOsModulos` confere `gerar/exe_fabrica.py` e `gerar/pacote_vps.ps1` |
| Chave vazada | Dados falsos | Chave por aparelho, HMAC, revogação, mestra fora do git |
| OTA ruim em 50 aparelhos | Coleta parada | Canário, ondas, rollback automático |
| Bateria do RTC | Ciclos sem hora | Hora do servidor a cada envio; alerta de relógio; troca da CR2032 a cada ~2 anos |

## 16. Pendências (não bloqueiam a fase 1)

1. **Nome do novo setor** e lista das ~50 máquinas (nome, linha ou célula,
   produção por hora). Pode ser cadastrado pelo próprio painel quando a
   fase 1 estiver pronta.
2. **Posição dos 2 APs** e tomada para o repetidor, conforme a prova de
   alcance.

## Apêndice A — Contingência: gateway ESP32 (ESP-NOW + cabo)

Analisada em 26/11/2026 e trocada pelos APs em malha. Só volta a valer se
a prova de alcance mostrar pontos que nem o repetidor alcança.

- O ESP32 da máquina envia por **ESP-NOW** (rádio direto entre ESP32, sem
  rede Wi-Fi, com alcance maior no modo LR) a um **gateway ESP32 com porta
  de rede**, que repassa ao mini-PC
  **pelo cabo**. Cada gateway atende ~10 máquinas.
- **A saída do gateway tem que ser pelo cabo**: um gateway que também
  sai pelo Wi-Fi só muda o problema de lugar.
- Confirmação e assinatura **de ponta a ponta** (o gateway não confirma nem
  forja nada), gateway reserva automático, OTA dos nós por um Wi-Fi
  temporário do gateway.
- Exige um firmware de gateway e o envio por ESP-NOW no nó. Por isso fica
  só como contingência.
