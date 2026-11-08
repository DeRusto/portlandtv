"""Fakes for the service-core seam: prober, clock and ffplayout client."""
import os


class FakeProber:
    """Durations from a table keyed by file name; unlisted files get `default`."""

    def __init__(self, table=None, default=600.0):
        self.table = table or {}
        self.default = default

    def duration(self, path):
        return self.table.get(os.path.basename(path), self.default)


class FakeClock:
    def __init__(self, now):
        self.now_value = now

    def now(self):
        return self.now_value


class FakeFfplayout:
    """Records every call so tests can check what was pushed."""

    def __init__(self, size=(1920, 1080)):
        self.calls = []
        self.size = size  # output resolution, for the cards

    def output_size(self):
        return self.size
