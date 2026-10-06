#ifndef UART_H
#define UART_H
#include <stdint.h>
#include <stdio.h>
void uart_init(void);
int  uart_getc(void);                    /* -1 if nothing received */
void uart_putc(char c);                  /* blocks only when the TX buffer is full */
void uart_flush(void);
extern FILE uart_stdout;                 /* printf goes here after uart_init() */
#endif
