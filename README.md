# TransitNotice: Public Transport Service Update Tracker

Cybernaut WEB-07 mini project. TransitNotice collects service advisories from permitted sources, detects what changed, keeps a revision history, and shows everything on a searchable dashboard with an honest "last verified" time.

Out of the box it runs in **DEMO MODE** with fictional sample notices. No live transport source is enabled until you document and approve it (see `docs/SOURCE_APPROVAL.md`).

## Windows setup (PowerShell or Command Prompt)

Requires Python 3.10 or newer (`py --version`).

```
cd TransitNotice
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and set `SECRET_KEY` and `ADMIN_TOKEN` to your own values. In PowerShell, if activation is blocked, run `Set-ExecutionPolicy -Scope Process RemoteSigned` first.

## Initialise the database and run

```
flask --app app init-db
flask --app app scrape
python app.py
```

Open http://127.0.0.1:5000. The app also creates the database on first start, so `init-db` is mainly for the checkpoint demo.

Other commands: `flask --app app reset-demo` resets the sample feed. Set `ENABLE_SCHEDULER=true` in `.env` to check sources automatically in the background.

## Run the tests

```
python -m pytest -v
```

Tests use mocked HTTP and saved HTML/XML fixtures. They never touch the internet. Results from the last run are in `docs/TEST_RESULTS.md`.

## New in version 2

| Feature | Where |
|---|---|
| Dark mode, Feed/Table layouts, route colours | header buttons, list toolbar |
| Developer view (ids, hashes, snapshots) | header switch, **visible and served only to a signed-in admin** |
| Sign up / log in, saved routes, alerts inbox. My routes sends visitors to login first and returns them afterwards | `/account`, `/my-routes` |
| Back button on every page except Notices | top of each page |
| Street map of notices that have coordinates | `/map` (Leaflet, bundled; tiles from OpenStreetMap) |
| Service diagram (schematic, one line per route) | `/map`, below the street map |
| Weather panel (Open-Meteo, live data only) | dashboard sidebar |
| "What changed recently" panel | dashboard sidebar |

### Upgrading from version 1

1. Stop the app (`Ctrl+C`).
2. Extract the new zip **over** your existing `TransitNotice` folder and choose "Replace". Your `venv`, `.env` and `instance` folders are not in the zip, so they are kept.
3. `pip install -r requirements.txt` (no new packages, safe to run).
4. Add the new lines from `.env.example` (weather and map settings) to your `.env`. The defaults work without them.
5. `python -m pytest -q`, then `python app.py`. The database upgrades itself on start (migration `002`). Your notices and history are kept; the demo feed is upgraded in place, so no fake revisions appear.

Notices, the map and notice details stay public; only My routes needs an account.

### Accounts and privacy

An account stores only an e-mail address, a salted PBKDF2 password hash, the routes you follow and your alert history. Passwords are never stored or logged in plain text, login is throttled (5 failures per 10 minutes per e-mail and address), and "Delete my account and data" removes everything. Admin access is separate and still needs `ADMIN_TOKEN`. Account alerts are recorded inside the app; they are not e-mailed.

### Map, weather and third-party services

| Service | Used for | Needs internet | Terms |
|---|---|---|---|
| OpenStreetMap tile server | map background | Yes (browser) | Keep the attribution; light use only. See https://operations.osmfoundation.org/policies/tiles/ |
| Open-Meteo | weather panel | Yes (server) | Free for non-commercial use, credit "Weather data by Open-Meteo.com". See https://open-meteo.com/en/terms |
| Leaflet 1.9.4 | map library | No (bundled in `static/vendor/leaflet`, BSD-2) | Licence file included |

Turn them off with `MAP_TILES_ENABLED=false` and `WEATHER_ENABLED=false`. Pins appear only for notices whose source supplied coordinates. The demo notices carry fictional positions and are labelled "DEMO location". Check both services' current terms before any use beyond a student demonstration.

## How it works

1. **Adapters** (`scraper/adapters.py`) fetch a source. The demo adapter renders a local JSON feed to HTML; HTML and RSS adapters fetch real URLs through `scraper/fetcher.py` (timeout, limited retries, exponential backoff, robots.txt, per-host rate limit).
2. **Parser** (`scraper/parser.py`) turns HTML/RSS into `ParsedNotice` objects. Missing fields stay empty; nothing is invented.
3. **Ingestion** (`services/ingest_service.py`) upserts in one transaction. A SHA-256 hash of the normalised content is the quick change check; `scraper/change_detector.py` then explains the field-level difference.
4. **Revisions**: every real change adds a row to `notice_revisions`. Repeat runs of unchanged data only refresh `last_confirmed_at`.
5. **Notifications** (`services/notification_service.py`): one row per (subscription, revision), enforced by a UNIQUE constraint.
6. **Dashboard** (`app.py`, `templates/`, `static/`) computes status at read time, so an expired notice can never be shown as active.

## Time zone

All timestamps are stored in UTC (`YYYY-MM-DDTHH:MM:SSZ`) and displayed in `DISPLAY_TIMEZONE` (default `Asia/Kolkata`, IST). Source times without an offset are read in the source's configured zone. A date-only end date means the end of that day (23:59:59 local). A date-only start means the start of the day.

## Status rules

| Status | Meaning |
|---|---|
| Active | Window has started, has not ended (or has no end date), and was confirmed within `FRESHNESS_MINUTES` |
| Upcoming | Start time is in the future and confirmed recently |
| Stale | Active or upcoming, but not confirmed within `FRESHNESS_MINUTES`. Shown as stale, never as live |
| Expired | End time has passed |
| Withdrawn | The source marked it withdrawn, or dropped it from a complete listing |

A failed source check changes nothing about notices: their `last_confirmed_at` stays put, so they age into "stale".

## Enabling a real source

Copy `sample_data/live_sources.example.json`, fill in the entry, set `LIVE_SOURCES_FILE` in `.env`. The source is enabled only if `permission_status` is `approved` and `approval_document` is filled in. Read `docs/SOURCE_APPROVAL.md` first. Prefer an official RSS/API feed over scraping a page.

## Optional e-mail

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM` in `.env`. Then e-mail subscriptions become available in Admin. A message is marked `smtp_accepted` when the mail server accepts it. Inbox delivery cannot be confirmed over SMTP, so the app never claims it. Use an app password, never your main password.

