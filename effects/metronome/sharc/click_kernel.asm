// click_kernel.asm - Click (preset-block metronome) as a primitive for the HX Effects SHARC.
// A port of effects/metronome/metronome.c; click_kernel.py checks it bit for bit against
// that reference in ssim. click_kernel.py puts the .equ block and the tables at "EQUS".
//
// Calling convention as the NAM kernel uses it (docs/baseline-audit.md, "modelled"):
// once per 16-sample block; I0 = the instance's DM block (zeroed at creation),
// I1 = 16 input floats, I2 = 16 output floats. Preserves R0-R15, I1-I4 and MODE1;
// leaves L1, L2, L4 at 0; uses no hardware loops or calls.
//
// Two conventions taken from the NAM kernel (the first hardware build hung the unit's
// controls without them):
// - DM(3, I0) is the stock knob writer's flag: it sets it on every knob write, and the
//   kernel clears it. Every call clears it.
// - The instance block is otherwise left alone: only the knob words are read, and only
//   DM(3) and DM(P_SLOT = 12) are written (NAM's own words 12..14). The state lives in
//   one of NSLOTS slots in Block 3, claimed as NAM claims its slots: a fresh block
//   (P_SLOT 0) or one whose slot was taken over claims a free slot, else one whose owner
//   has not run for STALE calls, and starts from reset; with none free it passes its input
//   through. A slot is {owner I0, last call count, the state words}.
//
// Knob words (ABI of this port; the firmware's Entry 3 must match it):
//   DM(5) Tempo float BPM   DM(6) Beats/Bar int    DM(7) Accent int dB
//   DM(8) Sound int         DM(9) Level float 0..1 DM(10) Subdivision int
// State: DM(ST_.., I3), I3 = this instance's slot.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000

// EQUS

.section pm 0x0c4ef8

CLICK_ENTRY:
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
    DM(SAVE + 19) = I1;                 // the caller's buffer pointers: NAM's exit puts them back
    DM(SAVE + 20) = I2;                 // (its B1/B2 restore reloads I1/I2), so must this one
    L1 = 0; L2 = 0; L3 = 0; L4 = 0;

    // ---- acknowledge the knob writer; find this instance's slot (I3)
    R8 = 0;
    DM(3, I0) = R8;
    R9 = DM(G_CALLS);
    R9 = R9 + 1;
    DM(G_CALLS) = R9;                   // R9: this call's count
    R10 = I0;                           // R10: this instance
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
c_claim:                                // fresh, or its slot was taken over
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
    JUMP k_pass;                        // no slot: pass the input through
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

    // ---- first call of this instance: beat 1 on its first sample (reset())
    R8 = DM(ST_STARTED, I3);
    R8 = PASS R8;
    IF NE JUMP k_knobs;
    R8 = 1;
    DM(ST_STARTED, I3) = R8;
    DM(ST_FIRE, I3) = R8;
    R8 = 0;
    DM(ST_ACC, I3) = R8;
    DM(ST_SUBIDX, I3) = R8;
    DM(ST_BEAT, I3) = R8;
    DM(ST_ACTIVE, I3) = R8;
    DM(ST_TICKS, I3) = R8;

    // ---- knobs, clamped as fx_param_clamp does (finite values)
