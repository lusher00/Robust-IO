# Robust IO firmware design

Target: ATmega1284P-AU on Robust IO rev A, 3.3 V, 12 MHz crystal (Y2).
Toolchain: avr-gcc, avr-libc, avrdude, one Makefile. C11, no RTOS, no Arduino core.

Status: firmware 0.3, feature complete for rev A. Compiles without warnings (avr-gcc 7.3). All simulation scenarios in test/ pass against models of the MC33978 and MCP2515. Nothing has run on hardware.

## 1. Goals

1. Prove every subsystem of rev A from a UART console on J20.
2. Use the same drivers for the application, so bring-up code is not thrown away.
3. Fail to a safe state: all outputs off, both motor drivers asleep.

## 2. Pin map

Taken from the rev A netlist (U2 pad nets). The same map is in `src/board.h`.

| Port | Pin | Net | Direction | Function |
|---|---|---|---|---|
| PA0 | 37 | AMUX0 | analog in, ADC0 | MC33978 analog mux output, through 1k, clamped to 3.3 V |
| PA1 | 36 | ISENSE (filtered) | analog in, ADC1 | BTS7008 current sense, shared by all four devices |
| PA2 | 35 | IPROPIM0 | analog in, ADC2 | Motor 0 current, 1.5 V per amp |
| PA3 | 34 | IPROPIM1 | analog in, ADC3 | Motor 1 current, 1.5 V per amp |
| PA4 | 33 | DEN2 | out | Diagnosis enable, U9 (outputs 4, 5) |
| PA5 | 32 | DEN3 | out | Diagnosis enable, U10 (outputs 6, 7) |
| PA6 | 31 | DSELn | out | Sense channel select, shared by all four BTS7008 |
| PA7 | 30 | nSLEEPMn | out | DRV8876 sleep, shared, low = asleep |
| PB0 | 40 | CS_CAN | out | MCP2515 chip select, active low |
| PB1 | 41 | CS_IN0 | out | MC33978 chip select, active low |
| PB2 | 42 | INT_B0 | in, INT2 | MC33978 interrupt, active low, 10k pull-up |
| PB3 | 43 | DEN0 | out | Diagnosis enable, U11 (outputs 0, 1) |
| PB4 | 44 | DEN1 | out | Diagnosis enable, U8 (outputs 2, 3). Also SPI SS: must stay an output |
| PB5 | 1 | MOSI0 | out | SPI, also ISP |
| PB6 | 2 | MISO0 | in | SPI, also ISP |
| PB7 | 3 | SCLK0 | out | SPI, also ISP |
| PC0..PC7 | 19..26 | DRV_OUT0..7 | out | BTS7008 inputs through 4.7k, high = output on |
| PD0 | 9 | RX0 | in | UART0 from J20 pin 4 through 1k |
| PD1 | 10 | TX0 | out | UART0 to J20 pin 5 through 1k |
| PD2 | 11 | INT_CAN0 | in, INT0 | MCP2515 interrupt, active low |
| PD3 | 12 | FAULTMn | in, INT1 | DRV8876 fault, shared, active low, 10k pull-up |
| PD4 | 13 | PH_M0 | out | Motor 0 direction |
| PD5 | 14 | EN_M0 | out, OC1A | Motor 0 PWM |
| PD6 | 15 | PH_M1 | out | Motor 1 direction |
| PD7 | 16 | EN_M1 | out, OC2A | Motor 1 PWM |

Output numbering: DRV_OUTn drives OUT_n on J3 (0 to 3) and J5 (4 to 7).

| BTS7008 | DEN | DSELn low | DSELn high |
|---|---|---|---|
| U11 | DEN0 | OUT_0 | OUT_1 |
| U8 | DEN1 | OUT_2 | OUT_3 |
| U9 | DEN2 | OUT_4 | OUT_5 |
| U10 | DEN3 | OUT_6 | OUT_7 |

Only one DEN may be high at a time, because all four sense pins share R25 (750 ohm).

## 3. Hardware facts that shape the firmware

These come from the netlist and the device datasheets. Items marked CHECK are to be confirmed on hardware.

