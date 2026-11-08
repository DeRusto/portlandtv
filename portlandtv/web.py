"""Web app: one server-rendered page that edits the YAML through Config.

Buttons post the whole form with an `action`. Every action except `save` only
re-renders the edited draft; `save` validates and writes the YAML.
"""
import glob
import os
import statistics
from datetime import datetime, timedelta

import yaml
from flask import Flask, redirect, render_template, request

from portlandtv import config, library, store


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


def _from_form(form, raw):
    """The posted form over `raw` (keys the form doesn't edit are kept)."""
    libs, i = [], 0
    while f"lib{i}.path" in form:
        libs.append({"path": form[f"lib{i}.path"].strip(), "kind": form[f"lib{i}.kind"]})
        i += 1
    blocks, i = [], 0
    while f"b{i}.length" in form:
        slots, j = [], 0
        while f"b{i}.s{j}.rule" in form:
            kind, _, name = form[f"b{i}.s{j}.rule"].partition(":")
            slots.append({"rule": {kind: name}} if kind else {})
            j += 1
        repeat = form[f"b{i}.repeat"].strip()
        blocks.append({"length": form[f"b{i}.length"].strip(),
                       "repeat": int(repeat) if repeat.isdigit() else repeat,
                       "slots": slots})
        i += 1
    return {**raw, "libraries": libs, "day_schedule": blocks}


def _apply(raw, action):
    """Edit the draft for one button: add/del/up/down of Blocks, Slots, Libraries."""
    verb, _, args = action.partition(":")
    idx = [int(a) for a in args.split(":") if a]
    blocks, libs = raw["day_schedule"], raw["libraries"]
    if verb == "add-block":
        blocks.append({"length": "1h", "repeat": 1, "slots": [{}]})
    elif verb == "del-block":
        del blocks[idx[0]]
    elif verb == "add-slot":
        blocks[idx[0]]["slots"].append({})
    elif verb == "del-slot":
        del blocks[idx[0]]["slots"][idx[1]]
    elif verb in ("up-slot", "down-slot"):
        slots, j = blocks[idx[0]]["slots"], idx[1]
        k = j - 1 if verb == "up-slot" else j + 1
        if 0 <= k < len(slots):
            slots[j], slots[k] = slots[k], slots[j]
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
                "day_schedule": raw.get("day_schedule") or []}

    def durations(rule, shows, groups, movies, prober):
        """Every length the rule can pick, in seconds."""
        if "show" in rule:
            paths = shows.get(rule["show"], [])
        elif "group" in rule:
            paths = [p for n in groups.get(rule["group"]) or [] for p in shows.get(n, [])]
        else:
            paths = movies
        return [d for d in map(prober.duration, paths) if d]

    def problems(missing_libs):
        out = []
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

    def render(raw, error=None, status=200):
        try:
            day_start = config.parse_day_start(raw.get("day_start", "06:00"))
        except config.ConfigError as e:
            error, day_start = error or str(e), config.parse_day_start("06:00")
        libs = [lib for lib in raw["libraries"] if lib.get("path")]
        missing = [lib["path"] for lib in libs if not os.path.isdir(lib["path"])]
        found = [lib for lib in libs if lib["path"] not in missing]
        prober = library.CachedProber(service.prober, os.path.join(data_dir, "durations.json"))
        shows, _ = library.scan_shows(found, prober)
        movies = library.scan_movies(found)
        groups = raw.get("show_groups") or {}
        t = datetime.combine(datetime.min.date(), day_start)
        blocks, total = [], 0
        for b in raw["day_schedule"]:
            try:
                length = config.parse_length(b.get("length"))
                repeat = int(b.get("repeat", 1))
            except (ValueError, TypeError):
                length, repeat = None, 0
            view = {"raw": b, "airs": [], "slots": [], "typical": 0, "max": 0}
            if length:
                total += length * repeat
                for _ in range(repeat):
                    view["airs"].append(t.strftime("%H:%M"))
                    t += timedelta(seconds=length)
            for s in b.get("slots") or []:
                rule = s.get("rule") or {}
                lengths = durations(rule, shows, groups, movies, prober)
                if lengths:
                    view["typical"] += statistics.median(lengths)
                    view["max"] += max(lengths)
                view["slots"].append(_rule_key(rule))
            view["over"] = bool(length) and view["max"] > length
            view["typical"], view["max"] = _hm(view["typical"]), _hm(view["max"])
            blocks.append(view)
        prober.save()
        choices = ([(f"show:{n}", n) for n in shows]
                   + [(f"group:{n}", f"Show Group: {n}") for n in groups]
                   + [("movie:random", "Random movie")])
        return render_template(
            "index.html", raw=raw, blocks=blocks, error=error, kinds=config.KINDS,
            day_start=day_start.strftime("%H:%M"), left=_hm(config.DAY - total),
            choices=choices, known={k for k, _ in choices},
            problems=problems(missing)), status

    @app.get("/")
    def index():
        return render(read_raw())

    @app.post("/")
    def post():
        raw = _from_form(request.form, read_raw())
        action = request.form.get("action", "save")
        if action not in ("save", "rebuild"):
            _apply(raw, action)
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
