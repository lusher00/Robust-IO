#ifndef MCP2515_H
#define MCP2515_H
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint16_t id;                         /* 11-bit standard identifier */
    uint8_t  dlc;
    uint8_t  data[8];
} can_frame_t;

typedef enum { CAN_125K, CAN_250K, CAN_500K, CAN_1M } can_rate_t;
typedef enum { CAN_MODE_NORMAL = 0x00, CAN_MODE_LOOPBACK = 0x40, CAN_MODE_CONFIG = 0x80 } can_mode_t;

bool    mcp2515_init(can_rate_t rate);   /* leaves the controller in config mode; false if not responding */
bool    mcp2515_set_mode(can_mode_t mode);
bool    mcp2515_send(const can_frame_t *f);          /* uses any free TX buffer; false if all three are busy */
uint8_t mcp2515_tx_busy(void);                       /* number of TX buffers waiting to send */
void    mcp2515_abort_tx(void);                      /* drop everything waiting to send */
bool    mcp2515_receive(can_frame_t *f);             /* false if nothing pending */
bool    mcp2515_loopback_test(void);                 /* leaves the controller in normal mode */
uint8_t mcp2515_read_reg(uint8_t addr);
void    mcp2515_stat(uint8_t *canstat, uint8_t *eflg, uint8_t *tec, uint8_t *rec);
#endif
