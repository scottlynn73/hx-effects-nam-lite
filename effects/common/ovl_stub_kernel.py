#!/usr/bin/env python3
"""ovl_stub_kernel.py - the resident stub of the overlay effects, and the check of the whole path.

An overlay effect's code and data travel inside Entry 4's Blob 0, which the unit copies verbatim to DDR2. Only
this stub is in the boot stream, and the effects share one internal region. When a block's effect is not the one
in the region, the stub saves the outgoing effect's live state (its call counter and its slots) back to that
effect's home in DDR2, copies the incoming effect's code in through the region's normal-word view (the INIT_L48
packing, proven on the unit by the probes in effects/probe) and its data after it, flushes the instruction cache and
jumps to the kernel, which returns to the host itself. A kernel therefore always runs from internal memory with
its data in internal memory; only a buffer it asks for (a ring) is in DDR2.

Every member is assembled for the same region: data from data0, code from code48. check() runs the members
through the stub in ssim, from a payload in simulated DDR2 and with the region's data filled with noise first:
each alone, then all of them interleaved (every call swaps), word for word against the C references.
"""
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kernel_rig as kr  # noqa: E402
import sasm  # noqa: E402  (kernel_rig puts tools/sharc on the path)
import ssim  # noqa: E402

GCALLS_OFF = 21                          # kernel_rig.Spec's layout: SAVE (21 words), then G_CALLS
NSV = 8                                  # the stub's save words
NDESC = 5                                # SRC_CODE, N_CODE, SRC_DATA, N_DATA, SLOTS_OFF
# The meter (build_all.py --meter): the real cycles a member takes, swap included, reported as beeps while that block's
# Pattern knob is on 8: every 20 UNITs of calls, a low 220 Hz mark, then one 440 Hz beep per 16,384 cycles of the worst
# call in the last report period (at most 9), a gap, then one 1,760 Hz beep per further 2,048 cycles (at most 7).
METER_ON_VALUE = 8
CFG = dict(meter=False, meter_on=1, unit=1024, code_n=0xE7000, data0=0xE6000,
           members=[dict(name='OTTOBIT', src_code=0x3E0000, n_code=660, src_data=0x3E1000, n_data=300, slots_off=200,
                         kernel=0xE5000)])

HEAD = """
.equ PEYEN,    0x200000
.equ BDCST9,   0x400000
.section dm {data0:#x}
SV:
.word {sv}
CUR:
.word 0
{descs}
.section pm {code:#x}
"""

METER_MEMBER = """
OVL_ENTRY_{name}:
    DM(SV + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SV + 1) = R0;
    R0 = EMUCLK;
    DM(M_T0) = R0;
    R0 = D_{name};
    CALL o_load;
    R0 = DM(SV + 1);
    MODE1 = DM(SV + 0);
    NOP;
    CALL {kernel:#x};
    DM(SV + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SV + 1) = R0;
    R0 = M_{name};
    CALL o_meter;
    R0 = DM(SV + 1);
    MODE1 = DM(SV + 0);
    NOP;
    RTS (LR);
"""

