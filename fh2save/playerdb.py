"""PlayerDatabase: an embedded SQLite 3 database with an 8-byte ``ssmc`` prefix.

The prefix is stripped before handing the bytes to :mod:`sqlite3` (via a temp
file) and re-attached when serialising.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile


class PlayerDatabase:
    PREFIX_LEN = 8

    def __init__(self, raw: bytes):
        self.prefix = raw[:self.PREFIX_LEN]
        self.db_bytes = raw[self.PREFIX_LEN:]
        self._dirty = False
        fd, self._tmp_path = tempfile.mkstemp(prefix="fh2pdb_", suffix=".sqlite")
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.db_bytes)
        self.conn = sqlite3.connect(self._tmp_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")

    # ---- schema --------------------------------------------------------
    def tables(self) -> list:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def columns(self, table: str) -> list:
        return [r[1] for r in self.conn.execute("PRAGMA table_info([%s])" % table)]

    def column_types(self, table: str) -> dict:
        return {r[1]: (r[2] or "") for r in self.conn.execute("PRAGMA table_info([%s])" % table)}

    def row_count(self, table: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM [%s]" % table).fetchone()[0]

    def rows(self, table: str, limit: int | None = None):
        """Rows as tuples; element 0 is always the SQLite rowid."""
        sql = "SELECT rowid, * FROM [%s]" % table
        if limit:
            sql += " LIMIT %d" % limit
        return self.conn.execute(sql).fetchall()

    @staticmethod
    def rowid_of(row) -> int:
        return row[0]

    def raw_rows(self, table: str):
        return self.conn.execute("SELECT * FROM [%s]" % table).fetchall()

    # ---- mutation ------------------------------------------------------
    def update_cell(self, table: str, rowid: int, column: str, value) -> None:
        # column name comes from the schema, not user text
        cols = self.columns(table)
        if column not in cols:
            raise ValueError("unknown column %r" % column)
        self.conn.execute(
            "UPDATE [%s] SET [%s]=? WHERE rowid=?" % (table, column), (value, rowid)
        )
        self.conn.commit()
        self._dirty = True

    def delete_row(self, table: str, rowid: int) -> None:
        self.conn.execute("DELETE FROM [%s] WHERE rowid=?" % table, (rowid,))
        self.conn.commit()
        self._dirty = True

    def insert_row(self, table: str, values: dict) -> int:
        cols = [c for c in values if c in self.columns(table)]
        if not cols:
            raise ValueError("no valid columns")
        sql = "INSERT INTO [%s] (%s) VALUES (%s)" % (
            table,
            ",".join("[%s]" % c for c in cols),
            ",".join("?" for _ in cols),
        )
        cur = self.conn.execute(sql, [values[c] for c in cols])
        self.conn.commit()
        self._dirty = True
        return cur.lastrowid

    def clone_row(self, table: str, rowid: int, overrides: dict) -> int:
        cols = self.columns(table)
        row = self.conn.execute(
            "SELECT * FROM [%s] WHERE rowid=?" % table, (rowid,)
        ).fetchone()
        if row is None:
            raise ValueError("row %d not found" % rowid)
        values = {c: row[c] for c in cols}
        # Never copy an auto primary key unless explicitly overridden.
        pk = self._pk(table)
        for k, v in overrides.items():
            if k in values:
                values[k] = v
        if pk and pk not in overrides:
            values.pop(pk, None)
        return self.insert_row(table, values)

    def _pk(self, table: str):
        for r in self.conn.execute("PRAGMA table_info([%s])" % table):
            if r[5]:  # pk flag
                return r[1]
        return None

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        self._dirty = True
        return cur

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    # ---- serialising ---------------------------------------------------
    def serialize(self) -> bytes:
        # Nothing has been written through this handle: return the original
        # bytes verbatim.  This keeps is_dirty() cheap (no 6 MB disk read).
        if not self._dirty:
            return self.prefix + self.db_bytes
        self.conn.commit()
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.commit()
        with open(self._tmp_path, "rb") as fh:
            data = fh.read()
        return self.prefix + data

    def mark_clean(self, raw: bytes = None) -> None:
        """Forget the dirty flag after a successful save."""
        if raw is not None:
            self.prefix = raw[:self.PREFIX_LEN]
            self.db_bytes = raw[self.PREFIX_LEN:]
        self._dirty = False

    def close(self):
        try:
            self.conn.close()
        finally:
            for path in (self._tmp_path, self._tmp_path + "-wal", self._tmp_path + "-shm"):
                try:
                    if os.path.exists(path):
                        os.unlink(path)
                except OSError:
                    pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
