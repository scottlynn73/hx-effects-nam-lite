"""kernel_rig.py - shared pieces for the effect kernels' builders and checks (Commander, Corrupt).

Geiger's and Click's builders (geiger_kernel.py, click_kernel.py) predate this and keep their own copies.

A kernel here is described by a Spec: its .asm file, entry symbol, knob words, slot state names and
data constants. The builder lays the data out at a place's data address (SAVE, G_CALLS, the
constants, any tables, the slot pointer table and the slots), substitutes it at the .asm's "// EQUS"
line and moves the code to the place's address. The check runs the kernel in ssim against the C
reference (effects/out/libfx.so through ctypes), word for word, with the register contract (R0-R15,
the alternate set, every DAG register but I15, MODE1), the writes it may make (outputs, P_SLOT, SAVE,
its slots) and a cycle budget enforced.
"""
import ctypes
import math
import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'sharc'))
import sasm  # noqa: E402
import ssim  # noqa: E402

SR = 48000.0
P_SLOT, STALE = 12, 64


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def fw(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


_LIB = None


def lib():
    """The C reference library, rebuilt first if a source changed."""
    global _LIB
    if _LIB is None:
        r = subprocess.run(['make', '-s', '-C', os.path.join(ROOT, 'effects'), 'out/libfx.so'], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'could not build effects/out/libfx.so:\n{r.stderr}')
        _LIB = ctypes.CDLL(os.path.join(ROOT, 'effects', 'out', 'libfx.so'))
    return _LIB


def exp_constants():
    """geiger_exp's Taylor coefficients, rounded as the C source rounds 1.0f / 720.0f etc."""
    return dict(K_C6=f32(1.0 / f32(720.0)), K_C5=f32(1.0 / f32(120.0)), K_C4=f32(1.0 / f32(24.0)), K_C3=f32(1.0 / f32(6.0)))


class Spec:
    def __init__(self, name, asm, entry, knobs, int_knobs, order, state, constants, nslots=8, tables=(), max_cycles=4000,
                 extra_equ=()):
        self.name, self.asm, self.entry = name, asm, entry
        self.knobs, self.int_knobs, self.order = knobs, set(int_knobs), order
        self.state = {f'ST_{n}': 2 + k for k, n in enumerate(state)}
        self.nstate, self.slotw, self.nslots = len(state), 2 + len(state), nslots
        self.constants, self.tables, self.max_cycles, self.extra_equ = constants, tables, max_cycles, list(extra_equ)
        self.places = {}

    def source(self, place):
        code, _, data0 = self.places[place]
        lay, a = [], data0
        lay.append(('SAVE', a, [0] * 21)); a += 21
        lay.append(('G_CALLS', a, [0])); a += 1
        for name, v in self.constants.items():
            lay.append((name, a, [fw(v)])); a += 1
        for name, words in self.tables:
            lay.append((name, a, list(words))); a += len(words)
        slots = a + self.nslots
        lay.append(('T_SLOTBASE', a, [slots + self.slotw * k for k in range(self.nslots)])); a += self.nslots
        lay.append(('SLOTS', a, [0] * (self.slotw * self.nslots))); a += self.slotw * self.nslots
        equ = [f'.equ {k}, {v}' for k, v in self.state.items()] + self.extra_equ
        equ += ['.equ S_OWNER, 0', '.equ S_LAST, 1', f'.equ P_SLOT, {P_SLOT}', f'.equ NSLOTS, {self.nslots}',
                f'.equ NSTATE, {self.nstate}', f'.equ STALE, {STALE}']
        equ += [f'.equ {name}, {addr:#x}' for name, addr, _ in lay]
        data = [f'.section dm {data0:#x}'] + ['.word ' + ', '.join(f'{w:#010x}' for w in words) for _, _, words in lay]
        asm = open(self.asm).read()
        assert asm.count('// EQUS') == 1 and asm.count('.section pm 0x0c4ef8') == 1
        asm = asm.replace('.section pm 0x0c4ef8', f'.section pm {code:#08x}')
        return asm.replace('// EQUS', '\n'.join(equ + data)), (data0, a)

    def assemble(self, place):
        src, data = self.source(place)
        secs, syms = sasm.assemble(src, os.path.basename(self.asm))
        pm = [s for s in secs if s.kind == 'pm']
        end = max(s.addr + len(s.words) for s in pm)
        code, code_end, _ = self.places[place]
        assert min(s.addr for s in pm) == code and end <= code_end, f'{self.name}: code {code:#x}..{end:#x}, past {code_end:#x}'
        base = code & ~0xFFFF
        if data[0] & ~0xFFFF == base:
            assert data[1] <= base + (code - base) * 3 // 2, f'{self.name}: data to {data[1]:#x} runs into the code'
        return src, secs, syms, end, data

    def data_size(self):
        """Words of data the layout takes (independent of the place)."""
        return 21 + 1 + len(self.constants) + sum(len(w) for _, w in self.tables) + self.nslots * (1 + self.slotw)


# ------------------------------------------------------------------ the reference, through ctypes

class FxAlgorithm(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('display_name', ctypes.c_char_p), ('state_bytes', ctypes.c_size_t),
                ('params', ctypes.c_void_p), ('n_params', ctypes.c_size_t),
                ('reset', ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_float)),
                ('process', ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_size_t))]


