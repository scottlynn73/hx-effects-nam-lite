#!/usr/bin/env python3
"""sequence_kernel.py - build and check the Sequence kernel (sequence_kernel.asm) for the HX Effects SHARC.

usage: sequence_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/sequence through effects/out/libfx.so), every
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

NSTEPS, NPAT = 8, 9
STATE = ['PRIMED', 'TOUT', 'TMIX', 'GOUT', 'GMIX', 'GGATE', 'PATR', 'SINC', 'WAVE', 'OCT', 'GK', 'TONEA',
         'DCX', 'DCY', 'LP1', 'LP2', 'ENV', 'SQ', 'CNT', 'BASE', 'INC', 'PH', 'SPHASE', 'STEP', 'T1', 'T2', 'OX', 'OY']

CONSTANTS = dict(
    K_INV48=float(np.float32(1.0) / np.float32(48000.0)), K_LN10_20=f32(0.115129255), K_LN100=f32(4.60517019),
    K_NEG_W=f32(-2 * math.pi / SR), K_TOP=f32(f32(0.45) * SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)),
    K_EPS=f32(1e-6), K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))),
    K_LPA=f32(1.0 - math.exp(-2 * math.pi * 300.0 / SR)), K_REL=f32(math.exp(-1.0 / (0.05 * SR))),
    K_HYST=f32(0.5), K_HFLOOR=f32(0.00001), K_GL=f32(-9.21034037), K_GATE=f32(0.0005), K_2M24=2.0 ** -24,
    K_INCMAX=f32(0.45), **kr.exp_constants())


def tables():
    lib = kr.lib()
    lib.sequence_ratio.restype = ctypes.c_float
    lib.sequence_ratio.argtypes = [ctypes.c_int, ctypes.c_int]
    patr = [kr.fw(lib.sequence_ratio(p, k)) for p in range(NPAT) for k in range(NSTEPS)]
    octv = (ctypes.c_float * 4).in_dll(lib, 'SEQUENCE_OCTAVE')
    return (('T_PATR', patr), ('T_OCT', [kr.fw(v) for v in octv]))


SPEC = kr.Spec('sequence', os.path.join(HERE, 'sequence_kernel.asm'), 'SEQUENCE_ENTRY',
               knobs=dict(pattern=5, speed=6, wave=7, octave=8, glide=9, tone=10, output=11, mix=13),
               int_knobs={'pattern', 'wave', 'octave'},
               order=['pattern', 'speed', 'wave', 'octave', 'glide', 'tone', 'output', 'mix'],   # = sequence.h Q_*
               state=STATE, constants=CONSTANTS, tables=tables(), max_cycles=6000,
               extra_equ=['.equ PMIN, 16', '.equ PMAX, 2400', '.equ CNT_MAX, 4096', '.equ NUM, 0x1000000'])
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)        # a Sequence-only placement, for the check

CASES = [
    dict(pattern=2, speed=6, wave=1, octave=2, glide=0.1, tone=0.6, output=-6, mix=1),          # the defaults
    dict(pattern=0, speed=4, wave=0, octave=2, glide=0, tone=1, output=0, mix=1),
    dict(pattern=4, speed=16, wave=2, octave=3, glide=0.5, tone=0.4, output=6, mix=0.7),
    dict(pattern=7, speed=0.5, wave=3, octave=0, glide=1, tone=0.8, output=-12, mix=1),
    dict(pattern=8, speed=9, wave=1, octave=1, glide=0.3, tone=0.2, output=12, mix=0.5),
    dict(pattern=99, speed=1e9, wave=99, octave=99, glide=9, tone=9, output=99, mix=9),          # out of range
    dict(pattern=-9, speed=-9, wave=-9, octave=-9, glide=-9, tone=-9, output=-99, mix=-9),
]


def rnd_knobs(r):
    return dict(pattern=r.randint(0, 8), speed=r.uniform(0.5, 16), wave=r.randint(0, 3), octave=r.randint(0, 3),
                glide=r.uniform(0, 1), tone=r.uniform(0, 1), output=r.uniform(-36, 12), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
