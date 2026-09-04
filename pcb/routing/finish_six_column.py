#!/usr/bin/env python3
"""Finish Cheapino 6-column routing.

Removes stacked A* traces that shorted ROW_4 / COL_1 / COL_2, then
re-routes those three nets sequentially on a 2-layer grid so later nets
treat earlier copper as obstacles.
"""
from __future__ import annotations

import heapq
import json
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

PCB = Path("/workspace/cheapino/pcb/cheapino.kicad_pcb")
OUT_JSON = Path("/workspace/public/board.json")
PUBLIC_PCB = Path("/workspace/public/cheapino.kicad_pcb")

GRID = 0.5
EDGE_INSET = 0.40
CLEAR_CU = 0.40
CLEAR_HOLE = 0.22
TRACE_W = 0.25
VIA_R = 0.35

NEW_NETS = {"COL_1", "COL_2", "COL_3", "ROW_4", "Net-(D22-K)", "Net-(D23-K)", "Net-(D24-K)"}


# ---------------------------------------------------------------------------
# s-expr
# ---------------------------------------------------------------------------

def tokenize(s: str):
    tokens = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "(":
            tokens.append(("LP", "(", i))
            i += 1
            continue
        if c == ")":
            tokens.append(("RP", ")", i))
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n:
                if s[j] == "\\" and j + 1 < n:
                    buf.append(s[j + 1])
                    j += 2
                    continue
                if s[j] == '"':
                    j += 1
                    break
                buf.append(s[j])
                j += 1
            tokens.append(("STR", "".join(buf), i))
            i = j
            continue
        j = i
        while j < n and s[j] not in " \t\r\n()":
            j += 1
        tokens.append(("ATOM", s[i:j], i))
        i = j
    return tokens


def parse(tokens):
    stack: list = [[]]
    for t, v, _pos in tokens:
        if t == "LP":
            stack.append([])
        elif t == "RP":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(v)
    return stack[0]


def children(node, name):
    if not isinstance(node, list):
        return []
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def first(node, name):
    cs = children(node, name)
    return cs[0] if cs else None


def nums(node):
    if not node:
        return []
    out = []
    for x in node[1:]:
        if isinstance(x, str):
            try:
                out.append(float(x))
            except ValueError:
                break
        else:
            break
    return out


def xy(node):
    ns = nums(node)
    return (ns[0], ns[1]) if len(ns) >= 2 else None


def layer_of(node):
    l = first(node, "layer")
    return l[1] if l and len(l) > 1 else None


def net_of(node):
    n = first(node, "net")
    if n and len(n) >= 2 and isinstance(n[1], str):
        return n[1]
    return None


def fp_at(fp):
    a = first(fp, "at")
    ns = nums(a)
    return ns[0], ns[1], (ns[2] if len(ns) > 2 else 0.0)


def rot(px, py, ang):
    r = math.radians(ang)
    c, s = math.cos(r), math.sin(r)
    return px * c - py * s, px * s + py * c


def pad_abs(fp, pad):
    fx, fy, fr = fp_at(fp)
    pa = first(pad, "at")
    ns = nums(pa)
    ax, ay = rot(ns[0], ns[1] if len(ns) > 1 else 0.0, fr)
    return fx + ax, fy + ay


def fmt(n: float) -> str:
    v = round(float(n), 4)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def seg_sexpr(x1, y1, x2, y2, layer, net, width=TRACE_W) -> str:
    return (
        f"\t(segment\n"
        f"\t\t(start {fmt(x1)} {fmt(y1)})\n"
        f"\t\t(end {fmt(x2)} {fmt(y2)})\n"
        f"\t\t(width {fmt(width)})\n"
        f"\t\t(layer \"{layer}\")\n"
        f"\t\t(net \"{net}\")\n"
        f"\t\t(uuid \"{uuid.uuid4()}\")\n"
        f"\t)\n"
    )


def via_sexpr(x, y, net, size=0.6, drill=0.3) -> str:
    return (
        f"\t(via\n"
        f"\t\t(at {fmt(x)} {fmt(y)})\n"
        f"\t\t(size {fmt(size)})\n"
        f"\t\t(drill {fmt(drill)})\n"
        f"\t\t(layers \"F.Cu\" \"B.Cu\")\n"
        f"\t\t(net \"{net}\")\n"
        f"\t\t(uuid \"{uuid.uuid4()}\")\n"
        f"\t)\n"
    )


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

