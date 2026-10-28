"""FH3 ``ProfileData`` container: property bag, BXML, binary state and SQLite.

The decrypted FH3 ProfileData is a sequence of four sections::

    u32 name_hash | u32 size | data

The four hashes are stable (they are the Forza ``CHashName`` of the section
name with seed 0x1505).  This module parses the ``profile`` property bag and
rebuilds the whole container, preserving every section byte-for-byte unless it
was explicitly modified.
"""

from __future__ import annotations

import struct

TYPE_NAMES = {
    0: "bool",
    1: "u8",
    2: "u16",
    3: "u32",
    4: "u64",
    5: "i8",
    6: "i16",
    7: "i32",
    8: "i64",
    9: "f32",
    10: "f64",
    11: "str",
    12: "wstr",
    13: "matrix",
    14: "vector",
    15: "bag",
    16: "dbbag",
    17: "u32obf",
}

# Types whose value can be edited through the generic editor.
EDITABLE_TYPES = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17}


def _hash_name(name: str, to_lower: bool = False, seed: int = 0x1505) -> int:
    for _ in range(2):
        for ch in name:
            c = ord(ch.lower()) if to_lower else ord(ch)
            seed = (seed ^ (c + (seed >> 2) + 32 * seed)) & 0xFFFFFFFF
    return seed


SECTION_HASHES = {
    _hash_name("profile"): "profile",
    _hash_name("savestate"): "savestate",
    _hash_name("binary"): "binary",
    _hash_name("database"): "database",
}
SECTION_ORDER = ("profile", "savestate", "binary", "database")

PROFILE_MAGIC = 0x4A8BF2B6


class Fh3ProfileError(Exception):
    pass


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise Fh3ProfileError("truncated profile data at 0x%x" % self.pos)
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self):
        return self.take(1)[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def i64(self):
        return struct.unpack("<q", self.take(8))[0]

    def f32(self):
        return struct.unpack("<f", self.take(4))[0]

    def f64(self):
        return struct.unpack("<d", self.take(8))[0]

    def string(self):
        n = self.i32()
        return self.take(n).decode("utf-8", "replace")

    def wstring(self):
        n = self.i32()
        return self.take(n * 2).decode("utf-16-le", "replace")


class Fh3Prop:
    """One property in a Forza property bag."""

    __slots__ = ("name", "type", "value", "cs", "bits", "path")

    def __init__(self, name, type_, value, cs=0, bits=32):
        self.name = name
        self.type = type_
        self.value = value
        self.cs = cs
        self.bits = bits
        self.path = name

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.type, "type%d" % self.type)

    @property
    def editable(self):
        return self.type in EDITABLE_TYPES

    @property
    def is_bag(self):
        return self.type in (15, 16)

    def get(self):
        return self.value

    def display(self):
        t = self.type
        v = self.value
        if t == 0:
            return "True" if v else "False"
        if t in (9, 10):
            return "%.6g" % v
        if t in (13, 14):
            return " ".join("%.6g" % x for x in v)
        if t in (11, 12):
            return repr(v)
        if t in (15, 16):
            return "%s(%d)" % (self.type_name, len(v))
        return str(v)

    def set(self, new):
        t = self.type
        if t == 0:
            self.value = bool(new)
        elif t in (1, 2, 3, 17):
            self.value = int(new) & 0xFFFFFFFF
            if t == 1:
                self.value &= 0xFF
            elif t == 2:
                self.value &= 0xFFFF
        elif t == 4:
            self.value = int(new) & 0xFFFFFFFFFFFFFFFF
        elif t in (5, 6, 7, 8):
            self.value = int(new)
        elif t in (9, 10):
            self.value = float(new)
        elif t in (11, 12):
            self.value = str(new)
        elif t in (13, 14):
            if isinstance(new, str):
                vals = [float(x) for x in new.replace(",", " ").split()]
            else:
                vals = [float(x) for x in new]
            need = 16 if t == 13 else 4
            if len(vals) != need:
                raise ValueError("%s needs %d numbers" % (self.type_name, need))
            self.value = vals
        else:
            raise ValueError("%s is not editable" % self.type_name)


