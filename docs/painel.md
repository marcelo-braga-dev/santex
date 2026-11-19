# Painel web (`painel/index.html`)

Dashboard de produção em uma página só (HTML/CSS/JS autocontido, sem
dependência de build) — abre direto no navegador, duplo clique no arquivo.
Visual de dashboard profissional com **identidade laranja** (menu
superior em gradiente laranja com texto branco, laranja como cor de
destaque da interface), tema claro por padrão e tema escuro opcional, com
menu principal fixo no topo e seções em abas —
tudo em CSS puro, sem biblioteca de UI. A versão anterior do layout está
guardada em `painel/_backup/index_v1_antes_redesign.html`.

### Layout geral (v3)

```
┌ Barra superior fixa (identidade da marca) ─────────────────────────────────┐
│ Logo │ Painel de Produção    ( Visão geral | Desempenho )   ⚙ → Turnos    │
│        Setor X                                           🕐 hora/data │ ⚙   │
└─────────────────────────────────────────────────────────────────────────────┘
┌ Barra de filtros (cartão) ──────────────────────────────────────────────────┐
│ [■] SETOR       │ [▦] PERÍODO                      │ [◷] TURNO      [Exportar│
│     Setor X ▾   │  Dia Semana Mês Ano  ‹ data ›    │  Todos ▾        Excel] │
├─────────────────────────────────────────────────────────────────────────────┤
│ ⏷ Exibindo: [Dia 13/11/2026 (hoje)] [Turno: Todos]        ↺ Voltar para hoje │
└─────────────────────────────────────────────────────────────────────────────┘
  ── conteúdo da aba ativa ──
┌ Barra de status fixa no rodapé ─────────────────────────────────────────────┐
```

- **Barra superior**: marca à esquerda, abas centralizadas num "trilho"
  (aba ativa = pílula branca sólida), relógio e ações à direita. Abaixo de
  1320 px as abas descem para uma segunda linha ocupando a largura toda.
- **Tema claro/escuro**: interruptor em ⚙ → Aparência → Tema escuro (o
  menu fica aberto para ver a troca); a escolha fica gravada.
- **Seleção de setor** saiu da barra superior e é o primeiro campo da barra
  de filtros. Com um só setor cadastrado, aparece só o nome (sem lista).
- **Exportar Excel** fica em destaque na barra de filtros (em telas
  menores desce para a linha do resumo). **Importar dados** foi para
  ⚙ → Dados (arrastar o CSV para a tela continua funcionando).
- **Linha "Exibindo"**: resumo em texto do período e turno na tela. Quando
  o filtro sai do padrão (outro dia/semana/mês/ano ou um turno escolhido)
  o chip fica destacado e aparece **Voltar para hoje**, que volta para Dia
  (hoje) + Todos os turnos.
- Versão anterior guardada em `painel/_backup/index_v2_antes_redesign_menu.html`.
- **Barra de status (rodapé)**: à esquerda, o controle de atualização
  automática (**Ao vivo / Pausado / Offline** + botão Pausar/Ativar); no
  meio, avisos curtos; à direita, o estado do ESP32.
  Clicar em **ESP32** abre os detalhes da sincronização (rede, IP, última
  sincronização, último lote, avisos de ciclos sobrescritos/relógio
  acertado); um ponto laranja no botão indica que há aviso. A antiga faixa
  "Fonte: … · N ciclos · último ciclo" foi removida.

| Seção (aba) | Conteúdo |
|---|---|
| **Visão geral** | Faixa de **alerta** (máquina parada além do limite); os cartões **Rendimento por máquina**; a **Linha do tempo por máquina**; 5 KPIs (tempo ligado, tempo parado, rendimento com meta/comparação/minigráfico, produção estimada, ligadas agora); **ranking** de rendimento |
| **Desempenho** | Tempo ligado por hora, **evolução do rendimento**, análise de paradas, **disciplina de turno**, **produção por turno** (gráfico + tabela), comparativo entre turnos e **tabela de ciclos registrados** (filtro por máquina, busca e "somente alertas"). A antiga aba "Análise temporal" foi incorporada aqui |
| **Turnos e calendário** (⚙ Configurações → Turnos e calendário) | Cards de configuração: **Turnos cadastrados** (edição direta — ver abaixo), **Intervalo de refeição**, **Calendário e paradas programadas**, **Motivos de parada** e **Histórico de configurações** |
| **Identidade visual** (⚙ → Aparência) | Editor da paleta da marca — ver abaixo |

### Como os cartões calculam (base: turno → agora)

Todos os números de tempo usam a mesma base, o **tempo disponível**:
cada turno conta do **início** até o **fim**, ou **até agora** se ainda
estiver correndo. Horas que ainda não passaram nunca entram.

| Valor | Cálculo |
|---|---|
| **Horímetro (tempo ligado)** | Tempo ligado **dentro** das janelas de turno (ciclo que começou antes do turno conta só o trecho depois do início) |
| **Parado** | Disponível − ligado |
| **Rendimento** | Ligado ÷ disponível |
| **Produção** | Ligado × taxa (digitada em m/h; guardada em m/min) |
| **Meta (anel)** | Ligado ÷ (meta % × tempo disponível de cada turno considerado, inteiro e sem pausas). Ex.: meta 85%, Turno 1 de 9 h → 7 h 39 min ligada; quando o Turno 2 começa, a meta do dia cresce junto |

