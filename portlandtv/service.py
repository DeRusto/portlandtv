"""Scheduler, the service core: each tick generates the Broadcast Days that are due."""
import os
import threading
from datetime import datetime, timedelta, timezone

from portlandtv import cards, config, day, library, records, store

LEAD = timedelta(hours=1)


class Service:
    def __init__(self, config_path, playlist_dir, prober, clock, ffplayout):
        self.config_path = config_path
        self.playlist_dir = playlist_dir
        self.prober = prober
        self.measurer = library.Measurer(prober, store.Paths(config_path).durations)
        self.clock = clock
        self.ffplayout = ffplayout
        self.paths = store.Paths(config_path)
        self.records = records.Records(self.paths.root)
        self.error = None  # last generation error, for the UI
        self.push_error = None  # last failed push to ffplayout, for the UI
        self.today = None  # date the current Broadcast Day started on, as of the last tick
        self.unplayable = []  # files the last scan left out, for the UI
        self._lock = threading.RLock()  # the tick thread and web requests both build
        config.ensure(config_path)

    def tick(self):
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                start = self._start(cfg)
                self.today = start.date()
                self._ensure(cfg, start.date())
                if self.clock.now() >= start + timedelta(days=1) - LEAD:
                    self._ensure(cfg, start.date() + timedelta(days=1))
                self.error = None
            except Exception as e:  # recorded for the UI; the next tick retries
                self.error = str(e)
                return
            try:
                self._push_day_start(cfg)
                self.push_error = None
            except Exception as e:
                self.push_error = str(e)

    def on_save(self, renames=()):
        """After the YAML is saved: a generated day that hasn't started is regenerated
        from its pre-generation state; today stays as it is. `renames`: the Show Groups
        renamed, as (old, new), whose progress carries over."""
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                today = self._start(cfg).date()
                # yesterday's record too: an unbuilt today starts from its state_after
                days = [today + timedelta(days=n) for n in (-1, 0, 1)]
                for old, new in renames:
                    self.records.rename_group(old, new, days)
                self.records.unbuild(today + timedelta(days=1))
            except Exception as e:
                self.error = str(e)
                return
            self.tick()

    def rebuild_today(self):
        """Re-run today's build with the saved YAML. Slots unchanged since today was
        built keep today's item; new or changed ones are filled fresh."""
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                today = self._start(cfg).date()
                record = self.records.get(today)
                if record:
                    self.records.unbuild(today + timedelta(days=1))  # it follows on from today
                    self._build(cfg, today, record.state_before, record.picked)
            except Exception as e:
                self.error = str(e)
                return
            self.tick()

    def _start(self, cfg):
        """When the current Broadcast Day started."""
        now = self.clock.now()
        start = datetime.combine(now.date(), cfg["day_start"], timezone.utc)
        return start - timedelta(days=1) if now < start else start

    def _push_day_start(self, cfg):
        """Push the YAML's day_start to ffplayout when it differs from the last push."""
        hhmm = cfg["day_start"].strftime("%H:%M")
        pushed = store.read_json(self.paths.ffplayout, {})
        if pushed.get("day_start") != hhmm:
            self.ffplayout.set_day_start(hhmm)
            store.write_json(self.paths.ffplayout, {**pushed, "day_start": hhmm})

    def _output_size(self):
        """ffplayout's output size; the last one known (else 1080p) while it is unreachable."""
        known = store.read_json(self.paths.ffplayout, {})
        try:
            size = list(self.ffplayout.output_size())
        except Exception:  # cards are still drawn; ffplayout rescales them
            return tuple(known.get("size", (1920, 1080)))
        if known.get("size") != size:
            store.write_json(self.paths.ffplayout, {**known, "size": size})
        return tuple(size)

    def _ensure(self, cfg, date):
        """Generate the Broadcast Day starting on `date` unless it already was."""
        if self.records.get(date) is None:
            self._build(cfg, date, self.records.state_before(date))

    def _build(self, cfg, date, before, kept=()):
        """Generate the Broadcast Day starting on `date` from the state `before` it."""
        prober = library.CachedProber(self.prober, self.paths.durations)
        found = library.catalogue(cfg["libraries"], prober)
        prober.save()
        self.unplayable = found.unplayable
        if found.missing:  # a build never airs a Library silently empty
            raise FileNotFoundError(f"Library missing: {found.missing[0]}")
        shows, filler, movies = found.shows, found.filler, found.movies
        built = day.build(
            config.on_weekday(cfg, date.weekday()), date, shows, before, prober,
            self.paths.card, filler, movies, kept, self.records.get(date - timedelta(days=1)))
        size = self._output_size()
        show_of = {p: name for name, eps in shows.items() for p in eps}

        def render(path, content):
            if "items" in content:
                cards.render(path, [cards.describe(p, show_of, movies) for p in content["items"]],
                             size)
            else:  # a schedule display frame
                cards.render_schedule(path, {**content, "rows": [
                    {"time": r["time"], **cards.describe(r["path"], show_of, movies),
                     "state": r["state"]} for r in content["rows"]]}, size)

        # shortcut: cards a rebuild no longer airs stay on disk; prune old days' card
        # folders if they pile up
        for path, content in built.cards.items():
            render(path, content)
        d = date.isoformat()
        # atomic, so ffplayout reloads a whole playlist at its next clip boundary
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": built.program})
        # the day before's End Cards were placeholders until this day's items were known;
        # redrawn before the commit, so a crash in between just builds the day again
        for path, content in built.redraw.items():
            render(path, content)
        self.records.commit(date, before, built)
