// grains_kernel.asm - Grains (granular delay) for the HX Effects SHARC. A port of effects/grains/grains.c;
// grains_kernel.py checks it bit for bit against that reference in ssim and puts the .equ block,
// constants and tables at "EQUS".
//
// Conventions as the other kernels (effects/README.md): once per 16-sample block, I0 = the instance's
// DM block, I1 = 16 inputs, I2 = 16 outputs; R0-R15, I1-I5, L5 and MODE1 come back unchanged; L1-L4
// left 0; no hardware loops; DM(3, I0) never touched; only P_SLOT (12) written; state in one of NSLOTS
// claimed slots; each slot's ring (RING_N words) at RING0 + (slot - 1) x RING_N, never zeroed (a grain
// never reads a sample its slot has not recorded). I4 walks the voices (VSIZE words each), I5 the ring.
//
// Knob words: DM(5) Size (int 0..7), DM(6) Density (int 1..4), DM(7) Pitch (int 0..6), DM(8) Spray 0..1,
//             DM(9) Scatter 0..1, DM(10) Reverse 0..1, DM(11) Feedback 0..0.9, DM(13) Mix 0..1.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

GRAINS_ENTRY:
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
    R13 = R11 - 1;                      // this slot's ring
    R13 = LSHIFT R13 BY RING_SHIFT;
    R14 = RING0;
    R13 = R13 + R14;
    DM(ST_RING, I3) = R13;
c_have:
    DM(S_LAST, I3) = R9;
    R8 = I5;                            // I5 and L5 are ours until the exit
    DM(ST_SVI5, I3) = R8;
    R8 = L5;
    DM(ST_SVL5, I3) = R8;
    L5 = 0;

    // ---- knobs (clamped as fx_param_clamp does, finite values)
    R2 = DM(5, I0);                     // Size 0..7 -> len, 1 / len
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 7;
    R2 = MIN(R2, R8);
    R8 = T_LEN;
    R8 = R8 + R2;
    I4 = R8;
    R8 = DM(0, I4);
    DM(ST_LEN, I3) = R8;
    R8 = T_INV;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_INV, I3) = F8;

    R2 = DM(6, I0);                     // Density 1..4 -> its count, the sum's scale, the stagger
    R8 = 1;
    R2 = MAX(R2, R8);
    R8 = 4;
    R2 = MIN(R2, R8);
    DM(ST_DENS, I3) = R2;
    R8 = T_NORM;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_NORM, I3) = F8;
    R8 = T_STAG;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_STAG, I3) = F8;

    R2 = DM(7, I0);                     // Pitch 0..6 -> speed
    R8 = 0;
    R2 = MAX(R2, R8);
    R8 = 6;
    R2 = MIN(R2, R8);
    R8 = T_SPEED;
    R8 = R8 + R2;
    I4 = R8;
    F8 = DM(0, I4);
    DM(ST_SPEED, I3) = F8;

    F0 = DM(8, I0);                     // Spray 0..1 -> x 24000 samples
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_SPRAY);
    F0 = F0 * F8;
    DM(ST_SPRAY, I3) = F0;

    F0 = DM(9, I0);                     // Scatter 0..1 -> threshold
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_2P24);
    F0 = F0 * F8;
    R0 = TRUNC F0;
    DM(ST_THRSC, I3) = R0;

    F0 = DM(10, I0);                    // Reverse 0..1 -> threshold
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    F8 = DM(K_2P24);
    F0 = F0 * F8;
    R0 = TRUNC F0;
    DM(ST_THRREV, I3) = R0;

    F0 = DM(11, I0);                    // Feedback 0..0.9
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = DM(K_FBMAX);
    F0 = MIN(F0, F8);
    DM(ST_FB, I3) = F0;

    F0 = DM(13, I0);                    // Mix 0..1
    F8 = 0.0;
    F0 = MAX(F0, F8);
    F8 = 1.0;
    F0 = MIN(F0, F8);
    DM(ST_MIX, I3) = F0;

    R8 = DM(ST_STARTED, I3);            // first call: stagger the voices across a grain
    R8 = PASS R8;
    IF NE JUMP k_loop;
    R8 = 1;
    DM(ST_STARTED, I3) = R8;
    R8 = I3;
    R9 = ST_V0 + VW;
    R8 = R8 + R9;
    I4 = R8;
    R5 = 0;                             // k x len
    R6 = NVOICES;
p_st:
    F8 = FLOAT R5;
    F9 = DM(ST_STAG, I3);
    F8 = F8 * F9;
    R8 = TRUNC F8;
    DM(0, I4) = R8;
    R8 = I4;
    R9 = VSIZE;
    R8 = R8 + R9;
    I4 = R8;
    R8 = DM(ST_LEN, I3);
    R5 = R5 + R8;
    R6 = R6 - 1;
    IF NE JUMP p_st;

k_loop:
    R4 = DM(ST_RING, I3);               // the ring's base, all call
    R6 = 16;
s_loop:
    F7 = DM(I1, 1);                     // x
    F13 = 0.0;                          // the grains' sum
    R5 = 0;                             // voice k
    R8 = I3;
    R9 = ST_V0;
    R8 = R8 + R9;
    I4 = R8;
v_loop:
    R8 = DM(VA, I4);
    R8 = PASS R8;
    IF EQ JUMP v_idle;
    // ---- an active grain: window, read, advance
    R8 = DM(VN, I4);
    F9 = FLOAT R8;
    F10 = DM(VI, I4);
    F9 = F9 * F10;                      // t
    F10 = 4.0;
    F10 = F10 * F9;
    F11 = 1.0;
    F11 = F11 - F9;
    F10 = F10 * F11;                    // win
    F8 = DM(VP, I4);
    R9 = TRUNC F8;                      // j
    R11 = DM(VS, I4);
    R12 = DM(VD, I4);
    R12 = PASS R12;
    IF LT JUMP v_back;
    R11 = R11 + R9;
    R14 = R11 + 1;
    JUMP v_rd;
