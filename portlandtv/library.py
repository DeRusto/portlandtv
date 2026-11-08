"""Library scanner: shows from folder names, episodes in airing order."""
import os
import re

from portlandtv import store

VIDEO = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
         ".webm", ".flv"}
EXTRAS = {"extras", "featurettes", "behind the scenes", "deleted scenes", "interviews",
          "scenes", "shorts", "trailers", "other", "sample", "samples"}
EXTRA_FILE = re.compile(r"(-sample|\.sample|-trailer|-featurette)$", re.I)
SEASON_DIR = re.compile(r"season\s*(\d+)$", re.I)
SXE = re.compile(r"s(\d+)e(\d+)", re.I)


def natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def episode_key(path):
    """(season, episode): season from the nearest `Season NN` folder, else SxxEyy, else 1;
    episode from SxxEyy, else 0."""
    sxe = SXE.search(os.path.basename(path))
    episode = int(sxe[2]) if sxe else 0
    for part in reversed(os.path.normpath(os.path.dirname(path)).split(os.sep)):
        folder = SEASON_DIR.match(part)
        if folder:
            return int(folder[1]), episode
    return (int(sxe[1]) if sxe else 1), episode


class CachedProber:
    """Prober with a JSON duration cache keyed by path, size and mtime.
    duration() is None for a file the prober can't read or that has no duration."""

    def __init__(self, prober, cache_path):
        self.prober = prober
        self.cache_path = cache_path
        self.cache = store.read_json(cache_path, {})

    def duration(self, path):
        st = os.stat(path)
        stamp = [st.st_size, st.st_mtime_ns]
        hit = self.cache.get(path)
        if hit and hit["stamp"] == stamp:
            return hit["duration"]
        try:
            seconds = self.prober.duration(path) or None
        except Exception:
            seconds = None
        self.cache[path] = {"stamp": stamp, "duration": seconds}
        return seconds

    def save(self):
        # shortcut: entries for deleted files are never pruned; prune here if the file grows large
        store.write_json(self.cache_path, self.cache)


def _videos(folder):
    """Episode files under a show folder, skipping hidden, extras and specials."""
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in EXTRAS
                   and d.lower() != "specials"
                   and not (SEASON_DIR.match(d) and int(SEASON_DIR.match(d)[1]) == 0)]
        for f in files:
            stem, ext = os.path.splitext(f)
            if not f.startswith(".") and ext.lower() in VIDEO and not EXTRA_FILE.search(stem):
                yield os.path.join(dirpath, f)


def scan_shows(libraries, prober):
    """-> ({show name: [episode paths in order]}, [unplayable paths]) from every `shows`
    Library. Same-named show folders merge; a duplicate (season, episode) is kept once."""
    found, unplayable = {}, []
    for lib in libraries:
        if lib.get("kind") != "shows":
            continue
        for name in sorted(os.listdir(lib["path"])):
            folder = os.path.join(lib["path"], name)
            if name.startswith(".") or not os.path.isdir(folder):
                continue
            for path in _videos(folder):
                season, episode = episode_key(path)
                if season == 0:
                    continue
                if prober.duration(path) is None:
                    unplayable.append(path)
                    continue
                rel = os.path.relpath(path, folder).replace(os.sep, "/")
                found.setdefault(name, []).append((season, natural(rel), episode, path))
    shows = {}
    for name, eps in found.items():
        seen = set()
        shows[name] = []
        for season, _, episode, path in sorted(eps):
            if episode and (season, episode) in seen:
                continue
            seen.add((season, episode))
            shows[name].append(path)
    return shows, unplayable


def scan_filler(libraries):
    """Every video file at any depth of every `filler` Library (no extras filtering)."""
    clips = []
    for lib in libraries:
        if lib.get("kind") != "filler":
            continue
        for dirpath, dirs, files in os.walk(lib["path"]):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            clips += [os.path.join(dirpath, f) for f in files
                      if not f.startswith(".") and os.path.splitext(f)[1].lower() in VIDEO]
    return sorted(clips)
