// warp_kernel.asm - Warp (modulated pitch shifter with regeneration) for the HX Effects SHARC. A port of
// effects/warp/warp.c; warp_kernel.py checks it bit for bit against that reference in ssim and puts the
// .equ block, constants and tables at "EQUS".
//
// Conventions as the other kernels (effects/README.md): once per 16-sample block, I0 = the instance's
// DM block, I1 = 16 inputs, I2 = 16 outputs; R0-R15, I1-I4 and MODE1 come back unchanged; L1-L4 left
// 0; no hardware loops; DM(3, I0) never touched; only P_SLOT (12) written; state in one of NSLOTS
// claimed slots; each slot's ring (RING_N words) at RING0 + (slot - 1) x RING_N, zeroed on claim.
//
// Knob words: DM(5) Pitch (int 0..7), DM(6) Depth 0..1, DM(7) Rate Hz, DM(8) Chaos 0..1,
//             DM(9) Feedback 0..0.95, DM(10) Tone 0..1, DM(11) Output dB, DM(13) Mix 0..1.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

WARP_ENTRY:
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
    R13 = SEED;                         // reset(): the PRNG's seed
    DM(ST_RND, I3) = R13;
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
    R2 = DM(5, I0);                     // Pitch 0..7 -> ratio
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 7;
    R2 = MIN(R2, R8);
    R8 = T_RATIO;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_RATIO, I3) = F8;

    F0 = DM(6, I0);                     // Depth 0..1 -> x 0.03
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_MD);
    F0 = F0 * F8;
    DM(ST_DEPTH, I3) = F0;

    F0 = DM(7, I0);                     // Rate 0.05..10 Hz
    F8 = DM(K_RMIN);
    F0 = MAX(F0, F8);
    F8 = 10.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_INV48);
    F0 = F0 * F8;
    DM(ST_LINC, I3) = F0;

    F0 = DM(8, I0);                     // Chaos 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_CHAOS, I3) = F0;

    F0 = DM(9, I0);                     // Feedback 0..0.95
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = DM(K_FBMAX);
    F0 = MIN(F0, F8);
    DM(ST_FB, I3) = F0;

    F0 = DM(10, I0);                    // Tone 0..1 -> 200 exp(t ln 100) Hz, at most 0.45 sr -> tone_a
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN100);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 200.0;
    F0 = F8 * F0;
    F8 = DM(K_TOP);
    COMP(F0, F8);
    IF GT F0 = PASS F8;
    F8 = DM(K_NEG_W);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_TONEA, I3) = F0;

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

    R8 = DM(ST_PRIMED, I3);             // first call: the gains at their targets
    R8 = PASS R8;
    IF NE JUMP k_loop;
    R8 = 1;
    DM(ST_PRIMED, I3) = R8;
    F8 = DM(ST_TOUT, I3);
    DM(ST_GOUT, I3) = F8;
    F8 = DM(ST_TMIX, I3);
    DM(ST_GMIX, I3) = F8;

k_loop:
    R4 = DM(ST_RING, I3);               // the ring's base, all call
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

    // ---- the modulation
    F8 = DM(ST_LPH, I3);
    F9 = DM(ST_LINC, I3);
    F8 = F8 + F9;
    F9 = 1.0;
    COMP(F8, F9);
    IF LT JUMP m_keep;
    F8 = F8 - F9;
    R10 = DM(ST_RND, I3);               // xorshift32 -> a new chaos target in [-1, 1)
    R11 = LSHIFT R10 BY 13;
    R10 = R10 XOR R11;
    R11 = LSHIFT R10 BY -17;
    R10 = R10 XOR R11;
    R11 = LSHIFT R10 BY 5;
    R10 = R10 XOR R11;
    DM(ST_RND, I3) = R10;
    R10 = LSHIFT R10 BY -8;
    F10 = FLOAT R10;
    F11 = DM(K_2M24);
    F10 = F10 * F11;
    F11 = 2.0;
    F10 = F10 * F11;
    F11 = 1.0;
    F10 = F10 - F11;
    DM(ST_CT, I3) = F10;