METER_COMMON = """
// R0 = the member's meter words (worst cycles, the instance word of its Pattern knob). Adds the report to the outputs.
o_meter:
    DM(SV + 2) = R1;
    DM(SV + 3) = R2;
    DM(SV + 4) = R3;
    DM(SV + 5) = R4;
    DM(SV + 6) = I3;
    DM(SV + 7) = I4;
    DM(M_I2) = I2;
    L2 = 0;
    L3 = 0;
    L4 = 0;
    R1 = EMUCLK;
    R2 = DM(M_T0);
    R1 = R1 - R2;
    I4 = R0;
    R2 = DM(0, I4);
    R1 = MAX(R1, R2);
    DM(0, I4) = R1;
    R2 = DM(1, I4);
    R3 = I0;
    R2 = R2 + R3;
    I3 = R2;
    R2 = DM(0, I3);
    R3 = ON_VALUE;
    COMP(R2, R3);
    IF NE JUMP om_done;
    R2 = DM(M_ON);
    R2 = PASS R2;
    IF EQ JUMP om_done;
    R2 = DM(M_T);
    R2 = R2 + 1;
    R3 = PERIOD;
    COMP(R2, R3);
    IF LT JUMP om_t;
    R2 = 0;
    R3 = DM(0, I4);
    R4 = LSHIFT R3 BY -14;
    R1 = 9;
    R4 = MIN(R4, R1);
    DM(M_N1) = R4;
    R4 = LSHIFT R3 BY -11;
    R1 = 7;
    R4 = R4 AND R1;
    DM(M_N2) = R4;
    R1 = 0;
    DM(0, I4) = R1;
om_t:
    DM(M_T) = R2;
    R3 = MARK;
    COMP(R2, R3);
    IF GE JUMP om_a;
    R1 = HALF_220;
    JUMP om_tone;
om_a:
    R3 = GAP;
    R2 = R2 - R3;
    IF LT JUMP om_done;
    R4 = DM(M_N1);
    R3 = LSHIFT R4 BY USHIFT;
    COMP(R2, R3);
    IF GE JUMP om_b;
    R1 = HALF_440;
    JUMP om_gate;
om_b:
    R2 = R2 - R3;
    R4 = UNIT;
    R2 = R2 - R4;
    IF LT JUMP om_done;
    R4 = DM(M_N2);
    R3 = LSHIFT R4 BY USHIFT;
    COMP(R2, R3);
    IF GE JUMP om_done;
    R1 = HALF_1760;
om_gate:
    R3 = UNIT - 1;
    R3 = R2 AND R3;
    R4 = UNIT_HALF;
    COMP(R3, R4);
    IF GE JUMP om_done;
om_tone:
    R0 = 16;
    R2 = DM(M_PH);
    F3 = DM(M_SIGN);
om_l:
    R2 = R2 + 1;
    COMP(R2, R1);
    IF LT JUMP om_k;
    R2 = 0;
    F3 = -F3;
om_k:
    F4 = DM(0, I2);
    F4 = F4 + F3;
    DM(I2, 1) = F4;
    R0 = R0 - 1;
    IF NE JUMP om_l;
    DM(M_PH) = R2;
    DM(M_SIGN) = F3;
om_done:
    I2 = DM(M_I2);
    R1 = DM(SV + 2);
    R2 = DM(SV + 3);
    R3 = DM(SV + 4);
    R4 = DM(SV + 5);
    I3 = DM(SV + 6);
    I4 = DM(SV + 7);
    RTS;
"""

MEMBER = """
OVL_ENTRY_{name}:
    DM(SV + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SV + 1) = R0;
    R0 = D_{name};
    CALL o_load;
    R0 = DM(SV + 1);
    MODE1 = DM(SV + 0);
    NOP;
    JUMP {kernel:#x};
"""

COMMON = """
// R0 = the wanted effect's descriptor. Puts that effect in the region if it is not there.
o_load:
    DM(SV + 2) = R1;
    R1 = DM(CUR);
    COMP(R0, R1);
    IF NE JUMP o_swap;
    R1 = DM(SV + 2);
    RTS;
o_swap:
    DM(SV + 3) = R2;
    DM(SV + 4) = R3;
    DM(SV + 5) = R4;
    DM(SV + 6) = I3;
    DM(SV + 7) = I4;
    L3 = 0;
    L4 = 0;
    R2 = R0;                            // the incoming descriptor
    R1 = PASS R1;
    IF EQ JUMP o_in;
    // ---- the outgoing effect's call counter and slots, back to its home
    I4 = R1;
    R0 = DM(2, I4);                     // its data's home
    R1 = DM(3, I4);                     // N_DATA
    R3 = DM(4, I4);                     // SLOTS_OFF
    R1 = R1 - R3;                       // the slots' length
    R4 = GCALLS_OFF;
    R4 = R0 + R4;
    I4 = R4;
    R4 = DM(GCALLS_ADDR);
    DM(0, I4) = R4;
    R4 = DATA0;
    R4 = R4 + R3;
    I3 = R4;
    R4 = R0 + R3;
    I4 = R4;
o_out:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R1 = R1 - 1;
    IF NE JUMP o_out;
o_in:
    // ---- the incoming effect's code, then its data
    I4 = R2;
    R0 = DM(0, I4);
    R1 = DM(1, I4);
    R3 = DM(2, I4);
    R4 = DM(3, I4);
    I3 = R0;
    I4 = CODE_N;
o_c:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R1 = R1 - 1;
    IF NE JUMP o_c;
    I3 = R3;
    I4 = DATA0;
o_d:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R4 = R4 - 1;
    IF NE JUMP o_d;
    FLUSH CACHE;
    DM(CUR) = R2;
    R1 = DM(SV + 2);
    R2 = DM(SV + 3);
    R3 = DM(SV + 4);
    R4 = DM(SV + 5);
    I3 = DM(SV + 6);
    I4 = DM(SV + 7);
    RTS;
"""


