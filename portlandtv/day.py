"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

from portlandtv import deck

MIN_STILL = 1.0  # a Break remainder shorter than this is dropped


def next_episode(shows, state, name):
    """The episode after the show's last-aired file; advances `state` in place."""
    eps = shows[name]
    last = state["shows"].get(name, {}).get("path")
    path = eps[(eps.index(last) + 1) % len(eps)] if last in eps else eps[0]
    state["shows"][name] = {"path": path}
    return path


def fill_break(length, filler_deck, clips, card):
    """Whole clips from the deck while they fit, then a still for the remainder."""
    out = []
    while (path := deck.peek(filler_deck, list(clips))) and clips[path] <= length:
        deck.take(filler_deck)
        out.append({"in": 0, "out": clips[path], "duration": clips[path], "source": path})
        length -= clips[path]
    if length >= MIN_STILL:
        out.append({"in": 0, "out": length, "duration": length, "source": card})
    return out


def build(cfg, shows, state, prober, card, filler=()):
    """-> (ffplayout program, the item picked for each Slot, the advanced state,
    the filler clips longer than every Break that day)."""
    state = copy.deepcopy(state)
    blocks = []
    for block in cfg["day_schedule"]:
        items = [next_episode(shows, state, rule["show"]) for rule in block["slots"]]
        lengths = [prober.duration(p) for p in items]
        blocks.append((block, items, lengths, (block["length"] - sum(lengths)) / len(items)))
    longest = max(b[3] for b in blocks)
    durations = {p: prober.duration(p) for p in filler}
    clips = {p: d for p, d in durations.items() if 0 < d <= longest}
    never_fits = sorted(p for p, d in durations.items() if d > longest)
    filler_deck = state.setdefault("filler", {})
    program = []
    for block, items, lengths, brk in blocks:
        airing = []
        for path, length in zip(items, lengths):
            airing.append({"in": 0, "out": length, "duration": length, "source": path})
            airing += fill_break(brk, filler_deck, clips, card)
        program += airing * block["repeat"]
    return program, [b[1] for b in blocks], state, never_fits
