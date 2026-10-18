"""ProfileData: the ``ssmc`` binary key/value profile.

Layout (all little-endian)::

    "ssmc"            4-byte magic
    u32  header_a     (observed 0x000033b3)
    u32  header_b     (observed 0x00000013)
    <records ...>
    <opaque trailing section, preserved verbatim>

Each record::

    u32  name_len
    char name[name_len]           ASCII, no NUL
    u8   0x20                     separator byte
    u32  reserved                 observed 0
    u32  type
    u8   value[...]               payload, size depends on type

Containers (type 0x0F) hold a child count as their value; the children simply
follow as subsequent records.
"""

from __future__ import annotations

import struct

MAGIC = b"ssmc"

# type tag -> (name, fixed size or None for dynamic)
TYPE_INFO = {
    0x00: ("bool", 1),
    0x01: ("enum8", 1),
    0x03: ("int32", 4),
    0x04: ("u64", 8),
    0x07: ("int32", 4),
    0x09: ("float", 4),
    0x0C: ("string", None),
    0x0F: ("container", 4),
}

# types whose value can be edited
EDITABLE = {0x00, 0x01, 0x03, 0x04, 0x07, 0x09, 0x0C}


def _is_name(data: bytes) -> bool:
    if not data:
        return False
    if not all(32 <= c < 127 for c in data):
        return False
    return any(chr(c).isalpha() for c in data)


class Prop:
    __slots__ = ("name", "type", "value")

    def __init__(self, name: str, type_: int, value: bytes):
        self.name = name
        self.type = type_
        self.value = value

    @property
    def type_name(self):
        return TYPE_INFO.get(self.type, ("unknown", 0))[0]

    def get(self):
        t, v = self.type, self.value
        if t in (0x00, 0x01):
            return v[0]
        if t in (0x03, 0x07):
            return struct.unpack("<i", v[:4])[0]
        if t == 0x04:
            return int.from_bytes(v[:8], "little", signed=False)
        if t == 0x09:
            return struct.unpack("<f", v[:4])[0]
        if t == 0x0C:
            if len(v) < 4:
                return ""
            count = struct.unpack("<I", v[:4])[0]
            return v[4:4 + count * 2].decode("utf-16-le", "replace")
        if t == 0x0F:
            return struct.unpack("<i", v[:4])[0]
        return v

    def set(self, new):
        t = self.type
        if t in (0x00, 0x01):
            self.value = struct.pack("<B", int(new) & 0xFF)
        elif t in (0x03, 0x07):
            self.value = struct.pack("<i", int(new))
        elif t == 0x04:
            self.value = int(new).to_bytes(8, "little", signed=False)
        elif t == 0x09:
            self.value = struct.pack("<f", float(new))
        elif t == 0x0C:
            s = str(new)
            raw = s.encode("utf-16-le")
            self.value = struct.pack("<I", len(s)) + raw
        else:
            raise ValueError("type %d is not editable" % t)

    def display(self):
        val = self.get()
        if self.type == 0x09:
            return "%.6g" % val
        if self.type == 0x04:
            return "0x%016x (%d)" % (val, val)
        if self.type == 0x0F:
            return "container(%d children)" % val
        if self.type == 0x0C:
            return repr(val)
        return str(val)


class ProfileData:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.header = (0, 0)
        self.props: list = []
        self.tail = b""
        self.parse()

    # ---- parsing -------------------------------------------------------
    def parse(self):
        raw = self.raw
        if raw[:4] != MAGIC:
            raise ValueError("ProfileData: bad magic %r" % raw[:4])
        self.header = struct.unpack("<II", raw[4:12])
        off = 12
        n = len(raw)
        props = []
        while off + 13 <= n:
            name_len = struct.unpack("<I", raw[off:off + 4])[0]
            if not (1 <= name_len <= 80):
                break
            name_bytes = raw[off + 4:off + 4 + name_len]
            if not _is_name(name_bytes):
                break
            p = off + 4 + name_len
            if raw[p:p + 1] != b"\x20":
                break
            if off + 4 + name_len + 1 + 4 + 4 > n:
                break
            _reserved = struct.unpack("<I", raw[p + 1:p + 5])[0]
            type_ = struct.unpack("<I", raw[p + 5:p + 9])[0]
            vstart = p + 9
            if type_ not in TYPE_INFO:
                break
            size = TYPE_INFO[type_][1]
            if size is None:  # string
                if vstart + 4 > n:
                    break
                count = struct.unpack("<I", raw[vstart:vstart + 4])[0]
                size = 4 + count * 2
            if vstart + size > n:
                break
            value = raw[vstart:vstart + size]
            props.append(Prop(name_bytes.decode("ascii"), type_, value))
            off = vstart + size
        self.props = props
        self.tail = raw[off:]

    # ---- serialising ---------------------------------------------------
    def serialize(self) -> bytes:
        out = bytearray()
        out += MAGIC
        out += struct.pack("<II", *self.header)
        for p in self.props:
            nb = p.name.encode("ascii")
            out += struct.pack("<I", len(nb))
            out += nb
            out += b"\x20"
            out += struct.pack("<I", 0)
            out += struct.pack("<I", p.type)
            out += p.value
        out += self.tail
        return bytes(out)

    # ---- access --------------------------------------------------------
    def find(self, name):
        for p in self.props:
            if p.name == name:
                return p
        return None

    def find_all(self, name):
        return [p for p in self.props if p.name == name]

    def __iter__(self):
        return iter(self.props)

    def __len__(self):
        return len(self.props)
