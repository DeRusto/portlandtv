import unittest

from tests.harness import Channel, utc

FILES = ["Show A/a01.mkv", "Show A/a02.mkv", "Show B/b01.mkv", "Show B/b02.mkv"]
MON, TUE = utc(2026, 11, 9, 12, 0), utc(2026, 11, 10, 12, 0)  # 2026-11-09 is a Monday


def week(*slots):
    return {"day_schedule": [{"length": "24h", "repeat": 1, "slots": list(slots)}]}


class WeekdayRulesTest(unittest.TestCase):
    def channel(self, config):
        s = Channel(config, FILES)
        self.addCleanup(s.close)
        return s

    def aired(self, s, date):
        return [s.rel(i["source"]) for i in s.playlist(date)["program"]
                if not i["source"].endswith(".png")]

    def test_distributed_slot_uses_the_weekday_rule_of_the_day_it_starts_on(self):
        s = self.channel(week({"rule": {"show": "Show A"}},
                              {"weekdays": {"mon": {"show": "Show B"}, "tue": {"show": "Show A"}}}))
        s.tick(MON)
        s.tick(TUE)
        self.assertIsNone(s.service.error)
        self.assertEqual(self.aired(s, "2026-11-09"), ["Show A/a01.mkv", "Show B/b01.mkv"])
        self.assertEqual(self.aired(s, "2026-11-10"), ["Show A/a02.mkv", "Show A/a01.mkv"])

    def test_empty_weekday_rule_skips_the_slot_into_the_breaks_and_is_flagged(self):
        s = self.channel(week({"rule": {"show": "Show A"}},
                              {"weekdays": {"mon": {}, "wed": {"show": "Show B"}}}))
        s.tick(MON)
        self.assertIsNone(s.service.error)
        self.assertEqual(self.aired(s, "2026-11-09"), ["Show A/a01.mkv"])
        program = s.playlist("2026-11-09")["program"]
        self.assertEqual(sum(i["out"] - i["in"] for i in program), 86400)
        problems = s.read_json("days/2026-11-09.json")["problems"]
        self.assertEqual(len(problems), 1)
        self.assertIn("Block 1 Slot 2: empty Weekday Rule", problems[0])
        self.assertNotIn("Show B", s.read_json("state.json")["shows"])

    def test_bad_weekday_key_is_a_config_error(self):
        s = self.channel(week({"weekdays": {"monday": {"show": "Show A"}}}))
        s.tick(MON)
        self.assertIn("bad weekdays", s.service.error)
