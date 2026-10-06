#include <avr/io.h>
#include <string.h>
#include "board.h"
#include "hal/spi.h"
#include "hal/tick.h"
#include "drivers/mcp2515.h"

#define CMD_RESET     0xC0
#define CMD_READ      0x03
#define CMD_WRITE     0x02
#define CMD_BITMOD    0x05
#define CMD_RTS       0x80          /* | 1, 2, 4 for TXB0..2 */
#define CMD_STATUS    0xA0

#define REG_CANSTAT   0x0E
#define REG_CANCTRL   0x0F
#define REG_TEC       0x1C
#define REG_REC       0x1D
#define REG_CNF3      0x28
#define REG_CNF2      0x29
#define REG_CNF1      0x2A
#define REG_CANINTE   0x2B
#define REG_CANINTF   0x2C
#define REG_EFLG      0x2D
#define REG_TXB0CTRL  0x30          /* TXB1 0x40, TXB2 0x50 */
#define REG_RXB0CTRL  0x60
#define REG_RXB0SIDH  0x61
#define REG_RXB1CTRL  0x70
#define REG_RXB1SIDH  0x71

#define ABAT          0x10
#define RX0IF         0x01
#define RX1IF         0x02

/* READ STATUS bits */
#define ST_RX0IF      0x01
#define ST_RX1IF      0x02
#define ST_TX0REQ     0x04
#define ST_TX1REQ     0x10
#define ST_TX2REQ     0x40

/* Bit timing for the 16 MHz crystal: 16 TQ per bit (8 TQ at 1 Mbit/s),
 * sample point 75 %, SJW 1. {CNF1, CNF2, CNF3} */
static const uint8_t timing[][3] = {
    [CAN_125K] = { 0x03, 0xBA, 0x03 },
    [CAN_250K] = { 0x01, 0xBA, 0x03 },
    [CAN_500K] = { 0x00, 0xBA, 0x03 },
    [CAN_1M]   = { 0x00, 0x91, 0x01 },
};

static void cs_low(void)  { spi_set_mode(MCP2515_SPI_MODE); PORTB &= (uint8_t)~(1 << CS_CAN_BIT); }
static void cs_high(void) { PORTB |= (1 << CS_CAN_BIT); }

uint8_t mcp2515_read_reg(uint8_t addr)
{
    cs_low(); spi_xfer(CMD_READ); spi_xfer(addr);
    uint8_t v = spi_xfer(0);
    cs_high();
    return v;
}

static void write_reg(uint8_t addr, uint8_t v)
{
    cs_low(); spi_xfer(CMD_WRITE); spi_xfer(addr); spi_xfer(v); cs_high();
}

static void bit_modify(uint8_t addr, uint8_t mask, uint8_t v)
{
    cs_low(); spi_xfer(CMD_BITMOD); spi_xfer(addr); spi_xfer(mask); spi_xfer(v); cs_high();
}

static uint8_t read_status(void)
{
    cs_low(); spi_xfer(CMD_STATUS);
    uint8_t v = spi_xfer(0);
    cs_high();
    return v;
}

bool mcp2515_set_mode(can_mode_t mode)
{
    bit_modify(REG_CANCTRL, 0xE0, (uint8_t)mode);
    for (uint8_t i = 0; i < 20; i++) {
        if ((mcp2515_read_reg(REG_CANSTAT) & 0xE0) == (uint8_t)mode) return true;
        delay_ms(1);
    }
    return false;
}

bool mcp2515_init(can_rate_t rate)
{
    if (rate > CAN_1M) rate = CAN_250K;
    cs_low(); spi_xfer(CMD_RESET); cs_high();
    delay_ms(5);
    if ((mcp2515_read_reg(REG_CANSTAT) & 0xE0) != CAN_MODE_CONFIG) return false;

    write_reg(REG_CNF1, timing[rate][0]);
    write_reg(REG_CNF2, timing[rate][1]);
    write_reg(REG_CNF3, timing[rate][2]);
    if (mcp2515_read_reg(REG_CNF1) != timing[rate][0]) return false;

    write_reg(REG_RXB0CTRL, 0x64);       /* receive any message, roll over to RXB1 */
    write_reg(REG_RXB1CTRL, 0x60);
    write_reg(REG_CANINTF, 0x00);
    write_reg(REG_CANINTE, RX0IF | RX1IF);   /* INT pin = receive pending */
    return true;
}

