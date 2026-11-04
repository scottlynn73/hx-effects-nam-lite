"""Read an all-in-one image back and check it, using its manifest (written by build_all.py; default
build/all_manifest.json, or e.g. build/all_commander_corrupt_manifest.json) for the addresses and the
single-effect images for comparison:

- NAM (model 72) and Click (model 48): parameters, metadata, states and Entry 0 rows as in their own
  images (build_effects.py, build_click.py); host blobs word for word but for the composite id;
- Geiger (model 7, the mono Megaphone), and Commander / Corrupt when built in: the eight knobs as
  build_all.py defines them, in Distortion > Mono, the map writing instance words 5..11 and 13;
- Entry 2: each kernel's code and data are what its assembler makes for its place (NAM from
  build/nam_lite_2slots[_fd17].asm), each hook record points at its kernel, Blob 0's size word and Heap 6;
- Blob 0: the three host composites, member 1 of each on its own primitive, within the buffer;
- no byte of internal memory used by two kernels (from the image's own load blocks);
- every other entry identical to stock.

usage: python3 tools/verify/verify_all.py [manifest.json]   (after build_effects.py, build_click.py and build_all.py)
"""
import json
import os
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
for p in ('tools', 'tools/sharc', 'effects/metronome/sharc', 'effects/geiger/sharc', 'effects/common',
          'effects/commander/sharc', 'effects/corrupt/sharc', '.'):
    sys.path.insert(0, os.path.join(ROOT, p))
os.environ['NAM_DEVICE'] = 'effects'
import build_all  # noqa: E402
import click_kernel  # noqa: E402
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import sasm  # noqa: E402

ok = True


def check(c, msg):
    global ok
    print(('  ok  ' if c else '  FAIL ') + msg)
    ok &= bool(c)


man = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'build', 'all_manifest.json')))
FX = ['geiger'] + man.get('extras', [])


def load(name):
    img, _ = pa.load_l6ia_from_any(os.path.join(ROOT, name))
    pa.select_device(img)
    return img


allimg = load(man['output'])
nam_img = load('build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf')
click_img = load('build/HX_Effects_v3.80.0_Click.hxf')
stock = load('firmware/HX_Effects_v3.80.0_0xd97239907.hxf')
import hashlib  # noqa: E402
check(hashlib.md5(open(os.path.join(ROOT, man['output']), 'rb').read()).hexdigest() == man['output_md5'],
      f'{man["output"]} is the image the manifest describes ({man["output_md5"]})')


def entry(img, k):
    es = l6ia.parse(img)
    return img[es[k]['payload_off']: es[k]['payload_off'] + es[k]['payload_len']]


def model(img, name):
    e3 = pa.get_entry_swapped(img, 3)
    info = pa.parse_entry3_full(e3)
    m = pa.find_model(info, name)
    S, d = info['strings'], m['words']
    states = [S[struct.unpack_from('<5I', e3, d[10] + 20 * k)[2]] for k in range(d[6])]
    params = [(p['name'], p['type'], p['slot'], struct.unpack_from('<3I', e3, p['off'] + 20), sorted((p.get('meta') or {}).items()))
              for p in sorted(m['params'], key=lambda p: p['slot'])]
    return dict(display=m['displayName'], meta=sorted((m.get('meta') or {}).items()), states=states, params=params), m


def blob(img, idx):
    e4 = pa.get_entry_swapped(img, 4)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    d = w4[3]
    ln, off = w4[d + 2 * idx], w4[d + 2 * idx + 1]
    return list(w4[off:off + ln])


def e0_rows(img, name):
    e0 = pa.get_entry_swapped(img, 0)
    idx = pa.find_model(pa.parse_entry3_full(pa.get_entry_swapped(stock, 3)), name)['words'][2]
    A = pa.EFFECTS_E0
    segs = pa._parse_e0_segments_any(e0)
    fo = lambda va, ln=4: pa._e0_vaddr_to_foff(segs, va, ln)
    t1 = next(struct.unpack_from('<IHHI', e0, fo(A.TAB1_BASE + 12 * i, 12)) for i in range(A.TAB1_CNT)
              if struct.unpack_from('<I', e0, fo(A.TAB1_BASE + 12 * i))[0] == idx)
    t2 = next(bytes(e0[fo(A.TAB2_BASE + 44 * i, 44): fo(A.TAB2_BASE + 44 * i, 44) + 44]) for i in range(A.TAB2_CNT)
              if struct.unpack_from('<I', e0, fo(A.TAB2_BASE + 44 * i))[0] == idx)
    return t1, t2


