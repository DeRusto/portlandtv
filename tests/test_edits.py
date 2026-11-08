"""#28: saved edits reach playout (on save, "rebuild today", day_start push)."""
import os
import unittest

import yaml

from tests.harness import Station, utc
from tests.web_harness import Browser

FILES = ["Show A/Show A - S01E01.mkv", "Show A/Show A - S01E02.mkv",
         "Show A/Show A - S01E03.mkv", "Show B/b.s01e01.mp4"]
DURATIONS = {"Show A - S01E01.mkv": 1200.0, "Show A - S01E02.mkv": 1500.0,
             "Show A - S01E03.mkv": 1300.0, "b.s01e01.mp4": 1800.0}
CONFIG = {"day_start": "06:00", "day_schedule": [
    {"length": "8h", "repeat": 2, "slots": [{"rule": {"show": "Show A"}}]},
    {"length": "4h", "repeat": 2, "slots": [{"rule": {"show": "Show B"}}]},
]}


class EditsTest(unittest.TestCase):
    def open(self, config=CONFIG, now=utc(2026, 11, 9, 12, 0)):
        s = Station(config, FILES, DURATIONS, now=now)
        self.addCleanup(s.close)
        s.tick()
        b = Browser(s)
        b.get()
        return s, b

    def test_save_leaves_today_and_takes_effect_next_day(self):
        s, b = self.open()
        today = s.playlist("2026-11-09")
        b.submit("add-slot:0")
        b.submit(changes={"b0.s1.rule": "show:Show A"})
        self.assertEqual(s.playlist("2026-11-09"), today)
        s.tick(utc(2026, 11, 10, 5, 30))
        self.assertEqual(s.read_json("days/2026-11-10.json")["slots"][0],
                         [s.path("Show A/Show A - S01E02.mkv"),
                          s.path("Show A/Show A - S01E03.mkv")])

    def test_save_regenerates_a_day_not_yet_started_without_double_advance(self):
        s, b = self.open(now=utc(2026, 11, 9, 12, 0))
        s.tick(utc(2026, 11, 10, 5, 30))  # tomorrow generated, not started
        self.assertEqual(s.read_json("days/2026-11-10.json")["slots"][0],
                         [s.path("Show A/Show A - S01E02.mkv")])
        b.submit("add-slot:0")
        b.submit(changes={"b0.s1.rule": "show:Show A"})
        record = s.read_json("days/2026-11-10.json")
        self.assertEqual(record["slots"][0], [s.path("Show A/Show A - S01E02.mkv"),
                                              s.path("Show A/Show A - S01E03.mkv")])
        self.assertEqual(s.playlist("2026-11-10")["program"][0]["source"],
                         s.path("Show A/Show A - S01E02.mkv"))
        self.assertEqual(s.read_json("state.json")["shows"]["Show A"]["path"],
                         s.path("Show A/Show A - S01E03.mkv"))

    def test_rebuild_today_keeps_existing_slots_and_fills_changed_ones(self):
        two_a = {"day_start": "06:00", "day_schedule": [
            {"length": "8h", "repeat": 2, "slots": [{"rule": {"show": "Show A"}}, {"rule": {"show": "Show A"}}]},
            {"length": "4h", "repeat": 2, "slots": [{"rule": {"show": "Show B"}}]},
        ]}
        s, b = self.open(two_a)
        # the first Slot changes; the second keeps today's episode (not a fresh S01E01)
        r = b.submit("rebuild", {"b0.s0.rule": "show:Show B"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(s.read_json("days/2026-11-09.json")["slots"],
                         [[s.path("Show B/b.s01e01.mp4"), s.path("Show A/Show A - S01E02.mkv")],
                          [s.path("Show B/b.s01e01.mp4")]])
        program = s.playlist("2026-11-09")["program"]
        self.assertEqual(program[0]["source"], s.path("Show B/b.s01e01.mp4"))
        # the kept episode counts as aired: tomorrow carries on after it
        s.tick(utc(2026, 11, 10, 5, 30))
        self.assertEqual(s.read_json("days/2026-11-10.json")["slots"][0][1],
                         s.path("Show A/Show A - S01E03.mkv"))
        leftovers = [f for _, _, fs in os.walk(s.root) for f in fs if f.startswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_rebuild_today_also_regenerates_a_generated_tomorrow(self):
        s, b = self.open()
        s.tick(utc(2026, 11, 10, 5, 30))
        b.submit("rebuild", {"b0.s0.rule": "show:Show B"})
        # today no longer advances Show A, so tomorrow starts at S01E01
        self.assertEqual(s.read_json("days/2026-11-10.json")["slots"][0],
                         [s.path("Show B/b.s01e01.mp4")])
        self.assertEqual(s.read_json("days/2026-11-10.json")["state_before"]["shows"].get("Show A"),
                         None)

    def test_day_start_change_is_pushed_to_ffplayout_once(self):
        s, _ = self.open()
        self.assertEqual(s.ffplayout.calls, [("set_day_start", "06:00")])
        with open(s.config_path) as f:
            raw = yaml.safe_load(f)
        raw["day_start"] = "07:00"
        with open(s.config_path, "w") as f:
            yaml.safe_dump(raw, f)
        s.tick()
        s.tick()
        self.assertEqual(s.ffplayout.calls, [("set_day_start", "06:00"),
                                             ("set_day_start", "07:00")])

    def test_failed_push_is_shown_and_retried(self):
        s, _ = self.open()
        s.ffplayout.calls.clear()
        with open(s.config_path) as f:
            raw = yaml.safe_load(f)
        raw["day_start"] = "07:00"
        with open(s.config_path, "w") as f:
            yaml.safe_dump(raw, f)
        s.ffplayout.fail = OSError("ffplayout down")
        s.tick()
        self.assertIn("ffplayout down", s.service.error)
        s.ffplayout.fail = None
        s.tick()
        self.assertIsNone(s.service.error)
        self.assertEqual(s.ffplayout.calls[-1], ("set_day_start", "07:00"))


if __name__ == "__main__":
    unittest.main()
