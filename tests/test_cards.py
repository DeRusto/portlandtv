import json
import os
import unittest

from PIL import Image

from portlandtv import cards
from tests.harness import Channel, utc

FILES = [
    "Show A/Season 1/Show A - S01E01 - Pilot.mkv",
    "Show A/Season 1/Show A - S01E02.mkv",
    "Show A/Season 1/Show A - S01E03 - The Long Way Home.mkv",
    "Show B/Season 02/b.s02e05.mp4",
    "Show B/Season 02/b.s02e06.mp4",
    "Show C/Season 1/c.s01e01.mkv",
    "Show C/Season 1/c.s01e02.mkv",
    "Show D/Season 3/d.s03e09.mkv",
    "Show D/Season 3/d.s03e10.mkv",
]
A1 = {"name": "Show A", "subtitle": "Season 1 · Episode 1 · Pilot"}
A2 = {"name": "Show A", "subtitle": "Season 1 · Episode 2"}
A3 = {"name": "Show A", "subtitle": "Season 1 · Episode 3 · The Long Way Home"}
B5 = {"name": "Show B", "subtitle": "Season 2 · Episode 5"}
B6 = {"name": "Show B", "subtitle": "Season 2 · Episode 6"}
C1 = {"name": "Show C", "subtitle": "Season 1 · Episode 1"}
D9 = {"name": "Show D", "subtitle": "Season 3 · Episode 9"}


def block(length, repeat, *shows):
    return {"length": length, "repeat": repeat,
            "slots": [{"rule": {"show": s}} for s in shows]}


def card(source):
    """The content record written beside a card PNG."""
    with open(os.path.splitext(source)[0] + ".json", encoding="utf-8") as f:
        return json.load(f)


def breaks(program):
    """The next-up card of each Break (no filler here; schedule frames skipped)."""
    return [i["source"] for i in program
            if i["source"].endswith(".png") and "sched-" not in os.path.basename(i["source"])]


