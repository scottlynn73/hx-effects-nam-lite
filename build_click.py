#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with the Click metronome block, for a hardware test.

usage: python3 build_click.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--no-check] [--diag-nam-knobs]

--diag-nam-knobs  a diagnostic image: Click's kernel with NAM's eight knob records exactly (proven on
                  the unit), to tell a kernel fault from a knob-definition fault. The kernel then reads
                  NAM's words: Tempo = Input (0..1, so 20 BPM), Level = Mid, Accent = Model (1..12 dB),
                  Sound = Bass (0 = Click, else Beep), Subdivision = Treble (0 = 1/4, else 1/16).
                  Names, DSP cost and strip title are NAM's too, so only Entry 2's kernel differs
                  from build_effects.py's image (the browser shows "NAM A2 Lite").
                  Writes build/HX_Effects_v3.80.0_Click_diag.hxf.
--probe           a diagnostic kernel with Click's knobs that reports instance words by sound: the
                  speed shows DM(3)'s value (0/1/2/other -> 60/120/180/240 BPM), and each change in
                  any other non-knob instance word steps the sound Click -> Wood -> Beep (Tempo,
                  Subdivision and Sound ignored).
                  Writes build/HX_Effects_v3.80.0_Click_probe.hxf.

Click takes over the mono Mod/Chorus Echo delay (Delay > Mono > "Click"; the stereo Mod/Chorus Echo
and every other delay stay), so the unit draws it with ordinary knob pages. Its DSP graph is a copy of
the 2048 IR block's (one in, one out) with the convolution replaced by primitive 0x9c75. (The first
builds took over the 1024 IR block as NAM does; HX draws an IR block's own page layout, with knob 1 as
the IR selector, which made a metronome unusable.)

  kernel  effects/metronome/sharc/click_kernel.asm (checked bit for bit against the C reference in
          the simulator first, unless --no-check)
  knobs   Time (Mod/Chorus Echo's own: ms, or a note value synced to tap tempo / the global BPM;
          default synced, 1/4), Beats/Bar (2/4..5/4), Accent (Off, 1..12 dB), Sound (Click, Wood,
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
TAKEOVER = 'HD2_DelayModChorusEchoMono'          # the stock model Click becomes
IR_TAKEOVER = 'HD2_ImpulseResponse1024Mono'      # the diagnostic build's (NAM's) target
CLONE = 'HD2_ImpulseResponse2048Mono'
NAME, DISPLAY, SHORT = 'HD2_ClickMetronome', 'Click', 'Click'
STRIP_TITLE = None                               # the IR category's title is left alone
# Measured worst case 1,361 of ~150,000 cycles per call (0.9 %); stock costs look like hundredths
# of a per cent, so ~91. Declared with a 3x margin.
DSP_COST = 300

# Knob: (slot, pid = instance word, template model, template param, display, short, kind, range, default)
LIST = 'list'
CLICK_PARAMS = (
    # slot 1: Time (see SYNC_PARAMS), Mod/Chorus Echo's own, with its tempo sync
    (2, 6,  'HD2_DelayMultiPassMono', 'Pattern', 'Beats/Bar', 'Beats', LIST,
     {2: '2/4', 3: '3/4', 4: '4/4', 5: '5/4'}, 4),
    (3, 7,  'HD2_TremoloPatternMono', 'Step1', 'Accent', 'Accent', LIST,
     {k: ('Off' if k == 0 else f'{k} dB') for k in range(13)}, 6),
    (4, 8,  'HD2_FM4SynthOMatic', 'Wave', 'Sound', 'Sound', LIST, {0: 'Click', 1: 'Wood', 2: 'Beep'}, 0),
    # Level on NAM's ChVol record (proven to reach the kernel); on Chorus 'Mix' it never arrived
    (5, 9,  'HD2_AmpLine6Clarity', 'ChVol', 'Level', 'Level', 'percent', (0.0, 1.0), 0.5),
    (6, 10, 'HD2_DelayCrissCrossMono', 'Shape', 'Subdivision', 'Subdiv', LIST,
     {1: '1/4', 2: '1/8', 3: '1/8T', 4: '1/16'}, 1),
)
# The tempo: a delay's Time knob and its tempo sync, copied from Mod/Chorus Echo (the model Click
# replaces). HX shows Time in ms, or as a note value (pressing the knob toggles Tempo Sync), and with
# sync on it follows tap tempo and the global BPM. Stock delays compute the effective time in their
# DSP parameter map (nodes 0x2a and 0x54); Click's map copies those two nodes and sends their output,
# the beat length in seconds, to the kernel's word 5. The slot links (coupledIndex: the knob's other
# half; toggleSelectIndex: the sync switch) are renumbered for Click's slots.
SYNC_MODEL = 'HD2_DelayModChorusEchoMono'
TIME_SLOT, SELECT_SLOT, SYNC_SLOT, TIME_PID = 1, 7, 8, 5
SYNC_PARAMS = (   # slot, stock name, role, (min, max, default) or None to keep, metadata overrides
    (TIME_SLOT, 'Time', 'time', (0.1, 4.0, 0.5), {'coupledIndex': str(SELECT_SLOT), 'toggleSelectIndex': str(SYNC_SLOT)}),
    (SELECT_SLOT, 'SyncSelect1', 'select', (1, 19, 6), {'coupledIndex': str(TIME_SLOT), 'toggleSelectIndex': str(SYNC_SLOT)}),
    (SYNC_SLOT, 'TempoSync1', 'sync', (0, 0, 1), {}),                  # default on: follow tap tempo, 1/4
)
SYNC_NODES = {'select_time': (0x2a, 4, [0, 0]),                         # op, state words, data (stock)
              'pick_time': (0x54, 9, [0x39b78034, 0x41000000])}        # (0.00035 s, 8 s)


def f2u(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def _state_of(pa, e3, info, m, pname):
    S, d = info['strings'], m['words']
    for k in range(d[6]):
        _, _, ni, _, _ = struct.unpack_from('<5I', e3, d[10] + 20 * k)
        if S[ni].split('.')[0] == pname + 'State':
            return S[ni]
    raise SystemExit(f'{m["name"]} has no state for {pname}')


def click_params(pa, e3, info):
    """Like patch_amp.nam_params: per knob the template's record (type, state) with our range,
    default and display metadata; the Time/sync trio copied whole from Mod/Chorus Echo. Each has a
    role for click_host_blob: 'direct' (written to its pid), 'time', 'select', 'sync'."""
    S = info['strings']
    out = []
    sm = pa.find_model(info, SYNC_MODEL)
    for slot, pname, role, rng, over in SYNC_PARAMS:
        p = next(p for p in sm['params'] if p['name'] == pname)
        raw = list(struct.unpack_from('<5I3I', e3, p['off']))
        raw[4] = slot
        if p['type'] == 3:
            raw[5], raw[6], raw[7] = f2u(rng[0]), f2u(rng[1]), f2u(rng[2])
        else:
            raw[5], raw[6], raw[7] = rng
        meta = []
        for k in range(raw[0]):                       # the stock metadata records, in order
            ks, kt, kv = struct.unpack_from('<3I', e3, raw[1] + 12 * k)
            key = S[ks]
            meta.append((key, kt, over.get(key, S[kv] if kt == 7 else kv)))
        assert set(over) <= {k for k, _, _ in meta}, f'{pname}: no field to override'
        out.append({'slot': slot, 'pid': None, 'role': role, 'name': pname, 'type': p['type'],
                    'op': pa.NAM_INPUT_OP[p['type']], 'raw': raw, 'meta': meta,
                    'state': _state_of(pa, e3, info, sm, pname), 'default_word': raw[7]})
    for slot, pid, mname, pname, disp, short, kind, rng, dflt in CLICK_PARAMS:
        m = pa.find_model(info, mname)
        p = next(p for p in m['params'] if p['name'] == pname)
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
        out.append({'slot': slot, 'pid': pid, 'role': 'direct', 'name': pname, 'type': p['type'],
                    'op': pa.NAM_INPUT_OP[p['type']], 'raw': raw, 'meta': meta,
                    'state': _state_of(pa, e3, info, m, pname), 'default_word': raw[7]})
    out.sort(key=lambda p: p['slot'])
    assert [p['slot'] for p in out] == list(range(1, len(out) + 1)), 'slots must run 1..n'
    assert len({p['name'] for p in out}) == len(out), 'two knobs share a parameter name'
    return out


def click_host_blob(comp_id, params, extra=()):
    """patch_amp.nam_host_blob's layout (see there), with Mod/Chorus Echo's tempo-sync step in the
    parameter map: input k for params[k]; a writer per 'direct' knob (member 1, its pid);
    sync -> 0x2a port 0, select -> 0x2a port 2; time -> 0x54 port 0, 0x2a -> 0x54 port 1;
    0x54 -> a writer of word TIME_PID. Header sizes as nam_host_blob documents (and as the stock
    Mod/Chorus Echo map has them)."""
    n = len(params)
    extra = list(extra)
    members = sorted({m for m, _, _, _ in extra if m >= 0})
    role = {p['role']: k for k, p in enumerate(params) if p['role'] != 'direct'}
    nodes, data, edges = [], [], []                    # node: [op, n_out, state, data words, is_input]
    for p in params:                                    # inputs 0 .. n-1
        nodes.append([p['op'], 1, 2, [], 1])
    writers = []                                        # (node, pid, default word)
    for k, p in enumerate(params):
        if p['role'] == 'direct':
            nodes.append([1, 0, 3, [0x0e, p['pid'], 1], 0])
            edges.append((k, len(nodes) - 1, 0, 0))
            writers.append((len(nodes) - 1, p['pid'], p['default_word']))
    op, st, dd = SYNC_NODES['select_time']
    nodes.append([op, 1, st, dd, 0]); n_sel = len(nodes) - 1
    op, st, dd = SYNC_NODES['pick_time']
    nodes.append([op, 1, st, dd, 0]); n_pick = len(nodes) - 1
    nodes.append([1, 0, 3, [0x0e, TIME_PID, 1], 0]); n_tw = len(nodes) - 1
    edges += [(role['sync'], n_sel, 0, 0), (role['select'], n_sel, 0, 2),
              (role['time'], n_pick, 0, 0), (n_sel, n_pick, 0, 1), (n_pick, n_tw, 0, 0)]
    writers.append((n_tw, TIME_PID, params[role['time']]['default_word']))

    a_off = 0x18
    data_start = a_off + 10 * len(nodes)
    rec, off = [], data_start
    for i, (op, nout, st, dd, inp) in enumerate(nodes):
        rec += [off if dd else data_start, 0, i, op, nout, st, len(dd), len(dd), inp, 0]
        if dd:
            data += dd
            off += len(dd)
    path_words = [data_start + (sum(len(nd[3]) for nd in nodes[:w])) for w, _, _ in writers]
    c_off = data_start + len(data)
    d_off = c_off + 4 * len(edges)
    e_off = d_off + 4 * n
    end = e_off + 4 * n
    nA, nC = len(nodes), len(edges)
    H = [sum(nd[2] for nd in nodes), nA, n + sum(nd[1] for nd in nodes) + n, nC + n + n, n, n]
    pm = [a_off, 0, c_off, 0, c_off, 0, d_off, 0, e_off, 0, end, 0] + H + [nA, 0, nC, n, n, 0]
    pm += rec + data
    for fr, to, fp, tp in edges:
        pm += [fr, to, fp, tp]
    for k, p in sorted(enumerate(params), key=lambda kp: kp[1]['slot']):
        pm += [k, k, p['slot'], 0]
    for k in range(n):
        pm += [k, k, k, 0]
    assert len(pm) == end

    path_of = {-1: 0x0c, 1: 0x0e}
    for i, m in enumerate(members):
        path_of[m] = 0x10 + 2 * i
    v0 = 0x10 + 2 * len(members)
    vals = [p['default_word'] for p in params] + [w for _, _, w in writers] + [v for _, _, v, _ in extra]
    tree = v0 + 2 * len(vals)
    pmo = tree + 4
    pin = pmo + len(pm)
    npin = n + len(writers) + len(extra)
    ini = pin + 4 * npin
    nini = len(writers) + npin
    sub = ini + 2 * nini
    b = [3, 2, tree, 1, ini, nini, pmo, len(pm), sub, 0, pin, npin]
    b += [1, 0, 1, 2]
    for m in members:
        b += [1, m + 1]
    for v in vals:
        b += [1, v]
    b += [0, comp_id, 0, 0]
    b += pm
    for k, p in enumerate(params):
        b += [0x0c, p['slot'], v0 + 2 * k, 1]
    for j, (_, pid, _) in enumerate(writers):
        b += [path_of[1], pid, v0 + 2 * (n + j), 2]
    for j, (m, pid, _, kind) in enumerate(extra):
        b += [path_of[m], pid, v0 + 2 * (n + len(writers) + j), kind]
    for w in path_words:
        b += [1, pmo + w]
    for k in range(npin):
        b += [1, pin + 4 * k]
    assert len(b) == sub
    return b


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
    probe = '--probe' in argv
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', 'HX_Effects_v3.80.0_Click_diag.hxf' if diag else
                     'HX_Effects_v3.80.0_Click_probe.hxf' if probe else 'HX_Effects_v3.80.0_Click.hxf')
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
    src, secs, syms, code_end, data = click_kernel.assemble(probe=probe)
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
    tgt = pa.find_model(info, IR_TAKEOVER if diag else TAKEOVER)
    params = pa.nam_params(e3, info) if diag else click_params(pa, e3, info)
    # diagnostic: everything but the kernel exactly as build_effects.py makes it (names, cost, title)
    name, display, cost_decl, title = ('HD2_AmpNAMLite', 'NAM A2 Lite', 2700, 'NAM / IR_2048') if diag else \
        (NAME, DISPLAY, DSP_COST, STRIP_TITLE)
    # Entry 3's new model copies the target's own metadata (category, subcategory, ...) except
    # for an IR target, where it copies the graph source's as NAM does
    meta_src, meta_set = (src_m, None) if diag else \
        (tgt, {'displayNameShort': SHORT, 'displayParamCount': str(len(params) - 2)})   # sync knobs share Time's

    # 2. Entry 4: the host graph (the 2048 IR block's, member 1 -> primitive 0x9c75)
    new_e4, blob, comp = pa.add_model_entry4(e4, src_m['blob_index'], params, 0,
                                             blob_fn=None if diag else click_host_blob)
    print(f'[+] Entry 4: host blob {blob} on composite {comp:#x}, a copy of {CLONE}\'s graph')

    # 3. Entry 2: Blob 0's buffer (the graph library grew) and Heap 6, as for NAM
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)

    # 4. Entry 3: the model, its descriptor copied over the takeover target's
    new_e3, new_id, _ = pa.add_model_entry3(e3, meta_src, name, display, blob, params, meta_set=meta_set)
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
    print(f'[+] Entry 3: {tgt["name"]} (model {tgt["model_id"]}) now carries {display}: '
          f'{len(params)} knobs{" (NAM\'s records, diagnostic)" if diag else ""}')

    # 5. Entry 0: cost, counts, names, strip title
    new_e0, pid, cost, hits = pa.takeover_entry0_effects(e0, tgt['words'][2], display, short_name=display,
                                                        dsp_cost=cost_decl, n_params=len(params), strip_title=title,
                                                        n_display=None if diag else len(params) - 2)
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
