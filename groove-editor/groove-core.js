/* groove-core.js - the groove editor's data: the user groove bank in one User IR slot (as
 * effects/drumchapel/grooves.py --user writes it, byte for byte: check_core.py), and MIDI loops converted to steps
 * (grooves.py convert(), the same rules). A browser global (GROOVE) and a Node module.
 *
 * A step is one byte (effects/drumchapel/drumchapel.h DC_B_*): kick 1, snare 2, hat 4, tom 8, open 16 (with the
 * hat: the open hat / cymbal), the tom's pitch in bits 5-6 (0 high .. 3 floor). The bank (drumchapel.h, "The
 * user groove bank"): 2,048 float samples; 0.5, -0.5, 5.0, 1.0, loops / 2, steps / 1024, a check, 0; each loop's
 * directory value (first step << 9 | length) x 2^-21 from sample 8; the steps three to a sample from sample 28. */
(function (root) {
  "use strict";
  var KICK = 1, SNARE = 2, HAT = 4, TOM = 8, OPEN = 16, PITCH = 5;
  var USER_DIR = 8, USER_STEPS = 28, USER_MAX_STEPS = 3 * (2047 - 28), USER_SLOT = 128, MAX_LOOPS = 20, MAX_STEPS = 384;
  var SCALE = Math.pow(2, -21);

  function fail(msg) { var e = new Error(msg); e.groove = true; return e; }

  // The 2,048 samples (float bits, Uint32Array) of a bank holding these loops (arrays of step bytes).
  function userBank(loops) {
    if (loops.length < 1 || loops.length > MAX_LOOPS) throw fail(loops.length + " patterns: the Pattern knob has " + MAX_LOOPS);
    var steps = [], dirs = [];
    loops.forEach(function (v, k) {
      if (v.length < 4 || v.length > MAX_STEPS || v.length % 4)
        throw fail("pattern " + (k + 1) + ": " + v.length + " sixteenths (4.." + MAX_STEPS + ", a multiple of 4)");
      dirs.push(steps.length * 512 + v.length);
      for (var i = 0; i < v.length; i++) steps.push(v[i] & 255);
    });
    if (steps.length > USER_MAX_STEPS) throw fail(steps.length + " sixteenths in all: one IR slot holds " + USER_MAX_STEPS);
    var vals = [];
    for (var i = 0; i < steps.length; i += 3)
      vals.push(steps[i] + (i + 1 < steps.length ? steps[i + 1] : 0) * 256 + (i + 2 < steps.length ? steps[i + 2] : 0) * 65536);
    var check = 0;
    dirs.concat(vals).forEach(function (x) { check = (check + x) % 2097152; });
    var out = [0.5, -0.5, 5.0, 1.0, loops.length / 2, steps.length / 1024, check * SCALE, 0];
    dirs.forEach(function (d) { out.push(d * SCALE); });
    while (out.length < USER_STEPS) out.push(0);
    vals.forEach(function (x) { out.push(x * SCALE); });
    while (out.length < 2048) out.push(0);
    var f = new Float32Array(out);
    return new Uint32Array(f.buffer);
  }

  // The slot's samples as the .wav data chunk (little-endian floats), and a whole 48 kHz mono 32-bit float .wav.
  function sampleBytes(words) {
    var b = new Uint8Array(words.length * 4), v = new DataView(b.buffer);
    for (var i = 0; i < words.length; i++) v.setUint32(4 * i, words[i], true);
    return b;
  }
  function wavBytes(words) {
    var data = sampleBytes(words), b = new Uint8Array(44 + data.length), v = new DataView(b.buffer);
    var put = function (o, s) { for (var i = 0; i < 4; i++) b[o + i] = s.charCodeAt(i); };
    put(0, "RIFF"); v.setUint32(4, 36 + data.length, true); put(8, "WAVE"); put(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 3, true); v.setUint16(22, 1, true); v.setUint32(24, 48000, true);
    v.setUint32(28, 192000, true); v.setUint16(32, 4, true); v.setUint16(34, 32, true); put(36, "data");
    v.setUint32(40, data.length, true); b.set(data, 44);
    return b;
  }

  // Read a bank back (a slot's samples): [[step bytes] per loop], or throw.
  function readBank(words) {
    var f = new Float32Array(new Uint32Array(words).buffer);
    if (f[0] !== 0.5 || f[1] !== -0.5 || f[2] !== 5 || f[3] !== 1) throw fail("not a Drum Chapel groove bank");
    var n = f[4] * 2, total = f[5] * 1024, loops = [];
    var byte = function (i) { var x = Math.round(f[USER_STEPS + Math.floor(i / 3)] / SCALE); return Math.floor(x / Math.pow(256, i % 3)) & 255; };
    for (var k = 0; k < n; k++) {
      var d = Math.round(f[USER_DIR + k] / SCALE), len = d % 512, first = Math.floor(d / 512), v = [];
      for (var i = 0; i < len && first + i < total; i++) v.push(byte(first + i));
      loops.push(v);
    }
    return loops;
  }

  // ---------- MIDI (grooves.py read_midi / convert: the same note map and rules) ----------
  var NOTES = { 35: KICK, 36: KICK, 37: SNARE, 38: SNARE, 40: SNARE, 42: HAT, 44: HAT };
  [24, 46, 49, 51, 52, 53, 54, 55, 56, 57, 59].forEach(function (n) { NOTES[n] = HAT | OPEN; });
  var TOMS = { 48: 0, 50: 0, 45: 1, 47: 1, 43: 2, 41: 3 };
  var MIN_VELOCITY = 40;

  function readMidi(b) {
    var u16 = function (i) { return b[i] << 8 | b[i + 1]; }, u32 = function (i) { return ((b[i] << 24) >>> 0) + (b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3]); };
    var tag = function (i) { return String.fromCharCode(b[i], b[i + 1], b[i + 2], b[i + 3]); };
    var vlq = function (i) { var v = 0; for (;;) { var c = b[i++]; v = v * 128 + (c & 127); if (!(c & 128)) return [v, i]; } };
    if (tag(0) !== "MThd") throw fail("not a MIDI file");
    var ntrk = u16(10), ppq = u16(12);
    if (ppq & 0x8000) throw fail("SMPTE time division");
    var i = 8 + u32(4), notes = [], end = 0;
    for (var t = 0; t < ntrk; t++) {
      if (tag(i) !== "MTrk") throw fail("bad track header");
      var j = i + 8, stop = i + 8 + u32(i + 4), tick = 0, run = null, r;
      while (j < stop) {
        r = vlq(j); tick += r[0]; j = r[1];
        var st = b[j];
        if (st === 0xFF) {
          var ty = b[j + 1]; r = vlq(j + 2); j = r[1] + r[0];
          if (ty === 0x2F) end = Math.max(end, tick);
          continue;
        }
        if (st === 0xF0 || st === 0xF7) { r = vlq(j + 1); j = r[1] + r[0]; continue; }
        if (st & 0x80) { run = st; j++; }
        var hi = run & 0xF0;
        if (hi === 0xC0 || hi === 0xD0) { j++; continue; }
        var d1 = b[j], d2 = b[j + 1]; j += 2;
        if (hi === 0x90 && d2 > 0) notes.push([tick, d1, d2]);
      }
      i = stop;
    }
    return { ppq: ppq, notes: notes, end: end };
  }

  // One MIDI loop -> its steps (one byte each), padded with empty steps to a multiple of 4 (as grooves.py --user).
  function convertMidi(bytes, stats) {
    stats = stats || {};
    var m = readMidi(bytes), ppq = m.ppq, tick16 = Math.floor(ppq / 4);
    if (ppq % 4) throw fail(ppq + " ticks a quarter is not a whole number of sixteenths");
    if (!m.notes.length) throw fail("no notes");
    var end = m.end;
    if (!end || end % tick16) end = (Math.floor(Math.max.apply(null, m.notes.map(function (x) { return x[0]; })) / ppq) + 1) * ppq;
    var n = end / tick16;
    if (n < 1 || n > MAX_STEPS) throw fail(n + " sixteenths (at most " + MAX_STEPS + ")");
    var steps = new Array(n).fill(0), tomVel = new Array(n).fill(0);
    m.notes.forEach(function (x) {
      var t = x[0], note = x[1], vel = x[2];
      if (vel < MIN_VELOCITY) { stats.ghost = (stats.ghost || 0) + 1; return; }
      var k = Math.floor((t + Math.floor(tick16 / 2)) / tick16) % n;
      stats.off = (stats.off || 0) + (t % tick16 !== 0 ? 1 : 0);
      stats.hits = (stats.hits || 0) + 1;
      if (note in NOTES) steps[k] |= NOTES[note];
      else if (note in TOMS) {
        var p = TOMS[note], old = steps[k] & TOM ? steps[k] >> PITCH & 3 : -1;
        if (vel > tomVel[k] || (vel === tomVel[k] && p > old)) { steps[k] = steps[k] & ~(3 << PITCH) | TOM | p << PITCH; tomVel[k] = vel; }
      } else {
        stats.dropped = stats.dropped || {};
        stats.dropped[note] = (stats.dropped[note] || 0) + 1;
      }
    });
    while (steps.length % 4) steps.push(0);
    return steps;
  }

  // Natural name order, as grooves.py --user sorts the files.
  function naturalKey(s) { return s.split(/(\d+)/).map(function (t) { return /^\d+$/.test(t) ? parseInt(t, 10) : t.toLowerCase(); }); }
  function naturalCompare(a, b) {
    var x = naturalKey(a), y = naturalKey(b);
    for (var i = 0; i < Math.min(x.length, y.length); i++) {
      if (x[i] === y[i]) continue;
      if (typeof x[i] === typeof y[i]) return x[i] < y[i] ? -1 : 1;
      return typeof x[i] === "number" ? -1 : 1;
    }
    return x.length - y.length;
  }

  var api = { KICK: KICK, SNARE: SNARE, HAT: HAT, TOM: TOM, OPEN: OPEN, PITCH: PITCH, USER_SLOT: USER_SLOT,
              USER_MAX_STEPS: USER_MAX_STEPS, MAX_LOOPS: MAX_LOOPS, MAX_STEPS: MAX_STEPS,
              userBank: userBank, sampleBytes: sampleBytes, wavBytes: wavBytes, readBank: readBank,
              convertMidi: convertMidi, naturalCompare: naturalCompare };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.GROOVE = api;
})(this);
