# Final report outline (Cybernaut WEB-07 structure)

1. **Cover page**: title, student/team IDs, mentor, academic year.
2. **Abstract and context**: problem (passengers lack clear, current service-change information), stakeholders, success criteria.
   - Success criteria: no duplicates on repeat runs; expired notices never active; failed fetches never refresh data; one alert per revision; every notice shows source and last-confirmed time.
3. **Source selection**: complete `docs/SOURCE_APPROVAL.md` for each real source (permission, robots.txt, terms, URLs, crawl policy). State clearly if only demo data was used.
4. **SRS**: use cases, functional and non-functional requirements, architecture and ER diagram (`docs/ARCHITECTURE.md`).
5. **Implementation**: collection logic, normalisation, scheduling, change detection.
6. **Testing**: test cases, sample inputs, expected vs actual (`docs/TEST_RESULTS.md`), your own screenshots.
7. **Evaluation**: collection quality, alert precision, refresh time, limitations.
8. **Deployment**: setup steps, sanitised configuration, monitoring (Admin run log, `logs/transitnotice.log`).
9. **Ethics and conclusion**: privacy (minimal data; e-mail optional), compliance, known gaps, future work.
10. **Appendix**: source-attributed screenshots, sample records, Git commit evidence (`git log --oneline`).

## Personas (edit to match real people you interview)

**Priya, daily commuter (age 24, college).** Uses route 12A and 12B. Needs to know before leaving home if the bridge is closed and until when. Usefulness: one place to check, last-verified time shows how far to trust it. Limitation: she must open the dashboard; alerts are demo-logged unless e-mail is configured.

**Mr. Rajan, evening-shift supervisor (age 45).** Travels by route 45 and plans around festival diversions. Needs advance notice of upcoming diversions and their end. Usefulness: "Upcoming" status and service-date filter. Limitation: notices with no end date give no planning certainty.

## Usefulness and limitations of scheduled public-source monitoring

Useful: consistent history, change explanations, one searchable view, honest freshness. Limited by: check interval (a change can be missed until the next run), what the agency publishes, layout changes that break parsing, no guarantee that an agency page is complete, and permission constraints on scraping.

## Marks checklist (100)

Problem and approval 10 / Source rights and data quality 15 / Extraction and parsing 15 / Persistence and repeatability 15 / Real-time updates and alerts 15 / UI 10 / Testing and live challenge 10 / Report, code, viva 10.