- Ligado + parado = disponível, em qualquer filtro.
- Entram os turnos em que o setor produziu (qualquer máquina) e o turno
  atual, mesmo sem ciclo ainda. Turno/dia sem produção nenhuma (folga) não
  entra. Ciclos fora de qualquer turno não entram nos cartões (continuam
  na tabela de ciclos).
- Turno escolhido que ainda não começou: parado e rendimento mostram "—".
- O selo **"Disponível: …"** no cabeçalho de "Rendimento por máquina" mostra
  a base atual (ex.: "Turno 1 · 07:00 → agora · 51m 35s"); passe o mouse
  para ver a lista de turnos considerados.
- **Meta em %** (antes era "horas ligada por dia"): a meta é a porcentagem
  do tempo disponível do turno em que cada máquina deve ficar ligada — o
  mesmo número aparece no selo "Meta por turno", na linha tracejada do
  comparativo, no ranking e (como % de cada hora) no gráfico por hora. Na
  atualização, a meta em horas foi convertida uma vez sem mudar a meta
  efetiva de um dia completo (8 h ÷ 14 h de turno = 57,1%); a antiga fica
  guardada no banco (`meta_horas_dia`), sem uso. Com a meta em horas, o
  mesmo valor aparecia como 89% de manhã e 57% à noite — por isso a troca.
- Sem data/hora real nos ciclos (ou "todo o histórico"): base do primeiro
  ao último ciclo, como antes.

### Os outros indicadores e gráficos usam a mesma base

Tudo que mostra tempo ligado, parado, rendimento ou produção sai do mesmo
cálculo dos cartões (ciclos do período + ciclo em andamento, recortados
pelas janelas turno → agora), então os números batem entre si:

| Onde | Como fica |
|---|---|
| **KPIs** (tempo ligado, rendimento médio, meta, produção) | **Tempo ligado = média por máquina** (o total aparece embaixo); rendimento e meta = média dos cartões; produção = soma. "Ciclos" avisa quantos começaram **fora de turno** |
| **Comparativo de rendimento** e **Ranking** | Mesmo rendimento dos cartões, agora **incluindo o ciclo em andamento**. Meta = meta ÷ horas de turno. Turno que ainda não começou: aviso em vez de barras zeradas |
| **Linha do tempo** | Eixo do **início do turno até agora** (antes: do 1º ao último ciclo). Trilho claro = turno, vazio = parado, hachurado = fora de turno, linha laranja "agora", ciclo em andamento pulsando, marcas de hora |
| **Tempo ligado por hora** | Cada ciclo é **dividido entre as horas que cobre** (antes, um ciclo 07:30–09:45 caía inteiro em 07h e passava de 1 h). Todas as horas de turno aparecem, mesmo sem produção. Vários dias = **média por dia** daquela hora (comparável com a meta por hora) |
| **Produção por turno** (página Turnos) | Ligado de cada turno = trecho dentro da janela daquele turno (ciclo que cruza a troca divide o tempo). Ocupação até agora no turno em andamento. "Fora de turno" = o que sobrou fora das janelas |
| **Excel** | Resumo, por máquina, por hora, por turno, **por dia** e **por dia e turno** com a mesma base; as abas por dia ganharam a coluna "Disponível por máquina (min)" |
| **Tabela de ciclos** | Continua mostrando cada ciclo inteiro, como foi gravado (é o registro bruto) |

### Regras de tempo, qualidade dos dados e histórico

**Qualidade dos dados** (aviso "⚠" no rodapé, detalhes ao passar o mouse):
- Ciclos **SIMULADOS** (modo de teste do ESP32) são ignorados — nunca contam como produção.
- Ciclos **sem data/hora** (RTC sem bateria) não entram em período nenhum — o rodapé conta quantos são.
- Ciclos **sobrepostos** da mesma máquina (ex.: o mesmo período importado duas vezes) são unidos — o tempo conta uma vez só.

**Intervalo de refeição** (aba Turnos → "Intervalo de refeição"): **um por turno** —
o nome é automático (**Almoço** se começa antes das 16:00, **Janta** a partir das 16:00).
Não conta como tempo disponível; se a máquina trabalhou no intervalo, esse trecho entra
como ligado e como disponível (para aquela máquina). Pode ser:

- **Horário fixo** — mesmo horário para todas as máquinas (ex.: janta 18:00–19:00).
- **Flexível** — faixa de horário permitida (ex.: 11:00–14:00) + duração **de/até**
  (padrão **30 a 60 min**, pois a refeição varia). Para cada máquina, em cada turno/dia,
  a refeição é a **maior parada dela dentro da faixa**, com a duração real dela até o
  máximo (o que passar do máximo é parada normal). Parada menor que o **mínimo** não é
  refeição (ex.: outro operador cobriu): nada é descontado e a parada conta como parada
  normal. A linha do tempo marca a refeição detectada de cada máquina (risco laranja).
  O "tempo líquido" do turno usa a duração máxima.

