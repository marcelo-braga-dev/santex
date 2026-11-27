# Histórico de versões

## 2.0.0-alfa.2 — fase 2 em andamento: atualização incremental e cadastro de dispositivos (app 2.0.0-alfa.2 · firmware 3.2 e programa remoto 1.2.0, sem mudança)

Não liberada (produção na 1.7.5). A alfa.1 não chegou a ser instalada: o
próximo deploy de teste já leva esta.

- **Painel baixa só os ciclos novos**: o `/dados` informa o maior id
  entregue (cabeçalho `X-Ultimo-Id`) e aceita `apos=<id>` (só os ciclos
  depois dele, pelo índice `setor+id`). Depois da primeira carga, o painel
  pede só os novos e acrescenta; a cada 10 min (ou ao voltar à aba) faz uma
  carga completa, que cobre o raro ciclo antigo que ganha a hora real
  depois. Vale para todos os setores; servidor antigo (sem o cabeçalho) =
  cargas completas, como antes.
- Teste de volume (1,8 milhão de ciclos): só os novos em 0,001 s (1,9 KB),
  contra ~1 s e 2,9 MB da janela de 16 dias a cada ciclo novo.
- **Cadastro de dispositivos** (tabelas `dispositivos` e
  `dispositivo_atribuicoes`, só aditivas; regras em
  `ferramentas/dispositivos.py`): aparelho novo aparece no primeiro contato;
  adotar (setor + máquina, uma máquina = um aparelho ativo), trocar o
  queimado pelo reserva, liberar, bloquear/desbloquear, apelido; histórico de
  atribuições. Rotas `GET /dispositivos` (com "sem sinal" calculado) e
  `POST /dispositivos` (só no computador da fábrica; adotar numa máquina
  nova a cadastra no setor pela configuração, que sincroniza com a VPS).
- O **ESP32 multi das Enfestadeiras** entra sozinho no cadastro (ativo, no
  setor dele) a cada contato — na leitura pelo Wi-Fi e no envio direto à
  VPS —, reconhecido pela série (a parte do MAC já mudou entre versões).
  Protegido para nunca parar a leitura.
- Setor com aparelho (atual ou no histórico) só pode ser desativado.
- **`POST /api/v2/coletor`** (só no servidor local; a VPS responde 404):
  o recebimento por push dos coletores de 1 por máquina. Assinatura
  HMAC-SHA256 com chave **por aparelho** (derivada da `COLETOR_CHAVE_MESTRA`),
  anti-replay de ±120 s (a recusa por relógio devolve a hora certa),
  bloqueado = recusado, não adotado = nada gravado (`ack_ate: 0`, os ciclos
  ficam no ESP32), adotado = grava com o setor e a máquina do cadastro e
  confirma (`ack_ate`) só depois de gravar. Reenvio não duplica. Código em
  `ferramentas/receptor_push.py`.
- **Simulador de coletores** (`ferramentas/simulador_coletores.py`): N
  ESP32 virtuais com o protocolo real, banco temporário, com queda de metade
  da rede, reinícios e relógio errado. 50 aparelhos por 3 min: nenhum ciclo
  perdido nem duplicado, resposta mediana de 5,6 ms (p95 34 ms); 200
  aparelhos também sem perda. Versão curta entra nos testes.
- **Alertas de comunicação** em `GET /dispositivos`: repetidor fora (todos
  os aparelhos de um AP sem sinal juntos, um alerta só), sem sinal, sinal
  fraco, memória do coletor enchendo, relógio inválido, reinícios demais e
  aparelho novo esperando adoção. A tela é da fase 4.
- `gerar_segredos.py` cria a `COLETOR_CHAVE_MESTRA` quando ela falta no
  `.env` e a põe só no `app/segredos_app.json` (nunca no firmware nem na
  VPS).

## 2.0.0-alfa.1 — fase 1 da 2.0: vários setores (app 2.0.0-alfa.1 · firmware 3.2 e programa remoto 1.2.0, sem mudança)

Plano em `docs/plano-2.0.md`, andamento em `docs/progresso-2.0.md`. **Não
liberada**: produção continua na 1.7.5. É a versão do primeiro deploy de
teste (VPS primeiro, só com o OK do usuário; passo a passo em
`vps/CLAUDE_VPS.md`).

- **Convivência com a 1.7.5 testada nos dois sentidos** (código da tag
  `v1.7.5` em processo separado): notebook 2.0 × VPS 1.7.5, VPS 2.0 ×
  notebook 1.7.5 e a volta para a 1.7.5 abrindo um banco que já passou pela
  2.0.
- O `ping` da VPS responde `"versao"` só com números (`"2.0.0"`) e a versão
  inteira em `"versaoCompleta"`: o notebook 1.7.x lê a versão com `int()` e,
  com o `-alfa.1`, acharia que a VPS é antiga. O notebook 2.0 também passa a
  aceitar sufixo. O gerador do `.exe` aceita sufixo no nome
  (`PainelProducaoSantex-2.0.0-alfa.1.exe`).
- Ao abrir, o banco confere se o `resumo_dia` conta os mesmos ciclos da
  tabela e recalcula se não (caso de alguém voltar para a 1.7.x, que grava
  ciclos sem manter o resumo, e subir a 2.0 de novo).

- **Cadastro de setores** no banco (tabela `setores`): criar, renomear,
  ordenar, desativar e apagar (só setor sem dados). As Enfestadeiras entram
  sozinhas no cadastro, com todo o histórico. Rotas `GET/POST /setores`;
  `/dados`, `/ao-vivo` e `/config` por setor.
- **Sincronização com a VPS por setor**: configuração (chaves `setor/item`
  para os setores novos; as Enfestadeiras no formato da 1.x), cadastro de
  setores, histórico e estado ao vivo de todos os setores.
- **Cadastro de setores convergente**: quando um lado mantém um setor com
  dados que faltava na lista recebida, a lista dele volta para o outro lado
  (antes os dois ficavam diferentes sem aviso).
- **Painel: seletor de setor** no cabeçalho (só os ativos; lembra a escolha
  no aparelho; `?setor=` no endereço abre direto, até um setor desativado).
  Trocar de setor recarrega máquinas, configuração, dados e estado ao vivo, e
  descarta respostas atrasadas do setor anterior. `/dados` passou a pedir o
  setor.
