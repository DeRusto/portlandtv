"""Seam 1 harness: a temp directory with the YAML, Library folders of empty files
and the state JSON, plus a Service wired to fakes."""
import json
import os
import re
import tempfile
from datetime import datetime, timezone

import yaml

from portlandtv.service import Service
from tests.fakes import FakeClock, FakeFfplayout, FakeProber


# cards whose UP NEXT/THEN reach past their Airing, and schedule display frames, so
# they differ between Repeats; every other source (shared b{block}-{slot} cards
# included) is identical in each Repeat
PER_AIRING_CARD = re.compile(r"[/\\](b\d+-a\d+-\d+|end-\d+|sched-b\d+-a\d+-\d+-\d+)\.png$")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Channel:
    def __init__(self, config, files=(), durations=None, now=None, filler=None,
                 more_shows=None, movies=None, ffplayout=None):
        """`more_shows`: {folder name under root: [rel paths]}, extra `shows` Libraries.
        `ffplayout`: the client the Service talks to (default a FakeFfplayout)."""
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
        if movies is not None:  # rel paths under a `movies` Library
            libraries.append({"path": os.path.join(self.root, "movies"), "kind": "movies"})
            for rel in movies:
                self.add_file("movies/" + rel)
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
        self.ffplayout = ffplayout or FakeFfplayout()
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

    def add_file(self, rel):
        """Create an empty file at `rel` under the root (e.g. "movies/x.mkv")."""
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

    def rel(self, path):
        """A playlist source as a path relative to the root's Library folders."""
        return os.path.relpath(path, os.path.dirname(self.library)).split(os.sep, 1)[1]

    def playlist(self, date):
        path = os.path.join(self.playlists, date[:4], date[5:7], date + ".json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def read_json(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return json.load(f)
