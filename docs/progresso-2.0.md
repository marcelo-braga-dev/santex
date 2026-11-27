# Progresso da versão 2.0

> Diário de execução do [plano da 2.0](plano-2.0.md). Atualize ao fim de
> cada sessão: o que ficou pronto, o que falta e onde parou.
> Última atualização: **27/11/2026** (revisão + etapas 1.3, 1.4 e 1.5).

## ⚠ Antes de tudo

- **A `main` tem código da 2.0 em andamento.** A versão em produção é a
  **`v1.7.5`** (tag). Enquanto a 2.0 não for liberada:
  - **não faça deploy da `main` na VPS** (`sudo bash vps/instalar.sh` a
    partir da `main` instalaria a 2.0 pela metade);
  - **não gere o `.exe` da fábrica a partir da `main`**;
  - uma correção urgente na 1.7.x sai da tag:
    `git checkout -b correcao-1.7 v1.7.5` → corrige → tag `v1.7.6` → deploy
    a partir dessa tag. Depois, leve a correção para a `main`.
- O `APP_VERSAO` da `main` é **`"2.0.0-alfa.2"`** (alfa.1 = fase 1
  fechada, nunca instalada; alfa.2 = + atualização incremental). Nenhum
  deploy de teste foi feito ainda: só com o OK do usuário, VPS primeiro
  (`vps/CLAUDE_VPS.md`). Cada entrega nova sobe o número da alfa.
- As regras do `CLAUDE.md` continuam valendo: banco de produção nunca
  apagado, testes só em pasta temporária, nunca ler o ESP32 real.

## Situação das fases

| Fase | Situação |
|---|---|
| 0. Rede e hardware | Decisões tomadas (plano §2 e §5); instalação e prova de alcance **pendentes** (com o usuário) |
| **1. Fundação multi-setor** | **Código pronto** (1.1 a 1.5, versão `2.0.0-alfa.1`). Falta o **deploy de teste** (VPS primeiro, depois o `.exe`), que depende do OK do usuário |
| 2. Protocolo e servidor (push dos ESP32) | **Quase pronta**: 2.1, 2.2, 2.3, 2.5 (simulador: 50 aparelhos sem perda) e 2.6 (alertas) feitas; 2.4 (fila) adiada com base nas medições; falta a rodada de 24 h do simulador |
| 3. Firmware 4.0 | Não iniciada |
| 4. Painel 50 máquinas | Não iniciada |
| 5. Piloto | Não iniciada |
| 6. Implantação | Não iniciada |

## Fase 1 — etapas

### ✅ 1.1 Cadastro de setores no banco e no servidor
- Tabela `setores` (`setor` = slug, `nome`, `tipo_coleta` multi/unitario,
  `ordem`, `ativo`, `criado_em`) em `ferramentas/banco_dados.py`. Na
  primeira abertura, o setor `enfestadeiras` (Enfestadeiras, multi) entra
  sozinho (`_semear_setores`, `SETOR_INICIAL`). Nada existente muda.
- Regras em **`ferramentas/setores.py`**: `criar`, `editar`, `apagar`,
  `resolver`, `setor_padrao`, `gerar_slug`, `aplicar_lista` (sync).
  - o slug é gerado do nome e nunca muda;
  - não há nomes repetidos;
  - setor com ciclos ou máquinas só pode ser desativado;
  - sempre fica ao menos um setor ativo.
- Rotas em `app/servidor.py`:
  - `GET /setores` → `{setores, padrao, tiposColeta}`;
  - `POST /setores` `{acao: criar|editar|apagar, ...}`, com a permissão de
    edição de sempre (na VPS: senha de edição + origem);
  - `/dados`, `/ao-vivo` e `/config` aceitam `?setor=` (ou `setor` no corpo
    do `POST /config`). Setor desconhecido → 404. Sem setor → o primeiro
    ativo;
  - o cache do CSV do `/dados` é por setor, e o ETag leva o setor.

### ✅ 1.2 Sincronização com a VPS por setor
Arquivo: `ferramentas/nuvem.py`.
- **Chaves de configuração com setor**: o setor legado (`SETOR_LEGADO` =
  `enfestadeiras`) fica **sem prefixo** (`maquina:1`, `turnos` — formato da
  1.x, a VPS 1.7.5 continua entendendo). Os outros setores levam o slug:
  `costura/maquina:1`, `costura/turnos`, `costura/extras:motivos`…
  Funções: `separar_chave`, `chave_do_setor`, `chave_item_valida`.
