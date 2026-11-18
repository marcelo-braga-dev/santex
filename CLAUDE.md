# Controle de Produção — Horímetro (instruções para o Claude Code)

Responda sempre em **português do Brasil**.

## Se você está na VPS (Linux, servidor do acesso remoto)

**Siga `deploy/CLAUDE_VPS.md`** — ele tem o deploy (atualização por
`git pull`), as verificações e as regras de segurança da VPS de produção
(`https://santex.rexar.com.br`). Leia-o inteiro antes de qualquer comando.
O resto deste arquivo é sobre o desenvolvimento no notebook (Windows).

## O projeto

| Parte | Onde | O que faz |
|---|---|---|
| Firmware 3.0 (ESP32) | `firmware/controle_producao_horimetro/` | Lê 4 relés, guarda ciclos na flash, responde ao notebook na rede local e envia para a VPS por HTTPS |
| App 1.1.0 (Windows) | `app/` + `ferramentas/` + `painel/` | Servidor + painel web; lê o ESP32 pelo Wi-Fi; banco SQLite; backup diário; envia configuração e histórico para a VPS |
| Servidor da VPS | o mesmo código, `PAINEL_MODO=nuvem` | Recebe do ESP32 e do notebook, serve o painel somente leitura com senha única |

Documentação: `README.md`, `docs/` (`nuvem-vps.md` = acesso remoto), `CHANGELOG.md`.

## Regras do projeto

- **Commits direto na `main`**, sem branches; versões por tag (`v1.0.0` é
  congelada — nunca mova nem recrie essa tag). Commit e push só quando o
  usuário pedir.
- **O repositório no GitHub é PÚBLICO.** Nunca versione `.env`, `segredos.h`,
  `app/segredos_app.json`, `app/build_info.json`, bancos (`*.db`), `backup/`,
  `dist-vps/` nem `dados/`. Antes de um push, confira que nenhum valor do
  `.env` aparece nos arquivos.
- **O banco de produção nunca é apagado nem reescrito**
  (`%APPDATA%\PainelProducaoSantex\dados\painel.db` no notebook,
  `/var/lib/painel-nuvem` na VPS). Teste em cópias (API de backup do SQLite,
  original aberto com `?mode=ro`). Nos testes, nunca inicie a leitura Wi-Fi
  do ESP32 real (ela baixa e limpa ciclos do controlador).
- Mudanças no banco só aditivas (coluna, índice, tabela nova).
- Senhas e chaves nunca aparecem em respostas, logs ou comandos com `echo`.

## Testes e build

```
python -m unittest discover -s testes -v      # 25 testes, pasta temporária
python ferramentas/gerar_segredos.py          # .env -> segredos.h + app/segredos_app.json
app\gerar_executavel.bat                      # .exe (app/dist)
.\deploy\empacotar_vps.ps1                    # pacote da VPS (alternativa ao git pull)
```

Firmware: Arduino IDE ou `arduino-cli compile --fqbn esp32:esp32:esp32` (núcleo 3.3.x).
