#!/usr/bin/env python3
"""Patch NPTH-clipping stitches on the 6th column, verify, export board.json.

Pass --verify-only to skip copper edits and only re-check + export.
"""
from __future__ import annotations

import json
import math
import re
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

PCB = Path("/workspace/cheapino/pcb/cheapino.kicad_pcb")
PUBLIC_PCB = Path("/workspace/public/cheapino.kicad_pcb")
OUT_JSON = Path("/workspace/public/board.json")
TRACE_W = 0.25
NEW_NETS = {"COL_1", "COL_2", "COL_3", "ROW_4", "Net-(D22-K)", "Net-(D23-K)", "Net-(D24-K)"}
COL6_REFS = {"K19", "K20", "K21", "D22", "D23", "D24"}
VERIFY_ONLY = "--verify-only" in sys.argv


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
    for t, v, _ in tokens:
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
    return f"{v:.4f}".rstrip("0").rstrip(".")


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


def dist_point_seg(px, py, x1, y1, x2, y2):
    vx, vy = x2 - x1, y2 - y1
    l2 = vx * vx + vy * vy
    if l2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / l2))
    return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))


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


print("loading…")
text = PCB.read_text()
root = parse(tokenize(text))[0]
fps = children(root, "footprint")
refs = {}
for fp in fps:
    for p in children(fp, "property"):
        if len(p) >= 3 and p[1] == "Reference":
            refs[p[2]] = fp

npths = []
pads = []
for ref, fp in refs.items():
    for pad in children(fp, "pad"):
        ptype = pad[2] if len(pad) > 2 else ""
        padnum = str(pad[1]) if len(pad) > 1 else "?"
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
            npths.append((x, y, max(dr, r), ref))
        else:
            pads.append((x, y, r, net, ref, padnum, tuple(layers), bool(dr)))

edge_raw = []
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
    return {"c": (cx, cy), "p1_th": (cx - 3.9, cy), "p2_th": (cx + 3.9, cy)}


def parse_seg_block(chunk: str):
    sm = re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    em = re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    nm = re.search(r'\(net\s+"([^"]+)"\)', chunk)
    lm = re.search(r'\(layer\s+"([^"]+)"\)', chunk)
    wm = re.search(r"\(width\s+([-\d.]+)\)", chunk)
    if not (sm and em):
        return None
    return {
        "x1": float(sm.group(1)),
        "y1": float(sm.group(2)),
        "x2": float(em.group(1)),
        "y2": float(em.group(2)),
        "net": nm.group(1) if nm else "",
        "layer": lm.group(1) if lm else "",
        "w": float(wm.group(1)) if wm else TRACE_W,
    }


def npth_hits_for(x1, y1, x2, y2, w=TRACE_W, only_refs=None):
    hits = []
    hw = w / 2
    for hx, hy, hr, ref in npths:
        if only_refs and ref not in only_refs:
            continue
        d = dist_point_seg(hx, hy, x1, y1, x2, y2)
        if d < hr + hw - 0.02:
            hits.append((ref, d, hr, (hx, hy)))
    return hits