- **Itens globais sem prefixo**: `extras:visual`, `extras:logo`, senhas,
  `edicao_remota` e **`setores`** (o cadastro inteiro, aplicado por
  `setores.aplicar_lista`; o item vai primeiro em cada troca —
  `_ordem_sync`).
- `itens_atuais(banco)` percorre **todos os setores do cadastro**.
  `alterar_setores()` registra revisão e auditoria do item `setores`.
- **Histórico**: `EnviadorConfig.enviar_historico` envia setor por setor
  (`_enviar_historico_setor`), com cursor próprio por setor no segredo
  `cursor_historico_nuvem` (`{"url", "ate" (legado), "setores": {slug: id}}`).
  A conferência de totais também é por setor.
- **Ao vivo**: `enviar_ao_vivo` manda cada setor com leitura recente. Nos
  setores que não são o legado, o notebook é a única fonte da VPS (laço
  rápido de 5 s; a VPS não compara com o envio direto do ESP32).
- A VPS recusa (400) histórico com slug de setor inválido.
- Ordem de implantação: **VPS primeiro**. Com a VPS 1.7.5, os itens dos
  setores novos ficam pendentes no notebook (sem perda), e as Enfestadeiras
  seguem normais.

### ✅ Revisão da fase 1 (26/11/2026, depois do pull)
Análise do que veio nas etapas 1.1 e 1.2. O que foi encontrado e o que foi
feito:

| # | Ponto | Situação |
|---|---|---|
| 1 | O painel pedia `/dados` sem setor: com outro setor em primeiro (ou as Enfestadeiras desativadas), mostraria o histórico errado | **Resolvido na 1.3** (`/dados?setor=` nos dois pontos) |
| 2 | Cadastro de setores sincroniza como lista inteira (a revisão mais nova vale): dois setores criados ao mesmo tempo, um em cada lado, na mesma janela de 15 s → o setor **sem dados** do lado perdedor some | **Limitação conhecida, aceita** (raro; o cadastro muda pouco). O setor com dados nunca some (ver 3). Se incomodar: trocar a lista por um item por setor (`setor:<slug>`), com exclusão explícita |
| 3 | Quem recebia a lista e mantinha um setor com dados fora dela ficava diferente do outro lado, sem aviso | **Resolvido**: o lado que manteve devolve a lista (notebook: `_setores_divergem` deixa o item pendente; a VPS dá revisão nova e o notebook junta na confirmação). Testes `test_setor_com_dados_mantido_*` |
| 4 | Apagar um setor deixa as revisões antigas das chaves dele em `config_rev` | **Aceito** (não causa erro; um setor recriado com o mesmo slug continua sobre elas). Itens de um setor que ainda não chegou ao cadastro do outro lado podem ficar gravados "sem dono" até a lista chegar; a convergência de 3 resolve quando o setor tem dados |
| 5 | Todo GET consultava o cadastro (até arquivos e `/status`) | **Resolvido**: só `/dados`, `/ao-vivo` e `/config` |
| 6 | Convivência notebook 2.0 × VPS 1.7.5 só descrita, sem teste | **Resolvido**: `TesteCompatibilidadeVps175` sobe a VPS do código da tag `v1.7.5` (extraído com `git archive` para a pasta temporária) |
| 7 | Cache do CSV por setor guarda o histórico inteiro de cada setor na memória | **Fica para a 1.4** (consultas por período + `resumo_dia`) |
| 8 | **Os geradores não levavam `setores.py`** (nem `unicodedata` no `.exe`): o `.exe` e a VPS gerados da `main` não abririam | **Resolvido** em `gerar/exe_fabrica.py` e `gerar/pacote_vps.ps1` (também `painel/js/`). `TesteGeradoresLevamOsModulos` confere a cada execução |

