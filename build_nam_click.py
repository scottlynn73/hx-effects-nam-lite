#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with both NAM A2 Lite and the Click metronome in one image.

usage: python3 build_nam_click.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--no-check]

  NAM A2 Lite   as build_effects.py: the 1024 IR block (IR > Single), primitive 0x9c75, kernel in Block 2's
                free tail (PM 0xc4ef8..), its slots in Block 3 (0xe4850..0xe7c14); but its DDR2 blocks
                0x1000 words higher (0x295400..), because two host graphs need a larger Blob 0 buffer
                (0x79000 words instead of 0x78000).
  Click         exactly as build_click.py: the mono Mod/Chorus Echo (Delay > Mono), with the delay's own
                Time knob and tap-tempo sync; but hooked to primitive 0x0128 (zero uses in the stock
                graphs) and placed in the top of Block 3 that NAM leaves free (click_kernel.py 'b3':
                data 0xe7c20.., code at 48-bit 0xe5390.. = normal 0xe7d58..0xe8000).

Both kernels are checked in the simulator first (NAM bit for bit against src/sharc/nam_a2.asm, Click bit
for bit against its C reference at its Block 3 addresses) unless --no-check, and the build asserts that
no two regions (NAM code, NAM data and slots, Click data, Click code) share a byte of internal memory.
Writes build/HX_Effects_v3.80.0_NAM_Click.hxf.
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

import build_click as bc  # noqa: E402  (Click's knobs, map builder, names)
import build_effects as be  # noqa: E402  (NAM's names and cost)

STOCK_MD5 = '7c2ebdf1bffb6bcc5f89dda97f91e40c'
NAM_PRIM, CLICK_PRIM = 0x9c75, 0x0128
# DDR2: the Blob 0 buffer starts at 0x21c400 (= stock Heap 6's start 0x292e2c - its stock size 0x76a2c).
# build_effects.py enlarges it to 0x78000 words (to 0x294400), where NAM's three 0x5000-word slots start.
# Two host graphs need more: 0x79000 words (to 0x295400), NAM's slots moved up to match, still inside
# the region freed by moving Heap 6 (to 0x2a8df6).
BLOB0_BASE, BLOB0_WORDS = 0x21C400, 0x79000
BLOB0_WORDS_ALL = 0x7A000                         # three host graphs (build_all.py)
NAM_SDR_BASE = BLOB0_BASE + BLOB0_WORDS
CLICK_PLACE = 'b3'


def run(*args, env=None):
    print('$ ' + ' '.join(os.path.relpath(a, HERE) if os.path.isabs(a) else a for a in args[1:]), flush=True)
    r = subprocess.run(list(args), cwd=HERE, capture_output=True, text=True, env=env)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(f'build_nam_click.py: step failed ({os.path.relpath(args[1], HERE)})')
    return r.stdout


