#include <avr/io.h>
#include <avr/pgmspace.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "version.h"
#include "hal/uart.h"
#include "hal/adc.h"
#include "hal/tick.h"
#include "drivers/mc33978.h"
#include "drivers/mcp2515.h"
#include "drivers/hsd.h"
#include "drivers/motor.h"
#include "app/config.h"
#include "app/inputs.h"
#include "app/canproto.h"
#include "app/selftest.h"
#include "app/console.h"

#define LINE_MAX 64
#define ARG_MAX  12

static char     line[LINE_MAX];
static uint8_t  len;
static uint8_t  rst_cause, want_reset, watch;
static uint32_t watch_last;

uint8_t console_reset_requested(void) { return want_reset; }

static bool is(const char *a, PGM_P b) { return !strcmp_P(a, b); }

static void print_bits(uint32_t v)
{
    printf_P(PSTR("SG13..0 "));
    for (int8_t i = 13; i >= 0; i--) putchar((v >> i) & 1 ? '1' : '0');
    printf_P(PSTR("  SP7..0 "));
    for (int8_t i = 21; i >= 14; i--) putchar((v >> i) & 1 ? '1' : '0');
}

static void cmd_ver(void)
{
    printf_P(PSTR("Robust IO rev A, firmware %u.%u (%s)\n"), FW_VER_MAJOR, FW_VER_MINOR, FW_VERSION);
    printf_P(PSTR("reset cause:%S%S%S%S%S\n"),
             (rst_cause & (1 << PORF))  ? PSTR(" power-on") : PSTR(""),
             (rst_cause & (1 << EXTRF)) ? PSTR(" external") : PSTR(""),
             (rst_cause & (1 << BORF))  ? PSTR(" brown-out") : PSTR(""),
             (rst_cause & (1 << WDRF))  ? PSTR(" watchdog") : PSTR(""),
             (rst_cause & (1 << JTRF))  ? PSTR(" jtag") : PSTR(""));
    printf_P(PSTR("MC33978 %S, MCP2515 %S, config from %S\n"),
             inputs_ok()    ? PSTR("ok") : PSTR("NOT RESPONDING"),
             canproto_ok()  ? PSTR("ok") : PSTR("NOT RESPONDING"),
             config_from_defaults() ? PSTR("defaults") : PSTR("EEPROM"));
    uint16_t rate;
    config_get(CFG_RATE, &rate);
    printf_P(PSTR("CAN node %u at %u kbit/s, uptime %lu s\n"), cfg.node, rate, tick_ms() / 1000UL);
}

static void cmd_help(void)
{
    printf_P(PSTR(
        "ver                       version, reset cause, device check\n"
        "in                        debounced and raw inputs\n"
        "in watch                  print inputs on change (any key stops)\n"
        "in raw <cmd-hex>          read one MC33978 register\n"
        "amux [code]               select AMUX channel (6 temp, 7 battery) and read mV\n"
        "out <0-7> <0|1>           switch one output\n"
        "out all 0                 all outputs off\n"
        "out clear                 clear latched output trips and faults\n"
        "isense                    state, sense voltage and current per output\n"
        "limit <0-7|all> <mA> [ms] trip level and time (cfg save to keep)\n"
        "motor <0|1> <-100..100>   command duty in percent, ramped\n"
        "motor off                 stop both now, drivers asleep\n"
        "motor clear               clear a latched driver fault\n"
        "motor                     status\n"
        "can                       status and counters\n"
        "can loop                  loopback self-test\n"
        "can tx <id-hex> [bytes]   send a standard frame\n"
        "cfg                       show settings\n"
        "cfg <name> <value>        change a setting (node and rate apply after reset)\n"
        "cfg save | cfg default    write to EEPROM | load defaults (not saved)\n"
        "selftest [out] [motor]    bring-up checks; 'out' pulses each output,\n"
        "                          'motor' runs each motor at 20 %% both ways\n"
        "reset                     reset through the watchdog\n"));
}

static void cmd_in(uint8_t argc, char **argv)
{
    if (argc >= 2 && is(argv[1], PSTR("watch"))) {
        watch = 1; watch_last = 0xFFFFFFFFUL;
        return;
    }
    if (argc >= 3 && is(argv[1], PSTR("raw"))) {
        uint8_t c = (uint8_t)strtoul(argv[2], NULL, 16);
        printf_P(PSTR("%02X: %06lX\n"), c, mc33978_read(c));
        return;
    }
    if (!inputs_ok()) printf_P(PSTR("MC33978 not responding, values are stale\n"));
    printf_P(PSTR("debounced "));  print_bits(inputs_state()); putchar('\n');
    printf_P(PSTR("raw       "));  print_bits(inputs_raw());   printf_P(PSTR("  (1 = closed)\n"));
    printf_P(PSTR("fault status %06lX, re-inits %u\n"), inputs_fault(), inputs_reinits());
}