print("loading PCB…")
text = PCB.read_text()
root = parse(tokenize(text))[0]

fps = children(root, "footprint")
refs = {}
for fp in fps:
    for p in children(fp, "property"):
        if len(p) >= 3 and p[1] == "Reference":
            refs[p[2]] = fp

edge_raw = []  # (kind, start, end, mid)
edge_segs = []
for kind in ("gr_line", "gr_arc"):
    for g in children(root, kind):
        if layer_of(g) != "Edge.Cuts":
            continue
        if kind == "gr_line":
            s, e = xy(first(g, "start")), xy(first(g, "end"))
            if s and e:
                edge_raw.append(("L", s, e, None))
                edge_segs.append((s[0], s[1], e[0], e[1]))
        else:
            s, e, m = xy(first(g, "start")), xy(first(g, "end")), xy(first(g, "mid"))
            if s and e:
                edge_raw.append(("A", s, e, m))
            if s and m:
                edge_segs.append((s[0], s[1], m[0], m[1]))
            if m and e:
                edge_segs.append((m[0], m[1], e[0], e[1]))


def point_in_board(px, py) -> bool:
    crossings = 0
    for x1, y1, x2, y2 in edge_segs:
        if y1 == y2:
            continue
        if y1 > y2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        if py < y1 or py >= y2:
            continue
        t = (py - y1) / (y2 - y1)
        ix = x1 + t * (x2 - x1)
        if ix > px:
            crossings += 1
    return crossings % 2 == 1


holes = []  # x, y, r, ref, net_or_None, npth
copper_pads = []  # x, y, r, net, ref, layers, pth, padnum

for ref, fp in refs.items():
    for pad in children(fp, "pad"):
        ptype = pad[2] if len(pad) > 2 else ""
        padnum = pad[1] if len(pad) > 1 else "?"
        x, y = pad_abs(fp, pad)
        size = nums(first(pad, "size") or [0, 0.8, 0.8])
        rx = (size[0] / 2) if size else 0.4
        ry = (size[1] / 2) if len(size) > 1 else rx
        r = max(rx, ry)
        drill = first(pad, "drill")
        dr = nums(drill)[0] / 2 if drill and nums(drill) else 0.0
        layers_n = first(pad, "layers")
        layers = [a for a in (layers_n[1:] if layers_n else []) if isinstance(a, str)]
        net = net_of(pad) or ""
        if ptype == "np_thru_hole" or (not net and dr):
            holes.append((x, y, max(dr, r), ref, None, True))
        else:
            if dr:
                holes.append((x, y, dr, ref, net, False))
            copper_pads.append((x, y, r, net, ref, tuple(layers), bool(dr), str(padnum)))


def k_pads(ref):
    fp = refs[ref]
    cx, cy, _ = fp_at(fp)
    return {
        "c": (cx, cy),
        "p1_fsmd": (cx - 6.29, cy - 5.08),
        "p1_bsmd": (cx - 6.29, cy + 5.08),
        "p1_th_a": (cx - 3.81, cy - 2.54),
        "p1_th_b": (cx - 3.81, cy + 2.54),
        "p2_th_a": (cx + 2.54, cy - 5.08),
        "p2_th_b": (cx + 2.54, cy + 5.08),
        "p2_fsmd": (cx + 7.56, cy - 2.54),
        "p2_bsmd": (cx + 7.56, cy + 2.54),
    }


def d_pads(ref):
    fp = refs[ref]
    cx, cy, _ = fp_at(fp)
    return {
        "c": (cx, cy),
        "p1_th": (cx - 3.9, cy),
        "p2_th": (cx + 3.9, cy),
    }


# ---------------------------------------------------------------------------
# existing copper (from file) — we'll drop A* / leftover junk first
# ---------------------------------------------------------------------------

def extract_blocks(src: str, header: str):
    out = []
    pat = re.compile(r"\n[ \t]*\(" + re.escape(header) + r"\b")
    for m in pat.finditer(src):
        st = src.find("(", m.start())
        depth = 0
        j = st
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append((st, j + 1))
                    break
            j += 1
    return out


