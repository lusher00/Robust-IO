#include <avr/io.h>
#include <avr/pgmspace.h>
#include "board.h"
#include "hal/spi.h"
#include "drivers/mc33978.h"

static const uint8_t wet_ma[8] PROGMEM = { 2, 6, 8, 10, 12, 14, 16, 20 };

/* 32-bit frames, MSB first. The response to a command is shifted out during
 * the following frame, so a register read takes two frames. */
uint32_t mc33978_xfer(uint32_t frame)
{
    uint32_t r = 0;
    spi_set_mode(MC33978_SPI_MODE);
    PORTB &= (uint8_t)~(1 << CS_IN_BIT);
    for (int8_t i = 3; i >= 0; i--)
        r = (r << 8) | spi_xfer((uint8_t)(frame >> (8 * i)));
    PORTB |= (1 << CS_IN_BIT);
    return r;
}

uint32_t mc33978_read(uint8_t cmd)
{
    mc33978_xfer((uint32_t)cmd << 24);
    return mc33978_xfer((uint32_t)cmd << 24) & 0x00FFFFFFUL;
}

void mc33978_write(uint8_t cmd, uint32_t data)
{
    mc33978_xfer(((uint32_t)cmd << 24) | (data & 0x00FFFFFFUL));
}

bool mc33978_check(void)
{
    mc33978_xfer((uint32_t)MC33978_SPI_CHECK << 24);
    uint32_t id = mc33978_xfer((uint32_t)MC33978_STATUS_R << 24) & 0x00FFFFFFUL;
    return id == MC33978_CHECK_VALUE;
}

bool mc33978_init(void)
{
    if (!mc33978_check()) return false;

    /* SP0..SP7 power up as switch-to-battery (config bits 7..0 = 1).
     * Rev A hardware only supports switch-to-ground on these pins (each input
     * has an LED and 2.2k from +24V), so clear them. Bits 9..8 stay 00 (AMUX
     * selected over SPI); the other bits keep their power-on values. */
    uint32_t cfg = mc33978_read(MC33978_CONFIG_R) & 0x003FFFUL;
    mc33978_write(MC33978_CONFIG_W, cfg & ~0x3FFUL);

    /* Interrupt on change for every input (power-on default, written explicitly). */
    mc33978_write(MC33978_INT_SP_W, 0x0000FFUL);
    mc33978_write(MC33978_INT_SG_W, 0x003FFFUL);
    return true;
}

uint32_t mc33978_inputs(void)
{
    return mc33978_read(MC33978_STATUS_R) & MC33978_INPUT_MASK;
}

static uint32_t repeat3(uint8_t code, uint8_t first, uint8_t count)
{
    uint32_t v = 0;
    for (uint8_t i = first; i < first + count; i++) v |= (uint32_t)(code & 7) << (3 * i);
    return v;
}

void mc33978_set_wetting(uint8_t sp_code, uint8_t sg_code)
{
    mc33978_write(MC33978_WET_SP_W,  repeat3(sp_code, 0, 8));   /* SP0..SP7  bits 2..0 .. 23..21 */
    mc33978_write(MC33978_WET_SG0_W, repeat3(sg_code, 0, 8));   /* SG0..SG7  bits 2..0 .. 23..21 */
    mc33978_write(MC33978_WET_SG1_W, repeat3(sg_code, 1, 6));   /* SG8..SG13 bits 5..3 .. 20..18 */
}

void mc33978_set_amux(uint8_t code)
{
    mc33978_write(MC33978_AMUX_W, code & 0x3F);
}

uint8_t mc33978_ma_to_code(uint8_t ma)
{
    for (uint8_t i = 0; i < 8; i++) if (pgm_read_byte(&wet_ma[i]) == ma) return i;
    return 0xFF;
}

uint8_t mc33978_code_to_ma(uint8_t code)
{
    return pgm_read_byte(&wet_ma[code & 7]);
}
