#include <avr/eeprom.h>
#include <avr/pgmspace.h>
#include <avr/wdt.h>
#include <util/crc16.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "drivers/mcp2515.h"
#include "drivers/mc33978.h"
#include "drivers/hsd.h"
#include "drivers/motor.h"
#include "app/inputs.h"
#include "app/config.h"

#define CFG_VERSION 1

config_t cfg;
static config_t EEMEM ee_cfg;
static bool defaults_in_use;

static const uint16_t rate_kbit[4] PROGMEM = { 125, 250, 500, 1000 };

static const char n_node[]     PROGMEM = "node";
static const char n_rate[]     PROGMEM = "rate";
static const char n_timeout[]  PROGMEM = "timeout";
static const char n_debounce[] PROGMEM = "debounce";
static const char n_wet_sp[]   PROGMEM = "wet_sp";
static const char n_wet_sg[]   PROGMEM = "wet_sg";
static const char n_slew[]     PROGMEM = "slew";
static const char n_idle[]     PROGMEM = "idle";
static PGM_P const names[8] PROGMEM = { n_node, n_rate, n_timeout, n_debounce, n_wet_sp, n_wet_sg, n_slew, n_idle };

static uint16_t crc_of(const config_t *c)
{
    const uint8_t *p = (const uint8_t *)c;
    uint16_t r = 0xFFFF;
    for (uint8_t i = 0; i < offsetof(config_t, crc); i++) r = _crc16_update(r, p[i]);
    return r;
}

void config_defaults(void)
{
    memset(&cfg, 0, sizeof cfg);
    cfg.version     = CFG_VERSION;
    cfg.node        = CFG_DEFAULT_NODE;
    cfg.rate        = CAN_250K;
    cfg.timeout_ms  = CFG_DEFAULT_TIMEOUT_MS;
    cfg.debounce_ms = CFG_DEFAULT_DEBOUNCE_MS;
    cfg.wet_sp = cfg.wet_sg = mc33978_ma_to_code(CFG_DEFAULT_WET_MA);
    cfg.slew        = CFG_DEFAULT_SLEW;
    cfg.idle_ms     = CFG_DEFAULT_IDLE_MS;
    for (uint8_t i = 0; i < HSD_COUNT; i++) {
        cfg.limit_ma[i] = HSD_LIMIT_MA_DEFAULT;
        cfg.trip_ms[i]  = HSD_TRIP_MS_DEFAULT;
    }
}

bool config_load(void)
{
    eeprom_read_block(&cfg, &ee_cfg, sizeof cfg);
    defaults_in_use = (cfg.version != CFG_VERSION || cfg.crc != crc_of(&cfg));
    if (defaults_in_use) config_defaults();
    return !defaults_in_use;
}

bool config_from_defaults(void) { return defaults_in_use; }

uint8_t config_save(void)
{
    cfg.version = CFG_VERSION;
    cfg.crc = crc_of(&cfg);
    const uint8_t *p = (const uint8_t *)&cfg;
    uint8_t *e = (uint8_t *)&ee_cfg;
    for (uint8_t i = 0; i < sizeof cfg; i++) {      /* about 3.4 ms per changed byte */
        eeprom_update_byte(e + i, p[i]);
        wdt_reset();
    }
    for (uint8_t i = 0; i < sizeof cfg; i++)
        if (eeprom_read_byte(e + i) != p[i]) return CFG_EEPROM_FAIL;
    defaults_in_use = false;
    return CFG_OK;
}

void config_apply(void)
{
    for (uint8_t i = 0; i < HSD_COUNT; i++) hsd_set_limit(i, cfg.limit_ma[i], cfg.trip_ms[i]);
    motor_config(cfg.slew, cfg.idle_ms);
    inputs_apply_config();
}

