"""Deliberately synthetic complete league fixture; never used for production."""
from datetime import datetime, timedelta, timezone

from nfl_calendar.teams import TEAMS


def synthetic_schedule():
    ring = list(TEAMS)
    games = []
    for round_number in range(17):
        for i in range(16):
            away, home = ring[i], ring[-i - 1]
            week = round_number + 1 if round_number < 8 else round_number + 2
            if round_number == 8 and i < 8:
                week = 9
            kickoff = datetime(2026, 9, 10, 17, tzinfo=timezone.utc) + timedelta(weeks=week - 1)
            games.append({"id": f"2026-REG-{away}-{home}", "season": 2026, "season_type": "REG", "week": week,
                          "away": away, "home": home, "start_time": kickoff.isoformat(), "date": kickoff.date().isoformat(),
                          "week_date": kickoff.date().isoformat(), "date_tbd": False, "time_tbd": False,
                          "venue": {}, "broadcast": {"tv": ["TEST NETWORK"], "streaming": [], "notes": []},
                          "status": "scheduled", "source_url": "https://example.com/synthetic-test-only", "source_ids": {}})
        ring = [ring[0], ring[-1], *ring[1:-1]]
    return {"schema_version": 1, "season": 2026, "fetched_at": "2026-09-01T12:00:00Z",
            "source": {"name": "Synthetic test fixture", "url": "https://example.com"}, "games": games}
