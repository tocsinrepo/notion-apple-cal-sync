"""One-off cleanup: remove duplicate Apple events created by the window bug.

Background
----------
Until commit 82fe4cb the Notion side read every dated page while the Apple side
read only a +/- window. Any Notion task dated outside that window looked, to
every run, like an Apple event that had been deleted — so the sync recreated it.
One fresh copy per run, forever. Jon's "Work" calendar ended up with 16 copies
each of the four HOA arrears tasks due in 2027 (plus another 13 each at a second
date), and a dozen copies each of five retired June tasks.

What this does
--------------
Groups every event whose UID ends in "@notion-apple-cal-sync" by its fingerprint
(title + start + end + all-day flag) and keeps exactly ONE per group. The
survivor is whichever copy sync_state.json already links to; failing that, the
lexicographically first UID, so repeat runs are deterministic.

Safety
------
  * A group with one member is never touched. This cannot delete a unique event.
  * A group with TWO OR MORE tracked copies is never touched either — that means
    Jon really does have two Notion pages with the same title and date, each
    correctly linked. Deleting one would only make the next sync recreate it.
  * Events NOT created by this sync (no matching UID suffix) are never touched.
  * Reports only, unless CONFIRM=delete is set.
  * Nothing here writes to Notion or to sync_state.json.

Run:  CONFIRM=delete python dedupe_apple.py
"""
import datetime as dt
import json
import os
from collections import defaultdict

from dateutil import tz
from icalendar import Calendar

import apple_side as ap
from config import Config

UID_SUFFIX = "@notion-apple-cal-sync"

# Deliberately much wider than the sync's own window — the whole point is to
# reach the far-future copies the sync cannot see.
SCAN_PAST_DAYS = int(os.getenv("SCAN_PAST_DAYS", "1500"))
SCAN_FUTURE_DAYS = int(os.getenv("SCAN_FUTURE_DAYS", "1500"))


def log(*a):
    print("[dedupe]", *a, flush=True)


def tracked_uids(path):
    """UIDs sync_state.json currently points at — these are the preferred keepers."""
    try:
        with open(path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        log("no readable state file; falling back to lowest-UID survivor")
        return set()
    return {lk.get("event_uid") for lk in state.get("links", []) if lk.get("event_uid")}


def scan(calendar):
    """Every sync-created event in the wide window, as (uid, fingerprint, obj)."""
    now = dt.datetime.now(tz=tz.gettz(Config.APPLE_TZ))
    results = calendar.search(
        start=now - dt.timedelta(days=SCAN_PAST_DAYS),
        end=now + dt.timedelta(days=SCAN_FUTURE_DAYS),
        event=True,
        expand=False,
    )
    out = []
    for ev in results:
        try:
            cal = Calendar.from_ical(ev.data)
        except Exception:
            continue
        for comp in cal.walk("VEVENT"):
            uid = str(comp.get("uid") or "")
            if not uid.endswith(UID_SUFFIX):
                break  # not ours — leave it completely alone
            item = ap._component_to_item(comp)
            fp = (
                item["title"].strip(),
                str(item["start"]),
                str(item["end"]),
                bool(item["all_day"]),
            )
            out.append((uid, fp, ev, item))
            break
    return out


def main():
    confirm = os.getenv("CONFIRM", "").strip().lower() == "delete"
    Config.validate()

    log("connecting to iCloud CalDAV ...")
    cal = ap.connect()
    log("using calendar:", getattr(cal, "name", "?"))

    keepers = tracked_uids(Config.STATE_FILE)
    log(f"{len(keepers)} uid(s) referenced by sync state")

    events = scan(cal)
    log(f"scanned {len(events)} sync-created event(s) "
        f"across -{SCAN_PAST_DAYS}/+{SCAN_FUTURE_DAYS} days")

    groups = defaultdict(list)
    for uid, fp, ev, item in events:
        groups[fp].append((uid, ev, item))

    dupes = {fp: g for fp, g in groups.items() if len(g) > 1}
    doomed = []
    protected = 0
    for fp, members in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
        members.sort(key=lambda m: m[0])
        tracked = [m for m in members if m[0] in keepers]
        if len(tracked) > 1:
            # Genuinely two Notion pages with the same title and date, each
            # correctly linked. Not our mess to clean.
            protected += 1
            log(f"  {len(members):3d}x  {fp[0][:58]!r}  {fp[1][:16]}  "
                f"-> SKIP, {len(tracked)} tracked copies (duplicated in Notion)")
            continue
        survivor = tracked[0] if tracked else members[0]
        losers = [m for m in members if m[0] != survivor[0]]
        doomed.extend(losers)
        log(f"  {len(members):3d}x  {fp[0][:58]!r}  {fp[1][:16]}  "
            f"-> keep {survivor[0][:8]}, drop {len(losers)}")

    log(f"groups: {len(groups)}   duplicated groups: {len(dupes)}   "
        f"protected: {protected}   copies to remove: {len(doomed)}")
    if not doomed:
        log("nothing to do — calendar is clean.")
        return

    if not confirm:
        log("REPORT ONLY. Re-run with CONFIRM=delete to remove them.")
        return

    removed = failed = 0
    for uid, ev, item in doomed:
        try:
            ev.delete()
            removed += 1
        except Exception as e:
            failed += 1
            log(f"  could not delete {uid[:8]} ({item['title'][:40]}): {e}")
    log(f"done. removed {removed}, failed {failed}, "
        f"survivors kept: {len(groups)}")


if __name__ == "__main__":
    main()
