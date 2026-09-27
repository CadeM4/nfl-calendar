# NFL Calendar · 2026–27

One subscription for every NFL game. Official schedule and game-specific viewing information, refreshed four times daily. Free public GitHub Actions + GitHub Pages hosting; no API key, paid service, server, or database.

- **Website:** https://cadem4.github.io/nfl-calendar/
- **Master subscription:** https://cadem4.github.io/nfl-calendar/nfl-2026.ics
- **Apple Calendar:** [Subscribe to all NFL games](webcal://cadem4.github.io/nfl-calendar/nfl-2026.ics)
- **Teams:** [choose any of the 32 feeds](https://cadem4.github.io/nfl-calendar/#teams)
- **Every team HTTPS URL:** [feed directory](FEEDS.md)
- **Evening games:** https://cadem4.github.io/nfl-calendar/primetime.ics
- **Unresolved games:** [current TBD list](https://cadem4.github.io/nfl-calendar/tbd.md)
- **Health:** [last successful verification and counts](https://cadem4.github.io/nfl-calendar/status.json)

Independent fan project; not affiliated with the NFL. Code is MIT licensed; team marks and source data belong to their respective owners.

## Add it to your iPhone

1. Open the website in Safari on your iPhone.
2. Tap **Subscribe to all NFL games** (or select a team).
3. Confirm the calendar subscription. Future updates use that same URL.

If the webcal link does not open Calendar, copy the HTTPS master URL and use **Calendar → Calendars → Add Calendar → Add Subscription Calendar**. On iOS 26, tap **Find**, choose the account/color, and tap **Done**. Older versions may say **Subscribe**.

Settings fallback: **Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed Calendar**. Older iOS versions put Calendar directly in Settings. Paste the HTTPS URL and keep SSL enabled. See [Apple's subscription instructions](https://support.apple.com/102301) and [account setup guide](https://support.apple.com/guide/iphone/set-up-mail-contacts-and-calendar-accounts-ipha0d932e96/ios).

Subscribe using the URL; importing a downloaded `.ics` creates a static copy. Apple controls how frequently subscriptions refresh, so the six-hour server refresh is not an iPhone delivery guarantee. To avoid overlapping subscriptions, choose either the master feed or your desired team feeds. Identical game UIDs across feeds do not guarantee every client deduplicates across separate calendars.

## What is published

The initial verified release contains **272 regular-season games, all 32 teams, 17 games per team**, and **0 announced postseason games**. There are **24 date/time/broadcast TBD games**: four in Week 16, four in Week 17, and all sixteen in Week 18. The live status and TBD list above supersede these initial counts.

The master and team calendars automatically include officially published Wild Card, Divisional, Conference Championship, and Super Bowl games. Preseason and the Pro Bowl are excluded. There are 34 feeds: one master, 32 teams, and one evening feed. `primetime.ics` means a confirmed kickoff at or after 7 PM Eastern, not a claim that the game airs nationally.

Each event includes full team names, an estimated 3-hour-15-minute duration, available venue information, source-reported TV and streaming information, restrictions, and a link to its NFL game page. The calendars contain no alarms and do not block your availability.

TBD kickoff with a confirmed date becomes a tentative all-day event on that date. When both are unknown, the event appears on the NFL's published **week anchor date**, explicitly titled **[Date & time TBD]**. That anchor is not an asserted game date. The same event moves when a confirmed kickoff arrives. Calendar descriptions explain this.

## Architecture and repository

```text
src/nfl_calendar/
  sources.py       bounded official-source retrieval and hydration parsing
  normalization.py pure game, time, status and broadcast normalization
  teams.py         canonical teams, names and aliases
  validation.py    completeness, identity and regression gates
  calendar.py      iCalendar rendering and persisted revision metadata
  changes.py       meaningful schedule differences in Eastern time
  publishing.py    staged feed generation, parser verification, rollback
  cli.py           refresh orchestration and failure reporting
tests/             offline unit/integration tests and small official fixtures
data/              last known good normalized schedule + revision state
site/              hand-authored static HTML/CSS/JS source
public/            generated feeds, site, status, normalized data and changes
.github/workflows/ six-hour refresh/deployment and cross-platform tests
config.json        season and expected league-size configuration
SCHEMA.md          normalized source-adapter contract
```

Flow: **retrieve → normalize → validate against last good state → diff/revise → stage/parse every feed → persist → deploy**. Source adapters return the contract in `SCHEMA.md`; calendar generation knows nothing about NFL HTML or APIs. A replacement provider must honor these identities, timestamps and unknown-value semantics. Postseason IDs require an explicit migration map if switching away from NFL UUIDs.

## Data sources and accuracy

1. **Primary:** [NFL official schedule](https://www.nfl.com/schedules/) at season-specific `/schedules/2026/by-week/week-1` through `week-18`. JSON hydration contains the official weekly game details, stable NFL UUIDs, actual venues, kickoff timestamps, and week selectors.
2. **Viewing authority:** the same official page's game-specific [ways-to-watch](https://www.nfl.com/ways-to-watch/) records. Television and streaming are kept separate. Streaming is only added from a named official game broadcast or a game-level live US entitlement. Internal playback rendition names are not treated as streaming services.
3. **Secondary validation:** ESPN was independently checked for the initial release: all 272 matchups and all 248 confirmed kickoff times matched. This is an acceptance check, not a runtime dependency or automatic override of NFL data.
4. **Operational fallback:** retain the last known good published feed. The system deliberately does not silently substitute an unverified third-party schedule during an NFL outage.

An adapter verifies the exact season/week query, every game identity, and agreement between schedule and viewing records. It refuses pages redirected to the current week. Requests use 30-second timeouts, at most three attempts for transient failures, and three concurrent requests; approximately 18 pages per six-hour refresh plus advertised playoff rounds.

Viewing information is US-oriented. NFL+ live games have phone/tablet and local-market restrictions. Paramount+ and FOX One are limited to eligible local coverage; Sunday Ticket is shown separately with out-of-market and blackout qualifications when explicitly supplied. No service is inferred merely because a game is on CBS, FOX, NBC, etc. Initially, **119 games have explicit game-level streaming information**; the others are not padded with guessed services.

The NFL does not offer a documented, stable public API contract for this page. A frontend/schema change can interrupt refreshes and require an adapter update. Official venue metadata can contain older sponsorship names and may omit US states; the feed retains supplied facts rather than guessing replacements. Some future streaming entitlements are absent until closer to game day. A source omission is not evidence that a service will never carry a game.

## Times, identity and revisions

The canonical display timezone is **America/New_York**, using IANA rules. Timed events store UTC instants (`...Z`), so Apple/Google/Outlook display the correct local instant even if the device timezone changes. Descriptions explicitly display EDT or EST as appropriate. No fixed EST offset is used. All-day TBD placeholders intentionally use date values without a timezone.

Regular game identity is `season + REG + away + home`, independent of kickoff, week, venue and provider transport IDs. An ordered regular-season matchup is unique; validation enforces that. Postseason uses the NFL game UUID, allowing TBD participants to resolve without a new event. UIDs are deterministic hashes of these stable IDs.

Persisted `data/revisions-2026.json` stores CREATED, modified timestamp, semantic fingerprint and SEQUENCE. A meaningful change increments sequence and advances LAST-MODIFIED/DTSTAMP; an unchanged game keeps all those values. Never delete or regenerate this file independently of the feed. Missing/corrupt history fails the refresh instead of resetting client revision ordering.

`icalendar` renders UTF-8 escaping, CRLF and byte-safe line folding. Every generated feed is independently parsed before promotion, checking event count, unique UIDs, required fields, sensible intervals and RFC 5545 physical line lengths. Calendars use METHOD:PUBLISH, not meeting invitations.

## Local use (PowerShell)

Requires Python 3.11+ (CI uses 3.13) and Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m nfl_calendar
.\.venv\Scripts\python.exe -m http.server 8765 --directory public
```

Open http://localhost:8765. A local file URL cannot load the JSON preview. Localhost previews cannot serve a public iPhone subscription; use the deployed HTTPS address.

On macOS/Linux, use `.venv/bin/python` in place of `.venv\Scripts\python.exe`.

Offline rebuild for development:

```powershell
.\.venv\Scripts\python.exe -m nfl_calendar --input data/schedule-2026.json
```

This retains the snapshot's original verification timestamp; it does not claim to have contacted NFL servers. It still validates against the current persisted state.

## Deploy or reproduce in another GitHub account

The project uses a **public** repository so standard GitHub-hosted Actions runners and Pages hosting work on GitHub Free. [Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage) and [Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) document these limits.

1. Push this repository to a public GitHub repository with `main` as default branch (or fork it).
2. Under **Settings → Pages → Build and deployment → Source**, select **GitHub Actions**.
3. Under **Actions**, enable workflows if this is a fork, select **Refresh and publish NFL calendar**, then **Run workflow**.
4. Open the Pages URL displayed by the deployment. All feed links derive from the page's actual location, so no source hostname changes are needed. Update this README's example URLs for your account.

The workflow needs contents:write, pages:write and id-token:write; there are no custom secrets. Branch protection or organization policy must allow the workflow's generated-data commit. A protected-branch rejection stops deployment rather than publishing a feed whose revision history was not saved.

## Automatic refreshes and manual updates

Refresh runs at **02:23, 08:23, 14:23 and 20:23 UTC** every day, away from the busy top of the hour. GitHub's scheduler may run late; it is not an exact-time service. Successful refreshes commit the verified snapshot and outputs, including the new verification time, then deploy the complete `public/` artifact. A failed fetch, test, validation, render, or push prevents deployment and leaves the previous Pages feed online.

Manual refresh: **GitHub → Actions → Refresh and publish NFL calendar → Run workflow → main → Run workflow**. The run summary and `public/changes.md` / `changes.json` show the differences from the previous successful refresh. Git history retains previous changes even when the latest run has no event changes.

The site shows the last successful retrieval and warns after 18 hours without fresh data. GitHub sends failed-workflow notifications according to your account's notification settings. Check that Actions notifications are enabled if you want email alerts. GitHub can disable scheduled workflows in a public repository after 60 days without repository activity; successful snapshot commits provide ongoing activity, but a prolonged outage or disabled workflow may require manually re-enabling it. See [GitHub scheduling limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Safety gates and troubleshooting

- **Incomplete data:** exactly 272 regular games, all 18 weeks, 32 teams, 17 games per team, distinct ordered matchups, no self-play or duplicate weekly appearances are required. Playoff round limits are 6/4/2/1 with no team twice in one round.
- **Missing games:** any previously published game disappearing rejects the snapshot. Cancellations remain as STATUS:CANCELLED when explicitly reported, preserving event identity.
- **Unreasonable changes:** invalid/naive/out-of-season times, contradictory TBD flags, missing revision history, or loss of more than eight known kickoff, broadcast or streaming records rejects the update. Inspect large legitimate NFL corrections before changing a gate.
- **NFL page changed / HTTP failure:** inspect the failed Actions log and `sources.py`; the existing live feed remains available. Update fixtures/parser with actual source evidence and rerun tests. Do not bypass count checks to publish a partial season.
- **Stale iPhone calendar:** check the website's retrieval time and the Actions run first. If server data is fresh, allow Apple to refresh its subscription. Make sure you subscribed instead of importing a file.
- **Pages 404:** confirm a successful deployment and Settings → Pages → GitHub Actions. Use the URL's repository path, including the trailing slash for the website.
- **Push rejected:** pull/rebase current `main` and resolve the repository policy/conflict. Do not force-push over newer revision history. Rerun the workflow after fixing it.
- **State recovery:** restore a matching `data/` and `public/` pair from the same known-good Git commit; then refresh. Do not reset event sequences to zero.

## Next season

Set `season` in `config.json` to 2027 (the scheduled workflow's default), or run with `--season 2027` / environment variable `SEASON=2027`. A complete officially published season is required; an unreleased schedule fails safely. The master becomes `nfl-2027.ics`; previous season masters and state are retained. Team and evening URLs follow the configured active season. The season-specific master subscription intentionally remains on its named season; use the new master URL for a new season.

The 272/17/18 invariants reflect the current league format. A future league-format change requires updating the corresponding validation rules and tests rather than accepting an incomplete schedule.

## Verification

Offline tests cover source normalization (including real prior-season Super Bowl data), streaming restrictions, partial/redirected/malformed responses, duplicate detection, timezone rollover, September EDT and December EST, UTF-8 escaping/folding, stable UIDs, simulated flex updates, revision persistence, cancellations, TBD resolution, team filtering, and preservation of every published file on failed refreshes.

Desktop and 390px mobile browser checks cover rendered counts, all 32 team cards, conference/search filters, link targets, no horizontal overflow, and absence of JavaScript errors. Actual Apple subscription polling is controlled by Apple and needs to be observed on your device after subscribing.
