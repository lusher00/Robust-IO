#ifndef SELFTEST_H
#define SELFTEST_H
#include <stdint.h>
/* Bring-up checks. The basic run never switches an output or a motor on.
 * with_outputs pulses each high-side output; with_motors runs each motor
 * at 20 % in both directions. Returns the number of failed steps. */
uint8_t selftest_run(uint8_t with_outputs, uint8_t with_motors);
#endif
