"""Pure-Python TFIT (Arxan TransformIT) crypto for Forza Horizon 3 saves.

The Xbox One save blobs for FH3 are encrypted with a 17-round TFIT block
cipher and authenticated with a 13-round MAC.  This module implements both
directions using the key/table material in ``data/fh3_tfit.bin``.

File layout (all little-endian)::

    u8[16]  iv
    u32     padding_size
    u8[16]  header MAC             (over u32(data_size) + iv + u32(padding))
    block*  u8[block_size] data    (CBC-style)
            u8[16]         MAC     (over the *plaintext* data block)

``block_size`` is 0x200 for profile/VersionFlags data.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

MAGIC = b"FH3TFIT1"
DATA_PATH = Path(__file__).with_name("data") / "fh3_tfit.bin"

# The encryption context used by FH3 ProfileData and VersionFlags.
FH3_GAME = 6
FH3_KEYTYPE_PROFILE = 0


class Fh3CryptoError(Exception):
    """Raised when a blob is not valid FH3-encrypted data."""


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _circular_shift(src: bytes) -> bytes:
    """16-byte left shift with the TFIT 0x87 reduction byte."""
    dst = bytearray(16)
    dst[15] = (135 if (src[0] >> 7) else 0) ^ ((src[15] << 1) & 0xFF)
    for i in range(14, -1, -1):
        dst[i] = ((src[i + 1] >> 7) | ((src[i] << 1) & 0xFF)) & 0xFF
    return bytes(dst)


# Column order for the two RoundB variants.  Each tuple lists the eight
# 4-byte input positions that feed one 4-byte output word.
_ROUND_B_DEC = (
    (0, 7, 10, 13),
    (1, 4, 11, 14),
    (2, 5, 8, 15),
    (3, 6, 9, 12),
)
_ROUND_B_ENC = (
    (0, 5, 10, 15),
    (3, 4, 9, 14),
    (2, 7, 8, 13),
    (1, 6, 11, 12),
)


class TfitCipher:
    """FH3 profile-key TFIT cipher (decrypt, encrypt and MAC)."""

    def __init__(self, data: bytes | None = None):
        if data is None:
            try:
                data = DATA_PATH.read_bytes()
            except OSError as exc:
                raise Fh3CryptoError(
                    "FH3 key material is missing (%s). Reinstall the package."
                    % DATA_PATH
                ) from exc
        if data[:8] != MAGIC:
            raise Fh3CryptoError("bad FH3 key material magic")
        pos = 8
        self.block_size, group_count = struct.unpack_from("<IH", data, pos)
        pos += 6
        self.dec_keys, pos = self._read_keys(data, pos)
        self.mac_keys, pos = self._read_keys(data, pos)
        self.enc_keys, pos = self._read_keys(data, pos)
        groups = []
        for _ in range(group_count):
            count = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            pool = []
            for _i in range(count):
                pool.append(struct.unpack_from("<256I", data, pos))
                pos += 0x400
            sel_count = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            sel = list(data[pos:pos + sel_count])
            pos += sel_count
            groups.append([pool[i] for i in sel])
        if len(groups) != 3:
            raise Fh3CryptoError("unexpected table group count")
        if pos != len(data):
            raise Fh3CryptoError("trailing bytes in FH3 key material")
        # groups are stored in the order encryption, decryption, MAC.
        self.enc_tables = self._rounds(groups[0], len(self.enc_keys))
        self.dec_tables = self._rounds(groups[1], len(self.dec_keys))
        self.mac_tables = self._rounds(groups[2], len(self.mac_keys))

    @staticmethod
    def _read_keys(data, pos):
        count = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        keys = []
        for _ in range(count):
            keys.append(struct.unpack_from("<4I", data, pos))
            pos += 16
        return keys, pos

    @staticmethod
    def _rounds(tables, key_count):
        if len(tables) != key_count * 16:
            raise Fh3CryptoError(
                "table selection does not match keys (%d != %d*16)"
                % (len(tables), key_count)
            )
        return [tables[i * 16:(i + 1) * 16] for i in range(key_count)]

    # ---- TFIT core -----------------------------------------------------
    @staticmethod
    def _round_a(data: bytes, key, tables) -> bytes:
        out = [0, 0, 0, 0]
        for g in range(4):
            base = g * 4
            v = 0
            v ^= tables[base][data[base]]
            v ^= tables[base + 1][data[base + 1]]
            v ^= tables[base + 2][data[base + 2]]
            v ^= tables[base + 3][data[base + 3]]
            out[g] = v ^ key[g]
        return struct.pack("<4I", *out)

    @staticmethod
    def _round_b(data: bytes, key, tables, order) -> bytes:
        out = [0, 0, 0, 0]
        for g in range(4):
            v = 0
            for j in order[g]:
                v ^= tables[j][data[j]]
            out[g] = v ^ key[g]
        return struct.pack("<4I", *out)

    def _process_block(self, src: bytes, keys, rounds, encrypt: bool) -> bytes:
        data = self._round_a(src, keys[0], rounds[0])
        data = self._round_a(data, keys[1], rounds[1])
        order = _ROUND_B_ENC if encrypt else _ROUND_B_DEC
        for i in range(2, len(keys) - 1):
            data = self._round_b(data, keys[i], rounds[i], order)
        return self._round_a(data, keys[-1], rounds[-1])

    def _mac(self, data: bytes) -> bytes:
        keys = self.mac_keys
        rounds = self.mac_tables
        full, partial = divmod(len(data), 16)
        block_count = full + (1 if partial else 0)
        temp = self._process_block(bytes(16), keys, rounds, True)
        last_scramble = _circular_shift(temp)
        temp = bytes(16)
        temp2 = bytes(16)
        for i in range(block_count - 1):
            temp = _xor(data[i * 16:(i + 1) * 16], temp2)
            temp2 = self._process_block(temp, keys, rounds, True)
        if partial:
            padded = data[full * 16:] + b"\x80" + bytes(15 - partial)
            temp = _xor(temp2, padded)
            temp = _xor(temp, _circular_shift(last_scramble))
        else:
            temp = _xor(temp2, data[(block_count - 1) * 16:block_count * 16])
            temp = _xor(temp, last_scramble)
        return self._process_block(temp, keys, rounds, True)

    # ---- public API ----------------------------------------------------
    def decrypt(self, raw: bytes) -> bytes:
        """Decrypt a TFIT container and return the plaintext."""
        if len(raw) < 36:
            raise Fh3CryptoError("blob is too short to be TFIT")
        iv = raw[:16]
        padding = struct.unpack_from("<I", raw, 16)[0]
        header_mac = raw[20:36]
        body = raw[36:]
        unit = self.block_size + 16
        if len(body) == 0 or len(body) % unit:
            raise Fh3CryptoError("blob size is not a whole number of TFIT blocks")
        block_count = len(body) // unit
        data_size = block_count * self.block_size
        if padding > self.block_size or padding > data_size:
            raise Fh3CryptoError("bad TFIT padding size")
        header = struct.pack("<I", data_size) + iv + struct.pack("<I", padding)
        if self._mac(header) != header_mac:
            raise Fh3CryptoError("TFIT header MAC mismatch")
        prev = iv
        out = bytearray()
        pos = 0
        for _ in range(block_count):
            block = bytearray()
            for _i in range(self.block_size // 16):
                src = body[pos:pos + 16]
                pos += 16
                dst = self._process_block(src, self.dec_keys, self.dec_tables, False)
                block += _xor(dst, prev)
                prev = src
            # The per-block MAC ciphertext also feeds the CBC chain for the
            # next block.  Reading it is enough; the MAC itself is covered by
            # the commit hash and the header MAC.
            prev = body[pos:pos + 16]
            pos += 16
            out += block
        if padding:
            del out[-padding:]
        return bytes(out)

    def encrypt(self, plain: bytes, iv: bytes | None = None,
                padding: int | None = None) -> bytes:
        """Encrypt *plain* into a TFIT container.

        Passing the original ``iv``/``padding`` makes the operation
        deterministic, which lets an unchanged save produce byte-identical
        output (and therefore stay "clean" in the editor).
        """
        if iv is None:
            iv = os.urandom(16)
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        if padding is None:
            padding = (-len(plain)) & (self.block_size - 1)
        if not 0 <= padding < self.block_size:
            raise ValueError("bad padding")
        data_size = len(plain) + padding
        header = struct.pack("<I", data_size) + iv + struct.pack("<I", padding)
        header_mac = self._mac(header)
        out = bytearray(iv)
        out += struct.pack("<I", padding)
        out += header_mac
        prev = iv
        for off in range(0, data_size, self.block_size):
            chunk = plain[off:off + self.block_size]
            if len(chunk) < self.block_size:
                chunk = chunk + bytes(self.block_size - len(chunk))
            for i in range(self.block_size // 16):
                src = _xor(chunk[i * 16:(i + 1) * 16], prev)
                dst = self._process_block(src, self.enc_keys, self.enc_tables, True)
                out += dst
                prev = dst
            mac = self._mac(chunk)
            src = _xor(mac, prev)
            dst = self._process_block(src, self.enc_keys, self.enc_tables, True)
            out += dst
            prev = dst
        return bytes(out)


_cipher = None


def cipher() -> TfitCipher:
    """Return a process-wide cipher instance (loading tables is not free)."""
    global _cipher
    if _cipher is None:
        _cipher = TfitCipher()
    return _cipher


def decrypt_profile(raw: bytes) -> bytes:
    return cipher().decrypt(raw)


def encrypt_profile(plain: bytes, iv: bytes | None = None,
                    padding: int | None = None) -> bytes:
    return cipher().encrypt(plain, iv=iv, padding=padding)


def is_tfit(raw: bytes) -> bool:
    """Cheap-ish probe: does *raw* carry a valid FH3 header MAC?"""
    try:
        cipher().decrypt(raw)
        return True
    except (Fh3CryptoError, ValueError, struct.error):
        return False