- **JTAG shares PC2 to PC5 with DRV_OUT2 to DRV_OUT5.** A factory-fresh ATmega1284P has the JTAGEN fuse programmed, which enables pull-ups on TCK, TMS and TDI (PC2, PC3, PC5). The BTS7008 inputs pull down with only 10 to 25 uA and switch between 0.8 V and 2.0 V, so a 20k to 50k pull-up to 3.3 V through the 4.7k series resistor will hold the input high: expect outputs 2, 3 and 5 to be ON on an unprogrammed chip. Program the fuses with JTAG disabled before any load is wired to J3 or J5. The firmware also sets JTD in MCUCR at start as a second guard.
- **CS_CAN has no pull-up.** During ISP the MCU pins are high impedance, so the MCP2515 chip select floats and the MCP2515 can drive MISO. If programming is unreliable, fit 10k from TP8 (CS_CAN) to TP1 (+3.3V); they are next to each other. The MC33978 CS_B has an internal pull-up to VDDQ (datasheet). Add a CS_CAN pull-up in rev B.
- **SPI bus is shared** by the MCP2515 (mode 0) and the MC33978 (32-bit frames, MSB first, up to 8 MHz, response returned in the following frame). The MC33978 datasheet says it latches MOSI on the rising edge, which is mode 0; `MC33978_SPI_MODE` in `board.h` is the switch if the SPI check (expects 0x123456) fails (CHECK). The SPI driver sets the mode per transaction. Clock is F_CPU/4 = 3 MHz.
- **ADC reference is AVCC (3.3 V).** AREF has only a capacitor.
- **ISENSE scaling:** I_load = V_adc / 750 ohm x kILIS. kILIS is 5400 typical: within 4 % at 5.5 A, 13.5 % at 1 A, 30 % at 100 mA. 3.3 V full scale is about 23 A, about 23 mA per count at 10 bits. The fault signal is a sense current of at least 4.4 mA, which is 3.3 V on R25, so a reading above 3.0 V means fault. With the output off, an open load gives 1.9 to 3.5 mA (1.4 to 2.6 V).
- **Motor current limit is set in hardware.** PMODE is tied low (PH/EN mode). VREF = 3.3 V x 16.2k / 26.2k = 2.04 V and IPROPI is 1.5k, so the DRV8876 regulates at about 1.36 A. Firmware reads current at 1.5 V per amp but cannot raise the limit.
- **nSLEEP and nFAULT are shared** between the two DRV8876. A fault cannot be attributed to one motor from the pin alone; the firmware uses the two IPROPI readings and the commanded state to decide.
- **SP0 to SP7 are configured as switch-to-ground.** SG pins are switch-to-ground only; SP pins are programmable as switch-to-ground or switch-to-battery. On rev A every input, SP included, has an indicator LED and 2.2k from +24V to the IC pin. In switch-to-battery mode that path sources about 8 mA into the pin with the switch open, more than the IC's sustain current sinks, so the input would read closed all the time. Switch-to-battery on an SP channel needs its LED removed (D14 to D17 for SP0 to SP3 on J9, D18 to D21 for SP4 to SP7 on J10). The MC33978 powers up with SP pins in switch-to-battery mode (datasheet), so the driver clears device configuration bits 7 to 0 before the first read.
- **Clocks:** MCU 12 MHz, MCP2515 16 MHz (Y1). 115200 baud at 12 MHz with U2X has 0.16 % error.
- **CAN termination** is SW1 (120 ohm). Not readable by firmware.

## 4. Fuses

| Fuse | Value | Meaning |
|---|---|---|
| low | 0xFF | External crystal 8 to 16 MHz, slowest start-up |
| high | 0xD1 | JTAG disabled, SPI programming enabled, EEPROM kept through chip erase, no bootloader |
| extended | 0xFD | Brown-out at 2.7 V |

`make fuses` writes these. EESAVE (in the high fuse) keeps the saved configuration when `make flash` erases the chip.

### Programmer: Raspberry Pi over SPI

The Pi's GPIO is 3.3 V, so it connects to J1 with no level shifting. avrdude uses the `linuxspi` programmer. Build and flash can both run on the Pi, or the hex file can be built on the Mac and copied over.

| Pi header pin | Pi signal | J1 pin | Board net |
|---|---|---|---|
| 19 | GPIO10 MOSI | 4 | MOSI0 |
| 21 | GPIO9 MISO | 1 | MISO0 |
| 23 | GPIO11 SCLK | 3 | SCLK0 |
| 22 | GPIO25 | 5 | RST |
| 25 | GND | 6 | GND |
| - | - | 2 | +3.3V, leave unconnected |