### ✅ 1.3 Painel: seletor de setor e cadastro
- **`index.html`** (mudanças pequenas, sem reescrever):
  - `SETORES` vem do servidor (`definirSetores`); até chegar (ou sem
    servidor), vale o setor legado com as 4 máquinas.
  - Máquinas do setor = as cadastradas no `/config` do setor (o legado
    sempre tem as 4). `sincronizarConfigComServidor` percebe quando a lista
    muda e refaz a tela (`selecionarSetor(id, maquinas)`).
  - `selecionarSetor` tira os cartões do setor anterior, zera o estado ao
    vivo e busca dados e ao vivo na hora. `/dados`, `/ao-vivo` e `/config`
    descartam respostas atrasadas do setor anterior.
  - `/dados?setor=` (atualização automática e backup; o nome do backup leva
    o setor, menos o das Enfestadeiras).
  - Cores: com mais de 6 máquinas a paleta se repete (a visão para 50
    máquinas é da fase 4).
  - Gravações em `/setores` contam como "deste painel" (sem o aviso de
    alteração feita por outro).
  - `window.PainelNucleo`: o que os módulos de `painel/js/` podem usar.
- **`painel/js/setores.js`** (novo):
  - seletor no cabeçalho (só os ativos). Setor inicial: `?setor=` no
    endereço (abre até desativado), senão o último escolhido no aparelho
    (`painel_setor`), senão o padrão do servidor; a troca atualiza os dois;
  - cartão **Configurações → Produção → Setores**: criar (nome, coleta,
    quantas máquinas), renomear, ↑/↓, desativar (com confirmação)/reativar,
    apagar (só sem dados, com confirmação) e "+ Máquina" (setores novos). Sem
    permissão: só a lista e a explicação.
- Servidor: `GET /setores` (e a resposta do POST) informa `maquinas` e
  `temDados` por setor.
- Conferido no navegador (Edge headless controlado por script, servidor com
  banco temporário e sem leitura do ESP32): troca de setor, cartões e dados
  certos, endereço e escolha lembrados, todas as ações do cartão, nome
  repetido recusado, sem erro no console.
- **Ainda não dá para remover uma máquina** de um setor (o servidor não tem
  essa operação). Fica para a fase 2/4 (dispositivos e máquinas `ativa`).

### ✅ 1.4 Histórico por período + resumo diário
- **`resumo_dia`** (`banco_dados.py`): ciclos e segundos ligada por setor,
  máquina e dia. Mantido na **mesma transação** de cada ciclo gravado
  (`gravar_ciclo`, `gravar_ciclo_remoto`, inclusive quando um ciclo sem hora
  ganha a hora real: tira a versão antiga e soma a nova). Mesmas regras do
  CSV: fora os simulados e os baixados sem relógio. Ciclo que passa da
  meia-noite divide o tempo entre os dias e conta no dia do fim
  (`partes_por_dia`). `recalcular_resumo` refaz tudo em SQL (só os que passam
  da meia-noite vão para o Python). Banco da 1.x: calculado na primeira
  abertura (`_garantir_resumo`, marca `resumo_dia_versao` em `segredos`).
- **Índice `ciclos(setor, gravado_em)`**, e não `(setor, maquina,
  inicio_ms)` como estava no plano: `inicio_ms` é texto e muitas vezes não
  tem hora real (plano §10 corrigido). O índice único `(dispositivo,
  origem_id)` já existia.
- **Rotas** (`servidor.py`, na VPS também, atrás do login):
  - `GET /api/v2/ciclos?setor=&de=&ate=&maquinas=&formato=csv|json`: CSV no
    formato do `/dados`, pelo fim do ciclo; até 400 dias por pedido;
  - `GET /api/v2/resumo?setor=&de=&ate=&agrupar=dia|maquina|dia_maquina&maquinas=`:
    até ~10 anos. **Por turno ainda não**: as regras de turno (pausas,
    calendário, turno que passa da meia-noite, horário por dia) estão só no
    painel; levar para o servidor é trabalho da fase 4;
  - `/dados?desde=AAAA-MM-DD` (ETag própria, cache por setor + janela).
- **Versão dos ciclos sem `COUNT(*)`** (maior id + somas do resumo).
- **Painel, setores novos** (`index.html`): janela de dados
  (`janelaDesde`, 14 dias + 2 de folga). `garantirJanela` amplia e rebaixa
  quando algo pede um período mais antigo; o gancho fica em
  `aplicarFiltroPeriodo` (cobre barra de período, `comPeriodo`, séries do
  Desempenho e histórico de paradas). Relatórios esperam a janela (período
  e o anterior) antes de gerar; períodos "sem produção" pedem desde o
  início deles (até ~13 meses). Respostas de uma janela antiga são
  descartadas. **As Enfestadeiras continuam com o histórico inteiro**
  (`janelaDesde = null`), sem mudança de comportamento.
