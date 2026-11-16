// MODELO de segredos.h - copie este arquivo para "segredos.h" (mesma pasta)
// e preencha com os dados reais. O segredos.h fica fora do git.

// Rede da empresa (o ESP32 entra nela como mais um aparelho).
const char *EMPRESA_SSID_PADRAO = "NOME_DA_REDE";
const char *EMPRESA_SENHA_PADRAO = "SENHA_DA_REDE";

// Rede propria (criada pelo ESP32). AP_SENHA tambem e a senha pedida para
// salvar alteracoes na pagina de configuracao.
const char *AP_SSID = "HORIMETRO_SANTEX";
const char *AP_SENHA = "TROQUE_ESTA_SENHA"; // minimo 8 caracteres
