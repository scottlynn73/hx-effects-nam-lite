#!/usr/bin/env python3
"""probe_kernel.py - build and check the overlay-swap probe (probe_kernel.asm).

usage: probe_kernel.py [--check]

The probe reads a magic word inside Blob 0 (DDR2) and, when the Bit Depth knob has stayed on 3, 2 or 1 for
1.5 s, copies routine A or B (alternating every call) from Blob 0 into one internal region and calls it,
checking that the routine it just copied is the one that ran (probe_kernel.asm has the tests and the tones).
build_all.py --probe sets EXT (where the words sit in Blob 0) before the final assembly and puts
tail_words(syms) inside Blob 0.

Found on the unit so far (docs/baseline-audit.md, "Finding more memory"): words inside Blob 0 land in DDR2 where
predicted; 48-bit code in DDR2 does not run; a routine copied into internal memory through its normal-word view
(the INIT_L48 packing) runs and returns.

--check runs it in ssim: the register contract, the memory it may write, the routine that ran on each call, and
each tone, against a model in Python. ssim has no instruction cache and no normal-word view of PM: the check
installs each copy into PM when its last word is written, so it covers the logic, not the cache.
"""
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'common'))
import kernel_rig as kr  # noqa: E402
import sasm  # noqa: E402  (kernel_rig puts tools/sharc on the path)
import ssim  # noqa: E402

BLOB0_BASE = 0x21C400
MAGIC, MAGIC2, MAGIC3 = 0x50524F42, 0x45584543, 0x53574150       # 'PROB', 'EXEC', 'SWAP'
DWELL = 4500                                      # calls (1.5 s) on a value before its test runs
HALF = dict(HALF_880=27, HALF_220=109, HALF_1760=14, HALF_110=218)
BEEP_BIT = 0x400
EXT = dict(tail=0x7A000)                          # Blob 0 word offset of the words; build_all.py sets it
# The region (a 48-bit address in Block 3, unused by every kernel in the probe image: Click's data starts at
# normal word 0xe7c20 = 48-bit 0xe52c0).
REG = 0xE5000
NINSN, NWORDS = 8, 12                             # a routine's instructions, and its 32-bit words when packed
ASM = os.path.join(HERE, 'probe_kernel.asm')
GLOBALS = ['G_CALLS', 'G_PH', 'G_SIGN', 'G_FLAG', 'G_LAST', 'G_DWELL', 'G_BAD', 'G_SV', 'G_SV1']


def normal_of(a48):
    """The normal-word address where 48-bit address a48 (Block 3, even offset) starts."""
    return 0xE0000 + (a48 - 0xE0000) * 3 // 2


def magic_addr():
    return BLOB0_BASE + EXT['tail']


class Spec:
    name, entry, knobs, int_knobs, slotw, nslots, max_cycles = 'probe', 'PROBE_ENTRY', {}, set(), 0, 0, 1500

    def __init__(self):
        self.places = {'b2': (0xC4EF8, 0xC5554, 0xE4850)}
        self.extra_writes = []

    def source(self, place):
        code, _, data0 = self.places[place]
        lay, a = [('SAVE', 13, [0] * 13)], data0
        lay += [(g, 1, [kr.fw(1.0) if g == 'G_SIGN' else 0]) for g in GLOBALS]
        lay += [('K_MAGIC', 1, [MAGIC]), ('K_MAGIC2', 1, [MAGIC2]), ('K_MAGIC3', 1, [MAGIC3])]
        equ, words = [], []
        for name, n, w in lay:
            equ.append(f'.equ {name}, {a:#x}')
            words += w
            a += n
        m = magic_addr()
        equ += [f'.equ SLOTS, {a:#x}', f'.equ MAGIC_ADDR, {m:#x}', f'.equ SRC, {m + 2:#x}', f'.equ FAM, {2 * NWORDS}',
                f'.equ NWORDS, {NWORDS}', f'.equ REG, {REG:#x}', f'.equ REG_N, {normal_of(REG):#x}',
                f'.equ DWELL, {DWELL}', f'.equ BEEP_BIT, {BEEP_BIT:#x}']
        equ += [f'.equ {k}, {v}' for k, v in HALF.items()]
        data = [f'.section dm {data0:#x}', '.word ' + ', '.join(f'{w:#010x}' for w in words)]
        asm = open(ASM).read()
        asm = asm.replace('.section pm 0x0c4ef8', f'.section pm {code:#08x}')
        return asm.replace('// EQUS', '\n'.join(equ + data)), (data0, a)

    def assemble(self, place):
        src, data = self.source(place)
        secs, syms = sasm.assemble(src, 'probe_kernel.asm')
        pm = [s for s in secs if s.kind == 'pm']
        end = max(s.addr + len(s.words) for s in pm)
        code, code_end, _ = self.places[place]
        assert end <= code_end, f'probe: code {code:#x}..{end:#x}, past {code_end:#x}'
        if code & ~0xFFFF == 0xE0000:
            assert end <= REG, f'probe: code to {end:#x} runs into the test region'
        self.extra_writes = [(normal_of(REG), normal_of(REG) + NWORDS), (data[0], data[1])]
        return src, secs, syms, end, data


SPEC = Spec()


def encode(text):
    r = sasm.encode(text)
    return r if isinstance(r, int) else r[0]


