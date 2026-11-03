#!/usr/bin/env python3
"""flash.py - flash an .hxf to the Line 6 HX Effects over USB, without Line 6 Updater,
then check that the unit boots back into its main app.

usage:
  python3 tools/flash.py info                    what the unit is running (read-only)
  python3 tools/flash.py flash <file.hxf> [-y]   flash it (asks first unless -y), then boot-check
  python3 tools/flash.py replay <file.hxf> <usblog.txt>
                                                 offline: run the update against a capture of
                                                 Line 6 Updater flashing the same file and check
                                                 every byte we would send matches what it sent

Close HX Edit and Line 6 Updater first: they hold the unit's USB interface.

The protocol was taken from a capture of Line 6 Updater 1.28 flashing 3.80.0 (tools/usb/):
  1. main app (0e41:4245, "F15Main"): open the update port, hello (cmd 01), info (03),
     cmd 02, close. The app restarts into the NXP ROM's USB DFU loader (1fc9:000c).
  2. DFU 1.1: the .hxf's second region (kind 5, the 83 KB updater app) in 2048-byte
     DNLOAD blocks, each followed by GETSTATUS, then a zero-length DNLOAD. It starts the
     updater app (0e41:4245, device class 0, "F15Updater").
  3. updater app: hello, info (14 images), cmd 02, image info (04) for each L6IA entry,
     then per entry: begin (05: id, words, Fletcher pair from the entry header), start (06),
     4096-word chunks (07: index, Fletcher pair of the chunk, words, little-endian data),
     end (09). Entries the unit reports damaged go first. Then finish (0a); it restarts.
  4. boot check: the unit comes back as 0e41:4245 class 0xef and its device-info port
     answers "F15Main".

Every message: 16-byte header (u16 length after 8, kind 0x28 connect / 0x18 stream, ports
0x1001 -> 0x03ef, u8 sequence, u16 flags 02 open/close 04 data 08 ack 10 heartbeat, u32
acknowledged byte count), then up to 496 payload bytes, padded to 4.
"""
import hashlib
import os
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import l6ia  # noqa: E402

VID, PID = 0x0e41, 0x4245
DFU_VID, DFU_PID = 0x1fc9, 0x000c
PRODUCT_HEAD = bytes.fromhex('00210005')        # .hxf HEAD bytes 8..12 for the HX Effects (midi id 0x210005)
HOST_PORT, DEV_PORT = 0x1001, 0x03ef
EP_OUT, EP_IN = 0x01, 0x81
MAX_PAYLOAD = 496                               # 512-byte transfers less the 16-byte header
WINDOW = 512                                    # unacknowledged bytes in flight (the Updater keeps about this)
HEARTBEAT = 1.0                                 # the unit times out after 4 s without a message
CHUNK_WORDS = 4096
DFU_BLOCK = 2048

PREAMBLE_UPDATE = (bytes.fromhex('000003000100000003'), bytes.fromhex('01000000020000000000'))
PREAMBLE_UPDATE_REPLY = bytes.fromhex('00000300020000000000')
PREAMBLE_INFO = bytes.fromhex('010005000100000005')
HELLO_REPLY = bytes.fromhex('01040404')
INFO_TAIL = bytes.fromhex('0300000001000000000000000200000000000000030000000100000000000000')
REPLY_LEN = {0x01: 4, 0x02: 4, 0x03: 36, 0x04: 28, 0x05: 60, 0x06: 4, 0x07: 8, 0x09: 4, 0x0a: 12}
# The updater app's image check (cmd 04): 1 = header and size fine, 4 = no header, 5 = the header's
# length is over the partition's declared size. Image 4 is always 5: its partition is declared 0x5000
# sectors (10 MiB) but stock 3.80.0's image 4 is already 12.4 MB; the physical gap to image 5 is 15.5 MiB.
IMAGE_STATUS = {1: 'ok', 4: 'no image', 5: 'over its declared partition size (normal for image 4, stock too)'}


class FlashError(RuntimeError):
    pass


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- the firmware file