static void cmd_amux(uint8_t argc, char **argv)
{
    if (argc >= 2) {
        mc33978_set_amux((uint8_t)atoi(argv[1]));
        delay_ms(2);
    }
    printf_P(PSTR("AMUX %u mV\n"), adc_read_mv(ADC_CH_AMUX));
}

static PGM_P status_name(hsd_status_t s)
{
    switch (s) {
    case HSD_OFF:      return PSTR("off");
    case HSD_OFF_HIGH: return PSTR("off, output HIGH");
    case HSD_ON:       return PSTR("on");
    case HSD_TRIPPED:  return PSTR("TRIPPED (over limit)");
    default:           return PSTR("FAULT (device)");
    }
}

static void cmd_out(uint8_t argc, char **argv)
{
    if (argc >= 2 && is(argv[1], PSTR("clear"))) {
        hsd_clear(0xFF);
    } else if (argc >= 3 && is(argv[1], PSTR("all"))) {
        if (atoi(argv[2])) printf_P(PSTR("only 'out all 0' is supported\n"));
        else hsd_all_off();
    } else if (argc >= 3) {
        if (!hsd_set((uint8_t)atoi(argv[1]), (uint8_t)atoi(argv[2])))
            printf_P(PSTR("refused: channel is latched off or out of range, see 'isense' and 'out clear'\n"));
    }
    printf_P(PSTR("outputs 7..0: "));
    for (int8_t i = 7; i >= 0; i--) putchar((hsd_get() >> i) & 1 ? '1' : '0');
    if (hsd_latched()) printf_P(PSTR("  latched mask %02X"), hsd_latched());
    putchar('\n');
}

static void cmd_isense(void)
{
    for (uint8_t ch = 0; ch < HSD_COUNT; ch++)
        printf_P(PSTR("out%u  %4u mV  %5u mA  limit %u mA / %u ms  %S\n"), ch,
                 hsd_mv(ch), hsd_ma(ch), hsd_limit_ma(ch), hsd_trip_ms(ch),
                 status_name(hsd_status(ch)));
}

static void cmd_limit(uint8_t argc, char **argv)
{
    if (argc >= 3) {
        uint8_t all = is(argv[1], PSTR("all"));
        for (uint8_t ch = 0; ch < HSD_COUNT; ch++) {
            if (!all && ch != (uint8_t)atoi(argv[1])) continue;
            if (config_set((uint8_t)(CFG_LIMIT0 + ch), (uint16_t)atol(argv[2])) != CFG_OK ||
                (argc >= 4 && config_set((uint8_t)(CFG_TRIP0 + ch), (uint16_t)atol(argv[3])) != CFG_OK)) {
                printf_P(PSTR("bad value: limit 100..30000 mA, time 0..10000 ms\n"));
                return;
            }
        }
    }
    cmd_isense();
}

static void cmd_motor(uint8_t argc, char **argv)
{
    if (argc >= 2 && is(argv[1], PSTR("off"))) {
        motor_stop_all();
    } else if (argc >= 2 && is(argv[1], PSTR("clear"))) {
        motor_clear_fault();
    } else if (argc >= 3) {
        if (!motor_command((uint8_t)atoi(argv[1]), (int8_t)atoi(argv[2])))
            printf_P(PSTR("refused: driver fault latched, use 'motor clear'\n"));
    }
    for (uint8_t m = 0; m < 2; m++)
        printf_P(PSTR("m%u  target %4d %%  actual %4d %%  %u mA\n"), m,
                 motor_target(m), motor_actual(m), motor_current_ma(m));
    printf_P(PSTR("drivers %S, fault pin %S, latched %S, faults %u"),
             motor_asleep() ? PSTR("asleep") : PSTR("awake"),
             motor_fault_pin() ? PSTR("LOW") : PSTR("high"),
             motor_fault_latched() ? PSTR("YES") : PSTR("no"), motor_fault_count());
    if (motor_fault_count())
        printf_P(PSTR(" (last at m0 %u mA, m1 %u mA)"), motor_fault_ma(0), motor_fault_ma(1));
    printf_P(PSTR("\nregulation limit %u mA (hardware)\n"), MOTOR_ITRIP_MA);
}

