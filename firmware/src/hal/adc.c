#include <avr/io.h>
#include "board.h"
#include "hal/adc.h"

void adc_init(void)
{
    DIDR0  = 0x0F;                                   /* PA0..PA3 are analog */
    ADMUX  = (1 << REFS0);                           /* AVCC reference */
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);   /* 93.75 kHz */
}

uint16_t adc_read(uint8_t ch)
{
    ADMUX = (1 << REFS0) | (ch & 0x07);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC)) { }
    return ADC;
}

uint16_t adc_read_mv(uint8_t ch)
{
    return (uint16_t)(((uint32_t)adc_read(ch) * ADC_VREF_MV + 511) / 1023);
}
