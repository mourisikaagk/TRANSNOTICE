# Viva guide

## Where to look (so you can explain and edit it yourself)

| Topic | File and function |
|---|---|
| How an advisory is read from HTML | `scraper/parser.py` `parse_notices_html` |
| Dates and time zones | `scraper/parser.py` `parse_datetime`, `timeutil.py` |
| Change hash and differences | `scraper/change_detector.py` `content_hash`, `diff_content` |
| Insert or update without duplicates | `services/ingest_service.py` `ingest_notices` |
| Active / upcoming / expired / stale | `services/notice_service.py` `compute_status` |
| Search and route filter SQL | `services/notice_service.py` `list_notices` |
| One alert per revision | `UNIQUE (subscription_id, revision_id)` and `queue_notifications` |
| Retries and robots.txt | `scraper/fetcher.py` `Fetcher.get` |

## Questions and answers

**1. What does TransitNotice do?** It collects public transport advisories from permitted sources, stores them, detects changes, and shows them with a clear last-verified time.

**2. Why SQLite?** It needs no server, is a single file, supports constraints and transactions, and is enough for one process. A busy multi-user system would need PostgreSQL.

**3. How do you avoid duplicate notices?** `UNIQUE (source_id, external_id)`. Ingestion looks the notice up first; if it exists it updates, otherwise inserts. Running the scraper ten times gives the same rows.

**4. What is a content hash?** A SHA-256 fingerprint of the normalised fields. Same data gives the same hash, so unchanged notices are skipped quickly. When the hash differs, `diff_content` finds which fields changed.

**5. Why store both a hash and field-level changes?** The hash only says "something changed". The field comparison says what, so users read "end time moved from X to Y".

**6. How do you stop repeated alerts?** One `notifications` row per (subscription, revision) with a UNIQUE constraint. A revision is created only on a real change.

**7. What does "stale" mean?** An active or upcoming notice that no successful fetch has confirmed within `FRESHNESS_MINUTES`. It is shown as stale, never as live.

**8. What happens when the source is down?** The run is logged as failed, the source keeps its old `last_success_at`, and notices keep their old `last_confirmed_at`. Nothing is deleted or refreshed.

**9. Why do you store UTC?** UTC has no daylight-saving shifts and sorts as text. Conversion to IST happens only when displaying.

**10. A notice has no end date. What happens?** `valid_to` stays NULL. It is active from its start until the source changes it. We never invent an expiry; the UI says "No end date announced".

**11. How is "expired" decided?** At read time: `now > valid_to`. It is not stored, so it can never be out of date.

**12. How do you respect websites?** robots.txt check, minimum interval per host, timeout, limited retries with backoff, honest User-Agent, no logins or CAPTCHA bypass, and a written approval before enabling a source.

**13. What is SQL injection and how do you avoid it?** Attacker text becoming SQL. All queries use `?` or `:name` parameters; the search text is also escaped for LIKE wildcards.

**14. What is CSRF?** A malicious site making your browser submit a form. Every POST needs a secret per-session token.

**15. Why is the demo data labelled?** So fabricated notices can never be mistaken for real information.

**16. Limitations?** Single process, no user accounts, no pagination, each real site needs its own parser, RSS has no validity dates, no live source approved.

## Version 2 questions

**17. How are passwords stored?** Never as text. `generate_password_hash` makes a salted PBKDF2-SHA256 hash; login compares with `check_password_hash`. A leaked database does not reveal passwords directly.

**18. How do you slow down password guessing?** After 5 failures for the same e-mail and address within 10 minutes, login is refused. An unknown e-mail takes the same time and gives the same message as a wrong password, so attackers cannot learn which e-mails exist.

**19. What is session fixation and how do you avoid it?** An attacker plants a session id before login. On login the session is cleared and a new CSRF token is issued.

**20. Why does My routes need an account, and how does the redirect work?** Followed routes and alerts belong to a person, so they are stored in `user_routes` and `subscriptions` under a user id. A visitor opening My routes is redirected to login with `next=/my-routes`; after login the app returns there. `next` is accepted only if it is a same-site path (starts with one `/`, not `//`), which blocks open-redirect attacks.

**21. Why does the map not show every notice?** Pins appear only when the source supplied coordinates. Guessing a place would be inventing data. The service diagram uses route data only and is labelled a schematic.

**22. Why is Leaflet bundled and not loaded from a CDN?** The Content-Security-Policy only allows our own scripts. Bundling keeps that strict and lets the page work with the map library offline (tiles still need internet).

**23. How do you stop XSS (script injection) on the map?** Titles from sources are put into popups with `textContent`, never `innerHTML`, and the pin data is embedded with `tojson`, which escapes `<`, `>` and quotes.

**24. How do alerts for an account avoid duplicates?** Following a route creates one subscription (unique per user and route). Each revision then produces at most one notification per subscription because of the `UNIQUE (subscription_id, revision_id)` constraint.

**26. Why is the Developer view admin-only?** Hashes, ids and raw snapshots are internal details. They are not hidden by CSS; they are not sent to non-admin visitors at all, so they cannot be read from the page source.

**25. Does weather change the notices?** No. It is shown for context from a separate service. If the service fails the panel says it is unavailable.

## Modify live (practice these)

1. **Add a new notice type keyword.** In `parser.py` add `"strike"` to the Cancellation tuple in `NOTICE_TYPES`. Run `pytest tests/test_parser.py`.
2. **Read a new date format.** Add `"%d.%m.%Y %H:%M"` to `DATE_FORMATS`. Add a test next to `test_helpers`.
3. **Count notices per route (SQL).**
   ```sql
   SELECT route_id, COUNT(*) AS notices FROM notice_routes GROUP BY route_id ORDER BY notices DESC;
   ```
4. **Notices with no end date.** `SELECT external_id, title FROM notices WHERE valid_to IS NULL;`
5. **Revision history of one notice.** `SELECT revision_no, change_type, change_summary FROM notice_revisions WHERE notice_id = 1 ORDER BY revision_no;`
6. **Change the freshness period.** `FRESHNESS_MINUTES` in `.env`; no code change.
7. **Followed routes per user (SQL).** `SELECT u.email, COUNT(*) FROM users u JOIN user_routes r ON r.user_id = u.id GROUP BY u.id;`
8. **Notices with a location.** `SELECT external_id, latitude, longitude FROM notices WHERE latitude IS NOT NULL;`
9. **Change the lockout limit.** `max_login_failures` in `config.py`.
