"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

from portlandtv import deck

AHEAD = 3  # a card names the next item and the two after it
MIN_STILL = 1.0  # a Break remainder shorter than this is dropped


def next_episode(shows, state, name):
    """The episode after the show's last-aired file; advances `state` in place."""
    eps = shows[name]
    last = state["shows"].get(name, {}).get("path")
    path = eps[(eps.index(last) + 1) % len(eps)] if last in eps else eps[0]
    state["shows"][name] = {"path": path}
    return path


def fill_break(length, filler_deck, clips):
    """-> (whole clips from the deck while they fit, the remainder left for the card)."""
    out = []
    while (path := deck.peek(filler_deck, list(clips))) and clips[path] <= length:
        deck.take(filler_deck)
        out.append({"in": 0, "out": clips[path], "duration": clips[path], "source": path})
        length -= clips[path]
    return out, length


def end_card(n):
    """Name of the card n Breaks from the end of the day (1 = final Break)."""
    return f"end-{n}"


def build(cfg, shows, state, prober, card, filler=()):
    """-> (ffplayout program, the item picked for each Slot, the advanced state,
    the filler clips longer than every Break that day, the day's sequence of items).

    card(name, upcoming item paths) -> PNG path. A name is shared by every Repeat
    only when its items stay inside the Airing; cards reaching past it are per
    Airing, and the day's last ones are end_card(n), filled in by the next day.
    """
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
    breaks = [[fill_break(brk, filler_deck, clips) for _ in items]
              for _, items, _, brk in blocks]
    sequence = [p for block, items, _, _ in blocks for _ in range(block["repeat"]) for p in items]
    program, k = [], 0
    for b, (block, items, lengths, _) in enumerate(blocks):
        for r in range(block["repeat"]):
            end = k + len(items)
            for j, (path, length) in enumerate(zip(items, lengths)):
                if k + AHEAD >= len(sequence):
                    name = end_card(len(sequence) - k)
                elif k + AHEAD >= end:
                    name = f"b{b}-a{r}-{j}"
                else:
                    name = f"b{b}-{j}"
                clip_items, rest = breaks[b][j]
                program.append({"in": 0, "out": length, "duration": length, "source": path})
                program += clip_items
                if rest >= MIN_STILL:
                    program.append({"in": 0, "out": rest, "duration": rest,
                                    "source": card(name, sequence[k + 1:k + 1 + AHEAD])})
                k += 1
    return program, [b[1] for b in blocks], state, never_fits, sequence