# NAM and Click: as in their own images
for key, single in (('nam', nam_img), ('click', click_img)):
    name = man[key]['model']
    a, ma = model(allimg, name)
    b, mb = model(single, name)
    check(a == b, f'{name} ({a["display"]}): parameters, metadata and states as in its own image')
    ba, bb = blob(allimg, ma['blob_index']), blob(single, mb['blob_index'])
    tree = ba[2]
    check(len(ba) == len(bb) and all(x == y or k == tree + 1 for k, (x, y) in enumerate(zip(ba, bb))),
          f'  host blob {ma["blob_index"]} word for word as in its image, composite {ba[tree + 1]:#x}')
    check(e0_rows(allimg, name) == e0_rows(single, name), '  Entry 0 rows as in its image')

# Geiger, Commander, Corrupt: the eight knobs as defined
for k in FX:
    E = build_all.EFFECTS[k]
    g, mg = model(allimg, man[k]['model'])
    gmeta = dict(g['meta'])
    check(g['display'] == E['display'] and gmeta.get('category') == 'distortion' and gmeta.get('subcategory') == 'mono',
          f'{man[k]["model"]} (model {mg["model_id"]}) is {g["display"]}, {gmeta.get("category")} > {gmeta.get("subcategory")}')
    got = [(p[2], p[0], dict(p[4]).get('displayName')) for p in g['params']]
    check(got == [(s[0], s[3], s[4]) for s in E['params']], f'  eight knobs: {[x[2] for x in got]}')
    for p in g['params']:
        lab = [v for kk, v in p[4] if kk.isdigit()]
        if lab:
            print(f'      {dict(p[4]).get("displayName")}: {lab[:4]}{" ..." if len(lab) > 4 else ""} ({len(lab)})')
    bg = blob(allimg, mg['blob_index'])
    pin, npin = bg[10], bg[11]
    writes = sorted(bg[pin + 4 * j + 1] for j in range(npin) if bg[pin + 4 * j + 3] == 2 and bg[pin + 4 * j] == 0x0e)
    check(writes == [5, 6, 7, 8, 9, 10, 11, 13], f'  its map writes instance words {writes}')
    check(pa.pmap_slots_without_param(pa.get_entry_swapped(allimg, 4), mg['blob_index'], mg['params']) == [], '  every mapped slot has a knob')
    t1, t2 = e0_rows(allimg, man[k]['model'])
    short = E['display'].encode()
    check(t1[3] == man[k]['dsp_cost'] and struct.unpack_from('<3I', t2, 24) == (8, 8, 8) and t2[4:4 + len(short)] == short,
          f'  Entry 0: dsp_cost {t1[3]}, counts {struct.unpack_from("<3I", t2, 24)}, short name {t2[4:20].rstrip(bytes(1))!r}')

# Blob 0
b0 = blob(allimg, 0)
ctab = b0[0x10]
prims = {}
order = ['nam', 'click'] + FX
for cid in range(0x6001c1, 0x6001c1 + len(order)):
    hdr = b0[ctab + 7 * (cid - 0x600000): ctab + 7 * (cid - 0x600000) + 7]
    prims[cid] = b0[hdr[3] + 20 + 6]
want = {0x6001c1 + j: man[k]['primitive'] for j, k in enumerate(order)}
check(prims == want, f'Blob 0 host composites on primitives { {hex(k): hex(v) for k, v in prims.items()} }')
err = pa.sharc_blob0_check(list(b0), man['blob0_words'])
check(err is None, f'Blob 0 ({len(b0):#x} words) fits the {man["blob0_words"]:#x}-word buffer{"" if err is None else ": " + err}')


