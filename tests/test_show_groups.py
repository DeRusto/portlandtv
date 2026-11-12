"""Seam 2: Show Groups are made and edited on the page, like every other YAML key."""
import unittest

from tests.harness import Channel, utc
from tests.web_harness import Browser


def eps(show, n):
    return [f"{show}/{show} - S01E{e:02}.mkv" for e in range(1, n + 1)]


FILES = eps("A", 2) + eps("B", 2) + eps("C", 2)
CONFIG = {
    "show_groups": {"G": ["A", "B"]},
    "show_list": [{"group": "G"}],
    "day_schedule": [{"length": "24h", "repeat": 1, "slots": [
        {"rule": {"group": "G"}},
        {"weekdays": {"mon": {"group": "G"}, "tue": {"show": "C"}}}]}]}


class ShowGroupsTest(unittest.TestCase):
    def open(self, config=CONFIG):
        s = Channel(config, FILES)
        self.addCleanup(s.close)
        b = Browser(s)
        b.get()
        return b

    def members(self, b, i=0):
        f = b.fields()
        return [f[f"g{i}.m{j}"] for j in range(len(f)) if f"g{i}.m{j}" in f]

    def test_a_group_is_made_filled_and_saved(self):
        b = self.open()
        b.submit("add-group", {"g.new": "Cartoons"})
        self.assertEqual(b.fields()["g1.name"], "Cartoons")
        # the member dropdown offers only scanned shows not yet in the group
        b.submit("add-member:1", {"g1.add": "C"})
        b.submit("add-member:1", {"g1.add": "A"})
        self.assertEqual(self.members(b, 1), ["C", "A"])
        self.assertNotIn('value="C"', b.html.split('name="g1.add"')[1].split("</select>")[0])
        # a new group is offered straight away, in Slot rules and the Show List
        self.assertIn('name="sl.add" value="group:Cartoons"', b.html)
        b.submit()
        self.assertEqual(b.yaml()["show_groups"], {"G": ["A", "B"], "Cartoons": ["C", "A"]})

    def test_members_reorder_and_remove(self):
        b = self.open()
        b.submit("down-member:0:0")
        self.assertEqual(self.members(b), ["B", "A"])
        b.submit("up-member:0:1")
        self.assertEqual(self.members(b), ["A", "B"])
        b.submit("del-member:0:0")
        b.submit()
        self.assertEqual(b.yaml()["show_groups"], {"G": ["B"]})

    def test_renaming_a_group_renames_every_use_of_it(self):
        b = self.open()
        b.submit(changes={"g0.name": "Kids"})
        raw = b.yaml()
        self.assertEqual(raw["show_groups"], {"Kids": ["A", "B"]})
        self.assertEqual(raw["show_list"], [{"group": "Kids"}])
        slots = raw["day_schedule"][0]["slots"]
        self.assertEqual(slots[0], {"rule": {"group": "Kids"}})
        self.assertEqual(slots[1]["weekdays"]["mon"], {"group": "Kids"})

    def test_a_renamed_group_carries_on_where_it_had_got_to(self):
        s = Channel({"show_groups": {"G": ["A", "B", "C"]}, "show_list": [],
                     "day_schedule": [{"length": "24h", "repeat": 1,
                                       "slots": [{"rule": {"group": "G"}}]}]},
                    eps("A", 1) + eps("B", 1) + eps("C", 3))
        self.addCleanup(s.close)
        for d in (9, 10, 11):  # one item a day: A1, B1, C1
            s.tick(utc(2026, 11, d, 12, 0))
        s.tick(utc(2026, 11, 12, 5, 30))  # tomorrow (the 12th) is generated too
        b = Browser(s)
        b.get()
        b.submit(changes={"g0.name": "Kids"})
        first = s.playlist("2026-11-12")["program"][0]["source"]
        self.assertEqual(s.rel(first), "C/C - S01E02.mkv")
        self.assertEqual(s.read_json("state.json")["groups"], {"Kids": {"show": "C"}})

    def test_a_deleted_group_still_in_use_is_a_problem_not_a_crash(self):
        b = self.open()
        b.submit("del-group:0")
        b.submit()
        self.assertEqual(b.yaml().get("show_groups") or {}, {})
        b.channel.tick()
        b.get()
        self.assertIn("Show Group &#39;G&#39; not defined", b.html.split('id="problems"')[1])

    def test_a_group_with_no_shows_is_not_saved(self):
        b = self.open()
        b.submit("add-group", {"g.new": "Empty"})
        r = b.submit()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Show Group Empty has no shows", b.html)
        self.assertEqual(b.yaml()["show_groups"], {"G": ["A", "B"]})


if __name__ == "__main__":
    unittest.main()
