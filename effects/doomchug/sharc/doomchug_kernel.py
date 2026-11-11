#!/usr/bin/env python3
"""doomchug_kernel.py - build and check the Doom Chug kernel (doomchug_kernel.asm) for the HX Effects SHARC.

usage: doomchug_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/doomchug through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write and a cycle budget.
"""
import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402

NPAT, NV, SEED = 9, 4, 0x2F6E2B1D
VFIELDS = ['BASE', 'D', 'DT', 'LP', 'LI', 'INC', 'PH', 'G', 'DG']
STATE = ['STEP', 'RND', 'SPHASE', 'ENV', 'Z1', 'Z2', 'TONEA'] + [f'V{k}' for k in range(NV * len(VFIELDS))]

CONSTANTS = {}                          # none in memory: every constant is an immediate in the .asm


def tables():
    lib = kr.lib()
    lib.doomchug_pattern.restype = ctypes.c_uint
    return (('T_PAT', [lib.doomchug_pattern(p) for p in range(NPAT)]),)


SPEC = kr.Spec('doomchug', os.path.join(HERE, 'doomchug_kernel.asm'), 'DOOMCHUG_ENTRY',
               knobs=dict(key=5, pattern=6, rate=7, drift=8, warble=9, chug=10, tone=11, level=13),
               int_knobs={'key', 'pattern'},
               order=['key', 'pattern', 'rate', 'drift', 'warble', 'chug', 'tone', 'level'],     # = doomchug.h Q_*
               state=STATE, constants=CONSTANTS, nslots=1, tables=tables(), max_cycles=6000,
               extra_equ=[f'.equ SEED, {SEED:#x}', f'.equ VSIZE, {len(VFIELDS)}'] +
                         [f'.equ V_{n}, {k}' for k, n in enumerate(VFIELDS)])
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)        # a Doom-Chug-only placement, for the check

CASES = [
    dict(key=0, pattern=1, rate=0.5, drift=0.35, warble=0.5, chug=0.4, tone=0.25, level=0.5),     # the defaults
    dict(key=0, pattern=0, rate=0.5, drift=0, warble=0, chug=0, tone=1, level=1),
    dict(key=11, pattern=7, rate=1, drift=1, warble=1, chug=1, tone=1, level=1),                  # everything up
    dict(key=5, pattern=4, rate=0.95, drift=0.6, warble=0.8, chug=0.7, tone=0.1, level=0.8),
    dict(key=7, pattern=8, rate=0.0, drift=0.2, warble=0.1, chug=0.1, tone=0.5, level=0.3),
    dict(key=99, pattern=99, rate=9, drift=9, warble=9, chug=9, tone=9, level=9),                 # out of range
    dict(key=-9, pattern=-9, rate=-9, drift=-9, warble=-9, chug=-9, tone=-9, level=-9),
]


def rnd_knobs(r):
    return dict(key=r.randint(0, 11), pattern=r.randint(0, 8), rate=r.uniform(0, 1), drift=r.uniform(0, 1),
                warble=r.uniform(0, 1), chug=r.uniform(0, 1), tone=r.uniform(0, 1), level=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
