#ifndef MC33978_H
#define MC33978_H
#include <stdint.h>
#include <stdbool.h>

/* Command bytes (bits 31..24 of the 32-bit frame; bit 24 is the write bit). */
#define MC33978_SPI_CHECK      0x00
#define MC33978_CONFIG_R       0x02
#define MC33978_CONFIG_W       0x03
#define MC33978_WET_SP_W       0x09
#define MC33978_WET_SG0_W      0x0B
#define MC33978_WET_SG1_W      0x0D
#define MC33978_INT_SP_W       0x1B
#define MC33978_INT_SG_W       0x1D
#define MC33978_AMUX_R         0x3A
#define MC33978_AMUX_W         0x3B
#define MC33978_STATUS_R       0x3E
#define MC33978_FAULT_R        0x42
#define MC33978_RESET_W        0x49

#define MC33978_CHECK_VALUE    0x123456UL
#define MC33978_FLAG_FAULT     (1UL << 23)
#define MC33978_FLAG_INT       (1UL << 22)
#define MC33978_INPUT_MASK     0x003FFFFFUL

/* Fault status register bits */
#define MC33978_F_POR          (1UL << 0)
#define MC33978_F_OT           (1UL << 2)
#define MC33978_F_TEMP         (1UL << 3)
#define MC33978_F_OV           (1UL << 4)
#define MC33978_F_UV           (1UL << 5)
#define MC33978_F_HASH         (1UL << 6)
#define MC33978_F_SPI          (1UL << 7)

/* AMUX channel codes */
#define MC33978_AMUX_TEMP      6
#define MC33978_AMUX_VBAT      7

uint32_t mc33978_xfer(uint32_t frame);              /* returns the response to the previous frame */
uint32_t mc33978_read(uint8_t cmd);                 /* 24-bit register content, flags included */
void     mc33978_write(uint8_t cmd, uint32_t data);
bool     mc33978_check(void);                       /* SPI check: true when the device answers 0x123456 */
bool     mc33978_init(void);                        /* check, SP pins to switch-to-ground, interrupts on */
uint32_t mc33978_inputs(void);                      /* bit n = 1 when closed; 0..13 SG, 14..21 SP */
void     mc33978_set_wetting(uint8_t sp_code, uint8_t sg_code);   /* codes 0..7 */
void     mc33978_set_amux(uint8_t code);
uint8_t  mc33978_ma_to_code(uint8_t ma);            /* 0xFF if not a valid level */
uint8_t  mc33978_code_to_ma(uint8_t code);
#endif
