"""Container layer: the Xbox One "Connected Storage" revision store.

Directory layout handled here::

    <root>/titles/<TITLEID>/saves/<slot>/User_<XUID>/revisions/<16-hex>/commit
                                                                        data/<blob>

A revision is a full snapshot of the blobs plus a text ``commit`` manifest that
holds a SHA-256 + byte size for every blob.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

COMMIT_HEADER = "Azimuth complete save revision v2"
DATA_BLOBS = [
    "BinarySaveState",
    "PlayerDatabase",
    "ProfileData",
    "SaveState",
    "VersionFlags",
]


@dataclass
class CommitEntry:
    sha256: str
    size: int
    name: str


@dataclass
class Commit:
    header: str
    declared_blobs: int
    entries: list

    @property
    def names(self):
        return [e.name for e in self.entries]


def parse_commit(text: str) -> Commit:
    lines = text.replace("\r\n", "\n").split("\n")
    lines = [ln for ln in lines if ln.strip() != ""]
    header = lines[0] if lines else ""
    declared = 0
    entries: list[CommitEntry] = []
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) == 2 and parts[0] == "blobs":
            declared = int(parts[1])
        elif len(parts) == 3 and len(parts[0]) == 64:
            entries.append(CommitEntry(parts[0], int(parts[1]), parts[2]))
    return Commit(header, declared, entries)


def build_commit(blobs: dict) -> str:
    lines = [COMMIT_HEADER, "blobs %d" % len(blobs)]
    for name in sorted(blobs):
        data = blobs[name]
        digest = hashlib.sha256(data).hexdigest()
        lines.append("%s %d %s" % (digest, len(data), name))
    return "\n".join(lines) + "\n"


def verify_commit(blobs: dict, commit: Commit) -> list:
    """Return a list of human-readable problems (empty == all good)."""
    problems = []
    for e in commit.entries:
        if e.name not in blobs:
            problems.append("missing blob: %s" % e.name)
            continue
        data = blobs[e.name]
        if len(data) != e.size:
            problems.append("%s: size %d != committed %d" % (e.name, len(data), e.size))
        actual = hashlib.sha256(data).hexdigest()
        if actual != e.sha256:
            problems.append("%s: sha256 mismatch" % e.name)
    for name in blobs:
        if name not in commit.names:
            problems.append("uncommitted blob: %s" % name)
    return problems


class Revision:
    def __init__(self, number: int, path: Path):
        self.number = number
        self.path = path

    def __repr__(self):
        return "Revision(0x%x @ %s)" % (self.number, self.path)


class SaveSet:
    """One (title, slot, user) save with one or more revisions."""

    def __init__(self, title_id: str, slot: str, user: str, revisions_dir: Path):
        self.title_id = title_id
        self.slot = slot
        self.user = user
        self.revisions_dir = Path(revisions_dir)

    # ---- discovery -----------------------------------------------------
    @property
    def xuid(self):
        u = self.user[5:] if self.user.startswith("User_") else self.user
        try:
            return int(u, 16)
        except ValueError:
            return None

    def revisions(self) -> list:
        revs = []
        if not self.revisions_dir.is_dir():
            return revs
        for child in self.revisions_dir.iterdir():
            if child.is_dir():
                try:
                    revs.append(Revision(int(child.name, 16), child))
                except ValueError:
                    pass
        revs.sort(key=lambda r: r.number)
        return revs

    def latest(self) -> Revision:
        revs = self.revisions()
        if not revs:
            raise FileNotFoundError("no revisions in %s" % self.revisions_dir)
        return revs[-1]

    def read_commit(self, rev: Revision) -> Commit:
        return parse_commit((rev.path / "commit").read_text(encoding="utf-8"))

    def read_revision(self, rev: Revision) -> dict:
        data_dir = rev.path / "data"
        blobs = {}
        if data_dir.is_dir():
            for f in sorted(data_dir.iterdir()):
                if f.is_file():
                    blobs[f.name] = f.read_bytes()
        return blobs

    def next_revision_number(self) -> int:
        revs = self.revisions()
        return (revs[-1].number + 1) if revs else 1

    # ---- writing -------------------------------------------------------
    def write_revision(self, blobs: dict, number: int | None = None,
                       data_names: list | None = None) -> Revision:
        if number is None:
            number = self.next_revision_number()
        path = self.revisions_dir / ("%016x" % number)
        data_dir = path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        # Remove any stale blob that is not part of this save set.
        keep = set(blobs)
        for f in data_dir.iterdir():
            if f.is_file() and f.name not in keep:
                f.unlink()
        for name, data in blobs.items():
            (data_dir / name).write_bytes(data)
        (path / "commit").write_text(build_commit(blobs), encoding="utf-8")
        return Revision(number, path)

    def backup_revision(self, rev: Revision, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / ("%016x" % rev.number)
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(rev.path, out)
        return out


def discover(root, search: bool = False) -> list:
    """Find every SaveSet at *root*.

    By default the lookup is literal and predictable: *root* itself must be a
    folder that directly contains a ``titles`` directory, or be the ``titles``
    directory itself.  No other directory is inspected, so the editor never
    silently picks up a save from a sibling/parent folder.

    Pass ``search=True`` (CLI: ``--search``) to additionally look up to two
    directory levels *below* *root* for a ``titles`` folder.
    """
    root = Path(root).expanduser().resolve()
    titles_dirs = []

    if (root / "titles").is_dir():
        titles_dirs.append(root / "titles")
    elif root.is_dir() and root.name == "titles":
        titles_dirs.append(root)
    elif search:
        for base in [*root.glob("*"), *root.glob("*/*")]:
            if base.is_dir() and (base / "titles").is_dir():
                titles_dirs.append(base / "titles")

    found = []
    seen = set()
    for titles in titles_dirs:
        for title in sorted(titles.iterdir()):
            saves = title / "saves"
            if not saves.is_dir():
                continue
            for slot in sorted(saves.iterdir()):
                if not slot.is_dir():
                    continue
                for user in sorted(slot.iterdir()):
                    revdir = user / "revisions"
                    if revdir.is_dir():
                        key = (title.name, slot.name, user.name)
                        if key in seen:
                            continue
                        seen.add(key)
                        found.append(SaveSet(title.name, slot.name, user.name, revdir))
    return found


def format_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return str(n)