def block_start_end(src, st, en):
    chunk = src[st:en]
    sm = re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    em = re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    am = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    nm = re.search(r'\(net\s+"([^"]+)"\)', chunk)
    lm = re.search(r'\(layer\s+"([^"]+)"\)', chunk)
    net = nm.group(1) if nm else ""
    layer = lm.group(1) if lm else ""
    if sm and em:
        return "seg", (float(sm.group(1)), float(sm.group(2))), (float(em.group(1)), float(em.group(2))), net, layer, sm, em
    if am:
        return "via", (float(am.group(1)), float(am.group(2))), None, net, layer, None, None
    return None, None, None, net, layer, None, None


def exactly_n_decimals(token: str, n: int) -> bool:
    if "." not in token:
        return n == 0
    frac = token.split(".", 1)[1]
    return len(frac) == n


ASTAR_4DEC = True


def is_astar_pair(sx, sy, ex, ey) -> bool:
    """A* writer used fmt() → at most 4 decimals; maze cells are *.xxxx with 4 digits."""
    return (
        exactly_n_decimals(sx, 4)
        and exactly_n_decimals(sy, 4)
        and exactly_n_decimals(ex, 4)
        and exactly_n_decimals(ey, 4)
    )


# leftover long runs that go through holes / don't join the matrix
BAD_SEGS = {
    tuple(sorted(((round(a[0], 3), round(a[1], 3)), (round(b[0], 3), round(b[1], 3)))))
    for a, b in (
        ((54.85, 111.0), (54.85, 90.0)),
        ((54.85, 90.0), (148.0, 90.0)),
        ((148.0, 90.0), (148.0, 111.0)),
        ((54.85, 118.49), (54.85, 80.49)),
        ((54.85, 80.49), (54.85, 111.0)),
        ((55.7, 108.0), (55.7, 92.0)),
        ((55.7, 92.0), (119.7, 92.0)),
        ((119.7, 92.0), (119.7, 108.0)),
        ((46.2, 95.8), (84.2, 95.8)),
        ((46.2, 91.87), (46.2, 95.8)),
        ((84.2, 105.0), (84.2, 95.8)),
        ((52.55, 75.41), (47.05, 75.41)),
        ((47.05, 75.41), (47.05, 80.49)),
        ((57.57, 72.87), (52.55, 75.41)),
        ((47.05, 94.41), (47.05, 99.49)),
        ((47.05, 116.41), (47.05, 118.49)),
        ((41.6, 87.25), (41.6, 122.0)),
        ((42.2, 68.25), (42.2, 108.0)),
        ((42.2, 108.0), (54.0, 108.0)),
        ((54.0, 108.0), (55.7, 108.0)),
        ((43.72, 68.25), (42.2, 68.25)),
        ((43.72, 87.25), (41.6, 87.25)),
        ((148.0, 111.0), (148.0, 112.0)),
        ((148.0, 112.0), (174.9, 112.0)),
    )
}

BAD_VIAS = {
    (round(41.6, 3), round(122.0, 3)),
    (round(54.85, 3), round(111.0, 3)),
    (round(148.0, 3), round(111.0, 3)),
    (round(42.2, 3), round(108.0, 3)),
    (round(54.0, 3), round(108.0, 3)),
    (round(55.7, 3), round(108.0, 3)),
}


remove_ranges = []
kept_segs = []  # (st, en, net, layer)
kept_vias = []

for st, en in extract_blocks(text, "segment"):
    kind, a, b, net, layer, sm, em = block_start_end(text, st, en)
    if kind != "seg":
        continue
    sx, sy = sm.group(1), sm.group(2)
    ex, ey = em.group(1), em.group(2)
    key = tuple(sorted(((round(a[0], 3), round(a[1], 3)), (round(b[0], 3), round(b[1], 3)))))
    drop = False
    if net in ("ROW_4", "COL_1", "COL_2") and is_astar_pair(sx, sy, ex, ey):
        drop = True
    if key in BAD_SEGS:
        drop = True
    if drop:
        remove_ranges.append((st, en))
    else:
        kept_segs.append((a, b, net, layer))

