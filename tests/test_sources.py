"""Exercise source drift protection using reduced actual NFL hydration data."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from nfl_calendar.sources import (
    DETAILS_QUERY, WATCH_QUERY, SourceError, decode_queries, fetch_html,
    fetch_schedule, normalize_broadcast, normalize_status, parse_schedule_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name="nfl-week-3"):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def html(queries):
    # Split a single record in the middle of JSON, just as Flight may do.
    payload = "a:" + json.dumps({"queries": queries}) + "\n"
    mid = len(payload) // 2
    return "".join("<script>self.__next_f.push(" + json.dumps([1, part]) + ")</script>"
                   for part in (payload[:mid], payload[mid:]))


def query(queries, name):
    return next(q for q in queries if q["queryKey"][0] == name)


class OfficialSourceTests(unittest.TestCase):
    def test_real_week_has_16_games_correct_eastern_dates_and_international_venue(self):
        games = parse_schedule_page(html(fixture()), 2026, "REG", 3)
        self.assertEqual(len(games), 16)
        thursday = next(g for g in games if g["away"] == "ATL")
        self.assertEqual(thursday["start_time"], "2026-09-25T00:15:00Z")
        self.assertEqual(thursday["date"], "2026-09-24")
        self.assertEqual(thursday["status"], "final")
        international = next(g for g in games if g["away"] == "BAL")
        self.assertEqual(international["venue"]["city"], "Rio de Janeiro")
        self.assertEqual(international["venue"]["country"], "Brazil")

    def test_real_tbd_games_have_no_invented_time_date_or_network(self):
        games = parse_schedule_page(html(fixture("nfl-week-18")), 2026, "REG", 18)
        self.assertEqual(len(games), 16)
        for game in games:
            self.assertIsNone(game["start_time"])
            self.assertIsNone(game["date"])
            self.assertTrue(game["date_tbd"])
            self.assertTrue(game["time_tbd"])
            self.assertEqual(game["week_date"], "2027-01-06")
            self.assertEqual(game["broadcast"]["tv"], [])
            self.assertEqual(game["broadcast"]["streaming"], [])

    def test_actual_superbowl_uses_source_week_four_and_normalized_week_five(self):
        games = parse_schedule_page(html(fixture("nfl-2025-superbowl")), 2025, "POST", 4)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["week"], 5)
        self.assertEqual(games[0]["source_week"], 4)
        self.assertTrue(games[0]["id"].startswith("2025-POST-nfl-"))

    def test_per_game_streaming_entitlements_and_restrictions(self):
        games = parse_schedule_page(html(fixture()), 2026, "REG", 3)
        cbs = next(g for g in games if g["away"] == "HOU")
        self.assertIn("Paramount+", cbs["broadcast"]["streaming"])
        self.assertTrue(any("local CBS" in n for n in cbs["broadcast"]["notes"]))
        fox = next(g for g in games if g["away"] == "LAC")
        self.assertEqual(fox["broadcast"]["tv"], ["FOX"])
        self.assertIn("FOX One", fox["broadcast"]["streaming"])
        self.assertTrue(any("phone or tablet" in n for n in fox["broadcast"]["notes"]))
        self.assertTrue(any("out-of-market" in n for n in fox["broadcast"]["notes"]))

    def test_tv_or_internal_streaming_routes_do_not_imply_services(self):
        info = {"homeNetworkChannels": ["CBS"], "awayNetworkChannels": ["CBS"],
                "streamingNetworks": [{"hostNetwork": "CBS", "networks": ["CBS"]}],
                "territory": "REGIONAL"}
        self.assertEqual(normalize_broadcast(info)["streaming"], [])

    def test_live_status_phase_and_administrative_precedence(self):
        cases = [
            ("SCHEDULED", None, "scheduled"), ("SCHEDULED", "PREGAME", "scheduled"),
            ("SCHEDULED", "INGAME", "live"), ("SCHEDULED", "HALFTIME", "live"),
            ("SCHEDULED", "SUSPENDED", "live"), ("SCHEDULED", "FINAL", "final"),
            ("SCHEDULED", "FINAL_OVERTIME", "final"), ("ARCHIVED", "FINAL", "final"),
            ("POSTPONED", "INGAME", "postponed"), ("CANCELLED", "FINAL", "cancelled"),
            ("CANCELED", None, "cancelled"), ("FORFEITED", None, "final"),
            ("IN_PROGRESS", None, "live"), ("LIVE", None, "live"),
            ("FINAL", "PREGAME", "final"),
        ]
        for status, phase, expected in cases:
            with self.subTest(status=status, phase=phase):
                self.assertEqual(normalize_status(status, phase), expected)
        for status, phase in (("ARCHIVED", None), ("UNKNOWN_NEW_STATUS", None), ("SCHEDULED", "UNKNOWN_PHASE")):
            with self.assertRaises(SourceError):
                normalize_status(status, phase)

    def test_suspended_and_forfeited_games_receive_explicit_notes(self):
        for status, phase, expected in (("SCHEDULED", "SUSPENDED", "suspended"), ("FORFEITED", None, "forfeited")):
            q = fixture()
            raw = query(q, DETAILS_QUERY)["state"]["data"][0]
            raw["status"] = status
            raw["summary"] = {"phase": phase}
            result = parse_schedule_page(html(q), 2026, "REG", 3)[0]
            self.assertIn(expected, result["notes"][0])

    def test_replay_audio_and_non_us_authorizations_do_not_imply_live_streams(self):
        info = {"homeNetworkChannels": ["CBS"], "awayNetworkChannels": ["CBS"]}
        coverage = {
            "broadcastAiringType": "LIVE", "deliveryMethod": "LIVE", "contentType": "GAME", "gameId": "example",
            "authorizations": {"paramount_plus": [{"PARAMOUNT PLUS - LIVE GAME": {"requirements": {"countryCode": ["US"]}}}]},
        }
        self.assertIn("Paramount+", normalize_broadcast(info, {"coverageMap": coverage})["streaming"])
        for key, value in (("broadcastAiringType", "REPLAY"), ("deliveryMethod", "VOD"), ("contentType", "AUDIO")):
            changed = copy.deepcopy(coverage)
            changed[key] = value
            self.assertEqual(normalize_broadcast(info, {"coverageMap": changed})["streaming"], [])
        for label, countries in (("PARAMOUNT PLUS - REPLAY", ["US"]), ("PARAMOUNT PLUS - AUDIO PASS", ["US"]),
                                 ("PARAMOUNT PLUS - LIVE GAME", ["CA"]), ("PARAMOUNT PLUS - LIVE GAME", None)):
            changed = copy.deepcopy(coverage)
            changed["authorizations"]["paramount_plus"] = [{label: {"requirements": {"countryCode": countries}}}]
            self.assertEqual(normalize_broadcast(info, {"coverageMap": changed})["streaming"], [])

    def test_entitlement_schema_drift_and_wrong_game_are_rejected(self):
        q = fixture()
        watch = query(q, WATCH_QUERY)["state"]["data"]["data"][0]
        watch["coverageMap"].pop("broadcastAiringType")
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)
        q = fixture()
        watch = query(q, WATCH_QUERY)["state"]["data"]["data"][0]
        watch["coverageMap"]["gameId"] = "some-other-game"
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_source_uuid_is_preserved_and_flex_keeps_regular_id(self):
        q = fixture()
        first = parse_schedule_page(html(q), 2026, "REG", 3)[0]
        raw = query(q, DETAILS_QUERY)["state"]["data"][0]
        raw["time"] = "2026-09-28T00:20:00Z"
        watch = query(q, WATCH_QUERY)["state"]["data"]["data"][0]
        watch["date"] = raw["time"]
        after = parse_schedule_page(html(q), 2026, "REG", 3)[0]
        self.assertEqual(first["id"], after["id"])
        self.assertEqual(first["source_ids"]["nfl"], after["source_ids"]["nfl"])
        self.assertNotEqual(first["date"], after["date"])

    def test_wrong_season_or_redirected_week_fails(self):
        for season, week in ((2025, 3), (2026, 2)):
            with self.assertRaises(SourceError):
                parse_schedule_page(html(fixture()), season, "REG", week)

    def test_game_from_wrong_week_fails(self):
        q = fixture()
        query(q, DETAILS_QUERY)["state"]["data"][0]["week"] = 2
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_missing_watch_query_or_game_fails(self):
        q = fixture()
        q = [item for item in q if item["queryKey"][0] != WATCH_QUERY]
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)
        q = fixture()
        query(q, WATCH_QUERY)["state"]["data"]["data"].pop()
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_disagreement_between_schedule_and_viewing_times_fails(self):
        q = fixture()
        query(q, WATCH_QUERY)["state"]["data"]["data"][0]["date"] = "2026-09-29T00:15:00Z"
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_duplicate_or_tiny_game_lists_fail(self):
        q = fixture()
        query(q, DETAILS_QUERY)["state"]["data"].append(copy.deepcopy(query(q, DETAILS_QUERY)["state"]["data"][0]))
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)
        q = fixture()
        query(q, DETAILS_QUERY)["state"]["data"] = query(q, DETAILS_QUERY)["state"]["data"][:1]
        query(q, WATCH_QUERY)["state"]["data"]["data"] = query(q, WATCH_QUERY)["state"]["data"]["data"][:1]
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_failed_query_and_conflicting_duplicate_query_fail(self):
        q = fixture()
        query(q, DETAILS_QUERY)["state"]["status"] = "error"
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)
        q = fixture()
        conflicting = copy.deepcopy(query(q, DETAILS_QUERY))
        conflicting["state"]["data"].pop()
        q.append(conflicting)
        with self.assertRaises(SourceError):
            parse_schedule_page(html(q), 2026, "REG", 3)

    def test_script_is_never_executed_and_malformed_page_fails(self):
        with self.assertRaises(SourceError):
            decode_queries('<script>self.__next_f.push(__import__("os").system("false"))</script>')
        with self.assertRaises(SourceError):
            decode_queries("<html>temporary maintenance</html>")

    def test_incomplete_season_selector_fails_before_other_requests(self):
        q = fixture()
        next(item for item in q if item["queryKey"][0] == "useFetchExperienceWeekSelectorBySeason")["state"]["data"]["data"].pop()
        with self.assertRaises(SourceError):
            fetch_schedule(2026, fetcher=lambda _: html(q))

    @patch("nfl_calendar.sources.time.sleep")
    @patch("nfl_calendar.sources.urlopen")
    def test_http_503_retries_are_bounded(self, urlopen, sleep):
        urlopen.side_effect = HTTPError("https://www.nfl.com", 503, "Unavailable", {}, None)
        with self.assertRaises(SourceError):
            fetch_html("https://www.nfl.com/schedules")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("nfl_calendar.sources.time.sleep")
    @patch("nfl_calendar.sources.urlopen")
    def test_http_404_is_not_retried(self, urlopen, sleep):
        urlopen.side_effect = HTTPError("https://www.nfl.com", 404, "Not Found", {}, None)
        with self.assertRaises(SourceError):
            fetch_html("https://www.nfl.com/schedules")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
