# Forza Horizon 3 (Xbox One) save format notes

These notes describe what this editor relies on when reading and writing FH3
"Connected Storage" saves.  They are sanitised: no real account names, XUIDs,
key bytes or save values are included.

Title ID used by the retail Xbox One build: `4CE1DFAB`.

FH3 uses the same revision-store layout as FH2 (see
[`ForzaHorizon2_XboxOne_Save_Format.md`](ForzaHorizon2_XboxOne_Save_Format.md)):

```
titles/4CE1DFAB/saves/<slot>/User_<XUID-hex>/revisions/<16-hex>/
    commit
    data/ProfileData
    data/VersionFlags
```

The commit manifest header and hashing rules are unchanged: `Azimuth complete
save revision v2`, then `<sha256> <size> <name>` for each blob.  Unlike FH2,
an FH3 revision normally contains only two blobs, and **both are encrypted**.

---

## 1. TFIT container

FH3 profiles use Arxan TransformIT ("TFIT") encryption.  All integers are
little-endian.

```
u8[16]  iv
u32     padding_size
u8[16]  header_mac
repeat:
    u8[block_size]  encrypted data block
    u8[16]          encrypted block MAC
```

For `ProfileData` and `VersionFlags`, `block_size = 0x200`.

* `padding_size = (-plaintext_size) mod block_size`.
* `data_size = plaintext_size + padding_size`; the last data block is zero
  padded to `block_size`.
* `header_mac = MAC(u32(data_size) || iv || u32(padding_size))`.
* The per-block MAC is computed over the **plaintext** data block (including
  the zero padding of the final block), then encrypted and appended.  It also
  participates in the cipher chain for the following block.
* Data blocks are chained CBC-style: the first plaintext block is XORed with
  the IV; each following block is XORed with the previous ciphertext *data*
  block, except that after the MAC block of a unit the MAC ciphertext becomes
  the chain value.
* The TFIT cipher has 17 rounds for data and 13 rounds for the MAC.  The first
  two and last rounds use the "A" column order; the middle rounds use one of
  two "B" column orders (encryption and decryption differ).

The editor implements this in pure Python (`fh2save/fh3crypto.py`).  It does
not ship or invoke an external crypto binary.  The key/table resource is
`fh2save/data/fh3_tfit.bin` (see `THIRD_PARTY_NOTICES.md`).

### Context

The FH3 Profile context (used for both `ProfileData` and `VersionFlags`) is:

```
game       = 6   (FH3)
key type   = 0   (Profile)
container  = 0
block size = 0x200
table set  = 1   ("fh3")
```

The resource stores the 17 decryption round keys, the 13 MAC round keys, the
17 encryption round keys, and three table groups (encryption, decryption and
MAC).  Each group is a pool of 84 tables plus a 272/208-entry selection array;
the selection is what maps round/sub-table positions to pool entries.  Storing
the pool plus the selection keeps the resource around 260 KiB instead of
duplicating each selected table.

### Stable re-encryption

When a save is loaded the editor keeps the original container IV and padding.
Re-encrypting unchanged plaintext therefore reproduces the original blob
exactly, so an unmodified document is not reported as "dirty".  When the
plaintext size changes the padding is recomputed and the same IV is reused.

---

## 2. Decrypted ProfileData

The plaintext is a sequence of four sections:

```
u32 name_hash
u32 size
u8[size] data
```

The hashes are `CHashName(name, toLower=0, seed=0x1505)` (two passes over the
name).  The observed order is:

| section | hash | contents |
|---|---|---|
| `profile` | `0x4A8BF2B6` | property bag + two trailing hash sets |
| `savestate` | `0xB60261FC` | BXML object dictionary |
| `binary` | `0x986CA5CB` | binary state dictionary (read-only here) |
| `database` | `0xA9F1F729` | embedded SQLite 3 database |

The editor validates the section hashes, parses each section, and rebuilds the
container with unchanged section bytes where possible.

### 2.1 Property bag

```
u32 count
repeat count:
    u8  case_sensitive
    i32 num_bits
    i32 name_len
    u8[name_len] name (UTF-8)
    i32 type
    value
```

`value` depends on `type`:

