// Controle de producao - horimetro de ATE 4 MAQUINAS no mesmo ESP32.
// Placa: ESP32 DevKit V1 / NodeMCU-32S (modulo WROOM-32), alimentado por
// fonte (5V no pino VIN ou USB). SEM display/LCD/botoes - so os 4 contatos
// secos, o RTC, o Wi-Fi e a Serial.
//
// Funciona SOZINHO, sem PC ligado: cada ciclo e gravado na flash do ESP32
// (LittleFS) com data/hora real do RTC DS3231M, e o PC busca pelo Wi-Fi o
// que ainda nao tem (ferramentas/monitor_wifi.py) sempre que estiver ligado.
// Nada se perde enquanto o PC esta desligado (cabem CAPACIDADE_REGISTROS
// ciclos - semanas de producao; so acima disso os mais antigos seriam
// sobrescritos). Depois que o PC extrai os dados, ele "zera" o
// armazenamento (POST /limpar) e o espaco volta a ficar livre.
//
// SEM watchdog customizado de proposito: a API esp_task_wdt desse nucleo
// (Arduino-ESP32 3.3.12 / ESP-IDF 5.x) se comportou de forma instavel nos
// testes (erros "already initialized" e depois "task not found" ao
// resetar) - um watchdog mal inscrito com trigger_panic ligado arrisca
// reiniciar o ESP32 sem motivo real, o que e pior do que nao ter watchdog.
// O loop() e simples e nao-bloqueante, entao o risco de travamento e baixo.
//
// Contatos dos reles de sinalizacao -> pino de cada maquina e GND:
//   Maquina 1 -> GPIO 16
//   Maquina 2 -> GPIO 17
//   Maquina 3 -> GPIO 18
//   Maquina 4 -> GPIO 19
// Assume contato fechando para GND quando a maquina liga (INPUT_PULLUP).
// Se algum rele fizer o contrario (abre quando liga), inverta a logica em
// lerContatoLigado().
//
// RTC DS3231M (I2C, endereco 0x68) - alimentar com 3V3 (nao 5V):
//   VCC -> 3V3 | GND -> GND | SDA -> GPIO 21 | SCL -> GPIO 22
// O RTC guarda a hora LOCAL (a do PC que acertou o relogio). O PC acerta a
// hora sozinho pelo Wi-Fi quando a diferenca passa de 3s; tambem da para
// acertar pela Serial com "T2026-10-30 14:05:00".
//
// Pinos evitados de proposito (nao usar para nada neste projeto):
//   GPIO 0, 2, 5, 12, 15  -> pinos de "strapping" (afetam o boot do ESP32)
//   GPIO 1, 3             -> UART0 (Serial/USB)
//   GPIO 6-11             -> ligados a flash SPI interna, nunca usar
//   GPIO 34-39            -> so entrada, sem pull-up interno (nao servem
//                            para os contatos, que dependem de INPUT_PULLUP)
// GPIO 2 e usado abaixo so para o LED onboard (saida), que e seguro.
//
// Saida Serial (CSV, 9600 baud): maquina,ciclo,inicio,fim,duracao_s,obs
// "inicio"/"fim" sao data/hora do RTC (AAAA-MM-DDTHH:MM:SS) ou "?" se a
// hora ainda nao foi acertada.
//
// Wi-Fi - 3 modos, escolhidos pela pagina http://192.168.4.1 (sem regravar):
//   AMBAS (padrao): entra na rede da empresa E cria a propria rede
//                   HORIMETRO_SANTEX ao mesmo tempo - o notebook acha o
//                   ESP32 de qualquer um dos dois jeitos.
//   SO EMPRESA:     so a rede da empresa. Se ela ficar 2 min fora, a rede
//                   propria liga sozinha (para nunca perder o acesso).
//   SO PROPRIA:     so a rede HORIMETRO_SANTEX (sem roteador).
// Modo, nome/senha da rede da empresa e IP fixo ficam gravados na NVS; os
// valores abaixo (EMPRESA_*_PADRAO) so valem ate a primeira configuracao.
// Rotas HTTP (porta 80, tambem http://horimetro.local):
//   GET  /                  -> pagina de situacao e configuracao do Wi-Fi
//   POST /config            -> salva a configuracao do Wi-Fi e reinicia
//   GET  /info              -> JSON: hora, ultimo id gravado, estado das maquinas
//   GET  /ciclos?desde=N    -> CSV dos ciclos com id > N (ate 200 por vez;
//                              cabecalho X-Lido-Ate = ultimo id examinado)
//   POST /hora?epoch=N      -> acerta o RTC (N = segundos desde 1970, hora local)
//   POST /limpar?ate=N      -> apaga do ESP32 os ciclos com id <= N (o PC so
//                              chama depois de confirmar que gravou no banco)
// Cada ciclo tem um id sequencial unico (nunca reinicia), por isso o PC
// sabe exatamente o que falta buscar e nunca grava um ciclo duas vezes.
//
// Persistencia:
//   - NVS (Preferences, namespace "horimetro"): um registro pequeno por
//     maquina (chaves "m1".."m4") gravado em toda transicao de estado e a
//     cada 30s enquanto a maquina esta ligada, mais o ultimo id de ciclo
//     ("seq") e o numero de serie deste ESP32 ("serie"). No boot, se a queda
//     de energia aconteceu com a maquina ligada e ela voltou desligada, o
//     ciclo pendente e fechado com os dados salvos (marcado
//     CICLO_RECUPERADO_APOS_QUEDA); se ela continuou ligada, a contagem do
//     ciclo retoma de onde parou.
//   - LittleFS ("/ciclos.bin"): historico de ciclos, registros de 24 bytes
//     num buffer circular (o id N fica no slot (N-1) % CAPACIDADE_REGISTROS).
// HISTORICO: a versao anterior usava a biblioteca EEPROM (emulada). No
// ESP32 cada EEPROM.commit() regravava o bloco inteiro de 4 KB na NVS - os
// dados nao estavam sobrevivendo ao reset (nada era recuperado no boot) e o
// desgaste da flash era alto. Preferences grava so os ~20 bytes da maquina.
//
// Estado ao vivo: a cada 10s o firmware emite, para cada maquina, a linha
//   # ESTADO,<maquina>,<1=ligada|0=desligada>,<segundos no estado atual>
// usada pelo monitor_serial.py (quando ligado por USB). Pelo Wi-Fi o mesmo
// estado vem em GET /info.
//
// Comandos pela Serial (Serial Monitor com "Nova linha" habilitado):
//   L1 .. L4  -> liga manualmente a maquina 1-4 (modo manual)
//   D1 .. D4  -> desliga manualmente a maquina 1-4 (modo manual)
//   R1 .. R4  -> devolve o controle ao contato real da maquina 1-4
//   T<AAAA-MM-DD HH:MM:SS> -> acerta o relogio (RTC)
//   I         -> mostra hora, Wi-Fi/IP e quantos ciclos estao gravados
//   S         -> diagnostico completo (RTC, I2C, pull-ups, Wi-Fi, memoria, eventos)
//   W         -> volta o Wi-Fi para a configuracao de fabrica (modo AMBAS)
//   X         -> apaga todos os ciclos guardados (use so se ja extraiu tudo)
// Em modo manual o contato real dessa maquina e ignorado ate o R
// correspondente. Os ciclos gerados assim sao marcados "SIMULADO" no log.

#include <Preferences.h>
#include <Wire.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <time.h>
#include <sys/time.h>
#include <NetworkClientSecure.h>
#include <HTTPClient.h>

// ---------------------------------------------------------------------
// Configuracao da rede (valores de fabrica - depois, tudo pela pagina
// http://192.168.4.1, sem precisar regravar o firmware)
// ---------------------------------------------------------------------
const uint8_t MODO_SO_PROPRIA = 0;
const uint8_t MODO_SO_EMPRESA = 1;
const uint8_t MODO_AMBAS = 2;
const uint8_t MODO_WIFI_PADRAO = MODO_AMBAS;

// Nomes de rede e senhas ficam no .env da raiz do projeto (FORA do git):
// EMPRESA_SSID_PADRAO, EMPRESA_SENHA_PADRAO, AP_SSID, AP_SENHA e API_CHAVE. O comando
//     python ferramentas/gerar_segredos.py
// gera o segredos.h desta pasta a partir dele (rode antes de compilar).
// Sem segredos.h o Arduino IDE para com "segredos.h: No such file".
#include "segredos.h"
#include "certificados.h" // certificado raiz da VPS (publico, versionado)
const IPAddress AP_IP(192, 168, 4, 1);
const uint8_t AP_CANAL = 6; // com a rede da empresa ligada, o ESP32 usa o canal do roteador
const uint8_t AP_MAX_CONEXOES = 3;

const char *NOME_REDE = "horimetro"; // http://horimetro.local

const uint8_t NUM_MAQUINAS = 4;
const uint8_t PINOS_RELE[NUM_MAQUINAS] = {16, 17, 18, 19};

const uint8_t PINO_LED_STATUS = 2; // LED onboard da maioria das placas ESP32 DevKit
const uint8_t PINO_SDA = 21;
const uint8_t PINO_SCL = 22;
const uint8_t ENDERECO_RTC = 0x68;
const unsigned long DEBOUNCE_MS = 1000;
const float DURACAO_MINIMA_VALIDA_S = 0.5; // abaixo disso, o ciclo ainda e logado, so marcado como suspeito
const unsigned long INTERVALO_SALVAMENTO_MS = 30000UL; // grava progresso na flash a cada 30 segundos (maquina ligada)
const unsigned long INTERVALO_ESTADO_MS = 10000UL; // linha "# ESTADO" para o painel ao vivo a cada 10 segundos
const unsigned long INTERVALO_RESYNC_RTC_MS = 600000UL; // rele o RTC a cada 10 min (millis() sozinho deriva)
const unsigned long INTERVALO_RECONEXAO_WIFI_MS = 60000UL;
const unsigned long TEMPO_ATE_LIGAR_REDE_PROPRIA_MS = 120000UL; // modo SO EMPRESA sem conexao -> liga a rede propria
// Se o ESP32 ficou desligado mais do que isso com a maquina ligada, nao da
// para saber se ela parou no meio - o ciclo antigo e fechado como
// recuperado e um novo comeca agora.
const uint32_t LIMITE_QUEDA_CONTINUA_S = 600;

const uint32_t CAPACIDADE_REGISTROS = 20000; // 20000 x 24 bytes = 480 KB do LittleFS
const char *ARQUIVO_CICLOS = "/ciclos.bin";
const uint32_t MAX_CICLOS_POR_RESPOSTA = 200;

const uint8_t FLAG_CURTO = 0x01;
const uint8_t FLAG_SIMULADO = 0x02;
const uint8_t FLAG_RECUPERADO = 0x04;
const uint8_t FLAG_SEM_HORA = 0x08;
// Ciclo sem hora gravado com o "relogio interno" no lugar da data: o campo
// inicioEpoch guarda os segundos desde que o ESP32 ligou (no fim do ciclo) e
// "reservado" o numero do boot. Quando a hora for acertada (PC, internet ou
// RTC) ainda no mesmo boot, corrigirCiclosSemHora() calcula a data real e
// tira as duas marcas. Nunca vai para o PC (so SEM_HORA aparece no obs).
const uint8_t FLAG_HORA_RELATIVA = 0x10;

Preferences prefs;
WebServer servidor(80);

enum class EstadoEquipamento : uint8_t {
  DESLIGADO = 0,
  LIGADO = 1
};

struct EstadoPersistido {
  uint32_t contadorCiclos;
  uint32_t totalSegundosLigado;
  uint32_t cicloAtualSegundos;
  uint32_t estadoLigado; // 1 = ligada (uint32_t para nao haver padding variavel)
  uint32_t inicioEpoch;  // data/hora (RTC) em que o ciclo atual comecou, 0 = desconhecida
};
const size_t TAMANHO_ESTADO_V1 = 16; // versao sem inicioEpoch - ainda lida, para nao zerar os contadores na atualizacao

// Data/hora LOCAL do RTC (sem fuso).
struct DataHora {
  uint16_t ano;
  uint8_t mes, dia, hora, minuto, segundo;
};

// Leitura "ao vivo" do RTC para a pagina de situacao: o chip responde no
// I2C? o oscilador parou (OSF)? esta configurado para parar na bateria
// (EOSC)? Le a hora e a temperatura interna (prova de que o chip funciona).
struct DiagnosticoRtc {
  bool responde;
  bool osf;          // registro 0x0F bit 7: oscilador parou (sem energia) desde o ultimo acerto
  bool eosc;         // registro 0x0E bit 7: oscilador desliga quando o RTC esta so na bateria
  bool leuHora;
  uint32_t epoch;
  bool temTemperatura;
  float temperatura; // graus C, resolucao 0,25
};

struct RegistroCiclo {
  uint32_t id;             // sequencial, nunca reinicia (0 = slot vazio)
  uint32_t ciclo;          // numero do ciclo daquela maquina
  uint32_t inicioEpoch;    // 0 = desconhecido
  uint32_t fimEpoch;       // 0 = desconhecido
  uint32_t duracaoDecimos; // decimos de segundo
  uint8_t maquina;         // 1-4
  uint8_t flags;           // FLAG_*
  uint16_t reservado;
};

EstadoEquipamento estadoAtual[NUM_MAQUINAS];
bool leituraEstavel[NUM_MAQUINAS];
unsigned long instanteMudanca[NUM_MAQUINAS];

unsigned long instanteInicioCiclo[NUM_MAQUINAS];
uint32_t inicioEpochCiclo[NUM_MAQUINAS];
unsigned long contadorCiclos[NUM_MAQUINAS];
unsigned long totalSegundosLigado[NUM_MAQUINAS];
unsigned long ultimoSalvamentoMs[NUM_MAQUINAS];
bool modoSimulacao[NUM_MAQUINAS];
unsigned long instanteEstado[NUM_MAQUINAS]; // quando a maquina entrou no estado atual (ligada ou desligada)
unsigned long ultimoEstadoMs = 0;

bool rtcPresente = false;
bool horaValida = false;
uint32_t epochBase = 0;        // hora (RTC) lida em millisBase
unsigned long millisBase = 0;
unsigned long ultimoResyncRtcMs = 0;
// Diagnostico do relogio (mostrado na pagina http://192.168.4.1)
bool rtcSemHoraNoBoot = false;   // no boot o RTC estava sem hora valida (OSF) - bateria fraca/ausente
uint32_t horaAcertadaEm = 0;     // hora (epoch) do ultimo acerto desde o boot, 0 = nao acertado
const char *origemAcerto = "";   // quem acertou: PC pelo Wi-Fi ou Serial
bool correcaoConhecida = false;  // a hora ja era valida antes do ultimo acerto (entao a correcao abaixo vale)
long ultimaCorrecaoS = 0;        // quanto o ultimo acerto mudou a hora (s, + = estava atrasado)
uint32_t falhasLeituraRtc = 0;   // releituras periodicas do RTC que falharam desde o boot

bool armazenamentoOk = false;

// ---------------------------------------------------------------------
// ACESSO REMOTO (firmware 3.0): alem de responder ao notebook na rede local
// (que continua sendo o fornecedor principal), o ESP32 ENVIA os ciclos e o
// estado das maquinas para a VPS (NUVEM_URL, por HTTPS) - quem esta fora da
// rede da empresa ve o painel por la, mesmo com o notebook desligado.
//  - Uma tarefa propria (tarefaNuvem, nucleo 0) faz o envio: uma VPS lenta
//    ou fora do ar nunca atrasa a leitura dos reles (loop, nucleo 1).
//  - nuvemAte (NVS) = ultimo ciclo que a VPS confirmou. Os ciclos so saem da
//    memoria (apagarCiclosAte) depois que a VPS e o notebook os tiverem.
//  - A VPS e conferida pelo certificado raiz (certificados.h) - nunca em
//    modo inseguro. NUVEM_URL vazia (.env) = envio desligado.
// ---------------------------------------------------------------------
const unsigned long NUVEM_INTERVALO_MS = 10000UL;   // com tudo enviado, confere a cada 10 s
const unsigned long NUVEM_ESPERA_MAX_MS = 60000UL;  // falhando: espera dobra ate 1 min (3.1: era 5 min)
const uint32_t NUVEM_MAX_CICLOS_POR_ENVIO = 50;
volatile uint32_t nuvemAte = 0;              // ultimo id confirmado pela VPS
volatile unsigned long nuvemUltimoOkMs = 0;  // ultimo envio confirmado (0 = nenhum desde o boot)
volatile uint32_t nuvemEnviosOk = 0;
char nuvemErro[128] = "";                    // ultimo erro ("" = ultimo envio deu certo)
// 3.1: a conexao HTTPS com a VPS fica aberta entre os envios (keep-alive) - sem
// um handshake TLS novo a cada 10 s (era o ponto das falhas intermitentes)
NetworkClientSecure *nuvemCliente = nullptr;
HTTPClient *nuvemHttp = nullptr;
volatile uint32_t nuvemConexoesNovas = 0; // handshakes TLS feitos (1 por reconexao)
volatile uint32_t nuvemFalhas = 0;        // envios que falharam desde o boot
TaskHandle_t tarefaNuvemHandle = nullptr;

