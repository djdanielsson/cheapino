# Cheapino 6×3 (6-column) conversion

A modified Cheapino v2 half with a 6th physical column (5×3+3 thumbs → 6×3+3 thumbs).
Reversible: order two copies, flip one.

## Status — ready to plot Gerbers after zone fill

- Edge.Cuts is a **single closed outline**; the new column sits on a left peninsula.
- File is valid KiCad S-expression (paren-balanced).
- **No traces through the bottom cutout.**
- K19 / K20 / K21 + D22 / D23 / D24 matrix-wired:
  - K19 → (COL_1, ROW_4) via D22, column joined to K4
  - K20 → (COL_2, ROW_4) via D23, column joined to K10
  - K21 → (COL_3, ROW_4) via D24, column joined to K15
- ROW_4 diode backbone (x=58.4) reaches U1 pad 8 (RP2040).
- Duplicate MX/diode pads are jumpers (KiCad 10 `duplicate_pad_numbers_are_jumpers yes`).
- K21 diode net `Net-(D24-K)` runs on **F.Cu** under the switch so it does not short COL_3 on B.Cu.

## Before fab (in KiCad)

1. Reload `pcb/cheapino.kicad_pcb` (File → Revert / reopen) so you have this version.
2. **Fill All Zones (B)** — keep “Refill all zones before DRC” checked.
3. Run DRC. Expect:
   - **0 shorting items**
   - Hole-clearance errors around MX NPTH (same as stock Cheapino) — ignore
   - Unconnected `R_COL_*` / `R_ROW_*` / `JP*` — those are the right-half solder bridges
4. Plot Gerbers + drill (Protel names, F/B Cu, Silk, Mask, Edge.Cuts).
5. Upload the zip to JLCPCB: 2-layer, 1.6 mm, HASL. Order 5; a split uses 2 (flip one).

## Files

- `pcb/cheapino.kicad_pcb` — this board
- `pcb/cheapino-original.kicad_pcb` — untouched upstream
- `pcb/routing/verify_and_patch.py` — checks (`--verify-only`)