def _read_value(r: _Reader, type_):
    if type_ == 0:
        return bool(r.u8())
    if type_ == 1:
        return r.u8()
    if type_ == 2:
        return struct.unpack("<H", r.take(2))[0]
    if type_ in (3, 17):
        return r.u32()
    if type_ == 4:
        return r.u64()
    if type_ == 5:
        return struct.unpack("<b", r.take(1))[0]
    if type_ == 6:
        return struct.unpack("<h", r.take(2))[0]
    if type_ == 7:
        return r.i32()
    if type_ == 8:
        return r.i64()
    if type_ == 9:
        return r.f32()
    if type_ == 10:
        return r.f64()
    if type_ == 11:
        return r.string()
    if type_ == 12:
        return r.wstring()
    if type_ == 13:
        return [r.f32() for _ in range(16)]
    if type_ == 14:
        return [r.f32() for _ in range(4)]
    if type_ in (15, 16):
        return _read_bag(r)
    raise Fh3ProfileError("unknown property type %d" % type_)


def _read_bag(r: _Reader):
    count = r.u32()
    if count > 1_000_000:
        raise Fh3ProfileError("implausible property count %d" % count)
    props = []
    for _ in range(count):
        cs = r.u8()
        bits = r.i32()
        name = r.string()
        type_ = r.i32()
        props.append(Fh3Prop(name, type_, _read_value(r, type_), cs, bits))
    return props