| type | name | encoding |
|---:|---|---|
| 0 | bool | u8 (0/1) |
| 1 | u8 | u8 |
| 2 | u16 | u16 |
| 3 | u32 | u32 |
| 4 | u64 | u64 |
| 5 | i8 | i8 |
| 6 | i16 | i16 |
| 7 | i32 | i32 |
| 8 | i64 | i64 |
| 9 | f32 | f32 |
| 10 | f64 | f64 |
| 11 | narrow string | i32 byte length + UTF-8 bytes |
| 12 | wide string | i32 code-unit count + UTF-16LE |
| 13 | matrix | 16 × f32 |
| 14 | vector | 4 × f32 |
| 15 | property bag | nested bag (same layout) |
| 16 | database property bag | nested bag (seen only in later titles) |
| 17 | u32 "obfuscated" | u32 (plain in FH3) |

In FH3 the type-17 fields (`Main/Credits`, `Main/XP`) are stored as ordinary
32-bit integers.  The editor treats them as u32.

The `profile` section ends with two sets, each encoded as `u32 count` followed
by `count × u32` hashes.  They are not interpreted; they are preserved
verbatim.

Example paths from a real FH3 profile (names only, no values):

```
Main/TotalCredits        u64
Main/Credits             u32 (type 17)
Main/TotalWinnings       u32
Main/Level               u32
Main/TotalXP             u64
Main/XP                  u32 (type 17)
Main/NumSkillTokens      u32
Main/TotalSkills         u64
MiscStats/...            various counters
CompareStats/...         per-discipline statistics
```

### 2.2 BXML save state

The `savestate` section is "Binary XML":

```
"BXML"
u8   version (2 in FH3)
i32  string_count
i32  string_table_size
repeat string_count: i16 len + utf8 bytes
u8   flag
node root
```

Node:

```
u8  flags           (1 = node, 2 = has attributes, 4 = has children)
idx name
if flags & 2: u8 count, then count × (idx key, idx value)
if flags & 4: i16 count, then count × node
```

`idx` is 1, 2 or 4 bytes depending on `string_count` (FH3 uses 2 bytes).  The
root is `ObjectDictionary`; each `Object` has `Id` and `Type` attributes and
`Property` children with `Name` and `Value` attributes.  Editors mutate the
attribute value index; new values are appended to the string table and reused
when already present.  An unmodified document serialises byte-for-byte.

### 2.3 Binary state

The `binary` section is an object dictionary:

```
u32 count
repeat count:
    u32 id_len + id (UTF-8)
    u32 type_len + type (UTF-8)
    u32 hash
    u32 data_size
    u8[data_size] data
    i32 index
```

Object order, stored hashes, indices and any unconsumed trailing bytes are
preserved.  The editor parses the progression objects listed below and
re-serialises them byte-for-byte when their state has not changed.

### 2.4 Database

The `database` section is a bare SQLite 3 file (`SQLite format 3\0` at offset
0).  FH2 databases carry an 8-byte prefix; FH3 does not.  The editor detects
the SQLite header at offset 0 or 8, so the same database code works for both
games.  FH3 tables include `Career_Garage`, `BarnFinds`, `BucketListProgress`,
`Career_RaceResults`, `Career_PurchasedParts`, `ChangeTracking`, and various
progress/unlock tables.

### 2.5 Authoritative progression objects

Career, bucket-list, discovery and festival progress is **not** stored in the
SQLite result tables.  A genuine 95%-complete save has `Career_EventResults`,
`Career_RaceResults`, `BucketListProgress` and `CareerRaceCollections` empty;
the authoritative state lives in the binary section and in `Stats` /
`CompareStats`.  The layouts below were reverse-engineered from that reference
save; all integers are little-endian.

#### `CareerState`

```
u32 version (2)
u32 count
count × u32                   field 1  (campaign tier counters)
u32 count
count × u32                   field 2  (mirror of field 1 in observed saves)
u32 count
count × (u32 event, u32 times_completed, u32 best_place)   field 3
u32 count
count × (u32 event, u32 times_completed, u32 best_place)   field 4
u32 count
count × u32                   field 5  (championship/collection IDs)
u32 count
count × u32                   field 6  (related ID list)
remaining u32s                opaque tail, preserved verbatim
```

The event IDs in fields 3/4 cover base-game events (`1`–`610`), expansion
events (`16777217`+, i.e. `0x01000001`+) and championship collections
(`33554432`+, i.e. `0x02000000`+).