- Conferido no navegador: Enfestadeiras pedem `/dados?setor=enfestadeiras`;
  Costura abre com `desde=` de 14 dias e, na visão de mês e no mês anterior,
  a janela cresceu sozinha com os números certos.
- **Teste de volume** (`ferramentas/teste_volume.py`, 1.825.000 ciclos =
  50 máquinas × 365 dias × 100; duas rodadas, a 2ª com o PC mais carregado):

  | Medição | Tempo |
  |---|---|
  | Calcular o `resumo_dia` do ano inteiro (uma vez) | 19–39 s (antes, em Python: 162 s) |
  | Gravar um ciclo (com o resumo junto) | 1,4–2,5 ms |
  | Resumo do ano por dia / por máquina | 0,02–0,16 s |
  | CSV de 1 dia (`/api/v2/ciclos`) | 0,07–0,4 s (179 KB) |
  | CSV da janela de 16 dias (`/dados?desde=`) | ~5 s (2,9 MB) |
  | CSV da janela de 35 dias | 2,2–7 s (6,2 MB) |
  | Versão dos ciclos (ETag) | 0,01–0,02 s (antes: 1,7 s) |
  | CSV do histórico inteiro (`/dados` antigo) | 18–60 s (64 MB) — inviável |
  | Tamanho do banco | 334 MB |

- **Conclusões para as próximas fases** (não bloqueiam o alfa, mas sim o
  piloto com 50 máquinas):
  1. **Atualização incremental**: com 50 máquinas chega ciclo a cada poucos
     segundos, e cada ciclo novo muda a versão e obriga a remontar (segundos
     de CPU) e rebaixar (MB) a janela inteira, em cada aparelho. Fazer
     `/dados?desde=&apos_id=` (só os ciclos novos) e o painel acrescentar
     sem reprocessar tudo. **Fase 2** (junto com o recebimento por push).
  2. **Séries e períodos longos pelo resumo**: a série do Desempenho busca
     6 meses (visão mês) ou 4 anos (visão ano) de ciclos brutos. Na fase 4,
     calcular essas séries e os relatórios longos com `/api/v2/resumo`.
  3. O backup do painel (CSV) de um setor grande baixa o histórico inteiro:
     na fase 4, trocar por exportação por período.

### ✅ 1.5 Fechamento da fase 1 (falta só o deploy, com o OK do usuário)
- `APP_VERSAO = "2.0.0-alfa.1"`; CHANGELOG; `vps/CLAUDE_VPS.md` com o bloco
  do deploy de teste (cópia do banco antes, VPS primeiro, verificações, como
  voltar); `docs/nuvem-vps.md` (seção 2.0) e `docs/painel.md` (setores,
  cadastro, janela de dados, limites).
- **Versão com sufixo**: o `ping` passou a responder `"versao": "2.0.0"` (só
  números) + `"versaoCompleta"`, porque o notebook 1.7.x lê a versão com
  `int()` e acharia que a VPS `2.0.0-alfa.1` é antiga (deixaria de
  reenviar a hora dos ciclos `SEM_HORA`). O notebook 2.0 aceita sufixo. O
  gerador do `.exe` aceita sufixo no nome.
- **Convivência testada nos dois sentidos**, com o código da tag `v1.7.5`
  extraído para a pasta temporária e rodando em processo separado:
  `TesteCompatibilidadeVps175` (notebook 2.0 × VPS 1.7.5) e
  `TesteCompatibilidadeNotebook175` (VPS 2.0 × notebook 1.7.5 — o caso
  real do deploy "VPS primeiro" — e a **volta para a 1.7.5** abrindo um
  banco que já passou pela 2.0).
- O teste da volta mostrou um problema e ele foi corrigido: ciclos gravados
  pela 1.7.5 depois de uma volta não entravam no `resumo_dia` quando a 2.0
  subia de novo. Agora, ao abrir, o banco confere a contagem
  (`_resumo_confere`) e recalcula se não bater. Custo: uma contagem ao
  abrir (≈1–2 s com 1,8 milhão de ciclos; hoje, instantânea).