uint8_t config_get(uint8_t key, uint16_t *v)
{
    if (key >= CFG_LIMIT0 && key < CFG_LIMIT0 + HSD_COUNT) { *v = cfg.limit_ma[key - CFG_LIMIT0]; return CFG_OK; }
    if (key >= CFG_TRIP0  && key < CFG_TRIP0  + HSD_COUNT) { *v = cfg.trip_ms[key - CFG_TRIP0];   return CFG_OK; }
    switch (key) {
    case CFG_NODE:     *v = cfg.node; break;
    case CFG_RATE:     *v = pgm_read_word(&rate_kbit[cfg.rate & 3]); break;
    case CFG_TIMEOUT:  *v = cfg.timeout_ms; break;
    case CFG_DEBOUNCE: *v = cfg.debounce_ms; break;
    case CFG_WET_SP:   *v = mc33978_code_to_ma(cfg.wet_sp); break;
    case CFG_WET_SG:   *v = mc33978_code_to_ma(cfg.wet_sg); break;
    case CFG_SLEW:     *v = cfg.slew; break;
    case CFG_IDLE:     *v = cfg.idle_ms; break;
    default:           return CFG_BAD_KEY;
    }
    return CFG_OK;
}

uint8_t config_set(uint8_t key, uint16_t v)
{
    if (key >= CFG_LIMIT0 && key < CFG_LIMIT0 + HSD_COUNT) {
        if (v < 100 || v > 30000) return CFG_BAD_VALUE;
        cfg.limit_ma[key - CFG_LIMIT0] = v;
        config_apply();
        return CFG_OK;
    }
    if (key >= CFG_TRIP0 && key < CFG_TRIP0 + HSD_COUNT) {
        if (v > 10000) return CFG_BAD_VALUE;
        cfg.trip_ms[key - CFG_TRIP0] = v;
        config_apply();
        return CFG_OK;
    }
    switch (key) {
    case CFG_NODE:
        if (v > 15) return CFG_BAD_VALUE;
        cfg.node = (uint8_t)v;
        return CFG_OK;
    case CFG_RATE:
        for (uint8_t i = 0; i < 4; i++)
            if (pgm_read_word(&rate_kbit[i]) == v) { cfg.rate = i; return CFG_OK; }
        return CFG_BAD_VALUE;
    case CFG_TIMEOUT:
        if (v > 60000) return CFG_BAD_VALUE;
        cfg.timeout_ms = v;
        break;
    case CFG_DEBOUNCE:
        if (v > 250) return CFG_BAD_VALUE;
        cfg.debounce_ms = (uint8_t)v;
        break;
    case CFG_WET_SP:
    case CFG_WET_SG: {
        uint8_t code = (v <= 255) ? mc33978_ma_to_code((uint8_t)v) : 0xFF;
        if (code == 0xFF) return CFG_BAD_VALUE;
        if (key == CFG_WET_SP) cfg.wet_sp = code; else cfg.wet_sg = code;
        break;
    }
    case CFG_SLEW:
        if (v < 1 || v > 100) return CFG_BAD_VALUE;
        cfg.slew = (uint8_t)v;
        break;
    case CFG_IDLE:
        if (v > 60000) return CFG_BAD_VALUE;
        cfg.idle_ms = v;
        break;
    default:
        return CFG_BAD_KEY;
    }
    config_apply();
    return CFG_OK;
}

/* Names: node rate timeout debounce wet_sp wet_sg slew idle limit0..7 trip0..7 */
bool config_key_by_name(const char *s, uint8_t *key)
{
    for (uint8_t i = 0; i < 8; i++)
        if (!strcmp_P(s, (PGM_P)pgm_read_word(&names[i]))) { *key = i; return true; }
    if (!strncmp_P(s, PSTR("limit"), 5) && s[5] >= '0' && s[5] <= '7' && !s[6]) { *key = (uint8_t)(CFG_LIMIT0 + s[5] - '0'); return true; }
    if (!strncmp_P(s, PSTR("trip"),  4) && s[4] >= '0' && s[4] <= '7' && !s[5]) { *key = (uint8_t)(CFG_TRIP0  + s[4] - '0'); return true; }
    return false;
}

void config_print(void)
{
    uint16_t v;
    printf_P(PSTR("source: %S\n"), defaults_in_use ? PSTR("defaults (EEPROM empty or invalid)") : PSTR("EEPROM"));
    for (uint8_t i = 0; i < 8; i++) {
        config_get(i, &v);
        printf_P(PSTR("  %-9S %u\n"), (PGM_P)pgm_read_word(&names[i]), v);
    }
    for (uint8_t i = 0; i < HSD_COUNT; i++)
        printf_P(PSTR("  limit%u    %u mA  trip%u %u ms\n"), i, cfg.limit_ma[i], i, cfg.trip_ms[i]);
}
