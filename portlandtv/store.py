"""Machine-owned files: every write goes to a temp file renamed into place."""
import json
import os
import tempfile


def write_atomic(path, write):
    """Call write(f) on a temp file beside `path`, then rename it over `path`."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
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
