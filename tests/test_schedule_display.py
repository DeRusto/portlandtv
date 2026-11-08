import json
import os
import unittest

from PIL import Image

from tests.harness import Station, utc
from tests.test_cards import FILES, block, card

A1 = ("Show A", "Season 1 · Episode 1 · Pilot")
A2 = ("Show A", "Season 1 · Episode 2")
B5 = ("Show B", "Season 2 · Episode 5")
B6 = ("Show B", "Season 2 · Episode 6")
C1 = ("Show C", "Season 1 · Episode 1")
C2 = ("Show C", "Season 1 · Episode 2")
D9 = ("Show D", "Season 3 · Episode 9")


def rows(*entries):
    """(time, (name, subtitle), state) -> the rows of a frame's content record."""
    return [{"time": t, "name": n, "subtitle": s, "state": st} for t, (n, s), st in entries]


def frames(program):
    return [i for i in program if "sched-" in os.path.basename(i["source"])]


class ScheduleDisplayTest(unittest.TestCase):
    def station(self, *blocks, **kw):
        s = Station({"day_schedule": list(blocks)}, FILES, **kw)
        self.addCleanup(s.close)
        return s

    def test_every_3rd_break_shows_the_airing_before_its_card(self):
        # 4 x 600 s Slots in 8 h: 6600 s Breaks, so the Slots start on the hour
        s = self.station(block("8h", 3, "Show A", "Show B", "Show C", "Show D"))
        s.tick(utc(2026, 11, 9, 12, 0))
        program = s.playlist("2026-11-09")["program"]
        airing = program[:9]
        self.assertTrue(airing[4]["source"].endswith("c.s01e01.mkv"))
        self.assertEqual(frames(airing), [airing[5]])
        self.assertEqual([i["duration"] for i in airing[5:7]], [10, 6590])
        self.assertEqual(card(airing[6]["source"])["up_next"]["name"], "Show D")
        self.assertEqual(len(frames(program)), 3)  # one per Airing

        first, second = (card(f["source"]) for f in frames(program)[:2])
        self.assertEqual(first, {
            "heading": "TODAY ON PORTLAND TV", "range": "06:00–14:00 UTC", "page": "1/1",
            "rows": rows(("06:00", A1, "aired"), ("08:00", B5, "aired"),
                         ("10:00", C1, "aired"), ("12:00", D9, "up_next"))})
        self.assertEqual(second["range"], "14:00–22:00 UTC")
        self.assertEqual([r["time"] for r in second["rows"]],
                         ["14:00", "16:00", "18:00", "20:00"])
        with Image.open(frames(program)[0]["source"]) as im:
            self.assertEqual(im.size, (1920, 1080))

    def test_long_airing_spans_frames_of_six_rows(self):
        # 7 x 600 s Slots in 14 h: 6600 s Breaks; displays in Breaks 3 and 6
        s = self.station(block("14h", 1, "Show A", "Show B", "Show C", "Show D",
                               "Show A", "Show B", "Show C"),
                         block("10h", 1, "Show A"))
        s.tick(utc(2026, 11, 9, 12, 0))
        program = s.playlist("2026-11-09")["program"]
        shown = frames(program)
        self.assertEqual([f["duration"] for f in shown], [10] * 4)
        self.assertEqual([card(f["source"])["page"] for f in shown], ["1/2", "2/2"] * 2)
        p1, p2, p3, p4 = (card(f["source"]) for f in shown)
        self.assertEqual(p1["range"], "06:00–20:00 UTC")
        self.assertEqual(p1["rows"], rows(
            ("06:00", A1, "aired"), ("08:00", B5, "aired"), ("10:00", C1, "aired"),
            ("12:00", D9, "up_next"), ("14:00", A2, "later"), ("16:00", B6, "later")))
        self.assertEqual(p2["rows"], rows(("18:00", C2, "later")))
        self.assertEqual([r["state"] for r in p3["rows"] + p4["rows"]],
                         ["aired"] * 6 + ["up_next"])
        # each Break: Slot, frames, card
        i = program.index(shown[0])
        self.assertTrue(program[i - 1]["source"].endswith("c.s01e01.mkv"))
        self.assertEqual(program[i + 1], shown[1])
        self.assertEqual(program[i + 2]["duration"], 6580)

    def test_display_moves_to_the_next_break_when_it_does_not_fit(self):
        s = self.station(block("8h", 3, "Show A", "Show B", "Show C", "Show D"),
                         filler=["a.mp4", "b.mp4", "c.mp4", "d.mp4"],
                         durations={"a.mp4": 4000, "b.mp4": 4000, "c.mp4": 6595,
                                    "d.mp4": 4000})
        # deal the deck in a known order: Breaks leave 2600, 2600, 5 and 2600 s
        with open(os.path.join(s.root, "state.json"), "w") as f:
            json.dump({"shows": {}, "filler": {"left": [
                os.path.join(s.filler, n) for n in ("a.mp4", "b.mp4", "c.mp4", "d.mp4")],
                "aired": []}}, f)
        s.tick(utc(2026, 11, 9, 12, 0))
        program = s.playlist("2026-11-09")["program"]
        shown = frames(program)
        self.assertEqual(len(shown), 3)
        i = program.index(shown[0])
        self.assertTrue(program[i - 2]["source"].endswith("d.s03e09.mkv"))
        self.assertTrue(program[i - 1]["source"].endswith("d.mp4"))
        self.assertEqual(program[i + 1]["duration"], 2590)
        self.assertEqual([r["state"] for r in card(shown[0]["source"])["rows"]],
                         ["aired"] * 4)


if __name__ == "__main__":
    unittest.main()
