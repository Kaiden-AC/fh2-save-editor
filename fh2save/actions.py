"""High-level, well-understood convenience actions on a SaveDocument."""

from __future__ import annotations


def _is_fh3(doc):
    return getattr(doc, "format", "FH2") == "FH3"


# FH3 bucket-list events: 30 in the base game, 7 Blizzard Mountain and 5 Hot
# Wheels.  The DB uses 1-based challenge IDs.
FH3_BUCKET_IDS = range(1, 43)
# The static FH3 career-event catalogue is not stored in the save.  FH2 event
# IDs go up to 1007, so cover a comfortably wider range for FH3 (including both
# expansions).  Rows for IDs the game does not define are ignored by the game.
FH3_EVENT_ID_MAX = 2000
FH3_MAX_CREDITS = 999_999_999
FH3_MAX_LEVEL = 999
FH3_MAX_XP = 50_000_000
FH3_MAX_FANS = 10_000_000


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _fh3_set(doc, path, value):
    """Set one flattened FH3 profile property by full path."""
    if doc.profile is None:
        return False
    prop = doc.profile.find(path)
    if prop is None:
        return False
    try:
        prop.set(value)
    except (TypeError, ValueError):
        return False
    return True


def _profile_set(doc, name, value, occurrences=1, match_old=None):
    if doc.profile is None:
        return 0
    n = 0
    for p in doc.profile.props:
        if p.name != name:
            continue
        try:
            old = p.get()
        except Exception:
            old = None
        if match_old is not None and old != match_old:
            continue
        p.set(value)
        n += 1
        if n >= occurrences:
            break
    return n


def _set_obj_prop(doc, obj, prop_name, value) -> bool:
    """Set a SaveState property on FH2 (SaveObject) or FH3 (XmlObject)."""
    setter = getattr(obj, "set_property", None)
    if setter is not None:
        return bool(setter(prop_name, value))
    if doc.savestate is not None:
        return bool(doc.savestate.set_property(obj.id, prop_name, value))
    return False


def _set_type_property(doc, type_name, prop_name, value):
    if doc.savestate is None:
        return 0
    n = 0
    for obj in doc.savestate.objects:
        if getattr(obj, "type", None) == type_name and _set_obj_prop(
                doc, obj, prop_name, value):
            n += 1
    return n


def _set_skill_state_prop(doc, prop_name, value):
    if doc.savestate is None:
        return 0
    if doc.savestate.set_property("skills_save_state", prop_name, value):
        return 1
    return _set_type_property(doc, "SkillsState", prop_name, value)


# --------------------------------------------------------------------------
# Money / XP / skills
# --------------------------------------------------------------------------
def set_credits(doc, amount: int) -> str:
    amount = max(0, int(amount))
    if doc.profile is None:
        return "no ProfileData"
    if _is_fh3(doc):
        credits = doc.profile.find("Main/Credits") or doc.profile.find("Credits")
        if credits is None:
            return "FH3 credits property not found"
        old = credits.get()
        credits.set(amount)
        # Keep lifetime counters at least as large as the wallet.  They are
        # separate stats in FH3 and should not be lowered.
        for path in ("Main/TotalCredits", "Main/TotalWinnings", "Main/OnlineWinnings"):
            prop = doc.profile.find(path)
            if prop is not None:
                try:
                    if prop.get() < amount:
                        prop.set(amount)
                except (TypeError, ValueError):
                    pass
        return "Credits = %d (was %s)" % (amount, old)
    old = None
    credits = doc.profile.find("Credits")
    if credits is not None:
        old = credits.get()
        credits.set(amount)
    # keep the paired TotalWinnings in sync (the one that matched Credits)
    n_tw = 0
    for p in doc.profile.props:
        if p.name == "TotalWinnings":
            try:
                if old is None or p.get() == old:
                    p.set(amount)
                    n_tw += 1
            except Exception:
                pass
    return "Credits = %d (TotalWinnings updated in %d place(s))" % (amount, n_tw)


