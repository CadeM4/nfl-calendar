# Internal contract

Normalized schedule is a JSON object with `schema_version: 1`, `season: int`,
`fetched_at: UTC ISO string`, `source: {name, url}`, `games: [...]`.

Each game is a dict:

```json
{"id":"2026-REG-BUF-MIA","season":2026,"season_type":"REG","week":1,
 "away":"BUF","home":"MIA","start_time":"2026-09-13T17:00:00Z",
 "date":"2026-09-13","time_tbd":false,"date_tbd":false,
 "week_date":"2026-09-13",
 "venue":{"name":"...","city":"...","state":"...","country":"..."},
 "broadcast":{"tv":[],"streaming":[],"notes":[]},
 "status":"scheduled","source_url":"https://...","source_ids":{}}
```

`REG` or `POST`; postseason week 1=Wild Card, 2=Divisional, 3=Conference,
5=Super Bowl (4 is Pro Bowl and excluded). Teams are canonical abbreviations,
or null for explicitly supplied postseason slots. REG ID is season + type +
away + home (ordered matchup occurs once a regular season); POST ID uses a
source-stable game identifier, persisted and reconciled across providers.
`start_time` is aware UTC or null. `date` is a confirmed Eastern date or null.
Unknown time is an all-day tentative event on a confirmed date. Unknown date
uses `week_date` as an explicitly labeled week placeholder, never as kickoff.
No unsupported postseason slots or inferred broadcasters.

Revision state maps game IDs to `{sequence, created, modified, fingerprint}`.
Calendar API: `render_calendar(games, season, name, revisions) -> bytes`;
`update_revisions(games, previous, now) -> dict`; `is_primetime(game) -> bool`.
Canonical teams: `TEAMS` dict keyed by abbreviation, values with `name`, `slug`,
`conference`, `division`; `canonical_team(value) -> str` resolves aliases.

Public `status.json` contains season, fetched_at, source, counts (regular,
postseason, total, teams), tbd (time, date, broadcast), and list `teams` with
id/name/slug/conference/division/count. `schedule.json` is normalized schedule.
Public feeds are at root: nfl-2026.ics, primetime.ics, and each team slug.ics.
Static site resides in `site/`, copied to `public/` by publisher. URLs derive
from current page URL; no deployment hostname is needed at build time.
