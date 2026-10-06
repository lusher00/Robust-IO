#ifndef SPI_H
#define SPI_H
#include <stdint.h>
void    spi_init(void);
void    spi_set_mode(uint8_t mode);      /* 0..3, clock is F_CPU/4 */
uint8_t spi_xfer(uint8_t out);
#endif
