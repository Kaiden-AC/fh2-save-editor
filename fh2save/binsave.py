"""BinarySaveState: the binary sibling of SaveState.

This blob uses absolute offset pointers, so edits that change its size would
break it.  The editor therefore treats it as **read-only** and offers:
  * a list of the serialised objects (id + type),
  * extraction of human-readable strings (UTF-16 gamertags + ASCII),
  * a raw hex viewer.
"""

from __future__ import annotations

import re
import struct


def _read_u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def scan_objects(data: bytes) -> list:
    """Find length-prefixed ``id``+``type`` string pairs."""
    out = []
    n = len(data)
    off = 0
    while off + 8 <= n:
        ln = _read_u32(data, off)
        if 1 <= ln <= 64 and off + 4 + ln + 4 <= n:
            name = data[off + 4:off + 4 + ln]
            if all(32 <= c < 127 for c in name):
                tpos = off + 4 + ln
                tln = _read_u32(data, tpos)
                if 1 <= tln <= 64 and tpos + 4 + tln <= n:
                    tname = data[tpos + 4:tpos + 4 + tln]
                    if all(32 <= c < 127 for c in tname):
                        out.append((off, name.decode("ascii"), tname.decode("ascii")))
                        off = tpos + 4 + tln
                        continue
        off += 1
    return out


def utf16_strings(data: bytes, minlen=4) -> list:
    out = []
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, data):
        out.append((m.start(), m.group().decode("utf-16-le")))
    return out


def ascii_strings(data: bytes, minlen=6) -> list:
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        out.append((m.start(), m.group().decode("ascii")))
    return out


class BinSave:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.objects = scan_objects(raw)

    def __len__(self):
        return len(self.raw)

    def summary(self) -> list:
        return [(o, i, t) for (o, i, t) in self.objects]

    def gamertags(self) -> list:
        return [s for (_, s) in utf16_strings(self.raw, 3)]

    def report(self) -> str:
        lines = ["BinarySaveState  (%d bytes)" % len(self.raw), ""]
        lines.append("Objects (%d):" % len(self.objects))
        for off, oid, otype in self.objects:
            lines.append("  0x%06x  %-34s %s" % (off, oid, otype))
        tags = self.gamertags()
        if tags:
            lines.append("")
            lines.append("UTF-16 strings / gamertags (%d):" % len(tags))
            for s in tags:
                lines.append("  %s" % s)
        return "\n".join(lines)

    def hexdump(self, start=0, length=512) -> str:
        data = self.raw
        out = []
        start = max(0, min(start, max(0, len(data) - 1)))
        end = min(len(data), start + length)
        for i in range(start, end, 16):
            chunk = data[i:i + 16]
            hexs = " ".join("%02x" % b for b in chunk)
            ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            out.append("%08x  %-47s  %s" % (i, hexs, ascii_))
        return "\n".join(out)
