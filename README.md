# Forza Save Editor (FH2 / FH3)

An intuitive, dependency-free (stdlib-only) **Python curses TUI** for viewing and
modifying **Forza Horizon 2** and **Forza Horizon 3** (Xbox One) save files, plus a
scriptable CLI.

It understands the Xbox One "Connected Storage" revision store and the blobs inside
it, including FH3's TFIT-encrypted `ProfileData`:

| blob | FH2 | FH3 |
|---|---|---|
| `ProfileData`   | full read/write (credits, XP, stats, settings, locale) | full read/write (nested property bag + BXML + binary + SQLite sections) |
| `SaveState`     | full read/write (any object property) | stored inside `ProfileData` (BXML; full read/write) |
| `PlayerDatabase`| full read/write (SQLite: garage, races, unlocks, perks…) | stored inside `ProfileData` (SQLite; full read/write) |
| `BinarySaveState` | read-only viewer (drivatars, road bitmap, radio) | stored inside `ProfileData` (read-only viewer) |
| `VersionFlags`  | read/write (plain u32) | read/write (TFIT-encrypted u32) |
| `commit`        | verified + regenerated (SHA-256) | verified + regenerated (SHA-256) |

Writes always go to a **new revision folder** with a freshly hashed `commit`, so the
previous revision is never overwritten.

---

## Install

A ready-to-install Arch/CachyOS package is built from this tree:

```sh
./build-package.sh          # produces fh2save-<version>-<pkgrel>-any.pkg.tar.zst
sudo pacman -U fh2save-1.1.2-1-any.pkg.tar.zst
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

The editor detects the game from the save contents (FH2 `ssmc` profile magic, or an
FH3 TFIT container with a valid header MAC). The title ID is only used as a fallback.

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

* **ProfileData** — every editable leaf in the profile. FH2 shows flat record names;
  FH3 shows the full path (e.g. `Main/Credits`, `MiscStats/...`). Ints, u64s, floats,
  bools, strings and vectors can all be changed. Type a value and press Enter;
  `Ctrl-U` clears the field.
* **SaveState** — browse every game object and open one to edit any of its properties
  (world position, radio, tombola seed, reward boards, danger signs/drift zones,
  dialogue flags, barn-find state, …).
* **PlayerDatabase** — browse all SQLite tables. Open a table → open a row → edit any
  column. `c` clones a row (handy for adding cars), `d` deletes a row.
* **BinarySaveState** — read-only report: object list, types and sizes.
* **VersionFlags** — the 32-bit save schema stamp (FH3: decrypted/encrypted
  transparently).
* **Quick actions** — one-keystroke helpers (below).
* **Integrity / commit** — SHA-256 verify, FH3 section sizes and the pending-changes list.

### Quick actions

* **MAX FH3 progression** — one entry that applies the full preset below.
* Set credits / money, XP, driver level, skill points and skill tokens; **MAX money**.
* Complete all **speed traps**, **speed zones**, **danger signs** and **drift zones**,
  or all PR stunts in one go.  FH3 stores these as `CameraState`,
  `DangerSignState` and `DriftZoneState` objects; the action sets `Completed` and a
  high `PersonalBest`.
* Unlock all reward boards and landmarks.
* Build every festival site at **level 5** and raise fans to 10,000,000 (FH3).
* Discover or complete all bucket-list challenges.  FH3 keeps these in the binary
  `BucketListChallengeState` object (the SQLite table is normally empty).
* Mark all dialogue seen/played.
* Complete all career events and races.  FH3 keeps these in the binary `CareerState`
  object, not in `Career_EventResults`/`Career_RaceResults`.
* Discover all map content (event, stunt and landmark components) and refresh the
  completion statistics shown in-game.
* Unlock/restore all barn finds, **add a car to the garage (clone)**, and reset all
  garage tuning to stock.

Actions are format-aware: the same menu works on FH2 and FH3, using the correct object
types and tables for each game.

---

## CLI usage

```
fh2save list                       # list discovered saves + revisions
fh2save info                       # verify hashes, show blob/section summary
fh2save dump ProfileData           # dump a blob
fh2save dump SaveState
fh2save dump PlayerDatabase        # alias: Database
fh2save dump BinarySaveState
fh2save set credits 5000000        # set a well-known value
fh2save set xp 999999
fh2save set level 999
fh2save set skillpoints 100000
fh2save set skilltokens 50
fh2save set versionflags 4
fh2save action speedtraps          # run a quick action by name
fh2save addcar 1234                # clone a garage car with a new CarId
fh2save selftest                   # round-trip sanity checks
```

Useful flags: `--root DIR`, `--save N`, `--rev 0x140`, `--search`, and `--dry-run`
on the mutating subcommands (shows what would change without writing). The global
options may be placed before *or* after the subcommand.

Available `action` names: `maxmoney`, `speedtraps`, `speedzones`, `dangersigns`,
`driftzones`, `prstunts`, `boards`, `landmarks`, `festivals`, `bucketslots`,
`discoverall`, `dialogue`, `bucketlist`, `raceresults`, `maxprogression`,
`barnfinds`, `stocktuning`.

`selftest` on an FH3 save checks: commit hashes, TFIT decrypt→encrypt byte equality,
the four ProfileData sections, the binary progression objects, BXML round-trip,
VersionFlags, the SQLite database and the clean-tree state.

---

## Format reference

* [`docs/ForzaHorizon2_XboxOne_Save_Format.md`](docs/ForzaHorizon2_XboxOne_Save_Format.md)
* [`docs/ForzaHorizon3_XboxOne_Save_Format.md`](docs/ForzaHorizon3_XboxOne_Save_Format.md)
* [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) — crypto key/table and format
  research attribution.

The short version:

### Container

```
titles/<TITLEID>/saves/<slot>/User_<XUID-hex>/revisions/<16-hex>/
    commit          text: header, "blobs N", then "<sha256> <size> <name>" per blob
    data/<blob>