bool nuvemAtiva() { return NUVEM_URL[0] != '\0'; }
uint32_t ciclosSemHoraNesteBoot = 0; // gravados com hora relativa, ainda nao corrigidos
uint32_t ultimoIdCiclo = 0;
uint32_t apagadoAte = 0; // ciclos com id <= apagadoAte ja foram extraidos e "apagados"
String idDispositivo;

struct ConfigWifi {
  uint8_t modo;
  String ssid;
  String senha;
  String ip;      // vazio = automatico (DHCP)
  String gateway; // vazio = x.x.x.1 do ip fixo
};
ConfigWifi cfgWifi;
bool apAtivo = false;
bool staAtivo = false;
unsigned long semEmpresaDesdeMs = 0;
unsigned long reiniciarEmMs = 0; // != 0: reinicia nesse instante (depois de salvar a config)

bool wifiConectado = false;
uint8_t clientesConectados = 0; // modo ponto de acesso: quantos notebooks estao na rede do ESP32
bool mdnsIniciado = false;
unsigned long ultimaTentativaWifiMs = 0;
// Diagnostico da rede / sistema (pagina http://192.168.4.1)
uint32_t quedasWifi = 0;             // vezes que a rede da empresa caiu desde o boot
unsigned long conectadoDesdeMs = 0;  // quando entrou na rede da empresa (vale com wifiConectado)
unsigned long ultimaQuedaMs = 0;     // 0 = nenhuma queda desde o boot
unsigned long ultimoContatoPcMs = 0; // ultimo acesso do PC (/info, /ciclos...), 0 = nenhum desde o boot
String ipUltimoContatoPc;
uint32_t contagemBoots = 0;

// ---------------------------------------------------------------------
// AUTODIAGNOSTICO E AUTOCORRECAO (v2) - menos intervencao manual:
//  - RTC redetectado sozinho (sem apertar EN) e barramento I2C destravado
//  - varredura I2C + teste de pull-up para diagnostico pelo painel
//  - hora pela internet (NTP) quando nao ha RTC nem PC
//  - Wi-Fi: motivo de cada queda, reinicio do radio se nao reconecta e
//    reconexao forcada quando o PC para de alcancar o ESP32 (repetidor)
//  - reinicio seguro se a memoria livre ficar perigosamente baixa
//  - registro dos ultimos eventos na flash (sobrevive a reinicios)
// ---------------------------------------------------------------------
const char *FIRMWARE_VERSAO = "3.1";
const unsigned long INTERVALO_REDETECTAR_RTC_MS = 30000UL;   // testa o RTC a cada 30 s
const uint8_t FALHAS_PARA_RTC_AUSENTE = 3;                   // 3 falhas seguidas = RTC sumiu
const unsigned long SEM_PC_PARA_RECONECTAR_MS = 15UL * 60UL * 1000UL; // 15 min sem o PC alcancar
const unsigned long MAX_ESPERA_RECONEXAO_MS = 2UL * 3600UL * 1000UL;  // intervalo maximo entre reconexoes forcadas
const uint8_t TENTATIVAS_ATE_REINICIAR_RADIO = 5;            // 5 tentativas (~5 min) -> reinicia o radio Wi-Fi
const unsigned long INTERVALO_NTP_MS = 60000UL;
const long FUSO_HORARIO_S = -3L * 3600L;                     // horario de Brasilia (sem horario de verao)
const uint32_t HEAP_MINIMO_SEGURO = 16000;                   // abaixo disso reinicia de forma segura
const char *ARQUIVO_EVENTOS = "/eventos.bin";

unsigned long ultimaRedeteccaoRtcMs = 0;
uint8_t falhasSeguidasRtc = 0;
uint32_t rtcEncontradoVezes = 0;  // redeteccoes bem-sucedidas desde o boot
uint32_t rtcPerdidoVezes = 0;
String enderecosI2C;              // ultima varredura: "0x57,0x68"
bool pullupSda = false, pullupScl = false; // resistores de pull-up detectados nas linhas I2C
unsigned long ultimaVarreduraMs = 0;

uint8_t motivoUltimaQueda = 0;          // codigo do motivo (evento STA_DISCONNECTED)
volatile uint8_t motivoQuedaPendente = 0; // escrito pelo evento do Wi-Fi (outra tarefa)
unsigned long duracaoUltimaQuedaMs = 0; // quanto tempo durou a ultima queda (ja resolvida)
uint8_t tentativasSemSucesso = 0;
uint32_t radioReiniciado = 0;
uint32_t reconexoesForcadas = 0;
unsigned long ultimaReconexaoForcadaMs = 0;
unsigned long esperaReconexaoMs = SEM_PC_PARA_RECONECTAR_MS;
bool reconexaoPreventiva = false; // a queda/volta a seguir foi provocada por nos: nao vira evento nem conta como queda

bool ntpIniciado = false;
unsigned long ultimaTentativaNtpMs = 0;
unsigned long ultimaVerificacaoHeapMs = 0;

struct Evento {
  uint32_t epoch;     // hora local (0 = sem hora)
  uint32_t ligadoS;   // segundos desde que o ESP32 ligou
  uint32_t boot;      // numero do boot
  char texto[84];
};
const uint8_t MAX_EVENTOS = 30;
Evento eventos[MAX_EVENTOS];
uint8_t qtdEventos = 0;
uint8_t proximoEvento = 0;

bool lerContatoLigado(uint8_t idMaquina) {
  return digitalRead(PINOS_RELE[idMaquina]) == LOW;
}

void atualizarLed() {
  bool algumaLigada = false;
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    if (estadoAtual[m] == EstadoEquipamento::LIGADO) {
      algumaLigada = true;
      break;
    }
  }
  digitalWrite(PINO_LED_STATUS, algumaLigada ? HIGH : LOW);
}

// ---------------------------------------------------------------------
// Relogio (RTC DS3231M). "epoch" aqui = segundos desde 1970-01-01 00:00
// na hora LOCAL (sem fuso) - e o mesmo valor que o PC envia em /hora.
// ---------------------------------------------------------------------
uint8_t bcdParaDec(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }
uint8_t decParaBcd(uint8_t v) { return ((v / 10) << 4) | (v % 10); }

// Conversao data <-> dias desde 1970 (algoritmos days_from_civil /
// civil_from_days de Howard Hinnant), validos para qualquer ano >= 1970.
uint32_t paraEpoch(const DataHora &d) {
  int32_t ano = d.ano - (d.mes <= 2 ? 1 : 0);
  int32_t era = ano / 400;
  uint32_t anoDaEra = ano - era * 400;
  uint32_t mesAjustado = d.mes > 2 ? d.mes - 3 : d.mes + 9;
  uint32_t diaDoAno = (153 * mesAjustado + 2) / 5 + d.dia - 1;
  uint32_t diaDaEra = anoDaEra * 365 + anoDaEra / 4 - anoDaEra / 100 + diaDoAno;
  uint32_t dias = era * 146097 + diaDaEra - 719468;
  return dias * 86400UL + d.hora * 3600UL + d.minuto * 60UL + d.segundo;
}

DataHora deEpoch(uint32_t t) {
  uint32_t z = t / 86400 + 719468;
  uint32_t segDoDia = t % 86400;
  uint32_t era = z / 146097;
  uint32_t diaDaEra = z - era * 146097;
  uint32_t anoDaEra = (diaDaEra - diaDaEra / 1460 + diaDaEra / 36524 - diaDaEra / 146096) / 365;
  uint32_t diaDoAno = diaDaEra - (365 * anoDaEra + anoDaEra / 4 - anoDaEra / 100);
  uint32_t mp = (5 * diaDoAno + 2) / 153;
  DataHora d;
  d.dia = diaDoAno - (153 * mp + 2) / 5 + 1;
  d.mes = mp < 10 ? mp + 3 : mp - 9;
  d.ano = anoDaEra + era * 400 + (d.mes <= 2 ? 1 : 0);
  d.hora = segDoDia / 3600;
  d.minuto = (segDoDia / 60) % 60;
  d.segundo = segDoDia % 60;
  return d;
}

// dest precisa de 20 bytes. Epoch 0 = hora desconhecida -> "?".
void formatarEpoch(uint32_t t, char *dest) {
  if (t == 0) {
    strcpy(dest, "?");
    return;
  }
  DataHora d = deEpoch(t);
  snprintf(dest, 20, "%04u-%02u-%02uT%02u:%02u:%02u", (unsigned)d.ano, (unsigned)d.mes, (unsigned)d.dia,
           (unsigned)d.hora, (unsigned)d.minuto, (unsigned)d.segundo);
}

int lerRegistroRtc(uint8_t reg) {
  Wire.beginTransmission(ENDERECO_RTC);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return -1;
  if (Wire.requestFrom(ENDERECO_RTC, (uint8_t)1) != 1) return -1;
  return Wire.read();
}

bool escreverRegistroRtc(uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(ENDERECO_RTC);
  Wire.write(reg);
  Wire.write(valor);
  return Wire.endTransmission() == 0;
}

bool lerRtc(uint32_t &epoch) {
  Wire.beginTransmission(ENDERECO_RTC);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(ENDERECO_RTC, (uint8_t)7) != 7) return false;
  uint8_t r[7];
  for (uint8_t i = 0; i < 7; i++) r[i] = Wire.read();

  DataHora d;
  d.segundo = bcdParaDec(r[0] & 0x7F);
  d.minuto = bcdParaDec(r[1] & 0x7F);
  d.hora = bcdParaDec(r[2] & 0x3F); // modo 24h (o firmware sempre grava assim)
  d.dia = bcdParaDec(r[4] & 0x3F);
  d.mes = bcdParaDec(r[5] & 0x1F);
  d.ano = 2000 + bcdParaDec(r[6]);
  if (d.mes < 1 || d.mes > 12 || d.dia < 1 || d.dia > 31 || d.hora > 23 || d.minuto > 59 || d.segundo > 59) return false;
  epoch = paraEpoch(d);
  return true;
}

bool gravarRtc(uint32_t epoch) {
  DataHora d = deEpoch(epoch);
  Wire.beginTransmission(ENDERECO_RTC);
  Wire.write(0x00);
  Wire.write(decParaBcd(d.segundo));
  Wire.write(decParaBcd(d.minuto));
  Wire.write(decParaBcd(d.hora)); // bit 6 = 0 -> modo 24h
  Wire.write(decParaBcd((epoch / 86400 + 4) % 7 + 1)); // dia da semana 1-7 (01/01/1970 foi quinta)
  Wire.write(decParaBcd(d.dia));
  Wire.write(decParaBcd(d.mes));
  Wire.write(decParaBcd(d.ano % 100));
  if (Wire.endTransmission() != 0) return false;

  // Limpa o OSF (bit 7 do registro de status): marca que a hora agora e confiavel.
  int status = lerRegistroRtc(0x0F);
  if (status >= 0) escreverRegistroRtc(0x0F, status & ~0x80);
  return true;
}

uint32_t agoraEpoch() {
  if (!horaValida) return 0;
  return epochBase + (millis() - millisBase) / 1000UL;
}

void sincronizarComRtc() {
  uint32_t epoch;
  if (rtcPresente && lerRtc(epoch)) {
    epochBase = epoch;
    millisBase = millis();
  } else if (rtcPresente) {
    falhasLeituraRtc++;
  }
  ultimoResyncRtcMs = millis();
}

// O relogio do sistema (time()) e o que o HTTPS usa para conferir a validade
// do certificado da VPS - fica sempre igual a hora do controlador (em UTC).
void ajustarRelogioSistema(uint32_t epochLocal) {
  struct timeval tv = {(time_t)((int64_t)epochLocal - FUSO_HORARIO_S), 0};
  settimeofday(&tv, nullptr);
}

void definirHora(uint32_t epoch, const char *origem) {
  correcaoConhecida = horaValida;
  if (horaValida) ultimaCorrecaoS = (long)epoch - (long)agoraEpoch();
  horaAcertadaEm = epoch;
  origemAcerto = origem;
  if (rtcPresente && !gravarRtc(epoch)) {
    Serial.println(F("# ERRO: falha ao gravar a hora no RTC"));
  }
  epochBase = epoch;
  millisBase = millis();
  ultimoResyncRtcMs = millis();
  horaValida = true;
  ajustarRelogioSistema(epoch);
  char texto[20];
  formatarEpoch(epoch, texto);
  Serial.print(F("# Relogio acertado: "));
  Serial.println(texto);
  corrigirCiclosSemHora();
}

// ---- Registro de eventos (RAM + flash) ----
void salvarEventos() {
  if (!armazenamentoOk) return;
  File f = LittleFS.open(ARQUIVO_EVENTOS, "w");
  if (!f) return;
  f.write(&qtdEventos, 1);
  f.write(&proximoEvento, 1);
  f.write((const uint8_t *)eventos, sizeof(eventos));
  f.close();
}

void carregarEventos() {
  File f = LittleFS.open(ARQUIVO_EVENTOS, "r");
  if (!f) return;
  if (f.size() == 2 + sizeof(eventos)) {
    f.read(&qtdEventos, 1);
    f.read(&proximoEvento, 1);
    f.read((uint8_t *)eventos, sizeof(eventos));
    if (qtdEventos > MAX_EVENTOS || proximoEvento >= MAX_EVENTOS) { qtdEventos = 0; proximoEvento = 0; }
  }
  f.close();
}

void registrarEvento(const String &texto) {
  Evento &e = eventos[proximoEvento];
  e.epoch = agoraEpoch();
  e.ligadoS = (uint32_t)(esp_timer_get_time() / 1000000LL);
  e.boot = contagemBoots;
  strncpy(e.texto, texto.c_str(), sizeof(e.texto) - 1);
  e.texto[sizeof(e.texto) - 1] = 0;
  proximoEvento = (proximoEvento + 1) % MAX_EVENTOS;
  if (qtdEventos < MAX_EVENTOS) qtdEventos++;
  Serial.print(F("# EVENTO: "));
  Serial.println(texto);
  salvarEventos();
}

// ---- Barramento I2C ----
// Destrava o barramento (um escravo pode ficar segurando SDA em LOW depois
// de um reset no meio de uma leitura): ate 9 pulsos de clock + STOP. Antes,
// mede se ha resistores de pull-up nas linhas (com pull-down interno: com
// pull-up externo a linha le HIGH; sem modulo/sem pull-up le LOW).
void recuperarBarramentoI2C() {
  Wire.end();
  pinMode(PINO_SDA, INPUT_PULLDOWN);
  pinMode(PINO_SCL, INPUT_PULLDOWN);
  delayMicroseconds(50);
  pullupSda = digitalRead(PINO_SDA) == HIGH;
  pullupScl = digitalRead(PINO_SCL) == HIGH;
  pinMode(PINO_SDA, INPUT_PULLUP);
  pinMode(PINO_SCL, OUTPUT_OPEN_DRAIN);
  digitalWrite(PINO_SCL, HIGH);
  for (uint8_t i = 0; i < 9 && digitalRead(PINO_SDA) == LOW; i++) {
    digitalWrite(PINO_SCL, LOW);
    delayMicroseconds(6);
    digitalWrite(PINO_SCL, HIGH);
    delayMicroseconds(6);
  }
  pinMode(PINO_SDA, OUTPUT_OPEN_DRAIN); // condicao de STOP
  digitalWrite(PINO_SDA, LOW);
  delayMicroseconds(6);
  digitalWrite(PINO_SCL, HIGH);
  delayMicroseconds(6);
  digitalWrite(PINO_SDA, HIGH);
  delayMicroseconds(6);
  Wire.begin(PINO_SDA, PINO_SCL);
  Wire.setTimeOut(50);
}

