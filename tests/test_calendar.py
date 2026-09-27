"""Calendar-client contracts: identity, UTC/DST, revision order and RFC output."""

import copy
import unittest
from datetime import date, datetime, timedelta, timezone

from icalendar import Calendar

from nfl_calendar.calendar import EASTERN, game_uid, is_primetime, render_calendar, update_revisions
from nfl_calendar.teams import TEAMS, canonical_team


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def sample_game(**overrides):
    game = {
        "id": "2026-REG-LAC-BUF", "season": 2026, "season_type": "REG", "week": 3,
        "away": "LAC", "home": "BUF", "start_time": "2026-09-27T17:00:00Z",
        "date": "2026-09-27", "time_tbd": False, "date_tbd": False,
        "week_date": "2026-09-27", "status": "scheduled",
        "venue": {"name": "Test Stadium", "city": "Orchard Park", "state": "NY", "country": "USA"},
        "broadcast": {"tv": ["FOX"], "streaming": [], "notes": []},
        "source_url": "https://www.nfl.com/schedules/", "source_ids": {"example": "123"},
    }
    game.update(overrides)
    return game


def serialized(games, revisions=None, name="NFL 2026–27"):
    revisions = revisions if revisions is not None else update_revisions(games, {}, NOW)
    return render_calendar(games, 2026, name, revisions)


def events(payload):
    return Calendar.from_ical(payload).walk("VEVENT")


