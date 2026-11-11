#!/usr/bin/env python3
"""syntax_kernel.py - build and check the Syntax kernel (syntax_kernel.asm) for the HX Effects SHARC.

usage: syntax_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/syntax through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write and a cycle budget.
"""
import ctypes
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402
from kernel_rig import f32, SR  # noqa: E402

NSTEPS, NPAT, NAP = 8, 9, 4
STATE = (['PRIMED', 'GDRIVE', 'GOUT', 'GMIX', 'TDRIVE', 'TOUT', 'TMIX', 'SHIFT', 'PAT', 'SINC', 'GK', 'TONEA',
          'DCX', 'DCY', 'ADEL', 'C', 'S', 'F', 'SPHASE', 'STEP', 'TONEZ'] + [f'AP{k}' for k in range(8 * NAP)])


def nf(x):
    return float(np.float32(x))


CONSTANTS = dict(
    K_INV48=nf(np.float32(1.0) / np.float32(48000.0)), K_TWO_PI_SR=f32(2 * math.pi / SR),
    K_NEG_W=f32(-2 * math.pi / SR), K_TOP=f32(f32(0.45) * SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)),
    K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_EPS=f32(1e-6), K_LN10_20=f32(0.115129255),
    K_LN100=f32(4.60517019), K_GL=f32(-9.21034037),
    K_S3=nf(np.float32(-1.0) / np.float32(6.0)), K_S5=nf(np.float32(1.0) / np.float32(120.0)),
    K_S7=nf(np.float32(-1.0) / np.float32(5040.0)),
    **kr.exp_constants())


def tables():
    lib = kr.lib()
    lib.syntax_pattern.restype = ctypes.POINTER(ctypes.c_float)
    pat = []
    for p in range(NPAT):
        row = lib.syntax_pattern(p)
        pat += [kr.fw(row[k]) for k in range(NSTEPS)]
    ca = (ctypes.c_float * NAP).in_dll(lib, 'SYNTAX_COEF_A')
    cb = (ctypes.c_float * NAP).in_dll(lib, 'SYNTAX_COEF_B')
    return (('T_PAT', pat), ('T_CA', [kr.fw(v) for v in ca]), ('T_CB', [kr.fw(v) for v in cb]))


SPEC = kr.Spec('syntax', os.path.join(HERE, 'syntax_kernel.asm'), 'SYNTAX_ENTRY',
               knobs=dict(drive=5, shift=6, pattern=7, speed=8, glide=9, tone=10, output=11, mix=13),
               int_knobs={'pattern'},
               order=['drive', 'shift', 'pattern', 'speed', 'glide', 'tone', 'output', 'mix'],   # = syntax.h Y_*
               state=STATE, constants=CONSTANTS, nslots=4, tables=tables(), max_cycles=8000,
               extra_equ=[f'.equ NSTEPS, {NSTEPS}'])
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)        # a Syntax-only placement, for the check

CASES = [
    dict(drive=12, shift=150, pattern=1, speed=4, glide=0.2, tone=0.7, output=-6, mix=1),        # the defaults
    dict(drive=0, shift=100, pattern=0, speed=4, glide=0, tone=1, output=0, mix=1),
    dict(drive=36, shift=1000, pattern=8, speed=16, glide=0, tone=0.5, output=6, mix=0.7),
    dict(drive=20, shift=40, pattern=6, speed=0.5, glide=1, tone=0.2, output=-12, mix=1),
    dict(drive=6, shift=500, pattern=4, speed=9, glide=0.6, tone=0.9, output=12, mix=0.4),
    dict(drive=99, shift=1e9, pattern=99, speed=1e9, glide=9, tone=9, output=99, mix=9),        # out of range
    dict(drive=-9, shift=-9, pattern=-9, speed=-9, glide=-9, tone=-9, output=-99, mix=-9),
]


def rnd_knobs(r):
    return dict(drive=r.uniform(0, 36), shift=r.uniform(0, 1000), pattern=r.randint(0, 8), speed=r.uniform(0.5, 16),
                glide=r.uniform(0, 1), tone=r.uniform(0, 1), output=r.uniform(-36, 12), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
