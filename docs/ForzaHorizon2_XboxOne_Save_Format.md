# Forza Horizon 2 (Xbox One) — Save Data Format Write‑up

*Analysis of a sample Forza Horizon 2 Xbox One save set. Date of analysis: 2026‑10‑18.*

This document reverse‑engineers how a single Forza Horizon 2 Xbox One save is laid out on
disk, and — more importantly for the question asked — **what each file stores and how it
encodes it**. Everything below was derived directly from the two revisions in the sample
save set; verified facts are stated plainly and inferences are marked as *likely*.

---

## 1. What is in the folder

The save is stored in the standard Xbox One / Xbox Live "Connected Storage" layout:

```
titles/
  1A96545B/                         <- Title ID (the game)
    saves/
      player-1/                     <- save slot ("player-1")
        User_<XUID-hex>/         <- owner XUID, hex (see §9)
          revisions/
            000000000000013f/       <- revision 0x13F (319)
              commit                <- text manifest (hashes + metadata)
              data/
                BinarySaveState
                PlayerDatabase
                ProfileData
                SaveState
                VersionFlags
            0000000000000140/       <- revision 0x140 (320, newest)
              commit
              data/ ... (same five blobs)
```

* **Title ID `1A96545B`** is the game identity as the console/cloud sees it.
* Each **revision folder** (`0x13F`, `0x140`) is a *complete snapshot* of the five data
  blobs, not a delta. The `commit` file is what makes revisions addressable and verifiable.
* Both revisions contain the same five blobs:

| blob | size (bytes) | notes |
|---|---:|---|
| `ProfileData`   | 20,488 | binary key/value "profile" (stats + settings) |
| `SaveState`     | 70,245 | XML `ObjectDictionary` |
| `BinarySaveState` | 112,875 | binary `ObjectDictionary` |
| `PlayerDatabase`| 6,291,464 | embedded **SQLite 3** database |
| `VersionFlags`  | 4 | single little‑endian u32 |

---

## 2. Container layer — the `commit` manifest

`commit` is plain UTF‑8/LF text. It names the save system, a revision scheme, a blob count,
and a **SHA‑256 digest for every blob**:

```
Azimuth complete save revision v2
blobs 5
<sha256> 112875 BinarySaveState
<sha256> 6291464 PlayerDatabase
<sha256> 20488 ProfileData
<sha256> 70245 SaveState
<sha256> 4 VersionFlags
```

Line format: `<sha256-hex> <size> <filename>`.

I re‑computed `sha256sum` for all five blobs in revision `0x140` and **all five matched**, so
the manifest is a straight integrity/identity record — it is *not* encrypted and *not* a
signature. The header string `Azimuth complete save revision v2` is the internal name of the
save system ("Azimuth", revision format v2).

Implications:

* The console can tell which blobs changed between revisions without diffing (compare hashes).
* If even one byte changes, the corresponding blob's hash changes, which is exactly what the
  `0x13F → 0x140` transition shows (§8).
* There is no per‑blob compression or crypto anywhere in these files — every blob is stored
  raw, which is why the contents are directly readable/debuggable.

---

## 3. `ProfileData` — the binary key/value profile

### 3.1 Header

```
73 73 6d 63   b3 33 00 00   13 00 00 00   ...
"ssmc"         0x000033b3      0x00000013
```

* 4‑byte ASCII magic **`ssmc`** (also used by `PlayerDatabase`, see §6).
* Two little‑endian u32 header words. For this file they are `0x33B3` (13235) and `0x13`
  (19). Their exact meaning is unclear (*likely* a section size/flag and a version/count);
  parsing does not depend on them, so the record stream starts at offset `0x0C`.

### 3.2 Record encoding

From offset `0x0C` the file is a flat stream of self‑describing records, byte‑packed with no
alignment:

```
u32   nameLen
char  name[nameLen]        ; ASCII, no NUL
u8    0x20                 ; separator/pad byte observed on every record
u32   reserved = 0
u32   type                 ; value type tag (see table)
u8    value[typeSize]      ; little-endian payload
```

Example (`RewindOnBack`, a controller setting, = 0 / "off"):

```
0c 00 00 00 | 52 65 77 69 6e 64 4f 6e 42 61 63 6b | 20 | 00 00 00 00 | 07 00 00 00 | 00 00 00 00
 nameLen=12   "RewindOnBack"                           reserved       type=7(int)    value=0
```

A record can be a **container** (type `0x0F`) whose value is the number of children that
follow it; e.g. `BristolOptions` (type `0x0F`, value `6`) is followed by six child records
(`RewindOnBack`, `RumbleSetting`, `InvertHandbrakeClutch`, `Layout`, `InvertGearUpDown`,
`InvertCameraLookBack`), then `Main`, `Options`, etc.

### 3.3 Observed type tags

| type | meaning | value size | example |
|---:|---|---|---|
| `0x00` | boolean | 1 | `IsXPIntroduced = 1` |
| `0x01` | 8‑bit enum/bool | 1 | `InitialExperienceState = 8`, `Braking = 1` |
| `0x03` | int32 | 4 | `NumSkillTokens = 5` |
| `0x04` | 64‑bit value | 8 | `Flags`, `RivalsCompletionTracking`, `UpTime` |
| `0x07` | int32 (settings) | 4 | `Layout = 0` |
| `0x09` | IEEE‑754 float32 | 4 | `Gamma = 0.6`, `BiggestAir = 2.0257` |
| `0x0C` | string | `u32 charCount` + UTF‑16LE | `KinectLocaleLastUsed = "en-NZ"` |
| `0x0F` | container/group | 4 (child count) | `BristolOptions = 6` |

A full parse of the record stream yields **357 records** and stops cleanly at offset
`0x2EDF`. Both the field offsets and the value sizes round‑trip exactly to that boundary, so
the encoding above is believed correct.

### 3.4 What it actually stores

The profile is a mix of **settings** and **aggregate player statistics**. Selected decoded
values for this save:

| property | type | value |
|---|---|---:|
| `Credits` | int | **495548** |
| `TotalWinnings` | int | **495548** |
| `XP` | int | 123548 |
| `WristbandLevel` | int | 123548 (same counter as XP here) |
| `GarageValue` | int | 425000 |
| `CarsInGarage` | int | 4 |
| `RoadsDiscovered` | int | 66 |
| `TimeDriven` | int | 4233 |
| `TotalCollisions` | int | 115 |
| `NumSkillTokens` | int | 5 |
| `PerksUnlocked` | int | 1 |
| `HighestSkillScore` | int | 48510 |
| `ShowcasesWonTotal` | int | 1 |
| `HorizonFinalProgress` | int | 6 |
| `BiggestAir` | float | 2.0257 |
| `LongestJump` | float | 89.19 |
| `Gamma` | float | 0.6 |
| `KinectLocaleLastUsed` | string | `en-NZ` |

Settings groups visible by name: `BristolOptions` (Xbox One controller), `ControllerOptions`,
`WheelOptions`, `WheelAdvancedOptions`, `BristolAdvancedOptions`,
`ControllerAdvancedOptions` (all the deadzones/rumble/force‑feedback floats), `Options`
(ghosts, units, HUD toggles: `Speedometer`, `Map`, `Mirror`, `DriftHud`, `CameraAngle`, …),
`CompareStats`, and stat buckets `Main` and `MiscStats` (`CarsInGarage`, `RoadsDiscovered`,
`TotalWinnings`, `PhotoChallengesCompleted`, `BucketlistEventsCompleted`, …).

There are also `V0`…`V6` entries (type `0x04`, 8‑byte values) that look like versioned
id/hash slots for DLC/version tracking.