def set_xp(doc, amount: int) -> str:
    amount = max(0, int(amount))
    if doc.profile is None:
        return "no ProfileData"
    if _is_fh3(doc):
        n = 0
        for path in ("Main/XP", "Main/TotalXP"):
            p = doc.profile.find(path)
            if p is not None:
                p.set(amount)
                n += 1
        return "XP / TotalXP = %d (%d field(s))" % (amount, n)
    _profile_set(doc, "XP", amount, occurrences=99)
    _profile_set(doc, "WristbandLevel", amount, occurrences=99)
    return "XP / WristbandLevel = %d" % amount


def set_level(doc, level: int) -> str:
    """Set the driver level (FH3) / wristband level (FH2)."""
    level = max(1, int(level))
    if _is_fh3(doc):
        n = 0
        for path in ("Main/Level", "Main/LastRewardedLevel"):
            if _fh3_set(doc, path, level):
                n += 1
        # Give enough XP that the level survives the game's own recomputation.
        _fh3_set(doc, "Main/XP", max(level * 60000, 1))
        _fh3_set(doc, "Main/TotalXP", max(level * 60000, 1))
        return "Level = %d (%d field(s) updated)" % (level, n)
    # FH2's WristbandLevel stores XP, not the numeric level, so only Level.
    _profile_set(doc, "Level", level, occurrences=99)
    return "Level = %d" % level


def set_skill_points(doc, total: int, unspent: int = None) -> str:
    total = max(0, int(total))
    if unspent is None:
        unspent = total
    unspent = max(0, int(unspent))
    if doc.savestate is not None:
        if _is_fh3(doc):
            _set_skill_state_prop(doc, "SkillPointsTotal", str(total))
            _set_skill_state_prop(doc, "UnspentSkillPointsTotal", str(unspent))
        else:
            doc.savestate.set_property("skills", "SkillPointsTotal", total)
            doc.savestate.set_property("skills", "UnspentSkillPointsTotal", unspent)
    return "Skill points total=%d unspent=%d" % (total, unspent)


def set_skill_tokens(doc, count: int) -> str:
    count = max(0, int(count))
    _profile_set(doc, "NumSkillTokens", count, occurrences=99)
    if doc.savestate is not None:
        if _is_fh3(doc):
            _set_skill_state_prop(doc, "CurrentSkillTokensTotal", str(count))
        else:
            doc.savestate.set_property("skills", "CurrentSkillTokensTotal", count)
    return "Skill tokens = %d" % count


# --------------------------------------------------------------------------
# World unlock helpers (SaveState)
# --------------------------------------------------------------------------
def _complete_stunt_type(doc, type_name, prefix=None, personal_best="9999"):
    """Mark every matching SaveState object completed with a strong PB."""
    if doc.savestate is None:
        return 0
    n = 0
    for obj in doc.savestate.objects:
        if getattr(obj, "type", None) != type_name:
            continue
        if prefix is not None and not obj.id.startswith(prefix):
            continue
        # FH2 CameraState has a Discovered flag; FH3's does not.  Setting it
        # is a no-op when the property is absent.
        _set_obj_prop(doc, obj, "Discovered", "true")
        _set_obj_prop(doc, obj, "Completed", "true")
        _set_obj_prop(doc, obj, "PersonalBest", personal_best)
        n += 1
    return n


