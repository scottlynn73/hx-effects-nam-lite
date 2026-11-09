// probe_kernel.asm - a one-off diagnostic for the HX Effects SHARC: swapping overlays. Can a kernel replace
// code that has already run in an internal region with different code from Entry 4's Blob 0 (DDR2), and
// be sure the new code is what runs? Built by probe_kernel.py; build_all.py --probe puts it on Geiger's host
// (Megaphone Mono) and the magic word and four 8-instruction routines inside Blob 0.
//
// It adds a tone to the input that says what it found, for as long as it runs:
//   880 Hz steady = the magic word is where expected (Blob 0's words landed); 220 Hz steady = it is not.
// A test runs only once the Bit Depth knob (DM(7)) has stayed on its value for DWELL calls (1.5 s), so a
// preset that loads the block at start-up is safe and turning past a value does nothing. Each call of a
// test copies routine A or B (alternating) into the one region REG through its normal-word view, calls it,
// and checks which flag value it stored (A stores K_MAGIC2, B K_MAGIC3):
//   Bit Depth 3: plain routines (no PM data access, as the real kernels), no flush;
//   Bit Depth 2: routines whose PM data accesses force the instruction cache to load them, FLUSH CACHE
//                before each call;
//   Bit Depth 1: the same forcing routines, no flush.
//   1760 Hz beeping = every call ran the routine just copied; 110 Hz steady = at least one ran the wrong one
//   (sticky until the knob moves); silence / a frozen unit = it never came back (power-cycle; do not save
//   the preset at 1, 2 or 3).
//
// Conventions as the other kernels: I0 = instance block, I1 = 16 inputs, I2 = 16 outputs; R0-R15,
// I1-I4, I8, L8 and MODE1 come back unchanged; L1-L4 left 0; no hardware loops; DM(3, I0) never touched;
// no instance word written (one probe block at a time: the state is global).

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

PROBE_ENTRY:
    DM(SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(SAVE + 1) = R0;
    DM(SAVE + 2) = R1;
    DM(SAVE + 3) = R2;
    DM(SAVE + 4) = R3;
    DM(SAVE + 5) = R4;
    DM(SAVE + 6) = R8;
    DM(SAVE + 7) = R9;
    DM(SAVE + 8) = R10;
    DM(SAVE + 9) = I1;
    DM(SAVE + 10) = I2;
    DM(SAVE + 11) = I3;
    DM(SAVE + 12) = I4;
    L1 = 0; L2 = 0; L3 = 0; L4 = 0;

    R9 = DM(G_CALLS);
    R9 = R9 + 1;
    DM(G_CALLS) = R9;

    R0 = DM(MAGIC_ADDR);                // inside Blob 0, in DDR2
    R1 = DM(K_MAGIC);
    COMP(R0, R1);
    IF NE JUMP p_lost;

    R2 = DM(7, I0);                     // Bit Depth, and how long it has stayed there
    R10 = DM(G_LAST);
    COMP(R2, R10);
    IF EQ JUMP p_same;
    DM(G_LAST) = R2;
    R10 = 0;
    DM(G_DWELL) = R10;
    DM(G_BAD) = R10;
p_same:
    R10 = DM(G_DWELL);
    R0 = DWELL;
    COMP(R10, R0);
    IF GE JUMP p_held;
    R10 = R10 + 1;
    DM(G_DWELL) = R10;
    JUMP p_landed;
p_held:
    R3 = 0;                             // R3: the routines' offset from SRC; R8: flush or not
    R8 = 0;
    R10 = 3;
    COMP(R2, R10);
    IF EQ JUMP p_go;
    R3 = FAM;
    R8 = 1;
    R10 = 2;
    COMP(R2, R10);
    IF EQ JUMP p_go;
    R8 = 0;
    R10 = 1;
    COMP(R2, R10);
    IF NE JUMP p_landed;

p_go:                                   // copy A (even calls) or B (odd calls) into the region
    R10 = 1;
    R10 = R9 AND R10;
    IF EQ JUMP p_src;
    R10 = NWORDS;
    R3 = R3 + R10;
p_src:
    R10 = SRC;
    R3 = R3 + R10;
    I3 = R3;
    I4 = REG_N;
    R10 = NWORDS;
p_copy:
    R0 = DM(I3, 1);
    DM(I4, 1) = R0;
    R10 = R10 - 1;
    IF NE JUMP p_copy;

    R8 = PASS R8;
    IF EQ JUMP p_nof;
    FLUSH CACHE;
p_nof:
    R0 = 0;
    DM(G_FLAG) = R0;
    R0 = I8;                            // the forcing routines read PM through I8
    DM(G_SV + 0) = R0;
    R0 = L8;
    DM(G_SV + 1) = R0;
    L8 = 0;
    I8 = REG;
    R4 = DM(K_MAGIC2);
    R3 = DM(K_MAGIC3);
    CALL REG;
    R0 = DM(G_SV + 0);
    I8 = R0;
    R0 = DM(G_SV + 1);
    L8 = R0;

    R0 = DM(G_FLAG);                    // the flag the copied routine should have stored
    R10 = 1;
    R10 = R9 AND R10;
    IF NE JUMP p_b;
    R1 = DM(K_MAGIC2);
    JUMP p_cmp;
p_b:
    R1 = DM(K_MAGIC3);
p_cmp:
    COMP(R0, R1);
    IF EQ JUMP p_ok;
    R0 = 1;
    DM(G_BAD) = R0;
p_ok:
    R0 = DM(G_BAD);
    R0 = PASS R0;
    IF NE JUMP p_bad;
    R2 = HALF_1760;
    F3 = 0.1;
    R0 = BEEP_BIT;
    R0 = R9 AND R0;
    IF NE JUMP p_tone;
    F3 = 0.0;
    JUMP p_tone;
p_bad:
    R2 = HALF_110;
    F3 = 0.1;
    JUMP p_tone;
p_landed:
    R2 = HALF_880;
    F3 = 0.1;
    JUMP p_tone;
p_lost:
    R2 = HALF_220;
    F3 = 0.1;

p_tone:                                 // out = in + a square wave (half period R2 samples, level F3)
    R8 = 16;
    R0 = DM(G_PH);
    F1 = DM(G_SIGN);
p_loop:
    R0 = R0 + 1;
    COMP(R0, R2);
    IF LT JUMP p_keep;
    R0 = 0;
    F1 = -F1;
p_keep:
    F4 = F1 * F3;
    F10 = DM(I1, 1);
    F10 = F10 + F4;
    DM(I2, 1) = F10;
    R8 = R8 - 1;
    IF NE JUMP p_loop;
    DM(G_PH) = R0;
    DM(G_SIGN) = F1;

    I4 = DM(SAVE + 12);
    I3 = DM(SAVE + 11);
    I2 = DM(SAVE + 10);
    I1 = DM(SAVE + 9);
    R10 = DM(SAVE + 8);
    R9 = DM(SAVE + 7);
    R8 = DM(SAVE + 6);
    R4 = DM(SAVE + 5);
    R3 = DM(SAVE + 4);
    R2 = DM(SAVE + 3);
    R1 = DM(SAVE + 2);
    R0 = DM(SAVE + 1);
    MODE1 = DM(SAVE + 0);
    RTS;
