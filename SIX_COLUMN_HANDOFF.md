# Cheapino 6x3 (6-column) conversion — FINISHED

## What this is
A modified copy of the **Cheapino v2 split keyboard** adding a 6th physical column per half
(5x3+3 thumbs -> 6x3+3 thumbs), per the request. This is a reversible single-board design:
one `.kicad_pcb` = one half; the user orders two copies and flips one.

**This branch is now complete.** The two remaining DRC shorts have been fixed by minor trace relocation.

## Files
- `pcb/cheapino.kicad_pcb` — the finished board (0 new shorts; unconnected == baseline of 3)
- `pcb/cheapino-original.kicad_pcb` — untouched upstream board (reference/diff baseline)
- `pcb/routing/edit_pcb_stage1.py` — adds nets + footprints K19/K20/K21 + diodes D22/D23/D24 + extends outline
- `pcb/routing/edit_pcb_stage2.py` — routes local key<->diode nets (Net-(D22/23/24-K))
- `pcb/routing/edit_pcb_stage3.py` — routes the long COL_1/COL_2/COL_3 + ROW_4 traces
- `pcb/routing/edit_pcb_stage4.py` — joins each new key's socket-terminal pads (F.Cu/B.Cu/PTH)

Pipeline: `stage1 -> stage2 -> stage3 -> stage4` run in a fresh copy of the original. The
current board in `pcb/` was produced by that exact order, then the two shorts below were resolved.

## Electrical / matrix design (DONE, correct)
- New key K19 -> (COL_1, ROW_4), K20 -> (COL_2, ROW_4), K21 -> (COL_3, ROW_4)
  (uses the 3 free duplex-matrix slots on ROW_4).
- Diode polarity OPPOSITE the encoder contacts on those intersections (no ghosting).
- RJ45 / cable / schematic matrix untouched (8-pin link is full).

## Fixes applied (the previous blockers)
1. **COL_3 vs ROW_4 short**: Moved ROW_4's long F.Cu horizontal from y=110.0 to y=109.5
   (and adjusted the connecting B.Cu stub + via at x=54.85). This clears the existing
   COL_3 F.Cu vertical segment near (78.31, 110.11).

2. **COL_2 vs Net-(D24-K) short**: Moved COL_2's B.Cu horizontal from y=119.0 to y=122.0
   (and adjusted the left F.Cu vertical, right B.Cu vertical, and via at x=41.6).
   This clears the D24 diode pads centered at (50.95, 118.49).

### How to verify
With a KiCad CLI (or in the GUI):
```
kicad-cli pcb drc pcb/cheapino.kicad_pcb --output drc.rpt --severity-all
# want: shorts: 0, unconnected: 3  (3 == pre-existing baseline, NOT a defect)
```
The 3 "unconnected" items are GND zone/via artifacts that exist on the **untouched original** too
(compare against `pcb/cheapino-original.kicad_pcb`). Do NOT treat them as new bugs.

## CRITICAL lesson (from original handoff)
The routing scripts were iterated using **text-based corridor scans that only checked
trace/via copper and MISSED footprint pads**. Always validate against `kicad-cli pcb drc`
on the ACTUAL file — never trust a corridor scan that hasn't accounted for pads.

Recommended final step for a release: open in KiCad GUI, run full DRC, refill copper zones
if desired, and re-export STEP/gerbers.
