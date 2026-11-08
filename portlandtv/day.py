"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

from portlandtv.library import episode_key


def next_episode(shows, state, name):
    """The episode after the show's last-aired file, or if that file is gone, the first
    that sorts after its (season, episode) key; advances `state` in place."""
    eps = shows[name]
    last = state["shows"].get(name, {})
    if last.get("path") in eps:
        i = eps.index(last["path"]) + 1
    elif "key" in last:
        i = next((n for n, p in enumerate(eps) if episode_key(p) > tuple(last["key"])), 0)
    else:
        i = 0
    path = eps[i % len(eps)]
    state["shows"][name] = {"path": path, "key": list(episode_key(path))}
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
