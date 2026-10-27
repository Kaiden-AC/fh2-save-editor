"""Forza Binary XML (BXML) reader/writer used by the FH3 save state.

Layout::

    "BXML"
    u8   version
    i32  string_count
    i32  string_table_size
    <string_count × (i16 len + bytes)>
    u8   flag
    node root (recursive)

Node::

    u8            flags        (1 = node, 2 = has attributes, 4 = has children)
    index         name
    if flags & 2:  u8 count, then count × (index key, index value)
    if flags & 4:  i16 count, then count × node

The string-table index width is 1, 2 or 4 bytes depending on the number of
strings.  Editing a value reuses an existing string when possible and appends
a new one otherwise; an unmodified document serialises back byte-for-byte.
"""

from __future__ import annotations

import struct

IDX_SIZE = {}


def _index_size(count: int) -> int:
    if count > 0xFFFF:
        return 4
    if count > 0xFF:
        return 2
    return 1


class BxmlError(Exception):
    pass


class BxmlNode:
    __slots__ = ("flags", "name_index", "attrs", "children")

    def __init__(self, flags=1, name_index=0, attrs=None, children=None):
        self.flags = flags
        self.name_index = name_index
        self.attrs = attrs if attrs is not None else []
        self.children = children if children is not None else []


class BxmlDocument:
    def __init__(self, data: bytes):
        if data[:4] != b"BXML":
            raise BxmlError("bad BXML magic")
        self.raw = data
        self.version = data[4]
        self.string_count = struct.unpack_from("<i", data, 5)[0]
        self.string_table_size = struct.unpack_from("<i", data, 9)[0]
        if self.string_count < 0 or self.string_table_size < 0:
            raise BxmlError("negative BXML string table size")
        pos = 13
        self.strings = []
        for _ in range(self.string_count):
            if pos + 2 > len(data):
                raise BxmlError("truncated BXML string table")
            length = struct.unpack_from("<h", data, pos)[0]
            pos += 2
            if length < 0 or pos + length > len(data):
                raise BxmlError("bad BXML string length")
            self.strings.append(data[pos:pos + length].decode("utf-8", "replace"))
            pos += length
        if pos != 13 + self.string_table_size:
            # Trust the explicit table size, but only when it points forward.
            end = 13 + self.string_table_size
            if not (13 < end <= len(data)):
                raise BxmlError("bad BXML string table size")
            pos = end
        self._index = {}
        for i, s in enumerate(self.strings):
            self._index.setdefault(s, i)
        if pos >= len(data):
            raise BxmlError("missing BXML flag byte")
        self.flag = data[pos]
        pos += 1
        self.idx_size = _index_size(len(self.strings))
        self.root, pos = self._read_node(data, pos, self.idx_size)
        self.end = pos

    def _read_index(self, data, pos, size):
        if size == 1:
            return data[pos], pos + 1
        if size == 2:
            return struct.unpack_from("<H", data, pos)[0], pos + 2
        return struct.unpack_from("<I", data, pos)[0], pos + 4

    def _read_node(self, data, pos, idx_size):
        if pos >= len(data):
            raise BxmlError("truncated BXML node")
        flags = data[pos]
        pos += 1
        name_index, pos = self._read_index(data, pos, idx_size)
        attrs = []
        if flags & 0x02:
            if pos >= len(data):
                raise BxmlError("truncated BXML attribute count")
            count = data[pos]
            pos += 1
            for _ in range(count):
                key, pos = self._read_index(data, pos, idx_size)
                value, pos = self._read_index(data, pos, idx_size)
                attrs.append((key, value))
        children = []
        if flags & 0x04:
            if pos + 2 > len(data):
                raise BxmlError("truncated BXML child count")
            count = struct.unpack_from("<h", data, pos)[0]
            pos += 2
            for _ in range(count):
                child, pos = self._read_node(data, pos, idx_size)
                children.append(child)
        return BxmlNode(flags, name_index, attrs, children), pos

    # ---- access --------------------------------------------------------
    def name(self, node: BxmlNode) -> str:
        if 0 <= node.name_index < len(self.strings):
            return self.strings[node.name_index]
        return ""

    def attr(self, node: BxmlNode, key: str, default=None):
        for k, v in node.attrs:
            if 0 <= k < len(self.strings) and self.strings[k] == key:
                return self.strings[v] if 0 <= v < len(self.strings) else default
        return default

    def set_attr(self, node: BxmlNode, key: str, value: str) -> None:
        """Set (or add) an attribute, appending strings when necessary."""
        key_index = self.add_string(key)
        value_index = self.add_string(value)
        for i, (k, _v) in enumerate(node.attrs):
            if 0 <= k < len(self.strings) and self.strings[k] == key:
                node.attrs[i] = (key_index, value_index)
                return
        node.attrs.append((key_index, value_index))
        node.flags |= 0x02

    def add_string(self, text: str) -> int:
        idx = self._index.get(text)
        if idx is not None:
            return idx
        idx = len(self.strings)
        self.strings.append(text)
        self._index[text] = idx
        return idx

    # ---- serialising ---------------------------------------------------
    def serialize(self) -> bytes:
        # Appending strings can in principle change the index width.  The FH3
        # save strings table is small, but handle it for correctness.
        idx_size = _index_size(len(self.strings))
        if idx_size != self.idx_size:
            raise BxmlError(
                "cannot grow the BXML string table past %d entries"
                % (0xFFFF if idx_size == 2 else 0xFF)
            )
        table = bytearray()
        for s in self.strings:
            raw = s.encode("utf-8")
            if len(raw) > 0x7FFF:
                raise BxmlError("BXML string is too long")
            table += struct.pack("<h", len(raw))
            table += raw
        out = bytearray(b"BXML")
        out.append(self.version & 0xFF)
        out += struct.pack("<i", len(self.strings))
        out += struct.pack("<i", len(table))
        out += table
        out.append(self.flag & 0xFF)
        out += self._write_node(self.root, idx_size)
        return bytes(out)

    def _write_index(self, value: int, idx_size: int) -> bytes:
        if idx_size == 1:
            return struct.pack("<B", value)
        if idx_size == 2:
            return struct.pack("<H", value)
        return struct.pack("<I", value)

    def _write_node(self, node: BxmlNode, idx_size: int) -> bytes:
        out = bytearray()
        flags = node.flags
        if node.attrs:
            flags |= 0x02
        out.append(flags & 0xFF)
        out += self._write_index(node.name_index, idx_size)
        if flags & 0x02:
            if len(node.attrs) > 0xFF:
                raise BxmlError("too many BXML attributes")
            out.append(len(node.attrs))
            for k, v in node.attrs:
                out += self._write_index(k, idx_size)
                out += self._write_index(v, idx_size)
        if flags & 0x04:
            if len(node.children) > 0x7FFF:
                raise BxmlError("too many BXML children")
            out += struct.pack("<h", len(node.children))
            for child in node.children:
                out += self._write_node(child, idx_size)
        return bytes(out)


