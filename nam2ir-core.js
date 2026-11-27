// nam2ir-core.js - a NAM A2 Lite capture (.nam) as a User IR (.wav) for NAM A2 Lite on the HX Effects,
// the same bytes as tools/nam2ir.py (with opts.match, as nam2ir.py --match: level-matched). Runs in the browser (window.NAM2IR) and
// in Node (module.exports) for the check against the Python tool.
//
// The .wav is 2,048 samples, 48 kHz, mono, 32-bit float: a header (0.5, -0.5,
// 3.0, a scale 2^e, 1871 / 1024, the input level, 0, 0), then the capture's 1,871 weights
// in the order the kernel loads them, then their silence state (72 words), all
// divided by 2^e so that every sample is within HX Edit's +-15.8 limit, then zeros.
(function (root) {
  "use strict";

  var C = 3;
  var HEAD_TAPS = 16;
  var IR_SAMPLES = 2048;
  var IR_LIMIT = 15.8489;           // HX Edit refuses a sample beyond +-24 dB
  var KERNEL = [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 15, 15, 6, 6, 6, 6, 6, 6, 6];
  var DILATION = [1, 3, 7, 17, 41, 101, 239, 1, 3, 7, 17, 41, 101, 239, 1, 13, 1, 3, 7, 17, 41, 101, 239];
  var N_WEIGHTS = 1871;
  var STOMP_DBU = 11.5;             // the Stomp's input at 0 dBFS, also used for the HX Effects (not measured on it): tools/sharc/nam_lite.py

  function same(a, b) {
    return Array.isArray(a) && a.length === b.length && a.every(function (x, i) { return x === b[i]; });
  }

  // The 3-channel WaveNet in a parsed .nam: the file itself, or the matching
  // submodel of a SlimmableContainer. Throws an Error that says what is wrong.
  function pickModel(d) {
    if (!d || typeof d !== "object" || !d.architecture) {
      throw new Error("This is not a NAM model file: it has no architecture.");
    }
    var subs = d.architecture === "SlimmableContainer"
      ? ((d.config && d.config.submodels) || []).map(function (s) { return s.model; })
      : [d];
    var seen = [];
    for (var i = 0; i < subs.length; i++) {
      var m = subs[i];
      if (!m || m.architecture !== "WaveNet" || !m.config || !m.config.layers || !m.config.layers.length) {
        if (m && m.architecture) seen.push(m.architecture);
        continue;
      }
      var ch = m.config.layers[0].channels;
      if (ch === C) return { model: m, slimmable: d.architecture === "SlimmableContainer" };
      seen.push(ch + "-channel WaveNet");
    }
    throw new Error("No 3-channel A2 Lite model inside (found: " + (seen.join(", ") || "nothing usable") +
                    "). NAM A2 Lite plays A2 Lite captures only.");
  }

  // What would make the kernel compute something else than this capture.
  function problems(m) {
    var out = [];
    var L = m.config.layers;
    if (L.length !== 1) out.push(L.length + " layer arrays; A2 Lite has 1");
    var l = L[0];
    if (l.kernel_sizes && !same(l.kernel_sizes, KERNEL)) out.push("kernel sizes differ from A2's");
    if (l.dilations && !same(l.dilations, DILATION)) out.push("dilations differ from A2's");
    (l.activation || []).forEach(function (a, i) {
      if (a && (a.type !== "LeakyReLU" || a.negative_slope !== 0.01)) {
        out.push("layer " + (i + 1) + " uses " + a.type + "; the kernel has LeakyReLU 0.01");
      }
    });
    (l.gating_mode || []).forEach(function (g, i) {
      if (g && g !== "none") out.push("layer " + (i + 1) + " is gated");
    });
    if (!Array.isArray(m.weights) || m.weights.length !== N_WEIGHTS) {
      out.push((m.weights ? m.weights.length : 0) + " weights; A2 Lite has " + N_WEIGHTS);
    }
    return out;
  }

  // The capture's input level in dBu (metadata input_level_dbu), or null when
  // the file does not give a number: tools/sharc/nam_pack.py input_level_dbu().
  function inputLevelDbu(meta) {
    var dbu = meta && meta.input_level_dbu;
    return typeof dbu === "number" && isFinite(dbu) ? dbu : null;
  }

  // IR word 5: tools/sharc/nam_lite.py level_word().
  function levelWord(dbu) {
    if (dbu === null) return 0;
    var g = Math.fround(Math.pow(10, -dbu / 20));
    if (!(g > 0 && g < IR_LIMIT)) throw new Error("Input level " + dbu + " dBu is out of range (above -24 dBu).");
    return g;
  }


  // Level matching, tools/sharc/nam_level.py: the model run in float64 on a fixed strummed E-A-D chord (1 s,
  // -10 dBFS peak, times the capture's input trim), K-weighted mean square in dB (BS.1770, 48 kHz).
  var TARGET = -18, FS = 48000, PAD = 8192;
  var K_SHELF = [[1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]];
  var K_HPF = [[1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]];

  function testSignal() {
    var out = new Float64Array(FS), f0s = [82.41, 110.0, 146.83], peak = 0, i, k, h;
    for (k = 0; k < 3; k++) {
      var t0 = Math.floor(k * 0.015 * FS);
      for (i = 0; i < FS - t0; i++) {
        var tt = i / FS, tone = 0;
        for (h = 0; h < 6; h++) tone += Math.pow(0.6, h) * Math.sin(2 * Math.PI * f0s[k] * (h + 1) * tt);
        out[t0 + i] += Math.exp(-3.0 * tt) * tone;
      }
    }
    for (i = 0; i < FS; i++) peak = Math.max(peak, Math.abs(out[i]));
    var g = Math.pow(10, -10 / 20) / peak;
    for (i = 0; i < FS; i++) out[i] *= g;
    return out;
  }

  function inputTrim(dbu) {
    var g = Math.fround(levelWord(dbu) * Math.fround(Math.pow(10, STOMP_DBU / 20)));
    return g > 0 ? g : 1.0;
  }

  function forward(w, sig) {
    var n = PAD + sig.length, u = new Float64Array(n), c, i, j, t, o = C;
    u.set(sig, PAD);
    var x = [], hs = [];
    for (c = 0; c < C; c++) {
      x.push(new Float64Array(n)); hs.push(new Float64Array(n));
      for (i = 0; i < n; i++) x[c][i] = w[c] * u[i];
    }
    KERNEL.forEach(function (k, L) {
      var d = DILATION[L], W = o; o += C * C * k;
      var b = o, mi = o + C; o += 2 * C;
      var W1 = o; o += C * C;
      var b1 = o; o += C;
      var a = [];
      for (c = 0; c < C; c++) {
        var z = new Float64Array(n);
        for (i = 0; i < n; i++) z[i] = w[b + c] + w[mi + c] * u[i];
        for (t = 0; t < k; t++) {
          var s = (k - 1 - t) * d;
          for (j = 0; j < C; j++) {
            var ww = w[W + (c * C + j) * k + t], xj = x[j];
            for (i = s; i < n; i++) z[i] += ww * xj[i - s];
          }
        }
        for (i = 0; i < n; i++) { var v = z[i]; z[i] = v > 0 ? v : 0.01 * v; hs[c][i] += z[i]; }
        a.push(z);
      }
      for (c = 0; c < C; c++) {
        var xc = x[c];
        for (i = 0; i < n; i++) {
          var acc = w[b1 + c];
          for (j = 0; j < C; j++) acc += w[W1 + c * C + j] * a[j][i];
          xc[i] += acc;
        }
      }
    });
    var Wh = o; o += C * HEAD_TAPS;
    var y = new Float64Array(sig.length);
    for (i = PAD; i < n; i++) {
      var acc2 = 0;
      for (t = 0; t < HEAD_TAPS; t++) {
        var s2 = HEAD_TAPS - 1 - t;
        if (i - s2 < 0) continue;
        for (c = 0; c < C; c++) acc2 += w[Wh + c * HEAD_TAPS + t] * hs[c][i - s2];
      }
      y[i - PAD] = w[o + 1] * (acc2 + w[o]);
    }
    return y;
  }

  function biquad(x, bc, ac) {
    var y = new Float64Array(x.length), x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (var i = 0; i < x.length; i++) {
      var r = bc[0] * x[i] + bc[1] * x1 + bc[2] * x2 - ac[1] * y1 - ac[2] * y2;
      x2 = x1; x1 = x[i]; y2 = y1; y1 = r; y[i] = r;
    }
    return y;
  }

  // The capture's loudness on the unit (dB) and the factor on its output scale that brings it to `target`.
  function levelMatch(w, dbu, target) {
    var sig = testSignal(), tr = inputTrim(dbu), i;
    for (i = 0; i < sig.length; i++) sig[i] *= tr;
    var k = biquad(biquad(forward(w, sig), K_SHELF[0], K_SHELF[1]), K_HPF[0], K_HPF[1]), ms = 0;
    for (i = 0; i < k.length; i++) ms += k[i] * k[i];
    var db = 10 * Math.log10(ms / k.length + 1e-20);
    return { db: db, gain: Math.pow(10, (target - db) / 20) };
  }

  // tools/sharc/nam_lite.py layer_weights(): per layer bias and mix-in per
  // output channel, the taps [tap][input][output], then per output channel
  // bias1 and its 1x1 weights; the head (bias, then [tap][channel]); the
  // rechannel weights; the head scale.
  function layerWeights(w) {
    var o = C, blocks = [];
    KERNEL.forEach(function (k) {
      var conv = o; o += C * C * k;
      var bias = o; o += C;
      var mixin = o; o += C;
      var w1 = o; o += C * C;
      var b1 = o; o += C;
      var blk = [], i, j, t;
      for (i = 0; i < C; i++) blk.push(w[bias + i], w[mixin + i]);
      for (t = 0; t < k; t++) for (j = 0; j < C; j++) for (i = 0; i < C; i++) blk.push(w[conv + (i * C + j) * k + t]);
      for (i = 0; i < C; i++) {
        blk.push(w[b1 + i]);
        for (j = 0; j < C; j++) blk.push(w[w1 + i * C + j]);
      }
      blocks.push(blk);
    });
    var head = [w[o + C * HEAD_TAPS]];
    for (var t = 0; t < HEAD_TAPS; t++) for (var j = 0; j < C; j++) head.push(w[o + j * HEAD_TAPS + t]);
    return { blocks: blocks, head: head, rech: w.slice(0, C), scale: w[o + C * HEAD_TAPS + 1] };
  }

  // tools/sharc/nam_lite.py silence(): what the rings hold after silence, in
  // float32 op for op as the kernel adds: the head's input (3) and each layer's
  // input x (23 x 3). A change of model fills the rings with it, so it does not pop.
  function silence(w) {
    var f = Math.fround;
    var lw = layerWeights(w.map(f));
    var x = lw.rech.map(function (r) { return f(r * 0); });
    var hs = [0, 0, 0], xs = [];
    KERNEL.forEach(function (k, n) {
      var blk = lw.blocks[n], a = [], i, j, t;
      xs.push(x.slice());
      for (i = 0; i < C; i++) {
        var v = f(f(blk[2 * i] + f(blk[2 * i + 1] * 0)) + 0);
        for (t = 0; t < k; t++) for (j = 0; j < C; j++) v = f(v + f(blk[2 * C + (t * C + j) * C + i] * x[j]));
        a.push(Math.max(v, f(v * f(0.01))));
      }
      hs = hs.map(function (h, i) { return f(h + a[i]); });
      var o = 2 * C + k * C * C;
      for (i = 0; i < C; i++) {
        var u = blk[o + 4 * i];
        for (j = 0; j < C; j++) u = f(u + f(a[j] * blk[o + 4 * i + 1 + j]));
        x[i] = f(x[i] + u);
      }
    });
    return { hs: hs, xs: xs };
  }

  // The words a model loads as: the 1,871 weights, then its silence state
  // (72 words, each / 16, as the kernel keeps them).
  function stream(w) {
    var lw = layerWeights(w);
    var out = lw.rech.concat(lw.head, [lw.scale]);
    lw.blocks.forEach(function (b) { out = out.concat(b); });
    var s = silence(w);
    s.xs.forEach(function (x) { s.hs = s.hs.concat(x); });
    return out.concat(s.hs.map(function (v) { return v / 16; }));
  }

  // The 2,048 IR samples as a Float32Array, and the scale exponent.
  function irSamples(w, dbu) {
    var st = stream(w);
    var peak = 0;
    st.forEach(function (x) { peak = Math.max(peak, Math.abs(x)); });
    var e = 0;
    while (peak / Math.pow(2, e) > 15.5) e++;
    var s = Math.pow(2, e);
    var vals = [0.5, -0.5, C, s, N_WEIGHTS / 1024, levelWord(dbu === undefined ? null : dbu), 0, 0].concat(st.map(function (x) { return x / s; }));
    if (vals.length >= IR_SAMPLES) throw new Error("Too many weights for one IR slot.");
    vals.forEach(function (v) {
      if (!(Math.abs(v) < IR_LIMIT)) throw new Error("A sample HX Edit would refuse (" + v + ").");
    });
    var out = new Float32Array(IR_SAMPLES);
    out.set(vals);
    return { samples: out, exponent: e, peak: peak };
  }

  // A 48 kHz mono IEEE-float .wav, as tools/nam2ir.py write_wav().
  function wavBytes(samples) {
    var n = samples.length, buf = new ArrayBuffer(44 + 4 * n), v = new DataView(buf);
    function tag(o, s) { for (var i = 0; i < 4; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    tag(0, "RIFF"); v.setUint32(4, 36 + 4 * n, true); tag(8, "WAVE");
    tag(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 3, true); v.setUint16(22, 1, true);
    v.setUint32(24, 48000, true); v.setUint32(28, 48000 * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 32, true);
    tag(36, "data"); v.setUint32(40, 4 * n, true);
    for (var i = 0; i < n; i++) v.setFloat32(44 + 4 * i, samples[i], true);
    return new Uint8Array(buf);
  }

  // "Mesa Boogie" + "Mesa Boogie JP-2C" -> "Mesa Boogie JP-2C"; unset fields left out.
  function gearName(make, model) {
    var ok = function (x) { return typeof x === "string" && x && !/^t3k-/i.test(x); };
    if (!ok(make)) return ok(model) ? model : "";
    if (!ok(model)) return make;
    return model.toLowerCase().indexOf(make.toLowerCase()) === 0 ? model : make + " " + model;
  }

  // Text of a .nam file -> { wav, info } or an Error thrown. opts: level: false
  // to leave the input level out (word 5 0: no trim).
  function convert(text, opts) {
    opts = opts || {};
    var d;
    try { d = JSON.parse(text); } catch (err) { throw new Error("The file is not valid JSON, so not a .nam file."); }
    var pick = pickModel(d);
    var bad = problems(pick.model);
    if (bad.length) throw new Error("Not an A2 Lite capture the kernel can run: " + bad.join("; ") + ".");
    var meta = d.metadata || {};
    var dbu = opts.level === false ? null : inputLevelDbu(meta);
    var weights = pick.model.weights, match = null;
    if (opts.match !== undefined && opts.match !== false) {
      var target = opts.match === true ? TARGET : opts.match;
      match = levelMatch(weights, dbu, target);
      weights = weights.slice(0, -1).concat([weights[weights.length - 1] * match.gain]);   // the head's scale: level only
      match.target = target;
    }
    var ir = irSamples(weights, dbu);
    var rate = pick.model.sample_rate || d.sample_rate;
    return {
      wav: wavBytes(ir.samples),
      info: {
        name: meta.name || "",
        modeledBy: meta.modeled_by || "",
        gear: gearName(meta.gear_make, meta.gear_model),
        slimmable: pick.slimmable,
        exponent: ir.exponent,
        peak: ir.peak,
        inputDbu: dbu,
        trimDb: dbu === null ? null : STOMP_DBU - dbu,
        levelDb: match ? match.db : null,
        matchDb: match ? 20 * Math.log10(match.gain) : null,
        sampleRate: rate,
        warnings: rate && rate !== 48000 ? ["Trained at " + rate + " Hz; the HX Effects runs at 48 kHz, so it will sound off."] : []
      }
    };
  }

  var api = { STOMP_DBU: STOMP_DBU, TARGET: TARGET, levelMatch: levelMatch, convert: convert, pickModel: pickModel, problems: problems, irSamples: irSamples, wavBytes: wavBytes };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.NAM2IR = api;
})(this);
