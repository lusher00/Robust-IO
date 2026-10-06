/* Robust IO rev A firmware.
 * Foreground loop, 1 ms tick, UART console on J20, CAN protocol. See ../DESIGN.md. */
#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/wdt.h>
#include "board.h"
#include "hal/tick.h"
#include "hal/uart.h"
#include "hal/spi.h"
#include "hal/adc.h"
#include "drivers/hsd.h"
#include "drivers/motor.h"
#include "app/config.h"
#include "app/inputs.h"
#include "app/canproto.h"
#include "app/console.h"

static uint8_t reset_cause __attribute__((section(".noinit")));

/* Runs before C start-up: put every pin in the safe state, record why we
 * reset, and stop the watchdog so a watchdog reset cannot loop. */
void early_init(void) __attribute__((naked, used, section(".init3")));
void early_init(void)
{
    PORTC = PORTC_INIT; DDRC = DDRC_INIT;        /* outputs off first */
    PORTA = PORTA_INIT; DDRA = DDRA_INIT;
    PORTD = PORTD_INIT; DDRD = DDRD_INIT;
    PORTB = PORTB_INIT; DDRB = DDRB_INIT;

    reset_cause = MCUSR;
    MCUSR = 0;
    wdt_disable();

    /* PC2..PC5 are JTAG pins. The fuse should already disable JTAG; this is
     * the second guard. JTD must be written twice within four cycles. */
    MCUCR |= (1 << JTD);
    MCUCR |= (1 << JTD);
}

int main(void)
{
    config_load();

    tick_init();
    uart_init();
    spi_init();
    adc_init();
    motor_init();
    hsd_init();
    sei();

    delay_ms(20);                                 /* let the MC33978 and MCP2515 leave reset */
    inputs_init();
    config_apply();
    canproto_init(reset_cause);

    console_init(reset_cause);
    wdt_enable(WDTO_250MS);

    for (;;) {
        if (!console_reset_requested()) wdt_reset();
        console_task();
        hsd_task();
        motor_task();
        inputs_task();
        canproto_task();
    }
}
