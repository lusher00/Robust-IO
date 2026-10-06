#include <avr/io.h>
#include <avr/pgmspace.h>
#include <avr/wdt.h>
#include <stdio.h>
#include "board.h"
#include "hal/adc.h"
#include "hal/tick.h"
#include "hal/uart.h"
#include "drivers/mc33978.h"
#include "drivers/mcp2515.h"
#include "drivers/hsd.h"
#include "drivers/motor.h"
#include "app/inputs.h"
#include "app/selftest.h"

static uint8_t passed, failed;

/* Wait while keeping the sense scan and the watchdog running. */
static void wait_ms(uint16_t ms)
{
    uint32_t t0 = tick_ms();
    while ((uint32_t)(tick_ms() - t0) < ms) { hsd_task(); motor_task(); inputs_task(); wdt_reset(); }
}

static void wait_scans(uint8_t n)
{
    uint16_t s0 = hsd_scans();
    while ((uint16_t)(hsd_scans() - s0) < n) { hsd_task(); motor_task(); inputs_task(); wdt_reset(); }
}

static void result(uint8_t ok, PGM_P name)
{
    if (ok) passed++; else failed++;
    printf_P(PSTR("%S  %S\n"), ok ? PSTR("PASS") : PSTR("FAIL"), name);
    uart_flush();
    wdt_reset();
}

static void test_inputs(void)
{
    uint8_t ok = mc33978_check();
    result(ok, PSTR("MC33978 SPI check (expects 123456)"));
    if (!ok) return;

    uint32_t cfg = mc33978_read(MC33978_CONFIG_R);
    result((cfg & 0xFF) == 0, PSTR("MC33978 SP0..7 set to switch-to-ground"));
    printf_P(PSTR("      config %06lX  fault status %06lX  inputs %06lX\n"),
             cfg, mc33978_read(MC33978_FAULT_R), mc33978_inputs());
}

static void test_can(void)
{
    result(mcp2515_loopback_test(), PSTR("MCP2515 loopback"));
}

static void test_outputs_off(void)
{
    hsd_all_off();
    wait_scans(2);
    uint8_t ok = 1;
    for (uint8_t ch = 0; ch < HSD_COUNT; ch++) {
        if (hsd_status(ch) != HSD_OFF) {
            ok = 0;
            printf_P(PSTR("      out%u: %u mV on the sense line with the output off\n"), ch, hsd_mv(ch));
        }
    }
    result(ok, PSTR("outputs off, sense line quiet on all 8 channels"));
}

static void test_motor_idle(void)
{
    motor_stop_all();
    motor_clear_fault();
    motor_hold_awake(true);
    wait_ms(20);
    uint8_t awake = !motor_asleep();
    uint8_t fault = motor_fault_pin() || motor_fault_latched();
    uint16_t i0 = motor_current_ma(0), i1 = motor_current_ma(1);
    motor_hold_awake(false);
    motor_stop_all();
    result(awake && !fault, PSTR("DRV8876 awake, fault pin clear"));
    result(i0 < 70 && i1 < 70, PSTR("DRV8876 idle current reads near zero"));
    printf_P(PSTR("      m0 %u mA, m1 %u mA\n"), i0, i1);
}

static void test_outputs_on(void)
{
    hsd_clear(0xFF);
    for (uint8_t ch = 0; ch < HSD_COUNT; ch++) {
        hsd_set(ch, 1);
        wait_ms(200);
        hsd_status_t st = hsd_status(ch);
        uint16_t mv = hsd_mv(ch), ma = hsd_ma(ch);
        hsd_set(ch, 0);
        wait_ms(50);
        printf_P(PSTR("      out%u: %u mV, %u mA\n"), ch, mv, ma);
        result(st == HSD_ON, PSTR("output switched on without a fault or trip"));
    }
}

static void test_motors_run(void)
{
    for (uint8_t m = 0; m < 2; m++) {
        for (int8_t dir = 1; dir >= -1; dir -= 2) {
            motor_command(m, (int8_t)(20 * dir));
            wait_ms(300);
            uint16_t ma = motor_current_ma(m);
            uint8_t ok = !motor_fault_latched() && motor_actual(m) == 20 * dir;
            motor_command(m, 0);
            wait_ms(200);
            printf_P(PSTR("      motor %u at %d %%: %u mA\n"), m, 20 * dir, ma);
            result(ok, PSTR("motor ran without a driver fault"));
            if (motor_fault_latched()) { motor_stop_all(); return; }
        }
    }
    motor_stop_all();
}

uint8_t selftest_run(uint8_t with_outputs, uint8_t with_motors)
{
    passed = failed = 0;
    printf_P(PSTR("selftest: basic%S%S\n"),
             with_outputs ? PSTR(" + outputs") : PSTR(""),
             with_motors  ? PSTR(" + motors")  : PSTR(""));

    test_inputs();
    test_can();
    test_outputs_off();
    test_motor_idle();
    printf_P(PSTR("      AMUX %u mV\n"), adc_read_mv(ADC_CH_AMUX));
    if (with_outputs) test_outputs_on();
    if (with_motors)  test_motors_run();

    printf_P(PSTR("selftest: %u passed, %u failed\n"), passed, failed);
    return failed;
}
