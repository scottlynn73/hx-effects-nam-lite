// stutter_kernel.asm - Stutter (triggered glitch repeater) for the HX Effects SHARC. A port of
// effects/stutter/stutter.c; stutter_kernel.py checks it bit for bit against that reference in ssim and
// puts the .equ block, constants and tables at "EQUS".
//
// Conventions as the other kernels (effects/README.md): once per 16-sample block, I0 = the instance's
// DM block, I1 = 16 inputs, I2 = 16 outputs; R0-R15, I1-I4 and MODE1 come back unchanged; L1-L4 left
// 0; no hardware loops; DM(3, I0) never touched; only P_SLOT (12) written; state in one of NSLOTS
// claimed slots; each slot's ring (RING_N words) at RING0 + (slot - 1) x RING_N, never zeroed: a
// slice never reaches past what the slot has recorded.
//
// Knob words: DM(5) Trigger (int 0..2), DM(6) Rate Hz, DM(7) Chance 0..1, DM(8) Length 0..1,
//             DM(9) Repeats (int 1..16), DM(10) Speed (int 0..5), DM(11) Random 0..1, DM(13) Mix 0..1.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

STUTTER_ENTRY:
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
    R13 = R11 - 1;                      // this slot's ring (not zeroed: only recorded samples are read)
    R13 = LSHIFT R13 BY RING_SHIFT;
    R14 = RING0;
    R13 = R13 + R14;
    DM(ST_RING, I3) = R13;
c_have:
    DM(S_LAST, I3) = R9;

    // ---- knobs (clamped as fx_param_clamp does, finite values)
    R2 = DM(5, I0);                     // Trigger 0..2
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 2;
    R2 = MIN(R2, R8);
    DM(ST_TRIG, I3) = R2;

    F0 = DM(6, I0);                     // Rate 0.5..16 Hz -> the clock's increment
    F8 = 0.5;
    F0 = MAX(F0, F8);
    F8 = 16.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_INV48);
    F0 = F0 * F8;
    DM(ST_CINC, I3) = F0;

    F0 = DM(7, I0);                     // Chance 0..1 -> threshold, x 2^24 truncated
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_2P24);
    F0 = F0 * F8;
    R0 = TRUNC F0;
    DM(ST_THR, I3) = R0;

    F0 = DM(8, I0);                     // Length 0..1 -> 960 exp(l ln 25) samples, truncated
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_LN25);
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 960.0;
    F0 = F8 * F0;
    R0 = TRUNC F0;
    DM(ST_BASE, I3) = R0;

    R2 = DM(9, I0);                     // Repeats 1..16
    R8 = 1;
    R2 = MAX(R2, R8);
    R8 = 16;
    R2 = MIN(R2, R8);
    DM(ST_REPS, I3) = R2;

    R2 = DM(10, I0);                    // Speed 0..5
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 5;
    R2 = MIN(R2, R8);
    DM(ST_SPD, I3) = R2;

    F0 = DM(11, I0);                    // Random 0..1 -> x 3
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = 3.0;
    F0 = F0 * F8;
    DM(ST_RND3, I3) = F0;

    F0 = DM(13, I0);                    // Mix 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_MIX, I3) = F0;

    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    R5 = 0;                             // fire
    // ---- the transient detector
    F8 = ABS F7;                        // a
    F9 = DM(ST_ENVF, I3);
    F10 = DM(K_SMR);
    F10 = F9 * F10;
    COMP(F8, F9);
    IF GT F10 = PASS F8;
    DM(ST_ENVF, I3) = F10;
    F11 = DM(ST_ENVS, I3);
    F12 = F8 - F11;
    F13 = DM(K_SLOWK);
    F12 = F13 * F12;
    F11 = F11 + F12;
    DM(ST_ENVS, I3) = F11;
    R8 = DM(ST_HOLD, I3);
    R8 = PASS R8;
    IF LE JUMP t_h0;
    R8 = R8 - 1;
    DM(ST_HOLD, I3) = R8;