for st, en in extract_blocks(text, "via"):
    kind, a, b, net, layer, sm, em = block_start_end(text, st, en)
    if kind != "via":
        continue
    k = (round(a[0], 3), round(a[1], 3))
    if k in BAD_VIAS:
        remove_ranges.append((st, en))
    else:
        kept_vias.append((a, net))

print(f"removing {len(remove_ranges)} leftover/A* blocks; keeping {len(kept_segs)} segs, {len(kept_vias)} vias")

# ---------------------------------------------------------------------------
# local stitches (idempotent: we add them; duplicates on same net are ok but
# we skip near-identical kept segs)
# ---------------------------------------------------------------------------

def seg_exists(x1, y1, x2, y2, layer, net, tol=0.05):
    for a, b, n, l in kept_segs:
        if n != net or l != layer:
            continue
        if (math.hypot(a[0] - x1, a[1] - y1) < tol and math.hypot(b[0] - x2, b[1] - y2) < tol) or (
            math.hypot(a[0] - x2, a[1] - y2) < tol and math.hypot(b[0] - x1, b[1] - y1) < tol
        ):
            return True
    return False


new_parts: list[str] = []
new_segs: list[tuple] = []  # (st, en, net, layer)
new_vias: list[tuple] = []


def add_seg(x1, y1, x2, y2, layer, net, width=TRACE_W):
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return
    if seg_exists(x1, y1, x2, y2, layer, net):
        return
    new_parts.append(seg_sexpr(x1, y1, x2, y2, layer, net, width))
    new_segs.append(((x1, y1), (x2, y2), net, layer))


def add_via(x, y, net):
    new_parts.append(via_sexpr(x, y, net))
    new_vias.append(((x, y), net))


def stitch_switch(ref, col_net, diode_net):
    p = k_pads(ref)
    ax, ay = p["p1_fsmd"]
    bx, by = p["p1_th_a"]
    # vertical at SMD x, then horizontal at TH y — avoids MX NPTH
    add_seg(ax, ay, ax, by, "F.Cu", col_net)
    add_seg(ax, by, bx, by, "F.Cu", col_net)
    cx1, cy1 = p["p1_bsmd"]
    dx, dy = p["p1_th_b"]
    add_seg(cx1, cy1, cx1, dy, "B.Cu", col_net)
    add_seg(cx1, dy, dx, dy, "B.Cu", col_net)
    a2x, a2y = p["p2_fsmd"]
    b2x, b2y = p["p2_th_a"]
    # vertical at SMD x, then horizontal at TH y — avoids MX NPTH at (cx+3.81, cy-2.54)
    add_seg(a2x, a2y, a2x, b2y, "F.Cu", diode_net)
    add_seg(a2x, b2y, b2x, b2y, "F.Cu", diode_net)
    c2x, c2y = p["p2_bsmd"]
    d2x, d2y = p["p2_th_b"]
    add_seg(c2x, c2y, c2x, d2y, "B.Cu", diode_net)
    add_seg(c2x, d2y, d2x, d2y, "B.Cu", diode_net)


print("local switch/diode stitches…")
stitch_switch("K19", "COL_1", "Net-(D22-K)")
stitch_switch("K20", "COL_2", "Net-(D23-K)")
stitch_switch("K21", "COL_3", "Net-(D24-K)")

# diode pad1 ← switch pad2, routed BELOW the switch (avoids MX NPTH at y of pad2)
for kref, dref, dnet in (
    ("K19", "D22", "Net-(D22-K)"),
    ("K20", "D23", "Net-(D23-K)"),
    ("K21", "D24", "Net-(D24-K)"),
):
    kp, dp = k_pads(kref), d_pads(dref)
    sx, sy = kp["p2_th_b"]
    ex, ey = dp["p1_th"]
    mid_y = (sy + ey) / 2.0  # between switch and diode
    add_seg(sx, sy, sx, mid_y, "B.Cu", dnet)
    add_seg(sx, mid_y, ex, mid_y, "B.Cu", dnet)
    add_seg(ex, mid_y, ex, ey, "B.Cu", dnet)