class Firmware:
    """An .hxf: its L6IA archive (region kind 0) and the DFU updater app (kind 5), checked."""

    def __init__(self, path):
        raw = open(path, 'rb').read()
        if raw[:4] != b'FORM' or raw[8:12] != b'L6FF':
            raise FlashError(f'{path}: not an .hxf file')
        chunks, pos = {}, 12
        dinf = []
        while pos < len(raw):
            cid, sz = raw[pos:pos + 4], struct.unpack('>I', raw[pos + 4:pos + 8])[0]
            body = raw[pos + 8:pos + 8 + sz]
            if cid == b'dinf':
                dinf.append(struct.unpack('>IIII', body[:16]))
            else:
                chunks[cid] = body
            pos += 8 + sz + (sz & 1)
        head = chunks[b'HEAD']
        if head[8:12] != PRODUCT_HEAD:
            raise FlashError(f'{path}: built for product {head[8:12].hex()}, not the HX Effects ({PRODUCT_HEAD.hex()})')
        payload = zlib.decompress(chunks[b'data'])
        if hashlib.md5(payload).digest() != head[20:36] or len(payload) != struct.unpack('>I', head[16:20])[0]:
            raise FlashError(f'{path}: payload MD5/size does not match its header (damaged file)')
        regions = {k: payload[off:off + ln] for k, _, off, ln in dinf}
        self.archive, self.dfu_app = regions[0], regions[5]
        if self.archive[:4] != b'L6IA':
            raise FlashError(f'{path}: region 0 is not an L6IA archive')
        self.entries = l6ia.parse(self.archive)
        self.path, self.md5 = path, hashlib.md5(raw).hexdigest()
        for e in self.entries:                       # the unit checks these; catch a bad build here
            be = self.body_be(e)
            if l6ia.fletcher_words(be) != (e['h1'], e['h2']):
                raise FlashError(f'{path}: entry {e["index"]} fails its Fletcher check')

    def body_be(self, e):
        o = e['off'] + 0x24                          # sub-header + payload, big-endian words
        return self.archive[o:o + 4 * e['words']]


# --------------------------------------------------------------------------- the message channel

