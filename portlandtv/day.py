"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy


def next_episode(shows, state, name):
    """The episode after the show's last-aired file; advances `state` in place."""
    eps = shows[name]
    last = state["shows"].get(name, {}).get("path")
    path = eps[(eps.index(last) + 1) % len(eps)] if last in eps else eps[0]
    state["shows"][name] = {"path": path}
    return path


def build(cfg, shows, state, prober, card):
    """-> (ffplayout program, the item picked for each Slot, the advanced state)."""
    state = copy.deepcopy(state)
    program, picks = [], []
    for block in cfg["day_schedule"]:
        items = [next_episode(shows, state, rule["show"]) for rule in block["slots"]]
        picks.append(items)
        lengths = [prober.duration(p) for p in items]
        brk = (block["length"] - sum(lengths)) / len(items)
        airing = []
        for path, length in zip(items, lengths):
            airing.append({"in": 0, "out": length, "duration": length, "source": path})
            airing.append({"in": 0, "out": brk, "duration": brk, "source": card})
        program += airing * block["repeat"]
    return program, picks, state
