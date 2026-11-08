"""Slot resolver: fills one Slot's rule with a concrete item, advancing the state."""
from portlandtv import deck
from portlandtv.library import episode_key


class Missing(LookupError):
    """The Slot names something not in the Libraries; it is dropped for the day."""


def resolve(rule, shows, movies, groups, state):
    """-> the item's path; advances `state` in place."""
    if not rule:
        raise Missing("empty Weekday Rule, the Slot is skipped today")
    if "show" in rule:
        return _episode(shows, state, rule["show"])
    if "group" in rule:
        return _group(shows, groups, state, rule["group"])
    return _movie(movies, state)


def _next(eps, last):
    """Index of the episode after `last` ({"path", "key"}); len(eps) once it has run out.
    If the last-aired file is gone, the first episode sorting after its key."""
    if last.get("path") in eps:
        return eps.index(last["path"]) + 1
    if "key" in last:
        return next((n for n, p in enumerate(eps) if episode_key(p) > tuple(last["key"])),
                    len(eps))
    return 0


def _episode(shows, state, name):
    """The episode after the show's last-aired one, wrapping to the first."""
    eps = shows.get(name)
    if not eps:
        raise Missing(f"show {name!r} not found")
    path = eps[_next(eps, state["shows"].get(name, {})) % len(eps)]
    state["shows"][name] = {"path": path, "key": list(episode_key(path))}
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
    if _next(shows[members[i]], state["shows"].get(members[i], {})) >= len(shows[members[i]]):
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


def keep(rule, path, shows, movies, groups, state):
    """Advance `state` as if the Slot had resolved to `path` (an item "rebuild today"
    keeps). Raises Missing when the rule no longer covers `path`."""
    if "movie" in rule:
        if path not in movies:
            raise Missing(f"movie {path!r} gone")
        movie_deck = state.setdefault("movies", {})
        deck.peek(movie_deck, movies)  # sync first, so the kept movie is in the deck
        if path in movie_deck["left"]:
            movie_deck["left"].remove(path)
            movie_deck["aired"].append(path)
        return path
    names = [rule["show"]] if "show" in rule else groups.get(rule["group"]) or []
    name = next((n for n in names if path in shows.get(n, [])), None)
    if name is None:
        raise Missing(f"{path!r} no longer covered by the rule")
    if "group" in rule:
        state.setdefault("groups", {})[rule["group"]] = {"show": name}
    state["shows"][name] = {"path": path, "key": list(episode_key(path))}
    return path