class Reference:
    def __init__(self, spec):
        self.lib, self.order = lib(), spec.order
        # the reference flushes denormals as the SHARC does, but only inside its own calls: left on, the
        # mode would change this process's other float arithmetic (an image build's, say)
        assert self.lib.fx_set_ftz(0) == 1, 'cannot flush denormals to zero here (as the SHARC does)'
        self.alg = FxAlgorithm.in_dll(self.lib, f'fx_{spec.name}')
        assert self.alg.n_params == len(self.order)

    def new(self):
        st = ctypes.create_string_buffer(self.alg.state_bytes)
        self.lib.fx_set_ftz(1)
        try:
            self.alg.reset(st, SR)
        finally:
            self.lib.fx_set_ftz(0)
        return st

    def process(self, st, knobs, block):
        p = (ctypes.c_float * 12)(*[float(knobs[k]) for k in self.order])
        i = (ctypes.c_float * 16)(*block)
        o = (ctypes.c_float * 16)()
        self.lib.fx_set_ftz(1)
        try:
            self.alg.process(st, p, i, o, 16)
        finally:
            self.lib.fx_set_ftz(0)
        return [fw(v) for v in o]


# ------------------------------------------------------------------ the kernel in ssim

class Rig:
    KEEP = [c for c in range(0x10, 0x50) if c != 0x1F]

    def __init__(self, spec, secs, syms, seed=1):
        self.spec = spec
        self.sim = ssim.Sim()
        self.sim.strict_cbufen = True
        self.sim.load(secs)
        self.syms, self.rnd, self.cycles = syms, random.Random(seed), []
        g = random.Random(seed + 1000)
        for lo, hi in getattr(spec, 'garbage', []):      # memory the kernel must not read before writing
            for a in range(lo, hi):
                self.sim.dm[a] = g.getrandbits(32)

    def inst(self, k):
        i0 = 0xB3000 + 0x400 * k
        for a in range(145):
            self.sim.wr(i0 + a, 0)
        self.sim.wr(i0 + 3, 1)                         # as on the unit: non-zero while the block is on
        return i0

    def knobs(self, i0, knobs):
        for k, v in knobs.items():
            self.sim.wr(i0 + self.spec.knobs[k], int(v) if k in self.spec.int_knobs else ssim.f2b(float(v)))

    def call(self, i0, block_words, label=''):
        sim, rnd, sp = self.sim, self.rnd, self.spec
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
            cyc = sim.call(self.syms[sp.entry], limit=200_000)
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
                   (self.syms['SLOTS'], self.syms['SLOTS'] + sp.slotw * sp.nslots)] + list(getattr(sp, 'extra_writes', []))
        stray = [a for a in writes if not any(x <= a < y for x, y in allowed)]
        if stray:
            raise AssertionError(f'{label}: wrote outside its memory: {[hex(a) for a in stray[:5]]}')
        return [sim.rd(BO + k) for k in range(16)]


