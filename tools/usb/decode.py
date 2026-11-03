#!/usr/bin/env python3
"""Decode a usblog capture (tools/usb/capture.sh) of a Line 6 Updater session.

usage: decode.py usblog/<time>.txt [--raw] [--max N]

Bulk messages on endpoints 0x01 (host->device) / 0x81 (device->host), each:
    u16 len        bytes after the first 8 (header tail + payload), message padded to 4
    u8  0, u8 kind 0x28 connect, 0x18 stream
    u16 src, u16 dst       the host's port 0x1001, the device's 0x03ef
    u16 seq (BE)   per-sender message number
    u16 flags (BE) 0x02 connect/close, 0x04 data, 0x08 ack, 0x10 heartbeat
    u32 ack        payload bytes received from the peer so far (+ the peer's base)
    payload        len - 8 bytes
Payloads carry the update commands: b'\\xaa\\x00\\x00' + cmd byte, then u32 arguments.
DFU (control requests on the NXP ROM loader) is printed as-is.
"""
import collections
import re
import struct
import sys

LINE = re.compile(r'^(\S+) (\S+) (.*)$')


def records(path):
    """(t, kind, fields, data) for every log line."""
    with open(path) as f:
        for ln in f:
            m = LINE.match(ln.rstrip('\n'))
            if not m:
                continue
            t, op, rest = float(m.group(1)), m.group(2), m.group(3)
            data = b''
            if ' data=' in rest:
                rest, hx = rest.split(' data=', 1)
                data = bytes.fromhex(hx)
            kv = dict(x.split('=', 1) for x in rest.split() if '=' in x)
            yield t, op, kv, data


def split_msgs(buf):
    out, o = [], 0
    while o + 16 <= len(buf):
        ln = struct.unpack_from('<H', buf, o)[0]
        total = 8 + ln
        msg = buf[o:o + total]
        out.append(msg)
        o += (total + 3) & ~3
    return out, buf[o:]


def parse_msg(m):
    ln, z, kind, src, dst = struct.unpack_from('<HBBHH', m, 0)
    seq, flags = struct.unpack_from('>HH', m, 8)
    ack = struct.unpack_from('<I', m, 12)[0]
    return dict(len=ln, kind=kind, src=src, dst=dst, seq=seq, flags=flags, ack=ack, payload=m[16:8 + ln])


def events(path):
    """Bulk messages and DFU requests in time order."""
    for t, op, kv, data in records(path):
        if op == 'xfer_submit' and kv.get('ep') == '01' and data:
            for m in split_msgs(data)[0]:
                yield t, '>', parse_msg(m)
        elif op == 'xfer_done' and kv.get('ep') == '81' and data:
            for m in split_msgs(data)[0]:
                yield t, '<', parse_msg(m)
        elif op in ('ctrl_out', 'ctrl_ret'):
            yield t, op, dict(kv, data=data)
        elif op in ('open', 'close', 'reset'):
            yield t, op, kv


def main():
    path = sys.argv[1]
    raw = '--raw' in sys.argv
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 10 ** 9
    shown = 0
    chunk = collections.Counter()
    last_chunk = None
    for t, d, e in events(path):
        if d in ('open', 'close', 'reset'):
            print(f'{t:9.3f} {d} {e}')
            continue
        if d.startswith('ctrl'):
            dd = e['data']
            if d == 'ctrl_out' and e['rq'] == '01':
                chunk['dfu_dnload'] += 1
                if e['len'] != '2048' or chunk['dfu_dnload'] == 1:
                    print(f'{t:9.3f} DFU_DNLOAD block={int(e["v"], 16)} len={e["len"]}')
            elif d == 'ctrl_ret' and e['rq'] != '01':
                if raw or e['rq'] != '03':
                    print(f'{t:9.3f} ctrl rt={e["rt"]} rq={e["rq"]} v={e["v"]} r={e["r"]} {dd.hex()}')
            elif d == 'ctrl_out' and e['rq'] != '01':
                print(f'{t:9.3f} ctrl_out rt={e["rt"]} rq={e["rq"]} v={e["v"]} len={e["len"]} {dd[:32].hex()}')
            continue
        p = e['payload']
        is_chunk = p[:4] == b'\xaa\x00\x00\x07'
        if is_chunk and not raw:
            chunk['data'] += 1
            chunk['bytes'] += len(p)
            last_chunk = (t, p[:32].hex())
            continue
        if not p and not raw and e['flags'] in (0x08, 0x10):
            continue
        if chunk['data'] and not raw:
            print(f'          ... {chunk["data"]} data chunks, {chunk["bytes"]} payload bytes; last {last_chunk[1]}')
            chunk['data'] = chunk['bytes'] = 0
        print(f'{t:9.3f} {d} k={e["kind"]:02x} seq={e["seq"]:04x} fl={e["flags"]:02x} ack={e["ack"]:08x} '
              f'{len(p):4d} {p[:48].hex()}')
        shown += 1
        if shown >= mx:
            break


if __name__ == '__main__':
    main()
