"""Library scanner: shows from folder names, episodes in airing order."""
import os
import re

VIDEO = {".mp4", ".mkv", ".m4v", ".mov", ".avi", ".webm", ".ts"}


def _episode_key(path):
    season = re.search(r"season\s*(\d+)", os.path.dirname(path), re.I)
    sxe = re.search(r"s(\d+)e(\d+)", os.path.basename(path), re.I)
    return (int(season[1]) if season else 0,
            (int(sxe[1]), int(sxe[2])) if sxe else (0, 0),
            os.path.basename(path).lower())


def scan_shows(libraries):
    """{show name: [episode paths in order]} from every `shows` Library.

    shortcut: basic scan only (no extras/specials/dedupe/natural sort), see #20.
    """
    shows = {}
    for lib in libraries:
        if lib.get("kind") != "shows":
            continue
        for name in sorted(os.listdir(lib["path"])):
            folder = os.path.join(lib["path"], name)
            if not os.path.isdir(folder):
                continue
            eps = shows.setdefault(name, [])
            for dirpath, _, files in os.walk(folder):
                eps += [os.path.join(dirpath, f) for f in files
                        if os.path.splitext(f)[1].lower() in VIDEO]
    for eps in shows.values():
        eps.sort(key=_episode_key)
    return shows


def _files(libraries, kind):
    """Every playable file at any depth of every Library of this kind."""
    return sorted(os.path.join(dirpath, f)
                  for lib in libraries if lib.get("kind") == kind
                  for dirpath, _, files in os.walk(lib["path"])
                  for f in files if os.path.splitext(f)[1].lower() in VIDEO)


def scan_filler(libraries):
    """Every playable file at any depth of every `filler` Library (no extras filtering)."""
    return _files(libraries, "filler")


def scan_movies(libraries):
    """Every playable file at any depth of every `movies` Library, one movie each.

    shortcut: extras are not skipped yet, the scanner ticket (#22) adds that.
    """
    return _files(libraries, "movies")