class CanonicalTeamsTests(unittest.TestCase):
    def test_all_32_teams_in_eight_balanced_divisions(self):
        self.assertEqual(len(TEAMS), 32)
        self.assertEqual(len({team["slug"] for team in TEAMS.values()}), 32)
        for conference in ("AFC", "NFC"):
            for division in ("East", "West", "North", "South"):
                self.assertEqual(sum(team["conference"] == conference and team["division"] == division for team in TEAMS.values()), 4)

    def test_aliases_and_full_names(self):
        for value, expected in [("JAC", "JAX"), ("WSH", "WAS"), ("LA", "LAR"), ("SD", "LAC"), ("OAK", "LV"), ("  buffalo bills ", "BUF"), ("Green-Bay Packers", "GB"), ("49ers", "SF")]:
            with self.subTest(value=value):
                self.assertEqual(canonical_team(value), expected)

    def test_unknown_or_ambiguous_teams_rejected(self):
        for value in (None, "Los Angeles", "New York", "Not an NFL team", "TBD"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_team(value)


class CalendarTests(unittest.TestCase):
    def test_valid_calendar_metadata_and_required_properties(self):
        payload = serialized([sample_game()])
        calendar = Calendar.from_ical(payload)
        self.assertEqual(str(calendar["version"]), "2.0")
        self.assertEqual(str(calendar["calscale"]), "GREGORIAN")
        self.assertEqual(str(calendar["method"]), "PUBLISH")
        self.assertEqual(str(calendar["x-wr-timezone"]), "America/New_York")
        self.assertEqual(calendar.decoded("refresh-interval"), timedelta(hours=6))
        event = calendar.walk("VEVENT")[0]
        for field in ("uid", "dtstamp", "dtstart", "dtend", "created", "last-modified", "sequence", "summary", "description", "location", "url", "status"):
            self.assertIn(field, event)
        self.assertEqual(str(event["summary"]), "Los Angeles Chargers @ Buffalo Bills")
        self.assertEqual(str(event["transp"]), "TRANSPARENT")
        self.assertEqual(event.walk("VALARM"), [])

    def test_september_kickoff_is_edt(self):
        event = events(serialized([sample_game()]))[0]
        local_start = event.decoded("dtstart").astimezone(EASTERN)
        self.assertEqual((local_start.hour, local_start.minute, local_start.tzname()), (13, 0, "EDT"))
        self.assertEqual(local_start.utcoffset(), timedelta(hours=-4))
        self.assertIn("1:00 PM EDT", str(event["description"]))

    def test_december_kickoff_is_est(self):
        game = sample_game(start_time="2026-12-13T18:00:00Z", date="2026-12-13", week=14)
        event = events(serialized([game]))[0]
        local_start = event.decoded("dtstart").astimezone(EASTERN)
        self.assertEqual((local_start.hour, local_start.minute, local_start.tzname()), (13, 0, "EST"))
        self.assertEqual(local_start.utcoffset(), timedelta(hours=-5))
        self.assertIn("1:00 PM EST", str(event["description"]))

    def test_utc_date_rollover_still_describes_correct_eastern_date(self):
        game = sample_game(start_time="2026-09-28T00:20:00Z")
        event = events(serialized([game]))[0]
        self.assertIn("Sunday, September 27, 2026 at 8:20 PM EDT", str(event["description"]))
        self.assertEqual(event.decoded("dtend") - event.decoded("dtstart"), timedelta(hours=3, minutes=15))

    def test_escaping_unicode_and_octet_line_folding_roundtrip(self):
        stadium = "Stade Café; Gate 1, \\ North\n" + "🏈" * 60
        note = "Local markets only; check listings, restrictions \\ apply.\nDeuxième ligne. " + "é" * 100
        game = sample_game(venue={"name": stadium}, broadcast={"tv": ["Test TV"], "streaming": [], "notes": [note]})
        payload = serialized([game])
        # RFC 5545 limits physical lines by octets, not Unicode characters.
        self.assertNotIn(b"\n", payload.replace(b"\r\n", b""))
        self.assertTrue(all(len(line) <= 75 for line in payload.split(b"\r\n")))
        for line in payload.split(b"\r\n"):
            line.decode("utf-8")
        self.assertIn(b"\r\n ", payload)
        event = events(payload)[0]
        self.assertEqual(str(event["location"]), stadium)
        self.assertIn(note, str(event["description"]))

    def test_flex_preserves_uid_created_and_increments_sequence(self):
        original = sample_game()
        before = update_revisions([original], {}, NOW)
        flexed = sample_game(start_time="2026-09-28T00:20:00Z", broadcast={"tv": ["NBC"], "streaming": [], "notes": []})
        after = update_revisions([flexed], before, NOW + timedelta(days=1))
        original_event = events(serialized([original], before))[0]
        flexed_event = events(serialized([flexed], after))[0]
        self.assertEqual(original_event["uid"], flexed_event["uid"])
        self.assertNotEqual(original_event.decoded("dtstart"), flexed_event.decoded("dtstart"))
        self.assertEqual(flexed_event.decoded("sequence"), 1)
        self.assertEqual(original_event.decoded("created"), flexed_event.decoded("created"))
        self.assertEqual(flexed_event.decoded("last-modified"), NOW + timedelta(days=1))
        self.assertEqual(flexed_event.decoded("dtstamp"), flexed_event.decoded("last-modified"))
        self.assertIn("TV: NBC", str(flexed_event["description"]))

    def test_unchanged_refresh_preserves_all_bytes_and_revision_state(self):
        game = sample_game()
        before = update_revisions([game], {}, NOW)
        after = update_revisions([game], before, NOW + timedelta(days=1))
        self.assertEqual(before, after)
        self.assertEqual(serialized([game], before), serialized([game], after))

    def test_source_ids_fetch_times_and_internal_fields_do_not_churn_revision(self):
        game = sample_game()
        before = update_revisions([game], {}, NOW)
        game.update(source_ids={"changed_source": "987"}, fetched_at="2026-09-03T11:00:00Z", internal_debug="different")
        self.assertEqual(update_revisions([game], before, NOW + timedelta(days=1)), before)

    def test_network_only_change_is_a_real_revision_without_invented_streaming(self):
        game = sample_game()
        before = update_revisions([game], {}, NOW)
        game["broadcast"]["tv"] = ["CBS"]
        after = update_revisions([game], before, NOW + timedelta(hours=6))
        self.assertEqual(after[game["id"]]["sequence"], 1)
        description = str(events(serialized([game], after))[0]["description"])
        self.assertIn("TV: CBS", description)
        self.assertNotIn("Paramount", description)
        self.assertNotIn("NFL+", description)
        self.assertNotIn("Streaming:", description)

    def test_streaming_and_restrictions_are_rendered_only_as_supplied(self):
        game = sample_game(broadcast={"tv": [], "streaming": ["Prime Video"], "notes": ["Local availability may differ."]})
        description = str(events(serialized([game]))[0]["description"])
        self.assertIn("Streaming: Prime Video", description)
        self.assertIn("Local availability may differ.", description)
        self.assertNotIn("TV:", description)
        self.assertNotIn("NFL+", description)

    def test_unknown_time_is_tentative_all_day_and_not_midnight_kickoff(self):
        game = sample_game(start_time=None, time_tbd=True)
        event = events(serialized([game]))[0]
        self.assertEqual(event.decoded("dtstart"), date(2026, 9, 27))
        self.assertEqual(event.decoded("dtend"), date(2026, 9, 28))
        self.assertEqual(event["dtstart"].params["VALUE"], "DATE")
        self.assertEqual(str(event["status"]), "TENTATIVE")
        self.assertIn("[Time TBD]", str(event["summary"]))
        self.assertIn("Kickoff: TBD", str(event["description"]))

    def test_unknown_date_uses_explicit_week_placeholder(self):
        game = sample_game(start_time=None, date=None, time_tbd=True, date_tbd=True)
        event = events(serialized([game]))[0]
        self.assertEqual(event.decoded("dtstart"), date(2026, 9, 27))
        self.assertIn("[Date & time TBD]", str(event["summary"]))
        self.assertIn("This is not a confirmed game date", str(event["description"]))
        self.assertIn("Broadcast information: TBD", str(events(serialized([sample_game(broadcast={})]))[0]["description"]))

    def test_tbd_to_confirmed_keeps_uid(self):
        game = sample_game(start_time=None, date=None, time_tbd=True, date_tbd=True)
        before = update_revisions([game], {}, NOW)
        after_game = sample_game()
        after = update_revisions([after_game], before, NOW + timedelta(hours=6))
        old_event = events(serialized([game], before))[0]
        new_event = events(serialized([after_game], after))[0]
        self.assertEqual(old_event["uid"], new_event["uid"])
        self.assertEqual(str(new_event["status"]), "CONFIRMED")
        self.assertIsInstance(new_event.decoded("dtstart"), datetime)
        self.assertEqual(new_event.decoded("sequence"), 1)

    def test_unplaceable_tbd_fails_instead_of_inventing_date(self):
        with self.assertRaisesRegex(ValueError, "no safe date"):
            serialized([sample_game(start_time=None, date=None, week_date=None, time_tbd=True, date_tbd=True)])

    def test_cancellation_retains_event_identity_and_advances_revision(self):
        game = sample_game()
        before = update_revisions([game], {}, NOW)
        cancelled = sample_game(status="cancelled")
        after = update_revisions([cancelled], before, NOW + timedelta(hours=6))
        event = events(serialized([cancelled], after))[0]
        self.assertEqual(str(event["uid"]), game_uid(game))
        self.assertEqual(str(event["status"]), "CANCELLED")
        self.assertEqual(event.decoded("sequence"), 1)
        self.assertTrue(str(event["summary"]).startswith("[Cancelled]"))

    def test_postponed_game_does_not_advertise_old_kickoff(self):
        event = events(serialized([sample_game(status="postponed")]))[0]
        self.assertEqual(str(event["status"]), "TENTATIVE")
        self.assertEqual(type(event.decoded("dtstart")), date)
        self.assertIn("[Postponed]", str(event["summary"]))
        self.assertNotIn("1:00 PM", str(event["description"]))

    def test_postseason_rounds_and_unknown_team_slots(self):
        for week, name in [(1, "Wild Card"), (2, "Divisional Round"), (3, "Conference Championships"), (5, "Super Bowl")]:
            with self.subTest(week=week):
                game = sample_game(id=f"2026-POST-source-{week}", season_type="POST", week=week, away=None, home=None, start_time=None, date="2027-01-17", time_tbd=True)
                event = events(serialized([game]))[0]
                self.assertIn(name, str(event["summary"]))
                self.assertIn("Teams TBD", str(event["summary"]))
        with self.assertRaisesRegex(ValueError, "Unsupported postseason"):
            serialized([sample_game(season_type="POST", week=4)])

    def test_international_venue_retains_country(self):
        game = sample_game(venue={"name": "Test Stadium", "city": "London", "country": "United Kingdom"})
        self.assertEqual(str(events(serialized([game]))[0]["location"]), "Test Stadium\nLondon, United Kingdom")

    def test_primetime_uses_eastern_time_even_when_utc_day_changes(self):
        self.assertFalse(is_primetime(sample_game()))
        self.assertTrue(is_primetime(sample_game(start_time="2026-09-28T00:20:00Z")))
        self.assertTrue(is_primetime(sample_game(start_time="2026-12-14T00:00:00Z")))
        self.assertFalse(is_primetime(sample_game(start_time="2026-12-13T23:59:00Z")))
        self.assertFalse(is_primetime(sample_game(start_time=None, time_tbd=True)))
        self.assertFalse(is_primetime(sample_game(start_time="2026-09-28T00:20:00Z", date_tbd=True)))

    def test_team_filtered_feed_shares_master_event_identity(self):
        games = [sample_game(), sample_game(id="2026-REG-MIA-NE", away="MIA", home="NE")]
        revisions = update_revisions(games, {}, NOW)
        team_games = [game for game in games if "BUF" in (game["away"], game["home"])]
        team_events = events(serialized(team_games, revisions, "Buffalo Bills 2026–27"))
        master_events = events(serialized(games, revisions))
        self.assertEqual(len(team_events), 1)
        self.assertIn(team_events[0]["uid"], [event["uid"] for event in master_events])

    def test_invalid_inputs_fail_closed(self):
        for games, message in [([sample_game(), sample_game()], "Duplicate"), ([sample_game(season=2027)], "does not belong"), ([sample_game(season_type="PRE")], "regular-season and postseason"), ([sample_game(start_time="2026-09-27T13:00:00")], "timezone-aware")]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                serialized(games)
        with self.assertRaises(KeyError):
            serialized([sample_game()], {})
        with self.assertRaisesRegex(ValueError, "stable game id"):
            serialized([sample_game(id="")])

    def test_revision_mutations_do_not_change_previous_state(self):
        game = sample_game()
        before = update_revisions([game], {}, NOW)
        saved = copy.deepcopy(before)
        game["status"] = "final"
        after = update_revisions([game], before, NOW - timedelta(days=1))
        self.assertEqual(before, saved)
        self.assertGreater(after[game["id"]]["modified"], before[game["id"]]["modified"])
        self.assertEqual(update_revisions([], after, NOW), after)


if __name__ == "__main__":
    unittest.main()
