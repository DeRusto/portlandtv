"""Scheduler, the service core: each tick generates the Broadcast Days that are due."""
import os
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

    def tick(self):
        try:
            cfg = config.load(self.config_path)
            now = self.clock.now()
            start = datetime.combine(now.date(), cfg["day_start"], timezone.utc)
            if now < start:
                start -= timedelta(days=1)
            self._ensure(cfg, start.date())
            if now >= start + timedelta(days=1) - LEAD:
                self._ensure(cfg, start.date() + timedelta(days=1))
            self.error = None
        except Exception as e:  # recorded for the UI; the next tick retries
            self.error = str(e)

    def _day_record_path(self, date):
        return os.path.join(self.data_dir, "days", f"{date.isoformat()}.json")

    def _ensure(self, cfg, date):
        """Generate the Broadcast Day starting on `date` unless it already was."""
        record_path = self._day_record_path(date)
        if os.path.exists(record_path):
            return
        before = store.read_json(self.state_path, {"shows": {}})
        prober = library.CachedProber(self.prober, os.path.join(self.data_dir, "durations.json"))
        shows, self.unplayable = library.scan_shows(cfg["libraries"], prober)
        filler, movies = [], []
        for found, paths in ((filler, library.scan_filler(cfg["libraries"])),
                             (movies, library.scan_movies(cfg["libraries"]))):
            for path in paths:
                (found if prober.duration(path) else self.unplayable).append(path)
        prober.save()
        program, picks, after, never_fits, problems, sequence = day.build(
            cfg, shows, before, prober, self._card_writer(shows, movies, date), filler, movies)
        d = date.isoformat()
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": program})
        store.write_json(record_path, {"slots": picks, "problems": problems,
                                       "state_before": before, "never_fits": never_fits,
                                       "tail": sequence[-day.AHEAD:]})
        store.write_json(self.state_path, after)
        # the previous day's last cards were placeholders until this day's items were known
        prev = store.read_json(self._day_record_path(date - timedelta(days=1)), {})
        if "tail" in prev:
            tail = prev["tail"]
            prev_card = self._card_writer(shows, movies, date - timedelta(days=1))
            for n in range(1, len(tail) + 1):
                t = len(tail) - n
                prev_card(day.end_card(n), (tail + sequence)[t + 1:t + 1 + day.AHEAD])

    def _card_writer(self, shows, movies, date):
        """card(name, item paths) -> path of that day's card, rendered once per name."""
        show_of = {p: name for name, eps in shows.items() for p in eps}
        size = self.ffplayout.output_size()
        written = set()

        def card(name, paths):
            path = os.path.join(self.data_dir, "cards", date.isoformat(), name + ".png")
            if name not in written:
                cards.render(path, [cards.describe(p, show_of, movies) for p in paths], size)
                written.add(name)
            return path
        return card