- **Deploy de teste: pendente.** Ordem: (1) cópia do banco da VPS, (2) VPS
  com a `main`, verificações do `vps/CLAUDE_VPS.md`, (3) gerar o `.exe`
  `PainelProducaoSantex-2.0.0-alfa.1.exe` e instalar no notebook,
  (4) conferir as Enfestadeiras idênticas e criar um setor de teste.

## Fase 2 — etapas

### ✅ 2.1 Atualização incremental do `/dados` (versão `2.0.0-alfa.2`)
- `banco.csv_e_ultimo_id(setor, desde, apos)`: CSV + maior id coberto. Com
  `apos`, só `id > apos` pelo índice `(setor, id)`; o `desde` é aplicado
  depois, para o id avançar também sobre um ciclo antigo que chegou
  atrasado (fora da janela). `csv_do_setor` continua igual (usa o novo).
- `/dados` manda `X-Ultimo-Id` (também no 304) e aceita `apos=`; com `apos`
  não há cache nem ETag (a consulta é instantânea). `X-Ultimo-Id` entra no
  `Access-Control-Expose-Headers`.
- Painel (`autoAtualizarDados`): depois de uma carga completa, pede
  `&apos=<último id>` e acrescenta as linhas novas ao texto que já tem
  (`loadFromText` do texto acumulado — o reprocessamento no navegador
  continua; trocar por um acréscimo de verdade é da fase 4). Carga completa
  a cada 10 min (`CARGA_COMPLETA_MS`), na troca de setor e quando a janela
  cresce. Servidor sem o cabeçalho: só cargas completas.
- **Limite conhecido**: um ciclo que já existe e muda (o caso 1.7.1: ganha
  a hora real) não é "novo" — aparece na próxima carga completa (até
  10 min). Acontece quase só na VPS, quando o notebook completa a hora.
- Teste: `test_dados_incrementais_somam_o_mesmo_que_a_carga_completa`
  (carga completa + incrementais == carga completa nova, com e sem
  `desde`, inclusive com ciclo atrasado). No navegador, com um ciclo novo a
  cada 4 s: os pedidos passam a `apos=6557`, `6558`, `6559`…
- Volume (1,8 milhão de ciclos): só os novos em **0,001 s** (50 ciclos,
  1,9 KB), contra ~1 s e 2,9 MB da janela de 16 dias.

### ✅ 2.2 Cadastro de dispositivos (versão `2.0.0-alfa.2`)
- Tabelas `dispositivos` e `dispositivo_atribuicoes` (plano §10; mais
  `criado_em` e o índice `idx_atribuicoes_disp`). Métodos de banco em
  `banco_dados.py` (`obter/listar/salvar_dispositivo`,
  `dispositivo_da_maquina`, `abrir/fechar_atribuicao`, `atribuicoes`).
- Regras em **`ferramentas/dispositivos.py`**:
  - ids: unitário `esp-<MAC 12 hex>`; multi (firmware 3.x)
    `<MAC 12 hex>-<série 8 hex>`. Outro formato = ignorado;
  - `registrar_contato` (cria "novo" no 1º contato — **só chamar depois
    de conferir a assinatura**, na 2.3; até 200 novos de uma vez);
  - `adotar` (unitário novo/reserva → máquina livre de um setor), `trocar`
    (o reserva assume a máquina do antigo), `liberar`, `bloquear` (libera a
    máquina), `desbloquear`, `renomear`; `executar` para a rota;
  - `registrar_multi`: o ESP32 das Enfestadeiras entra **ativo** no setor
    dele (era assim antes da 2.0), reconhecido pela **série** — o mesmo
    controlador já apareceu com 3 MACs diferentes. Nunca levanta exceção.
- Ganchos no caminho de produção (protegidos por `registrar_multi_seguro`,
  em `monitor_wifi.py`, que engole até erro de importação): leitura pelo
  Wi-Fi no notebook (`_baixar_ciclos`) e envio direto do ESP32 à VPS
  (`nuvem.receber_do_esp`).
- Rotas: `GET /dispositivos` (lista + `semSinal`, sem contato há mais de
  30 s; na VPS também, atrás do login) e `POST /dispositivos`
  `{acao, ...}` (só no computador da fábrica: na VPS, 403). Adotar numa
  máquina que o setor ainda não tem cadastra a máquina via
  `nuvem.aplicar_config` (com o apelido do aparelho como nome) — entra na
  auditoria e sincroniza com a VPS.
