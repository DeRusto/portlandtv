"""The portlandtv service: ticks the scheduler and serves the web UI.

python3 -m portlandtv CONFIG.yaml PLAYLIST_DIR [--port 8080]
"""
import argparse
import subprocess
import threading
import time
from datetime import datetime, timezone

from portlandtv.service import Service
from portlandtv.web import create_app

TICK = 60  # s; a failed generation is retried on the next tick


class FfprobeProber:
    # shortcut: no duration cache yet, #22 puts one in front of this
    def duration(self, path):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=True).stdout
        return float(out)


class Clock:
    def now(self):
        return datetime.now(timezone.utc)


def main():
    p = argparse.ArgumentParser(prog="portlandtv")
    p.add_argument("config")
    p.add_argument("playlist_dir")
    p.add_argument("--host", default="0.0.0.0")  # home network, no login (spec #20)
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    service = Service(args.config, args.playlist_dir, FfprobeProber(), Clock(), ffplayout=None)

    def loop():
        while True:
            service.tick()
            time.sleep(TICK)

    threading.Thread(target=loop, daemon=True).start()
    create_app(service).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
