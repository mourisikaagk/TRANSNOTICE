# Source approval document (task 01, checkpoint CP-1)

Complete one copy of the table below for every real source **before** setting `permission_status` to `approved`. Do not guess any answer: open the site and read it.

## Template

| Item | Answer |
|---|---|
| Agency and page name | |
| URL | |
| Access method | Official API / RSS / HTML page |
| Terms of use reviewed (date, link, quote of the relevant clause) | |
| robots.txt reviewed (date; is the path allowed?) | |
| Licence or written permission | |
| Fields available (map to the field dictionary) | |
| Refresh policy (minutes) and why it is polite | |
| Risks | Layout change, rate limiting, outage, wrong dates |
| Alternatives if refused | Official feed, open-data portal, email the agency, keep demo data |
| Approved by (mentor) and date | |

## Current status

| Source | Status |
|---|---|
| Demo feed (`DEMO-FEED`) | Local fictional data. No permission needed. Always labelled DEMO |
| Live sources | **None approved.** No real site has been reviewed for this project |

## Rules the code enforces

1. `robots.txt` is read before every host's first request; disallowed or unreadable means no fetch.
2. Minimum interval between requests to one host (`MIN_REQUEST_INTERVAL`).
3. Timeout, at most `MAX_RETRIES` attempts, exponential backoff, `Retry-After` honoured for 429.
4. No logins, no CAPTCHA handling, no private data.
5. A source with `permission_status != approved` or no `approval_document` is stored disabled.

## Third-party services (not notice sources)

| Service | Purpose | Data sent | Status |
|---|---|---|---|
| OpenStreetMap tiles | Map background | The browser requests tiles; OSM sees the viewer's IP and the page origin | Attribution shown on every map. Review the tile usage policy before wider use |
| Open-Meteo | Weather panel | The server sends only the configured latitude and longitude | Free non-commercial API, credit shown. Review terms before wider use. Weather is shown for context and is never used to create or change notices |

Neither service is a notice source and neither creates notices. If either is unavailable, the app says so and shows no substitute data.
