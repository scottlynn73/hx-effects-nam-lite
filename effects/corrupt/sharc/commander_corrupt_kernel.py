#!/usr/bin/env python3
"""commander_corrupt_kernel.py - build and check the combined Commander + Corrupt kernel
(commander_corrupt_kernel.asm), used by the image that has both (it saves Entry 2 space).

usage: commander_corrupt_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   Commander's and Corrupt's cases (as commander_kernel.py and corrupt_kernel.py) through
            their own entry points, each word for word against its C reference; then a Commander and
            a Corrupt instance interleaved, knobs moving, sharing the slot pool.
"""
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, '..', '..', 'common'), os.path.join(HERE, '..', '..', 'commander', 'sharc'), HERE):
    sys.path.insert(0, p)
import commander_kernel as ck  # noqa: E402
import corrupt_kernel as rk  # noqa: E402
import kernel_rig as kr  # noqa: E402
import ssim  # noqa: E402

CG_N = 6
STATE = (['PRIMED'] + [f'G{k}' for k in range(CG_N)] + [f'T{k}' for k in range(CG_N)] +
         ['GGATE', 'THR', 'TONEA', 'DCX', 'DCY', 'LP1', 'LP2', 'ENV', 'SQ', 'TA', 'TB', 'OX', 'OY', 'D1', 'D2',
          'GLK', 'NUM', 'CNT', 'INCT', 'INC', 'PH', 'SUB', 'MODE'])
CONSTANTS = dict(ck.CONSTANTS)
for k, v in rk.CONSTANTS.items():
    assert CONSTANTS.setdefault(k, v) == v, k
EQU = [f'.equ CG_N, {CG_N}', '.equ CNT_MAX, 4096', '.equ PMIN, 16', '.equ PMAX, 2400', '.equ QMAX, 0x800000']
ASM = os.path.join(HERE, 'commander_corrupt_kernel.asm')


def spec(of, entry):
    s = kr.Spec(of.SPEC.name, ASM, entry, knobs=of.SPEC.knobs, int_knobs=of.SPEC.int_knobs, order=of.SPEC.order,
                state=STATE, constants=CONSTANTS, extra_equ=EQU, max_cycles=5000)
    return s


SPEC_CMD = spec(ck, 'COMMANDER_ENTRY')
SPEC_COR = spec(rk, 'CORRUPT_ENTRY')
SPEC_COR.places = SPEC_CMD.places                    # one kernel, one place
SPEC = SPEC_CMD
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)


def check_mixed(place, seconds):
    _, secs, syms, _, _ = SPEC_CMD.assemble(place)
    rc, rr = kr.Reference(SPEC_CMD), kr.Reference(SPEC_COR)
    rig = kr.Rig(SPEC_CMD, secs, syms)
    r = random.Random(9)
    nblk = int(seconds * kr.SR) // 16
    insts = [(rig.inst(k), SPEC_CMD if k % 2 == 0 else SPEC_COR) for k in range(4)]
    refs = [(rc if s is SPEC_CMD else rr).new() for _, s in insts]
    xs = [kr.signal(nblk * 16, 30 + k, chord=k == 1) for k in range(4)]
    kn = [None] * 4
    for b in range(nblk):
        if b % 200 == 0:
            for k, (i0, s) in enumerate(insts):
                kn[k] = (ck if s is SPEC_CMD else rk).rnd_knobs(r)
                rig.spec = s
                rig.knobs(i0, kn[k])
        for k, (i0, s) in enumerate(insts):
            rig.spec = s
            blk = xs[k][16 * b:16 * b + 16]
            ref = rc if s is SPEC_CMD else rr
            if rig.call(i0, blk, f'mixed {s.name} block {b}') != ref.process(refs[k], kn[k], [ssim.b2f(v) for v in blk]):
                raise AssertionError(f'mixed: {s.name} instance {k}, block {b}: kernel and reference differ')
    print(f'  two Commander and two Corrupt instances interleaved, knobs moving: identical ({4 * nblk * 16} samples)')


def check(seconds=1.0, place='b2'):
    w1 = kr.check(SPEC_CMD, place, ck.CASES, ck.rnd_knobs, seconds)
    w2 = kr.check(SPEC_COR, place, rk.CASES, rk.rnd_knobs, seconds)
    check_mixed(place, seconds)
    return max(w1, w2)


def main():
    a = sys.argv[1:]
    place = a[a.index('--place') + 1] if '--place' in a else 'b2'
    if '-o' in a:
        src, *_ = SPEC.assemble(place)
        open(a[a.index('-o') + 1], 'w').write(src)
    if '--check' in a:
        secs = float(a[a.index('--seconds') + 1]) if '--seconds' in a else 1.0
        try:
            check(secs, place)
        except AssertionError as ex:
            sys.exit(f'commander_corrupt_kernel.py: CHECK FAILED: {ex}')
        print('CHECK OK')
    if not a:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
