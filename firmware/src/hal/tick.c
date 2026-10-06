#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/atomic.h>
#include "board.h"
#include "hal/tick.h"

/* Timer0 CTC, prescaler 64: 187500 counts/s, so 1 ms is 187.5 counts.
 * The period alternates between 187 and 188 counts, giving exactly 2 ms per two ticks. */
static volatile uint32_t ticks;

ISR(TIMER0_COMPA_vect)
{
    ticks++;
    OCR0A = (OCR0A == 186) ? 187 : 186;
}

void tick_init(void)
{
    TCCR0A = (1 << WGM01);
    OCR0A  = 186;
    TIMSK0 = (1 << OCIE0A);
    TCCR0B = (1 << CS01) | (1 << CS00);
}

uint32_t tick_ms(void)
{
    uint32_t t;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { t = ticks; }
    return t;
}

void delay_ms(uint16_t ms)
{
    uint32_t t0 = tick_ms();
    while ((uint32_t)(tick_ms() - t0) <= ms) { }
}
