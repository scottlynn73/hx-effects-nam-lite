#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with NAM A2 Lite, Click and Geiger in one image.

usage: python3 build_all.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--no-check]

  NAM A2 Lite   as build_nam_click.py, but with 2 slots (two NAM blocks at once; a third passes its
                input through) instead of 3, which frees Block 3 for Geiger, and its DDR2 blocks at
                0x296400 (the Blob 0 buffer holds three host graphs: 0x7a000 words). IR > Single.
  Click         as build_nam_click.py (Delay > Mono, the mono Mod/Chorus Echo's slot), primitive 0x0128,
                in the top of Block 3.
  Geiger        bit crusher / sample-rate reducer / 16-curve waveshaper (effects/geiger), taking over
                the mono Megaphone (Distortion > Mono > "Geiger"; the stereo Megaphone stays), primitive
                0x012e (zero uses in the stock graphs), code and data in the Block 3 space between
                NAM's slots and Click's data.

Each kernel is checked in the simulator first unless --no-check (NAM bit for bit against nam_a2.asm with
2 slots, Click and Geiger bit for bit against their C references at their addresses), and the build
asserts no byte of internal memory is used by two of them.
Writes build/HX_Effects_v3.80.0_All.hxf.
"""
import hashlib
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools')
for p in ('tools', 'tools/sharc', 'effects/metronome/sharc', 'effects/geiger/sharc'):
    sys.path.insert(0, os.path.join(HERE, p))

import build_click as bc  # noqa: E402
import build_effects as be  # noqa: E402
import build_nam_click as bnc  # noqa: E402

STOCK_MD5 = '7c2ebdf1bffb6bcc5f89dda97f91e40c'
NAM_PRIM, CLICK_PRIM, GEIGER_PRIM = 0x9c75, 0x0128, 0x012e
NAM_SLOTS = 2

GEIGER_TAKEOVER = 'HD2_DistMegaphoneMono'
GEIGER_NAME, GEIGER_DISPLAY = 'HD2_DistGeiger', 'Geiger'
GEIGER_COST = 500                      # measured worst 2,528 of ~150,000 cycles per call (1.7 %), x3
CURVE_NAMES = ['Linear', 'Soft', 'Hard', 'Sine Fold', 'Tri Fold', 'Full Wave', 'Half Wave', 'Steps',
               'Asym', 'Cheby 3', 'Cheby 5', 'Sine', 'Root', 'Spline', 'Ring', 'Gate']
LIST, BOOL = 'list', 'bool'
GEIGER_PARAMS = (   # slot, pid (instance word), template model, template param, display, short, kind, range, default
    (1, 5,  'HD2_AmpLine6Clarity', 'Drive', 'Gain', 'Gain', 'db', (0.0, 36.0), 6.0),
    (2, 6,  'HD2_AmpLine6Clarity', 'Bass', 'Sample Rate', 'Rate', 'hz', (250.0, 48000.0), 12000.0),
    (3, 7,  'HD2_DelayMultiPassMono', 'Pattern', 'Bit Depth', 'Bits', LIST,
     {b: (f'{b} bit' if b == 1 else f'{b} bits') for b in range(1, 17)}, 8),
    (4, 8,  'HD2_FM4SynthOMatic', 'Wave', 'Curve', 'Curve', LIST, dict(enumerate(CURVE_NAMES)), 0),
    (5, 9,  'HD2_AmpLine6Clarity', 'Treble', 'Tone', 'Tone', 'knob', (0.0, 1.0), 0.8),
    (6, 10, 'HD2_AmpLine6Clarity', 'Presence', 'Output', 'Output', 'db', (-36.0, 12.0), -6.0),
    (7, 11, 'HD2_AmpLine6Clarity', 'Mid', 'Mix', 'Mix', 'percent', (0.0, 1.0), 1.0),
    (8, 13, 'HD2_AmpLine6Clarity', 'HumSwitch', 'Anti-Alias', 'AntiAls', BOOL, ('Off', 'On'), 0),
)


def f2u(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def knob_params(pa, e3, info, spec):
    """Per knob the template's record (type, state) with our range, default and display metadata."""
    out = []
    for slot, pid, mname, pname, disp, short, kind, rng, dflt in spec:
        m = pa.find_model(info, mname)
        p = next(p for p in m['params'] if p['name'] == pname)
        raw = list(struct.unpack_from('<5I3I', e3, p['off']))
        raw[4] = slot
        meta = [('displayName', 7, disp), ('displayNameShort', 7, short)]
        if kind == LIST:
            assert p['type'] == 2 and len(rng) <= 21, f'{mname}.{pname}: not an int, or a list longer than stock'
            raw[5], raw[6], raw[7] = min(rng), max(rng), dflt
            meta = [('displayType', 7, 'list')] + meta + [(str(k), 7, v) for k, v in sorted(rng.items())]
        elif kind == BOOL:
            assert p['type'] == 1, f'{mname}.{pname} is not a bool'
            raw[5], raw[6], raw[7] = 0, 0, dflt
            meta += [('false', 7, rng[0]), ('true', 7, rng[1])]
        else:
            assert p['type'] == 3, f'{mname}.{pname} is not a float'
            raw[5], raw[6], raw[7] = f2u(rng[0]), f2u(rng[1]), f2u(dflt)
            meta = [('displayType', 7, kind)] + meta
        out.append({'slot': slot, 'pid': pid, 'role': 'direct', 'name': pname, 'type': p['type'],
                    'op': pa.NAM_INPUT_OP[p['type']], 'raw': raw, 'meta': meta,
                    'state': bc._state_of(pa, e3, info, m, pname), 'default_word': raw[7]})
    assert [p['slot'] for p in out] == list(range(1, len(out) + 1))
    assert len({p['name'] for p in out}) == len(out), 'two knobs share a parameter name'
    return out


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        sys.exit(__doc__)
    stock = os.path.abspath(argv.pop(0)) if argv and not argv[0].startswith('-') else \
        os.path.join(HERE, 'firmware', 'HX_Effects_v3.80.0_0xd97239907.hxf')
    if not os.path.isfile(stock) or hashlib.md5(open(stock, 'rb').read()).hexdigest() != STOCK_MD5:
        sys.exit(f'{stock}: missing or not the HX Effects 3.80.0 firmware (MD5 {STOCK_MD5}).')
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', 'HX_Effects_v3.80.0_All.hxf')
    build = os.path.join(HERE, 'build')
    os.makedirs(build, exist_ok=True)
    nam_asm = os.path.join(build, 'nam_lite_2slots.asm')
    image = os.path.join(build, 'all.l6ia')
    sdr_base = bnc.BLOB0_BASE + bnc.BLOB0_WORDS_ALL      # three host graphs: Blob 0 buffer 0x7a000 words
    env = dict(os.environ, NAM_DEVICE='effects', NAM_SDR_BASE=hex(sdr_base))
    check = '--no-check' not in argv
    run = bnc.run

    # 1. the kernels; Geiger goes between NAM's (now smaller) Block 3 area and Click's data
    log = run(sys.executable, be.KERNEL, '-o', nam_asm, '--slots', str(NAM_SLOTS), *(['--check'] if check else []), env=env)
    m = re.search(r'block 3: (0x[0-9a-f]+)\.\.(0x[0-9a-f]+)', log)
    nam_b3 = (int(m.group(1), 16), int(m.group(2), 16))
    import click_kernel
    import geiger_kernel as gk
    g_data0 = (nam_b3[1] + 0xF) & ~0xF
    gk.PLACES['probe'] = (0xC4EF8, 0xC5554, g_data0)            # to measure the data (code elsewhere)
    _, (_, g_data_end) = gk.source('probe')
    code48 = 0xE0000 + (((g_data_end - 0xE0000) * 2 + 2) // 3 + 1 & ~1)
    click_data0 = click_kernel.PLACES['b3'][2]
    code48_end = 0xE0000 + (click_data0 - 0xE0000) * 2 // 3
    gk.PLACES['b3g'] = (code48, code48_end, g_data0)
    if check:
        r = subprocess.run(['make', '-s', '-C', os.path.join(HERE, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'build_all.py: could not build effects/out/libfx.so:\n{r.stderr}')
        run(sys.executable, os.path.join(HERE, 'effects', 'metronome', 'sharc', 'click_kernel.py'), '--check', '--place', 'b3')
        try:
            gk.check(0.25, 'b3g')
        except AssertionError as ex:
            sys.exit(f'build_all.py: Geiger check failed: {ex}')

    os.environ['NAM_DEVICE'] = 'effects'
    import l6ia
    import patch_amp as pa
    import sasm

    l6ia_bytes, _ = pa.load_l6ia_from_any(stock)
    assert pa.select_device(l6ia_bytes) is pa.EFFECTS_DSP
    D = pa.EFFECTS_DSP
    assert D.HEAP6[0] - D.BLOB0_WORDS == bnc.BLOB0_BASE
    assert sdr_base + NAM_SLOTS * 0x5000 <= D.HEAP6[1]
    D.BLOB0_MAX_WORDS = bnc.BLOB0_WORDS_ALL
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    info = pa.parse_entry3_full(e3)
    clone = pa.find_model(info, be.CLONE)
    targets = {'nam': pa.find_model(info, be.TAKEOVER), 'click': pa.find_model(info, bc.TAKEOVER),
               'geiger': pa.find_model(info, GEIGER_TAKEOVER)}
    params = {'nam': pa.nam_params(e3, info), 'click': bc.click_params(pa, e3, info),
              'geiger': knob_params(pa, e3, info, GEIGER_PARAMS)}

    # 2. Entry 4: three host graphs (copies of the 2048 IR block's), each on its own primitive
    e4n, b_n, c_n = pa.add_model_entry4(e4, clone['blob_index'], params['nam'], 0, prim_id=NAM_PRIM)
    e4n, b_c, c_c = pa.add_model_entry4(e4n, clone['blob_index'], params['click'], 0, blob_fn=bc.click_host_blob, prim_id=CLICK_PRIM)
    e4n, b_g, c_g = pa.add_model_entry4(e4n, clone['blob_index'], params['geiger'], 0, prim_id=GEIGER_PRIM)
    blobs = {'nam': b_n, 'click': b_c, 'geiger': b_g}
    print(f'[+] Entry 4: NAM blob {b_n} on {c_n:#x} ({NAM_PRIM:#06x}), Click blob {b_c} on {c_c:#x} ({CLICK_PRIM:#06x}), '
          f'Geiger blob {b_g} on {c_g:#x} ({GEIGER_PRIM:#06x})')

    # 3. Entry 2: Blob 0's buffer and Heap 6
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)

    # 4. Entry 3: the three models, descriptors copied over their targets
    e3n, id_n, _ = pa.add_model_entry3(e3, clone, be.NAME, be.DISPLAY, b_n, params['nam'])
    e3n, id_c, _ = pa.add_model_entry3(e3n, targets['click'], bc.NAME, bc.DISPLAY, b_c, params['click'],
                                       meta_set={'displayNameShort': bc.SHORT, 'displayParamCount': str(len(params['click']) - 2)})
    e3n, id_g, _ = pa.add_model_entry3(e3n, targets['geiger'], GEIGER_NAME, GEIGER_DISPLAY, b_g, params['geiger'])
    e3n = bytearray(e3n)
    ms = pa.parse_entry3_full(bytes(e3n))['models']
    for new_id, key in ((id_n, 'nam'), (id_c, 'click'), (id_g, 'geiger')):
        d_new = struct.unpack_from('<14I', e3n, ms[new_id]['off'])
        d_tgt = list(struct.unpack_from('<14I', e3n, ms[targets[key]['model_id']]['off']))
        for k in (0, 1, 6, 7, 10, 11, 13):
            d_tgt[k] = d_new[k]
        struct.pack_into('<14I', e3n, ms[targets[key]['model_id']]['off'], *d_tgt)
    e3n = bytes(e3n)
    chk = pa.parse_entry3_full(e3n)['models']
    for key, disp in (('nam', be.DISPLAY), ('click', bc.DISPLAY), ('geiger', GEIGER_DISPLAY)):
        t = chk[targets[key]['model_id']]
        assert t['displayName'] == disp and t['blob_index'] == blobs[key] and len(t['params']) == len(params[key]), key
    print(f'[+] Entry 3: {be.TAKEOVER} -> {be.DISPLAY}; {bc.TAKEOVER} -> {bc.DISPLAY}; {GEIGER_TAKEOVER} -> {GEIGER_DISPLAY}')

    # 5. Entry 0
    e0n, *_ = pa.takeover_entry0_effects(e0, targets['nam']['words'][2], be.DISPLAY, short_name=be.SHORT,
                                         dsp_cost=be.DSP_COST, n_params=len(params['nam']), strip_title=be.STRIP_TITLE)
    e0n, *_ = pa.takeover_entry0_effects(e0n, targets['click']['words'][2], bc.DISPLAY, short_name=bc.SHORT,
                                         dsp_cost=bc.DSP_COST, n_params=len(params['click']), strip_title=None,
                                         n_display=len(params['click']) - 2)
    e0n, pid_g, _, hits_g = pa.takeover_entry0_effects(e0n, targets['geiger']['words'][2], GEIGER_DISPLAY,
                                                       short_name=GEIGER_DISPLAY, dsp_cost=GEIGER_COST,
                                                       n_params=len(params['geiger']), strip_title=None)
    print(f'[+] Entry 0: {GEIGER_DISPLAY} preset_id {pid_g}, browser slots {hits_g}, dsp_cost {GEIGER_COST}')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: e0n, 2: l6ia.swap32(e2_raw), 3: e3n, 4: e4n})

    # 6. Entry 2: the three kernels, no shared byte, three hooks
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked = pa._scan_e2_injected(e2_raw)
    assert used_pm_end <= 0x0c4ef8 and not hooked, 'Entry 2 already has injected code'
    n_secs, n_syms = sasm.assemble(open(nam_asm).read(), os.path.basename(nam_asm))
    _, c_secs, c_syms, c_end, c_data = click_kernel.assemble(place='b3')
    _, g_secs, g_syms, g_end, g_data = gk.assemble('b3g')
    kernels = {'NAM': (n_secs, n_syms['CUSTOM_AMP_ENTRY'], NAM_PRIM),
               'Click': (c_secs, c_syms['CLICK_ENTRY'], CLICK_PRIM),
               'Geiger': (g_secs, g_syms['GEIGER_ENTRY'], GEIGER_PRIM)}
    regions = {who: [(*bnc.byte_range(s.kind, s.addr, len(s.words)), f'{who} {s.kind} {s.addr:#x}+{len(s.words)}')
                     for s in secs] for who, (secs, _, _) in kernels.items()}
    regions['NAM'].append((*bnc.byte_range('dm', nam_b3[0], nam_b3[1] - nam_b3[0]), f'NAM Block 3 {nam_b3[0]:#x}..{nam_b3[1]:#x}'))
    owners = list(regions)
    for i, a in enumerate(owners):
        for b in owners[i + 1:]:
            for x in regions[a]:
                for y in regions[b]:
                    if x[0] == y[0] and x[1] < y[2] and y[1] < x[2]:
                        sys.exit(f'build_all.py: memory overlap: {x[3]} and {y[3]}')
    for reg in regions.values():
        for blk, lo, hi, what in reg:
            assert hi <= 0x20000, f'{what} runs past its block'
    print(f'[+] memory: NAM Block 3 {nam_b3[0]:#x}..{nam_b3[1]:#x}; Geiger data {g_data[0]:#x}..{g_data[1]:#x}, '
          f'code {gk.PLACES["b3g"][0]:#x}..{g_end:#x}; Click data {c_data[0]:#x}.., code {click_kernel.PLACES["b3"][0]:#x}..{c_end:#x}: '
          f'no byte shared')
    ldr = []
    for secs, _, _ in kernels.values():
        for s in secs:
            ldr += pa.pack_init_l48(s.addr, s.words) if s.kind == 'pm' else pa.pack_init_l32(s.addr, s.words)
    table, _ = pa.sharc_prim_table(e2_raw)
    template = pa.sharc_prim_record(e2_raw, 0x822)
    for who, (_, entry, prim) in kernels.items():
        assert prim in table, f'primitive {prim:#x} not in the table'
        ldr += pa.pack_init_l32(table[prim], [prim] + list(template[1:5]) + [entry, 0x91, 0x0d])
        print(f'[+] Entry 2: {who} at PM {entry:#x} via {prim:#06x} @ {table[prim]:#x}')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {2: l6ia.swap32(pa.inject_sharc_ldr_blocks(e2_raw, ldr))})
    open(image, 'wb').write(l6ia_bytes)

    # 7. verify and pack
    if 'ALL OK' not in run(sys.executable, os.path.join(TOOLS, 'l6ia_verify.py'), image):
        sys.exit('build_all.py: the image failed its checksum check')
    run(sys.executable, os.path.join(TOOLS, 'hxf.py'), 'pack', image, out, '--donor', stock)
    import json
    manifest = dict(input=os.path.basename(stock), input_md5=STOCK_MD5,
                    output=os.path.relpath(out, HERE), output_md5=hashlib.md5(open(out, 'rb').read()).hexdigest(),
                    nam=dict(model=be.TAKEOVER, primitive=NAM_PRIM, slots=NAM_SLOTS, block3=list(nam_b3),
                             sdram_base=sdr_base, dsp_cost=be.DSP_COST),
                    click=dict(model=bc.TAKEOVER, primitive=CLICK_PRIM, place=list(click_kernel.PLACES['b3']), dsp_cost=bc.DSP_COST),
                    geiger=dict(model=GEIGER_TAKEOVER, primitive=GEIGER_PRIM, place=list(gk.PLACES['b3g']),
                                data=list(g_data), dsp_cost=GEIGER_COST),
                    blob0_words=bnc.BLOB0_WORDS_ALL, checked=check)
    json.dump(manifest, open(os.path.join(build, 'all_manifest.json'), 'w'), indent=1)
    print(f'\nDone: {out}\nFlash: python3 tools/flash.py flash {os.path.relpath(out, HERE)}')


if __name__ == '__main__':
    main()
