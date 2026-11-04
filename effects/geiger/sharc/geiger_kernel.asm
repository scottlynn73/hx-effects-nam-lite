// geiger_kernel.asm - Geiger (bit crusher / sample-rate reducer / waveshaper) for the HX Effects
// SHARC. A port of effects/geiger/geiger.c; geiger_kernel.py checks it bit for bit against that
// reference in ssim and puts the .equ block, constants and the curve tables at "EQUS".
//
// Conventions (as Click's, learned on the unit; effects/README.md):
// - once per 16-sample block; I0 = the instance's DM block, I1 = 16 input floats, I2 = 16 outputs;
// - R0-R15, I1-I4 and MODE1 come back unchanged; L1-L4 are left 0; no hardware loops;
// - DM(3, I0) is not ours: never read or written. The only instance word written is P_SLOT (12);
//   the state lives in one of NSLOTS slots in DM, claimed per instance as Click claims them.
//
// Knob words: DM(5) Gain dB, DM(6) Rate Hz, DM(7) Bits (int), DM(8) Curve (int), DM(9) Tone 0..1,
//             DM(10) Output dB, DM(11) Mix 0..1, DM(13) Anti-Alias (int 0/1).

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

GEIGER_ENTRY:
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
c_have:
    DM(S_LAST, I3) = R9;

    // ---- knobs (clamped as fx_param_clamp does, finite values) and coefficients
    F0 = DM(5, I0);                     // Gain dB 0..36 -> linear
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 36.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_GAINT, I3) = F0;

    F0 = DM(10, I0);                    // Output dB -36..12 -> linear
    F8 = -36.0;
    F0 = MAX(F0, F8);
    F8 = 12.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN10_20);
    F0 = F0 * F8;
    CALL g_exp;
    DM(ST_OUTT, I3) = F0;

    F0 = DM(11, I0);                    // Mix 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_MIXT, I3) = F0;

    F5 = DM(6, I0);                     // Rate 250..48000 Hz (and <= sr)
    F8 = 250.0;
    F5 = MAX(F5, F8);
    F8 = 48000.0;
    F5 = MIN(F5, F8);
    F8 = DM(K_INV_SR);
    F1 = F5 * F8;                       // F1: inc
    DM(ST_INC, I3) = F1;
    F8 = DM(K_04);
    F0 = F5 * F8;                       // fc = 0.4 rate
    F8 = DM(K_NEG_W);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_AAA, I3) = F0;                // aa_a

    F0 = DM(9, I0);                     // Tone 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN100);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 200.0;
    F0 = F8 * F0;                       // fc = 200 x exp(tone ln 100)
    F8 = DM(K_TOP);
    COMP(F0, F8);
    IF GT F0 = PASS F8;
    F8 = DM(K_NEG_W);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_TONEA, I3) = F0;              // tone_a

    R2 = DM(7, I0);                     // Bits 1..16 -> q, 1/q
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

    R3 = DM(8, I0);                     // Curve 0..15 -> its table
    R8 = 0;
    R3 = MAX(R3, R8);
    R8 = 15;
    R3 = MIN(R3, R8);
    R8 = LSHIFT R3 BY 7;                // x 129
    R3 = R8 + R3;
    R8 = T_CURVES;
    R3 = R3 + R8;
    DM(ST_TAB, I3) = R3;

    R4 = DM(13, I0);                    // Anti-Alias: on, and the rate below sr
    R8 = 0;
    R4 = MAX(R4, R8);
    R8 = 1;
    R4 = MIN(R4, R8);
    F8 = 1.0;
    COMP(F1, F8);                       // inc < 1 ?
    IF GE R4 = R4 - R4;
    DM(ST_AAON, I3) = R4;

    R8 = DM(ST_PRIMED, I3);             // first call: the smoothed gains start at their targets
    R8 = PASS R8;
    IF NE JUMP k_loop;
    R8 = 1;
    DM(ST_PRIMED, I3) = R8;
    F8 = DM(ST_GAINT, I3);
    DM(ST_GGAIN, I3) = F8;
    F8 = DM(ST_OUTT, I3);
    DM(ST_GOUT, I3) = F8;
    F8 = DM(ST_MIXT, I3);
    DM(ST_GMIX, I3) = F8;

