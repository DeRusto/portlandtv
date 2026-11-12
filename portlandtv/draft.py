"""Draft: every edit the web UI makes to the raw YAML before it is saved.

Each function changes `raw` (config.read_raw's shape) in place. An edit that can't
apply (a move past either end, an empty or taken name, a show already there) does
nothing; config.save refuses whatever is left invalid.
"""
from portlandtv import config, distributor


def new_block():
    return {"length": "1h", "repeat": 1, "slots": [fixed_slot(None)]}


def fixed_slot(rule):
    """A raw fixed Slot airing `rule` every day; no rule is an empty Slot."""
    return {"rule": rule} if rule else {}


def distributed_slot(rules):
    """A raw distributed Slot from its rules Mon..Sun; only non-empty days are stored."""
    return {"weekdays": {d: dict(r) for d, r in zip(config.WEEKDAYS, rules) if r}}


def _move(items, j, step):
    k = j + step
    if 0 <= k < len(items):
        items[j], items[k] = items[k], items[j]


def add_block(raw):
    raw["day_schedule"].append(new_block())


def delete_block(raw, b):
    del raw["day_schedule"][b]


def add_slot(raw, b, distributed=False):
    """A new fixed Slot is empty, and so is a new distributed one on every weekday."""
    raw["day_schedule"][b]["slots"].append(distributed_slot([]) if distributed else fixed_slot(None))


def switch_mode(raw, b, s):
    """Fixed -> distributed with the rule on all seven days; distributed -> fixed
    keeping Monday's rule (the page confirms first)."""
    slots = raw["day_schedule"][b]["slots"]
    rules = config.slot_rules(slots[s])
    slots[s] = distributed_slot(rules) if config.is_fixed(slots[s]) else fixed_slot(rules[0])


def delete_slot(raw, b, s):
    del raw["day_schedule"][b]["slots"][s]


def move_slot(raw, b, s, step):
    _move(raw["day_schedule"][b]["slots"], s, step)


def add_library(raw):
    raw["libraries"].append({"path": "", "kind": "shows"})


def delete_library(raw, i):
    del raw["libraries"][i]


def add_entries(raw, rules):
    """Append each Show List entry not already in the list."""
    entries = raw["show_list"]
    for rule in rules:
        if rule and rule not in entries:
            entries.append(rule)


def delete_entry(raw, i):
    """The grid is left as it is."""
    del raw["show_list"][i]


def move_entry(raw, i, step):
    _move(raw["show_list"], i, step)


def add_group(raw, name):
    name = name.strip()
    if name and name not in raw["show_groups"]:
        raw["show_groups"][name] = []


def delete_group(raw, name):
    """Slots and Show List entries naming it are flagged by the next build, not changed."""
    del raw["show_groups"][name]


def add_member(raw, group, show):
    members = raw["show_groups"][group]
    if show and show not in members:
        members.append(show)


def delete_member(raw, group, j):
    del raw["show_groups"][group][j]


def move_member(raw, group, j, step):
    _move(raw["show_groups"][group], j, step)


def rename_group(raw, old, new):
    """Rename Show Group `old` in place, pointing every Slot rule and Show List entry
    naming it at `new`. An empty or taken name keeps the old one. True if renamed."""
    new = new.strip()
    groups = raw["show_groups"]
    if not new or new in groups or old not in groups:
        return False
    raw["show_groups"] = {new if k == old else k: v for k, v in groups.items()}
    rules = list(raw["show_list"])
    for b in raw["day_schedule"]:
        for s in b.get("slots") or []:
            rules += [s.get("rule")] + list((s.get("weekdays") or {}).values())
    for r in rules:
        if isinstance(r, dict) and r.get("group") == old:
            r["group"] = new
    return True


def _new_group(groups):
    return next(f"Group {n}" for n in range(1, len(groups) + 2) if f"Group {n}" not in groups)


def regroup(raw, show, src, dst):
    """Move `show` out of Show List entry `src` into entry `dst`, or into its own entry when
    `dst` is None. Dropping it on a show makes a new Show Group of the two in its place; a
    Show Group left with no shows leaves the Show List (Slots naming it are flagged)."""
    entries, groups = raw["show_list"], raw["show_groups"]
    source = entries[src]
    if dst == src or (dst is None and "show" in source):
        return
    gone = True  # whether entry `src` leaves the Show List
    if "group" in source:
        members = groups[source["group"]]
        members.remove(show)
        gone = not members
        if gone:
            del groups[source["group"]]
    # by position, never by value: a hand-edited Show List may hold an entry twice
    if dst is None:
        entries.insert(src + 1, {"show": show})
    elif "group" in entries[dst]:
        if show not in groups[entries[dst]["group"]]:
            groups[entries[dst]["group"]].append(show)
    else:
        name = _new_group(groups)
        groups[name] = [entries[dst]["show"], show]
        entries[dst] = {"group": name}
    if gone:
        del entries[src]


def auto_sort(raw, left):
    """Pack the Show List's single shows (episodes left in `left`, per entry) into Show
    Groups lasting no longer than its longest entry: largest first, each into the first
    existing or new group it fits, else a new one. A new group of one stays a single show."""
    entries, groups = raw["show_list"], raw["show_groups"]
    target = max(left, default=0)
    # [episodes, entry index, single shows' entry indexes]: Show List groups first
    bins = [[left[i], i, []] for i, e in enumerate(entries) if "group" in e]
    singles = sorted((i for i, e in enumerate(entries) if "show" in e), key=lambda i: -left[i])
    for i in singles:
        fit = next((b for b in bins if b[0] + left[i] <= target), None)
        if fit:
            fit[0] += left[i]
            fit[2].append(i)
        else:
            bins.append([left[i], i, []])
    gone = set()
    for _, at, added in bins:
        if not added:
            continue
        if "show" in entries[at]:  # a new group, in its largest show's place
            name = _new_group(groups)
            groups[name] = [entries[at]["show"]]
            entries[at] = {"group": name}
        groups[entries[at]["group"]] += [entries[i]["show"] for i in added]
        gone.update(added)
    entries[:] = [e for i, e in enumerate(entries) if i not in gone]


def distributed_slots(raw):
    """[(Block n, Slot m, Slot)] of the distributed Slots, in Distribute's cell order."""
    return [(n, m, s) for n, b in enumerate(raw["day_schedule"], 1)
            for m, s in enumerate(b.get("slots") or [], 1) if not config.is_fixed(s)]


def distribute(raw):
    """Overwrite every distributed cell with the Show List's shares; raises
    distributor.Refused, leaving the Draft as it was."""
    cells = distributed_slots(raw)
    for (_, _, s), rules in zip(cells, distributor.distribute(raw["show_list"], len(cells))):
        s.update(distributed_slot(rules))
