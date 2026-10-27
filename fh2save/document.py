"""SaveDocument: a loaded revision with all blobs parsed into models.

FH2 blobs are plaintext; FH3 ``ProfileData`` and ``VersionFlags`` are TFIT
containers.  The public surface (``profile``, ``savestate``, ``playerdb``,
``binsave``, ``compile``, ``save``) is the same for both, so the CLI and TUI
can stay mostly game-agnostic.
"""

from __future__ import annotations

import struct

from .binsave import BinSave
from .container import DATA_BLOBS, verify_commit
from .fh3crypto import Fh3CryptoError, cipher, decrypt_profile
from .fh3profile import Fh3SaveData
from .playerdb import PlayerDatabase
from .profile import ProfileData
from .savestate import SaveState

PROFILE = "ProfileData"
SAVESTATE = "SaveState"
BINSAVE = "BinarySaveState"
PLAYERDB = "PlayerDatabase"
VERSIONFLAGS = "VersionFlags"

FH2_TITLE_IDS = {"1A96545B"}
FH3_TITLE_IDS = {"4CE1DFAB"}
GAME_NAMES = {"FH2": "Forza Horizon 2", "FH3": "Forza Horizon 3"}


class SaveDocument:
    def __init__(self, saveset, rev, blobs: dict):
        self.saveset = saveset
        self.rev = rev
        self.original = dict(blobs)
        self.commit = saveset.read_commit(rev)
        self.format = self._detect_format(blobs)
        self.game_name = GAME_NAMES.get(self.format, self.format)
        self._dirty_cache = None
        if self.format == "FH3":
            self._load_fh3(blobs)
        else:
            self._load_fh2(blobs)

    # ---- format detection ---------------------------------------------
    def _detect_format(self, blobs) -> str:
        pd = blobs.get(PROFILE)
        if pd is not None:
            if pd[:4] == b"ssmc":
                return "FH2"
            try:
                plain = decrypt_profile(pd)
            except (Fh3CryptoError, ValueError, struct.error):
                plain = None
            if plain is not None:
                self._fh3_detected_plain = plain
                return "FH3"
        title = str(getattr(self.saveset, "title_id", "") or "").upper()
        if title in FH3_TITLE_IDS:
            return "FH3"
        return "FH2"

    # ---- FH2 -----------------------------------------------------------
    def _load_fh2(self, blobs):
        self.profile = ProfileData(blobs[PROFILE]) if PROFILE in blobs else None
        self.savestate = SaveState(blobs[SAVESTATE]) if SAVESTATE in blobs else None
        self.playerdb = PlayerDatabase(blobs[PLAYERDB]) if PLAYERDB in blobs else None
        self.binsave = BinSave(blobs[BINSAVE]) if BINSAVE in blobs else None
        self.versionflags = (
            struct.unpack("<I", blobs[VERSIONFLAGS][:4])[0]
            if VERSIONFLAGS in blobs else None
        )
        self.fh3 = None

    # ---- FH3 -----------------------------------------------------------
    def _load_fh3(self, blobs):
        if PROFILE not in blobs:
            raise Fh3CryptoError("FH3 save has no ProfileData blob")
        plain = getattr(self, "_fh3_detected_plain", None)
        if plain is None:
            plain = decrypt_profile(blobs[PROFILE])
        self._original_plain = plain
        self._profile_blob = blobs[PROFILE]
        self._profile_plain_len = len(plain)
        self.fh3 = Fh3SaveData(plain)
        self.profile = self.fh3.profile
        self.savestate = self.fh3.savestate
        self.playerdb = PlayerDatabase(self.fh3.database_raw)
        self.binsave = self.fh3.binary
        self.versionflags = None
        self._vf_blob = None
        self._original_vf_plain = None
        if VERSIONFLAGS in blobs:
            vf_plain = decrypt_profile(blobs[VERSIONFLAGS])
            self._vf_blob = blobs[VERSIONFLAGS]
            self._original_vf_plain = vf_plain
            if len(vf_plain) >= 4:
                self.versionflags = struct.unpack("<I", vf_plain[:4])[0]

    # ---- integrity -----------------------------------------------------
    def verify(self) -> list:
        return verify_commit(self.original, self.commit)

    # ---- compile / diff ------------------------------------------------
    def _compile_fh3(self) -> dict:
        out = dict(self.original)
        plain = self.fh3.serialize(database=self.playerdb)
        out[PROFILE] = self._encrypt_like(
            self._profile_blob, plain, self._profile_plain_len
        )
        if self._vf_blob is not None and self.versionflags is not None:
            vf_plain = struct.pack("<I", self.versionflags & 0xFFFFFFFF)
            out[VERSIONFLAGS] = self._encrypt_like(
                self._vf_blob, vf_plain, len(self._original_vf_plain or b"")
            )
        return out

    @staticmethod
    def _encrypt_like(blob: bytes, plain: bytes, original_len: int) -> bytes:
        iv = blob[:16]
        padding = struct.unpack_from("<I", blob, 16)[0]
        if len(plain) != original_len:
            padding = None  # size changed: recompute the zero padding
        return cipher().encrypt(plain, iv=iv, padding=padding)

    def compile(self) -> dict:
        if self.format == "FH3":
            return self._compile_fh3()
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
        if self.format == "FH3":
            changed = []
            plain = self.fh3.serialize(database=self.playerdb)
            if plain != self._original_plain:
                changed.append(PROFILE)
            if self._vf_blob is not None:
                vf_plain = struct.pack("<I", self.versionflags & 0xFFFFFFFF)
                if vf_plain != self._original_vf_plain:
                    changed.append(VERSIONFLAGS)
            return changed
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

    def mark_clean(self, compiled: dict | None = None) -> None:
        """Call after the document has been written to a new revision."""
        if self.playerdb is not None:
            if self.format == "FH3":
                self.playerdb.mark_clean(self.playerdb.serialize())
            elif compiled is not None and PLAYERDB in compiled:
                self.playerdb.mark_clean(compiled[PLAYERDB])
        if self.format == "FH3":
            self._profile_blob = self.original.get(PROFILE, self._profile_blob)
            self._vf_blob = self.original.get(VERSIONFLAGS, self._vf_blob)
            self._original_plain = self.fh3.serialize(database=self.playerdb)
            self._profile_plain_len = len(self._original_plain)
            if self._vf_blob is not None:
                self._original_vf_plain = struct.pack(
                    "<I", (self.versionflags or 0) & 0xFFFFFFFF
                )
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