**Calendário e paradas programadas** (aba Turnos):
- **Escala de cada turno**: dias da semana trabalhados por turno (ex.: Turno 1 seg–sex,
  Turno 2 seg–sáb). Com "Usar os dias trabalhados do calendário" ligado, todo dia da
  escala conta como disponível mesmo sem produção (dia inteiro parado aparece como
  parado). Desligado: critério antigo (só turnos com produção + turno atual).
- **Paradas programadas** por tipo — **Feriado, Folga, Reunião, Manutenção** — de dia
  inteiro (o dia sai do disponível de todos os turnos) ou com horário (desconta só o
  trecho, como um intervalo naquele dia).
- **Horas extras** — de dia inteiro (inclui um dia fora da escala, com todos os turnos)
  ou **com horário** (ex.: sábado 08:00–12:00): o intervalo vira tempo disponível a
  mais, mesmo fora de qualquer turno; o trecho que coincide com um turno não conta duas
  vezes. Aparecem como "Horas extras" na página Turnos/Excel, só sem filtro de turno, e
  não criam meta diária.
- Paradas e horas extras valem mesmo com o calendário desligado.

**Histórico de configurações** (aba Turnos): mudar taxa (m/h), meta ou turnos vale a
partir **do dia da mudança**; os dias anteriores continuam com a regra da época
(produção em metros, meta e turnos de cada dia). A data de início de cada vigência pode
ser ajustada ou removida; "Aplicar a configuração atual a todo o histórico" desfaz isso.

Tudo é guardado no navegador e no servidor local (`POST /config` → `extras`, tabela
`config_extra` do `painel.db`). **O aplicativo/servidor precisa ser atualizado** (gerar o
.exe de novo) para gravar essas configurações no banco; a versão antiga ignora o campo
e elas ficam só no navegador.

### Novos gráficos

| Onde | Gráfico |
|---|---|
| Desempenho → Análise de paradas | Nº de paradas (≥ 1 min, sem pausas), tempo parado, duração média, maior parada, tempo médio ligado entre paradas; barras por faixa (até 5 min / 5–30 / > 30). (A lista "Maiores paradas" saiu na 1.3.0; a maior aparece no indicador e no relatório) |
| Desempenho → Comparativo entre turnos | Rendimento de cada turno ao longo do período |

1.3.0:

| Onde | O quê |
|---|---|
| Visão geral → KPI Rendimento | Risco da meta na barra, % da meta cumprida, projeção do turno em andamento ("fim ≈ X%"), comparação com o período anterior (dia: o último dia com turno) em pontos percentuais e minigráfico dos últimos períodos |
| Visão geral → Linha do tempo | Clique numa parada = marcar o motivo; risco colorido = motivo marcado; a faixa do turno avisa quando o horário é de uma configuração antiga |
| Desempenho → Evolução do rendimento | Rendimento de cada máquina por dia (Ano: por semana); no filtro Dia, os últimos 14 dias |
| Desempenho → Disciplina de turno | Por máquina: atraso médio/pior na 1ª partida e saída antecipada média/pior (sem intervalos; verde < 5 min, vermelho > 10 min) |
| ⚙ → Alerta de máquina parada | Por aparelho (localStorage): limite em minutos (padrão 15) e bipe. Só dentro do turno, fora de intervalos fixos/paradas programadas; na refeição flexível, só depois da duração máxima |
| ⚙ → Modo TV | Tela cheia (Esc sai): estado e há quanto tempo de cada máquina, rendimento de hoje e a meta |
| ⚙ → Relatório do período | Indicadores, por máquina, maiores paradas com motivo e paradas por motivo — Imprimir / salvar PDF |

**Motivos de parada**: `extras.motivos = { catalogo: [{ id, nome, cor }], marcas:
{ "maquina|inicioEmSegundos": { m, obs } } }` (chave `motivos` de `config_extra`,
sincronizada como `extras:motivos`). A parada é identificada pela máquina + o
instante em que começou (vem dos ciclos, então é estável). **Endereço**: período,
data e turno ficam em `#p=…&d=AAAA-MM-DD&t=all|N` (abrir o link aplica o filtro).

Base de todos: estrutura `resumoJanelas()` — um resumo por turno/dia e máquina (ligado,
disponível, produção, paradas, almoço detectado), calculado com as
mesmas regras dos cartões.

### Diagnóstico do controlador (⚙ → Diagnóstico do controlador)

> Nomenclatura: na interface o equipamento de coleta (a placa ESP32) é chamado de
> **controlador** — painel, rodapé, mensagens do servidor e textos do firmware (eventos e
> página do próprio controlador). A documentação técnica continua citando "ESP32".

Página com a situação do equipamento de coleta, atualizada sozinha a cada 10 s:

