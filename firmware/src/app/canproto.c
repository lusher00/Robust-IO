#include <avr/io.h>
#include <string.h>
#include "board.h"
#include "version.h"
#include "hal/tick.h"
#include "drivers/mcp2515.h"
#include "drivers/hsd.h"
#include "drivers/motor.h"
#include "app/inputs.h"
#include "app/config.h"
#include "app/canproto.h"

#define ID_INPUTS     0x100
#define ID_OUTPUTS    0x110
#define ID_CURRENTS   0x120
#define ID_MOTORS     0x130
#define ID_HEARTBEAT  0x140
#define ID_SET_OUT    0x200
#define ID_SET_MOTOR  0x210
#define ID_CLEAR      0x220
#define ID_CONFIG     0x230
#define ID_CONFIG_REPLY 0x240

#define PERIOD_MS     100u
#define RETRY_MS      1000u
#define QLEN          8u

static bool     can_ok, host_active, timed_out;
static uint8_t  node, rst_cause, hb_div;
static uint32_t t_period, t_cmd, t_retry;
static can_frame_t q[QLEN];
static uint8_t  q_head, q_count;
static canproto_stats_t st;

static void enqueue(uint16_t id, uint8_t dlc, const uint8_t *d)
{
    if (q_count >= QLEN) { st.tx_dropped++; return; }
    can_frame_t *f = &q[(uint8_t)(q_head + q_count) % QLEN];
    f->id = (uint16_t)(id + node);
    f->dlc = dlc;
    memcpy(f->data, d, dlc);
    q_count++;
}

static void drain(void)
{
    while (q_count && mcp2515_send(&q[q_head])) {
        q_head = (uint8_t)(q_head + 1) % QLEN;
        q_count--;
        st.tx++;
    }
}

static uint8_t sat8(uint16_t v) { return v > 255 ? 255 : (uint8_t)v; }

static uint8_t state_flags(void)
{
    return (uint8_t)((host_active             ? 0x01 : 0) |
                     (timed_out               ? 0x02 : 0) |
                     (inputs_ok()             ? 0x04 : 0) |
                     (config_from_defaults()  ? 0x08 : 0) |
                     (motor_fault_latched()   ? 0x10 : 0) |
                     (hsd_latched()           ? 0x20 : 0));
}

static void send_inputs(void)
{
    uint32_t s = inputs_state();
    uint8_t d[4] = { (uint8_t)s, (uint8_t)(s >> 8), (uint8_t)(s >> 16),
                     (uint8_t)((inputs_ok() ? 0x01 : 0) | ((inputs_fault() & 0xFC) ? 0x02 : 0)) };
    enqueue(ID_INPUTS, 4, d);
}

static void send_outputs(void)
{
    uint8_t d[5] = { hsd_get(), 0, 0, 0, 0 };
    for (uint8_t i = 0; i < HSD_COUNT; i++) {
        uint8_t b = (uint8_t)(1 << i);
        switch (hsd_status(i)) {
        case HSD_ON:       d[1] |= b; break;
        case HSD_TRIPPED:  d[2] |= b; break;
        case HSD_FAULT:    d[3] |= b; break;
        case HSD_OFF_HIGH: d[4] |= b; break;
        default: break;
        }
    }
    enqueue(ID_OUTPUTS, 5, d);
}

static void send_currents(void)
{
    uint8_t d[8];
    for (uint8_t i = 0; i < HSD_COUNT; i++) d[i] = sat8((uint16_t)((hsd_ma(i) + 50u) / 100u));
    enqueue(ID_CURRENTS, 8, d);
}

static void send_motors(void)
{
    uint8_t d[6] = {
        (uint8_t)motor_actual(0), (uint8_t)motor_actual(1),
        sat8((uint16_t)((motor_current_ma(0) + 5u) / 10u)),
        sat8((uint16_t)((motor_current_ma(1) + 5u) / 10u)),
        (uint8_t)((motor_asleep() ? 0x01 : 0) | (motor_fault_latched() ? 0x02 : 0) | (motor_fault_pin() ? 0x04 : 0)),
        motor_fault_count()
    };
    enqueue(ID_MOTORS, 6, d);
}

static void send_heartbeat(void)
{
    uint8_t stat, eflg, tec, rec;
    mcp2515_stat(&stat, &eflg, &tec, &rec);
    uint8_t d[8] = { state_flags(), rst_cause, FW_VER_MAJOR, FW_VER_MINOR,
                     tec, rec, eflg, sat8(st.tx_dropped) };
    enqueue(ID_HEARTBEAT, 8, d);
}