class NextUpCardTest(unittest.TestCase):
    def channel(self, *blocks):
        s = Channel({"day_schedule": list(blocks)}, FILES)
        self.addCleanup(s.close)
        return s

    def test_release_style_file_names_give_a_clean_episode_title(self):
        s = Channel({"day_schedule": [block("8h", 3, "Show E", "Show E")]},
                    ["Show E/Show.E.S01E01.Rescue.Mission.720p.WEB.x264-GRP.mkv",
                     "Show E/Show_E_S01E02_Homecoming.mkv"])
        self.addCleanup(s.close)
        s.tick(utc(2026, 11, 9, 12, 0))
        first = breaks(s.playlist("2026-11-09")["program"])[0]
        self.assertEqual(card(first)["up_next"],
                         {"name": "Show E", "subtitle": "Season 1 · Episode 2 · Homecoming"})
        self.assertEqual(card(first)["then"][0],
                         {"name": "Show E", "subtitle": "Season 1 · Episode 1 · Rescue Mission"})

    def test_text_too_long_even_when_shrunk_stays_in_its_column(self):
        long = "Show L - S01E02 - " + "A Very Long Title " * 12
        s = Channel({"day_schedule": [block("8h", 3, "Show L", "Show L")]},
                    ["Show L/Show L - S01E01.mkv", f"Show L/{long}.mkv"])
        self.addCleanup(s.close)
        s.tick(utc(2026, 11, 9, 12, 0))
        # the card whose THEN row puts the long title in the first column
        cards_ = breaks(s.playlist("2026-11-09")["program"])
        with_long = next(c for c in cards_ if card(c)["then"]
                         and card(c)["then"][0]["subtitle"].endswith("Title"))
        with Image.open(with_long) as im:  # 1920x1080: column 1 ends at x=930, column 2 starts at 990
            gap = [im.getpixel((x, y)) for x in range(935, 985) for y in range(790, 840)]
        self.assertEqual(set(gap), {(0x0b, 0x0d, 0x12)})

    def test_card_names_next_item_and_the_two_after_it(self):
        s = self.channel(block("8h", 3, "Show A", "Show A", "Show B"))
        s.ffplayout.size = (1280, 720)
        s.tick(utc(2026, 11, 9, 12, 0))
        first = breaks(s.playlist("2026-11-09")["program"])[0]
        self.assertEqual(card(first), {"up_next": A2, "then": [B5, A1]})
        with Image.open(first) as im:
            self.assertEqual(im.size, (1280, 720))

    def test_unreachable_ffplayout_uses_the_last_known_output_size(self):
        s = self.channel(block("24h", 1, "Show A", "Show B"))
        s.ffplayout.size = (1280, 720)
        s.tick(utc(2026, 11, 9, 12, 0))
        s.ffplayout.size = OSError("ffplayout down")
        s.tick(utc(2026, 11, 10, 12, 0))
        self.assertIsNone(s.service.error)
        with Image.open(breaks(s.playlist("2026-11-10")["program"])[0]) as im:
            self.assertEqual(im.size, (1280, 720))

    def test_never_reached_ffplayout_draws_cards_at_1080p(self):
        s = self.channel(block("24h", 1, "Show A", "Show B"))
        s.ffplayout.size = OSError("ffplayout down")
        s.tick(utc(2026, 11, 9, 12, 0))
        self.assertIsNone(s.service.error)
        with Image.open(breaks(s.playlist("2026-11-09")["program"])[0]) as im:
            self.assertEqual(im.size, (1920, 1080))

    def test_cards_inside_the_airing_are_shared_by_repeats(self):
        s = self.channel(block("12h", 2, "Show A", "Show B", "Show C", "Show D"))
        s.tick(utc(2026, 11, 9, 12, 0))
        cards = breaks(s.playlist("2026-11-09")["program"])
        first, second = cards[:4], cards[4:]
        self.assertEqual(first[0], second[0])  # B5, C1, D9 all inside the Airing
        self.assertEqual(card(first[0]), {"up_next": B5, "then": [C1, D9]})
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(card(first[1]), {"up_next": C1, "then": [D9, A1]})

    def test_cards_look_past_the_block_into_the_next_one(self):
        s = self.channel(block("12h", 1, "Show A", "Show B"), block("12h", 1, "Show C"))
        s.tick(utc(2026, 11, 9, 12, 0))
        self.assertEqual(card(breaks(s.playlist("2026-11-09")["program"])[0]),
                         {"up_next": B5, "then": [C1]})

    def test_movie_is_named_by_its_file_as_a_feature_film(self):
        s = Channel({"day_schedule": [{"length": "24h", "repeat": 1, "slots": [
            {"rule": {"show": "Show A"}}, {"rule": {"movie": "random"}}]}]},
            FILES, movies=["Collection/Heat (1995)/Heat (1995).mkv"])
        self.addCleanup(s.close)
        s.tick(utc(2026, 11, 9, 12, 0))
        self.assertEqual(card(breaks(s.playlist("2026-11-09")["program"])[0]),
                         {"up_next": {"name": "Heat (1995)", "subtitle": "Feature film"},
                          "then": []})

    def test_last_cards_of_the_day_are_placeholders_until_tomorrow_is_built(self):
        s = self.channel(block("12h", 2, "Show A", "Show B", "Show C", "Show D"))
        s.tick(utc(2026, 11, 9, 12, 0))
        last = breaks(s.playlist("2026-11-09")["program"])[4:]
        self.assertEqual([card(c) for c in last], [
            {"up_next": B5, "then": [C1, D9]},
            {"up_next": C1, "then": [D9]},
            {"up_next": D9, "then": []},
            {"up_next": None, "then": []},  # plain PORTLAND TV card
        ])

        s.tick(utc(2026, 11, 10, 5, 0))
        self.assertEqual(breaks(s.playlist("2026-11-09")["program"])[4:], last)
        A2 = {"name": "Show A", "subtitle": "Season 1 · Episode 2"}
        C2 = {"name": "Show C", "subtitle": "Season 1 · Episode 2"}
        self.assertEqual([card(c) for c in last], [
            {"up_next": B5, "then": [C1, D9]},
            {"up_next": C1, "then": [D9, A2]},
            {"up_next": D9, "then": [A2, B6]},
            {"up_next": A2, "then": [B6, C2]},  # no "tomorrow" marker
        ])

    def test_placeholder_of_an_empty_first_block_is_filled_in_too(self):
        s = self.channel({"length": "12h", "repeat": 1, "slots": []}, block("12h", 1, "Show A"))
        s.tick(utc(2026, 11, 9, 12, 0))
        s.tick(utc(2026, 11, 10, 5, 0))
        self.assertEqual([card(c) for c in breaks(s.playlist("2026-11-09")["program"])],
                         [{"up_next": A1, "then": [A2]}, {"up_next": A2, "then": []}])

    def test_placeholders_stay_if_the_next_day_fails_to_build(self):
        s = self.channel(block("24h", 1, "Show A", "Show B"))
        s.tick(utc(2026, 11, 9, 12, 0))
        last = breaks(s.playlist("2026-11-09")["program"])[-1]

        with open(s.config_path, "w") as f:
            f.write("day_schedule: [")  # unreadable YAML: tomorrow cannot be built
        s.tick(utc(2026, 11, 10, 5, 0))
        self.assertIsNotNone(s.service.error)
        self.assertEqual(card(last), {"up_next": None, "then": []})


class DescribeTest(unittest.TestCase):
    def subtitle(self, path):
        path = os.path.join(*path.split("/"))
        return cards.describe(path, {path: "Show"})["subtitle"]

    def test_release_tags_end_the_title(self):
        self.assertEqual(self.subtitle("tv/Fallout/Season 1/s01e01.1080p.aac.repack.mkv"),
                         "Season 1 · Episode 1")
        self.assertEqual(self.subtitle("tv/X/S02E03.The.Proper.Way.PROPER.HDTV.mkv"),
                         "Season 2 · Episode 3 · The Proper Way")

    def test_tags_inside_words_are_kept(self):
        self.assertEqual(self.subtitle("tv/X/S01E04 - Cobwebs and Webster.mkv"),
                         "Season 1 · Episode 4 · Cobwebs and Webster")

    def test_nxnn_names_and_the_season_folder_wins(self):
        self.assertEqual(self.subtitle("tv/X/x.1x05.Gone.mkv"), "Season 1 · Episode 5 · Gone")
        self.assertEqual(self.subtitle("tv/X/Season 3/x.S01E05.mkv"), "Season 3 · Episode 5")
        self.assertEqual(self.subtitle("tv/X/x.1920x1080.mkv"), "")


if __name__ == "__main__":
    unittest.main()
