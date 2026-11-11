// ottobit_kernel.asm - Ottobit (sequenced crusher, resonant filter, stutters) for the HX Effects SHARC.
// A port of effects/ottobit/ottobit.c; ottobit_kernel.py checks it bit for bit against that reference
// in ssim and puts the .equ block, constants and tables at "EQUS".
//
// Conventions as the other kernels (effects/README.md): once per 16-sample block, I0 = the instance's
// DM block, I1 = 16 inputs, I2 = 16 outputs; R0-R15, I1-I4 and MODE1 come back unchanged; L1-L4 left
// 0; no hardware loops; DM(3, I0) never touched; only P_SLOT (12) written; state in one of NSLOTS
// claimed slots; each slot's stutter ring (RING_N words) at RING0 + (slot - 1) x RING_N, zeroed on claim.
//
// Knob words: DM(5) Rate Hz, DM(6) Bits (int 1..16), DM(7) Filter 0..1, DM(8) Pattern (int 0..8),
//             DM(9) Speed steps/s, DM(10) Stutter 0..1, DM(11) Output dB, DM(13) Mix 0..1.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

OTTOBIT_ENTRY:
    DM(SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SAVE + 1) = R0;
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
    R13 = SEED;                         // reset(): the PRNG's seed, a first "previous step" length
    DM(ST_RND, I3) = R13;
    R13 = PREV0;
    DM(ST_PREV, I3) = R13;
    R13 = R11 - 1;                      // this slot's ring, zeroed
    R13 = LSHIFT R13 BY RING_SHIFT;
    R14 = RING0;
    R13 = R13 + R14;
    DM(ST_RING, I3) = R13;
    I4 = R13;
    R13 = 0;
    R14 = RING_N;
c_rz:
    DM(I4, 1) = R13;
    R14 = R14 - 1;
    IF NE JUMP c_rz;
c_have:
    DM(S_LAST, I3) = R9;

    // ---- knobs (clamped as fx_param_clamp does, finite values)
    F0 = DM(5, I0);                     // Rate 250..48000 Hz -> inc
    F8 = 250.0;
    F0 = MAX(F0, F8);
    F8 = 48000.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_INV_SR);
    F0 = F0 * F8;
    DM(ST_INC, I3) = F0;

    R2 = DM(6, I0);                     // Bits 1..16 -> q, 1/q
    R8 = 1;
    R2 = MAX(R2, R8);
    R8 = 16;
    R2 = MIN(R2, R8);
    R8 = T_Q;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_Q, I3) = F8;
    R8 = T_QI;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_QI, I3) = F8;

    F0 = DM(7, I0);                     // Filter 0..1 -> 100 exp(f ln 80) Hz
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN80);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 100.0;
    F0 = F8 * F0;
    DM(ST_FBASE, I3) = F0;

    R2 = DM(8, I0);                     // Pattern 0..8 -> its row (12 words)
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 8;
    R2 = MIN(R2, R8);
    R8 = LSHIFT R2 BY 3;
    R9 = LSHIFT R2 BY 2;
    R8 = R8 + R9;
    R9 = T_PAT;
    R8 = R8 + R9;
    DM(ST_PAT, I3) = R8;

    F0 = DM(9, I0);                     // Speed 0.5..16 steps/s -> sinc
    F8 = 0.5;
    F0 = MAX(F0, F8);
    F8 = 16.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_INV_SR);
    F0 = F0 * F8;
    DM(ST_SINC, I3) = F0;

    F0 = DM(10, I0);                    // Stutter 0..1 -> threshold, x 2^24 truncated
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_2P24);
    F0 = F0 * F8;
    R0 = TRUNC F0;
    DM(ST_THR, I3) = R0;

    F0 = DM(11, I0);                    // Output dB -36..12 -> linear
    F8 = -36.0;
    F0 = MAX(F0, F8);
    F8 = 12.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_TOUT, I3) = F0;

    F0 = DM(13, I0);                    // Mix 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_TMIX, I3) = F0;

    R8 = DM(ST_PRIMED, I3);             // first call: the gains start at their targets
    R8 = PASS R8;
    IF NE JUMP k_loop;
    R8 = 1;
    DM(ST_PRIMED, I3) = R8;
    F8 = DM(ST_TOUT, I3);
    DM(ST_GOUT, I3) = F8;
    F8 = DM(ST_TMIX, I3);
    DM(ST_GMIX, I3) = F8;