v_back:
    R11 = R11 - R9;
    R14 = R11 - 1;
v_rd:
    R15 = RING_MASK;
    R11 = R11 AND R15;
    R14 = R14 AND R15;
    R11 = R11 + R4;
    R14 = R14 + R4;
    I5 = R11;
    F11 = DM(0, I5);                    // a
    I5 = R14;
    F12 = DM(0, I5);                    // b
    F9 = FLOAT R9;
    F9 = F8 - F9;                       // f
    F12 = F12 - F11;
    F12 = F9 * F12;
    F11 = F11 + F12;
    F11 = F11 * F10;
    F13 = F13 + F11;
    F9 = DM(VSP, I4);
    F8 = F8 + F9;
    DM(VP, I4) = F8;
    R8 = DM(VN, I4);
    R8 = R8 + 1;
    DM(VN, I4) = R8;
    R9 = DM(VL, I4);
    COMP(R8, R9);
    IF LT JUMP v_next;
    R8 = 0;
    DM(VA, I4) = R8;
    JUMP v_next;
v_idle:
    R8 = DM(ST_DENS, I3);
    COMP(R5, R8);
    IF GE JUMP v_next;
    R8 = DM(VW, I4);
    R8 = PASS R8;
    IF LE JUMP v_spawn;
    R8 = R8 - 1;
    DM(VW, I4) = R8;
    JUMP v_next;
v_spawn:                                // ---- a new grain
    F12 = DM(ST_SPEED, I3);             // sp
    CALL g_next;
    R9 = DM(ST_THRSC, I3);
    COMP(R8, R9);
    IF GE JUMP v_nosc;
    CALL g_next;
    R8 = LSHIFT R8 BY -23;
    R8 = PASS R8;
    IF EQ JUMP v_half;
    F9 = 2.0;
    F12 = F12 * F9;
    JUMP v_nosc;
v_half:
    F9 = 0.5;
    F12 = F12 * F9;
v_nosc:
    CALL g_next;
    R9 = DM(ST_THRREV, I3);
    R11 = 1;
    COMP(R8, R9);
    IF GE JUMP v_dir;
    R11 = -1;
v_dir:
    DM(VD, I4) = R11;
    CALL g_next;                        // off = (int)(next x 2^-24 x spray)
    F8 = FLOAT R8;
    F9 = DM(K_2M24);
    F8 = F8 * F9;
    F9 = DM(ST_SPRAY, I3);
    F8 = F8 * F9;
    R14 = TRUNC F8;
    R9 = DM(ST_LEN, I3);                // lsp = (int)(len x sp) + 1
    F9 = FLOAT R9;
    F9 = F9 * F12;
    R15 = TRUNC F9;
    R15 = R15 + 1;
    R11 = PASS R11;
    IF LT JUMP v_dback;
    R8 = R15 + 1;                       // forward: delay = lsp + 1 + off, need = delay
    R8 = R8 + R14;
    R9 = PASS R8;
    JUMP v_need;
v_dback:
    R8 = 2;                             // back: delay = 2 + off, need = delay + lsp
    R8 = R8 + R14;
    R9 = R8 + R15;
v_need:
    R14 = DM(ST_FILLED, I3);
    COMP(R9, R14);
    IF LE JUMP v_go;
    R9 = DM(ST_LEN, I3);                // not enough recorded: a silent grain
    DM(VW, I4) = R9;
    JUMP v_next;
v_go:
    R9 = DM(ST_W, I3);
    R9 = R9 - R8;
    R14 = RING_MASK;
    R9 = R9 AND R14;
    DM(VS, I4) = R9;
    R9 = 0;
    DM(VP, I4) = R9;
    DM(VN, I4) = R9;
    R9 = DM(ST_LEN, I3);
    DM(VL, I4) = R9;
    F9 = DM(ST_INV, I3);
    DM(VI, I4) = F9;
    DM(VSP, I4) = F12;
    R9 = 1;
    DM(VA, I4) = R9;
v_next:
    R8 = I4;
    R9 = VSIZE;
    R8 = R8 + R9;
    I4 = R8;
    R5 = R5 + 1;
    R8 = NVOICES;
    COMP(R5, R8);
    IF LT JUMP v_loop;

    // ---- the sum, fed back (clamped) into the ring with the input; the mix
    F8 = DM(ST_NORM, I3);
    F13 = F13 * F8;                     // wet
    F9 = 1.0;
    F9 = MIN(F13, F9);
    F10 = -1.0;
    F9 = MAX(F9, F10);
    F10 = DM(ST_FB, I3);
    F9 = F10 * F9;
    F9 = F7 + F9;
    R8 = DM(ST_W, I3);
    R11 = R8 + R4;
    I5 = R11;
    DM(0, I5) = F9;
    R8 = R8 + 1;
    R11 = RING_MASK;
    R8 = R8 AND R11;
    DM(ST_W, I3) = R8;
    R8 = DM(ST_FILLED, I3);
    R11 = RING_N;
    COMP(R8, R11);
    IF GE JUMP s_full;
    R8 = R8 + 1;
    DM(ST_FILLED, I3) = R8;
s_full:
    F8 = DM(ST_MIX, I3);
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
    R8 = DM(ST_SVL5, I3);
    L5 = R8;
    R8 = DM(ST_SVI5, I3);
    I5 = R8;
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