class Channel:
    """Line 6's reliable byte stream over bulk endpoints 0x01/0x81 (one port pair)."""

    def __init__(self, dev):
        self.dev = dev
        self.seq = 0
        self.rx = bytearray()
        self.tx_bytes = 0                              # payload bytes sent
        self.acked = 0                                 # of those, acknowledged by the unit
        self.rx_bytes = 0
        self.last_tx = 0.0
        self.closed = False
        self.connected = False
        self.host_base, self.dev_base = 0x1000, 0x200      # each side's announced base (connect payloads)

    # raw messages
    def _write(self, kind, flags, payload=b''):
        n = 8 + len(payload)
        ack = (self.host_base + self.rx_bytes) & 0xffffffff
        m = struct.pack('<HBBHH', n, 0, kind, HOST_PORT, DEV_PORT) + bytes([0, self.seq & 0xff]) + \
            struct.pack('>H', flags) + struct.pack('<I', ack) + payload
        m += b'\0' * (-len(m) % 4)
        self.dev.write(EP_OUT, m, timeout=5000)
        self.seq += 1
        self.last_tx = time.monotonic()

    def _read_once(self, timeout_ms):
        try:
            buf = bytes(self.dev.read(EP_IN, 512, timeout=timeout_ms))
        except Exception as ex:                         # usb.core.USBTimeoutError
            if 'timed out' in str(ex).lower() or 'timeout' in type(ex).__name__.lower():
                return []
            raise
        out, o = [], 0
        while o + 16 <= len(buf):
            ln, _, kind, src, dst = struct.unpack_from('<HBBHH', buf, o)
            flags = struct.unpack_from('>H', buf, o + 10)[0]
            ack = struct.unpack_from('<I', buf, o + 12)[0]
            out.append((kind, flags, ack, buf[o + 16:o + 8 + ln]))
            o += (8 + ln + 3) & ~3
        return out

    def _pump(self, timeout_ms=20):
        for kind, flags, ack, payload in self._read_once(timeout_ms):
            if kind == 0x28:
                self.dev_base = struct.unpack('<I', payload[:4])[0]
                self.connected = True
                continue
            if kind != 0x18:
                continue
            self.acked = max(self.acked, (ack - self.dev_base) & 0xffffffff)
            if flags & 0x02:
                self.closed = True
            if payload:
                self.rx += payload
                self.rx_bytes += len(payload)
                self._write(0x18, 0x08)               # acknowledge it
            elif flags & 0x10 and not self.closed:
                pass                                   # the unit's answer to our heartbeat
        if not self.closed and time.monotonic() - self.last_tx > HEARTBEAT:
            self._write(0x18, 0x10)

    # stream
    def open(self):
        while self._read_once(100):                    # purge anything stale
            pass
        self.connected = False
        m = struct.pack('<HBBHH', 0x0c, 0, 0x28, HOST_PORT, DEV_PORT) + bytes.fromhex('000000020001002100100000')
        self.dev.write(EP_OUT, m, timeout=5000)
        self.seq, self.last_tx = 2, time.monotonic()
        t = time.monotonic()
        while not self.connected:
            if time.monotonic() - t > 5:
                raise FlashError('the unit did not answer the connect message')
            self._pump(100)

    def send(self, data, timeout=10.0):
        o = 0
        t = time.monotonic()
        while o < len(data):
            n = min(MAX_PAYLOAD, len(data) - o)
            while self.tx_bytes - self.acked + n > WINDOW:
                if time.monotonic() - t > timeout:
                    raise FlashError(f'the unit stopped acknowledging ({self.tx_bytes - self.acked} bytes unacknowledged)')
                self._pump(20)
            self._write(0x18, 0x04, data[o:o + n])
            self.tx_bytes += n
            o += n
            t = time.monotonic()

    def recv(self, n, timeout=30.0):
        t = time.monotonic()
        while len(self.rx) < n:
            if self.closed:
                raise FlashError('the unit closed the connection')
            if time.monotonic() - t > timeout:
                raise FlashError(f'no reply from the unit within {timeout:.0f} s')
            self._pump(20)
        out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        return out

    def close(self):
        if not self.closed:
            try:
                self._write(0x18, 0x02)
                t = time.monotonic()
                while not self.closed and time.monotonic() - t < 1.0:
                    self._pump(50)
            except Exception:
                pass