k_loop:
    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    F8 = DM(ST_GOUT, I3);
    F9 = DM(ST_TOUT, I3);
    CALL g_smooth;
    DM(ST_GOUT, I3) = F8;
    F8 = DM(ST_GMIX, I3);
    F9 = DM(ST_TMIX, I3);
    CALL g_smooth;
    DM(ST_GMIX, I3) = F8;

    // ---- the sequencer
    R8 = DM(ST_CNT, I3);
    R8 = R8 + 1;
    DM(ST_CNT, I3) = R8;
    F8 = DM(ST_SPHASE, I3);
    F9 = DM(ST_SINC, I3);
    F8 = F8 + F9;
    F9 = 1.0;
    COMP(F8, F9);
    IF LT JUMP q_nostep;
    F8 = F8 - F9;
    DM(ST_SPHASE, I3) = F8;
    R8 = DM(ST_STEP, I3);
    R8 = R8 + 1;
    R9 = NSTEPS;
    COMP(R8, R9);
    IF LT JUMP q_s1;
    R8 = 0;
q_s1:
    DM(ST_STEP, I3) = R8;
    R8 = DM(ST_CNT, I3);
    DM(ST_PREV, I3) = R8;
    R9 = 0;
    DM(ST_CNT, I3) = R9;
    R8 = DM(ST_RND, I3);                // xorshift32
    R9 = LSHIFT R8 BY 13;
    R8 = R8 XOR R9;
    R9 = LSHIFT R8 BY -17;
    R8 = R8 XOR R9;
    R9 = LSHIFT R8 BY 5;
    R8 = R8 XOR R9;
    DM(ST_RND, I3) = R8;
    R8 = LSHIFT R8 BY -8;
    R9 = DM(ST_THR, I3);
    R10 = 0;
    COMP(R8, R9);
    IF GE JUMP q_set;
    R10 = 1;
q_set:
    DM(ST_STUT, I3) = R10;
    R10 = PASS R10;
    IF EQ JUMP q_done;
    R8 = DM(ST_PREV, I3);               // the loop: a quarter of the previous step, 64 .. RING_N
    R8 = LSHIFT R8 BY -2;
    R9 = LMIN;
    R8 = MAX(R8, R9);
    R9 = RING_N;
    R8 = MIN(R8, R9);
    DM(ST_LEN, I3) = R8;
    R9 = DM(ST_W, I3);
    R9 = R9 - R8;
    R10 = RING_MASK;
    R9 = R9 AND R10;
    DM(ST_START, I3) = R9;
    R9 = 0;
    DM(ST_J, I3) = R9;
    JUMP q_done;
q_nostep:
    DM(ST_SPHASE, I3) = F8;
q_done:

    // ---- DC block (F9)
    F8 = DM(ST_DCX, I3);
    F9 = F7 - F8;
    F10 = DM(K_DC_R);
    F11 = DM(ST_DCY, I3);
    F11 = F10 * F11;
    F9 = F9 + F11;
    DM(ST_DCX, I3) = F7;
    DM(ST_DCY, I3) = F9;

    // ---- stutter: play the loop, or record (F9 = the source)
    R10 = DM(ST_RING, I3);
    R8 = DM(ST_STUT, I3);
    R8 = PASS R8;
    IF EQ JUMP r_rec;
    R8 = DM(ST_START, I3);
    R11 = DM(ST_J, I3);
    R8 = R8 + R11;
    R12 = RING_MASK;
    R8 = R8 AND R12;
    R8 = R8 + R10;
    I4 = R8;
    F9 = DM(0, I4);
    R11 = R11 + 1;
    R12 = DM(ST_LEN, I3);
    COMP(R11, R12);
    IF LT JUMP r_j;
    R11 = 0;
r_j:
    DM(ST_J, I3) = R11;
    JUMP r_done;
