// fw-reader.js - the HX Effects firmware's own model tables, read in the browser from the person's firmware file.
//
// A JavaScript port of tools/preset_send.py model_table() and tools/patch_amp.py parse_entry3_full(), plus the
// details the page shows: each model's category and display name and its DSP cost; each knob's display name, display
// type, units and the names of its choices. Nothing here is Line 6 data: it is read from the archive the page is
// given (the stock .hxf, or a build made from it with a recipe, firmware-core.js).
//
//   FWREAD.read(archive) -> {name: {pid, btype, cost, display, category, subcategory, legacy, params: [knob...]}}
//   legacy: the firmware files the model under Legacy (the older Line 6 models), as the unit's browser does
//   knob: {name, type (1 switch, 2 whole number, 3 decimal), default, min, max, meta: {displayType, displayName, ...}}
(function (root) {
  "use strict";
  const be32 = (b, o) => ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0;
  const dec = new TextDecoder("latin1");

  // ---- the L6IA archive (tools/l6ia.py): entries of big-endian words ----
  const ROOT = 0x18, EH = 0x24, SH = 0x200;
  function entry(arc, idx) {
    if (dec.decode(arc.subarray(0, 4)) !== "L6IA") throw new Error("not an L6IA archive");
    const count = be32(arc, 0x14);
    let off = ROOT;
    for (let n = 0; n < count; n++) {
      const words = be32(arc, off + 0x10);
      if (n === idx) {
        const p = arc.subarray(off + EH + SH, off + EH + words * 4), out = new Uint8Array(p.length);
        const k = p.length & ~3;
        for (let i = 0; i < k; i += 4) { out[i] = p[i + 3]; out[i + 1] = p[i + 2]; out[i + 2] = p[i + 1]; out[i + 3] = p[i]; }
        out.set(p.subarray(k), k);
        return out;
      }
      off += EH + words * 4;
    }
    throw new Error("no entry " + idx);
  }

  // ---- Entry 3: the model and parameter catalogue (patch_amp.parse_entry3_full) ----
  function entry3(e3) {
    const v = new DataView(e3.buffer, e3.byteOffset, e3.byteLength);
    const u = o => v.getUint32(o, true), f = o => v.getFloat32(o, true), i32 = o => v.getInt32(o, true);
    if (u(0) !== 0x4023245e) throw new Error("bad Entry 3");
    const strOff = u(12), mtab = u(24), mcnt = u(28);
    const nstr = u(strOff), base = strOff + 8 + 12 * nstr, strings = new Array(nstr);
    for (let i = 0; i < nstr; i++) {
      const r = strOff + 8 + 12 * i;
      strings[i] = dec.decode(e3.subarray(base + u(r), base + u(r) + u(r + 8)));
    }
    const meta = (cnt, off) => {
      const m = {};
      for (let k = 0; k < cnt; k++) {
        const ks = u(off + 12 * k), kt = u(off + 12 * k + 4), kv = u(off + 12 * k + 8);
        m[strings[ks]] = kt === 7 && kv < nstr ? strings[kv] : kv;
      }
      return m;
    };
    const models = [];
    for (let i = 0; i < mcnt; i++) {
      const w = o => u(mtab + 56 * i + 4 * o);
      const params = [];
      for (let p = 0; p < w(7); p++) {
        const po = w(11) + 32 * p, type = u(po + 12);
        // a switch's or whole number's default, min and max are integers in the words a decimal's floats use
        const num = o => type === 1 ? !!i32(o) : type === 2 ? i32(o) : f(o);
        params.push({ name: strings[u(po + 8)], type, slot: u(po + 16), min: num(po + 20), max: num(po + 24),
                      default: num(po + 28), meta: meta(u(po), u(po + 4)) });
      }
      models.push({ nameIdx: w(2), name: strings[w(2)], meta: meta(w(0), w(1)), params });
    }
    return models;
  }

  // ---- Entry 0: the app (Table 1: preset id and DSP cost; the browser lists: block type) ----
  const A = {
    CODE_SEG: 2, CODE_DST: 0x28000000,
    TAB1_BASE_PTR: 0x28100b1c,                    // the live table: the amps build moves and grows it
    TAB1_CNT_INSNS: [0x2808d4ca, 0x280c8032, 0x280d7046, 0x280e6aac, 0x28100b5c],
    BLIST_PTR_TAB: 0x2810021c, BLIST_CNT_TAB: 0x2810030c,
  };
  function entry0(e0) {
    const v = new DataView(e0.buffer, e0.byteOffset, e0.byteLength), u = o => v.getUint32(o, true);
    if (u(0) !== 0x230b0c5e || u(4) !== e0.length) throw new Error("bad Entry 0");
    const segs = [];
    for (let s = 0, off = 0x34; s < u(16); s++) { const len = u(off), dst = u(off + 4); segs.push([off + 12, len, dst]); off += 12 + len; }
    if (segs[A.CODE_SEG][2] !== A.CODE_DST) throw new Error("not the HX Effects v3.80.0 app");
    const fo = (va, n = 4) => {
      for (const [p, len, dst] of segs) if (dst <= va && va + n <= dst + len) return p + va - dst;
      throw new Error("address " + va.toString(16) + " not in the app");
    };
    const vu32 = va => u(fo(va));
    const movw = va => {           // Thumb-2 movw Rd, #imm16
      const o = fo(va), h1 = v.getUint16(o, true), h2 = v.getUint16(o + 2, true);
      if ((h1 & 0xfbf0) !== 0xf240 || (h2 & 0x8000)) throw new Error("not a movw at " + va.toString(16));
      return ((h1 & 0xf) << 12) | (((h1 >> 10) & 1) << 11) | (((h2 >> 12) & 7) << 8) | (h2 & 0xff);
    };
    const t1 = vu32(A.TAB1_BASE_PTR), n1 = Math.max(...A.TAB1_CNT_INSNS.map(movw));
    const row = new Map();         // name index -> [preset id, cost]
    for (let i = 0; i < n1; i++) {
      let o; try { o = fo(t1 + 12 * i, 12); } catch (e) { break; }
      const n = u(o), pid = v.getUint16(o + 4, true), cost = u(o + 8);
      if (pid > 0x1000 || n > 0x10000) break;
      if (!row.has(n)) row.set(n, [pid, cost]);
    }
    const btype = new Map();       // name index -> the browser item's first byte
    for (let sl = 0; sl < 52; sl++) {
      const lp = vu32(A.BLIST_PTR_TAB + 4 * sl), lc = vu32(A.BLIST_CNT_TAB + 4 * sl);
      for (let k = 0; k < (lp ? lc : 0); k++) btype.set(vu32(lp + 48 * k + 4), e0[fo(lp + 48 * k, 1)]);
    }
    return { row, btype };
  }

  // the models the firmware lists, by firmware name (model_table: in Table 1 and in a browser list)
  function read(arc) {
    const { row, btype } = entry0(entry(arc, 0)), out = {};
    for (const m of entry3(entry(arc, 3))) {
      if (!row.has(m.nameIdx) || !btype.has(m.nameIdx) || out[m.name]) continue;
      const [pid, cost] = row.get(m.nameIdx);
      out[m.name] = { pid, btype: btype.get(m.nameIdx), cost, display: m.meta.displayName || "",
                      category: m.meta.category || "", subcategory: m.meta.subcategory || "", legacy: m.meta.legacy === "true",
                      params: m.params.map(p => ({ name: p.name, type: p.type, slot: p.slot, default: p.default, min: p.min, max: p.max, meta: p.meta })) };
    }
    return out;
  }

  const api = { read, entry, entry0, entry3 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FWREAD = api;
})(typeof self !== "undefined" ? self : this);
