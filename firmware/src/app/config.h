#ifndef CONFIG_H
#define CONFIG_H
#include <stdint.h>
#include <stdbool.h>
#include "board.h"

/* Settings kept in EEPROM. Keys are shared by the console ('cfg') and the
 * CAN configuration frame. Values are 16-bit, in the units listed. */
enum {
    CFG_NODE     = 0x00,   /* 0..15                                  applies after reset */
    CFG_RATE     = 0x01,   /* kbit/s: 125, 250, 500, 1000            applies after reset */
    CFG_TIMEOUT  = 0x02,   /* host timeout ms, 0 = off, max 60000 */
    CFG_DEBOUNCE = 0x03,   /* input debounce ms, 0..250 */
    CFG_WET_SP   = 0x04,   /* wetting current mA: 2 6 8 10 12 14 16 20 */
    CFG_WET_SG   = 0x05,
    CFG_SLEW     = 0x06,   /* motor duty change, percent per 10 ms, 1..100 */
    CFG_IDLE     = 0x07,   /* motor driver sleep delay ms, 0..60000 */
    CFG_LIMIT0   = 0x10,   /* 0x10..0x17: output trip level mA, 100..30000 */
    CFG_TRIP0    = 0x18,   /* 0x18..0x1F: output trip time ms, 0..10000 */
};

enum { CFG_OK = 0, CFG_BAD_KEY = 1, CFG_BAD_VALUE = 2, CFG_EEPROM_FAIL = 3 };

typedef struct {
    uint8_t  version;
    uint8_t  node;
    uint8_t  rate;             /* can_rate_t */
    uint8_t  debounce_ms;
    uint16_t timeout_ms;
    uint8_t  wet_sp, wet_sg;   /* MC33978 codes */
    uint8_t  slew;
    uint16_t idle_ms;
    uint16_t limit_ma[HSD_COUNT];
    uint16_t trip_ms[HSD_COUNT];
    uint16_t crc;
} config_t;

extern config_t cfg;

bool    config_load(void);                         /* false if EEPROM was invalid and defaults are in use */
bool    config_from_defaults(void);
void    config_defaults(void);                     /* RAM only */
uint8_t config_save(void);                         /* CFG_OK or CFG_EEPROM_FAIL */
void    config_apply(void);                        /* push run-time settings to the drivers */
uint8_t config_get(uint8_t key, uint16_t *value);
uint8_t config_set(uint8_t key, uint16_t value);   /* also applies it, except node and rate */
bool    config_key_by_name(const char *name, uint8_t *key);
void    config_print(void);
#endif
