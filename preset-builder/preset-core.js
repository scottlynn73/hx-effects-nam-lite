// preset-core.js - build HX Effects presets in the browser (and in Node, for the check against tools/preset_send.py).
// A JavaScript copy of preset_send.py's builder: the same rules, the same bytes (tools/preset-builder/check_core.py
// compares the two). A preset is "l6-helix", a table of section ends, then one old-spec msgpack map
// (docs/hxedit-preset-format.md, "Building presets" and the sections after it).
//
// PRESET.build(base, spec, models, irMd5s) -> Uint8Array
//   base     a preset blob read from the unit (its snapshots, tempo and settings are kept; blocks, footswitches,
//            controller assignments and snapshot values are replaced)
//   spec     {name, split, merge, split_values, merge_values, blocks: [{pos, model, values, on, footswitch, label, midi_bypass, snapshot_bypass}],
//            snapshots: {...}, controls: [...]}, as
//            preset_send.py build takes it; model is a firmware model name, values by position or by knob name
//   models   FW_MODELS.builds[build]: {name: [pid, block type, [[knob, type, default, min, max], ...], display name]}
//   irMd5s   {IR slot: MD5 hex} of the unit's User IRs (for IR blocks)
(function (root) {
  "use strict";

  // ---------- old-spec msgpack (what the unit writes: no str8, no bin, floats as float32) ----------
  function MpMap(pairs) { this.pairs = pairs; }                 // a map in a given key order
  const M = (...pairs) => new MpMap(pairs);
  function Raw(bytes) { this.bytes = bytes; }                   // a string as raw bytes
  const enc = new TextEncoder();
  const rawz = s => new Raw(enc.encode(s + "\0"));

  function encode(v) {
    const out = [];
    const be = (x, n) => { for (let i = n - 1; i >= 0; i--) out.push(Math.floor(x / 2 ** (8 * i)) & 255); };
    const go = x => {
      if (x === null || x === undefined) out.push(0xc0);
      else if (x === false) out.push(0xc2);
      else if (x === true) out.push(0xc3);
      else if (typeof x === "number" && x instanceof Object === false && Number.isInteger(x) && !Object.is(x, -0) && !(x instanceof Float)) {
        if (x >= 0) {
          if (x < 128) out.push(x); else if (x < 256) { out.push(0xcc, x); } else if (x < 65536) { out.push(0xcd); be(x, 2); }
          else { out.push(0xce); be(x, 4); }
        } else {
          if (x >= -32) out.push(x & 0xff); else if (x >= -128) out.push(0xd0, x & 0xff);
          else if (x >= -32768) { out.push(0xd1); be(x & 0xffff, 2); } else { out.push(0xd2); be(x >>> 0, 4); }
        }
      } else if (x instanceof Float || typeof x === "number") {
        const f = new DataView(new ArrayBuffer(4)); f.setFloat32(0, x instanceof Float ? x.v : x);
        out.push(0xca, ...new Uint8Array(f.buffer));
      } else if (x instanceof Raw || x instanceof Uint8Array) {
        const b = x instanceof Raw ? x.bytes : x;
        if (b.length < 32) out.push(0xa0 | b.length); else if (b.length < 65536) { out.push(0xda); be(b.length, 2); }
        else { out.push(0xdb); be(b.length, 4); }
        for (const c of b) out.push(c);
      } else if (x instanceof MpMap) {
        const n = x.pairs.length;
        if (n < 16) out.push(0x80 | n); else { out.push(0xde); be(n, 2); }
        for (const [k, w] of x.pairs) { go(k); go(w); }
      } else if (Array.isArray(x)) {
        if (x.length < 16) out.push(0x90 | x.length); else { out.push(0xdc); be(x.length, 2); }
        x.forEach(go);
      } else throw new Error("encode: " + typeof x);
    };
    go(v);
    return Uint8Array.from(out);
  }
  function Float(v) { this.v = v; }                            // a whole number that must go as a float
  const F = v => new Float(v);

  // decode one value at o; maps become {key: value} with numeric keys, raw strings Uint8Array
  function decodeAt(b, o) {
    const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const go = () => {
      const t = b[o++];
      if (t < 0x80) return t;
      if (t >= 0xe0) return t - 256;
      if ((t & 0xf0) === 0x80) return map(t & 15);
      if ((t & 0xf0) === 0x90) return arr(t & 15);
      if ((t & 0xe0) === 0xa0) return raw(t & 31);
      let n;
      switch (t) {
        case 0xc0: return null; case 0xc2: return false; case 0xc3: return true;
        case 0xca: n = v.getFloat32(o); o += 4; return n;
        case 0xcb: n = v.getFloat64(o); o += 8; return n;
        case 0xcc: return b[o++];
        case 0xcd: n = v.getUint16(o); o += 2; return n;
        case 0xce: n = v.getUint32(o); o += 4; return n;
        case 0xd0: n = v.getInt8(o); o += 1; return n;
        case 0xd1: n = v.getInt16(o); o += 2; return n;
        case 0xd2: n = v.getInt32(o); o += 4; return n;
        case 0xd9: n = b[o]; o += 1; return raw(n);
        case 0xda: case 0xc5: n = v.getUint16(o); o += 2; return raw(n);
        case 0xdb: case 0xc6: n = v.getUint32(o); o += 4; return raw(n);
        case 0xc4: n = b[o]; o += 1; return raw(n);
        case 0xdc: n = v.getUint16(o); o += 2; return arr(n);
        case 0xde: n = v.getUint16(o); o += 2; return map(n);
      }
      throw new Error("decode: type 0x" + t.toString(16) + " at " + (o - 1));
    };
    const raw = n => { const r = b.slice(o, o + n); o += n; return r; };
    const arr = n => Array.from({ length: n }, go);
    const map = n => { const m = {}; for (let i = 0; i < n; i++) { const k = go(); m[k] = go(); } return m; };
    const val = go();
    return { val, end: o };
  }

  // the parts of a blob: magic, section-end table, the preset map and where it starts
  function parse(blob) {
    const a = decodeAt(blob, 0);
    if (String.fromCharCode(...a.val.slice(0, 8)) !== "l6-helix") throw new Error("not a preset blob");
    const t = decodeAt(blob, a.end);
    const tv = new DataView(t.val.buffer, t.val.byteOffset, t.val.byteLength);
    const table = Array.from({ length: t.val.length / 4 }, (_, i) => tv.getUint32(4 * i, true));
    const body = decodeAt(blob, t.end);
    if (body.end !== blob.length) throw new Error("trailing bytes after the preset map");
    return { table, body: body.val, start: t.end };
  }

  // {path: [start, end, type byte]} for every node of the preset map
  function spans(blob) {
    const { start } = parse(blob), out = new Map();
    const v = new DataView(blob.buffer, blob.byteOffset, blob.byteLength);
    const walk = (o, path) => {
      const t = blob[o];
      let n, p;
      if ((t & 0xf0) === 0x80 || t === 0xde) {
        [n, p] = (t & 0xf0) === 0x80 ? [t & 15, o + 1] : [v.getUint16(o + 1), o + 3];
        for (let i = 0; i < n; i++) { const k = decodeAt(blob, p); p = walk(k.end, path.concat([k.val])); }
      } else if ((t & 0xf0) === 0x90 || t === 0xdc) {
        [n, p] = (t & 0xf0) === 0x90 ? [t & 15, o + 1] : [v.getUint16(o + 1), o + 3];
        for (let i = 0; i < n; i++) p = walk(p, path.concat([i]));
      } else p = decodeAt(blob, o).end;
      out.set(path.join(","), [o, p, t]);
      return p;
    };
    walk(start, []);
    return out;
  }

  function withTable(head, table, rest) {        // magic + table + the bytes after them
    const tb = new Uint8Array(4 * table.length), tv = new DataView(tb.buffer);
    table.forEach((x, i) => tv.setUint32(4 * i, x, true));
    const m = encode(new Raw(enc.encode("l6-helix\0"))), t = encode(tb);
    return concat(m, t, rest);
  }
  function concat(...parts) {
    const out = new Uint8Array(parts.reduce((s, p) => s + p.length, 0)); let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }

  // blob with the node at path replaced by value (encoded as the unit writes it), the section table kept right
  function replaceNode(blob, path, value) {
    const { table, start } = parse(blob);
    const [o, e] = spans(blob).get(path.join(","));
    const nb = encode(value), delta = nb.length - (e - o);
    const headLen = start;
    const rest = concat(blob.slice(headLen, o), nb, blob.slice(e));
    return withTable(null, table.map(x => x > o ? x + delta : x), rest);
  }

  // blob with the scalar at path changed in place, keeping its type and size (the unit writes some ints wide)
  function setInPlace(blob, path, value) {
    const sp = spans(blob).get(path.join(","));
    if (!sp) throw new Error("no value at " + path.join(","));
    const [o, , t] = sp, b = blob.slice(), v = new DataView(b.buffer);
    if (t === 0xca) v.setFloat32(o + 1, +value);
    else if (t === 0xcb) v.setFloat64(o + 1, +value);
    else if (t === 0xc2 || t === 0xc3) b[o] = value ? 0xc3 : 0xc2;
    else if (t === 0xd0) v.setInt8(o + 1, value); else if (t === 0xd1) v.setInt16(o + 1, value); else if (t === 0xd2) v.setInt32(o + 1, value);
    else if (t === 0xcc) b[o + 1] = value; else if (t === 0xcd) v.setUint16(o + 1, value); else if (t === 0xce) v.setUint32(o + 1, value);
    else if (t < 0x80 && value >= 0 && value < 0x80) b[o] = value;
    else throw new Error(`cannot change ${path.join(",")} (type 0x${t.toString(16)}) to ${value} in place`);
    return b;
  }

  // ---------- blocks ----------
  const TRAILS_TYPES = [8, 9, 13], IR_TYPE = 19;
  // A legacy single cab (block type 15) stores its Mic after its five knobs, counted in 2 but not in 3: {2: 6, 3: 5,
  // 4: [Distance, LowCut, HighCut, EarlyReflections, Level, mic]}, mic 0..15 (a preset saved on the unit, 2026-11-27)
  const CAB_TYPE = 15;
  const PATH_A = [1, 2, 3, 4, 5, 6, 7, 8, 9], PATH_B = [12, 13, 14, 15, 16, 17, 18, 19, 20];
  const EMPTY_BLOCK = M([19, 8], [20, null]);
  const SNAP_CTRL = 10;

  // Python round(): halves to even
  const pyRound = x => { const f = Math.floor(x), d = x - f; return d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1); };
  function value(t, v) {
    if (typeof v === "number" && Number.isNaN(v)) v = 0;
    if (v == null) v = 0;
    return t === 1 ? !!v : t === 2 ? pyRound(+v) : F(+v);
  }

  // The loopers the unit stores in a short form (block kind 7): {8: preset id, 9: block type, 10: on,
  // 7: {2: 4, 3: 4, 4: [Playback, Overdub, lowCut, highCut]}} (preset_send.py SHORT_LOOPERS)
  const SHORT_LOOPERS = ["HD2_LooperMono", "HD2_LooperStereo", "HD2_LooperOneSwitchMono", "HD2_LooperOneSwitchStereo"];
  const isBlock = blk => blk[19] === 6 || blk[19] === 7;
  function makeBlock(model, values, on, irMd5, name) {
    const [pid, btype, params] = model;
    if (SHORT_LOOPERS.includes(name)) {
      const vals = params.slice(0, 4).map(p => value(p[1], p[2]));
      (values || []).slice(0, 4).forEach((v, i) => { vals[i] = value(params[i][1], v); });
      return M([19, 7], [20, M([8, pid], [9, btype], [10, !!on], [7, M([2, 4], [3, 4], [4, vals])])]);
    }
    const vals = params.map(p => value(p[1], p[2]));
    (values || []).forEach((v, i) => { if (i < vals.length) vals[i] = value(params[i][1], v); });
    let n3 = vals.length;
    if (TRAILS_TYPES.includes(btype)) {
      const last = params[params.length - 1];
      if (last && last[1] === 1 && (last[0] === "DryThru" || last[0] === "Trails")) n3 -= 1;
      else vals.push(values && values.length > params.length ? !!values[params.length] : false);
    }
    if (btype === CAB_TYPE) vals.push(values && values.length > params.length ? Math.max(0, Math.min(15, pyRound(+values[params.length] || 0))) : 0);
    const pairs = [[24, M([23, false], [25, pid], [26, -1])], [9, btype], [10, !!on], [11, M([2, vals.length], [3, n3], [4, vals])]];
    if (btype === IR_TYPE) {
      if (!irMd5) throw new Error("an IR block needs the MD5 of the IR in its slot");
      pairs.push([27, new Raw(enc.encode(irMd5))]);
    } else pairs.push([12, M([2, 0], [3, 0], [4, []])]);
    return M([19, 6], [20, M(...pairs)]);
  }

  function setSnapshotStates(blob, pos, on) {
    const body = parse(blob).body;
    (body[10] && body[10][10] || []).forEach((snap, k) => {
      const st = snap && snap[3];
      if (st && pos < st.length && Array.isArray(st[pos]) && st[pos].length > 1 && st[pos][1] !== null) blob = setInPlace(blob, [10, 10, k, 3, pos, 1], !!on);
    });
    return blob;
  }
  function setPathB(blob, used) {
    blob = setInPlace(blob, [0, 22, 11, 20, 18], !!used);
    blob = setInPlace(blob, [0, 22, 21, 20, 18], !!used);
    return setInPlace(blob, [0, 21], used ? 1 : 0);
  }
  function addBlock(blob, pos, model, values, on, irMd5, name) {
    if (!PATH_A.includes(pos) && !PATH_B.includes(pos)) throw new Error(`block position ${pos}: 1..9 or 12..20`);
    const body = parse(blob).body;
    if (body[0][22][pos][19] !== 8) throw new Error(`block position ${pos} is not empty`);
    blob = replaceNode(blob, [0, 22, pos], makeBlock(model, values, on, irMd5, name));
    if (PATH_B.includes(pos)) blob = setPathB(blob, true);
    return setSnapshotStates(blob, pos, on);
  }
  function removeBlock(blob, pos) {
    blob = setSnapshotStates(replaceNode(blob, [0, 22, pos], EMPTY_BLOCK), pos, true);
    const body = parse(blob).body;
    if (PATH_B.includes(pos) && !PATH_B.some(p => isBlock(body[0][22][p]))) blob = setPathB(blob, false);
    return blob;
  }
  // A footswitch's LED colour by the block's category (the model's 5th field), [on, off]: the unit stores the lit colour
  // while the block is on and a dim one while it is off (preset_send.py LED). Amps and preamps take distortion's yellow;
  // send/return, FX loop and volume the looper's white.
  const LED = { distortion: [0xd0af00, 0x080600], amp: [0xd0af00, 0x080600], preamp: [0xd0af00, 0x080600],
    dynamics: [0x84ff00, 0x080c00], eq: [0x84ff00, 0x080c00], modulation: [0x0032ff, 0x00040d], delay: [0x06ff00, 0x010900],
    reverb: [0xff2d00, 0x100400], pitch: [0x3200ff, 0x03000b], synth: [0x3200ff, 0x03000b], filter: [0x3200ff, 0x03000b],
    wah: [0x3200ff, 0x03000b], ir: [0xff0028, 0x0b0007], cab: [0xff0003, 0x0b0000], looper: [0x6bffce, 0x07100c], send: [0x6bffce, 0x07100c],
    return: [0x6bffce, 0x07100c], fxloop: [0x6bffce, 0x07100c], volume: [0x6bffce, 0x07100c] };
  const led = (category, on) => (LED[category] || LED.distortion)[on ? 0 : 1];
  // 11 -> 7 is the block's on/off and 11 -> 6 its LED colour: both must match the block as loaded (a preset with every
  // switch stored on and dim yellow loaded with its LEDs dim and needed presses to line up, 2026-11-22)
  const footswitch = (pos, label, on = true, category = "") =>
    [M([10, 7], [11, M([0, 1], [5, rawz(label)], [6, led(category, on)], [7, !!on], [8, pos])], [12, false], [14, rawz("")],
       [13, false], [16, 0], [15, false])];

  // ---------- snapshots, controllers, footswitches (preset_send.py apply_controls) ----------
  const SOURCES = { exp1: 1, exp2: 2, fs1: 3, fs2: 4, fs3: 5, fs4: 6, fs5: 7, fs6: 8, midi: 9, snapshots: 10 };
  const fsKnob = (pos, ki, label, colour = 462860) =>
    M([10, 0], [11, M([0, 2], [5, rawz(label)], [6, colour], [7, false], [8, pos], [2, 0], [9, M([28, 0], [29, ki], [41, false])])],
      [12, false], [14, rawz("")], [13, false], [16, 0], [15, false]);
  const knobRange = p => p[1] === 3 ? [F(p[3] ?? NaN), F(p[4] ?? NaN)] : p[1] === 2 ? [p[3], p[4]] : [false, true];

  function applyControls(blob, spec, models) {
    const body = parse(blob).body, snaps = body[10][10], n = snaps.length, nslots = snaps[0][2].length;
    blob = replaceNode(blob, [4], Array(body[4].length).fill(null));
    for (let k = 0; k < n; k++) blob = replaceNode(blob, [10, 10, k, 2], snaps[k][2].map(() => [false, 64, null]));
    const sb = body[10][13];
    if (Array.isArray(sb)) for (let pos = 0; pos < sb.length; pos++) blob = setInPlace(blob, [10, 13, pos], true);
    const blocks = Object.fromEntries(spec.blocks.map(b => [+b.pos, b]));
    const sp = spec.snapshots || {};
    const cur = (sp.current || 1) - 1;
    if (!(cur >= 0 && cur < n)) throw new Error(`snapshots.current: 1..${n}`);
    (sp.names || []).slice(0, n).forEach((nm, k) => { blob = replaceNode(blob, [10, 10, k, 4], rawz(nm)); });
    for (const [p, states] of Object.entries(sp.states || {})) {
      const pos = +p;
      if (blocks[pos] && blocks[pos].snapshot_bypass === false)
        throw new Error(`snapshots.states[${pos}]: the block has snapshot_bypass false, so snapshots do not switch it`);
      if (!blocks[pos] || states.length !== n) throw new Error(`snapshots.states[${pos}]: ${n} on/off values for a block`);
      for (let k = 0; k < n; k++) blob = setInPlace(blob, [10, 10, k, 3, pos, 1], !!states[k]);
      blob = setInPlace(blob, [0, 22, pos, 20, 10], !!states[cur]);
    }
    const knobOf = (pos, knob, where) => {
      if (!blocks[pos]) throw new Error(`${where}: no block at ${pos}`);
      if (SHORT_LOOPERS.includes(blocks[pos].model)) throw new Error(`${where}: the looper's knobs can't take a controller`);
      const params = models[blocks[pos].model][2];
      const ki = typeof knob === "string" ? params.findIndex(p => p[0] === knob) : +knob;
      if (ki < 0) throw new Error(`${where}: ${blocks[pos].model} has no knob ${knob}`);
      return [ki, params[ki]];
    };
    const lists = new Map(), fs = new Map();
    const push = (map, k, v) => { if (!map.has(k)) map.set(k, []); map.get(k).push(v); };
    let nextId = 0;
    for (const b of spec.blocks) {
      const pos = +b.pos;
      if (b.midi_bypass != null)
        push(lists, SOURCES.midi, M([0, nextId++], [1, M([0, SOURCES.midi], [1, +b.midi_bypass], [2, null], [3, null], [4, 2], [5, pos],
                                                        [9, 5], [10, 300], [11, true], [12, 0])]));
      if (b.snapshot_bypass === false && Array.isArray(sb)) blob = setInPlace(blob, [10, 13, pos], false);
      const sws = Number.isInteger(b.footswitch) ? [b.footswitch] : (b.footswitch || []);
      if (sws.length > 1) throw new Error(`block ${pos}: one footswitch per block (several blocks may share a footswitch)`);
      for (const f of sws) {
        if (!(f >= 1 && f <= body[3][8].length)) throw new Error(`footswitch ${f}: 1..${body[3][8].length}`);
        const m = models[b.model];
        const st = (sp.states || {})[pos];
        // a looper's switch is stored off and dim whatever the block's state (every saved preset, 2026-11-22)
        const on = SHORT_LOOPERS.includes(b.model) ? false : st && st.length ? !!st[cur] : b.on !== false;
        push(fs, +f, footswitch(pos, b.label || m[3] || b.model, on, m[4] || "")[0]);
      }
    }
    const knobs = [];
    for (const kn of sp.knobs || []) {
      const [ki, p] = knobOf(+kn.pos, kn.knob, "snapshots.knobs");
      if (kn.values.length !== n) throw new Error(`snapshots.knobs ${kn.knob}: ${n} values`);
      const r = knobRange(p);
      knobs.push(["snapshots", +kn.pos, ki, p, r[0], r[1], 4, kn.values.map(x => value(p[1], x)), null]);
    }
    for (const c of spec.controls || []) {
      if (!(c.source in SOURCES) || c.source === "snapshots") throw new Error(`controls: source ${c.source}`);
      const [ki, p] = knobOf(+c.pos, c.knob, "controls");
      const r = knobRange(p);
      const lo = "min" in c ? value(p[1], c.min) : r[0], hi = "max" in c ? value(p[1], c.max) : r[1];
      if (c.source === "midi" && c.cc == null) throw new Error('controls: a midi control needs "cc"');
      knobs.push([c.source, +c.pos, ki, p, lo, hi, c.source === "midi" ? +c.cc : 4, null, c.label || null]);
    }
    if (knobs.length > nslots) throw new Error(`at most ${nslots} controlled knobs in a preset`);
    knobs.forEach(([src, pos, ki, p, lo, hi, cc, vals, label], slot) => {
      const cid = nextId++;
      if (vals == null) {
        const v = parse(blob).body[0][22][pos][20][11][4][ki];
        vals = Array(n).fill(p[1] === 3 ? F(v) : v);
      } else {
        const raw = vals[cur] instanceof Float ? vals[cur].v : vals[cur];
        blob = setInPlace(blob, [0, 22, pos, 20, 11, 4, ki], raw);
      }
      for (let k = 0; k < n; k++) blob = replaceNode(blob, [10, 10, k, 2, slot], [false, cid, vals[k]]);
      push(lists, SOURCES[src], M([0, cid], [1, M([0, SOURCES[src]], [1, cc], [2, lo], [3, hi], [4, 0], [5, pos],
                                                   [6, M([28, 0], [29, ki], [41, false])], [7, 0], [13, false])]));
      if (src.startsWith("fs")) push(fs, +src.slice(2), fsKnob(pos, ki, label || p[0]));
    });
    for (const [source, entries] of lists) blob = replaceNode(blob, [4, source], entries.slice().reverse());
    for (const [f, entries] of fs) {
      // field 10, in assignment order (HX Edit, 2026-11-22): the first entry 7 if it turns a block on/off, 0 if it
      // moves a knob; every later one counts down from 7 (after a knob) or 6 (after an on/off). Two knob entries both
      // left at 0 froze the unit when it was asked for its state, and at start-up.
      let c = 7;
      entries.forEach((e, k) => {
        const inner = e.pairs.find(p => p[0] === 11)[1], bypass = inner.pairs.find(p => p[0] === 0)[1] === 1;
        e.pairs.find(p => p[0] === 10)[1] = k === 0 && !bypass ? 0 : c--;
      });
      blob = replaceNode(blob, [3, 8, f - 1], entries.slice().reverse());
    }
    blob = setInPlace(blob, [10, 8], knobs.length);
    return setInPlace(blob, [10, 6], cur);
  }

  // ---------- the whole preset ----------
  function build(base, spec, models, irMd5s) {
    const body = parse(base).body;
    let blob = base;
    body[0][22].forEach((blk, pos) => { if (isBlock(blk)) blob = removeBlock(blob, pos); });
    for (let j = 0; j < body[3][8].length; j++) blob = replaceNode(blob, [3, 8, j], null);
    for (const b of spec.blocks) {
      const m = models[b.model];
      if (!m) throw new Error(`model ${b.model} is not in this firmware`);
      let vals = b.values;
      if (vals && !Array.isArray(vals)) vals = m[2].map(p => (p[0] in vals ? vals[p[0]] : p[2]));
      let md5 = null;
      if (m[1] === IR_TYPE) {
        const slot = pyRound(+((vals && vals[0]) ?? m[2][0][2]));
        md5 = (irMd5s || {})[slot];
        if (!md5) throw new Error(`IR block at ${b.pos}: User IR slot ${slot} is empty on the unit`);
      }
      blob = addBlock(blob, +b.pos, m, vals, b.on !== false, md5, b.model);
    }
    blob = applyControls(blob, spec, models);
    blob = setInPlace(blob, [0, 22, 11, 20, 15, 13], spec.split ?? 1);    // always written: see the format notes
    blob = setInPlace(blob, [0, 22, 21, 20, 17, 13], spec.merge ?? 10);
    // the split's knobs [Balance A, Balance B] and the merge mixer's [A Level, A Pan, B Level, B Pan, B Polarity, Level]
    for (const [key, path] of [["split_values", [0, 22, 11, 20, 15, 7, 4]], ["merge_values", [0, 22, 21, 20, 17, 7, 4]]])
      (spec[key] || []).forEach((v, i) => { if (v != null) blob = setInPlace(blob, [...path, i], v); });
    return blob;
  }

  const api = { build, parse, spans, replaceNode, setInPlace, makeBlock, encode, decodeAt, M, Raw, F };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PRESET = api;
})(typeof self !== "undefined" ? self : this);
