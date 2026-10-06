/* Robust IO rev A - pin map and board constants.
 * Source: rev A netlist (U2 pad nets). See ../DESIGN.md section 2. */
#ifndef BOARD_H
#define BOARD_H

#include <avr/io.h>

#ifndef F_CPU
#define F_CPU            12000000UL   /* Y2 */
#endif
#define MCP2515_F_OSC    16000000UL   /* Y1 */
#define UART_BAUD        115200UL

/* Port A */
#define ADC_CH_AMUX      0            /* PA0  MC33978 AMUX */
#define ADC_CH_ISENSE    1            /* PA1  BTS7008 IS, shared */
#define ADC_CH_IPROPI0   2            /* PA2  motor 0 current */
#define ADC_CH_IPROPI1   3            /* PA3  motor 1 current */
#define DEN2_BIT         PA4          /* U9,  outputs 4, 5 */
#define DEN3_BIT         PA5          /* U10, outputs 6, 7 */
#define DSEL_BIT         PA6          /* shared, low = channel 0 of each device */
#define NSLEEP_BIT       PA7          /* DRV8876 nSLEEP, shared */

/* Port B */
#define CS_CAN_BIT       PB0
#define CS_IN_BIT        PB1
#define INT_IN_BIT       PB2          /* INT2, MC33978 INT_B, active low */
#define DEN0_BIT         PB3          /* U11, outputs 0, 1 */
#define DEN1_BIT         PB4          /* U8,  outputs 2, 3. Also SPI SS: keep as output */
#define SPI_MOSI_BIT     PB5
#define SPI_MISO_BIT     PB6
#define SPI_SCK_BIT      PB7

/* Port C: DRV_OUT0..7 on PC0..PC7, high = output on.
 * PC2..PC5 are JTAG pins: JTAGEN fuse must be unprogrammed. */
#define HSD_COUNT        8

/* Port D */
#define INT_CAN_BIT      PD2          /* INT0, MCP2515 INT, active low */
#define FAULTM_BIT       PD3          /* INT1, DRV8876 nFAULT, shared, active low */
#define PH_M0_BIT        PD4
#define EN_M0_BIT        PD5          /* OC1A */
#define PH_M1_BIT        PD6
#define EN_M1_BIT        PD7          /* OC2A */

/* Reset-state port values: everything off, chip selects high. */
#define PORTA_INIT       0x00
#define DDRA_INIT        ((1<<DEN2_BIT)|(1<<DEN3_BIT)|(1<<DSEL_BIT)|(1<<NSLEEP_BIT))
#define PORTB_INIT       ((1<<CS_CAN_BIT)|(1<<CS_IN_BIT))
#define DDRB_INIT        ((1<<CS_CAN_BIT)|(1<<CS_IN_BIT)|(1<<DEN0_BIT)|(1<<DEN1_BIT)| \
                          (1<<SPI_MOSI_BIT)|(1<<SPI_SCK_BIT))
#define PORTC_INIT       0x00
#define DDRC_INIT        0xFF
#define PORTD_INIT       ((1<<PD0)|(1<<PD1)|(1<<INT_CAN_BIT))   /* RX pull-up, TX idle high, INT pull-up */
#define DDRD_INIT        ((1<<PD1)|(1<<PH_M0_BIT)|(1<<EN_M0_BIT)|(1<<PH_M1_BIT)|(1<<EN_M1_BIT))

/* Scaling */
#define ADC_VREF_MV          3300UL   /* AVCC reference */
#define ISENSE_R_OHM         750UL    /* R25 */
#define BTS7008_KILIS        5400UL   /* datasheet typ; +/-4 % at 5.5 A, +/-30 % at 100 mA */
#define ISENSE_SETTLE_MS     2        /* datasheet worst case 0.4 ms at small load */
#define ISENSE_FAULT_MV      3000UL   /* fault current is >= 4.4 mA = 3.3 V on 750 ohm */
#define HSD_OFF_HIGH_MV      1000UL   /* off-state diagnosis current is 1.9..3.5 mA = 1.4..2.6 V */
#define HSD_LIMIT_MA_DEFAULT  5000     /* software trip level per output; set per channel with 'limit' */
#define HSD_TRIP_MS_DEFAULT  100      /* time over the limit before the output is switched off */
#define IPROPI_R_OHM         1500UL   /* 1000 uA per amp into 1.5k = 1.5 V per amp */
#define MOTOR_ITRIP_MA       1360     /* set by VREF divider, not firmware */

/* Configuration defaults (see app/config.c; all can be changed and saved) */
#define CFG_DEFAULT_NODE        0
#define CFG_DEFAULT_RATE_KBIT   250
#define CFG_DEFAULT_TIMEOUT_MS  500      /* host timeout, 0 disables */
#define CFG_DEFAULT_DEBOUNCE_MS 20
#define CFG_DEFAULT_WET_MA      16       /* MC33978 wetting current, power-on default */
#define CFG_DEFAULT_SLEW        10       /* motor duty change, percent per 10 ms */
#define CFG_DEFAULT_IDLE_MS     1000     /* motor drivers sleep after this long at zero */

/* MC33978 */
#define MC33978_INPUTS       22       /* bits 0..13 = SG0..SG13, bits 14..21 = SP0..SP7 */
#define MC33978_SPI_MODE     0        /* CHECK at bring-up: datasheet text says latch on rising edge.
                                         If the SPI check fails, try mode 1. */
#define MCP2515_SPI_MODE     0

#endif