def _write_value(out: bytearray, prop: Fh3Prop):
    t = prop.type
    v = prop.value
    if t == 0:
        out.append(1 if v else 0)
    elif t == 1:
        out += struct.pack("<B", int(v) & 0xFF)
    elif t == 2:
        out += struct.pack("<H", int(v) & 0xFFFF)
    elif t in (3, 17):
        out += struct.pack("<I", int(v) & 0xFFFFFFFF)
    elif t == 4:
        out += struct.pack("<Q", int(v) & 0xFFFFFFFFFFFFFFFF)
    elif t == 5:
        out += struct.pack("<b", int(v))
    elif t == 6:
        out += struct.pack("<h", int(v))
    elif t == 7:
        out += struct.pack("<i", int(v))
    elif t == 8:
        out += struct.pack("<q", int(v))
    elif t == 9:
        out += struct.pack("<f", float(v))
    elif t == 10:
        out += struct.pack("<d", float(v))
    elif t == 11:
        raw = str(v).encode("utf-8")
        out += struct.pack("<i", len(raw)) + raw
    elif t == 12:
        raw = str(v).encode("utf-16-le")
        out += struct.pack("<i", len(raw) // 2) + raw
    elif t == 13:
        out += struct.pack("<16f", *[float(x) for x in v])
    elif t == 14:
        out += struct.pack("<4f", *[float(x) for x in v])
    elif t in (15, 16):
        _write_bag(out, v)
    else:
        raise Fh3ProfileError("cannot serialise property type %d" % t)


def _write_bag(out: bytearray, props):
    out += struct.pack("<I", len(props))
    for prop in props:
        name = prop.name.encode("utf-8")
        out.append(prop.cs & 0xFF)
        out += struct.pack("<i", prop.bits)
        out += struct.pack("<i", len(name)) + name
        out += struct.pack("<i", prop.type)
        _write_value(out, prop)


class Fh3Profile:
    """The ``profile`` property bag, flattened for the generic editor."""

    def __init__(self, section: bytes):
        self.raw = section
        r = _Reader(section)
        self.root = _read_bag(r)
        self.trailer = section[r.pos:]
        self.props = []
        self._flatten(self.root)

    def _flatten(self, props, prefix=""):
        for prop in props:
            prop.path = prefix + prop.name
            if prop.is_bag:
                self._flatten(prop.value, prop.path + "/")
            else:
                self.props.append(prop)

    def serialize(self) -> bytes:
        out = bytearray()
        _write_bag(out, self.root)
        out += self.trailer
        return bytes(out)

    def find(self, name):
        if "/" in name:
            for prop in self.props:
                if prop.path == name:
                    return prop
        for prop in self.props:
            if prop.name == name:
                return prop
        return None

    def find_all(self, name):
        return [p for p in self.props if p.name == name]

    def __iter__(self):
        return iter(self.props)

    def __len__(self):
        return len(self.props)


class Fh3BinaryObject:
    __slots__ = ("id", "type", "hash", "size", "data", "index")

    def __init__(self, ident, type_, hash_, data, index):
        self.id = ident
        self.type = type_
        self.hash = hash_
        self.data = data
        self.size = len(data)
        self.index = index


class Fh3BinaryState:
    """View of the FH3 ``binary`` section.

    Objects can be read and their ``data`` replaced.  ``serialize`` rebuilds
    the section, preserving object order, hashes, indices and any trailing
    bytes so an unmodified document round-trips byte-for-byte.
    """

    def __init__(self, raw: bytes):
        self.raw = raw
        self.objects = []
        pos = 0
        if len(raw) < 4:
            raise Fh3ProfileError("binary section is too short")
        count = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        if count > 1_000_000:
            raise Fh3ProfileError("implausible binary object count")
        for _ in range(count):
            ident, pos = self._read_string(raw, pos)
            type_, pos = self._read_string(raw, pos)
            if pos + 8 > len(raw):
                raise Fh3ProfileError("truncated binary object")
            hash_ = struct.unpack_from("<I", raw, pos)[0]
            size = struct.unpack_from("<I", raw, pos + 4)[0]
            pos += 8
            if pos + size + 4 > len(raw):
                raise Fh3ProfileError("truncated binary object data")
            data = raw[pos:pos + size]
            pos += size
            index = struct.unpack_from("<i", raw, pos)[0]
            pos += 4
            self.objects.append(Fh3BinaryObject(ident, type_, hash_, data, index))
        self.end = pos

    @staticmethod
    def _read_string(raw, pos):
        if pos + 4 > len(raw):
            raise Fh3ProfileError("truncated binary object header")
        n = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        if pos + n > len(raw):
            raise Fh3ProfileError("truncated binary object name")
        return raw[pos:pos + n].decode("utf-8", "replace"), pos + n

    def find(self, object_id):
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    def serialize(self) -> bytes:
        out = bytearray(struct.pack("<I", len(self.objects)))
        for obj in self.objects:
            for text in (obj.id, obj.type):
                encoded = text.encode("utf-8")
                out += struct.pack("<I", len(encoded))
                out += encoded
            out += struct.pack("<II", obj.hash & 0xFFFFFFFF, len(obj.data))
            out += obj.data
            out += struct.pack("<i", obj.index)
        # Preserve any bytes the parser did not consume (future-proofing).
        out += self.raw[self.end:]
        return bytes(out)

    def report(self) -> str:
        lines = [
            "FH3 BinarySaveState: %d objects, %d bytes"
            % (len(self.objects), len(self.raw)),
            "",
        ]
        for obj in self.objects:
            lines.append("%-50s [%s]  %d bytes" % (obj.id, obj.type, obj.size))
        return "\n".join(lines)

    def __len__(self):
        return len(self.objects)


class Fh3SaveData:
    """The four-section decrypted ``ProfileData`` container."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.sections = {}
        self.order = []
        pos = 0
        for _ in range(len(SECTION_ORDER)):
            if pos + 8 > len(raw):
                raise Fh3ProfileError("truncated section header")
            name_hash, size = struct.unpack_from("<II", raw, pos)
            pos += 8
            name = SECTION_HASHES.get(name_hash)
            if name is None:
                raise Fh3ProfileError("unknown section hash 0x%08x" % name_hash)
            data = raw[pos:pos + size]
            if len(data) != size:
                raise Fh3ProfileError("truncated section %s" % name)
            pos += size
            self.sections[name] = data
            self.order.append((name_hash, name))
        if pos != len(raw):
            raise Fh3ProfileError("trailing bytes after the last section")
        self.profile = Fh3Profile(self.sections["profile"])
        from .fh3bxml import Fh3SaveState

        self.savestate = Fh3SaveState(self.sections["savestate"])
        self.binary = Fh3BinaryState(self.sections["binary"])

    @property
    def database_raw(self) -> bytes:
        return self.sections["database"]

    def serialize(self, database=None) -> bytes:
        data = dict(self.sections)
        data["profile"] = self.profile.serialize()
        data["savestate"] = self.savestate.serialize()
        data["binary"] = self.binary.serialize()
        if database is not None:
            data["database"] = database.serialize()
        out = bytearray()
        for name_hash, name in self.order:
            section = data[name]
            out += struct.pack("<II", name_hash, len(section))
            out += section
        return bytes(out)
