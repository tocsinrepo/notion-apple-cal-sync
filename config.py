"""Configuration, read from environment variables.

Every value has a safe default except the required secrets. Empty strings
coming from GitHub Actions (unset `vars`) fall back to the defaults.
"""
import os

# Jon's Life OS -> Agent Kanban tasks database, and its data source (collection).
# Repointed 2026-07-24: the previous default (d3406f60 / 4f410f8d) is now the
# retired "XXX- Archive Tasks" database. Live tasks are in "Agent Kanban".
# Notion's newer API queries the DATA SOURCE, not the database, so we keep both.
# To override without editing code, set NOTION_DATABASE_ID / NOTION_DATA_SOURCE_ID.
DEFAULT_DATABASE_ID = "9de9329a2e8d4cea8b6a56fca7583d3c"
DEFAULT_DATA_SOURCE_ID = "01d9a0e6-1da5-47fd-96c3-b26eadc88114"


def _s(name, default=""):
    v = os.getenv(name)
    return v if v else default


def _i(name, default):
    v = os.getenv(name)
    try:
        return int(v) if v else default
    except ValueError:
        return default


def _b(name, default=False):
    v = os.getenv(name)
    if not v:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Notion ---
    NOTION_TOKEN = _s("NOTION_TOKEN")
    NOTION_DATABASE_ID = _s("NOTION_DATABASE_ID", DEFAULT_DATABASE_ID)
    NOTION_DATA_SOURCE_ID = _s("NOTION_DATA_SOURCE_ID", DEFAULT_DATA_SOURCE_ID)
    NOTION_TITLE_PROP = _s("NOTION_TITLE_PROP", "Name")
    NOTION_DATE_PROP = _s("NOTION_DATE_PROP", "Due")
    NOTION_VERSION = _s("NOTION_VERSION", "2025-09-03")  # data-source-aware API

    # --- Apple / iCloud CalDAV ---
    APPLE_ID = _s("APPLE_ID")
    APPLE_APP_PASSWORD = _s("APPLE_APP_PASSWORD")
    APPLE_CALDAV_URL = _s("APPLE_CALDAV_URL", "https://caldav.icloud.com")
    APPLE_CALENDAR_NAME = _s("APPLE_CALENDAR_NAME")  # empty = first writable calendar
    APPLE_TZ = _s("APPLE_TZ", "America/New_York")

    # --- Sync behavior ---
    WINDOW_PAST_DAYS = _i("WINDOW_PAST_DAYS", 30)
    WINDOW_FUTURE_DAYS = _i("WINDOW_FUTURE_DAYS", 180)
    ALLOW_DELETES = _b("ALLOW_DELETES", False)   # default OFF — safest for v1
    DRY_RUN = _b("DRY_RUN", False)               # set true to preview with no writes
    STATE_FILE = _s("STATE_FILE", "sync_state.json")

    @classmethod
    def validate(cls):
        required = ("NOTION_TOKEN", "APPLE_ID", "APPLE_APP_PASSWORD")
        missing = [n for n in required if not getattr(cls, n)]
        if missing:
            raise SystemExit(
                "STOP: these GitHub secrets are missing or empty: "
                + ", ".join(missing)
                + ". Add them under Settings -> Secrets and variables -> Actions."
            )
