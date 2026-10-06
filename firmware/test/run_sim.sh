#!/bin/bash
# Builds the simulator and runs the firmware against the scenario scripts below,
# or, with 'live [PORT]', runs it in real time for the host tools (tools/python).
# Needs simavr (headers and library) and libelf. Run from firmware/.
set -e
cd "$(dirname "$0")/.."
make -s
# Linux: apt install libsimavr-dev libelf-dev. macOS: brew install simavr (osx-cross/avr tap) libelf.
PREFIX=$(brew --prefix 2>/dev/null || echo /usr)
cc -O1 -o build/sim test/sim.c -I"$PREFIX/include/simavr" -I"$PREFIX/include" -L"$PREFIX/lib" -lsimavr -lelf
ELF=build/robust-io.elf

if [ "$1" = "live" ]; then
  echo "firmware running in real time; CAN on udp 127.0.0.1:${2:-29536}; type console commands here"
  echo "in another terminal: robustio -i sim status"
  exec build/sim $ELF --udp "${2:-29536}"
fi

case "${1:-all}" in
boot|all)
  echo "=== boot, version, config"
  build/sim $ELF "mute:1; c:ver; c:cfg" ;;&
selftest|all)
  echo "=== selftest with outputs and motors (sense line 0 V, motor current 0)"
  build/sim $ELF "mute:1; c:selftest out motor; w:6000" ;;&
inputs|all)
  echo "=== inputs: debounce and CAN on change"
  build/sim $ELF "mute:1; w:200; c:in; mute:0; in:000005; w:60; mute:1; c:in; in:200000; w:10; in:000005; w:60; c:in" ;;&
can|all)
  echo "=== CAN: host sets outputs and motors, then goes quiet"
  build/sim $ELF "w:250; rx:200 FF 03; w:120; rx:210 32 CE; w:300; c:motor; c:can; mute:1; w:600; c:out; c:motor; c:can" ;;&
config|all)
  echo "=== CAN config: read, write, save"
  build/sim $ELF "mute:1; w:100; mute:0; rx:230 00 02; w:20; rx:230 01 02 E8 03; w:20; rx:230 01 02 FF FF; w:20; rx:230 02 00; w:200; mute:1; c:cfg" ;;&
protect|all)
  echo "=== output trip and motor fault"
  build/sim $ELF "mute:1; adc:1:900; c:out 2 1; w:300; c:isense; c:motor 0 50; w:100; fault:1; w:20; fault:0; c:motor; c:motor 0 30; c:motor clear; c:motor 0 30; w:100; c:motor" ;;&
noack|all)
  echo "=== no other node on the bus"
  build/sim $ELF "mute:1; ack:0; w:1000; c:can" ;;
esac
