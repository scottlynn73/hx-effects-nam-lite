// doomchug_kernel.asm - Doom Chug (a low four-voice drone generator) for the HX Effects SHARC. A port of
// effects/doomchug/doomchug.c; doomchug_kernel.py checks it bit for bit against that reference in ssim and
// puts the .equ block, constants and tables at "EQUS".
//
// Conventions as the other kernels (effects/README.md): once per 16-sample block, I0 = the instance's
// DM block, I1 = 16 inputs, I2 = 16 outputs; R0-R15, I1-I4 and MODE1 come back unchanged; L1-L4 left
// 0; no hardware loops; DM(3, I0) never touched; only P_SLOT (12) written; state in one of NSLOTS
// claimed slots. Each voice's state: VSIZE words from ST_V0, fields V_*.
//
// Knob words: DM(5) Key (int 0..11), DM(6) Pattern (int 0..8), DM(7) Rate 0..1, DM(8) Drift 0..1,
//             DM(9) Warble 0..1, DM(10) Chug 0..1, DM(11) Tone 0..1, DM(13) Level 0..1.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

DOOMCHUG_ENTRY:
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
    I3 = SLOTS;
    R11 = DM(P_SLOT, I0);
    R11 = PASS R11;
    IF EQ JUMP c_claim;
    R13 = DM(S_OWNER, I3);
    COMP(R13, R10);
    IF EQ JUMP c_have;
c_claim:
    R13 = DM(S_OWNER, I3);              // free, ours (re-created in place), or abandoned; else pass through
    R13 = PASS R13;
    IF EQ JUMP c_take;
    COMP(R13, R10);
    IF EQ JUMP c_take;
    R13 = DM(S_LAST, I3);
    R13 = R9 - R13;
    R15 = STALE;
    COMP(R13, R15);
    IF LE JUMP k_pass;
c_take:
    R11 = 1;
    DM(P_SLOT, I0) = R11;
    DM(S_OWNER, I3) = R10;
    R13 = 0;
    I4 = SLOTS + 2;
    R14 = NSTATE;
c_zero:
    DM(I4, 1) = R13;
    R14 = R14 - 1;
    IF NE JUMP c_zero;
    R13 = SEED;                         // reset()
    DM(ST_RND, I3) = R13;
    F13 = 1.0;
    DM(ST_SPHASE, I3) = F13;
c_have:
    DM(S_LAST, I3) = R9;

    // ---- knobs (clamped as fx_param_clamp does, finite values)
    R1 = DM(5, I0);                     // Key 0..11
    R8 = 0;
    R1 = MAX(R1, R8);
    R8 = 11;
    R1 = MIN(R1, R8);

    R5 = DM(6, I0);                     // Pattern 0..8 -> its word of eight 4-bit steps
    R8 = 0;
    R5 = MAX(R5, R8);
    R8 = 8;
    R5 = MIN(R5, R8);
    R8 = T_PAT;
    R8 = R5 + R8;
    I4 = R8;
    R5 = DM(0, I4);

    F0 = DM(7, I0);                     // Rate 0..1 -> 0.05 exp(r ln 160) steps/s, in steps a tick (F6)
    CALL g_cl;
    F8 = 5.075173819999999835772542;
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 0.000016666667000000000596;
    F6 = F0 * F8;

    F0 = DM(8, I0);                     // Drift -> dk (F7)
    CALL g_cl;
    F8 = 0.5;
    F7 = F0 * F8;

    F0 = DM(9, I0);                     // Warble -> wk (F12), tk (F13)
    CALL g_cl;
    F8 = 0.160000000000000003330669;
    F12 = F0 * F8;
    F8 = 1.199999999999999955591079;
    F13 = F0 * F8;

    F0 = DM(10, I0);                    // Chug (F14)
    CALL g_cl;
    F14 = PASS F0;

    F0 = DM(11, I0);                    // Tone 0..1 -> 100 exp(t ln 80) Hz -> tone_a
    CALL g_cl;
    F8 = 4.382026630000000366749191;
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 100.0;
    F0 = F8 * F0;
    F8 = -0.000130899690000000002354;
    F0 = F0 * F8;
    CALL g_exp;
    F8 = 1.0;
    F0 = F8 - F0;
    DM(ST_TONEA, I3) = F0;

    // ---- the tick: the step (the first tick always is one)
    F8 = DM(ST_SPHASE, I3);
    F8 = F8 + F6;
    F9 = 1.0;
    COMP(F8, F9);
    IF LT JUMP t_keep;
    F8 = F8 - F9;
    R9 = DM(ST_STEP, I3);
    R9 = R9 + 1;
    R10 = 7;
    R9 = R9 AND R10;
    DM(ST_STEP, I3) = R9;
    F9 = 1.0;
    DM(ST_ENV, I3) = F9;
    R10 = I3;
    R11 = ST_V0;
    R10 = R10 + R11;
    I4 = R10;
    R9 = DM(ST_RND, I3);
    R11 = 4;
