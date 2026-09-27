"""RFC 5545 subscriptions with stable identities and persistent revisions.

Providers supply facts. This module never infers networks, streaming rights,
stadiums or kickoff times. UTC event values display correctly in any device
timezone; descriptions explicitly use America/New_York, including DST.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, vDuration

from .teams import TEAMS, canonical_team

EASTERN = ZoneInfo("America/New_York")
GAME_DURATION = timedelta(hours=3, minutes=15)
POSTSEASON_ROUNDS = {
    1: "Wild Card", 2: "Divisional Round", 3: "Conference Championships",
    5: "Super Bowl",
}


def _instant(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"A timezone-aware timestamp is required: {value!r}")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value: str | datetime) -> str:
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return sorted({str(item).strip() for item in value if str(item).strip()}, key=str.casefold)


def _facts(game: Mapping[str, Any]) -> dict[str, Any]:
    """Only visible facts affect a revision; fetching alone never churns it."""
    fields = (
        "season", "season_type", "week", "away", "home", "start_time", "date",
        "time_tbd", "date_tbd", "week_date", "status", "source_url", "name", "label",
    )
    result = {key: game.get(key) for key in fields}
    if result["start_time"]:
        result["start_time"] = _timestamp(result["start_time"])
    venue = game.get("venue") or {}
    result["venue"] = {key: venue.get(key) for key in ("name", "city", "state", "country")}
    broadcast = game.get("broadcast") or {}
    result["broadcast"] = {key: _strings(broadcast.get(key)) for key in ("tv", "streaming", "notes")}
    result["notes"] = _strings(game.get("notes"))
    return result


def _fingerprint(game: Mapping[str, Any]) -> str:
    payload = json.dumps(_facts(game), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def update_revisions(
    games: Iterable[Mapping[str, Any]], previous: Mapping[str, Any], now: str | datetime,
) -> dict[str, Any]:
    """Preserve CREATED/DTSTAMP for unchanged games; advance changed sequences.

    Keep old revision records as well, so a removed and later restored game
    cannot accidentally reset its sequence. The caller decides which games
    are safe to publish and persists this state only after validation.
    """
    revisions = copy.deepcopy(dict(previous))
    current_time = _instant(now)
    seen = set()
    for game in games:
        identifier = game.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("A stable game id is required")
        if identifier in seen:
            raise ValueError(f"Duplicate game id: {identifier}")
        seen.add(identifier)
        fingerprint = _fingerprint(game)
        old = previous.get(identifier)
        if old and old.get("fingerprint") == fingerprint:
            continue
        modified = current_time
        if old:
            # Protect client ordering during retries or a backwards host clock.
            modified = max(modified, _instant(old["modified"]) + timedelta(seconds=1))
        revisions[identifier] = {
            "sequence": int(old["sequence"]) + 1 if old else 0,
            "created": old["created"] if old else _timestamp(current_time),
            "modified": _timestamp(modified),
            "fingerprint": fingerprint,
        }
    return revisions


def game_uid(game: Mapping[str, Any]) -> str:
    """Identity depends only on the persisted game id, never its kickoff."""
    identifier = game.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("A stable game id is required")
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32] + "@nfl-calendar.local"


def _round(game: Mapping[str, Any]) -> str:
    if game.get("season_type") == "POST":
        week = int(game["week"])
        if week not in POSTSEASON_ROUNDS:
            raise ValueError(f"Unsupported postseason round: {week}")
        return POSTSEASON_ROUNDS[week]
    if game.get("season_type") != "REG":
        raise ValueError("Only regular-season and postseason games belong in this feed")
    return f"Week {game['week']}"


def _team_name(team: str | None) -> str:
    return TEAMS[canonical_team(team)]["name"] if team else "Team TBD"


def _matchup(game: Mapping[str, Any]) -> str:
    if not game.get("away") and not game.get("home"):
        return str(game.get("name") or game.get("label") or f"{_round(game)} — Teams TBD")
    return f"{_team_name(game.get('away'))} @ {_team_name(game.get('home'))}"


def _location(game: Mapping[str, Any]) -> str:
    venue = game.get("venue") or {}
    locality = ", ".join(str(venue[key]) for key in ("city", "state") if venue.get(key))
    country = venue.get("country")
    if country and str(country).strip().casefold() not in {"us", "usa", "united states", "united states of america"}:
        locality = ", ".join(filter(None, (locality, str(country))))
    return "\n".join(filter(None, (str(venue.get("name") or ""), locality)))


def _date_label(value: date) -> str:
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}"


def _clock_label(value: datetime) -> str:
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'} {value.tzname()}"


def _is_timed(game: Mapping[str, Any]) -> bool:
    return bool(game.get("start_time") and not game.get("time_tbd") and not game.get("date_tbd") and game.get("status") != "postponed")


def _placeholder_date(game: Mapping[str, Any]) -> date:
    value = game.get("date") if not game.get("date_tbd") else None
    value = value or game.get("week_date")
    if not value:
        raise ValueError(f"Game {game.get('id')} has no safe date for a TBD placeholder")
    return date.fromisoformat(value)


def is_primetime(game: Mapping[str, Any]) -> bool:
    """Confirmed games kicking off at or after 7 PM Eastern.

    This is a time-of-day feed, not a claim about nationwide viewing rights.
    Unknown kickoff times stay in the master/team feeds until confirmed.
    """
    return _is_timed(game) and _instant(game["start_time"]).astimezone(EASTERN).hour >= 19


def _description(game: Mapping[str, Any], timed: bool, location: str) -> str:
    lines = [f"NFL {game['season']} · {_round(game)}", "", _matchup(game), ""]
    if timed:
        eastern = _instant(game["start_time"]).astimezone(EASTERN)
        lines.extend([
            f"Kickoff: {_date_label(eastern.date())} at {_clock_label(eastern)} (America/New_York)",
            "Estimated game duration: 3 hours 15 minutes.",
        ])
    elif game.get("date_tbd") or not game.get("date"):
        lines.extend([
            "Date and kickoff: TBD.",
            f"Week placeholder: {_date_label(_placeholder_date(game))}. This is not a confirmed game date.",
            "The event will move to its confirmed date and kickoff when announced.",
        ])
    else:
        lines.extend([
            f"Date: {_date_label(_placeholder_date(game))}",
            "Kickoff: TBD. Shown as an all-day placeholder until announced.",
        ])
    status = str(game.get("status") or "scheduled").lower()
    if status in {"cancelled", "canceled", "postponed"}:
        lines.extend(["", f"Status: {'Cancelled' if status in {'cancelled', 'canceled'} else 'Postponed'}."])
    broadcast = game.get("broadcast") or {}
    television = _strings(broadcast.get("tv"))
    streaming = _strings(broadcast.get("streaming"))
    lines.extend(["", "Watch"])
    if television:
        lines.append("TV: " + ", ".join(television))
    if streaming:
        lines.append("Streaming: " + ", ".join(streaming))
    if not television and not streaming:
        lines.append("Broadcast information: TBD.")
    lines.extend(_strings(broadcast.get("notes")))
    if location:
        lines.extend(["", "Venue", location])
    if game.get("notes"):
        lines.extend(["", *_strings(game["notes"])])
    if game.get("source_url"):
        lines.extend(["", "Schedule source: " + str(game["source_url"])])
    return "\n".join(lines)


def render_calendar(
    games: Iterable[Mapping[str, Any]], season: int, name: str, revisions: Mapping[str, Any],
) -> bytes:
    """Render deterministic UTF-8 iCalendar bytes, including CRLF/folding.

    Every published game must have a persisted revision. Missing revisions or
    unplaceable placeholders fail the build instead of silently losing games.
    """
    calendar = Calendar()
    calendar.add("prodid", "-//NFL Calendar//Independent schedule subscriptions//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("name", name)
    calendar.add("x-wr-calname", name)
    calendar.add("x-wr-timezone", "America/New_York")
    calendar.add("x-wr-caldesc", f"{season} NFL regular season and postseason. Eastern Time; automatically updated.")
    calendar.add("refresh-interval", vDuration(timedelta(hours=6)), parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "PT6H")
    seen = set()
    sorted_games = sorted(games, key=lambda game: (str(game.get("start_time") or game.get("date") or game.get("week_date") or ""), str(game.get("id"))))
    for game in sorted_games:
        if int(game["season"]) != int(season):
            raise ValueError(f"Game {game['id']} does not belong to season {season}")
        if game["id"] in seen:
            raise ValueError(f"Duplicate game id: {game['id']}")
        seen.add(game["id"])
        revision = revisions[game["id"]]
        event = Event()
        event.add("uid", game_uid(game))
        event.add("sequence", int(revision["sequence"]))
        event.add("created", _instant(revision["created"]))
        event.add("dtstamp", _instant(revision["modified"]))
        event.add("last-modified", _instant(revision["modified"]))
        timed = _is_timed(game)
        title = _matchup(game)
        if timed:
            start = _instant(game["start_time"])
            event.add("dtstart", start)
            event.add("dtend", start + GAME_DURATION)
        else:
            start_date = _placeholder_date(game)
            event.add("dtstart", start_date)
            event.add("dtend", start_date + timedelta(days=1))
            title = f"[{'Date & time TBD' if game.get('date_tbd') or not game.get('date') else 'Time TBD'}] {title}"
        status = str(game.get("status") or "scheduled").lower()
        if status in {"cancelled", "canceled"}:
            event.add("status", "CANCELLED")
            title = "[Cancelled] " + title
        elif status == "postponed":
            event.add("status", "TENTATIVE")
            title = "[Postponed] " + title
        else:
            event.add("status", "CONFIRMED" if timed else "TENTATIVE")
        location = _location(game)
        event.add("summary", title)
        event.add("description", _description(game, timed, location))
        if location:
            event.add("location", location)
        if game.get("source_url"):
            event.add("url", game["source_url"])
        event.add("categories", ["NFL", "Football", _round(game)])
        event.add("transp", "TRANSPARENT")
        calendar.add_component(event)
    return calendar.to_ical()
