"""Library scanner: shows from folder names, episodes in airing order."""
import os
import re
import sys
import threading

from portlandtv import store

VIDEO = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
         ".webm", ".flv"}
EXTRAS = {"extras", "featurettes", "behind the scenes", "deleted scenes", "interviews",
          "scenes", "shorts", "trailers", "other", "sample", "samples"}
EXTRA_FILE = re.compile(r"(^|[-._ ])(sample|trailer|featurette)$", re.I)
SEASON_DIR = re.compile(r"season\s*(\d+)$", re.I)
SAVE_EVERY = 20  # new durations between cache writes during a scan
SXE = re.compile(r"s(\d+)e(\d+)|\b(\d{1,2})x(\d{2,3})\b", re.I)  # S01E02 or 1x02


def natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def file_episode(name):
    """(season, episode, end of the match) from a SxxEyy or NxNN file name, else None."""
    m = SXE.search(name)
    return m and (int(m[1] or m[3]), int(m[2] or m[4]), m.end())


def episode_key(path):
    """(season, episode): season from the nearest `Season NN` folder, else SxxEyy, else 1;
    episode from SxxEyy, else 0."""
    sxe = file_episode(os.path.basename(path))
    episode = sxe[1] if sxe else 0
    for part in reversed(os.path.normpath(os.path.dirname(path)).split(os.sep)):
        folder = SEASON_DIR.match(part)
        if folder:
            return int(folder[1]), episode
    return (sxe[0] if sxe else 1), episode


class CachedProber:
    """Prober with a JSON duration cache keyed by path, size and mtime.
    duration() is None for a file the prober can't read or that has no duration.
    With measure=False it never probes: a file not yet measured is 0 (playable, length
    unknown) and is listed in `pending`."""

    def __init__(self, prober, cache_path, measure=True):
        self.prober = prober
        self.cache_path = cache_path
        self.cache = store.read_json(cache_path, {})
        self.unsaved = 0
        self.measure = measure
        self.pending = []

    def duration(self, path):
        st = os.stat(path)
        stamp = [st.st_size, st.st_mtime_ns]
        hit = self.cache.get(path)
        if hit and hit["stamp"] == stamp:
            return hit["duration"]
        if not self.measure:
            self.pending.append(path)
            return 0
        try:
            seconds = self.prober.duration(path) or None
        except Exception:
            return None  # not cached: a failed probe may be transient (slow drive, timeout)
        self.cache[path] = {"stamp": stamp, "duration": seconds}
        self.unsaved += 1
        if self.unsaved >= SAVE_EVERY:  # a long first scan cut short by a reload keeps its work
            self.save()
        return seconds

    def save(self):
        # shortcut: entries for deleted files are never pruned; prune here if the file grows large
        # merged over the file, so the Measurer and a build saving at once keep both's work
        store.write_json(self.cache_path, {**store.read_json(self.cache_path, {}), **self.cache})
        self.unsaved = 0


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


def _folder(lib):
    """A Library's path; a missing one is a generation error, never silently empty."""
    if not os.path.isdir(lib["path"]):
        raise FileNotFoundError(f"Library missing: {lib['path']}")
    return lib["path"]


def scan_shows(libraries, prober):
    """-> ({show name: [episode paths in order]}, [unplayable paths]) from every `shows`
    Library. Same-named show folders merge; a duplicate (season, episode) is kept once."""
    found, unplayable = {}, []
    for lib in libraries:
        if lib.get("kind") != "shows":
            continue
        for name in sorted(os.listdir(_folder(lib))):
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
        for dirpath, dirs, files in os.walk(_folder(lib)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            clips += [os.path.join(dirpath, f) for f in files
                      if not f.startswith(".") and os.path.splitext(f)[1].lower() in VIDEO]
    return sorted(clips)


def scan_movies(libraries):
    """Every non-extra video file at any depth of every `movies` Library, one movie each."""
    return sorted(path for lib in libraries if lib.get("kind") == "movies"
                  for path in _videos(_folder(lib)))


class Measurer:
    """Measures new files of the Libraries it is asked for on its own thread, so a page
    load never waits on the prober. Until start(), want() measures inline (tests)."""

    def __init__(self, prober, cache_path):
        self.prober = prober
        self.cache_path = cache_path
        self.left = 0  # files still to measure, for the UI
        self._wanted = {}
        self._lock = threading.Lock()
        self._wake = None
        self.idle = threading.Event()  # set while nothing is asked for or being measured
        self.idle.set()

    def start(self):
        self._wake = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def want(self, libraries):
        with self._lock:
            self._wanted.update(((lib["path"], lib.get("kind")), lib) for lib in libraries)
            self.idle.clear()
        if self._wake:
            self._wake.set()
        else:
            self._measure()
            self.idle.set()

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            try:
                self._measure()
            except Exception as e:  # a folder gone mid-walk; the next want() retries
                self.left = 0
                print(f"measuring failed: {e}", file=sys.stderr, flush=True)
            with self._lock:
                if not self._wanted:
                    self.idle.set()

    def _measure(self):
        with self._lock:
            libs, self._wanted = list(self._wanted.values()), {}
        libs = [lib for lib in libs if os.path.isdir(lib["path"])]
        peek = CachedProber(self.prober, self.cache_path, measure=False)
        scan_shows(libs, peek)
        for path in scan_filler(libs) + scan_movies(libs):
            peek.duration(path)
        self.left = len(peek.pending)
        prober = CachedProber(self.prober, self.cache_path)
        for path in peek.pending:
            prober.duration(path)
            self.left -= 1
        prober.save()