t_v:
    R10 = LSHIFT R9 BY 13;              // xorshift32
    R9 = R9 XOR R10;
    R10 = LSHIFT R9 BY -17;
    R9 = R9 XOR R10;
    R10 = LSHIFT R9 BY 5;
    R9 = R9 XOR R10;
    R10 = LSHIFT R9 BY -16;
    F10 = FLOAT R10;
    F15 = 0.0000152587890625;
    F10 = F10 * F15;
    DM(V_DT, I4) = F10;
    R10 = 0xFFFF;
    R10 = R9 AND R10;
    F10 = FLOAT R10;
    F10 = F10 * F15;
    F15 = 0.002000000000000000041633;
    F10 = F15 * F10;
    F15 = 0.000100000000000000004792;
    F10 = F15 + F10;
    DM(V_LI, I4) = F10;
    R10 = I4;
    R15 = VSIZE;
    R10 = R10 + R15;
    I4 = R10;
    R11 = R11 - 1;
    IF NE JUMP t_v;
    DM(ST_RND, I3) = R9;
t_keep:
    DM(ST_SPHASE, I3) = F8;

    F8 = DM(ST_ENV, I3);                // the Chug envelope -> cg (F14)
    F9 = 0.998500000000000054178884;
    F8 = F8 * F9;
    DM(ST_ENV, I3) = F8;
    F9 = 1.0;
    F10 = F9 - F8;
    F14 = F14 * F10;
    F14 = F9 - F14;

    R9 = DM(ST_STEP, I3);               // Key + this step's semitones, in octaves (F1)
    R9 = LSHIFT R9 BY 2;
    R9 = -R9;
    R8 = LSHIFT R5 BY R9;
    R10 = 15;
    R8 = R8 AND R10;
    R1 = R1 + R8;
    F1 = FLOAT R1;
    F8 = 0.083333335999999993970455;
    F1 = F1 * F8;

    R8 = I3;
    R9 = ST_V0;
    R8 = R8 + R9;
    I4 = R8;
    F15 = 0.0;
    CALL v_ctl;
    F15 = 0.0120000000000000002498;
    CALL v_ctl;
    F15 = 0.583333300000000054552629;
    CALL v_ctl;
    F15 = 1.0;
    CALL v_ctl;

    F0 = DM(13, I0);                    // Level (F13)
    CALL g_cl;
    F13 = PASS F0;

    // ---- the samples
    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    R8 = I3;
    R9 = ST_V0;
    R8 = R8 + R9;
    I4 = R8;
    F5 = 0.0;                           // z
    R10 = 4;
s_v:
    F8 = DM(V_PH, I4);
    F9 = DM(V_INC, I4);
    F8 = F8 + F9;
    F9 = 1.0;
    COMP(F8, F9);
    IF LT JUMP s_1;
    F8 = F8 - F9;