// Lista os enderecos que respondem no I2C (ex.: "0x57,0x68").
void varrerI2C() {
  String r;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      char t[6];
      snprintf(t, sizeof(t), "0x%02X", a);
      if (r.length()) r += ',';
      r += t;
    }
  }
  enderecosI2C = r;
  ultimaVarreduraMs = millis();
}

// Procura o RTC de novo. Encontrou: passa a usa-lo sem reiniciar, corrige
// o EOSC (oscilador desligando na bateria) e sincroniza a hora nos dois
// sentidos (ESP32 com hora valida -> grava no RTC; senao, le do RTC).
bool redetectarRtc(bool manual) {
  recuperarBarramentoI2C();
  varrerI2C();
  int status = lerRegistroRtc(0x0F);
  if (status < 0) {
    if (manual) {
      registrarEvento(String(F("Redeteccao do RTC: nao respondeu (I2C: ")) + (enderecosI2C.length() ? enderecosI2C : String(F("nada"))) +
                      F(", pull-up SDA/SCL: ") + (pullupSda ? F("sim") : F("nao")) + "/" + (pullupScl ? F("sim") : F("nao")) + ")");
    }
    return false;
  }
  rtcPresente = true;
  falhasSeguidasRtc = 0;
  rtcEncontradoVezes++;
  int controle = lerRegistroRtc(0x0E);
  if (controle >= 0 && (controle & 0x80)) escreverRegistroRtc(0x0E, controle & ~0x80); // EOSC: mantem o oscilador na bateria
  uint32_t epoch;
  bool rtcValido = !(status & 0x80) && lerRtc(epoch) && epoch >= paraEpoch({2024, 1, 1, 0, 0, 0});
  if (horaValida) {
    gravarRtc(agoraEpoch());
    registrarEvento(F("RTC encontrado - hora atual gravada nele"));
  } else if (rtcValido) {
    epochBase = epoch;
    millisBase = millis();
    ultimoResyncRtcMs = millis();
    horaValida = true;
    ajustarRelogioSistema(epoch);
    horaAcertadaEm = epoch;
    origemAcerto = "RTC (redetectado)";
    correcaoConhecida = false;
    registrarEvento(F("RTC encontrado - hora lida do RTC"));
    corrigirCiclosSemHora();
  } else {
    rtcSemHoraNoBoot = true;
    registrarEvento(F("RTC encontrado, mas sem hora valida (bateria?) - aguardando o PC ou a internet"));
  }
  return true;
}

// Chamado no loop: confere o RTC periodicamente.
void verificarRtc() {
  if (millis() - ultimaRedeteccaoRtcMs < INTERVALO_REDETECTAR_RTC_MS) return;
  ultimaRedeteccaoRtcMs = millis();
  if (rtcPresente) {
    if (lerRegistroRtc(0x0F) >= 0) {
      falhasSeguidasRtc = 0;
      return;
    }
    if (++falhasSeguidasRtc >= FALHAS_PARA_RTC_AUSENTE) {
      rtcPresente = false;
      rtcPerdidoVezes++;
      registrarEvento(F("RTC parou de responder - usando o relogio interno (tentando redetectar)"));
      recuperarBarramentoI2C();
    }
    return;
  }
  redetectarRtc(false);
}

// Hora pela internet quando nao ha hora valida (sem RTC e sem o PC).
void verificarNtp() {
  if (horaValida || !wifiConectado || millis() - ultimaTentativaNtpMs < INTERVALO_NTP_MS) return;
  ultimaTentativaNtpMs = millis();
  if (!ntpIniciado) {
    configTime(0, 0, "a.st1.ntp.br", "pool.ntp.org");
    ntpIniciado = true;
    return; // a resposta chega em segundo plano
  }
  time_t utc = time(nullptr);
  if (utc > 1704067200) { // depois de 01/01/2024
    definirHora((uint32_t)(utc + FUSO_HORARIO_S), "internet (NTP)");
    registrarEvento(F("Hora acertada pela internet (NTP)"));
  }
}

// Memoria livre perigosamente baixa = sinal de vazamento: reinicia de forma
// segura (o estado das maquinas e salvo antes) em vez de travar.
void verificarMemoria() {
  if (millis() - ultimaVerificacaoHeapMs < 10000UL) return;
  ultimaVerificacaoHeapMs = millis();
  if (ESP.getFreeHeap() < HEAP_MINIMO_SEGURO) {
    registrarEvento(String(F("Memoria livre baixa (")) + ESP.getFreeHeap() + F(" bytes) - reiniciando de forma segura"));
    reiniciarComSeguranca();
  }
}

const char *textoMotivoQueda(uint8_t r) {
  switch (r) {
    case 0: return "-";
    case 2: return "autenticacao expirou";
    case 3: return "roteador desconectou o controlador";
    case 4: case 5: return "roteador encerrou por inatividade/lotacao";
    case 8: return "Controlador saiu (reconexao)";
    case 15: case 204: return "senha recusada (handshake)";
    case 200: return "sinal perdido (beacon timeout)";
    case 201: return "rede nao encontrada";
    case 202: return "falha de autenticacao (senha?)";
    case 203: return "falha de associacao";
    case 205: return "conexao falhou";
    default: return "outro motivo";
  }
}

// Reinicia so o radio Wi-Fi (sem reiniciar o ESP32) - resolve a maioria
// dos "travamentos" de conexao com roteador/repetidor.
void reiniciarRadioWifi(const __FlashStringHelper *motivo) {
  radioReiniciado++;
  registrarEvento(String(F("Reiniciando o radio Wi-Fi: ")) + motivo);
  bool comPropria = apAtivo;
  WiFi.disconnect(true, false);
  WiFi.mode(WIFI_OFF);
  delay(200);
  WiFi.mode(comPropria ? WIFI_AP_STA : WIFI_STA);
  WiFi.setSleep(false);
  if (comPropria) { apAtivo = false; ligarRedePropria(); }
  WiFi.setAutoReconnect(!comPropria);
  if (cfgWifi.ip.length()) {
    IPAddress ip, gateway;
    if (ip.fromString(cfgWifi.ip)) {
      if (!cfgWifi.gateway.length() || !gateway.fromString(cfgWifi.gateway)) gateway = IPAddress(ip[0], ip[1], ip[2], 1);
      WiFi.config(ip, gateway, IPAddress(255, 255, 255, 0), gateway);
    }
  }
  conectarRedeEmpresa();
  tentativasSemSucesso = 0;
}

void iniciarRelogio() {
  Wire.begin(PINO_SDA, PINO_SCL);
  Wire.setTimeOut(50);
  int status = lerRegistroRtc(0x0F);
  rtcPresente = status >= 0;
  if (!rtcPresente) {
    Serial.println(F("# AVISO: RTC DS3231M nao encontrado (SDA=21, SCL=22) - ciclos ficam sem data/hora ate o PC acertar"));
    recuperarBarramentoI2C(); // destrava o barramento e tenta de novo
    varrerI2C();
    if (lerRegistroRtc(0x0F) >= 0) { redetectarRtc(false); }
    return;
  }
  varrerI2C();
  int controle = lerRegistroRtc(0x0E);
  if (controle >= 0 && (controle & 0x80)) escreverRegistroRtc(0x0E, controle & ~0x80); // EOSC: mantem o oscilador na bateria
  uint32_t epoch;
  bool oscilador_parou = status & 0x80; // OSF: o RTC ficou sem energia (bateria fraca/ausente) ou nunca foi acertado
  if (oscilador_parou || !lerRtc(epoch) || epoch < paraEpoch({2024, 1, 1, 0, 0, 0})) {
    Serial.println(F("# AVISO: RTC sem hora valida (bateria?) - acerte com T<AAAA-MM-DD HH:MM:SS> ou deixe o PC acertar pelo Wi-Fi"));
    rtcSemHoraNoBoot = true;
    return;
  }
  epochBase = epoch;
  millisBase = millis();
  ultimoResyncRtcMs = millis();
  horaValida = true;
  ajustarRelogioSistema(epoch);
  char texto[20];
  formatarEpoch(epoch, texto);
  Serial.print(F("# RTC: "));
  Serial.println(texto);
}

// Leitura "ao vivo" do RTC para a pagina de situacao (struct DiagnosticoRtc).
DiagnosticoRtc diagnosticarRtc() {
  DiagnosticoRtc d = {};
  int status = lerRegistroRtc(0x0F);
  d.responde = status >= 0;
  if (!d.responde) return d;
  d.osf = status & 0x80;
  int controle = lerRegistroRtc(0x0E);
  d.eosc = controle >= 0 && (controle & 0x80);
  d.leuHora = lerRtc(d.epoch);
  int msb = lerRegistroRtc(0x11);
  int lsb = lerRegistroRtc(0x12);
  if (msb >= 0 && lsb >= 0) {
    d.temTemperatura = true;
    d.temperatura = (int8_t)msb + (lsb >> 6) * 0.25f;
  }
  return d;
}

// ---------------------------------------------------------------------
// Historico de ciclos na flash (LittleFS, buffer circular)
// ---------------------------------------------------------------------
uint32_t primeiroIdDisponivel() {
  uint32_t primeiroNoBuffer = ultimoIdCiclo <= CAPACIDADE_REGISTROS ? 1 : ultimoIdCiclo - CAPACIDADE_REGISTROS + 1;
  return max(primeiroNoBuffer, apagadoAte + 1);
}

// "Zera" o armazenamento ate o id informado. Os ids NUNCA voltam para 1
// (assim o PC nunca confunde um ciclo novo com um antigo): so se marca ate
// onde ja foi apagado, e os slots desses ciclos passam a ser reaproveitados.
void apagarCiclosAte(uint32_t id) {
  if (id > ultimoIdCiclo) id = ultimoIdCiclo;
  // Acesso remoto: o que a VPS ainda nao recebeu continua guardado
  if (nuvemAtiva() && id > nuvemAte) id = nuvemAte;
  if (id <= apagadoAte) return;
  apagadoAte = id;
  prefs.putUInt("apagado", apagadoAte);
  Serial.print(F("# Armazenamento limpo ate o ciclo id "));
  Serial.print(apagadoAte);
  Serial.print(F(" - pendentes: "));
  Serial.println(ultimoIdCiclo - apagadoAte);
}

size_t posicaoDoId(uint32_t id) {
  return ((id - 1) % CAPACIDADE_REGISTROS) * sizeof(RegistroCiclo);
}

bool gravarRegistroNaFlash(const RegistroCiclo &r) {
  if (!armazenamentoOk) return false;
  File f = LittleFS.exists(ARQUIVO_CICLOS) ? LittleFS.open(ARQUIVO_CICLOS, "r+") : LittleFS.open(ARQUIVO_CICLOS, "w+");
  if (!f) return false;

  size_t pos = posicaoDoId(r.id);
  size_t tamanho = f.size() - (f.size() % sizeof(RegistroCiclo));
  if (tamanho < pos) {
    // Arquivo menor que o esperado (ex.: apagado, mas o contador na NVS
    // ficou): completa com slots vazios ate a posicao deste id.
    RegistroCiclo vazio = {};
    f.seek(tamanho);
    while (tamanho < pos && f.write((const uint8_t *)&vazio, sizeof(vazio)) == sizeof(vazio)) {
      tamanho += sizeof(vazio);
    }
  }
  bool ok = f.seek(pos) && f.write((const uint8_t *)&r, sizeof(r)) == sizeof(r);
  f.close();
  return ok;
}

bool lerRegistroDaFlash(File &f, uint32_t id, RegistroCiclo &r) {
  if (!f.seek(posicaoDoId(id))) return false;
  if (f.read((uint8_t *)&r, sizeof(r)) != sizeof(r)) return false;
  return r.id == id; // slot sobrescrito ou vazio
}

// Da data real aos ciclos gravados sem hora NESTE boot (ver
// FLAG_HORA_RELATIVA): fim = agora - (tempo ligado agora - tempo ligado no
// fim do ciclo). So olha os ciclos ainda nao extraidos pelo PC.
void corrigirCiclosSemHora() {
  if (ciclosSemHoraNesteBoot == 0 || !horaValida || !armazenamentoOk) return;
  File f = LittleFS.open(ARQUIVO_CICLOS, "r+");
  if (!f) return;
  uint32_t agora = agoraEpoch();
  uint32_t ligadoAgora = (uint32_t)segundosLigadoEsp();
  uint16_t boot = (uint16_t)(contagemBoots & 0xFFFF);
  uint32_t corrigidos = 0;
  for (uint32_t id = primeiroIdDisponivel(); id <= ultimoIdCiclo && id != 0; id++) {
    RegistroCiclo r;
    if (!lerRegistroDaFlash(f, id, r)) continue;
    if (!(r.flags & FLAG_HORA_RELATIVA) || r.reservado != boot || r.inicioEpoch > ligadoAgora) continue;
    uint32_t fim = agora - (ligadoAgora - r.inicioEpoch);
    r.fimEpoch = fim;
    r.inicioEpoch = fim - r.duracaoDecimos / 10UL;
    r.flags &= ~(FLAG_HORA_RELATIVA | FLAG_SEM_HORA);
    r.reservado = 0;
    if (f.seek(posicaoDoId(id)) && f.write((const uint8_t *)&r, sizeof(r)) == sizeof(r)) corrigidos++;
  }
  f.close();
  ciclosSemHoraNesteBoot = 0;
  if (corrigidos) {
    Serial.print(F("# Hora real calculada para "));
    Serial.print(corrigidos);
    Serial.println(F(" ciclo(s) gravados sem hora"));
    registrarEvento(String(corrigidos) + F(" ciclo(s) sem hora receberam a hora real"));
  }
}

void iniciarArmazenamento() {
  armazenamentoOk = LittleFS.begin(true); // formata na primeira vez (particao vazia)
  if (!armazenamentoOk) {
    Serial.println(F("# ERRO: LittleFS nao montou - verifique o esquema de particao (precisa ter SPIFFS/LittleFS)"));
  }

  uint32_t serie = prefs.getUInt("serie", 0);
  if (serie == 0) {
    serie = (uint32_t)esp_random() | 1;
    prefs.putUInt("serie", serie);
  }
  ultimoIdCiclo = prefs.getUInt("seq", 0);
  apagadoAte = prefs.getUInt("apagado", 0);
  nuvemAte = prefs.getUInt("nuvem", 0);
  if (nuvemAte > ultimoIdCiclo) nuvemAte = ultimoIdCiclo;
  // Firmware 2.x nao enviava para a VPS: na primeira vez com o 3.0, o que ja
  // foi liberado da memoria nao existe mais - comeca dali.
  if (nuvemAte < apagadoAte) nuvemAte = apagadoAte;

  // Identifica este ESP32 + esta "vida" da flash: se a NVS for apagada, a
  // serie muda e o PC recomeca a contagem de ids do zero para ele.
  // MAC gravado de fabrica no chip (eFuse) - estavel e valido mesmo antes
  // do Wi-Fi iniciar (WiFi.macAddress() aqui devolvia um valor que mudava a
  // cada boot, e o PC tratava o controlador como um aparelho novo).
  uint8_t mac[6];
  uint64_t efuse = ESP.getEfuseMac();
  for (uint8_t i = 0; i < 6; i++) mac[i] = (efuse >> (8 * i)) & 0xFF;
  char texto[24];
  snprintf(texto, sizeof(texto), "%02X%02X%02X%02X%02X%02X-%08lX", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5],
           (unsigned long)serie);
  idDispositivo = texto;
}

void montarObs(uint8_t flags, char *dest, size_t tamanho) {
  dest[0] = '\0';
  const char *nomes[] = {"CICLO_CURTO", "SIMULADO", "CICLO_RECUPERADO_APOS_QUEDA", "SEM_HORA"};
  const uint8_t bits[] = {FLAG_CURTO, FLAG_SIMULADO, FLAG_RECUPERADO, FLAG_SEM_HORA};
  for (uint8_t i = 0; i < 4; i++) {
    if (!(flags & bits[i])) continue;
    if (dest[0]) strlcat(dest, "+", tamanho);
    strlcat(dest, nomes[i], tamanho);
  }
}

