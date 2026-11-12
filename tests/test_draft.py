"""The Draft's edits, on the raw YAML dict the web UI posts."""
import copy
import unittest

from portlandtv import draft, distributor

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
A, B, C, D = ({"show": s} for s in "ABCD")


def raw(**keys):
    return {"libraries": [], "day_schedule": [], "show_groups": {}, "show_list": [], **keys}


def entries(r):
    return [e.get("show") or "group:" + e["group"] for e in r["show_list"]]


class EditTest(unittest.TestCase):
    def test_moves_past_either_end_do_nothing(self):
        r = raw(show_list=[A, B])
        draft.move_entry(r, 0, -1)
        draft.move_entry(r, 1, 1)
        self.assertEqual(r["show_list"], [A, B])
        draft.move_entry(r, 0, 1)
        self.assertEqual(r["show_list"], [B, A])

    def test_added_entries_skip_ones_already_listed(self):
        r = raw(show_list=[A])
        draft.add_entries(r, [B, A, None, B])
        self.assertEqual(r["show_list"], [A, B])

    def test_switch_mode_copies_the_rule_out_and_keeps_monday_back(self):
        r = raw(day_schedule=[{"slots": [{"rule": A}]}])
        draft.switch_mode(r, 0, 0)
        self.assertEqual(r["day_schedule"][0]["slots"][0], {"weekdays": dict.fromkeys(DAYS, A)})
        r["day_schedule"][0]["slots"][0]["weekdays"]["mon"] = B
        draft.switch_mode(r, 0, 0)
        self.assertEqual(r["day_schedule"][0]["slots"][0], {"rule": B})

    def test_groups_and_members_ignore_empty_and_taken_names(self):
        r = raw(show_groups={"G": ["A"]})
        for name in ("", "  ", "G"):
            draft.add_group(r, name)
        draft.add_member(r, "G", "A")
        draft.add_member(r, "G", "")
        self.assertEqual(r["show_groups"], {"G": ["A"]})


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.r = raw(show_groups={"G": ["A"], "H": ["B"]}, show_list=[{"group": "G"}],
                     day_schedule=[{"slots": [{"rule": {"group": "G"}},
                                              {"weekdays": {"mon": {"group": "G"}}}]}])

    def test_renames_every_use_and_keeps_the_group_order(self):
        draft.rename_group(self.r, "G", " Kids ")
        self.assertEqual(list(self.r["show_groups"]), ["Kids", "H"])
        self.assertEqual(self.r["show_list"], [{"group": "Kids"}])
        self.assertEqual(self.r["day_schedule"][0]["slots"],
                         [{"rule": {"group": "Kids"}}, {"weekdays": {"mon": {"group": "Kids"}}}])

    def test_an_empty_or_taken_name_keeps_the_old_one(self):
        before = copy.deepcopy(self.r)
        for name in ("", " ", "H", "G"):
            draft.rename_group(self.r, "G", name)
        self.assertEqual(self.r, before)


class RegroupTest(unittest.TestCase):
    def test_dragging_shows_together_and_apart(self):
        r = raw(show_list=[A, B, C])
        draft.regroup(r, "C", 2, 1)  # C onto B: a new group in B's place
        self.assertEqual(entries(r), ["A", "group:Group 1"])
        draft.regroup(r, "A", 0, 1)  # A onto the group
        self.assertEqual(entries(r), ["group:Group 1"])
        draft.regroup(r, "B", 0, None)  # B out, just after its group
        self.assertEqual(entries(r), ["group:Group 1", "B"])
        self.assertEqual(r["show_groups"], {"Group 1": ["C", "A"]})
        # the last show out of a Show Group takes the group off the Show List
        for show in ("C", "A"):
            draft.regroup(r, show, 0, None)
        self.assertEqual(entries(r), ["A", "C", "B"])
        self.assertEqual(r["show_groups"], {})

    def test_a_single_show_dragged_out_or_onto_itself_stays(self):
        r = raw(show_list=[A, B])
        draft.regroup(r, "A", 0, None)
        draft.regroup(r, "A", 0, 0)
        self.assertEqual(r["show_list"], [A, B])


class AutoSortTest(unittest.TestCase):
    def test_packs_single_shows_up_to_the_longest_entry(self):
        r = raw(show_list=[A, B, C, D])
        draft.auto_sort(r, [8, 2, 1, 3])  # A 8 alone; D 3 + B 2 + C 1 = 6 fit under it
        self.assertEqual(entries(r), ["A", "group:Group 1"])
        self.assertEqual(r["show_groups"], {"Group 1": ["D", "B", "C"]})

    def test_tops_up_existing_show_groups_first(self):
        r = raw(show_groups={"G": ["D"]}, show_list=[A, B, {"group": "G"}, C])
        draft.auto_sort(r, [8, 2, 3, 1])  # G has D's 3; B 2 and C 1 fit in under A's 8
        self.assertEqual(entries(r), ["A", "group:G"])
        self.assertEqual(r["show_groups"], {"G": ["D", "B", "C"]})


class DistributeTest(unittest.TestCase):
    def schedule(self, show_list):
        return raw(show_list=show_list, day_schedule=[{"length": "24h", "repeat": 1, "slots": [
            {"rule": D}, {"weekdays": {"mon": A}}, {"weekdays": {}}]}])

    def test_follows_list_order_day_by_day_and_leaves_fixed_slots(self):
        r = self.schedule([C, A, B])
        draft.distribute(r)
        slots = r["day_schedule"][0]["slots"]
        self.assertEqual(slots[0], {"rule": D})
        self.assertEqual(slots[1], {"weekdays": dict(zip(DAYS, [C, B, A, C, B, A, C]))})
        self.assertEqual(slots[2], {"weekdays": dict(zip(DAYS, [A, C, B, A, C, B, A]))})
        self.assertEqual([(n, m) for n, m, _ in draft.distributed_slots(r)], [(1, 2), (1, 3)])

    def test_refused_leaves_the_draft_as_it_was(self):
        r = self.schedule([{"show": str(n)} for n in range(15)])
        before = copy.deepcopy(r)
        with self.assertRaises(distributor.Refused):
            draft.distribute(r)
        self.assertEqual(r, before)


if __name__ == "__main__":
    unittest.main()
