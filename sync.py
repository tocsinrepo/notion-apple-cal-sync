"""Two-way sync orchestrator: Notion database  <->  Apple Calendar (iCloud).

Run:  python sync.py

How it works each run:
  1. Load the mapping store (sync_state.json).
  2. Read all dated Notion pages and all Apple events in the time window.
  3. For every existing link, detect what changed and propagate it. If both
     sides changed (a conflict), the side with the newer modification time wins.
  4. New Notion pages become Apple events; new Apple events become Notion pages.
  5. Save the updated mapping store.

Safety:
  * ALLOW_DELETES defaults to False. When off, a deletion on one side is treated
    as "recreate from the other side" instead of deleting data.
  * DRY_RUN=True logs everything but writes nothing.
"""
import datetime as dt

from dateutil import parser as dtparser
from dateutil import tz

import apple_side as ap
import notion_side as ns
import state as st
from config import Config


def log(*a):
    print("[sync]", *a, flush=True)


def _utc(value):
    """Parse an ISO timestamp into a UTC datetime. None if empty/unparseable."""
    if not value:
        return None
    try:
        d = dtparser.isoparse(str(value))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz.gettz(Config.APPLE_TZ))
    return d.astimezone(dt.timezone.utc).replace(microsecond=0)


def canon(item):
    """Fingerprint used to detect REAL changes between runs.

    Both sides are normalized so the same event yields the same string no
    matter which system reported it:
      * timed events -> absolute UTC instants (kills timezone/format drift)
      * a missing end on a timed event -> start + 30 min, which is what we
        actually write to the calendar, so "no end in Notion" matches the
        real event that comes back from iCloud
      * all-day events -> plain YYYY-MM-DD

    Without this normalization the sync considered every event "changed" and
    rewrote all of them on every run (runs grew from ~3s to 7+ minutes).
    """
    all_day = bool(item.get("all_day"))
    title = (item.get("title") or "").strip()
    if all_day:
        start = str(item.get("start") or "")[:10]
        end = str(item.get("end") or "")[:10]
        return f"{title}|{start}|{end}|AD"
    s = _utc(item.get("start"))
    e = _utc(item.get("end")) or (s + dt.timedelta(minutes=30) if s else None)
    return f"{title}|{s.isoformat() if s else ''}|{e.isoformat() if e else ''}|T"


def _newer(a, b):
    try:
        return dtparser.isoparse(a) >= dtparser.isoparse(b)
    except Exception:
        return True


