"""Read build/HX_Effects_v3.80.0_NAM_Click.hxf back and check it against the two images proven on the
unit (build_effects.py's NAM image, build_click.py's Click image) and the stock firmware:

- Entry 3: model 72 (1024 IR) is exactly the NAM image's model 72; model 48 (mono Mod/Chorus Echo) is
  exactly the Click image's model 48 (names, types, slots, ranges, metadata, blob, states);
- Entry 4: each host blob is the single image's, word for word, but for its composite id; Blob 0 holds
  both composites, each member 1 on its own primitive;
- Entry 2: NAM's code differs from the NAM image's only in the instructions that load its DDR2 slot
  base; Click's code is click_kernel.assemble(place='b3'); the two primitive records point at them;
  the Blob 0 size word is 0x79000 and Heap 6 is moved;
- Entry 0: both rows as in their own images;
- every other entry identical to stock.

usage: python3 tools/verify/verify_nam_click.py   (after build_effects.py, build_click.py, build_nam_click.py)
"""
import os
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
for p in ('tools', 'tools/sharc', 'effects/metronome/sharc', '.'):
    sys.path.insert(0, os.path.join(ROOT, p))
os.environ['NAM_DEVICE'] = 'effects'
import click_kernel  # noqa: E402
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402

ok = True


def check(c, msg):
    global ok
    print(('  ok  ' if c else '  FAIL ') + msg)
    ok &= bool(c)


def load(name):
    img, _ = pa.load_l6ia_from_any(os.path.join(ROOT, name))
    pa.select_device(img)
    return img


combo = load('build/HX_Effects_v3.80.0_NAM_Click.hxf')
nam_img = load('build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf')
click_img = load('build/HX_Effects_v3.80.0_Click.hxf')
stock = load('firmware/HX_Effects_v3.80.0_0xd97239907.hxf')


def entry(img, k):
    es = l6ia.parse(img)
    return img[es[k]['payload_off']: es[k]['payload_off'] + es[k]['payload_len']]


def model_view(img, name):
    e3 = pa.get_entry_swapped(img, 3)
    info = pa.parse_entry3_full(e3)
    m = pa.find_model(info, name)
    S, d = info['strings'], m['words']
    states = [S[struct.unpack_from('<5I', e3, d[10] + 20 * k)[2]] for k in range(d[6])]
    params = [(p['name'], p['type'], p['slot'], struct.unpack_from('<3I', e3, p['off'] + 20), sorted((p.get('meta') or {}).items()))
              for p in sorted(m['params'], key=lambda p: p['slot'])]
    return dict(display=m['displayName'], meta=sorted((m.get('meta') or {}).items()), states=states, params=params), m


def blob_words(img, idx):
    e4 = pa.get_entry_swapped(img, 4)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    d = w4[3]
    ln, off = w4[d + 2 * idx], w4[d + 2 * idx + 1]
    return list(w4[off:off + ln]), w4


# Entry 3
for name, single in (('HD2_ImpulseResponse1024Mono', nam_img), ('HD2_DelayModChorusEchoMono', click_img)):
    a, ma = model_view(combo, name)
    b, mb = model_view(single, name)
    check(a == b, f'{name} ({a["display"]}): same parameters, metadata and states as in its own image')
    # Entry 4: the host blob, but for the composite id at the tree root
    ba, w4a = blob_words(combo, ma['blob_index'])
    bb, _ = blob_words(single, mb['blob_index'])
    tree = ba[2]
    same = len(ba) == len(bb) and all(x == y or k == tree + 1 for k, (x, y) in enumerate(zip(ba, bb)))
    check(same, f'  host blob {ma["blob_index"]}: word for word as blob {mb["blob_index"]} of its image, '
                f'composite {ba[tree + 1]:#x} (there {bb[tree + 1]:#x})')

# Blob 0: both composites, member 1 on its own primitive
_, w4 = blob_words(combo, 0)
b0 = blob_words(combo, 0)[0]
ctab = b0[0x10]
prims = {}
for cid in (0x6001c1, 0x6001c2):
    hdr = b0[ctab + 7 * (cid - 0x600000): ctab + 7 * (cid - 0x600000) + 7]
    prims[cid] = b0[hdr[3] + 20 + 6]
check(prims == {0x6001c1: 0x9c75, 0x6001c2: 0x0128}, f'Blob 0: member 1 of each host composite {{{", ".join(f"{k:#x}: {v:#x}" for k, v in prims.items())}}}')
err = pa.sharc_blob0_check(list(b0), 0x79000)
check(err is None, f'Blob 0 fits the 0x79000-word buffer ({len(b0):#x} words){"" if err is None else ": " + err}')


