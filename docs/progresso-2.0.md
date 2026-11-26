# Progresso da versão 2.0

> Diário de execução do [plano da 2.0](plano-2.0.md). Atualize ao fim de
> cada sessão: o que ficou pronto, o que falta e onde parou.
> Última atualização: **26/11/2026** (2ª sessão: revisão + etapa 1.3).

## ⚠ Antes de tudo

- **A `main` tem código da 2.0 em andamento.** A versão em produção é a
  **`v1.7.5`** (tag). Enquanto a 2.0 não for liberada:
  - **não faça deploy da `main` na VPS** (`sudo bash vps/instalar.sh` a
    partir da `main` instalaria a 2.0 pela metade);
  - **não gere o `.exe` da fábrica a partir da `main`**;
  - uma correção urgente na 1.7.x sai da tag:
    `git checkout -b correcao-1.7 v1.7.5` → corrige → tag `v1.7.6` → deploy
    a partir dessa tag. Depois, leve a correção para a `main`.
- O `APP_VERSAO` continua `"1.7.5"` de propósito. Ele só muda para
  `2.0.0-alfa.1` quando a fase 1 terminar (primeiro deploy de teste da 2.0).
- As regras do `CLAUDE.md` continuam valendo: banco de produção nunca
  apagado, testes só em pasta temporária, nunca ler o ESP32 real.

## Situação das fases

| Fase | Situação |
|---|---|
| 0. Rede e hardware | Decisões tomadas (plano §2 e §5); instalação e prova de alcance **pendentes** (com o usuário) |
| **1. Fundação multi-setor** | **Em andamento**: etapas 1.1, 1.2 e 1.3 prontas; faltam 1.4 e 1.5 |
| 2. Protocolo e servidor (push dos ESP32) | Não iniciada |
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

### ⏭ 1.4 Histórico por período + resumo diário (PRÓXIMA)
- Tabela `resumo_dia (setor, maquina, dia, ciclos, segundos_ligada,
  atualizado_em)`, mantida a cada ciclo gravado e recalculável (plano §10).
- Índices `ciclos(setor, maquina, inicio_ms)` e
  `ciclos(dispositivo, origem_id)`. **Atenção**: já existe o índice único
  `idx_ciclos_origem` em `(dispositivo, origem_id)`, então não duplicar.
- Rotas `GET /api/v2/ciclos?setor=&de=&ate=&maquinas=` e
  `GET /api/v2/resumo?setor=&de=&ate=&agrupar=dia|turno|maquina`.
- Painel passa a pedir por período. O `/dados` antigo continua existindo
  (compatibilidade com o programa remoto 1.2.0).
- Teste de volume: 1 ano sintético de 50 máquinas (~2 milhões de ciclos).

### 1.5 Fechamento da fase 1
- `APP_VERSAO = "2.0.0-alfa.1"`, CHANGELOG, `vps/CLAUDE_VPS.md` (bloco do
  deploy da 2.0: VPS primeiro), `docs/nuvem-vps.md`, `docs/painel.md`.
- Deploy de teste na VPS **só com o OK do usuário**; depois, o `.exe`.

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

## Como testar
```
python -m unittest discover -s testes -v     # 63 testes (45 da 1.7.5 + 18 da 2.0), pasta temporária
```
Testes da 2.0: `testes/test_setores.py` (regras, banco, rotas, sincronização
de configuração e convergência do cadastro, histórico/ao vivo contra uma VPS
de teste em processo separado, notebook 2.0 contra a VPS 1.7.5 da tag e
conferência dos geradores). O teste da VPS 1.7.5 é pulado se o `git` ou a
tag não estiverem disponíveis.

Painel no navegador sem tocar em nada real: um script que aponta
`caminhos.dir_dados_usuario` para uma pasta temporária (como o
`test_backend`), grava dados de exemplo e sobe `servidor.Handler` em
`[::1]` sem chamar `main()` (então sem leitura do ESP32 nem envio à VPS).

## Registro das sessões
| Data | O que foi feito |
|---|---|
| 26/11/2026 | Tag `v1.7.5` (fim da série 1.x). Plano da 2.0 (`docs/plano-2.0.md`) com as decisões do usuário. Fase 1: etapas 1.1 (cadastro de setores) e 1.2 (sincronização por setor), 59 testes passando |
| 26/11/2026 | Revisão das etapas 1.1/1.2 (tabela acima): convergência do cadastro, GET mais leve, geradores corrigidos, testes de compatibilidade com a VPS 1.7.5 e dos geradores. Etapa 1.3 (seletor de setor e cartão Setores, `painel/js/setores.js`), conferida no navegador. 63 testes passando |
