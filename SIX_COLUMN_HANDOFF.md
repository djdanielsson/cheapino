# Cheapino 6x3 (6-column) conversion — FINISHED & VALIDATED

## What this is
A modified copy of the **Cheapino v2 split keyboard** adding a 6th physical column per half
(5x3+3 thumbs -> 6x3+3 thumbs), per the request. This is a reversible single-board design:
one `.kicad_pcb` = one half; the user orders two copies and flips one.

**This branch is complete and DRC-validated** with KiCad 8.0.9.

## Validation (KiCad 8.0.9)
```
kicad-cli pcb drc pcb/cheapino.kicad_pcb --severity-all
→ shorting_items: 0
→ unconnected_items: 3   (exact baseline of the original board)
```
Original board also has 0 shorts / 3 unconnected. Many silk/hole/clearance warnings remain
(pre-existing; original had ~432 total violations, this board ~365).

## Files
- `pcb/cheapino.kicad_pcb` — finished board
- `pcb/cheapino-original.kicad_pcb` — untouched upstream board (reference)
- `pcb/routing/edit_pcb_stage1.py` … `stage4.py` — original WIP pipeline

## Electrical / matrix design (DONE)
- K19 → (COL_1, ROW_4), K20 → (COL_2, ROW_4), K21 → (COL_3, ROW_4)
- Diode polarity opposite encoder contacts on those intersections
- RJ45 / cable / schematic matrix untouched

## Routing fixes applied
1. COL_2 B.Cu horizontal moved to **y=122** (clears D24 pads @ y≈118.5)
2. ROW_4 long horizontal moved to **B.Cu at y=111** + via at (148, 111)
   (avoids dense COL_3 / ROW_2 F.Cu copper on the left side of the board)

## Recommended next steps for release
- Open in KiCad GUI, refill copper zones if desired
- Re-run full DRC + visual inspection
- Export gerbers / STEP as usual
