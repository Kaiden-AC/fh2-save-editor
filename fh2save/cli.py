"""Command-line interface (also usable non-interactively / for scripting)."""

from __future__ import annotations

import argparse
import os
import sys

from . import actions, container
from .container import format_bytes
from .document import SaveDocument


def _resolve(root, save_index=0, search=False):
    sets = container.discover(root, search=search)
    if not sets:
        raise SystemExit(
            "no Forza saves found at %s\n"
            "point --root at the folder that contains 'titles/' "
            "(or use --search to look a little deeper)" % root)
    if save_index >= len(sets):
        raise SystemExit("save index %d out of range (%d found)" % (save_index, len(sets)))
    return sets, sets[save_index]


def _load(saveset, rev_number=None):
    revs = saveset.revisions()
    if not revs:
        raise SystemExit("no revisions")
    rev = revs[-1]
    if rev_number is not None:
        match = [r for r in revs if r.number == rev_number]
        if not match:
            raise SystemExit("revision 0x%x not found" % rev_number)
        rev = match[0]
    return rev, SaveDocument(saveset, rev, saveset.read_revision(rev))


def cmd_list(args):
    sets = container.discover(args.root, search=getattr(args, 'search', False))
    if not sets:
        print("No Forza saves found at %s" % args.root)
        print("Point --root at the folder that contains 'titles/' "
              "(or add --search).")
        return 1
    for i, s in enumerate(sets):
        revs = s.revisions()
        print("[%d] title=%s slot=%s user=%s xuid=%s" % (
            i, s.title_id, s.slot, s.user, s.xuid))
        print("    revisions: %s" % ", ".join("0x%x" % r.number for r in revs))
        if revs:
            blobs = s.read_revision(revs[-1])
            print("    latest blobs: %s" % ", ".join(
                "%s(%s)" % (n, format_bytes(len(d))) for n, d in sorted(blobs.items())))
    return 0