#### `BucketListChallengeState`

```
u32 version (2)
u32 count
count × 14-byte record:
    u32 challenge_id
    u32 unknown
    u8[6] flags        (completed, attempted, viewed, …)
remaining bytes        second list, preserved verbatim
```

Base-game challenge IDs are `67`–`96`; Blizzard Mountain and Hot Wheels add
`97`–`108`.  The reference save also contains a sentinel record with ID
`0xFFFFFFFF`.

#### `DiscoveryState`

```
u32 version (1)
u32 count
count × entry:
    u16 flags
    u32 name_hash
    u32 name_len + UTF-8 name
    u8  discovered (1)
```

Entries are map components (`*_discovery_component`) and numbered slots
(`slot_N_discovery`).  The reference save has 356 entries.

#### `CampaignSlotsState`

```
u32 version (1)
u32 core_count
core_count × entry:
    u16 flags (1)
    u32 name_hash
    u32 name_len + UTF-8 name       e.g. slot_2_core
    u8  state                       (1 = expanded)
    u32 value (1)
u32 race_count
race_count × entry:
    u16 flags (1)
    u32 name_hash
    u32 name_len + UTF-8 name       e.g. slot_48_modified_race_collection
    u32 collection_ref
remaining bytes                      preserved verbatim
```

The reference save has 70 core entries (13 with `state = 1`) and 45 race
entries.  The stored name hashes do **not** match the editor's generic
`CHashName` helper, so the bundled hash values are used verbatim.

#### `iestate`

```
u32 version (1)
u32 count
count × entry:
    u32 name_len + UTF-8 name
    u8  value (1)
```

This holds tutorial/introduction flags such as `IntroducedANNA`.

#### `Stats`

```
u32 version (1)
u32 count
count × entry:
    u16 flags
    u32 name_hash
    u32 name_len + UTF-8 name
    u32 value_len + UTF-8 value (decimal string)
```

`Stats` holds the counters the game uses for records and completion, including
`TotalUniqueCompleted`, `TotalCompleted`, `TotalDiscovered`,
`RacesUniqueCompleted`, `BucketListsUniqueCompleted`,
`CampaignSlotExhibitionsCompleted`, `CampaignSlotChampionshipsCompleted`,
`TotalFestivalsBuilt/Activated/Upgraded` and `RoadsDiscovered`.  The same
values are mirrored into the profile's `CompareStats/` bag, including
`ProgressToFinalShowcase` (100 in the reference save).

### 2.6 Other progression fields used by the quick actions

FH3 also keeps stunt and festival state in the BXML save state:

| Progress | Store | Field(s) |
| --- | --- | --- |
| Speed traps and speed zones | BXML `CameraState` (`speed_trap_*`, `speed_zone_*`) | `Completed`, `PersonalBest` |
| Danger signs | BXML `DangerSignState` | `Completed`, `PersonalBest` |
| Drift zones | BXML `DriftZoneState` | `Completed`, `PersonalBest` |
| Reward boards | BXML `DiscountBoardSaveState` | `State = Collected` |
| Festival sites | BXML `FestivalSiteState` | `Activated`, `Built`, `Level` (max 5) |
| Fans | BXML `CurrencyBucket_Fans_*` | `Total` |

The quick actions edit the binary progression objects above, not the empty
SQLite result tables.  `fh2save/data/fh3_progress.json` contains the
game-internal identifiers, names, hashes and completed counter values derived
from the reference save (no account data); see `THIRD_PARTY_NOTICES.md`.

The reference save is a genuine 95%-complete save, not a literal 100% save:
some championships and DLC events remain incomplete.  Importing its values
therefore cannot guarantee an exact 100% display in every game build.


---

## 3. Editing and writing

* Every edit is made in memory on parsed models.
* Saving writes a **new** revision folder; existing revisions are never
  overwritten.
* `ProfileData` is rebuilt from the four sections, then re-encrypted with the
  original IV (and original padding when the size is unchanged).
* `VersionFlags` is re-encrypted in the same way.
* The commit manifest is regenerated with SHA-256 for every blob.

The editor was tested with a save copy: TFIT decryption/encryption is
byte-exact, the property bag and BXML round-trip exactly, credits/XP/skill
edits survive a decrypt with an independent tool, and the game database edits
(e.g. barn-find state) are visible in the written revision.
