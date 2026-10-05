# Robust IO

A rugged industrial I/O board designed in KiCad.

## Status

- **Schematic:** Complete across four hierarchical sheets — power regulation,
  ATmega1284P processor/CAN interface, multi-switch input detection, and
  high-side/motor-driver outputs.
- **PCB layout:** All footprints placed; routing in progress (not yet complete).

## Architecture

| Sheet | Contents |
|---|---|
| `power` | TPS5604 regulation, inductors, input fusing/protection |
| `processor` | ATmega1284P MCU, MCP2515 + MCP2562 (CAN), crystal, ISP header |
| `inputs` | MC33978 multi-switch detect, protected/fused input channels |
| `outputs2` | BTS7008 high-side switches, DRV8876 motor drivers, TC4427 gate drivers |

## Files

- `robust-io.kicad_pro` — project file
- `robust-io.kicad_sch` — root/hierarchical sheet
- `power.kicad_sch`, `processor.kicad_sch`, `inputs.kicad_sch`, `outputs2.kicad_sch` — schematic sheets
- `robust-io.kicad_pcb` — PCB layout

## License

See [LICENSE](LICENSE). Free for personal, educational, and open-source use.
For commercial licensing, contact ryan.lush@gmail.com.
