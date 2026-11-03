"""Read build/HX_Effects_v3.80.0_Click.hxf back and check it: the kernel in Entry 2 is the
assembled (simulator-checked) one, primitive 0x9c75 points at it, Entry 3 has the six knobs,
Entry 4 maps each knob to its instance word, and every entry but 0/2/3/4 is stock.
usage: python3 tools/verify/verify_click.py [--probe] (after build_click.py [--probe])"""
import sys, os, struct
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
for p in ('tools', 'tools/sharc', 'effects/metronome/sharc', '.'): sys.path.insert(0, os.path.join(ROOT, p))
os.environ['NAM_DEVICE'] = 'effects'
import patch_amp as pa, l6ia, click_kernel, build_click
PROBE = '--probe' in sys.argv
img, _ = pa.load_l6ia_from_any(os.path.join(ROOT, 'build/HX_Effects_v3.80.0_Click_probe.hxf' if PROBE else 'build/HX_Effects_v3.80.0_Click.hxf'))
stock, _ = pa.load_l6ia_from_any(os.path.join(ROOT, 'firmware/HX_Effects_v3.80.0_0xd97239907.hxf'))
pa.select_device(img)
ok = True
def check(c, msg):
    global ok
    print(('  ok  ' if c else '  FAIL ') + msg); ok &= bool(c)