- Power the board from its own supply before connecting, and share only ground. Do not join the Pi's 3.3 V to the board's 3.3 V.
- SPI must be enabled on the Pi (`dtparam=spi=on`), giving `/dev/spidev0.0`.
- Packages on the Pi: `avrdude` (version 7 or later), plus `gcc-avr` and `avr-libc` if building there.
- Port string: `-c linuxspi -P /dev/spidev0.0:/dev/gpiochip0:25`. On a Pi 5 the header GPIO chip is `gpiochip0` or `gpiochip4` depending on the kernel; `gpiodetect` shows which one is `pinctrl-rp1`.
- A new chip runs from its 1 MHz internal clock, so the first connection must be slow: `-b 100000`. After the fuses select the 12 MHz crystal, `-b 1000000` works.
- Keep the wires short (under about 15 cm).

The Pi's UART can also serve as the J20 console: Pi pin 8 (TXD) to J20 pin 4, Pi pin 10 (RXD) to J20 pin 5, ground to J20 pin 1.

## 5. Architecture

Single foreground loop plus short interrupt handlers. No dynamic memory.

    app        console commands, CAN protocol, output/motor state machines
    --------------------------------------------------------------------
    drivers    mc33978   mcp2515   hsd (BTS7008)   motor (DRV8876)
    --------------------------------------------------------------------
    hal        gpio   spi   uart   adc   tick   pwm   eeprom   wdt
    --------------------------------------------------------------------
    board.h    pin map, scaling constants, F_CPU

Rules:

- Only `hal/` touches AVR registers. Drivers call the HAL. This lets the drivers and the protocol code be compiled and unit-tested on the Mac.
- Interrupt handlers only move bytes or set flags: 1 ms tick (Timer0 CTC), UART RX and TX ring buffers, INT0/INT1/INT2 set "service me" flags. All SPI traffic happens in the foreground, so the bus needs no locking.
- Every module has `init()` and a non-blocking `task()` called from the main loop. No `_delay_ms()` after start-up.

Timers:

| Timer | Use |
|---|---|
| Timer0 | 1 ms system tick (CTC). OC0A/OC0B stay disconnected because PB3/PB4 are DEN0/DEN1 |
| Timer1 | Motor 0 PWM on OC1A, phase-correct 8-bit, 23.5 kHz |
| Timer2 | Motor 1 PWM on OC2A, phase-correct, 23.5 kHz |

Main loop schedule:

| Period | Task |
|---|---|
| every pass | UART console, CAN receive, interrupt flags |
| 1 ms | ADC sequencer step |
| 10 ms | Poll MC33978 inputs (also on INT_B0), debounce, output and motor state machines |
| 100 ms | Periodic CAN status frames, watchdog kick, heartbeat |

## 6. Drivers

**mc33978** - 22 switch inputs (SG0 to SG13, SP0 to SP7).
Init: read device ID, set SP pins as switch-to-ground or switch-to-battery, set wetting current and wetting timer, set thresholds, enable interrupts on change. Run time: read switch status (one 32-bit frame returns all 22 bits), select AMUX channel to read an input voltage, battery sense or die temperature on ADC0. Reports SPI error and over-temperature flags.

**mcp2515** - CAN controller.
Init: reset, set bit timing for the 16 MHz crystal (250 kbit/s default; 125k, 500k and 1M tables included), set filters, enter normal mode. Loopback mode is used for the self-test. Run time: receive from both buffers into a software queue, transmit from a software queue using the three TX buffers, track error counters and bus-off, recover from bus-off after a delay.

**hsd** - eight high-side outputs.
On/off only. PWM is provided on the motor drivers, not on these outputs.
Per channel: commanded state, measured current, status (off, on, overcurrent, open load, fault). The ADC sequencer raises one DEN, sets DSELn, waits for the sense output to settle (datasheet worst case 0.4 ms at small load; the design uses 2 ms), samples ADC1, then moves to the next channel. A full scan of eight channels takes about 20 ms. Software overcurrent trip per channel with configurable limit and time, latched until cleared by command. The BTS7008's own protection remains the backstop.

**motor** - two DRV8876 in PH/EN mode.
Signed duty command, slew-rate limited. nSLEEP is raised when either motor is commanded and dropped when both have been idle for a set time. Fault handling: on FAULTMn low, stop both, record currents, pulse nSLEEP to clear, report.

## 7. Safe state and fault handling

Safe state = DRV_OUT0..7 low, EN_M0/EN_M1 low, nSLEEPMn low.

Entered on:

- Reset, before anything else runs (ports are set in `.init3`, before C start-up).
- Watchdog reset (250 ms watchdog, kicked once per main-loop pass).
- Brown-out.
- Loss of host: after a set-outputs or set-motors frame has been received, no further one for the configured timeout (default 500 ms, 0 disables). Console commands do not start the timeout.

Per-device faults stop only what they affect:

- Output over the software limit for the trip time, or the BTS7008 fault level on two consecutive readings: that output off and latched until cleared.
- DRV8876 nFAULT low: both motors stopped and the drivers put to sleep (which also clears them); motor commands refused until cleared. The fault count and the currents at the time are recorded.
- MC33978 SPI check failing (checked every second): inputs flagged invalid on CAN; the chip is set up again when it answers. A device power-on reset seen in the fault status register also triggers a new setup.
- MCP2515 not answering at start: retried every second.

The reset cause (MCUSR) is saved at start and reported on the console and in the CAN heartbeat.

## 8. Console (UART0, 115200 8N1)

Line-based text commands, used for bring-up and service. `help` lists them.

    ver                        version, reset cause, device check, node, uptime
    in                         debounced and raw inputs, MC33978 fault status
    in watch                   print debounced inputs on change (any key stops)
    in raw <cmd-hex>           read one MC33978 register
    amux [code]                select AMUX channel (6 temperature, 7 battery) and read mV
    out <0-7> <0|1>            switch one output
    out all 0                  all outputs off
    out clear                  clear latched trips and faults
    isense                     state, sense voltage, current and limit per output
    limit <0-7|all> <mA> [ms]  trip level and time
    motor <0|1> <-100..100>    command duty in percent, ramped
    motor off                  stop both now, drivers asleep
    motor clear                clear a latched driver fault
    motor                      status
    can                        status and counters
    can loop                   loopback self-test
    can tx <id-hex> [bytes]    send a standard frame
    cfg                        show settings
    cfg <name> <value>         change a setting
    cfg save | cfg default     write to EEPROM | load defaults (not saved)
    selftest                   checks that switch nothing on: SPI devices, CAN loopback,
                               outputs quiet, motor drivers idle
    selftest out               also pulses each output for 200 ms
    selftest motor             also runs each motor at 20 % both ways
    reset

## 9. CAN protocol

Standard 11-bit IDs, node number N (0 to 15) and bit rate from the configuration. Multi-byte values are little-endian.

| ID | Dir | When | DLC | Data |
|---|---|---|---|---|
| 0x100+N | out | on debounced change, and 100 ms | 4 | d0..d2: input bits, bit n = input n (0..13 SG0..SG13, 14..21 SP0..SP7), 1 = closed. d3: bit0 inputs valid, bit1 MC33978 fault flag (UV, OV, temperature, SPI, hash) |
| 0x110+N | out | 100 ms | 5 | d0 commanded mask, d1 on mask, d2 tripped mask, d3 device-fault mask, d4 off-but-high mask (open load or short to supply) |
| 0x120+N | out | 100 ms | 8 | output 0..7 current, 100 mA per count, 255 = 25.5 A or more |
| 0x130+N | out | 100 ms | 6 | d0, d1 motor 0, 1 duty (signed %), d2, d3 current (10 mA per count), d4 bit0 asleep, bit1 fault latched, bit2 nFAULT low, d5 fault count |
| 0x140+N | out | 1 s | 8 | d0 state, d1 reset cause (MCUSR), d2 version major, d3 version minor, d4 TEC, d5 REC, d6 EFLG, d7 frames dropped |
| 0x200+N | in | | 2 | d0 mask, d1 values: for each bit set in d0, output n is set to bit n of d1 |
| 0x210+N | in | | 2 | d0, d1 motor 0, 1 duty, signed percent -100..100, ramped |
| 0x220+N | in | | 1-2 | d0 output mask to clear, d1 bit0 clear motor fault |
| 0x230+N | in | | 2-4 | d0 op (0 read, 1 write, 2 save, 3 load defaults), d1 key, d2-d3 value |
| 0x240+N | out | reply to 0x230 | 5 | d0 op, d1 key, d2-d3 value, d4 result (0 ok, 1 bad key, 2 bad value, 3 EEPROM failed) |

Heartbeat state bits: 0 host active, 1 host timed out (until the next command), 2 inputs valid, 3 configuration from defaults, 4 motor fault latched, 5 an output is latched off.

A set-outputs or set-motors frame makes the host active and restarts the timeout. Commands to a latched output or motor are ignored until a clear frame.

Transmission: status frames are queued in software and loaded into the MCP2515's three transmit buffers. If frames from the previous 100 ms period are still waiting when the next period starts (no other node acknowledging), they are aborted and counted as dropped, so the bus only ever carries current data.

## 10. Configuration (EEPROM)

One struct with a version byte and CRC16, loaded at start; defaults are used when the CRC fails. Changes take effect at once except node and rate, which apply after `cfg save` and a reset.

