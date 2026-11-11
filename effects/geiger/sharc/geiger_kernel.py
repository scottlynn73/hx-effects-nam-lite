#!/usr/bin/env python3
"""geiger_kernel.py - build and check the Geiger kernel (geiger_kernel.asm) for the HX Effects SHARC.

usage: geiger_kernel.py [-o out.asm] [--check] [--seconds S] [--place b2|b3]

  --check   run it in ssim (tools/sharc) against the C reference (effects/geiger, through
            effects/out/libfx.so: `make -C effects out/libfx.so`), requiring every output word to be
            identical, the register contract (R0-R15, the alternate set, every DAG register except I15,
            MODE1), no instance-block writes but P_SLOT, and a cycle budget.

The curve tables are read from the C library itself (geiger_table), so they are the reference's to
the bit. Constants are rounded exactly as geiger.c rounds them.
"""
import ctypes
import math
import os
import random
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'sharc'))
import sasm  # noqa: E402
import ssim  # noqa: E402

SR = 48000.0
# placements: 'b2' a Geiger-only image (NAM's regions); 'b3' is set by the all-in-one build
PLACES = {'b2': (0xC4EF8, 0xC5554, 0xE4850)}
EXT_CURVES = None                           # the curve tables' address when they are not in the kernel's data
KNOB = dict(gain=5, rate=6, bits=7, curve=8, tone=9, output=10, mix=11, aa=13)
INT_KNOBS = {'bits', 'curve', 'aa'}
PARAM_ORDER = ['gain', 'rate', 'bits', 'curve', 'tone', 'output', 'mix', 'aa']    # = geiger.h G_*
_ST = ['PRIMED', 'GAINT', 'OUTT', 'MIXT', 'INC', 'AAA', 'TONEA', 'Q', 'QI', 'TAB', 'AAON', 'GGAIN', 'GOUT',
       'GMIX', 'DCINX', 'DCINY', 'DCOUTX', 'DCOUTY', 'AA1', 'AA2', 'PHASE', 'HELD', 'TONEZ']