// ---------------------------------------------------------------------
// Estado por maquina (NVS)
// ---------------------------------------------------------------------
void chaveMaquina(uint8_t idMaquina, char *chave) {
  chave[0] = 'm';
  chave[1] = '1' + idMaquina;
  chave[2] = '\0';
}

void salvarEstado(uint8_t idMaquina, bool ligado, unsigned long cicloAtualSeg) {
  EstadoPersistido registro;
  registro.contadorCiclos = contadorCiclos[idMaquina];
  registro.totalSegundosLigado = totalSegundosLigado[idMaquina];
  registro.cicloAtualSegundos = cicloAtualSeg;
  registro.estadoLigado = ligado ? 1 : 0;
  registro.inicioEpoch = ligado ? inicioEpochCiclo[idMaquina] : 0;

  char chave[3];
  chaveMaquina(idMaquina, chave);
  size_t gravados = prefs.putBytes(chave, &registro, sizeof(registro));
  if (gravados != sizeof(registro)) {
    Serial.print(F("# [M"));
    Serial.print(idMaquina + 1);
    Serial.println(F("] ERRO: falha ao gravar estado na flash (NVS)"));
  }
}

bool carregarEstadoPersistido(uint8_t idMaquina, EstadoPersistido &destino) {
  char chave[3];
  chaveMaquina(idMaquina, chave);
  destino = {};
  size_t tamanho = prefs.getBytesLength(chave);
  if (tamanho != sizeof(EstadoPersistido) && tamanho != TAMANHO_ESTADO_V1) return false;
  return prefs.getBytes(chave, &destino, tamanho) == tamanho;
}

void emitirEstados() {
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    Serial.print(F("# ESTADO,"));
    Serial.print(m + 1);
    Serial.print(',');
    Serial.print(estadoAtual[m] == EstadoEquipamento::LIGADO ? 1 : 0);
    Serial.print(',');
    Serial.println((millis() - instanteEstado[m]) / 1000UL);
  }
}

// Fecha um ciclo: conta, grava no historico da flash (com id sequencial)
// e imprime na Serial.
void registrarCiclo(uint8_t idMaquina, unsigned long duracaoMs, uint32_t inicioEpoch, uint32_t fimEpoch, uint8_t flags) {
  contadorCiclos[idMaquina]++;
  totalSegundosLigado[idMaquina] += duracaoMs / 1000UL;

  // Ciclo recuperado nao e marcado curto: a duracao dele e so a do ultimo checkpoint.
  if (!(flags & FLAG_RECUPERADO) && duracaoMs < DURACAO_MINIMA_VALIDA_S * 1000) flags |= FLAG_CURTO;
  // Hora acertada no meio do ciclo: o inicio sai da duracao medida.
  if (inicioEpoch == 0 && fimEpoch != 0) inicioEpoch = fimEpoch - duracaoMs / 1000UL;
  if (fimEpoch == 0) flags |= FLAG_SEM_HORA;

  RegistroCiclo r = {};
  r.id = ultimoIdCiclo + 1;
  r.ciclo = contadorCiclos[idMaquina];
  r.inicioEpoch = inicioEpoch;
  r.fimEpoch = fimEpoch;
  r.duracaoDecimos = duracaoMs / 100UL;
  r.maquina = idMaquina + 1;
  r.flags = flags;
  // Sem hora agora, mas o ciclo acabou de terminar neste boot: guarda o
  // tempo ligado para calcular a data quando a hora for acertada. (Ciclo
  // recuperado apos queda terminou ANTES deste boot - nao da para calcular.)
  bool horaRelativa = fimEpoch == 0 && !(flags & FLAG_RECUPERADO);
  if (horaRelativa) {
    r.flags |= FLAG_HORA_RELATIVA;
    r.inicioEpoch = (uint32_t)segundosLigadoEsp();
    r.reservado = (uint16_t)(contagemBoots & 0xFFFF);
  }

  if (gravarRegistroNaFlash(r)) {
    ultimoIdCiclo = r.id;
    prefs.putUInt("seq", ultimoIdCiclo);
    if (horaRelativa) ciclosSemHoraNesteBoot++;
  } else {
    Serial.print(F("# [M"));
    Serial.print(idMaquina + 1);
    Serial.println(F("] ERRO: falha ao gravar o ciclo no historico (LittleFS)"));
  }

  char inicio[20], fim[20], obs[64];
  formatarEpoch(horaRelativa ? 0 : r.inicioEpoch, inicio);
  formatarEpoch(r.fimEpoch, fim);
  montarObs(r.flags, obs, sizeof(obs));
  Serial.print(idMaquina + 1);
  Serial.print(',');
  Serial.print(r.ciclo);
  Serial.print(',');
  Serial.print(inicio);
  Serial.print(',');
  Serial.print(fim);
  Serial.print(',');
  Serial.print(duracaoMs / 1000.0, 1);
  Serial.print(',');
  Serial.println(obs);
}

// Ponto unico de transicao de estado - usado tanto pela leitura real do
// contato quanto pelos comandos manuais via Serial, para nunca duplicar a
// logica.
void mudarEstadoEquipamento(uint8_t idMaquina, bool ligado, bool simulado) {
  if (ligado) {
    estadoAtual[idMaquina] = EstadoEquipamento::LIGADO;
    instanteInicioCiclo[idMaquina] = millis();
    inicioEpochCiclo[idMaquina] = agoraEpoch();
    instanteEstado[idMaquina] = millis();
    Serial.print(F("# [M"));
    Serial.print(idMaquina + 1);
    Serial.println(simulado ? F("] [SIM] LIGOU") : F("] LIGOU"));
    salvarEstado(idMaquina, true, 0);
  } else {
    estadoAtual[idMaquina] = EstadoEquipamento::DESLIGADO;
    instanteEstado[idMaquina] = millis();
    Serial.print(F("# [M"));
    Serial.print(idMaquina + 1);
    Serial.println(simulado ? F("] [SIM] DESLIGOU") : F("] DESLIGOU"));
    registrarCiclo(idMaquina, millis() - instanteInicioCiclo[idMaquina], inicioEpochCiclo[idMaquina], agoraEpoch(),
                   simulado ? FLAG_SIMULADO : 0);
    salvarEstado(idMaquina, false, 0);
  }
  atualizarLed();
  ultimoSalvamentoMs[idMaquina] = millis();
}

// ---------------------------------------------------------------------
// Wi-Fi + servidor HTTP
// ---------------------------------------------------------------------
uint64_t segundosLigadoEsp() {
  return (uint64_t)(esp_timer_get_time() / 1000000LL); // 64 bits: nao "vira" em 49 dias como millis()
}

String formatarDuracao(uint64_t s) {
  char t[40];
  if (s < 60) snprintf(t, sizeof(t), "%u s", (unsigned)s);
  else if (s < 3600) snprintf(t, sizeof(t), "%u min %02u s", (unsigned)(s / 60), (unsigned)(s % 60));
  else if (s < 86400) snprintf(t, sizeof(t), "%u h %02u min", (unsigned)(s / 3600), (unsigned)((s % 3600) / 60));
  else snprintf(t, sizeof(t), "%u d %u h", (unsigned)(s / 86400), (unsigned)((s % 86400) / 3600));
  return String(t);
}

// Motivo do ultimo reinicio. Obs.: o botao EN/RESET da placa aparece como
// "ligado na energia" na maioria das placas ESP32.
const char *textoMotivoReset(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "ligado na energia (ou botão EN)";
    case ESP_RST_EXT: return "pino de reset externo";
    case ESP_RST_SW: return "reinício pelo firmware (nova configuração)";
    case ESP_RST_PANIC: return "erro no firmware (panic)";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "watchdog (travamento)";
    case ESP_RST_DEEPSLEEP: return "saiu do deep sleep";
    case ESP_RST_BROWNOUT: return "queda de tensão (brownout) - fonte fraca ou mau contato";
    default: return "desconhecido";
  }
}

bool resetPreocupante(esp_reset_reason_t r) {
  return r == ESP_RST_PANIC || r == ESP_RST_INT_WDT || r == ESP_RST_TASK_WDT || r == ESP_RST_WDT ||
         r == ESP_RST_BROWNOUT;
}

const char *textoStatusWifi(wl_status_t s) {
  switch (s) {
    case WL_CONNECTED: return "conectado";
    case WL_NO_SSID_AVAIL: return "rede não encontrada (repetidor desligado ou fora de alcance?)";
    case WL_CONNECT_FAILED: return "falha ao conectar (senha errada?)";
    case WL_CONNECTION_LOST: return "conexão perdida";
    default: return "tentando conectar...";
  }
}

const char *qualidadeSinal(int rssi) {
  if (rssi >= -60) return "ótimo";
  if (rssi >= -70) return "bom";
  if (rssi >= -80) return "fraco";
  return "muito fraco";
}

// Chamado nas rotas usadas pelo PC (monitor_wifi.py) - a pagina mostra ha
// quanto tempo o painel nao busca os dados (ajuda a achar falha na rede).
void registrarContatoPc() {
  ultimoContatoPcMs = millis();
  if (ultimoContatoPcMs == 0) ultimoContatoPcMs = 1;
  esperaReconexaoMs = SEM_PC_PARA_RECONECTAR_MS;
  ipUltimoContatoPc = servidor.client().remoteIP().toString();
}

void responderInfo() {
  registrarContatoPc();
  char hora[20];
  uint32_t agora = agoraEpoch();
  formatarEpoch(agora, hora);

  String j;
  j.reserve(1800);
  j += F("{\"dispositivo\":\"");
  j += idDispositivo;
  j += F("\",\"hora\":\"");
  j += hora;
  j += F("\",\"epoch\":");
  j += agora;
  j += F(",\"hora_valida\":");
  j += horaValida ? F("true") : F("false");
  j += F(",\"rtc\":");
  j += rtcPresente ? F("true") : F("false");
  j += F(",\"armazenamento\":");
  j += armazenamentoOk ? F("true") : F("false");
  j += F(",\"ultimo_id\":");
  j += ultimoIdCiclo;
  j += F(",\"primeiro_id\":");
  j += primeiroIdDisponivel();
  j += F(",\"apagado_ate\":");
  j += apagadoAte;
  j += F(",\"pendentes\":");
  j += ultimoIdCiclo - apagadoAte;
  j += F(",\"capacidade\":");
  j += CAPACIDADE_REGISTROS;
  j += F(",\"modo_wifi\":");
  j += cfgWifi.modo;
  j += F(",\"rede_empresa\":\"");
  j += escaparJson(cfgWifi.ssid);
  j += F("\",\"ip_empresa\":\"");
  if (wifiConectado) j += WiFi.localIP().toString();
  j += '"';
  // Diagnostico (campos extras - o PC ignora os que nao conhece)
  j += F(",\"rtc_sem_hora_no_boot\":");
  j += rtcSemHoraNoBoot ? F("true") : F("false");
  j += F(",\"rssi\":");
  j += wifiConectado ? WiFi.RSSI() : 0;
  j += F(",\"canal\":");
  j += WiFi.channel();
  j += F(",\"bssid\":\"");
  if (wifiConectado) j += WiFi.BSSIDstr();
  j += F("\",\"quedas_wifi\":");
  j += quedasWifi;
  j += F(",\"ligado_ha_s\":");
  j += (uint32_t)segundosLigadoEsp();
  j += F(",\"motivo_reset\":\"");
  j += textoMotivoReset(esp_reset_reason());
  j += F("\",\"boots\":");
  j += contagemBoots;
  j += F(",\"firmware\":\"" __DATE__ " " __TIME__ "\"");
  // ---- diagnostico v2 ----
  DiagnosticoRtc rtcAgora = diagnosticarRtc();
  j += F(",\"versao\":\"");
  j += FIRMWARE_VERSAO;
  j += F("\",\"rtc_responde\":");
  j += rtcAgora.responde ? F("true") : F("false");
  j += F(",\"rtc_osf\":");
  j += rtcAgora.osf ? F("true") : F("false");
  j += F(",\"rtc_eosc\":");
  j += rtcAgora.eosc ? F("true") : F("false");
  if (rtcAgora.temTemperatura) {
    j += F(",\"rtc_temperatura\":");
    j += String(rtcAgora.temperatura, 2);
  }
  if (rtcAgora.leuHora && horaValida) {
    j += F(",\"rtc_diferenca_s\":");
    j += (long)rtcAgora.epoch - (long)agora;
  }
  j += F(",\"rtc_encontrado_vezes\":");
  j += rtcEncontradoVezes;
  j += F(",\"rtc_perdido_vezes\":");
  j += rtcPerdidoVezes;
  j += F(",\"rtc_falhas_leitura\":");
  j += falhasLeituraRtc;
  j += F(",\"i2c\":\"");
  j += enderecosI2C;
  j += F("\",\"i2c_varredura_ha_s\":");
  j += ultimaVarreduraMs ? (millis() - ultimaVarreduraMs) / 1000UL : 0;
  j += F(",\"i2c_pullup_sda\":");
  j += pullupSda ? F("true") : F("false");
  j += F(",\"i2c_pullup_scl\":");
  j += pullupScl ? F("true") : F("false");
  j += F(",\"fonte_hora\":\"");
  j += escaparJson(origemAcerto);
  j += F("\",\"hora_acertada_em\":");
  j += horaAcertadaEm;
  j += F(",\"wifi_conectado\":");
  j += wifiConectado ? F("true") : F("false");
  j += F(",\"wifi_status\":\"");
  j += textoStatusWifi(WiFi.status());
  j += F("\",\"gateway\":\"");
  if (wifiConectado) j += WiFi.gatewayIP().toString();
  j += F("\",\"conectado_ha_s\":");
  j += wifiConectado ? (millis() - conectadoDesdeMs) / 1000UL : 0;
  j += F(",\"ultima_queda_ha_s\":");
  j += ultimaQuedaMs ? (millis() - ultimaQuedaMs) / 1000UL : 0;
  j += F(",\"duracao_ultima_queda_s\":");
  j += duracaoUltimaQuedaMs / 1000UL;
  j += F(",\"motivo_ultima_queda\":\"");
  j += textoMotivoQueda(motivoUltimaQueda);
  j += F("\",\"radio_reiniciado\":");
  j += radioReiniciado;
  j += F(",\"reconexoes_forcadas\":");
  j += reconexoesForcadas;
  j += F(",\"ap_ativo\":");
  j += apAtivo ? F("true") : F("false");
  j += F(",\"ap_ssid\":\"");
  j += AP_SSID;
  j += F("\",\"ap_clientes\":");
  j += apAtivo ? WiFi.softAPgetStationNum() : 0;
  j += F(",\"mac\":\"");
  j += WiFi.macAddress();
  j += F("\",\"heap_livre\":");
  j += ESP.getFreeHeap();
  j += F(",\"heap_minimo\":");
  j += ESP.getMinFreeHeap();
  j += F(",\"flash_usado_kb\":");
  j += armazenamentoOk ? (uint32_t)(LittleFS.usedBytes() / 1024) : 0;
  j += F(",\"flash_total_kb\":");
  j += armazenamentoOk ? (uint32_t)(LittleFS.totalBytes() / 1024) : 0;
  j += F(",\"reset_preocupante\":");
  j += resetPreocupante(esp_reset_reason()) ? F("true") : F("false");
  j += F(",\"eventos\":");
  j += qtdEventos;
  j += F(",\"nuvem_ativa\":");
  j += nuvemAtiva() ? F("true") : F("false");
  j += F(",\"nuvem_ate\":");
  j += nuvemAte;
  j += F(",\"nuvem_ultimo_envio_s\":");
  if (nuvemUltimoOkMs) j += (uint32_t)((millis() - nuvemUltimoOkMs) / 1000UL);
  else j += F("null");
  j += F(",\"nuvem_envios_ok\":");
  j += nuvemEnviosOk;
  j += F(",\"nuvem_falhas\":");
  j += nuvemFalhas;
  j += F(",\"nuvem_conexoes_novas\":");
  j += nuvemConexoesNovas;
  j += F(",\"nuvem_erro\":\"");
  j += escaparJson(String(nuvemErro));
  j += F("\",\"maquinas\":[");
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    if (m) j += ',';
    j += F("{\"maquina\":");
    j += m + 1;
    j += F(",\"ligado\":");
    j += estadoAtual[m] == EstadoEquipamento::LIGADO ? 1 : 0;
    j += F(",\"segundos\":");
    j += (millis() - instanteEstado[m]) / 1000UL;
    j += F(",\"ciclos\":");
    j += contadorCiclos[m];
    j += F(",\"total_ligado_s\":");
    j += totalSegundosLigado[m];
    j += '}';
  }
  j += F("]}");
  servidor.send(200, "application/json", j);
}

