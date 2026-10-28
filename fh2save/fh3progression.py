"""Edit the authoritative FH3 progression state.

FH3 stores career, bucket-list, discovery and festival progress in the binary
``BinarySaveState`` section and in the profile's ``Stats``/``CompareStats``
property bags -- not in the SQLite tables.  The table rows that older versions
of this editor inserted were ignored by the game.

The reference identifiers and completed values in ``data/fh3_progress.json``
were derived from a genuine, largely-completed FH3 save.  They contain only
game-internal event/challenge identifiers, names and counter values; no account
data.  See ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

_DATA = None
_DATA_ERROR = None

# Profile values that belong to the money/XP actions and must not be replaced
# by the reference snapshot.
_PROFILE_SKIP = {
    "Main/Credits",
    "Main/TotalCredits",
    "Main/TotalWinnings",
    "Main/OnlineWinnings",
    "Main/XP",
    "Main/TotalXP",
    "Main/Level",
    "Main/LastRewardedLevel",
    "Main/WristbandLevel",
    "Main/NumSkillTokens",
}


class Fh3ProgressionError(Exception):
    pass


def _data():
    global _DATA, _DATA_ERROR
    if _DATA is None and _DATA_ERROR is None:
        path = Path(__file__).with_name("data") / "fh3_progress.json"
        try:
            _DATA = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _DATA_ERROR = "FH3 progression data is unavailable: %s" % exc
    if _DATA is None:
        raise Fh3ProgressionError(_DATA_ERROR)
    return _DATA


# --------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------
def _binary_object(doc, object_id):
    state = getattr(doc, "binsave", None)
    if state is None or not hasattr(state, "objects"):
        return None
    return state.find(object_id)


def _replace(doc, object_id, data: bytes) -> bool:
    obj = _binary_object(doc, object_id)
    if obj is None:
        return False
    obj.data = data
    obj.size = len(data)
    if hasattr(doc, "invalidate"):
        doc.invalidate()
    return True


def _cstring(data: bytes, pos: int):
    length = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    return data[pos:pos + length].decode("utf-8", "replace"), pos + length


# --------------------------------------------------------------------------
# Bucket lists
# --------------------------------------------------------------------------
def _parse_bucket(data: bytes):
    if len(data) < 8:
        raise Fh3ProgressionError("BucketListChallengeState is truncated")
    version, count = struct.unpack_from("<II", data, 0)
    if version not in (1, 2) or count > 10000 or 8 + count * 14 > len(data):
        raise Fh3ProgressionError("BucketListChallengeState has an unknown layout")
    pos = 8
    records = []
    for _ in range(count):
        challenge_id, unknown = struct.unpack_from("<II", data, pos)
        pos += 8
        flags = list(data[pos:pos + 6])
        pos += 6
        records.append([challenge_id, unknown, flags])
    return version, records, data[pos:]


def _write_bucket(version, records, tail) -> bytes:
    out = bytearray(struct.pack("<II", version, len(records)))
    for challenge_id, unknown, flags in records:
        out += struct.pack("<II", challenge_id, unknown)
        out += bytes((flags + [0] * 6)[:6])
    out += tail
    return bytes(out)


def _complete_bucket_state(doc, completed: bool) -> int:
    obj = _binary_object(doc, "BucketListChallengeState")
    if obj is None:
        return 0
    version, records, tail = _parse_bucket(obj.data)
    by_id = {record[0]: record for record in records}
    wanted = [1, 1, 1, 0, 0, 1] if completed else [0, 1, 1, 0, 0, 1]
    touched = 0
    for challenge_id, unknown, _flags in _data()["bucket"]:
        if challenge_id == 0xFFFFFFFF:
            continue
        record = by_id.get(challenge_id)
        if record is None:
            record = [challenge_id, unknown, wanted[:]]
            records.append(record)
            by_id[challenge_id] = record
        if completed:
            record[2] = wanted[:]
        else:
            # Only mark discovered/attempted and keep any existing completion.
            record[2] = [max(a, b) for a, b in zip(record[2], wanted)]
        touched += 1
    _replace(doc, "BucketListChallengeState",
             _write_bucket(version, records, tail))
    return touched


def complete_bucket_lists(doc) -> int:
    return _complete_bucket_state(doc, completed=True)


def discover_bucket_lists(doc) -> int:
    return _complete_bucket_state(doc, completed=False)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def _parse_discovery(data: bytes):
    if len(data) < 8:
        raise Fh3ProgressionError("DiscoveryState is truncated")
    version, count = struct.unpack_from("<II", data, 0)
    if version not in (1, 2) or count > 100000:
        raise Fh3ProgressionError("DiscoveryState has an unknown layout")
    pos = 8
    entries = []
    for _ in range(count):
        if pos + 10 > len(data):
            raise Fh3ProgressionError("DiscoveryState is truncated")
        flags, name_hash, length = struct.unpack_from("<HII", data, pos)
        pos += 10
        if pos + length + 1 > len(data):
            raise Fh3ProgressionError("DiscoveryState has a bad name length")
        name = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        value = data[pos]
        pos += 1
        entries.append([flags, name_hash, name, value])
    return version, entries, data[pos:]


def _write_discovery(version, entries, tail) -> bytes:
    out = bytearray(struct.pack("<II", version, len(entries)))
    for flags, name_hash, name, value in entries:
        encoded = name.encode("utf-8")
        out += struct.pack("<HII", flags, name_hash, len(encoded))
        out += encoded
        out += bytes((value & 0xFF,))
    out += tail
    return bytes(out)


def discover_everything(doc) -> int:
    obj = _binary_object(doc, "DiscoveryState")
    if obj is None:
        return 0
    version, entries, tail = _parse_discovery(obj.data)
    known = {entry[2] for entry in entries}
    added = 0
    for name, name_hash in _data()["discovery"]:
        if name in known:
            entry = next(e for e in entries if e[2] == name)
            entry[3] = 1
            continue
        entries.append([1, name_hash, name, 1])
        known.add(name)
        added += 1
    _replace(doc, "DiscoveryState", _write_discovery(version, entries, tail))
    return added


# --------------------------------------------------------------------------
# Career / event results
# --------------------------------------------------------------------------
def _parse_career(data: bytes):
    if len(data) < 36 or len(data) % 4:
        raise Fh3ProgressionError("CareerState is truncated")
    count = len(data) // 4
    values = list(struct.unpack_from("<%dI" % count, data, 0))
    if values[0] not in (1, 2):
        raise Fh3ProgressionError("CareerState has an unknown version")
    pos = 1

    def take(width):
        nonlocal pos
        if pos >= len(values):
            raise Fh3ProgressionError("CareerState is truncated")
        length = values[pos]
        pos += 1
        if length > (len(values) - pos) // width:
            raise Fh3ProgressionError("CareerState has an implausible record count")
        rows = []
        for _ in range(length):
            rows.append(list(values[pos:pos + width]))
            pos += width
        return rows

    field1 = take(1)
    field2 = take(1)
    field3 = take(3)
    field4 = take(3)
    field5 = take(1)
    field6 = take(1)
    return values[0], field1, field2, field3, field4, field5, field6, values[pos:]


def _write_career(version, field1, field2, field3, field4, field5, field6,
                  rest) -> bytes:
    out = bytearray(struct.pack("<I", version))

    def put(width, rows):
        out.extend(struct.pack("<I", len(rows)))
        for row in rows:
            out.extend(struct.pack("<%dI" % width, *row))

    put(1, field1)
    put(1, field2)
    put(3, field3)
    put(3, field4)
    put(1, field5)
    put(1, field6)
    for value in rest:
        out.extend(struct.pack("<I", value))
    return bytes(out)


def _merge_triples(rows, ids):
    merged = {row[0]: [row[0], 1, 1] for row in rows}
    for event_id in ids:
        merged[event_id] = [event_id, 1, 1]
    return [merged[key] for key in sorted(merged)]


def _merge_ids(rows, ids):
    seen = {row[0] for row in rows}
    out = [list(row) for row in rows]
    for value in ids:
        if value not in seen:
            out.append([value])
            seen.add(value)
    return out


def complete_career(doc) -> int:
    obj = _binary_object(doc, "CareerState")
    if obj is None:
        return 0
    (version, field1, field2, field3, field4, field5, field6,
     rest) = _parse_career(obj.data)
    reference = _data()["career"]
    if len(field1) < len(reference["f1"]):
        field1 = [[value] for value in reference["f1"]]
    if len(field2) < len(reference["f2"]):
        field2 = [[value] for value in reference["f2"]]
    field3 = _merge_triples(field3, reference["f3"])
    field4 = _merge_triples(field4, reference["f4"])
    field5 = _merge_ids(field5, reference["f5"])
    field6 = _merge_ids(field6, reference["f6"])
    _replace(doc, "CareerState",
             _write_career(version, field1, field2, field3, field4, field5,
                           field6, rest))
    return len(field3) + len(field4)


# --------------------------------------------------------------------------
# Campaign slots / festival sites
# --------------------------------------------------------------------------
def _parse_campaign(data: bytes):
    if len(data) < 8:
        raise Fh3ProgressionError("CampaignSlotsState is truncated")
    version, count = struct.unpack_from("<II", data, 0)
    if version not in (1, 2) or count > 10000:
        raise Fh3ProgressionError("CampaignSlotsState has an unknown layout")
    pos = 8
    entries = []
    for _ in range(count):
        if pos + 10 > len(data):
            raise Fh3ProgressionError("CampaignSlotsState is truncated")
        flags, name_hash, length = struct.unpack_from("<HII", data, pos)
        pos += 10
        if pos + length + 5 > len(data):
            raise Fh3ProgressionError("CampaignSlotsState has a bad name length")
        name = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        state = data[pos]
        pos += 1
        value = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        entries.append([flags, name_hash, name, state, value])
    return version, entries, data[pos:]


def _write_campaign(version, entries, tail) -> bytes:
    out = bytearray(struct.pack("<II", version, len(entries)))
    for flags, name_hash, name, state, value in entries:
        encoded = name.encode("utf-8")
        out += struct.pack("<HII", flags, name_hash, len(encoded))
        out += encoded
        out += bytes((state & 0xFF,))
        out += struct.pack("<I", value)
    out += tail
    return bytes(out)


def complete_campaign_slots(doc) -> int:
    obj = _binary_object(doc, "CampaignSlotsState")
    if obj is None:
        return 0
    version, entries, tail = _parse_campaign(obj.data)
    known = {entry[2] for entry in entries}
    for name, name_hash, state in _data()["campaign_core"]:
        entry = next((e for e in entries if e[2] == name), None)
        if entry is None:
            entries.append([1, name_hash, name, state, 1])
            known.add(name)
        else:
            entry[3] = max(entry[3], state)
    _replace(doc, "CampaignSlotsState", _write_campaign(version, entries, tail))
    return len(entries)


# --------------------------------------------------------------------------
# iestate (tutorial / introduction flags)
# --------------------------------------------------------------------------
def _parse_iestate(data: bytes):
    if len(data) < 8:
        raise Fh3ProgressionError("iestate is truncated")
    version, count = struct.unpack_from("<II", data, 0)
    if version not in (1, 2) or count > 100000:
        raise Fh3ProgressionError("iestate has an unknown layout")
    pos = 8
    entries = []
    for _ in range(count):
        if pos + 4 > len(data):
            raise Fh3ProgressionError("iestate is truncated")
        length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if pos + length + 1 > len(data):
            raise Fh3ProgressionError("iestate has a bad name length")
        name = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        entries.append([name, data[pos]])
        pos += 1
    return version, entries, data[pos:]


def _write_iestate(version, entries, tail) -> bytes:
    out = bytearray(struct.pack("<II", version, len(entries)))
    for name, value in entries:
        encoded = name.encode("utf-8")
        out += struct.pack("<I", len(encoded))
        out += encoded
        out += bytes((value & 0xFF,))
    out += tail
    return bytes(out)


def mark_introductions_done(doc) -> int:
    obj = _binary_object(doc, "iestate")
    if obj is None:
        return 0
    version, entries, tail = _parse_iestate(obj.data)
    for entry in entries:
        entry[1] = 1
    _replace(doc, "iestate", _write_iestate(version, entries, tail))
    return len(entries)


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def _parse_stats(data: bytes):
    if len(data) < 8:
        raise Fh3ProgressionError("Stats is truncated")
    version, count = struct.unpack_from("<II", data, 0)
    if version not in (1, 2) or count > 100000:
        raise Fh3ProgressionError("Stats has an unknown layout")
    pos = 8
    entries = []
    for _ in range(count):
        if pos + 10 > len(data):
            raise Fh3ProgressionError("Stats is truncated")
        flags, name_hash, length = struct.unpack_from("<HII", data, pos)
        pos += 10
        if pos + length + 4 > len(data):
            raise Fh3ProgressionError("Stats has a bad name length")
        name = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        value_length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if pos + value_length > len(data):
            raise Fh3ProgressionError("Stats has a bad value length")
        value = data[pos:pos + value_length].decode("utf-8", "replace")
        pos += value_length
        entries.append([flags, name_hash, name, value])
    return version, entries, data[pos:]


def _write_stats(version, entries, tail) -> bytes:
    out = bytearray(struct.pack("<II", version, len(entries)))
    for flags, name_hash, name, value in entries:
        encoded_name = name.encode("utf-8")
        encoded_value = str(value).encode("utf-8")
        out += struct.pack("<HII", flags, name_hash, len(encoded_name))
        out += encoded_name
        out += struct.pack("<I", len(encoded_value))
        out += encoded_value
    out += tail
    return bytes(out)


def apply_stats(doc) -> int:
    obj = _binary_object(doc, "Stats")
    if obj is None:
        return 0
    version, entries, tail = _parse_stats(obj.data)
    targets = _data()["stats"]
    updated = 0
    for entry in entries:
        if entry[2] in targets:
            value = str(targets[entry[2]])
            if entry[3] != value:
                entry[3] = value
                updated += 1
    _replace(doc, "Stats", _write_stats(version, entries, tail))

    # Mirror the same counters into the profile bags (CompareStats/MiscStats
    # are what the menus and records screens read).
    if getattr(doc, "profile", None) is not None:
        for path, value in _data().get("profile", {}).items():
            if path in _PROFILE_SKIP:
                continue
            prop = doc.profile.find(path)
            if prop is None:
                continue
            try:
                prop.set(value)
            except (TypeError, ValueError):
                pass
    return updated


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def verify_roundtrip(doc):
    """Re-serialise every parsed progression object and compare bytes.

    Returns a list of human-readable problems; an empty list means every
    object this module understands round-trips byte-identically.
    """
    checks = (
        ("BucketListChallengeState", _parse_bucket, _write_bucket),
        ("DiscoveryState", _parse_discovery, _write_discovery),
        ("CareerState", _parse_career, _write_career),
        ("CampaignSlotsState", _parse_campaign, _write_campaign),
        ("iestate", _parse_iestate, _write_iestate),
        ("Stats", _parse_stats, _write_stats),
    )
    problems = []
    for object_id, parser, writer in checks:
        obj = _binary_object(doc, object_id)
        if obj is None:
            continue
        try:
            parsed = parser(obj.data)
            rebuilt = writer(*parsed)
        except (Fh3ProgressionError, struct.error) as exc:
            problems.append("%s: %s" % (object_id, exc))
            continue
        if rebuilt != obj.data:
            problems.append("%s: re-serialised data differs" % object_id)
    return problems
