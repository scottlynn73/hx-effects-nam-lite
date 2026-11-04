// commander_corrupt_kernel.asm - Commander (octave fuzz) and Corrupt (tracking synth) in one kernel,
// for the image that has both: they share the entry/exit, slot pool, knob-to-gain smoothing, tracking
// front end (DC block, lowpasses, envelope, comparator), gate, tone and the exp routine, which saves
// about 230 instructions of the DSP boot stream (Entry 2 must fit its 512 KiB partition). Two entry
// points, one per primitive; the mode (0 Commander, 1 Corrupt) is kept in the slot. Each path is a port
// of its C reference (effects/commander/commander.c, effects/corrupt/corrupt.c), checked word for word
// by commander_corrupt_kernel.py. Corrupt's gains sit where Commander's do (G0 Square, G1 Master,
// G2 Sub, G5 Output; G3/G4 stay 0) and its fixed -66 dB gate is written to THR.
//
// Knob words as the standalone kernels: Commander DM(5..10) Fuzz, Sub -1, Sub -2, Octave Up, Tone,
// Output; DM(11) Gate; DM(13) Dry. Corrupt DM(5..10) Square, Master, Sub, Glide, Tone, Output;
// DM(11) Root; DM(13) Harmonic.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

COMMANDER_ENTRY:
    DM(SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SAVE + 1) = R0;
    R0 = 0;
    JUMP k_save;
CORRUPT_ENTRY:
    DM(SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SAVE + 1) = R0;
    R0 = 1;
k_save:
    DM(SAVE + 2) = R1;
    DM(SAVE + 3) = R2;
    DM(SAVE + 4) = R3;
    DM(SAVE + 5) = R4;
    DM(SAVE + 6) = R5;
    DM(SAVE + 7) = R6;
    DM(SAVE + 8) = R7;
    DM(SAVE + 9) = R8;
    DM(SAVE + 10) = R9;
    DM(SAVE + 11) = R10;
    DM(SAVE + 12) = R11;
    DM(SAVE + 13) = R12;
    DM(SAVE + 14) = R13;
    DM(SAVE + 15) = R14;
    DM(SAVE + 16) = R15;
    DM(SAVE + 17) = I4;
    DM(SAVE + 18) = I3;
    DM(SAVE + 19) = I1;
    DM(SAVE + 20) = I2;
    L1 = 0; L2 = 0; L3 = 0; L4 = 0;

    // ---- this instance's slot (I3), as Click
    R9 = DM(G_CALLS);
    R9 = R9 + 1;
    DM(G_CALLS) = R9;
    R10 = I0;
    R11 = DM(P_SLOT, I0);
    R11 = PASS R11;
    IF EQ JUMP c_claim;
    R12 = T_SLOTBASE - 1;
    R12 = R12 + R11;
    I4 = R12;
    R12 = DM(0, I4);
    I3 = R12;
    R13 = DM(S_OWNER, I3);
    COMP(R13, R10);
    IF EQ JUMP c_have;
c_claim:
    R11 = 1;
    R14 = NSLOTS;
    I4 = T_SLOTBASE;
c_free:
    R12 = DM(I4, 1);
    I3 = R12;
    R13 = DM(S_OWNER, I3);
    R13 = PASS R13;
    IF EQ JUMP c_take;
    R11 = R11 + 1;
    R14 = R14 - 1;
    IF NE JUMP c_free;
    R11 = 1;
    R14 = NSLOTS;
    I4 = T_SLOTBASE;
c_stale:
    R12 = DM(I4, 1);
    I3 = R12;
    R13 = DM(S_LAST, I3);
    R13 = R9 - R13;
    R15 = STALE;
    COMP(R13, R15);
    IF GT JUMP c_take;
    R11 = R11 + 1;
    R14 = R14 - 1;
    IF NE JUMP c_stale;
    JUMP k_pass;
c_take:
    DM(P_SLOT, I0) = R11;
    DM(S_OWNER, I3) = R10;
    R13 = 0;
    R14 = 2;
    R14 = R12 + R14;
    I4 = R14;
    R14 = NSTATE;
