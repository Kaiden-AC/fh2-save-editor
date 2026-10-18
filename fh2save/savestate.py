"""SaveState: an XML ``ObjectDictionary`` of ``<Object>`` / ``<Property>``.

We keep the original text and perform *targeted* edits so the exact formatting
(CRLF line endings, self-closing tags, attribute order) is preserved.
"""

from __future__ import annotations

import re

_OBJECT_TAG = re.compile(r'<Object\b[^>]*?>')


class Prop:
    __slots__ = ("name", "value")

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def display(self):
        return self.value


class SaveObject:
    def __init__(self, oid, otype, start, end):
        self.id = oid
        self.type = otype
        self.start = start
        self.end = end
        self.props: list = []

    def find(self, name):
        for p in self.props:
            if p.name == name:
                return p
        return None


class SaveState:
    def __init__(self, raw: bytes):
        self.raw = raw
        try:
            self.text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self.text = raw.decode("utf-8", "replace")
        self._parse()

    # ---- parsing -------------------------------------------------------
    def _parse(self):
        text = self.text
        self.objects: list = []
        pos = 0
        for m in _OBJECT_TAG.finditer(text):
            tag = m.group(0)
            if not tag.startswith("<Object "):
                continue
            idm = re.search(r'Id="([^"]*)"', tag)
            tm = re.search(r'Type="([^"]*)"', tag)
            if not idm or not tm:
                continue
            self_closing = tag.rstrip().endswith("/>")
            if self_closing:
                end = m.end()
            else:
                close = text.find("</Object>", m.end())
                end = close + len("</Object>") if close >= 0 else m.end()
            obj = SaveObject(idm.group(1), tm.group(1), m.start(), end)
            block = text[m.start():end]
            for pm in re.finditer(r'<Property\s+Name="([^"]*)"\s+Value="([^"]*)"', block):
                obj.props.append(Prop(pm.group(1), pm.group(2)))
            self.objects.append(obj)

    # ---- editing -------------------------------------------------------
    def _locate(self, obj_id):
        for o in self.objects:
            if o.id == obj_id:
                return o
        return None

    def set_property(self, obj_id, name, value) -> bool:
        obj = self._locate(obj_id)
        if obj is None:
            return False
        block = self.text[obj.start:obj.end]
        pat = re.compile(r'(<Property\s+Name="%s"\s+Value=")([^"]*)(")' % re.escape(name))
        if not pat.search(block):
            return False
        value_s = str(value).replace('"', "&quot;")
        new_block = pat.sub(lambda m: m.group(1) + value_s + m.group(3), block, count=1)
        self.text = self.text[:obj.start] + new_block + self.text[obj.end:]
        shift = len(new_block) - len(block)
        obj.end += shift
        for other in self.objects:
            if other.start > obj.start:
                other.start += shift
                other.end += shift
        p = obj.find(name)
        if p:
            p.value = value_s
        else:
            obj.props.append(Prop(name, value_s))
        return True

    def add_property(self, obj_id, name, value) -> bool:
        obj = self._locate(obj_id)
        if obj is None or obj.find(name) is not None:
            return False
        block = self.text[obj.start:obj.end]
        if not block.rstrip().endswith(">"):
            return False
        close = block.rfind("</Object>")
        if close < 0:
            return False
        indent_m = re.search(r'\n([ \t]*)<Property', block)
        indent = indent_m.group(1) if indent_m else "    "
        nl = "\r\n" if "\r\n" in block else "\n"
        prop = '%s<Property Name="%s" Value="%s"/>' % (indent, name, value)
        new_block = block[:close] + prop + nl + block[close:]
        self.text = self.text[:obj.start] + new_block + self.text[obj.end:]
        shift = len(new_block) - len(block)
        obj.end += shift
        for other in self.objects:
            if other.start > obj.start:
                other.start += shift
                other.end += shift
        obj.props.append(Prop(name, value))
        return True

    def serialize(self) -> bytes:
        return self.text.encode("utf-8")

    def __iter__(self):
        return iter(self.objects)

    def __len__(self):
        return len(self.objects)

    def find(self, obj_id):
        return self._locate(obj_id)