def byte_range(kind, addr, n):
    """[start, end) in bytes from the block's base, and the block, for n words at addr."""
    base = addr & ~0xFFFF
    if kind == 'pm':                     # 48-bit instructions
        return base, (addr - base) * 6, (addr - base + n + (n & 1)) * 6
    return base, (addr - base) * 4, (addr - base + n) * 4


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        sys.exit(__doc__)
    stock = os.path.abspath(argv.pop(0)) if argv and not argv[0].startswith('-') else \
        os.path.join(HERE, 'firmware', 'HX_Effects_v3.80.0_0xd97239907.hxf')
    if not os.path.isfile(stock) or hashlib.md5(open(stock, 'rb').read()).hexdigest() != STOCK_MD5:
        sys.exit(f'{stock}: missing or not the HX Effects 3.80.0 firmware (MD5 {STOCK_MD5}).')
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', 'HX_Effects_v3.80.0_NAM_Click.hxf')
    build = os.path.join(HERE, 'build')
    os.makedirs(build, exist_ok=True)
    nam_asm = os.path.join(build, 'nam_lite.asm')
    image = os.path.join(build, 'nam_click.l6ia')
    env = dict(os.environ, NAM_DEVICE='effects', NAM_SDR_BASE=hex(NAM_SDR_BASE))
    check = '--no-check' not in argv

    # 1. the kernels
    log = run(sys.executable, be.KERNEL, '-o', nam_asm, *(['--check'] if check else []), env=env)
    m = re.search(r'block 3: (0x[0-9a-f]+)\.\.(0x[0-9a-f]+)', log)
    nam_b3 = (int(m.group(1), 16), int(m.group(2), 16)) if m else (0xE4850, 0xE7C14)
    if check:
        r = subprocess.run(['make', '-s', '-C', os.path.join(HERE, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'build_nam_click.py: could not build effects/out/libfx.so:\n{r.stderr}')
        run(sys.executable, os.path.join(HERE, 'effects', 'metronome', 'sharc', 'click_kernel.py'),
            '--check', '--place', CLICK_PLACE)

    os.environ['NAM_DEVICE'] = 'effects'
    import click_kernel
    import l6ia
    import patch_amp as pa
    import sasm

    l6ia_bytes, _ = pa.load_l6ia_from_any(stock)
    assert pa.select_device(l6ia_bytes) is pa.EFFECTS_DSP, 'not the HX Effects firmware'
    D = pa.EFFECTS_DSP
    assert D.HEAP6[0] - D.BLOB0_WORDS == BLOB0_BASE, 'the Blob 0 buffer is not where expected'
    assert NAM_SDR_BASE + 3 * 0x5000 <= D.HEAP6[1], "NAM's slots would leave the freed Heap 6 region"
    D.BLOB0_MAX_WORDS = BLOB0_WORDS                     # this build only (build_effects.py keeps 0x78000)
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    info = pa.parse_entry3_full(e3)
    clone = pa.find_model(info, be.CLONE)
    nam_tgt = pa.find_model(info, be.TAKEOVER)
    click_tgt = pa.find_model(info, bc.TAKEOVER)
    nam = pa.nam_params(e3, info)
    click = bc.click_params(pa, e3, info)

    # 2. Entry 4: two host graphs, both copies of the 2048 IR block's, on different primitives
    e4n, nam_blob, nam_comp = pa.add_model_entry4(e4, clone['blob_index'], nam, 0, prim_id=NAM_PRIM)
    e4n, click_blob, click_comp = pa.add_model_entry4(e4n, clone['blob_index'], click, 0,
                                                      blob_fn=bc.click_host_blob, prim_id=CLICK_PRIM)
    print(f'[+] DDR2: Blob 0 buffer {BLOB0_BASE:#x}..{NAM_SDR_BASE:#x} ({BLOB0_WORDS:#x} words), '
          f'NAM slots {NAM_SDR_BASE:#x}..{NAM_SDR_BASE + 3 * 0x5000:#x}')
    print(f'[+] Entry 4: NAM host blob {nam_blob} on {nam_comp:#x} (primitive {NAM_PRIM:#06x}), '
          f'Click host blob {click_blob} on {click_comp:#x} (primitive {CLICK_PRIM:#06x})')

    # 3. Entry 2: Blob 0's buffer and Heap 6, once
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)

    # 4. Entry 3: both models, each descriptor copied over its takeover target's
    e3n, nam_id, _ = pa.add_model_entry3(e3, clone, be.NAME, be.DISPLAY, nam_blob, nam)
    e3n, click_id, _ = pa.add_model_entry3(e3n, click_tgt, bc.NAME, bc.DISPLAY, click_blob, click,
                                           meta_set={'displayNameShort': bc.SHORT,
                                                     'displayParamCount': str(len(click) - 2)})
    e3n = bytearray(e3n)
    ms = pa.parse_entry3_full(bytes(e3n))['models']
    for new_id, tgt in ((nam_id, nam_tgt), (click_id, click_tgt)):
        d_new = struct.unpack_from('<14I', e3n, ms[new_id]['off'])
        d_tgt = list(struct.unpack_from('<14I', e3n, ms[tgt['model_id']]['off']))
        for k in (0, 1, 6, 7, 10, 11, 13):
            d_tgt[k] = d_new[k]
        struct.pack_into('<14I', e3n, ms[tgt['model_id']]['off'], *d_tgt)
    e3n = bytes(e3n)
    chk = pa.parse_entry3_full(e3n)['models']
    assert chk[nam_tgt['model_id']]['displayName'] == be.DISPLAY and chk[nam_tgt['model_id']]['blob_index'] == nam_blob
    assert chk[click_tgt['model_id']]['displayName'] == bc.DISPLAY and chk[click_tgt['model_id']]['blob_index'] == click_blob
    print(f'[+] Entry 3: {be.TAKEOVER} -> {be.DISPLAY} ({len(nam)} knobs); {bc.TAKEOVER} -> {bc.DISPLAY} ({len(click)} parameters)')

    # 5. Entry 0: both rows
    e0n, pid_n, _, hits_n = pa.takeover_entry0_effects(e0, nam_tgt['words'][2], be.DISPLAY, short_name=be.SHORT,
                                                       dsp_cost=be.DSP_COST, n_params=len(nam), strip_title=be.STRIP_TITLE)
    e0n, pid_c, _, hits_c = pa.takeover_entry0_effects(e0n, click_tgt['words'][2], bc.DISPLAY, short_name=bc.SHORT,
                                                       dsp_cost=bc.DSP_COST, n_params=len(click), strip_title=None,
                                                       n_display=len(click) - 2)
    print(f'[+] Entry 0: {be.DISPLAY} preset_id {pid_n} slots {hits_n}; {bc.DISPLAY} preset_id {pid_c} slots {hits_c}')
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: e0n, 2: l6ia.swap32(e2_raw), 3: e3n, 4: e4n})

    # 6. Entry 2: both kernels and their data, both primitives hooked
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked = pa._scan_e2_injected(e2_raw)
    assert used_pm_end <= 0x0c4ef8 and not hooked, 'Entry 2 already has injected code'
    nam_secs, nam_syms = sasm.assemble(open(nam_asm).read(), os.path.basename(nam_asm))
    nam_entry = nam_syms.get('CUSTOM_AMP_ENTRY')
    _, click_secs, click_syms, click_end, click_data = click_kernel.assemble(place=CLICK_PLACE)
    click_entry = click_syms['CLICK_ENTRY']

    regions = {'NAM': [], 'Click': []}                   # owner -> (block, start byte, end byte, what)
    for who, secs in (('NAM', nam_secs), ('Click', click_secs)):
        for sec in secs:
            regions[who].append((*byte_range(sec.kind, sec.addr, len(sec.words)), f'{who} {sec.kind} {sec.addr:#x}+{len(sec.words)}'))
    regions['NAM'].append((*byte_range('dm', nam_b3[0], nam_b3[1] - nam_b3[0]), f'NAM Block 3 slots {nam_b3[0]:#x}..{nam_b3[1]:#x}'))
    for c in regions['Click']:                           # no byte of internal memory used by both
        for n_ in regions['NAM']:
            if c[0] == n_[0] and c[1] < n_[2] and n_[1] < c[2]:
                sys.exit(f'build_nam_click.py: memory overlap: {c[3]} and {n_[3]}')
    for blk, lo, hi, what in regions['NAM'] + regions['Click']:
        assert hi <= 0x20000, f'{what} runs past its block'
    nreg = len(regions['NAM']) + len(regions['Click'])
    print(f'[+] memory: {nreg} regions, no byte shared between NAM and Click; Click code {click_entry:#x}..{click_end:#x}, '
          f'data {click_data[0]:#x}..{click_data[1]:#x}; NAM Block 3 to {nam_b3[1]:#x}')

    ldr = []
    for s in nam_secs + click_secs:
        ldr += pa.pack_init_l48(s.addr, s.words) if s.kind == 'pm' else pa.pack_init_l32(s.addr, s.words)
    table, _ = pa.sharc_prim_table(e2_raw)
    template = pa.sharc_prim_record(e2_raw, 0x822)
    for prim, entry in ((NAM_PRIM, nam_entry), (CLICK_PRIM, click_entry)):
        assert prim in table, f'primitive {prim:#x} not in the table'
        ldr += pa.pack_init_l32(table[prim], [prim] + list(template[1:5]) + [entry, 0x91, 0x0d])
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {2: l6ia.swap32(pa.inject_sharc_ldr_blocks(e2_raw, ldr))})
    print(f'[+] Entry 2: NAM at PM {nam_entry:#x} via {NAM_PRIM:#06x} @ {table[NAM_PRIM]:#x}; '
          f'Click at PM {click_entry:#x} via {CLICK_PRIM:#06x} @ {table[CLICK_PRIM]:#x}')
    open(image, 'wb').write(l6ia_bytes)

    # 7. verify and pack
    if 'ALL OK' not in run(sys.executable, os.path.join(TOOLS, 'l6ia_verify.py'), image):
        sys.exit('build_nam_click.py: the image failed its checksum check')
    run(sys.executable, os.path.join(TOOLS, 'hxf.py'), 'pack', image, out, '--donor', stock)
    print(f'\nDone: {out}\nFlash: python3 tools/flash.py flash {os.path.relpath(out, HERE)}')


if __name__ == '__main__':
    main()
