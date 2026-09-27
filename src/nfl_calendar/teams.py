"""Canonical current NFL teams, shared by providers, validation and publishing."""

from __future__ import annotations

import re


# These identities deliberately do not contain mutable venue or broadcast data.
_TEAM_ROWS = (
    ("ARI", "Arizona Cardinals", "NFC", "West"),
    ("ATL", "Atlanta Falcons", "NFC", "South"),
    ("BAL", "Baltimore Ravens", "AFC", "North"),
    ("BUF", "Buffalo Bills", "AFC", "East"),
    ("CAR", "Carolina Panthers", "NFC", "South"),
    ("CHI", "Chicago Bears", "NFC", "North"),
    ("CIN", "Cincinnati Bengals", "AFC", "North"),
    ("CLE", "Cleveland Browns", "AFC", "North"),
    ("DAL", "Dallas Cowboys", "NFC", "East"),
    ("DEN", "Denver Broncos", "AFC", "West"),
    ("DET", "Detroit Lions", "NFC", "North"),
    ("GB", "Green Bay Packers", "NFC", "North"),
    ("HOU", "Houston Texans", "AFC", "South"),
    ("IND", "Indianapolis Colts", "AFC", "South"),
    ("JAX", "Jacksonville Jaguars", "AFC", "South"),
    ("KC", "Kansas City Chiefs", "AFC", "West"),
    ("LV", "Las Vegas Raiders", "AFC", "West"),
    ("LAC", "Los Angeles Chargers", "AFC", "West"),
    ("LAR", "Los Angeles Rams", "NFC", "West"),
    ("MIA", "Miami Dolphins", "AFC", "East"),
    ("MIN", "Minnesota Vikings", "NFC", "North"),
    ("NE", "New England Patriots", "AFC", "East"),
    ("NO", "New Orleans Saints", "NFC", "South"),
    ("NYG", "New York Giants", "NFC", "East"),
    ("NYJ", "New York Jets", "AFC", "East"),
    ("PHI", "Philadelphia Eagles", "NFC", "East"),
    ("PIT", "Pittsburgh Steelers", "AFC", "North"),
    ("SF", "San Francisco 49ers", "NFC", "West"),
    ("SEA", "Seattle Seahawks", "NFC", "West"),
    ("TB", "Tampa Bay Buccaneers", "NFC", "South"),
    ("TEN", "Tennessee Titans", "AFC", "South"),
    ("WAS", "Washington Commanders", "NFC", "East"),
)

TEAMS: dict[str, dict[str, str]] = {
    abbreviation: {
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "conference": conference,
        "division": division,
    }
    for abbreviation, name, conference, division in _TEAM_ROWS
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


_ALIASES = {}
for _abbreviation, _team in TEAMS.items():
    for _alias in (_abbreviation, _team["name"], _team["slug"], _team["name"].split()[-1]):
        _ALIASES[_key(_alias)] = _abbreviation

# Provider abbreviations, including common former-location codes. City-only
# aliases are intentionally absent: "Los Angeles" and "New York" are ambiguous.
for _alias, _abbreviation in {
    "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
    "GBP": "GB", "GNB": "GB", "JAC": "JAX", "KAN": "KC", "KCC": "KC",
    "LVR": "LV", "OAK": "LV", "Oakland Raiders": "LV",
    "SD": "LAC", "SDG": "LAC", "San Diego Chargers": "LAC",
    "LA": "LAR", "RAM": "LAR", "STL": "LAR", "St. Louis Rams": "LAR",
    "NWE": "NE", "NEP": "NE", "NOR": "NO", "NOS": "NO",
    "SFO": "SF", "SFF": "SF", "TAM": "TB", "TBB": "TB",
    "WSH": "WAS", "WFT": "WAS", "Washington Football Team": "WAS",
    "Washington Redskins": "WAS",
}.items():
    _ALIASES[_key(_alias)] = _abbreviation


def canonical_team(value: str) -> str:
    """Resolve an explicit team identity; reject unknown/ambiguous values."""
    if not isinstance(value, str) or _key(value) not in _ALIASES:
        raise ValueError(f"Unknown NFL team: {value!r}")
    return _ALIASES[_key(value)]