c_zero:
    DM(I4, 1) = R13;
    R14 = R14 - 1;
    IF NE JUMP c_zero;
c_have:
    DM(S_LAST, I3) = R9;
    DM(ST_MODE, I3) = R0;
    R0 = PASS R0;
    IF NE JUMP r_knobs;

    // ---- knobs (clamped as fx_param_clamp does, finite values) -> the targets
    F0 = DM(5, I0);                     // Fuzz 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T0, I3) = F0;
    F0 = DM(6, I0);                     // Sub -1 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T1, I3) = F0;
    F0 = DM(7, I0);                     // Sub -2 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T2, I3) = F0;
    F0 = DM(8, I0);                     // Octave Up 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T3, I3) = F0;

    R2 = DM(13, I0);                    // Dry 0..10 -> k x 0.1
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 10;
    R2 = MIN(R2, R8);
    F0 = FLOAT R2;
    F8 = DM(K_01);
    F0 = F0 * F8;
    DM(ST_T4, I3) = F0;

    F0 = DM(10, I0);                    // Output dB -36..12 -> linear
    F8 = -36.0;
    F0 = MAX(F0, F8);
    F8 = 12.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_T5, I3) = F0;

    R2 = DM(11, I0);                    // Gate 0..10: 0 off, else exp((6k - 90) ln10/20)
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 10;
    R2 = MIN(R2, R8);
    F0 = 0.0;
    R2 = PASS R2;
    IF EQ JUMP h_gate;
    R8 = LSHIFT R2 BY 2;
    R9 = LSHIFT R2 BY 1;
    R8 = R8 + R9;                       // 6k
    R9 = 90;
    R8 = R8 - R9;
    F0 = FLOAT R8;
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
h_gate:
    DM(ST_THR, I3) = F0;

    F0 = DM(9, I0);                     // Tone 0..1 -> fc = 100 exp(tone ln 100), at most 0.45 sr
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN100);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 100.0;
    F0 = F8 * F0;
    F8 = DM(K_TOP);
    F0 = MIN(F0, F8);
    F8 = DM(K_NEG_W);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_TONEA, I3) = F0;

    JUMP k_primed;

r_knobs:
    // ---- knobs (clamped as fx_param_clamp does, finite values) -> the targets and coefficients
    F0 = DM(5, I0);
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T0, I3) = F0;
    F0 = DM(6, I0);
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T1, I3) = F0;
    F0 = DM(7, I0);
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_T2, I3) = F0;

    F0 = DM(10, I0);                    // Output dB -36..12 -> linear
    F8 = -36.0;
    F0 = MAX(F0, F8);
    F8 = 12.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_T5, I3) = F0;

    F0 = DM(8, I0);
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_GL);                      // Glide 0..1 -> k = exp(glide ln 1e-4)
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_GLK, I3) = F0;

    F0 = DM(9, I0);
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN100);                   // Tone -> fc = 100 exp(tone ln 100), at most 0.45 sr
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 100.0;
    F0 = F8 * F0;
    F8 = DM(K_TOP);
    F0 = MIN(F0, F8);
    F8 = DM(K_NEG_W);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_TONEA, I3) = F0;

    R2 = DM(11, I0);                    // Root 0..3, Harmonic 1..8 -> num = harm << (22 + root)
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 3;
    R2 = MIN(R2, R8);
    R8 = 22;
    R2 = R2 + R8;
    R3 = DM(13, I0);
    R8 = 1;
    R3 = MAX(R3, R8);
    R8 = 8;
    R3 = MIN(R3, R8);
    R3 = LSHIFT R3 BY R2;
    DM(ST_NUM, I3) = R3;

    F0 = DM(K_GATE);
    DM(ST_THR, I3) = F0;

k_primed:
    R8 = DM(ST_PRIMED, I3);             // first call: the gains start at their targets, the squares at +1
    R8 = PASS R8;
    IF NE JUMP k_loop;
    R8 = 1;
    DM(ST_PRIMED, I3) = R8;
    R8 = I3;
    R9 = ST_G0;
    R8 = R8 + R9;
    I4 = R8;
    R5 = CG_N;