| Key | Name | Unit, range | Default |
|---|---|---|---|
| 0x00 | node | 0..15 | 0 |
| 0x01 | rate | kbit/s: 125, 250, 500, 1000 | 250 |
| 0x02 | timeout | host timeout ms, 0 = off, up to 60000 | 500 |
| 0x03 | debounce | ms, 0..250 | 20 |
| 0x04 | wet_sp | SP wetting current mA: 2 6 8 10 12 14 16 20 | 16 |
| 0x05 | wet_sg | SG wetting current mA | 16 |
| 0x06 | slew | motor duty change, % per 10 ms, 1..100 | 10 |
| 0x07 | idle | motor driver sleep delay ms, 0..60000 | 1000 |
| 0x10-0x17 | limit0..7 | output trip level mA, 100..30000 | 5000 |
| 0x18-0x1F | trip0..7 | output trip time ms, 0..10000 | 100 |

Wetting current is applied for 20 ms after a switch closes, then drops to the sustain current (MC33978 default, not changed).

## 11. Layout and build

    firmware/
      Makefile
      DESIGN.md
      src/
        board.h          pin map, scaling, defaults
        version.h
        main.c           start-up, main loop
        hal/             tick, uart, spi, adc
        drivers/         mc33978, mcp2515, hsd (BTS7008), motor (DRV8876)
        app/             config, inputs, canproto, console, selftest
      test/
        sim.c            simavr harness with MC33978 and MCP2515 models
        run_sim.sh       builds it and runs the scenarios

Make targets: `all`, `flash`, `fuses`, `size`, `clean`. The programmer settings are Makefile variables (`PROGRAMMER`, `PORT`, `SPI_HZ`), defaulting to the Raspberry Pi `linuxspi` setup above.

Main loop, every pass: console, output sense scan, motor control, inputs, CAN. Each task keeps its own timing from the 1 ms tick: sense scan one channel per 3 ms, inputs every 5 ms or on INT_B, motor ramp every 10 ms, CAN status every 100 ms, heartbeat every 1 s, device checks every 1 s.

Simulation: `bash test/run_sim.sh [boot|selftest|inputs|can|config|protect|noack]` runs the firmware on simavr against simple models of the two SPI devices. It checks the firmware's logic and protocol handling, not the real chips. Needs simavr and libelf.

## 11a. What is implemented

| Area | State |
|---|---|
| Safe-state start-up, reset cause, watchdog, JTAG disable | done |
| HAL: tick, UART (interrupt driven), SPI, ADC | done |
| MC33978: check, SP mode, wetting current, interrupts, AMUX, fault status, re-setup | done |
| Inputs: 5 ms poll and INT_B, per-input debounce | done |
| MCP2515: bit timing, modes, three TX buffers, abort, receive | done |
| High-side outputs: background sense scan, software trip, device fault, latching | done |
| Motors: ramped PWM, wake and idle sleep, fault latch and clear | done |
| CAN protocol and host timeout | done |
| EEPROM configuration over console and CAN | done |
| Console and selftest | done |
| Simulation scenarios | done; all pass |
| Run on hardware | not yet |

Firmware 0.3: about 19 KB flash, 0.7 KB RAM.

## 12. Bring-up sequence

Each step is one console command and is what `selftest` automates.

1. Fuses, then flash. Heartbeat line appears on J20.
2. `ver` shows the reset cause as power-on.
3. `in`: MC33978 ID reads correctly; shorting an input to ground changes its bit.
4. `can loop` passes; then `can tx` is seen by a second node with SW1 set as needed.
5. `out n 1` with a resistive load on each output in turn; `isense` matches a meter.
6. `motor 0 20`, `motor 0 -20`, same for motor 1; `motor stat` current matches a meter.
7. Remove the host: outputs drop after the timeout.

## 13. Open questions

None blocking. Decisions taken as defaults, all changeable in configuration:

- CAN runs at 250 kbit/s with the IDs in section 9. No existing bus is assumed.
- SP0 to SP7 are switch-to-ground.
- The high-side outputs are on/off only; PWM is on the motor drivers.
- The programmer is a Raspberry Pi over SPI.

To confirm on hardware:

- MC33978 SPI mode (see section 3).
- Which of each BTS7008's two channels reaches which connector pin. The firmware assumes DRV_OUTn switches OUT_n; `out n 1` at bring-up confirms it, and a swap within a pair is a one-line table change.
- The layout of the MC33978 device configuration register above bit 7. The driver reads the register and writes it back with only bits 7 to 0 cleared.
