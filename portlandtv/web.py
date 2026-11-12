"""Web app: one server-rendered page that edits the YAML through Config.

Buttons post the whole form with an `action`. Every action except `save` and
`replace` (Distribute's confirm) only re-renders the edited draft; those two
validate and write the YAML.
"""
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, Request, redirect, render_template, request
from markupsafe import escape

from portlandtv import config, distributor, draft, library, review, store

# Show List colours, by entry position; off-list rules are grey
PALETTE = ("#cfe3ff", "#d6f5d6", "#ffe1c4", "#ecd9ff", "#ffd6e0", "#d4f1f4", "#fff3b0", "#e2e2ff")
OFF_LIST = "#e6e6e6"


def _hm(seconds):
    sign = "−" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 3600}h{seconds % 3600 // 60:02}"


def _form_rule(value):
    """'show:X' -> {show: X}; '' -> None."""
    kind, _, name = value.partition(":")
    return {kind: name} if kind else None


def _block(length, repeat, slots):
    """A raw Block from form text; `repeat` is stored as a number when it is one."""
    repeat = repeat.strip()
    return {"length": length.strip(), "repeat": int(repeat) if repeat.isdigit() else repeat,
            "slots": slots}


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
            if s + ".mon" in form:
                slots.append(draft.distributed_slot(
                    [_form_rule(form[f"{s}.{d}"]) for d in config.WEEKDAYS]))
            else:
                slots.append(draft.fixed_slot(_form_rule(form[s + ".rule"])))
            j += 1
        blocks.append(_block(form[f"b{i}.length"], form[f"b{i}.repeat"], slots))
        i += 1
    entries, k = [], 0
    while f"sl{k}" in form:
        entries.append(_form_rule(form[f"sl{k}"]))
        k += 1
    groups, renames, i = {}, [], 0
    while f"g{i}.name" in form:
        members, j = [], 0
        while f"g{i}.m{j}" in form:
            members.append(form[f"g{i}.m{j}"])
            j += 1
        was, name = form.get(f"g{i}.was", ""), form[f"g{i}.name"]
        groups[was or name.strip()] = members
        if was:
            renames.append((was, name))
        i += 1
    out = {**raw, "libraries": libs, "day_schedule": blocks, "show_list": entries,
           "show_groups": groups}
    for was, name in renames:
        draft.rename_group(out, was, name)
    if "day_start" in form:
        out["day_start"] = form["day_start"].strip()
    return out


def _apply(raw, action, form):
    """One button's edit of the Draft: `verb:i:j` picks the Block, Slot, entry, Show Group
    (by position on the page) or Library, and the form gives what the add dropdowns picked."""
    verb, _, args = action.partition(":")
    idx = [int(a) for a in args.split(":") if a]
    step = -1 if verb.startswith("up-") else 1
    names = list(raw["show_groups"])
    to = form.get("bal.to", "")
    edits = {
        "add-block": lambda: draft.add_block(raw),
        "del-block": lambda: draft.delete_block(raw, idx[0]),
        "add-slot": lambda: draft.add_slot(raw, idx[0]),
        "add-dslot": lambda: draft.add_slot(raw, idx[0], distributed=True),
        "mode-slot": lambda: draft.switch_mode(raw, *idx),
        "del-slot": lambda: draft.delete_slot(raw, *idx),
        "move-slot": lambda: draft.move_slot(raw, *idx, step),
        "move-entry": lambda: draft.move_entry(raw, idx[0], step),
        "del-entry": lambda: draft.delete_entry(raw, idx[0]),
        "add-entry": lambda: draft.add_entries(raw, map(_form_rule, form.getlist("sl.add"))),
        "add-group": lambda: draft.add_group(raw, form.get("g.new", "")),
        "del-group": lambda: draft.delete_group(raw, names[idx[0]]),
        "add-member": lambda: draft.add_member(raw, names[idx[0]], form.get(f"g{idx[0]}.add", "")),
        "del-member": lambda: draft.delete_member(raw, names[idx[0]], idx[1]),
        "move-member": lambda: draft.move_member(raw, names[idx[0]], idx[1], step),
        "add-lib": lambda: draft.add_library(raw),
        "del-lib": lambda: draft.delete_library(raw, idx[0]),
        "regroup": lambda: draft.regroup(raw, form["bal.show"], int(form["bal.from"]),
                                         int(to) if to else None),
    }
    edits.get(re.sub(r"^(up|down)-", "move-", verb), lambda: None)()


class _Request(Request):
    # the page posts every grid cell; Werkzeug's default 1000 fields refuses a big schedule (413)
    max_form_parts = 100_000


def create_app(service):
    app = Flask(__name__)
    app.request_class = _Request

    def problems(missing_libs, schedule):
        out = list(schedule)
        if service.error:
            out.append(f"Generation error: {service.error} (retrying)")
        if service.push_error:
            out.append(f"ffplayout push problem: {service.push_error} (retrying)")
        out += [f"Library missing: {p}" for p in missing_libs]
        if service.measurer.left:
            out.append(f"Measuring video lengths: {service.measurer.left} files left."
                       " Block lengths are partial until it finishes; reload to update.")
        out += [f"Unplayable: {p}" for p in service.unplayable]
        # today's and a generated tomorrow's dropped/flagged Slots and filler
        for date in [service.today, service.today + timedelta(days=1)] if service.today else []:
            record = store.read_json(service.paths.day(date), {})
            out += [f"{date}: {p}" for p in record.get("problems") or []]
            out += [f"Filler never fits: {p}" for p in record.get("never_fits") or []]
        return out

    def stream_url():
        """ffplayout's HLS stream on the host this page was opened on (install.sh's port)."""
        host = urlparse(request.host_url).hostname
        return f"http://{f'[{host}]' if ':' in host else host}:8787/public/1/live/stream.m3u8"

    def scan(raw):
        """-> (prober, Catalogue) of the draft's Libraries."""
        service.measurer.want(raw["libraries"])
        # lengths measured so far only: a page load never waits on ffprobe
        prober = library.CachedProber(service.prober, service.paths.durations, measure=False)
        return prober, library.catalogue(raw["libraries"], prober)

    def reviewed(raw):
        """-> (the draft's Catalogue, its Review)."""
        prober, found = scan(raw)
        state = store.read_json(service.paths.state, {"shows": {}})
        return found, review.review(raw, found.shows, found.movies, prober.duration, state)

    def render(raw, error=None, status=200, preview=False, refused=None):
        try:
            day_start = config.parse_day_start(raw.get("day_start", "06:00"))
        except config.ConfigError as e:
            error, day_start = error or str(e), config.parse_day_start("06:00")
        found, rv = reviewed(raw)
        shows = found.shows
        groups = raw.get("show_groups") or {}
        entries = [e.key for e in rv.entries]
        colour = {e: PALETTE[i % len(PALETTE)] for i, e in enumerate(entries)}
        choices = ([(f"show:{n}", n) for n in shows]
                   + [(f"group:{n}", f"Show Group: {n}") for n in groups])
        names = dict(choices)
        add = [(k, t) for k, t in choices if k not in entries]
        choices = ([(k, t if k in entries else f"{t} (not in list)") for k, t in choices]
                   + [("movie:random", "Random movie")])
        start = datetime.combine(datetime.min.date(), day_start)

        def hhmm(seconds):
            return (start + timedelta(seconds=seconds)).strftime("%H:%M")

        def weeks(n, count):
            return f"{n / count:.1f}" if count else "not scheduled"

        def cell(key, changed=False):
            label = "Random movie" if key == "movie:random" else key.partition(":")[2]
            return {"label": names.get(key, label or "— empty"),
                    "colour": colour.get(key, OFF_LIST) if key else "", "changed": changed}

        blocks = []
        for b, br in zip(raw["day_schedule"], rv.blocks):
            length, view_slots = br.length, []
            for fixed, rules in br.slots:
                keys = [review.rule_key(r) for r in rules]
                # cells[d]: that weekday's dropdown value; colours[d]: its Show List colour
                view_slots.append({"fixed": fixed, "cells": keys, "colours": [
                    colour.get(k, OFF_LIST) if k else "" for k in keys]})
            blocks.append({
                "raw": b, "airs": [hhmm(t) for t in br.airs], "slots": view_slots,
                "fill": [{"content": _hm(t), "brk": _hm(length - t) if length else "?",
                          "over": bool(length) and t > length} for t in br.typical],
                "over": bool(length) and max(br.most) > length,
                "typical": _hm(max(br.typical)), "max": _hm(max(br.most))})
        show_list = [{"key": e.key, "label": names.get(e.key, e.key), "colour": colour[e.key],
                      "left": e.left, "cells": e.cells, "weeks": weeks(e.left, e.cells)}
                     for e in rv.entries]
        # balance view: a column per entry, a segment per show, heights in episodes left
        balance = [{**row, "segments": e.members} for row, e in zip(show_list, rv.entries)]
        tallest = max((e.left for e in rv.entries), default=0) or 1
        dialog = None
        if preview:
            try:
                pv = review.preview(raw, rv)
            except distributor.Refused as e:
                refused = str(e)
            else:
                dialog = {"rows": [{"name": f"Block {n} Slot {m}", "now": [cell(k) for k in now],
                                    "then": [cell(k, k != o) for k, o in zip(then, now)]}
                                   for n, m, now, then in pv.rows],
                          "changed": pv.changed,
                          "weeks": [(row["label"], row["weeks"], weeks(e.left, after))
                                    for row, e, after in zip(show_list, rv.entries, pv.cells)]}
        return render_template(
            "index.html", raw=raw, blocks=blocks, error=error, kinds=config.KINDS,
            day_start=day_start.strftime("%H:%M"), left=_hm(config.DAY - rv.assigned),
            choices=choices, known={k for k, _ in choices}, add=add, show_list=show_list,
            groups=[{"name": n, "members": ms, "add": [s for s in shows if s not in ms]}
                    for n, ms in groups.items()],
            dialog=dialog, refused=refused, days=[d.title() for d in config.WEEKDAYS],
            stream=stream_url(), balance=balance, tallest=tallest,
            problems=problems(found.missing, rv.problems)), status

    @app.get("/")
    def index():
        raw = config.read_raw(service.config_path)
        try:
            return render(raw)
        except Exception as e:  # a hand edit the editor can't show: say why, so it can be fixed by hand
            try:
                config.parse(raw)
            except config.ConfigError as bad:
                e = bad
            return (f"<h1>PortlandTV</h1><p>The config file can't be shown in the editor: "
                    f"{escape(str(e))}</p><p>Fix {escape(service.config_path)} by hand.</p>")

    @app.get("/folders")
    def folders():
        """A folder's subfolders for the Library picker, as the service user sees them.
        A path that doesn't exist opens its nearest existing parent."""
        path = os.path.abspath(request.args.get("path") or "/")
        while not os.path.isdir(path):
            path = os.path.dirname(path)
        parent = os.path.dirname(path)
        out = {"path": path, "parent": parent if parent != path else None, "dirs": []}
        try:
            names = sorted((e.name for e in os.scandir(path)
                            if e.is_dir() and not e.name.startswith(".")), key=str.lower)
        except OSError as e:  # e.g. the service user may not open it: what "Library missing" means
            out["error"] = f"Can't open this folder: {e.strerror}"
            return out
        out["dirs"] = [{"name": n, "path": os.path.join(path, n)} for n in names]
        return out

    @app.post("/")
    def post():
        # no login (spec), but a page on another site mustn't post edits from the operator's browser
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return "Cross-site edit refused", 403
        raw = _from_form(request.form, config.read_raw(service.config_path))
        action = request.form.get("action", "save")
        if action == "distribute":
            return render(raw, preview=True)
        if action == "replace":  # the dialog's confirm: overwrite every distributed cell, save
            try:
                draft.distribute(raw)
            except distributor.Refused as e:
                return render(raw, refused=str(e))
            action = "save"
        if action == "auto-sort":
            draft.auto_sort(raw, [e.left for e in reviewed(raw)[1].entries])
            return render(raw)
        if action not in ("save", "rebuild"):
            _apply(raw, action, request.form)
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
