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
        shows = library.scan_shows(cfg["libraries"])
        card = self._card_writer(shows, date)
        program, picks, after, sequence = day.build(cfg, shows, before, self.prober, card)
        d = date.isoformat()
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": program})
        store.write_json(record_path, {"slots": picks, "state_before": before,
                                       "tail": sequence[-day.AHEAD:]})
        store.write_json(self.state_path, after)
        # the previous day's last cards were placeholders until this day's items were known
        prev = store.read_json(self._day_record_path(date - timedelta(days=1)), {})
        if "tail" in prev:
            tail, prev_card = prev["tail"], self._card_writer(shows, date - timedelta(days=1))
            for n in range(1, len(tail) + 1):
                t = len(tail) - n
                prev_card(day.end_card(n), (tail + sequence)[t + 1:t + 1 + day.AHEAD])

    def _card_writer(self, shows, date):
        """card(name, item paths) -> path of that day's card, rendered once per name."""
        show_of = {p: name for name, eps in shows.items() for p in eps}
        size = self.ffplayout.output_size()
        written = set()

        def card(name, paths):
            path = os.path.join(self.data_dir, "cards", date.isoformat(), name + ".png")
            if name not in written:
                cards.render(path, [cards.describe(p, show_of) for p in paths], size)
                written.add(name)
            return path
        return card