# --------------------------------------------------------------------------
# FH3 save-state adapter (same shape as the FH2 SaveState model)
# --------------------------------------------------------------------------
class XmlProperty:
    __slots__ = ("_state", "_node", "name")

    def __init__(self, state, node, name):
        self._state = state
        self._node = node
        self.name = name

    @property
    def value(self):
        return self._state.doc.attr(self._node, "Value", "")

    @value.setter
    def value(self, text):
        self._state.doc.set_attr(self._node, "Value", str(text))

    def __repr__(self):
        return "XmlProperty(%s=%r)" % (self.name, self.value)


class XmlObject:
    __slots__ = ("_state", "id", "type", "props", "_node")

    def __init__(self, state, node):
        self._state = state
        self._node = node
        self.id = state.doc.attr(node, "Id", "")
        self.type = state.doc.attr(node, "Type", "")
        props = []
        for child in node.children:
            if state.doc.name(child) != "Property":
                continue
            name = state.doc.attr(child, "Name", "")
            props.append(XmlProperty(state, child, name))
        self.props = props

    def set_property(self, name, value):
        for prop in self.props:
            if prop.name == name:
                prop.value = str(value)
                return True
        return False

    def __repr__(self):
        return "XmlObject(%s [%s])" % (self.id, self.type)


class Fh3SaveState:
    """BXML ObjectDictionary with an FH2-compatible read/write surface."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.doc = BxmlDocument(raw)
        self.objects = []
        root = self.doc.root
        if self.doc.name(root) == "ObjectDictionary":
            for child in root.children:
                if self.doc.name(child) == "Object":
                    self.objects.append(XmlObject(self, child))

    def set_property(self, object_id, name, value) -> bool:
        for obj in self.objects:
            if obj.id == object_id:
                return obj.set_property(name, value)
        return False

    def serialize(self) -> bytes:
        return self.doc.serialize()

    def __len__(self):
        return len(self.objects)