### 3.5 Trailing section (0x2EDF → end of file)

After the key/value stream there is a second, differently structured region (~8.5 KB):

* A **fixed‑stride table** of 24‑byte rows (e.g. rows built from `0x0BB8`=3000,
  `0x07D0`=2000, `0x1770`=6000 ids, small enums, and `0xFFFF`/`-1` sentinels). These look
  like per‑event / per‑rival progress records.
* A long run of repeated sentinel rows: `00 00 00 FF*12 00*9`, i.e. a table of mostly
  "unset" entries.
* The file ends with ~2 KB of zero padding.

This region is separate from the key/value profile and appears to be a progress/leaderboard
side‑table; its exact row semantics were not fully decoded.

---

## 4. `SaveState` — the XML object dictionary

`SaveState` is a readable XML document (CRLF line endings, UTF‑8), beginning directly with
`\r\n<ObjectDictionary>` and ending `</ObjectDictionary>`:

```xml
<ObjectDictionary>
  <Object Id="BucketListState" Type="BucketListState">
    <Property Name="LastActiveForMainland" Value="1"/>
    <Property Name="LastActiveForIsland" Value="-1"/>
    <Property Name="LastNumberOfChallenges" Value="63"/>
  </Object>
  ...
</ObjectDictionary>
```

Shape: **353 `<Object>` elements** (349 with a closing tag + 4 self‑closing such as
`<Object Id="GameDVRState" Type="GameDVRState"/>`), **820 `<Property>` entries**, and
**165 distinct property names.**
Each object has an `Id` (instance name) and a `Type` (class). This is a classic
"save‑game object graph serialized to XML".

Type histogram (the important ones):

| Type | count | what it holds |
|---|---:|---|
| `DiscountBoardSaveState` | 150 | reward boards (`travel_*`, `xp_a/b/c_*`) — `State="Discovered"` |
| `DialogueSaveState` | 86 | `DIALOGUE_*` "seen once" flags (`Seen="true"`) |
| `CameraState` | 45 | speed traps (`speed_trap_01..30`) and speed zones (`speed_zone_01..15`): `Discovered/Completed/PersonalBest` |
| `BucketListSlotState` | 30 | bucket‑list slot discovery (`bucket_list_slot_*`) |
| `BarnFindState` | 11 | `barn_find_01..10` + `pdlc_barn_find_01` (`State`, `TimeAtDiscovery`, …) |
| `TutorialSaveState` | 4 | `Seen` flags |
| `GameTimeState` | 3 | `ActiveTime` accumulators |
| `UGCSaveState` | 2 | livery/tuning time counters |
| `ChampionshipDrivatarsState` | 2 | main + island drivatar rosters (payload lives in `BinarySaveState`) |
| singles | 1 each | `PlayerState`, `CareerState`, `RadioState`, `TombolaState`, `RoadDiscoveryState`, `SkillsState`, `ForzaEconomyState`, `GameDVRState`, `RaceEncounterState`, `RestorePointState`, `CurrentCarState`, `CurrentDestinationState`, `GameTimeState`, … |

Interesting objects decoded:

```xml
<Object Id="PlayerState" Type="PlayerState">
  PlayerPosition                 = 8270.53,88.3673,-4223.6      (world x,y,z)
  PlayerFacing                   = 0.515012,-0.00114997,-0.857182 (direction)
  TreasureMapPurchased           = true
  IslandTreasureMapPurchased     = true
  LastTrackVisited               = 542
</Object>

<Object Id="CareerState" Type="CareerState">
  ActiveCareerLocation = Mainland        RoadTripPlaythroughId = 1
  CurrentCampaign       = 55             ChampionshipsPlayedCount = 1
  RoadTripStarted       = true
</Object>

<Object Id="skills" Type="SkillsState">
  SkillPointsTotal        = 468655
  UnspentSkillPointsTotal = 66655
  CurrentSkillTokensTotal = 4
  BestSkillsCombo         = 48510
</Object>

<Object Id="TombolaState" Type="TombolaState">
  Seed = 20826156   PrizeIndex = 8   Spins = 0
</Object>

<Object Id="RadioState" Type="RadioState">
  PlayedMusic = StationOff,0,0|Horizon Pulse,900427317,2883625326|Bass Arena,120637126,3036605953|...
  ActiveStation = Horizon Pulse
  StationListenTime = StationOff,0|Horizon Pulse,4005|Bass Arena,544|...   (seconds)
</Object>
```

