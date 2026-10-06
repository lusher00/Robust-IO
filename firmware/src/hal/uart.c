#include <avr/io.h>
#include <avr/interrupt.h>
#include "board.h"
#include "hal/uart.h"

#define RX_SIZE 64u
#define TX_SIZE 128u                     /* powers of two */

static volatile uint8_t rx_buf[RX_SIZE], rx_head, rx_tail;
static volatile uint8_t tx_buf[TX_SIZE], tx_head, tx_tail;

ISR(USART0_RX_vect)
{
    uint8_t c = UDR0;
    uint8_t next = (uint8_t)(rx_head + 1) & (RX_SIZE - 1);
    if (next != rx_tail) { rx_buf[rx_head] = c; rx_head = next; }
}

ISR(USART0_UDRE_vect)
{
    if (tx_head == tx_tail) {
        UCSR0B &= (uint8_t)~(1 << UDRIE0);
    } else {
        UDR0 = tx_buf[tx_tail];
        tx_tail = (uint8_t)(tx_tail + 1) & (TX_SIZE - 1);
    }
}

static int uart_put(char c, FILE *f)
{
    (void)f;
    if (c == '\n') uart_putc('\r');
    uart_putc(c);
    return 0;
}

FILE uart_stdout = FDEV_SETUP_STREAM(uart_put, NULL, _FDEV_SETUP_WRITE);

void uart_init(void)
{
    /* U2X: 12 MHz / (8 * 115200) - 1 = 12.02 -> 12, error 0.16 % */
    UCSR0A = (1 << U2X0);
    UBRR0  = (uint16_t)((F_CPU + 4UL * UART_BAUD) / (8UL * UART_BAUD) - 1UL);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
    UCSR0B = (1 << RXEN0) | (1 << TXEN0) | (1 << RXCIE0);
    stdout = &uart_stdout;
}

int uart_getc(void)
{
    if (rx_head == rx_tail) return -1;
    uint8_t c = rx_buf[rx_tail];
    rx_tail = (uint8_t)(rx_tail + 1) & (RX_SIZE - 1);
    return c;
}

void uart_putc(char c)
{
    uint8_t next = (uint8_t)(tx_head + 1) & (TX_SIZE - 1);
    while (next == tx_tail) { }          /* wait for the ISR to make room */
    tx_buf[tx_head] = (uint8_t)c;
    tx_head = next;
    UCSR0B |= (1 << UDRIE0);
}

void uart_flush(void)
{
    while (tx_head != tx_tail) { }
    while (!(UCSR0A & (1 << UDRE0))) { }
}
