"""day.build directly: the cards a Broadcast Day needs, and the previous day's End Cards
it redraws, with no files written."""
import unittest
from datetime import date, time
from types import SimpleNamespace

from portlandtv import day
from tests.fakes import FakeProber

DAY1, DAY2 = date(2026, 11, 9), date(2026, 11, 10)
SHOWS = {s: [f"{s}/{n}.mkv" for n in range(1, 6)] for s in "ABCD"}  # 600 s each


def card_path(d, name):
    return f"{d}/{name}.png"


def cfg(*blocks):
    return {"day_start": time(6), "show_groups": {}, "day_schedule": list(blocks)}


def block(hours, repeat, *shows):
    return {"length": hours * 3600, "repeat": repeat, "slots": [{"show": s} for s in shows]}


def build(c, on=DAY1, state=None, previous=None):
    return day.build(c, on, SHOWS, state or {"shows": {}}, FakeProber(), card_path,
                     previous=previous)


def cards(built):
    """The program's next-up cards (schedule frames left out), in airing order."""
    return [i["source"] for i in built.program if i["source"].endswith(".png")
            and "items" in built.cards[i["source"]]]


def items(built, path):
    return built.cards[path]["items"]


class CardsTest(unittest.TestCase):
    def test_repeats_share_a_card_only_when_it_shows_the_same_items(self):
        built = build(cfg(block(12, 2, "A", "B", "C", "D")))
        first, second = cards(built)[:4], cards(built)[4:]
        self.assertEqual(first[0], second[0])
        self.assertEqual(items(built, first[0]), ["B/1.mkv", "C/1.mkv", "D/1.mkv"])
        self.assertNotEqual(first[1], second[1])  # it looks past the Airing
        self.assertEqual(items(built, first[1]), ["C/1.mkv", "D/1.mkv", "A/1.mkv"])

    def test_every_card_in_the_program_is_listed_once(self):
        built = build(cfg(block(12, 2, "A", "B", "C", "D")))
        sources = {i["source"] for i in built.program if i["source"].endswith(".png")}
        self.assertEqual(sources, set(built.cards))

    def test_last_breaks_air_end_cards_listed_for_the_day_record(self):
        built = build(cfg(block(12, 2, "A", "B", "C", "D")))
        last = cards(built)[-3:]
        self.assertEqual(last, [card_path(DAY1, f"end-{n}") for n in (3, 2, 1)])
        self.assertEqual([items(built, p) for p in last],
                         [["C/1.mkv", "D/1.mkv"], ["D/1.mkv"], []])
        self.assertEqual(built.end_cards, ["end-3", "end-2", "end-1"])
        self.assertEqual(built.tail, ["B/1.mkv", "C/1.mkv", "D/1.mkv"])

    def test_schedule_frame_lists_the_airing_with_clock_times(self):
        built = build(cfg(block(8, 3, "A", "B", "C", "D")))
        frame = next(c for c in built.cards.values() if "rows" in c)
        self.assertEqual(frame["range"], "06:00–14:00 UTC")
        self.assertEqual([(r["time"], r["path"], r["state"]) for r in frame["rows"]], [
            ("06:00", "A/1.mkv", "aired"), ("08:00", "B/1.mkv", "aired"),
            ("10:00", "C/1.mkv", "aired"), ("12:00", "D/1.mkv", "up_next")])


class RedrawTest(unittest.TestCase):
    def today(self, previous):
        return build(cfg(block(24, 1, "A", "B")), on=DAY2, previous=previous)

    def test_previous_days_end_cards_get_todays_first_items(self):
        prev = SimpleNamespace(tail=["x", "y", "z"], end_cards=["end-3", "end-2", "end-1"])
        self.assertEqual(self.today(prev).redraw, {
            card_path(DAY1, "end-3"): {"items": ["y", "z", "A/1.mkv"]},
            card_path(DAY1, "end-2"): {"items": ["z", "A/1.mkv", "B/1.mkv"]},
            card_path(DAY1, "end-1"): {"items": ["A/1.mkv", "B/1.mkv"]}})

    def test_only_the_end_cards_the_previous_day_aired_are_redrawn(self):
        prev = SimpleNamespace(tail=["x", "y", "z"], end_cards=["end-1"])
        self.assertEqual(list(self.today(prev).redraw), [card_path(DAY1, "end-1")])

    def test_empty_first_block_airs_an_end_card_before_the_days_first_item(self):
        yesterday = build(cfg({"length": 43200, "repeat": 1, "slots": []}, block(12, 1, "A")))
        self.assertEqual(yesterday.end_cards, ["end-2", "end-1"])
        self.assertEqual(yesterday.tail, ["A/1.mkv"])
        prev = SimpleNamespace(tail=yesterday.tail, end_cards=yesterday.end_cards)
        today = build(cfg(block(24, 1, "A", "B")), on=DAY2, previous=prev,
                      state=yesterday.state)
        self.assertEqual(today.redraw, {
            card_path(DAY1, "end-2"): {"items": ["A/1.mkv", "A/2.mkv", "B/1.mkv"]},
            card_path(DAY1, "end-1"): {"items": ["A/2.mkv", "B/1.mkv"]}})

    def test_record_from_before_end_cards_redraws_every_one_its_tail_allows(self):
        prev = SimpleNamespace(tail=["z"], end_cards=None)
        self.assertEqual(list(self.today(prev).redraw),
                         [card_path(DAY1, "end-1"), card_path(DAY1, "end-2")])

    def test_record_without_a_tail_or_no_previous_day_redraws_nothing(self):
        self.assertEqual(self.today(SimpleNamespace(tail=None, end_cards=None)).redraw, {})
        self.assertEqual(self.today(None).redraw, {})


if __name__ == "__main__":
    unittest.main()