p_g:
    F8 = DM(CG_N, I4);
    DM(I4, 1) = F8;
    R5 = R5 - 1;
    IF NE JUMP p_g;
    F8 = 1.0;
    DM(ST_SQ, I3) = F8;
    DM(ST_D1, I3) = F8;
    DM(ST_D2, I3) = F8;
    DM(ST_SUB, I3) = F8;

k_loop:
    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    R8 = I3;                            // the smoothed gains, toward their targets
    R9 = ST_G0;
    R8 = R8 + R9;
    I4 = R8;
    R5 = CG_N;
s_g:
    F8 = DM(0, I4);
    F9 = DM(CG_N, I4);
    CALL g_smooth;
    DM(I4, 1) = F8;
    R5 = R5 - 1;
    IF NE JUMP s_g;
    // DC block
    F8 = DM(ST_DCX, I3);
    F9 = F7 - F8;
    F10 = DM(K_DC_R);
    F11 = DM(ST_DCY, I3);
    F11 = F10 * F11;
    F9 = F9 + F11;
    DM(ST_DCX, I3) = F7;
    DM(ST_DCY, I3) = F9;
    // the tracking signal t (F13)
    F10 = DM(K_LPA);
    F11 = DM(ST_LP1, I3);
    F12 = F9 - F11;
    F12 = F10 * F12;
    F11 = F11 + F12;
    DM(ST_LP1, I3) = F11;
    F13 = DM(ST_LP2, I3);
    F12 = F11 - F13;
    F12 = F10 * F12;
    F13 = F13 + F12;
    DM(ST_LP2, I3) = F13;
    // envelope (F15), a = |t| (F14)
    F14 = ABS F13;
    F15 = DM(ST_ENV, I3);
    F12 = DM(K_REL);
    F12 = F15 * F12;
    COMP(F14, F15);
    IF GT F12 = PASS F14;
    F15 = PASS F12;
    DM(ST_ENV, I3) = F15;
    // the period counter, saturating
    R8 = DM(ST_CNT, I3);
    R9 = CNT_MAX;
    COMP(R8, R9);
    IF GE JUMP n_cnt;
    R8 = R8 + 1;
    DM(ST_CNT, I3) = R8;
n_cnt:
    // the comparator, with hysteresis h (F12); on a rising edge, the period
    F12 = DM(K_HYST);
    F12 = F15 * F12;
    F11 = DM(K_HFLOOR);
    F12 = F12 + F11;
    F11 = DM(ST_SQ, I3);
    F11 = PASS F11;
    IF LE JUMP c_low;
    F10 = -F12;
    COMP(F13, F10);
    IF GE JUMP c_done;
    F11 = -1.0;
    DM(ST_SQ, I3) = F11;
    JUMP c_done;
c_low:
    COMP(F13, F12);
    IF LE JUMP c_done;
    F11 = 1.0;
    DM(ST_SQ, I3) = F11;
    R8 = DM(ST_MODE, I3);
    R8 = PASS R8;
    IF NE JUMP c_period;
    F10 = DM(ST_D1, I3);                // Commander: the dividers step
    F10 = -F10;
    DM(ST_D1, I3) = F10;
    F10 = PASS F10;
    IF LE JUMP c_done;
    F10 = DM(ST_D2, I3);
    F10 = -F10;
    DM(ST_D2, I3) = F10;
    JUMP c_done;
c_period:
    R1 = DM(ST_CNT, I3);                // the period P
    R8 = 0;
    DM(ST_CNT, I3) = R8;
    R8 = PMIN;
    COMP(R1, R8);
    IF LT JUMP c_done;
    R8 = PMAX;
    COMP(R1, R8);
    IF GT JUMP c_done;
    R0 = DM(ST_NUM, I3);                // q = num / P: restoring division, 29 bits (num < 2^29)
    R0 = LSHIFT R0 BY 3;
    R2 = 0;
    R3 = 0;
    R4 = 29;