- **Configurações → Produção → Setores**: criar (com quantas máquinas),
  renomear, mudar a ordem, desativar/reativar, apagar (só sem dados) e
  “+ Máquina”. Somente leitura sem permissão de edição. Código novo em
  `painel/js/setores.js`.
- Servidor: só `/dados`, `/ao-vivo` e `/config` consultam o cadastro de
  setores; `GET /setores` informa máquinas e se há dados por setor.
- **Resumo por dia** (tabela `resumo_dia`, só aditiva): ciclos e tempo
  ligado por setor, máquina e dia, mantido na mesma transação de cada ciclo
  gravado (inclusive quando um ciclo sem hora ganha a hora real) e
  recalculável (`recalcular_resumo`). Calculado sozinho na primeira abertura
  de um banco da 1.x. Índice novo `ciclos(setor, gravado_em)`.
- **Consultas por período**: `GET /api/v2/ciclos?setor=&de=&ate=&maquinas=`
  (CSV no formato do `/dados`, ou `formato=json`; até 400 dias) e
  `GET /api/v2/resumo?setor=&de=&ate=&agrupar=dia|maquina|dia_maquina`
  (até ~10 anos). `/dados` aceita `desde=AAAA-MM-DD` (ETag própria).
- **Painel, setores novos**: carrega só uma janela de dias (14, mais 2 de
  folga), que cresce sozinha quando um período mais antigo é pedido (barra
  de período, séries do Desempenho, histórico de paradas, relatórios — que
  esperam os dados antes de gerar —, períodos sem produção). As
  Enfestadeiras continuam com o histórico inteiro, como na 1.x.
- **Versão dos ciclos (ETag do `/dados`) sem `COUNT(*)`**: de 1,7 s para
  0,01 s com 1,8 milhão de ciclos.
- `ferramentas/teste_volume.py`: 1 ano sintético de 50 máquinas num banco
  temporário, com os tempos de carga, gravação e consultas.
- Geradores: o `.exe` da fábrica e o pacote da VPS levam `setores.py` e
  `painel/js/` (sem isso, a 2.0 não abriria). Teste novo confere os
  geradores, e outro roda o notebook 2.0 contra a VPS 1.7.5 da tag.

## 1.7.5 — Configurações em abas e histórico de notificações enxuto (app 1.7.5 · firmware 3.2 e programa remoto 1.2.0, sem mudança)

- **Configurações em abas**: Produção (máquinas e meta, turnos/calendário/
  motivos, parada longa) · Alertas · Acesso remoto (senhas e aplicativo para
  Windows) · Aparência · Dados · Sistema (controlador e sobre). A última aba
  aberta fica lembrada neste aparelho; aba sem nada para mostrar (ex.:
  Sistema na VPS) some da barra; os atalhos (ex.: "Acesso remoto" do menu)
  abrem direto a aba certa. No celular a barra de abas rola na horizontal.
- **Configurar máquina pelo cartão** (Visão geral): engrenagem ao lado do
  histórico de paradas abre um popup com tudo da máquina — nome, produção
  (m/h), **cor** (padrão, 10 sugestões ou qualquer outra), situação Com/Sem
  produção e o histórico de paradas. A cor vale nos cartões, gráficos,
  linha do tempo e relatórios, e vai junto com a identidade visual para
  todos os aparelhos e a VPS (`extras.visual.cores`, sem mudança no banco).
- **Cartão da máquina só de leitura**: nada se edita mais direto no cartão
  — nome e produção por hora mudam pela engrenagem
  "Configurar máquina". A produção por hora (m/h) saiu do cartão. Cada
  campo mostra só o valor ao passar o mouse (sem cálculo nem explicação):
  horímetro (e o tempo sem produção), parado e rendimento ("X de Y"),
  produção (a produção por hora) e a meta. O checkbox
  "Produção" continua alternando Com/Sem produção com um clique.
- **Notificações no menu Configurações** (o sino saiu do cabeçalho): item
  "Notificações" no menu, com a contagem de novas no próprio item e no botão
  Configurações; a lista abre logo abaixo do botão, como antes.
- **Crédito "Desenvolvido por Marcelo Braga" um pouco mais visível** no
  rodapé da página: ícone `</>` discreto e o nome em negrito na cor da
  identidade.
- **Cabeçalho de Relatórios compacto**: uma linha — "Relatórios · Período e
  turno são escolhidos ao gerar" + Excel completo / PDF completo. Saíram o
  parágrafo de instruções, os chips de período/turno/setor (o período é
  escolhido ao gerar) e a faixa de aviso — a nota sobre refeição e paradas
  programadas ficou no ⓘ (passe o mouse ou toque).

- **Histórico de notificações enxuto**: avisos do painel só se
  duraram 2 min ou mais (antes, 15 s), só com a duração, e sem "paradas sem
  motivo"; do controlador, só problemas sérios (reinício por erro, ciclos
  perdidos/sobrescritos, RTC parou, memória baixa, firmware atualizado) — sem
  quedas/reconexões de Wi-Fi nem falhas passageiras de envio à nuvem; de
  configuração, uma linha por alteração por dia, sem "Histórico de
  configurações". O registro antigo deste aparelho passa pelo mesmo filtro.

## 1.7.4 — atualizar o firmware do controlador pelo painel (app 1.7.4 · firmware 3.2 e programa remoto 1.2.0, sem mudança)

- **Diagnóstico do controlador → Atualizar firmware**: escolha o
  `controle_producao_horimetro.ino.bin` e clique em **Enviar e atualizar**. O
  aplicativo repassa o arquivo ao ESP32 (rota `/atualizar` do firmware 3.2)
  com a **senha do equipamento embutida no app** — nada para digitar —,
  espera o controlador reiniciar e mostra a versão antes → depois.
- A senha vem do `.env` (`AP_SENHA`) para o `app/segredos_app.json`
  (`ap_senha`), como a chave da API; `conexao.json` pode sobrepor com
  `senha_equipamento`. Depois de atualizar o app: `python
  ferramentas/gerar_segredos.py` e gerar o `.exe` de novo.
- Só no painel do próprio computador da fábrica (mesmas proteções das senhas
  guardadas: `localhost`, sem `Origin` de fora, sem CORS); escondido na VPS.
