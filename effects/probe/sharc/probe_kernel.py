#!/usr/bin/env python3
"""probe_kernel.py - build and check the external-memory probe (probe_kernel.asm).

usage: probe_kernel.py [--check]

The probe reads a magic word from Blob 0's tail in DDR2 and later jumps to a two-instruction routine
stored there (see probe_kernel.asm for the tones). build_all.py --probe sets EXT (where Blob 0's tail
lands) before the final assembly and appends tail_words(syms) to Blob 0.

External code: the stock firmware runs code from DDR2 as 16-bit parcels, two to a 32-bit word with the
first parcel in the high half, at PC = 2 x the word address; a 48-bit instruction is its three parcels,
high first, with the ISA encoding unchanged (seen: DM(abs) = ureg, JUMP abs, CJUMP). The routine uses
only those forms and no RTS (its 48-bit form never appears in the stock external code).

--check runs the kernel in ssim with the routine placed (as ISA) at EXT_PC: the register contract, the
memory it may write, and each stage's tone, against a model in Python.
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
MAGIC, MAGIC2 = 0x50524F42, 0x45584543            # 'PROB', 'EXEC'
STAGE2 = 12000                                    # calls (4 s)
HALF = dict(HALF_880=27, HALF_220=109, HALF_1760=14, HALF_110=218)
BEEP_BIT = 0x400
EXT = dict(tail=0x7A000)                          # Blob 0 word offset of the tail; build_all.py sets it
ASM = os.path.join(HERE, 'probe_kernel.asm')
GLOBALS = ['G_CALLS', 'G_PH', 'G_SIGN', 'G_FLAG']


def magic_addr():
    return BLOB0_BASE + EXT['tail']


def ext_pc():
    return 2 * (BLOB0_BASE + EXT['tail'] + 2)


class Spec:
    name, entry, knobs, int_knobs, slotw, nslots, max_cycles = 'probe', 'PROBE_ENTRY', {}, set(), 0, 0, 1500

    def __init__(self):
        self.places = {'b2': (0xC4EF8, 0xC5554, 0xE4850)}

    def source(self, place):
        code, _, data0 = self.places[place]
        lay, a = [('SAVE', 11, [0] * 11)], data0
        lay += [(g, 1, [kr.fw(1.0) if g == 'G_SIGN' else 0]) for g in GLOBALS]
        lay += [('K_MAGIC', 1, [MAGIC]), ('K_MAGIC2', 1, [MAGIC2])]
        equ, words = [], []
        for name, n, w in lay:
            equ.append(f'.equ {name}, {a:#x}')
            words += w
            a += n
        equ += [f'.equ SLOTS, {a:#x}', f'.equ MAGIC_ADDR, {magic_addr():#x}', f'.equ EXT_PC, {ext_pc():#x}',
                f'.equ STAGE2, {STAGE2}', f'.equ BEEP_BIT, {BEEP_BIT:#x}'] + [f'.equ {k}, {v}' for k, v in HALF.items()]
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
        return src, secs, syms, end, data


SPEC = Spec()


def ext_insns(syms):
    """The external routine, as 48-bit ISA words: store R4 in G_FLAG, jump back to PROBE_RET."""
    a = sasm.encode(f'DM({syms["G_FLAG"]:#x}) = R4')
    b = sasm.encode(f'JUMP {syms["PROBE_RET"]:#x}')
    a, b = (x if isinstance(x, int) else x[0] for x in (a, b))     # [0]: the absolute JUMP (op 0x06)
    assert a >> 40 == 0x11 and b >> 40 == 0x06, (hex(a), hex(b))
    return [a, b]


def tail_words(syms):
    """The words to append to Blob 0 at EXT['tail']: the magic word, a pad, then the routine's parcels."""
    par = []
    for w in ext_insns(syms):
        par += [w >> 32 & 0xFFFF, w >> 16 & 0xFFFF, w & 0xFFFF]
    if len(par) & 1:
        par.append(0)
    return [MAGIC, 0] + [par[k] << 16 | par[k + 1] for k in range(0, len(par), 2)]


def check(seconds=1.0, place='b2'):
    src, secs, syms, end, data = SPEC.assemble(place)
    code = SPEC.places[place][0]
    print(f'[probe {place}] code {code:#x}..{end:#x} ({end - code} instructions), data {data[0]:#x}..{data[1]:#x}; '
          f'magic at {magic_addr():#x}, routine at PC {ext_pc():#x}')
    tail = tail_words(syms)
    # the parcels decode back to the routine
    par = [p for w in tail[2:] for p in (w >> 16, w & 0xFFFF)]
    assert [par[0] << 32 | par[1] << 16 | par[2], par[3] << 32 | par[4] << 16 | par[5]] == ext_insns(syms)

    def run(landed, start_calls, nblk, seed):
        rig = kr.Rig(SPEC, secs, syms, seed)
        ext = sasm.Section('pm', ext_pc())
        ext.words = ext_insns(syms)
        rig.sim.load([ext])
        if landed:
            rig.sim.wr(magic_addr(), MAGIC)
        rig.sim.wr(syms['G_CALLS'], start_calls)
        i0 = rig.inst(0)
        r = random.Random(seed)
        ph, sign, calls = 0, 1.0, start_calls
        for b in range(nblk):
            blk = [kr.fw(kr.f32(r.uniform(-0.5, 0.5))) for _ in range(16)]
            got = rig.call(i0, blk, f'landed={landed} block {b}')
            calls += 1
            if not landed:
                half, amp = HALF['HALF_220'], 0.1
            elif calls < STAGE2:
                half, amp = HALF['HALF_880'], 0.1
            else:
                half, amp = HALF['HALF_1760'], (0.1 if calls & BEEP_BIT else 0.0)
                assert rig.sim.rd(syms['G_FLAG']) == MAGIC2, 'the routine did not set the flag'
            want = []
            for k in range(16):
                ph += 1
                if ph >= half:
                    ph, sign = 0, -sign
                tone = kr.f32(kr.f32(sign) * kr.f32(amp))
                want.append(kr.fw(kr.f32(ssim.b2f(blk[k]) + tone)))
            assert got == want, f'landed={landed} calls={calls}: output differs'
        return rig

    nblk = int(seconds * kr.SR) // 16
    rig = run(False, 0, nblk, 1)
    print(f'  not landed: 220 Hz, {nblk} calls: as modelled')
    rig = run(True, 0, nblk, 2)
    print(f'  landed, stage 1: 880 Hz, {nblk} calls: as modelled')
    rig2 = run(True, STAGE2 - 100, nblk + 2000, 3)
    print(f'  landed, stage 2 (through the routine at {ext_pc():#x}), {nblk + 2000} calls: beeps as modelled')
    worst = max(rig.cycles + rig2.cycles)
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