STATE = {f'ST_{n}': 2 + k for k, n in enumerate(_ST)}
NSLOTS, NSTATE, SLOTW, STALE, P_SLOT = 8, len(_ST), 2 + len(_ST), 64, 12
TABLE = 64                                  # = geiger.h GEIGER_TABLE (a power of 2)
MAX_CYCLES = 4000


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def fw(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


_LIB = None


def lib():
    """The C reference library, rebuilt first if a source changed: the curve tables and the
    reference both come from it, so a stale library (say, built with another table size) would
    make the kernel and the check agree with the wrong effect."""
    global _LIB
    if _LIB is None:
        import subprocess
        r = subprocess.run(['make', '-s', '-C', os.path.join(ROOT, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'could not build effects/out/libfx.so:\n{r.stderr}')
        _LIB = ctypes.CDLL(os.path.join(ROOT, 'effects', 'out', 'libfx.so'))
    return _LIB


def tables():
    L = lib()
    L.geiger_table.restype = ctypes.POINTER(ctypes.c_float)
    out = []
    for c in range(16):
        t = L.geiger_table(c)
        out += [fw(t[i]) for i in range(TABLE + 1)]
    return out


def constants():
    one = np.float32(1.0)
    return dict(
        K_LN10_20=f32(0.115129255), K_LN100=f32(4.60517019), K_INV_SR=f32(1.0 / SR), K_NEG_W=f32(-2 * math.pi / SR),
        K_04=f32(0.4), K_TOP=f32(f32(0.45) * SR), K_DC_R=f32(1.0 - f32(2 * math.pi * 10.0 / SR)), K_EPS=f32(1e-6),
        K_SMK=f32(1.0 - math.exp(-1.0 / (0.005 * SR))), K_HALFT=float(TABLE // 2),
        K_C6=float(one / np.float32(720.0)), K_C5=float(one / np.float32(120.0)),
        K_C4=float(one / np.float32(24.0)), K_C3=float(one / np.float32(6.0)))


def source(place='b2'):
    code, _, data0 = PLACES[place]
    lay, a = [], data0
    lay.append(('SAVE', a, [0] * 21)); a += 21
    lay.append(('G_CALLS', a, [0])); a += 1
    for name, v in constants().items():
        lay.append((name, a, [fw(v)])); a += 1
    q = [float(2 ** max(b - 1, 0)) for b in range(17)]
    lay.append(('T_Q', a, [fw(v) for v in q])); a += 17
    lay.append(('T_QI', a, [fw(float(np.float32(1.0) / np.float32(v))) for v in q])); a += 17
    if EXT_CURVES is None:
        curves = tables()
        lay.append(('T_CURVES', a, curves)); a += len(curves)
    else:
        lay.append(('T_CURVES', EXT_CURVES, []))      # elsewhere (inside Blob 0, in DDR2): no words here
    slots = a + NSLOTS
    lay.append(('T_SLOTBASE', a, [slots + SLOTW * k for k in range(NSLOTS)])); a += NSLOTS
    lay.append(('SLOTS', a, [0] * (SLOTW * NSLOTS))); a += SLOTW * NSLOTS
    equ = [f'.equ {k}, {v}' for k, v in STATE.items()]
    equ += [f'.equ TABLE, {TABLE}', f'.equ TSHIFT, {TABLE.bit_length() - 1}']
    equ += ['.equ S_OWNER, 0', '.equ S_LAST, 1', f'.equ P_SLOT, {P_SLOT}', f'.equ NSLOTS, {NSLOTS}',
            f'.equ NSTATE, {NSTATE}', f'.equ STALE, {STALE}']
    equ += [f'.equ {name}, {addr:#x}' for name, addr, _ in lay]
    data = [f'.section dm {data0:#x}'] + ['.word ' + ', '.join(f'{w:#010x}' for w in words) for _, _, words in lay if words]
    asm = open(os.path.join(HERE, 'geiger_kernel.asm')).read()
    assert asm.count('// EQUS') == 1 and asm.count('.section pm 0x0c4ef8') == 1
    asm = asm.replace('.section pm 0x0c4ef8', f'.section pm {code:#08x}')
    return asm.replace('// EQUS', '\n'.join(equ + data)), (data0, a)


def assemble(place='b2'):
    src, data = source(place)
    secs, syms = sasm.assemble(src, 'geiger_kernel.asm')
    pm = [s for s in secs if s.kind == 'pm']
    end = max(s.addr + len(s.words) for s in pm)
    code, code_end, _ = PLACES[place]
    assert min(s.addr for s in pm) == code and end <= code_end, f'code {code:#x}..{end:#x}, past {code_end:#x}'
    base = code & ~0xFFFF
    if data[0] & ~0xFFFF == base:
        assert data[1] <= base + (code - base) * 3 // 2, f'data to {data[1]:#x} runs into the code'
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
        self.lib = lib()
        self.alg = FxAlgorithm.in_dll(self.lib, 'fx_geiger')
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
    KEEP = [c for c in range(0x10, 0x50) if c != 0x1F]

    def __init__(self, secs, syms, data, seed=1):
        self.sim = ssim.Sim()
        self.sim.strict_cbufen = True
        self.sim.load(secs)
        self.syms, self.rnd, self.cycles, self.data = syms, random.Random(seed), [], data

    def inst(self, k):
        i0 = 0xB3000 + 0x400 * k
        for a in range(145):
            self.sim.wr(i0 + a, 0)
        self.sim.wr(i0 + 3, 1)                         # as on the unit: non-zero while the block is on
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
        sim.set(0x13, rnd.getrandbits(32) & 0xFFFFF)
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
            cyc = sim.call(self.syms['GEIGER_ENTRY'], limit=200_000)
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
        lo = self.syms['SAVE']
        allowed = [(BO, BO + 16), (i0 + P_SLOT, i0 + P_SLOT + 1), (lo, lo + 22),
                   (self.syms['SLOTS'], self.syms['SLOTS'] + SLOTW * NSLOTS)]
        stray = [a for a in writes if not any(x <= a < y for x, y in allowed)]
        if stray:
            raise AssertionError(f'{label}: wrote outside its memory: {[hex(a) for a in stray[:5]]}')
        return [sim.rd(BO + k) for k in range(16)]


def signal(n, seed, amp=0.6):
    r = random.Random(seed)
    out, ph, a, f = [], 0.0, 0.0, 110.0
    for i in range(n):
        if i % 24000 == 0:
            a, f = amp, r.choice([82.41, 110.0, 146.83, 196.0, 246.94, 329.63])
        a *= 0.99995
        ph += 2 * math.pi * f / SR
        out.append(fw(f32(a * math.sin(ph) + 0.3 * a * math.sin(3.01 * ph) + 0.01 * r.uniform(-1, 1))))
    return out


def check(seconds=1.0, place='b2'):
    src, secs, syms, end, data = assemble(place)
    ref = Reference()
    rig = Rig(secs, syms, data)
    if EXT_CURVES is not None:                       # as the image's Blob 0 provides them
        for k, w in enumerate(tables()):
            rig.sim.dm[EXT_CURVES + k] = w
    nblk = int(seconds * SR) // 16
    code = PLACES[place][0]
    print(f'[{place}] code {code:#x}..{end:#x} ({end - code} instructions), data {data[0]:#x}..{data[1]:#x}')
    cases = [
        dict(gain=6, rate=12000, bits=8, curve=0, tone=0.8, output=-6, mix=1.0, aa=0),        # the defaults
        dict(gain=12, rate=6000, bits=4, curve=0, tone=0.7, output=-6, mix=1.0, aa=0),        # crush
        dict(gain=24, rate=48000, bits=16, curve=4, tone=0.9, output=-9, mix=1.0, aa=1),      # fold
        dict(gain=18, rate=3000, bits=6, curve=13, tone=0.35, output=-3, mix=1.0, aa=0),      # radio
        dict(gain=36, rate=250, bits=1, curve=12, tone=0.0, output=12, mix=0.5, aa=1),        # extremes
        dict(gain=0, rate=47000.5, bits=16, curve=7, tone=1.0, output=-36, mix=0.0, aa=1),    # mix 0: dry
        dict(gain=50, rate=99999, bits=40, curve=30, tone=2.0, output=20, mix=3.0, aa=5),     # out of range
    ] + [dict(gain=10, rate=9000, bits=5, curve=c, tone=0.6, output=-3, mix=0.8, aa=c & 1) for c in range(16)]
    total = 0
    for n, kn in enumerate(cases):
        i0 = rig.inst(0)
        rig.knobs(i0, kn)
        st = ref.new()
        x = signal(nblk * 16, n, amp=1.5 if n == 4 else 0.6)
        for b in range(nblk):
            blk = x[16 * b:16 * b + 16]
            got = rig.call(i0, blk, f'case {n} block {b}')
            want = ref.process(st, kn, [ssim.b2f(v) for v in blk])
            if got != want:
                k = next(j for j in range(16) if got[j] != want[j])
                raise AssertionError(f'case {n} {kn}: block {b} sample {k}: kernel {got[k]:#010x} '
                                     f'({ssim.b2f(got[k])}), reference {want[k]:#010x} ({ssim.b2f(want[k])})')
            total += 16
    print(f'  {len(cases)} settings (the variants, every curve, extremes, Mix 0, out of range): identical')

    r = random.Random(5)                               # knobs moving, two instances interleaved
    ia, ib = rig.inst(0), rig.inst(1)
    sa, sb = ref.new(), ref.new()
    xa, xb = signal(nblk * 16, 11), signal(nblk * 16, 12)

    def rnd_knobs():
        return dict(gain=r.uniform(0, 36), rate=r.uniform(250, 48000), bits=r.randint(1, 16), curve=r.randint(0, 15),
                    tone=r.uniform(0, 1), output=r.uniform(-36, 12), mix=r.uniform(0, 1), aa=r.randint(0, 1))
    for b in range(nblk):
        if b % 300 == 0:
            ka, kb = rnd_knobs(), rnd_knobs()
            rig.knobs(ia, ka)
            rig.knobs(ib, kb)
        for i0, st, kn, x in ((ia, sa, ka, xa), (ib, sb, kb, xb)):
            blk = x[16 * b:16 * b + 16]
            if rig.call(i0, blk, f'moving block {b}') != ref.process(st, kn, [ssim.b2f(v) for v in blk]):
                raise AssertionError(f'moving knobs, block {b}: kernel and reference differ')
            total += 16
    print('  two instances, every knob moving every 100 ms: identical')

    kn = cases[1]                                      # a block deleted and re-created in place
    i0 = rig.inst(2)
    rig.knobs(i0, kn)
    x = signal(400 * 16, 21)
    st = ref.new()
    for b in range(400):
        if b == 200:
            i0 = rig.inst(2)
            rig.knobs(i0, kn)
            st = ref.new()
        blk = x[16 * b:16 * b + 16]
        if rig.call(i0, blk, f're-created block {b}') != ref.process(st, kn, [ssim.b2f(v) for v in blk]):
            raise AssertionError(f're-created block: block {b} differs')
    total += 400 * 16
    print('  a block re-created in place starts from reset: identical')

    worst, mean = max(rig.cycles), sum(rig.cycles) / len(rig.cycles)
    print(f'{total} samples identical to the reference; cycles per 16-sample call: worst {worst}, mean {mean:.0f} '
          f'(budget {MAX_CYCLES}; about 150,000 per call at 450 MHz)')
    assert worst <= MAX_CYCLES, f'worst case {worst} cycles over the budget {MAX_CYCLES}'


def main():
    a = sys.argv[1:]
    place = a[a.index('--place') + 1] if '--place' in a else 'b2'
    if '-o' in a:
        src, *_ = assemble(place)
        open(a[a.index('-o') + 1], 'w').write(src)
    if '--check' in a:
        secs = float(a[a.index('--seconds') + 1]) if '--seconds' in a else 1.0
        try:
            check(secs, place)
        except AssertionError as ex:
            sys.exit(f'geiger_kernel.py: CHECK FAILED: {ex}')
        print('CHECK OK')
    if not a:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
