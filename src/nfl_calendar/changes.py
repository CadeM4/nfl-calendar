"""Human-readable semantic diffs, independent of source transport metadata."""
from datetime import datetime
from zoneinfo import ZoneInfo

FIELDS = ("away", "home", "week", "start_time", "date", "date_tbd", "time_tbd", "week_date", "venue", "broadcast", "status", "notes", "source_url")


def detect_changes(previous, current):
    before = {g["id"]: g for g in (previous or {}).get("games", [])}
    changes = []
    for g in current["games"]:
        old = before.get(g["id"])
        fields = {key: {"before": old.get(key), "after": g.get(key)} for key in FIELDS if old and old.get(key) != g.get(key)}
        if old is None or fields:
            changes.append({"kind": "NEW" if old is None else "UPDATED", "id": g["id"], "away": g.get("away"), "home": g.get("home"), "week": g["week"], "fields": fields})
    return changes


def display(value, field):
    if field == "start_time" and value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        return dt.strftime("%a %b %d, %Y %I:%M %p %Z")
    if value is None:
        return "TBD"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in value.items() if v)
    return str(value)


def changes_markdown(changes, fetched_at):
    lines = ["# Schedule changes", "", f"Verified: {fetched_at}", ""]
    if not changes:
        lines.append("No event changes since the previous successful refresh.")
    for change in changes:
        lines += [f"## {change['kind']}: {change['away'] or 'TBD'} @ {change['home'] or 'TBD'} — Week {change['week']}", ""]
        for key, values in change["fields"].items():
            lines.append(f"- {key.replace('_', ' ').capitalize()}: {display(values['before'], key)} → {display(values['after'], key)}")
        lines.append("")
    return "\n".join(lines) + "\n"
