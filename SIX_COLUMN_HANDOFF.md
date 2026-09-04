# Cheapino 6×3 (6-column) conversion

A modified Cheapino v2 half with a 6th physical column (5×3+3 thumbs → 6×3+3 thumbs).
Reversible: order two copies, flip one.

## Status — routing complete

- Edge.Cuts is a **single closed outline**; the new column sits on a left peninsula.
- File is valid KiCad S-expression (paren-balanced).
- **No traces through the bottom cutout.**
- **New-column traces clear MX NPTH holes** (pad-1 / pad-2 stitches go vertical-at-SMD-x, then horizontal-at-TH-y).
- K19 / K20 / K21 + D22 / D23 / D24 are on-board and matrix-wired:
  - K19 → (COL_1, ROW_4) via D22, column joined to K4
  - K20 → (COL_2, ROW_4) via D23, column joined to K10
  - K21 → (COL_3, ROW_4) via D24, column joined to K15 / K14 (B.Cu bypass under K21 at y=118.9)
- ROW_4 diode backbone (x=58.4) reaches U1 pad 8 (RP2040).
- No shorts between ROW_4 / COL_1 / COL_2 / COL_3.

## Before fab

1. Open `pcb/cheapino.kicad_pcb` in KiCad 8 or 10.
2. **Fill All Zones (B)** — the GND pour is unfilled after outline edits.
3. Re-run DRC. Expect 0 shorts; zone-related warnings until step 2.
4. Plot Gerbers + drill as usual.

## Files

- `pcb/cheapino.kicad_pcb` — this board
- `pcb/cheapino-original.kicad_pcb` — untouched upstream
- `pcb/routing/verify_and_patch.py` — NPTH-safe stitches + checks (`--verify-only` to re-export)
- `pcb/routing/finish_six_column.py` — sequential A* for ROW_4 / COL_1 / COL_2 (do not re-run unless you intend to replace those long runs)
