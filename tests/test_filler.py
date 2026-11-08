import os
import unittest

from tests.harness import PER_AIRING_CARD, Channel, utc

# 24 one-hour Airings of a 1200 s episode: one 2400 s Break each
HOURLY = {"day_schedule": [{"length": "1h", "repeat": 24, "slots": [
    {"rule": {"show": "Show A"}}]}]}
EPISODES = ["Show A/Season 1/Show A - S01E01.mkv", "Show A/Season 1/Show A - S01E02.mkv"]


class FillerTest(unittest.TestCase):
    def channel(self, filler, durations=None):
        s = Channel(HOURLY, EPISODES, {"Show A - S01E01.mkv": 1200.0,
                                       "Show A - S01E02.mkv": 1200.0, **(durations or {})},
                    filler=filler)
        self.addCleanup(s.close)
        return s

    def airing(self, s, date="2026-11-09"):
        """The day's first Airing, after checking all 24 are written verbatim
        (apart from the cards looking past their Airing, which differ per Repeat)."""
        program = s.playlist(date)["program"]
        n = len(program) // 24
        masked = [{**i, "source": "card"} if PER_AIRING_CARD.search(i["source"]) else i
                  for i in program]
        self.assertEqual(masked, masked[:n] * 24)
        self.assertIn(program[0]["source"], [s.path(e) for e in EPISODES])
        return program[:n]

    def assertStill(self, item, seconds):
        self.assertTrue(item["source"].endswith(".png"))
        self.assertEqual((item["in"], item["out"], item["duration"]), (0, seconds, seconds))

    def test_break_takes_whole_clips_then_a_still_for_the_rest(self):
        s = self.channel(["a.mp4", "deep/er/b-trailer.mkv", "c.mov", "notes.txt"],
                         {"a.mp4": 1000.0, "b-trailer.mkv": 700.0, "c.mov": 500.0})
        s.tick(utc(2026, 11, 9, 12, 0))
        airing = self.airing(s)
        self.assertEqual(len(airing), 5)
        clips = airing[1:4]
        self.assertEqual(sorted(c["source"] for c in clips),
                         sorted(os.path.join(s.filler, p)
                                for p in ["a.mp4", "deep/er/b-trailer.mkv", "c.mov"]))
        for c in clips:
            self.assertEqual((c["in"], c["out"]), (0, c["duration"]))
        self.assertStill(airing[4], 200.0)

    def test_deck_persists_across_days_and_reshuffles_when_used_up(self):
        # one clip per Break (any two overrun 2400 s), so one draw per day
        s = self.channel(["x.mp4", "y.mp4", "z.mp4"],
                         {"x.mp4": 1300.0, "y.mp4": 1400.0, "z.mp4": 1500.0})
        drawn = []
        for day in range(9, 15):
            s.tick(utc(2026, 11, day, 12, 0))
            airing = self.airing(s, f"2026-11-{day:02}")
            self.assertEqual(len(airing), 3)
            clip = airing[1]
            self.assertStill(airing[2], 2400.0 - clip["duration"])
            drawn.append(os.path.basename(clip["source"]))
        self.assertEqual(sorted(drawn[:3]), ["x.mp4", "y.mp4", "z.mp4"])
        self.assertEqual(sorted(drawn[3:]), ["x.mp4", "y.mp4", "z.mp4"])

    def test_short_filler_repeats_within_a_break(self):
        s = self.channel(["only.mp4"], {"only.mp4": 500.0})
        s.tick(utc(2026, 11, 9, 12, 0))
        airing = self.airing(s)
        self.assertEqual([os.path.basename(i["source"]) for i in airing[1:5]],
                         ["only.mp4"] * 4)
        self.assertStill(airing[5], 400.0)

    def test_leftover_under_one_second_is_not_written(self):
        s = self.channel(["long.mp4"], {"long.mp4": 2399.5})
        s.tick(utc(2026, 11, 9, 12, 0))
        airing = self.airing(s)
        self.assertEqual([os.path.basename(i["source"]) for i in airing],
                         ["Show A - S01E01.mkv", "long.mp4"])

    def test_empty_filler_folder_makes_the_whole_break_one_still(self):
        s = self.channel([])
        s.tick(utc(2026, 11, 9, 12, 0))
        self.assertIsNone(s.service.error)
        airing = self.airing(s)
        self.assertEqual(len(airing), 2)
        self.assertStill(airing[1], 2400.0)

    def test_a_clip_too_long_for_this_break_does_not_block_shorter_ones(self):
        # a 300 s Break, then a 23 h one; five 1000 s clips and one 200 s clip
        config = {"day_schedule": [
            {"length": "1h", "repeat": 1, "slots": [{"rule": {"show": "Show S"}}]},
            {"length": "23h", "repeat": 1, "slots": [{"rule": {"show": "Show A"}}]}]}
        long = [f"long{n}.mp4" for n in range(5)]
        for _ in range(4):  # the deck is shuffled: the short clip is rarely at the front
            s = Channel(config, ["Show S/s.mkv", EPISODES[0]],
                        {"s.mkv": 3300.0, "short.mp4": 200.0, **{p: 1000.0 for p in long}},
                        filler=long + ["short.mp4"])
            self.addCleanup(s.close)
            s.tick(utc(2026, 11, 9, 12, 0))
            program = s.playlist("2026-11-09")["program"]
            self.assertEqual(os.path.basename(program[1]["source"]), "short.mp4")
            self.assertStill(program[2], 100.0)

    def test_clips_longer_than_any_break_never_fit_and_are_reported(self):
        s = self.channel(["huge.mp4", "ok.mp4"], {"huge.mp4": 3000.0, "ok.mp4": 1300.0})
        s.tick(utc(2026, 11, 9, 12, 0))
        airing = self.airing(s)
        self.assertEqual([os.path.basename(i["source"]) for i in airing[:2]],
                         ["Show A - S01E01.mkv", "ok.mp4"])
        self.assertStill(airing[2], 1100.0)
        self.assertEqual(s.read_json("days/2026-11-09.json")["never_fits"],
                         [os.path.join(s.filler, "huge.mp4")])


if __name__ == "__main__":
    unittest.main()
