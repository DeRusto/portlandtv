"""Day builder: fill each Slot once, lay out Breaks, write each Airing N times, and work
out the Generated Filler the day airs, End Cards included."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from portlandtv import deck, slots


class Day(NamedTuple):
    """What build() returns."""
    program: list  # the ffplayout program
    block_items: list  # per Block, the items it airs
    state: dict  # the state after the day
    never_fits: list  # filler clips longer than every Break that day
    problems: list  # dropped Slots, flagged
    slot_fills: list  # per Block, per Slot [rule, path or None]; a later build's `kept`
    cards: dict  # card PNG path -> what it shows: {"items"} or a schedule display frame
    redraw: dict  # path of an End Card of the day before -> {"items"} it shows now
    tail: list  # the day's last items, which the next day's build completes End Cards from
    end_cards: list  # names of the End Cards the day airs


_AHEAD = 3  # a card names the next item and the two after it
_MIN_STILL = 1.0  # a Break remainder shorter than this is dropped
_FRAME_ROWS, _FRAME_SECONDS = 6, 10  # schedule display: Slots per frame, seconds per frame
_DISPLAY_EVERY = 3  # the schedule display airs in every 3rd Break of an Airing


def _fill_break(length, filler_deck, clips):
    """-> (whole clips from the deck while any fits, the remainder left for the card).
    A clip too long for what is left stays in the deck for a later Break."""
    out = []
    while path := deck.draw(filler_deck, list(clips), lambda p: clips[p] <= length):
        out.append({"in": 0, "out": clips[path], "duration": clips[path], "source": path})
        length -= clips[path]
    return out, length


def _resolve_block(cfg, block, b, shows, movies, state, prober, problems, kept=()):
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


def _end_card(n):
    """Name of the End Card n Breaks from the end of the day (1 = final Break)."""
    return f"end-{n}"


def _card_name(content):
    """A card is named by what it shows, so every Break showing the same shares one file."""
    return hashlib.sha1(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def build(cfg, date, shows, state, prober, card_path, filler=(), movies=(), kept=(),
          previous=None):
    """-> the Day starting on `date`, built from `state`.

    card_path(date, name) -> where that day's card `name` lives; the program airs those
    paths, and Day.cards says what each shows. Cards are named by their content, so
    Repeats share a card whenever it shows the same; the day's last ones are End Cards,
    fixed names the next day's build redraws.
    `kept`: a previous build's slot_fills for this day ("rebuild today").
    `previous`: the day before's Day Record (tail, end_cards) or None; its End Cards
    are completed with this day's first items, in Day.redraw.
    """
    blocks, problems, slot_fills = [], [], []
    for b, block in enumerate(cfg["day_schedule"], 1):
        items, lengths, state, fills = _resolve_block(
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
    breaks = [[_fill_break(brk, filler_deck, clips) for _ in items or [None]]
              for _, items, _, brk in blocks]
    sequence = [p for block, items, _, _ in blocks for _ in range(block["repeat"]) for p in items]
    start = datetime.combine(date, cfg["day_start"], timezone.utc)
    cards, end_cards = {}, []

    def hhmm(seconds):
        return (start + timedelta(seconds=seconds)).strftime("%H:%M")

    def card(content, name=None):
        path = card_path(date, name or _card_name(content))
        cards[path] = content
        return path

    def frames(rows, upcoming, span):
        """That Airing's schedule display, _FRAME_ROWS Slots a frame."""
        entries = [{"time": hhmm(t), "path": p,
                    "state": "aired" if i < upcoming else "up_next" if i == upcoming else "later"}
                   for i, (t, p) in enumerate(rows)]
        pages = [entries[i:i + _FRAME_ROWS] for i in range(0, len(entries), _FRAME_ROWS)]
        return [card({"heading": "TODAY ON PORTLAND TV",
                      "range": f"{hhmm(span[0])}–{hhmm(span[1])} UTC",
                      "page": f"{n}/{len(pages)}", "rows": page})
                for n, page in enumerate(pages, 1)]

    program, k, t = [], 0, 0  # k: index in `sequence` of the next item; t: Airing start
    for b, (block, items, lengths, _) in enumerate(blocks):
        starts, at = [], 0  # Slot starts within the Airing, from the Breaks as laid out
        for length, (clip_items, rest) in zip(lengths, breaks[b]):
            starts.append(at)
            at += length + sum(c["duration"] for c in clip_items) + (rest if rest >= _MIN_STILL else 0)
        n_frames = -(-len(items) // _FRAME_ROWS)
        for _ in range(block["repeat"]):
            since = 0
            for j, (clip_items, rest) in enumerate(breaks[b]):
                if j < len(items):
                    program.append({"in": 0, "out": lengths[j], "duration": lengths[j],
                                    "source": items[j]})
                    k += 1
                program += clip_items
                since += 1
                if items and since >= _DISPLAY_EVERY and rest >= n_frames * _FRAME_SECONDS:
                    since, rest = 0, rest - n_frames * _FRAME_SECONDS
                    rows = [(t + o, p) for o, p in zip(starts, items)]
                    program += [{"in": 0, "out": _FRAME_SECONDS, "duration": _FRAME_SECONDS,
                                 "source": f}
                                for f in frames(rows, j + 1, (t, t + block["length"]))]
                if rest < _MIN_STILL:
                    continue
                upcoming = {"items": sequence[k:k + _AHEAD]}
                if k + _AHEAD > len(sequence):
                    name = _end_card(len(sequence) - k + 1)
                    if name not in end_cards:
                        end_cards.append(name)
                    source = card(upcoming, name)
                else:
                    source = card(upcoming)
                program.append({"in": 0, "out": rest, "duration": rest, "source": source})
            t += block["length"]
    return Day(program, [b[1] for b in blocks], state, never_fits, problems, slot_fills,
               cards, _redraw(previous, sequence, card_path, date), sequence[-_AHEAD:],
               end_cards)


def _redraw(previous, sequence, card_path, date):
    """The day before's End Cards, completed with this day's first items."""
    if previous is None or previous.tail is None:
        return {}
    tail, aired = previous.tail, previous.end_cards  # aired: None in an older record
    before = date - timedelta(days=1)
    out = {}
    # end-(n) shows the day's items from len(tail) - n + 1; n reaches len(tail) + 1
    # when a Break airs before the day's first item (an empty first Block)
    for n in range(1, min(len(tail) + 1, _AHEAD) + 1):
        if aired is None or _end_card(n) in aired:
            i = len(tail) - n + 1
            out[card_path(before, _end_card(n))] = {"items": (tail + sequence)[i:i + _AHEAD]}
    return out
