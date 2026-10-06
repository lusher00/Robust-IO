#ifndef ADC_H
#define ADC_H
#include <stdint.h>
void     adc_init(void);
uint16_t adc_read(uint8_t ch);           /* 0..1023, blocking, about 0.14 ms */
uint16_t adc_read_mv(uint8_t ch);
#endif
