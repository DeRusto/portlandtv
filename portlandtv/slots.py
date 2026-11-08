"""Slot resolver: fills one Slot's rule with a concrete item, advancing the state."""
from portlandtv import deck


class Missing(LookupError):
    """The Slot names something not in the Libraries; it is dropped for the day."""


def resolve(rule, shows, movies, groups, state):
    """-> the item's path; advances `state` in place."""
    if "show" in rule:
        return _episode(shows, state, rule["show"])
    if "group" in rule:
        return _group(shows, groups, state, rule["group"])
    return _movie(movies, state)


def _episode(shows, state, name):
    """The episode after the show's last-aired file, wrapping to the first."""
    eps = shows.get(name)
    if not eps:
        raise Missing(f"show {name!r} not found")
    last = state["shows"].get(name, {}).get("path")
    path = eps[(eps.index(last) + 1) % len(eps)] if last in eps else eps[0]
    state["shows"][name] = {"path": path}
    return path


def _group(shows, groups, state, name):
    """Next episode of the current member; once it has run out, of the next member."""
    members = groups.get(name)
    if not members:
        raise Missing(f"Show Group {name!r} not defined")
    for m in members:
        if not shows.get(m):
            raise Missing(f"Show Group {name!r} member {m!r} not found")
    current = state.setdefault("groups", {}).get(name, {}).get("show")
    i = members.index(current) if current in members else 0
    if state["shows"].get(members[i], {}).get("path") == shows[members[i]][-1]:
        i = (i + 1) % len(members)
    state["groups"][name] = {"show": members[i]}
    return _episode(shows, state, members[i])


def _movie(movies, state):
    """Draw from a shuffled deck keyed by path; none repeats until it is used up."""
    if not movies:
        raise Missing("no movies in any movies Library")
    movie_deck = state.setdefault("movies", {})
    path = deck.peek(movie_deck, movies)
    deck.take(movie_deck)
    return path
