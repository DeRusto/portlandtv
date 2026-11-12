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

    def on_save(self):
        """After the YAML is saved: a generated day that hasn't started is regenerated
        from its pre-generation state; today stays as it is."""
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                self.records.unbuild(self._start(cfg).date() + timedelta(days=1))
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
        size = self._output_size()
        show_of = {p: name for name, eps in shows.items() for p in eps}

        def describe(path):
            return cards.describe(path, show_of, movies)

        built = day.build(
            config.on_weekday(cfg, date.weekday()), shows, before, prober,
            self._card_writer(describe, date, size), filler, movies,
            self._schedule_writer(describe, date, cfg["day_start"], size), kept)
        sequence = built.sequence
        d = date.isoformat()
        # atomic, so ffplayout reloads a whole playlist at its next clip boundary
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": built.program})
        self.records.commit(date, before, built)
        # the previous day's last cards were placeholders until this day's items were known
        prev = self.records.get(date - timedelta(days=1))
        if prev and prev.tail is not None:
            tail = prev.tail
            prev_date = date - timedelta(days=1)
            prev_card = self._card_writer(describe, prev_date, size)
            # end-(n) shows the day's items from len(tail) - n + 1; n reaches len(tail) + 1
            # when a Break airs before the day's first item (an empty first Block)
            for n in range(1, min(len(tail) + 1, day.AHEAD) + 1):
                if os.path.exists(self.paths.card(prev_date, day.end_card(n))):
                    t = len(tail) - n
                    prev_card(day.end_card(n), (tail + sequence)[t + 1:t + 1 + day.AHEAD])

    def _card_writer(self, describe, date, size):
        """card(name, item paths) -> path of that day's card, rendered once per name."""
        written = set()

        def card(name, paths):
            path = self.paths.card(date, name)
            if name not in written:
                cards.render(path, [describe(p) for p in paths], size)
                written.add(name)
            return path
        return card

    def _schedule_writer(self, describe, date, day_start, size):
        """schedule(name, rows, upcoming, span) -> that Airing's schedule display frames."""
        start = datetime.combine(date, day_start, timezone.utc)

        def hhmm(seconds):
            return (start + timedelta(seconds=seconds)).strftime("%H:%M")

        def schedule(name, rows, upcoming, span):
            entries = [{"time": hhmm(t), **describe(p),
                        "state": "aired" if i < upcoming else
                        "up_next" if i == upcoming else "later"}
                       for i, (t, p) in enumerate(rows)]
            pages = [entries[i:i + day.FRAME_ROWS] for i in range(0, len(entries), day.FRAME_ROWS)]
            paths = []
            for n, page in enumerate(pages, 1):
                path = self.paths.card(date, f"sched-{name}-{n}")
                cards.render_schedule(path, {
                    "heading": "TODAY ON PORTLAND TV",
                    "range": f"{hhmm(span[0])}–{hhmm(span[1])} UTC",
                    "page": f"{n}/{len(pages)}", "rows": page}, size)
                paths.append(path)
            return paths
        return schedule
