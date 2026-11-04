#!/usr/bin/env python3
"""commander_kernel.py - build and check the Commander kernel (commander_kernel.asm) for the HX Effects SHARC.

usage: commander_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/commander through effects/out/libfx.so),
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

CG_N = 6
STATE = (['PRIMED'] + [f'G{k}' for k in range(CG_N)] + [f'T{k}' for k in range(CG_N)] +
         ['GGATE', 'THR', 'TONEA', 'DCX', 'DCY', 'LP1', 'LP2', 'ENV', 'SQ', 'D1', 'D2', 'TA', 'TB'])
CONSTANTS = dict(
    K_LN10_20=f32(0.115129255), K_LN100=f32(4.60517019), K_NEG_W=f32(-2 * math.pi / SR),
    K_TOP=f32(f32(0.45) * SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)), K_EPS=f32(1e-6),
    K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_LPA=f32(1.0 - math.exp(-2 * math.pi * 300.0 / SR)),
    K_REL=f32(math.exp(-1.0 / (0.05 * SR))), K_HYST=f32(0.5), K_HFLOOR=f32(0.00001), K_01=f32(0.1),
    **kr.exp_constants())

SPEC = kr.Spec('commander', os.path.join(HERE, 'commander_kernel.asm'), 'COMMANDER_ENTRY',
               knobs=dict(fuzz=5, sub1=6, sub2=7, up=8, tone=9, output=10, gate=11, dry=13),
               int_knobs={'gate', 'dry'},
               order=['fuzz', 'sub1', 'sub2', 'up', 'tone', 'gate', 'dry', 'output'],       # = commander.h C_*
               state=STATE, constants=CONSTANTS, extra_equ=[f'.equ CG_N, {CG_N}'])
SPEC.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)      # a Commander-only placement, for the check
assert SPEC.state['ST_T0'] == SPEC.state['ST_G0'] + CG_N

CASES = [
    dict(fuzz=0.7, sub1=0.5, sub2=0.0, up=0.0, tone=0.5, gate=3, dry=0, output=-6),       # the defaults
    dict(fuzz=1.0, sub1=0.0, sub2=0.0, up=0.0, tone=1.0, gate=0, dry=0, output=0),
    dict(fuzz=0.0, sub1=1.0, sub2=1.0, up=0.0, tone=0.3, gate=5, dry=3, output=-3),
    dict(fuzz=0.3, sub1=0.0, sub2=0.0, up=1.0, tone=0.8, gate=10, dry=10, output=6),
    dict(fuzz=1.0, sub1=1.0, sub2=1.0, up=1.0, tone=0.0, gate=1, dry=5, output=12),       # loud input
    dict(fuzz=9.0, sub1=-2.0, sub2=3.0, up=2.0, tone=7.0, gate=40, dry=-4, output=99),    # out of range
    dict(fuzz=0.0, sub1=0.0, sub2=0.0, up=0.0, tone=0.5, gate=0, dry=10, output=-36),     # dry only
]


def rnd_knobs(r):
    return dict(fuzz=r.uniform(0, 1), sub1=r.uniform(0, 1), sub2=r.uniform(0, 1), up=r.uniform(0, 1),
                tone=r.uniform(0, 1), gate=r.randint(0, 10), dry=r.randint(0, 10), output=r.uniform(-36, 12))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