# ROW_4 backbone in the inter-column channel
print("ROW_4 diode backbone…")
CH = 58.4
d22, d23, d24 = d_pads("D22"), d_pads("D23"), d_pads("D24")
add_seg(d22["p2_th"][0], d22["p2_th"][1], CH, d22["p2_th"][1], "B.Cu", "ROW_4")
add_seg(d23["p2_th"][0], d23["p2_th"][1], CH, d23["p2_th"][1], "B.Cu", "ROW_4")
add_seg(d24["p2_th"][0], d24["p2_th"][1], CH, d24["p2_th"][1], "B.Cu", "ROW_4")
add_seg(CH, d24["p2_th"][1], CH, 115.0, "B.Cu", "ROW_4")
add_seg(CH, d22["p2_th"][1], CH, 115.0, "B.Cu", "ROW_4")

# COL_3 already joins K21 along y=115.5 in kept segs.

# ---------------------------------------------------------------------------
# occupancy / A*
# ---------------------------------------------------------------------------

xs = [x for x1, y1, x2, y2 in edge_segs for x in (x1, x2)]
ys = [y for x1, y1, x2, y2 in edge_segs for y in (y1, y2)]
X0, Y0 = min(xs) - 1, min(ys) - 1
X1, Y1 = max(xs) + 1, max(ys) + 1
W = int((X1 - X0) / GRID) + 1
H = int((Y1 - Y0) / GRID) + 1
print(f"grid {W}x{H} layers=2")


def gxy(x, y):
    return int(round((x - X0) / GRID)), int(round((y - Y0) / GRID))


def xy_of(i, j):
    return X0 + i * GRID, Y0 + j * GRID


# board mask
board_ok = [[False] * H for _ in range(W)]
for i in range(W):
    for j in range(H):
        x, y = xy_of(i, j)
        if not point_in_board(x, y):
            continue
        if not (
            point_in_board(x + EDGE_INSET, y)
            and point_in_board(x - EDGE_INSET, y)
            and point_in_board(x, y + EDGE_INSET)
            and point_in_board(x, y - EDGE_INSET)
        ):
            continue
        board_ok[i][j] = True


def fill_circle(mask, cx, cy, rr):
    i0, j0 = gxy(cx - rr, cy - rr)
    i1, j1 = gxy(cx + rr, cy + rr)
    r2 = rr * rr
    for i in range(max(0, i0), min(W, i1 + 1)):
        for j in range(max(0, j0), min(H, j1 + 1)):
            x, y = xy_of(i, j)
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                mask[i][j] = True


def dist_point_seg(px, py, x1, y1, x2, y2):
    vx, vy = x2 - x1, y2 - y1
    l2 = vx * vx + vy * vy
    if l2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / l2))
    return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))


def fill_stadium(mask, x1, y1, x2, y2, rr):
    i0, j0 = gxy(min(x1, x2) - rr, min(y1, y2) - rr)
    i1, j1 = gxy(max(x1, x2) + rr, max(y1, y2) + rr)
    for i in range(max(0, i0), min(W, i1 + 1)):
        for j in range(max(0, j0), min(H, j1 + 1)):
            x, y = xy_of(i, j)
            if dist_point_seg(x, y, x1, y1, x2, y2) <= rr:
                mask[i][j] = True


LAYERS = ("F.Cu", "B.Cu")
LIDX = {"F.Cu": 0, "B.Cu": 1}


def blank_mask():
    return [[[False] * H for _ in range(W)] for _ in range(2)]


# static obstacles: holes + other-net pads. Traces filled per-net.
hole_mask = [[False] * H for _ in range(W)]  # NPTH always
npth_only = [[False] * H for _ in range(W)]
for hx, hy, hr, ref, hnet, npth in holes:
    fill_circle(npth_only if npth else hole_mask, hx, hy, hr + CLEAR_HOLE)
    if npth:
        fill_circle(hole_mask, hx, hy, hr + CLEAR_HOLE)


def layer_hits(layers, layer_name):
    if not layers:
        return True
    for l in layers:
        if l == layer_name or l.startswith("*.") or l == "*.Cu":
            return True
        if layer_name[:2] in l and "Cu" in l:
            return True
    return False