- **Saúde do equipamento** — semáforo (ok / atenção / problema) com o que fazer: comunicação,
  firmware, relógio RTC (com a causa provável quando não é encontrado, pela varredura I2C e
  teste de pull-up), bateria do RTC, hora (diferença para o PC), sinal Wi-Fi, estabilidade da
  rede, autocorreções, último reinício, memória e ciclos guardados.
- **Detalhes** — Relógio (RTC), Rede, Sistema e armazenamento, Máquinas (vistas pelo ESP32) e
  **Registro de eventos** (últimos 30).
- **Ações** — Atualizar, **Redetectar RTC**, **Varrer barramento I2C**, **Reconectar Wi-Fi** e
  **Reiniciar ESP32** (as duas últimas pedem confirmação).
- **Conexão** — origem dos dados (**Wi-Fi** ou **cabo USB**; a troca vale na hora) e botão para
  abrir a página de configuração do Wi-Fi do ESP32. O atalho "⚙ Configurações" do painel ESP32
  no rodapé abre esta página já no painel Conexão.

O servidor local repassa as consultas (`GET /esp/diagnostico`, `POST /esp/acao`). Só funciona com a
leitura pelo Wi-Fi. Com firmware antigo, a página mostra o que houver e indica gravar o 2.0.

### Edição direta (sem abrir o menu ⚙)

Na **Visão geral**, os valores editáveis podem ser alterados clicando
neles mesmos. Ao passar o mouse aparece um lápis ✎ e um destaque:

| Onde clicar | O que acontece |
|---|---|
| **Nome da máquina** (cartão) | Vira um campo de texto ali mesmo — Enter ou clicar fora salva, Esc cancela |
| **Pill da taxa** ("1.980 m/h" / "definir taxa") | Vira um campo numérico ali mesmo (aceita vírgula) — Enter/clicar fora salva, Esc cancela |
| **Selo "Meta por turno"** (cabeçalho de "Rendimento por máquina"), KPI **Rendimento**, legenda da meta no **ranking** e no gráfico **por hora** | Abre o popup da meta diária |
| KPI **Produção estimada** | Abre o popup de configuração das máquinas |

Salvar pela edição direta grava igual ao popup (navegador + banco do
servidor local, `POST /config`) e redesenha o painel inteiro (nomes nos
gráficos, tabela, seletores). O campo pisca em verde ao salvar. Máquinas,
meta e turnos **não estão mais no menu ⚙**: são editados direto na página
(os popups de máquinas e meta abrem ao clicar nos valores).

Para tornar outro elemento clicável: basta o atributo
`data-abrir-popup="<nome>"` (meta, maquinas, turnos, conexao,
identidade). Há um único tratador por delegação no `document`, então
funciona também em elementos criados depois (gráficos). Com
`role="button"`, também abre por Enter/Espaço.

### Turnos cadastrados (página Turnos)

Tabela no topo da página **Turnos** com todos os turnos do setor, editável
direto nas células (mesmo padrão da edição direta):

- **Nome, início e fim**: clique e edite; salva ao sair do campo ou com
  Enter, Esc desfaz. O campo pisca em verde ao salvar.
- Antes de gravar, a lista inteira é validada com as mesmas regras do
  popup (horário completo, início ≠ fim, sem sobreposição). Se não
  passar, aparece o motivo no rodapé do card e o campo volta ao valor
  anterior.
- **Adicionar turno**: abre uma linha de rascunho (início sugerido = fim
  do último turno), gravada só ao clicar em **Adicionar**.
- **Horário por dia da semana** (ícone de calendário em Ações): abre uma
  linha com os 7 dias, já preenchidos com o horário padrão do turno. Mude
  só os dias diferentes (ex.: sexta 07:00 → 16:00 em vez de 17:00); o dia
  fica destacado e aparece um selo na coluna Observação. **Padrão** volta o
  dia ao horário normal. A validação (sem sobreposição) é feita dia a dia.
  Os horários por dia valem para tudo: classificação dos ciclos, tempo
  disponível, parado, rendimento e meta. Ficam no banco (coluna `dias` da
  tabela `turnos`) e entram no **Histórico de configurações** como
  qualquer mudança de turno (valem a partir do dia em que foram feitos).
