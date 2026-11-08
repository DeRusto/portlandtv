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


def read_raw(path):
    """The YAML's raw dict, with the lists the editor works on always present."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return {**raw, "libraries": raw.get("libraries") or [],
            "day_schedule": raw.get("day_schedule") or [],
            "show_list": raw.get("show_list") or []}


def load(path):
    return parse(read_raw(path))


def save(path, raw):
    """Validate `raw` (the YAML's shape) and write it, or raise ConfigError."""
    parse(raw)
    if "day_start" in raw:  # keep HH:MM readable, never a base-60 int
        raw = {**raw, "day_start": parse_day_start(raw["day_start"]).strftime("%H:%M")}
    text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    store.write_atomic(path, lambda f: f.write(text.encode()))


def block(length, repeat, slots):
    """A raw Block from form text; `repeat` is stored as a number when it is one."""
    repeat = repeat.strip()
    return {"length": length.strip(), "repeat": int(repeat) if repeat.isdigit() else repeat,
            "slots": slots}


def new_block():
    return {"length": "1h", "repeat": 1, "slots": [fixed_slot(None)]}


def fixed_slot(rule):
    """A raw fixed Slot airing `rule` every day; no rule is an empty Slot."""
    return {"rule": rule} if rule else {}


def distributed_slot(rules):
    """A raw distributed Slot from its rules Mon..Sun; only non-empty days are stored."""
    return {"weekdays": {d: dict(r) for d, r in zip(WEEKDAYS, rules) if r}}


def is_fixed(slot):
    return "weekdays" not in slot


def slot_rules(slot):
    """A raw Slot's 7 rules Mon..Sun, {} for an empty day (not validated)."""
    if is_fixed(slot):
        return [slot.get("rule") or {}] * 7
    return [(slot["weekdays"] or {}).get(d) or {} for d in WEEKDAYS]


def switch_mode(slot):
    """Fixed -> distributed with the rule on all seven days; distributed -> fixed
    keeping Monday's rule."""
    rules = slot_rules(slot)
    return distributed_slot(rules) if is_fixed(slot) else fixed_slot(rules[0])


def length_repeat(raw_block):
    """A raw Block's (length s, repeat), or raise ConfigError."""
    repeat = raw_block.get("repeat", 1)
    if not str(repeat).isdigit() or int(repeat) < 1:
        raise ConfigError(f"bad Block repeat {repeat!r}, use a whole number from 1")
    return parse_length(raw_block.get("length")), int(repeat)


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
    if not isinstance(raw, dict):
        raise ConfigError("the config file must be a mapping of keys")
    day_start = parse_day_start(raw.get("day_start", "06:00"))
    for lib in raw.get("libraries") or []:
        if not isinstance(lib, dict) or not lib.get("path") or lib.get("kind") not in KINDS:
            raise ConfigError(f"bad Library {lib!r}, it needs a path and a kind of "
                              + ", ".join(KINDS))
    show_list = raw.get("show_list") or []
    for e in show_list:
        if not isinstance(e, dict) or len(e) != 1 or next(iter(e)) not in ("show", "group"):
            raise ConfigError(f"bad Show List entry {e!r}, use {{show: X}} or {{group: X}}")
    blocks = []
    for b in raw.get("day_schedule") or []:
        if not isinstance(b, dict):
            raise ConfigError(f"bad Block {b!r}, it needs a length, a repeat and slots")
        slots = []
        for s in b.get("slots") or []:
            if not isinstance(s, dict):
                raise ConfigError(f"bad Slot {s!r}, use rule: or weekdays:")
            if not is_fixed(s) and set(s["weekdays"] or {}) - set(WEEKDAYS):
                raise ConfigError(f"bad weekdays {sorted(s['weekdays'])!r}, use mon .. sun")
            # an empty day, or a fixed Slot with no rule, is an empty Weekday Rule
            slots.append([_rule(r) if r else {} for r in slot_rules(s)])
        length, repeat = length_repeat(b)
        blocks.append({"length": length, "repeat": repeat, "slots": slots})
    total = sum(b["length"] * b["repeat"] for b in blocks)
    if total != DAY:
        raise ConfigError(f"Day Schedule totals {total / 3600:g} h, it must be exactly 24 h")
    return {"libraries": raw.get("libraries") or [], "day_start": day_start,
            "day_schedule": blocks, "show_groups": raw.get("show_groups") or {},
            "show_list": show_list}
