"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times."""
import copy
from typing import NamedTuple

from portlandtv import deck, slots


class Day(NamedTuple):
    """What build() returns."""
    program: list  # the ffplayout program
    block_items: list  # per Block, the items it airs
    state: dict  # the state after the day
    never_fits: list  # filler clips longer than every Break that day
    problems: list  # dropped Slots, flagged
    sequence: list  # the day's items in airing order
    slot_fills: list  # per Block, per Slot [rule, path or None]; a later build's `kept`


AHEAD = 3  # a card names the next item and the two after it
MIN_STILL = 1.0  # a Break remainder shorter than this is dropped
FRAME_ROWS, FRAME_SECONDS = 6, 10  # schedule display: Slots per frame, seconds per frame
DISPLAY_EVERY = 3  # the schedule display airs in every 3rd Break of an Airing


def fill_break(length, filler_deck, clips):
    """-> (whole clips from the deck while any fits, the remainder left for the card).
    A clip too long for what is left stays in the deck for a later Break."""
    out = []
    while path := deck.draw(filler_deck, list(clips), lambda p: clips[p] <= length):
        out.append({"in": 0, "out": clips[path], "duration": clips[path], "source": path})
        length -= clips[path]
    return out, length


def end_card(n):
    """Name of the card n Breaks from the end of the day (1 = final Break)."""
    return f"end-{n}"


def resolve_block(cfg, block, b, shows, movies, state, prober, problems, kept=()):
    """-> (items, lengths, state, [[rule, path or None] per Slot]) for the Slots
    that exist and fit the Block.

    A Slot naming something missing is dropped and flagged; once a Slot overruns,
    it and the Slots after it are dropped. Dropped Slots advance nothing.
    `kept`: an earlier build's [rule, path] per Slot; a Slot at the same position
    with the same rule keeps that path.
    """
    items, lengths, fills = [], [], []
    for s, rule in enumerate(block["slots"], 1):
        fills.append([rule, None])
        trial, path = copy.deepcopy(state), None
        if s <= len(kept) and kept[s - 1][0] == rule and kept[s - 1][1]:
            try:
                path = slots.keep(rule, kept[s - 1][1], shows, movies, cfg["show_groups"], trial)
            except slots.Missing:  # the kept item is gone: fill the Slot fresh
                trial = copy.deepcopy(state)
        try:
            path = path or slots.resolve(rule, shows, movies, cfg["show_groups"], trial)
        except slots.Missing as e:
            problems.append(f"Block {b} Slot {s}: {e}")
            continue
        length = prober.duration(path)
        if sum(lengths) + length > block["length"]:
            break
        items.append(path)
        lengths.append(length)
        fills[-1][1] = path
        state = trial
    return items, lengths, state, fills


def build(cfg, shows, state, prober, card, filler=(), movies=(), schedule=None, kept=()):
    """-> the Day built from `state`.

    card(name, upcoming item paths) -> PNG path. A name is shared by every Repeat
    only when its items stay inside the Airing; cards reaching past it are per
    Airing, and the day's last ones are end_card(n), filled in by the next day.

    schedule(name, [(start s, path) per Slot], upcoming Slot index, (start s, end s))
    -> that Airing's schedule display frame PNGs; times are seconds from day start.
    `kept`: a previous build's slot_fills for this day ("rebuild today").
    """
    blocks, problems, slot_fills = [], [], []
    for b, block in enumerate(cfg["day_schedule"], 1):
        items, lengths, state, fills = resolve_block(
            cfg, block, b, shows, movies, state, prober, problems,
            kept[b - 1] if b <= len(kept) else ())
        slot_fills.append(fills)
        brk = (block["length"] - sum(lengths)) / max(len(items), 1)
        blocks.append((block, items, lengths, brk))
    state = copy.deepcopy(state)  # never mutate the caller's state
    longest = max(b[3] for b in blocks)
    durations = {p: prober.duration(p) for p in filler}
    clips = {p: d for p, d in durations.items() if 0 < d <= longest}
    never_fits = sorted(p for p, d in durations.items() if d > longest)
    filler_deck = state.setdefault("filler", {})
    # filler is drawn once per Break position and shared by Repeats; a Block with
    # no items airs as one Break
    breaks = [[fill_break(brk, filler_deck, clips) for _ in items or [None]]
              for _, items, _, brk in blocks]
    sequence = [p for block, items, _, _ in blocks for _ in range(block["repeat"]) for p in items]
    program, k, t = [], 0, 0  # k: index in `sequence` of the next item; t: Airing start
    for b, (block, items, lengths, _) in enumerate(blocks):
        starts, at = [], 0  # Slot starts within the Airing, from the Breaks as laid out
        for length, (clip_items, rest) in zip(lengths, breaks[b]):
            starts.append(at)
            at += length + sum(c["duration"] for c in clip_items) + (rest if rest >= MIN_STILL else 0)
        frames = -(-len(items) // FRAME_ROWS)
        for r in range(block["repeat"]):
            end, since = k + len(items), 0
            for j, (clip_items, rest) in enumerate(breaks[b]):
                if j < len(items):
                    program.append({"in": 0, "out": lengths[j], "duration": lengths[j],
                                    "source": items[j]})
                    k += 1
                program += clip_items
                since += 1
                if (schedule and items and since >= DISPLAY_EVERY
                        and rest >= frames * FRAME_SECONDS):
                    since, rest = 0, rest - frames * FRAME_SECONDS
                    rows = [(t + o, p) for o, p in zip(starts, items)]
                    program += [{"in": 0, "out": FRAME_SECONDS, "duration": FRAME_SECONDS,
                                 "source": f} for f in
                                schedule(f"b{b}-a{r}-{j}", rows, j + 1, (t, t + block["length"]))]
                if rest < MIN_STILL:
                    continue
                if k + AHEAD > len(sequence):
                    name = end_card(len(sequence) - k + 1)
                elif k + AHEAD > end:
                    name = f"b{b}-a{r}-{j}"
                else:
                    name = f"b{b}-{j}"
                program.append({"in": 0, "out": rest, "duration": rest,
                                "source": card(name, sequence[k:k + AHEAD])})
            t += block["length"]
    return Day(program, [b[1] for b in blocks], state, never_fits, problems, sequence,
               slot_fills)
