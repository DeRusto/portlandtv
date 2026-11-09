"""Web app: one server-rendered page that edits the YAML through Config.

Buttons post the whole form with an `action`. Every action except `save` and
`replace` (Distribute's confirm) only re-renders the edited draft; those two
validate and write the YAML.
"""
import collections
import os
import statistics
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, redirect, render_template, request
from markupsafe import escape

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
    if not isinstance(rule, dict) or len(rule) != 1:
        return f"invalid:{rule}"  # a hand-edited rule; the page still renders so it can be fixed
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
            if s + ".mon" in form:
                slots.append(config.distributed_slot(
                    [_form_rule(form[f"{s}.{d}"]) for d in config.WEEKDAYS]))
            else:
                slots.append(config.fixed_slot(_form_rule(form[s + ".rule"])))
            j += 1
        blocks.append(config.block(form[f"b{i}.length"], form[f"b{i}.repeat"], slots))
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
        was, name = form.get(f"g{i}.was", ""), form[f"g{i}.name"].strip()
        if not name or name in groups:  # an empty or taken name keeps the old one
            name = was
        if was and name != was:
            renames.append((was, name))
        groups[name] = members
        i += 1
    out = {**raw, "libraries": libs, "day_schedule": blocks, "show_list": entries,
           "show_groups": groups}
    for was, name in renames:
        config.rename_group(out, was, name)
    if "day_start" in form:
        out["day_start"] = form["day_start"].strip()
    return out


def _move(items, j, k):
    if 0 <= k < len(items):
        items[j], items[k] = items[k], items[j]


def _apply(raw, action, form):
    """Edit the draft for one button: add/del/up/down of Blocks, Slots, Libraries,
    Show List entries and Show Groups and their shows (picked in the form's add dropdowns)."""
    verb, _, args = action.partition(":")
    idx = [int(a) for a in args.split(":") if a]
    blocks, libs, entries = raw["day_schedule"], raw["libraries"], raw["show_list"]
    groups = raw["show_groups"]
    names = list(groups)
    if verb == "add-block":
        blocks.append(config.new_block())
    elif verb == "del-block":
        del blocks[idx[0]]
    elif verb == "add-slot":
        blocks[idx[0]]["slots"].append(config.fixed_slot(None))
    elif verb == "add-dslot":  # a new distributed Slot starts empty
        blocks[idx[0]]["slots"].append(config.distributed_slot([]))
    elif verb == "mode-slot":  # distributed -> fixed keeps only Monday: the page confirms
        slots = blocks[idx[0]]["slots"]
        slots[idx[1]] = config.switch_mode(slots[idx[1]])
    elif verb == "del-slot":
        del blocks[idx[0]]["slots"][idx[1]]
    elif verb in ("up-slot", "down-slot"):
        j = idx[1]
        _move(blocks[idx[0]]["slots"], j, j - 1 if verb == "up-slot" else j + 1)
    elif verb in ("up-entry", "down-entry"):
        _move(entries, idx[0], idx[0] - 1 if verb == "up-entry" else idx[0] + 1)
    elif verb == "del-entry":  # the grid is left as it is
        del entries[idx[0]]
    elif verb == "add-entry":  # every ticked show and Show Group
        for rule in map(_form_rule, form.getlist("sl.add")):
            if rule and rule not in entries:
                entries.append(rule)
    elif verb == "add-group" and (name := form.get("g.new", "").strip()) and name not in groups:
        groups[name] = []
    elif verb == "del-group":  # Slots and entries naming it are flagged, not changed
        del groups[names[idx[0]]]
    elif verb == "add-member" and (show := form.get(f"g{idx[0]}.add", ""))             and show not in groups[names[idx[0]]]:
        groups[names[idx[0]]].append(show)
    elif verb == "del-member":
        del groups[names[idx[0]]][idx[1]]
    elif verb in ("up-member", "down-member"):
        j = idx[1]
        _move(groups[names[idx[0]]], j, j - 1 if verb == "up-member" else j + 1)
    elif verb == "add-lib":
        libs.append({"path": "", "kind": "shows"})
    elif verb == "del-lib":
        del libs[idx[0]]
    elif verb == "regroup":  # a show dragged in the balance view
        to = form.get("bal.to", "")
        _regroup(raw, form["bal.show"], int(form["bal.from"]), int(to) if to else None)


def _new_group(groups):
    return next(f"Group {n}" for n in range(1, len(groups) + 2) if f"Group {n}" not in groups)


def _regroup(raw, show, src, dst):
    """Move `show` out of Show List entry `src` into entry `dst`, or into its own entry when
    `dst` is None. Dropping it on a show makes a new Show Group of the two in its place; a
    Show Group left with no shows leaves the Show List (Slots naming it are flagged)."""
    entries, groups = raw["show_list"], raw["show_groups"]
    target = None if dst is None else entries[dst]
    source = entries[src]
    if target is source or (target is None and "show" in source):
        return
    if target is None:  # before `source` may go, so it lands just after it
        entries.insert(src + 1, {"show": show})
    if "group" in source:
        members = groups[source["group"]]
        members.remove(show)
        if not members:
            del groups[source["group"]]
            entries.remove(source)
    else:
        entries.remove(source)
    if target is None:
        pass
    elif "group" in target:
        if show not in groups[target["group"]]:
            groups[target["group"]].append(show)
    else:
        name = _new_group(groups)
        groups[name] = [target["show"], show]
        entries[entries.index(target)] = {"group": name}