- `setor_tem_dados` conta aparelhos e atribuições: setor que já teve
  aparelho só pode ser desativado.
- Ainda **sem tela no painel** (Configurações → Sistema → Dispositivos é da
  fase 4) e o cadastro **não sobe para a VPS** (plano §11: só leitura,
  depois). `config_rev` do aparelho fica para a 2.3 (configuração enviada
  na resposta do coletor).
- `testes/test_dispositivos.py` (10 testes).

### ✅ 2.3 `/api/v2/coletor` (versão `2.0.0-alfa.2`)
- **Chave-mestra** `COLETOR_CHAVE_MESTRA`: o `gerar_segredos.py` cria uma
  aleatória no `.env` quando falta (como já fazia com `API_CHAVE` e
  `NUVEM_CHAVE`) e a põe **só** no `app/segredos_app.json` (nunca no
  `segredos.h` do firmware, nunca na VPS). `.env.exemplo` documenta. O
  `.env` real **ainda não foi tocado**: a chave é criada na próxima vez que
  o `gerar_segredos.py` rodar (antes de gerar o `.exe`). Sem a mestra, a
  rota responde 503 ("coletores desligados").
- **`ferramentas/receptor_push.py`**:
  - `chave_do_aparelho(mestra, id)` = HMAC-SHA256 em hex — é essa string
    (texto hex) que o provisionamento grava no aparelho e que o firmware usa
    como chave do HMAC;
  - `autenticar`: corpo ≤ 64 KB, `v: 2`, id válido, `X-Assinatura` =
    HMAC(chave do aparelho, `X-Ts` + "." + corpo) comparada em tempo
    constante; `X-Ts` fora de ±120 s → 401 `"relogio"` **com a hora do
    servidor** (um aparelho com o RTC errado consegue se acertar e tentar de
    novo; a hora não é segredo);
  - `processar`: registra o contato; bloqueado → 403; não adotado →
    `adotado: false, ack_ate: 0` (nada gravado); adotado → cada ciclo
    gravado com **setor e máquina do cadastro** (o canal só vale no perfil
    multi), `gravado_em` = fim do ciclo (com `SEM_HORA`: sem hora real, fica
    fora do resumo), estado ao vivo, e `ack_ate` = maior id do lote ou o
    maior já guardado (batimento sem ciclos também libera a flash). Ciclo
    inválido é confirmado assim mesmo (nunca ficaria válido e travaria a
    flash). No máximo 200 ciclos por pedido. Vírgula no `obs` vira `;` (CSV).
- Rota no `servidor.py`, **antes** do login/PIN (a assinatura é a
  autenticação); na VPS → 404. Assinatura errada conta por IP
  (`limite_coletor`, 10 em 10 min → 429). Resposta só depois do COMMIT de
  cada ciclo.
- **Não feito (de propósito)**: conferência do `seq` contra reenvio dentro
  dos 120 s (um reenvio só repete dados idempotentes); comandos
  (`identificar`, `reiniciar`, `ota`) — `comando` vai sempre `null` até a
  fase 3; `config.rev` vai o do cadastro (0).
- `testes/test_coletor.py` (9 testes) + a VPS recusando a rota (404).

### ✅ 2.5 Simulador de coletores (feito antes da 2.4, para medir primeiro)
- **`ferramentas/simulador_coletores.py`**: N ESP32 virtuais com o
  protocolo real contra o servidor num banco **temporário** (sem `main()`:
  sem leitura do ESP32 nem envio à VPS). Cada um liga/desliga a máquina,
  guarda os ciclos numa "flash" e só apaga até o `ack_ate`, batimento a cada
  `--intervalo` s, envio na mudança (atraso 0–2 s), espera dobrando na
  falha. Caos: reinícios (reenvio imediato), **metade cai junta** (repetidor
  fora) entre 40 % e 60 % do tempo, aparelho nº 1 com o **relógio 10 min
  errado** (o servidor recusa e devolve a hora). No fim confere cada ciclo
  no banco (`banco.ciclos_por_origem`). Mais de 50 aparelhos: um setor a
  cada 50 (limite de 64 máquinas por setor).