void responderCiclos() {
  registrarContatoPc();
  uint32_t desde = servidor.hasArg("desde") ? strtoul(servidor.arg("desde").c_str(), nullptr, 10) : 0;
  uint32_t maximo = servidor.hasArg("max") ? strtoul(servidor.arg("max").c_str(), nullptr, 10) : MAX_CICLOS_POR_RESPOSTA;
  if (maximo == 0 || maximo > MAX_CICLOS_POR_RESPOSTA) maximo = MAX_CICLOS_POR_RESPOSTA;

  String csv;
  csv.reserve(maximo * 80 + 64);
  csv += F("id,maquina,ciclo,inicio,fim,duracao_s,obs\n");

  uint32_t id = max(desde + 1, primeiroIdDisponivel());
  uint32_t lidoAte = desde;
  uint32_t enviados = 0;
  File f = armazenamentoOk ? LittleFS.open(ARQUIVO_CICLOS, "r") : File();
  if (f) {
    for (; id <= ultimoIdCiclo && enviados < maximo; id++) {
      lidoAte = id;
      RegistroCiclo r;
      if (!lerRegistroDaFlash(f, id, r)) continue;
      char inicio[20], fim[20], obs[64], linha[160];
      bool relativa = r.flags & FLAG_HORA_RELATIVA; // ainda sem data (boot anterior ou hora nao acertada)
      formatarEpoch(relativa ? 0 : r.inicioEpoch, inicio);
      formatarEpoch(relativa ? 0 : r.fimEpoch, fim);
      montarObs(r.flags, obs, sizeof(obs));
      snprintf(linha, sizeof(linha), "%lu,%u,%lu,%s,%s,%lu.%lu,%s\n", (unsigned long)r.id, (unsigned)r.maquina,
               (unsigned long)r.ciclo, inicio, fim, (unsigned long)(r.duracaoDecimos / 10),
               (unsigned long)(r.duracaoDecimos % 10), obs);
      csv += linha;
      enviados++;
    }
    f.close();
  }
  // Ultimo id examinado (mesmo se o slot estava vazio/sobrescrito) - o PC
  // continua a partir dele, senao ficaria preso num buraco do historico.
  servidor.sendHeader("X-Lido-Ate", String(lidoAte));
  servidor.send(200, "text/csv", csv);
}

void responderEventos() {
  registrarContatoPc();
  String j;
  j.reserve(qtdEventos * 140 + 32);
  j += F("{\"agora_ligado_s\":");
  j += (uint32_t)(esp_timer_get_time() / 1000000LL);
  j += F(",\"boot\":");
  j += contagemBoots;
  j += F(",\"eventos\":[");
  for (uint8_t i = 0; i < qtdEventos; i++) {
    // do mais novo para o mais antigo
    const Evento &e = eventos[(proximoEvento + MAX_EVENTOS - 1 - i) % MAX_EVENTOS];
    if (i) j += ',';
    char hora[20] = "";
    if (e.epoch) formatarEpoch(e.epoch, hora);
    j += F("{\"hora\":\"");
    j += hora;
    j += F("\",\"ligado_s\":");
    j += e.ligadoS;
    j += F(",\"boot\":");
    j += e.boot;
    j += F(",\"texto\":\"");
    j += escaparJson(String(e.texto));
    j += F("\"}");
  }
  j += F("]}");
  servidor.send(200, "application/json", j);
}

// Acoes pedidas pelo painel: redetectar_rtc, varrer_i2c, reconectar_wifi, reiniciar.
void responderAcao() {
  if (!exigirChave()) return;
  registrarContatoPc();
  String acao = servidor.hasArg("acao") ? servidor.arg("acao") : String();
  String msg;
  bool ok = true;
  if (acao == "redetectar_rtc") {
    bool achou = rtcPresente ? (lerRegistroRtc(0x0F) >= 0) : redetectarRtc(true);
    if (rtcPresente && achou) varrerI2C();
    msg = achou ? String(F("RTC respondendo e em uso.")) : String(F("RTC nao respondeu. I2C: ")) + (enderecosI2C.length() ? enderecosI2C : String(F("nenhum dispositivo")));
    ok = achou;
  } else if (acao == "varrer_i2c") {
    recuperarBarramentoI2C();
    varrerI2C();
    msg = String(F("Varredura concluida: ")) + (enderecosI2C.length() ? enderecosI2C : String(F("nenhum dispositivo respondeu")));
  } else if (acao == "reconectar_wifi") {
    if (!staAtivo) { ok = false; msg = F("Rede da empresa desligada (modo so rede propria)."); }
    else {
      registrarEvento(F("Reconexao do Wi-Fi pedida pelo painel"));
      reiniciarEmMs = 0;
      msg = F("Reconectando - o controlador fica alguns segundos sem responder.");
      String j = String(F("{\"ok\":true,\"mensagem\":\"")) + escaparJson(msg) + F("\"}");
      servidor.send(200, "application/json", j);
      delay(100);
      reiniciarRadioWifi(F("pedido pelo painel"));
      return;
    }
  } else if (acao == "reiniciar") {
    registrarEvento(F("Reinicio pedido pelo painel"));
    reiniciarEmMs = millis() + 1500;
    msg = F("Reiniciando em instantes - os contadores das maquinas sao salvos antes.");
  } else {
    servidor.send(400, "application/json", F("{\"ok\":false,\"mensagem\":\"acao desconhecida\"}"));
    return;
  }
  String j = String(F("{\"ok\":")) + (ok ? F("true") : F("false")) + F(",\"mensagem\":\"") + escaparJson(msg) + F("\"}");
  servidor.send(200, "application/json", j);
}

// Rotas que ALTERAM o ESP32 (/hora, /limpar, /acao) exigem a API_CHAVE
// (segredos.h, gerada do .env) no cabecalho X-Chave - sem ela, qualquer
// aparelho na rede poderia apagar ciclos ainda nao baixados. API_CHAVE
// vazia = sem verificacao (compatibilidade).
bool exigirChave() {
  if (API_CHAVE[0] == '\0') return true;
  String chave = servidor.header("X-Chave");
  if (chave.length() == 0) chave = servidor.arg("chave");
  if (chave == API_CHAVE) return true;
  servidor.send(403, "application/json", F("{\"ok\":false,\"mensagem\":\"chave invalida\"}"));
  return false;
}

void responderHora() {
  if (!exigirChave()) return;
  uint32_t epoch = servidor.hasArg("epoch") ? strtoul(servidor.arg("epoch").c_str(), nullptr, 10) : 0;
  DataHora minimo = {2024, 1, 1, 0, 0, 0};
  if (epoch < paraEpoch(minimo)) {
    servidor.send(400, "text/plain", "epoch invalido");
    return;
  }
  definirHora(epoch, "PC pelo Wi-Fi");
  responderInfo();
}

void responderLimpar() {
  if (!exigirChave()) return;
  if (!servidor.hasArg("ate")) {
    servidor.send(400, "text/plain", "informe ate=<id>");
    return;
  }
  apagarCiclosAte(strtoul(servidor.arg("ate").c_str(), nullptr, 10));
  responderInfo();
}

String escaparHtml(const String &texto) {
  String r;
  r.reserve(texto.length() + 8);
  for (size_t i = 0; i < texto.length(); i++) {
    char c = texto[i];
    if (c == '&') r += F("&amp;");
    else if (c == '<') r += F("&lt;");
    else if (c == '>') r += F("&gt;");
    else if (c == '"') r += F("&quot;");
    else if (c == '\'') r += F("&#39;");
    else r += c;
  }
  return r;
}

String escaparJson(const String &texto) {
  String r;
  for (size_t i = 0; i < texto.length(); i++) {
    char c = texto[i];
    if (c == '"' || c == '\\') r += '\\';
    if ((uint8_t)c >= 0x20) r += c;
  }
  return r;
}

void carregarConfigWifi() {
  cfgWifi.modo = prefs.getUChar("wmodo", MODO_WIFI_PADRAO);
  if (cfgWifi.modo > MODO_AMBAS) cfgWifi.modo = MODO_WIFI_PADRAO;
  cfgWifi.ssid = prefs.getString("wssid", EMPRESA_SSID_PADRAO);
  cfgWifi.senha = prefs.getString("wsenha", EMPRESA_SENHA_PADRAO);
  cfgWifi.ip = prefs.getString("wip", "");
  cfgWifi.gateway = prefs.getString("wgw", "");
}

void salvarConfigWifi() {
  prefs.putUChar("wmodo", cfgWifi.modo);
  prefs.putString("wssid", cfgWifi.ssid);
  prefs.putString("wsenha", cfgWifi.senha);
  prefs.putString("wip", cfgWifi.ip);
  prefs.putString("wgw", cfgWifi.gateway);
}

void restaurarConfigWifiDeFabrica() {
  const char *chaves[] = {"wmodo", "wssid", "wsenha", "wip", "wgw"};
  for (const char *chave : chaves) prefs.remove(chave);
}

// Antes de reiniciar (nova config de Wi-Fi), grava o progresso dos ciclos
// em andamento - no boot eles continuam de onde pararam.
void reiniciarComSeguranca() {
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    if (estadoAtual[m] == EstadoEquipamento::LIGADO) {
      salvarEstado(m, true, (millis() - instanteInicioCiclo[m]) / 1000UL);
    }
  }
  Serial.println(F("# Reiniciando para aplicar a nova configuracao de Wi-Fi..."));
  Serial.flush();
  ESP.restart();
}

void iniciarMdns() {
  if (!mdnsIniciado && MDNS.begin(NOME_REDE)) {
    MDNS.addService("http", "tcp", 80);
    mdnsIniciado = true;
  }
}

void ligarRedePropria() {
  WiFi.softAPConfig(AP_IP, AP_IP, IPAddress(255, 255, 255, 0));
  if (WiFi.softAP(AP_SSID, AP_SENHA, AP_CANAL, false, AP_MAX_CONEXOES)) {
    apAtivo = true;
    Serial.print(F("# Rede propria \""));
    Serial.print(AP_SSID);
    Serial.print(F("\" ligada - conecte o notebook nela e acesse http://"));
    Serial.println(WiFi.softAPIP());
    iniciarMdns();
  } else {
    Serial.println(F("# ERRO: nao foi possivel criar a rede propria (AP_SENHA precisa ter 8+ caracteres)"));
  }
}

void conectarRedeEmpresa() {
  WiFi.disconnect();
  WiFi.begin(cfgWifi.ssid.c_str(), cfgWifi.senha.c_str()); // nao bloqueia: o loop() segue contando ciclos
  ultimaTentativaWifiMs = millis();
}

void iniciarWifi() {
  carregarConfigWifi();
  bool usarEmpresa = cfgWifi.modo != MODO_SO_PROPRIA && cfgWifi.ssid.length() > 0;
  bool usarPropria = cfgWifi.modo != MODO_SO_EMPRESA || !usarEmpresa;

  WiFi.setHostname(NOME_REDE);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) { motivoQuedaPendente = info.wifi_sta_disconnected.reason; },
               ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  WiFi.mode(usarEmpresa && usarPropria ? WIFI_AP_STA : (usarPropria ? WIFI_AP : WIFI_STA));
  // Sem economia de energia no Wi-Fi: com ela o ESP32 "cochila" entre os
  // beacons e perde pedidos ARP - atras de um repetidor isso faz o notebook
  // nao encontrar o ESP32 ("Host de destino inacessivel") mesmo conectado.
  WiFi.setSleep(false);
  if (usarPropria) ligarRedePropria();
  if (usarEmpresa) {
    staAtivo = true;
    IPAddress ip, gateway;
    if (cfgWifi.ip.length() && ip.fromString(cfgWifi.ip)) {
      if (!cfgWifi.gateway.length() || !gateway.fromString(cfgWifi.gateway)) {
        gateway = IPAddress(ip[0], ip[1], ip[2], 1);
      }
      WiFi.config(ip, gateway, IPAddress(255, 255, 255, 0), gateway);
    }
    // Com a rede propria ligada, o auto-reconnect do nucleo (que fica
    // varrendo canais sem parar) derruba quem esta conectado nela - a
    // reconexao e feita a mao, a cada INTERVALO_RECONEXAO_WIFI_MS.
    WiFi.setAutoReconnect(!usarPropria);
    Serial.print(F("# Conectando na rede da empresa \""));
    Serial.print(cfgWifi.ssid);
    Serial.println('"');
    conectarRedeEmpresa();
    semEmpresaDesdeMs = millis();
  }

  servidor.on("/", HTTP_GET, responderPagina);
  servidor.on("/config", HTTP_POST, responderSalvarConfig);
  servidor.on("/info", HTTP_GET, responderInfo);
  servidor.on("/ciclos", HTTP_GET, responderCiclos);
  servidor.on("/hora", HTTP_POST, responderHora);
  servidor.on("/limpar", HTTP_POST, responderLimpar);
  servidor.on("/eventos", HTTP_GET, responderEventos);
  servidor.on("/acao", HTTP_POST, responderAcao);
  servidor.onNotFound([]() { servidor.send(404, "text/plain", "nao encontrado"); });
  static const char *cabecalhos[] = {"X-Chave"}; // o WebServer so guarda os cabecalhos pedidos
  servidor.collectHeaders(cabecalhos, 1);
  servidor.begin();
}

