"""High-level, well-understood convenience actions on a SaveDocument."""

from __future__ import annotations


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Money / XP / skills
# --------------------------------------------------------------------------
def set_credits(doc, amount: int) -> str:
    amount = max(0, int(amount))
    old = None
    credits = doc.profile.find("Credits") if doc.profile else None
    if credits is not None:
        old = credits.get()
        credits.set(amount)
    # keep the paired TotalWinnings in sync (the one that matched Credits)
    n_tw = 0
    if doc.profile:
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
    _profile_set(doc, "XP", amount, occurrences=99)
    _profile_set(doc, "WristbandLevel", amount, occurrences=99)
    return "XP / WristbandLevel = %d" % amount


def set_skill_points(doc, total: int, unspent: int = None) -> str:
    total = max(0, int(total))
    if unspent is None:
        unspent = total
    unspent = max(0, int(unspent))
    if doc.savestate is not None:
        doc.savestate.set_property("skills", "SkillPointsTotal", total)
        doc.savestate.set_property("skills", "UnspentSkillPointsTotal", unspent)
    return "Skill points total=%d unspent=%d" % (total, unspent)


def set_skill_tokens(doc, count: int) -> str:
    count = max(0, int(count))
    _profile_set(doc, "NumSkillTokens", count, occurrences=99)
    if doc.savestate is not None:
        doc.savestate.set_property("skills", "CurrentSkillTokensTotal", count)
    return "Skill tokens = %d" % count


# --------------------------------------------------------------------------
# World unlock helpers (SaveState)
# --------------------------------------------------------------------------
def unlock_all_speed_traps(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if o.id.startswith("speed_trap_"):
            doc.savestate.set_property(o.id, "Discovered", "true")
            doc.savestate.set_property(o.id, "Completed", "true")
            n += 1
    return "Unlocked %d speed traps" % n


def unlock_all_speed_zones(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if o.id.startswith("speed_zone_"):
            doc.savestate.set_property(o.id, "Discovered", "true")
            doc.savestate.set_property(o.id, "Completed", "true")
            n += 1
    return "Unlocked %d speed zones" % n


def unlock_all_reward_boards(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if o.id.startswith("discount_board_"):
            doc.savestate.set_property(o.id, "State", "Discovered")
            n += 1
    return "Marked %d reward boards discovered" % n


def mark_all_dialogue_seen(doc) -> str:
    if doc.savestate is None:
        return "no SaveState"
    n = 0
    for o in doc.savestate.objects:
        if o.type == "DialogueSaveState":
            doc.savestate.set_property(o.id, "Seen", "true")
            n += 1
    return "Marked %d dialogue entries seen" % n


def discover_all_bucket_list_slots(doc) -> str:
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
    cur = doc.playerdb.execute(
        "UPDATE BucketListProgress SET Completed=1, Attempted=1, Viewed=1"
    )
    return "Completed %d bucket-list challenges" % cur.rowcount


def complete_all_race_results(doc) -> str:
    if doc.playerdb is None:
        return "no PlayerDatabase"
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
# Generic
# --------------------------------------------------------------------------
def set_version_flags(doc, value: int) -> str:
    doc.versionflags = int(value)
    return "VersionFlags = %d" % int(value)


QUICK_ACTIONS = [
    ("Set credits", "money"),
    ("Set XP / wristband level", "xp"),
    ("Set skill points", "skills"),
    ("Set skill tokens", "tokens"),
    ("Unlock all speed traps", unlock_all_speed_traps),
    ("Unlock all speed zones", unlock_all_speed_zones),
    ("Unlock all reward boards", unlock_all_reward_boards),
    ("Discover all bucket-list slots", discover_all_bucket_list_slots),
    ("Mark all dialogue as seen", mark_all_dialogue_seen),
    ("Complete all bucket-list challenges", complete_all_bucket_list),
    ("Set all race results to 1st", complete_all_race_results),
    ("Unlock/restore all barn finds", "barnfind"),
    ("Add car to garage (clone)", "addcar"),
]