## Security notes

Parameterised SQL everywhere; CSRF token on every POST; admin actions need `ADMIN_TOKEN`; secrets only in `.env`; strict Content-Security-Policy; RSS parsed with `defusedxml`; only http/https links are kept; error logs hold no tokens or e-mail addresses.

## Backup and recovery

The whole state is one SQLite file.

```
copy instance\transitnotice.db backups\transitnotice-2026-10-29.db
```

Stop the app first, or use `sqlite3 instance\transitnotice.db ".backup backups\copy.db"`. To recover, stop the app and copy the backup over `instance\transitnotice.db`. If the file is lost, delete `instance\*.db*`, run `flask --app app init-db`, then `flask --app app scrape`; notices are rebuilt from the source (revision history before the loss is not recoverable without a backup).

## Git

```
git init
git add .
git commit -m "Initial TransitNotice project"
```

Check `git status` first: `.env`, `instance/*.db` and logs are ignored. Use small commits per feature (for example `git commit -m "Add change detection"`) so the history shows your progress.

## Deployment (not tested by the author)

For a demo, run on your laptop. For a small server: use Linux, install requirements, set real `SECRET_KEY`/`ADMIN_TOKEN` in the environment, run behind HTTPS with `waitress-serve --call app:create_app` (add `waitress` to requirements; Windows-friendly) or gunicorn on Linux, and run ONE process only (the scheduler thread and SQLite are designed for a single process). Run `ENABLE_SCHEDULER=true`. This path has not been verified by the author.

## Known limitations

- My routes needs an account (there is no browser-only mode).
- Account alerts stay in the app (no e-mail for accounts); there is no password-reset flow.
- Map and weather need internet. The street map, dark mode, follow buttons and weather rendering were checked by reading the code and by server-side tests, but not clicked through in a real browser by the author.
- The dashboard shows up to 300 notices and has no pagination.
- HTML scraping assumes the `article.advisory` structure in `scraper/parser.py`; each real site needs its own parser/selectors.
- The RSS parser does not read validity dates (feeds rarely carry them); those stay empty.
- Absent-from-listing withdrawal only applies to sources marked `complete_listing`.
- Manual refresh runs inside the web request; a slow live source can make the button wait.
- No "plan a trip", station exit, restroom or AI assistant features: they need routing/station data or paid services.
- Single process only. No screenshots or deployment results are included.