Radio station names (`Horizon Pulse`, `Bass Arena`, `Horizon XS`, `Hospital Records`,
`Ninja Tune`, `Innovative Leisure`, `Radio Levante`), the bucket‑list/anchor/ANNA/Storm‑Island
(`Island*`) objects, wristbands and reward boards all confirm the title is **Forza Horizon 2**
(including its Storm Island content).

Note that timers are stored as `ActiveTime` counters on `GameTimeState` objects rather than as
wall‑clock dates; there are no absolute timestamps anywhere in these blobs.

---

## 5. `BinarySaveState` — the binary object dictionary

`BinarySaveState` is the binary sibling of `SaveState` and holds the objects whose payloads
are large/binary rather than scalar. It starts with a count and then length‑prefixed
`id`/`type` pairs plus a payload:

```
05 00 00 00                       ; 5 objects
1a 00 00 00 "ChampionshipDrivatarsState"   ; id
1a 00 00 00 "ChampionshipDrivatarsState"   ; type
...
```

The five objects are:

| id | type | payload |
|---|---|---|
| `ChampionshipDrivatarsState` | `ChampionshipDrivatarsState` | full drivatar roster (~105 KB) |
| `IslandChampionshipDrivatarsState` | `ChampionshipDrivatarsState` | Storm‑Island roster |
| `GameDVRState` | `GameDVRState` | game‑DVR/clip bookkeeping |
| `RadioState` | `RadioState` | same radio strings as the XML copy |
| `RoadDiscovery` | `RoadDiscoveryState` | road‑discovery bitmask |

### 5.1 Drivatar roster

The first object enumerates drivatars as **fixed‑size ~9,816‑byte records** (stride
`0x2658`), each starting with a UTF‑16LE gamertag:

```
0x54     "Drivatar_01"
0x26AC   "Drivatar_02"
0x4D04   "Drivatar_03"
0x735C   "Drivatar_04"
0x99B4   "Drivatar_05"
0xC00C   "Drivatar_06"
0xE664   "Drivatar_07"
0x10CBC  "Drivatar_08"
0x13314  "Drivatar_09"
0x1596C  "Drivatar_10"
0x17FC4  "Drivatar_11"
```

Each record also carries the drivatar's XUID and per‑drivatar state (car/skill data) — the
records are large, suggesting they embed the same kind of car/physics snapshot seen in the
SQLite garage table.

### 5.2 Radio + road discovery

The `RadioState` object repeats the listen‑time and played‑music strings verbatim, then the
file continues into `RoadDiscovery`, whose payload is a long run of `0xFF`/mask bytes (the
"which roads have been discovered" bitmap), matching the `RoadsDiscovered = 66` counter seen
in `ProfileData`.

### 5.3 Relationship to `SaveState`

The five ids present here are exactly the five objects whose XML form in `SaveState` is empty
or only a placeholder (`<Object Id="GameDVRState" Type="GameDVRState"/>`,
`<Object Id="RoadDiscovery" .../>`, etc.). So the design is: **scalar/small objects go to the
XML `SaveState`; large or binary objects go to `BinarySaveState`**, and the two files together
reconstruct one object graph.

---

## 6. `PlayerDatabase` — embedded SQLite database

The biggest blob (6,291,464 B) is a SQLite 3 database with an 8‑byte prefix:

