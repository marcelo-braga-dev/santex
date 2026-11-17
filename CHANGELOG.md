# Histórico de versões

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
