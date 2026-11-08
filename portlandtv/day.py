"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

from portlandtv import slots


def build(cfg, shows, state, prober, card, movies=()):
    """-> (ffplayout program, the items picked per Block, the advanced state, problems).

    A Slot naming something missing is dropped and flagged; once a Slot overruns its
    Block, it and the Slots after it are dropped. Dropped Slots advance nothing.
    """
    program, picks, problems = [], [], []
    for b, block in enumerate(cfg["day_schedule"], 1):
        items, lengths = [], []
        for s, rule in enumerate(block["slots"], 1):
            trial = copy.deepcopy(state)
            try:
                path = slots.resolve(rule, shows, movies, cfg["show_groups"], trial)
            except slots.Missing as e:
                problems.append(f"Block {b} Slot {s}: {e}")
                continue
            length = prober.duration(path)
            if sum(lengths) + length > block["length"]:
                break
            items.append(path)
            lengths.append(length)
            state = trial
        picks.append(items)
        if not items:
            airing = [{"in": 0, "out": block["length"], "duration": block["length"],
                       "source": card}]
        else:
            brk = (block["length"] - sum(lengths)) / len(items)
            airing = []
            for path, length in zip(items, lengths):
                airing.append({"in": 0, "out": length, "duration": length, "source": path})
                airing.append({"in": 0, "out": brk, "duration": brk, "source": card})
        program += airing * block["repeat"]
    return program, picks, state, problems