void verificarWifi() {
  if (apAtivo) {
    uint8_t clientes = WiFi.softAPgetStationNum();
    if (clientes != clientesConectados) {
      Serial.print(clientes > clientesConectados ? F("# Notebook conectou na rede propria") : F("# Notebook saiu da rede propria"));
      Serial.print(F(" (conectados: "));
      Serial.print(clientes);
      Serial.println(')');
      clientesConectados = clientes;
    }
  }
  if (!staAtivo) return;

  bool conectado = WiFi.status() == WL_CONNECTED;
  if (conectado != wifiConectado) {
    wifiConectado = conectado;
    if (conectado) {
      Serial.print(F("# Conectado na rede da empresa - IP: "));
      Serial.println(WiFi.localIP());
      iniciarMdns();
      conectadoDesdeMs = millis();
      tentativasSemSucesso = 0;
      if (reconexaoPreventiva) {
        reconexaoPreventiva = false; // volta da reconexao preventiva - nada a registrar
      } else if (ultimaQuedaMs) {
        duracaoUltimaQuedaMs = millis() - ultimaQuedaMs;
        registrarEvento(String(F("Rede da empresa voltou apos ")) + formatarDuracao(duracaoUltimaQuedaMs / 1000UL) +
                        F(" - IP ") + WiFi.localIP().toString() + F(", sinal ") + WiFi.RSSI() + F(" dBm"));
      } else {
        registrarEvento(String(F("Conectado na rede da empresa - IP ")) + WiFi.localIP().toString());
      }
    } else {
      Serial.println(F("# Rede da empresa fora do ar - os ciclos continuam sendo gravados na flash"));
      semEmpresaDesdeMs = millis();
      if (!reconexaoPreventiva) {
        quedasWifi++;
        ultimaQuedaMs = millis();
        if (ultimaQuedaMs == 0) ultimaQuedaMs = 1;
        motivoUltimaQueda = motivoQuedaPendente;
        registrarEvento(String(F("Rede da empresa caiu: ")) + textoMotivoQueda(motivoUltimaQueda) + F(" (cod. ") + motivoUltimaQueda + ")");
      }
    }
  }
  if (conectado) {
    // Conectado, mas o PC (que buscava os dados) parou de alcancar o ESP32
    // ha muito tempo: tipico de associacao "presa" no repetidor. Reconecta,
    // com espera crescente (15 min, 30, 60, ate 2 h) enquanto o PC nao voltar.
    // referencia: ultimo contato do PC ou, se o PC ainda nao alcancou o
    // controlador desde o boot, o momento em que ele entrou na rede
    unsigned long referenciaPc = ultimoContatoPcMs ? ultimoContatoPcMs : conectadoDesdeMs;
    // 3.1: envio para a VPS em dia = o Wi-Fi esta funcionando (o PC so esta
    // desligado ou com o app fechado) - nao derruba a conexao a toa
    bool internetOk = nuvemAtiva() && nuvemUltimoOkMs && millis() - nuvemUltimoOkMs < 120000UL;
    if (!internetOk && millis() - referenciaPc >= esperaReconexaoMs && millis() - ultimaReconexaoForcadaMs >= esperaReconexaoMs) {
      reconexoesForcadas++;
      ultimaReconexaoForcadaMs = millis();
      if (esperaReconexaoMs == SEM_PC_PARA_RECONECTAR_MS) { // so a 1a de cada periodo sem o PC vira evento
        registrarEvento(String(F("PC sem contato ha ")) + formatarDuracao((millis() - referenciaPc) / 1000UL) +
                        F(" - reconectando ao Wi-Fi por precaucao (repete com intervalo crescente ate o PC voltar)"));
      }
      reconexaoPreventiva = true;
      esperaReconexaoMs = min(esperaReconexaoMs * 2, MAX_ESPERA_RECONEXAO_MS);
      conectarRedeEmpresa();
    }
    return;
  }

  // Reconexao preventiva que nao voltou em 2 min: era queda de verdade.
  if (reconexaoPreventiva && millis() - ultimaReconexaoForcadaMs >= 120000UL) {
    reconexaoPreventiva = false;
    quedasWifi++;
    ultimaQuedaMs = ultimaReconexaoForcadaMs ? ultimaReconexaoForcadaMs : 1;
    motivoUltimaQueda = motivoQuedaPendente;
    registrarEvento(String(F("Rede da empresa nao voltou apos a reconexao preventiva: ")) + textoMotivoQueda(motivoUltimaQueda));
  }

  if (millis() - ultimaTentativaWifiMs >= INTERVALO_RECONEXAO_WIFI_MS) {
    if (++tentativasSemSucesso >= TENTATIVAS_ATE_REINICIAR_RADIO) reiniciarRadioWifi(F("sem reconectar ha varios minutos"));
    else conectarRedeEmpresa();
  }

  // Modo SO EMPRESA sem conexao (senha trocada, roteador desligado...): liga
  // a rede propria para o ESP32 continuar acessivel e configuravel.
  if (!apAtivo && millis() - semEmpresaDesdeMs >= TEMPO_ATE_LIGAR_REDE_PROPRIA_MS) {
    Serial.println(F("# Sem a rede da empresa ha 2 min - ligando a rede propria para acesso"));
    WiFi.setAutoReconnect(false);
    WiFi.mode(WIFI_AP_STA);
    WiFi.setSleep(false);
    ligarRedePropria();
    conectarRedeEmpresa();
  }
}