class Commands:
    """The update protocol on top of a stream (a Channel, or the replay stand-in)."""

    def __init__(self, ch):
        self.ch = ch

    def cmd(self, k, args=b'', data=b'', timeout=30.0):
        self.ch.send(b'\xaa\x00\x00' + bytes([k]) + args + data)
        return self.ch.recv(REPLY_LEN[k], timeout)

    def update_mode(self):
        self.ch.send(PREAMBLE_UPDATE[0])
        self.ch.send(PREAMBLE_UPDATE[1])
        r = self.ch.recv(len(PREAMBLE_UPDATE_REPLY))
        if r != PREAMBLE_UPDATE_REPLY:
            raise FlashError(f'unexpected update-port handshake {r.hex()}')
        if (r := self.cmd(0x01)) != HELLO_REPLY:
            raise FlashError(f'unknown update protocol version {r.hex()} (expected {HELLO_REPLY.hex()})')
        r = self.cmd(0x03)
        if r[4:] != INFO_TAIL:
            raise FlashError(f'unexpected device info {r.hex()}')
        n_images = struct.unpack('<I', r[:4])[0]
        if (r := self.cmd(0x02)) != b'\0' * 4:
            raise FlashError(f'cmd 02 refused: {r.hex()}')
        return n_images

    def image_info(self, i):
        status, version, typ = struct.unpack('<3I', self.cmd(0x04, struct.pack('<I', i))[:12])
        return status, version, typ

    def write_image(self, fw, e, progress=None):
        be = fw.body_be(e)
        r = self.cmd(0x05, struct.pack('<7I', e['index'], 0, e['words'], e['h1'], e['h2'], 0, 0))
        w = struct.unpack('<15I', r)
        if w[0] != 1 or w[1] < CHUNK_WORDS:
            raise FlashError(f'image {e["index"]}: the unit refused the begin command ({r.hex()})')
        if (r := self.cmd(0x06)) != b'\0' * 4:
            raise FlashError(f'image {e["index"]}: start refused ({r.hex()})')
        nchunks = (e['words'] + CHUNK_WORDS - 1) // CHUNK_WORDS
        for k in range(nchunks):
            part = be[4 * CHUNK_WORDS * k: 4 * CHUNK_WORDS * (k + 1)]
            a, b = l6ia.fletcher_words(part)
            r = self.cmd(0x07, struct.pack('<4I', k, a, b, len(part) // 4), l6ia.swap32(part))
            if r != b'\0' * 8:
                raise FlashError(f'image {e["index"]} chunk {k}: the unit reported {r.hex()}')
            if progress:
                progress(k + 1, nchunks)
        if (r := self.cmd(0x09, timeout=60.0)) != b'\0' * 4:
            raise FlashError(f'image {e["index"]}: the unit rejected it at the end ({r.hex()})')

    def finish(self):
        r = self.cmd(0x0a, struct.pack('<2I', 1, 0))
        if r != b'\0' * 12:
            raise FlashError(f'finish refused ({r.hex()})')


# --------------------------------------------------------------------------- USB helpers

def backend():
    try:
        import libusb_package
        import usb.core  # noqa: F401
    except ImportError:
        raise SystemExit('needs pyusb and libusb-package: pip install pyusb libusb-package (in the .venv)')
    return libusb_package.get_libusb1_backend()


def find(vid, pid, dev_class=None):
    import usb.core
    for d in usb.core.find(find_all=True, idVendor=vid, idProduct=pid, backend=backend()):
        if dev_class is None or d.bDeviceClass == dev_class:
            return d
    return None


def wait_for(what, timeout, *specs):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        for spec in specs:
            d = find(*spec)
            if d is not None:
                return d, spec
        time.sleep(0.25)
    raise FlashError(f'the unit did not come back as {what} within {timeout:.0f} s')


def claim(d):
    import usb.util
    try:
        usb.util.claim_interface(d, 0)
    except Exception as ex:
        raise FlashError(f'cannot claim the unit\'s USB interface ({ex}). Is HX Edit or Line 6 Updater open?')


def release(d):
    import usb.util
    try:
        usb.util.release_interface(d, 0)
    except Exception:
        pass
    usb.util.dispose_resources(d)


def device_info(d):
    """(name, version) from the device-info port: ('F15Main', 0x03800020) or ('F15Updater', ...)."""
    claim(d)
    try:
        ch = Channel(d)
        ch.open()
        ch.send(PREAMBLE_INFO)
        r = ch.recv(32, timeout=5)
        ch.close()
    finally:
        release(d)
    p = r[8:]
    return p[1:12].split(b'\0')[0].decode('latin1'), struct.unpack('<I', p[16:20])[0]


def fmt_version(v):
    return f'{v >> 24:x}.{(v >> 16) & 0xff:02x}' if v >> 24 else f'0.{(v >> 16) & 0xff:02x}.{(v >> 8) & 0xff:x}{chr(0x60 + (v & 0xff)) if v & 0xff else ""}'


def which_mode():
    d = find(DFU_VID, DFU_PID)
    if d is not None:
        return 'dfu', d
    d = find(VID, PID)
    if d is None:
        return None, None
    return ('updater' if d.bDeviceClass == 0 else 'main'), d


# --------------------------------------------------------------------------- the update

def enter_dfu(d):
    log('[1/4] main app: asking it to restart into its DFU loader')
    claim(d)
    try:
        ch = Channel(d)
        ch.open()
        n = Commands(ch).update_mode()
        if n != 0:
            raise FlashError(f'the main app reported {n} images; expected 0 (is this really the main app?)')
        ch.close()
    finally:
        release(d)
    d, _ = wait_for('its DFU loader', 30, (DFU_VID, DFU_PID))
    return d


def dfu_download(d, app):
    log(f'[2/4] DFU: loading the updater app ({len(app)} bytes)')
    claim(d)
    try:
        nblocks = (len(app) + DFU_BLOCK - 1) // DFU_BLOCK
        for i in range(nblocks):
            d.ctrl_transfer(0x21, 1, i, 0, app[DFU_BLOCK * i: DFU_BLOCK * (i + 1)], timeout=5000)
            st = bytes(d.ctrl_transfer(0xa1, 3, 0, 0, 6, timeout=5000))
            if st[0] != 0 or st[4] != 5:
                raise FlashError(f'DFU block {i}: status {st.hex()} (expected status 0, state dfuDNLOAD-IDLE)')
            poll = st[1] | st[2] << 8 | st[3] << 16
            if poll:
                time.sleep(poll / 1000)
        try:                                           # end of download: the loader starts the app and detaches
            d.ctrl_transfer(0x21, 1, nblocks, 0, None, timeout=5000)
            d.ctrl_transfer(0xa1, 3, 0, 0, 6, timeout=2000)
        except Exception:
            pass
    finally:
        release(d)
    d, _ = wait_for('the updater app', 30, (VID, PID, 0))
    return d


def write_archive(d, fw):
    log('[3/4] updater app: writing the firmware')
    claim(d)
    try:
        ch = Channel(d)
        ch.open()
        c = Commands(ch)
        n = c.update_mode()
        if n != len(fw.entries):
            raise FlashError(f'the updater app has {n} image slots; the file has {len(fw.entries)} images')
        bad = []
        for e in fw.entries:
            status, version, typ = c.image_info(e['index'])
            if status != 1:
                bad.append(e['index'])
                log(f'      image {e["index"]}: {IMAGE_STATUS.get(status, f"status {status}")} on the unit')
        order = bad + [e['index'] for e in fw.entries if e['index'] not in bad]
        total = sum(e['words'] for e in fw.entries)
        done = [0]
        t0 = time.monotonic()
        for i in order:
            e = fw.entries[i]

            def progress(k, n, e=e):
                w = done[0] + min(k * CHUNK_WORDS, e['words'])
                if k == n or k % 16 == 0:
                    pct = 100 * w / total
                    rate = 4 * w / max(time.monotonic() - t0, 1e-3) / 1e3
                    print(f'\r      image {i:2d} ({e["words"] * 4 / 1e6:6.2f} MB)  {pct:5.1f}%  {rate:5.0f} kB/s', end='', flush=True)
            c.write_image(fw, e, progress)
            done[0] += e['words']
        print()
        c.finish()
    finally:
        release(d)
    log(f'      written in {time.monotonic() - t0:.0f} s')


def boot_check(timeout=120):
    log('[4/4] waiting for the unit to boot')
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        mode, d = which_mode()
        if mode == 'main':
            time.sleep(1.0)
            try:
                name, ver = device_info(d)
            except Exception:
                time.sleep(1.0)
                continue
            if name == 'F15Main':
                return True, f'main app {name} v{fmt_version(ver)} after {time.monotonic() - t:.0f} s'
            return False, f'answered as {name}'
        time.sleep(0.5)
    mode, _ = which_mode()
    return False, f'no main app after {timeout} s (the unit is {"not on USB" if mode is None else "in " + mode + " mode"})'


def flash(path, yes=False):
    fw = Firmware(path)
    log(f'{os.path.basename(path)}: md5 {fw.md5}, {len(fw.entries)} images, '
        f'{len(fw.archive) / 1e6:.1f} MB, updater app {len(fw.dfu_app)} bytes: file checks OK')
    mode, d = which_mode()
    if mode is None:
        raise FlashError('no HX Effects on USB')
    log(f'the unit is in {mode} mode')
    if not yes:
        if input('Flash it? Type "flash" to go on: ').strip() != 'flash':
            raise SystemExit('not flashed')
    t0 = time.monotonic()
    if mode == 'main':
        d = enter_dfu(d)
        mode = 'dfu'
    if mode == 'dfu':
        d = dfu_download(d, fw.dfu_app)
    write_archive(d, fw)
    ok, msg = boot_check()
    log(f'{"BOOTED" if ok else "BOOT FAILED"}: {msg}; {time.monotonic() - t0:.0f} s in all')
    if not ok:
        log('Recovery: hold > while powering on, then flash the stock .hxf (this tool or Line 6 Updater).')
    return ok


# --------------------------------------------------------------------------- replay (offline check)

def replay(path, logpath):
    """Run phase 3 against the device side of a capture; compare our stream with the Updater's."""
    sys.path.insert(0, os.path.join(HERE, 'usb'))
    import decode
    fw = Firmware(path)
    conns, cur = [], None
    for t, d, e in decode.events(logpath):
        if d not in ('>', '<'):
            continue
        if e['kind'] == 0x28 and d == '>':
            cur = dict(h=bytearray(), d=bytearray())
            conns.append(cur)
        elif cur is not None and e['kind'] == 0x18 and e['payload']:
            cur['h' if d == '>' else 'd'] += e['payload']
    upd = max(conns, key=lambda c: len(c['h']))
    main = next(c for c in conns if c['h'].startswith(PREAMBLE_UPDATE[0]) and c is not upd)

    class Fake:
        def __init__(self, dev_stream):
            self.dev, self.sent = bytes(dev_stream), bytearray()

        def send(self, data, timeout=0):
            self.sent += data

        def recv(self, n, timeout=0):
            out, self.dev = self.dev[:n], self.dev[n:]
            if len(out) < n:
                raise FlashError('the capture ran out of replies')
            return out

    ok = True
    f = Fake(main['d'])                                 # phase 1
    Commands(f).update_mode()
    same = bytes(f.sent) == bytes(main['h'])
    log(f'phase 1 (main app): {len(f.sent)} bytes, {"identical" if same else "DIFFERENT"}')
    ok &= same

    blocks = {}                                         # phase 2
    for t, op, kv, data in decode.records(logpath):
        if op == 'ctrl_out' and kv['rq'] == '01':
            blocks[int(kv['v'], 16)] = data
    sent = b''.join(blocks[i] for i in sorted(blocks))
    n = (len(fw.dfu_app) + DFU_BLOCK - 1) // DFU_BLOCK
    same = sent == fw.dfu_app and sorted(blocks) == list(range(n + 1)) and blocks[n] == b''
    log(f'phase 2 (DFU): {len(blocks)} blocks, {"identical" if same else "DIFFERENT"}')
    ok &= same

    f = Fake(upd['d'])                                  # phase 3
    c = Commands(f)
    c.update_mode()
    bad = [e['index'] for e in fw.entries if c.image_info(e['index'])[0] != 1]
    for i in bad + [e['index'] for e in fw.entries if e['index'] not in bad]:
        c.write_image(fw, fw.entries[i])
    c.finish()
    same = bytes(f.sent) == bytes(upd['h'])
    if not same:
        k = next((i for i, (a, b) in enumerate(zip(f.sent, upd['h'])) if a != b), min(len(f.sent), len(upd['h'])))
        log(f'  first difference at byte {k}: ours {bytes(f.sent[k:k + 16]).hex()} / Updater {bytes(upd["h"][k:k + 16]).hex()}')
    log(f'phase 3 (updater app): {len(f.sent)} bytes vs {len(upd["h"])}, damaged-first order {bad}: '
        f'{"identical" if same else "DIFFERENT"}; device replies left over: {len(f.dev)}')
    ok &= same and not f.dev
    log('REPLAY MATCHES' if ok else 'REPLAY DIFFERS')
    return ok


def main():
    a = sys.argv[1:]
    try:
        if a[:1] == ['info']:
            mode, d = which_mode()
            if mode is None:
                raise FlashError('no HX Effects on USB')
            if mode == 'dfu':
                log('the unit is in its DFU loader (1fc9:000c)')
                return
            name, ver = device_info(d)
            log(f'{mode} mode: {name} v{fmt_version(ver)} ({ver:#010x})')
        elif a[:1] == ['flash'] and len(a) >= 2:
            sys.exit(0 if flash(a[1], yes='-y' in a) else 1)
        elif a[:1] == ['replay'] and len(a) >= 3:
            sys.exit(0 if replay(a[1], a[2]) else 1)
        else:
            sys.exit(__doc__)
    except FlashError as ex:
        sys.exit(f'flash.py: {ex}')


if __name__ == '__main__':
    main()