s_1:
    DM(V_PH, I4) = F8;
    F9 = DM(V_G, I4);
    F11 = DM(V_DG, I4);
    F9 = F9 + F11;
    DM(V_G, I4) = F9;
    F11 = 0.5;
    F8 = F8 - F11;
    F8 = F8 * F9;
    F5 = F5 + F8;
    R8 = I4;
    R9 = VSIZE;
    R8 = R8 + R9;
    I4 = R8;
    R10 = R10 - 1;
    IF NE JUMP s_v;

    F8 = 0.59999999999999997779554;                       // soft clip
    F5 = F5 * F8;
    F8 = 1.0;
    F5 = MIN(F5, F8);
    F8 = -1.0;
    F5 = MAX(F5, F8);
    F8 = 1.5;
    F8 = F8 * F5;
    F9 = 0.5;
    F9 = F9 * F5;
    F9 = F9 * F5;
    F9 = F9 * F5;
    F5 = F8 - F9;

    F8 = DM(ST_TONEA, I3);              // two one-poles, Level, the input added
    F9 = DM(ST_Z1, I3);
    F10 = F5 - F9;
    F10 = F8 * F10;
    F9 = F9 + F10;
    DM(ST_Z1, I3) = F9;
    F10 = DM(ST_Z2, I3);
    F9 = F9 - F10;
    F9 = F8 * F9;
    F10 = F10 + F9;
    DM(ST_Z2, I3) = F10;
    F10 = F10 * F13;
    F9 = F7 + F10;
    DM(I2, 1) = F9;
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

// ---- one voice's tick: F15 = its interval, F1 = the step's pitch, F7 dk, F12 wk, F13 tk, F14 cg; state at
//      I4, which moves to the next voice. Uses F0, F2-F4 (g_exp), F8-F11, F15.
v_ctl:
    F15 = F1 + F15;                     // target
    F8 = DM(V_BASE, I4);                // the glide (F8 = base)
    F15 = F15 - F8;
    F9 = 0.001500000000000000031225;
    F15 = F9 * F15;
    F8 = F8 + F15;
    DM(V_BASE, I4) = F8;
    F9 = DM(V_D, I4);                   // the walk (F9 = d)
    F10 = DM(V_DT, I4);
    F10 = F10 - F9;
    F11 = 0.001000000000000000020817;
    F10 = F11 * F10;
    F9 = F9 + F10;
    DM(V_D, I4) = F9;
    F10 = DM(V_LP, I4);                 // the LFO, a triangle 0..1 (F10)
    F11 = DM(V_LI, I4);
    F10 = F10 + F11;
    F11 = 1.0;
    COMP(F10, F11);
    IF LT JUMP v_2;
    F10 = F10 - F11;
v_2:
    DM(V_LP, I4) = F10;
    F11 = 0.5;
    F10 = F10 - F11;
    F10 = ABS F10;
    F9 = F7 * F9;                       // the pitch, folded at two octaves (F8)
    F11 = F12 * F10;
    F8 = F8 + F9;
    F8 = F8 + F11;
    F9 = 2.0;
    COMP(F8, F9);
    IF LE JUMP v_3;
    F9 = 4.0;
    F8 = F9 - F8;
v_3:
    F9 = 0.69314718200000002834571;
    F0 = F8 * F9;
    CALL g_exp;
    F9 = 0.002291666700000000167492;
    F0 = F0 * F9;
    DM(V_INC, I4) = F0;
    F9 = F13 * F10;                     // the gain ramp
    F11 = 1.0;
    F11 = F11 - F9;
    F11 = F11 * F14;
    F9 = DM(V_G, I4);
    F11 = F11 - F9;
    F9 = 0.0625;
    F11 = F11 * F9;
    DM(V_DG, I4) = F11;
    R8 = I4;
    R9 = VSIZE;
    R8 = R8 + R9;
    I4 = R8;
    RTS;

// ---- F0 clamped to 0..1. Uses F8.
g_cl:
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    RTS;

// ---- F0 = geiger_exp(F0): Taylor degree 6 of z = y/16 (Horner), squared four times. Uses F2, F3, F4.
g_exp:
    F2 = 0.0625;
    F2 = F0 * F2;
    F3 = 0.001388888922519981861115;
    F3 = F3 * F2;
    F4 = 0.008333333767950534820557;
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = 0.041666667908430099487305;
    F3 = F3 + F4;
    F3 = F3 * F2;
    F4 = 0.166666671633720397949219;
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
