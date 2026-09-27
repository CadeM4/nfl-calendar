import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from icalendar import Calendar

from nfl_calendar.cli import refresh
from nfl_calendar.changes import changes_markdown, detect_changes
from nfl_calendar.validation import ValidationError
from nfl_calendar.teams import TEAMS
from support import synthetic_schedule


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "site").mkdir()
        (self.root / "site" / "index.html").write_text("<title>Test</title>")
        self.schedule = synthetic_schedule()

    def tearDown(self):
        self.temp.cleanup()

    def run_refresh(self, schedule=None):
        return refresh(self.root, 2026, fetcher=lambda season: copy.deepcopy(schedule or self.schedule))

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for name in ("data", "public") for p in (self.root / name).rglob("*") if p.is_file()}

    def test_complete_bundle_and_team_filters(self):
        self.run_refresh()
        self.assertEqual(len(list((self.root / "public").glob("*.ics"))), 34)
        master = Calendar.from_ical((self.root / "public" / "nfl-2026.ics").read_bytes())
        uids = {str(e["UID"]) for e in master.walk("VEVENT")}
        for team in TEAMS.values():
            feed = Calendar.from_ical((self.root / "public" / f"{team['slug']}.ics").read_bytes())
            events = feed.walk("VEVENT")
            self.assertEqual(len(events), 17)
            self.assertTrue(all(team["name"] in str(e["SUMMARY"]) for e in events))
            self.assertTrue({str(e["UID"]) for e in events}.issubset(uids))

    def test_rejected_refresh_preserves_every_file(self):
        self.run_refresh()
        original = self.snapshot()
        broken = copy.deepcopy(self.schedule)
        broken["games"] = broken["games"][:14]
        with self.assertRaises(ValidationError):
            self.run_refresh(broken)
        self.assertEqual(original, self.snapshot())

    def test_source_failure_preserves_every_file(self):
        self.run_refresh()
        original = self.snapshot()
        def fail(season):
            raise ConnectionError("Simulated source outage")
        with self.assertRaises(ConnectionError):
            refresh(self.root, 2026, fetcher=fail)
        self.assertEqual(original, self.snapshot())

    def test_render_failure_preserves_every_file(self):
        self.run_refresh()
        original = self.snapshot()
        with patch("nfl_calendar.publishing.render_calendar", return_value=b"garbage"):
            with self.assertRaises(ValueError):
                self.run_refresh()
        self.assertEqual(original, self.snapshot())

    def test_interrupted_local_promotion_rolls_back_both_directories(self):
        self.run_refresh()
        original = self.snapshot()
        replacement = copy.deepcopy(self.schedule)
        replacement["fetched_at"] = "2026-09-02T12:00:00Z"
        real_replace = os.replace
        def fail_data_promotion(source, destination):
            if Path(source).name == "data" and Path(source).parent.name.startswith(".build-"):
                raise OSError("Simulated interrupted promotion")
            return real_replace(source, destination)
        with patch("nfl_calendar.publishing.os.replace", side_effect=fail_data_promotion):
            with self.assertRaisesRegex(OSError, "interrupted promotion"):
                self.run_refresh(replacement)
        self.assertEqual(original, self.snapshot())

    def test_flex_and_unchanged_refresh_sequences(self):
        self.run_refresh()
        path = self.root / "data" / "revisions-2026.json"
        old = json.loads(path.read_text())
        updated = copy.deepcopy(self.schedule)
        updated["fetched_at"] = "2026-09-02T12:00:00Z"
        self.run_refresh(updated)
        self.assertEqual(json.loads(path.read_text()), old)
        g = updated["games"][0]
        g["start_time"] = "2026-09-11T00:20:00Z"  # Same Eastern day, 8:20 PM EDT.
        self.run_refresh(updated)
        new = json.loads(path.read_text())
        self.assertEqual(new[g["id"]]["sequence"], old[g["id"]]["sequence"] + 1)
        self.assertEqual(len(new), len(old))
        changes = json.loads((self.root / "public" / "changes.json").read_text())
        self.assertEqual(len(changes), 1)
        self.assertIn("start_time", changes[0]["fields"])

    def test_missing_revision_state_does_not_reset_sequences(self):
        self.run_refresh()
        (self.root / "data" / "revisions-2026.json").unlink()
        with self.assertRaisesRegex(ValueError, "Revision state missing"):
            self.run_refresh()

    def test_readable_eastern_change_log(self):
        updated = copy.deepcopy(self.schedule)
        updated["games"][0]["start_time"] = "2026-09-11T00:20:00Z"
        text = changes_markdown(detect_changes(self.schedule, updated), updated["fetched_at"])
        self.assertIn("01:00 PM EDT", text)
        self.assertIn("08:20 PM EDT", text)

    def test_partial_revision_loss_cannot_reset_one_event(self):
        self.run_refresh()
        path = self.root / "data" / "revisions-2026.json"
        state = json.loads(path.read_text())
        state.pop(self.schedule["games"][0]["id"])
        path.write_text(json.dumps(state))
        original = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Revision state missing"):
            self.run_refresh()
        self.assertEqual(original, self.snapshot())
