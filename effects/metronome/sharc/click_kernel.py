#!/usr/bin/env python3
"""click_kernel.py - build and check the Click kernel (click_kernel.asm) for the HX Effects SHARC.

usage: click_kernel.py [-o out.asm] [--check] [--seconds S]

  -o out.asm   write the assembled-ready source (the .equ block and tables filled in)
  --check      run it in ssim (tools/sharc) against the C reference (effects/metronome,
               through effects/out/libfx.so: `make -C effects out/libfx.so`) and require
               every output word to be identical, plus the register contract and a cycle budget

Memory (Phase A: Click replaces NAM's kernel, so it takes NAM's regions):
  PM 0xc4ef8..   the code (must end at or before 0xc5554, the build's guard)
  DM 0xe4850..   the save area, constants and tables (Block 3)
  instance block DM(5..10) knobs, DM(16..37) state (see click_kernel.asm)
"""
import ctypes
import math
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'sharc'))
import sasm  # noqa: E402
import ssim  # noqa: E402

SR = 48000.0
CODE, CODE_END = 0xC4EF8, 0xC5554
DATA = 0xE4850
STATE = dict(ST_STARTED=16, ST_FIRE=17, ST_ACC=18, ST_SUBIDX=19, ST_BEAT=20, ST_ACTIVE=21, ST_SOUND=22,
             ST_C0=23, ST_S0=24, ST_WC0=25, ST_WS0=26, ST_C1=27, ST_S1=28, ST_WC1=29, ST_WS1=30,
             ST_AMP=31, ST_ENV=32, ST_DECAY=33, ST_MIX2=34, ST_AGE=35, ST_TICKS=36, ST_KIND=37)
KNOB = dict(tempo=5, meter=6, accent=7, sound=8, level=9, subdiv=10)
INT_KNOBS = {'meter', 'accent', 'sound', 'subdiv'}
PARAM_ORDER = ['tempo', 'meter', 'accent', 'sound', 'level', 'subdiv']    # = metronome.h M_*
MAX_CYCLES = 3000                         # per 16-sample call; the NAM kernel's budget is 33,000

# The reference's constants (metronome.c); each rounded to float exactly as C does.
PITCH = [[1760.0, 1320.0, 990.0], [1150.0, 880.0, 660.0], [1760.0, 1320.0, 990.0]]
WOOD_RATIO, WOOD_MIX, SUB_GAIN, SILENT = 2.71, 0.45, 0.4, 1e-4
TAU_CLICK, TAU_WOOD, BEEP_GATE, BEEP_RELEASE, MAX_VOICE = 0.003, 0.012, 0.040, 0.005, 0.2


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def fw(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def constants():
    gate = int(f32(f32(BEEP_GATE) * SR))
    release = int(f32(f32(BEEP_RELEASE) * SR))
    max_age = int(f32(f32(MAX_VOICE) * SR))
    period = int(f32(f32(SR * 6000.0) + 0.5))
    decay = [f32(math.exp(-1.0 / (f32(TAU_CLICK) * SR))), f32(math.exp(-1.0 / (f32(TAU_WOOD) * SR))), 1.0]
    osc = []
    for s in range(3):
        for k in range(3):
            hz0 = f32(PITCH[s][k])
            hz1 = f32(hz0 * f32(WOOD_RATIO))
            w0, w1 = 2 * math.pi * hz0 / SR, 2 * math.pi * hz1 / SR
            osc += [f32(math.cos(w0)), f32(math.sin(w0)), f32(math.cos(w1)), f32(math.sin(w1))]
    return dict(gate=gate, max_age=max_age, period=period, relstep=f32(1.0 / release), decay=decay, osc=osc,
                accent=[f32(10.0 ** (k / 20.0)) for k in range(13)], mix2=[0.0, f32(WOOD_MIX), 0.0])


def source():
    c = constants()
    lay, a = [], DATA
    lay.append(('SAVE', a, [0] * 18)); a += 18
    for name, v in (('K_HUNDREDTH', 0.01), ('K_SUBGAIN', SUB_GAIN), ('K_SILENT', SILENT), ('K_RELSTEP', c['relstep'])):
        lay.append((name, a, [fw(f32(v))])); a += 1
    for name, vals in (('T_ACCENT', c['accent']), ('T_OSC', c['osc']), ('T_MIX2', c['mix2']), ('T_DECAY', c['decay'])):
        lay.append((name, a, [fw(v) for v in vals])); a += len(vals)
    equ = [f'.equ {k}, {v}' for k, v in STATE.items()]
    equ += [f'.equ PERIOD, {c["period"]}', f'.equ GATE, {c["gate"]}', f'.equ MAXAGE, {c["max_age"]}']
    equ += [f'.equ {name}, {addr:#x}' for name, addr, _ in lay]
    data = [f'.section dm {DATA:#x}'] + ['.word ' + ', '.join(f'{w:#010x}' for w in words) for _, _, words in lay]
    asm = open(os.path.join(HERE, 'click_kernel.asm')).read()
    assert asm.count('// EQUS') == 1
    return asm.replace('// EQUS', '\n'.join(equ + data)), (DATA, a)


def assemble():
    src, data = source()
    secs, syms = sasm.assemble(src, 'click_kernel.asm')
    pm = [s for s in secs if s.kind == 'pm']
    end = max(s.addr + len(s.words) for s in pm)
    assert end <= CODE_END, f'code ends at {end:#x}, past {CODE_END:#x}'
    return src, secs, syms, end, data


# ------------------------------------------------------------------ the reference, through ctypes

class FxAlgorithm(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('display_name', ctypes.c_char_p), ('state_bytes', ctypes.c_size_t),
                ('params', ctypes.c_void_p), ('n_params', ctypes.c_size_t),
                ('reset', ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_float)),
                ('process', ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_size_t))]


