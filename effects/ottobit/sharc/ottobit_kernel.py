#!/usr/bin/env python3
"""ottobit_kernel.py - build and check the Ottobit kernel (ottobit_kernel.asm) for the HX Effects SHARC.

usage: ottobit_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/ottobit through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write (its slots and,
            per slot, a RING_N-word stutter ring at RING0 + (slot - 1) x RING_N) and a cycle budget.

RING0 is where the rings go: DDR2 on the unit (set by the image build); any free address in the check.
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

RING_N, RING_SHIFT, NSTEPS, NPAT, LMIN, SEED = 2048, 11, 6, 9, 64, 0x12345678
NSLOTS = 4
RING0 = 0x380000                     # the check's; build_all.py sets the unit's (DDR2)

STATE = ['PRIMED', 'GOUT', 'GMIX', 'TOUT', 'TMIX', 'INC', 'FBASE', 'SINC', 'THR', 'Q', 'QI', 'PAT', 'RING',
         'DCX', 'DCY', 'OX', 'OY', 'PHASE', 'HELD', 'LOW', 'BAND', 'SPHASE', 'STEP', 'CNT', 'PREV', 'RND',
         'STUT', 'LEN', 'J', 'W', 'START']


def nf(x):
    return float(np.float32(x))


CONSTANTS = dict(
    K_INV_SR=f32(1.0 / SR), K_PI_SR=f32(math.pi / SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)),
    K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_EPS=f32(1e-6), K_LN10_20=f32(0.115129255),
    K_LN80=f32(4.38202663), K_2P24=16777216.0, K_Q=0.5,
    K_S3=nf(np.float32(-1.0) / np.float32(6.0)), K_S5=nf(np.float32(1.0) / np.float32(120.0)),
    K_S7=nf(np.float32(-1.0) / np.float32(5040.0)),
    **kr.exp_constants())


def tables():
    lib = kr.lib()
    lib.ottobit_pattern.restype = ctypes.POINTER(ctypes.c_float)
    pat = []
    for p in range(NPAT):
        row = lib.ottobit_pattern(p)
        pat += [kr.fw(row[k]) for k in range(2 * NSTEPS)]
    q = [kr.fw(float(2 ** (b - 1))) if b else 0 for b in range(17)]
    qi = [kr.fw(1.0 / 2 ** (b - 1)) if b else 0 for b in range(17)]
    return (('T_Q', q), ('T_QI', qi), ('T_PAT', pat))


def make_spec(ring0=RING0):
    spec = kr.Spec('ottobit', os.path.join(HERE, 'ottobit_kernel.asm'), 'OTTOBIT_ENTRY',
                   knobs=dict(rate=5, bits=6, filter=7, pattern=8, speed=9, stutter=10, output=11, mix=13),
                   int_knobs={'bits', 'pattern'},
                   order=['rate', 'bits', 'filter', 'pattern', 'speed', 'stutter', 'output', 'mix'],   # = ottobit.h O_*
                   state=STATE, constants=CONSTANTS, nslots=NSLOTS, tables=tables(), max_cycles=12000,
                   extra_equ=[f'.equ RING0, {ring0:#x}', f'.equ RING_N, {RING_N}', f'.equ RING_SHIFT, {RING_SHIFT}',
                              f'.equ RING_MASK, {RING_N - 1}', f'.equ NSTEPS, {NSTEPS}', f'.equ LMIN, {LMIN}',
                              f'.equ SEED, {SEED:#x}', f'.equ PREV0, {4 * LMIN}'])
    spec.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)       # an Ottobit-only placement, for the check
    spec.extra_writes = [(ring0, ring0 + RING_N * NSLOTS)]
    return spec


SPEC = make_spec()

CASES = [
    dict(rate=8000, bits=6, filter=0.7, pattern=1, speed=4, stutter=0.2, output=-6, mix=1),          # the defaults
    dict(rate=48000, bits=16, filter=1, pattern=0, speed=4, stutter=0, output=0, mix=1),
    dict(rate=3000, bits=2, filter=0.4, pattern=3, speed=12, stutter=1, output=6, mix=0.6),
    dict(rate=1000, bits=1, filter=0.0, pattern=8, speed=16, stutter=0.5, output=-3, mix=1),
    dict(rate=20000, bits=8, filter=0.9, pattern=7, speed=0.5, stutter=0.9, output=12, mix=0.3),
    dict(rate=1e9, bits=99, filter=9, pattern=99, speed=1e9, stutter=9, output=99, mix=9),        # out of range
    dict(rate=-5, bits=-3, filter=-1, pattern=-4, speed=-1, stutter=-1, output=-99, mix=-1),
    dict(rate=6000, bits=4, filter=0.5, pattern=5, speed=8, stutter=0.4, output=0, mix=0),          # dry only
]


def rnd_knobs(r):
    return dict(rate=r.uniform(250, 48000), bits=r.randint(1, 16), filter=r.uniform(0, 1), pattern=r.randint(0, 8),
                speed=r.uniform(0.5, 16), stutter=r.uniform(0, 1), output=r.uniform(-36, 12), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
