"""Official NFL retrieval, hydration parsing, and fetch orchestration.

NFL.com serves the schedule and its per-game viewing entitlements in Next.js
Flight hydration records. We JSON-decode those records; never execute site JS.
The query identity and each game's season/week are checked before accepting it.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Re-export normalization functions for existing adapter callers.
from .normalization import normalize_broadcast, normalize_game, normalize_status
from .source_common import BASE, POST_ROUNDS, SourceError, week_url as _week_url

LOG = logging.getLogger(__name__)
DETAILS_QUERY = "useFetchFootballWeeklyGameDetails"
WEEKS_QUERY = "useFetchExperienceWeekSelectorBySeason"
WATCH_QUERY = "useFetchExperienceWaysToWatchGamesByWeek"


def fetch_html(url: str) -> str:
    """Bounded unauthenticated HTTPS fetch with transient-error retries."""
    for attempt in range(3):
        try:
            request = Request(url, headers={
                "User-Agent": "NFLCalendar/1.0 (personal calendar; six-hour refresh)",
                "Accept": "text/html", "Accept-Language": "en-US,en;q=0.8",
            })
            with urlopen(request, timeout=30) as response:
                body = response.read(12_000_001)
            if len(body) > 12_000_000:
                raise SourceError(f"Oversized schedule response: {url}")
            return body.decode("utf-8")
        except (HTTPError, URLError, TimeoutError, UnicodeError, OSError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (408, 429, 500, 502, 503, 504)
            if not retryable or attempt == 2:
                raise SourceError(f"Could not retrieve {url}: {exc}") from exc
            LOG.warning("NFL fetch failed; retry %d/2: %s", attempt + 1, url)
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def decode_queries(html: str) -> list[dict]:
    """Extract complete JSON Flight records, including cross-script chunks."""
    chunks = []
    for encoded in re.findall(r"self\.__next_f\.push\((.*?)\)</script>", html, re.DOTALL):
        try:
            packet = json.loads(encoded)
        except ValueError as exc:
            raise SourceError("Malformed NFL hydration packet") from exc
        if isinstance(packet, list) and len(packet) == 2 and packet[0] == 1 and isinstance(packet[1], str):
            chunks.append(packet[1])
    records = []
    for line in "".join(chunks).splitlines():
        prefix, _, value = line.partition(":")
        if not re.fullmatch(r"[0-9a-f]+", prefix) or not value.startswith(("[", "{")):
            continue  # Ignore React imports, text records, and references.
        try:
            records.append(json.loads(value))
        except ValueError:
            continue  # A non-JSON React record is not schedule data.
    queries = [item for record in records for item in _walk(record)
               if isinstance(item.get("queryKey"), list) and "state" in item]
    if not queries:
        raise SourceError("NFL page contains no usable schedule hydration queries")
    return queries


def _query(queries, name, criteria, *, required=True):
    matches = []
    for item in queries:
        key = item["queryKey"]
        if len(key) != 2 or key[0] != name or not isinstance(key[1], dict):
            continue
        if all(str(key[1].get(k)) == str(v) for k, v in criteria.items()):
            state = item["state"]
            if state.get("status") != "success" or state.get("error") is not None:
                raise SourceError(f"NFL query {name} returned an error")
            matches.append(state.get("data"))
    if not matches:
        if required:
            raise SourceError(f"Missing exact NFL query {name}: {criteria}")
        return None
    if any(value != matches[0] for value in matches[1:]):
        raise SourceError(f"Conflicting copies of NFL query {name}")
    return matches[0]


def _data_list(payload, label):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceError(f"Invalid {label} result structure")
    if (payload.get("errors") or {}).get("error"):
        raise SourceError(f"NFL reports an error for {label}")
    return payload["data"]


def week_metadata(queries, season):
    payload = _query(queries, WEEKS_QUERY, {"season": season})
    weeks = _data_list(payload, "week selector")
    if any(not isinstance(w, dict) or w.get("season") != season for w in weeks):
        raise SourceError("NFL week selector returned an unexpected season")
    identities = [(w.get("seasonType"), w.get("week")) for w in weeks]
    if len(identities) != len(set(identities)):
        raise SourceError("NFL week selector contains duplicate weeks")
    return weeks


def parse_schedule_page(html: str, season: int, season_type: str, week: int) -> list[dict]:
    """Parse only the requested week; rejects fallback/current-week pages."""
    queries = decode_queries(html)
    weeks = week_metadata(queries, season)
    matches = [w for w in weeks if w.get("seasonType") == season_type and w.get("week") == week]
    if len(matches) != 1:
        raise SourceError(f"Official selector does not contain {season} {season_type} week {week}")
    metadata = matches[0]
    if season_type == "POST" and metadata.get("weekType") not in POST_ROUNDS:
        raise SourceError("Unsupported postseason round (Pro Bowl is excluded)")
    raw_games = _query(queries, DETAILS_QUERY, {"season": season, "seasonType": season_type, "week": week})
    if not isinstance(raw_games, list):
        raise SourceError("NFL weekly games are not an array")
    # Despite its name, this query's weekType is REG/POST, not WC/DIV/SB.
    watch_payload = _query(queries, WATCH_QUERY, {"season": season, "weekType": season_type, "week": week})
    watch_games = _data_list(watch_payload, "ways to watch")
    watch = {}
    for game in watch_games:
        if not isinstance(game, dict) or not game.get("id") or game["id"] in watch:
            raise SourceError("Invalid or duplicate NFL ways-to-watch game")
        watch[game["id"]] = game
    raw_ids = [g.get("id") for g in raw_games if isinstance(g, dict)]
    if len(raw_ids) != len(raw_games) or len(raw_ids) != len(set(raw_ids)):
        raise SourceError("Invalid or duplicate NFL weekly game")
    if set(watch) != set(raw_ids):
        raise SourceError("Official schedule and viewing game lists disagree")
    games = [normalize_game(g, watch[g["id"]], metadata, season, season_type, week) for g in raw_games]
    if season_type == "REG" and not 8 <= len(games) <= 16:
        raise SourceError(f"Implausible regular-season week count: {len(games)}")
    return games


def fetch_schedule(season: int, *, fetcher: Callable[[str], str] | None = None) -> dict:
    """Fetch all regular weeks and every officially advertised playoff round."""
    fetcher = fetcher or fetch_html
    first_url = f"{BASE}/schedules/{season}/by-week/week-1"
    first_html = fetcher(first_url)
    weeks = week_metadata(decode_queries(first_html), season)
    regular = {w["week"] for w in weeks if w.get("seasonType") == "REG"}
    if regular != set(range(1, 19)):
        raise SourceError(f"Full 18-week {season} schedule is not available: {sorted(regular)}")
    targets = [w for w in weeks if w.get("seasonType") == "REG" or
               (w.get("seasonType") == "POST" and w.get("weekType") in POST_ROUNDS)]
    def retrieve(metadata):
        week, season_type = metadata["week"], metadata["seasonType"]
        url = _week_url(season, season_type, metadata)
        html = first_html if url == first_url else fetcher(url)
        result = parse_schedule_page(html, season, season_type, week)
        LOG.info("Official NFL %s week %s: %d games", season_type, week, len(result))
        return result
    with ThreadPoolExecutor(max_workers=3) as executor:
        games = [g for result in executor.map(retrieve, targets) for g in result]
    games.sort(key=lambda g: (g["season_type"] != "REG", g["week"], g["start_time"] or "~", g["id"]))
    return {
        "schema_version": 1, "season": season,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {"name": "NFL.com official schedule and game-specific viewing data", "url": f"{BASE}/schedules/{season}/by-week/week-1"},
        "games": games,
    }
