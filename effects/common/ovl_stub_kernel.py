#!/usr/bin/env python3
"""ovl_stub_kernel.py - the resident stub of an overlay effect, and the check of the whole path.

An overlay effect's code and data travel inside Entry 4's Blob 0, which the unit copies verbatim to DDR2. Only
this stub is in the boot stream. On the first call it copies the code into its internal region through the
region's normal-word view (the INIT_L48 packing, proven on the unit by the probes in effects/probe), copies
the data, flushes the instruction cache and marks the job done; every call then jumps to the kernel, which
returns to the host itself. The kernel therefore runs from internal memory with its data in internal memory;
only a buffer it asks for (a ring) is in DDR2.

check() runs the kernel through the stub in ssim, from a payload in simulated DDR2 and with the internal data
region filled with noise first, word for word against the C reference.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kernel_rig as kr  # noqa: E402
import sasm  # noqa: E402  (kernel_rig puts tools/sharc on the path)

NDATA = 6                                # SV0..SV4, LOADED
CFG = dict(src_code=0x3E0000, n_code=660, code_n=0xE7000, src_data=0x3E1000, n_data=300, data0=0xE6000, kernel=0xE5000)

ASM = """
.equ PEYEN,    0x200000
.equ BDCST9,   0x400000
.section dm {data0:#x}
SV:
.word 0, 0, 0, 0, 0
LOADED:
.word 0
.section pm {code:#x}
OVL_ENTRY:
    DM(SV + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SV + 1) = R0;
    R0 = DM(LOADED);
    R0 = PASS R0;
    IF NE JUMP o_go;
    DM(SV + 2) = R1;
    DM(SV + 3) = I3;
    DM(SV + 4) = I4;
    L3 = 0;
    L4 = 0;
    I3 = {src_code:#x};
    I4 = {code_n:#x};
    R1 = {n_code};
o_c:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R1 = R1 - 1;
    IF NE JUMP o_c;
    I3 = {src_data:#x};
    I4 = {data_d:#x};
    R1 = {n_data};
o_d:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R1 = R1 - 1;
    IF NE JUMP o_d;
    FLUSH CACHE;
    R0 = 1;
    DM(LOADED) = R0;
    R1 = DM(SV + 2);
    I3 = DM(SV + 3);
    I4 = DM(SV + 4);
o_go:
    R0 = DM(SV + 1);
    MODE1 = DM(SV + 0);
    NOP;
    JUMP {kernel:#x};
"""


def configure(**kw):
    CFG.update(kw)


class Stub:
    def __init__(self):
        self.places = {}

    def source(self, place):
        code, _, data0 = self.places[place]
        return ASM.format(data0=data0, code=code, src_code=CFG['src_code'], code_n=CFG['code_n'], n_code=CFG['n_code'],
                          src_data=CFG['src_data'], data_d=CFG['data0'], n_data=CFG['n_data'], kernel=CFG['kernel']), \
            (data0, data0 + NDATA)

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
    """(code words, data words, code address, data address) of a kernel assembled for its overlay region."""
    pm = [s for s in secs if s.kind == 'pm']
    dm = [s for s in secs if s.kind == 'dm']
    assert len(pm) == 1 and len(dm) == 1, 'an overlay kernel is one code and one data section'
    return packed(pm[0].words), list(dm[0].words), pm[0].addr, dm[0].addr


def normal_of(a48):
    assert not (a48 - 0xE0000) & 1, 'code must start on an even address'
    return 0xE0000 + (a48 - 0xE0000) * 3 // 2


class Flow:
    """A kernel through its stub, for kernel_rig.check: the kernel exists only as a payload in DDR2."""

    def __init__(self, spec, kplace, entry):
        self.k, self.kplace, self.kentry = spec, kplace, entry
        self.name, self.knobs, self.int_knobs, self.order = spec.name, spec.knobs, spec.int_knobs, spec.order
        self.slotw, self.nslots, self.entry, self.max_cycles = spec.slotw, spec.nslots, 'OVL_ENTRY', 20000
        self.places = SPEC.places

    def assemble(self, place):
        _, ksecs, ksyms, _, kdata = self.k.assemble(self.kplace)
        code, data, code48, data0 = payload(ksecs)
        src = 0x3E0000
        configure(src_code=src, n_code=len(code), code_n=normal_of(code48), src_data=src + len(code), n_data=len(data),
                  data0=data0, kernel=ksyms[self.kentry])
        s, secs, syms, end, sdata = SPEC.assemble(place)
        p = sasm.Section('dm', src)
        p.words = code + data
        self.pm_view = (code48, len(code) * 2 // 3)
        self.garbage = [(data0, data0 + len(data))]
        self.extra_writes = list(getattr(self.k, 'extra_writes', [])) + [
            (data0, data0 + len(data)), (normal_of(code48), normal_of(code48) + len(code)), (sdata[0], sdata[1])]
        return s, secs + [p], {**ksyms, **syms}, end, sdata


def check_flow(spec, kplace, entry, cases, rnd_knobs, seconds, place):
    return kr.check(Flow(spec, kplace, entry), place, cases, rnd_knobs, seconds)


def check(seconds=0.25, place='b3'):
    import ottobit_kernel as ok
    return check_flow(ok.SPEC, 'b3', 'OTTOBIT_ENTRY', ok.CASES, ok.rnd_knobs, seconds, place)
