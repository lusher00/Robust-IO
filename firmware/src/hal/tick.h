#ifndef TICK_H
#define TICK_H
#include <stdint.h>
void     tick_init(void);
uint32_t tick_ms(void);
void     delay_ms(uint16_t ms);          /* busy wait on the tick; start-up and console tests only */
#endif
