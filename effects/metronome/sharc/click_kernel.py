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
_ST = ['CHK', 'STARTED', 'FIRE', 'ACC', 'SUBIDX', 'BEAT', 'ACTIVE', 'SOUND', 'C0', 'S0', 'WC0', 'WS0', 'C1', 'S1',
       'WC1', 'WS1', 'AMP', 'ENV', 'DECAY', 'MIX2', 'AGE', 'TICKS', 'KIND']
STATE = {f'ST_{n}': 2 + k for k, n in enumerate(_ST)}          # offsets in a slot, after OWNER and LAST
NSLOTS, NSTATE, SLOTW, STALE, P_SLOT = 8, len(_ST), 2 + len(_ST), 64, 12
KNOB = dict(time=5, meter=6, accent=7, sound=8, level=9, subdiv=10)
INT_KNOBS = {'meter', 'accent', 'sound', 'subdiv'}
PARAM_ORDER = ['time', 'meter', 'accent', 'sound', 'level', 'subdiv']    # = metronome.h M_*
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


BYPASS = """    // ---- DM(3): non-zero the whole time the block is on (probe builds on the unit); the
    //      footswitch did not change it. Not a usable bypass flag: ignored, never written.
k_on:
"""
PROBE = """    // ---- PROBE (diagnostic build), never writes DM(3):
    // speed shows DM(3)'s value: 0 -> 60 BPM, 1 -> 120, 2 -> 180, else 240 (quarters);
    // each change in the other instance words (all but the knobs 5..10 and P_SLOT 12)
    // steps the sound Click -> Wood -> Beep -> Click (the Sound knob is ignored).
    R8 = DM(3, I0);
    DM(G_PSOUND) = R8;
    R14 = DM(0, I0);
    R15 = DM(1, I0);
    R14 = R14 + R15;
    R15 = DM(2, I0);
    R14 = R14 + R15;
    R15 = DM(4, I0);
    R14 = R14 + R15;
    R15 = DM(11, I0);
    R14 = R14 + R15;
    R15 = 13;
    R15 = R10 + R15;
    I4 = R15;
    R12 = 132;
p_sum:
    R15 = DM(I4, 1);
    R14 = R14 + R15;
    R12 = R12 - 1;
    IF NE JUMP p_sum;
    R15 = DM(ST_CHK, I3);
    COMP(R14, R15);
    IF EQ JUMP k_on;
    DM(ST_CHK, I3) = R14;
    R15 = DM(ST_STARTED, I3);           // a fresh slot's first sum is not a change
    R15 = PASS R15;
    IF EQ JUMP k_on;
    R15 = DM(G_PCOUNT);
    R15 = R15 + 1;
    R13 = 3;
    COMP(R15, R13);
    IF GE R15 = R15 - R13;
    DM(G_PCOUNT) = R15;
k_on:
"""
SOUND = """    R8 = 2;
    R3 = MIN(R3, R8);
"""
SUBDIV = """    R8 = 4;
    R2 = MIN(R2, R8);
"""
PROBE_TEMPO = """    R2 = 1;                             // PROBE: DM(3) 0/1/2/other -> 60/120/180/240 BPM
    R8 = DM(G_PSOUND);
    R0 = 6000;
    R8 = PASS R8;
    IF EQ JUMP p_tempo;
    R0 = 12000;
    R9 = 1;
    COMP(R8, R9);
    IF EQ JUMP p_tempo;
    R0 = 18000;
    R9 = 2;
    COMP(R8, R9);
    IF EQ JUMP p_tempo;
    R0 = 24000;
p_tempo:
"""


def source(probe=False):
    c = constants()
    lay, a = [], DATA
    lay.append(('SAVE', a, [0] * 21)); a += 21
    lay.append(('G_CALLS', a, [0])); a += 1
    lay.append(('G_PSOUND', a, [0])); a += 1
    lay.append(('G_PCOUNT', a, [0])); a += 1
    slots = a + NSLOTS                         # SLOTS follows the table
    lay.append(('T_SLOTBASE', a, [slots + SLOTW * k for k in range(NSLOTS)])); a += NSLOTS
    lay.append(('SLOTS', a, [0] * (SLOTW * NSLOTS))); a += SLOTW * NSLOTS
    for name, v in (('K_TMIN', 0.1), ('K_SUBGAIN', SUB_GAIN), ('K_SILENT', SILENT), ('K_RELSTEP', c['relstep'])):
        lay.append((name, a, [fw(f32(v))])); a += 1
    for name, vals in (('T_ACCENT', c['accent']), ('T_OSC', c['osc']), ('T_MIX2', c['mix2']), ('T_DECAY', c['decay'])):
        lay.append((name, a, [fw(v) for v in vals])); a += len(vals)
    equ = [f'.equ {k}, {v}' for k, v in STATE.items()]
    equ += ['.equ S_OWNER, 0', '.equ S_LAST, 1', f'.equ P_SLOT, {P_SLOT}', f'.equ NSLOTS, {NSLOTS}',
            f'.equ NSTATE, {NSTATE}', f'.equ STALE, {STALE}']
    equ += ['.equ BPM100_NUM, 2304000000', f'.equ PERIOD, {c["period"]}', f'.equ GATE, {c["gate"]}', f'.equ MAXAGE, {c["max_age"]}']
    equ += [f'.equ {name}, {addr:#x}' for name, addr, _ in lay]
    data = [f'.section dm {DATA:#x}'] + ['.word ' + ', '.join(f'{w:#010x}' for w in words) for _, _, words in lay]
    asm = open(os.path.join(HERE, 'click_kernel.asm')).read()
    assert asm.count('// EQUS') == 1 and asm.count(BYPASS) == 1 and asm.count(SOUND) == 1 and asm.count(SUBDIV) == 1
    if probe:
        asm = asm.replace(BYPASS, PROBE).replace(SOUND, SOUND + "    R3 = DM(G_PCOUNT);                  // PROBE: the change count picks the sound\n")
        asm = asm.replace(SUBDIV, SUBDIV + PROBE_TEMPO)
    return asm.replace('// EQUS', '\n'.join(equ + data)), (DATA, a)


