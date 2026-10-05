/* Robust IO rev A - pin map and board constants.
 * Source: rev A netlist (U2 pad nets). See ../DESIGN.md section 2. */
#ifndef BOARD_H
#define BOARD_H

#include <avr/io.h>

#define F_CPU            12000000UL   /* Y2 */
#define MCP2515_F_OSC    16000000UL   /* Y1 */
#define UART_BAUD        115200UL

/* Port A */
#define ADC_CH_AMUX      0            /* PA0  MC33978 AMUX */
#define ADC_CH_ISENSE    1            /* PA1  BTS7008 IS, shared */
#define ADC_CH_IPROPI0   2            /* PA2  motor 0 current */
#define ADC_CH_IPROPI1   3            /* PA3  motor 1 current */
#define DEN2_PORT        PORTA
#define DEN2_DDR         DDRA
#define DEN2_BIT         PA4
#define DEN3_PORT        PORTA
#define DEN3_DDR         DDRA
#define DEN3_BIT         PA5
#define DSEL_PORT        PORTA
#define DSEL_DDR         DDRA
#define DSEL_BIT         PA6
#define NSLEEP_PORT      PORTA
#define NSLEEP_DDR       DDRA
#define NSLEEP_BIT       PA7

/* Port B */
#define CS_CAN_PORT      PORTB
#define CS_CAN_DDR       DDRB
#define CS_CAN_BIT       PB0
#define CS_IN_PORT       PORTB
#define CS_IN_DDR        DDRB
#define CS_IN_BIT        PB1
#define INT_IN_PIN       PINB
#define INT_IN_BIT       PB2          /* INT2, MC33978 INT_B, active low */
#define DEN0_PORT        PORTB
#define DEN0_DDR         DDRB
#define DEN0_BIT         PB3
#define DEN1_PORT        PORTB
#define DEN1_DDR         DDRB
#define DEN1_BIT         PB4          /* also SPI SS: keep as output */
#define SPI_PORT         PORTB
#define SPI_DDR          DDRB
#define SPI_MOSI_BIT     PB5
#define SPI_MISO_BIT     PB6
#define SPI_SCK_BIT      PB7

/* Port C: DRV_OUT0..7 on PC0..PC7, high = output on.
 * PC2..PC5 are JTAG pins: JTAGEN fuse must be unprogrammed. */
#define HSD_PORT         PORTC
#define HSD_DDR          DDRC
#define HSD_COUNT        8

/* Port D */
#define INT_CAN_PIN      PIND
#define INT_CAN_BIT      PD2          /* INT0, MCP2515 INT, active low */
#define FAULTM_PIN       PIND
#define FAULTM_BIT       PD3          /* INT1, DRV8876 nFAULT, shared, active low */
#define MOTOR_PORT       PORTD
#define MOTOR_DDR        DDRD
#define PH_M0_BIT        PD4
#define EN_M0_BIT        PD5          /* OC1A */
#define PH_M1_BIT        PD6
#define EN_M1_BIT        PD7          /* OC2A */

/* Scaling. Values marked CHECK must be confirmed against the datasheet. */
#define ADC_VREF_MV          3300U    /* AVCC reference */
#define ISENSE_R_OHM         750U     /* R25 */
#define BTS7008_KILIS        5400U    /* CHECK */
#define ISENSE_SETTLE_MS     2U       /* CHECK: DEN/DSEL to valid IS */
#define IPROPI_MV_PER_A      1500U    /* 1.5k x 1000 uA/A */
#define MOTOR_ITRIP_MA       1360U    /* set by VREF divider, not firmware */

#define MC33978_INPUTS       22       /* SG0..SG13, SP0..SP7 */

#endif
