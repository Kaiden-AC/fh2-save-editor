"""SaveDocument: a loaded revision with all blobs parsed into models."""

from __future__ import annotations

import struct

from .binsave import BinSave
from .container import DATA_BLOBS, verify_commit
from .playerdb import PlayerDatabase
from .profile import ProfileData
from .savestate import SaveState

PROFILE = "ProfileData"
SAVESTATE = "SaveState"
BINSAVE = "BinarySaveState"
PLAYERDB = "PlayerDatabase"
VERSIONFLAGS = "VersionFlags"


class SaveDocument:
    def __init__(self, saveset, rev, blobs: dict):
        self.saveset = saveset
        self.rev = rev
        self.original = dict(blobs)
        self.commit = saveset.read_commit(rev)

        self.profile = ProfileData(blobs[PROFILE]) if PROFILE in blobs else None
        self.savestate = SaveState(blobs[SAVESTATE]) if SAVESTATE in blobs else None
        self.playerdb = PlayerDatabase(blobs[PLAYERDB]) if PLAYERDB in blobs else None
        self.binsave = BinSave(blobs[BINSAVE]) if BINSAVE in blobs else None
        self.versionflags = (
            struct.unpack("<I", blobs[VERSIONFLAGS][:4])[0] if VERSIONFLAGS in blobs else None
        )
        self._dirty_cache = None

    # ---- integrity -----------------------------------------------------
    def verify(self) -> list:
        return verify_commit(self.original, self.commit)

    # ---- compile / diff ------------------------------------------------
    def compile(self) -> dict:
        out = dict(self.original)
        if self.profile is not None:
            out[PROFILE] = self.profile.serialize()
        if self.savestate is not None:
            out[SAVESTATE] = self.savestate.serialize()
        if self.playerdb is not None:
            out[PLAYERDB] = self.playerdb.serialize()
        if self.binsave is not None:
            out[BINSAVE] = self.binsave.raw
        if self.versionflags is not None:
            out[VERSIONFLAGS] = struct.pack("<I", self.versionflags & 0xFFFFFFFF)
        return out

    def changed_blobs(self) -> list:
        compiled = self.compile()
        changed = []
        for name in sorted(set(compiled) | set(self.original)):
            if compiled.get(name) != self.original.get(name):
                changed.append(name)
        return changed

    def is_dirty(self) -> bool:
        # Cached: recomputing this on every rendered frame used to re-serialise
        # every blob (including a 6 MB database read) and made navigation lag.
        if self._dirty_cache is None:
            self._dirty_cache = bool(self.changed_blobs())
        return self._dirty_cache

    def invalidate(self) -> None:
        """Call after any edit so the cached dirty flag is recomputed once."""
        self._dirty_cache = None

    def mark_clean(self) -> None:
        """Call after the document has been written to a new revision."""
        self._dirty_cache = False

    # ---- save ----------------------------------------------------------
    def save(self, number=None):
        compiled = self.compile()
        return self.saveset.write_revision(compiled, number=number)

    def close(self):
        if self.playerdb is not None:
            self.playerdb.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
