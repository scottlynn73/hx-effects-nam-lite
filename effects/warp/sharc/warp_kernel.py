#!/usr/bin/env python3
"""warp_kernel.py - build and check the Warp kernel (warp_kernel.asm) for the HX Effects SHARC.

usage: warp_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/warp through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write (its slots and,
            per slot, a RING_N-word ring at RING0 + (slot - 1) x RING_N, zeroed on claim) and a cycle budget.

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

RING_N, RING_SHIFT, WIN, SEED = 4096, 12, 2048, 0x7F4A7C15
NSLOTS = 4
RING0 = 0x380000                     # the check's; the image build sets the unit's (DDR2)

STATE = ['PRIMED', 'TOUT', 'TMIX', 'GOUT', 'GMIX', 'RATIO', 'DEPTH', 'LINC', 'CHAOS', 'FB', 'TONEA', 'RING',
         'D', 'LPH', 'CV', 'CT', 'RND', 'W', 'TONEZ']

CONSTANTS = dict(
    K_INV48=float(np.float32(1.0) / np.float32(48000.0)), K_LN10_20=f32(0.115129255), K_LN100=f32(4.60517019),
    K_NEG_W=f32(-2 * math.pi / SR), K_TOP=f32(f32(0.45) * SR), K_EPS=f32(1e-6),
    K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_MD=f32(0.03), K_CV=f32(0.001), K_RMIN=f32(0.05),
    K_FBMAX=f32(0.95), K_WIN=float(WIN), K_HALF=float(WIN // 2), K_2W=2.0 / WIN, K_BASE=64.0, K_2M24=2.0 ** -24,
    **kr.exp_constants())


def tables():
    ratio = (ctypes.c_float * 8).in_dll(kr.lib(), 'WARP_RATIO')
    return (('T_RATIO', [kr.fw(v) for v in ratio]),)


def make_spec(ring0=RING0):
    spec = kr.Spec('warp', os.path.join(HERE, 'warp_kernel.asm'), 'WARP_ENTRY',
                   knobs=dict(pitch=5, depth=6, rate=7, chaos=8, feedback=9, tone=10, output=11, mix=13),
                   int_knobs={'pitch'},
                   order=['pitch', 'depth', 'rate', 'chaos', 'feedback', 'tone', 'output', 'mix'],   # = warp.h W_*
                   state=STATE, constants=CONSTANTS, nslots=NSLOTS, tables=tables(), max_cycles=16000,
                   extra_equ=[f'.equ RING0, {ring0:#x}', f'.equ RING_N, {RING_N}', f'.equ RING_SHIFT, {RING_SHIFT}',
                              f'.equ RING_MASK, {RING_N - 1}', f'.equ SEED, {SEED:#x}'])
    spec.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)       # a Warp-only placement, for the check
    spec.extra_writes = [(ring0, ring0 + RING_N * NSLOTS)]
    return spec


SPEC = make_spec()

CASES = [
    dict(pitch=6, depth=0.3, rate=0.5, chaos=0, feedback=0.5, tone=0.7, output=-3, mix=0.5),     # the defaults
    dict(pitch=0, depth=0, rate=1, chaos=0, feedback=0, tone=1, output=0, mix=1),
    dict(pitch=7, depth=1, rate=10, chaos=1, feedback=0.95, tone=0.3, output=6, mix=1),
    dict(pitch=3, depth=0.8, rate=3, chaos=0.5, feedback=0.2, tone=0.9, output=-12, mix=0.8),
    dict(pitch=2, depth=0.1, rate=0.05, chaos=0.2, feedback=0.7, tone=0.5, output=12, mix=0.6),
    dict(pitch=99, depth=9, rate=1e9, chaos=9, feedback=9, tone=9, output=99, mix=9),            # out of range
    dict(pitch=-9, depth=-9, rate=-9, chaos=-9, feedback=-9, tone=-9, output=-99, mix=-9),
]


def rnd_knobs(r):
    return dict(pitch=r.randint(0, 7), depth=r.uniform(0, 1), rate=r.uniform(0.05, 10), chaos=r.uniform(0, 1),
                feedback=r.uniform(0, 0.95), tone=r.uniform(0, 1), output=r.uniform(-36, 12), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
