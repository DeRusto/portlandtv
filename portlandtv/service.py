"""Scheduler, the service core: each tick generates the Broadcast Days that are due."""
import os
import threading
from datetime import datetime, timedelta, timezone

from portlandtv import cards, config, day, library, store

LEAD = timedelta(hours=1)


class Service:
    def __init__(self, config_path, playlist_dir, prober, clock, ffplayout):
        self.config_path = config_path
        self.playlist_dir = playlist_dir
        self.prober = prober
        self.clock = clock
        self.ffplayout = ffplayout
        self.data_dir = os.path.dirname(os.path.abspath(config_path))
        self.state_path = os.path.join(self.data_dir, "state.json")
        self.error = None  # last generation error, for the UI
        self.unplayable = []  # files the last scan left out, for the UI
        self._lock = threading.RLock()  # the tick thread and web requests both build

    def tick(self):
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                start = self._start(cfg)
                self._ensure(cfg, start.date())
                if self.clock.now() >= start + timedelta(days=1) - LEAD:
                    self._ensure(cfg, start.date() + timedelta(days=1))
                self._push_day_start(cfg)
                self.error = None
            except Exception as e:  # recorded for the UI; the next tick retries
                self.error = str(e)

    def on_save(self):
        """After the YAML is saved: a generated day that hasn't started is regenerated
        from its pre-generation state; today stays as it is."""
        with self._lock:
            try:
                cfg = config.load(self.config_path)
                self._unbuild(self._start(cfg).date() + timedelta(days=1))
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
                record = store.read_json(self._day_record_path(today), None)
                if record:
                    self._unbuild(today + timedelta(days=1))  # it follows on from today
                    self._build(cfg, today, record["state_before"], record.get("picked", ()))
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
        path = os.path.join(self.data_dir, "ffplayout.json")
        pushed = store.read_json(path, {})
        if pushed.get("day_start") != hhmm:
            self.ffplayout.set_day_start(hhmm)
            store.write_json(path, {**pushed, "day_start": hhmm})

    def _output_size(self):
        """ffplayout's output size; the last one known (else 1080p) while it is unreachable."""
        path = os.path.join(self.data_dir, "ffplayout.json")
        known = store.read_json(path, {})
        try:
            size = list(self.ffplayout.output_size())
        except Exception:  # cards are still drawn; ffplayout rescales them
            return tuple(known.get("size", (1920, 1080)))
        if known.get("size") != size:
            store.write_json(path, {**known, "size": size})
        return tuple(size)

    def _unbuild(self, date):
        """Forget the generated day `date`, putting the state back to before it."""
        record_path = self._day_record_path(date)
        record = store.read_json(record_path, None)
        if record:
            store.write_json(self.state_path, record["state_before"])
            os.remove(record_path)

    def _day_record_path(self, date):
        return os.path.join(self.data_dir, "days", f"{date.isoformat()}.json")

    def _ensure(self, cfg, date):
        """Generate the Broadcast Day starting on `date` unless it already was."""
        if not os.path.exists(self._day_record_path(date)):
            self._build(cfg, date, store.read_json(self.state_path, {"shows": {}}))

    def _build(self, cfg, date, before, kept=()):
        """Generate the Broadcast Day starting on `date` from the state `before` it."""
        record_path = self._day_record_path(date)
        prober = library.CachedProber(self.prober, os.path.join(self.data_dir, "durations.json"))
        shows, self.unplayable = library.scan_shows(cfg["libraries"], prober)
        filler, movies = [], []
        for found, paths in ((filler, library.scan_filler(cfg["libraries"])),
                             (movies, library.scan_movies(cfg["libraries"]))):
            for path in paths:
                (found if prober.duration(path) else self.unplayable).append(path)
        prober.save()
        size = self._output_size()
        program, picks, after, never_fits, problems, sequence, picked = day.build(
            config.on_weekday(cfg, date.weekday()), shows, before, prober,
            self._card_writer(shows, movies, date, size), filler, movies,
            self._schedule_writer(shows, movies, date, cfg["day_start"], size), kept)
        d = date.isoformat()
        # atomic, so ffplayout reloads a whole playlist at its next clip boundary
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": program})
        store.write_json(record_path, {"slots": picks, "problems": problems,
                                       "state_before": before, "never_fits": never_fits,
                                       "tail": sequence[-day.AHEAD:], "picked": picked})
        store.write_json(self.state_path, after)
        # the previous day's last cards were placeholders until this day's items were known
        prev = store.read_json(self._day_record_path(date - timedelta(days=1)), {})
        if "tail" in prev:
            tail = prev["tail"]
            prev_date = date - timedelta(days=1)
            prev_card = self._card_writer(shows, movies, prev_date, size)
            # end-(n) shows the day's items from len(tail) - n + 1; n reaches len(tail) + 1
            # when a Break airs before the day's first item (an empty first Block)
            for n in range(1, min(len(tail) + 1, day.AHEAD) + 1):
                if os.path.exists(self._card_path(prev_date, day.end_card(n))):
                    t = len(tail) - n
                    prev_card(day.end_card(n), (tail + sequence)[t + 1:t + 1 + day.AHEAD])

    def _card_path(self, date, name):
        return os.path.join(self.data_dir, "cards", date.isoformat(), name + ".png")

    def _card_writer(self, shows, movies, date, size):
        """card(name, item paths) -> path of that day's card, rendered once per name."""
        show_of = {p: name for name, eps in shows.items() for p in eps}
        written = set()

        def card(name, paths):
            path = self._card_path(date, name)
            if name not in written:
                cards.render(path, [cards.describe(p, show_of, movies) for p in paths], size)
                written.add(name)
            return path
        return card

    def _schedule_writer(self, shows, movies, date, day_start, size):
        """schedule(name, rows, upcoming, span) -> that Airing's schedule display frames."""
        show_of = {p: name for name, eps in shows.items() for p in eps}
        start = datetime.combine(date, day_start, timezone.utc)

        def hhmm(seconds):
            return (start + timedelta(seconds=seconds)).strftime("%H:%M")

        def schedule(name, rows, upcoming, span):
            entries = [{"time": hhmm(t), **cards.describe(p, show_of, movies),
                        "state": "aired" if i < upcoming else
                        "up_next" if i == upcoming else "later"}
                       for i, (t, p) in enumerate(rows)]
            pages = [entries[i:i + day.FRAME_ROWS] for i in range(0, len(entries), day.FRAME_ROWS)]
            paths = []
            for n, page in enumerate(pages, 1):
                path = os.path.join(self.data_dir, "cards", date.isoformat(),
                                    f"sched-{name}-{n}.png")
                cards.render_schedule(path, {
                    "heading": "TODAY ON PORTLAND TV",
                    "range": f"{hhmm(span[0])}–{hhmm(span[1])} UTC",
                    "page": f"{n}/{len(pages)}", "rows": page}, size)
                paths.append(path)
            return paths
        return schedule
