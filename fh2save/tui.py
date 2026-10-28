"""Curses TUI for the FH2 Save Editor.

Zero third-party dependencies — everything here is the Python standard library.
"""

from __future__ import annotations

import curses
import os

from . import actions
from .container import format_bytes, verify_commit
from .document import SaveDocument

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
BOOL_TRUE = {"1", "true", "yes", "y", "on"}


def _to_int(text):
    t = text.strip()
    neg = t.startswith("-")
    body = t[1:] if neg else t
    if body.lower().startswith("0x"):
        val = int(body, 16)
    elif body.lower().startswith("0b"):
        val = int(body, 2)
    else:
        val = int(body, 10)
    return -val if neg else val


def parse_for_type(type_tag, text):
    t = text.strip()
    if type_tag in (0x00, 0x01):
        if t.lower() in BOOL_TRUE:
            return 1
        if t.lower() in ("0", "false", "no", "n", "off"):
            return 0
        return _to_int(t) & 0xFF
    if type_tag in (0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x11):
        return _to_int(t)
    if type_tag in (0x09, 0x0A):
        return float(t)
    if type_tag in (0x0B, 0x0C):
        return text
    if type_tag in (0x0D, 0x0E):
        return [float(x) for x in t.replace(",", " ").split()]
    raise ValueError("type %d not editable" % type_tag)