// ---------------------------------------------------------------------
// Pagina de situacao/configuracao (http://192.168.4.1 ou IP da empresa)
// ---------------------------------------------------------------------
const char PAGINA_HTML[] = R"html(<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Horímetro Santex</title>
<style>
body{font-family:system-ui,Segoe UI,sans-serif;max-width:560px;margin:0 auto;padding:16px;background:#f3f4f6;color:#1f2937}
h1{font-size:1.35em;margin:8px 0}h2{font-size:1.05em;margin:0 0 10px}
section{background:#fff;border-radius:10px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.12)}
table{width:100%;border-collapse:collapse}td{padding:4px 0;vertical-align:top}td+td{text-align:right;font-weight:600}
label{display:block;margin:12px 0 4px;font-weight:600}
.op{display:flex;gap:8px;font-weight:400;margin:8px 0;align-items:flex-start}.op input{margin-top:3px}
input[type=text],input[type=password]{width:100%;padding:9px;box-sizing:border-box;border:1px solid #c7cbd1;border-radius:6px;font-size:1em}
small{color:#6b7280;font-weight:400}button{margin-top:16px;padding:11px 18px;border:0;border-radius:6px;background:#2563eb;color:#fff;font-size:1em;width:100%}
.ok{color:#15803d}.ruim{color:#b91c1c}.alerta{color:#b45309}a{color:#2563eb}
.avisos{background:#fef2f2;border:1px solid #fecaca}.avisos ul{margin:0;padding-left:20px}.avisos li{margin:6px 0}
.tudo-ok{background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d;font-weight:600}
.topo{display:flex;justify-content:space-between;align-items:baseline}
</style></head><body>
<div class="topo"><h1>Horímetro Santex</h1><a href="/">Atualizar</a></div>
%SITUACAO%
<section><h2>Wi-Fi</h2><form method="post" action="/config">
<label>Como o ESP32 fica na rede</label>
<div class="op"><input type="radio" name="modo" value="2" id="m2" %M2%><label for="m2" style="margin:0;font-weight:400"><b>Ambas</b> (recomendado)<br><small>Entra na rede da empresa e também cria a rede HORIMETRO_SANTEX.</small></label></div>
<div class="op"><input type="radio" name="modo" value="1" id="m1" %M1%><label for="m1" style="margin:0;font-weight:400"><b>Só rede da empresa</b><br><small>Se a rede da empresa ficar 2 min fora, a rede própria liga sozinha.</small></label></div>
<div class="op"><input type="radio" name="modo" value="0" id="m0" %M0%><label for="m0" style="margin:0;font-weight:400"><b>Só rede própria</b><br><small>Sem roteador: o notebook conecta em HORIMETRO_SANTEX.</small></label></div>
<label>Nome da rede da empresa</label><input type="text" name="ssid" value="%SSID%" maxlength="32">
<label>Senha da rede da empresa</label><input type="password" name="senha" placeholder="deixe em branco para manter a atual" maxlength="63">
<label>IP fixo na rede da empresa <small>(opcional)</small></label><input type="text" name="ip" value="%IP%" placeholder="automático">
<label>Gateway <small>(opcional)</small></label><input type="text" name="gateway" value="%GW%" placeholder="automático">
%DICA_IP%
<label>Senha do equipamento <small>(a mesma da rede HORIMETRO_SANTEX)</small></label><input type="password" name="senha_equip" required>
<button>Salvar e reiniciar</button>
<small>Reiniciar não perde nenhum ciclo: os que estão em andamento continuam de onde pararam.</small>
</form></section></body></html>)html";

String spanCor(const char *classe, const String &texto) {
  return String("<span class=\"") + classe + "\">" + texto + "</span>";
}

void linhaTabela(String &h, const char *rotulo, const String &valor) {
  h += F("<tr><td>");
  h += rotulo;
  h += F("</td><td>");
  h += valor;
  h += F("</td></tr>");
}

// Todas as secoes de situacao da pagina: avisos (o que precisa de atencao),
// relogio/RTC, rede, maquinas e sistema.
String montarSituacao() {
  DiagnosticoRtc rtc = diagnosticarRtc();
  esp_reset_reason_t motivoReset = esp_reset_reason();
  uint32_t agora = agoraEpoch();
  uint32_t pendentes = ultimoIdCiclo - apagadoAte;
  int rssi = wifiConectado ? WiFi.RSSI() : 0;
  unsigned long semPcS = ultimoContatoPcMs ? (millis() - ultimoContatoPcMs) / 1000UL : 0;
  unsigned long conectadoHaS = wifiConectado ? (millis() - conectadoDesdeMs) / 1000UL : 0;
  long difRtcS = (rtc.leuHora && horaValida) ? (long)rtc.epoch - (long)agora : 0;
  char texto[64];

  // ---- Avisos ----
  String avisos;
  auto aviso = [&avisos](const String &t) {
    avisos += F("<li>");
    avisos += t;
    avisos += F("</li>");
  };
  if (!rtc.responde) {
    aviso(F("<b>RTC DS3231 não responde.</b> Verifique os fios (SDA=GPIO21, SCL=GPIO22) e a alimentação 3V3. "
            "Sem ele os ciclos ficam sem data/hora até o PC acertar o relógio."));
  } else if (!rtcPresente) {
    aviso(F("<b>O RTC passou a responder.</b> O firmware passa a usá-lo sozinho em até 30 s (não precisa reiniciar)."));
  }
  if (rtcSemHoraNoBoot) {
    aviso(F("<b>O RTC estava sem hora quando o controlador ligou</b>: a bateria (CR2032) do módulo está fraca ou ausente. "
            "Troque a bateria; até lá, a cada falta de energia os ciclos ficam marcados SEM_HORA até o PC acertar o relógio."));
  }
  if (rtc.responde && rtc.eosc) {
    aviso(F("<b>O oscilador do RTC está configurado para parar na bateria (EOSC)</b> - ele perde a hora em toda falta de energia."));
  }
  if (rtc.responde && rtc.osf && horaValida) {
    aviso(F("<b>O RTC sinalizou que o oscilador parou</b> depois do último acerto de hora (falha no módulo ou na bateria)."));
  }
  if (!horaValida) {
    aviso(F("<b>Relógio não acertado</b>: os ciclos estão sendo gravados SEM_HORA. Abra o painel no PC (acerta sozinho pelo Wi-Fi) "
            "ou envie T<i>AAAA-MM-DD HH:MM:SS</i> pela Serial."));
  }
  if (rtc.leuHora && horaValida && labs(difRtcS) > 10) {
    snprintf(texto, sizeof(texto), "%ld s", difRtcS);
    aviso(String(F("<b>A hora do RTC difere da hora interna em ")) + texto + F("</b> - possível falha de leitura do RTC."));
  }
  if (!armazenamentoOk) {
    aviso(F("<b>Armazenamento (LittleFS) com falha</b>: os ciclos NÃO estão sendo guardados na flash."));
  } else if (pendentes > CAPACIDADE_REGISTROS * 8 / 10) {
    aviso(F("<b>Armazenamento quase cheio</b>: o PC precisa buscar os ciclos, senão os mais antigos serão sobrescritos."));
  }
  if (staAtivo && !wifiConectado) {
    aviso(String(F("<b>Sem conexão com a rede da empresa</b> (")) + textoStatusWifi(WiFi.status()) +
          F("). Os ciclos continuam sendo gravados; o controlador tenta reconectar a cada 60 s."));
  }
  if (wifiConectado && rssi < -80) {
    aviso(F("<b>Sinal Wi-Fi muito fraco</b>: aproxime o repetidor ou reposicione o controlador/antena."));
  }
  if (wifiConectado && conectadoHaS > 300 && (ultimoContatoPcMs == 0 || semPcS > 900)) {
    String t = F("<b>Conectado ao Wi-Fi, mas o painel do PC não acessa o controlador ");
    t += ultimoContatoPcMs ? String(F("há ")) + formatarDuracao(semPcS) : String(F("desde que ele ligou"));
    t += F(".</b> Se o PC está ligado com o painel aberto, o repetidor pode não estar repassando a rede: "
           "aperte EN/RESET no controlador ou religue o repetidor.");
    aviso(t);
  }
  if (resetPreocupante(motivoReset)) {
    aviso(String(F("<b>O último reinício foi por ")) + textoMotivoReset(motivoReset) + F("</b>."));
  }

  String h;
  h.reserve(6000);
  if (avisos.length()) {
    h += F("<section class=\"avisos\"><h2 class=\"ruim\">Atenção</h2><ul>");
    h += avisos;
    h += F("</ul></section>");
  } else {
    h += F("<section class=\"tudo-ok\">Tudo funcionando normalmente.</section>");
  }

  // ---- Relogio ----
  char hora[20];
  h += F("<section><h2>Relógio (RTC DS3231)</h2><table>");
  formatarEpoch(agora, hora);
  linhaTabela(h, "Hora atual", horaValida ? String(hora) : spanCor("ruim", F("não acertada")));
  String modulo;
  if (!rtc.responde) modulo = spanCor("ruim", F("não responde"));
  else if (!rtcPresente) modulo = spanCor("alerta", F("responde (será usado em até 30 s)"));
  else modulo = spanCor("ok", F("respondendo"));
  linhaTabela(h, "Módulo no I2C (0x68)", modulo);
  if (rtc.responde) {
    if (rtc.leuHora) {
      formatarEpoch(rtc.epoch, hora);
      String v = String(hora).substring(11);
      if (horaValida) {
        snprintf(texto, sizeof(texto), " (dif. %+ld s)", difRtcS);
        v += texto;
      }
      linhaTabela(h, "Hora lida do chip agora", labs(difRtcS) > 10 ? spanCor("ruim", v) : v);
    } else {
      linhaTabela(h, "Hora lida do chip agora", spanCor("ruim", F("falha na leitura")));
    }
    if (rtc.temTemperatura) {
      snprintf(texto, sizeof(texto), "%.2f &deg;C", rtc.temperatura);
      linhaTabela(h, "Temperatura do chip", texto);
    }
    linhaTabela(h, "Oscilador (flag OSF)", rtc.osf ? spanCor("ruim", F("parou desde o último acerto")) : spanCor("ok", F("ok")));
  }
  linhaTabela(h, "Bateria (hora ao ligar o controlador)",
              !rtcPresente ? String(F("-"))
              : rtcSemHoraNoBoot ? spanCor("ruim", F("estava SEM hora: bateria fraca/ausente"))
                                 : spanCor("ok", F("hora mantida: bateria ok")));
  if (horaAcertadaEm) {
    formatarEpoch(horaAcertadaEm, hora);
    String v = String(hora).substring(0, 16);
    v.replace("T", " ");
    v += String(F(" &middot; ")) + origemAcerto;
    if (correcaoConhecida) {
      snprintf(texto, sizeof(texto), " (corrigiu %+ld s)", ultimaCorrecaoS);
      v += texto;
    } else {
      v += F(" (estava sem hora)");
    }
    linhaTabela(h, "Último acerto de hora", v);
  } else {
    linhaTabela(h, "Último acerto de hora", F("nenhum desde que ligou"));
  }
  if (falhasLeituraRtc) linhaTabela(h, "Falhas de leitura do RTC", spanCor("alerta", String(falhasLeituraRtc)));
  linhaTabela(h, "Barramento I2C (dispositivos)", enderecosI2C.length() ? enderecosI2C : spanCor("ruim", F("nenhum respondeu")));
  linhaTabela(h, "Pull-up SDA / SCL",
              String(pullupSda ? F("sim") : F("NÃO")) + " / " + (pullupScl ? F("sim") : F("NÃO")) +
                  ((!pullupSda || !pullupScl) ? String(F(" <small>(sem pull-up: módulo desligado/desconectado ou sem resistores)</small>")) : String()));
  h += F("</table></section>");

  // ---- Rede ----
  h += F("<section><h2>Rede</h2><table>");
  if (!staAtivo) {
    linhaTabela(h, "Rede da empresa", F("desligada (modo só rede própria)"));
  } else if (wifiConectado) {
    linhaTabela(h, "Rede da empresa", spanCor("ok", F("conectado")) + "<br>" + escaparHtml(cfgWifi.ssid));
    linhaTabela(h, "IP / gateway", WiFi.localIP().toString() + " &middot; " + WiFi.gatewayIP().toString());
    snprintf(texto, sizeof(texto), "%d dBm (%s)", rssi, qualidadeSinal(rssi));
    linhaTabela(h, "Sinal", rssi < -80 ? spanCor("ruim", texto) : rssi < -70 ? spanCor("alerta", texto) : String(texto));
    linhaTabela(h, "Ponto de acesso (BSSID) / canal", WiFi.BSSIDstr() + " &middot; " + String(WiFi.channel()));
    linhaTabela(h, "Conectado há", formatarDuracao(conectadoHaS));
  } else {
    linhaTabela(h, "Rede da empresa", spanCor("ruim", textoStatusWifi(WiFi.status())) + "<br>" + escaparHtml(cfgWifi.ssid));
  }
  if (staAtivo) {
    String quedas = String(quedasWifi);
    if (ultimaQuedaMs) quedas += String(F(" (última há ")) + formatarDuracao((millis() - ultimaQuedaMs) / 1000UL) + F(": ") + textoMotivoQueda(motivoUltimaQueda) + ")";
    linhaTabela(h, "Quedas desde que ligou", quedas);
  }
  linhaTabela(h, "Último acesso do painel (PC)",
              ultimoContatoPcMs ? String(F("há ")) + formatarDuracao(semPcS) + " &middot; " + ipUltimoContatoPc
                                : String(F("nenhum desde que ligou")));
  linhaTabela(h, "Rede própria",
              apAtivo ? String(AP_SSID) + " &middot; " + WiFi.softAPIP().toString() + "<br>" +
                            String(WiFi.softAPgetStationNum()) + " aparelho(s) conectado(s)"
                      : String(F("desligada")));
  linhaTabela(h, "MAC do controlador", WiFi.macAddress());
  h += F("</table></section>");

  // ---- Maquinas ----
  h += F("<section><h2>Máquinas</h2><table>");
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    bool ligada = estadoAtual[m] == EstadoEquipamento::LIGADO;
    String v = ligada ? spanCor("ok", F("LIGADA")) : String(F("parada"));
    v += String(F(" há ")) + formatarDuracao((millis() - instanteEstado[m]) / 1000UL);
    if (modoSimulacao[m]) v += spanCor("alerta", F(" (modo manual)"));
    v += String(F("<br><small>")) + String(contadorCiclos[m]) + F(" ciclos &middot; ") +
         formatarDuracao(totalSegundosLigado[m]) + F(" ligada no total</small>");
    snprintf(texto, sizeof(texto), "Enfestadeira %u <small>(GPIO %u)</small>", (unsigned)(m + 1), (unsigned)PINOS_RELE[m]);
    linhaTabela(h, texto, v);
  }
  h += F("</table></section>");

  // ---- Sistema ----
  h += F("<section><h2>Sistema</h2><table>");
  snprintf(texto, sizeof(texto), "%lu de %lu (%lu%%)", (unsigned long)pendentes, (unsigned long)CAPACIDADE_REGISTROS,
           (unsigned long)(pendentes * 100UL / CAPACIDADE_REGISTROS));
  linhaTabela(h, "Ciclos guardados (ainda não extraídos)", texto);
  linhaTabela(h, "Último id de ciclo", String(ultimoIdCiclo));
  if (armazenamentoOk) {
    snprintf(texto, sizeof(texto), "ok &middot; %u de %u KB", (unsigned)(LittleFS.usedBytes() / 1024),
             (unsigned)(LittleFS.totalBytes() / 1024));
    linhaTabela(h, "Armazenamento (LittleFS)", spanCor("ok", texto));
  } else {
    linhaTabela(h, "Armazenamento (LittleFS)", spanCor("ruim", F("falha")));
  }
  linhaTabela(h, "Ligado há", formatarDuracao(segundosLigadoEsp()));
  linhaTabela(h, "Motivo do último reinício",
              resetPreocupante(motivoReset) ? spanCor("ruim", textoMotivoReset(motivoReset)) : String(textoMotivoReset(motivoReset)));
  linhaTabela(h, "Reinícios (total)", String(contagemBoots));
  snprintf(texto, sizeof(texto), "%u KB (mínima %u KB)", (unsigned)(ESP.getFreeHeap() / 1024),
           (unsigned)(ESP.getMinFreeHeap() / 1024));
  linhaTabela(h, "Memória livre", texto);
  linhaTabela(h, "Firmware", String(FIRMWARE_VERSAO) + F(" &middot; compilado em " __DATE__ " " __TIME__));
  if (radioReiniciado || reconexoesForcadas) {
    linhaTabela(h, "Autocorreções de Wi-Fi", String(radioReiniciado) + F(" reinício(s) do rádio &middot; ") + String(reconexoesForcadas) + F(" reconexão(ões) preventiva(s)"));
  }
  linhaTabela(h, "Dispositivo", idDispositivo);
  if (nuvemAtiva()) {
    String sit = nuvemErro[0] ? spanCor("ruim", escaparHtml(String(nuvemErro)))
               : nuvemUltimoOkMs ? spanCor("bom", String(F("enviando - último envio há ")) + formatarDuracao((millis() - nuvemUltimoOkMs) / 1000UL))
               : String(F("aguardando o primeiro envio"));
    sit += String(F(" &middot; ")) + String(ultimoIdCiclo - nuvemAte) + F(" ciclo(s) na fila");
    linhaTabela(h, "Acesso remoto (nuvem)", sit);
  } else {
    linhaTabela(h, "Acesso remoto (nuvem)", F("desligado (NUVEM_URL vazia no .env)"));
  }
  h += F("</table></section>");
  return h;
}

void responderPagina() {
  String pagina = PAGINA_HTML;
  pagina.replace("%SITUACAO%", montarSituacao());

  pagina.replace("%M0%", cfgWifi.modo == MODO_SO_PROPRIA ? "checked" : "");
  pagina.replace("%M1%", cfgWifi.modo == MODO_SO_EMPRESA ? "checked" : "");
  pagina.replace("%M2%", cfgWifi.modo == MODO_AMBAS ? "checked" : "");
  pagina.replace("%SSID%", escaparHtml(cfgWifi.ssid));
  pagina.replace("%IP%", escaparHtml(cfgWifi.ip));
  pagina.replace("%GW%", escaparHtml(cfgWifi.gateway));

  String dica;
  if (wifiConectado && !cfgWifi.ip.length()) {
    String ip = WiFi.localIP().toString(), gw = WiFi.gatewayIP().toString();
    dica = "<small>IP atual: " + ip + " &middot; <a href=\"#\" onclick=\"var f=document.forms[0];f.ip.value='" + ip +
           "';f.gateway.value='" + gw + "';return false\">usar este IP como fixo</a> (assim o notebook sempre acha o controlador)</small>";
  }
  pagina.replace("%DICA_IP%", dica);
  servidor.send(200, "text/html; charset=utf-8", pagina);
}

void responderMensagem(int status, const String &mensagem) {
  String pagina = F("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                    "<title>Horímetro Santex</title></head><body style=\"font-family:system-ui,sans-serif;max-width:560px;margin:40px auto;padding:16px\">");
  pagina += mensagem;
  pagina += F("<p><a href=\"/\">Voltar</a></p></body></html>");
  servidor.send(status, "text/html; charset=utf-8", pagina);
}

void responderSalvarConfig() {
  if (servidor.arg("senha_equip") != AP_SENHA) {
    responderMensagem(403, F("<h2>Senha do equipamento incorreta</h2><p>Nada foi alterado.</p>"));
    return;
  }
  long modo = servidor.arg("modo").toInt();
  String ssid = servidor.arg("ssid");
  String ip = servidor.arg("ip");
  String gateway = servidor.arg("gateway");
  ssid.trim();
  ip.trim();
  gateway.trim();
  IPAddress teste;
  if (modo < MODO_SO_PROPRIA || modo > MODO_AMBAS) {
    responderMensagem(400, F("<h2>Escolha um modo</h2>"));
    return;
  }
  if (modo != MODO_SO_PROPRIA && ssid.length() == 0) {
    responderMensagem(400, F("<h2>Informe o nome da rede da empresa</h2>"));
    return;
  }
  if ((ip.length() && !teste.fromString(ip)) || (gateway.length() && !teste.fromString(gateway))) {
    responderMensagem(400, F("<h2>IP ou gateway inválido</h2><p>Use o formato 192.168.15.50 ou deixe em branco.</p>"));
    return;
  }

  cfgWifi.modo = modo;
  if (ssid != cfgWifi.ssid || servidor.arg("senha").length()) cfgWifi.senha = servidor.arg("senha");
  cfgWifi.ssid = ssid;
  cfgWifi.ip = ip;
  cfgWifi.gateway = gateway;
  salvarConfigWifi();

  String aviso = F("<h2>Configuração salva</h2><p>O controlador está reiniciando (cerca de 10 s).</p>");
  if (modo == MODO_SO_EMPRESA) {
    aviso += F("<p>A rede HORIMETRO_SANTEX vai sumir. Conecte o notebook na rede da empresa");
    if (ip.length()) {
      aviso += F(" e acesse http://");
      aviso += ip;
    }
    aviso += F(". Se o controlador não conseguir entrar nela, a rede própria volta sozinha em 2 min.</p>");
  }
  responderMensagem(200, aviso);
  reiniciarEmMs = millis() + 1500; // da tempo da resposta chegar ao navegador
}

// ---------------------------------------------------------------------
// Comandos via Serial: L1-L4, D1-D4, R1-R4 (controle manual, substituem
// os botoes do LCD), T<data hora> (acerta o relogio) e I (informacoes).
// ---------------------------------------------------------------------
void imprimirInfo() {
  char hora[20];
  formatarEpoch(agoraEpoch(), hora);
  Serial.print(F("# Hora: "));
  Serial.print(hora);
  Serial.print(rtcPresente ? F(" (RTC ok)") : F(" (SEM RTC)"));
  Serial.print(F(" | rede da empresa: "));
  if (!staAtivo) {
    Serial.print(F("desligada"));
  } else {
    Serial.print(cfgWifi.ssid);
    Serial.print(' ');
    if (wifiConectado) {
      Serial.print(WiFi.localIP());
    } else {
      Serial.print(F("(sem conexao)"));
    }
  }
  Serial.print(F(" | rede propria: "));
  if (apAtivo) {
    Serial.print(WiFi.softAPIP());
    Serial.print(F(" ("));
    Serial.print(WiFi.softAPgetStationNum());
    Serial.print(F(" conectado(s))"));
  } else {
    Serial.print(F("desligada"));
  }
  Serial.print(F(" | ciclos guardados (ainda nao extraidos): "));
  Serial.print(ultimoIdCiclo - apagadoAte);
  Serial.print(F(" | ultimo id "));
  Serial.print(ultimoIdCiclo);
  Serial.print(F(" | dispositivo "));
  Serial.println(idDispositivo);
}

// Comando "S" pela Serial: diagnostico completo sem depender do Wi-Fi.
void imprimirDiagnostico() {
  DiagnosticoRtc rtc = diagnosticarRtc();
  if (!rtcPresente) { recuperarBarramentoI2C(); varrerI2C(); rtc = diagnosticarRtc(); }
  char hora[20] = "?";
  if (horaValida) formatarEpoch(agoraEpoch(), hora);
  Serial.println(F("# ===== DIAGNOSTICO DO CONTROLADOR ====="));
  Serial.print(F("# Firmware: ")); Serial.print(FIRMWARE_VERSAO); Serial.println(F(" (compilado em " __DATE__ " " __TIME__ ")"));
  Serial.print(F("# Dispositivo: ")); Serial.print(idDispositivo); Serial.print(F(" | boot ")); Serial.print(contagemBoots);
  Serial.print(F(" | ligado ha ")); Serial.print(formatarDuracao(segundosLigadoEsp()));
  Serial.print(F(" | ultimo reinicio: ")); Serial.println(textoMotivoReset(esp_reset_reason()));
  Serial.print(F("# Hora: ")); Serial.print(hora); Serial.print(F(" | fonte: ")); Serial.println(*origemAcerto ? origemAcerto : "-");
  Serial.print(F("# RTC em uso: ")); Serial.print(rtcPresente ? F("SIM") : F("NAO"));
  Serial.print(F(" | responde agora (0x68): ")); Serial.print(rtc.responde ? F("SIM") : F("NAO"));
  if (rtc.responde) {
    Serial.print(F(" | OSF (parou/bateria): ")); Serial.print(rtc.osf ? F("sim") : F("nao"));
    if (rtc.temTemperatura) { Serial.print(F(" | temperatura: ")); Serial.print(rtc.temperatura, 2); Serial.print(F(" C")); }
  }
  Serial.println();
  Serial.print(F("# I2C (SDA=GPIO")); Serial.print(PINO_SDA); Serial.print(F(", SCL=GPIO")); Serial.print(PINO_SCL);
  Serial.print(F("): dispositivos: ")); Serial.print(enderecosI2C.length() ? enderecosI2C : String(F("NENHUM")));
  Serial.print(F(" | pull-up SDA: ")); Serial.print(pullupSda ? F("sim") : F("NAO"));
  Serial.print(F(" | pull-up SCL: ")); Serial.println(pullupScl ? F("sim") : F("NAO"));
  if (!rtc.responde) {
    if (!enderecosI2C.length() && !pullupSda && !pullupScl)
      Serial.println(F("#   -> nada no barramento e sem pull-up: modulo sem energia/desconectado (meca 3,3 V em VCC-GND do modulo)"));
    else if (!enderecosI2C.length())
      Serial.println(F("#   -> ha pull-up mas nada responde: SDA/SCL trocados, modulo de outro tipo (DS1302 nao e I2C; DS1307 exige 5 V) ou com defeito"));
    else if (enderecosI2C.indexOf("0x68") < 0)
      Serial.println(F("#   -> ha dispositivo(s), mas nao no 0x68: chip do relogio nao responde (0x57 costuma ser so a EEPROM do modulo)"));
  }
  Serial.print(F("# Wi-Fi: ")); Serial.print(staAtivo ? (wifiConectado ? F("conectado") : F("desconectado")) : F("rede da empresa desligada"));
  if (wifiConectado) { Serial.print(F(" | IP ")); Serial.print(WiFi.localIP()); Serial.print(F(" | sinal ")); Serial.print(WiFi.RSSI()); Serial.print(F(" dBm")); }
  Serial.print(F(" | quedas: ")); Serial.print(quedasWifi);
  Serial.print(F(" | ultimo motivo: ")); Serial.println(textoMotivoQueda(motivoUltimaQueda));
  Serial.print(F("# Memoria livre: ")); Serial.print(ESP.getFreeHeap()); Serial.print(F(" bytes (minima ")); Serial.print(ESP.getMinFreeHeap()); Serial.println(F(")"));
  Serial.println(F("# Ultimos eventos:"));
  for (uint8_t i = 0; i < qtdEventos && i < 8; i++) {
    const Evento &e = eventos[(proximoEvento + MAX_EVENTOS - 1 - i) % MAX_EVENTOS];
    char h[20] = "";
    if (e.epoch) formatarEpoch(e.epoch, h);
    Serial.print(F("#   ")); Serial.print(e.epoch ? h : "(sem hora)"); Serial.print(F(" | ")); Serial.println(e.texto);
  }
  Serial.println(F("# ======================================"));
}

void tratarComandosSerial() {
  if (!Serial.available()) return;
  String linha = Serial.readStringUntil('\n');
  linha.trim();
  if (linha.length() == 0) return;

  char comando = toupper(linha[0]);
  if (comando == 'I') {
    imprimirInfo();
    return;
  }
  if (comando == 'S' && linha.length() == 1) {
    imprimirDiagnostico();
    return;
  }
  if (comando == 'W' && linha.length() == 1) {
    restaurarConfigWifiDeFabrica();
    Serial.println(F("# Wi-Fi voltou para a configuracao de fabrica"));
    reiniciarComSeguranca();
    return;
  }
  if (comando == 'X' && linha.length() == 1) {
    apagarCiclosAte(ultimoIdCiclo);
    return;
  }
  if (comando == 'T') {
    unsigned ano, mes, dia, hora, minuto, segundo;
    if (sscanf(linha.c_str() + 1, "%u-%u-%u%*[ T]%u:%u:%u", &ano, &mes, &dia, &hora, &minuto, &segundo) == 6 &&
        ano >= 2024 && ano < 2100 && mes >= 1 && mes <= 12 && dia >= 1 && dia <= 31 && hora < 24 && minuto < 60 &&
        segundo < 60) {
      DataHora d = {(uint16_t)ano, (uint8_t)mes, (uint8_t)dia, (uint8_t)hora, (uint8_t)minuto, (uint8_t)segundo};
      definirHora(paraEpoch(d), "Serial");
    } else {
      Serial.println(F("# Formato: T2026-10-30 14:05:00"));
    }
    return;
  }

  if (linha.length() < 2) return;
  if (linha[1] < '1' || linha[1] > '9') return;
  uint8_t idMaquina = linha[1] - '1'; // '1'-'4' -> 0-3
  if (idMaquina >= NUM_MAQUINAS) return;

  switch (comando) {
    case 'L': // liga manualmente
      modoSimulacao[idMaquina] = true;
      if (estadoAtual[idMaquina] != EstadoEquipamento::LIGADO) {
        mudarEstadoEquipamento(idMaquina, true, true);
      }
      break;
    case 'D': // desliga manualmente
      modoSimulacao[idMaquina] = true;
      if (estadoAtual[idMaquina] != EstadoEquipamento::DESLIGADO) {
        mudarEstadoEquipamento(idMaquina, false, true);
      }
      break;
    case 'R': // devolve o controle ao contato real
      if (modoSimulacao[idMaquina]) {
        modoSimulacao[idMaquina] = false;
        Serial.print(F("# [M"));
        Serial.print(idMaquina + 1);
        Serial.println(F("] Modo real retomado"));
      }
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------------
// Envio para a VPS (tarefa propria, nucleo 0)
// ---------------------------------------------------------------------
// Monta o lote: {"dispositivo", "firmware", "hora", "hora_valida",
// "ultimo_id", "lido_ate", "perdidos", "maquinas": [...], "ciclos": "csv"}
// - o mesmo formato que a VPS espera (ferramentas/nuvem.py,
// testes/test_nuvem.py). Devolve o ultimo id examinado (lidoAte).
uint32_t montarEnvioNuvem(String &corpo, uint32_t &perdidos) {
  uint32_t ultimo = ultimoIdCiclo;
  uint32_t primeiroNoBuffer = ultimo <= CAPACIDADE_REGISTROS ? 1 : ultimo - CAPACIDADE_REGISTROS + 1;
  uint32_t inicio = nuvemAte + 1;
  perdidos = 0;
  if (inicio < primeiroNoBuffer) { // a memoria circular passou por cima antes do envio
    perdidos = primeiroNoBuffer - inicio;
    inicio = primeiroNoBuffer;
  }
  uint32_t lidoAte = inicio - 1;

  char hora[20];
  formatarEpoch(agoraEpoch(), hora);
  corpo = F("{\"dispositivo\":\"");
  corpo += idDispositivo;
  corpo += F("\",\"firmware\":\"");
  corpo += FIRMWARE_VERSAO;
  corpo += F("\",\"hora\":\"");
  corpo += hora;
  corpo += F("\",\"hora_valida\":");
  corpo += horaValida ? F("true") : F("false");
  corpo += F(",\"ultimo_id\":");
  corpo += ultimo;
  corpo += F(",\"maquinas\":[");
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    if (m) corpo += ',';
    corpo += F("{\"maquina\":");
    corpo += m + 1;
    corpo += F(",\"ligado\":");
    corpo += estadoAtual[m] == EstadoEquipamento::LIGADO ? F("true") : F("false");
    corpo += F(",\"segundos\":");
    corpo += (millis() - instanteEstado[m]) / 1000UL;
    corpo += '}';
  }
  corpo += F("],\"ciclos\":\"id,maquina,ciclo,inicio,fim,duracao_s,obs\\n");
  File f = LittleFS.open(ARQUIVO_CICLOS, "r");
  if (f) {
    uint32_t enviados = 0;
    for (uint32_t id = inicio; id <= ultimo && enviados < NUVEM_MAX_CICLOS_POR_ENVIO; id++) {
      lidoAte = id;
      RegistroCiclo r;
      if (!lerRegistroDaFlash(f, id, r)) continue; // slot vazio/sobrescrito: so avanca
      bool relativa = r.flags & FLAG_HORA_RELATIVA;
      char ini[20], fim[20], obs[64], linha[160];
      formatarEpoch(relativa ? 0 : r.inicioEpoch, ini);
      formatarEpoch(relativa ? 0 : r.fimEpoch, fim);
      montarObs(r.flags, obs, sizeof(obs));
      snprintf(linha, sizeof(linha), "%lu,%u,%lu,%s,%s,%lu.%lu,%s\\n", (unsigned long)r.id, (unsigned)r.maquina,
               (unsigned long)r.ciclo, ini, fim, (unsigned long)(r.duracaoDecimos / 10),
               (unsigned long)(r.duracaoDecimos % 10), obs);
      corpo += linha;
      enviados++;
    }
    f.close();
  }
  corpo += F("\",\"lido_ate\":");
  corpo += lidoAte;
  corpo += F(",\"perdidos\":");
  corpo += perdidos;
  corpo += '}';
  return lidoAte;
}

// Um envio. Devolve 1 = enviado e ainda ha fila, 0 = enviado e em dia,
// -1 = falhou (nada muda: o mesmo lote vai de novo depois).
// Um POST pela conexao guardada (abre uma nova se nao houver). Devolve o
// codigo HTTP ou o erro do HTTPClient (< 0).
int postarNuvem(const String &corpo, bool &reaproveitou) {
  if (!nuvemCliente) {
    nuvemCliente = new NetworkClientSecure();
    nuvemCliente->setCACert(NUVEM_CA);
    nuvemCliente->setTimeout(15); // segundos
  }
  if (!nuvemHttp) {
    nuvemHttp = new HTTPClient();
    nuvemHttp->setReuse(true); // keep-alive: a conexao fica aberta para o proximo envio
    nuvemHttp->setConnectTimeout(10000);
    nuvemHttp->setTimeout(15000);
  }
  reaproveitou = nuvemCliente->connected();
  if (!nuvemHttp->begin(*nuvemCliente, String(NUVEM_URL) + F("/api/nuvem/enviar"))) return HTTPC_ERROR_CONNECTION_REFUSED;
  nuvemHttp->addHeader(F("Content-Type"), F("application/json"));
  nuvemHttp->addHeader(F("X-Chave-Nuvem"), NUVEM_CHAVE);
  int codigo = nuvemHttp->POST(corpo);
  nuvemHttp->end(); // com setReuse a conexao continua aberta (se a VPS permitir)
  if (codigo > 0 && !reaproveitou) nuvemConexoesNovas = nuvemConexoesNovas + 1;
  return codigo;
}

int enviarLoteNuvem(Preferences &p) {
  String corpo;
  uint32_t perdidos = 0;
  uint32_t lidoAte = montarEnvioNuvem(corpo, perdidos);

  if (strncmp(NUVEM_URL, "https://", 8) != 0 && strncmp(NUVEM_URL, "http://", 7) != 0) {
    strlcpy(nuvemErro, "endereco da VPS invalido (NUVEM_URL)", sizeof(nuvemErro));
    return -1;
  }
  bool reaproveitou = false;
  int codigo = postarNuvem(corpo, reaproveitou);
  if (codigo < 0 && reaproveitou) {
    // a conexao guardada tinha caido (VPS reiniciou, roteador trocou o IP...): abre outra na hora
    nuvemCliente->stop();
    codigo = postarNuvem(corpo, reaproveitou);
  }

  if (codigo == 200) {
    if (lidoAte > nuvemAte) {
      nuvemAte = lidoAte;
      p.putUInt("nuvem", lidoAte);
    }
    if (perdidos) {
      registrarEvento(String(perdidos) + F(" ciclo(s) sobrescritos antes de chegar a nuvem"));
    }
    nuvemUltimoOkMs = millis();
    nuvemEnviosOk = nuvemEnviosOk + 1;
    nuvemErro[0] = '\0';
    return lidoAte < ultimoIdCiclo ? 1 : 0;
  }
  nuvemFalhas = nuvemFalhas + 1;
  if (codigo == 403) strlcpy(nuvemErro, "a VPS recusou a chave (NUVEM_CHAVE diferente)", sizeof(nuvemErro));
  else if (codigo > 0) snprintf(nuvemErro, sizeof(nuvemErro), "a VPS respondeu HTTP %d", codigo);
  else {
    // 3.1: o erro real por baixo do "connection refused" (DNS, TCP ou TLS)
    char tls[64] = "";
    int e = nuvemCliente ? nuvemCliente->lastError(tls, sizeof(tls)) : 0;
    if (e) snprintf(nuvemErro, sizeof(nuvemErro), "sem conexao com a VPS (%s; TLS -0x%04X %s)", HTTPClient::errorToString(codigo).c_str(), -e, tls);
    else snprintf(nuvemErro, sizeof(nuvemErro), "sem conexao com a VPS (%s; %s)", HTTPClient::errorToString(codigo).c_str(),
                  WiFi.status() == WL_CONNECTED ? "Wi-Fi ok, sem resposta da VPS/DNS" : "Wi-Fi desconectado");
  }
  if (nuvemCliente) nuvemCliente->stop(); // proxima tentativa abre conexao nova
  return -1;
}

void tarefaNuvem(void *) {
  Preferences p;
  p.begin("horimetro", false); // handle proprio desta tarefa (a NVS e segura entre tarefas)
  unsigned long espera = 5000UL, recuo = NUVEM_INTERVALO_MS;
  bool avisouFalha = false;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(espera));
    if (!wifiConectado || !staAtivo || !armazenamentoOk) { // so a rede da empresa tem internet
      espera = NUVEM_INTERVALO_MS;
      continue;
    }
    int r = enviarLoteNuvem(p);
    if (r >= 0) {
      if (avisouFalha) {
        registrarEvento(F("Envio para a nuvem voltou a funcionar"));
        avisouFalha = false;
      }
      recuo = NUVEM_INTERVALO_MS;
      espera = r > 0 ? 300UL : NUVEM_INTERVALO_MS; // fila: o proximo lote logo em seguida
    } else {
      if (!avisouFalha && recuo >= 4 * NUVEM_INTERVALO_MS) { // falhou varias vezes seguidas
        registrarEvento(String(F("Envio para a nuvem falhando: ")) + nuvemErro);
        avisouFalha = true;
      }
      espera = recuo;
      recuo = min(recuo * 2, NUVEM_ESPERA_MAX_MS);
    }
  }
}

void iniciarNuvem() {
  if (!nuvemAtiva()) {
    Serial.println(F("# Acesso remoto desligado (NUVEM_URL vazia no .env)"));
    return;
  }
  Serial.print(F("# Acesso remoto: enviando para "));
  Serial.println(NUVEM_URL);
  // 12 KB de pilha (HTTPS), prioridade baixa, nucleo 0 (o loop roda no 1)
  xTaskCreatePinnedToCore(tarefaNuvem, "nuvem", 12288, nullptr, 1, &tarefaNuvemHandle, 0);
}

void setup() {
  Serial.begin(9600);
  delay(200); // da tempo do monitor serial conectar antes dos primeiros prints

  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    pinMode(PINOS_RELE[m], INPUT_PULLUP);
  }
  pinMode(PINO_LED_STATUS, OUTPUT);

  prefs.begin("horimetro", false); // namespace proprio na NVS (leitura e escrita)
  contagemBoots = prefs.getUInt("boots", 0) + 1;
  prefs.putUInt("boots", contagemBoots);

  Serial.println(F("Controle de producao - horimetro (controlador, 4 maquinas, RTC + flash + Wi-Fi)"));
  Serial.print(F("Firmware compilado em: "));
  Serial.print(F(__DATE__));
  Serial.print(' ');
  Serial.println(F(__TIME__));

  iniciarArmazenamento();
  carregarEventos();
  iniciarRelogio();
  registrarEvento(String(F("Controlador ligou (boot ")) + contagemBoots + F(", firmware ") + FIRMWARE_VERSAO + F("): ") + textoMotivoReset(esp_reset_reason()));

  Serial.println(F("maquina,ciclo,inicio,fim,duracao_s,obs"));

  uint32_t agora = agoraEpoch();

  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    bool ligadaNoBoot = lerContatoLigado(m);
    leituraEstavel[m] = ligadaNoBoot;
    inicioEpochCiclo[m] = 0;

    EstadoPersistido salvo;
    bool temHistorico = carregarEstadoPersistido(m, salvo);
    bool cicloPendente = temHistorico && salvo.estadoLigado == 1;

    if (temHistorico) {
      contadorCiclos[m] = salvo.contadorCiclos;
      totalSegundosLigado[m] = salvo.totalSegundosLigado;

      Serial.print(F("# [M"));
      Serial.print(m + 1);
      Serial.print(F("] Recuperado da flash - ciclos: "));
      Serial.print(contadorCiclos[m]);
      Serial.print(F(" | total ligado (s): "));
      Serial.println(totalSegundosLigado[m]);
    }

    // Tempo real decorrido desde o inicio do ciclo pendente (so com hora valida dos dois lados).
    bool sabeDecorrido = cicloPendente && salvo.inicioEpoch != 0 && agora >= salvo.inicioEpoch;
    uint32_t decorrido = sabeDecorrido ? agora - salvo.inicioEpoch : salvo.cicloAtualSegundos;
    // Quanto tempo o ESP32 ficou desligado (desde o ultimo checkpoint).
    bool quedaLonga = sabeDecorrido && decorrido > salvo.cicloAtualSegundos + LIMITE_QUEDA_CONTINUA_S;

    if (cicloPendente && (!ligadaNoBoot || quedaLonga)) {
      // Maquina desligou durante a queda (ou a queda foi longa demais para
      // saber): fecha o ciclo pendente com o que deu para salvar.
      uint32_t inicio = salvo.inicioEpoch;
      registrarCiclo(m, salvo.cicloAtualSegundos * 1000UL, inicio, inicio ? inicio + salvo.cicloAtualSegundos : 0,
                     FLAG_RECUPERADO);
      salvarEstado(m, false, 0);
      cicloPendente = false;
    }

    if (ligadaNoBoot) {
      estadoAtual[m] = EstadoEquipamento::LIGADO;
      if (cicloPendente) {
        instanteInicioCiclo[m] = millis() - decorrido * 1000UL;
        inicioEpochCiclo[m] = salvo.inicioEpoch ? salvo.inicioEpoch : (agora ? agora - decorrido : 0);
        Serial.print(F("# [M"));
        Serial.print(m + 1);
        Serial.println(sabeDecorrido ? F("] Seguiu ligada durante o reset - ciclo continua (duracao pelo RTC)")
                                     : F("] AVISO: seguiu ligada durante um reset - duracao deste ciclo e aproximada"));
      } else {
        instanteInicioCiclo[m] = millis();
        inicioEpochCiclo[m] = agora;
        Serial.print(F("# [M"));
        Serial.print(m + 1);
        Serial.println(F("] AVISO: ja estava LIGADA no boot - duracao do 1o ciclo sera parcial"));
      }
      salvarEstado(m, true, (millis() - instanteInicioCiclo[m]) / 1000UL);
    } else {
      estadoAtual[m] = EstadoEquipamento::DESLIGADO;
    }

    instanteEstado[m] = (estadoAtual[m] == EstadoEquipamento::LIGADO) ? instanteInicioCiclo[m] : millis();
    ultimoSalvamentoMs[m] = millis();
  }

  atualizarLed();
  iniciarWifi();
  iniciarNuvem();
  emitirEstados();
  ultimoEstadoMs = millis();
}

void loop() {
  for (uint8_t m = 0; m < NUM_MAQUINAS; m++) {
    bool leituraBruta = lerContatoLigado(m);

    if (leituraBruta != leituraEstavel[m]) {
      instanteMudanca[m] = millis();
      leituraEstavel[m] = leituraBruta;
    }

    bool deveEstarLigada = (estadoAtual[m] == EstadoEquipamento::LIGADO);

    // Em modo manual (via Serial), o contato real e ignorado - quem manda e o comando L/D.
    if (!modoSimulacao[m] && (millis() - instanteMudanca[m]) > DEBOUNCE_MS && leituraEstavel[m] != deveEstarLigada) {
      mudarEstadoEquipamento(m, leituraEstavel[m], false);
    }

    if (estadoAtual[m] == EstadoEquipamento::LIGADO && (millis() - ultimoSalvamentoMs[m]) >= INTERVALO_SALVAMENTO_MS) {
      unsigned long cicloAtualSeg = (millis() - instanteInicioCiclo[m]) / 1000UL;
      salvarEstado(m, true, cicloAtualSeg);
      ultimoSalvamentoMs[m] = millis();
    }
  }

  if (millis() - ultimoEstadoMs >= INTERVALO_ESTADO_MS) {
    emitirEstados();
    ultimoEstadoMs = millis();
  }

  if (horaValida && millis() - ultimoResyncRtcMs >= INTERVALO_RESYNC_RTC_MS) {
    sincronizarComRtc();
  }

  verificarRtc();
  verificarWifi();
  verificarNtp();
  verificarMemoria();
  servidor.handleClient();
  if (reiniciarEmMs && (long)(millis() - reiniciarEmMs) >= 0) reiniciarComSeguranca();
  tratarComandosSerial();
}