```
73 73 6d 63 00 08 01 00 | 53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00 ...
"ssmc" + u32             | "SQLite format 3\0"  <- real SQLite header starts at 0x08
```

Carving from offset 8 produces a valid database:

* `pragma page_size = 1024`, `page_count = 6144`, `schema_version = 42`, UTF‑8, no freelist.
* 6 MB of pages for only a few hundred rows — the DB is pre‑sized/over‑allocated (mostly
  empty pages), *likely* to allow fast in‑place growth.

It contains **42 tables**. The whole list:

```
AddOnState, BadgeTitleProgress, BadgeTitleUnlocks, BarnFinds, BucketListProgress,
CarExperienceRevealsSeen, CarExperienceUnlocks, CarPointsOfInterestProgress,
Career_AIHistory, Career_Affinity, Career_CampaignResults, Career_CarGroups,
Career_ChampionshipEventsCompleted, Career_ChampionshipHistory, Career_ChampionshipStandings,
Career_ChampionshipsCompleted, Career_ChampionshipsWon, Career_DestinationUnlock,
Career_Destination_Stats, Career_EventCarsClaimed, Career_EventResults, Career_EventUnlock,
Career_Garage, Career_Playthrough, Career_PurchasedParts, Career_RaceResults,
Career_Track_DrivatarStats, Career_Track_RaceFeats, Career_Track_Stats, ChangeTracking,
ContentSeen, FreeCars, GameplayAggregate, IslandCareer_*(6 tables), LastUsedGarageId,
PerkUnlock, PhotoCaptures, VisitedHopperCategories
```

Row counts (this save): `Career_EventUnlock` 197, `ChangeTracking` 129, `Career_PurchasedParts`
69, `BadgeTitleUnlocks` 51, `Career_ChampionshipHistory/Standings` 12, `BarnFinds` 11,
`Career_RaceResults`/`Career_EventResults` 7, `Career_Garage` 5, `BucketListProgress` 5,
`CarExperienceUnlocks` 4, `Career_DestinationUnlock` 2, most others empty.

### 6.1 The garage — `Career_Garage`

This is the most detailed table: **124 columns per car**. It stores the full ownership record
*and* a complete performance/tuning snapshot. Column groups:

* **Identity/ownership:** `Id`, `CarId`, `Guid`, `OriginalOwner`, `NumOwners`, `NumTimesSold`.
* **Performance:** `PerformanceIndex`, `ClassID`, `SpeedRating`, `AccelerationRating`,
  `LaunchRating`, `BrakingRating`, `HandlingRating`, `CurbWeight`, `WeightDistribution`,
  `AspirationTypeId`, `TopSpeed`.
* **Sim physics:** `SimPeakPower`, `SimPeakAngVel`, `SimPeakTorque`, `SimPeakTorqueAngVel`,
  `SimRedlineAngVel`, `PeakIntakePSI`.
* **Usage:** `DistanceDriven`, `TimeDriven`, `TotalWinnings`, `TotalRepairs`, `NumVictories`,
  `NumPodiums`, `NumRaces`, `NumSkillPointsEarned`.
* **Build/parts:** `Engine`, `Drivetrain`, `Motor`, `Brakes`, `SpringDamper`, `AntiSway*`,
  `TireCompound`, `Turbo/Supercharger*`, `Transmission`, `Differential`, body/aero parts, …
  (each part is a numeric part‑id, `-1` = stock).
* **Cosmetics/assets:** `LiveryFileName`, `TuneFileName`, `VersionedTuneId`,
  `VersionedLiveryId`, `Thumbnail` (e.g. `game:\Media\Stripped\RC0\Thumbnail_1218.png`),
  `DefaultManufacturerColorIndex`, `WheelStyle`, `TireBrand`.
* **Full tune:** `Tuning_*` — tire pressures, final drive, all eight gear ratios, camber, toe,
  caster, ARBs, springs, ride height, damping, downforce, brake balance/pressure, diff
  accel/decel, center torque (all `-1.0` when the car is untuned).

