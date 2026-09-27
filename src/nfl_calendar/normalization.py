"""Pure conversion of official NFL records into the shared calendar data model.

No network, HTML parsing, filesystem writes, or publishing occurs here.
Game-specific viewing evidence and Eastern dates are normalized explicitly.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import re
from zoneinfo import ZoneInfo

from .source_common import BASE, POST_ROUNDS, SourceError, week_url as _week_url
from .teams import canonical_team

EASTERN = ZoneInfo("America/New_York")

TV_NAMES = {
    "CBS": "CBS", "FOX": "FOX", "NBC": "NBC", "ABC": "ABC",
    "ESPN": "ESPN", "ESPN2": "ESPN2", "ESPN DEPORTES": "ESPN Deportes",
    "FOX DEPORTES": "FOX Deportes", "TELEMUNDO": "Telemundo",
    "UNIVERSO": "Universo", "NFL NETWORK": "NFL Network", "NFLN": "NFL Network",
}

STREAM_NAMES = {
    "PRIME VIDEO": "Prime Video", "PRIME": "Prime Video",
    "NETFLIX": "Netflix", "PEACOCK": "Peacock", "PARAMOUNT+": "Paramount+",
    "FOX ONE": "FOX One", "ESPN+": "ESPN+", "ESPN UNLIMITED": "ESPN Unlimited",
    "YOUTUBE": "YouTube", "NFL+": "NFL+",
}

ENTITLEMENTS = {
    "amazon_prime": "Prime Video", "netflix": "Netflix", "peacock": "Peacock",
    "paramount_plus": "Paramount+", "fox_one": "FOX One",
    "espn_unlimited": "ESPN Unlimited", "espn_plus": "ESPN+",
    "youtube": "YouTube", "nfl_plus": "NFL+", "nfl_plus_premium": "NFL+",
}

def _eastern_date(value):
    if not isinstance(value, str):
        raise SourceError("Missing official week anchor date")
    try:
        if "T" not in value:
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(EASTERN).date().isoformat()
    except ValueError as exc:
        raise SourceError(f"Invalid official date: {value}") from exc

def _team(value, season_type):
    if value is None and season_type == "POST":
        return None
    if not isinstance(value, dict):
        raise SourceError("Missing NFL team object")
    name = value.get("fullName") or value.get("abbreviation")
    if season_type == "POST" and name in (None, "TBD", "To Be Determined"):
        return None
    try:
        return canonical_team(name)
    except ValueError as exc:
        raise SourceError(f"Unknown NFL team: {name}") from exc

def normalize_status(status, phase=None):
    """Normalize NFL's separate administrative status and live summary phase.

    Administrative cancellation/postponement wins over a stale live summary.
    NFL's own UI classifies SUSPENDED with in-game phases, so it remains live
    here and receives an explicit suspended note in the event description.
    """
    status = str(status or "SCHEDULED").strip().upper().replace("-", "_").replace(" ", "_")
    phase = str(phase or "UNSPECIFIED").strip().upper().replace("-", "_").replace(" ", "_")
    if status in {"CANCELLED", "CANCELED"} or phase in {"CANCELLED", "CANCELED"}:
        return "cancelled"
    if status == "POSTPONED" or phase == "POSTPONED":
        return "postponed"
    if status == "FORFEITED":
        return "final"
    raw_mapping = {
        "SCHEDULED": "scheduled", "PREGAME": "scheduled", "PRE_GAME": "scheduled",
        "LIVE": "live", "IN_PROGRESS": "live", "INPROGRESS": "live", "INGAME": "live",
        "HALFTIME": "live", "SUSPENDED": "live", "FINAL": "final",
        "FINAL_OVERTIME": "final", "COMPLETED": "final", "COMPLETE": "final",
        "ARCHIVED": None,
    }
    phase_mapping = {
        "FINAL": "final", "FINAL_OVERTIME": "final", "INGAME": "live",
        "IN_PROGRESS": "live", "LIVE": "live", "HALFTIME": "live", "SUSPENDED": "live",
        "PREGAME": "scheduled", "PRE_GAME": "scheduled", "UNSPECIFIED": None,
    }
    if status not in raw_mapping or phase not in phase_mapping:
        raise SourceError(f"Unrecognized NFL game status/phase: {status}/{phase}")
    if "final" in (phase_mapping[phase], raw_mapping[status]):
        return "final"
    if "live" in (phase_mapping[phase], raw_mapping[status]):
        return "live"
    normalized = phase_mapping[phase] or raw_mapping[status]
    if normalized is None:
        raise SourceError("Archived NFL game has no usable summary phase")
    return normalized

def _live_us_entitlements(coverage):
    auth = coverage.get("authorizations") or {}
    if not isinstance(auth, dict):
        raise SourceError("Invalid NFL viewing authorizations")
    if not auth:
        return set()
    required = ("broadcastAiringType", "deliveryMethod", "contentType", "gameId")
    if any(not coverage.get(k) for k in required):
        raise SourceError("Viewing authorizations are missing live-game identity metadata")
    if (coverage["broadcastAiringType"], coverage["deliveryMethod"], coverage["contentType"]) != ("LIVE", "LIVE", "GAME"):
        return set()  # Replay, audio, pregame and non-game products are not live game evidence.
    eligible = set()
    for provider, entries in auth.items():
        if not isinstance(entries, list):
            raise SourceError("NFL provider authorization is not a list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise SourceError("NFL authorization rule is not an object")
            for label, rule in entry.items():
                if not isinstance(rule, dict):
                    raise SourceError("NFL authorization details are not an object")
                if not isinstance(label, str) or not label.upper().endswith(" - LIVE GAME"):
                    continue
                requirements = rule.get("requirements") or {}
                if not isinstance(requirements, dict):
                    raise SourceError("NFL authorization requirements are not an object")
                countries = requirements.get("countryCode")
                if isinstance(countries, list) and "US" in countries:
                    eligible.add(provider)
    return eligible

def normalize_broadcast(info: dict, watch: dict | None = None) -> dict:
    """Use per-game entitlements, never infer a service from a TV network."""
    if not isinstance(info, dict):
        raise SourceError("Missing broadcastInfo object")
    tv, streaming, notes = set(), set(), []
    home_channels = info.get("homeNetworkChannels")
    away_channels = info.get("awayNetworkChannels")
    if not isinstance(home_channels, list) or not isinstance(away_channels, list):
        raise SourceError("NFL broadcast channels are not lists")
    for channel in home_channels + away_channels:
        if not isinstance(channel, str):
            raise SourceError("Invalid NFL broadcast channel")
        key = channel.strip().upper()
        if key in TV_NAMES:
            tv.add(TV_NAMES[key])
        elif key in STREAM_NAMES:
            streaming.add(STREAM_NAMES[key])
        elif key not in ("", "TBD", "TBA"):
            notes.append(f"Other official watch listing: {channel}")
    territory = info.get("territory")
    if territory == "REGIONAL":
        notes.append("Regional broadcast; local market coverage varies.")
    elif territory == "NATIONAL":
        notes.append("US national broadcast.")
    if set(home_channels) != set(away_channels):
        notes.append("Home and away market listings differ; check local listings.")

    # These are the actual public page's game-level entitlement keys, not the
    # similarly named streamingNetworks list of internal playback renditions.
    coverage = (watch or {}).get("coverageMap") or {}
    if not isinstance(coverage, dict):
        raise SourceError("Invalid NFL viewing coverage object")
    eligible = _live_us_entitlements(coverage)
    for key, name in ENTITLEMENTS.items():
        if key in eligible:
            streaming.add(name)
    if "NFL+" in streaming:
        notes.append("NFL+: local and primetime live game streams require a phone or tablet; market and device restrictions apply.")
    if "Paramount+" in streaming:
        notes.append("Paramount+: this game must be carried by your local CBS station.")
    if "FOX One" in streaming:
        notes.append("FOX One: local FOX coverage and market restrictions apply.")
    if "sunday_ticket" in eligible:
        notes.append("NFL Sunday Ticket: eligible out-of-market Sunday afternoon viewing; local and national blackouts apply.")
    if streaming:
        notes.append("Streaming listings are for the US; eligible subscriptions and geographic restrictions apply.")
    return {"tv": sorted(tv), "streaming": sorted(streaming), "notes": list(dict.fromkeys(notes))}

def normalize_game(raw, watch, metadata, season, season_type, source_week):
    if not isinstance(raw, dict) or (raw.get("season"), raw.get("seasonType"), raw.get("week")) != (season, season_type, source_week):
        raise SourceError("Game season/type/week does not match its requested page")
    source_id = raw.get("id")
    if not isinstance(source_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", source_id):
        raise SourceError("Missing or invalid stable NFL game UUID")
    away, home = _team(raw.get("awayTeam"), season_type), _team(raw.get("homeTeam"), season_type)
    week_type = metadata["weekType"]
    week = source_week if season_type == "REG" else POST_ROUNDS[week_type][0]
    start = raw.get("time")
    if start:
        try:
            parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone missing")
            start = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            confirmed_date = parsed.astimezone(EASTERN).date().isoformat()
        except (ValueError, AttributeError) as exc:
            raise SourceError("Invalid NFL kickoff timestamp") from exc
    else:
        start = None
        confirmed_date = _eastern_date(raw["date"]) if raw.get("date") else None
    source_ids = {"nfl": source_id}
    for item in raw.get("externalIds") or []:
        if isinstance(item, dict) and item.get("source") and item.get("id"):
            source_ids[item["source"]] = item["id"]
    slug = source_ids.get("slug")
    if slug and not re.fullmatch(r"[a-z0-9-]+", slug):
        raise SourceError("Invalid official game URL slug")
    source_url = f"{BASE}/games/{slug}" if slug else _week_url(season, season_type, metadata)
    if watch is not None:
        if watch.get("id") != source_id or (watch.get("season"), watch.get("seasonType"), watch.get("week")) != (season, season_type, source_week):
            raise SourceError("Viewing data identity disagrees with NFL game")
        if watch.get("date") and start:
            watch_start = datetime.fromisoformat(watch["date"].replace("Z", "+00:00"))
            if watch_start != parsed:
                raise SourceError("Schedule and viewing kickoff times disagree")
        coverage = watch.get("coverageMap") or {}
        if not isinstance(coverage, dict):
            raise SourceError("Invalid NFL viewing coverage object")
        if coverage.get("gameId") and coverage["gameId"] != source_id:
            raise SourceError("Viewing entitlement coverage belongs to another game")
    phase = (raw.get("summary") or {}).get("phase")
    status = normalize_status(raw.get("status"), phase)
    venue = raw.get("venue") or {}
    if not isinstance(venue, dict):
        raise SourceError("Invalid NFL venue")
    game = {
        "id": f"{season}-REG-{away}-{home}" if season_type == "REG" else f"{season}-POST-nfl-{source_id}",
        "season": season, "season_type": season_type, "week": week,
        "away": away, "home": home, "start_time": start,
        "date": confirmed_date, "time_tbd": start is None, "date_tbd": confirmed_date is None,
        "week_date": _eastern_date(metadata["dateBegin"]),
        "venue": {k: venue[k] for k in ("name", "city", "state", "country") if venue.get(k)},
        "broadcast": normalize_broadcast(raw.get("broadcastInfo"), watch),
        "status": status, "source_url": source_url, "source_ids": source_ids,
        "category": raw.get("category"), "international": bool(raw.get("international")),
        "source_week": source_week,
    }
    if raw.get("status") == "FORFEITED":
        game["notes"] = ["Game marked forfeited by the NFL."]
    elif phase == "SUSPENDED" or raw.get("status") == "SUSPENDED":
        game["notes"] = ["Game suspended; follow the official game page for resumption updates."]
    return game