static void cmd_can(uint8_t argc, char **argv)
{
    if (argc >= 2 && is(argv[1], PSTR("loop"))) {
        printf_P(PSTR("can loopback %S\n"), mcp2515_loopback_test() ? PSTR("PASS") : PSTR("FAIL"));
        return;
    }
    if (argc >= 3 && is(argv[1], PSTR("tx"))) {
        can_frame_t f = { .id = (uint16_t)(strtoul(argv[2], NULL, 16) & 0x7FF) };
        for (uint8_t i = 3; i < argc && f.dlc < 8; i++)
            f.data[f.dlc++] = (uint8_t)strtoul(argv[i], NULL, 16);
        printf_P(PSTR("%S\n"), mcp2515_send(&f) ? PSTR("queued") : PSTR("all TX buffers busy"));
        return;
    }
    uint8_t s, e, tec, rec;
    uint16_t rate;
    const canproto_stats_t *c = canproto_stats();
    config_get(CFG_RATE, &rate);
    mcp2515_stat(&s, &e, &tec, &rec);
    printf_P(PSTR("node %u, %u kbit/s, controller %S\n"), cfg.node, rate,
             canproto_ok() ? PSTR("ok") : PSTR("NOT RESPONDING"));
    printf_P(PSTR("CANSTAT %02X  EFLG %02X  TEC %u  REC %u  TX busy %u\n"), s, e, tec, rec, mcp2515_tx_busy());
    printf_P(PSTR("rx %u  ignored %u  tx %u  dropped %u\n"), c->rx, c->rx_ignored, c->tx, c->tx_dropped);
    printf_P(PSTR("host %S, timeout %u ms, timeouts %u\n"),
             canproto_host_active() ? PSTR("active") : PSTR("inactive"), cfg.timeout_ms, c->timeouts);
}

static void cmd_cfg(uint8_t argc, char **argv)
{
    if (argc == 2 && is(argv[1], PSTR("save"))) {
        printf_P(PSTR("%S\n"), config_save() == CFG_OK ? PSTR("saved") : PSTR("EEPROM write FAILED"));
        return;
    }
    if (argc == 2 && is(argv[1], PSTR("default"))) {
        config_defaults();
        config_apply();
        printf_P(PSTR("defaults loaded, not saved\n"));
        return;
    }
    if (argc >= 3) {
        uint8_t key;
        if (!config_key_by_name(argv[1], &key)) { printf_P(PSTR("unknown setting\n")); return; }
        uint8_t r = config_set(key, (uint16_t)atol(argv[2]));
        if (r != CFG_OK) { printf_P(PSTR("bad value\n")); return; }
        if (key == CFG_NODE || key == CFG_RATE) printf_P(PSTR("applies after 'cfg save' and reset\n"));
    }
    config_print();
}

static void execute(void)
{
    char *argv[ARG_MAX];
    uint8_t argc = 0;
    for (char *t = strtok(line, " "); t && argc < ARG_MAX; t = strtok(NULL, " ")) argv[argc++] = t;
    if (argc == 0) return;
    const char *c = argv[0];

    if      (is(c, PSTR("help")))   cmd_help();
    else if (is(c, PSTR("ver")))    cmd_ver();
    else if (is(c, PSTR("in")))     cmd_in(argc, argv);
    else if (is(c, PSTR("amux")))   cmd_amux(argc, argv);
    else if (is(c, PSTR("out")))    cmd_out(argc, argv);
    else if (is(c, PSTR("isense"))) cmd_isense();
    else if (is(c, PSTR("limit")))  cmd_limit(argc, argv);
    else if (is(c, PSTR("motor")))  cmd_motor(argc, argv);
    else if (is(c, PSTR("can")))    cmd_can(argc, argv);
    else if (is(c, PSTR("cfg")))    cmd_cfg(argc, argv);
    else if (is(c, PSTR("selftest"))) {
        uint8_t o = 0, m = 0;
        for (uint8_t i = 1; i < argc; i++) {
            if (is(argv[i], PSTR("out")))   o = 1;
            if (is(argv[i], PSTR("motor"))) m = 1;
        }
        selftest_run(o, m);
    }
    else if (is(c, PSTR("reset")))  want_reset = 1;
    else printf_P(PSTR("unknown command, try help\n"));
}

void console_init(uint8_t reset_cause)
{
    rst_cause = reset_cause;
    putchar('\n');
    cmd_ver();
    printf_P(PSTR("> "));
}

void console_task(void)
{
    int ch = uart_getc();

    if (watch) {
        if (ch >= 0) { watch = 0; printf_P(PSTR("> ")); return; }
        uint32_t v = inputs_state();
        if (v != watch_last) { watch_last = v; print_bits(v); putchar('\n'); }
        return;
    }
    if (ch < 0) return;

    if (ch == '\r' || ch == '\n') {
        putchar('\n');
        line[len] = 0;
        execute();
        len = 0;
        if (!watch) printf_P(PSTR("> "));
    } else if (ch == 0x08 || ch == 0x7F) {
        if (len) { len--; printf_P(PSTR("\b \b")); }
    } else if (ch >= 0x20 && len < LINE_MAX - 1) {
        line[len++] = (char)ch;
        uart_putc((char)ch);
    }
}
