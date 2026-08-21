#!/usr/bin/env python3
"""stage3 = EXACT verified 0-short config (drc_s):
 COL_1: F.Cu y=98 out, B.Cu 42.2->83 @98, F.Cu 83->120 @98, up spine
 COL_2: B.Cu y=104
 COL_3: B.Cu y=115.5
 ROW_4: B.Cu up, F.Cu y=110, B.Cu y=112, F descent
"""
import re, uuid as _uuid
PATH='/opt/data/cheapino-6x3/pcb/cheapino.kicad_pcb'
data=open(PATH).read()
netdef={int(m.group(1)):m.group(2) for m in re.finditer(r'\(net (\d+) "([^"]+)"\)',data)}
by_name={v:k for k,v in netdef.items()}
COL_1,COL_2,COL_3,ROW_4=by_name['COL_1'],by_name['COL_2'],by_name['COL_3'],by_name['ROW_4']
def seg(x1,y1,x2,y2,layer,nid):
    return ('\t(segment\n'
            f'\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n'
            '\t\t(width 0.25)\n'
            f'\t\t(layer "{layer}")\n\t\t(net {nid})\n'
            f'\t\t(uuid "{_uuid.uuid4()}")\n\t)\n')
def via(x,y,nid):
    return ('\t(via\n'
            f'\t\t(at {x} {y})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n'
            '\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net {nid})\n'
            f'\t\t(uuid "{_uuid.uuid4()}")\n\t)\n')
S=[];V=[]
S += [
 (43.72,113.41,43.72,115.5,'B.Cu',COL_3),
 (43.72,115.5,54.0,115.5,'F.Cu',COL_3),   # hop to F.Cu to clear
 (54.0,115.5,55.7,115.5,'F.Cu',COL_3),
 (55.7,115.5,62.72,115.5,'B.Cu',COL_3),
 (62.72,115.5,62.72,113.35,'B.Cu',COL_3),
]
V += [(43.72,115.5,COL_3),(54.0,115.5,COL_3),(55.7,115.5,COL_3)]
S += [
 (43.72,84.25,41.6,84.25,'F.Cu',COL_2),
 (41.6,84.25,41.6,119.0,'F.Cu',COL_2),
 (41.6,119.0,84.2,119.0,'B.Cu',COL_2),
 (84.2,119.0,84.2,95.8,'B.Cu',COL_2),
]
V += [(41.6,119.0,COL_2)]
S += [
 (43.72,65.25,42.2,65.25,'F.Cu',COL_1),
 (42.2,65.25,42.2,108.0,'F.Cu',COL_1),
 (42.2,108.0,54.0,108.0,'B.Cu',COL_1),
 (54.0,108.0,55.7,108.0,'F.Cu',COL_1),   # hop to F.Cu over ROW_4 chain
 (55.7,108.0,119.72,108.0,'B.Cu',COL_1),
 (119.72,108.0,119.72,103.40,'B.Cu',COL_1),
]
V += [(42.2,108.0,COL_1),(54.0,108.0,COL_1),(55.7,108.0,COL_1)]
S += [
 (54.85,118.49,54.85,80.49,'B.Cu',ROW_4),
 (54.85,80.49,54.85,110.0,'B.Cu',ROW_4),
 (54.85,110.0,148.0,110.0,'F.Cu',ROW_4),
 (148.0,110.0,148.0,112.0,'F.Cu',ROW_4),
 (148.0,112.0,174.9,112.0,'F.Cu',ROW_4),
 (174.9,112.0,174.9,107.0,'F.Cu',ROW_4),
]
V += [(54.85,110.0,ROW_4),(174.9,107.0,ROW_4)]
first=data.find('\t(segment\n')
data=data[:first]+''.join(seg(*s) for s in S)+''.join(via(*v) for v in V)+data[first:]
open(PATH,'w').write(data)
print("stage3 = exact drc_s (0-short) config")
