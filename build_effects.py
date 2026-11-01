#!/usr/bin/env python3
"""Build HX Effects firmware 3.80.0 with NAM A2 Lite, in one step, from your own copy of the stock firmware.

usage: python3 build_effects.py [HX_Effects_v3.80.0_0xd97239907.hxf] [-o out.hxf] [--no-check]

With no file given, the build looks for firmware/HX_Effects_v3.80.0_0xd97239907.hxf (the firmware/
folder is git-ignored: Line 6's file is never committed).

Reads Line 6's stock HX Effects 3.80.0 firmware, adds the NAM A2 Lite block and writes
build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf for Line 6 Updater. Nothing of Line 6's is in this
folder; the build changes four parts of the firmware and leaves the bootloader alone.

The NAM block takes over the 1024-sample IR block's identity (the 2048-sample IR block stays):
it is found under IR > Single as "NAM A2 Lite", with the knobs Model (the User IR slot holding
the capture), Input, Bass, Mid, Treble, Presence, Ch Vol and Polarity.

What the build does (through the tools in tools/, which carry the HX Effects support):
  1. tools/sharc/nam_multi.py        the SHARC kernel for the HX Effects (its IR store, fixed DDR2 blocks),
                                     checked bit for bit in the simulator unless --no-check
  2. Entry 4 (DSP graph library)     a copy of the IR block's graph with the convolution replaced by the
                                     NAM primitive; the other members parked at the IR block's default knobs
                                     (cuts off, mix fully wet, level 0 dB)
  3. Entry 2 (SHARC boot stream)     Blob 0 buffer enlarged to 0x78000 words, Heap 6 moved to 0x30d100
  4. Entry 3 (model table)           the NAM model's parameters and states, written into the 1024 IR's descriptor
  5. Entry 0 (main application)      the 1024 IR's Table 1 cost, Table 2 counts/name, browser name and the
                                     IR category's strip title, in place
  6. Entry 2 again                   the kernel into the boot stream, primitive 0x9c75 hooked to it
  7. every checksum verified, the .hxf packed
"""
import hashlib
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, 'sharc'))

STOCK_MD5 = '7c2ebdf1bffb6bcc5f89dda97f91e40c'       # HX_Effects_v3.80.0_0xd97239907.hxf
TAKEOVER = 'HD2_ImpulseResponse1024Mono'              # the stock model the NAM block becomes
CLONE = 'HD2_ImpulseResponse2048Mono'                 # the graph the NAM host is built on
NAME, DISPLAY, SHORT = 'HD2_AmpNAMLite', 'NAM A2 Lite', 'NAM A2 Lite'
STRIP_TITLE = 'NAM / IR_2048'      # the IR category's default scribble-strip title (also the 2048 IR's while empty)
DSP_COST = 2700
KERNEL = os.path.join(TOOLS, 'sharc', 'nam_multi.py')


def run(*args, env=None):
    print('$ ' + ' '.join(os.path.relpath(a, ROOT) if os.path.isabs(a) else a for a in args[1:]), flush=True)
    r = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, env=env)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(f'build_effects.py: step failed ({os.path.relpath(args[1], ROOT)})')
    return r.stdout