t_h0:
    R9 = DM(ST_TRIG, I3);
    R9 = PASS R9;
    IF EQ JUMP t_done;
    R8 = PASS R8;
    IF NE JUMP t_done;
    F12 = 2.0;
    F12 = F12 * F11;
    F13 = DM(K_FLOOR);
    F12 = F12 + F13;
    COMP(F10, F12);
    IF LE JUMP t_done;
    R8 = HOLD;
    DM(ST_HOLD, I3) = R8;
    R5 = 1;
t_done:
    // ---- the clock
    F8 = DM(ST_CPH, I3);
    F9 = DM(ST_CINC, I3);
    F8 = F8 + F9;
    F9 = 1.0;
    COMP(F8, F9);
    IF LT JUMP k_nt;
    F8 = F8 - F9;
    R9 = DM(ST_TRIG, I3);
    R10 = 1;
    COMP(R9, R10);
    IF EQ JUMP k_nt;
    R5 = 1;
k_nt:
    DM(ST_CPH, I3) = F8;

    // ---- a firing: Chance, then the slice
    R5 = PASS R5;
    IF EQ JUMP f_done;
    CALL g_next;
    R9 = DM(ST_THR, I3);
    COMP(R8, R9);
    IF GE JUMP f_done;
    CALL g_next;                        // k = (int)(next x 2^-24 x rnd3)
    F8 = FLOAT R8;
    F9 = DM(K_2M24);
    F8 = F8 * F9;
    F9 = DM(ST_RND3, I3);
    F8 = F8 * F9;
    R8 = TRUNC F8;
    R9 = DM(ST_BASE, I3);
    R8 = -R8;
    R9 = ASHIFT R9 BY R8;               // len = base >> k
    R10 = LMIN;
    R9 = MAX(R9, R10);
    R10 = LMAX;
    R9 = MIN(R9, R10);
    R10 = DM(ST_FILLED, I3);            // only what has been recorded
    R9 = MIN(R9, R10);
    R10 = LMIN;
    COMP(R9, R10);
    IF LT JUMP f_done;
    DM(ST_LEN, I3) = R9;
    R10 = DM(ST_SPD, I3);               // the speed: the list's, or a random one
    R11 = 5;
    COMP(R10, R11);
    IF NE JUMP f_fix;
    CALL g_next;
    R8 = LSHIFT R8 BY -21;
    R10 = T_RS;
    R10 = R10 + R8;
    JUMP f_sp;
f_fix:
    R11 = T_SP;
    R10 = R10 + R11;
f_sp:
    I4 = R10;
    F10 = DM(0, I4);
    DM(ST_SPEED, I3) = F10;
    R11 = DM(ST_W, I3);                 // start = (w - len) & mask
    R11 = R11 - R9;
    R12 = RING_MASK;
    R11 = R11 AND R12;
    DM(ST_START, I3) = R11;
    F11 = 0.0;                          // pos: 0, or len - 1 in reverse
    F10 = PASS F10;
    IF GT JUMP f_pos;
    R11 = R9 - 1;
    F11 = FLOAT R11;
f_pos:
    DM(ST_POS, I3) = F11;
    R11 = DM(ST_REPS, I3);
    DM(ST_LEFT, I3) = R11;
    R11 = 1;
    DM(ST_PLAY, I3) = R11;
f_done:

    // ---- play the slice, or record
    F13 = 0.0;                          // wet
    R10 = DM(ST_RING, I3);
    R8 = DM(ST_PLAY, I3);
    R8 = PASS R8;
    IF EQ JUMP r_rec;
    F8 = DM(ST_POS, I3);
    R15 = TRUNC F8;                     // j
    R11 = DM(ST_START, I3);
    R11 = R11 + R15;
    F9 = FLOAT R15;
    F9 = F8 - F9;                       // f
    R12 = RING_MASK;
    R11 = R11 AND R12;                  // b0
    R13 = R11 + R10;
    I4 = R13;
    F14 = DM(0, I4);                    // v0
    R15 = R15 + 1;                      // b1: the next sample, if it is inside the slice
    R13 = DM(ST_LEN, I3);
    COMP(R15, R13);
    IF GE JUMP r_last;
    R11 = R11 + 1;
    R11 = R11 AND R12;
