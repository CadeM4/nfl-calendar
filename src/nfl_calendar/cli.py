"""Run with `python -m nfl_calendar` or the nfl-calendar command."""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .calendar import update_revisions
from .changes import changes_markdown, detect_changes
from .publishing import publish
from .sources import fetch_schedule
from .validation import validate_schedule

LOG = logging.getLogger(__name__)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def refresh(root, season=None, *, fetcher=fetch_schedule, input_path=None):
    root = Path(root)
    config = load_json(root / "config.json") or {}
    season = season or int(os.environ.get("SEASON", config.get("season", 2026)))
    previous = load_json(root / "data" / f"schedule-{season}.json")
    old_revisions = load_json(root / "data" / f"revisions-{season}.json") or {}
    if previous:
        for game in previous["games"]:
            revision = old_revisions.get(game["id"])
            if not revision:
                raise ValueError(f"Revision state missing for {game['id']}; refusing to reset published event sequences")
            if type(revision.get("sequence")) is not int or revision["sequence"] < 0 or not isinstance(revision.get("fingerprint"), str):
                raise ValueError(f"Corrupt revision state for {game['id']}")
            for field in ("created", "modified"):
                instant = datetime.fromisoformat(revision[field].replace("Z", "+00:00"))
                if instant.utcoffset() is None:
                    raise ValueError(f"Naive revision {field} for {game['id']}")
    schedule = load_json(Path(input_path)) if input_path else fetcher(season)
    if schedule.get("season") != season:
        raise ValueError("Fetched schedule does not match requested season")
    counts = validate_schedule(schedule, previous, config.get("expected_regular_games", 272), config.get("expected_games_per_team", 17))
    revisions = update_revisions(schedule["games"], old_revisions, schedule["fetched_at"])
    changes = detect_changes(previous, schedule)
    markdown = changes_markdown(changes, schedule["fetched_at"])
    publish(root, schedule, revisions, counts, changes, markdown)
    LOG.info("Published %d regular + %d postseason games; %d meaningful changes", counts["regular"], counts["postseason"], len(changes))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"Validated **{counts['regular']} regular games**, **{counts['teams']} teams**, **{counts['postseason']} postseason games**.\n\n" + markdown)
    return counts


def main():
    parser = argparse.ArgumentParser(description="Fetch, validate, and publish NFL subscription feeds")
    parser.add_argument("--season", type=int)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, help="Rebuild a normalized snapshot offline; still validates against persisted state")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        refresh(args.root, args.season, input_path=args.input)
    except Exception:
        LOG.exception("Refresh failed. Last known good files remain intact; do not deploy this run.")
        return 1
    return 0