Sample of the five owned cars:

| Id | CarId | Class | PerfIndex | PeakPower | TopSpeed | DistDriven | Races | Wins | Owner |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2 | 1218 | 3 | 0.6859 | 2498.78 | 67.57 | 177108 | 4 | 4 | Player |
| 3 | 297  | 4 | 0.8012 | 3049.73 | 78.00 | 212966 | 1 | 1 | Player |
| 4 | 299  | 1 | 0.4593 | 3355.35 | 0      | 0 | 0 | 0 | Player |
| 5 | 1661 | 2 | 0.5724 | 1839.83 | 0      | 0 | 0 | 0 | Player |
| 6 | 2007 | 1 | 0.5120 | 1469.87 | 0      | 0 | 0 | 0 | Player |

*(`CarId` is the game's internal car ordinal; the `Guid` column identifies the individual
purchased instance, and `Id` matches `LastUsedGarageId = 6` — the last car used.)*

### 6.2 Other notable tables

* **`Career_RaceResults` / `Career_EventResults`** — `(RaceId/EventId, Place, TargetAchieved, TimesCompleted)`; here every completed race is `Place=1`.
* **`Career_ChampionshipStandings` / `Career_ChampionshipHistory`** — the leaderboard of the
  active championship. The human entry is `PlayerXUID = <XUID>` with 20 pts
  (position 0), the rest are offline drivatars with ids like `9`, `16`, `18`, …
* **`BarnFinds(CarOrdinal, State)`** — 11 barn finds, all `State=0` (undiscovered/found‑but‑not‑restored).
* **`BucketListProgress(ChallengeId, Completed, Attempted, Viewed, CompletedCoop, …)`**.
* **`BadgeTitleUnlocks(UnlockId, IsNewBadge, IsNewTitle)`** — 51 unlock ids (e.g. 326 = the
  current badge/title also mirrored as `PlayerCardBadgeId`/`PlayerCardTitleId` in `ProfileData`).
* **`Career_EventUnlock(UnlockId)`** — 197 unlocked event ids.
* **`PerkUnlock(UnlockId)`** — 1 perk.
* **`ChangeTracking(TableID, RowID, Action, TransactionId)`** — 129 rows; this is a
  **dirty‑row journal** the game keeps inside the DB so it knows which rows to push to the
  cloud save. Combined with the `commit` hashes, this is how the engine avoids re‑uploading
  the whole 6 MB DB.

---

## 7. `VersionFlags`

A single little‑endian u32, value **`6`**:

```
06 00 00 00
```

Same in both revisions. It is *likely* a save‑schema/version stamp consumed together with the
`commit` line `... revision v2`.

---

## 8. How a save revision changes (`0x13F` → `0x140`)

Comparing the two revisions byte‑for‑byte shows exactly what a "next autosave" looks like:

* `BinarySaveState` — **identical**
* `PlayerDatabase` — **identical**
* `VersionFlags` — **identical**
* `ProfileData` — **5 bytes differ**
* `SaveState` — **1 byte differs**

**`ProfileData` change** (credits increased, as if a race/event paid out):

```
0x0DEC: 2c 2a 00 00  →  bc 8f 00 00      Credits      469548 → 495548
0x0E39: 2c 2a 00 00  →  bc 8f 00 00      TotalWinnings 469548 → 495548
0x0E03: 8b          →  a1                (one byte of the u64 "UpTime" value)
```

(The two identical `469548 → 495548` edits are the separate `Credits` and `TotalWinnings`
properties; the small byte change is inside the 8‑byte `UpTime` timestamp/counter.)

**`SaveState` change** (a tombola/wheelspin result advanced):

```
0x685E:  "PrizeIndex" Value="7"  →  Value="8"
```