d_loop:
    R2 = LSHIFT R2 BY 1;
    R0 = PASS R0;
    IF LT R2 = R2 + 1;
    R0 = LSHIFT R0 BY 1;
    R3 = LSHIFT R3 BY 1;
    COMP(R2, R1);
    IF LT JUMP d_skip;
    R2 = R2 - R1;
    R3 = R3 + 1;
d_skip:
    R4 = R4 - 1;
    IF NE JUMP d_loop;
    R8 = QMAX;
    R3 = MIN(R3, R8);
    F3 = FLOAT R3;
    F8 = DM(K_2M24);
    F3 = F3 * F8;
    DM(ST_INCT, I3) = F3;
c_done:
    R8 = DM(ST_MODE, I3);
    R8 = PASS R8;
    IF NE JUMP o_corrupt;
    // octave up (F11): |t| above half the envelope
    F10 = 0.5;
    F10 = F15 * F10;
    F11 = -1.0;
    COMP(F14, F10);
    IF LE JUMP u_done;
    F11 = 1.0;
u_done:
    // the mix of the squares (F13)
    F8 = DM(ST_SQ, I3);
    F9 = DM(ST_G0, I3);
    F8 = F8 * F9;
    F9 = DM(ST_D1, I3);
    F10 = DM(ST_G1, I3);
    F9 = F9 * F10;
    F8 = F8 + F9;
    F9 = DM(ST_D2, I3);
    F10 = DM(ST_G2, I3);
    F9 = F9 * F10;
    F8 = F8 + F9;
    F10 = DM(ST_G3, I3);
    F11 = F11 * F10;
    F13 = F8 + F11;
    JUMP m_level;
o_corrupt:
    // the oscillator: the rate glides to its target; Master (F11) and Sub
    F8 = DM(ST_INC, I3);
    F9 = DM(ST_INCT, I3);
    F9 = F9 - F8;
    F10 = DM(ST_GLK, I3);
    F9 = F10 * F9;
    F8 = F8 + F9;
    DM(ST_INC, I3) = F8;
    F9 = DM(ST_PH, I3);
    F9 = F9 + F8;
    F10 = 1.0;
    COMP(F9, F10);
    IF LT JUMP o_nw;
    F9 = F9 - F10;
    F11 = DM(ST_SUB, I3);
    F11 = -F11;
    DM(ST_SUB, I3) = F11;
o_nw:
    DM(ST_PH, I3) = F9;
    F11 = 1.0;
    F10 = 0.5;
    COMP(F9, F10);
    IF LT JUMP o_m;
    F11 = -1.0;
o_m:
    // the mix (F13)
    F8 = DM(ST_SQ, I3);
    F9 = DM(ST_G0, I3);
    F8 = F8 * F9;
    F9 = DM(ST_G1, I3);
    F11 = F11 * F9;
    F8 = F8 + F11;
    F9 = DM(ST_SUB, I3);
    F10 = DM(ST_G2, I3);
    F9 = F9 * F10;
    F13 = F8 + F9;
m_level:
    // level (F14): envelope x 4, at most 1
    F9 = 4.0;
    F14 = F15 * F9;
    F9 = 1.0;
    F14 = MIN(F14, F9);
    // the gate
    F10 = DM(ST_THR, I3);
    F9 = 0.0;
    COMP(F15, F10);
    IF LE JUMP g_done;
    F9 = 1.0;
g_done:
    F8 = DM(ST_GGATE, I3);
    CALL g_smooth;
    DM(ST_GGATE, I3) = F8;
    F13 = F13 * F14;
    F13 = F13 * F8;                     // w
    // tone
    F10 = DM(ST_TONEA, I3);
    F11 = DM(ST_TA, I3);
    F12 = F13 - F11;
    F12 = F10 * F12;
    F11 = F11 + F12;
    DM(ST_TA, I3) = F11;
    F13 = DM(ST_TB, I3);
    F12 = F11 - F13;
    F12 = F10 * F12;
    F13 = F13 + F12;
    DM(ST_TB, I3) = F13;
    R8 = DM(ST_MODE, I3);
    R8 = PASS R8;
    IF NE JUMP y_corrupt;
    // out = x dry + tone x output
    F8 = DM(ST_G4, I3);
    F8 = F7 * F8;
    F9 = DM(ST_G5, I3);
    F9 = F13 * F9;
    F9 = F8 + F9;
    JUMP y_guard;