- Resultados (3 min, com a queda e o relógio errado):

  | Aparelhos | Pedidos/s | Ciclos | Perdidos / duplicados | Resposta mediana / p95 / máx |
  |---|---|---|---|---|
  | **50** (o previsto) | 7,2 | 544 | **0 / 0** | 5,6 / 34 / 537 ms |
  | 200 (4×) | 28,3 | 2.163 | **0 / 0** | 11 / 613 / 2.065 ms |

  (Com 200, parte da demora é o próprio simulador: 200 threads Python no
  mesmo processo do servidor.)
- Versão curta na suíte (`test_simulador_curto_sem_perda_nem_duplicacao`:
  6 aparelhos, 12 s, com a queda e o relógio errado).
- **Falta**: a rodada de 24 h do critério da fase 2 (`--minutos 1440`),
  de preferência no mini-PC.

### ⏸ 2.4 Fila com gravador único — adiada (com base na 2.5)
Com 50 aparelhos a gravação direta responde em 34 ms (p95) sem perder nada,
então a fila não é necessária agora. O que mais escreve no disco é o
**estado ao vivo** (um UPSERT por batimento). Gravar só na mudança não
serve: o painel calcula "sem sinal" pelo `atualizado_em`
(`obter_estado_ao_vivo`). O certo é manter o estado ao vivo em memória e
juntá-lo na leitura (plano §9.3). Fazer quando: o piloto mostrar demora,
ou antes de passar de ~100 aparelhos.

### ✅ 2.6 Alertas de comunicação
- `dispositivos.alertas(banco)` (plano §9.4), devolvido em
  `GET /dispositivos` → `"alertas"`: `[{tipo, nivel, dispositivo?, setor?,
  maquina?, texto}]`. Só aparelhos **ativos** contam para comunicação.
  - `repetidor` (crítico): todos os ativos de um mesmo AP (`bssid`, 2 ou
    mais) sem sinal juntos → **um** alerta, no lugar dos "sem sinal" deles;
  - `sem_sinal`: sem contato há mais de 30 s;
  - `sinal_fraco`: último RSSI < −75 dBm (o plano pede a **média de 10
    min**: falta guardar histórico de saúde);
  - `flash`: `flash_uso_pct` > 50 %;
  - `relogio`: `hora_valida: false` (o receptor passou a guardar esse campo
    na saúde);
  - `reinicios`: `resets_1h` > 3 — **o firmware 4.0 precisa mandar esse
    campo** na saúde (anotar no protocolo da fase 3);
  - `novo`: aparelhos esperando adoção.
- Ainda **sem tela** (fase 4: cartão cinza "sem sinal", lista de
  Dispositivos) e sem aviso no rodapé do painel.
- Teste `test_alertas_de_comunicacao`.

### Fase 2 — o que falta
- **Rodada de 24 h** do simulador (critério da fase 2), de preferência no
  mini-PC: `python ferramentas/simulador_coletores.py --minutos 1440`.
- 2.4 (estado ao vivo em memória), se o piloto pedir.
- Média de RSSI de 10 min (histórico de saúde).
- Depois: **fase 3 (firmware 4.0)** — o protocolo do servidor já está
  pronto e testado pelo simulador.

## Pontos de atenção para quem continuar
- `SETOR_PADRAO` (`ferramentas/monitor_serial.py`) ainda existe e é usado
  em: recebimento do ESP32 multi na VPS (`/api/nuvem/enviar`), leitura serial
  e Wi-Fi do notebook, logo da empresa (global, tanto faz) e
  `EnviadorConfig` (setor legado). Está certo: o ESP32 multi pertence às
  Enfestadeiras. Na fase 2, o setor do ESP32 multi passa a vir do cadastro
  de dispositivos.
- `apagar_setor` apaga a configuração (turnos, extras, metas, ao vivo) do
  setor **vazio** apagado. Ciclos e máquinas nunca são apagados.
- Os testes `test_backend` que usavam um setor fictício `"s"` em itens
  sincronizados passaram a usar `enfestadeiras`: na 2.0, só setores do
  cadastro entram na sincronização.
- **Arquivo novo em `ferramentas/` ou `painel/`** precisa entrar nos dois
  geradores (`gerar/exe_fabrica.py` e `gerar/pacote_vps.ps1`). O
  `vps/instalar.sh` copia as pastas inteiras. O teste dos geradores pega
  módulo esquecido que o servidor importa.
