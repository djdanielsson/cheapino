#!/usr/bin/env python3
"""Finish Cheapino 6-column routing.

Fixes from the 3mm column shift + cutout re-route:
  * diode stubs that no longer hit D22/D23/D24
  * COL_1 traces sitting on Net-(D22-K) copper
  * long ROW_4 / COL_1 / COL_2 runs through switch holes, D9 pads, and the
    bottom cutout
  * missing on-board path from the new column to the original matrix
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
OUT_JSON = Path("/workspace/cheapino/pcb/routing/board_view.json")

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
    ax, ay = rot(ns[0], ns[1], fr)
    return fx + ax, fy + ay


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

edge_segs = []
for kind in ("gr_line", "gr_arc"):
    for g in children(root, kind):
        if layer_of(g) != "Edge.Cuts":
            continue
        if kind == "gr_line":
            s, e = xy(first(g, "start")), xy(first(g, "end"))
            if s and e:
                edge_segs.append((s[0], s[1], e[0], e[1]))
        else:
            s, e, m = xy(first(g, "start")), xy(first(g, "end")), xy(first(g, "mid"))
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


# pads / holes
holes = []  # (x, y, r, ref, net_or_None, is_npth)
copper_pads = []  # (x, y, r, net, ref, layer_set)

for ref, fp in refs.items():
    for pad in children(fp, "pad"):
        ptype = pad[2] if len(pad) > 2 else ""
        x, y = pad_abs(fp, pad)
        size = nums(first(pad, "size") or [0, 0.8, 0.8])
        rx = (size[0] / 2) if size else 0.4
        ry = (size[1] / 2) if len(size) > 1 else rx
        r = max(rx, ry)
        drill = first(pad, "drill")
        dr = nums(drill)[0] / 2 if drill and nums(drill) else 0.0
        layers_n = first(pad, "layers")
        layers = [a for a in (layers_n[1:] if layers_n else []) if isinstance(a, str)]
        net = net_of(pad)
        if ptype == "np_thru_hole" or (not net and dr):
            holes.append((x, y, max(dr, r), ref, None, True))
        else:
            if dr:
                holes.append((x, y, dr, ref, net, False))
            copper_pads.append((x, y, r, net or "", ref, tuple(layers)))


def seg_key(st, en):
    a = (round(st[0], 4), round(st[1], 4))
    b = (round(en[0], 4), round(en[1], 4))
    return tuple(sorted((a, b)))


# ---------------------------------------------------------------------------
# traces to delete (coordinate match, either direction)
# ---------------------------------------------------------------------------

DELETE = {
    # ROW_4 through K14 / D9 / K9 / K3
    seg_key((54.85, 90.0), (148.0, 90.0)),
    seg_key((148.0, 90.0), (148.0, 111.0)),
    seg_key((54.85, 111.0), (54.85, 90.0)),
    # old ROW_4 vertical that clips switch NPTH; replaced by channel route
    seg_key((54.85, 118.49), (54.85, 80.49)),
    seg_key((54.85, 80.49), (54.85, 111.0)),
    # COL_1 through K9 / K14
    seg_key((55.7, 108.0), (55.7, 92.0)),
    seg_key((55.7, 92.0), (119.7, 92.0)),
    seg_key((119.7, 92.0), (119.7, 108.0)),
    # COL_2 through K14 / K20 holes
    seg_key((46.2, 95.8), (84.2, 95.8)),
    seg_key((46.2, 91.87), (46.2, 95.8)),
    seg_key((84.2, 105.0), (84.2, 95.8)),
    # COL_1 traces that actually sit on K19 pad-2 / D22 copper
    seg_key((52.55, 75.41), (47.05, 75.41)),
    seg_key((47.05, 75.41), (47.05, 80.49)),
    seg_key((57.57, 72.87), (52.55, 75.41)),
    # 3mm-short diode stubs (replaced)
    seg_key((47.05, 94.41), (47.05, 99.49)),
    seg_key((47.05, 116.41), (47.05, 118.49)),
    # COL_2 dangling vertical into the bottom corner
    seg_key((41.6, 87.25), (41.6, 122.0)),
}

# also delete dangling via at (41.6, 122) and unused (54.85, 111) ROW_4 via
DELETE_VIAS = {
    (round(41.6, 3), round(122.0, 3)),
    (round(54.85, 3), round(111.0, 3)),
    (round(148.0, 3), round(111.0, 3)),
}


def fmt(n: float) -> str:
    v = round(n, 4)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def seg_sexpr(x1, y1, x2, y2, layer, net, width=0.25) -> str:
    return (
        f'\t(segment\n'
        f'\t\t(start {fmt(x1)} {fmt(y1)})\n'
        f'\t\t(end {fmt(x2)} {fmt(y2)})\n'
        f'\t\t(width {fmt(width)})\n'
        f'\t\t(layer "{layer}")\n'
        f'\t\t(net "{net}")\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t)\n'
    )


def via_sexpr(x, y, net, size=0.6, drill=0.3) -> str:
    return (
        f'\t(via\n'
        f'\t\t(at {fmt(x)} {fmt(y)})\n'
        f'\t\t(size {fmt(size)})\n'
        f'\t\t(drill {fmt(drill)})\n'
        f'\t\t(layers "F.Cu" "B.Cu")\n'
        f'\t\t(net "{net}")\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t)\n'
    )


new_parts: list[str] = []


def add_seg(x1, y1, x2, y2, layer, net, width=0.25):
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return
    new_parts.append(seg_sexpr(x1, y1, x2, y2, layer, net, width))


def add_via(x, y, net):
    new_parts.append(via_sexpr(x, y, net))


def manhattan(x1, y1, x2, y2, layer, net):
    """Two-segment Manhattan: horizontal then vertical."""
    if abs(x1 - x2) > 1e-6:
        add_seg(x1, y1, x2, y1, layer, net)
    if abs(y1 - y2) > 1e-6:
        add_seg(x2, y1, x2, y2, layer, net)


# ---------------------------------------------------------------------------
# local new-column connections (exact pad coordinates)
# ---------------------------------------------------------------------------

# K19/K20/K21 pad geometry (absolute)
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
    cx, cy, _ = fp_at(fp)  # rot 180 already baked into pad_abs; use pad_abs
    # pad 1 TH local (3.9,0) @ 180 → (cx-3.9, cy); pad 2 TH (-3.9,0)@180 → (cx+3.9, cy)
    return {
        "c": (cx, cy),
        "p1_th": (cx - 3.9, cy),
        "p2_th": (cx + 3.9, cy),
    }


def stitch_switch(ref, col_net, diode_net):
    p = k_pads(ref)
    # pad 1 (column): F SMD → top TH, B SMD → bottom TH, THs together
    ax, ay = p["p1_fsmd"]
    bx, by = p["p1_th_a"]
    add_seg(ax, ay, bx, ay, "F.Cu", col_net)
    add_seg(bx, ay, bx, by, "F.Cu", col_net)
    cx1, cy1 = p["p1_bsmd"]
    dx, dy = p["p1_th_b"]
    add_seg(cx1, cy1, dx, cy1, "B.Cu", col_net)
    add_seg(dx, cy1, dx, dy, "B.Cu", col_net)
    add_seg(bx, by, dx, dy, "B.Cu", col_net)
    # pad 2 (to diode)
    a2x, a2y = p["p2_fsmd"]
    b2x, b2y = p["p2_th_a"]
    add_seg(a2x, a2y, b2x, a2y, "F.Cu", diode_net)
    add_seg(b2x, a2y, b2x, b2y, "F.Cu", diode_net)
    c2x, c2y = p["p2_bsmd"]
    d2x, d2y = p["p2_th_b"]
    add_seg(c2x, c2y, d2x, c2y, "B.Cu", diode_net)
    add_seg(d2x, c2y, d2x, d2y, "B.Cu", diode_net)
    add_seg(b2x, b2y, d2x, d2y, "B.Cu", diode_net)


print("adding local switch/diode stitches…")
stitch_switch("K19", "COL_1", "Net-(D22-K)")
stitch_switch("K20", "COL_2", "Net-(D23-K)")
stitch_switch("K21", "COL_3", "Net-(D24-K)")

# diode pad1 ← switch pad2 (B.Cu, around the bottom TH)
for kref, dref, dnet in (
    ("K19", "D22", "Net-(D22-K)"),
    ("K20", "D23", "Net-(D23-K)"),
    ("K21", "D24", "Net-(D24-K)"),
):
    kp, dp = k_pads(kref), d_pads(dref)
    sx, sy = kp["p2_th_b"]
    ex, ey = dp["p1_th"]
    # left then down onto the diode TH
    add_seg(sx, sy, ex, sy, "B.Cu", dnet)
    add_seg(ex, sy, ex, ey, "B.Cu", dnet)

# ROW_4: tie D22/D23/D24 pad 2 together in the inter-column channel (x=58.4)
# Stay on the peninsula at the bottom (x<=58.8 near y=121), then step into the
# fused region at y=115 where x=60 is on copper.
print("adding ROW_4 diode backbone…")
d22, d23, d24 = d_pads("D22"), d_pads("D23"), d_pads("D24")
CH = 58.4  # between K19 pad2 SMD (57.57) and the slot / K13 (62.72)
# D22 stub
add_seg(d22["p2_th"][0], d22["p2_th"][1], CH, d22["p2_th"][1], "B.Cu", "ROW_4")
# D23 stub
add_seg(d23["p2_th"][0], d23["p2_th"][1], CH, d23["p2_th"][1], "B.Cu", "ROW_4")
# D24: stay inside peninsula, then join channel at y=115
add_seg(d24["p2_th"][0], d24["p2_th"][1], CH, d24["p2_th"][1], "B.Cu", "ROW_4")
add_seg(CH, d24["p2_th"][1], CH, 115.0, "B.Cu", "ROW_4")
# backbone
add_seg(CH, d22["p2_th"][1], CH, 115.0, "B.Cu", "ROW_4")

# ---------------------------------------------------------------------------
# A* for long joins on B.Cu
# ---------------------------------------------------------------------------

GRID = 0.5
CLEAR_CU = 0.45  # pad radius already included; extra to trace center
CLEAR_HOLE = 0.20
EDGE_INSET = 0.45

xs = [x for x1, y1, x2, y2 in edge_segs for x in (x1, x2)]
ys = [y for x1, y1, x2, y2 in edge_segs for y in (y1, y2)]
X0, Y0 = min(xs) - 1, min(ys) - 1
X1, Y1 = max(xs) + 1, max(ys) + 1


def gxy(x, y):
    return int(round((x - X0) / GRID)), int(round((y - Y0) / GRID))


def xy_of(i, j):
    return X0 + i * GRID, Y0 + j * GRID


W = int((X1 - X0) / GRID) + 1
H = int((Y1 - Y0) / GRID) + 1
print(f"grid {W}x{H}")

# precompute occupancy for B.Cu: blocked if outside, hole, or other-net copper
# We'll build per-net blocked sets lazily.


def blocked_for(net: str):
    """Return a set of (i,j) that this net may not occupy on B.Cu."""
    bad = set()
    # sample a coarse mask using circles
    for i in range(W):
        for j in range(H):
            x, y = xy_of(i, j)
            if not point_in_board(x, y):
                bad.add((i, j))
                continue
            # edge inset: also reject if a 0.45mm offset is outside
            if not point_in_board(x + EDGE_INSET, y) or not point_in_board(x - EDGE_INSET, y) \
                    or not point_in_board(x, y + EDGE_INSET) or not point_in_board(x, y - EDGE_INSET):
                bad.add((i, j))
    # holes
    for hx, hy, hr, ref, hnet, npth in holes:
        rr = hr + (CLEAR_HOLE if npth else CLEAR_CU)
        # skip holes of the same net (thru-hole pads we want to hit)
        if hnet == net:
            continue
        r2 = rr * rr
        i0, j0 = gxy(hx - rr, hy - rr)
        i1, j1 = gxy(hx + rr, hy + rr)
        for i in range(max(0, i0), min(W, i1 + 1)):
            for j in range(max(0, j0), min(H, j1 + 1)):
                x, y = xy_of(i, j)
                if (x - hx) ** 2 + (y - hy) ** 2 <= r2:
                    bad.add((i, j))
    # other-net copper pads (B.Cu or *.Cu)
    for px, py, pr, pnet, ref, layers in copper_pads:
        if pnet == net:
            continue
        if not any(l in ("B.Cu", "*.Cu") or l.startswith("*.") for l in layers) and "*.Cu" not in str(layers):
            # skip F.Cu-only SMD
            if layers and all("F." in l for l in layers):
                continue
        rr = pr + CLEAR_CU
        r2 = rr * rr
        i0, j0 = gxy(px - rr, py - rr)
        i1, j1 = gxy(px + rr, py + rr)
        for i in range(max(0, i0), min(W, i1 + 1)):
            for j in range(max(0, j0), min(H, j1 + 1)):
                x, y = xy_of(i, j)
                if (x - px) ** 2 + (y - py) ** 2 <= r2:
                    bad.add((i, j))
    return bad


def astar(start, goal, blocked, max_exp=250000):
    si, sj = gxy(*start)
    gi, gj = gxy(*goal)
    # snap start/goal out of blocked if needed
    def nearest_free(i, j):
        if (i, j) not in blocked:
            return i, j
        for r in range(1, 12):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < W and 0 <= nj < H and (ni, nj) not in blocked:
                        return ni, nj
        return i, j

    si, sj = nearest_free(si, sj)
    gi, gj = nearest_free(gi, gj)
    if (si, sj) in blocked or (gi, gj) in blocked:
        return None

    def h(i, j):
        return abs(i - gi) + abs(j - gj)

    openh = [(h(si, sj), 0, si, sj)]
    came = {}
    gscore = {(si, sj): 0}
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    exp = 0
    while openh and exp < max_exp:
        _f, g, i, j = heapq.heappop(openh)
        exp += 1
        if (i, j) == (gi, gj):
            path = [(i, j)]
            while (i, j) in came:
                i, j = came[(i, j)]
                path.append((i, j))
            path.reverse()
            return [xy_of(a, b) for a, b in path]
        for di, dj in dirs:
            ni, nj = i + di, j + dj
            if not (0 <= ni < W and 0 <= nj < H):
                continue
            if (ni, nj) in blocked:
                continue
            # prefer straight: extra cost on turn is applied via parent dir later
            ng = g + 1
            if ng < gscore.get((ni, nj), 1e18):
                gscore[(ni, nj)] = ng
                came[(ni, nj)] = (i, j)
                heapq.heappush(openh, (ng + h(ni, nj), ng, ni, nj))
    print(f"  A* failed after {exp} expansions {start}->{goal}")
    return None


def compress(path):
    """Keep only corner points of an orthogonal path."""
    if not path:
        return path
    out = [path[0]]
    for p in path[1:]:
        if len(out) < 2:
            out.append(p)
            continue
        a, b = out[-2], out[-1]
        # colinear?
        if (abs(a[0] - b[0]) < 1e-9 and abs(b[0] - p[0]) < 1e-9) or (
            abs(a[1] - b[1]) < 1e-9 and abs(b[1] - p[1]) < 1e-9
        ):
            out[-1] = p
        else:
            out.append(p)
    return out


def route_net(net, start, goal, label):
    print(f"A* {label} {net} {start} -> {goal}")
    blocked = blocked_for(net)
    # allow the start/goal cells
    for pt in (start, goal):
        i, j = gxy(*pt)
        blocked.discard((i, j))
        for di in range(-1, 2):
            for dj in range(-1, 2):
                blocked.discard((i + di, j + dj))
    path = astar(start, goal, blocked)
    if not path:
        print(f"  FAILED {label}")
        return False
    pts = compress(path)
    print(f"  {len(path)} cells, {len(pts)} corners")
    for a, b in zip(pts, pts[1:]):
        add_seg(a[0], a[1], b[0], b[1], "B.Cu", net)
    return True


# Join ROW_4 backbone (CH, D22.y) to existing ROW_4 via at (167.2844, 74.2442)
print("building occupancy + long routes…")
route_net("ROW_4", (CH, d22["p2_th"][1]), (167.2844, 74.2442), "ROW_4 to MCU via")

# COL_1: K19 B SMD pad 1 -> K4 B SMD pad 1 (both COL_1)
k19, k4 = k_pads("K19"), k_pads("K4")
route_net("COL_1", k19["p1_bsmd"], k4["p1_bsmd"], "COL_1 K19 to K4")

# COL_2: K20 B SMD pad 1 -> K10 B SMD pad 1
k20, k10 = k_pads("K20"), k_pads("K10")
route_net("COL_2", k20["p1_bsmd"], k10["p1_bsmd"], "COL_2 K20 to K10")

# vias where F.Cu SMD must meet a B.Cu long run: already connected through TH
# (stitch_switch tied F SMD to TH which is *.Cu). No extra via required.

print(f"new copper items: {len(new_parts)}")

# ---------------------------------------------------------------------------
# rewrite file: drop deleted segments/vias, append new ones
# ---------------------------------------------------------------------------

# operate on raw text with a small state machine for top-level segment/via
# We already have the tree; serialize is hard. Edit text instead.

def extract_blocks(src: str, header: str):
    """Yield (start, end) of top-level (header ...) blocks."""
    out = []
    i = 0
    needle = "\n\t(" + header if False else "(" + header
    # find "(segment" or "(via" at beginning of a token
    pat = re.compile(r"\n[ \t]*\(" + re.escape(header) + r"\b")
    for m in pat.finditer(src):
        st = m.start() + 1  # keep the newline out; start at whitespace/paren
        # actually start at '('
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
    """Parse start/end or at from a segment/via block."""
    chunk = src[st:en]
    sm = re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    em = re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    am = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    if sm and em:
        return "seg", (float(sm.group(1)), float(sm.group(2))), (float(em.group(1)), float(em.group(2)))
    if am:
        return "via", (float(am.group(1)), float(am.group(2))), None
    return None, None, None


remove_ranges = []
for st, en in extract_blocks(text, "segment"):
    kind, a, b = block_start_end(text, st, en)
    if kind == "seg" and seg_key(a, b) in DELETE:
        remove_ranges.append((st, en))

for st, en in extract_blocks(text, "via"):
    kind, a, b = block_start_end(text, st, en)
    if kind == "via":
        k = (round(a[0], 3), round(a[1], 3))
        if k in DELETE_VIAS:
            remove_ranges.append((st, en))

print(f"removing {len(remove_ranges)} blocks")
remove_ranges.sort(reverse=True)
new_text = text
for st, en in remove_ranges:
    # also drop surrounding extra blank lines
    while st > 0 and new_text[st - 1] in " \t":
        st -= 1
    if st > 0 and new_text[st - 1] == "\n":
        st -= 1
    new_text = new_text[:st] + new_text[en:]

insert = "\n" + "".join(new_parts)
# insert before final (embedded_fonts no)
idx = new_text.rfind("(embedded_fonts no)")
if idx < 0:
    raise SystemExit("could not find insertion point")
new_text = new_text[:idx] + insert + "\n\t" + new_text[idx:]

# paren check
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
print("wrote", PCB, "bytes", len(new_text))
