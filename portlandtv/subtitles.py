"""Extracts embedded text subtitles to WebVTT sidecars (`Video.vtt` beside `Video.mkv`),
which ffplayout plays in HLS mode once its `vtt_enable` option is on.

python3 -m portlandtv.subtitles FOLDER... [--language eng]

Run it as a user who can write to the media folders; videos that already have a .vtt
are skipped, so it is safe to re-run after adding files.
"""
import argparse
import json
import os
import subprocess
import sys

from portlandtv.library import VIDEO

# picture subtitles (Blu-ray PGS, DVD VobSub) need OCR to become text, so they are skipped
TEXT = {"subrip", "ass", "ssa", "mov_text", "webvtt", "text"}


def pick(streams, language):
    """The subtitle stream to extract: a text one that isn't forced-only, in `language`
    if there is one, else the first; None if there is none."""
    usable = [s for s in streams
              if s.get("codec_name") in TEXT and not s.get("disposition", {}).get("forced")]
    return next((s for s in usable if s.get("tags", {}).get("language") == language),
                usable[0] if usable else None)


def extract(video, language, run=subprocess.run):
    """Write `video`'s subtitles to its .vtt -> what happened, for the report."""
    vtt = os.path.splitext(video)[0] + ".vtt"
    if os.path.exists(vtt):
        return "has .vtt"
    part = vtt + ".part"  # renamed into place only when complete
    try:
        probe = run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                     "stream=index,codec_name:stream_tags=language:stream_disposition=forced",
                     "-of", "json", video],
                    capture_output=True, text=True, check=True, timeout=120).stdout
        streams = json.loads(probe).get("streams") or []
        if not streams:
            return "no subtitles"
        stream = pick(streams, language)
        if not stream:
            return "no text subtitles (picture or forced only)"
        run(["ffmpeg", "-v", "error", "-y", "-i", video, "-map", f"0:{stream['index']}",
             "-c:s", "webvtt", "-f", "webvtt", part],
            capture_output=True, text=True, check=True, timeout=1800)
        os.replace(part, vtt)
    except subprocess.CalledProcessError as e:
        _remove(part)
        lines = (e.stderr or "").strip().splitlines()
        return f"failed: {lines[-1] if lines else e}"
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        _remove(part)
        return f"failed: {e}"
    return "extracted"


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def videos(folder):
    """Every video file under `folder`, skipping hidden files and folders."""
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in VIDEO:
                yield os.path.join(dirpath, f)


def main(argv=None, run=subprocess.run):
    p = argparse.ArgumentParser(prog="python3 -m portlandtv.subtitles",
                                description="Extract embedded text subtitles to .vtt files.")
    p.add_argument("folders", nargs="+")
    p.add_argument("--language", default="eng",
                   help="preferred subtitle language tag (default: eng)")
    args = p.parse_args(argv)
    failed = 0
    for folder in args.folders:
        if not os.path.isdir(folder):
            print(f"not a folder: {folder}", file=sys.stderr)
            failed += 1
            continue
        for video in videos(folder):
            result = extract(video, args.language, run)
            failed += result.startswith("failed")
            print(f"{result}: {video}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
