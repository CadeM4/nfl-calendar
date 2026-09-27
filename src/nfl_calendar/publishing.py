"""Stage complete, validated feed bundles before replacing local output."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from icalendar import Calendar

from .calendar import is_primetime, render_calendar
from .teams import TEAMS


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status_data(schedule, counts, changes):
    games = schedule["games"]
    unresolved = []
    for g in games:
        broadcast_tbd = not (g["broadcast"]["tv"] or g["broadcast"]["streaming"])
        if g["time_tbd"] or g["date_tbd"] or broadcast_tbd:
            unresolved.append({key: g.get(key) for key in ("id", "away", "home", "week", "season_type", "time_tbd", "date_tbd")} | {"broadcast_tbd": broadcast_tbd})
    return {
        "season": schedule["season"], "fetched_at": schedule["fetched_at"],
        "source": schedule["source"], "counts": counts,
        "tbd": {"time": sum(g["time_tbd"] for g in games), "date": sum(g["date_tbd"] for g in games),
                "broadcast": sum(not (g["broadcast"]["tv"] or g["broadcast"]["streaming"]) for g in games), "games": unresolved},
        "teams": [{"id": code, **team, "count": sum(code in (g["away"], g["home"]) for g in games)} for code, team in TEAMS.items()],
        "primetime_count": sum(is_primetime(g) for g in games),
        "change_count": len(changes), "refresh_hours": 6,
    }


def verify_calendar(content, expected):
    parsed = Calendar.from_ical(content)
    events = parsed.walk("VEVENT")
    if len(events) != expected:
        raise ValueError(f"Rendered calendar lost events: {len(events)} != {expected}")
    uids = [str(e["UID"]) for e in events]
    if len(set(uids)) != expected:
        raise ValueError("Rendered duplicate UID")
    if b"\n" in content.replace(b"\r\n", b""):
        raise ValueError("ICS contains a bare LF")
    if any(len(line) > 75 for line in content.split(b"\r\n")):
        raise ValueError("ICS physical line exceeds 75 octets")
    for e in events:
        for field in ("UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY", "LAST-MODIFIED", "SEQUENCE"):
            if field not in e:
                raise ValueError(f"Rendered event missing {field}")
        if e.decoded("DTEND") <= e.decoded("DTSTART"):
            raise ValueError("Rendered event ends before it starts")


def publish(root, schedule, revisions, counts, changes, markdown):
    """No live output changes until every generated calendar passes parser checks.

    GitHub Pages then publishes the whole public/ directory as one deployment.
    Local replacement is recoverable with rollback; the persisted state and feed
    directories are committed together by the workflow.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=root) as temporary:
        stage = Path(temporary)
        output = stage / "public"
        shutil.copytree(root / "site", output)
        (output / ".nojekyll").touch()
        season = schedule["season"]
        groups = [(f"nfl-{season}.ics", f"NFL {season}–{str(season + 1)[-2:]}", schedule["games"])]
        groups += [(f"{team['slug']}.ics", f"{team['name']} · {season}", [g for g in schedule["games"] if code in (g["away"], g["home"])]) for code, team in TEAMS.items()]
        groups.append(("primetime.ics", f"NFL Evening Games · {season}", [g for g in schedule["games"] if is_primetime(g)]))
        for filename, title, games in groups:
            content = render_calendar(games, season, title, revisions)
            verify_calendar(content, len(games))
            (output / filename).write_bytes(content)
        status = status_data(schedule, counts, changes)
        write_json(output / "status.json", status)
        tbd_lines = ["# Games awaiting schedule information", "", f"Last verified: {schedule['fetched_at']}", "", "Week | Away | Home | Date | Kickoff | Broadcast", "--- | --- | --- | --- | --- | ---"]
        for g in status["tbd"]["games"]:
            tbd_lines.append(f"{g['week']} | {TEAMS.get(g['away'], {}).get('name', 'TBD')} | {TEAMS.get(g['home'], {}).get('name', 'TBD')} | {'TBD' if g['date_tbd'] else 'Known'} | {'TBD' if g['time_tbd'] else 'Known'} | {'TBD' if g['broadcast_tbd'] else 'Known'}")
        if not status["tbd"]["games"]:
            tbd_lines += ["", "No unresolved date, kickoff, or broadcast information."]
        (output / "tbd.md").write_text("\n".join(tbd_lines) + "\n", encoding="utf-8")
        write_json(output / "schedule.json", schedule)
        write_json(output / "changes.json", changes)
        (output / "changes.md").write_text(markdown, encoding="utf-8")
        data = stage / "data"
        data.mkdir()
        write_json(data / f"schedule-{season}.json", schedule)
        write_json(data / f"revisions-{season}.json", revisions)
        # Retain prior seasons when season configuration advances.
        for dirname in ("public", "data"):
            existing = root / dirname
            if existing.exists():
                for f in existing.iterdir():
                    if f.is_file() and not (stage / dirname / f.name).exists():
                        shutil.copy2(f, stage / dirname / f.name)
        swapped = []
        try:
            for dirname in ("public", "data"):
                destination = root / dirname
                backup = stage / f"old-{dirname}"
                if destination.exists():
                    os.replace(destination, backup)
                swapped.append((destination, backup))
                os.replace(stage / dirname, destination)
        except BaseException:
            for destination, backup in reversed(swapped):
                if destination.resolve().parent != root:
                    raise ValueError(f"Refusing rollback outside publishing root: {destination}")
                if destination.exists():
                    shutil.rmtree(destination)
                if backup.exists():
                    os.replace(backup, destination)
            raise
