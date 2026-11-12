"""Day Records and state.json: what each generated Broadcast Day aired, and the state
the next one follows on from. Both live beside the YAML, in a format existing installs keep."""
import os
from datetime import timedelta
from typing import NamedTuple

from portlandtv import day, store


class DayRecord(NamedTuple):
    slots: list  # per Block, the items it airs
    problems: list  # dropped and flagged Slots
    state_before: dict  # the state the day was built from
    state_after: object  # the state after it; None in a record that predates it
    never_fits: list  # filler clips longer than every Break that day
    tail: object  # the day's last items, for the previous day's end cards; None if unrecorded
    picked: list  # per Block, per Slot [rule, path or None]; what "rebuild today" keeps


class Records:
    def __init__(self, root):
        self.root = root
        self.state_path = os.path.join(root, "state.json")

    def path(self, date):
        """The Day Record of the Broadcast Day starting on `date`."""
        return os.path.join(self.root, "days", f"{date.isoformat()}.json")

    def state(self):
        """The current state: where each show, Show Group and deck has got to."""
        return store.read_json(self.state_path, {"shows": {}})

    def get(self, date):
        """The Day Record of `date`, or None when that day hasn't been generated."""
        r = store.read_json(self.path(date), None)
        if r is None:
            return None
        return DayRecord(r.get("slots") or [], r.get("problems") or [], r["state_before"],
                         r.get("state_after"), r.get("never_fits") or [], r.get("tail"),
                         r.get("picked") or [])

    def state_before(self, date):
        """The state a build of `date` starts from. The day before's record wins over
        state.json: a crash may have come between writing the two."""
        prev = self.get(date - timedelta(days=1))
        return (prev and prev.state_after) or self.state()

    def commit(self, date, before, built):
        """Record `date`, built (a day.Day) from state `before`, then make its state the
        current one, in that order (see state_before)."""
        store.write_json(self.path(date), {
            "slots": built.block_items, "problems": built.problems,
            "state_before": before, "state_after": built.state,
            "never_fits": built.never_fits, "tail": built.sequence[-day.AHEAD:],
            "picked": built.slot_fills})
        store.write_json(self.state_path, built.state)

    def unbuild(self, date):
        """Forget the generated day `date`, putting the state back to before it."""
        record = self.get(date)
        if record is not None:
            store.write_json(self.state_path, record.state_before)
            os.remove(self.path(date))
