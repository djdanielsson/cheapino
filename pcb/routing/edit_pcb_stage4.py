#!/usr/bin/env python3
"""Stage4 v2: join each new key's terminal pads (pin1 & pin2) the way the original does —
connect F pad -> PTH1 (F.Cu), PTH pads bridge layers, PTH2 -> B pad (B.Cu).
K19 pin1 (COL_1): F(43.72,65.25) PTH1(46.2,67.79) PTH2(46.2,72.87) B(43.72,75.41)
K20 pin1 (COL_2): F(43.72,84.25) PTH1(46.2,86.79) PTH2(46.2,91.87) B(43.72,94.41)
K21 pin1 (COL_3): F(43.72,103.25) PTH1(46.2,105.79) PTH2(46.2,110.87) B(43.72,113.41)
K19 pin2 (Net-D22-K): PTH1(52.55,65.25) F(57.57,67.79) B(57.57,72.87) PTH2(52.55,75.41)
K20 pin2 (Net-D23-K): PTH1(52.55,84.25) F(57.57,86.79) B(57.57,91.87) PTH2(52.55,94.41)
K21 pin2 (Net-D24-K): PTH1(52.55,103.25) F(57.57,105.79) B(57.57,110.87) PTH2(52.55,113.41)
Join taps COL spine pad1 (already connected) and bridges the rest.
"""
import re, uuid as _uuid
PATH='/opt/data/cheapino-6x3/pcb/cheapino.kicad_pcb'
data=open(PATH).read()
netdef={int(m.group(1)):m.group(2) for m in re.finditer(r'\(net (\d+) "([^"]+)"\)',data)}
by_name={v:k for k,v in netdef.items()}
def seg(x1,y1,x2,y2,layer,nid):
    return ('\t(segment\n'
            f'\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n'
            '\t\t(width 0.25)\n'
            f'\t\t(layer "{layer}")\n\t\t(net {nid})\n'
            f'\t\t(uuid "{_uuid.uuid4()}")\n\t)\n')
S=[]
# pin1: F pad -> PTH1 on F.Cu ; B pad -> PTH2 on B.Cu ; PTHs bridge layers (through holes)
pin1=[
 ('COL_1',43.72,65.25,43.72,75.41,46.2,67.79,46.2,72.87),
 ('COL_2',43.72,84.25,43.72,94.41,46.2,86.79,46.2,91.87),
 ('COL_3',43.72,103.25,43.72,113.41,46.2,105.79,46.2,110.87),
]
for netn, xf,yf, xb,yb, p1x,p1y, p2x,p2y in pin1:
    nid=by_name[netn]
    S.append((xf,yf,p1x,p1y,'F.Cu',nid))  # F pad -> PTH1
    S.append((p1x,p1y,p2x,p2y,'F.Cu',nid))# PTH1 -> PTH2 (F.Cu, via pads connect layers)
    S.append((p2x,p2y,xb,yb,'B.Cu',nid))  # PTH2 -> B pad
# pin2
pin2=[
 ('Net-(D22-K)',52.55,65.25,57.57,67.79,57.57,72.87,52.55,75.41),
 ('Net-(D23-K)',52.55,84.25,57.57,86.79,57.57,91.87,52.55,94.41),
 ('Net-(D24-K)',52.55,103.25,57.57,105.79,57.57,110.87,52.55,113.41),
]
for netn, p1x,p1y, fx,fy, bx,by, p2x,p2y in pin2:
    nid=by_name[netn]
    # PTH1 -> F smd on F.Cu ; vertical F.Cu tying PTH1-PTH2 (through holes bridge layers) ; B smd -> PTH2 on B.Cu
    S.append((p1x,p1y,fx,fy,'F.Cu',nid))
    S.append((p1x,p1y,p2x,p2y,'F.Cu',nid))
    S.append((bx,by,p2x,p2y,'B.Cu',nid))
first=data.find('\t(segment\n')
data=data[:first]+''.join(seg(*s) for s in S)+data[first:]
open(PATH,'w').write(data)
print("stage4 v2 added",len(S),"segs")