def assemble(probe=False):
    src, data = source(probe)
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
    # nam_multi.Rig's contract, plus I1-I3: the NAM kernel puts them back too (its B1-B3 restore),
    # and leaving I1/I2 advanced froze the unit's controls in the first hardware builds
    KEEP = [c for c in range(0x10, 0x50) if c != 0x1F]

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
        self.sim.wr(i0 + 3, 1)                       # as on the unit: non-zero while the block is on
        return i0

    def knobs(self, i0, knobs):
        for k, v in knobs.items():
            self.sim.wr(i0 + KNOB[k], int(v) if k in INT_KNOBS else ssim.f2b(float(v)))

    def bypass(self, i0, on):
        self.sim.wr(i0 + 3, 1 if on else 0)         # the host's bypass flag (stock 0x822's DM(3))

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
        sim.set(0x13, rnd.getrandbits(32) & 0xFFFFF)        # I3: the call-list entry (unused here)
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
        if 3 + i0 in writes:
            raise AssertionError(f'{label}: wrote DM(3), the host\'s bypass flag')
        lo = self.syms['SAVE']
        allowed = [(BO, BO + 16), (i0 + P_SLOT, i0 + P_SLOT + 1), (lo, lo + 24),       # SAVE (21), G_CALLS, G_PSOUND, G_PCOUNT
                   (self.syms['SLOTS'], self.syms['SLOTS'] + SLOTW * NSLOTS)]
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
        dict(time=0.5, meter=4, accent=6, sound=0, level=0.5, subdiv=1),
        dict(time=60 / 137.5, meter=3, accent=12, sound=1, level=1, subdiv=2),
        dict(time=0.2, meter=5, accent=0, sound=2, level=0.75, subdiv=4),
        dict(time=3.0, meter=2, accent=3, sound=1, level=0.3, subdiv=3),
        dict(time=60 / 97.31, meter=4, accent=12, sound=0, level=0, subdiv=1),          # level 0: dry
        dict(time=9.0, meter=9, accent=40, sound=7, level=2.5, subdiv=0),          # out of range: clamped
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
            ka = dict(time=r.uniform(0.05, 5.0), meter=r.randint(2, 5), accent=r.randint(0, 12),
                      sound=r.randint(0, 2), level=round(r.uniform(0, 1), 3), subdiv=r.randint(1, 4))
            kb = dict(time=r.uniform(0.05, 5.0), meter=r.randint(2, 5), accent=r.randint(0, 12),
                      sound=r.randint(0, 2), level=round(r.uniform(0, 1), 3), subdiv=r.randint(1, 4))
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

    # a block deleted and re-created at the same place: zeroed block -> fresh slot state (reset)
    kn = dict(time=0.4, meter=3, accent=9, sound=2, level=0.8, subdiv=2)
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
    print('  a block re-created at the same place starts again at beat 1: identical')

    # more blocks than slots: the extra one passes its input through; a block that stops
    # running loses its slot after STALE calls, and the next newcomer gets it
    rig2 = Rig(secs, syms, data, seed=3)
    insts = [rig2.inst(k) for k in range(NSLOTS + 1)]
    for i0 in insts:
        rig2.knobs(i0, kn)
    x = signal(16, 4)
    for i0 in insts[:NSLOTS]:
        rig2.call(i0, x)
    out = rig2.call(insts[NSLOTS], x, 'no free slot')
    if out != x:
        raise AssertionError('with every slot taken, a block does not pass its input through')
    for _ in range(STALE // (NSLOTS - 1) + 2):            # all but the first keep running
        for i0 in insts[1:NSLOTS]:
            rig2.call(i0, x)
    st = ref.new()
    got = rig2.call(insts[NSLOTS], x, 'stale slot taken')
    if got != ref.process(st, kn, [ssim.b2f(v) for v in x]) or rig2.sim.rd(insts[NSLOTS] + P_SLOT) != 1:
        raise AssertionError('a stale slot was not taken over by the waiting block')
    st0 = ref.new()                                        # the first one comes back: claims anew
    rig2.call(insts[0], x, 'returning block')
    print(f'  {NSLOTS} slots: a 9th block passes through; a stale slot goes to the next block')

    # DM(3) as the unit has it (non-zero while on, any value): ignored, never written
    kn = dict(time=0.3, meter=4, accent=12, sound=1, level=0.9, subdiv=2)
    rig3 = Rig(secs, syms, data, seed=9)
    i0 = rig3.inst(0)
    rig3.knobs(i0, kn)
    x = signal(600 * 16, 31)
    st = ref.new()
    for b in range(600):
        rig3.sim.wr(i0 + 3, (1, 2, 0x12345, 0)[b // 150])
        blk = x[16 * b:16 * b + 16]
        if rig3.call(i0, blk, f'DM(3) block {b}') != ref.process(st, kn, [ssim.b2f(v) for v in blk]):
            raise AssertionError(f'DM(3) test block {b}: the kernel reacted to DM(3)')
    total += 600 * 16
    print('  DM(3) ignored (0, 1, 2, other) and never written')
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
