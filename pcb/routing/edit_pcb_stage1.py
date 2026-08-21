#!/usr/bin/env python3
"""Cheapino 6-col PCB edit — stage 1 (fixed): nets + cloned footprints + outline."""
import re, uuid as _uuid

PATH = '/opt/data/cheapino-6x3/pcb/cheapino.kicad_pcb'
K13_TPL = open('/opt/data/template_K13.txt').read()
D13_TPL = open('/opt/data/template_D13.txt').read()

def indent(blk, n):
    # template first line lost its base tab; inner lines already correct.
    # add n tabs to the first line only.
    lines = blk.split('\n')
    lines[0] = '\t'*n + lines[0]
    return '\n'.join(lines)

# ---- balanced-paren scanning ----
def split_blocks(s, open_pat):
    """yield (m.start, content_start, content_end, m.end, matched_open_text) for top-level matches of open_pat.
    Balanced; not nesting-aware of same open_pat but tracks paren depth."""
    res = []
    for m in open_pat.finditer(s):
        i = m.end()
        depth = 1
        while i < len(s) and depth > 0:
            if s[i] == '(':
                depth += 1
            elif s[i] == ')':
                depth -= 1
            i += 1
        res.append((m.start(), m.end(), s[m.end():i-1], i, m.group(0)))
    return res

def rewrite_pads(blk, mapping):
    """mapping: padnumber -> (new_net_id, new_net_name).
    For each top-level (pad ...) block: read its net, if its padnum in mapping rewrite net."""
    padre = re.compile(r'\t*\(pad "([^"]+)"')
    out = []
    prev = 0
    for st, cont_start, cont, end, _ in split_blocks(blk, padre):
        out.append(blk[prev:st])
        padnum = re.match(r'\t*\(pad "([^"]+)"', blk[st:]).group(1)
        netm = re.search(r'\(net (\d+) "([^"]*)"\)', cont)
        seg = blk[st:end]
        if padnum in mapping:
            newid, newname = mapping[padnum]
            seg = re.sub(r'\(net \d+ "[^"]*"\)', f'(net {newid} "{newname}")', seg, count=1)
        out.append(seg)
        prev = end
    out.append(blk[prev:])
    return ''.join(out)

def clone_fp(tpl, ref, x, y, mapping):
    blk = indent(tpl, 1)
    # fresh uuids + path
    seen = {}
    def nu(mm):
        k = mm.group(1)
        if k not in seen:
            seen[k] = str(_uuid.uuid4())
        return f'(uuid "{seen[k]}")'
    blk = re.sub(r'\(uuid "([^"]+)"\)', nu, blk)
    blk = re.sub(r'\(path "/[^"]*"\)', f'(path "/{_uuid.uuid4()}")', blk, count=1)
    # reference/value
    blk = re.sub(r'\(property "Reference" "[^"]*"', f'(property "Reference" "{ref}"', blk, count=1)
    blk = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{ref}"', blk, count=1)
    # position: first (at X Y[ rot]) anywhere (footprint position comes before descr)
    blk, n = re.subn(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([.\-0-9]+))?\)',
                     lambda m: f'(at {x:.4f} {y:.4f}' + (f' {m.group(3)}' if m.group(3) else '') + ')',
                     blk, count=1)
    if n == 0:
        raise SystemExit(f"could not set position {ref}")
    blk = rewrite_pads(blk, mapping)
    return blk

if __name__ == '__main__':
    # ---- nets ----
    data = open(PATH).read()
    netdef = {int(m.group(1)): m.group(2) for m in re.finditer(r'\(net (\d+) "([^"]+)"\)', data)}
    by_name = {v: k for k, v in netdef.items()}
    COL_1, COL_2, COL_3 = by_name['COL_1'], by_name['COL_2'], by_name['COL_3']
    ROW_4 = by_name['ROW_4']
    maxnet = max(netdef)
    NEW = {f'Net-(D22-K)': maxnet+1, f'Net-(D23-K)': maxnet+2, f'Net-(D24-K)': maxnet+3}
    print("COL_1/2/3=%d/%d/%d ROW_4=%d new=%s" % (COL_1, COL_2, COL_3, ROW_4, NEW))

    # Insert new nets after the last top-level (1-tab) (net ...) declaration.
    last_net = max(m.end() for m in re.finditer(r'\n\t\(net \d+ "[^"]+"\)\n', data))
    add_nets = ''.join(f'\t(net {v} "{k}")\n' for k, v in NEW.items())
    data = data[:last_net] + add_nets + data[last_net:]

    keys = [
        ('K19', 50.0118, 70.3326, {'1': (COL_1, 'COL_1'), '2': (NEW['Net-(D22-K)'], 'Net-(D22-K)')}),
        ('K20', 50.0118, 89.3318, {'1': (COL_2, 'COL_2'), '2': (NEW['Net-(D23-K)'], 'Net-(D23-K)')}),
        ('K21', 50.0118, 108.331, {'1': (COL_3, 'COL_3'), '2': (NEW['Net-(D24-K)'], 'Net-(D24-K)')}),
    ]
    diodes = [
        ('D22', 50.9486, 80.4926, {'1': (NEW['Net-(D22-K)'], 'Net-(D22-K)'), '2': (ROW_4, 'ROW_4')}),
        ('D23', 50.9486, 99.4918, {'1': (NEW['Net-(D23-K)'], 'Net-(D23-K)'), '2': (ROW_4, 'ROW_4')}),
        ('D24', 50.9486, 118.491, {'1': (NEW['Net-(D24-K)'], 'Net-(D24-K)'), '2': (ROW_4, 'ROW_4')}),
    ]
    new_fps = []
    for ref, x, y, nm in keys:
        new_fps.append(clone_fp(K13_TPL, ref, x, y, nm))
    for ref, x, y, nm in diodes:
        new_fps.append(clone_fp(D13_TPL, ref, x, y, nm))

    # sanity checks
    fp0 = new_fps[0]
    print("K19 pos:", re.search(r'\(at ([^)]+)\)', fp0).group(1))
    print("K19 nets present:", 'COL_1' in fp0, 'Net-(D22-K)' in fp0, 'Net-(D13-K)' in fp0, 'COL_3' in fp0)
    print("D22 nets present:", 'ROW_4' in new_fps[3], 'Net-(D22-K)' in new_fps[3], 'ROW_1' in new_fps[3])

    anchor = data.find('(footprint "project_footprints:Kailh_socket')
    assert anchor != -1
    data = data[:anchor] + '\n'.join(new_fps) + '\n' + data[anchor:]
    open(PATH, 'w').write(data)
    print("Stage1 done, bytes=", len(data))