# Entry 2
def e2_blocks(img):
    e2 = entry(img, 2)
    w = struct.unpack('<%dI' % (len(e2) // 4), e2)
    NW = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2, 6: lambda c: c * 2,
          0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
    pm, dm = {}, {}
    i = 384
    while i + 3 <= len(w):
        tag, cnt, addr = w[i:i + 3]
        if tag == 0:
            break
        body = w[i + 3: i + 3 + NW.get(tag, lambda c: 0)(cnt)]
        if tag == 5:
            raw = struct.pack('<%dI' % len(body), *body)
            for k in range(cnt):
                pm[addr + k] = int.from_bytes(raw[6 * k: 6 * k + 6], 'little')
        elif tag == 4:
            for k in range(cnt):
                dm[addr + k] = body[k]
        i += 3 + NW.get(tag, lambda c: 0)(cnt)
    return pm, dm, w


cpm, cdm, cw = e2_blocks(combo)
npm, ndm, nw = e2_blocks(nam_img)
nam_code = {a: v for a, v in npm.items() if 0xC4EF8 <= a < 0xC5554}
diff = [a for a, v in nam_code.items() if cpm.get(a) != v]
check(len(nam_code) > 1000 and len(diff) <= 4,
      f'NAM code: {len(nam_code)} instructions as in the NAM image but {len(diff)} (its DDR2 slot base) at {[hex(a) for a in diff]}')
src, secs, syms, end, data = click_kernel.assemble(place='b3')
want = {s.addr + k: v for s in secs if s.kind == 'pm' for k, v in enumerate(s.words)}
wantd = {s.addr + k: v for s in secs if s.kind == 'dm' for k, v in enumerate(s.words)}
check(all(cpm.get(a) == v for a, v in want.items()), f'Click code: {len(want)} instructions at {min(want):#x} as assembled for Block 3')
check(all(cdm.get(a) == v for a, v in wantd.items()), f'Click data: {len(wantd)} words at {min(wantd):#x} as assembled')
table, _ = pa.sharc_prim_table(entry(combo, 2))
rec_n = [cdm.get(table[0x9c75] + k) for k in range(8)]
rec_c = [cdm.get(table[0x0128] + k) for k in range(8)]
check(rec_n[0] == 0x9c75 and rec_n[5] == 0xC4EF8 and rec_n[6:] == [0x91, 0x0d], f'primitive 0x9c75 -> {rec_n[5]:#x} (NAM)')
check(rec_c[0] == 0x0128 and rec_c[5] == syms['CLICK_ENTRY'] and rec_c[6:] == [0x91, 0x0d], f'primitive 0x0128 -> {rec_c[5]:#x} (Click)')
D = pa.EFFECTS_DSP
check(cw[D.BLOB0_SIZE[1]] == 0x79000 and (cw[D.HEAP6_WORDS[0]], cw[D.HEAP6_WORDS[1]]) == D.HEAP6_MOVED,
      f'Blob 0 buffer size word {cw[D.BLOB0_SIZE[1]]:#x}, Heap 6 at {cw[D.HEAP6_WORDS[0]]:#x}..{cw[D.HEAP6_WORDS[1]]:#x}')


# Entry 0 rows
def row(img, name):
    e0 = pa.get_entry_swapped(img, 0)
    info = pa.parse_entry3_full(pa.get_entry_swapped(stock, 3))
    idx = pa.find_model(info, name)['words'][2]
    A = pa.EFFECTS_E0
    segs = pa._parse_e0_segments_any(e0)
    fo = lambda va, ln=4: pa._e0_vaddr_to_foff(segs, va, ln)
    t1 = next(struct.unpack_from('<IHHI', e0, fo(A.TAB1_BASE + 12 * i, 12)) for i in range(A.TAB1_CNT)
              if struct.unpack_from('<I', e0, fo(A.TAB1_BASE + 12 * i))[0] == idx)
    t2 = next(bytes(e0[fo(A.TAB2_BASE + 44 * i, 44): fo(A.TAB2_BASE + 44 * i, 44) + 44]) for i in range(A.TAB2_CNT)
              if struct.unpack_from('<I', e0, fo(A.TAB2_BASE + 44 * i))[0] == idx)
    return t1, t2


for name, single in (('HD2_ImpulseResponse1024Mono', nam_img), ('HD2_DelayModChorusEchoMono', click_img)):
    check(row(combo, name) == row(single, name), f'Entry 0 rows of {name} as in its own image')

others = [k for k in range(len(l6ia.parse(combo))) if k not in (0, 2, 3, 4)]
check(all(entry(combo, k) == entry(stock, k) for k in others), f'entries {others} identical to stock')
print('ALL OK' if ok else 'PROBLEMS')
sys.exit(0 if ok else 1)
