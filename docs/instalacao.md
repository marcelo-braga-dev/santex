# Instalação e configuração do ambiente

Guia completo para deixar o ambiente pronto do zero: Arduino IDE + núcleo
ESP32, driver USB da placa, e as dependências Python das ferramentas.

## 1. Requisitos

- **Placa**: ESP32 DevKit V1 / NodeMCU-32S (módulo WROOM-32), alimentada por
  cabo USB.
- **Arduino IDE** (2.x recomendado).
- **Python 3** (para as ferramentas de leitura/servidor local).
- **Cabo USB de dados** (não só de carga — muitos cabos baratos só carregam,
  não transmitem dados; se a porta nunca aparecer, troque o cabo antes de
  qualquer outra coisa).

## 2. Instalar o núcleo ESP32 na Arduino IDE

1. Abra **File > Preferences**.
2. Em "Additional Boards Manager URLs", adicione:
   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```
3. **Tools > Board > Boards Manager** → busque `esp32` → instale
   **"esp32 by Espressif Systems"**.
4. **Tools > Board > ESP32 Arduino** → selecione **"ESP32 Dev Module"**.

> O firmware deste projeto foi validado no núcleo **3.3.12**. Núcleos mais
> novos ou mais antigos podem mudar a API de algumas bibliotecas internas
> (já aconteceu com o watchdog — ver `docs/solucao-de-problemas.md`).

## 3. Driver USB (CP210x ou CH340)

A placa só aparece em **Tools > Port** se o Windows reconhecer o chip
USB-serial dela. Os dois mais comuns:

- **CP2102 / CP210x (Silicon Labs)** — a maioria das placas "ESP32 DevKit V1"
  genéricas vendidas no Brasil usa esse chip.
- **CH340** — outro chip comum, mais barato.

### Diagnóstico rápido

Se a porta não aparece em **Tools > Port**, abra o **Gerenciador de
Dispositivos** do Windows e procure por algo com um ícone de alerta
amarelo em "Portas (COM e LPT)" ou um dispositivo desconhecido. Se aparecer
como **"CP2102 USB to UART Bridge Controller"** com status de erro, o driver
não está instalado (código de erro 28 do Windows = "os drivers para este
dispositivo não estão instalados").

### Instalar o driver CP210x

1. Baixe em: **https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers**
2. Baixe o pacote "CP210x Universal Windows Driver" e extraia o `.zip`.
3. Esse pacote **não tem instalador com tela** — é só o `.inf`/`.sys`. Duas
   formas de instalar:
   - **Pelo Gerenciador de Dispositivos**: clique com o botão direito no
     dispositivo com erro → "Atualizar driver" → "Procurar no computador"
     → aponte para a pasta extraída.
   - **Via `pnputil` (linha de comando, como admin)**:
     ```
     pnputil /add-driver "caminho\para\silabser.inf" /install
     ```
4. Desconecte e reconecte o cabo USB.
5. Confirme no Gerenciador de Dispositivos: deve aparecer **"Silicon Labs
   CP210x USB to UART Bridge (COMx)"** com status **OK**.

### Instalar o driver CH340

Baixe o driver "CH340" (busque "CH340 driver Windows" do fabricante WCH) e
instale normalmente — esse já vem com instalador de tela.

## 4. Gravar o firmware pela primeira vez

1. Abra `firmware/controle_producao_horimetro/controle_producao_horimetro.ino`
   na Arduino IDE.
2. **Tools > Board** → "ESP32 Dev Module".
3. **Tools > Port** → a porta COM da placa.
4. Clique em **Verificar** (✓) para compilar.
5. Clique em **Carregar/Upload** (→).
   - Se travar em "Connecting....." — segure o botão **BOOT** da placa até
     o upload começar (comum em placas sem circuito de auto-reset).
6. Abra o **Serial Monitor** a **9600 baud** e confira se aparece a
   mensagem de boot do firmware (ver `docs/firmware.md`).

> **Não use o botão de "Debug" (ícone de inseto) da Arduino IDE** — ele
> tenta abrir uma sessão JTAG via OpenOCD, que exige hardware de depuração
> que essa placa não tem embutido. Use sempre Verificar/Carregar.

## 5. Dependências Python

```
pip install pyserial
```

É a única dependência externa das ferramentas (`monitor_serial.py` e
`controle_leitura_server.py`). `gerar_dados_historico.py` só usa a
biblioteca padrão do Python.

## 6. Checklist de uma instalação pronta

- [ ] Núcleo ESP32 instalado na Arduino IDE
- [ ] Driver USB instalado (porta aparece com status OK no Gerenciador de
      Dispositivos)
- [ ] Firmware compila e grava sem erros
- [ ] Serial Monitor mostra o boot e o cabeçalho CSV
- [ ] `pip install pyserial` concluído
- [ ] `python ferramentas/controle_leitura_server.py` sobe sem erro e
      responde em `http://localhost:8787/status`
