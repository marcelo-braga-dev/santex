# Histórico de versões

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
- **`PainelSantexRemoto.exe`**: programa para os computadores de fora — só
  abre a VPS, sem chave nem banco; login guardado por 30 dias.
- **Estrutura reorganizada**: `deploy/` → `vps/` (instalador `vps/instalar.sh`);
  geradores em `gerar/` (`gerar.bat` com menu); todos os entregáveis em
  `distribuir/` (fora do git); código do programa remoto em `remoto/`.
- 32 testes (7 novos de edição remota com servidor real) e teste ponta a
  ponta no navegador com a cópia do banco de produção.


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