- Recusa antes de enviar: arquivo que não é firmware do ESP32 (`.merged.bin`,
  bootloader, partições) ou maior que a partição; uma atualização por vez.
- **Rodapé sem a pill "✏ Edição remota"**: quem entra pela internet com a
  senha de edição não vê mais esse aviso (desnecessário); a pill de
  "somente leitura" continua para quem só visualiza.
- **Avisos do rodapé curtos e diretos** (não quebram mais no celular): só
  o título, sem a frase de explicação — "Enfestadeira 1 parada 12 min",
  "2 máquinas paradas", "3 paradas sem motivo", "Leitura pausada", "Sem dados
  do controlador", "Sem sinal das máquinas". A explicação continua no tooltip
  e no sino de notificações; o texto longo é cortado com "…" se não couber.
- 1 teste novo (45), com um ESP32 simulado.

## 1.7.3 — RTC DS1302 como alternativa ao DS3231 (app 1.7.3 · firmware 3.2 · programa remoto 1.2.0, sem mudança)

- **Firmware 3.2 aceita o RTC DS1302** (o DS3231 instalado parou de
  responder no I2C): CLK→GPIO 25, DAT→GPIO 26, RST→GPIO 27, VCC 3,3 V.
  Detecção automática — DS3231 no I2C tem preferência, depois o DS1302 —
  repetida a cada 30 s: trocar de módulo não exige regravar. Protocolo de 3
  fios no próprio firmware (sem biblioteca); presença confirmada gravando e
  relendo a RAM do chip; o bit CH (relógio parado) faz o papel do OSF.
- Página do controlador, `/info` (`rtc_modelo`), comando `S` pela Serial e
  diagnóstico do painel mostram qual RTC está em uso; o aviso de "RTC não
  responde" lista os pinos dos dois modelos.
- O firmware 3.2 ainda não foi gravado no ESP32 — sai com a correção da hora
  na VPS, a atualização pelo Wi-Fi e o DS1302 de uma vez (pela USB).

## 1.7.2 — senhas do acesso remoto guardadas no notebook (app 1.7.2 · firmware 3.2 e programa remoto 1.2.0, sem mudança)

- **Senhas guardadas neste computador** (Configurações → Acesso remoto): o
  computador da fábrica guarda o texto das senhas de visualização e de edição
  definidas nele, com **Mostrar** e **Copiar** — esqueceu, consulta aqui em vez
  de criar outra. A VPS continua só com o hash; o texto nunca é sincronizado.
- Só aparecem no painel do próprio computador da fábrica: recusadas na VPS,
  em aparelhos da rede (mesmo com o PIN) e para sites abertos no navegador
  deste PC (exige `localhost`, sem `Origin` de fora, resposta sem CORS).
- Senha definida antes da 1.7.2 ou trocada pela internet (só o hash chega ao
  notebook) aparece como "não conhecida aqui": digitando a senha em vigor em
  **Guardar**, ela é conferida com o hash e passa a aparecer.
- **`ferramentas/acesso_vps.py`**: consulta o painel da VPS (só GET) com a
  senha guardada, sem imprimi-la — para o Claude Code conferir o que a VPS
  mostra (`python ferramentas/acesso_vps.py /status`).
- **Reenvio da hora só para VPS que sabe completar**: o reenvio único do
  histórico (1.7.1) agora espera o `ping` da VPS responder 1.7.1 ou mais nova
  (confere a cada 10 min). O app 1.7.1 podia gastar o reenvio numa VPS ainda
  antiga, sem corrigir nada — por isso a 1.7.2 reenvia mais uma vez (sem
  duplicar).
- **Versão no nome do `.exe` da fábrica**: `gerar/exe_fabrica.py` gera
  `distribuir\PainelProducaoSantex-1.7.2.exe` (lida do `APP_VERSAO`). A pasta
  de dados continua `%APPDATA%\PainelProducaoSantex\` — nada muda nos dados.
  Atalho de início automático aponta para um arquivo: ao trocar de versão,
  refaça com `ferramentas\instalar_inicio_automatico.ps1 "<novo .exe>"`.
- 1 teste novo (44).

## 1.7.1 — VPS com a hora certa quando o ESP32 envia sem hora (app 1.7.1 · firmware 3.2 · programa remoto 1.2.0, sem mudança)

Diagnóstico que motivou (23/11/2026): o ESP32 reiniciou por panic no dia
anterior e, com o RTC fora (SDA sem pull-up), ficou sem hora; o repetidor não
repassava a internet. Às 08:12:02 a rede voltou e o ESP32 mandou para a VPS
os 55 ciclos da manhã (07:06–08:11) **sem hora**, 1 s antes de o notebook
acertar o relógio (08:12:03). A VPS os guardou como `SEM_HORA` (fora dos dias
e turnos) e depois ignorou a versão com hora que o notebook enviou, por já ter
o ciclo. O notebook estava certo; a VPS ficou sem ~1 h 10 min de produção.

- **O notebook corrige a VPS**: quando chega um ciclo que a VPS (ou o
  notebook) tem gravado `SEM_HORA` e a nova versão tem hora, a hora é
  completada (início, fim, obs e hora de registro). Só nesse caso, e só se
  máquina, ciclo e duração baterem; ciclo com hora nunca é alterado.
- **Reenvio único do histórico**: o app 1.7.1 manda o histórico inteiro para
  a VPS uma vez (sem duplicar) — corrige os ciclos de 23/11 e qualquer outro
  que tenha chegado sem hora enquanto o notebook tinha a hora certa.
- **Firmware 3.2**: o envio direto para a VPS espera o acerto do relógio (PC
  ou internet) antes de mandar ciclos deste boot ainda sem hora — eles vão
  depois, já com a hora real. Ciclos sem hora de um boot anterior (não há mais
  como calcular) seguem como antes, para não travar a fila.
- **Firmware 3.2 — atualização pelo Wi-Fi (OTA)**: página
  `http://<ip do controlador>/atualizar` (link no fim da página do ESP32),
  pela rede própria (192.168.4.1) ou pela rede da empresa/repetidor. Pede a
  senha do equipamento, conferida antes de gravar; aceita só o
  `controle_producao_horimetro.ino.bin` (Arduino IDE → Sketch → Exportar
  binário compilado). Grava na outra partição de aplicativo: ciclos e
  configuração são mantidos e, se o envio cair, o firmware atual continua.
  **A gravação do 3.2 ainda é pela USB**; a partir dele, as próximas vão
  pelo Wi-Fi.
