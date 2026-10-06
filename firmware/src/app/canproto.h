#ifndef CANPROTO_H
#define CANPROTO_H
#include <stdint.h>
#include <stdbool.h>
/* CAN protocol, standard 11-bit IDs, N = node number (DESIGN.md section 9).
 *   out 0x100+N inputs      on change and every 100 ms
 *   out 0x110+N outputs     100 ms
 *   out 0x120+N currents    100 ms
 *   out 0x130+N motors      100 ms
 *   out 0x140+N heartbeat   1 s
 *   out 0x240+N config reply
 *   in  0x200+N set outputs, 0x210+N set motors, 0x220+N clear faults, 0x230+N config
 * A set-outputs or set-motors frame makes the host active. If the host then
 * sends neither for the configured timeout, all outputs and motors are stopped. */

typedef struct {
    uint16_t rx, rx_ignored, tx, tx_dropped, timeouts;
} canproto_stats_t;

void canproto_init(uint8_t reset_cause);
void canproto_task(void);
bool canproto_ok(void);
bool canproto_host_active(void);
const canproto_stats_t *canproto_stats(void);
#endif
