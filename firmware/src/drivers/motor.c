#include <avr/io.h>
#include "board.h"
#include "hal/adc.h"
#include "hal/tick.h"
#include "drivers/motor.h"

#define WAKE_MS   2u        /* datasheet tWAKE max 1 ms */
#define STEP_MS   10u

static int8_t   target[2], actual[2];
static bool     awake, latched, hold;
static uint8_t  fault_count;
static uint16_t fault_ma[2];
static uint8_t  slew = CFG_DEFAULT_SLEW;
static uint16_t idle_ms = CFG_DEFAULT_IDLE_MS;
static uint32_t t_wake, t_idle, t_step;

/* Phase-correct 8-bit PWM, no prescaler: 12 MHz / 510 = 23.5 kHz.
 * Motor 0: EN on OC1A (PD5), PH on PD4. Motor 1: EN on OC2A (PD7), PH on PD6.
 * EN low = brake (both low-side on). */
static void hw_duty(uint8_t m, int8_t percent)
{
    uint8_t mag  = (uint8_t)(percent < 0 ? -percent : percent);
    uint8_t duty = (uint8_t)(((uint16_t)mag * 255u) / 100u);
    uint8_t ph   = (m == 0) ? PH_M0_BIT : PH_M1_BIT;
    if (percent < 0) PORTD &= (uint8_t)~(1 << ph);
    else             PORTD |= (uint8_t)(1 << ph);
    if (m == 0) OCR1A = duty;
    else        OCR2A = duty;
}

static void hw_sleep(bool asleep)
{
    if (asleep) PORTA &= (uint8_t)~(1 << NSLEEP_BIT);
    else        PORTA |= (1 << NSLEEP_BIT);
}

void motor_init(void)
{
    OCR1A  = 0;
    TCCR1A = (1 << COM1A1) | (1 << WGM10);
    TCCR1B = (1 << CS10);
    OCR2A  = 0;
    TCCR2A = (1 << COM2A1) | (1 << WGM20);
    TCCR2B = (1 << CS20);
    hw_sleep(true);
}

void motor_config(uint8_t s, uint16_t idle)
{
    slew = (s == 0) ? 1 : (s > 100 ? 100 : s);
    idle_ms = idle;
}

bool motor_command(uint8_t m, int8_t percent)
{
    if (m > 1) return false;
    if (latched) return false;
    if (percent > 100)  percent = 100;
    if (percent < -100) percent = -100;
    target[m] = percent;
    return true;
}

void motor_stop_all(void)
{
    target[0] = target[1] = actual[0] = actual[1] = 0;
    hw_duty(0, 0); hw_duty(1, 0);
    hw_sleep(true);
    awake = false;
}

void motor_hold_awake(bool on) { hold = on; }

void motor_clear_fault(void)
{
    /* The drivers were put to sleep when the fault latched, which clears them. */
    latched = false;
}

static int8_t step_toward(int8_t a, int8_t t)
{
    int16_t d = (int16_t)t - a;
    if (d >  slew) d =  slew;
    if (d < -slew) d = -slew;
    return (int8_t)(a + d);
}

void motor_task(void)
{
    uint32_t now = tick_ms();

    if (awake && (uint32_t)(now - t_wake) >= WAKE_MS && motor_fault_pin()) {
        if (!latched) {
            fault_ma[0] = motor_current_ma(0);
            fault_ma[1] = motor_current_ma(1);
            if (fault_count < 255) fault_count++;
            latched = true;
        }
        motor_stop_all();
        return;
    }
    if (latched) return;

    bool want = target[0] || target[1] || actual[0] || actual[1] || hold;
    if (want && !awake) {
        hw_sleep(false);
        awake = true;
        t_wake = t_idle = t_step = now;
        return;
    }
    if (!awake || (uint32_t)(now - t_wake) < WAKE_MS) return;

    if ((uint32_t)(now - t_step) >= STEP_MS) {
        t_step = now;
        for (uint8_t m = 0; m < 2; m++) {
            if (actual[m] != target[m]) {
                actual[m] = step_toward(actual[m], target[m]);
                hw_duty(m, actual[m]);
            }
        }
    }

    if (want) {
        t_idle = now;
    } else if ((uint32_t)(now - t_idle) >= idle_ms) {
        hw_sleep(true);
        awake = false;
    }
}

int8_t   motor_target(uint8_t m)       { return m < 2 ? target[m] : 0; }
int8_t   motor_actual(uint8_t m)       { return m < 2 ? actual[m] : 0; }
bool     motor_asleep(void)            { return !awake; }
bool     motor_fault_pin(void)         { return !(PIND & (1 << FAULTM_BIT)); }
bool     motor_fault_latched(void)     { return latched; }
uint8_t  motor_fault_count(void)       { return fault_count; }
uint16_t motor_fault_ma(uint8_t m)     { return m < 2 ? fault_ma[m] : 0; }

uint16_t motor_current_ma(uint8_t m)
{
    uint16_t mv = adc_read_mv(m == 0 ? ADC_CH_IPROPI0 : ADC_CH_IPROPI1);
    return (uint16_t)((uint32_t)mv * 1000UL / IPROPI_R_OHM);
}