def configure(**kw):
    CFG.update(kw)


class Stub:
    def __init__(self):
        self.places = {}

    def source(self, place):
        code, _, data0 = self.places[place]
        ms = CFG['members']
        descs = '\n'.join(f"D_{m['name']}:\n.word {m['src_code']:#x}, {m['n_code']}, {m['src_data']:#x}, {m['n_data']}, {m['slots_off']}"
                          for m in ms)
        equ = (f".equ CODE_N, {CFG['code_n']:#x}\n.equ DATA0, {CFG['data0']:#x}\n.equ GCALLS_OFF, {GCALLS_OFF}\n"
               f".equ GCALLS_ADDR, {CFG['data0'] + GCALLS_OFF:#x}\n")
        nd = NSV + 1 + NDESC * len(ms)
        if CFG['meter']:
            u = CFG['unit']
            assert u & (u - 1) == 0, 'the meter unit must be a power of two'
            mw = [('M_T0', 0), ('M_I2', 0), ('M_T', 0), ('M_N1', 0), ('M_N2', 0), ('M_PH', 0), ('M_SIGN', kr.fw(0.1)), ('M_ON', CFG['meter_on'])]
            descs += '\n' + '\n'.join(f'{n}:\n.word {v:#x}' for n, v in mw)
            descs += '\n' + '\n'.join(f"M_{m['name']}:\n.word 0, {m['pattern_word']}" for m in ms)
            nd += len(mw) + 2 * len(ms)
            equ += (f'.equ PERIOD, {20 * u}\n.equ MARK, {u * 3 // 4}\n.equ GAP, {2 * u}\n.equ UNIT, {u}\n.equ UNIT_HALF, {u // 2}\n'
                    f'.equ USHIFT, {u.bit_length() - 1}\n.equ ON_VALUE, {METER_ON_VALUE}\n.equ HALF_220, 109\n.equ HALF_440, 55\n.equ HALF_1760, 14\n')
        src = equ + HEAD.format(data0=data0, code=code, sv=', '.join(['0'] * NSV), descs=descs)
        one = METER_MEMBER if CFG['meter'] else MEMBER
        src += ''.join(one.format(name=m['name'], kernel=m['kernel']) for m in ms) + COMMON
        if CFG['meter']:
            src += METER_COMMON
        return src, (data0, data0 + nd)

    def assemble(self, place):
        src, data = self.source(place)
        secs, syms = sasm.assemble(src, 'ovl_stub')
        pm = [s for s in secs if s.kind == 'pm']
        end = max(s.addr + len(s.words) for s in pm)
        code, code_end, _ = self.places[place]
        assert min(s.addr for s in pm) == code and end <= code_end, f'stub: code {code:#x}..{end:#x}, past {code_end:#x}'
        base = code & ~0xFFFF
        if data[0] & ~0xFFFF == base:
            assert data[1] <= base + (code - base) * 3 // 2, f'stub: data to {data[1]:#x} runs into the code'
        return src, secs, syms, end, data