So a new revision = the same five blobs re‑written, with the SHA‑256 digests in `commit`
updated. The engine clearly rewrites whole blobs rather than storing deltas, while
`ChangeTracking`/`Schema_version` inside the SQLite DB provide the internal fine‑grained
dirty tracking.

---

## 9. Player identity

* The `User_<XUID-hex>` folder is the owner's **XUID in hex**; the same account appears
  as `PlayerXUID` in the SQLite championship tables.
* The garage's `OriginalOwner` (and the active `LastUsedGarageId` owner) is the player's
  gamertag.
* No XUID of friends/followed players is stored as text, but drivatar records in
  `BinarySaveState` do carry per‑drivatar identifiers.

---

## 10. Where each kind of data lives (cheat‑sheet)

| Data | File | Encoding |
|---|---|---|
| Container manifest, hashes, sizes | `commit` | text + SHA‑256 |
| Save schema version | `VersionFlags` | LE u32 = 6 |
| Credits, XP, winnings, per‑type stats, controller/wheel/HUD settings, locale | `ProfileData` | `ssmc` binary key/value records |
| World position, career/road‑trip state, radio, tombola seed, treasure‑map flags, tutorials, dialogue "seen" flags, reward boards, speed traps/zones, bucket‑list slots, barn‑find state | `SaveState` | XML `ObjectDictionary` |
| Drivatar rosters (main + Storm Island), road‑discovery bitmask, GameDVR, duplicate radio state | `BinarySaveState` | binary object dictionary |
| Garage/owned cars + full tune, race/championship results, unlocks, perks, badges, barn finds, dirty‑row journal | `PlayerDatabase` | SQLite 3 (8‑byte `ssmc` prefix) |
| Non‑vehicle gameplay timers | `SaveState`/`BinarySaveState` (`GameTimeState`) | accumulating `ActiveTime` counters |

---

## 11. Practical notes / caveats

* **Everything is plaintext or trivially decodable.** There is no encryption, no
  per‑save key, and no obfuscation; only `commit` SHA‑256 integrity hashes and the
  cross‑references between files.
* The XML `SaveState` and binary `BinarySaveState` are complementary halves of one object
  graph, and the five ids in `BinarySaveState` are exactly the "binary" objects left blank in
  the XML — a clean split by payload kind.
* `CarId` values (297, 299, 1218, 1661, 2007, …) are **game‑internal car ordinals**, not
  names; resolving them to car names requires an external ordinal→car table for FH2, which is
  not present in the save.
* `TimeDriven`, `ActiveTime`, etc. are gameplay counters (seconds), so the save contains no
  absolute calendar timestamps to correlate.
* The trailing table inside `ProfileData` (24‑byte stride) and the exact semantics of the
  two `ProfileData` header words (`0x33B3`, `0x13`) were not fully decoded; they are the only
  parts of the format left as *likely* rather than verified.

---

### Appendix — `ProfileData` header/record bytes (verified samples)

```
Offset 0x00:  73 73 6d 63   b3 33 00 00   13 00 00 00    "ssmc" magic + 2 u32 header words
Offset 0x0C:  first record (BristolOptions)
  0e 00 00 00                                   nameLen = 14
  42 72 69 73 74 6f 6c 4f 70 74 69 6f 6e 73     "BristolOptions"
  20                                            separator
  00 00 00 00                                   reserved
  0f 00 00 00                                   type = 0x0F (container)
  06 00 00 00                                   child count = 6
```

```
PlayerDatabase prefix:
  73 73 6d 63 00 08 01 00   "ssmc" + u32, then the SQLite file at offset 0x08
```

```
commit (revision 0x140):
  Azimuth complete save revision v2
  blobs 5
  <sha256> 112875 BinarySaveState
  <sha256> 6291464 PlayerDatabase
  <sha256> 20488 ProfileData
  <sha256> 70245 SaveState
  <sha256> 4 VersionFlags
```
