"""Seam 2: the Show List panel and Distribute, over HTTP."""
import json
import os
import unittest

from tests.harness import Channel
from tests.web_harness import Browser

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def eps(show, n):
    return [f"{show}/{show} - S01E{e:02}.mkv" for e in range(1, n + 1)]


# A has 8 episodes, B 2, C 1, D 3; every episode 600 s (the fake prober's default)
FILES = eps("A", 8) + eps("B", 2) + eps("C", 1) + eps("D", 3)
CONFIG = {
    "show_list": [{"show": "A"}, {"show": "B"}, {"show": "C"}],
    "day_schedule": [{"length": "24h", "repeat": 1, "slots": [
        {"rule": {"show": "D"}},
        {"weekdays": {"mon": {"show": "A"}, "tue": {"show": "A"}, "wed": {"show": "B"}}},
        {"weekdays": {}}]}]}


class ShowListTest(unittest.TestCase):
    def open(self, config=CONFIG, state=None):
        s = Channel(config, FILES)
        self.addCleanup(s.close)
        if state:
            with open(os.path.join(s.root, "state.json"), "w") as f:
                json.dump(state, f)
        b = Browser(s)
        b.get()
        return b

    def entries(self, b):
        f = b.fields()
        return [f[f"sl{k}"] for k in range(len(f)) if f"sl{k}" in f]

    def test_show_list_is_an_ordered_yaml_key_kept_on_save(self):
        b = self.open()
        self.assertEqual(self.entries(b), ["show:A", "show:B", "show:C"])
        b.submit()
        self.assertEqual(b.yaml()["show_list"], CONFIG["show_list"])

    def test_show_list_entries_must_be_shows_or_show_groups(self):
        s = Channel({**CONFIG, "show_list": [{"movie": "random"}]}, FILES)
        self.addCleanup(s.close)
        s.tick()
        self.assertIn("Show List", s.service.error)

    def test_panel_shows_episodes_left_cells_and_weeks_left(self):
        # A aired up to episode 2, so 6 left over 2 cells: 3.0 weeks
        b = self.open(state={"shows": {"A": {"path": os.path.join(
            "SHOWS", "A", "A - S01E02.mkv"), "key": [1, 2]}}})
        self.assertIn('<tr class="entry"><td class="swatch" style="background:#cfe3ff"></td>'
                      "<td>A</td><td>6</td><td>2</td><td>3.0</td>", b.html)
        self.assertIn("<td>B</td><td>2</td><td>1</td><td>2.0</td>", b.html)
        self.assertIn("<td>C</td><td>1</td><td>0</td><td>not scheduled</td>", b.html)

    def test_entries_reorder_remove_and_add(self):
        b = self.open()
        b.submit("down-entry:0")
        self.assertEqual(self.entries(b), ["show:B", "show:A", "show:C"])
        b.submit("up-entry:2")
        self.assertEqual(self.entries(b), ["show:B", "show:C", "show:A"])
        b.submit("del-entry:1")
        self.assertEqual(self.entries(b), ["show:B", "show:A"])
        # the add checklist offers only shows and Show Groups not yet in the list
        offered = b.html.split('class="pick"')[1].split("</fieldset>")[0]
        self.assertIn('name="sl.add" value="show:C"', offered)
        self.assertNotIn('value="show:A"', offered)
        self.assertNotIn('value="movie:random"', offered)
        b.submit("add-entry", {"sl.add": ["show:D", "show:C"]})  # several ticked at once
        self.assertEqual(self.entries(b), ["show:B", "show:A", "show:D", "show:C"])
        b.submit()
        self.assertEqual(b.yaml()["show_list"],
                         [{"show": "B"}, {"show": "A"}, {"show": "D"}, {"show": "C"}])

    def test_removing_an_entry_leaves_the_grid_untouched(self):
        b = self.open()
        before = b.yaml()["day_schedule"]
        b.submit("del-entry:0")
        b.submit()
        self.assertEqual(b.yaml()["day_schedule"], before)
        self.assertEqual(b.yaml()["show_list"], [{"show": "B"}, {"show": "C"}])

    def test_cells_coloured_by_entry_and_off_list_rules_grey(self):
        b = self.open()
        self.assertIn('<td class="cell" data-rule="show:A" style="background:#cfe3ff">', b.html)
        self.assertIn('<td class="cell" data-rule="show:B" style="background:#d6f5d6">', b.html)
        self.assertIn('<td colspan="7" class="cell" data-rule="show:D" style="background:#e6e6e6">',
                      b.html)
        self.assertIn('<option value="show:D" selected>D (not in list)</option>', b.html)
        self.assertIn('<option value="show:A" selected>A</option>', b.html)