k_knobs:
    F0 = DM(5, I0);                     // Tempo
    F8 = 20.0;
    F0 = MAX(F0, F8);
    F8 = 300.0;
    F0 = MIN(F0, F8);
    F8 = 100.0;
    F0 = F0 * F8;
    F8 = 0.5;
    F0 = F0 + F8;
    R0 = TRUNC F0;                      // BPM x 100

    R1 = DM(6, I0);                     // Beats/Bar 2..5
    R8 = 2;
    R1 = MAX(R1, R8);
    R8 = 5;
    R1 = MIN(R1, R8);

    R5 = DM(7, I0);                     // Accent 0..12 dB -> its gain
    R8 = 0;
    R5 = MAX(R5, R8);
    R8 = 12;
    R5 = MIN(R5, R8);
    R8 = T_ACCENT;
    R5 = R5 + R8;
    I4 = R5;
    F5 = DM(0, I4);

    R3 = DM(8, I0);                     // Sound 0..2
    R8 = 0;
    R3 = MAX(R3, R8);
    R8 = 2;
    R3 = MIN(R3, R8);

    F4 = DM(9, I0);                     // Level 0..1
    F8 = 0.0;
    F4 = MAX(F4, F8);
    F8 = 1.0;
    F4 = MIN(F4, F8);

    R2 = DM(10, I0);                    // Subdivision 1..4
    R8 = 1;
    R2 = MAX(R2, R8);
    R8 = 4;
    R2 = MIN(R2, R8);

    R8 = R0;                            // inc = BPM x 100 x Subdivision
    R9 = 2;
    COMP(R2, R9);
    IF GE R8 = R8 + R0;
    R9 = 3;
    COMP(R2, R9);
    IF GE R8 = R8 + R0;
    R9 = 4;
    COMP(R2, R9);
    IF GE R8 = R8 + R0;
    R0 = R8;

    R6 = 16;

    // ---- one sample
s_loop:
    R7 = DM(I1, 1);                     // x, as a raw word
    R8 = DM(ST_FIRE, I3);
    R8 = PASS R8;
    IF EQ JUMP s_acc;
    R8 = 0;
    DM(ST_FIRE, I3) = R8;
    JUMP s_tick;
s_acc:
    R8 = DM(ST_ACC, I3);
    R8 = R8 + R0;
    R9 = PERIOD;
    COMP(R8, R9);
    IF LT JUMP s_noacc;
    R8 = R8 - R9;
    DM(ST_ACC, I3) = R8;
    JUMP s_tick;
s_noacc:
    DM(ST_ACC, I3) = R8;
    JUMP s_voice;

    // ---- a tick: where in the bar, then (re)start the voice
s_tick:
    R9 = DM(ST_SUBIDX, I3);
    R10 = DM(ST_BEAT, I3);
    COMP(R9, R2);                       // Subdivision turned down
    IF LT JUMP t1;
    R9 = 0;
    R10 = R10 + 1;
t1: COMP(R10, R1);                      // Beats/Bar turned down
    IF LT JUMP t2;
    R10 = 0;
t2: R11 = 2;                            // CLICK_SUB
    R9 = PASS R9;
    IF NE JUMP t3;
    R11 = 1;                            // CLICK_BEAT
    R10 = PASS R10;
    IF NE JUMP t3;
    R11 = 0;                            // CLICK_ACCENT
t3: DM(ST_KIND, I3) = R11;
    F12 = PASS F4;                      // a = level
    R13 = R11;                          // the pitch's kind
    R11 = PASS R11;
    IF NE JUMP t_notacc;
    F14 = 1.0;
    COMP(F5, F14);
    IF GT JUMP t_acc;
    R13 = 1;                            // Accent 0 dB: the beat's sound
t_acc:
    F12 = F12 * F5;
    JUMP t_amp;
t_notacc:
    R14 = 2;
    COMP(R11, R14);
    IF NE JUMP t_amp;
    F14 = DM(K_SUBGAIN);
    F12 = F12 * F14;
t_amp:
    F14 = 1.0;
    F12 = MIN(F12, F14);
    DM(ST_AMP, I3) = F12;
    R15 = 0;
    F14 = 0.0;
    COMP(F12, F14);
    IF GT R15 = R15 + 1;
    DM(ST_ACTIVE, I3) = R15;
    DM(ST_SOUND, I3) = R3;
    F14 = 1.0;
    DM(ST_ENV, I3) = F14;
    DM(ST_C0, I3) = F14;
    DM(ST_C1, I3) = F14;
    R14 = 0;
    DM(ST_AGE, I3) = R14;
    DM(ST_S0, I3) = R14;
    DM(ST_S1, I3) = R14;
    R14 = LSHIFT R3 BY 2;               // T_OSC + (sound x 3 + kind) x 4
    R15 = LSHIFT R3 BY 3;
    R14 = R14 + R15;
    R15 = LSHIFT R13 BY 2;
    R14 = R14 + R15;
    R15 = T_OSC;
    R14 = R14 + R15;
    I4 = R14;
    F14 = DM(0, I4);
    DM(ST_WC0, I3) = F14;
    F14 = DM(1, I4);
    DM(ST_WS0, I3) = F14;
    F14 = DM(2, I4);
    DM(ST_WC1, I3) = F14;
    F14 = DM(3, I4);
    DM(ST_WS1, I3) = F14;
    R14 = T_MIX2;
    R14 = R14 + R3;
    I4 = R14;
    F14 = DM(0, I4);
    DM(ST_MIX2, I3) = F14;
    R14 = T_DECAY;
    R14 = R14 + R3;
    I4 = R14;
    F14 = DM(0, I4);
    DM(ST_DECAY, I3) = F14;
    R9 = R9 + 1;                        // the next tick's place
    COMP(R9, R2);
    IF LT JUMP t4;
    R9 = 0;
    R10 = R10 + 1;
    COMP(R10, R1);
    IF LT JUMP t4;
    R10 = 0;
