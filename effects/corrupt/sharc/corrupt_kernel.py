#!/usr/bin/env python3
"""corrupt_kernel.py - build and check the Corrupt kernel (corrupt_kernel.asm) for the HX Effects SHARC.

usage: corrupt_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/corrupt through effects/out/libfx.so),
            every output word identical, with the register contract and a cycle budget
            (effects/common/kernel_rig.py).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402
from kernel_rig import f32, SR  # noqa: E402

RG_N = 4
STATE = (['PRIMED'] + [f'G{k}' for k in range(RG_N)] + [f'T{k}' for k in range(RG_N)] +
         ['GGATE', 'GLK', 'TONEA', 'NUM', 'DCX', 'DCY', 'LP1', 'LP2', 'ENV', 'SQ', 'CNT', 'INCT', 'INC', 'PH', 'SUB',
          'TA', 'TB', 'OX', 'OY'])
CONSTANTS = dict(
    K_LN10_20=f32(0.115129255), K_LN100=f32(4.60517019), K_NEG_W=f32(-2 * math.pi / SR),
    K_TOP=f32(f32(0.45) * SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)), K_EPS=f32(1e-6),
    K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_LPA=f32(1.0 - math.exp(-2 * math.pi * 300.0 / SR)),
    K_REL=f32(math.exp(-1.0 / (0.05 * SR))), K_HYST=f32(0.5), K_HFLOOR=f32(0.00001), K_GL=f32(-9.21034037),
    K_GATE=f32(0.0005), K_2M24=2.0 ** -24, **kr.exp_constants())

SPEC = kr.Spec('corrupt', os.path.join(HERE, 'corrupt_kernel.asm'), 'CORRUPT_ENTRY',
               knobs=dict(square=5, master=6, sub=7, glide=8, tone=9, output=10, root=11, harm=13),
               int_knobs={'root', 'harm'},
               order=['square', 'master', 'sub', 'glide', 'tone', 'output', 'root', 'harm'],    # = corrupt.h R_*
               state=STATE, constants=CONSTANTS,
               extra_equ=[f'.equ RG_N, {RG_N}', '.equ CNT_MAX, 4096', '.equ PMIN, 16', '.equ PMAX, 2400',
                          '.equ QMAX, 0x800000'])
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)      # a Corrupt-only placement, for the check
assert SPEC.state['ST_T0'] == SPEC.state['ST_G0'] + RG_N

CASES = [
    dict(square=0.0, master=0.8, sub=0.4, glide=0.2, tone=0.6, output=-6, root=2, harm=1),    # the defaults
    dict(square=1.0, master=0.0, sub=0.0, glide=0.0, tone=1.0, output=0, root=2, harm=1),
    dict(square=0.3, master=1.0, sub=1.0, glide=0.0, tone=0.3, output=-3, root=0, harm=1),
    dict(square=0.0, master=1.0, sub=0.5, glide=0.7, tone=0.8, output=6, root=3, harm=8),
    dict(square=1.0, master=1.0, sub=1.0, glide=1.0, tone=0.0, output=12, root=1, harm=3),    # loud input
    dict(square=9.0, master=-2.0, sub=3.0, glide=7.0, tone=7.0, output=99, root=40, harm=-4), # out of range
    dict(square=0.0, master=1.0, sub=0.0, glide=0.5, tone=0.5, output=-36, root=2, harm=5),
]


def rnd_knobs(r):
    return dict(square=r.uniform(0, 1), master=r.uniform(0, 1), sub=r.uniform(0, 1), glide=r.uniform(0, 1),
                tone=r.uniform(0, 1), output=r.uniform(-36, 12), root=r.randint(0, 3), harm=r.randint(1, 8))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
