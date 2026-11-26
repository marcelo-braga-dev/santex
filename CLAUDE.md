# Controle de Produção — Horímetro (instruções para o Claude Code)

Responda sempre em **português do Brasil**.

## Se você está na VPS (Linux, servidor do acesso remoto)

**Siga `vps/CLAUDE_VPS.md`** — ele tem o deploy (atualização por
`git pull`), as verificações e as regras de segurança da VPS de produção
(`https://santex.rexar.com.br`). Leia-o inteiro antes de qualquer comando.
(Até a 1.1.0 essa pasta se chamava `deploy/`.) O resto deste arquivo é sobre
o desenvolvimento no notebook (Windows).

## O projeto

| Parte | Onde | O que faz |
|---|---|---|
| Firmware 3.2 (ESP32) | `firmware/controle_producao_horimetro/` | Lê 4 relés, guarda ciclos na flash, responde ao notebook na rede local e envia para a VPS por HTTPS |
| App 1.7.5 da fábrica (Windows) | `app/` + `ferramentas/` + `painel/` | Servidor + painel web (abas Visão geral, Desempenho e Relatórios — Excel/PDF); lê o ESP32; banco SQLite; backup diário; **mestre** (edita sem senha); sincroniza configuração (duas mãos, 15 s) e histórico com a VPS |
| Servidor da VPS | o mesmo código, `PAINEL_MODO=nuvem`; instalação em `vps/` | Recebe do ESP32 e do notebook; painel com senha de visualização ou de edição; auditoria |
| Programa remoto | `remoto/painel_remoto.py` + `remoto/icone.ico` | "Painel de Produção.exe": janela que só abre a VPS (sem chave); cópia publicada em `vps/app-remoto/` e baixada pelo painel da VPS |
| Geradores | `gerar/` → saída em `distribuir/` (fora do git) | `gerar.bat`: `.exe` da fábrica, `.exe` remoto, pacote da VPS |

Documentação: `README.md`, `docs/` (`nuvem-vps.md` = acesso remoto e edição remota), `CHANGELOG.md`.

## Versão 2.0 em desenvolvimento (desde 26/11/2026)

A `main` tem a 2.0 em andamento: vários setores e ~50 ESP32 (um por
máquina). **Produção = tag `v1.7.5`.** Antes de continuar, leia
`docs/progresso-2.0.md` (onde parou, próxima etapa, cuidados) e
`docs/plano-2.0.md` (plano completo e decisões). **Não faça deploy da `main`
na VPS nem gere o `.exe` da fábrica a partir dela** até a 2.0 ser liberada.
Ao fim de cada sessão, atualize `docs/progresso-2.0.md`.

## Regras do projeto

- **Commits direto na `main`**, sem branches; versões por tag (`v1.0.0` é
  congelada — nunca mova nem recrie essa tag). Commit e push só quando o
  usuário pedir.
- **O repositório no GitHub é PÚBLICO.** Nunca versione `.env`, `segredos.h`,
  `app/segredos_app.json`, `app/build_info.json`, bancos (`*.db`), `backup/`,
  `distribuir/`, `gerar/_trabalho/` nem `dados/`. Antes de um push, confira
  que nenhum valor do `.env` aparece nos arquivos.
- O `PainelProducaoSantex-<versão>.exe` leva a chave da fábrica: nunca o distribua
  para fora — fora usa-se o `PainelSantexRemoto.exe`.
- **O banco de produção nunca é apagado nem reescrito**
  (`%APPDATA%\PainelProducaoSantex\dados\painel.db` no notebook,
  `/var/lib/painel-nuvem` na VPS). Teste em cópias (API de backup do SQLite,
  original aberto com `?mode=ro`). Nos testes, nunca inicie a leitura Wi-Fi
  do ESP32 real (ela baixa e limpa ciclos do controlador) — por isso o
  `.exe` da fábrica não é aberto em testes.
- Mudanças no banco só aditivas (coluna, índice, tabela nova).
- Senhas e chaves nunca aparecem em respostas, logs ou comandos com `echo`.
- **Ver o painel da VPS (Claude Code)**: `python ferramentas/acesso_vps.py /status`
  (ou `/dados?setor=enfestadeiras`, `/config`; `--edicao` para a senha de
  edição; `--saida arquivo` para gravar). Usa a senha de acesso remoto
  guardada no notebook (banco aberto só para leitura), só faz GET e nunca
  imprime a senha. Senha não guardada: o usuário guarda no painel do notebook
  (Configurações → Acesso remoto → Senhas guardadas neste computador).

## Testes e build

```
python -m unittest discover -s testes -v      # 59 testes, pasta temporária
python ferramentas/gerar_segredos.py          # .env -> segredos.h + app/segredos_app.json
gerar\gerar.bat                               # menu: .exe da fábrica / .exe remoto / pacote VPS -> distribuir\
python gerar/exe_fabrica.py                   # (ou cada um direto)
python gerar/exe_remoto.py
.\gerar\pacote_vps.ps1
```

Firmware: Arduino IDE ou `arduino-cli compile --fqbn esp32:esp32:esp32` (núcleo 3.3.x).