if not VERIFY_ONLY:
    seg_blocks = extract_blocks(text, "segment")
    segs = []
    for st, en in seg_blocks:
        info = parse_seg_block(text[st:en])
        if info:
            info["st"] = st
            info["en"] = en
            segs.append(info)

    print(f"segments {len(segs)} npths {len(npths)}")
    remove = []
    print("\nNPTH clips on new-column nets:")
    for s in segs:
        if s["net"] not in NEW_NETS:
            continue
        hits = npth_hits_for(s["x1"], s["y1"], s["x2"], s["y2"], s["w"], COL6_REFS)
        if hits:
            print(
                f"  {s['net']:14} {s['layer']:5} "
                f"({s['x1']:.3f},{s['y1']:.3f})-({s['x2']:.3f},{s['y2']:.3f}) "
                f"-> {[(h[0], round(h[1], 3), round(h[2], 3)) for h in hits]}"
            )
            remove.append((s["st"], s["en"]))
    print(f"delete {len(remove)} segments")

    new_parts: list[str] = []

    def add_seg(x1, y1, x2, y2, layer, net):
        if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
            return
        hits = npth_hits_for(x1, y1, x2, y2)
        if hits:
            print(f"  REFUSING clip {net} ({x1:.3f},{y1:.3f})-({x2:.3f},{y2:.3f}) {hits[:2]}")
            return
        new_parts.append(seg_sexpr(x1, y1, x2, y2, layer, net))

    def stitch_safe(smd, th, layer, net):
        add_seg(smd[0], smd[1], smd[0], th[1], layer, net)
        add_seg(smd[0], th[1], th[0], th[1], layer, net)

    print("adding NPTH-safe stitches…")
    for kref, dnet, cnet in (
        ("K19", "Net-(D22-K)", "COL_1"),
        ("K20", "Net-(D23-K)", "COL_2"),
        ("K21", "Net-(D24-K)", "COL_3"),
    ):
        p = k_pads(kref)
        stitch_safe(p["p1_fsmd"], p["p1_th_a"], "F.Cu", cnet)
        stitch_safe(p["p1_bsmd"], p["p1_th_b"], "B.Cu", cnet)
        stitch_safe(p["p2_fsmd"], p["p2_th_a"], "F.Cu", dnet)
        stitch_safe(p["p2_bsmd"], p["p2_th_b"], "B.Cu", dnet)
        dp = d_pads({"K19": "D22", "K20": "D23", "K21": "D24"}[kref])
        sx, sy = p["p2_th_b"]
        ex, ey = dp["p1_th"]
        mid_y = (sy + ey) / 2.0
        add_seg(sx, sy, sx, mid_y, "B.Cu", dnet)
        add_seg(sx, mid_y, ex, mid_y, "B.Cu", dnet)
        add_seg(ex, mid_y, ex, ey, "B.Cu", dnet)

    CH = 58.4
    for dref in ("D22", "D23", "D24"):
        dp = d_pads(dref)
        add_seg(dp["p2_th"][0], dp["p2_th"][1], CH, dp["p2_th"][1], "B.Cu", "ROW_4")
    d22y, d24y = d_pads("D22")["p2_th"][1], d_pads("D24")["p2_th"][1]
    add_seg(CH, d24y, CH, 115.0, "B.Cu", "ROW_4")
    add_seg(CH, d22y, CH, 115.0, "B.Cu", "ROW_4")
    add_seg(CH, d22y, 58.457, 83.266, "B.Cu", "ROW_4")
    add_seg(167.457, 74.266, 167.2844, 74.2442, "F.Cu", "ROW_4")
    add_seg(167.457, 74.266, 167.2844, 74.2442, "B.Cu", "ROW_4")
    k19, k20 = k_pads("K19"), k_pads("K20")
    add_seg(k19["p1_bsmd"][0], k19["p1_bsmd"][1], 43.957, 78.266, "B.Cu", "COL_1")
    add_seg(k20["p1_bsmd"][0], k20["p1_bsmd"][1], 43.957, 97.266, "B.Cu", "COL_2")
    # COL_3 bypass under K21
    add_seg(43.722, 116.411, 43.722, 118.9, "B.Cu", "COL_3")
    add_seg(43.722, 118.9, 55.7, 118.9, "B.Cu", "COL_3")
    add_seg(55.7, 118.9, 55.7, 115.5, "B.Cu", "COL_3")

    print(f"new segments: {len(new_parts)}")
    remove = sorted(set(remove), reverse=True)
    new_text = text
    for st, en in remove:
        while st > 0 and new_text[st - 1] in " \t":
            st -= 1
        if st > 0 and new_text[st - 1] == "\n":
            st -= 1
        new_text = new_text[:st] + new_text[en:]
    insert = "\n" + "".join(new_parts)
    idx = new_text.rfind("(embedded_fonts no)")
    if idx < 0:
        raise SystemExit("no insertion point")
    new_text = new_text[:idx] + insert + "\n\t" + new_text[idx:]
    bal = new_text.count("(") - new_text.count(")")
    print("paren balance", bal)
    if bal != 0:
        raise SystemExit("paren imbalance, abort")
    PCB.write_text(new_text)
    PUBLIC_PCB.write_text(new_text)
    print("wrote PCB", len(new_text))
    text = new_text
    root = parse(tokenize(text))[0]
    fps = children(root, "footprint")
    refs = {}
    for fp in fps:
        for p in children(fp, "property"):
            if len(p) >= 3 and p[1] == "Reference":
                refs[p[2]] = fp
    npths = []
    pads = []
    for ref, fp in refs.items():
        for pad in children(fp, "pad"):
            ptype = pad[2] if len(pad) > 2 else ""
            padnum = str(pad[1]) if len(pad) > 1 else "?"
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
                npths.append((x, y, max(dr, r), ref))
            else:
                pads.append((x, y, r, net, ref, padnum, tuple(layers), bool(dr)))