def main():
    argv = sys.argv[1:]
    if argv and not argv[0].startswith('-'):
        stock = os.path.abspath(argv.pop(0))
    else:
        stock = os.path.join(HERE, 'firmware', 'HX_Effects_v3.80.0_0xd97239907.hxf')
    if '-h' in argv or '--help' in argv:
        sys.exit(__doc__)
    if not os.path.isfile(stock):
        sys.exit(f'{stock}: not found. Download the stock HX Effects 3.80.0 firmware from Line 6 and put it in '
                 f'{os.path.join(HERE, "firmware")}/ (see README.md, "Getting the stock firmware").')
    md5 = hashlib.md5(open(stock, 'rb').read()).hexdigest()
    if md5 != STOCK_MD5:
        sys.exit(f'{stock}: MD5 {md5}, not the HX Effects 3.80.0 firmware (expected {STOCK_MD5}).')
    out = os.path.abspath(argv[argv.index('-o') + 1]) if '-o' in argv else \
        os.path.join(HERE, 'build', 'HX_Effects_v3.80.0_NAM_A2_Lite.hxf')
    build = os.path.join(HERE, 'build')
    os.makedirs(build, exist_ok=True)
    asm = os.path.join(build, 'nam_lite.asm')
    image = os.path.join(build, 'nam_lite.l6ia')
    env = dict(os.environ, NAM_DEVICE='effects')

    # 1. the kernel
    run(sys.executable, KERNEL, '-o', asm, *([] if '--no-check' in argv else ['--check']), env=env)

    os.environ['NAM_DEVICE'] = 'effects'
    import l6ia
    import sasm
    import patch_amp as pa

    l6ia_bytes, _ = pa.load_l6ia_from_any(stock)
    dev = pa.select_device(l6ia_bytes)
    assert dev is pa.EFFECTS_DSP, 'the tools did not recognise the HX Effects firmware'
    src_text = open(pa.__file__).read()
    assert hasattr(pa, 'takeover_entry0_effects') and '(5, 1): f2u(-120.0)' in src_text and 'strip_title' in src_text, \
        'tools/patch_amp.py lacks the HX Effects support (takeover, member inits, strip title)'

    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    info = pa.parse_entry3_full(e3)
    src = pa.find_model(info, CLONE)
    tgt = pa.find_model(info, TAKEOVER)
    nam = pa.nam_params(e3, info)

    # 2. Entry 4: the NAM host graph and blob
    new_e4, blob, comp = pa.add_model_entry4(e4, src['blob_index'], nam, 0)
    print(f'[+] Entry 4: NAM host blob {blob} on composite {comp:#x}, a copy of {CLONE}\'s graph')

    # 3. Entry 2: the SHARC's Blob 0 buffer and Heap 6
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = pa.expand_sharc_blob0_buffer(e2_raw)
    print(f'[+] Entry 2: Blob 0 buffer {dev.BLOB0_WORDS:#x} -> {dev.BLOB0_MAX_WORDS:#x} words, Heap 6 moved to {dev.HEAP6_MOVED[0]:#x}')

    # 4. Entry 3: the model, then its descriptor copied over the takeover target's
    new_e3, new_id, slots = pa.add_model_entry3(e3, src, NAME, DISPLAY, blob, nam)
    new_e3 = bytearray(new_e3)
    ms = pa.parse_entry3_full(bytes(new_e3))['models']
    d_new = struct.unpack_from('<14I', new_e3, ms[new_id]['off'])
    d_tgt = list(struct.unpack_from('<14I', new_e3, ms[tgt['model_id']]['off']))
    for k in (0, 1, 6, 7, 10, 11, 13):          # metadata, states, parameters, blob
        d_tgt[k] = d_new[k]
    struct.pack_into('<14I', new_e3, ms[tgt['model_id']]['off'], *d_tgt)
    new_e3 = bytes(new_e3)
    chk = pa.parse_entry3_full(new_e3)['models'][tgt['model_id']]
    assert chk['displayName'] == DISPLAY and chk['blob_index'] == blob and len(chk['params']) == len(nam)
    print(f'[+] Entry 3: {TAKEOVER} (model {tgt["model_id"]}) now carries {DISPLAY}: {len(nam)} parameters, blob {blob}')

    # 5. Entry 0: cost, parameter counts, names and the strip title, in place
    new_e0, pid, cost, hits = pa.takeover_entry0_effects(e0, tgt['words'][2], DISPLAY, short_name=SHORT,
                                                        dsp_cost=DSP_COST, n_params=len(nam), strip_title=STRIP_TITLE)
    print(f'[+] Entry 0: {TAKEOVER} keeps preset_id={pid}; dsp_cost={cost}; renamed in browser list slots {hits}; '
          f'strip title "{STRIP_TITLE}"')

    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: new_e0, 2: l6ia.swap32(e2_raw), 3: new_e3, 4: new_e4})

    # 6. the kernel into Entry 2, hooked to an unused primitive
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked = pa._scan_e2_injected(e2_raw)
    asm_src = open(asm).read()
    if used_pm_end > 0x0c4ef8:
        asm_src = re.sub(r'(\.section\s+pm\s+)0x0*c4ef8\b', f'\\g<1>{used_pm_end:#08x}', asm_src, flags=re.I)
    secs, syms = sasm.assemble(asm_src, os.path.basename(asm))
    pm_secs = [s for s in secs if s.kind == 'pm']
    entry_addr = syms.get('CUSTOM_AMP_ENTRY', pm_secs[0].addr if pm_secs else secs[0].addr)
    ldr = []
    for s in secs:
        if s.kind == 'pm':
            assert s.addr + len(s.words) <= 0x0c5554, f'PM kernel at {s.addr:#x} exceeds Block 2 tail 0x0c5554'
            ldr += pa.pack_init_l48(s.addr, s.words)
        elif s.kind == 'dm':
            ldr += pa.pack_init_l32(s.addr, s.words)
    table, _ = pa.sharc_prim_table(e2_raw)
    prim_id, prim_addr = next((p, table[p]) for p in pa.UNUSED_SHARC_PRIM_IDS if p in table and table[p] not in hooked)
    template = pa.sharc_prim_record(e2_raw, 0x822)
    ldr += pa.pack_init_l32(prim_addr, [prim_id] + list(template[1:5]) + [entry_addr, 0x91, 0x0d])
    l6ia_bytes, _, _ = l6ia.rebuild_archive(l6ia_bytes, {2: l6ia.swap32(pa.inject_sharc_ldr_blocks(e2_raw, ldr))})
    print(f'[+] Entry 2: kernel at PM {entry_addr:#x}, primitive {prim_id:#06x} @ {prim_addr:#x} hooked to it')
    open(image, 'wb').write(l6ia_bytes)

    # 7. verify and pack
    report = run(sys.executable, os.path.join(TOOLS, 'l6ia_verify.py'), image)
    if 'ALL OK' not in report:
        sys.exit('build_effects.py: the image failed its checksum check')
    run(sys.executable, os.path.join(TOOLS, 'hxf.py'), 'pack', image, out, '--donor', stock)
    print(f'\nDone: {out}\nInstall it with Line 6 Updater (Choose File); read README.md first.')


if __name__ == '__main__':
    main()
