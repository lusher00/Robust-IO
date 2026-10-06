#include <avr/io.h>
#include "board.h"
#include "hal/adc.h"
#include "hal/tick.h"
#include "drivers/hsd.h"

typedef struct {
    uint16_t mv;
    uint16_t limit_ma;
    uint16_t trip_ms;
    uint32_t over_since;        /* tick when the current first exceeded the limit */
    uint8_t  over        : 1;
    uint8_t  fault_count : 2;   /* consecutive scans with the device fault level */
    uint8_t  status      : 3;
} hsd_ch_t;

static hsd_ch_t ch_state[HSD_COUNT];
static uint8_t  scan_ch;
static uint8_t  scan_armed;     /* DEN/DSEL are set for scan_ch and settling */
static uint32_t scan_t0;
static uint16_t scans;

static uint16_t mv_to_ma(uint16_t mv)
{
    uint32_t ma = (uint32_t)mv * BTS7008_KILIS / ISENSE_R_OHM;
    return ma > 0xFFFF ? 0xFFFF : (uint16_t)ma;
}

static void den_all_off(void)
{
    PORTB &= (uint8_t)~((1 << DEN0_BIT) | (1 << DEN1_BIT));
    PORTA &= (uint8_t)~((1 << DEN2_BIT) | (1 << DEN3_BIT));
}

/* All four IS pins share one sense resistor, so only one DEN is high at a time.
 * Device = ch / 2 (DEN0..DEN3), channel within the device = ch & 1 (DSEL). */
static void select(uint8_t ch)
{
    den_all_off();
    if (ch & 1) PORTA |= (1 << DSEL_BIT);
    else        PORTA &= (uint8_t)~(1 << DSEL_BIT);
    switch (ch >> 1) {
    case 0:  PORTB |= (1 << DEN0_BIT); break;
    case 1:  PORTB |= (1 << DEN1_BIT); break;
    case 2:  PORTA |= (1 << DEN2_BIT); break;
    default: PORTA |= (1 << DEN3_BIT); break;
    }
}

static void pin(uint8_t ch, uint8_t on)
{
    if (on) PORTC |= (uint8_t)(1 << ch);
    else    PORTC &= (uint8_t)~(1 << ch);
}

void hsd_init(void)
{
    for (uint8_t i = 0; i < HSD_COUNT; i++) {
        ch_state[i].limit_ma = HSD_LIMIT_MA_DEFAULT;
        ch_state[i].trip_ms  = HSD_TRIP_MS_DEFAULT;
        ch_state[i].status   = HSD_OFF;
    }
}

static void evaluate(uint8_t ch, uint16_t mv, uint32_t now)
{
    hsd_ch_t *c = &ch_state[ch];
    c->mv = mv;

    if (c->status == HSD_TRIPPED || c->status == HSD_FAULT) return;     /* latched */

    if (!(PORTC & (1 << ch))) {
        c->status = (mv >= HSD_OFF_HIGH_MV) ? HSD_OFF_HIGH : HSD_OFF;
        c->over = 0; c->fault_count = 0;
        return;
    }

    c->status = HSD_ON;

    /* Device fault level: act on the second consecutive reading. */
    if (mv >= ISENSE_FAULT_MV) {
        if (++c->fault_count >= 2) { pin(ch, 0); c->status = HSD_FAULT; }
        return;
    }
    c->fault_count = 0;

    /* Software limit: over the limit continuously for trip_ms. */
    if (mv_to_ma(mv) > c->limit_ma) {
        if (!c->over) { c->over = 1; c->over_since = now; }
        else if ((uint32_t)(now - c->over_since) >= c->trip_ms) { pin(ch, 0); c->status = HSD_TRIPPED; }
    } else {
        c->over = 0;
    }
}

void hsd_task(void)
{
    uint32_t now = tick_ms();
    if (!scan_armed) {
        select(scan_ch);
        scan_t0 = now;
        scan_armed = 1;
        return;
    }
    if ((uint32_t)(now - scan_t0) < ISENSE_SETTLE_MS + 1u) return;      /* +1: tick granularity */

    evaluate(scan_ch, adc_read_mv(ADC_CH_ISENSE), now);
    scan_armed = 0;
    if (++scan_ch >= HSD_COUNT) { scan_ch = 0; scans++; }
}

bool hsd_set(uint8_t ch, uint8_t on)
{
    if (ch >= HSD_COUNT) return false;
    hsd_ch_t *c = &ch_state[ch];
    if (on && (c->status == HSD_TRIPPED || c->status == HSD_FAULT)) return false;
    c->over = 0; c->fault_count = 0;
    pin(ch, on);
    return true;
}

void hsd_all_off(void) { PORTC = 0; }
uint8_t hsd_get(void)  { return PORTC; }

void hsd_clear(uint8_t mask)
{
    for (uint8_t i = 0; i < HSD_COUNT; i++)
        if ((mask & (1 << i)) && (ch_state[i].status == HSD_TRIPPED || ch_state[i].status == HSD_FAULT))
            ch_state[i].status = HSD_OFF;
}

hsd_status_t hsd_status(uint8_t ch) { return ch < HSD_COUNT ? (hsd_status_t)ch_state[ch].status : HSD_OFF; }
uint16_t     hsd_mv(uint8_t ch)     { return ch < HSD_COUNT ? ch_state[ch].mv : 0; }
uint16_t     hsd_scans(void)        { return scans; }

uint16_t hsd_ma(uint8_t ch)
{
    if (ch >= HSD_COUNT || ch_state[ch].status != HSD_ON) return 0;
    return mv_to_ma(ch_state[ch].mv);
}

uint8_t hsd_latched(void)
{
    uint8_t m = 0;
    for (uint8_t i = 0; i < HSD_COUNT; i++)
        if (ch_state[i].status == HSD_TRIPPED || ch_state[i].status == HSD_FAULT) m |= (uint8_t)(1 << i);
    return m;
}

void hsd_set_limit(uint8_t ch, uint16_t ma, uint16_t trip_ms)
{
    if (ch >= HSD_COUNT) return;
    ch_state[ch].limit_ma = ma;
    ch_state[ch].trip_ms  = trip_ms;
}

uint16_t hsd_limit_ma(uint8_t ch) { return ch < HSD_COUNT ? ch_state[ch].limit_ma : 0; }
uint16_t hsd_trip_ms(uint8_t ch)  { return ch < HSD_COUNT ? ch_state[ch].trip_ms : 0; }
