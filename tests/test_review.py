"""The Review of a Draft: numbers and problems, from dicts and a duration table."""
import unittest

from portlandtv import distributor, review

A_EPS = ["A/1.mkv", "A/2.mkv", "A/3.mkv"]
SHOWS = {"A": A_EPS, "B": ["B/1.mkv"], "C": ["C/1.mkv", "C/2.mkv"]}
MOVIES = ["m1.mkv", "m2.mkv", "m3.mkv"]
DURATIONS = {"A/1.mkv": 1200, "A/2.mkv": 1500, "A/3.mkv": 1300, "B/1.mkv": 1800,
             "C/1.mkv": 600, "C/2.mkv": 600, "m1.mkv": 5400, "m2.mkv": 7200, "m3.mkv": 6000}
A, B, C = ({"show": s} for s in "ABC")


def draft(day_schedule, show_list=(), show_groups=None):
    return {"libraries": [], "day_schedule": day_schedule, "show_list": list(show_list),
            "show_groups": show_groups or {}}


def run(raw, state=None):
    return review.review(raw, SHOWS, MOVIES, DURATIONS.get, state or {"shows": {}})


class BlockTest(unittest.TestCase):
    def test_airings_start_one_after_another_and_bad_blocks_take_no_time(self):
        rv = run(draft([{"length": "8h", "repeat": 2, "slots": []},
                        {"length": "soon", "repeat": 1, "slots": []},
                        {"length": "4h", "repeat": 2, "slots": []}]))
        self.assertEqual([b.airs for b in rv.blocks], [[0, 28800], [], [57600, 72000]])
        self.assertIsNone(rv.blocks[1].length)
        self.assertEqual(rv.assigned, 24 * 3600)

    def test_typical_is_the_median_and_most_the_longest_per_weekday(self):
        rv = run(draft([{"length": "8h", "repeat": 3, "slots": [
            {"rule": {"movie": "random"}},
            {"weekdays": {"mon": A}}]}]))
        b = rv.blocks[0]
        self.assertEqual(b.typical, [6000 + 1300] + [6000] * 6)
        self.assertEqual(b.most, [7200 + 1500] + [7200] * 6)
        self.assertEqual(b.slots[1][0], False)
        self.assertEqual(b.slots[1][1][:2], [A, {}])

    def test_empty_slots_and_overruns_are_problems(self):
        rv = run(draft([{"length": "30m", "repeat": 48, "slots": [
            {"rule": A}, {},
            {"weekdays": {d: B for d in ("mon", "tue", "wed", "thu", "fri")}}]}]))
        self.assertEqual(rv.problems[:3], [
            "Block 1 Slot 2 is empty every day: skipped",
            "Block 1 Slot 3 is empty on Sat, Sun: skipped those days",
            "Block 1 content runs past its length on Mon, Tue, Wed, Thu, Fri"])


class ShowListTest(unittest.TestCase):
    def test_entries_without_cells_and_off_list_shows_are_problems(self):
        rv = run(draft([{"length": "24h", "repeat": 1, "slots": [
            {"rule": {"show": "C"}},  # fixed: never off-list
            {"weekdays": {"mon": A, "tue": {"show": "C"}, "wed": {"movie": "random"}}}]}],
            [A, B, {"group": "G"}, {"show": "Gone"}], {"G": ["B"]}))
        self.assertEqual(rv.problems[-4:], [
            "Show List: B has no cells on the grid",
            "Show List: Show Group: G has no cells on the grid",
            "Show List: show:Gone has no cells on the grid",
            "C is on the grid but not in the Show List"])

    def test_entries_count_episodes_left_cells_and_members(self):
        state = {"shows": {"A": {"path": "A/1.mkv", "key": [1, 1]}}}
        rv = run(draft([{"length": "24h", "repeat": 1, "slots": [
            {"rule": A}, {"weekdays": {"mon": {"group": "G"}, "tue": {"group": "G"}}}]}],
            [A, {"group": "G"}], {"G": ["B", "C"]}), state)
        a, g = rv.entries
        self.assertEqual((a.key, a.left, a.cells, a.members), ("show:A", 2, 7, [("A", 2)]))
        self.assertEqual((g.key, g.left, g.cells, g.members),
                         ("group:G", 3, 2, [("B", 1), ("C", 2)]))


class PreviewTest(unittest.TestCase):
    RAW = draft([{"length": "24h", "repeat": 1, "slots": [
        {"rule": C}, {"weekdays": {"mon": A, "tue": A, "wed": B}}, {"weekdays": {}}]}],
        [A, B])

    def test_rows_changed_cells_and_cells_after(self):
        pv = review.preview(self.RAW, run(self.RAW))
        self.assertEqual([(n, m) for n, m, _, _ in pv.rows], [(1, 2), (1, 3)])
        self.assertEqual(pv.rows[0][2][:4], ["show:A", "show:A", "show:B", ""])
        # in turn, day by day: Mon Slot 2, Mon Slot 3, Tue Slot 2, ...
        self.assertEqual(pv.rows[0][3], ["show:A"] * 7)
        self.assertEqual(pv.rows[1][3], ["show:B"] * 7)
        self.assertEqual(pv.changed, 5 + 7)  # Wed..Sun, and all of Slot 3
        self.assertEqual(pv.cells, [7, 7])

    def test_refused_with_no_entries(self):
        raw = draft(self.RAW["day_schedule"])
        with self.assertRaises(distributor.Refused):
            review.preview(raw, run(raw))


if __name__ == "__main__":
    unittest.main()