m_keep:
    DM(ST_LPH, I3) = F8;
    F9 = DM(ST_CV, I3);                 // cv glides to ct
    F10 = DM(ST_CT, I3);
    F10 = F10 - F9;
    F11 = DM(K_CV);
    F10 = F11 * F10;
    F9 = F9 + F10;
    DM(ST_CV, I3) = F9;
    F10 = 0.5;                          // tri = 1 - 4 |lph - 0.5|
    F10 = F8 - F10;
    F10 = ABS F10;
    F11 = 4.0;
    F10 = F11 * F10;
    F11 = 1.0;
    F10 = F11 - F10;
    F12 = DM(ST_CHAOS, I3);             // mod = tri (1 - chaos) + cv chaos
    F13 = F11 - F12;
    F10 = F10 * F13;
    F9 = F9 * F12;
    F10 = F10 + F9;
    F11 = DM(ST_DEPTH, I3);             // r = ratio (1 + depth mod)
    F10 = F11 * F10;
    F11 = 1.0;
    F10 = F11 + F10;
    F12 = DM(ST_RATIO, I3);
    F10 = F12 * F10;

    // ---- the shifter: d (F8), d2 (F9), gains g1 (F10), g2 (F11)
    F11 = 1.0;
    F10 = F11 - F10;
    F8 = DM(ST_D, I3);
    F8 = F8 + F10;
    F12 = DM(K_WIN);
    F13 = 0.0;
    COMP(F8, F13);
    IF GE JUMP d_pos;
    F8 = F8 + F12;
d_pos:
    COMP(F8, F12);
    IF LT JUMP d_in;
    F8 = F8 - F12;
d_in:
    DM(ST_D, I3) = F8;
    F13 = DM(K_HALF);
    F9 = F8 + F13;
    COMP(F9, F12);
    IF LT JUMP d2_in;
    F9 = F9 - F12;
d2_in:
    F12 = DM(K_2W);
    F13 = 1.0;
    F10 = F8 * F12;
    F10 = F10 - F13;
    F10 = ABS F10;
    F10 = F13 - F10;                    // g1
    F11 = F9 * F12;
    F11 = F11 - F13;
    F11 = ABS F11;
    F11 = F13 - F11;                    // g2
    F12 = DM(K_BASE);
    F0 = F8 + F12;
    CALL g_head;
    F13 = F0 * F10;
    F0 = F9 + F12;
    CALL g_head;
    F0 = F0 * F11;
    F13 = F13 + F0;                     // wet

    // ---- record, with the shifted signal fed back (clamped)
    F9 = 1.0;
    F9 = MIN(F13, F9);
    F10 = -1.0;
    F9 = MAX(F9, F10);
    F10 = DM(ST_FB, I3);
    F9 = F10 * F9;
    F9 = F7 + F9;
    R8 = DM(ST_W, I3);
    R10 = R8 + R4;
    I4 = R10;
    DM(0, I4) = F9;
    R8 = R8 + 1;
    R10 = RING_MASK;
    R8 = R8 AND R10;
    DM(ST_W, I3) = R8;

    // ---- tone, output, mix
    F10 = DM(ST_TONEA, I3);
    F11 = DM(ST_TONEZ, I3);
    F12 = F13 - F11;
    F12 = F10 * F12;
    F11 = F11 + F12;
    DM(ST_TONEZ, I3) = F11;
    F8 = DM(ST_GOUT, I3);
    F13 = F11 * F8;                     // wet
    F8 = DM(ST_GMIX, I3);
    F10 = 1.0;
    F10 = F10 - F8;
    F10 = F7 * F10;
    F13 = F13 * F8;
    F9 = F10 + F13;
    F10 = ABS F9;
    F11 = 8.0;
    COMP(F10, F11);
    IF LE JUMP s_out;
    R9 = 0;
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

// ---- F0 = the ring F0 samples back from the write head, interpolated (ring base R4).
//      Uses R1, R2, R3, R15 and I4.
g_head:
    R15 = RING_MASK;
    R1 = TRUNC F0;                      // j
    R2 = DM(ST_W, I3);
    R2 = R2 - R1;
    R3 = R2 - 1;
    R2 = R2 AND R15;
    R3 = R3 AND R15;
    R2 = R2 + R4;
    R3 = R3 + R4;
    F1 = FLOAT R1;
    F1 = F0 - F1;                       // f
    I4 = R2;
    F2 = DM(0, I4);                     // a
    I4 = R3;
    F3 = DM(0, I4);                     // b
    F3 = F3 - F2;
    F3 = F1 * F3;
    F0 = F2 + F3;
    RTS;

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
