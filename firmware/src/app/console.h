#ifndef CONSOLE_H
#define CONSOLE_H
#include <stdint.h>
void    console_init(uint8_t reset_cause);
void    console_task(void);
uint8_t console_reset_requested(void);
#endif
