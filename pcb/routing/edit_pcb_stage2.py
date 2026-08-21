#!/usr/bin/env python3
"""Route key-pad2 -> diode-pad1 nets (Net-(D22/23/24-K)) and verify positions first."""
import re, uuid as _uuid
PATH='/opt/data/cheapino-6x3/pcb/cheapino.kicad_pcb'
data=open(PATH).read()
netdef={int(m.group(1)):m.group(2) for m in re.finditer(r'\(net (\d+) "([^"]+)"\)',data)}
by_name={v:k for k,v in netdef.items()}
print("nets present:", {n: netdef.get(by_name.get(n)) for n in ('Net-(D22-K)','Net-(D23-K)','Net-(D24-K)','COL_1','COL_2','COL_3','ROW_4')})
N22,N23,N24=by_name['Net-(D22-K)'],by_name['Net-(D23-K)'],by_name['Net-(D24-K)']
print("ids",N22,N23,N24)

# Geometry: each key's pad2 (net Net-(Dxx-K)) is a thru-hole at (52.55, yk+5.08) [pad "2" at 2.54,5.08]
# and B.Cu smd at (57.57, yk+2.54). Diode pin1 (same net) pads at (49.55, yd),(48.45,yd),(47.05,yd)
# where yd = diode center y (= key y + 10.16).
# Simplest reliable route on B.Cu: from key pad2 B.Cu (57.57, yk+2.54) go DOWN to (57.57, yd)
# but that would hit diode pin2 (ROW_4) at (54.85,yd).. no, 57.57 is fine (pin2 at 52.35-54.85).
# Actually connect key pad2 (52.55, yk+5.08) down the left? no.
# Route: key pad2 (57.57, yk+2.54) -> (54.85, yd) won't hit pin2 if x differs.
# Keep it simple and verified: 3 two-segment routes on B.Cu.
routes=[
 (57.57, 72.87, 54.85, 80.49, N22),  # K19 pad2 smd -> D22 pin2-side then need bridge to pin1
 (57.57, 91.87, 54.85, 99.49, N23),
 (57.57, 110.87, 54.85, 118.49, N24),
]
# Wait: D22 pin1 (Net-(D22-K)) pads are at x=49.55/48.45/47.05, y=80.49.
# D22 pin2 (ROW_4) pads are at x=54.85/53.45/52.35, y=80.49.
# So we want key-pad2 (Net) to reach diode PIN1 = x 47.05..49.55.
# The (57.57,yd)->(54.85,yd) would touch diode PIN2 (ROW_4)=WRONG net! Avoid.
# Instead route key pad2 (52.55, yk+5.08) WEST to (47.05, yk+5.08) then DOWN to (47.05, yd).
routes=[
 (52.55, 75.41, 47.05, 75.41, N22, 47.05, 80.49),
 (52.55, 94.41, 47.05, 94.41, N23, 47.05, 99.49),
 (52.55, 113.41, 47.05, 113.41, N24, 47.05, 118.49),
]
segs=[]
for fx,fy,tx1,ty1,nid,tx2,ty2 in routes:
    segs += [(fx,fy,tx1,ty1,'B.Cu',nid),(tx1,ty1,tx2,ty2,'B.Cu',nid)]

def blk(x1,y1,x2,y2,layer,nid):
    return ('\t(segment\n'
            f'\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n'
            '\t\t(width 0.25)\n'
            f'\t\t(layer "{layer}")\n\t\t(net {nid})\n'
            f'\t\t(uuid "{_uuid.uuid4()}")\n\t)\n')
first=data.find('\t(segment\n')
data=data[:first]+''.join(blk(*s) for s in segs)+data[first:]
open(PATH,'w').write(data)
print("wrote",len(segs),"segments")