def main():
    Config.validate()
    # Startup diagnostic — shows which values arrived, without leaking their contents.
    present = {
        "NOTION_TOKEN": bool(Config.NOTION_TOKEN),
        "NOTION_DATABASE_ID": bool(Config.NOTION_DATABASE_ID),
        "APPLE_ID": bool(Config.APPLE_ID),
        "APPLE_APP_PASSWORD": bool(Config.APPLE_APP_PASSWORD),
    }
    log("inputs present -> " + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in present.items()))
    log(f"apple calendar target: {Config.APPLE_CALENDAR_NAME or '(first writable)'}  tz={Config.APPLE_TZ}")
    try:
        log("notion token identity -> " + ns.whoami())
    except Exception as e:
        log("notion whoami failed:", e)

    dry = Config.DRY_RUN
    state = st.load_state(Config.STATE_FILE)
    links = state.get("links", [])

    log("connecting to iCloud CalDAV ...")
    cal = ap.connect()
    log("using calendar:", getattr(cal, "name", "?"))

    notion_items = ns.fetch_pages()
    apple_items = ap.fetch_events(cal)
    log(f"notion pages: {len(notion_items)}   apple events: {len(apple_items)}")

    by_page = {i["page_id"]: i for i in notion_items}
    by_uid = {i["uid"]: i for i in apple_items}

    new_links = []
    linked_pages = set()
    linked_uids = set()
    writes = 0

    # 1) Reconcile existing links.
    for lk in links:
        pid = lk.get("notion_id")
        uid = lk.get("event_uid")
        n = by_page.get(pid)
        a = by_uid.get(uid)

        if n is None and a is None:
            continue  # both gone — drop the link

        if n is None:  # Notion page disappeared
            if Config.ALLOW_DELETES:
                log("notion deleted -> delete apple:", lk.get("title"))
                if not dry:
                    ap.delete_event(cal, uid)
                writes += 1
                continue
            log("notion missing (deletes off) -> recreate in notion:", a["title"])
            npid = pid if dry else ns.create_page(a)
            writes += 1
            lk.update(notion_id=npid, notion_canon=canon(a), event_canon=canon(a))
            new_links.append(lk)
            linked_pages.add(npid)
            linked_uids.add(uid)
            continue

        if a is None:  # Apple event disappeared
            if Config.ALLOW_DELETES:
                log("apple deleted -> archive notion:", lk.get("title"))
                if not dry:
                    ns.archive_page(pid)
                writes += 1
                continue
            log("apple missing (deletes off) -> recreate in apple:", n["title"])
            nuid = uid if dry else ap.create_event(cal, n)
            writes += 1
            lk.update(event_uid=nuid, notion_canon=canon(n), event_canon=canon(n))
            new_links.append(lk)
            linked_pages.add(pid)
            linked_uids.add(nuid)
            continue

        # Both sides exist.
        linked_pages.add(pid)
        linked_uids.add(uid)
        n_canon, a_canon = canon(n), canon(a)
        n_changed = n_canon != lk.get("notion_canon")
        a_changed = a_canon != lk.get("event_canon")

        if n_changed and not a_changed:
            log("update apple  <- notion:", n["title"])
            if not dry:
                ap.update_event(cal, uid, n)
            writes += 1
            lk["notion_canon"] = n_canon
            lk["event_canon"] = n_canon
        elif a_changed and not n_changed:
            log("update notion <- apple:", a["title"])
            if not dry:
                ns.update_page(pid, a)
            writes += 1
            lk["notion_canon"] = a_canon
            lk["event_canon"] = a_canon
        elif n_changed and a_changed:
            if _newer(n.get("last_mod", ""), a.get("last_mod", "")):
                log("conflict -> notion wins:", n["title"])
                if not dry:
                    ap.update_event(cal, uid, n)
                writes += 1
                lk["notion_canon"] = n_canon
                lk["event_canon"] = n_canon
            else:
                log("conflict -> apple wins:", a["title"])
                if not dry:
                    ns.update_page(pid, a)
                writes += 1
                lk["notion_canon"] = a_canon
                lk["event_canon"] = a_canon

        lk["title"] = n["title"]
        new_links.append(lk)

    # 2) New Notion pages -> Apple.
    for i in notion_items:
        if i["page_id"] in linked_pages:
            continue
        log("new notion -> create apple:", i["title"])
        uid = f"dry-{i['page_id']}" if dry else ap.create_event(cal, i)
        writes += 1
        new_links.append({
            "notion_id": i["page_id"],
            "event_uid": uid,
            "notion_canon": canon(i),
            "event_canon": canon(i),
            "title": i["title"],
        })
        linked_uids.add(uid)

    # 3) New Apple events -> Notion.
    for i in apple_items:
        if i["uid"] in linked_uids:
            continue
        log("new apple  -> create notion:", i["title"])
        pid = f"dry-{i['uid']}" if dry else ns.create_page(i)
        writes += 1
        new_links.append({
            "notion_id": pid,
            "event_uid": i["uid"],
            "notion_canon": canon(i),
            "event_canon": canon(i),
            "title": i["title"],
        })

    state["links"] = new_links
    state["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
    st.save_state(Config.STATE_FILE, state)
    log(f"done. total links: {len(new_links)}  writes this run: {writes}  "
        f"(dry_run={dry}, allow_deletes={Config.ALLOW_DELETES})")
    if writes > 25:
        log("WARNING: unusually high write count — possible rewrite loop. Investigate.")


if __name__ == "__main__":
    main()
