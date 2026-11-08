"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy

from portlandtv import deck, slots

MIN_STILL = 1.0  # a Break remainder shorter than this is dropped


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


def resolve_block(cfg, block, b, shows, movies, state, prober, problems):
    """-> (items, lengths, state) for the Slots that exist and fit the Block.

    A Slot naming something missing is dropped and flagged; once a Slot overruns,
    it and the Slots after it are dropped. Dropped Slots advance nothing.
    """
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
    return items, lengths, state


def build(cfg, shows, state, prober, card, filler=(), movies=()):
    """-> (ffplayout program, the items picked per Block, the advanced state,
    the filler clips longer than every Break that day, the dropped-Slot problems)."""
    blocks, problems = [], []
    for b, block in enumerate(cfg["day_schedule"], 1):
        items, lengths, state = resolve_block(cfg, block, b, shows, movies, state,
                                              prober, problems)
        brk = (block["length"] - sum(lengths)) / max(len(items), 1)
        blocks.append((block, items, lengths, brk))
    state = copy.deepcopy(state)  # never mutate the caller's state
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
        if not items:  # nothing aired: the whole Block is one Break
            airing = fill_break(brk, filler_deck, clips, card)
        program += airing * block["repeat"]
    return program, [b[1] for b in blocks], state, never_fits, problems
