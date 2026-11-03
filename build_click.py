#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with the Click metronome block (instead of NAM), for a hardware test.

usage: python3 build_click.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--no-check] [--diag-nam-knobs]

--diag-nam-knobs  a diagnostic image: Click's kernel with NAM's eight knob records exactly (proven on
                  the unit), to tell a kernel fault from a knob-definition fault. The kernel then reads
                  NAM's words: Tempo = Input (0..1, so 20 BPM), Level = Mid, Accent = Model (1..12 dB),
                  Sound = Bass (0 = Click, else Beep), Subdivision = Treble (0 = 1/4, else 1/16).
                  Names, DSP cost and strip title are NAM's too, so only Entry 2's kernel differs
                  from build_effects.py's image (the browser shows "NAM A2 Lite").
                  Writes build/HX_Effects_v3.80.0_Click_diag.hxf.

The same takeover as build_effects.py: Click becomes the 1024-sample IR block (IR > Single > "Click";
the 2048 IR block stays), on a copy of the 2048 IR block's graph with its convolution replaced by
primitive 0x9c75. Only the kernel and the knobs differ:

  kernel  effects/metronome/sharc/click_kernel.asm (checked bit for bit against the C reference in
          the simulator first, unless --no-check)
  knobs   Tempo (20..300 BPM), Beats/Bar (2/4..5/4), Accent (Off, 1..12 dB), Sound (Click, Wood,
          Beep), Level (0..100 %), Subdivision (1/4, 1/8, 1/8T, 1/16)

