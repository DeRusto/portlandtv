"""Web app: one server-rendered page that edits the YAML through Config.

Buttons post the whole form with an `action`. Every action except `save` and
`replace` (Distribute's confirm) only re-renders the edited draft; those two
validate and write the YAML.
"""
import collections
import glob
import os
import statistics
from datetime import datetime, timedelta

import yaml
from flask import Flask, redirect, render_template, request

from portlandtv import config, distributor, library, slots, store

# Show List colours, by entry position; off-list rules are grey
PALETTE = ("#cfe3ff", "#d6f5d6", "#ffe1c4", "#ecd9ff", "#ffd6e0", "#d4f1f4", "#fff3b0", "#e2e2ff")
OFF_LIST = "#e6e6e6"


def _hm(seconds):
    sign = "−" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 3600}h{seconds % 3600 // 60:02}"


def _rule_key(rule):
    """{show: X} -> 'show:X', the value of a Slot's rule dropdown."""
    if not rule:
        return ""
    (kind, name), = rule.items()
    return f"{kind}:{name}"


def _form_rule(value):
    """'show:X' -> {show: X}; '' -> None."""
    kind, _, name = value.partition(":")
    return {kind: name} if kind else None


def _from_form(form, raw):
    """The posted form over `raw` (keys the form doesn't edit are kept)."""
    libs, i = [], 0
    while f"lib{i}.path" in form:
        libs.append({"path": form[f"lib{i}.path"].strip(), "kind": form[f"lib{i}.kind"]})
        i += 1
    blocks, i = [], 0
    while f"b{i}.length" in form:
        slots, j = [], 0
        while (s := f"b{i}.s{j}") + ".rule" in form or s + ".mon" in form:
            if s + ".mon" in form:  # distributed: only the non-empty days are stored
                slots.append({"weekdays": {d: r for d in config.WEEKDAYS
                                           if (r := _form_rule(form[f"{s}.{d}"]))}})
            else:
                r = _form_rule(form[s + ".rule"])
                slots.append({"rule": r} if r else {})
            j += 1
        repeat = form[f"b{i}.repeat"].strip()
        blocks.append({"length": form[f"b{i}.length"].strip(),
                       "repeat": int(repeat) if repeat.isdigit() else repeat,
                       "slots": slots})
        i += 1
    entries, k = [], 0
    while f"sl{k}" in form:
        entries.append(_form_rule(form[f"sl{k}"]))
        k += 1
    return {**raw, "libraries": libs, "day_schedule": blocks, "show_list": entries}


def _move(items, j, k):
    if 0 <= k < len(items):
        items[j], items[k] = items[k], items[j]


def _apply(raw, action, add=""):
    """Edit the draft for one button: add/del/up/down of Blocks, Slots, Libraries,
    Show List entries (`add`: the rule key picked in the add dropdown)."""
    verb, _, args = action.partition(":")
    idx = [int(a) for a in args.split(":") if a]
    blocks, libs, entries = raw["day_schedule"], raw["libraries"], raw["show_list"]
    if verb == "add-block":
        blocks.append({"length": "1h", "repeat": 1, "slots": [{}]})
    elif verb == "del-block":
        del blocks[idx[0]]
    elif verb == "add-slot":
        blocks[idx[0]]["slots"].append({})
    elif verb == "add-dslot":  # a new distributed Slot starts empty
        blocks[idx[0]]["slots"].append({"weekdays": {}})
    elif verb == "mode-slot":
        slots, j = blocks[idx[0]]["slots"], idx[1]
        if "weekdays" in slots[j]:  # -> fixed, keeping Monday's rule (the page confirms)
            mon = (slots[j]["weekdays"] or {}).get("mon")
            slots[j] = {"rule": mon} if mon else {}
        else:  # -> distributed, the rule copied to all seven days
            rule = slots[j].get("rule")
            slots[j] = {"weekdays": {d: dict(rule) for d in config.WEEKDAYS} if rule else {}}
    elif verb == "del-slot":
        del blocks[idx[0]]["slots"][idx[1]]
    elif verb in ("up-slot", "down-slot"):
        j = idx[1]
        _move(blocks[idx[0]]["slots"], j, j - 1 if verb == "up-slot" else j + 1)
    elif verb in ("up-entry", "down-entry"):
        _move(entries, idx[0], idx[0] - 1 if verb == "up-entry" else idx[0] + 1)
    elif verb == "del-entry":  # the grid is left as it is
        del entries[idx[0]]
    elif verb == "add-entry" and (rule := _form_rule(add)) and rule not in entries:
        entries.append(rule)
    elif verb == "add-lib":
        libs.append({"path": "", "kind": "shows"})
    elif verb == "del-lib":
        del libs[idx[0]]


def create_app(service):
    app = Flask(__name__)
    data_dir = os.path.dirname(os.path.abspath(service.config_path))

    def read_raw():
        with open(service.config_path) as f:
            raw = yaml.safe_load(f) or {}
        return {**raw, "libraries": raw.get("libraries") or [],
                "day_schedule": raw.get("day_schedule") or [],
                "show_list": raw.get("show_list") or []}

    def durations(rule, shows, groups, movies, prober):
        """Every length the rule can pick, in seconds."""
        if not rule:
            return []
        if "show" in rule:
            paths = shows.get(rule["show"], [])
        elif "group" in rule:
            paths = [p for n in groups.get(rule["group"]) or [] for p in shows.get(n, [])]
        else:
            paths = movies
        return [d for d in map(prober.duration, paths) if d]

    def problems(missing_libs, schedule):
        out = list(schedule)
        if service.error:
            out.append(f"Generation error: {service.error} (retrying)")
        out += [f"Library missing: {p}" for p in missing_libs]
        out += [f"Unplayable: {p}" for p in service.unplayable]
        records = sorted(glob.glob(os.path.join(data_dir, "days", "*.json")))
        if records:  # the latest per-day record's dropped/flagged Slots and filler
            record = store.read_json(records[-1], {})
            date = os.path.basename(records[-1])[:-5]
            out += [f"{date}: {p}" for p in record.get("problems") or []]
            out += [f"Filler never fits: {p}" for p in record.get("never_fits") or []]
        return out

    def scan(raw):
        """-> (missing Library folders, prober, shows, movies) for the draft's Libraries."""
        libs = [lib for lib in raw["libraries"] if lib.get("path")]
        missing = [lib["path"] for lib in libs if not os.path.isdir(lib["path"])]
        found = [lib for lib in libs if lib["path"] not in missing]
        prober = library.CachedProber(service.prober, os.path.join(data_dir, "durations.json"))
        shows, _ = library.scan_shows(found, prober)
        return missing, prober, shows, library.scan_movies(found)

    def remaining(raw, shows):
        """Episodes left per Show List entry; a Show Group sums its members."""
        state = store.read_json(os.path.join(data_dir, "state.json"), {"shows": {}})
        groups = raw.get("show_groups") or {}

        def left(name):  # episodes after the show's last-aired one
            eps = shows.get(name, [])
            return len(eps) - min(slots._next(eps, state["shows"].get(name, {})), len(eps))

        return [left(e["show"]) if "show" in e else sum(map(left, groups.get(e.get("group")) or []))
                for e in raw["show_list"]]

    def distributed(raw):
        """[(Block n, Slot m, Slot)] of the distributed Slots, in Distribute's cell order."""
        return [(n, m, s) for n, b in enumerate(raw["day_schedule"], 1)
                for m, s in enumerate(b.get("slots") or [], 1) if "weekdays" in s]

    def plan(raw, shows):
        """New Weekday Rules per distributed Slot; raises distributor.Refused."""
        return distributor.distribute(raw["show_list"], remaining(raw, shows),
                                      len(distributed(raw)))

    def render(raw, error=None, status=200, preview=False, refused=None):
        try:
            day_start = config.parse_day_start(raw.get("day_start", "06:00"))
        except config.ConfigError as e:
            error, day_start = error or str(e), config.parse_day_start("06:00")
        missing, prober, shows, movies = scan(raw)
        groups = raw.get("show_groups") or {}
        entries = [_rule_key(e) for e in raw["show_list"]]
        eps_left = remaining(raw, shows)
        colour = {e: PALETTE[i % len(PALETTE)] for i, e in enumerate(entries)}
        choices = ([(f"show:{n}", n) for n in shows]
                   + [(f"group:{n}", f"Show Group: {n}") for n in groups])
        names = dict(choices)
        add = [(k, t) for k, t in choices if k not in entries]
        choices = ([(k, t if k in entries else f"{t} (not in list)") for k, t in choices]
                   + [("movie:random", "Random movie")])
        t = datetime.combine(datetime.min.date(), day_start)
        blocks, total, schedule = [], 0, []
        cells = collections.Counter()  # rule key -> cells per week
        off_list = {}  # off-list shows and Show Groups on distributed cells, in order
        for n, b in enumerate(raw["day_schedule"], 1):
            try:
                length = config.parse_length(b.get("length"))
                repeat = int(b.get("repeat", 1))
            except (ValueError, TypeError):
                length, repeat = None, 0
            view = {"raw": b, "airs": [], "slots": []}
            typical, most = [0] * 7, [0] * 7  # content per weekday
            if length:
                total += length * repeat
                for _ in range(repeat):
                    view["airs"].append(t.strftime("%H:%M"))
                    t += timedelta(seconds=length)
            for m, s in enumerate(b.get("slots") or [], 1):
                fixed = "weekdays" not in s
                rules = ([s.get("rule") or {}] * 7 if fixed else
                         [(s["weekdays"] or {}).get(d) or {} for d in config.WEEKDAYS])
                for d, rule in enumerate(rules):
                    lengths = durations(rule, shows, groups, movies, prober)
                    if lengths:
                        typical[d] += statistics.median(lengths)
                        most[d] += max(lengths)
                keys = [_rule_key(r) for r in rules]
                cells.update(k for k in keys if k)
                if not fixed:
                    off_list.update((k, None) for k in keys
                                    if k and k not in colour and not k.startswith("movie:"))
                # cells[d]: that weekday's dropdown value; colours[d]: its Show List colour
                view["slots"].append({"fixed": fixed, "cells": keys, "colours": [
                    colour.get(k, OFF_LIST) if k else "" for k in keys]})
                empty = [day.title() for day, r in zip(config.WEEKDAYS, rules) if not r]
                if empty and not fixed:
                    schedule.append(f"Block {n} Slot {m} is empty on {', '.join(empty)}:"
                                    " skipped those days")
            view["fill"] = [{"content": _hm(t), "brk": _hm(length - t) if length else "?",
                             "over": bool(length) and t > length} for t in typical]
            over = [day.title() for day, f in zip(config.WEEKDAYS, view["fill"]) if f["over"]]
            if over:
                schedule.append(f"Block {n} content runs past its length on {', '.join(over)}")
            view["over"] = bool(length) and max(most) > length
            view["typical"], view["max"] = _hm(max(typical)), _hm(max(most))
            blocks.append(view)
        prober.save()
        schedule += [f"Show List: {names.get(e, e)} has no cells on the grid"
                     for e in entries if not cells[e]]
        schedule += [f"{names.get(k, k)} is on the grid but not in the Show List"
                     for k in off_list]

        def weeks(n, count):
            return f"{n / count:.1f}" if count else "not scheduled"

        def cell(key, changed=False):
            return {"label": names.get(key, "Random movie" if key else "— empty"),
                    "colour": colour.get(key, OFF_LIST) if key else "", "changed": changed}

        show_list = [{"key": e, "label": names.get(e, e), "colour": colour[e], "left": n,
                      "cells": cells[e], "weeks": weeks(n, cells[e])}
                     for e, n in zip(entries, eps_left)]
        dialog = None
        if preview:
            try:
                new = plan(raw, shows)
            except distributor.Refused as e:
                refused = str(e)
            else:
                rows, after = [], cells.copy()
                for (n, m, s), rules in zip(distributed(raw), new):
                    now = [_rule_key((s["weekdays"] or {}).get(d)) for d in config.WEEKDAYS]
                    then = [_rule_key(r) for r in rules]
                    after.subtract(k for k in now if k)
                    after.update(then)
                    rows.append({"name": f"Block {n} Slot {m}", "now": [cell(k) for k in now],
                                 "then": [cell(k, k != o) for k, o in zip(then, now)]})
                dialog = {"rows": rows,
                          "changed": sum(c["changed"] for r in rows for c in r["then"]),
                          "weeks": [(e["label"], e["weeks"], weeks(n, after[e["key"]]))
                                    for e, n in zip(show_list, eps_left)]}
        return render_template(
            "index.html", raw=raw, blocks=blocks, error=error, kinds=config.KINDS,
            day_start=day_start.strftime("%H:%M"), left=_hm(config.DAY - total),
            choices=choices, known={k for k, _ in choices}, add=add, show_list=show_list,
            dialog=dialog, refused=refused, days=[d.title() for d in config.WEEKDAYS],
            problems=problems(missing, schedule)), status

    @app.get("/")
    def index():
        return render(read_raw())

    @app.post("/")
    def post():
        raw = _from_form(request.form, read_raw())
        action = request.form.get("action", "save")
        if action == "distribute":
            return render(raw, preview=True)
        if action == "replace":  # the dialog's confirm: overwrite every distributed cell, save
            try:
                new = plan(raw, scan(raw)[2])
            except distributor.Refused as e:
                return render(raw, refused=str(e))
            for (_, _, s), rules in zip(distributed(raw), new):
                s["weekdays"] = {d: dict(r) for d, r in zip(config.WEEKDAYS, rules)}
            action = "save"
        if action not in ("save", "rebuild"):
            _apply(raw, action, request.form.get("sl.add", ""))
            return render(raw)
        try:
            config.save(service.config_path, raw)
        except config.ConfigError as e:
            return render(raw, error=str(e), status=400)
        service.on_save()
        if action == "rebuild":
            service.rebuild_today()
        return redirect("/", 303)

    return app
