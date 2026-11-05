# Field dictionary (checkpoint CP-2)

| Brief field | Column / source | Type | Notes |
|---|---|---|---|
| notice_id | `notices.external_id` | text | Source's own id (`data-notice-id` or RSS guid). Unique per source |
| agency | `agencies.name` via `sources` | text | |
| route_id | `notice_routes.route_id` | text | Many per notice. Upper-cased, validated `^[A-Z0-9][A-Z0-9._-]{0,11}$` |
| area | `notices.area` | text | May be empty |
| source_url | `notices.source_url` | text | Only http/https. Falls back to the source page URL |
| type | `notices.notice_type` | text | Diversion, Delay, Cancellation, Stop Closure, Planned Maintenance, Route Change, Other |
| summary | `notices.summary` | text | Whitespace normalised |
| published_at | `notices.published_at` | UTC ISO | Empty if the source gives none |
| valid_from / valid_to | `notices.valid_from` / `valid_to` | UTC ISO | `valid_to` NULL means "no end date announced" |
| latitude / longitude | `notices.latitude` / `longitude` | real | Optional. From `data-lat` / `data-lon` on the advisory. Out-of-range values are ignored with a warning. Changing a location updates the notice without creating a revision |
| status | computed in `compute_status` | derived | active / upcoming / stale / expired / withdrawn |
| observed_at | `notices.first_observed_at` | UTC ISO | First time we saw it |
| last_confirmed_at | `notices.last_confirmed_at` | UTC ISO | Last successful fetch that contained it |
| content_hash | `notices.content_hash`, `notice_revisions.content_hash` | SHA-256 | Over normalised tracked fields |
| revision_id | `notice_revisions.id` (`revision_no` per notice) | int | |
| change_summary | `notice_revisions.change_summary` | text | Plain-language difference |
| subscriber_filter | `subscriptions.route_filter` | text | NULL = all routes |
| alert_status | `notifications.status` | text | pending, demo_logged, smtp_accepted, failed, skipped |
| alerted_at | `notifications.alerted_at` | UTC ISO | When the alert was handled |

## Expected HTML structure (parser contract)

```html
<article class="advisory" data-notice-id="ID">
  <h2 class="advisory-title">...</h2>   <span class="advisory-type">...</span>
  <ul class="advisory-routes"><li>12A</li></ul>
  <!-- optional attributes on the article: data-lat="13.08" data-lon="80.27" -->
  <p class="advisory-area">...</p>      <p class="advisory-summary">...</p>
  <time class="advisory-published" datetime="..."></time>
  <time class="advisory-valid-from" datetime="..."></time>
  <time class="advisory-valid-to" datetime="..."></time>
  <span class="advisory-status">Active|Withdrawn</span>
  <a class="advisory-link" href="...">...</a>
</article>
```

## Error-handling strategy

| Problem | Behaviour |
|---|---|
| Timeout / connection error / 429 / 5xx | Retry with backoff up to `MAX_RETRIES`, then record a failed run. Existing data is kept, not re-verified |
| 4xx other than 429 | No retry, failed run |
| robots.txt disallows or is unreadable | No fetch, failed run |
| Item without an id | Skipped with a warning; withdrawal-by-absence is disabled for that run |
| Missing title/routes/dates | Stored as empty; warning logged; nothing invented |
| Unreadable date | Stored empty, warning logged |
| End before start | End ignored, warning logged |
| Zero notices when notices already exist | Treated as a failure (possible layout change), nothing withdrawn |