static void host_seen(uint32_t now)
{
    host_active = true;
    timed_out = false;
    t_cmd = now;
}

static void handle(const can_frame_t *f, uint32_t now)
{
    uint16_t base = (uint16_t)(f->id - node);
    const uint8_t *d = f->data;

    if (f->id < node) base = 0;
    switch (base) {
    case ID_SET_OUT:
        if (f->dlc < 2) break;
        for (uint8_t i = 0; i < HSD_COUNT; i++)
            if (d[0] & (1 << i)) hsd_set(i, (uint8_t)((d[1] >> i) & 1));
        host_seen(now);
        st.rx++;
        return;
    case ID_SET_MOTOR:
        if (f->dlc < 2) break;
        motor_command(0, (int8_t)d[0]);
        motor_command(1, (int8_t)d[1]);
        host_seen(now);
        st.rx++;
        return;
    case ID_CLEAR:
        if (f->dlc < 1) break;
        hsd_clear(d[0]);
        if (f->dlc >= 2 && (d[1] & 1)) motor_clear_fault();
        st.rx++;
        return;
    case ID_CONFIG: {
        if (f->dlc < 2) break;
        uint8_t op = d[0], key = d[1], res = CFG_OK;
        uint16_t v = (f->dlc >= 4) ? (uint16_t)(d[2] | (d[3] << 8)) : 0;
        switch (op) {
        case 0:  res = config_get(key, &v); break;                     /* read */
        case 1:  res = config_set(key, v); if (res == CFG_OK) config_get(key, &v); break;  /* write */
        case 2:  res = config_save(); break;                           /* save */
        case 3:  config_defaults(); config_apply(); break;             /* defaults, RAM only */
        default: res = CFG_BAD_KEY; break;
        }
        uint8_t r[5] = { op, key, (uint8_t)v, (uint8_t)(v >> 8), res };
        enqueue(ID_CONFIG_REPLY, 5, r);
        st.rx++;
        return;
    }
    default:
        break;
    }
    st.rx_ignored++;
}

void canproto_init(uint8_t reset_cause)
{
    rst_cause = reset_cause;
    node = cfg.node;
    can_ok = mcp2515_init((can_rate_t)cfg.rate) && mcp2515_set_mode(CAN_MODE_NORMAL);
    t_period = t_retry = tick_ms();
}

void canproto_task(void)
{
    uint32_t now = tick_ms();

    if (!can_ok) {
        if ((uint32_t)(now - t_retry) >= RETRY_MS) {
            t_retry = now;
            can_ok = mcp2515_init((can_rate_t)cfg.rate) && mcp2515_set_mode(CAN_MODE_NORMAL);
        }
    } else {
        can_frame_t f;
        for (uint8_t i = 0; i < 4 && !(PIND & (1 << INT_CAN_BIT)) && mcp2515_receive(&f); i++)
            handle(&f, now);
    }

    /* Host timeout applies to CAN control only; console commands do not start it. */
    if (host_active && cfg.timeout_ms && (uint32_t)(now - t_cmd) >= cfg.timeout_ms) {
        hsd_all_off();
        motor_stop_all();
        host_active = false;
        timed_out = true;
        st.timeouts++;
    }

    if (!can_ok) return;

    if (inputs_take_change()) send_inputs();
    drain();                    /* load anything queued this pass before judging the backlog */

    if ((uint32_t)(now - t_period) >= PERIOD_MS) {
        t_period += PERIOD_MS;
        if ((uint32_t)(now - t_period) >= PERIOD_MS) t_period = now;   /* fell behind */
        /* Anything still queued after drain() means all three TX buffers have
         * been busy since the last period: the bus is not taking frames (no
         * other node acknowledging). Drop the backlog so data stays fresh. */
        if (q_count) {
            st.tx_dropped += q_count;
            q_count = 0;
            mcp2515_abort_tx();
        }
        send_inputs();
        send_outputs();
        send_currents();
        send_motors();
        if (++hb_div >= 10) { hb_div = 0; send_heartbeat(); }
    }
    drain();
}

bool canproto_ok(void)          { return can_ok; }
bool canproto_host_active(void) { return host_active; }
const canproto_stats_t *canproto_stats(void) { return &st; }
