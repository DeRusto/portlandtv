"""Scheduler, the service core: each tick generates the Broadcast Days that are due."""
import os
from datetime import datetime, timedelta, timezone

from PIL import Image

from portlandtv import config, day, library, store

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
        prober.save()
        program, picks, after = day.build(cfg, shows, before, prober, self._placeholder())
        d = date.isoformat()
        store.write_json(os.path.join(self.playlist_dir, d[:4], d[5:7], d + ".json"),
                         {"date": d, "program": program})
        store.write_json(record_path, {"slots": picks, "state_before": before})
        store.write_json(self.state_path, after)

    def _placeholder(self):
        path = os.path.join(self.data_dir, "cards", "placeholder.png")
        if not os.path.exists(path):
            # shortcut: plain still for every Break until the card renderer lands
            img = Image.new("RGB", (1280, 720), "#0b0d12")
            store.write_atomic(path, lambda f: img.save(f, "PNG"))
        return path
