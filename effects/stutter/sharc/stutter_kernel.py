#!/usr/bin/env python3
"""stutter_kernel.py - build and check the Stutter kernel (stutter_kernel.asm) for the HX Effects SHARC.

usage: stutter_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/stutter through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write (its slots and,
            per slot, a RING_N-word ring at RING0 + (slot - 1) x RING_N, filled with noise first: the kernel
            must never read a sample it has not recorded) and a cycle budget.

RING0 is where the rings go: DDR2 on the unit (set by the image build); any free address in the check.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402
from kernel_rig import f32, SR  # noqa: E402

RING_N, RING_SHIFT, LMIN, LMAX, HOLD, SEED = 32768, 15, 64, 24000, 2400, 0x9E3779B9
NSLOTS = 4
RING0 = 0x380000                     # the check's; the image build sets the unit's (DDR2)

STATE = ['TRIG', 'CINC', 'THR', 'BASE', 'REPS', 'SPD', 'RND3', 'MIX', 'RING',
         'ENVF', 'ENVS', 'HOLD', 'CPH', 'RND', 'W', 'FILLED', 'PLAY', 'START', 'LEN', 'LEFT', 'POS', 'SPEED', 'AMT']

CONSTANTS = dict(
    K_SMR=f32(math.exp(-1.0 / (0.005 * SR))), K_SLOWK=f32(1.0 - math.exp(-1.0 / (0.05 * SR))),
    K_INV48=float(np.float32(1.0) / np.float32(48000.0)), K_LN25=f32(3.21887582), K_FLOOR=f32(0.02),
    K_FADE=1.0 / 32, K_XF=1.0 / 64, K_2M24=2.0 ** -24, K_2P24=16777216.0,
    **kr.exp_constants())
SPEEDS = [1.0, 2.0, 0.5, -1.0, -2.0]
RSPEEDS = [1.0, 2.0, 0.5, -1.0, -2.0, 1.0, -0.5, 0.5]


def make_spec(ring0=RING0):
    spec = kr.Spec('stutter', os.path.join(HERE, 'stutter_kernel.asm'), 'STUTTER_ENTRY',
                   knobs=dict(trigger=5, rate=6, chance=7, length=8, repeats=9, speed=10, random=11, mix=13),
                   int_knobs={'trigger', 'repeats', 'speed'},
                   order=['trigger', 'rate', 'chance', 'length', 'repeats', 'speed', 'random', 'mix'],   # = stutter.h U_*
                   state=STATE, constants=CONSTANTS, nslots=NSLOTS, max_cycles=6000,
                   tables=(('T_SP', [kr.fw(v) for v in SPEEDS]), ('T_RS', [kr.fw(v) for v in RSPEEDS])),
                   extra_equ=[f'.equ RING0, {ring0:#x}', f'.equ RING_N, {RING_N}', f'.equ RING_SHIFT, {RING_SHIFT}',
                              f'.equ RING_MASK, {RING_N - 1}', f'.equ LMIN, {LMIN}', f'.equ LMAX, {LMAX}',
                              f'.equ HOLD, {HOLD}', f'.equ SEED, {SEED:#x}'])
    spec.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)       # a Stutter-only placement, for the check
    spec.extra_writes = [(ring0, ring0 + RING_N * NSLOTS)]
    spec.garbage = [(ring0, ring0 + RING_N * NSLOTS)]     # the check fills the rings with noise first
    return spec


SPEC = make_spec()

CASES = [
    dict(trigger=0, rate=2, chance=0.5, length=0.5, repeats=4, speed=0, random=0, mix=1),     # the defaults
    dict(trigger=0, rate=8, chance=1, length=0.2, repeats=3, speed=3, random=0, mix=1),
    dict(trigger=1, rate=16, chance=1, length=0.3, repeats=8, speed=1, random=0.5, mix=0.7),
    dict(trigger=2, rate=6, chance=0.7, length=0.6, repeats=2, speed=5, random=1, mix=0.8),
    dict(trigger=2, rate=12, chance=0.9, length=0.0, repeats=16, speed=4, random=0.3, mix=1),
    dict(trigger=2, rate=4, chance=1, length=1.0, repeats=1, speed=2, random=0, mix=0.5),
    dict(trigger=99, rate=1e9, chance=9, length=9, repeats=99, speed=99, random=9, mix=9),     # out of range
    dict(trigger=-9, rate=-9, chance=-9, length=-9, repeats=-9, speed=-9, random=-9, mix=-9),
]


def rnd_knobs(r):
    return dict(trigger=r.randint(0, 2), rate=r.uniform(0.5, 16), chance=r.uniform(0, 1), length=r.uniform(0, 1),
                repeats=r.randint(1, 16), speed=r.randint(0, 5), random=r.uniform(0, 1), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
