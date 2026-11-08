import os
import unittest

from tests.harness import PER_AIRING_CARD, Station, utc

SHOW_FILES = [
    "Show A/Season 10/Show A - S10E01.mkv",
    "Show A/Season 2/Show A - S02E01.mkv",
    "Show A/Season 1/Show A - S01E02.mkv",
    "Show A/Season 1/Show A - S01E01.mkv",
    "Show B/Season 01/b.s01e02.mp4",
    "Show B/Season 01/b.s01e01.mp4",
]
DURATIONS = {
    "Show A - S01E01.mkv": 1200.0, "Show A - S01E02.mkv": 1200.0,
    "Show A - S02E01.mkv": 1200.0, "Show A - S10E01.mkv": 1200.0,
    "b.s01e01.mp4": 1800.0, "b.s01e02.mp4": 1800.0,
}
EIGHT_BY_THREE = {"day_schedule": [{"length": "8h", "repeat": 3, "slots": [
    {"rule": {"show": "Show A"}},
    {"rule": {"show": "Show A"}},
    {"rule": {"show": "Show B"}},
]}]}


def starts(program):
    """Clock offset (s from day_start) of each item, as ffplayout computes it."""
    t, out = 0.0, []
    for item in program:
        out.append(t)
        t += item["out"] - item["in"]
    return out


class BroadcastDayTest(unittest.TestCase):
    def station(self, config=EIGHT_BY_THREE, **kw):
        s = Station(config, SHOW_FILES, DURATIONS, **kw)
        self.addCleanup(s.close)
        return s

    def test_startup_generates_current_day_with_verbatim_repeats(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 12, 0))

        playlist = s.playlist("2026-11-09")
        self.assertEqual(playlist["date"], "2026-11-09")
        program = playlist["program"]
        self.assertEqual(len(program), 18)
        airing = program[:6]
        # verbatim apart from the cards looking past their Airing (here all of them)
        masked = [{**i, "source": "card"} if PER_AIRING_CARD.search(i["source"]) else i
                  for i in program]
        self.assertEqual(masked[6:12], masked[:6])
        self.assertEqual(masked[12:], masked[:6])
        self.assertEqual(
            [i["source"] for i in airing[::2]],
            [s.path("Show A/Season 1/Show A - S01E01.mkv"),
             s.path("Show A/Season 1/Show A - S01E02.mkv"),
             s.path("Show B/Season 01/b.s01e01.mp4")])
        self.assertEqual(airing[0], {"in": 0, "out": 1200.0, "duration": 1200.0,
                                     "source": airing[0]["source"]})
        # gap 28800 - 4200 = 24600, split into 3 Breaks of 8200 s
        for brk in airing[1::2]:
            self.assertEqual((brk["in"], brk["out"], brk["duration"]), (0, 8200.0, 8200.0))
            self.assertTrue(brk["source"].endswith(".png"))
        t = starts(program)
        self.assertEqual((t[0], t[6], t[12]), (0, 28800, 57600))
        self.assertEqual(sum(i["out"] - i["in"] for i in program), 86400)

    def test_schedule_not_totalling_24h_is_rejected_with_error(self):
        s = self.station({"day_schedule": [{"length": "8h", "repeat": 2, "slots": [
            {"rule": {"show": "Show A"}}]}]})
        s.tick()
        self.assertIsNone(s.playlist("2026-11-09"))
        self.assertIn("24 h", s.service.error)

    def test_blocks_air_back_to_back_from_day_start(self):
        s = self.station({"day_start": "05:30", "day_schedule": [
            {"length": "6h", "repeat": 2, "slots": [{"rule": {"show": "Show A"}}]},
            {"length": "4h", "repeat": 3, "slots": [{"rule": {"show": "Show B"}},
                                                    {"rule": {"show": "Show A"}}]},
        ]})
        s.tick(utc(2026, 11, 9, 5, 30))
        program = s.playlist("2026-11-09")["program"]
        t = starts(program)
        self.assertEqual([t[i] for i in (0, 2, 4, 8, 12)],
                         [0, 6 * 3600, 12 * 3600, 16 * 3600, 20 * 3600])
        self.assertEqual(sum(i["out"] - i["in"] for i in program), 86400)
        # Show A keeps one position across Blocks
        self.assertEqual([program[i]["source"] for i in (0, 6)],
                         [s.path("Show A/Season 1/Show A - S01E01.mkv"),
                          s.path("Show A/Season 1/Show A - S01E02.mkv")])

    def test_unquoted_day_start_in_hand_written_yaml(self):
        s = self.station()
        with open(s.config_path, "a") as f:
            f.write("day_start: 07:15\n")  # YAML 1.1 reads this as the integer 435
        s.tick(utc(2026, 11, 9, 6, 0))
        self.assertIsNotNone(s.playlist("2026-11-08"))
        self.assertIsNone(s.playlist("2026-11-09"))

    def test_before_day_start_the_current_day_is_yesterdays(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 3, 0))
        self.assertIsNotNone(s.playlist("2026-11-08"))
        self.assertIsNone(s.playlist("2026-11-09"))

    def test_next_day_generated_one_hour_before_it_starts(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 12, 0))
        s.tick(utc(2026, 11, 10, 4, 59))
        self.assertIsNone(s.playlist("2026-11-10"))
        s.tick(utc(2026, 11, 10, 5, 0))
        self.assertEqual(
            [i["source"] for i in s.playlist("2026-11-10")["program"][:6:2]],
            [s.path("Show A/Season 2/Show A - S02E01.mkv"),
             s.path("Show A/Season 10/Show A - S10E01.mkv"),
             s.path("Show B/Season 01/b.s01e02.mp4")])

    def test_ticks_within_a_day_do_not_regenerate_or_advance(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 12, 0))
        first = s.playlist("2026-11-09")
        s.tick(utc(2026, 11, 9, 13, 0))
        self.assertEqual(s.playlist("2026-11-09"), first)
        self.assertEqual(s.read_json("state.json")["shows"]["Show A"]["path"],
                         s.path("Show A/Season 1/Show A - S01E02.mkv"))

    def test_days_never_generated_advance_nothing(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 12, 0))
        s.tick(utc(2026, 11, 14, 12, 0))  # laptop was off 10th-13th
        self.assertIsNone(s.playlist("2026-11-12"))
        self.assertEqual(s.playlist("2026-11-14")["program"][0]["source"],
                         s.path("Show A/Season 2/Show A - S02E01.mkv"))

    def test_state_and_day_record(self):
        s = self.station()
        s.tick(utc(2026, 11, 9, 12, 0))
        state_after_day1 = s.read_json("state.json")
        self.assertEqual(state_after_day1["shows"], {
            "Show A": {"path": s.path("Show A/Season 1/Show A - S01E02.mkv"), "key": [1, 2]},
            "Show B": {"path": s.path("Show B/Season 01/b.s01e01.mp4"), "key": [1, 1]},
        })
        s.tick(utc(2026, 11, 10, 5, 0))
        record = s.read_json("days/2026-11-10.json")
        self.assertEqual(record["state_before"], state_after_day1)
        self.assertEqual(record["slots"], [[
            s.path("Show A/Season 2/Show A - S02E01.mkv"),
            s.path("Show A/Season 10/Show A - S10E01.mkv"),
            s.path("Show B/Season 01/b.s01e02.mp4")]])

    def test_no_temp_files_left_behind(self):
        s = self.station()
        s.tick()
        leftovers = [f for _, _, fs in os.walk(s.root) for f in fs if f.startswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