def cmd_info(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    print("Game : %s" % doc.game_name)
    print("Save : %s / %s / %s" % (s.title_id, s.slot, s.user))
    print("Rev  : 0x%x  (%s)" % (rev.number, rev.path))
    print("Commit: %s" % doc.commit.header)
    problems = doc.verify()
    print("Verify: %s" % ("OK" if not problems else "%d problem(s)" % len(problems)))
    for p in problems:
        print("   - %s" % p)
    if doc.profile:
        c = doc.profile.find("Credits")
        x = doc.profile.find("XP")
        print("ProfileData : %d entries; Credits=%s XP=%s" % (
            len(doc.profile), c.get() if c else "?", x.get() if x else "?"))
    if doc.format == "FH3" and doc.fh3 is not None:
        print("FH3 sections: %s" % ", ".join(
            "%s(%d)" % (n, len(doc.fh3.sections[n]))
            for n in ("profile", "savestate", "binary", "database")))
    if doc.savestate:
        print("SaveState   : %d objects" % len(doc.savestate))
    if doc.playerdb:
        print("PlayerDatabase: %d tables" % len(doc.playerdb.tables()))
        print("            garage rows: %d" % doc.playerdb.row_count("Career_Garage"))
    if doc.binsave:
        print("BinarySaveState: %d objects (read-only)" % len(doc.binsave.objects))
    print("VersionFlags: %s" % doc.versionflags)
    return 0


def cmd_dump(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    what = args.blob
    if what == "ProfileData":
        for p in doc.profile:
            path = getattr(p, "path", p.name)
            print("%-52s %-9s %s" % (path, p.type_name, p.display()))
    elif what == "SaveState":
        for o in doc.savestate.objects:
            print("%-44s [%s] (%d props)" % (o.id, o.type, len(o.props)))
    elif what == "BinarySaveState":
        print(doc.binsave.report())
    elif what in ("PlayerDatabase", "Database"):
        db = doc.playerdb
        for t in db.tables():
            print("%-46s %6d rows" % (t, db.row_count(t)))
    else:
        print("unknown blob %s" % what)
        return 1
    return 0


def cmd_set(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    key = args.key.lower()
    val = args.value
    if key == "credits":
        msg = actions.set_credits(doc, int(val, 0))
    elif key == "xp":
        msg = actions.set_xp(doc, int(val, 0))
    elif key == "skillpoints":
        msg = actions.set_skill_points(doc, int(val, 0))
    elif key == "skilltokens":
        msg = actions.set_skill_tokens(doc, int(val, 0))
    elif key == "versionflags":
        msg = actions.set_version_flags(doc, int(val, 0))
    else:
        print("unknown key %s (try: credits, xp, skillpoints, skilltokens, versionflags)" % key)
        return 1
    print(msg)
    return _finish(doc, args)


NAMED_ACTIONS = {
    "maxmoney": lambda d: actions.set_credits(d, 2000000000),
    "speedtraps": actions.unlock_all_speed_traps,
    "speedzones": actions.unlock_all_speed_zones,
    "boards": actions.unlock_all_reward_boards,
    "landmarks": actions.activate_all_landmarks,
    "festivals": actions.activate_all_festival_sites,
    "bucketslots": actions.discover_all_bucket_list_slots,
    "dialogue": actions.mark_all_dialogue_seen,
    "bucketlist": actions.complete_all_bucket_list,
    "raceresults": actions.complete_all_race_results,
    "barnfinds": lambda d: actions.unlock_all_barn_finds(d, 2),
    "stocktuning": actions.set_all_garage_tuning_stock,
}


def cmd_action(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    if args.name not in NAMED_ACTIONS:
        print("unknown action %s (available: %s)" % (
            args.name, ", ".join(sorted(NAMED_ACTIONS))))
        return 1
    msg = NAMED_ACTIONS[args.name](doc)
    print(msg)
    return _finish(doc, args)


def cmd_addcar(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    msg = actions.add_car_to_garage(doc, int(args.car_id, 0),
                                    args.clone_rowid)
    print(msg)
    return _finish(doc, args)


def _finish(doc, args):
    changed = doc.changed_blobs()
    if not changed:
        print("No changes.")
        return 0
    print("Changed blobs: %s" % ", ".join(changed))
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    rev = doc.save()
    print("Wrote revision 0x%x -> %s" % (rev.number, rev.path))
    return 0


def cmd_selftest(args):
    _sets, s = _resolve(args.root, args.save, getattr(args, 'search', False))
    rev, doc = _load(s, args.rev)
    from .fh3bxml import BxmlDocument
    from .fh3crypto import cipher
    from .profile import ProfileData
    from .savestate import SaveState

    ok = True
    print("Selftest @ %s revision 0x%x" % (doc.game_name, rev.number))
    problems = doc.verify()
    print("  commit verify .......... %s" % ("OK" if not problems else problems))
    ok &= not problems

    if doc.format == "FH3":
        raw = doc.original["ProfileData"]
        plain = cipher().decrypt(raw)
        padding = int.from_bytes(raw[16:20], "little")
        reenc = cipher().encrypt(plain, iv=raw[:16], padding=padding)
        print("  TFIT decrypt/encrypt ... %s" % ("OK" if reenc == raw else "MISMATCH"))
        ok &= reenc == raw
        rebuilt = doc.fh3.serialize(database=doc.playerdb)
        print("  ProfileData sections ... %s" % ("OK" if rebuilt == plain else "MISMATCH"))
        ok &= rebuilt == plain
        ss_raw = doc.fh3.sections["savestate"]
        ss_doc = BxmlDocument(ss_raw)
        ss_rt = ss_doc.serialize() == ss_raw
        print("  BXML round-trip ........ %s (%d objects, %d strings)" % (
            ss_rt, len(doc.savestate), len(ss_doc.strings)))
        ok &= ss_rt
        vf = doc.original.get("VersionFlags")
        if vf:
            vf_plain = cipher().decrypt(vf)
            vf_rt = cipher().encrypt(
                vf_plain, iv=vf[:16], padding=int.from_bytes(vf[16:20], "little")
            ) == vf
            print("  VersionFlags ........... %s (%s)" % (
                vf_rt, vf_plain[:4].hex()))
            ok &= vf_rt
    else:
        if "ProfileData" in doc.original:
            pd = ProfileData(doc.original["ProfileData"])
            rt = pd.serialize() == doc.original["ProfileData"]
            print("  ProfileData round-trip .. %s (%d records)" % (rt, len(pd)))
            ok &= rt
        if "SaveState" in doc.original:
            ss = SaveState(doc.original["SaveState"])
            rt = ss.serialize() == doc.original["SaveState"]
            print("  SaveState round-trip .... %s (%d objects)" % (rt, len(ss)))
            ok &= rt

    if doc.playerdb:
        try:
            n = doc.playerdb.row_count("Career_Garage")
            print("  PlayerDatabase ......... OK (%d garage rows)" % n)
        except Exception as exc:
            print("  PlayerDatabase ......... FAIL: %s" % exc)
            ok = False
    changed = doc.changed_blobs()
    print("  clean tree ............. %s" % ("OK" if not changed else changed))
    ok &= not changed
    print("Result: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def build_parser():
    # A parent with the same options but SUPPRESSed defaults, so that a value
    # given *before* the subcommand is not clobbered by the subparser.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS,
                        help="folder containing titles/ (default: current directory)")
    common.add_argument("--save", type=int, default=argparse.SUPPRESS,
                        help="save index (see 'list')")
    common.add_argument("--rev", type=lambda x: int(x, 0), default=argparse.SUPPRESS,
                        help="revision number (default: latest)")
    common.add_argument("--search", action="store_true", default=argparse.SUPPRESS,
                        help="also look up to 2 levels below --root for a 'titles' folder")

    p = argparse.ArgumentParser(
        prog="fh2save",
        description="Forza Horizon 2/3 (Xbox One) save editor.",
    )
    p.add_argument("--root", default=".",
                   help="folder containing titles/ (default: current directory)")
    p.add_argument("--save", type=int, default=0, help="save index (see 'list')")
    p.add_argument("--rev", type=lambda x: int(x, 0), default=None,
                   help="revision number (default: latest)")
    p.add_argument("--search", action="store_true",
                   help="also look up to 2 levels below --root for a 'titles' folder")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("list", parents=[common], help="list discovered saves")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("info", parents=[common], help="show revision info + verify")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("dump", parents=[common], help="dump a blob")
    sp.add_argument("blob", choices=["ProfileData", "SaveState", "BinarySaveState",
                                     "PlayerDatabase", "Database"])
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("set", parents=[common], help="set a well-known value")
    sp.add_argument("key")
    sp.add_argument("value")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("action", parents=[common], help="run a quick action")
    sp.add_argument("name")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_action)

    sp = sub.add_parser("addcar", parents=[common], help="clone a garage car with a new CarId")
    sp.add_argument("car_id")
    sp.add_argument("--clone-rowid", type=int, default=None)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_addcar)

    sp = sub.add_parser("selftest", parents=[common], help="round-trip sanity checks on a save")
    sp.set_defaults(func=cmd_selftest)

    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        return run_tui_or_help(parser)
    args = parser.parse_args(argv)
    if args.cmd is None:
        return run_tui_or_help(parser)
    return args.func(args)


def run_tui_or_help(parser):
    try:
        interactive = sys.stdout.isatty()
    except Exception:
        interactive = False
    if not interactive:
        parser.print_help()
        return 1
    from . import tui
    import curses

    args = parser.parse_known_args()[0]
    root = getattr(args, "root", ".")
    search = getattr(args, "search", False)
    sets = container.discover(root, search=search)
    if not sets:
        print("No Forza saves found at %s" % root)
        print("Point --root at the folder that contains 'titles/' "
              "(or add --search to look a little deeper).")
        return 1
    index = 0
    if len(sets) > 1 and sys.stdin.isatty():
        print("Multiple saves found:")
        for i, s in enumerate(sets):
            print("  [%d] %s / %s / %s" % (i, s.title_id, s.slot, s.user))
        try:
            index = int(input("Select save [0]: ") or "0")
        except Exception:
            index = 0
    # Must be set before curses is initialised (wrapper -> initscr).
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(tui.run, sets, index)
    return 0