bool mcp2515_send(const can_frame_t *f)
{
    static const uint8_t req[3] = { ST_TX0REQ, ST_TX1REQ, ST_TX2REQ };
    uint8_t st = read_status();
    for (uint8_t b = 0; b < 3; b++) {
        if (st & req[b]) continue;
        uint8_t dlc = f->dlc > 8 ? 8 : f->dlc;
        cs_low();
        spi_xfer(CMD_WRITE); spi_xfer((uint8_t)(REG_TXB0CTRL + 0x10 * b + 1));
        spi_xfer((uint8_t)(f->id >> 3));
        spi_xfer((uint8_t)(f->id << 5));
        spi_xfer(0); spi_xfer(0);
        spi_xfer(dlc);
        for (uint8_t i = 0; i < dlc; i++) spi_xfer(f->data[i]);
        cs_high();
        cs_low(); spi_xfer((uint8_t)(CMD_RTS | (1 << b))); cs_high();
        return true;
    }
    return false;
}

uint8_t mcp2515_tx_busy(void)
{
    uint8_t st = read_status();
    return (uint8_t)(!!(st & ST_TX0REQ) + !!(st & ST_TX1REQ) + !!(st & ST_TX2REQ));
}

void mcp2515_abort_tx(void)
{
    bit_modify(REG_CANCTRL, ABAT, ABAT);
    for (uint8_t i = 0; i < 3 && mcp2515_tx_busy(); i++) delay_ms(1);
    bit_modify(REG_CANCTRL, ABAT, 0);
}

bool mcp2515_receive(can_frame_t *f)
{
    uint8_t st = read_status();
    uint8_t base, flag;
    if (st & ST_RX0IF)      { base = REG_RXB0SIDH; flag = RX0IF; }
    else if (st & ST_RX1IF) { base = REG_RXB1SIDH; flag = RX1IF; }
    else return false;

    cs_low();
    spi_xfer(CMD_READ); spi_xfer(base);
    uint8_t sidh = spi_xfer(0), sidl = spi_xfer(0);
    spi_xfer(0); spi_xfer(0);
    f->dlc = spi_xfer(0) & 0x0F;
    if (f->dlc > 8) f->dlc = 8;
    for (uint8_t i = 0; i < f->dlc; i++) f->data[i] = spi_xfer(0);
    cs_high();
    f->id = ((uint16_t)sidh << 3) | (sidl >> 5);
    bit_modify(REG_CANINTF, flag, 0);
    return true;
}

bool mcp2515_loopback_test(void)
{
    can_frame_t tx = { .id = 0x5A5, .dlc = 4, .data = { 0xDE, 0xAD, 0xBE, 0xEF } }, rx;
    bool pass = false;
    mcp2515_abort_tx();
    while (mcp2515_receive(&rx)) { }                  /* drain */
    if (mcp2515_set_mode(CAN_MODE_LOOPBACK) && mcp2515_send(&tx)) {
        delay_ms(10);
        pass = mcp2515_receive(&rx) && rx.id == tx.id && rx.dlc == tx.dlc &&
               !memcmp(rx.data, tx.data, tx.dlc);
    }
    return mcp2515_set_mode(CAN_MODE_NORMAL) && pass;
}

void mcp2515_stat(uint8_t *canstat, uint8_t *eflg, uint8_t *tec, uint8_t *rec)
{
    *canstat = mcp2515_read_reg(REG_CANSTAT);
    *eflg    = mcp2515_read_reg(REG_EFLG);
    *tec     = mcp2515_read_reg(REG_TEC);
    *rec     = mcp2515_read_reg(REG_REC);
}