- 2 testes novos (43).

## 1.7.0 — notebook como segunda fonte da VPS e firmware 3.1 (app 1.7.0 · firmware 3.1 · programa remoto 1.2.0, sem mudança)

Diagnóstico que motivou: o ESP32 falha por períodos ao enviar direto para a
VPS ("connection refused") enquanto o notebook, na mesma internet, alcança a
VPS 100% das vezes — o painel remoto ficava "Controlador sem enviar" e com o
estado das máquinas congelado. Agora o notebook cobre essas falhas.

- **Notebook repassa o estado ao vivo**: junto do histórico de ciclos, o app
  da fábrica manda para a VPS o estado das máquinas que ele lê do ESP32 pela
  rede local (ligada/parada, desde quando, e há quantos segundos falou com o
  ESP32). A VPS **só aplica se for mais novo** que o último envio direto do
  ESP32 — o ESP32 continua a fonte principal.
- Quando a VPS responde que o ESP32 está sem enviar direto, o notebook passa
  a mandar **a cada 5 s** (estado e ciclos novos); com o ESP32 em dia, a cada
  15 s como antes.
- **Status com as duas fontes** (`fonte`: `esp`, `notebook` ou nenhuma):
  "Controlador enviando", **"Via computador da fábrica"** (com aviso de que o
  controlador não envia direto desde X) ou "Controlador sem enviar" (nem um
  nem outro). O painel do notebook avisa quando ele está repassando.
- Compatível nos dois sentidos: VPS antiga ignora o campo novo; notebook
  antigo continua como antes. O banco não muda (só o arquivo de status da
  VPS ganha campos). Precisa do app aberto no notebook.
- **Aviso do rodapé com ×**: fecha o aviso; ele só volta se a situação
  mudar (outra máquina parada, outro tipo de aviso).
- **Notificações no sino** (menu superior, ao lado do relógio): bandeja com
  tudo o que foi avisado, por dia, com filtros Painel / Controlador /
  Configuração; o número no sino conta os avisos importantes que chegaram
  desde a última abertura — avisos do painel com
  início e duração (registrados neste aparelho; passageiros de menos de 15 s
  ficam fora), eventos do controlador (quedas de rede, envio para a nuvem,
  reinícios — no computador da fábrica) e alterações/avisos de configuração.
- 2 testes novos (41).
- **Firmware 3.1** (regravar o ESP32 pela USB; ciclos e configuração na flash
  são mantidos): conexão HTTPS com a VPS reaproveitada (keep-alive, sem
  handshake TLS a cada 10 s), erro real do TLS em `nuvem_erro`, espera máxima
  de 1 min entre tentativas (era 5 min) e a reconexão "PC sem contato" não
  derruba mais o Wi-Fi quando o envio para a VPS está em dia. `/info` ganhou
  `nuvem_envios_ok`, `nuvem_falhas` e `nuvem_conexoes_novas`. Detalhes em
  `docs/firmware.md`.


## 1.6.0 — histórico de paradas e parada registrada (app 1.6.0 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; no notebook, `.exe` novo.
Atualize os dois juntos: uma versão anterior trataria a parada registrada
como "Sem produção" comum (mesma conta, mas poderia encerrá-la pela volta
automática).

- **Histórico de paradas por máquina**: ícone de relógio no cabeçalho do
  cartão (Visão geral, logo depois da pill de produção m/h) abre "Paradas — Máquina X", separado por dia, com
  horário, duração e motivo: paradas longas (acima de 30 min dentro do
  turno, fora dos intervalos — motivo e "Registrar" na linha), paradas
  programadas do calendário do setor, paradas registradas e períodos Sem
  produção. As pausas normais entre os ciclos não aparecem. Setas
  ‹ › trocam o dia/semana/mês sem mexer no filtro da tela.
- **Registrar parada (retroativa)**: "+ Registrar parada" (data, das, até,
  motivo do cadastro de motivos, observação) ou "Registrar" numa parada
  longa. O tempo sai do disponível, do parado, da meta e do rendimento da
  máquina — como um intervalo do turno, só dela. Até 60 dias para trás e
  24 h por registro; não pode ser no futuro nem sobrepor outro registro ou
  período Sem produção; avisa se a máquina ficou ligada no horário (esse
  tempo deixaria de contar como produção). Apagar devolve o tempo.
- **Parada longa configurável** (Configurações → card "Parada longa", 10 a
  240 min; padrão 30): vale para todos os aparelhos (guardado nos motivos de
  parada, `longaMin`, sincroniza com a VPS). Usado no histórico de paradas,
  no aviso de paradas longas sem motivo e nas faixas dos relatórios
  (até 5 min · 5 min a X · acima de X).
- Guardado junto dos períodos Sem produção (`extras:semProducao`, item com
  `tipo: "parada"`), então sincroniza com a VPS e entra na auditoria; na
  linha do tempo aparece como "parada registrada".


## 1.5.2 — filtros fixos e aviso no rodapé (app 1.5.2 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; no notebook, `.exe` novo.

- **Barra de filtros fixa e compacta**: fica presa logo abaixo do menu
  superior ao rolar (o período e o turno filtrados estão sempre à vista) e
  ocupa uma linha só no computador, com controles de bom tamanho. Só filtros: setor, Dia/Semana/
  Mês/Ano, data com o dia da semana e "· hoje", turno e "Voltar para hoje".
  Fora do período atual, a data fica na cor da marca; turno escolhido
  também. Saíram os chips "Exibindo" (repetiam a data e o turno).
- **Aviso de destaque no rodapé**: selo de uma linha no centro da barra de
  status (ícone, título e detalhe), aproveitando a largura; o nome da
  máquina vem entre aspas ("Enfestadeira 2" parada · 23 min).