k_loop:
    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    // smoothed gains
    F8 = DM(ST_GGAIN, I3);
    F9 = DM(ST_GAINT, I3);
    CALL g_smooth;
    DM(ST_GGAIN, I3) = F8;
    F8 = DM(ST_GOUT, I3);
    F9 = DM(ST_OUTT, I3);
    CALL g_smooth;
    DM(ST_GOUT, I3) = F8;
    F8 = DM(ST_GMIX, I3);
    F9 = DM(ST_MIXT, I3);
    CALL g_smooth;
    DM(ST_GMIX, I3) = F8;
    // DC block, gain
    F8 = DM(ST_DCINX, I3);
    F9 = F7 - F8;
    F10 = DM(K_DC_R);
    F11 = DM(ST_DCINY, I3);
    F11 = F10 * F11;
    F9 = F9 + F11;
    DM(ST_DCINX, I3) = F7;
    DM(ST_DCINY, I3) = F9;
    F8 = DM(ST_GGAIN, I3);
    F9 = F9 * F8;                       // F9: y
    // anti-alias
    R8 = DM(ST_AAON, I3);
    R8 = PASS R8;
    IF EQ JUMP s_sh;
    F10 = DM(ST_AAA, I3);
    F11 = DM(ST_AA1, I3);
    F12 = F9 - F11;
    F12 = F10 * F12;
    F11 = F11 + F12;
    DM(ST_AA1, I3) = F11;
    F13 = DM(ST_AA2, I3);
    F12 = F11 - F13;
    F12 = F10 * F12;
    F13 = F13 + F12;
    DM(ST_AA2, I3) = F13;
    F9 = PASS F13;
s_sh:
    // sample-and-hold at Rate
    F10 = DM(ST_PHASE, I3);
    F11 = DM(ST_INC, I3);
    F10 = F10 + F11;
    F11 = 1.0;
    COMP(F10, F11);
    IF LT JUMP s_noh;
    F10 = F10 - F11;
    DM(ST_HELD, I3) = F9;
s_noh:
    DM(ST_PHASE, I3) = F10;
    // quantise
    F9 = DM(ST_HELD, I3);
    F10 = -1.0;
    F9 = MAX(F9, F10);
    F10 = 1.0;
    F9 = MIN(F9, F10);
    F10 = DM(ST_Q, I3);
    F9 = F9 * F10;
    F10 = 0.5;
    F9 = F9 + F10;                      // v
    R11 = TRUNC F9;                     // floor(v): truncate, one less if that rounded up
    F11 = FLOAT R11;
    COMP(F11, F9);
    IF LE JUMP s_fl;
    F10 = 1.0;
    F11 = F11 - F10;
s_fl:
    F10 = DM(ST_QI, I3);
    F9 = F11 * F10;
    // the curve: 129-point table, linear interpolation
    F10 = -1.0;
    F9 = MAX(F9, F10);
    F10 = 1.0;
    F9 = MIN(F9, F10);
    F9 = F9 + F10;
    F10 = 64.0;
    F9 = F9 * F10;                      // p
    R11 = TRUNC F9;                     // i
    R12 = 127;
    R11 = MIN(R11, R12);
    F12 = FLOAT R11;
    F9 = F9 - F12;                      // f
    R12 = DM(ST_TAB, I3);
    R11 = R11 + R12;
    I4 = R11;
    F12 = DM(0, I4);
    F13 = DM(1, I4);
    F13 = F13 - F12;
    F13 = F9 * F13;
    F9 = F12 + F13;
    // tone
    F10 = DM(ST_TONEA, I3);
    F11 = DM(ST_TONEZ, I3);
    F12 = F9 - F11;
    F12 = F10 * F12;
    F11 = F11 + F12;
    DM(ST_TONEZ, I3) = F11;
    // DC block (the rectifying curves add DC), output gain
    F8 = DM(ST_DCOUTX, I3);
    F12 = F11 - F8;
    F10 = DM(K_DC_R);
    F13 = DM(ST_DCOUTY, I3);
    F13 = F10 * F13;
    F12 = F12 + F13;
    DM(ST_DCOUTX, I3) = F11;
    DM(ST_DCOUTY, I3) = F12;
    F8 = DM(ST_GOUT, I3);
    F12 = F12 * F8;                     // wet
    // mix
    F8 = DM(ST_GMIX, I3);
    F10 = 1.0;
    F10 = F10 - F8;
    F10 = F7 * F10;
    F12 = F12 * F8;
    F9 = F10 + F12;                     // y
    // never pass on a bad value
    F10 = ABS F9;
    F11 = 8.0;
    COMP(F10, F11);
    IF LE JUMP s_out;
    R9 = 0;
    DM(ST_DCINX, I3) = R9;
    DM(ST_DCINY, I3) = R9;
    DM(ST_DCOUTX, I3) = R9;
    DM(ST_DCOUTY, I3) = R9;
    DM(ST_AA1, I3) = R9;
    DM(ST_AA2, I3) = R9;
    DM(ST_HELD, I3) = R9;
    DM(ST_TONEZ, I3) = R9;
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
