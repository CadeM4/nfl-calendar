"""Fail closed before a fetched snapshot is allowed anywhere near published data."""

from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .teams import TEAMS


class ValidationError(ValueError):
    pass


def validate_schedule(schedule, previous=None, expected_regular=272, per_team=17):
    errors = []
    season = schedule.get("season")
    games = schedule.get("games", [])
    if not isinstance(season, int):
        raise ValidationError("Missing integer season")
    regular = [g for g in games if g.get("season_type") == "REG"]
    if len(regular) != expected_regular:
        errors.append(f"Expected {expected_regular} regular games; received {len(regular)}")
    ids = [g.get("id") for g in games]
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        errors.append("Duplicate or missing game IDs")
    matchups = Counter((g.get("away"), g.get("home")) for g in regular)
    if any(n != 1 for n in matchups.values()):
        errors.append("Duplicate regular-season matchup")
    team_counts = Counter(t for g in regular for t in (g.get("away"), g.get("home")))
    if set(team_counts) != set(TEAMS):
        errors.append("Regular schedule does not contain exactly all 32 canonical teams")
    if any(team_counts[t] != per_team for t in TEAMS):
        errors.append(f"Each team must have {per_team} regular games")
    if {g.get("week") for g in regular} != set(range(1, 19)):
        errors.append("Regular schedule must cover weeks 1–18")
    weekly_teams = Counter((g.get("week"), t) for g in regular for t in (g.get("away"), g.get("home")))
    if any(n > 1 for n in weekly_teams.values()):
        errors.append("A team appears more than once in a regular-season week")
    for g in games:
        label = g.get("id", "missing ID")
        try:
            if g.get("season") != season:
                raise ValueError("wrong season")
            if g.get("season_type") not in {"REG", "POST"}:
                raise ValueError("unsupported season type")
            if g.get("season_type") == "POST" and g.get("week") not in {1, 2, 3, 5}:
                raise ValueError("unsupported postseason round (Pro Bowl excluded)")
            if g.get("away") is not None and g.get("away") == g.get("home"):
                raise ValueError("home and away are identical")
            for side in ("away", "home"):
                if g.get(side) not in TEAMS and not (g["season_type"] == "POST" and g.get(side) is None):
                    raise ValueError(f"invalid {side} team")
            if not isinstance(g.get("week"), int):
                raise ValueError("missing week")
            if g.get("status") not in {"scheduled", "live", "final", "postponed", "cancelled"}:
                raise ValueError("unrecognized status")
            for field in ("date", "week_date"):
                if g.get(field):
                    d = date.fromisoformat(g[field])
                    if not date(season, 9, 1) <= d <= date(season + 1, 3, 1):
                        raise ValueError(f"{field} outside season")
            if g.get("start_time"):
                dt = datetime.fromisoformat(g["start_time"].replace("Z", "+00:00"))
                if dt.utcoffset() is None:
                    raise ValueError("naive kickoff timestamp")
                eastern_date = dt.astimezone(ZoneInfo("America/New_York")).date()
                if not date(season, 9, 1) <= eastern_date <= date(season + 1, 3, 1):
                    raise ValueError("kickoff outside season")
                if g.get("time_tbd") or g.get("date_tbd"):
                    raise ValueError("TBD game cannot claim a kickoff timestamp")
                if g.get("date") != eastern_date.isoformat():
                    raise ValueError("confirmed date disagrees with Eastern kickoff")
            elif not g.get("time_tbd"):
                raise ValueError("missing kickoff without explicit TBD flag")
            if g.get("date_tbd") and g.get("date"):
                raise ValueError("TBD date cannot claim a confirmed date")
            if not g.get("date") and not g.get("week_date"):
                raise ValueError("no confirmed date or explicitly labeled week anchor")
            b = g.get("broadcast", {})
            for field in ("tv", "streaming", "notes"):
                if not isinstance(b.get(field), list) or not all(isinstance(x, str) for x in b[field]):
                    raise ValueError(f"invalid broadcast.{field}")
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f"{label}: {exc}")
    if len([g for g in games if g.get("season_type") == "POST"]) > 13:
        errors.append("More than 13 postseason games")
    playoffs = [g for g in games if g.get("season_type") == "POST"]
    round_counts = Counter(g.get("week") for g in playoffs)
    for week, maximum in {1: 6, 2: 4, 3: 2, 5: 1}.items():
        if round_counts[week] > maximum:
            errors.append(f"Too many postseason games in round {week}: maximum {maximum}")
    playoff_teams = Counter((g.get("week"), team) for g in playoffs for team in (g.get("away"), g.get("home")) if team)
    if any(n > 1 for n in playoff_teams.values()):
        errors.append("A team appears more than once in a postseason round")
    if previous:
        if previous.get("season") != season:
            errors.append("Previous snapshot belongs to a different season")
        before = {g["id"]: g for g in previous.get("games", [])}
        after = {g["id"]: g for g in games}
        missing = before.keys() - after.keys()
        if missing:
            errors.append(f"Previously published games disappeared: {', '.join(sorted(missing))}")
        degraded = 0
        for ident in before.keys() & after.keys():
            old, new = before[ident], after[ident]
            if old.get("start_time") and not new.get("start_time"):
                degraded += 1
            if old.get("season_type") != new.get("season_type"):
                errors.append(f"Game type changed: {ident}")
        if degraded > 8:
            errors.append(f"Suspicious loss of confirmed kickoffs: {degraded} games")
        known_before = sum(bool(g.get("broadcast", {}).get("tv") or g.get("broadcast", {}).get("streaming")) for g in before.values())
        known_after = sum(bool(g.get("broadcast", {}).get("tv") or g.get("broadcast", {}).get("streaming")) for g in after.values())
        if known_before - known_after > 8:
            errors.append("Suspicious mass loss of broadcast information")
        streams_before = sum(bool(g.get("broadcast", {}).get("streaming")) for g in before.values())
        streams_after = sum(bool(g.get("broadcast", {}).get("streaming")) for g in after.values())
        if streams_before - streams_after > 8:
            errors.append("Suspicious mass loss of streaming information")
    if errors:
        raise ValidationError("Refresh rejected:\n- " + "\n- ".join(errors))
    return {"regular": len(regular), "postseason": len(games) - len(regular), "total": len(games), "teams": len(team_counts)}