- **Relatórios: janela "Gerar relatório"** — Visualizar, Excel e PDF (e os
  "completos") abrem antes uma janela com o período (Dia/Semana/Mês/Ano,
  atalhos como Hoje, Ontem, Semana passada, Mês passado; setas e calendário)
  e o turno, já com o filtro atual, mais o resumo do que vai sair (período,
  turno e quantos ciclos; avisa se ficaria vazio). Ao confirmar, o filtro
  também passa para a barra de filtros. Os cartões não ficam mais
  desativados.


## 1.5.1 — alerta de máquina parada mais discreto (app 1.5.1 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; no notebook, `.exe` novo.

- **Visão geral**: saiu a faixa vermelha "Máquina parada" do topo, que
  repetia o aviso de destaque da barra de filtros (este continua, um aviso
  por vez). O cartão da máquina em alerta não pulsa mais: fica só com a borda
  vermelha fina e o selo "⚠ Parada 23 min". O aviso de destaque ficou em
  uma linha só ("Enfestadeira 2 parada · 23 min" / "2 máquinas paradas",
  detalhes no tooltip).


## 1.5.0 — máquinas Com produção / Sem produção (app 1.5.0 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel e a sincronização mudaram: na VPS, `git pull` (precisa da 1.5.0 lá
para os períodos irem e voltarem); no notebook, `.exe` novo. Banco: nenhuma
tabela nova — os períodos são uma chave nova (`semProducao`) em `config_extra`,
por setor.

- **Checkbox "Produção" em cada máquina** (cabeçalho do cartão da Visão geral
  e Turnos e calendário → Máquinas sem produção), com **"Sem produção desde"**
  (retroativo, até 14 dias; avisa se a máquina já trabalhou o bastante depois
  do horário e não deixa cair dentro de um período anterior), motivo (sem
  pedido, manutenção, ajuste, falta de operador, outro) e observação.
- Enquanto "Sem produção": o **horímetro continua** (o cartão mostra todo o
  tempo ligado), mas o período **sai do disponível, do parado, do
  rendimento, da meta, da produção, das paradas, da disciplina de turno e dos
  alertas** (como um intervalo, só daquela máquina). Máquina sem produção o
  período todo fica fora das médias. Cartão tracejado com a legenda "Volta à
  produção após 30 min rodando · x/30", faixa listrada na linha do tempo,
  quadrado listrado em "Ligadas agora" e estado próprio no Modo TV.
- **Volta automática**: quando a máquina trabalha **30 min seguidos, com
  pausas de até 10 min entre os ciclos** (os dois configuráveis), volta
  sozinha para Com produção **a partir do começo desse trabalho** — ciclos
  soltos de teste/ajuste não bastam. (Regra escolhida pelos dados reais: as
  enfestadeiras trabalham em ciclos curtos e ficam 12–32 min ligadas por hora
  produzindo; em produção as sequências de trabalho passam de 55 min.) A
  volta é calculada dos próprios ciclos (notebook, VPS e relatórios chegam ao
  mesmo resultado, mesmo com ciclos atrasados) e o computador da fábrica a
  grava no histórico.
- Histórico dos períodos (máquina, início, fim, duração, motivo, como voltou)
  com "Apagar" para marcações por engano; relatório "Tempo ligado e parado"
  ganha a coluna "Sem produção (fora)" e a lista dos períodos; o aviso dos
  relatórios cita os períodos sem produção.
- Cartão mais enxuto: estado ao vivo curto ("Ligada 12 min", "Parada 3 min",
  "Sem sinal", "Pausada", "⚠ Parada 23 min" com alerta; o detalhe no
  tooltip); a taxa (m/h) desceu para a linha do estado e o checkbox Produção
  subiu para o cabeçalho.
- **Modo TV redesenhado** para ficar aberto o dia todo: segue o tema claro/
  escuro da plataforma; logo, setor, turno atual com barra de progresso e
  "faltam…", relógio grande; indicadores do dia (rendimento com anel,
  produção, ligadas agora, paradas); cartão grande por máquina com estado e
  tempo, anel de rendimento contra a meta, ligada/parada/produção/ciclos de
  hoje e a linha do tempo do turno; cores de estado (ligada, parada, alerta,
  sem produção, sem sinal); atualiza sem piscar, esconde o cursor parado,
  ajusta-se a telas pequenas e abre direto pelo endereço com `#tv`.
- **Página Configurações** (⚙ → Configurações): máquinas e meta, atalho para
  Turnos e calendário, **alerta de máquina parada** e **acesso remoto** como
  cartões (antes eram popups), **dados** (importar CSV, backup, relatórios),
  aparência (identidade visual, Modo TV, tema), controlador, aplicativo para
  Windows e "sobre". O menu ⚙ ficou com Configurações, Turnos e calendário,
  Modo TV, Tema escuro e Sair.
- Sai o aviso "Meta do turno em risco" (não há uma meta única do setor).
- 39 testes (períodos sem produção no banco e na sincronização).


## 1.4.0 — Central de relatórios, Excel e PDF (app 1.4.0 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; quem usa o programa remoto recebe
ao reabrir; no notebook, `.exe` novo. Banco e sincronização sem mudança.

- **Nova aba Relatórios** (ao lado de Desempenho): a central de relatórios do
  painel. Nove relatórios, todos seguindo o período e o turno da barra de
  filtros, cada um com **Visualizar** (na tela), **Excel** e **PDF**:
  Resumo executivo, Produção diária, Tempo ligado e parado (por dia e
  máquina, com totais e rendimento), Rendimento diário, Produção por turno,
  Paradas, Motivos de parada, Disciplina de turno e Ciclos registrados.
  **Excel completo** e **PDF completo** juntam todos num arquivo só.
- **Excel formatado** (ExcelJS): faixa de título na cor do relatório,
  indicadores, cabeçalho escuro, linhas alternadas, total destacado, valores
  numéricos de verdade (durações em [h]:mm, %, metros, datas), destaque
  verde/vermelho, filtro automático e cabeçalho congelado nas listas, pronto
  para imprimir em paisagem.
- **PDF** (jsPDF + AutoTable): A4 paisagem com o logo, cartões de
  indicadores, tabelas com cabeçalho repetido em cada página e rodapé com
  número de página.
- Bibliotecas guardadas em `painel/assets` (funcionam sem internet na
  fábrica; carregadas só ao baixar): `exceljs.min.js` 4.4.0,
  `jspdf.umd.min.js` 2.5.1 e `jspdf.plugin.autotable.min.js` 3.8.4 (MIT).