y_corrupt:
    // DC block, output gain
    F8 = DM(ST_OX, I3);
    F12 = F13 - F8;
    F10 = DM(K_DC_R);
    F11 = DM(ST_OY, I3);
    F11 = F10 * F11;
    F12 = F12 + F11;
    DM(ST_OX, I3) = F13;
    DM(ST_OY, I3) = F12;
    F9 = DM(ST_G5, I3);
    F9 = F12 * F9;
y_guard:
    // never pass on a bad value
    F10 = ABS F9;
    F11 = 8.0;
    COMP(F10, F11);
    IF LE JUMP s_out;
    R9 = 0;
    DM(ST_DCX, I3) = R9;
    DM(ST_DCY, I3) = R9;
    DM(ST_LP1, I3) = R9;
    DM(ST_LP2, I3) = R9;
    DM(ST_ENV, I3) = R9;
    DM(ST_TA, I3) = R9;
    DM(ST_TB, I3) = R9;
    DM(ST_OX, I3) = R9;
    DM(ST_OY, I3) = R9;
s_out:
    DM(I2, 1) = R9;
    R6 = R6 - 1;
    IF NE JUMP s_loop;
    JUMP k_exit;

k_pass:                                 // no slot free: pass the input through
    R6 = 16;
k_pw:
    R7 = DM(I1, 1);
    DM(I2, 1) = R7;
    R6 = R6 - 1;
    IF NE JUMP k_pw;

k_exit:
    R0 = DM(SAVE + 1);
    R1 = DM(SAVE + 2);
    R2 = DM(SAVE + 3);
    R3 = DM(SAVE + 4);
    R4 = DM(SAVE + 5);
    R5 = DM(SAVE + 6);
    R6 = DM(SAVE + 7);
    R7 = DM(SAVE + 8);
    R8 = DM(SAVE + 9);
    R9 = DM(SAVE + 10);
    R10 = DM(SAVE + 11);
    R11 = DM(SAVE + 12);
    R12 = DM(SAVE + 13);
    R13 = DM(SAVE + 14);
    R14 = DM(SAVE + 15);
    R15 = DM(SAVE + 16);
    I4 = DM(SAVE + 17);
    I3 = DM(SAVE + 18);
    I1 = DM(SAVE + 19);
    I2 = DM(SAVE + 20);
    MODE1 = DM(SAVE + 0);
    NOP;
    RTS (LR);

// ---- F8 = smooth(F8 current, F9 target): the target once within 1e-6, else cur + k (target - cur)
g_smooth:
    F10 = F9 - F8;
    F11 = ABS F10;
    F12 = DM(K_EPS);
    COMP(F11, F12);
    IF GE JUMP g_sm1;
    F8 = PASS F9;
    RTS;
g_sm1:
    F12 = DM(K_SMK);
    F10 = F12 * F10;
    F8 = F8 + F10;
    RTS;

// ---- F0 = geiger_exp(F0): Taylor degree 6 of z = y/16 (Horner), squared four times. Uses F2, F3, F4.
g_exp:
    F2 = 0.0625;
    F2 = F0 * F2;
    F3 = DM(K_C6);
    F3 = F3 * F2;
    F4 = DM(K_C5);
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = DM(K_C4);
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = DM(K_C3);
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = 0.5;
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = 1.0;
    F3 = F3 + F4;
    F3 = F3 * F2;
    F3 = F3 + F4;
    F3 = F3 * F3;
    F3 = F3 * F3;
    F3 = F3 * F3;
    F0 = F3 * F3;
    RTS;
