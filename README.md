# FH2 Save Editor

An intuitive, dependency-free (stdlib-only) **Python curses TUI** for viewing and
modifying **Forza Horizon 2 (Xbox One)** save files, plus a scriptable CLI.

It understands the Xbox One "Connected Storage" revision store, and every blob inside it:

| blob | support |
|---|---|
| `ProfileData`   | full read/write (credits, XP, stats, settings, locale) |
| `SaveState`     | full read/write (any object property) |
| `PlayerDatabase`| full read/write (SQLite: garage, races, unlocks, perks…) |
| `BinarySaveState` | read-only viewer (drivatars, road bitmap, radio) |
| `VersionFlags`  | read/write |
| `commit`        | verified + regenerated (SHA-256) |

Writes always go to a **new revision folder** with a freshly hashed `commit`, so the
previous revision is never overwritten.

---

## Install

A ready-to-install Arch/CachyOS package is built from this tree:

```sh
./build-package.sh          # produces fh2save-<version>-<pkgrel>-any.pkg.tar.zst
sudo pacman -U fh2save-1.0.0-4-any.pkg.tar.zst
```

Then run it from anywhere:

```sh
fh2save --root /path/to/folder-containing-titles/
```

Or run it straight from the source tree without installing:

```sh
python3 -m fh2save --root /path/to/save-root
```

The `--root` is the folder that contains `titles/` (e.g. the folder this repo lives in).
If omitted it defaults to the current directory. Discovery is **literal** — only
`<root>/titles` is inspected, so the editor never silently opens a save from a
parent/sibling folder. To look a bit deeper, add `--search`.

---

## Using the TUI

```
s / S / F2  save changes as a new revision
b / B       back up the current revision
q / Q       quit (asks first if there are unsaved changes)
↑/↓ j/k     move           Enter   open / edit
/           filter the current list
←/→         move the cursor inside the edit/filter line
Home / End  jump to the start / end of the line
Ctrl-U      clear the line   Ctrl-W  delete previous word
Esc         back one level
```

(Letter hotkeys accept either case: `q` and `Q` both quit, `s` and `S` both save.)

> Escape is detected with a 25 ms timeout instead of ncurses' 1000 ms default, so
> going back a level is instant. If you ever need a different value, set
> `FH2SAVE_ESCDELAY` (milliseconds).

Sections on the main menu:

* **ProfileData** — every key/value record. Editable ones are marked with a space
  (`·` = container, not directly editable). Ints, u64s, floats, bools, enums and
  strings can all be changed. Type a value and press Enter; `Ctrl-U` clears the field.
* **SaveState** — browse all 350+ game objects; open one to edit any of its properties
  (world position, radio, tombola seed, reward boards, speed traps/zones, dialogue
  flags, barn-find state, …).
* **PlayerDatabase** — browse all SQLite tables. Open a table → open a row → edit any
  column. `c` clones a row (handy for adding cars), `d` deletes a row.
* **BinarySaveState** — read-only report: object list, extracted gamertags.
* **VersionFlags** — the 32-bit save schema stamp.
* **Quick actions** — one-keystroke helpers (below).
* **Integrity / commit** — SHA-256 verify and the pending-changes list.

### Quick actions

Set credits, set XP/wristband, set skill points, set skill tokens, **MAX money**,
unlock all speed traps / speed zones / reward boards, discover all bucket-list slots,
mark all dialogue seen, complete all bucket-list challenges, set all race results to
1st, unlock/restore all barn finds, **add a car to the garage (clone)**, and reset all
garage tuning to stock.

---

## CLI usage

```
fh2save list                       # list discovered saves + revisions
fh2save info                       # verify hashes, show blob summary
fh2save dump ProfileData           # dump a blob (ProfileData|SaveState|PlayerDatabase|BinarySaveState)
fh2save set credits 5000000        # set a well-known value
fh2save set xp 999999
fh2save set skillpoints 100000
fh2save set skilltokens 50
fh2save set versionflags 6
fh2save action speedtraps          # run a quick action by name
fh2save addcar 1234                # clone a garage car with a new CarId
fh2save selftest                   # round-trip sanity checks
```

Useful flags: `--root DIR`, `--save N`, `--rev 0x140`, `--search`, and `--dry-run`
on the mutating subcommands (shows what would change without writing). The global
options may be placed before *or* after the subcommand.

Available `action` names: `maxmoney`, `speedtraps`, `speedzones`, `boards`,
`bucketslots`, `dialogue`, `bucketlist`, `raceresults`, `barnfinds`, `stocktuning`.

---

## Format reference (what the editor relies on)

The full reverse-engineering write-up is in
[`docs/ForzaHorizon2_XboxOne_Save_Format.md`](docs/ForzaHorizon2_XboxOne_Save_Format.md).
The short version:

### Container

```
titles/<TITLEID>/saves/<slot>/User_<XUID-hex>/revisions/<16-hex>/
    commit          text: header, "blobs N", then "<sha256> <size> <name>" per blob
    data/<blob>
```

`commit` header is `Azimuth complete save revision v2`. Writes create the next
`<16-hex>` folder with a full snapshot and recomputed hashes.

### ProfileData

```
"ssmc"                  magic
u32  header_a           observed 0x000033b3
u32  header_b           observed 0x00000013
records..., then an opaque trailing table (preserved verbatim)
```

Record: `u32 nameLen | name | 0x20 | u32 0 | u32 type | value[typeSize]`.

| type | meaning | size |
|---:|---|---|
| 0x00,0x01 | bool / enum8 | 1 |
| 0x03,0x07 | int32 | 4 |
| 0x04 | u64 | 8 |
| 0x09 | float32 | 4 |
| 0x0C | wstring (u32 charCount + UTF-16LE) | variable |
| 0x0F | container (child count) | 4 |

### SaveState

XML `ObjectDictionary` with `<Object Id= Type=>` / `<Property Name= Value=/>`.
Edits are done in-place so CRLF, indentation and self-closing tags are preserved.

### PlayerDatabase

SQLite 3 database prefixed with 8 bytes (`ssmc` + 4). 42 tables; the garage is
`Career_Garage` (124 columns/car including a full physics & tuning snapshot).

### BinarySaveState

Binary object dictionary using absolute offsets → treated as read-only.

---

## Safety

* Never writes over an existing revision; each save produces a new one.
* `commit` hashes are recomputed on write, so `fh2save info` stays "Verify: OK".
* Take a backup anyway (the TUI has a **Backup** action, or copy the `revisions/`
  folder) — this is a fan-made tool with no affiliation to Turn 10 / Playground /
  Microsoft.

## AI usage disclaimer

This project was created with the use of **DeepSeek V4.1 Flash**, an AI coding
assistant. Basic features (such as editing credits) have been tested, but the project
has not been thoroughly tested. It should work, but no guarantee is made. The software
is provided under the MIT License, "as is", without warranty of any kind, and the author
accepts no liability for any damage or loss arising from its use. See
[`AI_USAGE.md`](AI_USAGE.md) and [`LICENSE`](LICENSE) for details.

## License

MIT — see `LICENSE`.
