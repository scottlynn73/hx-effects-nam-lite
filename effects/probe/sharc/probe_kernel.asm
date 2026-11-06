// probe_kernel.asm - a one-off diagnostic for the HX Effects SHARC: can a kernel find data, and run
// code, that rode in at the tail of Entry 4's Blob 0 (which the unit copies verbatim to DDR2 0x21c400)?
// Built by probe_kernel.py; build_all.py --probe puts it on Geiger's host (Megaphone Mono) and appends
// the magic word and the external routine to Blob 0.
//
// It adds a tone to the input that says what it found (3,000 calls a second):
//   first 4 s (12,000 calls): 880 Hz steady = the magic word is at MAGIC_ADDR (Blob 0's tail landed);
//                             220 Hz steady = it is not (the external code is then never tried).
//   after that, if it landed: each call jumps to the external routine at EXT_PC, which stores R4 in
//                             G_FLAG and jumps back to PROBE_RET.
//                             1760 Hz beeping (about 3 beeps in 2 s) = it ran and came back;
//                             110 Hz steady = it came back but the flag is wrong;
//                             silence / a frozen unit = it never came back.
//
// Conventions as the other kernels: I0 = instance block, I1 = 16 inputs, I2 = 16 outputs; R0-R15,
// I1-I4 and MODE1 come back unchanged; L1/L2 left 0; no hardware loops; DM(3, I0) never touched; no
// instance word written (one probe block at a time: the state is global).

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
    L1 = 0; L2 = 0;

    R9 = DM(G_CALLS);
    R9 = R9 + 1;
    DM(G_CALLS) = R9;

    R0 = DM(MAGIC_ADDR);                // Blob 0's tail, in DDR2
    R1 = DM(K_MAGIC);
    COMP(R0, R1);
    IF NE JUMP p_lost;
    R10 = STAGE2;
    COMP(R9, R10);
    IF LT JUMP p_landed;

    R0 = 0;                             // stage 2: run the external routine
    DM(G_FLAG) = R0;
    R4 = DM(K_MAGIC2);
    JUMP EXT_PC;
PROBE_RET:
    R0 = DM(G_FLAG);
    R1 = DM(K_MAGIC2);
    COMP(R0, R1);
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