This image has no NAM block. Rebuild with build_effects.py and flash that to go back.
"""
import hashlib
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools')
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, 'sharc'))
sys.path.insert(0, os.path.join(HERE, 'effects', 'metronome', 'sharc'))

STOCK_MD5 = '7c2ebdf1bffb6bcc5f89dda97f91e40c'
TAKEOVER = 'HD2_ImpulseResponse1024Mono'
CLONE = 'HD2_ImpulseResponse2048Mono'
NAME, DISPLAY, SHORT = 'HD2_ClickMetronome', 'Click', 'Click'
STRIP_TITLE = 'Click / IR_2048'
# Measured worst case 1,361 of ~150,000 cycles per call (0.9 %); stock costs look like hundredths
# of a per cent, so ~91. Declared with a 3x margin.
DSP_COST = 300

# Knob: (slot, pid = instance word, template model, template param, display, short, kind, range, default)
LIST = 'list'
CLICK_PARAMS = (
    # Tempo as a list: a float with the 'tenths' display (the EQ's Q) froze the unit's controls
    (1, 5,  'HD2_DelayAdriaticDelayMono', 'BBD Size', 'Tempo', 'Tempo', LIST,
     {k: f'{k} BPM' for k in range(20, 301)}, 120),
    (2, 6,  'HD2_DelayMultiPassMono', 'Pattern', 'Beats/Bar', 'Beats', LIST,
     {2: '2/4', 3: '3/4', 4: '4/4', 5: '5/4'}, 4),
    (3, 7,  'HD2_TremoloPatternMono', 'Step1', 'Accent', 'Accent', LIST,
     {k: ('Off' if k == 0 else f'{k} dB') for k in range(13)}, 6),
    (4, 8,  'HD2_FM4SynthOMatic', 'Wave', 'Sound', 'Sound', LIST, {0: 'Click', 1: 'Wood', 2: 'Beep'}, 0),
    (5, 9,  'HD2_ChorusMono', 'Mix', 'Level', 'Level', 'percent', (0.0, 1.0), 0.5),
    (6, 10, 'HD2_DelayCrissCrossMono', 'Shape', 'Subdivision', 'Subdiv', LIST,
     {1: '1/4', 2: '1/8', 3: '1/8T', 4: '1/16'}, 1),
)


def f2u(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def click_params(pa, e3, info):
    """Like patch_amp.nam_params: per knob the template's record (type, state) with our range,
    default and display metadata."""
    S = info['strings']
    out = []
    for slot, pid, mname, pname, disp, short, kind, rng, dflt in CLICK_PARAMS:
        m = pa.find_model(info, mname)
        p = next(p for p in m['params'] if p['name'] == pname)
        d = m['words']
        st = None
        for k in range(d[6]):
            _, _, ni, _, _ = struct.unpack_from('<5I', e3, d[10] + 20 * k)
            if S[ni].split('.')[0] == pname + 'State':
                st = S[ni]
        assert st, f'{mname} has no state for {pname}'
        raw = list(struct.unpack_from('<5I3I', e3, p['off']))
        raw[4] = slot
        if kind == LIST:
            assert p['type'] == 2, f'{mname}.{pname} is not an integer parameter'
            raw[5], raw[6], raw[7] = min(rng), max(rng), dflt
            meta = [('displayType', 7, 'list'), ('displayName', 7, disp), ('displayNameShort', 7, short)]
            meta += [(str(k), 7, v) for k, v in sorted(rng.items())]
        else:
            assert p['type'] == 3, f'{mname}.{pname} is not a float parameter'
            raw[5], raw[6], raw[7] = f2u(rng[0]), f2u(rng[1]), f2u(dflt)
            meta = [('displayType', 7, kind), ('displayName', 7, disp), ('displayNameShort', 7, short)]
        out.append({'slot': slot, 'pid': pid, 'name': pname, 'type': p['type'], 'op': pa.NAM_INPUT_OP[p['type']],
                    'raw': raw, 'meta': meta, 'state': st, 'default_word': raw[7]})
    assert len({p['name'] for p in out}) == len(out), 'two knobs share a parameter name'
    return out


def run(*args):
    print('$ ' + ' '.join(os.path.relpath(a, HERE) if os.path.isabs(a) else a for a in args[1:]), flush=True)
    r = subprocess.run(list(args), cwd=HERE, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(f'build_click.py: step failed ({os.path.relpath(args[1], HERE)})')
    return r.stdout


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        sys.exit(__doc__)
    stock = os.path.abspath(argv.pop(0)) if argv and not argv[0].startswith('-') else \
        os.path.join(HERE, 'firmware', 'HX_Effects_v3.80.0_0xd97239907.hxf')
    if not os.path.isfile(stock):
        sys.exit(f'{stock}: not found (see README.md, "Getting the stock firmware").')
    md5 = hashlib.md5(open(stock, 'rb').read()).hexdigest()
    if md5 != STOCK_MD5:
        sys.exit(f'{stock}: MD5 {md5}, not the HX Effects 3.80.0 firmware (expected {STOCK_MD5}).')
    diag = '--diag-nam-knobs' in argv
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', 'HX_Effects_v3.80.0_Click_diag.hxf' if diag else 'HX_Effects_v3.80.0_Click.hxf')
    build = os.path.join(HERE, 'build')
    os.makedirs(build, exist_ok=True)
    image = os.path.join(build, 'click.l6ia')

    # 1. the kernel, checked against the C reference first
    if '--no-check' not in argv:
        lib = os.path.join(HERE, 'effects', 'out', 'libfx.so')
        r = subprocess.run(['make', '-s', '-C', os.path.join(HERE, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode or not os.path.exists(lib):
            sys.exit(f'build_click.py: could not build {lib}:\n{r.stderr}')
        run(sys.executable, os.path.join(HERE, 'effects', 'metronome', 'sharc', 'click_kernel.py'), '--check')
    import click_kernel
    src, secs, syms, code_end, data = click_kernel.assemble()
    open(os.path.join(build, 'click.asm'), 'w').write(src)

    os.environ['NAM_DEVICE'] = 'effects'
    import l6ia
    import patch_amp as pa

    l6ia_bytes, _ = pa.load_l6ia_from_any(stock)
    assert pa.select_device(l6ia_bytes) is pa.EFFECTS_DSP, 'not the HX Effects firmware'
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    info = pa.parse_entry3_full(e3)
    src_m = pa.find_model(info, CLONE)
    tgt = pa.find_model(info, TAKEOVER)
    params = pa.nam_params(e3, info) if diag else click_params(pa, e3, info)
    # diagnostic: everything but the kernel exactly as build_effects.py makes it (names, cost, title)
    name, display, cost_decl, title = ('HD2_AmpNAMLite', 'NAM A2 Lite', 2700, 'NAM / IR_2048') if diag else \
        (NAME, DISPLAY, DSP_COST, STRIP_TITLE)

    # 2. Entry 4: the host graph (the 2048 IR block's, member 1 -> primitive 0x9c75)
    new_e4, blob, comp = pa.add_model_entry4(e4, src_m['blob_index'], params, 0)
    print(f'[+] Entry 4: host blob {blob} on composite {comp:#x}, a copy of {CLONE}\'s graph')

    # 3. Entry 2: Blob 0's buffer (the graph library grew) and Heap 6, as for NAM
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)

    # 4. Entry 3: the model, its descriptor copied over the takeover target's
    new_e3, new_id, _ = pa.add_model_entry3(e3, src_m, name, display, blob, params)
    new_e3 = bytearray(new_e3)
    ms = pa.parse_entry3_full(bytes(new_e3))['models']
    d_new = struct.unpack_from('<14I', new_e3, ms[new_id]['off'])
    d_tgt = list(struct.unpack_from('<14I', new_e3, ms[tgt['model_id']]['off']))
    for k in (0, 1, 6, 7, 10, 11, 13):
        d_tgt[k] = d_new[k]
    struct.pack_into('<14I', new_e3, ms[tgt['model_id']]['off'], *d_tgt)
    new_e3 = bytes(new_e3)
    chk = pa.parse_entry3_full(new_e3)['models'][tgt['model_id']]
    assert chk['displayName'] == display and chk['blob_index'] == blob and len(chk['params']) == len(params)
    for p, q in zip(sorted(chk['params'], key=lambda x: x['slot']), sorted(params, key=lambda x: x['slot'])):
        assert (p['name'], p['type'], p['slot']) == (q['name'], q['type'], q['slot'])
    print(f'[+] Entry 3: {TAKEOVER} (model {tgt["model_id"]}) now carries {display}: '
          f'{len(params)} knobs{" (NAM\'s records, diagnostic)" if diag else ""}')

    # 5. Entry 0: cost, counts, names, strip title
    new_e0, pid, cost, hits = pa.takeover_entry0_effects(e0, tgt['words'][2], display, short_name=display,
                                                        dsp_cost=cost_decl, n_params=len(params), strip_title=title)
    print(f'[+] Entry 0: preset_id={pid} kept; dsp_cost={cost}; browser slots {hits}; strip title "{title}"')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: new_e0, 2: l6ia.swap32(e2_raw), 3: new_e3, 4: new_e4})

    # 6. Entry 2: the kernel and its data in, primitive 0x9c75 hooked to it
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked = pa._scan_e2_injected(e2_raw)
    assert used_pm_end <= click_kernel.CODE, f'Entry 2 already has code up to {used_pm_end:#x}'
    entry_addr = syms['CLICK_ENTRY']
    ldr = []
    for s in secs:
        if s.kind == 'pm':
            assert s.addr + len(s.words) <= 0x0c5554, 'kernel past the Block 2 tail'
            ldr += pa.pack_init_l48(s.addr, s.words)
        elif s.kind == 'dm':
            ldr += pa.pack_init_l32(s.addr, s.words)
    table, _ = pa.sharc_prim_table(e2_raw)
    prim_id, prim_addr = next((p, table[p]) for p in pa.UNUSED_SHARC_PRIM_IDS if p in table and table[p] not in hooked)
    assert prim_id == 0x9c75, f'expected primitive 0x9c75 free, got {prim_id:#x}'
    template = pa.sharc_prim_record(e2_raw, 0x822)
    ldr += pa.pack_init_l32(prim_addr, [prim_id] + list(template[1:5]) + [entry_addr, 0x91, 0x0d])
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {2: l6ia.swap32(pa.inject_sharc_ldr_blocks(e2_raw, ldr))})
    print(f'[+] Entry 2: kernel at PM {entry_addr:#x}..{code_end:#x}, data {data[0]:#x}..{data[1]:#x}, '
          f'primitive {prim_id:#06x} @ {prim_addr:#x} hooked to it')
    open(image, 'wb').write(l6ia_bytes)

    # 7. verify and pack
    report = run(sys.executable, os.path.join(TOOLS, 'l6ia_verify.py'), image)
    if 'ALL OK' not in report:
        sys.exit('build_click.py: the image failed its checksum check')
    run(sys.executable, os.path.join(TOOLS, 'hxf.py'), 'pack', image, out, '--donor', stock)
    print(f'\nDone: {out}\nThis image has Click instead of NAM. Flash: python3 tools/flash.py flash {os.path.relpath(out, HERE)}')


if __name__ == '__main__':
    main()