def routine(syms, reg, forcing):
    """A routine of NINSN words storing register `reg` in G_FLAG twice (the last store is the one that
    counts). The forcing form puts PM data accesses just before the stores, so the fetches they collide with
    (the stores) go into the instruction cache."""
    head = 'R1 = PM(0, I8)' if forcing else 'NOP'
    store = f'DM({syms["G_FLAG"]:#x}) = {reg}'
    return [encode(t) for t in [head] * 4 + [store, store, 'NOP', 'RTS']]


def routines(syms):
    """[plain A, plain B, forcing A, forcing B]: A stores R4 (K_MAGIC2), B R3 (K_MAGIC3)."""
    return [routine(syms, r, f) for f in (False, True) for r in ('R4', 'R3')]


def packed(insns):
    """The INIT_L48 packing: each instruction's 6 bytes little-endian, back to back, read as 32-bit words."""
    raw = b''.join(int(w).to_bytes(6, 'little') for w in insns)
    return list(struct.unpack('<%dI' % (len(raw) // 4), raw))


def unpacked(words):
    raw = struct.pack('<%dI' % len(words), *words)
    return [int.from_bytes(raw[6 * k:6 * k + 6], 'little') for k in range(len(raw) // 6)]


def tail_words(syms):
    """The words for Blob 0 at EXT['tail']: magic, pad, then the four routines packed."""
    return [MAGIC, 0] + [w for r in routines(syms) for w in packed(r)]


def check(seconds=1.0, place='b2'):
    src, secs, syms, end, data = SPEC.assemble(place)
    code = SPEC.places[place][0]
    print(f'[probe {place}] code {code:#x}..{end:#x} ({end - code} instructions), data {data[0]:#x}..{data[1]:#x}; '
          f'magic at {magic_addr():#x}; region {REG:#x}')
    rs = routines(syms)
    assert all(len(r) == NINSN and len(packed(r)) == NWORDS and unpacked(packed(r)) == r for r in rs)

    def run(landed, bits, nblk, seed, corrupt=False):
        rig = kr.Rig(SPEC, secs, syms, seed)
        n = normal_of(REG)
        wr0 = rig.sim.wr
        ran = []

        def wr(a, v):                          # the normal-word view: the last word written installs the copy
            wr0(a, v)
            if a == n + NWORDS - 1:
                insns = unpacked([rig.sim.dm[n + k] for k in range(NWORDS)])
                ran.append(insns)
                if corrupt:                    # as a stale cache would: the other routine's stores run instead
                    other = rs[[rs.index(x) for x in rs if x == insns][0] ^ 1]
                    insns = other
                for k, w in enumerate(insns):
                    rig.sim.pm[REG + k] = w
        rig.sim.wr = wr
        if landed:
            for k, w in enumerate(tail_words(syms)):
                wr0(magic_addr() + k, w)
        i0 = rig.inst(0)
        rig.sim.wr(i0 + 7, bits)
        rng = random.Random(seed)
        ph, sign, calls = 0, 1.0, 0
        for b in range(nblk):
            blk = [kr.fw(kr.f32(rng.uniform(-0.5, 0.5))) for _ in range(16)]
            before = len(ran)
            got = rig.call(i0, blk, f'landed={landed} bits={bits} block {b}')
            calls += 1
            test = landed and bits in (1, 2, 3) and calls > DWELL
            assert len(ran) - before == (1 if test else 0), 'a copy ran when it should not, or did not when it should'
            if not landed:
                half, amp = HALF['HALF_220'], 0.1
            elif not test:
                half, amp = HALF['HALF_880'], 0.1
            elif corrupt:
                half, amp = HALF['HALF_110'], 0.1
            else:
                half, amp = HALF['HALF_1760'], (0.1 if calls & BEEP_BIT else 0.0)
                odd = calls & 1
                want_r = rs[(0 if bits == 3 else 2) + odd]
                assert ran[-1] == want_r, f'call {calls}: copied the wrong routine'
                assert rig.sim.rd(syms['G_FLAG']) == (MAGIC3 if odd else MAGIC2), f'call {calls}: wrong flag'
            want = []
            for k in range(16):
                ph += 1
                if ph >= half:
                    ph, sign = 0, -sign
                tone = kr.f32(kr.f32(sign) * kr.f32(amp))
                want.append(kr.fw(kr.f32(ssim.b2f(blk[k]) + tone)))
            assert got == want, f'landed={landed} bits={bits} calls={calls}: output differs'
        return rig

    nblk = DWELL + 2000
    rigs = []
    for landed, bits in ((False, 3), (True, 8), (True, 3), (True, 2), (True, 1)):
        rigs.append(run(landed, bits, nblk, 1 + bits))
        print(f'  landed={landed}, Bit Depth {bits}: as modelled')
    rigs.append(run(True, 1, nblk, 9, corrupt=True))
    print('  a stale routine (the other one runs) gives the low drone: as modelled')
    worst = max(c for g in rigs for c in g.cycles)
    print(f'cycles per call: worst {worst} (budget {SPEC.max_cycles})')
    assert worst <= SPEC.max_cycles
    return worst


if __name__ == '__main__':
    if '--check' in sys.argv:
        try:
            check()
        except AssertionError as ex:
            sys.exit(f'probe_kernel.py: CHECK FAILED: {ex}')
        print('CHECK OK')
    else:
        sys.exit(__doc__)
