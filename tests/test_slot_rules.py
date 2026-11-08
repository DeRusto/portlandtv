import os
import unittest

from tests.harness import Station, utc

FILES = [
    "Show A/a01.mkv", "Show A/a02.mkv",
    "Show B/b01.mkv", "Show B/b02.mkv",
    "Show C/c01.mkv", "Show C/c02.mkv",
]
DAY1, DAY2 = utc(2026, 11, 9, 12, 0), utc(2026, 11, 10, 12, 0)


def day(*rules, **extra):
    return {"day_schedule": [{"length": "24h", "repeat": 1,
                              "slots": [{"rule": r} for r in rules]}], **extra}


class SlotRulesTest(unittest.TestCase):
    def station(self, config, files=FILES, durations=None, **kw):
        s = Station(config, files, durations, **kw)
        self.addCleanup(s.close)
        return s

    def aired(self, s, date):
        """Content items of the day's first Airing, as Library-relative paths."""
        return [s.rel(i["source"]) for i in s.playlist(date)["program"]
                if not i["source"].endswith(".png")]

    def test_show_wraps_silently_to_its_first_episode(self):
        s = self.station(day({"show": "Show A"}, {"show": "Show A"}, {"show": "Show A"}))
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"),
                         ["Show A/a01.mkv", "Show A/a02.mkv", "Show A/a01.mkv"])
        self.assertIsNone(s.service.error)

    def test_show_group_plays_members_in_order_and_wraps(self):
        s = self.station(day(*[{"group": "Group X"}] * 3,
                             show_groups={"Group X": ["Show B", "Show C"]}))
        s.tick(DAY1)
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-09"),
                         ["Show B/b01.mkv", "Show B/b02.mkv", "Show C/c01.mkv"])
        self.assertEqual(self.aired(s, "2026-11-10"),
                         ["Show C/c02.mkv", "Show B/b01.mkv", "Show B/b02.mkv"])

    def test_a_show_keeps_one_position_across_slots_and_groups(self):
        s = self.station(day({"group": "Group X"}, {"show": "Show B"}, {"group": "Group X"},
                             show_groups={"Group X": ["Show B", "Show C"]}))
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"),
                         ["Show B/b01.mkv", "Show B/b02.mkv", "Show C/c01.mkv"])

    def test_missing_show_or_group_member_is_dropped_and_flagged(self):
        s = self.station(day({"show": "Show A"}, {"show": "Nope"},
                             {"group": "Group Y"}, {"show": "Show A"},
                             show_groups={"Group Y": ["Show B", "Gone"]}))
        s.tick(DAY1)
        self.assertIsNone(s.service.error)
        self.assertEqual(self.aired(s, "2026-11-09"), ["Show A/a01.mkv", "Show A/a02.mkv"])
        problems = s.read_json("days/2026-11-09.json")["problems"]
        self.assertEqual(len(problems), 2)
        self.assertIn("Nope", problems[0])
        self.assertIn("Gone", problems[1])
        # dropped Slots advance nothing
        self.assertNotIn("Show B", s.read_json("state.json")["shows"])
        program = s.playlist("2026-11-09")["program"]
        self.assertEqual(sum(i["out"] - i["in"] for i in program), 86400)

    def test_trailing_slots_that_overrun_are_dropped_without_advancing(self):
        s = self.station(
            {"day_schedule": [{"length": "1h", "repeat": 24, "slots": [
                {"rule": {"show": "Show A"}}, {"rule": {"show": "Show B"}},
                {"rule": {"show": "Show C"}}]}]},
            durations={"a01.mkv": 1800.0, "b01.mkv": 1500.0, "c01.mkv": 600.0})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09")[:3],
                         ["Show A/a01.mkv", "Show B/b01.mkv", "Show A/a01.mkv"])
        self.assertEqual(s.read_json("days/2026-11-09.json")["slots"],
                         [[s.path("Show A/a01.mkv"), s.path("Show B/b01.mkv")]])
        self.assertNotIn("Show C", s.read_json("state.json")["shows"])
        program = s.playlist("2026-11-09")["program"]
        # the 300 s left over goes to the two Breaks
        self.assertEqual([i["duration"] for i in program[:4]], [1800.0, 150.0, 1500.0, 150.0])
        self.assertEqual(sum(i["out"] - i["in"] for i in program), 86400)

    def test_block_with_nothing_that_fits_is_one_break(self):
        s = self.station(day({"show": "Nope"}))
        s.tick(DAY1)
        program = s.playlist("2026-11-09")["program"]
        self.assertEqual(len(program), 1)
        self.assertEqual(program[0]["duration"], 86400)

    def test_random_movie_deck_never_repeats_until_used_up(self):
        movies = ["A (2001).mkv", "Collection/B/B.mp4", "Collection/C/deeper/C.avi"]
        s = self.station(day(*[{"movie": "random"}] * 2), movies=movies)
        for d in range(9, 12):
            s.tick(utc(2026, 11, d, 12, 0))
        aired = [m for d in ("09", "10", "11") for m in self.aired(s, f"2026-11-{d}")]
        self.assertEqual(sorted(aired[:3]), sorted(movies))
        self.assertEqual(sorted(aired[3:]), sorted(movies))

    def test_new_movies_join_the_remaining_deck_and_removed_ones_drop_out(self):
        movies = [f"m{n:02}.mkv" for n in range(1, 11)]
        s = self.station(day(*[{"movie": "random"}] * 2), movies=movies)
        s.tick(DAY1)
        remaining = sorted(set(movies) - set(self.aired(s, "2026-11-09")))
        s.add_file("movies/new.mkv")
        os.remove(os.path.join(s.root, "movies", remaining.pop(0)))
        aired = []
        for d in range(10, 14):  # 8 draws: exactly what was left, plus the new movie
            s.tick(utc(2026, 11, d, 12, 0))
            aired += self.aired(s, f"2026-11-{d}")
        self.assertEqual(sorted(aired), sorted(remaining + ["new.mkv"]))

    def test_movie_extras_and_unplayable_files_are_skipped(self):
        movies = ["A (2001).mkv", "A-trailer.mkv", "B/Extras/making-of.mkv", "Bad.mkv"]
        s = self.station(day(*[{"movie": "random"}] * 2), movies=movies,
                         durations={"Bad.mkv": None})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), ["A (2001).mkv"] * 2)
        self.assertEqual([s.rel(p) for p in s.service.unplayable], ["Bad.mkv"])

    def test_missing_movies_are_flagged_not_fatal(self):
        s = self.station(day({"movie": "random"}, {"show": "Show A"}))
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), ["Show A/a01.mkv"])
        self.assertIn("movies", s.read_json("days/2026-11-09.json")["problems"][0])


if __name__ == "__main__":
    unittest.main()
