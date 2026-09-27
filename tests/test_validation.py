import copy
import unittest

from nfl_calendar.validation import ValidationError, validate_schedule
from support import synthetic_schedule


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.schedule = synthetic_schedule()

    def test_complete_league(self):
        self.assertEqual(validate_schedule(self.schedule), {"regular": 272, "postseason": 0, "total": 272, "teams": 32})

    def test_truncated_refresh_rejected(self):
        self.schedule["games"] = self.schedule["games"][:14]
        with self.assertRaisesRegex(ValidationError, "Expected 272"):
            validate_schedule(self.schedule)

    def test_duplicate_matchup_even_with_new_id(self):
        self.schedule["games"][1] = copy.deepcopy(self.schedule["games"][0])
        self.schedule["games"][1]["id"] = "new-id"
        with self.assertRaisesRegex(ValidationError, "Duplicate regular-season matchup"):
            validate_schedule(self.schedule)

    def test_invalid_team_self_play_and_naive_time(self):
        for patch in ({"away": "NOTATEAM"}, {"away": self.schedule["games"][0]["home"]}, {"start_time": "2026-09-10T17:00:00"}):
            with self.subTest(patch=patch):
                schedule = copy.deepcopy(self.schedule)
                schedule["games"][0].update(patch)
                with self.assertRaises(ValidationError):
                    validate_schedule(schedule)

    def test_wrong_season_timestamp(self):
        self.schedule["games"][0]["start_time"] = "2025-09-10T17:00:00Z"
        with self.assertRaisesRegex(ValidationError, "outside season"):
            validate_schedule(self.schedule)

    def test_known_game_cannot_disappear(self):
        old = copy.deepcopy(self.schedule)
        self.schedule["games"][0]["id"] = "unexpected-new-id"
        with self.assertRaisesRegex(ValidationError, "disappeared"):
            validate_schedule(self.schedule, old)

    def test_mass_degradation_rejected(self):
        old = copy.deepcopy(self.schedule)
        for g in self.schedule["games"][:9]:
            g["time_tbd"] = True
            g["start_time"] = None
        with self.assertRaisesRegex(ValidationError, "loss of confirmed kickoffs"):
            validate_schedule(self.schedule, old)

    def test_mass_network_loss_rejected(self):
        old = copy.deepcopy(self.schedule)
        for g in self.schedule["games"]:
            g["broadcast"]["tv"] = []
        with self.assertRaisesRegex(ValidationError, "broadcast information"):
            validate_schedule(self.schedule, old)

    def test_tbd_is_honest(self):
        self.schedule["games"][0]["time_tbd"] = True
        with self.assertRaisesRegex(ValidationError, "cannot claim a kickoff"):
            validate_schedule(self.schedule)

    def test_streaming_loss_rejected_even_when_tv_remains(self):
        for game in self.schedule["games"]:
            game["broadcast"]["streaming"] = ["TEST STREAM"]
        old = copy.deepcopy(self.schedule)
        for game in self.schedule["games"]:
            game["broadcast"]["streaming"] = []
        with self.assertRaisesRegex(ValidationError, "streaming information"):
            validate_schedule(self.schedule, old)

    def test_postseason_added_then_cannot_disappear(self):
        old = copy.deepcopy(self.schedule)
        playoff = copy.deepcopy(self.schedule["games"][0])
        playoff.update(id="2026-POST-official-id", season_type="POST", week=1,
                       away=None, home=None, start_time=None, date=None, time_tbd=True, date_tbd=True, week_date="2027-01-13")
        self.schedule["games"].append(playoff)
        self.assertEqual(validate_schedule(self.schedule, old)["postseason"], 1)
        with self.assertRaisesRegex(ValidationError, "disappeared"):
            validate_schedule(old, self.schedule)

    def test_duplicate_super_bowl_with_distinct_id_rejected(self):
        for ident in ("one", "two"):
            playoff = copy.deepcopy(self.schedule["games"][0])
            playoff.update(id=ident, season_type="POST", week=5)
            self.schedule["games"].append(playoff)
        with self.assertRaisesRegex(ValidationError, "Too many postseason games"):
            validate_schedule(self.schedule)
