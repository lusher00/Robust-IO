#!/bin/bash
# Generates the documentation PDFs and images in docs/ from the KiCad files.
# Run after saving the schematic and board:  bash docs/make_docs.sh
cd "$(dirname "$0")/.."
CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
OUT=docs
SCH=robust-io.kicad_sch
PCB=robust-io.kicad_pcb
FAIL=0

step() {
  local name="$1"; shift
  if "$@" > "$OUT/.last.log" 2>&1; then
    echo "ok    $name"
  else
    echo "FAIL  $name"; sed 's/^/        /' "$OUT/.last.log"; FAIL=1
  fi
}

# Schematic, all sheets in one PDF
step "schematic PDF" \
  "$CLI" sch export pdf --output "$OUT/robust-io-schematic.pdf" "$SCH"

# 3D renders
step "3D render, top" \
  "$CLI" pcb render --output "$OUT/board-top.png" --side top \
  --width 2400 --height 1600 --quality high --background opaque "$PCB"
step "3D render, bottom" \
  "$CLI" pcb render --output "$OUT/board-bottom.png" --side bottom \
  --width 2400 --height 1600 --quality high --background opaque "$PCB"
step "3D render, angled" \
  "$CLI" pcb render --output "$OUT/board-angle.png" --side top \
  --rotate "-45,0,20" --perspective \
  --width 2400 --height 1600 --quality high --background opaque "$PCB"

# Layout drawings (PDF)
step "layout PDF, top copper" \
  "$CLI" pcb export pdf --output "$OUT/layout-top.pdf" --mode-single \
  --layers F.Cu,F.SilkS,Edge.Cuts "$PCB"
step "layout PDF, bottom copper" \
  "$CLI" pcb export pdf --output "$OUT/layout-bottom.pdf" --mode-single --mirror \
  --layers B.Cu,B.SilkS,Edge.Cuts "$PCB"
step "assembly drawing PDF" \
  "$CLI" pcb export pdf --output "$OUT/assembly-top.pdf" --mode-single --black-and-white \
  --layers F.Fab,F.SilkS,Edge.Cuts "$PCB"

rm -f "$OUT/.last.log"
echo
ls -l "$OUT"
exit $FAIL