- Aviso no topo dos relatórios de tempo (tela, Excel e PDF): intervalos de
  refeição e paradas programadas já estão descontados — não contam como
  disponível nem como parado (só "Ciclos registrados" mostra a duração bruta).
- "Tempo ligado e parado": tabela em blocos por dia — uma linha por máquina e
  "Total do dia" destacado (data e dia só na 1ª linha do bloco na tela/PDF;
  no Excel em todas, para filtrar); datas alinhadas à esquerda em todos.
- **Logo da empresa e ícone do navegador** (Identidade visual): enviar o logo
  (PNG/JPG/WebP, reduzido sozinho) e, opcionalmente, um ícone quadrado. O
  logo vale para o painel inteiro e todos os aparelhos (chave nova `logo` na
  configuração geral, sincronizada com a VPS) e aparece no topo do painel, na
  tela de abertura, na prévia, nos relatórios PDF e Excel, na tela de login
  da VPS e no programa remoto — o servidor passa a entregá-lo em
  `assets/logo.png`. Ícone da aba: o enviado (`assets/icone-empresa.png`) ou,
  sem ele, um quadrado montado a partir do logo. SVG não é aceito (poderia
  rodar script).
- **Gráficos nos relatórios** (na tela, no PDF e como imagem no Excel),
  desenhados pelo próprio painel: rendimento e ligada × parada por máquina
  (Resumo), produção por dia (Produção diária), ligado × parado por dia e por
  máquina (Tempo), linhas de rendimento com a meta (Rendimento diário),
  rendimento por turno (Produção por turno), tempo por faixa de duração e
  paradas por hora do dia (Paradas), tempo por motivo (Motivos), atraso e
  saída antecipada (Disciplina), ciclos por máquina e distribuição da duração
  (Ciclos).
- PDF: as páginas de continuação têm cabeçalho compacto com o logo, o nome do
  relatório e o período.
- Revisão dos cálculos: os totais batem entre os relatórios (tempo parado do
  Resumo = Tempo ligado e parado = paradas de 1 min ou mais + paradas curtas).
  Paradas ganhou a coluna "Intervalo descontado" (parada que atravessa o
  almoço: a duração já vem sem ele) e o indicador "Paradas curtas"; Rendimento
  diário usa o rendimento do período (ponderado pelo tempo de turno) no lugar
  da média simples dos dias; o Resumo não lista turnos sem nada no período.
- Nome dos arquivos diz o período (ex.: `paradas_semana_2026-11-15.pdf`,
  `resumo_executivo_2026-11.xlsx`) em vez da hora do download; durações abaixo
  de 1 min como "17s".
- O antigo "Relatório do período" do menu ⚙ foi substituído pela aba.
- Saiu o botão **Exportar Excel** da barra de filtros (planilha única sem
  formatação) e a biblioteca `xlsx.full.min.js`; os downloads ficam na aba
  Relatórios. No lugar, um **aviso de destaque** que só aparece quando há
  algo importante, um por vez e do mais urgente: máquina parada além do
  limite, dados sem atualizar no turno e paradas longas de hoje sem
  motivo. Clicar leva ao lugar certo.
- **Menu ⚙ Configurações** com rolagem: passava da altura da tela e os
  últimos itens ficavam inacessíveis; agora vai até o fim da janela e rola
  por dentro.


## 1.3.1 — sem o mapa de calor e o Pareto de motivos (app 1.3.1 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; quem usa o programa remoto recebe
ao reabrir; no notebook, `.exe` novo.

- **Desempenho**: saíram o "Mapa de calor — ocupação por dia da semana e
  hora" e o "Paradas por motivo" (Pareto). A Disciplina de turno ocupa a linha
  inteira. O motivo de cada parada continua sendo marcado na linha do tempo e
  aparece no tooltip e no relatório do período (com o resumo por motivo).


## 1.3.0 — gestão: paradas com motivo, tendência, alerta, modo TV e relatório (app 1.3.0 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel e a sincronização mudaram: na VPS, `git pull` (precisa da 1.3.0 lá
para os motivos de parada irem e voltarem); quem usa o programa remoto recebe ao
reabrir; no notebook, `.exe` novo. Banco: nenhuma tabela nova — os motivos são
uma chave nova (`motivos`) em `config_extra`.

- **Produção em metros por hora (m/h)**: a taxa de cada máquina aparece e é
  digitada em m/h (cartões, ⚙ Máquinas, histórico, auditoria). Continua
  guardada em m/min (banco, sincronização e vigências antigas intactos):
  33 m/min = 1.980 m/h; digitar 2000 guarda 33,33 m/min.
- **Visão geral**
  - Indicadores do topo: **Tempo ligado**, **Tempo parado** (novo: média,
    total e maior parada), **Rendimento** (juntou "Rendimento médio" e
    "Progresso da meta": barra com risco da meta, % da meta cumprida,
    projeção para o fim do turno em andamento, comparação em pontos
    percentuais com o período anterior e minigráfico dos últimos
    períodos), **Produção estimada** e **Ligadas agora** (cada máquina num
    quadrado com o número: verde = ligada, vermelho = alerta, cinza =
    parada, tracejado = sem sinal). O KPI "Ciclos" virou texto no rodapé
    do Tempo ligado.
  - Saiu o gráfico "Comparativo de rendimento" (repetia o ranking e os
    cartões); o **Ranking** ocupa a linha inteira.
  - Linha do tempo: clicar numa parada marca o motivo; parada com motivo
    ganha um risco da cor do motivo; a faixa do turno avisa quando o dia
    usa um horário de uma configuração antiga.
- **Motivos de parada**: lista editável em Turnos e calendário (8
  sugestões: falta de material, troca de rolo, manutenção…); marcar pela
  linha do tempo, com observação; sincroniza com a
  VPS e entra na auditoria. Quem só visualiza não marca.
- **Desempenho**: **Evolução do rendimento** por máquina (dia a dia; no
  filtro Dia, os últimos 14 dias), **Paradas por motivo** (Pareto, com o
  quanto do tempo parado já tem motivo) e **Disciplina de turno** (atraso
  na 1ª partida e saída antecipada por máquina, médio e pior caso).
