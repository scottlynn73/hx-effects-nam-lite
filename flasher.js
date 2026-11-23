// flasher.js - tools/flash.py in the browser (WebUSB): install an .hxf on the HX Effects without Line 6 Updater.
// The same protocol, step for step (see flash.py's docstring):
//   1. main app (0e41:4245, class 0xef): update-port handshake, cmd 01/03/02; it restarts into the NXP ROM's DFU
//      loader (1fc9:000c);
//   2. DFU 1.1: the .hxf's kind-5 region (the updater app) in 2048-byte blocks; it starts the updater app
//      (0e41:4245, class 0);
//   3. updater app: per L6IA entry 05 begin, 06 start, 07 chunks of 4096 words, 09 end; then 0a finish;
//   4. boot check: the main app answers "F15Main" on its device-info port.
// FLASHER.flash(opts) runs all of it from whichever mode the unit is in.
//   opts.hxf      Uint8Array, the .hxf (checked here as flash.py checks it)
//   opts.usb      navigator.usb (or a stand-in)
//   opts.inflate  zlib inflate (pako.inflate)
//   opts.ask(stage) -> Promise resolved by a click, after which the browser may show its device list
//   opts.unask(), opts.stage(name), opts.progress(fraction), opts.log(text), opts.sleep(ms)
// Rejects with an Error whose .code is one of CODES. Also: FLASHER.Commands, FLASHER.firmware (for tests).
(function (root) {
  "use strict";

  var VID = 0x0E41, PID = 0x4245, DFU_VID = 0x1FC9, DFU_PID = 0x000C;
  var MAIN = [{ vendorId: VID, productId: PID }], DFU = [{ vendorId: DFU_VID, productId: DFU_PID }];
  var HOST_PORT = 0x1001, DEV_PORT = 0x03EF;
  var MAX_PAYLOAD = 496, WINDOW = 512, HEARTBEAT = 1000, CHUNK_WORDS = 4096, DFU_BLOCK = 2048;
  var PRODUCT_HEAD = [0x00, 0x21, 0x00, 0x05];
  var PREAMBLE_UPDATE = [h("000003000100000003"), h("01000000020000000000")];
  var PREAMBLE_UPDATE_REPLY = h("00000300020000000000");
  var PREAMBLE_INFO = h("010005000100000005");
  var HELLO_REPLY = h("01040404");
  var INFO_TAIL = h("0300000001000000000000000200000000000000030000000100000000000000");
  var REPLY_LEN = { 1: 4, 2: 4, 3: 36, 4: 28, 5: 60, 6: 4, 7: 8, 9: 4, 10: 12 };
  var CODES = ["file", "busy", "notfound", "protocol", "refused", "gone", "cancel", "boot"];

  function h(s) { var b = new Uint8Array(s.length / 2); for (var i = 0; i < b.length; i++) b[i] = parseInt(s.substr(2 * i, 2), 16); return b; }
  function hex(b) { return Array.prototype.map.call(b, function (x) { return (x < 16 ? "0" : "") + x.toString(16); }).join(""); }
  function fail(code, text) { var e = new Error(text); e.code = code; return e; }
  function eq(a, b) { if (a.length !== b.length) return false; for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }
  function zeros(b) { for (var i = 0; i < b.length; i++) if (b[i]) return false; return true; }
  function concat(parts) {
    var n = 0; parts.forEach(function (p) { n += p.length; });
    var out = new Uint8Array(n), o = 0;
    parts.forEach(function (p) { out.set(p, o); o += p.length; });
    return out;
  }
  function le(words) {
    var b = new Uint8Array(4 * words.length), v = new DataView(b.buffer);
    words.forEach(function (w, i) { v.setUint32(4 * i, w >>> 0, true); });
    return b;
  }
  function be32(b, o) { return ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0; }
  function realSleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // (a, b): Fletcher sums over big-endian words, mod 2^32 (tools/l6ia.py fletcher_words)
  function fletcher(be) {
    var n = be.length >>> 2, a = 0, b = 0;
    for (var i = 0; i < n; i++) {
      var w = be32(be, 4 * i);
      a = (a + w) >>> 0;
      // b += w * (n - i), mod 2^32: split the product to stay exact in doubles
      var k = n - i, lo = (w & 0xFFFF) * k, hi = ((w >>> 16) * k) % 65536;
      b = (b + lo + hi * 65536) % 4294967296;
    }
    return [a >>> 0, b >>> 0];
  }
  function swap32(be) {
    var out = new Uint8Array(be.length);
    for (var i = 0; i + 3 < be.length; i += 4) { out[i] = be[i + 3]; out[i + 1] = be[i + 2]; out[i + 2] = be[i + 1]; out[i + 3] = be[i]; }
    return out;
  }

  // ---- the file (flash.py Firmware) ----
  function firmware(raw, inflate) {
    function tag(o) { return String.fromCharCode(raw[o], raw[o + 1], raw[o + 2], raw[o + 3]); }
    if (tag(0) !== "FORM" || tag(8) !== "L6FF") throw fail("file", "not an .hxf file");
    var pos = 12, head = null, data = null, dinf = [];
    while (pos + 8 <= raw.length) {
      var id = tag(pos), sz = be32(raw, pos + 4), body = raw.subarray(pos + 8, pos + 8 + sz);
      if (id === "HEAD") head = body; else if (id === "data") data = body;
      else if (id === "dinf") dinf.push([be32(body, 0), be32(body, 8), be32(body, 12)]);
      pos += 8 + sz + (sz & 1);
    }
    if (!head || !data) throw fail("file", "the .hxf has no HEAD or data");
    if (!eq(head.subarray(8, 12), PRODUCT_HEAD)) throw fail("file", "this firmware is for another Line 6 product, not the HX Effects");
    var payload = inflate(data);
    if (payload.length !== be32(head, 16)) throw fail("file", "the file is damaged (size)");
    var region = {};
    dinf.forEach(function (d) { region[d[0]] = payload.subarray(d[1], d[1] + d[2]); });
    var archive = region[0], app = region[5];
    if (!archive || !app || archive[0] !== 0x4C || archive[1] !== 0x36 || archive[2] !== 0x49 || archive[3] !== 0x41) {
      throw fail("file", "the file has no L6IA archive or updater app");
    }
    var count = be32(archive, 0x14), off = 0x18, entries = [];
    for (var n = 0; n < count; n++) {
      if (be32(archive, off + 4) !== 0x03800000) throw fail("file", "bad entry marker (entry " + n + ")");
      var e = { index: be32(archive, off), off: off, words: be32(archive, off + 0x10), h1: be32(archive, off + 0x14), h2: be32(archive, off + 0x18) };
      e.be = archive.subarray(off + 0x24, off + 0x24 + 4 * e.words);
      var f = fletcher(e.be);
      if (f[0] !== e.h1 || f[1] !== e.h2) throw fail("file", "entry " + e.index + " fails its Fletcher check: the file is damaged");
      entries.push(e);
      off += 0x24 + 4 * e.words;
    }
    return { archive: archive, app: app, entries: entries };
  }

  // ---- the message channel (flash.py Channel) over a WebUSB device, interface 0, bulk 0x01/0x81 ----
  // Several channels can share the endpoints (HX Edit opens one for requests, 0x1001-0x03ef service 2, and one for
  // notifications, 0x1002-0x03f0 service 4). link(a, b): b reads through a's reader; each message goes to the channel
  // whose unit port sent it, and pumping either keeps both acknowledged and heartbeating.
  function Channel(dev, o, hostPort, devPort) {
    this.dev = dev; this.o = o; this.hostPort = hostPort || HOST_PORT; this.devPort = devPort || DEV_PORT;
    this.io = this; this.siblings = []; this.inbox = [];
    this.seq = 0; this.rx = new Uint8Array(0); this.txBytes = 0; this.acked = 0; this.rxBytes = 0;
    this.lastTx = 0; this.closed = false; this.connected = false; this.hostBase = 0x1000; this.devBase = 0x200;
    this.queue = []; this.waiter = null; this.reading = false; this.dead = null;
  }
  Channel.prototype.raw = function (m) {
    var self = this;
    return this.dev.transferOut(1, m).then(function (r) {
      if (r.status !== "ok") throw fail("protocol", "USB write: " + r.status);
      self.lastTx = Date.now();
    });
  };
  Channel.prototype.write = function (kind, flags, payload) {
    payload = payload || new Uint8Array(0);
    var n = 8 + payload.length, m = new Uint8Array((16 + payload.length + 3) & ~3), v = new DataView(m.buffer);
    v.setUint16(0, n, true); m[2] = 0; m[3] = kind; v.setUint16(4, this.hostPort, true); v.setUint16(6, this.devPort, true);
    m[8] = 0; m[9] = this.seq & 0xFF; v.setUint16(10, flags, false);
    v.setUint32(12, (this.hostBase + this.rxBytes) >>> 0, true);
    m.set(payload, 16);
    this.seq++;
    return this.raw(m);
  };
  Channel.link = function (a, b) { b.io = a; a.siblings = [b]; b.siblings = [a]; };
  Channel.prototype.startReading = function () {
    if (this.io !== this) return this.io.startReading();
    var self = this;
    if (this.reading) return;
    this.reading = true;
    (function next() {
      if (!self.reading) return;
      self.dev.transferIn(1, 512).then(function (r) {
        if (r.data && r.data.byteLength) self.queue.push(new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength).slice());
        if (self.waiter) { var w = self.waiter; self.waiter = null; w(); }
        next();
      }, function (err) {
        self.reading = false; self.dead = err;
        if (self.waiter) { var w = self.waiter; self.waiter = null; w(); }
      });
    })();
  };
  Channel.prototype.nextIn = function (ms) {
    var self = this.io;                                 // the shared reader (itself unless linked)
    if (self.queue.length) return Promise.resolve(self.queue.shift());
    if (!self.reading) return Promise.resolve(null);
    return new Promise(function (resolve) {
      var done = false;
      function finish() { if (done) return; done = true; self.waiter = null; resolve(self.queue.length ? self.queue.shift() : null); }
      self.waiter = finish;
      self.o.sleep(ms).then(finish);
    });
  };
  Channel.prototype.pump = async function (ms) {
    var buf = await this.nextIn(ms);
    if (buf) {
      var v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength), o = 0;
      while (o + 16 <= buf.length) {
        var ln = v.getUint16(o, true), src = v.getUint16(o + 4, true);
        var msg = { kind: buf[o + 3], flags: v.getUint16(o + 10, false), ack: v.getUint32(o + 12, true), payload: buf.slice(o + 16, o + 8 + ln) };
        o += (8 + ln + 3) & ~3;
        var other = this.siblings.filter(function (c) { return c.devPort === src; })[0];
        (other || this).inbox.push(msg);
      }
    }
    await this.handle();
    for (var i = 0; i < this.siblings.length; i++) await this.siblings[i].handle();
  };
  Channel.prototype.handle = async function () {
    var msgs = this.inbox; this.inbox = [];
    for (var i = 0; i < msgs.length; i++) {
      var m = msgs[i];
      if (m.kind === 0x28) { this.devBase = new DataView(m.payload.buffer).getUint32(0, true); this.connected = true; continue; }
      if (m.kind !== 0x18) continue;
      this.acked = Math.max(this.acked, (m.ack - this.devBase) >>> 0);
      if (m.flags & 0x02) this.closed = true;
      if (m.payload.length) {
        this.rx = concat([this.rx, m.payload]);
        this.rxBytes += m.payload.length;
        await this.write(0x18, 0x08);
      }
    }
    if (!this.closed && this.connected && Date.now() - this.lastTx > HEARTBEAT) await this.write(0x18, 0x10);
  };
  Channel.prototype.open = async function () {
    this.startReading();
    if (this.io === this) while (await this.nextIn(100)) { /* purge anything stale */ }
    this.connected = false;
    var m = new Uint8Array(20), v = new DataView(m.buffer);
    v.setUint16(0, 0x0C, true); m[3] = 0x28; v.setUint16(4, this.hostPort, true); v.setUint16(6, this.devPort, true);
    m.set(h("000000020001002100100000"), 8);
    await this.raw(m);
    this.seq = 2;
    var end = Date.now() + 5000;
    while (!this.connected) {
      if (Date.now() > end) throw fail("protocol", "the unit did not answer the connect message");
      await this.pump(100);
    }
  };
  Channel.prototype.send = async function (data) {
    var o = 0, t = Date.now();
    while (o < data.length) {
      var n = Math.min(MAX_PAYLOAD, data.length - o);
      while (this.txBytes - this.acked + n > WINDOW) {
        if (Date.now() - t > 10000) throw fail("protocol", "the unit stopped acknowledging");
        if (this.io.dead) throw fail("gone", "the unit left USB");
        await this.pump(20);
      }
      await this.write(0x18, 0x04, data.subarray(o, o + n));
      this.txBytes += n; o += n; t = Date.now();
    }
  };
  Channel.prototype.recv = async function (n, seconds) {
    var end = Date.now() + 1000 * (seconds || 30);
    while (this.rx.length < n) {
      if (this.closed) throw fail("refused", "the unit closed the connection");
      if (this.io.dead) throw fail("gone", "the unit left USB");
      if (Date.now() > end) throw fail("protocol", "no reply from the unit");
      await this.pump(20);
    }
    var out = this.rx.slice(0, n);
    this.rx = this.rx.slice(n);
    return out;
  };
  Channel.prototype.close = async function () {
    try {
      if (!this.closed) {
        await this.write(0x18, 0x02);
        var end = Date.now() + 1000;
        while (!this.closed && Date.now() < end) await this.pump(50);
      }
    } catch (e) { /* it may be restarting */ }
    if (this.io === this) this.reading = false;
  };

  // ---- the update protocol (flash.py Commands), on any stream with send(bytes) and recv(n, seconds) ----
  function Commands(ch) { this.ch = ch; }
  Commands.prototype.cmd = async function (k, args, data, seconds) {
    await this.ch.send(concat([new Uint8Array([0xAA, 0, 0, k]), args || new Uint8Array(0), data || new Uint8Array(0)]));
    return this.ch.recv(REPLY_LEN[k], seconds || 30);
  };
  Commands.prototype.updateMode = async function () {
    await this.ch.send(PREAMBLE_UPDATE[0]);
    await this.ch.send(PREAMBLE_UPDATE[1]);
    var r = await this.ch.recv(PREAMBLE_UPDATE_REPLY.length);
    if (!eq(r, PREAMBLE_UPDATE_REPLY)) throw fail("protocol", "unexpected update-port handshake " + hex(r));
    r = await this.cmd(1);
    if (!eq(r, HELLO_REPLY)) throw fail("protocol", "unknown update protocol version " + hex(r));
    r = await this.cmd(3);
    if (!eq(r.subarray(4), INFO_TAIL)) throw fail("protocol", "unexpected device info " + hex(r));
    var nImages = new DataView(r.buffer, r.byteOffset).getUint32(0, true);
    r = await this.cmd(2);
    if (!zeros(r)) throw fail("refused", "the unit refused update mode (" + hex(r) + ")");
    return nImages;
  };
  Commands.prototype.imageStatus = async function (i) {
    var r = await this.cmd(4, le([i]));
    return new DataView(r.buffer, r.byteOffset).getUint32(0, true);
  };
  Commands.prototype.writeImage = async function (e, progress) {
    var r = await this.cmd(5, le([e.index, 0, e.words, e.h1, e.h2, 0, 0]));
    var v = new DataView(r.buffer, r.byteOffset);
    if (v.getUint32(0, true) !== 1 || v.getUint32(4, true) < CHUNK_WORDS) throw fail("refused", "image " + e.index + ": the unit refused it (" + hex(r) + ")");
    r = await this.cmd(6);
    if (!zeros(r)) throw fail("refused", "image " + e.index + ": start refused (" + hex(r) + ")");
    var nchunks = Math.ceil(e.words / CHUNK_WORDS);
    for (var k = 0; k < nchunks; k++) {
      var part = e.be.subarray(4 * CHUNK_WORDS * k, 4 * CHUNK_WORDS * (k + 1)), f = fletcher(part);
      r = await this.cmd(7, le([k, f[0], f[1], part.length / 4]), swap32(part));
      if (!zeros(r)) throw fail("refused", "image " + e.index + " chunk " + k + ": the unit reported " + hex(r));
      if (progress) progress(k + 1, nchunks);
    }
    r = await this.cmd(9, null, null, 60);
    if (!zeros(r)) throw fail("refused", "image " + e.index + ": the unit rejected it at the end (" + hex(r) + ")");
  };
  Commands.prototype.finish = async function () {
    var r = await this.cmd(10, le([1, 0]));
    if (!zeros(r)) throw fail("refused", "finish refused (" + hex(r) + ")");
  };

  // ---- devices ----
  async function present(o, filters, cls) {
    var list = await o.usb.getDevices();
    return list.filter(function (d) {
      return filters.some(function (f) { return d.vendorId === f.vendorId && d.productId === f.productId; }) &&
             (cls === undefined || d.deviceClass === cls);
    })[0] || null;
  }
  // the device for a stage: one already allowed, as soon as it comes up, or the one the person picks after clicking
  async function find(o, filters, cls, stage, seconds) {
    var clicked = false, end = Date.now() + seconds * 1000;
    o.ask(stage).then(function () { clicked = true; });
    for (;;) {
      var d = await present(o, filters, cls);
      if (d) { o.unask(); return d; }
      if (clicked) break;
      if (Date.now() > end) throw fail("gone", "the unit did not come back (" + stage + ")");
      await o.sleep(250);
    }
    try { return await o.usb.requestDevice({ filters: filters }); }
    catch (e) { throw fail("cancel", "no device chosen (" + stage + ")"); }
  }
  async function claim(dev) {
    await dev.open();
    if (!dev.configuration) await dev.selectConfiguration(1);
    try { await dev.claimInterface(0); }
    catch (e) { try { await dev.close(); } catch (e2) { /* closed */ } throw fail("busy", "cannot use the unit's USB connection: " + e.message); }
  }
  async function release(dev) {
    try { await dev.releaseInterface(0); } catch (e) { /* restarting */ }
    try { await dev.close(); } catch (e) { /* restarting */ }
  }

  async function enterDfu(dev, o) {
    o.stage("reboot");
    await claim(dev);
    var ch = new Channel(dev, o);
    try {
      await ch.open();
      var n = await new Commands(ch).updateMode();
      if (n !== 0) throw fail("protocol", "the main app reported " + n + " images; expected 0");
      await ch.close();
    } finally { ch.reading = false; await release(dev); }
    o.log("main app: restarting into the DFU loader\n");
  }

  async function dfuDownload(dev, app, o) {
    o.stage("dfu");
    await claim(dev);
    var setup = function (req, value) { return { requestType: "class", recipient: "interface", request: req, value: value, index: 0 }; };
    try {
      var nblocks = Math.ceil(app.length / DFU_BLOCK);
      for (var i = 0; i < nblocks; i++) {
        var r = await dev.controlTransferOut(setup(1, i), app.slice(DFU_BLOCK * i, DFU_BLOCK * (i + 1)));
        if (r.status !== "ok") throw fail("protocol", "DFU block " + i + ": " + r.status);
        var st = await dev.controlTransferIn(setup(3, 0), 6), s = new Uint8Array(st.data.buffer, st.data.byteOffset, 6);
        if (s[0] !== 0 || s[4] !== 5) throw fail("protocol", "DFU block " + i + ": status " + hex(s));
        var poll = s[1] | (s[2] << 8) | (s[3] << 16);
        if (poll) await o.sleep(poll);
        o.progress((i + 1) / nblocks);
      }
      try { await dev.controlTransferOut(setup(1, nblocks), new Uint8Array(0)); await dev.controlTransferIn(setup(3, 0), 6); }
      catch (e) { /* the loader starts the updater app and leaves USB */ }
    } finally { await release(dev); }
    o.log("DFU: updater app loaded (" + app.length + " bytes)\n");
  }

  async function writeArchive(dev, fw, o) {
    o.stage("write");
    await claim(dev);
    var ch = new Channel(dev, o);
    try {
      await ch.open();
      var c = new Commands(ch), n = await c.updateMode();
      if (n !== fw.entries.length) throw fail("protocol", "the unit has " + n + " image slots; the file has " + fw.entries.length);
      var bad = [];
      for (var i = 0; i < fw.entries.length; i++) {
        var s = await c.imageStatus(fw.entries[i].index);
        if (s !== 1) { bad.push(fw.entries[i].index); o.log("image " + fw.entries[i].index + ": status " + s + " on the unit\n"); }
      }
      var order = bad.concat(fw.entries.map(function (e) { return e.index; }).filter(function (x) { return bad.indexOf(x) < 0; }));
      var total = 0, done = 0, t0 = Date.now();
      fw.entries.forEach(function (e) { total += e.words; });
      for (var k = 0; k < order.length; k++) {
        var e = fw.entries.filter(function (x) { return x.index === order[k]; })[0];
        await c.writeImage(e, function (j, nj) { o.progress((done + Math.min(j * CHUNK_WORDS, e.words)) / total); });
        done += e.words;
        o.log("image " + e.index + ": " + (4 * e.words / 1e6).toFixed(2) + " MB written\n");
      }
      await c.finish();
      o.log("written in " + Math.round((Date.now() - t0) / 1000) + " s\n");
    } finally { ch.reading = false; await release(dev); }
  }

  async function deviceInfo(dev, o) {
    await claim(dev);
    var ch = new Channel(dev, o);
    try {
      await ch.open();
      await ch.send(PREAMBLE_INFO);
      var r = await ch.recv(32, 5);
      await ch.close();
      var p = r.subarray(8), name = "";
      for (var i = 1; i < 12 && p[i]; i++) name += String.fromCharCode(p[i]);
      return name;
    } finally { ch.reading = false; await release(dev); }
  }

  async function bootCheck(o, seconds) {
    o.stage("boot");
    var end = Date.now() + seconds * 1000;
    while (Date.now() < end) {
      var d = await present(o, MAIN, 0xEF);
      if (d) {
        await o.sleep(1000);
        try { if ((await deviceInfo(d, o)) === "F15Main") return true; } catch (e) { /* still starting */ }
      }
      await o.sleep(1000);
    }
    return false;
  }

  async function flash(o) {
    o.sleep = o.sleep || realSleep;
    o.log = o.log || function () {};
    o.progress = o.progress || function () {};
    o.stage = o.stage || function () {};
    o.unask = o.unask || function () {};
    var fw = firmware(o.hxf, o.inflate);
    o.log("file: " + fw.entries.length + " images, " + (fw.archive.length / 1e6).toFixed(1) + " MB, updater app " + fw.app.length + " bytes: checks OK\n");
    o.stage("pick");
    var dev = (await present(o, DFU)) || (await present(o, MAIN));
    if (!dev) {
      try { dev = await o.usb.requestDevice({ filters: MAIN.concat(DFU) }); }
      catch (e) { throw fail("cancel", "no device chosen"); }
    }
    var t0 = Date.now();
    if (dev.vendorId === VID && dev.deviceClass !== 0) {
      await enterDfu(dev, o);
      dev = await find(o, DFU, undefined, "dfu", 60);
    }
    if (dev.vendorId === DFU_VID) {
      await dfuDownload(dev, fw.app, o);
      dev = await find(o, MAIN, 0, "updater", 60);
    }
    await writeArchive(dev, fw, o);
    var ok = await bootCheck(o, 120);
    o.log((ok ? "BOOTED" : "BOOT FAILED") + " after " + Math.round((Date.now() - t0) / 1000) + " s\n");
    if (!ok) throw fail("boot", "the unit did not start its main app after the update");
  }

  // ---- User IR slots (tools/ir_upload.py): the same channel, service 2, old-spec msgpack requests ----
  // Request: [u16 1][u16 2][u32 n] {102: id, 100: op, 101: args}; answer {102: id, 103: status, 104: result}.
  // op 13 {101: 2}: the list [{112: index, 109: name, 104: MD5 hex}]; op 9: import {112: index, 113: the samples'
  // 32-bit words summed, 109: name, 114: 1, 115: 3, 123: false, 124: false, 125: 0, 110: samples}. The unit refuses
  // str8/bin (newer msgpack) and drops samples whose sum is wrong; it answers an import "working" (1), and the list
  // shows the samples' MD5 when it is done.
  function MpMap(pairs) { this.pairs = pairs; }
  function M() { return new MpMap(Array.prototype.slice.call(arguments)); }   // M([k, v], ...)
  function mpEncode(v) {
    var out = [];
    function u8(x) { out.push(x & 255); }
    function be(x, n) { for (var i = n - 1; i >= 0; i--) out.push(Math.floor(x / Math.pow(256, i)) & 255); }
    function enc(x) {
      if (x === null || x === undefined) u8(0xC0);
      else if (x === false) u8(0xC2);
      else if (x === true) u8(0xC3);
      else if (typeof x === "number") {
        if (x >= 0 && x < 128) u8(x); else if (x >= 0 && x < 256) { u8(0xCC); u8(x); }
        else if (x >= 0 && x < 65536) { u8(0xCD); be(x, 2); } else if (x >= 0 && x <= 0xFFFFFFFF) { u8(0xCE); be(x, 4); }
        else throw new Error("mpEncode: number " + x);
      } else if (x instanceof Uint8Array) {     // raw (old spec): fixraw, raw16, raw32
        if (x.length < 32) u8(0xA0 | x.length); else if (x.length < 65536) { u8(0xDA); be(x.length, 2); } else { u8(0xDB); be(x.length, 4); }
        for (var i = 0; i < x.length; i++) out.push(x[i]);
      } else if (x instanceof MpMap) {          // a map in the given key order (HX Edit's order)
        if (x.pairs.length < 16) u8(0x80 | x.pairs.length); else { u8(0xDE); be(x.pairs.length, 2); }
        x.pairs.forEach(function (p) { enc(p[0]); enc(p[1]); });
      } else throw new Error("mpEncode: " + typeof x);
    }
    enc(v);
    return new Uint8Array(out);
  }
  function mpDecode(b) {
    var o = 0, v = new DataView(b.buffer, b.byteOffset, b.byteLength);
    function str(n) { var r = b.slice(o, o + n); o += n; return r; }      // raw: names are decoded by txt(), samples stay bytes
    function arr(n) { var a = []; for (var i = 0; i < n; i++) a.push(dec()); return a; }
    function map(n) { var m = {}; for (var i = 0; i < n; i++) { var k = dec(); m[k] = dec(); } return m; }
    function dec() {
      var t = b[o++], r;
      if (t < 0x80) return t;
      if (t >= 0xE0) return t - 256;
      if ((t & 0xF0) === 0x80) return map(t & 15);
      if ((t & 0xF0) === 0x90) return arr(t & 15);
      if ((t & 0xE0) === 0xA0) return str(t & 31);
      switch (t) {
        case 0xC0: return null; case 0xC2: return false; case 0xC3: return true;
        case 0xC4: r = b[o]; o += 1; return b.slice(o, (o += r));
        case 0xC5: r = v.getUint16(o); o += 2; return b.slice(o, (o += r));
        case 0xC6: r = v.getUint32(o); o += 4; return b.slice(o, (o += r));
        case 0xCA: r = v.getFloat32(o); o += 4; return r;
        case 0xCB: r = v.getFloat64(o); o += 8; return r;
        case 0xCC: return b[o++];
        case 0xCD: r = v.getUint16(o); o += 2; return r;
        case 0xCE: r = v.getUint32(o); o += 4; return r;
        case 0xCF: r = v.getUint32(o) * 4294967296 + v.getUint32(o + 4); o += 8; return r;
        case 0xD0: return v.getInt8(o++);
        case 0xD1: r = v.getInt16(o); o += 2; return r;
        case 0xD2: r = v.getInt32(o); o += 4; return r;
        case 0xD9: r = b[o]; o += 1; return str(r);
        case 0xDA: r = v.getUint16(o); o += 2; return str(r);
        case 0xDB: r = v.getUint32(o); o += 4; return str(r);
        case 0xDC: r = v.getUint16(o); o += 2; return arr(r);
        case 0xDD: r = v.getUint32(o); o += 4; return arr(r);
        case 0xDE: r = v.getUint16(o); o += 2; return map(r);
        case 0xDF: r = v.getUint32(o); o += 4; return map(r);
      }
      throw new Error("mpDecode: type 0x" + t.toString(16));
    }
    return dec();
  }
  function wordSum(s) {
    var v = new DataView(s.buffer, s.byteOffset, s.byteLength), t = 0;
    for (var i = 0; i + 3 < s.length; i += 4) t = (t + v.getUint32(i, true)) % 4294967296;
    return t;
  }
  function txt(x) {          // a NUL-terminated string from the unit as text
    if (!(x instanceof Uint8Array)) return x == null ? "" : String(x);
    var n = x.indexOf(0); if (n < 0) n = x.length;
    var s = ""; for (var i = 0; i < n; i++) s += String.fromCharCode(x[i]);
    try { return decodeURIComponent(escape(s)); } catch (e) { return s; }
  }
  function utf8z(s) { var u = unescape(encodeURIComponent(s)), b = new Uint8Array(u.length + 1); for (var i = 0; i < u.length; i++) b[i] = u.charCodeAt(i); return b; }

  // The samples of a 48 kHz mono 32-bit float .wav (what nam2ir writes), or throws.
  function wavSamples(raw) {
    function tag(o) { return String.fromCharCode(raw[o], raw[o + 1], raw[o + 2], raw[o + 3]); }
    var v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    if (raw.length < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") throw fail("file", "not a .wav file");
    var pos = 12, fmt = null, data = null;
    while (pos + 8 <= raw.length) {
      var id = tag(pos), n = v.getUint32(pos + 4, true);
      if (id === "fmt ") fmt = [v.getUint16(pos + 8, true), v.getUint16(pos + 10, true), v.getUint32(pos + 12, true), v.getUint16(pos + 22, true)];
      else if (id === "data") data = raw.slice(pos + 8, pos + 8 + n);
      pos += 8 + n + (n & 1);
    }
    if (!fmt || !data) throw fail("file", "the .wav has no fmt or data chunk");
    if (fmt[0] !== 3 || fmt[1] !== 1 || fmt[2] !== 48000 || fmt[3] !== 32) throw fail("file", "only 48 kHz mono 32-bit float .wav files (as this page makes)");
    return data;
  }

  function Api(ch) { this.ch = ch; this.id = 1000; }
  Api.prototype.open = async function () {
    await this.ch.send(h("010002000100000002"));
    var r = await this.ch.recv(9, 10);
    if (r[0] || r[1]) throw fail("protocol", "unexpected service answer " + hex(r));
  };
  // typ 2: requests; typ 6: "live" requests (load, current preset). One id counter for both: the unit may answer a
  // type-6 request as type 2, so answers are matched by id (tools/preset_send.py).
  Api.prototype.request = async function (op, args, acceptWorking, typ) {
    var rid = this.id++, body = mpEncode(M([102, rid], [100, op], [101, args]));
    var head = new Uint8Array(8), v = new DataView(head.buffer);
    v.setUint16(0, 1, true); v.setUint16(2, typ || 2, true); v.setUint32(4, body.length, true);
    await this.ch.send(concat([head, body]));
    var end = Date.now() + 30000;
    while (Date.now() < end) {
      var hd = await this.ch.recv(8, 30), hv = new DataView(hd.buffer, hd.byteOffset, 8);
      var typ = hv.getUint16(2, true), n = hv.getUint32(4, true);
      var m = mpDecode(await this.ch.recv(n, 30));
      if (typ !== 4 && m && m[102] === rid) {       // type 2, or 10240 for a slot's samples
        if (m[103] === 1 && acceptWorking) return { status: 1 };
        if (m[103] === 1) continue;
        return { status: m[103], result: m[104] };
      }
      if (typ === 4 && m && m[106] && m[106][102] === rid) return { status: m[106][103], result: m[106][104] };
    }
    throw fail("protocol", "no answer to request " + op);
  };
  Api.prototype.list = async function () {
    var r = await this.request(13, M([101, 2]));
    if (r.status !== 0) throw fail("refused", "the unit refused the IR list (" + r.status + ")");
    return (r.result || []).map(function (e) {
      return { slot: e[112] + 1, name: txt(e[109]), md5: txt(e[104]) };
    });
  };
  // Write one slot and wait until the list shows these samples (md5: their MD5 as hex, from the caller).
  Api.prototype.put = async function (slot, samples, name, md5, sleep) {
    var r = await this.request(9, M([112, slot - 1], [113, wordSum(samples)], [109, utf8z(name)], [114, 1], [115, 3],
                                    [123, false], [124, false], [125, 0], [110, samples]), true);
    if (r.status !== 0 && r.status !== 1) throw fail("refused", "the unit refused slot " + slot + " (" + r.status + ")");
    var end = Date.now() + 30000;
    while (Date.now() < end) {
      var e = (await this.list()).filter(function (x) { return x.slot === slot; })[0];
      if (e && e.md5 === md5) return e;
      await sleep(500);
    }
    throw fail("refused", "slot " + slot + " did not end up holding the capture");
  };

  Api.prototype.has = async function (slot) {
    if (!(await this.list()).some(function (e) { return e.slot === slot && e.md5; })) throw fail("refused", "slot " + slot + " is empty");
  };
  Api.prototype.until = async function (slot, test, what, sleep) {
    var end = Date.now() + 30000;
    while (Date.now() < end) {
      var e = (await this.list()).filter(function (x) { return x.slot === slot; })[0];
      if (test(e)) return e;
      await sleep(300);
    }
    throw fail("refused", "slot " + slot + " was not " + what);
  };
  // op 10: rename (answers "working", then done)
  Api.prototype.rename = async function (slot, name, sleep) {
    await this.has(slot);
    var r = await this.request(10, M([112, slot - 1], [109, utf8z(name)]), true);
    if (r.status !== 0 && r.status !== 1) throw fail("refused", "the unit refused to rename slot " + slot);
    return this.until(slot, function (e) { return e && e.name === name; }, "renamed", sleep);
  };
  // op 15: delete (the unit never answers a samples request for an empty slot, so has() guards those)
  Api.prototype.remove = async function (slot, sleep) {
    var r = await this.request(15, M([112, slot - 1]));
    if (r.status !== 0) throw fail("refused", "the unit refused to clear slot " + slot);
    return this.until(slot, function (e) { return !e || !e.md5; }, "cleared", sleep);
  };
  // copy, as HX Edit does it: op 12 (name) + op 11 (samples) from one slot, op 9 into the other
  Api.prototype.copy = async function (src, dst, md5of, sleep) {
    await this.has(src);
    var info = await this.request(12, M([112, src - 1]));
    var data = await this.request(11, M([112, src - 1], [101, 2]));
    if (info.status !== 0 || data.status !== 0) throw fail("refused", "the unit refused to read slot " + src);
    var samples = data.result instanceof Uint8Array ? data.result : new Uint8Array(0);
    return this.put(dst, samples, txt(info.result[109]), md5of(samples), sleep);
  };

  // ---- presets (tools/preset_send.py; docs/hxedit-preset-format.md "On the wire") ----
  Api.prototype.presetList = async function () {
    var r = await this.request(1, M([107, 0], [101, 2]));
    if (r.status !== 0) throw fail("refused", "the unit refused the preset list (" + r.status + ")");
    return (r.result || []).map(function (e) {
      var k = Object.keys(e)[0];
      return { index: +k, name: txt(e[k][109]) };
    });
  };
  // the preset's blob, or null for an empty slot
  Api.prototype.presetRead = async function (n) {
    var r = await this.request(4, M([107, 0], [108, n], [101, 2]));
    if (r.status !== 0) throw fail("refused", "the unit refused to read preset " + n);
    return r.result instanceof Uint8Array ? r.result : null;
  };
  // write a blob into a slot (HX Edit brackets it with 255/254); the caller checks it by reading it back
  // Wait for the unit's "done" notification for request rid. Notifications come on their own connection (this.notes:
  // 0x1002-0x03f0, service 4), as HX Edit opens it; false if none came in time.
  Api.prototype.waitDone = async function (rid, ms) {
    var ch = this.notes || this.ch, end = Date.now() + ms;
    while (Date.now() < end) {
      if (ch.rx.length < 8) { await ch.pump(20); continue; }
      var hd = await ch.recv(8, 30), hv = new DataView(hd.buffer, hd.byteOffset, 8);
      var typ = hv.getUint16(2, true), m = mpDecode(await ch.recv(hv.getUint32(4, true), 30));
      if (typ === 4 && m && m[106] && m[106][102] === rid) return true;
    }
    return false;
  };
  Api.prototype.presetWrite = async function (n, blob, name, sleep) {
    await this.request(255, M());
    var r, rid;
    try {
      rid = this.id;
      r = await this.request(8, M([107, 0], [108, n], [109, utf8z(name)], [123, false], [124, false], [125, 0], [110, blob]), true);
      // 1 = "working": the unit stores the file after answering. HX Edit closes (254) only after the done
      // notification; closing at once left slots with a scrambled start (tools/preset_send.py, 2026-11-22).
      if (r.status === 1) this.lastDone = await this.waitDone(rid, 5000);
    }
    finally { await this.request(254, M()); }
    if (r.status !== 0 && r.status !== 1) throw fail("refused", "the unit refused to write preset " + n + " (" + r.status + ")");
    await sleep(500);
  };
  Api.prototype.presetLoad = async function (n) {
    var r = await this.request(20, M([107, 0], [108, n]), true, 6);
    if (r.status !== 0 && r.status !== 1) throw fail("refused", "the unit refused to load preset " + n);
  };
  Api.prototype.current = async function () {
    var r = await this.request(23, null, false, 6);
    if (r.status !== 0) throw fail("refused", "the unit refused the current preset");
    return { index: r.result[108], name: txt(r.result[109]) };
  };

  // irSession(o, fn): the running unit (the one the page may use, or the one picked), its API opened, fn(api) run.
  // o: { usb, log, sleep }. The browser asks for the device when none is allowed yet (needs a click).
  // One session at a time, and a short gap after the last one closed: a quick reconnect jammed the unit's USB
  // (tools/preset_send.py tests, 2026-11-22). A page may start one per click.
  var sessionQueue = Promise.resolve(), sessionEnd = 0, SESSION_GAP = 1500;
  function irSession(o, fn) {
    var run = sessionQueue.then(function () { return oneSession(o, fn); });
    sessionQueue = run.then(function () {}, function () {});
    return run;
  }
  async function oneSession(o, fn) {
    o.sleep = o.sleep || realSleep; o.log = o.log || function () {};
    var wait = sessionEnd + SESSION_GAP - Date.now();
    if (wait > 0) await realSleep(wait);
    var dev = await present(o, MAIN, 0xEF);
    if (!dev) {
      try { dev = await o.usb.requestDevice({ filters: MAIN }); }
      catch (e) { throw fail("cancel", "no device chosen"); }
    }
    if (dev.deviceClass === 0) throw fail("protocol", "the unit is in update mode: turn it off and on first");
    await claim(dev);
    // Two connections, as HX Edit opens them: requests (service 2) and notifications (service 4). Without the
    // notification connection the unit took only about 16 preset writes per power-on (tools/preset_send.py, 2026-11-22).
    var ch = new Channel(dev, o), notes = new Channel(dev, o, 0x1002, 0x03F0);
    Channel.link(ch, notes);
    try {
      await ch.open();
      await notes.open();
      await notes.send(h("010004000100000004"));
      var r = await notes.recv(9, 10);
      if (r[0] || r[1]) throw fail("protocol", "unexpected notification service answer " + hex(r));
      var api = new Api(ch);
      api.notes = notes;
      await api.open();
      return await fn(api);
    } finally {
      await notes.close();
      await ch.close();
      ch.reading = false;
      await release(dev);
      sessionEnd = Date.now();
    }
  }

  var api = { flash: flash, firmware: firmware, Commands: Commands, fletcher: fletcher, CODES: CODES, MAIN: MAIN, DFU: DFU,
              irSession: irSession, wavSamples: wavSamples, wordSum: wordSum, mpEncode: mpEncode, mpDecode: mpDecode, M: M };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FLASHER = api;
})(typeof self !== "undefined" ? self : this);