r_rec:
    R8 = DM(ST_W, I3);
    R11 = R8 + R10;
    I4 = R11;
    DM(0, I4) = F9;
    R8 = R8 + 1;
    R12 = RING_MASK;
    R8 = R8 AND R12;
    DM(ST_W, I3) = R8;
r_done:

    // ---- sample-and-hold at inc x the step's rate multiplier (I4 -> the step's pair)
    R8 = DM(ST_STEP, I3);
    R8 = LSHIFT R8 BY 1;
    R11 = DM(ST_PAT, I3);
    R8 = R8 + R11;
    I4 = R8;
    F10 = DM(ST_INC, I3);
    F11 = DM(0, I4);
    F10 = F10 * F11;
    F8 = DM(ST_PHASE, I3);
    F8 = F8 + F10;
    F11 = 1.0;
    COMP(F8, F11);
    IF LT JUMP h_keep;
    F8 = F8 - F11;
    DM(ST_HELD, I3) = F9;
h_keep:
    DM(ST_PHASE, I3) = F8;

    // ---- quantise (as geiger_quantize)
    F9 = DM(ST_HELD, I3);
    F10 = -1.0;
    F9 = MAX(F9, F10);
    F10 = 1.0;
    F9 = MIN(F9, F10);
    F10 = DM(ST_Q, I3);
    F9 = F9 * F10;
    F10 = 0.5;
    F9 = F9 + F10;
    R11 = TRUNC F9;                     // floor: truncate, one less if that rounded up
    F11 = FLOAT R11;
    COMP(F11, F9);
    IF LE JUMP s_fl;
    F10 = 1.0;
    F11 = F11 - F10;
s_fl:
    F10 = DM(ST_QI, I3);
    F9 = F11 * F10;

    // ---- the filter: f = 2 sin(fbase x the step's filter multiplier x pi / sr), Chamberlin
    F10 = DM(ST_FBASE, I3);
    F11 = DM(1, I4);
    F10 = F10 * F11;
    F11 = DM(K_PI_SR);
    F10 = F10 * F11;                    // x
    F11 = F10 * F10;                    // x^2
    F12 = DM(K_S7);
    F12 = F12 * F11;
    F13 = DM(K_S5);
    F12 = F12 + F13;
    F12 = F12 * F11;
    F13 = DM(K_S3);
    F12 = F12 + F13;
    F12 = F12 * F11;
    F13 = 1.0;
    F12 = F12 + F13;
    F12 = F12 * F10;                    // sin
    F13 = 2.0;
    F12 = F13 * F12;                    // f
    F10 = DM(ST_LOW, I3);
    F11 = DM(ST_BAND, I3);
    F13 = F12 * F11;
    F10 = F10 + F13;                    // low += f band
    F13 = F9 - F10;
    F14 = DM(K_Q);
    F14 = F14 * F11;
    F13 = F13 - F14;                    // high = y - low - q band
    F14 = F12 * F13;
    F11 = F11 + F14;                    // band += f high
    DM(ST_LOW, I3) = F10;
    DM(ST_BAND, I3) = F11;
    F9 = PASS F10;

    // ---- DC block, output gain, mix
    F8 = DM(ST_OX, I3);
    F13 = F9 - F8;
    F10 = DM(K_DC_R);
    F11 = DM(ST_OY, I3);
    F11 = F10 * F11;
    F13 = F13 + F11;
    DM(ST_OX, I3) = F9;
    DM(ST_OY, I3) = F13;
    F8 = DM(ST_GOUT, I3);
    F13 = F13 * F8;                     // wet
    F8 = DM(ST_GMIX, I3);
    F10 = 1.0;
    F10 = F10 - F8;
    F10 = F7 * F10;
    F13 = F13 * F8;
    F9 = F10 + F13;
    // never pass on a bad value
    F10 = ABS F9;
    F11 = 8.0;
    COMP(F10, F11);
    IF LE JUMP s_out;
    R9 = 0;
    DM(ST_DCX, I3) = R9;
    DM(ST_DCY, I3) = R9;
    DM(ST_OX, I3) = R9;
    DM(ST_OY, I3) = R9;
    DM(ST_HELD, I3) = R9;
    DM(ST_LOW, I3) = R9;
    DM(ST_BAND, I3) = R9;
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