- **Alerta de máquina parada** (⚙ → Alerta de máquina parada, por
  aparelho): dentro do turno e fora dos intervalos, máquina parada além do
  limite (padrão 15 min) fica em vermelho no cartão, no topo da Visão geral
  e no Modo TV; bipe opcional.
- **Modo TV** (⚙ → Aparência): tela cheia para o chão de fábrica — estado
  de cada máquina, há quanto tempo, rendimento de hoje contra a meta.
- **Relatório do período** (⚙): indicadores, por máquina, maiores paradas
  com motivo e paradas por motivo, pronto para imprimir ou salvar em PDF.
- Saiu a lista "Maiores paradas" do Desempenho (a maior parada continua no
  indicador Tempo parado, na Análise de paradas e no relatório).
- Página "Produção por turno" (configuração) passa a se chamar **Turnos e
  calendário**.
- Tooltips dos gráficos abrem por toque no celular; período, data e turno
  vão no endereço (`#p=dia&d=2026-11-13&t=0`) para mandar o link de um dia.
- Cores com sentido fixo (ligado verde, parado vermelho, parada curta
  amarela, intervalo laranja).
- 37 testes (1 novo: motivos de parada no banco e na sincronização).


## 1.2.1 — linha do tempo com tempo parado (app 1.2.1 · firmware 3.0 e programa remoto 1.2.0, sem mudança)

Só o painel mudou: na VPS basta o `git pull`; quem usa o programa remoto
recebe ao reabrir (não precisa baixar outro `.exe`); no notebook, `.exe` novo.

- **Linha do tempo por máquina**: o tooltip de cada ciclo mostra o tempo
  ligado, a parada antes dele e os totais do período (ligada / parada); os
  trechos vazios (paradas) também têm tooltip, com horário e tempo parado
  (mesma regra da "Análise de paradas"); a faixa dos turnos mostra o nome e
  o horário de cada turno.


## 1.2.0 — edição remota (app 1.2.0 · firmware 3.0, sem mudança)

Quem está fora da empresa também altera a configuração de forma permanente,
sem precisar do computador da fábrica. Ver `docs/nuvem-vps.md`, "Edição remota".

- **Computador da fábrica = mestre**: nunca pede senha, pode tudo, define as
  senhas e liga/desliga a edição remota (⚙ Configurações → Acesso remoto).
- **Duas senhas na VPS**: visualização (só vê) e edição (vê e altera
  máquinas, metas, turnos, intervalos, calendário, vigências e cores). O
  papel vai no cookie assinado; trocar uma senha derruba só as sessões dela.
  Pela VPS, trocar senha exige redigitar a senha de edição atual.
- **Configuração nas duas mãos**: cada item tem revisão (tabela nova
  `config_rev`); o notebook troca com a VPS a cada 15 s
  (`POST /api/nuvem/config`, `"versao": 2`). Mesmo item alterado nos dois
  lados = vale o mais recente, e quem perdeu recebe aviso; itens diferentes
  nunca se perdem; edição offline sobe quando a internet volta.
- **Auditoria** (tabela nova `alteracoes`): quem, de onde (fábrica/internet +
  IP), quando e o quê — no popup Acesso remoto, "Últimas alterações".
- Painéis abertos se atualizam sozinhos quando outra pessoa altera
  ("Configuração atualizada por outro usuário").
- Segurança: CSRF (cabeçalho `X-Painel-Edicao` + origem), sem CORS na VPS,
  leitura do controlador/conexão nunca pela VPS, bloqueio por tentativas.
- Compatível nos dois sentidos: VPS 1.2.0 aceita o notebook 1.1.0 sem
  desfazer edições remotas; notebook 1.2.0 cai no envio antigo com VPS 1.1.0.
- **`Painel de Produção.exe`** (programa remoto): para os computadores de
  fora — só abre a VPS, sem chave nem banco; login guardado por 30 dias;
  ícone com a marca da Santex (o "S" na elipse vermelha do logo, nítido de
  16 a 256 px).
- **Download pelo painel da VPS**: link na tela de login, cartão "Painel no
  seu computador" (dispensável por 30 dias), item ⚙ Configurações →
  Aplicativo para Windows e janela com os passos de instalação (incluindo o
  aviso do SmartScreen). Só em computador com Windows, nunca no celular nem
  dentro do próprio programa. O arquivo vai versionado em `vps/app-remoto/`
  (atualizado só quando o programa muda) e o `vps/instalar.sh` o instala.
- **Downloads no aplicativo**: "Exportar Excel" e "Backup dos dados" não
  faziam nada no `.exe` (o pywebview cancelava todo download) — agora abrem
  "Salvar como" do Windows.
- **Estrutura reorganizada**: `deploy/` → `vps/` (instalador `vps/instalar.sh`);
  geradores em `gerar/` (`gerar.bat` com menu); todos os entregáveis em
  `distribuir/` (fora do git); código do programa remoto em `remoto/`.
- 34 testes (9 novos de edição remota com servidor real), teste ponta a
  ponta no navegador com a cópia do banco de produção e teste de
  estabilidade (painel da fábrica + editor remoto abertos juntos, sem loop).
- Revisão final antes da produção definitiva:
  - nome de turno escapado na tabela de ciclos (um nome malicioso salvo pela
    internet não executa nada no painel da fábrica);
  - bloqueio por senhas erradas usa o IP acrescentado pelo proxy (último do
    `X-Forwarded-For`): trocar o "IP" a cada tentativa não burla mais;
  - VPS envia `X-Frame-Options`/`frame-ancestors` (nenhum site embute o
    painel), `nosniff`, `Referrer-Policy` e HSTS;
  - VPS reinstalada ou restaurada de backup: o notebook percebe e reenvia a
    configuração (vence o que for mais recente);
  - auditoria com a hora real na primeira sincronização (antes aparecia 1970);
  - alterações feitas por aparelho da rede local com PIN aparecem como
    "rede local (IP)" na auditoria;
  - lista de IPs com senha errada não cresce sem limite.


## 1.1.0 — em desenvolvimento (app 1.1.0 · firmware 3.0)

Acesso remoto: quem está fora da rede da empresa vê o painel em
**https://santex.rexar.com.br**, com login e somente leitura. Ver
`docs/nuvem-vps.md`.

