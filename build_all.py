#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with NAM A2 Lite, Click and Geiger in one image.

usage: python3 build_all.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--with commander[,corrupt]] [--no-check]

  NAM A2 Lite   as build_nam_click.py, but with 2 slots (two NAM blocks at once; a third passes its
                input through) instead of 3, which frees Block 3 for Geiger, and its DDR2 blocks at
                0x296400 (the Blob 0 buffer holds three host graphs: 0x7a000 words). IR > Single.
  Click         as build_nam_click.py (Delay > Mono, the mono Mod/Chorus Echo's slot), primitive 0x0128,
                in the top of Block 3.
  Geiger        bit crusher / sample-rate reducer / 16-curve waveshaper (effects/geiger), taking over
                the mono Megaphone (Distortion > Mono > "Geiger"; the stereo Megaphone stays), primitive
                0x012e (zero uses in the stock graphs), code and data in the Block 3 space between
                NAM's slots and Click's data.

  --with commander          adds Commander (square-wave octave fuzz, effects/commander) on the mono
                            Xenomorph Fuzz (Distortion > Mono), primitive 0x0100;
  --with commander,corrupt  and Corrupt (pitch-tracking square synth, effects/corrupt) on Octave Fuzz
                            (Distortion > Mono), primitive 0x0838.
                With either, NAM keeps 2 slots but puts its d >= 17 rings in DDR2 too (nam_multi.py
                --far-d 17), which frees Block 3 for the extra kernels; the Blob 0 buffer grows to
                0x7b000 words (five host graphs) and NAM's DDR2 slots move up to 0x297400. Geiger,
                Commander and Corrupt are packed in that order between NAM's Block 3 end and Click's data.
                Output build/HX_Effects_v3.80.0_All_Commander[_Corrupt].hxf, manifest
                build/all_commander[_corrupt]_manifest.json.

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
for p in ('tools', 'tools/sharc', 'effects/metronome/sharc', 'effects/geiger/sharc', 'effects/common',
          'effects/commander/sharc', 'effects/corrupt/sharc', 'effects/probe/sharc'):
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


COMMANDER_TAKEOVER, CORRUPT_TAKEOVER = 'HD2_DistXenomorphFuzzMono', 'HD2_DM4OctaveFuzz'
COMMANDER_PARAMS = (   # as GEIGER_PARAMS; the kernel reads words 5..11 and 13 (effects/commander/sharc)
    (1, 5,  'HD2_AmpLine6Clarity', 'Drive', 'Fuzz', 'Fuzz', 'percent', (0.0, 1.0), 0.7),
    (2, 6,  'HD2_AmpLine6Clarity', 'Bass', 'Sub -1 Oct', 'Sub1', 'percent', (0.0, 1.0), 0.5),
    (3, 7,  'HD2_AmpLine6Clarity', 'Mid', 'Sub -2 Oct', 'Sub2', 'percent', (0.0, 1.0), 0.0),
    (4, 8,  'HD2_AmpLine6Clarity', 'Treble', 'Octave Up', 'OctUp', 'percent', (0.0, 1.0), 0.0),
    (5, 9,  'HD2_AmpLine6Clarity', 'Presence', 'Tone', 'Tone', 'knob', (0.0, 1.0), 0.5),
    (6, 10, 'HD2_AmpLine6Clarity', 'ChVol', 'Output', 'Output', 'db', (-36.0, 12.0), -6.0),
    (7, 11, 'HD2_TremoloPatternMono', 'Step1', 'Gate', 'Gate', LIST,
     {k: ('Off' if k == 0 else f'{6 * k - 90} dB') for k in range(11)}, 3),
    (8, 13, 'HD2_DelayCrissCrossMono', 'Shape', 'Dry', 'Dry', LIST, {k: f'{10 * k}%' for k in range(11)}, 0),
)
CORRUPT_PARAMS = (
    (1, 5,  'HD2_AmpLine6Clarity', 'Drive', 'Square', 'Square', 'percent', (0.0, 1.0), 0.0),
    (2, 6,  'HD2_AmpLine6Clarity', 'Bass', 'Master', 'Master', 'percent', (0.0, 1.0), 0.8),
    (3, 7,  'HD2_AmpLine6Clarity', 'Mid', 'Sub', 'Sub', 'percent', (0.0, 1.0), 0.4),
    (4, 8,  'HD2_AmpLine6Clarity', 'Treble', 'Glide', 'Glide', 'knob', (0.0, 1.0), 0.2),
    (5, 9,  'HD2_AmpLine6Clarity', 'Presence', 'Tone', 'Tone', 'knob', (0.0, 1.0), 0.6),
    (6, 10, 'HD2_AmpLine6Clarity', 'ChVol', 'Output', 'Output', 'db', (-36.0, 12.0), -6.0),
    (7, 11, 'HD2_DelayMultiPassMono', 'Pattern', 'Root', 'Root', LIST, {0: '-2 Oct', 1: '-1 Oct', 2: 'Unison', 3: '+1 Oct'}, 2),
    (8, 13, 'HD2_FM4SynthOMatic', 'Wave', 'Harmonic', 'Harm', LIST,
     {1: '1x Root', 2: '2x Octave', 3: '3x Fifth', 4: '4x 2 Oct', 5: '5x Third', 6: '6x Fifth', 7: '7x Flat 7', 8: '8x 3 Oct'}, 1),
)
# the Block 3 kernels after NAM, in packing order: model, name, display, Entry 0 cost, primitive, knobs, entry symbol
EFFECTS = {
    'geiger': dict(takeover=GEIGER_TAKEOVER, name=GEIGER_NAME, display=GEIGER_DISPLAY, cost=GEIGER_COST, prim=GEIGER_PRIM,
                   params=GEIGER_PARAMS, entry='GEIGER_ENTRY'),
    'commander': dict(takeover=COMMANDER_TAKEOVER, name='HD2_DistCommander', display='Commander', cost=700, prim=0x0100,
                      params=COMMANDER_PARAMS, entry='COMMANDER_ENTRY'),   # measured worst 3,441 cycles of ~150,000 (2.3 %)
    'corrupt': dict(takeover=CORRUPT_TAKEOVER, name='HD2_DistCorrupt', display='Corrupt', cost=700, prim=0x0838,
                    params=CORRUPT_PARAMS, entry='CORRUPT_ENTRY'),         # measured worst 3,545
    # --probe: a diagnostic on Geiger's host instead of Geiger (effects/probe/sharc/probe_kernel.asm)
    'probe': dict(takeover=GEIGER_TAKEOVER, name='HD2_DistProbe', display='Probe', cost=300, prim=GEIGER_PRIM,
                  params=GEIGER_PARAMS, entry='PROBE_ENTRY'),
}
BLOB0_WORDS_5 = 0x7B000                # five host graphs
NAM_FAR_D_EXTRA = 17                   # NAM's layout when the extra kernels are in


class Kernel:
    """One Block 3 kernel behind one interface: Geiger's own module, or a kernel_rig Spec."""

    def __init__(self, key):
        self.key = key
        if key == 'geiger':
            import geiger_kernel as m
            self.places = m.PLACES
            self._asm = m.assemble
            self._check = lambda sec, pl: m.check(sec, pl)
        elif key == 'commander_corrupt':                 # both in one kernel, two entry points
            import commander_corrupt_kernel as m
            self.places = m.SPEC.places
            self._asm = m.SPEC.assemble
            self._check = lambda sec, pl: m.check(sec, pl)
        else:
            m = __import__(f'{key}_kernel')
            self.places = m.SPEC.places
            self._asm = m.SPEC.assemble
            self._check = lambda sec, pl: m.check(sec, pl)
        self.place = None

    def measure(self, data0):
        """(data end, instructions) with the data at data0."""
        self.places['probe'] = (0xC4EF8, 0xC5554, data0)
        _, secs, _, end, data = self._asm('probe')
        return data[1], end - 0xC4EF8

    def set_place(self, code48, code48_end, data0):
        self.place = f'b3{self.key[0]}' if self.key == 'geiger' else 'b3'
        self.places[self.place] = (code48, code48_end, data0)

    def assemble(self):
        return self._asm(self.place)

    def check(self, seconds):
        return self._check(seconds, self.place)


def append_blob0(e4, words):
    """Entry 4 with `words` appended to Blob 0 (the blobs after it move up; stock blobs stay)."""
    w4 = list(struct.unpack('<%dI' % (len(e4) // 4), e4))
    nblobs, dir_off = w4[2], w4[3]
    b0_len, b0_off = w4[dir_off], w4[dir_off + 1]
    end = b0_off + b0_len
    assert w4[4] == b0_off and all(w4[dir_off + 2 * k + 1] + w4[dir_off + 2 * k] <= dir_off or
                                   w4[dir_off + 2 * k + 1] >= end for k in range(1, nblobs))
    for k in range(1, nblobs):
        if w4[dir_off + 2 * k + 1] >= end:
            w4[dir_off + 2 * k + 1] += len(words)
    w4[dir_off] = b0_len + len(words)
    w4 = w4[:end] + list(words) + w4[end:]
    w4[5] = len(w4)
    return struct.pack('<%dI' % len(w4), *w4), b0_len


def b3_normal(a48):
    """The first normal (32-bit) word at or after 48-bit address a48 in Block 3."""
    return 0xE0000 + ((a48 - 0xE0000) * 3 + 1) // 2


def b3_code48(normal):
    """The first even 48-bit address at or after normal word `normal` in Block 3."""
    return 0xE0000 + (((normal - 0xE0000) * 2 + 2) // 3 + 1 & ~1)


def ldr_l32(pa, addr, words, zero_fill):
    """LDR blocks loading `words` at `addr`: one INIT_L32, or, with zero_fill, runs of 8+ zero words as
    ZERO_LDATA blocks (tag 1: a 3-word header, no payload; the stock boot stream has 81 of them) and the
    rest as INIT_L32. Entry 2 must stay within its 512 KiB partition."""
    if not zero_fill:
        return pa.pack_init_l32(addr, words)
    out, i, n = [], 0, len(words)
    while i < n:
        j = i
        while j < n and words[j] == 0:
            j += 1
        if j - i >= 8 or (j == n and j > i):
            out += [1, j - i, addr + i]
            i = j
            continue
        k = i
        while k < n:                                  # up to the next run of 8+ zeros
            if words[k] == 0:
                z = k
                while z < n and words[z] == 0:
                    z += 1
                if z - k >= 8 or z == n:
                    break
                k = z
            else:
                k += 1
        out += pa.pack_init_l32(addr + i, words[i:k])
        i = k
    return out


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
    extras = argv[argv.index('--with') + 1].split(',') if '--with' in argv else []
    if extras not in ([], ['commander'], ['commander', 'corrupt']):
        sys.exit('build_all.py: --with takes commander, or commander,corrupt')
    probe = '--probe' in argv
    if probe and extras:
        sys.exit('build_all.py: --probe goes alone')
    first = 'probe' if probe else 'geiger'
    fx = [first] + extras                                # the models after NAM and Click
    # the Block 3 kernels after NAM, in packing order: Commander and Corrupt together share one kernel
    blocks = [first] + (['commander_corrupt'] if 'corrupt' in extras else extras)
    entries_of = {k: [k] for k in blocks}
    entries_of['commander_corrupt'] = ['commander', 'corrupt']
    stock = os.path.abspath(argv.pop(0)) if argv and not argv[0].startswith('-') else \
        os.path.join(HERE, 'firmware', 'HX_Effects_v3.80.0_0xd97239907.hxf')
    if not os.path.isfile(stock) or hashlib.md5(open(stock, 'rb').read()).hexdigest() != STOCK_MD5:
        sys.exit(f'{stock}: missing or not the HX Effects 3.80.0 firmware (MD5 {STOCK_MD5}).')
    suffix = '_Probe' if probe else ''.join('_' + k.capitalize() for k in extras)
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', f'HX_Effects_v3.80.0_All{suffix}.hxf')
    build = os.path.join(HERE, 'build')
    os.makedirs(build, exist_ok=True)
    nam_asm = os.path.join(build, 'nam_lite_2slots.asm' if not extras else f'nam_lite_2slots_fd{NAM_FAR_D_EXTRA}.asm')
    image = os.path.join(build, f'all{suffix.lower()}.l6ia')
    manifest_path = os.path.join(build, f'all{suffix.lower()}_manifest.json')
    blob0_words = BLOB0_WORDS_5 if extras else bnc.BLOB0_WORDS_ALL
    sdr_base = bnc.BLOB0_BASE + blob0_words            # NAM's DDR2 slots just above the Blob 0 buffer
    env = dict(os.environ, NAM_DEVICE='effects', NAM_SDR_BASE=hex(sdr_base))
    check = '--no-check' not in argv
    run = bnc.run

    # 1. the kernels: NAM, then Geiger (and the extras) packed between NAM's Block 3 end and Click's data
    far = ['--far-d', str(NAM_FAR_D_EXTRA)] if extras else []
    log = run(sys.executable, be.KERNEL, '-o', nam_asm, '--slots', str(NAM_SLOTS), *far, *(['--check'] if check else []), env=env)
    m = re.search(r'block 3: (0x[0-9a-f]+)\.\.(0x[0-9a-f]+)', log)
    nam_b3 = (int(m.group(1), 16), int(m.group(2), 16))
    import click_kernel
    click_data0 = click_kernel.PLACES['b3'][2]
    code48_limit = 0xE0000 + (click_data0 - 0xE0000) * 2 // 3
    ks = {k: Kernel(k) for k in blocks}
    cursor = (nam_b3[1] + 0xF) & ~0xF
    for k in blocks:
        data_end, n_code = ks[k].measure(cursor)
        code48 = b3_code48(data_end)
        ks[k].set_place(code48, code48_limit, cursor)
        cursor = (b3_normal(code48 + n_code + (n_code & 1)) + 0xF) & ~0xF   # code loads in pairs
    if cursor > click_data0 + 0xF:
        sys.exit(f'build_all.py: {", ".join(blocks)} do not fit between NAM ({nam_b3[1]:#x}) and Click ({click_data0:#x}): '
                 f'they need to {cursor:#x}')
    if check:
        r = subprocess.run(['make', '-s', '-C', os.path.join(HERE, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'build_all.py: could not build effects/out/libfx.so:\n{r.stderr}')
        run(sys.executable, os.path.join(HERE, 'effects', 'metronome', 'sharc', 'click_kernel.py'), '--check', '--place', 'b3')
        for k in blocks:
            try:
                ks[k].check(0.25)
            except AssertionError as ex:
                sys.exit(f'build_all.py: {k} check failed: {ex}')

    os.environ['NAM_DEVICE'] = 'effects'
    import l6ia
    import patch_amp as pa
    import sasm

    l6ia_bytes, _ = pa.load_l6ia_from_any(stock)
    assert pa.select_device(l6ia_bytes) is pa.EFFECTS_DSP
    D = pa.EFFECTS_DSP
    assert D.HEAP6[0] - D.BLOB0_WORDS == bnc.BLOB0_BASE
    assert sdr_base + NAM_SLOTS * 0x5000 <= D.HEAP6[1]
    D.BLOB0_MAX_WORDS = blob0_words
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    info = pa.parse_entry3_full(e3)
    clone = pa.find_model(info, be.CLONE)
    targets = {'nam': pa.find_model(info, be.TAKEOVER), 'click': pa.find_model(info, bc.TAKEOVER)}
    params = {'nam': pa.nam_params(e3, info), 'click': bc.click_params(pa, e3, info)}
    for k in fx:
        targets[k] = pa.find_model(info, EFFECTS[k]['takeover'])
        params[k] = knob_params(pa, e3, info, EFFECTS[k]['params'])

    # 2. Entry 4: the host graphs (copies of the 2048 IR block's), each on its own primitive
    e4n, b_n, c_n = pa.add_model_entry4(e4, clone['blob_index'], params['nam'], 0, prim_id=NAM_PRIM)
    e4n, b_c, c_c = pa.add_model_entry4(e4n, clone['blob_index'], params['click'], 0, blob_fn=bc.click_host_blob, prim_id=CLICK_PRIM)
    blobs, comps = {'nam': b_n, 'click': b_c}, {'nam': c_n, 'click': c_c}
    for k in fx:
        e4n, blobs[k], comps[k] = pa.add_model_entry4(e4n, clone['blob_index'], params[k], 0, prim_id=EFFECTS[k]['prim'])
    print('[+] Entry 4: ' + ', '.join(f'{k} blob {blobs[k]} on {comps[k]:#x}' for k in blobs))
    if probe:                                            # the magic word and the routine at Blob 0's tail
        import probe_kernel
        w4 = struct.unpack('<%dI' % (len(e4n) // 4), e4n)
        b0_len = w4[w4[3]]
        probe_kernel.EXT['tail'] = (b0_len + 1) & ~1
        _, _, p_syms, _, _ = ks['probe'].assemble()
        tail = [0] * (probe_kernel.EXT['tail'] - b0_len) + probe_kernel.tail_words(p_syms)
        e4n, _ = append_blob0(e4n, tail)
        w4 = struct.unpack('<%dI' % (len(e4n) // 4), e4n)
        d = w4[3]
        b0 = list(w4[w4[d + 1]: w4[d + 1] + w4[d]])
        assert len(b0) <= blob0_words, f'Blob 0 {len(b0):#x} words, its buffer {blob0_words:#x}'
        err = pa.sharc_blob0_check(b0, blob0_words)
        assert err is None, err
        assert b0[probe_kernel.EXT['tail']] == probe_kernel.MAGIC
        print(f'[+] Entry 4: Blob 0 {b0_len:#x} -> {len(b0):#x} words: magic at DDR2 {probe_kernel.magic_addr():#x}, '
              f'routine at PC {probe_kernel.ext_pc():#x}')
        if check:
            probe_kernel.check(0.25, ks['probe'].place)

    # 3. Entry 2: Blob 0's buffer and Heap 6
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)

    # 4. Entry 3: the models, descriptors copied over their targets
    e3n, id_n, _ = pa.add_model_entry3(e3, clone, be.NAME, be.DISPLAY, b_n, params['nam'])
    e3n, id_c, _ = pa.add_model_entry3(e3n, targets['click'], bc.NAME, bc.DISPLAY, b_c, params['click'],
                                       meta_set={'displayNameShort': bc.SHORT, 'displayParamCount': str(len(params['click']) - 2)})
    ids = {'nam': id_n, 'click': id_c}
    for k in fx:
        e3n, ids[k], _ = pa.add_model_entry3(e3n, targets[k], EFFECTS[k]['name'], EFFECTS[k]['display'], blobs[k], params[k])
    e3n = bytearray(e3n)
    ms = pa.parse_entry3_full(bytes(e3n))['models']
    for key, new_id in ids.items():
        d_new = struct.unpack_from('<14I', e3n, ms[new_id]['off'])
        d_tgt = list(struct.unpack_from('<14I', e3n, ms[targets[key]['model_id']]['off']))
        for k in (0, 1, 6, 7, 10, 11, 13):
            d_tgt[k] = d_new[k]
        struct.pack_into('<14I', e3n, ms[targets[key]['model_id']]['off'], *d_tgt)
    e3n = bytes(e3n)
    chk = pa.parse_entry3_full(e3n)['models']
    displays = {'nam': be.DISPLAY, 'click': bc.DISPLAY, **{k: EFFECTS[k]['display'] for k in fx}}
    for key, disp in displays.items():
        t = chk[targets[key]['model_id']]
        assert t['displayName'] == disp and t['blob_index'] == blobs[key] and len(t['params']) == len(params[key]), key
    print('[+] Entry 3: ' + '; '.join(f'{targets[k]["name"]} -> {displays[k]}' for k in displays))

    # 5. Entry 0
    e0n, *_ = pa.takeover_entry0_effects(e0, targets['nam']['words'][2], be.DISPLAY, short_name=be.SHORT,
                                         dsp_cost=be.DSP_COST, n_params=len(params['nam']), strip_title=be.STRIP_TITLE)
    e0n, *_ = pa.takeover_entry0_effects(e0n, targets['click']['words'][2], bc.DISPLAY, short_name=bc.SHORT,
                                         dsp_cost=bc.DSP_COST, n_params=len(params['click']), strip_title=None,
                                         n_display=len(params['click']) - 2)
    for k in fx:
        e0n, pid, _, hits = pa.takeover_entry0_effects(e0n, targets[k]['words'][2], EFFECTS[k]['display'],
                                                       short_name=EFFECTS[k]['display'], dsp_cost=EFFECTS[k]['cost'],
                                                       n_params=len(params[k]), strip_title=None)
        print(f'[+] Entry 0: {EFFECTS[k]["display"]} preset_id {pid}, browser slots {hits}, dsp_cost {EFFECTS[k]["cost"]}')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: e0n, 2: l6ia.swap32(e2_raw), 3: e3n, 4: e4n})

    # 6. Entry 2: the kernels, no shared byte, one hook each
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked = pa._scan_e2_injected(e2_raw)
    assert used_pm_end <= 0x0c4ef8 and not hooked, 'Entry 2 already has injected code'
    n_secs, n_syms = sasm.assemble(open(nam_asm).read(), os.path.basename(nam_asm))
    _, c_secs, c_syms, c_end, c_data = click_kernel.assemble(place='b3')
    kernels = {'NAM': (n_secs, n_syms['CUSTOM_AMP_ENTRY'], NAM_PRIM),
               'Click': (c_secs, c_syms['CLICK_ENTRY'], CLICK_PRIM)}
    placed = {}
    for b in blocks:
        _, secs, syms, end, data = ks[b].assemble()
        for j, k in enumerate(entries_of[b]):            # a shared kernel's code and data go in once
            kernels[EFFECTS[k]['display']] = (secs if j == 0 else [], syms[EFFECTS[k]['entry']], EFFECTS[k]['prim'])
            placed[k] = (end, data, b)
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
    print(f'[+] memory: NAM Block 3 {nam_b3[0]:#x}..{nam_b3[1]:#x}; ' +
          '; '.join(f'{placed[k][2]} data {placed[k][1][0]:#x}..{placed[k][1][1]:#x}, '
                    f'code {ks[placed[k][2]].places[ks[placed[k][2]].place][0]:#x}..{placed[k][0]:#x}' for k in fx if entries_of[placed[k][2]][0] == k) +
          f'; Click data {c_data[0]:#x}.., code {click_kernel.PLACES["b3"][0]:#x}..{c_end:#x}: no byte shared')
    ldr = []
    for secs, _, _ in kernels.values():
        for s in secs:
            ldr += pa.pack_init_l48(s.addr, s.words) if s.kind == 'pm' else ldr_l32(pa, s.addr, s.words, bool(extras))
    table, _ = pa.sharc_prim_table(e2_raw)
    template = pa.sharc_prim_record(e2_raw, 0x822)
    for who, (_, entry, prim) in kernels.items():
        assert prim in table, f'primitive {prim:#x} not in the table'
        ldr += pa.pack_init_l32(table[prim], [prim] + list(template[1:5]) + [entry, 0x91, 0x0d])
        print(f'[+] Entry 2: {who} at PM {entry:#x} via {prim:#06x} @ {table[prim]:#x}')
    e2_new = pa.inject_sharc_ldr_blocks(e2_raw, ldr)
    print(f'[+] Entry 2: {len(e2_new)} bytes of the 524288-byte partition ({524288 - len(e2_new)} free)')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {2: l6ia.swap32(e2_new)})
    open(image, 'wb').write(l6ia_bytes)

    # 7. verify and pack
    if 'ALL OK' not in run(sys.executable, os.path.join(TOOLS, 'l6ia_verify.py'), image):
        sys.exit('build_all.py: the image failed its checksum check')
    run(sys.executable, os.path.join(TOOLS, 'hxf.py'), 'pack', image, out, '--donor', stock)
    import json
    manifest = dict(input=os.path.basename(stock), input_md5=STOCK_MD5,
                    output=os.path.relpath(out, HERE), output_md5=hashlib.md5(open(out, 'rb').read()).hexdigest(),
                    nam=dict(model=be.TAKEOVER, primitive=NAM_PRIM, slots=NAM_SLOTS, block3=list(nam_b3),
                             sdram_base=sdr_base, dsp_cost=be.DSP_COST, **({'far_d': NAM_FAR_D_EXTRA} if extras else {})),
                    click=dict(model=bc.TAKEOVER, primitive=CLICK_PRIM, place=list(click_kernel.PLACES['b3']), dsp_cost=bc.DSP_COST))
    for k in fx:
        b = placed[k][2]
        manifest[k] = dict(model=EFFECTS[k]['takeover'], primitive=EFFECTS[k]['prim'], place=list(ks[b].places[ks[b].place]),
                           data=list(placed[k][1]), dsp_cost=EFFECTS[k]['cost'], **({'kernel': b} if b != k else {}))
    if extras:
        manifest['extras'] = extras
    manifest.update(blob0_words=blob0_words, checked=check)
    json.dump(manifest, open(manifest_path, 'w'), indent=1)
    print(f'\nDone: {out}\nFlash: python3 tools/flash.py flash {os.path.relpath(out, HERE)}')


if __name__ == '__main__':
    main()