SPEC = Stub()


def packed(insns):
    """Instructions as the normal-word view holds them (an even count; the INIT_L48 packing)."""
    ins = list(insns)
    if len(ins) & 1:
        ins.append(0)
    raw = b''.join(int(w).to_bytes(6, 'little') for w in ins)
    return list(struct.unpack('<%dI' % (len(raw) // 4), raw))


def payload(secs):
    """(code words, data words, code address, data address) of a kernel assembled for the overlay region."""
    pm = [s for s in secs if s.kind == 'pm']
    dm = [s for s in secs if s.kind == 'dm']
    assert len(pm) == 1 and len(dm) == 1, 'an overlay kernel is one code and one data section'
    return packed(pm[0].words), list(dm[0].words), pm[0].addr, dm[0].addr


def normal_of(a48):
    assert not (a48 - 0xE0000) & 1, 'code must start on an even address'
    return 0xE0000 + (a48 - 0xE0000) * 3 // 2


def layout(members, base):
    """members: [(name, kernel spec, place, entry symbol)]. Lays their payloads out from DDR2 address `base`:
    (the words, CFG settings for configure())."""
    words, ms, code48, data0 = [], [], None, None
    for name, spec, kplace, entry in members:
        _, secs, syms, _, data = spec.assemble(kplace)
        code, dwords, c48, d0 = payload(secs)
        assert code48 in (None, c48) and data0 in (None, d0), f'{name}: not assembled for the shared region'
        code48, data0 = c48, d0
        src_code = base + len(words)
        words += code
        src_data = base + len(words)
        words += dwords
        ms.append(dict(name=name, src_code=src_code, n_code=len(code), src_data=src_data, n_data=len(dwords),
                       slots_off=syms['SLOTS'] - data0, kernel=syms[entry], pattern_word=spec.knobs['pattern']))
    return words, dict(code_n=normal_of(code48), data0=data0, members=ms)


class Flow:
    """One member through the stub, for kernel_rig: the kernel exists only as a payload in DDR2."""

    def __init__(self, spec, name, members):
        self.k, self.members = spec, members
        self.name, self.knobs, self.int_knobs, self.order = spec.name, spec.knobs, spec.int_knobs, spec.order
        self.slotw, self.nslots, self.entry, self.max_cycles = spec.slotw, spec.nslots, f'OVL_ENTRY_{name}', 20000
        self.places = SPEC.places

    def assemble(self, place):
        src = 0x3E0000
        words, cfg = layout(self.members, src)
        configure(**cfg)
        s, secs, syms, end, sdata = SPEC.assemble(place)
        p = sasm.Section('dm', src)
        p.words = words
        ninsn = max(m['n_code'] for m in cfg['members']) * 2 // 3
        code48 = 0xE0000 + (cfg['code_n'] - 0xE0000) * 2 // 3
        ndata = max(m['n_data'] for m in cfg['members'])
        all_syms = {}
        for _, spec, kplace, _ in self.members:
            all_syms.update(spec.assemble(kplace)[2])
        self.pm_view = (code48, ninsn)
        self.garbage = [(cfg['data0'], cfg['data0'] + ndata)]
        self.extra_writes = [w for _, spec, _, _ in self.members for w in getattr(spec, 'extra_writes', [])] + [
            (cfg['data0'], cfg['data0'] + ndata), (cfg['code_n'], cfg['code_n'] + ninsn * 3 // 2), (sdata[0], sdata[1]),
            (src, src + len(words))]
        return s, secs + [p], {**all_syms, **syms}, end, sdata


def check_interleaved(members, cases_of, rnd_knobs_of, seconds, place):
    """Every member on its own instance, called in turn so that every call swaps."""
    flows = [Flow(m[1], m[0], members) for m in members]
    s, secs, syms, end, sdata = flows[0].assemble(place)
    for f in flows[1:]:
        f.pm_view, f.garbage, f.extra_writes = flows[0].pm_view, flows[0].garbage, flows[0].extra_writes
    rig = kr.Rig(flows[0], secs, syms)
    refs = [kr.Reference(f) for f in flows]
    nblk, total = int(seconds * kr.SR) // 16, 0
    r = random.Random(7)
    inst = [rig.inst(j) for j in range(len(flows))]
    states = [ref.new() for ref in refs]
    x = kr.signal(nblk * 16, 31, chord=True)
    knobs = [None] * len(flows)
    for b in range(nblk):
        for j, f in enumerate(flows):
            rig.spec = f
            if b % 300 == 0:
                knobs[j] = rnd_knobs_of[j](r)
                rig.knobs(inst[j], knobs[j])
            blk = x[16 * b:16 * b + 16]
            got = rig.call(inst[j], blk, f'{f.name} block {b}')
            want = refs[j].process(states[j], knobs[j], [ssim.b2f(v) for v in blk])
            if got != want:
                k = next(i for i in range(16) if got[i] != want[i])
                raise AssertionError(f'interleaved: {f.name} block {b} sample {k}: kernel {got[k]:#010x}, reference {want[k]:#010x}')
            total += 16
    print(f'  {" and ".join(f.name for f in flows)} interleaved, every call swapping: {total} samples identical')


def check_members(members, cases_of, rnd_knobs_of, seconds, place):
    for j, (name, spec, _, _) in enumerate(members):
        kr.check(Flow(spec, name, members), place, cases_of[j], rnd_knobs_of[j], seconds)
    if len(members) > 1:
        check_interleaved(members, cases_of, rnd_knobs_of, seconds, place)


MEMBERS = []                             # (name, spec, place, entry symbol, kernel module): build_all.py sets it


def check_meter(members, knobs, place):
    """The meter's report through a real kernel, with a short unit: the output is the reference's plus the tone,
    and silent with Pattern off 8."""
    name, spec, _, _ = members[0]
    saved = CFG['unit'], CFG['meter_on']
    configure(unit=64, meter_on=1)
    try:
        f = Flow(spec, name, members)
        src, secs, syms, end, sdata = f.assemble(place)
        for want_tone, pat in ((True, 8), (False, 1)):
            rig = kr.Rig(f, secs, syms)
            ref = kr.Reference(f)
            i0 = rig.inst(0)
            kn = dict(knobs, pattern=pat)
            rig.knobs(i0, kn)
            st = ref.new()
            x = kr.signal(16 * 64 * 42, 3)
            kinds = set()
            for b in range(64 * 42):
                blk = x[16 * b:16 * b + 16]
                got = rig.call(i0, blk, f'meter pattern {pat} block {b}')
                want = ref.process(st, kn, [ssim.b2f(v) for v in blk])
                for g, w in zip(got, want):
                    d = ssim.b2f(g) - ssim.b2f(w)
                    assert abs(abs(d) - 0.1) < 1e-4 or abs(d) < 1e-9, f'meter: block {b}: output off by {d}'
                    if abs(d) > 0.05:
                        kinds.add(b)
            if want_tone:
                assert kinds, 'the meter never sounded'
                n1, n2 = rig.sim.rd(syms['M_N1']), rig.sim.rd(syms['M_N2'])
                print(f'  meter: sounded on {len(kinds)} of {64 * 42} calls, last report {n1} + {n2} beeps')
            else:
                assert not kinds, 'the meter sounded with Pattern off 8'
        print('  meter: silent unless Pattern is on 8, and otherwise the kernel\'s output exactly')
    finally:
        configure(unit=saved[0], meter_on=saved[1])


def check(seconds=0.25, place='b3'):
    ms = [m[:4] for m in MEMBERS]
    if CFG['meter']:
        configure(meter_on=0)                # the tone is not the reference's: off for the bit-exact checks
    try:
        check_members(ms, [m[4].CASES for m in MEMBERS], [m[4].rnd_knobs for m in MEMBERS], seconds, place)
    finally:
        configure(meter_on=1)
    if CFG['meter']:
        check_meter(ms, MEMBERS[0][4].CASES[0], place)
