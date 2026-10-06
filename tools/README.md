# Robust IO host tools

Everything here talks to the board over CAN using the protocol in
`firmware/DESIGN.md` section 9.

| Item | What it is |
|---|---|
| `robustio-node0.dbc` | DBC file for node 0. Opens in SavvyCAN, PCAN-View, cantools, Vector tools and most CAN loggers, so every frame decodes to named signals |
| `python/robustio/` | Python package: protocol, `RobustIO` device class, `robustio` command-line tool, terminal dashboard, browser dashboard, bring-up test runner, DBC generator, simulator bus |
| `python/tests/` | Protocol and DBC tests, and end-to-end tests of the tools against the firmware running in the simulator |
| `ros2/robustio_ros/` | ROS 2 driver node: inputs, outputs, currents and motors as topics, services, `/diagnostics` |

## Install

    pip install -e tools/python            # add [test] for pytest and cantools

Needs Python 3.8 or later and python-can, which supports SocketCAN (Raspberry Pi
CAN HATs, most USB adapters on Linux), slcan/CANable, PEAK PCAN, gs_usb and
others.

## Command-line tool

    robustio scan                     list Robust IO nodes on the bus
    robustio status                   one status snapshot
    robustio watch                    live status screen
    robustio dump                     every decoded frame
    robustio out 3 on                 switch output 3 on and hold it (Ctrl-C ends)
    robustio out all off
    robustio motor 0 40               run motor 0 at 40 % and hold it
    robustio motor off
    robustio clear                    clear latched output trips and the motor fault
    robustio cfg                      all settings
    robustio cfg timeout 1000         change one setting
    robustio cfg save                 write settings to EEPROM
    robustio dbc -n 3 -o node3.dbc    DBC file for another node number
    robustio tui                      terminal dashboard
    robustio web                      browser dashboard on http://127.0.0.1:8080/
    robustio bringup --console /dev/serial0 --serial RA-0001
                                      bring-up / end-of-line test with a written report

Global options: `-i` interface (default socketcan), `-c` channel (default can0),
`-b` bitrate (default 250000), `-n` node (default 0). The same values can be set
in the environment as `ROBUSTIO_INTERFACE`, `ROBUSTIO_CHANNEL`,
`ROBUSTIO_BITRATE` and `ROBUSTIO_NODE`.

The board turns everything off when the host goes quiet for the configured
timeout (500 ms by default). `out` and `motor` therefore keep running and repeat
a keepalive frame until Ctrl-C or `--hold SECONDS` ends them; the board then
times out to all off.

SocketCAN on the Pi, once per boot:

    sudo ip link set can0 up type can bitrate 250000

## Terminal dashboard

`robustio tui` shows inputs, outputs with current, motors and CAN state on one
screen. Keys: `0`-`7` toggle an output, `a` all off, `m` set a motor duty (typed),
`s` stop, `c` clear faults, `q` quit. Quitting sends stop.

## Browser dashboard

`robustio web` serves a page with the same view plus every setting, using only
the Python standard library. Motor duty and settings are typed number fields.
The keepalive runs only while a page is polling, so closing the tab, losing the
network or stopping the server lets the board time out to all off.

It listens on 127.0.0.1 by default. `--host 0.0.0.0` makes it reachable from
other machines, for example to open the Pi's dashboard from a laptop. There is
no login: anyone who can reach the port can switch outputs and run motors.

## Bring-up and end-of-line test

    robustio bringup --console /dev/serial0 --serial RA-0001 [--loads] [--report DIR]

Runs `ver` and `selftest` on the J20 console, then checks over CAN: status
frames, matching firmware version, error counters, settings, every output by
command, both motors, and that outputs drop when the host goes quiet. Writes
`bringup-<serial>-<date>.txt` and exits non-zero if anything failed.

Without `--loads` it expects nothing connected to the outputs and motors. With
`--loads` the self-test also pulses each output and runs each motor, and every
output must draw at least `--min-amps` (0.1 A default). `--console` needs
pyserial (`pip install -e "tools/python[bringup]"`); leave it out to run only
the CAN checks.

## ROS 2

See `ros2/robustio_ros/README.md`.

## Python

    import can
    from robustio import RobustIO

    with RobustIO(can.Bus(interface="socketcan", channel="can0"), node=0) as io:
        io.wait_ready()
        io.set_output(3, True)
        io.set_motors(40, 0)
        print(io.inputs.as_dict(), io.currents.amps, io.motors.amps)
        io.config_set("debounce", 30)

`RobustIO` keeps the latest of every status frame (`inputs`, `outputs`,
`currents`, `motors`, `heartbeat`), sends the keepalive in the background once
anything has been commanded, and accepts listeners that are called for each
decoded frame.

## Without hardware

The firmware simulator in `firmware/test` can run in real time with its CAN
traffic on a local UDP port, and every tool here can use it:

    bash firmware/test/run_sim.sh live        terminal 1: the firmware, console on stdin
    robustio -i sim watch                      terminal 2 (or tui, web, cfg, ...)
    robustio bringup --sim                     starts its own simulator and runs the full test

The simulated board has no loads or switches attached; output currents read
zero and inputs stay open unless you drive the console or the models.

## Tests

    cd tools/python && pytest

The end-to-end tests start the simulator themselves and are skipped if
`firmware/build/sim` has not been built (`bash firmware/test/run_sim.sh` builds it).
