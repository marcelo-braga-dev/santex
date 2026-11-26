# Progresso da versão 2.0

> Diário de execução do [plano da 2.0](plano-2.0.md). Atualize ao fim de
> cada sessão: o que ficou pronto, o que falta e onde parou.
> Última atualização: **26/11/2026**.

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
| **1. Fundação multi-setor** | **Em andamento**: etapas 1.1 e 1.2 prontas; faltam 1.3 a 1.5 |
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

### ⏭ 1.3 Painel: seletor de setor e cadastro (PRÓXIMA)
- `painel/index.html` (11,6 mil linhas, um arquivo). Hoje ele usa a
  variável `setorAtual` nas chamadas `/ao-vivo?setor=` e `/config?setor=`
  (linhas ~5094, ~6680, ~7293), mas **`/dados` é chamado sem setor**
  (linhas ~7080 e ~7158). Ali é preciso passar `?setor=`.
- Fazer:
  1. Carregar `GET /setores` ao abrir; **seletor no cabeçalho** (só os
     ativos); lembrar o último setor no `localStorage` e aceitar `?setor=`
     na URL. Trocar o setor recarrega dados, configuração e ao vivo.
  2. **Configurações → Produção → Setores**: lista com nome, tipo e
     situação; criar, renomear, mudar a ordem, desativar/reativar e apagar
     (com a mensagem de erro do servidor quando não puder).
  3. Partes novas em módulo JS separado (`painel/js/setores.js`), sem
     reescrever o que já funciona. Conferir o modo VPS (só leitura sem a
     senha de edição).
- Conferir o resultado no navegador (painel local com banco de teste).
  Nunca abrir o `.exe` da fábrica para testar.

### 1.4 Histórico por período + resumo diário
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

## Como testar
```
python -m unittest discover -s testes -v     # 59 testes (45 da 1.7.5 + 14 da 2.0), pasta temporária
```
Testes da 2.0: `testes/test_setores.py` (regras, banco, rotas, sincronização
de configuração e histórico/ao vivo contra uma VPS de teste em processo
separado).

## Registro das sessões
| Data | O que foi feito |
|---|---|
| 26/11/2026 | Tag `v1.7.5` (fim da série 1.x). Plano da 2.0 (`docs/plano-2.0.md`) com as decisões do usuário. Fase 1: etapas 1.1 (cadastro de setores) e 1.2 (sincronização por setor), 59 testes passando |