class BalanceTest(unittest.TestCase):
    open = ShowListTest.open
    entries = ShowListTest.entries

    def test_columns_are_entries_as_tall_as_their_episodes_left(self):
        html = self.open().html.split('id="balance"')[1]
        self.assertIn('data-show="A"\n                style="height:100.0%', html)
        self.assertIn('data-show="B"\n                style="height:25.0%', html)
        self.assertIn("C · 1", html)

    def test_a_dragged_show_reaches_the_saved_yaml(self):
        b = self.open()
        b.submit("regroup", {"bal.show": "C", "bal.from": "2", "bal.to": "1"})  # C onto B
        self.assertEqual(self.entries(b), ["show:A", "group:Group 1"])
        b.submit()
        self.assertEqual(b.yaml()["show_groups"], {"Group 1": ["B", "C"]})

    def test_auto_sort_packs_single_shows_up_to_the_longest_entry(self):
        b = self.open({**CONFIG, "show_list": [{"show": s} for s in "ABCD"]})
        b.submit("auto-sort")  # A 8 alone; D 3 + B 2 + C 1 = 6 fit under it
        self.assertEqual(self.entries(b), ["show:A", "group:Group 1"])
        b.submit()
        self.assertEqual(b.yaml()["show_groups"], {"Group 1": ["D", "B", "C"]})


class DistributeTest(unittest.TestCase):
    open = ShowListTest.open

    def cells(self, b, slot):
        f = b.fields()
        return [f[f"{slot}.{d}"] for d in DAYS]

    def test_preview_shows_both_grids_changed_cells_and_weeks_left(self):
        b = self.open()
        before = b.yaml()
        b.submit("distribute")
        dialog = b.html.split('id="distribute"')[1]
        self.assertIn("<h3>Now</h3>", dialog)
        self.assertIn("<h3>After distributing</h3>", dialog)
        # Slot 2 Wed..Sun and all of Slot 3 change
        self.assertEqual(dialog.count('class="changed"'), 12)
        self.assertIn('value="replace">Replace 12 cells</button>', dialog)
        self.assertIn('value="cancel">Cancel</button>', dialog)
        # weeks left, equal shares of 14 cells: A 8 eps over 2 -> 5 cells, B 2 over 1 -> 5,
        # C 1 over 0 -> 4
        self.assertIn("<td>A</td><td>4.0</td><td>1.6</td>", dialog)
        self.assertIn("<td>B</td><td>2.0</td><td>0.4</td>", dialog)
        self.assertIn("<td>C</td><td>not scheduled</td><td>0.2</td>", dialog)
        # nothing changes until the confirm
        self.assertEqual(b.yaml(), before)
        self.assertEqual(self.cells(b, "b0.s1")[:3], ["show:A", "show:A", "show:B"])

    def test_confirm_writes_the_worked_example(self):
        b = self.open()
        b.submit("distribute")
        b.submit("replace")
        self.assertNotIn('id="distribute"', b.html)
        a, bb, c = {"show": "A"}, {"show": "B"}, {"show": "C"}
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"], [
            {"rule": {"show": "D"}},
            # in turn, day by day: Mon Slot 2, Mon Slot 3, Tue Slot 2, ...
            {"weekdays": dict(zip(DAYS, [a, c, bb, a, c, bb, a]))},
            {"weekdays": dict(zip(DAYS, [bb, a, c, bb, a, c, bb]))}])
        # A now has 5 cells a week, however many episodes it has left (saving also builds
        # today, so episodes left vary)
        self.assertRegex(b.html, r"<td>A</td><td>\d+</td><td>5</td>")

    def test_cancel_leaves_everything_as_it_was(self):
        b = self.open()
        before = b.yaml()
        b.submit("distribute")
        b.submit("cancel")
        self.assertNotIn('id="distribute"', b.html)
        self.assertEqual(self.cells(b, "b0.s1")[:3], ["show:A", "show:A", "show:B"])
        self.assertEqual(self.cells(b, "b0.s2"), [""] * 7)
        self.assertEqual(b.yaml(), before)

    def test_refused_with_more_entries_than_cells(self):
        groups = {f"G{n}": ["D"] for n in range(5)}
        b = self.open({"show_groups": groups,
                       "show_list": [{"show": "A"}, {"show": "B"}, {"show": "C"}]
                       + [{"group": g} for g in groups],
                       "day_schedule": [{"length": "24h", "repeat": 1, "slots": [
                           {"weekdays": {"mon": {"show": "A"}}}]}]})
        before = b.yaml()
        b.submit("distribute")
        self.assertNotIn('id="distribute"', b.html)
        self.assertIn("Distribute refused: 8 Show List entries for 7 distributed cells",
                      b.html)
        b.submit("replace")
        self.assertEqual(b.yaml(), before)


if __name__ == "__main__":
    unittest.main()
