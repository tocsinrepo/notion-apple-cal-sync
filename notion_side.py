"""Notion side of the sync: read dated pages, create/update/archive pages.

Uses the plain REST API via `requests` so there is no heavy SDK dependency.
A normalized "item" dict looks like:
    {source, page_id, title, start, end, all_day, last_mod, archived}
where `start`/`end` are ISO strings ("YYYY-MM-DD" for all-day).
"""
import requests

from config import Config

API = "https://api.notion.com/v1"


def _headers():
    return {
        "Authorization": f"Bearer {Config.NOTION_TOKEN}",
        "Notion-Version": Config.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _read_title(props):
    for v in props.values():
        if v.get("type") == "title":
            txt = "".join(t.get("plain_text", "") for t in v.get("title", []))
            return txt or "(untitled)"
    return "(untitled)"


def _page_to_item(pg):
    props = pg.get("properties", {})
    dp = props.get(Config.NOTION_DATE_PROP, {})
    date = dp.get("date")
    if not date or not date.get("start"):
        return None
    start = date["start"]
    end = date.get("end")
    all_day = "T" not in start
    return {
        "source": "notion",
        "page_id": pg["id"],
        "title": _read_title(props),
        "start": start,
        "end": end,
        "all_day": all_day,
        "last_mod": pg.get("last_edited_time", ""),
        "archived": pg.get("archived", False),
    }


def fetch_pages():
    """Return all non-archived pages that have a date in the configured property."""
    items = []
    url = f"{API}/databases/{Config.NOTION_DATABASE_ID}/query"
    payload = {
        "page_size": 100,
        "filter": {"property": Config.NOTION_DATE_PROP, "date": {"is_not_empty": True}},
    }
    cursor = None
    while True:
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(url, headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        for pg in data.get("results", []):
            if pg.get("archived"):
                continue
            it = _page_to_item(pg)
            if it:
                items.append(it)
        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break
    return items


def _date_payload(item):
    d = {"start": item["start"]}
    if item.get("end"):
        d["end"] = item["end"]
    return d


def _props(item):
    return {
        Config.NOTION_TITLE_PROP: {"title": [{"text": {"content": item["title"]}}]},
        Config.NOTION_DATE_PROP: {"date": _date_payload(item)},
    }


def create_page(item):
    body = {"parent": {"database_id": Config.NOTION_DATABASE_ID}, "properties": _props(item)}
    r = requests.post(f"{API}/pages", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def update_page(page_id, item):
    r = requests.patch(
        f"{API}/pages/{page_id}", headers=_headers(), json={"properties": _props(item)}, timeout=30
    )
    r.raise_for_status()


def archive_page(page_id):
    r = requests.patch(
        f"{API}/pages/{page_id}", headers=_headers(), json={"archived": True}, timeout=30
    )
    r.raise_for_status()
