#include <avr/io.h>
#include "board.h"
#include "hal/spi.h"

/* Master, MSB first, F_CPU/4 = 3 MHz. PB4 (SS) is an output (DEN1), so the
 * controller cannot be forced into slave mode. Foreground use only. */
void spi_init(void)
{
    SPCR = (1 << SPE) | (1 << MSTR);
    SPSR = 0;
}

void spi_set_mode(uint8_t mode)
{
    uint8_t r = (1 << SPE) | (1 << MSTR);
    if (mode & 2) r |= (1 << CPOL);
    if (mode & 1) r |= (1 << CPHA);
    SPCR = r;
}

uint8_t spi_xfer(uint8_t out)
{
    SPDR = out;
    while (!(SPSR & (1 << SPIF))) { }
    return SPDR;
}