def build_blocked(net: str, extra_segs, extra_vias):
    """Blocked[layer][i][j] for this net."""
    blocked = blank_mask()
    # board + holes
    for i in range(W):
        for j in range(H):
            if not board_ok[i][j] or hole_mask[i][j]:
                blocked[0][i][j] = True
                blocked[1][i][j] = True
    # other-net plated holes: already in hole_mask unless same net
    for hx, hy, hr, ref, hnet, npth in holes:
        if npth:
            continue
        if hnet == net:
            # un-block this hole so we can touch the pad
            i0, j0 = gxy(hx - hr, hy - hr)
            i1, j1 = gxy(hx + hr, hy + hr)
            r2 = (hr + 0.05) ** 2
            for i in range(max(0, i0), min(W, i1 + 1)):
                for j in range(max(0, j0), min(H, j1 + 1)):
                    x, y = xy_of(i, j)
                    if (x - hx) ** 2 + (y - hy) ** 2 <= r2 and board_ok[i][j]:
                        blocked[0][i][j] = False
                        blocked[1][i][j] = False
    # pads
    for px, py, pr, pnet, ref, layers, pth, padnum in copper_pads:
        if pnet == net:
            continue
        rr = pr + CLEAR_CU
        for li, ln in enumerate(LAYERS):
            if pth or layer_hits(layers, ln):
                fill_circle(blocked[li], px, py, rr)
    # traces
    for a, b, n, l in list(kept_segs) + list(extra_segs):
        if n == net:
            continue
        if l not in LIDX:
            continue
        fill_stadium(blocked[LIDX[l]], a[0], a[1], b[0], b[1], TRACE_W / 2 + CLEAR_CU)
    # vias of other nets block both layers
    for at, n in list(kept_vias) + list(extra_vias):
        if n == net:
            continue
        fill_circle(blocked[0], at[0], at[1], VIA_R + CLEAR_CU)
        fill_circle(blocked[1], at[0], at[1], VIA_R + CLEAR_CU)
    return blocked


def nearest_free(blocked, layer, i, j, max_r=14):
    if 0 <= i < W and 0 <= j < H and not blocked[layer][i][j]:
        return i, j
    for r in range(1, max_r + 1):
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                if abs(di) != r and abs(dj) != r:
                    continue
                ni, nj = i + di, j + dj
                if 0 <= ni < W and 0 <= nj < H and not blocked[layer][ni][nj]:
                    return ni, nj
    return None


def astar(blocked, start, goal, start_layer=1, goal_layer=1, max_exp=400000):
    """start/goal are (x,y). layer 0=F 1=B. Returns list of (x,y,layer) or None."""
    si, sj = gxy(*start)
    gi, gj = gxy(*goal)
    s = nearest_free(blocked, start_layer, si, sj)
    g = nearest_free(blocked, goal_layer, gi, gj)
    if not s or not g:
        print(f"  no free start/goal {start}->{goal}")
        return None
    si, sj = s
    gi, gj = g
    start_state = (si, sj, start_layer)
    goal_state = (gi, gj, goal_layer)

    def h(i, j, l):
        return abs(i - gi) + abs(j - gj) + (0 if l == goal_layer else 3)

    openh = [(h(si, sj, start_layer), 0, si, sj, start_layer)]
    came = {}
    gscore = {start_state: 0}
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    exp = 0
    while openh and exp < max_exp:
        _f, cost, i, j, l = heapq.heappop(openh)
        exp += 1
        if (i, j, l) == goal_state:
            path = [(i, j, l)]
            while (i, j, l) in came:
                i, j, l = came[(i, j, l)]
                path.append((i, j, l))
            path.reverse()
            print(f"  A* ok {len(path)} cells, {exp} expansions")
            return [(xy_of(a, b)[0], xy_of(a, b)[1], la) for a, b, la in path]
        # orthogonal
        for di, dj in dirs:
            ni, nj = i + di, j + dj
            if not (0 <= ni < W and 0 <= nj < H):
                continue
            if blocked[l][ni][nj]:
                continue
            ng = cost + 1
            st = (ni, nj, l)
            if ng < gscore.get(st, 1e18):
                gscore[st] = ng
                came[st] = (i, j, l)
                heapq.heappush(openh, (ng + h(ni, nj, l), ng, ni, nj, l))
        # via
        ol = 1 - l
        if not blocked[ol][i][j]:
            ng = cost + 6
            st = (i, j, ol)
            if ng < gscore.get(st, 1e18):
                gscore[st] = ng
                came[st] = (i, j, l)
                heapq.heappush(openh, (ng + h(i, j, ol), ng, i, j, ol))
    print(f"  A* FAILED after {exp} expansions {start}->{goal}")
    return None