# ---------------------------------------------------------------------------
# verify + export
# ---------------------------------------------------------------------------
seg_blocks = extract_blocks(text, "segment")
segs = []
for st, en in seg_blocks:
    info = parse_seg_block(text[st:en])
    if info:
        segs.append(info)

vias = []
for st, en in extract_blocks(text, "via"):
    chunk = text[st:en]
    am = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
    nm = re.search(r'\(net\s+"([^"]+)"\)', chunk)
    if am:
        vias.append({"x": float(am.group(1)), "y": float(am.group(2)), "net": nm.group(1) if nm else ""})

print("\n=== VERIFY ===")
print("parens", text.count("(") - text.count(")"))

endpts = Counter()
for kind, s, e, m in edge_raw:
    a = (round(s[0], 4), round(s[1], 4))
    b = (round(e[0], 4), round(e[1], 4))
    endpts[a] += 1
    endpts[b] += 1
odd = [p for p, c in endpts.items() if c % 2]
print("Edge.Cuts odd endpoints", odd)
outline_ok = len(odd) == 0

off = 0
for s in segs:
    for t in (0.0, 0.5, 1.0):
        px = s["x1"] + t * (s["x2"] - s["x1"])
        py = s["y1"] + t * (s["y2"] - s["y1"])
        if not point_in_board(px, py):
            off += 1
            if off <= 8:
                print(f"  off-board {s['net']} ({px:.2f},{py:.2f})")
            break
print("off-board traces", off)

npth_new = 0
for s in segs:
    hits6 = npth_hits_for(s["x1"], s["y1"], s["x2"], s["y2"], s["w"], COL6_REFS)
    if hits6:
        npth_new += 1
        if npth_new <= 12:
            print(
                f"  NPTH col6 {s['net']} ({s['x1']:.3f},{s['y1']:.3f})-"
                f"({s['x2']:.3f},{s['y2']:.3f}) {hits6[0]}"
            )
print("NPTH clips on col6 footprints", npth_new)

WATCH = ["ROW_4", "COL_1", "COL_2", "COL_3"]
short_n = 0
by_layer = defaultdict(list)
for s in segs:
    if s["net"] in WATCH:
        by_layer[s["layer"]].append(s)
for layer, ls in by_layer.items():
    for i, a in enumerate(ls):
        for b in ls[i + 1 :]:
            if a["net"] == b["net"]:
                continue
            hit = False
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                px = a["x1"] + t * (a["x2"] - a["x1"])
                py = a["y1"] + t * (a["y2"] - a["y1"])
                d = dist_point_seg(px, py, b["x1"], b["y1"], b["x2"], b["y2"])
                if d < (a["w"] + b["w"]) / 2 + 0.13:
                    hit = True
                    break
            if hit:
                short_n += 1
                if short_n <= 8:
                    print(f"  SHORT {a['net']}/{b['net']} {layer}")
print("shorts among ROW/COL", short_n)

SNAP = 0.55
TJ = 0.15