r_last:
    R13 = R11 + R10;
    I4 = R13;
    F15 = DM(0, I4);                    // v1
    F15 = F15 - F14;
    F15 = F9 * F15;
    F13 = F14 + F15;                    // wet
    R11 = DM(ST_LEN, I3);               // the fades
    R11 = R11 - 1;
    F12 = FLOAT R11;                    // len - 1
    F11 = F12 - F8;                     // e
    COMP(F8, F11);
    IF LT F11 = PASS F8;
    F14 = DM(K_FADE);
    F11 = F11 * F14;
    F14 = 1.0;
    COMP(F11, F14);
    IF GE JUMP r_nf;
    F13 = F13 * F11;
r_nf:
    F14 = DM(ST_SPEED, I3);             // advance, wrapping at len - 1
    F8 = F8 + F14;
    R11 = DM(ST_LEN, I3);
    F14 = FLOAT R11;
    F15 = 1.0;
    F14 = F14 - F15;
    COMP(F8, F14);
    IF LT JUMP r_lo;
    F8 = F8 - F12;
    JUMP r_dec;
r_lo:
    F14 = 0.0;
    COMP(F8, F14);
    IF GE JUMP r_adv;
    F8 = F8 + F12;
r_dec:
    R11 = DM(ST_LEFT, I3);
    R11 = R11 - 1;
    DM(ST_LEFT, I3) = R11;
r_adv:
    DM(ST_POS, I3) = F8;
    R11 = DM(ST_LEFT, I3);
    R11 = PASS R11;
    IF GT JUMP r_amt;
    R11 = 0;
    DM(ST_PLAY, I3) = R11;
r_amt:
    F8 = DM(ST_AMT, I3);
    F9 = DM(K_XF);
    F8 = F8 + F9;
    F9 = 1.0;
    F8 = MIN(F8, F9);
    DM(ST_AMT, I3) = F8;
    JUMP r_done;
r_rec:
    R8 = DM(ST_W, I3);
    R11 = R8 + R10;
    I4 = R11;
    DM(0, I4) = F7;
    R8 = R8 + 1;
    R12 = RING_MASK;
    R8 = R8 AND R12;
    DM(ST_W, I3) = R8;
    R8 = DM(ST_FILLED, I3);
    R12 = RING_N;
    COMP(R8, R12);
    IF GE JUMP r_full;
    R8 = R8 + 1;
    DM(ST_FILLED, I3) = R8;
r_full:
    F8 = DM(ST_AMT, I3);
    F9 = DM(K_XF);
    F8 = F8 - F9;
    F9 = 0.0;
    F8 = MAX(F8, F9);
    DM(ST_AMT, I3) = F8;
r_done:

    // ---- out = x (1 - a) + wet a, a = Mix x amt
    F8 = DM(ST_AMT, I3);
    F9 = DM(ST_MIX, I3);
    F8 = F9 * F8;
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

// ---- R8 = next(): xorshift32 on ST_RND, then >> 8. Uses R8, R15.
g_next:
    R8 = DM(ST_RND, I3);
    R15 = LSHIFT R8 BY 13;
    R8 = R8 XOR R15;
    R15 = LSHIFT R8 BY -17;
    R8 = R8 XOR R15;
    R15 = LSHIFT R8 BY 5;
    R8 = R8 XOR R15;
    DM(ST_RND, I3) = R8;
    R8 = LSHIFT R8 BY -8;
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
