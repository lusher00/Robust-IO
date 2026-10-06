#ifndef HSD_H
#define HSD_H
#include <stdint.h>
#include <stdbool.h>

/* Eight BTS7008 high-side outputs, DRV_OUT0..7 on PC0..PC7.
 * hsd_task() scans the shared current-sense line in the background, one
 * channel every ISENSE_SETTLE_MS, and switches a channel off when it trips. */

typedef enum {
    HSD_OFF,            /* commanded off, output low */
    HSD_OFF_HIGH,       /* commanded off, but the device reports the output pulled high
                           (open load with a pull-up, or short to supply) */
    HSD_ON,             /* commanded on, current within limit */
    HSD_TRIPPED,        /* switched off by firmware: over the current limit for the trip time. Latched */
    HSD_FAULT           /* switched off by firmware: device signalled a fault (short circuit,
                           over-temperature). Latched */
} hsd_status_t;

void         hsd_init(void);
void         hsd_task(void);
bool         hsd_set(uint8_t ch, uint8_t on);    /* false if the channel is latched off */
void         hsd_all_off(void);
uint8_t      hsd_get(void);                      /* commanded mask */
void         hsd_clear(uint8_t mask);            /* clear latched trips; channels stay off */
hsd_status_t hsd_status(uint8_t ch);
uint16_t     hsd_mv(uint8_t ch);                 /* last sense voltage */
uint16_t     hsd_ma(uint8_t ch);                 /* last load current, 0 when off */
uint8_t      hsd_latched(void);                  /* mask of tripped or faulted channels */
uint16_t     hsd_scans(void);                    /* completed scans, wraps; lets callers wait for fresh data */
void         hsd_set_limit(uint8_t ch, uint16_t ma, uint16_t trip_ms);
uint16_t     hsd_limit_ma(uint8_t ch);
uint16_t     hsd_trip_ms(uint8_t ch);
#endif
