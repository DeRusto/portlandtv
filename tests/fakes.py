"""Fakes for the service-core seam: prober, clock and ffplayout client."""
import os


class FakeProber:
    """Durations from a table keyed by file name; unlisted files get `default`.
    A table value of None means "no duration"; an exception instance is raised.
    Every probed path is recorded in `.calls`."""

    def __init__(self, table=None, default=600.0):
        self.table = table or {}
        self.default = default
        self.calls = []

    def duration(self, path):
        self.calls.append(path)
        value = self.table.get(os.path.basename(path), self.default)
        if isinstance(value, Exception):
            raise value
        return value


class FakeClock:
    def __init__(self, now):
        self.now_value = now

    def now(self):
        return self.now_value


class FakeFfplayout:
    """Records every call so tests can check what was pushed."""

    def __init__(self):
        self.calls = []
