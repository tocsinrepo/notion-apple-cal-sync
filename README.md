# Notion ⇄ Apple Calendar Sync

Two-way sync between a **Notion database** and your **Apple (iCloud) Calendar** — running for free on **GitHub Actions**, no server to babysit.

- A dated Notion page → becomes an event in Apple Calendar.
- An event in Apple Calendar → becomes a page in your Notion database.
- Edit either side → the change flows to the other. If both changed, the **newer edit wins**.

```
   ┌─────────────┐        every 20 min         ┌──────────────────┐
   │   NOTION    │  ◀────  GitHub Actions  ────▶ │  APPLE CALENDAR  │
   │  (database) │        runs sync.py          │    (iCloud)      │
   └─────────────┘                              └──────────────────┘
             mapping remembered in sync_state.json
```

---

## 🧩 What you need (gather these first)

1. A **Notion internal integration token** (starts with `secret_` or `ntn_`).
2. Your **Notion database ID**.
3. Your **Apple ID email**.
4. An **Apple app-specific password** (NOT your normal password).

Keep them handy for a few minutes — you'll paste them into GitHub.

---

## 🛠️ Setup — step by step

### Step 1 — Create the Notion integration
1. Go to **notion.so/my-integrations** → **New integration**.
2. Name it `Apple Cal Sync`, pick your workspace, submit.
3. Copy the **Internal Integration Secret** → this is your `NOTION_TOKEN`.

### Step 2 — Let the integration see your calendar database
1. Open your Notion **Tasks / Calendar database** as a full page.
2. Top-right **•••** → **Connections** → **Connect to** → pick `Apple Cal Sync`.

### Step 3 — Get the database ID
1. Copy the page URL. It looks like:
   `notion.so/Tasks-`**`d3406f60b6654bb48ff38b90cbea34b7`**`?v=...`
2. The 32-character chunk before `?v=` is your `NOTION_DATABASE_ID`.
   *(The default in this repo is already your Life OS → Tasks database.)*

### Step 4 — Make an Apple app-specific password
1. Go to **account.apple.com** → sign in → **Sign-In and Security** → **App-Specific Passwords**.
2. **Generate**, label it `cal-sync`, copy the `abcd-efgh-ijkl-mnop` value → this is `APPLE_APP_PASSWORD`.

### Step 5 — Add the secrets to GitHub
In this repo: **Settings → Secrets and variables → Actions → Secrets tab → New repository secret.** Add these four:

| Secret name | Value |
|---|---|
| `NOTION_TOKEN` | from Step 1 |
| `NOTION_DATABASE_ID` | from Step 3 |
| `APPLE_ID` | your iCloud email |
| `APPLE_APP_PASSWORD` | from Step 4 |

### Step 6 — (Optional) Add settings as Variables
Same page, **Variables tab**. All optional — skip to accept the defaults.

| Variable | Default | What it does |
|---|---|---|
| `APPLE_CALENDAR_NAME` | *(first calendar)* | Which iCloud calendar to use (exact name) |
| `APPLE_TZ` | `America/New_York` | Your timezone |
| `NOTION_DATE_PROP` | `Due` | The date property to sync |
| `NOTION_TITLE_PROP` | `Name` | The title property |
| `DRY_RUN` | `false` | `true` = preview only, writes nothing |
| `ALLOW_DELETES` | `false` | `true` = deleting on one side deletes on the other |

### Step 7 — Do a safe first run (IMPORTANT)
1. Add a Variable `DRY_RUN` = `true`.
2. Go to the **Actions** tab → **Notion ⇄ Apple Calendar Sync** → **Run workflow**.
3. Open the run and read the log. You'll see lines like `new notion -> create apple: ...`. Nothing is written yet — this is a preview.
4. If it looks right, set `DRY_RUN` = `false` and **Run workflow** again. Real sync happens.

### Step 8 — Let it run itself
After one good real run, it keeps running **every 20 minutes** automatically. You can always trigger it by hand from the **Actions** tab.

---

## 🛡️ Safety notes

- **`ALLOW_DELETES` is OFF by default.** With it off, if something disappears on one side the tool *recreates* it from the other side instead of deleting — so you never lose data by accident. Turn it on only once you trust the sync.
- **Always test with `DRY_RUN=true` first** after any change.
- The file `sync_state.json` is the memory linking the two sides. Don't delete it — if you do, the next run may create duplicates.

---

## 🧪 Run it locally (optional)
```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in your values
export $(grep -v '^#' .env | xargs)
python sync.py
```

---

## ⚠️ Limitations (v1)
- Syncs **title + date/time** only (not description, location, attendees, or recurring-event rules).
- Recurring Apple events are treated as their next single instance.
- All-day vs timed is inferred from whether the Notion date has a time.
- Conflict resolution is "newest edit wins" — it does not merge field-by-field.

PRs welcome. Built as a starting point — read `sync.py`; it's short and commented.
