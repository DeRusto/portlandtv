"""Config: the single owner of the human-owned YAML shape."""
import re
from datetime import time

import yaml

from portlandtv import store

DAY = 24 * 3600
RULES = {"show"}
KINDS = ("shows", "movies", "filler")


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


def parse(raw):
    """The YAML's raw dict -> the validated config, or raise ConfigError."""
    day_start = parse_day_start(raw.get("day_start", "06:00"))
    for lib in raw.get("libraries") or []:
        if not lib.get("path") or lib.get("kind") not in KINDS:
            raise ConfigError(f"bad Library {lib!r}, it needs a path and a kind of "
                              + ", ".join(KINDS))
    blocks = []
    for b in raw.get("day_schedule") or []:
        slots = []
        for s in b.get("slots") or []:
            rule = s.get("rule") or {}
            if len(rule) != 1 or next(iter(rule)) not in RULES:
                raise ConfigError(f"unknown Slot rule {rule!r}")
            slots.append(rule)
        repeat = b.get("repeat", 1)
        if not str(repeat).isdigit() or int(repeat) < 1:
            raise ConfigError(f"bad Block repeat {repeat!r}, use a whole number from 1")
        blocks.append({"length": parse_length(b.get("length")),
                       "repeat": int(repeat), "slots": slots})
    total = sum(b["length"] * b["repeat"] for b in blocks)
    if total != DAY:
        raise ConfigError(f"Day Schedule totals {total / 3600:g} h, it must be exactly 24 h")
    return {"libraries": raw.get("libraries") or [], "day_start": day_start,
            "day_schedule": blocks}
