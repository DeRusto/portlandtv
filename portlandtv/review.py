"""Review: what the web UI reports about a Draft, as numbers and rules for the page to show."""
import collections
import statistics
from typing import NamedTuple

from portlandtv import config, distributor, draft, slots


class BlockReview(NamedTuple):
    length: object  # seconds, None when the length or repeat doesn't parse
    airs: list  # each Airing's start, seconds from the day's start
    slots: list  # per Slot, (fixed, its 7 rules Mon..Sun, {} for an empty day)
    typical: list  # per weekday, the Slots' median candidate lengths summed
    most: list  # per weekday, the Slots' longest candidate lengths summed


class EntryReview(NamedTuple):
    rule: dict  # the Show List entry
    key: str  # its rule_key
    left: int  # episodes left; a Show Group sums its members
    cells: int  # cells per week naming it, on any Slot
    members: list  # [(show, episodes left)], one for a show


class Review(NamedTuple):
    blocks: list  # a BlockReview per Block
    assigned: int  # seconds of the day the Blocks fill
    entries: list  # an EntryReview per Show List entry
    cells: collections.Counter  # rule_key -> cells per week
    problems: list  # what's wrong with the Draft, for the problems panel


class Preview(NamedTuple):
    rows: list  # per distributed Slot, (Block n, Slot m, rule_keys now, rule_keys after)
    changed: int  # cells Distribute would change
    cells: list  # per Show List entry, its cells per week after


def rule_key(rule):
    """{show: X} -> 'show:X', the value of a Slot's rule dropdown."""
    if not rule:
        return ""
    if not isinstance(rule, dict) or len(rule) != 1:
        return f"invalid:{rule}"  # a hand-edited rule; the page still renders so it can be fixed
    (kind, name), = rule.items()
    return f"{kind}:{name}"


def _label(key, shows, groups):
    kind, _, name = key.partition(":")
    if kind == "show" and name in shows:
        return name
    if kind == "group" and name in groups:
        return f"Show Group: {name}"
    return key


def review(raw, shows, movies, duration, state):
    """The Review of Draft `raw` against the scanned `shows` and `movies`.
    duration(path) -> seconds, 0 or None when unknown; `state` is state.json's."""
    groups = raw.get("show_groups") or {}
    keys = [rule_key(e) for e in raw["show_list"]]
    blocks, problems, at = [], [], 0
    cells = collections.Counter()
    off_list = {}  # off-list shows and Show Groups on distributed cells, in order
    for n, b in enumerate(raw["day_schedule"], 1):
        try:
            length, repeat = config.length_repeat(b)
        except config.ConfigError:
            length, repeat = None, 0
        airs = [at + length * r for r in range(repeat)]
        at += (length or 0) * repeat
        typical, most, block_slots = [0] * 7, [0] * 7, []
        for m, s in enumerate(b.get("slots") or [], 1):
            fixed, rules = config.is_fixed(s), config.slot_rules(s)
            block_slots.append((fixed, rules))
            for d, rule in enumerate(rules):
                lengths = [x for x in map(duration, slots.candidates(rule, shows, movies, groups))
                           if x]
                if lengths:
                    typical[d] += statistics.median(lengths)
                    most[d] += max(lengths)
            slot_keys = [rule_key(r) for r in rules]
            cells.update(k for k in slot_keys if k)
            if not fixed:
                off_list.update((k, None) for k in slot_keys
                                if k and k not in keys and not k.startswith("movie:"))
            empty = [day.title() for day, r in zip(config.WEEKDAYS, rules) if not r]
            if empty and fixed:
                problems.append(f"Block {n} Slot {m} is empty every day: skipped")
            elif empty:
                problems.append(f"Block {n} Slot {m} is empty on {', '.join(empty)}:"
                                " skipped those days")
        over = [day.title() for day, t in zip(config.WEEKDAYS, typical) if length and t > length]
        if over:
            problems.append(f"Block {n} content runs past its length on {', '.join(over)}")
        blocks.append(BlockReview(length, airs, block_slots, typical, most))
    problems += [f"Show List: {_label(k, shows, groups)} has no cells on the grid"
                 for k in keys if not cells[k]]
    problems += [f"{_label(k, shows, groups)} is on the grid but not in the Show List"
                 for k in off_list]
    entries = []
    for rule, key in zip(raw["show_list"], keys):
        members = (groups.get(rule["group"], []) if "group" in rule else [rule["show"]]) \
            if isinstance(rule, dict) and rule.keys() & {"group", "show"} else []
        entries.append(EntryReview(
            rule, key, slots.episodes_left(rule, shows, groups, state), cells[key],
            [(m, slots.episodes_left({"show": m}, shows, groups, state)) for m in members]))
    return Review(blocks, at, entries, cells, problems)


def preview(raw, rv):
    """What Distribute would do to Draft `raw` (whose Review is `rv`); raises
    distributor.Refused."""
    distributed = draft.distributed_slots(raw)
    rows, after = [], rv.cells.copy()
    for (n, m, s), rules in zip(distributed, distributor.distribute(raw["show_list"],
                                                                     len(distributed))):
        now = [rule_key(r) for r in config.slot_rules(s)]
        then = [rule_key(r) for r in rules]
        after.subtract(k for k in now if k)
        after.update(then)
        rows.append((n, m, now, then))
    changed = sum(k != o for _, _, now, then in rows for k, o in zip(then, now))
    return Preview(rows, changed, [after[e.key] for e in rv.entries])
