// firmware-core.js - the setup page's firmware build: the user's stock HX Effects 3.80.0 .hxf plus web/recipe.bin
// (tools/recipe.py) gives the tested build, byte for byte. Runs in the page's worker (firmware-worker.js) and in
// Node (tests/test_web.py), with pako (zlib) and an MD5 function passed in.
//
// An .hxf is an IFF container: FORM <size> L6FF, then HEAD (payload size at 16, payload MD5 at 20), two dinf
// regions and data (the zlib-compressed L6IA archive). The recipe rebuilds the archive from the stock one; the
// container is then written as tools/hxf.py pack --donor stock writes it, and its MD5 checked against the recipe.
(function (root) {
  "use strict";

  function be32(b, o) { return ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0; }
  function le32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }
  function setBe32(b, o, v) { b[o] = v >>> 24; b[o + 1] = (v >>> 16) & 255; b[o + 2] = (v >>> 8) & 255; b[o + 3] = v & 255; }
  function hex(b) { return Array.prototype.map.call(b, function (x) { return (x < 16 ? "0" : "") + x.toString(16); }).join(""); }
  function tag(b, o) { return String.fromCharCode(b[o], b[o + 1], b[o + 2], b[o + 3]); }

  function chunks(raw) {
    if (raw.length < 12 || tag(raw, 0) !== "FORM" || tag(raw, 8) !== "L6FF") throw new Error("notHxf");
    var pos = 12, out = [];
    while (pos + 8 <= raw.length) {
      var sz = be32(raw, pos + 4);
      out.push({ id: tag(raw, pos), body: raw.subarray(pos + 8, pos + 8 + sz) });
      pos += 8 + sz + (sz & 1);
    }
    return out;
  }

  function parseRecipe(r) {
    if (tag(r, 0) !== "HXR1") throw new Error("badRecipe");
    return { stockMd5: hex(r.subarray(4, 20)), archiveMd5: hex(r.subarray(20, 36)), hxfMd5: hex(r.subarray(36, 52)),
             size: le32(r, 52), nops: le32(r, 56), body: r };
  }

  // build(stockBytes, recipeBytes (zlib), {pako, md5, progress}) -> { hxf: Uint8Array, md5 }
  // Throws Error("notHxf" | "notStock" | "badRecipe" | "archiveMismatch" | "hxfMismatch").
  function build(stock, recipeZ, env) {
    var p = env.progress || function () {};
    var R = parseRecipe(env.pako.inflate(recipeZ));
    p("read", 1);
    var ch = chunks(stock);
    var data = ch.filter(function (c) { return c.id === "data"; })[0];
    if (!data) throw new Error("notHxf");
    var old = env.pako.inflate(data.body);
    p("check", 2);
    if (env.md5(old) !== R.stockMd5) throw new Error("notStock");
    p("apply", 3);
    var out = new Uint8Array(R.size), d = 0, q = 60, r = R.body;
    for (var k = 0; k < R.nops; k++) {
      var n;
      if (r[q] === 0) {
        var s = le32(r, q + 1); n = le32(r, q + 5);
        out.set(old.subarray(s, s + n), d); q += 9;
      } else {
        n = le32(r, q + 1);
        out.set(r.subarray(q + 5, q + 5 + n), d); q += 5 + n;
      }
      d += n;
    }
    if (d !== R.size || env.md5(out) !== R.archiveMd5) throw new Error("archiveMismatch");
    p("compress", 4);
    var comp = env.pako.deflate(out, { level: 9 });
    p("pack", 5);
    // the container: the stock HEAD and dinf chunks with the new size, MD5 and region bounds (tools/hxf.py pack)
    var head = new Uint8Array(ch.filter(function (c) { return c.id === "HEAD"; })[0].body);
    setBe32(head, 16, out.length);
    for (var i = 0; i < 16; i++) head[20 + i] = parseInt(R.archiveMd5.substr(2 * i, 2), 16);
    var dinfs = ch.filter(function (c) { return c.id === "dinf"; }).map(function (c) { return new Uint8Array(c.body); });
    if (dinfs.length === 2 && tag(out, 0) === "L6IA") {
      var trailer = be32(dinfs[1], 12), end = out.length - trailer;
      setBe32(dinfs[0], 8, 0); setBe32(dinfs[0], 12, end);
      setBe32(dinfs[1], 8, end); setBe32(dinfs[1], 12, trailer);
    }
    var parts = [["HEAD", head]].concat(dinfs.map(function (x) { return ["dinf", x]; }), [["data", comp]]);
    var len = 4;
    parts.forEach(function (x) { len += 8 + x[1].length + (x[1].length & 1); });
    var hxf = new Uint8Array(8 + len), o = 0;
    function put(s) { for (var j = 0; j < 4; j++) hxf[o + j] = s.charCodeAt(j); o += 4; }
    put("FORM"); setBe32(hxf, o, len); o += 4; put("L6FF");
    parts.forEach(function (x) {
      put(x[0]); setBe32(hxf, o, x[1].length); o += 4;
      hxf.set(x[1], o); o += x[1].length + (x[1].length & 1);
    });
    var md5 = env.md5(hxf);
    if (md5 !== R.hxfMd5) throw new Error("hxfMismatch");
    p("done", 6);
    return { hxf: hxf, md5: md5 };
  }

  var api = { build: build, parseRecipe: parseRecipe, STEPS: 6 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FIRMWARE = api;
})(this);
