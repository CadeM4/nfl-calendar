"""Small shared contract for official NFL URLs, rounds, and ingestion errors."""

BASE = "https://www.nfl.com"

POST_ROUNDS = {
    "WC": (1, "wild-card-weekend"),
    "DIV": (2, "divisional-playoffs"),
    "CONF": (3, "conference-championships"),
    "SB": (5, "super-bowl-sunday"),
}

class SourceError(RuntimeError):
    """The official response cannot safely be accepted as a schedule."""

def week_url(season, season_type, metadata):
    suffix = f"week-{metadata['week']}" if season_type == "REG" else POST_ROUNDS[metadata["weekType"]][1]
    return f"{BASE}/schedules/{season}/by-week/{suffix}"