t4: DM(ST_SUBIDX, I3) = R9;
    DM(ST_BEAT, I3) = R10;
    R14 = DM(ST_TICKS, I3);
    R14 = R14 + 1;
    DM(ST_TICKS, I3) = R14;

    // ---- the voice
s_voice:
    R8 = DM(ST_ACTIVE, I3);
    R8 = PASS R8;
    IF EQ JUMP s_dry;
    F8 = DM(ST_C0, I3);                 // rotor 0: y = s; (c, s) rotated
    F9 = DM(ST_S0, I3);
    F10 = DM(ST_WC0, I3);
    F11 = DM(ST_WS0, I3);
    F12 = F8 * F10;
    F13 = F9 * F11;
    F12 = F12 - F13;
    F13 = F9 * F10;
    F14 = F8 * F11;
    F13 = F13 + F14;
    DM(ST_C0, I3) = F12;
    DM(ST_S0, I3) = F13;
    F15 = DM(ST_MIX2, I3);
    F14 = 0.0;
    COMP(F15, F14);
    IF EQ JUMP v_amp;
    F8 = DM(ST_C1, I3);                 // rotor 1 (wood's second partial)
    F10 = DM(ST_S1, I3);
    F11 = DM(ST_WC1, I3);
    F14 = DM(ST_WS1, I3);
    F12 = F8 * F11;
    F13 = F10 * F14;
    F12 = F12 - F13;
    F13 = F10 * F11;
    F11 = F8 * F14;
    F13 = F13 + F11;
    DM(ST_C1, I3) = F12;
    DM(ST_S1, I3) = F13;
    F12 = 1.0;                          // y = (1 - mix2) y + mix2 y2
    F12 = F12 - F15;
    F12 = F12 * F9;
    F13 = F15 * F10;
    F9 = F12 + F13;
v_amp:
    F10 = DM(ST_AMP, I3);
    F11 = DM(ST_ENV, I3);
    F12 = F10 * F11;
    F9 = F9 * F12;
    F9 = MIN(F9, F10);
    F13 = -F10;
    F9 = MAX(F9, F13);
    R12 = DM(ST_AGE, I3);
    R12 = R12 + 1;
    DM(ST_AGE, I3) = R12;
    R13 = DM(ST_SOUND, I3);
    R14 = 2;                            // SOUND_BEEP
    COMP(R13, R14);
    IF NE JUMP v_decay;
    R14 = GATE;
    COMP(R12, R14);
    IF LE JUMP v_check;
    F13 = DM(K_RELSTEP);
    F11 = F11 - F13;
    JUMP v_env;
v_decay:
    F13 = DM(ST_DECAY, I3);
    F11 = F11 * F13;
v_env:
    DM(ST_ENV, I3) = F11;
v_check:
    F13 = DM(K_SILENT);
    COMP(F11, F13);
    IF LT JUMP v_off;
    R14 = MAXAGE;
    COMP(R12, R14);
    IF LE JUMP v_out;
v_off:
    R14 = 0;
    DM(ST_ACTIVE, I3) = R14;
v_out:
    F7 = F7 + F9;
s_dry:
    DM(I2, 1) = R7;
    R6 = R6 - 1;
    IF NE JUMP s_loop;
    JUMP k_exit;

k_pass:                                 // no slot free
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