class Reference:
    def __init__(self):
        lib = os.path.join(ROOT, 'effects', 'out', 'libfx.so')
        if not os.path.exists(lib):
            raise SystemExit(f'{lib} missing: make -C effects out/libfx.so')
        self.lib = ctypes.CDLL(lib)
        self.alg = FxAlgorithm.in_dll(self.lib, 'fx_metronome')
        assert self.alg.n_params == len(PARAM_ORDER)

    def new(self):
        st = ctypes.create_string_buffer(self.alg.state_bytes)
        self.alg.reset(st, SR)
        return st

    def process(self, st, knobs, block):
        p = (ctypes.c_float * 12)(*[float(knobs[k]) for k in PARAM_ORDER])
        i = (ctypes.c_float * 16)(*block)
        o = (ctypes.c_float * 16)()
        self.alg.process(st, p, i, o, 16)
        return [fw(v) for v in o]


# ------------------------------------------------------------------ the kernel in ssim

class Rig:
    KEEP = [c for c in range(0x10, 0x50) if c not in (0x11, 0x12, 0x13, 0x1F)]   # nam_multi.Rig's contract

    def __init__(self, secs, syms, data, seed=1):
        self.sim = ssim.Sim()
        self.sim.strict_cbufen = True
        self.sim.load(secs)
        self.syms, self.rnd, self.cycles = syms, random.Random(seed), []
        self.data = data

    def inst(self, k):
        i0 = 0xB3000 + 0x400 * k
        for a in range(145):
            self.sim.wr(i0 + a, 0)
        self.sim.wr(i0 + 3, 1)
        return i0

    def knobs(self, i0, knobs):
        for k, v in knobs.items():
            self.sim.wr(i0 + KNOB[k], int(v) if k in INT_KNOBS else ssim.f2b(float(v)))

    def call(self, i0, block_words, label=''):
        sim, rnd = self.sim, self.rnd
        BI, BO = 0xB8000, 0xB8100
        for k in range(16):
            sim.wr(BI + k, block_words[k])
            sim.wr(BO + k, rnd.getrandbits(32))
        for r in range(16):
            sim.setR(r, rnd.getrandbits(32))
            sim.alt[r] = rnd.getrandbits(32)
        for c in self.KEEP + [0x1F]:
            if 0x30 <= c < 0x40:
                sim.set(c, rnd.getrandbits(8) or 1)
            elif c >= 0x40:
                sim.u[c] = rnd.getrandbits(32) & 0xFFFFF
            elif c not in (0x10, 0x18):
                sim.set(c, rnd.getrandbits(32) & 0xFFFFF)
        for b, v in ((0x40, i0), (0x41, BI), (0x42, BO)):
            sim.set(b, v)
        sim.u[ssim.U_MODE1] |= 0x1000000
        mode1 = sim.u[ssim.U_MODE1]
        before = ([sim.R(r) for r in range(16)], list(sim.alt[:16]), {c: sim.get(c) for c in self.KEEP})
        writes = []
        wr = sim.wr

        def logged(a, v):
            writes.append(a)
            wr(a, v)
        sim.wr = logged
        try:
            cyc = sim.call(self.syms['CLICK_ENTRY'], limit=100_000)
        finally:
            sim.wr = wr
        self.cycles.append(cyc)
        bad = [f'R{r}' for r in range(16) if sim.R(r) != before[0][r]]
        bad += [f'S{r}' for r in range(16) if sim.alt[r] != before[1][r]]
        bad += [f'{c:#x}' for c in self.KEEP
                if sim.get(c) != before[2][c] and not (0x30 <= c < 0x40 and c != 0x37 and sim.get(c) == 0)]
        if sim.u[ssim.U_MODE1] != mode1:
            bad.append('MODE1')
        if bad:
            raise AssertionError(f'{label}: registers changed: {bad}')
        if sim.loops or sim.pcstk:
            raise AssertionError(f'{label}: returns with the loop or PC stack not empty')
        allowed = [(BO, BO + 16), (i0 + 16, i0 + 38), (self.data[0], self.data[0] + 18)]
        stray = [a for a in writes if not any(lo <= a < hi for lo, hi in allowed)]
        if stray:
            raise AssertionError(f'{label}: wrote outside its memory: {[hex(a) for a in stray[:5]]}')
        return [sim.rd(BO + k) for k in range(16)]