def compress_layer_path(path):
    """Keep corners and layer changes."""
    if not path:
        return path
    out = [path[0]]
    for p in path[1:]:
        if len(out) < 2:
            out.append(p)
            continue
        a, b = out[-2], out[-1]
        if a[2] != b[2] or b[2] != p[2]:
            out.append(p)
            continue
        colinear = (abs(a[0] - b[0]) < 1e-9 and abs(b[0] - p[0]) < 1e-9) or (
            abs(a[1] - b[1]) < 1e-9 and abs(b[1] - p[1]) < 1e-9
        )
        if colinear:
            out[-1] = p
        else:
            out.append(p)
    return out


def emit_path(path, net):
    pts = compress_layer_path(path)
    for a, b in zip(pts, pts[1:]):
        if a[2] != b[2]:
            add_via(a[0], a[1], net)
            continue
        layer = LAYERS[a[2]]
        add_seg(a[0], a[1], b[0], b[1], layer, net)


def route_net(net, start, goal, label, start_layer=1, goal_layer=1):
    print(f"route {label} {net} {start} -> {goal}")
    blocked = build_blocked(net, new_segs, new_vias)
    # allow start/goal neighborhood
    for pt, ly in ((start, start_layer), (goal, goal_layer)):
        i, j = gxy(*pt)
        for di in range(-2, 3):
            for dj in range(-2, 3):
                ni, nj = i + di, j + dj
                if 0 <= ni < W and 0 <= nj < H and board_ok[ni][nj]:
                    blocked[ly][ni][nj] = False
    path = astar(blocked, start, goal, start_layer, goal_layer)
    if not path:
        return False
    emit_path(path, net)
    return True


k19, k20, k21 = k_pads("K19"), k_pads("K20"), k_pads("K21")
k4, k10 = k_pads("K4"), k_pads("K10")
ROW4_VIA = (167.2844, 74.2442)

print("long routes (sequential, other copper is obstacle)…")
ok_r4 = route_net("ROW_4", (CH, d22["p2_th"][1]), ROW4_VIA, "ROW_4 backbone to MCU via")
ok_c1 = route_net("COL_1", k19["p1_bsmd"], k4["p1_bsmd"], "COL_1 K19 to K4")
ok_c2 = route_net("COL_2", k20["p1_bsmd"], k10["p1_bsmd"], "COL_2 K20 to K10")
# COL_3: stay on B.Cu under K21 (y=118.9) to the existing via at (55.7, 115.5)
add_seg(k21["p1_bsmd"][0], k21["p1_bsmd"][1], k21["p1_bsmd"][0], 118.9, "B.Cu", "COL_3")
add_seg(k21["p1_bsmd"][0], 118.9, 55.7, 118.9, "B.Cu", "COL_3")
add_seg(55.7, 118.9, 55.7, 115.5, "B.Cu", "COL_3")
print("route results", {"ROW_4": ok_r4, "COL_1": ok_c1, "COL_2": ok_c2})
print(f"new copper items: {len(new_parts)}")

if not (ok_r4 and ok_c1 and ok_c2):
    raise SystemExit("routing failed; not writing file")

# ---------------------------------------------------------------------------
# rewrite PCB text
# ---------------------------------------------------------------------------

remove_ranges = sorted(set(remove_ranges), reverse=True)
new_text = text
for st, en in remove_ranges:
    while st > 0 and new_text[st - 1] in " \t":
        st -= 1
    if st > 0 and new_text[st - 1] == "\n":
        st -= 1
    new_text = new_text[:st] + new_text[en:]

insert = "\n" + "".join(new_parts)
idx = new_text.rfind("(embedded_fonts no)")
if idx < 0:
    raise SystemExit("could not find insertion point")
new_text = new_text[:idx] + insert + "\n\t" + new_text[idx:]

bal = 0
for c in new_text:
    if c == "(":
        bal += 1
    elif c == ")":
        bal -= 1
print("paren balance", bal)
if bal != 0:
    raise SystemExit("paren imbalance, abort")

PCB.write_text(new_text)
PUBLIC_PCB.write_text(new_text)
print("wrote", PCB, "bytes", len(new_text))
