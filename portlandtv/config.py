"""Config: the single owner of the human-owned YAML shape."""
import re
from datetime import time

import yaml

from portlandtv import store

DAY = 24 * 3600
RULES = {"show", "group", "movie"}
KINDS = ("shows", "movies", "filler")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # date.weekday() order


class ConfigError(ValueError):
    pass


def parse_length(text):
    """'8h', '90m' or '1h30m' -> seconds."""
    m = re.fullmatch(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*", str(text))
    if not m or not any(m.groups()):
        raise ConfigError(f"bad Block length {text!r}, use e.g. 8h or 1h30m")
    return int(m[1] or 0) * 3600 + int(m[2] or 0) * 60


def parse_day_start(start):
    """'06:00', or the base-60 int YAML 1.1 makes of an unquoted 06:00 -> time."""
    try:
        if isinstance(start, int):
            start = f"{start // 60:02}:{start % 60:02}"
        return time.fromisoformat(start)
    except (TypeError, ValueError):
        raise ConfigError(f"bad day_start {start!r}, use UTC HH:MM")


def load(path):
    with open(path) as f:
        return parse(yaml.safe_load(f) or {})


def save(path, raw):
    """Validate `raw` (the YAML's shape) and write it, or raise ConfigError."""
    parse(raw)
    if "day_start" in raw:  # keep HH:MM readable, never a base-60 int
        raw = {**raw, "day_start": parse_day_start(raw["day_start"]).strftime("%H:%M")}
    text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    store.write_atomic(path, lambda f: f.write(text.encode()))


def _rule(rule):
    if not isinstance(rule, dict) or len(rule) != 1 or next(iter(rule)) not in RULES:
        raise ConfigError(f"unknown Slot rule {rule!r}")
    return rule


def on_weekday(cfg, weekday):
    """The config with each Slot reduced to its rule on `weekday` (0 = Monday)."""
    return {**cfg, "day_schedule": [{**b, "slots": [s[weekday] for s in b["slots"]]}
                                    for b in cfg["day_schedule"]]}


def parse(raw):
    """The YAML's raw dict -> the validated config, or raise ConfigError."""
    day_start = parse_day_start(raw.get("day_start", "06:00"))
    for lib in raw.get("libraries") or []:
        if not lib.get("path") or lib.get("kind") not in KINDS:
            raise ConfigError(f"bad Library {lib!r}, it needs a path and a kind of "
                              + ", ".join(KINDS))
    show_list = raw.get("show_list") or []
    for e in show_list:
        if not isinstance(e, dict) or len(e) != 1 or next(iter(e)) not in ("show", "group"):
            raise ConfigError(f"bad Show List entry {e!r}, use {{show: X}} or {{group: X}}")
    blocks = []
    for b in raw.get("day_schedule") or []:
        slots = []
        for s in b.get("slots") or []:
            if "weekdays" in s:  # distributed: a missing or empty day is an empty Weekday Rule
                days = s["weekdays"] or {}
                if set(days) - set(WEEKDAYS):
                    raise ConfigError(f"bad weekdays {sorted(days)!r}, use mon .. sun")
                slots.append([_rule(days[d]) if days.get(d) else {} for d in WEEKDAYS])
            else:
                slots.append([_rule(s.get("rule") or {})] * 7)
        repeat = b.get("repeat", 1)
        if not str(repeat).isdigit() or int(repeat) < 1:
            raise ConfigError(f"bad Block repeat {repeat!r}, use a whole number from 1")
        blocks.append({"length": parse_length(b.get("length")),
                       "repeat": int(repeat), "slots": slots})
    total = sum(b["length"] * b["repeat"] for b in blocks)
    if total != DAY:
        raise ConfigError(f"Day Schedule totals {total / 3600:g} h, it must be exactly 24 h")
    return {"libraries": raw.get("libraries") or [], "day_start": day_start,
            "day_schedule": blocks, "show_groups": raw.get("show_groups") or {},
            "show_list": show_list}