# Entry 2: the load blocks
def blocks(img):
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
        elif tag == 1:                                # ZERO_LDATA
            for k in range(cnt):
                dm[addr + k] = 0
        i += 3 + NW.get(tag, lambda c: 0)(cnt)
    return pm, dm, w


apm, adm, aw = blocks(allimg)
spm, sdm, _ = blocks(stock)
nam_asm = 'nam_lite_2slots.asm' if 'far_d' not in man['nam'] else f'nam_lite_2slots_fd{man["nam"]["far_d"]}.asm'
n_secs, n_syms = sasm.assemble(open(os.path.join(ROOT, 'build', nam_asm)).read(), nam_asm)
_, c_secs, c_syms, _, _ = click_kernel.assemble(place='b3')
owners = [('NAM', n_secs, n_syms['CUSTOM_AMP_ENTRY'], man['nam']['primitive']),
          ('Click', c_secs, c_syms['CLICK_ENTRY'], man['click']['primitive'])]
done = set()
for k in FX:
    b = man[k].get('kernel', k)                       # Commander and Corrupt may share one kernel
    kern = build_all.Kernel(b)
    kern.set_place(*man[k]['place'])
    _, k_secs, k_syms, _, _ = kern.assemble()
    owners.append((build_all.EFFECTS[k]['display'] + (f' ({b})' if b != k else ''), [] if b in done else k_secs,
                   k_syms[build_all.EFFECTS[k]['entry']], man[k]['primitive']))
    done.add(b)
used = {}                                             # byte -> owner, for the overlap check
for who, secs, ent, prim in owners:
    pmw = {s.addr + k: v for s in secs if s.kind == 'pm' for k, v in enumerate(s.words)}
    dmw = {s.addr + k: v for s in secs if s.kind == 'dm' for k, v in enumerate(s.words)}
    if pmw:
        check(all(apm.get(a) == v for a, v in pmw.items()) and all(adm.get(a) == v for a, v in dmw.items()),
              f'{who}: {len(pmw)} instructions at {min(pmw):#x} and {len(dmw)} data words as assembled for its place')
    table, _ = pa.sharc_prim_table(entry(allimg, 2))
    rec = [adm.get(table[prim] + k) for k in range(8)]
    check(rec[0] == prim and rec[5] == ent and rec[6:] == [0x91, 0x0d], f'  primitive {prim:#06x} -> {ent:#x}')
    for a in pmw:
        base = a & ~0xFFFF
        for byte in range((a - base) * 6, (a - base) * 6 + 6):
            used.setdefault((base, byte), set()).add(who)
    for a in dmw:
        base = a & ~0xFFFF
        for byte in range((a - base) * 4, (a - base) * 4 + 4):
            used.setdefault((base, byte), set()).add(who)
lo, hi = man['nam']['block3']
for a in range(lo, hi):
    for byte in range((a - 0xE0000) * 4, (a - 0xE0000) * 4 + 4):
        used.setdefault((0xE0000, byte), set()).add('NAM')
shared = [k for k, v in used.items() if len(v) > 1]
check(not shared, f'no byte of internal memory used by two kernels ({len(used)} bytes in use)')
D = pa.EFFECTS_DSP
check(aw[D.BLOB0_SIZE[1]] == man['blob0_words'] and (aw[D.HEAP6_WORDS[0]], aw[D.HEAP6_WORDS[1]]) == D.HEAP6_MOVED,
      f'Blob 0 buffer size word {aw[D.BLOB0_SIZE[1]]:#x}, Heap 6 moved to {aw[D.HEAP6_WORDS[0]]:#x}')

e2_bytes = len(entry(allimg, 2))
check(e2_bytes <= 0x80000, f'Entry 2: {e2_bytes} bytes, within its 512 KiB partition ({0x80000 - e2_bytes} free)')
others = [k for k in range(len(l6ia.parse(allimg))) if k not in (0, 2, 3, 4)]
check(all(entry(allimg, k) == entry(stock, k) for k in others), f'entries {others} identical to stock')
print('ALL OK' if ok else 'PROBLEMS')
sys.exit(0 if ok else 1)
