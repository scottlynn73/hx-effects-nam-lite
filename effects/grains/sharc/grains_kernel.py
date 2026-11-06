#!/usr/bin/env python3
"""grains_kernel.py - build and check the Grains kernel (grains_kernel.asm) for the HX Effects SHARC.

usage: grains_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2]

  --check   run it in ssim against the C reference (effects/grains through effects/out/libfx.so), every
            output word identical, with the register contract, the memory it may write (its slots and,
            per slot, a RING_N-word ring at RING0 + (slot - 1) x RING_N, filled with noise first: the kernel
            must never read a sample it has not recorded) and a cycle budget.

RING0 is where the rings go: DDR2 on the unit (set by the image build); any free address in the check.
"""
import ctypes
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402

RING_N, RING_SHIFT, NVOICES, VSIZE, SEED = 65536, 16, 4, 9, 0x2545F491
NSLOTS = 3
RING0 = 0x380000                     # the check's; the image build sets the unit's (DDR2)
VOICE = dict(VA=0, VW=1, VN=2, VL=3, VS=4, VD=5, VI=6, VP=7, VSP=8)

STATE = (['RING', 'SVI5', 'SVL5', 'LEN', 'INV', 'DENS', 'NORM', 'STAG', 'SPEED', 'SPRAY', 'THRSC', 'THRREV', 'FB',
          'MIX', 'STARTED', 'RND', 'W', 'FILLED'] + [f'V{k}' for k in range(NVOICES * VSIZE)])

CONSTANTS = dict(K_SPRAY=24000.0, K_2P24=16777216.0, K_2M24=2.0 ** -24, K_FBMAX=float(np.float32(0.9)))


def tables():
    lib = kr.lib()
    ln = (ctypes.c_int * 8).in_dll(lib, 'GRAINS_LEN')
    inv = (ctypes.c_float * 8).in_dll(lib, 'GRAINS_INV')
    sp = (ctypes.c_float * 7).in_dll(lib, 'GRAINS_SPEED')
    norm = (ctypes.c_float * 5).in_dll(lib, 'GRAINS_NORM')
    stag = (ctypes.c_float * 5).in_dll(lib, 'GRAINS_STAGGER')
    return (('T_LEN', list(ln)), ('T_INV', [kr.fw(v) for v in inv]), ('T_SPEED', [kr.fw(v) for v in sp]),
            ('T_NORM', [kr.fw(v) for v in norm]), ('T_STAG', [kr.fw(v) for v in stag]))


def make_spec(ring0=RING0):
    spec = kr.Spec('grains', os.path.join(HERE, 'grains_kernel.asm'), 'GRAINS_ENTRY',
                   knobs=dict(size=5, density=6, pitch=7, spray=8, scatter=9, reverse=10, feedback=11, mix=13),
                   int_knobs={'size', 'density', 'pitch'},
                   order=['size', 'density', 'pitch', 'spray', 'scatter', 'reverse', 'feedback', 'mix'],   # = grains.h N_*
                   state=STATE, constants=CONSTANTS, nslots=NSLOTS, tables=tables(), max_cycles=9000,
                   extra_equ=[f'.equ RING0, {ring0:#x}', f'.equ RING_N, {RING_N}', f'.equ RING_SHIFT, {RING_SHIFT}',
                              f'.equ RING_MASK, {RING_N - 1}', f'.equ NVOICES, {NVOICES}', f'.equ VSIZE, {VSIZE}',
                              f'.equ SEED, {SEED:#x}'] + [f'.equ {k}, {v}' for k, v in VOICE.items()])
    spec.places['b2'] = (0xC4EF8, 0xC5554, 0xE4850)       # a Grains-only placement, for the check
    spec.extra_writes = [(ring0, ring0 + RING_N * NSLOTS)]
    spec.garbage = [(ring0, ring0 + RING_N * NSLOTS)]
    return spec


SPEC = make_spec()

CASES = [
    dict(size=4, density=3, pitch=3, spray=0.3, scatter=0.1, reverse=0.2, feedback=0.3, mix=0.5),   # the defaults
    dict(size=7, density=2, pitch=6, spray=0, scatter=0, reverse=0, feedback=0, mix=1),
    dict(size=0, density=4, pitch=0, spray=1, scatter=1, reverse=1, feedback=0.9, mix=1),
    dict(size=2, density=1, pitch=2, spray=0.5, scatter=0.5, reverse=0.5, feedback=0.5, mix=0.7),
    dict(size=5, density=4, pitch=5, spray=0.8, scatter=0.3, reverse=0.7, feedback=0.7, mix=0.9),
    dict(size=99, density=99, pitch=99, spray=9, scatter=9, reverse=9, feedback=9, mix=9),          # out of range
    dict(size=-9, density=-9, pitch=-9, spray=-9, scatter=-9, reverse=-9, feedback=-9, mix=-9),
]


def rnd_knobs(r):
    return dict(size=r.randint(0, 7), density=r.randint(1, 4), pitch=r.randint(0, 6), spray=r.uniform(0, 1),
                scatter=r.uniform(0, 1), reverse=r.uniform(0, 1), feedback=r.uniform(0, 0.9), mix=r.uniform(0, 1))


def check(seconds=1.0, place='b2'):
    return kr.check(SPEC, place, CASES, rnd_knobs, seconds)


if __name__ == '__main__':
    kr.main(SPEC, CASES, rnd_knobs, __doc__)
