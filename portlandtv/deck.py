"""Shuffled deck kept in state: nothing repeats until every item has been drawn."""
import random


def peek(deck, items):
    """The next item, after syncing `deck` ({"left", "aired"} path lists) with `items`.

    Removed items drop out, new ones are shuffled into what is left, and a
    used-up deck is reshuffled. None when `items` is empty.
    """
    present = set(items)
    left = [p for p in deck.get("left", []) if p in present]
    aired = [p for p in deck.get("aired", []) if p in present]
    known = set(left) | set(aired)
    for p in items:
        if p not in known:
            left.insert(random.randint(0, len(left)), p)
    if not left:
        left, aired = random.sample(list(items), len(items)), []
    deck["left"], deck["aired"] = left, aired
    return left[0] if left else None


def take(deck):
    """Draw the item `peek` returned."""
    deck["aired"].append(deck["left"].pop(0))


def draw(deck, items, fits):
    """Draw the first item in deck order that `fits`, leaving the ones skipped in
    place; None when nothing left fits."""
    peek(deck, items)
    item = next((p for p in deck["left"] if fits(p)), None)
    if item is not None:
        deck["left"].remove(item)
        deck["aired"].append(item)
    return item