def _auto_sort(raw, left):
    """Pack the Show List's single shows (episodes left in `left`, per entry) into Show
    Groups lasting no longer than its longest entry: largest first, each into the first
    existing or new group it fits, else a new one. A new group of one stays a single show."""
    entries, groups = raw["show_list"], raw["show_groups"]
    target = max(left, default=0)
    # [episodes, entry index, single shows' entry indexes]: Show List groups first
    bins = [[left[i], i, []] for i, e in enumerate(entries) if "group" in e]
    singles = sorted((i for i, e in enumerate(entries) if "show" in e), key=lambda i: -left[i])
    for i in singles:
        fit = next((b for b in bins if b[0] + left[i] <= target), None)
        if fit:
            fit[0] += left[i]
            fit[2].append(i)
        else:
            bins.append([left[i], i, []])
    gone = set()
    for _, at, added in bins:
        if not added:
            continue
        if "show" in entries[at]:  # a new group, in its largest show's place
            name = _new_group(groups)
            groups[name] = [entries[at]["show"]]
            entries[at] = {"group": name}
        groups[entries[at]["group"]] += [entries[i]["show"] for i in added]
        gone.update(added)
    entries[:] = [e for i, e in enumerate(entries) if i not in gone]


def create_app(service):
    app = Flask(__name__)

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
        """-> (missing Library folders, prober, shows, movies) for the draft's Libraries."""
        libs = [lib for lib in raw["libraries"] if lib.get("path")]
        missing = [lib["path"] for lib in libs if not os.path.isdir(lib["path"])]
        found = [lib for lib in libs if lib["path"] not in missing]
        service.measurer.want(found)
        # lengths measured so far only: a page load never waits on ffprobe
        prober = library.CachedProber(service.prober, service.paths.durations, measure=False)
        shows, _ = library.scan_shows(found, prober)
        return missing, prober, shows, library.scan_movies(found)

    def remaining(raw, shows):
        """Episodes left per Show List entry; a Show Group sums its members."""
        state = store.read_json(service.paths.state, {"shows": {}})
        return [slots.episodes_left(e, shows, raw.get("show_groups") or {}, state)
                for e in raw["show_list"]]

    def distributed(raw):
        """[(Block n, Slot m, Slot)] of the distributed Slots, in Distribute's cell order."""
        return [(n, m, s) for n, b in enumerate(raw["day_schedule"], 1)
                for m, s in enumerate(b.get("slots") or [], 1) if not config.is_fixed(s)]

    def plan(raw):
        """New Weekday Rules per distributed Slot; raises distributor.Refused."""
        return distributor.distribute(raw["show_list"], len(distributed(raw)))

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
                length, repeat = config.length_repeat(b)
            except config.ConfigError:
                length, repeat = None, 0
            view = {"raw": b, "airs": [], "slots": []}
            typical, most = [0] * 7, [0] * 7  # content per weekday
            if length:
                total += length * repeat
                for _ in range(repeat):
                    view["airs"].append(t.strftime("%H:%M"))
                    t += timedelta(seconds=length)
            for m, s in enumerate(b.get("slots") or [], 1):
                fixed, rules = config.is_fixed(s), config.slot_rules(s)
                for d, rule in enumerate(rules):
                    lengths = [x for x in map(prober.duration,
                                              slots.candidates(rule, shows, movies, groups)) if x]
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
                if empty and fixed:
                    schedule.append(f"Block {n} Slot {m} is empty every day: skipped")
                elif empty:
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
        schedule += [f"Show List: {names.get(e, e)} has no cells on the grid"
                     for e in entries if not cells[e]]
        schedule += [f"{names.get(k, k)} is on the grid but not in the Show List"
                     for k in off_list]

        def weeks(n, count):
            return f"{n / count:.1f}" if count else "not scheduled"

        def cell(key, changed=False):
            label = "Random movie" if key == "movie:random" else key.partition(":")[2]
            return {"label": names.get(key, label or "— empty"),
                    "colour": colour.get(key, OFF_LIST) if key else "", "changed": changed}

        show_list = [{"key": e, "label": names.get(e, e), "colour": colour[e], "left": n,
                      "cells": cells[e], "weeks": weeks(n, cells[e])}
                     for e, n in zip(entries, eps_left)]
        # balance view: a column per entry, a segment per show, heights in episodes left
        state = store.read_json(service.paths.state, {"shows": {}})
        balance = []
        for rule, e in zip(raw["show_list"], show_list):
            members = (groups.get(rule["group"], []) if "group" in rule else [rule["show"]]) \
                if isinstance(rule, dict) and rule.keys() & {"group", "show"} else []
            balance.append({**e, "segments": [
                (m, slots.episodes_left({"show": m}, shows, groups, state)) for m in members]})
        tallest = max((e["left"] for e in show_list), default=0) or 1
        dialog = None
        if preview:
            try:
                new = plan(raw)
            except distributor.Refused as e:
                refused = str(e)
            else:
                rows, after = [], cells.copy()
                for (n, m, s), rules in zip(distributed(raw), new):
                    now = [_rule_key(r) for r in config.slot_rules(s)]
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
            groups=[{"name": n, "members": ms, "add": [s for s in shows if s not in ms]}
                    for n, ms in groups.items()],
            dialog=dialog, refused=refused, days=[d.title() for d in config.WEEKDAYS],
            stream=stream_url(), balance=balance, tallest=tallest,
            problems=problems(missing, schedule)), status

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
                new = plan(raw)
            except distributor.Refused as e:
                return render(raw, refused=str(e))
            for (_, _, s), rules in zip(distributed(raw), new):
                s.update(config.distributed_slot(rules))
            action = "save"
        if action == "auto-sort":
            _auto_sort(raw, remaining(raw, scan(raw)[2]))
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