- **Firmware 3.0**: além de responder ao notebook, o ESP32 envia os ciclos e
  o estado das máquinas para a VPS por HTTPS (tarefa própria, a cada ~10 s),
  conferindo o certificado da Let's Encrypt. Só libera um ciclo da memória
  depois que a VPS **e** o notebook o receberam. Funciona com o notebook
  desligado; sem internet, guarda e envia depois.
- **Notebook** continua o fornecedor principal na empresa e envia a
  configuração (máquinas, metas, turnos, cores) para a VPS quando muda.
- **VPS**: o mesmo servidor em `PAINEL_MODO=nuvem` — recebe do ESP32 e do
  notebook com a `NUVEM_CHAVE`, sempre somente leitura, bloqueio após 10
  senhas erradas.
- **Histórico completo na VPS**: o notebook envia todos os ciclos que a VPS
  ainda não tem (lotes de 500; depois os novos a cada 30 s), sem duplicar o
  que o ESP32 manda direto (mesma chave: série + id). De hora em hora
  confere os totais e, se a VPS tiver perdido algo, reenvia tudo. Provado
  com a cópia do banco de produção: 4.215 ciclos em ~12 s, histórico da VPS
  idêntico ao do notebook. Rota `POST /api/nuvem/historico`.
- **Deploy pelo git na VPS**: `git pull --ff-only && sudo bash deploy/instalar_vps.sh`.
  `CLAUDE.md` na raiz (projeto + aponta para `deploy/CLAUDE_VPS.md` na VPS),
  com a seção "Deploy de uma atualização (git pull)" e as verificações.
- Chave certa nunca é bloqueada pelo limite de tentativas (erros de terceiros
  não travam o ESP32 nem o notebook).
- **Senha única do acesso remoto**, definida e trocada no notebook
  (⚙ Configurações → Acesso remoto). O notebook guarda só o hash (PBKDF2) e
  o envia para a VPS com a configuração; a VPS mostra uma tela de login só
  com senha e mantém a sessão por 30 dias. Trocar a senha desconecta todos.
  O hash nunca sai pelo `GET /config` (tabela `segredos` separada). Arquivos de
  instalação em `deploy/` (systemd + Caddy).
- **Painel**: na VPS mostra "Controlador enviando / sem enviar", quando a
  configuração chegou do notebook e esconde os controles da rede local; no
  notebook mostra se a configuração e os ciclos estão chegando à VPS.
- Notebook não baixa de novo o que já tem e pede a limpeza do ESP32 no
  máximo a cada 60 s enquanto a VPS não alcança.
- `deploy/empacotar_vps.ps1` monta o pacote da VPS (sem segredos, com quebra
  de linha Linux) e inclui `deploy/CLAUDE_VPS.md` como `CLAUDE.md`: o Claude
  Code roda a instalação na VPS seguindo esse roteiro.
- `POST /api/nuvem/ping`: confere a chave sem gravar nada (teste da instalação).
- Verificado: `santex.rexar.com.br` está com o proxy da Cloudflare ligado —
  precisa ficar "Somente DNS" para o ESP32 conseguir enviar.

## 1.0.0 — 17/11/2026 (app 1.0.0 · firmware 2.2)

Primeira versão para produção permanente.

### Desempenho
- `/dados` responde **304** (sem corpo) enquanto não chega ciclo novo e vai
  comprimido com gzip (204 KB → 42 KB). Antes o histórico inteiro era
  baixado e redesenhado a cada 5 s, por aparelho.
- Servidor atende várias requisições ao mesmo tempo (o diagnóstico do ESP32
  não trava mais o painel dos outros); painel com `Cache-Control: no-cache`.
- Painel não consulta nada com a janela minimizada e nunca sobrepõe consultas.

### Dados
- **Backup automático diário** do banco em `backup\` na raiz do projeto
  (14 dias + 1 por mês por 12 meses), fora do git e do `.exe`.
- Ciclos gravados sem relógio (`SEM_HORA`) não aparecem mais empilhados na
  hora do download — ficam no banco, contados à parte ("sem data/hora").
  Firmware 2.2 dá a hora real a esses ciclos quando o relógio é acertado no
  mesmo boot.
- Deduplicação pela série do ESP32 (o id do dispositivo mudou 2 vezes).
- Leitura pela USB reconecta sozinha se o cabo soltar.

### Segurança
- Outros aparelhos da rede abrem o painel em **somente leitura**; alteração
  remota só com PIN (`dados/seguranca.json`).
- ESP32 exige a `API_CHAVE` em `/limpar`, `/hora` e `/acao`. Chave
  divergente nunca impede o download dos ciclos (só a limpeza e o relógio).
- Nomes de máquina/turno escapados no HTML; firewall documentado só para
  redes Privada/Domínio; cópias antigas do painel fora do `.exe`.

### Painel
- **Meta em %** do tempo disponível de cada turno (antes: horas ligada/dia),
  convertida sem mudar a meta efetiva (8 h ÷ 14 h = 57,1%). Selo
  renomeado de "Meta/dia" para "Meta por turno".
- Faixa e linhas tracejadas dos **turnos** na Linha do tempo.
- Removido o gráfico "Tendência diária de rendimento" da página Desempenho.
- Aviso "⚠ N sem data/hora" do rodapé pode ser dispensado (×); volta sozinho
  só se surgirem ciclos sem hora novos ("1 sem data/hora (novos)").
- Versão no rodapé; aviso de backup e de chave no popover do controlador.
- Linha "Exibindo" mostra o dia da semana no período Dia
  ("Terça-feira, 17/11/2026 (hoje)").
- Rodapé: "Desenvolvido por Marcelo Braga" no lugar da dica de arrastar CSV
  (arrastar um CSV para a tela continua funcionando).
- Excel funciona **sem internet**: biblioteca SheetJS 0.18.5 incluída em
  `painel/assets/xlsx.full.min.js` (a internet fica só como reserva).

### Operação
- `ferramentas/instalar_inicio_automatico.ps1` (abrir com o Windows).
- `controle_leitura_server.py` passou a ser o mesmo servidor do app.
- Testes automáticos: `python -m unittest discover -s testes -v`.
