# Demonstration script (six mentor checkpoints)

Before starting: `flask --app app reset-demo`, delete `instance\transitnotice.db*`, set `FRESHNESS_MINUTES=2` in `.env` for the stale demo, start with `python app.py`. Admin token is in your `.env`.

## CP-1 Problem, data rights, measurable requirements
Show `docs/SOURCE_APPROVAL.md` and the personas in `docs/REPORT_OUTLINE.md`. State the measurable requirements: no duplicate notices after repeated runs; an expired notice is never "active"; a failed fetch never refreshes data; one alert per revision.

## CP-2 Extraction, field dictionary, error strategy
Open `docs/FIELD_DICTIONARY.md`. Run `python -m pytest tests/test_parser.py -v`. Open `tests/fixtures/missing_fields.html` and show the matching test output (skipped item, empty fields, ignored bad end date).

## CP-3 Database design and repeat runs
Open `docs/ARCHITECTURE.md` (ER diagram). Run `flask --app app scrape` twice. In the Admin "Recent collection runs" table: first run `new=6`, second run `unchanged=6`. Show the UNIQUE constraints in `database/migrations/001_initial.sql`.

## CP-4 Scheduling, history, reliable alerts
Set `ENABLE_SCHEDULER=true` and `REFRESH_INTERVAL_MINUTES=1`, restart. Admin > "Extend outage by 24 h", wait one minute. Open the notice: Revision 2 "Validity extended". Admin > Notification log: exactly one new row for that revision, status "demo logged".

## CP-5 Two browser sessions and a source update
Session A (normal window): dashboard. Session B (private window): Admin sign-in. In B click "Add advisory with no end date" then "Run all sources now". In A, within about 20 seconds the "Notices have changed" banner appears; reload to see DEMO-099 listed with "No end date announced".

## CP-6 Failure simulation and viva
1. Admin > "Simulate source failure" > "Run all sources now". Dashboard: red "latest check failed" banner; notices keep their old "last confirmed" time.
2. Wait past `FRESHNESS_MINUTES`: active notices turn **Stale** (dashed, "was active").
3. Admin > "Restore source" > run: stale notices return to Active, and no duplicates appear.
4. Mentor challenges: "Extend outage by 24 h" (done in CP-4); "Add advisory with no end date" (done in CP-5).
5. Live viva: see `docs/VIVA.md`, section "Modify live".

## Version 2 extras (optional, 5 minutes)

1. **Feed and Table views, dark mode:** click Table, then Dark mode. Reload: both choices are remembered.
2. **Developer view (admin only):** sign in as admin; the Developer view switch appears in the header. Turn it on: each row shows its id, hash and revision count; open a notice to see the raw snapshot. Use this when the mentor asks "how do you know it changed?". A normal visitor never sees it.
3. **My routes needs login:** as a visitor click My routes: you are sent to the login page. Sign up; you land on My routes. Open Riverside Bridge, press Follow 12A, open My routes: notices for 12A appear. Use the Back button on any page except Notices.
4. **Account alerts:** Sign up, follow 12A. In Admin run "Extend outage by 24 h" then "Run all sources now". My routes > Your alerts shows one "Validity extended" entry. Run sources again: still one.
5. **Map and diagram:** open Map. Click a pin. State that pins are fictional demo positions and that notices without coordinates are not pinned. Scroll to the Service diagram.
6. **Weather:** the sidebar shows live conditions when online. Switch off Wi-Fi and reload: it says "unavailable" and shows nothing invented.

## Acceptance tests quick map

| Acceptance test | Automated test |
|---|---|
| Expired not active | `test_expired_and_upcoming_status`, `test_expired_notice_is_not_active_on_page` |
| Multi-route filter | `test_multiple_routes_stored_and_filterable`, `test_route_filter_matches_notices_with_multiple_routes` |
| Extension keeps history | `test_extension_updates_same_notice_and_keeps_history`, `test_mentor_extends_outage_by_24_hours` |
| Time zone documented | `tests/test_timeutil.py`, README "Time zone" |
| Stale labelled | `test_old_notices_become_stale_not_live`, `test_stale_data_labelled_after_failed_refresh` |
| Failed fetch no refresh | `test_failed_fetch_does_not_refresh_old_data` |
| No repeat duplicates/alerts | `test_repeated_runs_create_no_duplicates_or_alerts`, `test_each_revision_alerts_once` |
| Missing end date safe | `test_missing_end_date_is_stored_as_null_and_stays_active`, `test_advisory_without_end_date_does_not_crash` |