class UF:
    def __init__(self):
        self.p = {}

    def add(self, x):
        self.p.setdefault(x, x)

    def find(self, x):
        self.add(x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


uf = UF()
for x, y, r, net, ref, padnum, layers, pth in pads:
    node = ("P", ref, padnum, net)
    uf.add(node)
    lys = ["F.Cu", "B.Cu"] if pth or any(str(l).startswith("*.") for l in layers) else [l for l in layers if l in ("F.Cu", "B.Cu")]
    for ly in lys:
        pt = (round(x, 2), round(y, 2), ly, net)
        uf.union(node, pt)

for s in segs:
    a = (round(s["x1"], 2), round(s["y1"], 2), s["layer"], s["net"])
    b = (round(s["x2"], 2), round(s["y2"], 2), s["layer"], s["net"])
    uf.union(a, b)

for s in segs:
    a = (round(s["x1"], 2), round(s["y1"], 2), s["layer"], s["net"])
    b = (round(s["x2"], 2), round(s["y2"], 2), s["layer"], s["net"])
    for o in segs:
        if o is s or o["net"] != s["net"] or o["layer"] != s["layer"]:
            continue
        if dist_point_seg(s["x1"], s["y1"], o["x1"], o["y1"], o["x2"], o["y2"]) < TJ:
            oa = (round(o["x1"], 2), round(o["y1"], 2), o["layer"], o["net"])
            uf.union(a, oa)
        if dist_point_seg(s["x2"], s["y2"], o["x1"], o["y1"], o["x2"], o["y2"]) < TJ:
            oa = (round(o["x1"], 2), round(o["y1"], 2), o["layer"], o["net"])
            uf.union(b, oa)

for v in vias:
    a = (round(v["x"], 2), round(v["y"], 2), "F.Cu", v["net"])
    b = (round(v["x"], 2), round(v["y"], 2), "B.Cu", v["net"])
    uf.union(a, b)

for x, y, r, net, ref, padnum, layers, pth in pads:
    node = ("P", ref, padnum, net)
    lys = ["F.Cu", "B.Cu"] if pth or any(str(l).startswith("*.") for l in layers) else [l for l in layers if l in ("F.Cu", "B.Cu")]
    for ly in lys:
        for s in segs:
            if s["net"] != net or s["layer"] != ly:
                continue
            if math.hypot(s["x1"] - x, s["y1"] - y) < SNAP or math.hypot(s["x2"] - x, s["y2"] - y) < SNAP:
                uf.union(node, (round(s["x1"], 2), round(s["y1"], 2), ly, net))
            elif dist_point_seg(x, y, s["x1"], s["y1"], s["x2"], s["y2"]) < SNAP:
                uf.union(node, (round(s["x1"], 2), round(s["y1"], 2), ly, net))
        for v in vias:
            if v["net"] == net and math.hypot(v["x"] - x, v["y"] - y) < SNAP:
                uf.union(node, (round(v["x"], 2), round(v["y"], 2), ly, net))


def connected(ref_a, pad_a, net, ref_b, pad_b):
    na = ("P", ref_a, pad_a, net)
    nb = ("P", ref_b, pad_b, net)
    return uf.find(na) == uf.find(nb)


matrix = [
    ("K19", "1", "COL_1", "K4", "1"),
    ("K20", "1", "COL_2", "K10", "1"),
    ("K21", "1", "COL_3", "K15", "1"),
    ("K21", "1", "COL_3", "K13", "1"),
    ("K19", "2", "Net-(D22-K)", "D22", "1"),
    ("K20", "2", "Net-(D23-K)", "D23", "1"),
    ("K21", "2", "Net-(D24-K)", "D24", "1"),
    ("D22", "2", "ROW_4", "D23", "2"),
    ("D22", "2", "ROW_4", "D24", "2"),
    ("D22", "2", "ROW_4", "U1", "8"),
]
print("\nconnectivity:")
for a, pa, n, b, pb in matrix:
    ok = connected(a, pa, n, b, pb)
    print(f"  {a}.{pa} --{n}-- {b}.{pb}  {'OK' if ok else 'FAIL'}")

k19ok = connected("K19", "1", "COL_1", "K4", "1")
k20ok = connected("K20", "1", "COL_2", "K10", "1")
k21ok = connected("K21", "1", "COL_3", "K15", "1")
d22ok = connected("K19", "2", "Net-(D22-K)", "D22", "1")
d23ok = connected("K20", "2", "Net-(D23-K)", "D23", "1")
d24ok = connected("K21", "2", "Net-(D24-K)", "D24", "1")
row4ok = connected("D22", "2", "ROW_4", "U1", "8")

adj = defaultdict(list)
for i, (kind, s, e, m) in enumerate(edge_raw):
    a = (round(s[0], 4), round(s[1], 4))
    b = (round(e[0], 4), round(e[1], 4))
    adj[a].append((b, i))
    adj[b].append((a, i))
used = set()
start = min(adj.keys(), key=lambda p: (p[0], p[1]))
loop = [start]
cur = start
guard = 0
while guard < 500:
    guard += 1
    nxt = None
    for nb, i in adj[cur]:
        if i in used:
            continue
        used.add(i)
        nxt = nb
        break
    if nxt is None:
        break
    loop.append(nxt)
    cur = nxt
    if cur == start and len(loop) > 2:
        break

keys, diodes, other = [], [], []
for ref, fp in sorted(refs.items()):
    x, y, r = fp_at(fp)
    if re.fullmatch(r"K\d+", ref):
        keys.append({"id": ref, "x": round(x, 3), "y": round(y, 3), "r": round(r, 3), "col6": ref in COL6_REFS})
    elif re.fullmatch(r"D\d+", ref):
        diodes.append({"id": ref, "x": round(x, 3), "y": round(y, 3), "r": round(r, 3), "col6": ref in COL6_REFS})
    elif ref in ("U1", "ENC1") or ref.startswith("J"):
        kind = "mcu" if ref == "U1" else ("enc" if ref == "ENC1" else "jack")
        other.append({"id": ref, "x": round(x, 3), "y": round(y, 3), "r": round(r, 3), "kind": kind})

xs = [p[0] for p in loop] or [0]
ys = [p[1] for p in loop] or [0]
bbox = {"x": round(min(xs), 2), "y": round(min(ys), 2), "w": round(max(xs) - min(xs), 2), "h": round(max(ys) - min(ys), 2)}

traces_out = []
for s in segs:
    traces_out.append(
        {
            "n": s["net"] if s["net"] in NEW_NETS else "",
            "a": s["net"] in NEW_NETS,
            "x1": round(s["x1"], 3),
            "y1": round(s["y1"], 3),
            "x2": round(s["x2"], 3),
            "y2": round(s["y2"], 3),
            "l": 0 if s["layer"] == "F.Cu" else 1,
            "w": s["w"],
        }
    )
vias_out = [
    {"x": round(v["x"], 3), "y": round(v["y"], 3), "a": v["net"] in NEW_NETS, "n": v["net"] if v["net"] in NEW_NETS else ""}
    for v in vias
]

checks = [
    {"id": "load", "label": "Board file is valid KiCad S-expression", "ok": True},
    {"id": "outline", "label": "Edge.Cuts is a single closed outline", "ok": outline_ok},
    {"id": "cutout", "label": "No traces through the bottom cutout", "ok": off == 0},
    {"id": "shorts", "label": "No shorts between ROW_4 / COL_1 / COL_2 / COL_3", "ok": short_n == 0},
    {"id": "npth", "label": "New-column traces clear MX NPTH holes", "ok": npth_new == 0},
    {"id": "k19", "label": "K19 → D22 → COL_1 / ROW_4", "ok": bool(k19ok and d22ok)},
    {"id": "k20", "label": "K20 → D23 → COL_2 / ROW_4", "ok": bool(k20ok and d23ok)},
    {"id": "k21", "label": "K21 → D24 → COL_3 / ROW_4", "ok": bool(k21ok and d24ok)},
    {"id": "row4", "label": "ROW_4 reaches the RP2040 (U1 pad 8)", "ok": bool(row4ok)},
    {"id": "zones", "label": "GND pour needs Fill All Zones in KiCad before fab", "ok": False, "warn": True},
]

board = {
    "title": "Cheapino 6×3",
    "rev": "2-sixcol",
    "bbox": bbox,
    "outline": [
        {
            "x1": round(s[0], 4),
            "y1": round(s[1], 4),
            "x2": round(e[0], 4),
            "y2": round(e[1], 4),
            "mx": None if m is None else round(m[0], 4),
            "my": None if m is None else round(m[1], 4),
            "k": kind,
        }
        for kind, s, e, m in edge_raw
    ],
    "loop": [{"x": round(p[0], 4), "y": round(p[1], 4)} for p in loop],
    "keys": keys,
    "diodes": diodes,
    "other": other,
    "traces": traces_out,
    "vias": vias_out,
    "matrix": [
        {"key": "K19", "diode": "D22", "col": "COL_1", "row": "ROW_4", "ok": bool(k19ok and d22ok)},
        {"key": "K20", "diode": "D23", "col": "COL_2", "row": "ROW_4", "ok": bool(k20ok and d23ok)},
        {"key": "K21", "diode": "D24", "col": "COL_3", "row": "ROW_4", "ok": bool(k21ok and d24ok)},
    ],
    "checks": checks,
}
OUT_JSON.write_text(json.dumps(board, separators=(",", ":")))
PUBLIC_PCB.write_text(text)
print("wrote", OUT_JSON, "bytes", OUT_JSON.stat().st_size)
print("CHECKS", {c["id"]: c["ok"] for c in checks})
