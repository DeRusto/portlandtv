"""Machine-owned files: every write goes to a temp file renamed into place."""
import json
import os
import tempfile


def write_atomic(path, write):
    """Call write(f) on a temp file beside `path`, then rename it over `path`."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())  # so a power cut after the rename can't leave an empty file
        os.chmod(tmp, 0o644)  # mkstemp makes it 0600; the YAML must stay readable for backups
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write_json(path, data):
    write_atomic(path, lambda f: f.write(json.dumps(data, indent=2).encode()))


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


class Paths:
    """Where the machine-owned files live, beside the YAML."""

    def __init__(self, config_path):
        self.root = os.path.dirname(os.path.abspath(config_path))
        self.state = os.path.join(self.root, "state.json")
        self.durations = os.path.join(self.root, "durations.json")
        self.ffplayout = os.path.join(self.root, "ffplayout.json")  # last push, output size

    def day(self, date):
        """The day record of the Broadcast Day starting on `date`."""
        return os.path.join(self.root, "days", f"{date.isoformat()}.json")

    def card(self, date, name):
        return os.path.join(self.root, "cards", date.isoformat(), name + ".png")