def unlock_all_speed_traps(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    if _is_fh3(doc):
        n = _complete_stunt_type(doc, "CameraState", "speed_trap_", "9999")
        return "Completed %d speed traps" % n
    n = _complete_stunt_type(doc, "CameraState", "speed_trap_", "9999")
    return "Unlocked %d speed traps" % n


def unlock_all_speed_zones(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    if _is_fh3(doc):
        n = _complete_stunt_type(doc, "CameraState", "speed_zone_", "9999")
        return "Completed %d speed zones" % n
    n = _complete_stunt_type(doc, "CameraState", "speed_zone_", "9999")
    return "Unlocked %d speed zones" % n


def complete_all_danger_signs(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = _complete_stunt_type(doc, "DangerSignState", None, "9999")
    return "Completed %d danger signs" % n


def complete_all_drift_zones(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = _complete_stunt_type(doc, "DriftZoneState", None, "999999")
    return "Completed %d drift zones" % n


def complete_all_pr_stunts(doc) -> str:
    """Complete speed traps, speed zones, danger signs and drift zones."""
    if doc.savestate is None:
        return "no SaveState"
    traps = _complete_stunt_type(doc, "CameraState", "speed_trap_", "9999")
    zones = _complete_stunt_type(doc, "CameraState", "speed_zone_", "9999")
    signs = _complete_stunt_type(doc, "DangerSignState", None, "9999")
    drifts = _complete_stunt_type(doc, "DriftZoneState", None, "999999")
    return ("Completed %d speed traps, %d speed zones, %d danger signs and "
            "%d drift zones" % (traps, zones, signs, drifts))


def unlock_all_reward_boards(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    if _is_fh3(doc):
        n = _set_type_property(doc, "DiscountBoardSaveState", "State", "Collected")
        return "Marked %d reward boards collected" % n
    n = 0
    for o in doc.savestate.objects:
        if o.id.startswith("discount_board_"):
            doc.savestate.set_property(o.id, "State", "Discovered")
            n += 1
    return "Marked %d reward boards discovered" % n


def mark_all_dialogue_seen(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    if _is_fh3(doc):
        n = _set_type_property(doc, "DialogueSaveState", "PlayCount", "1")
        return "Marked %d dialogue entries as played" % n
    n = 0
    for o in doc.savestate.objects:
        if o.type == "DialogueSaveState":
            doc.savestate.set_property(o.id, "Seen", "true")
            n += 1
    return "Marked %d dialogue entries seen" % n


def activate_all_landmarks(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if getattr(o, "type", None) == "LandmarkSaveState":
            if _set_obj_prop(doc, o, "Activated", "true"):
                n += 1
    return "Activated %d landmarks" % n


def activate_all_festival_sites(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if getattr(o, "type", None) == "FestivalSiteState":
            ok = _set_obj_prop(doc, o, "Activated", "true")
            ok = _set_obj_prop(doc, o, "Built", "true") or ok
            if _is_fh3(doc):
                # FH3 festival sites max out at level 5; level 5 unlocks the
                # remaining routes, showcases and the Goliath circuit.
                ok = _set_obj_prop(doc, o, "Level", "5") or ok
            if ok:
                n += 1
    msg = "Activated/built %d festival sites" % n
    if _is_fh3(doc):
        fans = 0
        for o in doc.savestate.objects:
            if getattr(o, "type", None) != "CurrencyBucket":
                continue
            if o.id.startswith("CurrencyBucket_Fans_"):
                _set_obj_prop(doc, o, "Total", str(FH3_MAX_FANS))
                fans += 1
        msg += " at level 5"
        if fans:
            msg += "; fans = %s" % format(FH3_MAX_FANS, ",")
    return msg


def discover_all_bucket_list_slots(doc) -> str:
    if _is_fh3(doc):
        if doc.playerdb is None:
            return "no PlayerDatabase"
        # The table is empty in a fresh FH3 save, so the old UPDATE did
        # nothing.  Insert the 42 known challenge IDs instead.
        for challenge_id in FH3_BUCKET_IDS:
            doc.playerdb.execute(
                "INSERT OR IGNORE INTO BucketListProgress "
                "(ChallengeId, Completed, Attempted, Viewed, CompletedCoop, "
                "AttemptedCoop, ViewedCoop) VALUES (?,0,1,1,0,0,0)",
                (challenge_id,),
            )
        cur = doc.playerdb.execute(
            "UPDATE BucketListProgress SET Attempted=1, Viewed=1"
        )
        return "Discovered %d bucket-list slots" % cur.rowcount
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if o.type == "BucketListSlotState":
            doc.savestate.set_property(o.id, "Discovered", "true")
            n += 1
    return "Discovered %d bucket-list slots" % n


# --------------------------------------------------------------------------
# PlayerDatabase helpers
# --------------------------------------------------------------------------
def complete_all_bucket_list(doc) -> str:
    if doc.playerdb is None:
        return "no PlayerDatabase"
    if _is_fh3(doc):
        # BucketListProgress is empty until a challenge is attempted, so use
        # inserts rather than an UPDATE (which used to be a silent no-op).
        for challenge_id in FH3_BUCKET_IDS:
            doc.playerdb.execute(
                "INSERT INTO BucketListProgress "
                "(ChallengeId, Completed, Attempted, Viewed, CompletedCoop, "
                "AttemptedCoop, ViewedCoop) VALUES (?,1,1,1,1,0,0) "
                "ON CONFLICT(ChallengeId) DO UPDATE SET Completed=1, "
                "Attempted=1, Viewed=1",
                (challenge_id,),
            )
        cur = doc.playerdb.execute(
            "UPDATE BucketListProgress SET Completed=1, Attempted=1, Viewed=1"
        )
        return "Completed %d bucket-list challenges (IDs 1-%d)" % (
            cur.rowcount, max(FH3_BUCKET_IDS))
    cur = doc.playerdb.execute(
        "UPDATE BucketListProgress SET Completed=1, Attempted=1, Viewed=1"
    )
    return "Completed %d bucket-list challenges" % cur.rowcount


def complete_all_race_results(doc) -> str:
    if doc.playerdb is None:
        return "no PlayerDatabase"
    if _is_fh3(doc):
        # The result tables are empty in a normal FH3 save and the static
        # event catalogue is not stored in the save, so insert a plausible
        # 1..N range.  Rows for IDs the game does not define are ignored.
        for event_id in range(1, FH3_EVENT_ID_MAX + 1):
            doc.playerdb.execute(
                "INSERT OR IGNORE INTO Career_EventResults "
                "(EventId, Place, TargetAchieved, TimesCompleted) "
                "VALUES (?,1,100,1)",
                (event_id,),
            )
            doc.playerdb.execute(
                "INSERT OR IGNORE INTO Career_RaceResults "
                "(RaceId, Place, TargetAchieved, TimesCompleted) "
                "VALUES (?,1,100,1)",
                (event_id,),
            )
        doc.playerdb.execute(
            "UPDATE Career_EventResults SET Place=1, TargetAchieved=100, "
            "TimesCompleted=CASE WHEN TimesCompleted < 1 THEN 1 "
            "ELSE TimesCompleted END"
        )
        doc.playerdb.execute(
            "UPDATE Career_RaceResults SET Place=1, TargetAchieved=100, "
            "TimesCompleted=CASE WHEN TimesCompleted < 1 THEN 1 "
            "ELSE TimesCompleted END"
        )
        events = doc.playerdb.row_count("Career_EventResults")
        races = doc.playerdb.row_count("Career_RaceResults")
        return ("Completed %d career events and %d races (experimental IDs "
                "1-%d)" % (events, races, FH3_EVENT_ID_MAX))
    cur = doc.playerdb.execute(
        "UPDATE Career_RaceResults SET Place=1, TargetAchieved=100"
    )
    return "Set %d race results to 1st" % cur.rowcount


def unlock_all_barn_finds(doc, state: int = 1) -> str:
    """Set every BarnFinds.State (0=hidden, 1=found, 2=restored — game-defined)."""
    if doc.playerdb is None:
        return "no PlayerDatabase"
    cur = doc.playerdb.execute("UPDATE BarnFinds SET State=?", (int(state),))
    return "Set %d barn finds to State=%d" % (cur.rowcount, int(state))


def add_car_to_garage(doc, car_id: int, clone_rowid: int = None) -> str:
    if doc.playerdb is None:
        return "no PlayerDatabase"
    rows = doc.playerdb.rows("Career_Garage")
    if not rows:
        return "garage is empty; nothing to clone"
    if clone_rowid is None:
        clone_rowid = rows[-1][0]
    new_id = doc.playerdb.clone_row(
        "Career_Garage", clone_rowid, {"CarId": int(car_id)}
    )
    return "Cloned garage row %s as CarId=%d (new Id=%s)" % (
        clone_rowid, int(car_id), new_id,
    )


def set_all_garage_tuning_stock(doc) -> str:
    if doc.playerdb is None:
        return "no PlayerDatabase"
    cols = [c for c in doc.playerdb.columns("Career_Garage") if c.startswith("Tuning_")]
    if not cols:
        return "no Tuning_ columns"
    assigns = ",".join("[%s]=-1.0" % c for c in cols)
    cur = doc.playerdb.execute("UPDATE Career_Garage SET %s" % assigns)
    return "Reset tuning on %d cars" % cur.rowcount


# --------------------------------------------------------------------------
# All-in-one FH3 progression
# --------------------------------------------------------------------------
def max_fh3_progression(doc) -> str:
    """Apply the full FH3 progression preset in one go."""
    if not _is_fh3(doc):
        return "FH3 only"
    set_credits(doc, FH3_MAX_CREDITS)
    set_xp(doc, FH3_MAX_XP)
    set_level(doc, FH3_MAX_LEVEL)
    set_skill_points(doc, 999_999, 999_999)
    set_skill_tokens(doc, 999)
    # Max out the statistics that are displayed alongside progression.
    for path, value in (
        ("Main/TotalSkills", 9_999_999),
        ("Main/HighestSkillScore", 999_999),
        ("Main/NumRaces", FH3_EVENT_ID_MAX),
        ("Main/NumVictories", FH3_EVENT_ID_MAX),
        ("Main/NumPodiums", FH3_EVENT_ID_MAX),
        ("Main/NumLinearPlayRaces", FH3_EVENT_ID_MAX),
    ):
        _fh3_set(doc, path, value)
    complete_all_pr_stunts(doc)
    unlock_all_reward_boards(doc)
    activate_all_landmarks(doc)
    activate_all_festival_sites(doc)
    mark_all_dialogue_seen(doc)
    complete_all_bucket_list(doc)
    complete_all_race_results(doc)
    return ("FH3 max progression: credits, level %d, skills, all PR stunts, "
            "boards, festival sites, bucket list and career events"
            % FH3_MAX_LEVEL)


# --------------------------------------------------------------------------
# Generic
# --------------------------------------------------------------------------
def set_version_flags(doc, value: int) -> str:
    doc.versionflags = int(value)
    return "VersionFlags = %d" % int(value)


QUICK_ACTIONS = [
    ("Set credits", "money"),
    ("Set XP / wristband level", "xp"),
    ("Set driver level", set_level),
    ("Set skill points", "skills"),
    ("Set skill tokens", "tokens"),
    ("Complete all speed traps", unlock_all_speed_traps),
    ("Complete all speed zones", unlock_all_speed_zones),
    ("Complete all danger signs", complete_all_danger_signs),
    ("Complete all drift zones", complete_all_drift_zones),
    ("Complete all PR stunts", complete_all_pr_stunts),
    ("Unlock all reward boards", unlock_all_reward_boards),
    ("Activate/build all festival sites", activate_all_festival_sites),
    ("Discover all bucket-list slots", discover_all_bucket_list_slots),
    ("Mark all dialogue as seen", mark_all_dialogue_seen),
    ("Complete all bucket-list challenges", complete_all_bucket_list),
    ("Complete all career events and races", complete_all_race_results),
    ("Max FH3 progression (all of the above)", max_fh3_progression),
    ("Unlock/restore all barn finds", "barnfind"),
    ("Add car to garage (clone)", "addcar"),
]
