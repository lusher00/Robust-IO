#ifndef INPUTS_H
#define INPUTS_H
#include <stdint.h>
#include <stdbool.h>
/* MC33978 switch inputs: polled every 5 ms and whenever INT_B is low,
 * debounced per input, health-checked once a second, re-initialised after
 * a device power-on reset or a lost SPI check. Bit n: 0..13 = SG0..SG13,
 * 14..21 = SP0..SP7, 1 = switch closed. */
void     inputs_init(void);
void     inputs_task(void);
void     inputs_apply_config(void);
bool     inputs_ok(void);
uint32_t inputs_state(void);         /* debounced */
uint32_t inputs_raw(void);           /* last read */
bool     inputs_take_change(void);   /* true once after the debounced state changes */
uint32_t inputs_fault(void);         /* last fault status register read */
uint8_t  inputs_reinits(void);
#endif
