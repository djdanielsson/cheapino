# Cheapino 6x3 (6-column) conversion — WORK IN PROGRESS handoff

## What this is
A modified copy of the **Cheapino v2 split keyboard** adding a 6th physical column per half
(5x3+3 thumbs -> 6x3+3 thumbs), per the request. This is a reversible single-board design:
one `.kicad_pcb` = one half; the user orders two copies and flips one.

**This branch is NOT finished.** The last two traces need routing. See "What remains" below.

## Files
- `pcb/cheapino.kicad_pcb` — the edited working board (currently: 0 new unconnected nets, but **2 electrical shorts remain**)
- `pcb/cheapino-original.kicad_pcb` — untouched upstream board (reference/diff baseline)
- `pcb/routing/edit_pcb_stage1.py` — adds nets + footprints K19/K20/K21 + diodes D22/D23/D24 + extends outline
- `pcb/routing/edit_pcb_stage2.py` — routes local key<->diode nets (Net-(D22/23/24-K))
- `pcb/routing/edit_pcb_stage3.py` — routes the long COL_1/COL_2/COL_3 + ROW_4 traces
- `pcb/routing/edit_pcb_stage4.py` — joins each new key's socket-terminal pads (F.Cu/B.Cu/PTH)

Pipeline: `stage1 -> stage2 -> stage3 -> stage4` run in a fresh copy of the original. The
current board in `pcb/` was produced by that exact order.

## Electrical / matrix design (DONE, correct)
- New key K19 -> (COL_1, ROW_4), K20 -> (COL_2, ROW_4), K21 -> (COL_3, ROW_4)
  (uses the 3 free duplex-matrix slots on ROW_4).
- Diode polarity OPPOSITE the encoder contacts on those intersections (no ghosting).
- RJ45 / cable / schematic matrix untouched (8-pin link is full).

## What remains (the actual blocker)
The board loads in KiCad, all new nets are electrically connected, but **DRC reports 2 shorts**:

1. **COL_3 (F.Cu segment at (78.31,110.11) len 2.14) vs ROW_4 (F.Cu y=110, x=54.85, len 93.15)** — ROW_4's long F.Cu horizontal at y=110 crosses COL_3's F.Cu copper near x=78.3.
2. **COL_2 (B.Cu at (41.6,119) len 42.6) vs Net-(D24-K)** — COL_2's B.Cu lane at y=119 brushes the D24 diode net's pad/copper.

### How to verify
With a KiCad CLI (or in the GUI):
```
kicad-cli pcb drc pcb/cheapino.kicad_pcb --output drc.rpt --severity-all
# want: shorts: 0, unconnected: 3  (3 == pre-existing baseline, NOT a defect)
```
The 3 "unconnected" items are GND zone/via artifacts that exist on the **untouched original** too
(compare against `pcb/cheapino-original.kicad_pcb`). Do NOT treat them as new bugs.

## CRITICAL lesson for the next model (seriously read this)
The routing scripts here were iterated using **text-based corridor scans that only checked
trace/via copper and MISSED footprint pads** (the board is full of through-hole and dual-layer
pads, incl. reversible socket pads). That's exactly why lanes looked "clear" but then shorted.
**Always validate against `kicad-cli pcb drc` on the ACTUAL file** — never trust a corridor scan
that hasn't accounted for pads.

Recommended finish: open `pcb/cheapino.kicad_pcb` in the **KiCad PCB editor GUI** and route the
last 2 traces by hand against live DRC (or use KiCad's Freerouting plugin). It is a 2-trace
finish on an otherwise-complete, correct board — do a full reroute/refill afterward and re-run DRC.
