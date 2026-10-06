#include <avr/io.h>
#include "board.h"
#include "hal/tick.h"
#include "drivers/mc33978.h"
#include "app/config.h"
#include "app/inputs.h"

#define POLL_MS   5u
#define CHECK_MS  1000u

static bool     ok, changed;
static uint32_t raw, cand, stable, fault;
static uint16_t t_change[MC33978_INPUTS];
static uint32_t t_poll, t_check, t_reinit;
static uint8_t  reinits;

static bool start(void)
{
    if (!mc33978_init()) return false;
    mc33978_set_wetting(cfg.wet_sp, cfg.wet_sg);
    return true;
}

void inputs_init(void)
{
    ok = start();
    if (ok) raw = cand = stable = mc33978_inputs();
    t_poll = t_check = t_reinit = tick_ms();
}

void inputs_apply_config(void)
{
    if (ok) mc33978_set_wetting(cfg.wet_sp, cfg.wet_sg);
}

static void reinit(uint32_t now)
{
    if ((uint32_t)(now - t_reinit) < CHECK_MS) return;
    t_reinit = now;
    if (reinits < 255) reinits++;
    ok = start();
}

static void debounce(uint32_t now)
{
    uint16_t n16 = (uint16_t)now;
    for (uint8_t i = 0; i < MC33978_INPUTS; i++) {
        uint32_t b = 1UL << i;
        if ((raw ^ cand) & b) {
            cand ^= b;
            t_change[i] = n16;
        } else if (((cand ^ stable) & b) && (uint16_t)(n16 - t_change[i]) >= cfg.debounce_ms) {
            stable ^= b;
            changed = true;
        }
    }
}

void inputs_task(void)
{
    uint32_t now = tick_ms();

    if ((uint32_t)(now - t_check) >= CHECK_MS) {
        t_check = now;
        bool was = ok;
        ok = mc33978_check();
        if (ok && !was) reinit(now);
    }
    if (!ok) return;

    bool irq = !(PINB & (1 << INT_IN_BIT));
    if (!irq && (uint32_t)(now - t_poll) < POLL_MS) return;
    t_poll = now;

    uint32_t r = mc33978_read(MC33978_STATUS_R);
    if (r & MC33978_FLAG_FAULT) {
        fault = mc33978_read(MC33978_FAULT_R);
        if (fault & MC33978_F_POR) reinit(now);
    }
    raw = r & MC33978_INPUT_MASK;
    debounce(now);
}

bool     inputs_ok(void)      { return ok; }
uint32_t inputs_state(void)   { return stable; }
uint32_t inputs_raw(void)     { return raw; }
uint32_t inputs_fault(void)   { return fault; }
uint8_t  inputs_reinits(void) { return reinits; }

bool inputs_take_change(void)
{
    bool c = changed;
    changed = false;
    return c;
}