# Entry 2: the injected blocks decode back to the assembled kernel
es = l6ia.parse(img)
e2 = img[es[2]['payload_off']: es[2]['payload_off'] + es[2]['payload_len']]
w = struct.unpack('<%dI' % (len(e2) // 4), e2)
NW = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2, 6: lambda c: c * 2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
pm, dm, prim = {}, {}, None
i = 384
while i + 3 <= len(w):
    tag, cnt, addr = w[i:i + 3]
    if tag == 0: break
    body = w[i + 3: i + 3 + NW.get(tag, lambda c: 0)(cnt)]
    if tag == 5 and 0x0c4ef8 <= addr < 0x0c5554:
        raw = struct.pack('<%dI' % len(body), *body)
        for k in range(cnt): pm[addr + k] = int.from_bytes(raw[6 * k: 6 * k + 6], 'little')
    elif tag == 4 and 0xe4850 <= addr < 0xe8000:
        for k in range(cnt): dm[addr + k] = body[k]
    elif tag == 4 and cnt == 8 and addr == 0x200588:
        prim = list(body)
    i += 3 + NW.get(tag, lambda c: 0)(cnt)
src, secs, syms, end, data = click_kernel.assemble(probe=PROBE)
want_pm = {s.addr + k: v for s in secs if s.kind == 'pm' for k, v in enumerate(s.words)}
want_dm = {s.addr + k: v for s in secs if s.kind == 'dm' for k, v in enumerate(s.words)}
check(all(pm.get(a) == v for a, v in want_pm.items()) and len(want_pm) > 200, f'kernel code in the image = assembled ({len(want_pm)} instructions at {min(want_pm):#x})')
check(dm == want_dm, f'kernel data in the image = assembled ({len(dm)} words at {min(dm):#x})')
check(prim is not None and prim[0] == 0x9c75 and prim[5] == syms['CLICK_ENTRY'] and prim[6:] == [0x91, 0x0d],
      f'primitive 0x9c75 record -> {prim[5]:#x}, DM 0x91 / PM 0x0d' if prim else 'primitive record missing')

# Entry 3: the knobs as the unit will read them
e3 = pa.get_entry_swapped(img, 3)
info = pa.parse_entry3_full(e3)
m = pa.find_model(info, build_click.TAKEOVER)
md = m.get('meta') or {}
check(m['displayName'] == 'Click' and md.get('category') == 'delay' and md.get('subcategory') == 'mono'
      and md.get('displayNameShort') == 'Click' and md.get('displayParamCount') == '6',
      f"{build_click.TAKEOVER} (model {m['model_id']}) is Click, Delay > Mono, 6 knobs shown: {md}")
stock3 = pa.parse_entry3_full(pa.get_entry_swapped(stock, 3))
ir = pa.find_model(info, 'HD2_ImpulseResponse1024Mono'); ir0 = pa.find_model(stock3, 'HD2_ImpulseResponse1024Mono')
check(ir['displayName'] == ir0['displayName'] and ir['blob_index'] == ir0['blob_index'] and len(ir['params']) == len(ir0['params']),
      'the 1024 IR block is stock again')
def f(x): return struct.unpack('<f', struct.pack('<I', x))[0]
ps = sorted(m['params'], key=lambda p: p['slot'])
for p, c in zip(ps, build_click.CLICK_PARAMS):
    raw = struct.unpack_from('<5I3I', e3, p['off'])
    rng = (raw[5], raw[6], raw[7]) if p['type'] == 2 else tuple(round(f(x), 3) for x in raw[5:8])
    meta = p.get('meta') or {}
    labels = [meta.get(str(k)) for k in range(rng[0], rng[1] + 1)] if p['type'] == 2 else []
    print(f"      slot {p['slot']} {meta.get('displayName')!r:14s} type {p['type']} {meta.get('displayType'):8s} range {rng} {labels}")
check([p['slot'] for p in ps] == list(range(1, 9)), 'eight parameters, slots 1..8 (six knobs shown)')
byname = {p['name']: p for p in ps}
check(byname['Time']['meta'].get('coupledIndex') == '7' and byname['Time']['meta'].get('toggleSelectIndex') == '8'
      and byname['SyncSelect1']['meta'].get('coupledIndex') == '1' and byname['SyncSelect1']['meta'].get('toggleSelectIndex') == '8',
      'Time <-> note value (slot 7), Tempo Sync (slot 8) linked')
S = info['strings']; dd = m['words']
states = [S[struct.unpack_from('<5I', e3, dd[10] + 20 * k)[2]] for k in range(dd[6])]
print('      states:', states)
e0 = pa.get_entry_swapped(img, 0); A = pa.EFFECTS_E0; segs = pa._parse_e0_segments_any(e0)
fo = lambda va, ln=4: pa._e0_vaddr_to_foff(segs, va, ln)
for i in range(A.TAB2_CNT):
    va = A.TAB2_BASE + 44 * i
    if struct.unpack_from('<I', e0, fo(va))[0] == m['words'][2]:
        counts = struct.unpack_from('<3I', e0, fo(va, 44) + 24)
check(counts == (6, 8, 8), f'Entry 0 Table 2 counts {counts} (shown, parameters, parameters)')

# the parameter map: the sync step as stock Mod/Chorus Echo has it
def pmap(e4w, bi):
    d = e4w[3]; ln, off = e4w[d + 2 * bi], e4w[d + 2 * bi + 1]; bw = list(e4w[off:off + ln])
    pm = bw[bw[6]: bw[6] + bw[7]]
    nodes = [pm[pm[0] + 10 * k: pm[0] + 10 * k + 10] for k in range(pm[18])]
    edges = [tuple(pm[pm[4] + 4 * k: pm[4] + 4 * k + 4]) for k in range(pm[20])]
    return bw, pm, nodes, edges
def sig(nodes, edges, pm, k):                       # a node's op, outs, state, data
    n = nodes[k]; return (n[3], n[4], n[5], tuple(pm[n[0]: n[0] + n[6]]))
# Entry 4: the host blob maps every slot, each to the right instance word
e4 = pa.get_entry_swapped(img, 4)
check(pa.pmap_slots_without_param(e4, m['blob_index'], ps) == [], f"blob {m['blob_index']}: every mapped slot has a knob")
w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
d = w4[3]; ln, off = w4[d + 2 * m['blob_index']], w4[d + 2 * m['blob_index'] + 1]
b = w4[off: off + ln]
pin, npin = b[10], b[11]
pins = [b[pin + 4 * k: pin + 4 * k + 4] for k in range(npin)]
writes = sorted(q[1] for q in pins if q[3] == 2 and q[0] == 0x0e)   # path 0x0e = member 1, the primitive
others = sorted((hex(q[0]), q[1]) for q in pins if q[3] != 1 and q[0] != 0x0e); print('      other members inits (path, pid):', others)
check(writes == [5, 6, 7, 8, 9, 10], f'knob inits write instance words {writes}')
e4s = struct.unpack('<%dI' % (len(pa.get_entry_swapped(stock, 4)) // 4), pa.get_entry_swapped(stock, 4))
sm = pa.find_model(stock3, build_click.SYNC_MODEL)
_, spm, sn, se = pmap(e4s, sm['blob_index'])
_, cpm, cn, ce = pmap(w4, m['blob_index'])
def chain(nodes, edges, pm):                        # (input op -> port) feeding each 0x2a / 0x54 node
    out = {}
    for k, nd in enumerate(nodes):
        if nd[3] in (0x2a, 0x54):
            ins = sorted((nodes[f][3], tp) for f, t, fp, tp in edges if t == k)
            out[nd[3]] = (sig(nodes, edges, pm, k), ins)
    return out
cs, ss = chain(cn, ce, cpm), chain(sn, se, spm)
print('      stock sync step:', ss); print('      Click sync step:', cs)
check(cs == ss, 'sync step identical to stock (ops, state, data, inputs by op and port)')
pick = next(k for k, nd in enumerate(cn) if nd[3] == 0x54)
tw = [t for f, t, fp, tp in ce if f == pick]
check(len(tw) == 1 and cn[tw[0]][3] == 1 and cpm[cn[tw[0]][0] + 1] == 5, 'the synced time is written to word 5')
H = cpm[12:18]; nA, nC, nD = cpm[18], cpm[20], cpm[21]
check(H == [sum(nd[5] for nd in cn), nA, nD + sum(nd[4] for nd in cn) + sum(nd[8] for nd in cn),
            nC + nD + sum(nd[8] for nd in cn), nD, cpm[22]], f'map header sizes consistent {H}')


# Entries untouched
same = [k for k in range(len(es)) if k not in (0, 2, 3, 4) and
        img[es[k]['payload_off']: es[k]['payload_off'] + es[k]['payload_len']] ==
        stock[l6ia.parse(stock)[k]['payload_off']: l6ia.parse(stock)[k]['payload_off'] + l6ia.parse(stock)[k]['payload_len']]]
check(same == [k for k in range(len(es)) if k not in (0, 2, 3, 4)], f'entries other than 0/2/3/4 identical to stock: {same}')
print('ALL OK' if ok else 'PROBLEMS')