- Ao abrir um setor novo pela primeira vez, o painel grava nele os turnos e
  os extras padrão (comportamento de sempre do painel). Isso não conta como
  "dados": o setor continua podendo ser apagado.

- O `resumo_dia` é **dado derivado**: `recalcular_resumo` apaga e refaz só
  ele (os ciclos nunca mudam). Mudou a regra do resumo → suba
  `VERSAO_RESUMO` (`banco_dados.py`) e ele se recalcula sozinho na próxima
  abertura (com 1,8 milhão de ciclos leva ~20 s, uma vez).
- A "versão dos ciclos" (ETag do `/dados`) usa o maior id do setor e as
  somas do `resumo_dia`. Apagar ciclos direto no SQLite (só em teste) não
  muda a versão: em produção nunca se apaga ciclo.

## Como testar
```
python -m unittest discover -s testes -v     # 96 testes (45 da 1.7.5 + 51 da 2.0), pasta temporária
python ferramentas/simulador_coletores.py    # 50 coletores virtuais por 5 min, banco temporário (--aparelhos, --minutos)
python ferramentas/teste_volume.py           # volume: 1 ano de 50 máquinas, banco temporário (~5 min)
```
Testes da 2.0: `testes/test_setores.py` (regras, banco, rotas, sincronização
de configuração e convergência do cadastro, histórico/ao vivo contra uma VPS
de teste em processo separado, notebook 2.0 contra a VPS 1.7.5 da tag e
conferência dos geradores) e `testes/test_resumo.py` (divisão por dia,
quem entra no resumo, incremental = recálculo, hora completada depois,
banco da 1.x, agrupamentos e as rotas `/api/v2/*` e `/dados?desde=`). O
teste da VPS 1.7.5 é pulado se o `git` ou a tag não estiverem disponíveis.

Painel no navegador sem tocar em nada real: um script que aponta
`caminhos.dir_dados_usuario` para uma pasta temporária (como o
`test_backend`), grava dados de exemplo e sobe `servidor.Handler` em
`[::1]` sem chamar `main()` (então sem leitura do ESP32 nem envio à VPS).

## Registro das sessões
| Data | O que foi feito |
|---|---|
| 26/11/2026 | Tag `v1.7.5` (fim da série 1.x). Plano da 2.0 (`docs/plano-2.0.md`) com as decisões do usuário. Fase 1: etapas 1.1 (cadastro de setores) e 1.2 (sincronização por setor), 59 testes passando |
| 26/11/2026 | Revisão das etapas 1.1/1.2 (tabela acima): convergência do cadastro, GET mais leve, geradores corrigidos, testes de compatibilidade com a VPS 1.7.5 e dos geradores. Etapa 1.3 (seletor de setor e cartão Setores, `painel/js/setores.js`), conferida no navegador. 63 testes passando |
| 26/11/2026 | Etapa 1.4: `resumo_dia`, índice por `gravado_em`, `/api/v2/ciclos`, `/api/v2/resumo`, `/dados?desde=`, janela de dados no painel (só setores novos), ETag sem `COUNT(*)`, teste de volume (tabela na 1.4). 72 testes passando |
| 27/11/2026 | Etapa 1.5: versão `2.0.0-alfa.1` (ping só com números + `versaoCompleta`; `.exe` com sufixo), testes da convivência com a 1.7.5 nos dois sentidos e da volta para a 1.7.5 (corrigido: resumo recalculado ao abrir se não bater), docs do deploy de teste. 74 testes passando. Deploy de teste pendente (OK do usuário) |
| 27/11/2026 | Fase 2, etapa 2.1: atualização incremental do `/dados` (`X-Ultimo-Id`, `apos=`), conferida no navegador e no volume. Etapa 2.2: cadastro de dispositivos (adoção, troca, ESP32 multi registrado pela série). Etapa 2.3: `/api/v2/coletor` (HMAC por aparelho, chave-mestra gerada pelo `gerar_segredos.py`). Etapa 2.5: simulador (50 e 200 aparelhos por 3 min, com queda de rede e relógio errado: nenhum ciclo perdido nem duplicado); 2.4 adiada. Etapa 2.6: alertas de comunicação. Versão `2.0.0-alfa.2`. 96 testes passando |
