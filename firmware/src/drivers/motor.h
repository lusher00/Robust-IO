#ifndef MOTOR_H
#define MOTOR_H
#include <stdint.h>
#include <stdbool.h>

/* Two DRV8876 in PH/EN mode (PMODE low), IMODE low: fixed off-time current
 * regulation at about 1.36 A and automatic retry after overcurrent.
 * nSLEEP and nFAULT are shared by both drivers.
 *
 * motor_task() ramps each motor toward its commanded duty, wakes the drivers
 * when needed and puts them to sleep after the idle time. When nFAULT goes
 * low it stops both motors, puts the drivers to sleep and latches the fault;
 * commands are refused until motor_clear_fault(). */

void     motor_init(void);
void     motor_config(uint8_t slew_pct_per_10ms, uint16_t idle_sleep_ms);
void     motor_task(void);                       /* call every main-loop pass */
bool     motor_command(uint8_t m, int8_t percent);   /* -100..100; false while a fault is latched */
void     motor_stop_all(void);                   /* immediate stop and sleep, no ramp */
void     motor_hold_awake(bool on);              /* keep the drivers awake at zero duty (self-test) */
void     motor_clear_fault(void);

int8_t   motor_target(uint8_t m);
int8_t   motor_actual(uint8_t m);
bool     motor_asleep(void);
bool     motor_fault_pin(void);                  /* nFAULT low now */
bool     motor_fault_latched(void);
uint8_t  motor_fault_count(void);
uint16_t motor_fault_ma(uint8_t m);              /* current recorded when the fault latched */
uint16_t motor_current_ma(uint8_t m);
#endif