- **Remover**: lixeira com confirmação na própria linha ("Remover? Sim /
  Não"); é preciso manter pelo menos um turno. Se o turno removido
  estava selecionado no filtro, o filtro volta para "Todos".
- Colunas calculadas: **duração** e **"cruza a meia-noite"**; no rodapé,
  quantas horas do dia ficam **sem turno** (ciclos nesse horário aparecem
  como "Fora de turno").
- Gravar reclassifica todo o histórico na hora e persiste igual ao popup
  (`localStorage` + `POST /config`). A tabela não é redesenhada enquanto um campo dela está em
  foco (a atualização automática de dados não atrapalha a digitação).

### Identidade visual (⚙ Configurações → Aparência → Identidade visual)

Página para editar as cores da marca, com aplicação ao vivo no painel
inteiro:

- **4 cores**: principal (botões, aba ativa, seleção, foco, destaques),
  secundária (detalhes/gradientes), e início/fim do gradiente do **menu
  superior**. Cada uma com seletor de cor e campo hexadecimal.
- **Nome da empresa** (opcional, `localStorage` `painel_empresa`): usado no
  título da janela, no rodapé da página e no texto alternativo da logo. O
  painel não tem nome de empresa fixo no código.
- **Modelos prontos**: Laranja (padrão), Grafite + laranja, Azul
  industrial, Verde, Vermelho e Roxo.
- **Verificação de contraste** (WCAG): texto branco nos botões, texto do
  menu e destaques sobre fundo claro — "Ótimo" (≥ 4,5:1), "Bom" (≥ 3:1) ou
  "Pouco legível". Se o menu ficar claro demais para texto branco, o texto
  do menu passa a escuro sozinho.
- **Pré-visualização** dos principais componentes.
- **Salvar paleta** grava no navegador (`localStorage`
  `painel_identidade`, vale para todos os setores); **Descartar** ou sair
  da página sem salvar volta para a paleta salva; **Restaurar padrão**
  volta ao laranja.
- O tema escuro e os tons derivados (hover, brilhos) são calculados a
  partir das 4 cores (`PainelIdentidade.gerarCss()`, no `<head>` do
  `index.html`, aplicado antes do primeiro desenho para não "piscar").
- As **cores das máquinas** (`--m1`…`--m6`) não são editáveis: são
  validadas para daltonismo.
- Ainda não é gravada no banco do servidor local (só no navegador do
  app, que é persistente).

A aba aberta e o tema ficam gravados no navegador (`painel_view_atual`,
`painel_tema`). Os filtros de período/turno e as ações valem para todas as
abas. Como os gráficos medem a largura do container, eles são redesenhados
ao trocar de aba (`mostrarView()` → `renderGraficos()`).

## Duas formas de abrir

| Forma | O que funciona | O que não funciona |
|---|---|---|
| **Arquivo local** (duplo clique) | Tudo, inclusive a atualização automática (via `controle_leitura_server.py` em `localhost`) | — |
| **Link publicado (claude.ai)** | Gráficos, filtros, exportação Excel (usa a API de download da plataforma) | Atualização automática — a página hospedada roda numa sandbox sem acesso à rede local (o chip mostra "indisponível") |

## Estrutura da página

### Barra superior (menu principal)
Fixa no topo: logo, nome do painel + setor atual, as abas de navegação, o
**seletor de setor** (ver "Múltiplos setores" abaixo), relógio, o menu
**⚙ Configurações** e o botão de tema.

O controle de **Atualização automática** fica no canto esquerdo da barra
de status (rodapé) — chip curto "Ao vivo" / "Pausado" / "Offline" (texto
completo no tooltip) + botão Pausar/Ativar (liga/desliga o
`monitor_serial.py` batendo no `controle_leitura_server.py`, com status
ativo/pausada/indisponível — por trás das cortinas isso ainda é chamado de
"leitura serial" no código e nos scripts, só o texto exibido ao usuário foi
simplificado).

### Barra de sincronização com o ESP32

Fica logo abaixo dos filtros, sempre que o painel está aberto pelo
app (ou com o servidor local rodando). Atualiza a cada 3 s via
`GET /sincronizacao`:

| Situação | O que aparece |
|---|---|
| **Rede conectada** (verde) | Por qual rede (empresa ou `HORIMETRO_SANTEX`), o IP, a hora da última sincronização e o último lote baixado. O acesso à página do ESP32 fica em **⚙ Configurações → Diagnóstico do controlador → painel **Conexão****. |
| **Baixando ciclos…** (roxo, piscando) | Extraindo os ciclos guardados no ESP32 (quantos faltam). |
| **ESP32 não encontrado** (vermelho) | Em qual rede conectar o notebook e há quanto tempo foi a última sincronização ("há 3 dias"). |
| **Sincronização pausada** | Leitura pausada pelo botão **Pausar** da barra superior. |

Avisos abaixo do texto: ciclos **sobrescritos** no ESP32 antes de serem
extraídos (laranja, mostrado por 7 dias) e relógio do ESP32 acertado pelo
PC (cinza, por 24 h).

**Origem dos dados** (em **⚙ Configurações → Diagnóstico do controlador → painel **Conexão****): escolhe entre **Wi-Fi (ESP32)** (padrão) e **Cabo
USB**. A escolha é gravada em `conexao.json` (`POST /conexao`) e a leitura
reinicia na origem nova. No Wi-Fi, a sincronização **começa sozinha ao
abrir o app**. Não é preciso clicar em nada, só conectar o notebook numa
das redes. Os dados novos aparecem nos gráficos em até ~5 s.

### Menu ⚙ Configurações (barra superior)

Menu no canto direito da barra superior. Máquinas, meta e turnos saíram do
menu — são editados direto na página (Visão geral e aba Turnos).

| Seção | Item | O que configura |
|---|---|---|
| Aparência | **Tema escuro** | Interruptor claro/escuro |
| Aparência | **Identidade visual** | Paleta de cores do painel |
| Conexão | **Diagnóstico do controlador** | Saúde do equipamento, RTC, rede, eventos e ações (ver acima) + painel **Conexão**: origem dos dados (Wi-Fi/USB) e link para a página de Wi-Fi do ESP32 (o painel Conexão só aparece com o app/servidor local rodando). Substitui o antigo popup "Conexão e ESP32" |
| Dados | **Importar dados** | Carregar arquivo CSV |
| Dados | **Backup dos dados** | Baixa uma cópia bruta de todos os ciclos (CSV) |

Para incluir uma configuração nova: um `<button class="menu-item"
data-abrir="<nome>">` no `#config-menu`, o popup `.modal-overlay` e, no
script, `ABRIR_POPUP.<nome> = abrir...` + `ligarPopup("<prefixo>", fechar...)`.

### Toolbar (período + área de ações)
- **Filtro de período**: Dia / Semana / Mês / Ano, com navegação `‹ ›`
  entre períodos. **Só funciona com dados que têm data/hora real** — sem
  isso (formato atual do firmware, baseado em `millis()`), os botões ficam
  desabilitados e uma nota ("Filtro por período disponível em breve")
  explica isso sem entrar em detalhe técnico. Volta sempre para "Dia" a
  cada novo arquivo carregado manualmente (não fica preso no último período
  navegado).
- **Área de ações** (bloco destacado rotulado "AÇÕES"): os dois botões de
  uso mais frequente ficam sempre visíveis —
  - **Importar dados** (upload manual de arquivo CSV);
  - **Exportar Excel** (verde, ícone de planilha — cor e ícone sugestivos
    de propósito).
- **Importar dados** e **Backup dos dados** ficam no menu
  **⚙ Configurações**, seção "Dados" (ver abaixo).

### Rendimento por máquina
Um bloco por máquina do setor atual (cor fixa de identidade, validada para
daltonismo, atribuída pela posição da máquina na lista do setor — nunca
pelo número bruto do id), com: nome configurável, horímetro (tempo ligado,
mostrado em gradiente de cor), tempo parado, rendimento (%), produção
estimada (se a taxa em m/h estiver configurada), e uma barra de progresso
contra a **meta de rendimento em %** (selo "Meta por turno" no cabeçalho da
seção — clique para editar). Nome e produção por
hora (m/h) de cada máquina: **⚙ Configurações → Máquinas**. A grade se ajusta sozinha à quantidade de máquinas do
setor (não é mais fixa em 4 colunas).

### Ranking de rendimento
Máquinas da maior para a menor rendimento, com a barra, o risco da meta e a
diferença em pontos percentuais. (O "Comparativo de rendimento" em barras saiu
na 1.3.0: repetia os mesmos números.)

### Linha do tempo por máquina
Uma pista por máquina na mesma escala de tempo — ligado (cor da máquina)
vs. parado (cinza) — pra comparar visualmente onde cada uma ficou parada.

### Tempo ligado por hora
Barras agrupadas (uma coluna por máquina, por hora), com uma linha
tracejada de meta (a meta % de cada hora de turno: 85% = 51 min por hora). Sem data real, os
rótulos de hora são uma **aproximação**: ancoram o bloco mais recente na
hora atual do computador e contam pra trás — não é a hora real gravada
nesse caso.

### Registro detalhado (tabela)
Aba **Registros** (sempre aberta; não é mais recolhível).
Ao abrir, mostra: seletor de máquina (Todas + uma opção por máquina do
setor atual, com o **nome configurado** de cada uma — não mais "M1"/"M2"
fixos), busca por texto, filtro "somente alertas", e a tabela com
Máquina/Ciclo/Início/Fim/Duração/Status. Esses filtros afetam **só esta
tabela** — os gráficos acima sempre mostram a visão completa/comparativa.

## Múltiplos setores

O painel foi estruturado para atender vários setores da empresa, cada um
com seu próprio conjunto de máquinas — hoje só o setor **Enfestadeiras**
(4 máquinas) existe de verdade; os demais setores da empresa ainda não
foram cadastrados.

### Como funciona

No topo da página, à esquerda da logo, fica o seletor **Setor**. Trocar de
setor:

- troca o conjunto de máquinas mostrado em todos os cards/gráficos/tabela;
- troca o nome exibido no título do painel e na exportação Excel;
- **limpa os dados carregados na tela** (um CSV de um setor não faz sentido
  em outro — o usuário precisa carregar/gerar dados de novo para o setor
  recém-selecionado);
- troca qual configuração de máquina (nome, taxa) e qual meta diária são
  lidas/gravadas — cada setor tem as suas, isoladas, no `localStorage` do
  navegador (chaves com sufixo `__<id-do-setor>`, ex.:
  `painel_config_maquinas__enfestadeiras`) **e**, quando há um servidor
  local rodando (`controle_leitura_server.py` ou o aplicativo desktop), no
  banco de dados persistente (`dados/painel.db` — ver
  `docs/ferramentas.md`). Configuração de um setor nunca vaza pra outro.

### Como adicionar um novo setor

No `<script>` do `index.html`, logo no início, existe o
registro central:

```js
const SETORES = [
  { id: "enfestadeiras", nome: "Enfestadeiras", machineIds: [1, 2, 3, 4] }
];
```

Basta acrescentar um novo item — `id` único (vira parte da chave de
`localStorage`, então não deve mudar depois de criado), `nome` (exibido na
UI) e `machineIds` (lista de ids de máquina daquele setor; não precisa ser
`[1,2,3,4]`, nem ter a mesma quantidade de outro setor). Todo o resto do
painel (seletor de setor, cards, gráficos, tabela, filtro, exportação
Excel) lê esse registro e se adapta sozinho — nenhuma outra parte do código
precisa saber quantos setores existem ou quantas máquinas cada um tem.

Limites atuais dessa estrutura, pra quem for estender:

- **Cores de identidade**: até **6 máquinas por setor** têm cor própria
  validada contra daltonismo (`--m1` a `--m6` no CSS, atribuída pela
  *posição* da máquina na lista do setor). Um setor com mais de 6 máquinas
  precisaria de cores novas, validadas com
  `scripts/validate_palette.js` da skill `dataviz` antes de entrar.
- **Firmware/ferramentas**: cada setor provavelmente terá seu próprio
  ESP32 e seus próprios scripts de leitura (portas COM diferentes, CSVs
  diferentes) — isso ainda não foi construído para nenhum setor além de
  Enfestadeiras. O registro `SETORES` é só do lado do painel; a leitura de
  dados reais de um setor novo exige repetir o processo de
  `firmware/`/`ferramentas/` descrito em `docs/firmware.md` e
  `docs/ferramentas.md`.

## Configurar máquinas (popup — ⚙ Configurações → Máquinas)

Por máquina: **nome** (usado em todos os gráficos, tabela e legendas) e
**produção por minuto** (na unidade que fizer sentido — ex.:
metros/minuto numa enfestadeira de fita). Com taxa > 0, o painel calcula
produção estimada = `(tempo ligado em minutos) × taxa` e passa a mostrar
isso nos blocos e nos tooltips da linha do tempo e do gráfico por hora.

Configuração salva no `localStorage` do navegador (leitura instantânea,
sem esperar rede, e único lugar onde fica salva na versão hospedada) e, em
paralelo, enviada para `POST /config` no servidor local — que grava no
banco de dados persistente (`dados/painel.db`), sobrevivendo a reinstalar
ou atualizar o aplicativo desktop, trocar de navegador, ou limpar os dados
do navegador. Ao carregar a página (ou trocar de setor), o painel busca
`GET /config` do servidor e usa esse valor por cima do que estava no
`localStorage`, se os dois divergirem — o banco de dados é a fonte mais
confiável quando ela está disponível, mas nunca obrigatória (sem servidor
local, como na página hospedada, o painel segue funcionando só com
`localStorage`).

## Estado ao vivo nos cartões

Cada cartão de máquina mostra "Ligada agora · há X min" (verde) ou "Parada
agora · há X min", consultando `GET /ao-vivo` do servidor local a cada 5 s.
Mostra "Sem sinal da máquina" se o firmware não confirmar o estado há mais
de 30 s ("Sem contato com o ESP32" no Wi-Fi), e "Leitura pausada" com a
leitura desligada. Sem servidor local, o indicador some.

**Os valores do cartão incluem o ciclo em andamento.** Com a máquina ligada,
o tempo desde que ela ligou já entra em tempo ligado, rendimento, produção e
meta, recortado ao período e ao turno selecionados. Enquanto alguma máquina
está ligada, os cartões se atualizam **a cada segundo**. Quando a máquina
desliga, esse tempo é substituído pelo ciclo gravado, sem contar duas
vezes (`cicloEmAndamento()` em `index.html`). Os gráficos e a tabela continuam
mostrando só ciclos já fechados.

## Turnos (filtro + cadastro)

Os turnos **não são gravados nos ciclos**: cada ciclo continua salvo só
com seus horários, e o turno é calculado na hora de exibir, a partir dos
turnos cadastrados. Mudar o cadastro reclassifica todo o histórico na hora.

- **Select "Turno"** (toolbar): "Todos os turnos" ou um turno específico.
  Filtra a tela inteira: blocos, gráficos, tabela e exportação. Fica
  desabilitado quando os dados não têm horário real.
- **⚙ Configurações → Turnos**: abre o modal com nome, início e
  fim (`HH:MM`) de cada turno. Aceita quantos turnos forem necessários.
  Recusa início igual ao fim e turnos sobrepostos.
- **Regras de classificação**:
  - o ciclo entra no turno em que **começou**;
  - um turno que cruza a meia-noite (ex.: 22:00 → 06:00) conta o trecho
    após 00:00 no **dia de produção** em que começou. Os filtros Dia/
    Semana/Mês/Ano usam esse dia de produção;
  - ciclo fora de todos os turnos aparece como "Fora de turno".
- **Painel "Produção por turno"**: gráfico de barras (um grupo por turno,
  uma barra por máquina) e tabela turno × máquina com ciclos, tempo
  ligado, ocupação e produção. Clicar numa barra filtra pelo turno.
  Ocupação = tempo ligado ÷ (duração do turno × dias com produção nele).
- Com um turno selecionado, o rendimento dos blocos usa como tempo
  disponível só as horas daquele turno nos dias com produção.
- **Persistência**: `localStorage` (`painel_config_turnos__<setor>`) e
  tabela `turnos` do banco (`dados/painel.db`), via `GET/POST /config`
  (campo `turnos`). Padrão inicial: 06–14, 14–22 e 22–06.

## Exportação Excel

Gera um `.xlsx` **em uma única planilha** (sem abas), com as seções
empilhadas, cada uma com um título. O cabeçalho já identifica o setor
atual (`Painel de Produção — <nome do setor>`):

1. **Resumo executivo** — indicadores gerais do período (todas as
   máquinas do setor) + ranking de rendimento.
2. **Por máquina** — modelo transposto: cada indicador numa linha, cada
   máquina numa coluna, com coluna **Total/Geral** ao final (soma, média
   ou extremo, dependendo do indicador).
3. **Tempo ligado por hora** — cruzamento hora × máquina, em minutos.
4. **Tempo ligado por dia** — cruzamento data × máquina (só aparece com
   data real).
5. **Produção por turno** e **Tempo ligado por dia de produção e turno** —
   com os turnos cadastrados (só com data real). A coluna "Turno" dos
   registros também usa o cadastro.
6. **Alertas** — lista de ciclos com problema (curto/recuperado), dentro
   do período e máquina selecionados no "Detalhamento".
7. **Registros detalhados** — réplica exata do que a tabela mostra na
   tela (mesmos filtros: período + máquina + busca + alertas).

Usa a biblioteca [SheetJS](https://sheetjs.com/) (`xlsx`), carregada via
CDN (`cdnjs.cloudflare.com`) **sob demanda** (`carregarXlsx()`): em segundo
plano ~4 s depois que o painel abre, ou ao clicar em Exportar (o botão
mostra "Preparando…"). Nunca bloqueia a abertura; sem internet, avisa na
hora de exportar. Botão verde com ícone de planilha, no bloco
"Ações" da toolbar.

## Backup dos dados

**⚙ Configurações → Backup dos dados**: baixa uma cópia bruta do
banco de dados, sem nenhum processamento.

1. Tenta buscar a versão mais atual direto de
   `http://localhost/dados` (reconstruída na hora a partir do banco de
   dados persistente, `dados/painel.db`).
2. Se a fonte local não responder (ex.: página hospedada, sem rede
   local), cai para o último arquivo carregado na própria página.

Nome do arquivo: `backup_producao_AAAAMMDD_HHMM.csv`.

## Download de arquivos: local vs. hospedado

Tanto a exportação Excel quanto o backup usam a mesma lógica de salvamento
(`salvarArquivoParaUsuario`):

- **Página hospedada (claude.ai)**: usa a API de download da plataforma
  (`window.claude.use("downloads")`), que pede confirmação ao usuário.
- **Arquivo local**: cai no download direto do navegador (cria um link
  temporário e clica nele sozinho).

## Formato de CSV aceito

O parser (`parseCsv`) é tolerante:

- Aceita tanto o formato atual (`maquina,ciclo,inicio_ms,fim_ms,duracao_s,obs`)
  quanto o futuro com RTC (`maquina,ciclo,data,hora_inicio,hora_fim,duracao_min,obs`)
  — detecta automaticamente pela presença das colunas `data`/`hora_inicio`.
- Coluna opcional `registrado_em` (`AAAA-MM-DDTHH:MM:SS`), enviada pelo
  servidor local em `/dados`: data/hora do PC quando o ciclo chegou pela
  Serial (= fim do ciclo). Enquanto o ESP32 não tem RTC, é ela que dá
  horário real aos ciclos (início = fim − duração), habilitando os filtros
  de período e de turno.
- A coluna `maquina` é opcional — CSVs antigos sem ela são tratados como a
  primeira máquina do setor atual.
- A coluna `ciclo` também é opcional — se ausente, é numerada
  automaticamente por máquina.
- Linhas que começam com `#` (log do `monitor_serial.py`) são ignoradas.
- IDs de máquina fora da lista do setor atual (`machineIds`) também caem
  na primeira máquina do setor — protege contra CSV de um setor sendo
  carregado sem querer com outro setor selecionado.

## Tema claro/escuro

Tema claro por padrão; o interruptor **⚙ → Aparência → Tema escuro** alterna para o escuro e grava a escolha (`painel_tema`). A barra superior é laranja nos dois temas (`.scope-brand`).
Paleta de cores das
máquinas (`--m1` a `--m6`) e dos estados (normal/alerta/crítico) validada
para daltonismo (rode `scripts/validate_palette.js` da skill `dataviz`
para reproduzir a checagem). Cor de destaque da interface (botões, chips,
título) é laranja (`--accent`, com âmbar em `--accent-2`), separado das cores de
identidade das máquinas — nunca reaproveitado como cor de série num
gráfico.
