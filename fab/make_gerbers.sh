#!/bin/bash
# Plots Gerbers and drill files for robust-io with KiCad's command line tool and zips them for upload.
set -e
cd "$(dirname "$0")/.."
CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
OUT=fab/gerbers
mkdir -p "$OUT"
"$CLI" pcb export gerbers --output "$OUT/" \
  --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  --subtract-soldermask robust-io.kicad_pcb
"$CLI" pcb export drill --output "$OUT/" --format excellon --drill-origin absolute \
  --excellon-units mm --excellon-zeros-format decimal --excellon-separate-th robust-io.kicad_pcb
"$CLI" pcb export pos --output fab/kicad-pos.csv --format csv --units mm --side both robust-io.kicad_pcb
( cd "$OUT" && zip -q -r ../robust-io-gerbers.zip . )
echo "Done:"; ls -l "$OUT" fab/robust-io-gerbers.zip
