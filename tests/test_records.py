"""Day Records and state.json, on a temp folder."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date

from portlandtv import day, records

DAY1, DAY2 = date(2026, 11, 9), date(2026, 11, 10)
S0, S1, S2 = ({"shows": {"A": {"path": f"A/{n}.mkv", "key": [1, n]}}} for n in range(3))


def built(state, sequence=("a", "b", "c", "d")):
    return day.Day(program=[], block_items=[list(sequence)], state=state, never_fits=["long"],
                   problems=["Block 1 Slot 2: gone"], sequence=list(sequence),
                   slot_fills=[[[{"show": "A"}, "a"]]])


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.records = records.Records(self.root)

    def write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def test_a_fresh_install_starts_empty(self):
        self.assertEqual(self.records.state(), {"shows": {}})
        self.assertEqual(self.records.state_before(DAY1), {"shows": {}})
        self.assertIsNone(self.records.get(DAY1))

    def test_commit_writes_the_record_then_the_state(self):
        self.records.commit(DAY1, S0, built(S1))
        r = self.records.get(DAY1)
        self.assertEqual((r.state_before, r.state_after, r.slots, r.problems, r.never_fits),
                         (S0, S1, [["a", "b", "c", "d"]], ["Block 1 Slot 2: gone"], ["long"]))
        self.assertEqual(r.tail, ["b", "c", "d"])  # the last day.AHEAD items
        self.assertEqual(r.picked, [[[{"show": "A"}, "a"]]])
        self.assertEqual(self.records.state(), S1)
        self.assertEqual(self.records.state_before(DAY2), S1)

    def test_the_day_befores_record_wins_over_a_stale_state(self):
        self.records.commit(DAY1, S0, built(S1))
        self.write(self.records.state_path, S0)  # the crash came before state.json was written
        self.assertEqual(self.records.state_before(DAY2), S1)

    def test_with_no_record_the_day_before_the_state_is_used(self):
        self.write(self.records.state_path, S2)
        self.assertEqual(self.records.state_before(DAY2), S2)

    def test_unbuild_restores_the_state_and_forgets_the_day(self):
        self.records.commit(DAY1, S0, built(S1))
        self.records.commit(DAY2, S1, built(S2))
        self.records.unbuild(DAY2)
        self.assertIsNone(self.records.get(DAY2))
        self.assertEqual(self.records.state(), S1)
        self.records.unbuild(DAY2)  # nothing left to forget
        self.assertEqual(self.records.state(), S1)

    def test_an_older_record_without_newer_fields_still_loads(self):
        self.write(self.records.path(DAY1), {"slots": [], "problems": [], "state_before": S0})
        r = self.records.get(DAY1)
        self.assertEqual((r.state_after, r.tail, r.picked, r.never_fits), (None, None, [], []))
        self.write(self.records.state_path, S2)
        self.assertEqual(self.records.state_before(DAY2), S2)


if __name__ == "__main__":
    unittest.main()
