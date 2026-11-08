"""Seam 1 harness: a temp directory with the YAML, Library folders of empty files
and the state JSON, plus a Service wired to fakes."""
import json
import os
import tempfile
from datetime import datetime, timezone

import yaml

from portlandtv.service import Service
from tests.fakes import FakeClock, FakeFfplayout, FakeProber


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Station:
    def __init__(self, config, files=(), durations=None, now=None, filler=None,
                 more_shows=None):
        """`more_shows`: {folder name under root: [rel paths]}, extra `shows` Libraries."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.library = os.path.join(self.root, "shows")
        shows = {"shows": files, **(more_shows or {})}
        for lib, rels in shows.items():
            for rel in rels:
                path = os.path.join(self.root, lib, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").close()
        libraries = [{"path": os.path.join(self.root, lib), "kind": "shows"} for lib in shows]
        if filler is not None:  # rel paths under a `filler` Library; [] = empty folder
            self.filler = os.path.join(self.root, "filler")
            os.makedirs(self.filler)
            for rel in filler:
                path = os.path.join(self.filler, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").close()
            libraries.append({"path": self.filler, "kind": "filler"})
        config = {"libraries": libraries, **config}
        self.config_path = os.path.join(self.root, "portlandtv.yaml")
        with open(self.config_path, "w") as f:
            yaml.safe_dump(config, f)
        self.playlists = os.path.join(self.root, "playlists")
        self.prober = FakeProber(durations)
        self.clock = FakeClock(now or utc(2026, 11, 9, 12, 0))
        self.ffplayout = FakeFfplayout()
        self.service = Service(self.config_path, self.playlists,
                               prober=self.prober, clock=self.clock,
                               ffplayout=self.ffplayout)

    def close(self):
        self._tmp.cleanup()

    def tick(self, now=None):
        if now:
            self.clock.now_value = now
        self.service.tick()

    def path(self, rel):
        return os.path.join(self.library, rel)

    def playlist(self, date):
        path = os.path.join(self.playlists, date[:4], date[5:7], date + ".json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def read_json(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return json.load(f)