```

`commit` header is `Azimuth complete save revision v2`. Writes create the next
`<16-hex>` folder with a full snapshot and recomputed hashes.

### FH2 ProfileData

```
"ssmc"                  magic
u32  header_a           observed 0x000033b3
u32  header_b           observed 0x00000013
records..., then an opaque trailing table (preserved verbatim)
```

Record: `u32 nameLen | name | 0x20 | u32 0 | u32 type | value[typeSize]`.

### FH3 ProfileData

TFIT container → four sections (`profile`, `savestate`, `binary`, `database`).
`profile` is a nested property bag; `savestate` is BXML; `binary` is a read-only
object dictionary; `database` is bare SQLite. Full details are in the format doc.

### FH2 PlayerDatabase

SQLite 3 database prefixed with 8 bytes (`ssmc` + 4). 42 tables; the garage is
`Career_Garage` (124 columns/car including a full physics & tuning snapshot).
FH3 databases have no prefix; the SQLite header is auto-detected.

### FH2 SaveState

XML `ObjectDictionary` with `<Object Id= Type=>` / `<Property Name= Value=/>`.
Edits are done in-place so CRLF, indentation and self-closing tags are preserved.

---

## Safety

* Never writes over an existing revision; each save produces a new one.
* `commit` hashes are recomputed on write, so `fh2save info` stays "Verify: OK".
* An unmodified FH3 document re-encrypts to byte-identical blobs, so the editor
  reports "clean" until you actually change something.
* Take a backup anyway (the TUI has a **Backup** action, or copy the `revisions/`
  folder) — this is a fan-made tool with no affiliation to Turn 10 / Playground /
  Microsoft. Keep your original save and test on a copy first.

## AI usage disclaimer

This project was created with the use of **DeepSeek V4.1 Flash**, an AI coding
assistant. Basic features (such as editing credits) have been tested, but the project
has not been thoroughly tested. It should work, but no guarantee is made. The software
is provided under the MIT License, "as is", without warranty of any kind, and the author
accepts no liability for any damage or loss arising from its use. See
[`AI_USAGE.md`](AI_USAGE.md) and [`LICENSE`](LICENSE) for details.

## License

MIT — see `LICENSE`. Copyright (c) 2026 KaidenAC.