def signal(n, seed, amp=0.6, notes=(82.41, 110.0, 146.83, 196.0, 246.94, 329.63), every=24000, chord=False):
    """A guitar-like test signal: notes (or two-note chords) that decay, with a little noise."""
    r = random.Random(seed)
    out, ph, ph2, a, f, f2 = [], 0.0, 0.0, 0.0, 110.0, 165.0
    for i in range(n):
        if i % every == 0:
            a, f = amp, r.choice(notes)
            f2 = f * r.choice([1.5, 1.26, 2.0])
        a *= 0.99995
        ph += 2 * math.pi * f / SR
        ph2 += 2 * math.pi * f2 / SR
        v = a * math.sin(ph) + 0.3 * a * math.sin(3.01 * ph) + 0.01 * r.uniform(-1, 1)
        if chord:
            v += 0.7 * a * math.sin(ph2)
        out.append(fw(f32(v)))
    return out


def check(spec, place, cases, rnd_knobs, seconds=1.0, signals=None):
    """cases: knob dicts, each run on its own instance from reset; then two instances with knobs moving;
    then a block re-created in place. signals(n, case) -> input words, default signal()."""
    src, secs, syms, end, data = spec.assemble(place)
    ref = Reference(spec)
    rig = Rig(spec, secs, syms)
    nblk = int(seconds * SR) // 16
    code = spec.places[place][0]
    sig = signals or (lambda n, k: signal(n, k, amp=1.5 if k == 4 else 0.6, chord=k % 3 == 2))
    print(f'[{spec.name} {place}] code {code:#x}..{end:#x} ({end - code} instructions), data {data[0]:#x}..{data[1]:#x}')
    total = 0
    for n, kn in enumerate(cases):
        i0 = rig.inst(0)
        rig.knobs(i0, kn)
        st = ref.new()
        x = sig(nblk * 16, n)
        for b in range(nblk):
            blk = x[16 * b:16 * b + 16]
            got = rig.call(i0, blk, f'case {n} block {b}')
            want = ref.process(st, kn, [ssim.b2f(v) for v in blk])
            if got != want:
                k = next(j for j in range(16) if got[j] != want[j])
                raise AssertionError(f'case {n} {kn}: block {b} sample {k}: kernel {got[k]:#010x} '
                                     f'({ssim.b2f(got[k])}), reference {want[k]:#010x} ({ssim.b2f(want[k])})')
            total += 16
    print(f'  {len(cases)} settings: identical')

    r = random.Random(5)
    ia, ib = rig.inst(0), rig.inst(1)
    sa, sb = ref.new(), ref.new()
    xa, xb = signal(nblk * 16, 11, chord=True), signal(nblk * 16, 12)
    for b in range(nblk):
        if b % 300 == 0:
            ka, kb = rnd_knobs(r), rnd_knobs(r)
            rig.knobs(ia, ka)
            rig.knobs(ib, kb)
        for i0, st, kn, x in ((ia, sa, ka, xa), (ib, sb, kb, xb)):
            blk = x[16 * b:16 * b + 16]
            if rig.call(i0, blk, f'moving block {b}') != ref.process(st, kn, [ssim.b2f(v) for v in blk]):
                raise AssertionError(f'moving knobs, block {b}: kernel and reference differ')
            total += 16
    print('  two instances, every knob moving every 100 ms: identical')

    kn = cases[0]
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
          f'(budget {spec.max_cycles}; about 150,000 per call at 450 MHz)')
    assert worst <= spec.max_cycles, f'worst case {worst} cycles over the budget {spec.max_cycles}'
    return worst


def main(spec, cases, rnd_knobs, doc):
    a = sys.argv[1:]
    place = a[a.index('--place') + 1] if '--place' in a else 'b2'
    if '-o' in a:
        src, *_ = spec.assemble(place)
        open(a[a.index('-o') + 1], 'w').write(src)
    if '--check' in a:
        secs = float(a[a.index('--seconds') + 1]) if '--seconds' in a else 1.0
        try:
            check(spec, place, cases, rnd_knobs, secs)
        except AssertionError as ex:
            sys.exit(f'{spec.name}_kernel.py: CHECK FAILED: {ex}')
        print('CHECK OK')
    if not a:
        sys.exit(doc)