def signal(n, seed):
    """A guitar-like input as float words: decaying plucks plus a little noise."""
    r = random.Random(seed)
    out, ph, amp = [], 0.0, 0.0
    for i in range(n):
        if i % 24000 == 0:
            amp, f = 0.6, r.choice([82.41, 110.0, 146.83, 196.0, 246.94, 329.63])
        amp *= 0.99995
        ph += 2 * math.pi * f / SR
        out.append(fw(f32(amp * math.sin(ph) + 0.01 * r.uniform(-1, 1))))
    return out


def check(seconds=2.0):
    src, secs, syms, end, data = assemble()
    ref = Reference()
    rig = Rig(secs, syms, data)
    nblk = int(seconds * SR) // 16
    print(f'code {CODE:#x}..{end:#x} ({end - CODE} instructions), data {data[0]:#x}..{data[1]:#x}')
    cases = [
        dict(tempo=120, meter=4, accent=6, sound=0, level=50, subdiv=1),
        dict(tempo=137.5, meter=3, accent=12, sound=1, level=100, subdiv=2),
        dict(tempo=300, meter=5, accent=0, sound=2, level=75, subdiv=4),
        dict(tempo=20, meter=2, accent=3, sound=1, level=30, subdiv=3),
        dict(tempo=97.31, meter=4, accent=12, sound=0, level=0, subdiv=1),          # level 0: dry
        dict(tempo=500, meter=9, accent=40, sound=7, level=250, subdiv=0),          # out of range: clamped
    ]
    total = 0
    for n, kn in enumerate(cases):
        i0 = rig.inst(0)
        rig.knobs(i0, kn)
        st = ref.new()
        x = signal(nblk * 16, n)
        for b in range(nblk):
            blk = x[16 * b:16 * b + 16]
            got = rig.call(i0, blk, f'case {n} block {b}')
            want = ref.process(st, kn, [ssim.b2f(v) for v in blk])
            if got != want:
                k = next(j for j in range(16) if got[j] != want[j])
                raise AssertionError(f'case {n} {kn}: block {b} sample {k}: kernel {got[k]:#010x} '
                                     f'({ssim.b2f(got[k])}), reference {want[k]:#010x} ({ssim.b2f(want[k])})')
            total += 16
        print(f'  case {n}: {nblk * 16} samples identical  {kn}')

    r = random.Random(5)                       # knobs moving, two instances interleaved
    ia, ib = rig.inst(0), rig.inst(1)
    sa, sb = ref.new(), ref.new()
    xa, xb = signal(nblk * 16, 11), signal(nblk * 16, 12)
    for b in range(nblk):
        if b % 300 == 0:
            ka = dict(tempo=round(r.uniform(20, 300), 2), meter=r.randint(2, 5), accent=r.randint(0, 12),
                      sound=r.randint(0, 2), level=round(r.uniform(0, 100), 1), subdiv=r.randint(1, 4))
            kb = dict(tempo=round(r.uniform(20, 300), 2), meter=r.randint(2, 5), accent=r.randint(0, 12),
                      sound=r.randint(0, 2), level=round(r.uniform(0, 100), 1), subdiv=r.randint(1, 4))
            rig.knobs(ia, ka)
            rig.knobs(ib, kb)
        for i0, st, kn, x in ((ia, sa, ka, xa), (ib, sb, kb, xb)):
            blk = x[16 * b:16 * b + 16]
            got = rig.call(i0, blk, f'moving block {b}')
            want = ref.process(st, kn, [ssim.b2f(v) for v in blk])
            if got != want:
                raise AssertionError(f'moving knobs, block {b}: kernel and reference differ')
            total += 16
    print(f'  two instances, knobs moving every 100 ms: {2 * nblk * 16} samples identical')
    worst, mean = max(rig.cycles), sum(rig.cycles) / len(rig.cycles)
    print(f'{total} samples identical to the reference; cycles per 16-sample call: worst {worst}, mean {mean:.0f} '
          f'(budget {MAX_CYCLES}; about 150,000 per call at 450 MHz)')
    assert worst <= MAX_CYCLES, f'worst case {worst} cycles over the budget {MAX_CYCLES}'
    return dict(worst=worst, mean=mean, code=end - CODE)


def main():
    a = sys.argv[1:]
    if '-o' in a:
        src, *_ = assemble()
        open(a[a.index('-o') + 1], 'w').write(src)
    if '--check' in a:
        secs = float(a[a.index('--seconds') + 1]) if '--seconds' in a else 2.0
        try:
            check(secs)
        except AssertionError as ex:
            sys.exit(f'click_kernel.py: CHECK FAILED: {ex}')
        print('CHECK OK')
    if not a:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
