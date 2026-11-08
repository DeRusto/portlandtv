"""Config: the single owner of the human-owned YAML shape."""
import re
from datetime import time

import yaml

DAY = 24 * 3600
RULES = {"show", "group", "movie"}


class ConfigError(ValueError):
    pass


def parse_length(text):
    """'8h', '90m' or '1h30m' -> seconds."""
    m = re.fullmatch(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*", str(text))
    if not m or not any(m.groups()):
        raise ConfigError(f"bad Block length {text!r}, use e.g. 8h or 1h30m")
    return int(m[1] or 0) * 3600 + int(m[2] or 0) * 60


def load(path):
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    start = raw.get("day_start", "06:00")
    try:
        if isinstance(start, int):  # unquoted HH:MM is a base-60 int in YAML 1.1
            start = f"{start // 60:02}:{start % 60:02}"
        day_start = time.fromisoformat(start)
    except (TypeError, ValueError):
        raise ConfigError(f"bad day_start {raw.get('day_start')!r}, use UTC HH:MM")
    blocks = []
    for b in raw.get("day_schedule") or []:
        slots = []
        for s in b.get("slots") or []:
            rule = s.get("rule") or {}
            if len(rule) != 1 or next(iter(rule)) not in RULES:
                raise ConfigError(f"unknown Slot rule {rule!r}")
            slots.append(rule)
        blocks.append({"length": parse_length(b["length"]),
                       "repeat": int(b.get("repeat", 1)), "slots": slots})
    total = sum(b["length"] * b["repeat"] for b in blocks)
    if total != DAY:
        raise ConfigError(f"Day Schedule totals {total / 3600:g} h, it must be exactly 24 h")
    return {"libraries": raw.get("libraries") or [], "day_start": day_start,
            "day_schedule": blocks, "show_groups": raw.get("show_groups") or {}}