def addstr(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def clip(text, width):
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[:width - 1] + "\u2026"


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
class View:
    title = ""

    def render(self, app, win, top, height, width):
        raise NotImplementedError

    def handle(self, app, key):
        pass

    def footer(self, app):
        return "", ""

    def on_enter(self, app):
        pass


class ListView(View):
    def __init__(self, title, build_items, on_select=None, footer="", filterable=True):
        self.title = title
        self._build = build_items
        self.on_select = on_select
        self._footer = footer
        self.filterable = filterable
        self.app = None
        self.cursor = 0
        self.offset = 0
        self.filter = ""
        self.items = []

    def on_enter(self, app):
        self.app = app
        self.refresh()

    def refresh(self):
        items = list(self._build())
        if self.filter:
            f = self.filter.lower()
            items = [it for it in items if f in it[0].lower()]
        self.items = items
        if self.cursor >= len(items):
            self.cursor = max(0, len(items) - 1)

    def render(self, app, win, top, height, width):
        header = self.title
        if self.filter:
            header += "   /%s" % self.filter
        header += "   (%d)" % len(self.items)
        addstr(win, top, 0, clip(header, width), curses.A_BOLD)
        rows = height - 2
        if self.cursor < self.offset:
            self.offset = self.cursor
        if self.cursor >= self.offset + rows:
            self.offset = self.cursor - rows + 1
        for i in range(rows):
            idx = self.offset + i
            if idx >= len(self.items):
                break
            text, _ = self.items[idx]
            attr = curses.A_REVERSE if idx == self.cursor else 0
            addstr(win, top + 1 + i, 0, clip(" " + text, width), attr)

    def handle(self, app, key):
        n = len(self.items)
        rows_guess = 20
        if key in (curses.KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(n - 1, self.cursor + 1) if n else 0
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - rows_guess)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(n - 1, self.cursor + rows_guess) if n else 0
        elif key == curses.KEY_HOME:
            self.cursor = 0
        elif key == curses.KEY_END:
            self.cursor = max(0, n - 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.items and self.on_select:
                self.on_select(app, self.items[self.cursor])
            return
        elif self.filterable and key == ord("/"):
            app.prompt("filter", self.filter, self._set_filter)
            return
        elif key == 27:  # ESC
            if self.filter:
                self.filter = ""
                self.refresh()
            else:
                app.pop()
            return
        else:
            return
        self.refresh()

    def _set_filter(self, app, text):
        self.filter = text
        self.cursor = 0
        self.refresh()

    def footer(self, app):
        base = "[\u2191\u2193] move  [Enter] open"
        if self.filterable:
            base += "  [/] filter"
        if self._footer:
            base += "  " + self._footer
        base += "  [Esc] back"
        return base, ""


class TextView(View):
    def __init__(self, title, text):
        self.title = title
        self.lines = text.split("\n")
        self.offset = 0

    def render(self, app, win, top, height, width):
        addstr(win, top, 0, clip(self.title, width), curses.A_BOLD)
        rows = height - 2
        if self.offset > max(0, len(self.lines) - rows):
            self.offset = max(0, len(self.lines) - rows)
        for i in range(rows):
            idx = self.offset + i
            if idx >= len(self.lines):
                break
            addstr(win, top + 1 + i, 0, clip(self.lines[idx].rstrip("\n"), width))

    def handle(self, app, key):
        rows = 20
        if key in (curses.KEY_UP, ord("k")):
            self.offset = max(0, self.offset - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.offset = min(max(0, len(self.lines) - 1), self.offset + 1)
        elif key == curses.KEY_PPAGE:
            self.offset = max(0, self.offset - rows)
        elif key == curses.KEY_NPAGE:
            self.offset += rows
        elif key == curses.KEY_HOME:
            self.offset = 0
        elif key == curses.KEY_END:
            self.offset = max(0, len(self.lines) - 1)
        elif key in (27, curses.KEY_ENTER, 10, 13, ord("q"), ord("Q")):
            app.pop()

    def footer(self, app):
        return "[\u2191\u2193] scroll  [Esc] back", ""


# --------------------------------------------------------------------------
# Main menu
# --------------------------------------------------------------------------
class MainMenu(View):
    title = "Main menu"

    def _items(self):
        d = self.app.doc
        n_profile = len(d.profile) if d.profile else 0
        n_objects = len(d.savestate) if d.savestate else 0
        n_tables = len(d.playerdb.tables()) if d.playerdb else 0
        n_bin = len(d.binsave.objects) if d.binsave else 0
        return [
            ("ProfileData          %4d entries    (stats, credits, settings)" % n_profile,
             lambda a: a.push(ProfileView())),
            ("SaveState            %4d objects    (career, radio, boards)" % n_objects,
             lambda a: a.push(SaveStateView())),
            ("PlayerDatabase       %4d tables     (garage, races, unlocks)" % n_tables,
             lambda a: a.push(DbTablesView())),
            ("BinarySaveState      %4d objects    (drivatars, read-only)" % n_bin,
             lambda a: a.push(TextView("BinarySaveState",
                                       d.binsave.report() if d.binsave else "missing"))),
            ("VersionFlags         %s" % (d.versionflags if d.versionflags is not None else "?"),
             lambda a: a.edit_version_flags()),
            ("Quick actions        (money, XP, unlock helpers)",
             lambda a: a.push(QuickActionsView())),
            ("Integrity / commit   (verify + write settings)",
             lambda a: a.push(TextView("Integrity", a.integrity_text()))),
        ]

    def __init__(self, app):
        self.app = app
        self.cursor = 0

    def render(self, app, win, top, height, width):
        d = app.doc
        info = "%s   title %s   rev 0x%x   %s" % (
            d.game_name, d.saveset.title_id, d.rev.number,
            "DIRTY" if d.is_dirty() else "clean")
        addstr(win, top, 0, clip("Save: %s   %s" % (d.saveset.user, info), width),
               curses.A_BOLD)
        items = self._items()
        for i, (text, _) in enumerate(items):
            attr = curses.A_REVERSE if i == self.cursor else 0
            addstr(win, top + 2 + i, 0, clip("  " + text, width), attr)
        y = top + 2 + len(items) + 1
        addstr(win, y, 0, clip("  [S] Save as new revision", width))
        addstr(win, y + 1, 0, clip("  [B] Backup latest revision", width))

    def handle(self, app, key):
        items = self._items()
        if key in (curses.KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(len(items) - 1, self.cursor + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            items[self.cursor][1](app)
        elif key in (ord("s"), ord("S")):
            app.save()
        elif key in (ord("b"), ord("B")):
            app.backup()
        elif key in (ord("q"), ord("Q")):
            app.quit()

    def footer(self, app):
        return "[s] save  [b] backup  [q] quit", ""


# --------------------------------------------------------------------------
# ProfileData
# --------------------------------------------------------------------------
class ProfileView(ListView):
    def __init__(self):
        super().__init__(
            "ProfileData — stats & settings",
            self._items,
            on_select=self._select,
            footer="[Enter] edit",
        )

    def _items(self):
        props = self.app.doc.profile
        if props is None:
            return []
        out = []
        for p in props:
            editable = getattr(p, "editable", p.type not in (0x0F, 0x10))
            mark = " " if editable else "\u00b7"
            path = getattr(p, "path", p.name)
            text = "%s %-46s = %s   [%s]" % (mark, path, p.display(), p.type_name)
            out.append((text, p))
        return out

    def _select(self, app, item):
        p = item[1]
        if not getattr(p, "editable", p.type not in (0x0F, 0x10)):
            app.message("%s is a container and cannot be edited" % getattr(p, "path", p.name))
            return
        label = getattr(p, "path", p.name)
        app.prompt("Set %s [%s]" % (label, p.type_name), p.display(), self._set, p)

    def _set(self, app, text, prop):
        try:
            prop.set(parse_for_type(prop.type, text))
            app.message("Set %s = %s" % (getattr(prop, "path", prop.name), prop.display()))
        except Exception as exc:
            app.message("Invalid value: %s" % exc)


# --------------------------------------------------------------------------
# SaveState
# --------------------------------------------------------------------------
class SaveStateView(ListView):
    def __init__(self):
        super().__init__(
            "SaveState — game objects",
            self._items,
            on_select=self._select,
            footer="[Enter] open object",
        )

    def _items(self):
        ss = self.app.doc.savestate
        if ss is None:
            return []
        out = []
        for o in ss.objects:
            out.append(("%-42s [%s]  (%d props)" % (o.id, o.type, len(o.props)), o))
        return out

    def _select(self, app, item):
        app.push(SaveStateObjectView(item[1]))


class SaveStateObjectView(ListView):
    def __init__(self, obj):
        self.obj = obj
        super().__init__(
            "Object %s [%s]" % (obj.id, obj.type),
            self._items,
            on_select=self._select,
            footer="[Enter] edit",
        )

    def _items(self):
        return [("%-30s = %s" % (p.name, p.value), p) for p in self.obj.props]

    def _select(self, app, item):
        p = item[1]
        app.prompt("Set %s.%s" % (self.obj.id, p.name), p.value, self._set, p)

    def _set(self, app, text, prop):
        ok = self.app.doc.savestate.set_property(self.obj.id, prop.name, text)
        if ok:
            prop.value = text
            app.message("Set %s.%s = %s" % (self.obj.id, prop.name, text))
        else:
            app.message("Failed to set property")


# --------------------------------------------------------------------------
# PlayerDatabase
# --------------------------------------------------------------------------
class DbTablesView(ListView):
    def __init__(self):
        super().__init__(
            "PlayerDatabase — tables",
            self._items,
            on_select=self._select,
            footer="[Enter] open table",
        )

    def _items(self):
        db = self.app.doc.playerdb
        if db is None:
            return []
        out = []
        for t in db.tables():
            try:
                n = db.row_count(t)
            except Exception:
                n = "?"
            out.append(("%-44s %5s rows" % (t, n), t))
        return out

    def _select(self, app, item):
        app.push(DbRowsView(item[1]))


class DbRowsView(ListView):
    def __init__(self, table):
        self.table = table
        super().__init__(
            "PlayerDatabase — %s" % table,
            self._items,
            on_select=self._select,
            footer="[Enter] open row   [c] clone   [d] delete",
        )

    def _items(self):
        db = self.app.doc.playerdb
        cols = db.columns(self.table)
        out = []
        for r in db.rows(self.table):
            rowid = r[0]
            bits = []
            for i, c in enumerate(cols[:4]):
                bits.append("%s=%s" % (c, r[i + 1]))
            out.append(("rowid %-6s  %s" % (rowid, "  ".join(bits)), (rowid, r)))
        return out

    def _select(self, app, item):
        app.push(DbRowView(self.table, item[1][0]))

    def handle(self, app, key):
        if key in (ord("d"), ord("D")) and self.items:
            rowid = self.items[self.cursor][1][0]
            app.confirm("Delete rowid %s from %s?" % (rowid, self.table),
                        lambda a: self._delete(a, rowid))
            return
        if key in (ord("c"), ord("C")) and self.items:
            rowid = self.items[self.cursor][1][0]
            app.prompt("Clone row %s: new value for primary key column (blank = auto)"
                       % rowid, "", lambda a, t: self._clone(a, rowid, t))
            return
        super().handle(app, key)

    def _delete(self, app, rowid):
        app.doc.playerdb.delete_row(self.table, rowid)
        app.doc.invalidate()
        app.message("Deleted rowid %s" % rowid)
        self.refresh()

    def _clone(self, app, rowid, text):
        try:
            overrides = {}
            if text.strip():
                pk = app.doc.playerdb._pk(self.table)
                if pk:
                    overrides[pk] = int(text, 0)
            new = app.doc.playerdb.clone_row(self.table, rowid, overrides)
            app.message("Cloned rowid %s -> %s" % (rowid, new))
        except Exception as exc:
            app.message("Clone failed: %s" % exc)
        self.refresh()


class DbRowView(ListView):
    def __init__(self, table, rowid):
        self.table = table
        self.rowid = rowid
        super().__init__(
            "Row %s of %s" % (rowid, table),
            self._items,
            on_select=self._select,
            footer="[Enter] edit field",
        )

    def _items(self):
        db = self.app.doc.playerdb
        row = db.conn.execute(
            "SELECT * FROM [%s] WHERE rowid=?" % self.table, (self.rowid,)
        ).fetchone()
        if row is None:
            return []
        cols = db.columns(self.table)
        return [("%-30s = %s" % (c, row[c]), (c, row[c])) for c in cols]

    def _select(self, app, item):
        col, val = item[1]
        app.prompt("Set %s.%s" % (self.table, col), "" if val is None else str(val),
                   self._set, col)

    def _set(self, app, text, col):
        val = coerce_db_value(text)
        try:
            app.doc.playerdb.update_cell(self.table, self.rowid, col, val)
            app.message("Set %s.%s = %r" % (self.table, col, val))
        except Exception as exc:
            app.message("Update failed: %s" % exc)


def coerce_db_value(text):
    t = text.strip()
    if t == "":
        return None
    if t.lower() in ("none", "null"):
        return None
    try:
        return _to_int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return text


# --------------------------------------------------------------------------
# Quick actions
# --------------------------------------------------------------------------
class QuickActionsView(ListView):
    def __init__(self):
        super().__init__(
            "Quick actions",
            self._items,
            on_select=self._select,
            footer="[Enter] run",
            filterable=False,
        )

    def _items(self):
        return [
            ("MAX FH3 progression (everything below)",
             lambda a: a.message(actions.max_fh3_progression(a.doc))),
            ("Set credits / money", lambda a: a.edit_credits()),
            ("Set XP", lambda a: a.edit_xp()),
            ("Set driver level", lambda a: a.edit_level()),
            ("Set skill points (total + unspent)", lambda a: a.edit_skills()),
            ("Set skill tokens", lambda a: a.edit_tokens()),
            ("MAX credits (set 999,999,999)",
             lambda a: (actions.set_credits(a.doc, actions.FH3_MAX_CREDITS),
                        a.message("Credits maxed"))),
            ("Complete all speed traps",
             lambda a: a.message(actions.unlock_all_speed_traps(a.doc))),
            ("Complete all speed zones",
             lambda a: a.message(actions.unlock_all_speed_zones(a.doc))),
            ("Complete all danger signs",
             lambda a: a.message(actions.complete_all_danger_signs(a.doc))),
            ("Complete all drift zones",
             lambda a: a.message(actions.complete_all_drift_zones(a.doc))),
            ("Complete all PR stunts (all four types)",
             lambda a: a.message(actions.complete_all_pr_stunts(a.doc))),
            ("Unlock all reward boards",
             lambda a: a.message(actions.unlock_all_reward_boards(a.doc))),
            ("Activate all landmarks",
             lambda a: a.message(actions.activate_all_landmarks(a.doc))),
            ("Build all festival sites at level 5 + max fans",
             lambda a: a.message(actions.activate_all_festival_sites(a.doc))),
            ("Discover all bucket-list slots",
             lambda a: a.message(actions.discover_all_bucket_list_slots(a.doc))),
            ("Discover all map content (events, stunts, landmarks)",
             lambda a: a.message(actions.discover_everything(a.doc))),
            ("Mark all dialogue as played/seen",
             lambda a: a.message(actions.mark_all_dialogue_seen(a.doc))),
            ("Complete all bucket-list challenges",
             lambda a: a.message(actions.complete_all_bucket_list(a.doc))),
            ("Complete all career events + races",
             lambda a: a.message(actions.complete_all_race_results(a.doc))),
            ("Unlock/restore all barn finds (State=2)",
             lambda a: a.message(actions.unlock_all_barn_finds(a.doc, 2))),
            ("Add car to garage (clone)", lambda a: a.edit_add_car()),
            ("Reset garage tuning to stock",
             lambda a: a.message(actions.set_all_garage_tuning_stock(a.doc))),
        ]

    def _select(self, app, item):
        item[1](app)
        app.doc.invalidate()
        self.refresh()


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
class App:
    def __init__(self, stdscr, savesets, index=0):
        self.stdscr = stdscr
        self.savesets = savesets
        self.index = index
        self.stack = []
        self.message_text = ""
        self.prompt_active = False
        self.prompt_label = ""
        self.prompt_buf = ""
        self.prompt_pos = 0
        self.prompt_cb = None
        self.prompt_args = ()
        self.confirm_active = False
        self.confirm_text = ""
        self.confirm_cb = None
        self.running = True
        self._body = None
        self._body_dims = None
        self._load(index)
        self.push(MainMenu(self))

    # ---- document handling --------------------------------------------
    def _load(self, index):
        s = self.savesets[index]
        rev = s.latest()
        blobs = s.read_revision(rev)
        self.doc = SaveDocument(s, rev, blobs)

    def reload(self):
        self.doc = None
        self._load(self.index)

    def push(self, view):
        self.stack.append(view)
        view.on_enter(self)

    def pop(self):
        if self.stack:
            self.stack.pop()
        # Re-enter the newly exposed view so it reflects any edits made below.
        if self.stack:
            self.stack[-1].on_enter(self)

    def quit(self):
        self.running = False

    def message(self, text):
        self.message_text = text

    # ---- prompt / confirm ---------------------------------------------
    def prompt(self, label, current, callback, *args):
        self.prompt_active = True
        self.prompt_label = label
        self.prompt_buf = "" if current is None else str(current)
        self.prompt_pos = len(self.prompt_buf)
        self.prompt_cb = callback
        self.prompt_args = args

    def _finish_prompt(self, accept):
        cb = self.prompt_cb
        buf = self.prompt_buf
        args = self.prompt_args
        self.prompt_active = False
        self.prompt_cb = None
        if accept and cb:
            cb(self, buf, *args)
            # An edit may have changed the document: invalidate the cached
            # dirty flag and rebuild the visible list immediately (without
            # needing to move the selection).
            self.doc.invalidate()
            if self.stack and hasattr(self.stack[-1], "refresh"):
                self.stack[-1].refresh()

    def confirm(self, text, callback):
        self.confirm_active = True
        self.confirm_text = text
        self.confirm_cb = callback

    # ---- edit helpers --------------------------------------------------
    def edit_credits(self):
        cur = "0"
        p = self.doc.profile.find("Credits") if self.doc.profile else None
        if p:
            cur = str(p.get())
        self.prompt("Set credits", cur,
                    lambda a, t: a.message(actions.set_credits(a.doc, int(t, 0))))

    def edit_xp(self):
        cur = "0"
        p = self.doc.profile.find("XP") if self.doc.profile else None
        if p:
            cur = str(p.get())
        self.prompt("Set XP", cur,
                    lambda a, t: a.message(actions.set_xp(a.doc, int(t, 0))))

    def edit_level(self):
        cur = "1"
        p = self.doc.profile.find("Level") if self.doc.profile else None
        if p:
            cur = str(p.get())
        self.prompt("Set driver level", cur,
                    lambda a, t: a.message(actions.set_level(a.doc, int(t, 0))))

    def edit_skills(self):
        self.prompt("Set skill points total", "0",
                    lambda a, t: a.edit_skills2(int(t, 0)))

    def edit_skills2(self, total):
        self.prompt("Set unspent skill points", str(total),
                    lambda a, t: a.message(actions.set_skill_points(a.doc, total, int(t, 0))))

    def edit_tokens(self):
        self.prompt("Set skill tokens", "0",
                    lambda a, t: a.message(actions.set_skill_tokens(a.doc, int(t, 0))))

    def edit_add_car(self):
        self.prompt("Add car: enter CarId (ordinal)", "",
                    lambda a, t: a.message(actions.add_car_to_garage(a.doc, int(t, 0))))

    def edit_version_flags(self):
        self.prompt("Set VersionFlags (u32)", str(self.doc.versionflags or 0),
                    lambda a, t: a.message(actions.set_version_flags(a.doc, int(t, 0))))

    # ---- save / integrity ---------------------------------------------
    def integrity_text(self):
        d = self.doc
        lines = ["Game:      %s" % d.game_name,
                 "Save:      %s / %s / %s" % (d.saveset.title_id, d.saveset.slot, d.saveset.user),
                 "Revision:  0x%x" % d.rev.number,
                 "Commit:    %s" % d.commit.header,
                 ""]
        problems = d.verify()
        if problems:
            lines.append("Committed blob verification: %d problem(s)" % len(problems))
            lines += ["  - " + p for p in problems]
        else:
            lines.append("Committed blob verification: OK (all SHA-256 match)")
        if d.format == "FH3" and d.fh3 is not None:
            lines.append("")
            lines.append("FH3 sections (decrypted):")
            for name in ("profile", "savestate", "binary", "database"):
                lines.append("  %-9s %d bytes" % (name, len(d.fh3.sections[name])))
        lines.append("")
        lines.append("Pending changes (uncommitted):")
        changed = d.changed_blobs()
        if changed:
            for name in changed:
                lines.append("  - %s" % name)
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("Revisions present:")
        for r in d.saveset.revisions():
            lines.append("  0x%x" % r.number)
        return "\n".join(lines)

    def save(self):
        if not self.doc.is_dirty():
            self.message("Nothing to save (no changes)")
            return
        changed = self.doc.changed_blobs()
        try:
            newrev = self.doc.save()
        except Exception as exc:
            self.message("Save failed: %s" % exc)
            return
        # rebase the document onto the new revision
        compiled = self.doc.compile()
        self.doc.original = compiled
        self.doc.rev = newrev
        self.doc.commit = self.doc.saveset.read_commit(newrev)
        self.doc.mark_clean(compiled)
        self.message("Saved revision 0x%x (%s) — %d blob(s)"
                     % (newrev.number, newrev.path.name, len(changed)))

    def backup(self):
        import os
        from pathlib import Path
        base = Path(self.doc.saveset.revisions_dir).parents[1] / "backups"
        try:
            out = self.doc.saveset.backup_revision(self.doc.rev, base)
            self.message("Backed up to %s" % out)
        except Exception as exc:
            self.message("Backup failed: %s" % exc)

    # ---- main loop -----------------------------------------------------
    def run(self):
        # ncurses waits ESCDELAY milliseconds after a lone ESC to decide whether
        # it is the start of an escape sequence (arrow keys etc.).  The default
        # is 1000 ms, which makes every "go back" feel like a hang.  25 ms is
        # plenty for real terminals.  Override with FH2SAVE_ESCDELAY if needed.
        try:
            delay = int(os.environ.get("FH2SAVE_ESCDELAY", "25"))
        except ValueError:
            delay = 25
        try:
            curses.set_escdelay(max(1, delay))
        except (AttributeError, curses.error):
            pass
        curses.curs_set(0)
        self.stdscr.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
        except curses.error:
            pass
        while self.running:
            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()
            top = 2
            height = h - top - 2
            if height < 3:
                height = 3
            # header
            title = " FH2/FH3 Save Editor — rev 0x%x %s " % (
                self.doc.rev.number, "*DIRTY*" if self.doc.is_dirty() else "")
            attr = curses.A_REVERSE
            try:
                attr |= curses.color_pair(1)
            except curses.error:
                pass
            addstr(self.stdscr, 0, 0, clip(title.center(max(0, w)), w), attr)
            # body
            if self.stack:
                dims = (height, w, top, 0)
                if self._body is None or self._body_dims != dims:
                    try:
                        self._body = self.stdscr.subwin(*dims)
                        self._body.keypad(True)
                    except curses.error:
                        self._body = None
                    self._body_dims = dims
                sub = self._body
                if sub is not None:
                    sub.erase()
                    self.stack[-1].render(self, sub, 0, height, w)
            # footer
            view = self.stack[-1] if self.stack else None
            hint = view.footer(self) if view else ""
            if isinstance(hint, tuple):
                hint = hint[0]
            if self.prompt_active:
                label = "%s: " % self.prompt_label
                avail = max(1, w - len(label) - 1)
                start = 0
                if self.prompt_pos >= avail:
                    start = self.prompt_pos - avail + 1
                visible = self.prompt_buf[start:start + avail]
                addstr(self.stdscr, h - 2, 0, label + visible, curses.A_BOLD)
                addstr(self.stdscr, h - 1, 0,
                       clip("[←→] move  [Home/End]  [Ctrl-U] clear  [Enter] accept  [Esc] cancel", w))
                # Park the terminal cursor on the edit position (must be done
                # after all addstr calls, otherwise they move it again).
                try:
                    self.stdscr.move(h - 2, min(w - 1, len(label) + self.prompt_pos - start))
                    curses.curs_set(1)
                except curses.error:
                    pass
            elif self.confirm_active:
                addstr(self.stdscr, h - 2, 0, clip(self.confirm_text, w), curses.A_BOLD)
                addstr(self.stdscr, h - 1, 0, clip("[y] yes  [n] no", w))
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
            else:
                addstr(self.stdscr, h - 2, 0, clip(self.message_text, w), curses.A_DIM if hasattr(curses, 'A_DIM') else 0)
                addstr(self.stdscr, h - 1, 0, clip(hint, w))
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_RESIZE:
                continue
            if self.prompt_active:
                self._handle_prompt_key(key)
                continue
            if self.confirm_active:
                self._handle_confirm_key(key)
                continue
            if key == -1:
                continue
            # global hotkeys (prompts/confirms already handled above)
            if key in (ord("s"), ord("S"), 19, curses.KEY_F2):  # s/S/Ctrl-S/F2
                self.save()
                continue
            if key in (ord("q"), ord("Q")):
                self.request_quit()
                continue
            view = self.stack[-1] if self.stack else None
            if view:
                view.handle(self, key)

    def request_quit(self):
        if self.doc.is_dirty():
            self.confirm("Unsaved changes!  [y] discard and quit   [n] cancel",
                         lambda a: a.quit())
        else:
            self.quit()

    def _handle_prompt_key(self, key):
        buf = self.prompt_buf
        pos = self.prompt_pos
        if key in (curses.KEY_ENTER, 10, 13):
            self._finish_prompt(True)
        elif key == 27:
            self._finish_prompt(False)
        elif key in (curses.KEY_LEFT, 2):          # ← / Ctrl-B
            self.prompt_pos = max(0, pos - 1)
        elif key in (curses.KEY_RIGHT, 6):         # → / Ctrl-F
            self.prompt_pos = min(len(buf), pos + 1)
        elif key in (curses.KEY_HOME, 1):          # Home / Ctrl-A
            self.prompt_pos = 0
        elif key in (curses.KEY_END, 5):           # End / Ctrl-E
            self.prompt_pos = len(buf)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if pos > 0:
                self.prompt_buf = buf[:pos - 1] + buf[pos:]
                self.prompt_pos = pos - 1
        elif key == curses.KEY_DC:                 # Delete
            if pos < len(buf):
                self.prompt_buf = buf[:pos] + buf[pos + 1:]
        elif key == 21:                            # Ctrl-U: clear the line
            self.prompt_buf = ""
            self.prompt_pos = 0
        elif key == 11:                            # Ctrl-K: kill to end
            self.prompt_buf = buf[:pos]
        elif key == 23:                            # Ctrl-W: delete previous word
            i = pos
            while i > 0 and buf[i - 1] == " ":
                i -= 1
            while i > 0 and buf[i - 1] != " ":
                i -= 1
            self.prompt_buf = buf[:i] + buf[pos:]
            self.prompt_pos = i
        elif 32 <= key < 127:
            self.prompt_buf = buf[:pos] + chr(key) + buf[pos:]
            self.prompt_pos = pos + 1

    def _handle_confirm_key(self, key):
        if key in (ord("y"), ord("Y")):
            cb = self.confirm_cb
            self.confirm_active = False
            if cb:
                cb(self)
        elif key in (ord("n"), ord("N"), 27):
            self.confirm_active = False


def run(stdscr, savesets, index=0):
    App(stdscr, savesets, index).run()
