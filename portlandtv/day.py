"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

AHEAD = 3  # a card names the next item and the two after it


def next_episode(shows, state, name):
    """The episode after the show's last-aired file; advances `state` in place."""
    eps = shows[name]
    last = state["shows"].get(name, {}).get("path")
    path = eps[(eps.index(last) + 1) % len(eps)] if last in eps else eps[0]
    state["shows"][name] = {"path": path}
    return path


def end_card(n):
    """Name of the card n Breaks from the end of the day (1 = final Break)."""
    return f"end-{n}"


def build(cfg, shows, state, prober, card):
    """-> (ffplayout program, the item picked for each Slot, the advanced state,
    the day's sequence of items).

    card(name, upcoming item paths) -> PNG path. A name is shared by every Repeat
    only when its items stay inside the Airing; cards reaching past it are per
    Airing, and the day's last ones are end_card(n), filled in by the next day.
    """
    state = copy.deepcopy(state)
    picks, airings = [], []
    for b, block in enumerate(cfg["day_schedule"]):
        items = [next_episode(shows, state, rule["show"]) for rule in block["slots"]]
        picks.append(items)
        lengths = [prober.duration(p) for p in items]
        brk = (block["length"] - sum(lengths)) / len(items)
        airings += [(b, r, items, lengths, brk) for r in range(block["repeat"])]
    sequence = [p for a in airings for p in a[2]]
    program, k = [], 0
    for b, r, items, lengths, brk in airings:
        end = k + len(items)
        for j, (path, length) in enumerate(zip(items, lengths)):
            if k + AHEAD >= len(sequence):
                name = end_card(len(sequence) - k)
            elif k + AHEAD >= end:
                name = f"b{b}-a{r}-{j}"
            else:
                name = f"b{b}-{j}"
            program.append({"in": 0, "out": length, "duration": length, "source": path})
            program.append({"in": 0, "out": brk, "duration": brk,
                            "source": card(name, sequence[k + 1:k + 1 + AHEAD])})
            k += 1
    return program, picks, state, sequence
