"""The portlandtv service: ticks the scheduler and serves the web UI.

python3 -m portlandtv CONFIG.yaml PLAYLIST_DIR [--port 8080]
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from portlandtv import ffplayout
from portlandtv.service import Service
from portlandtv.web import create_app

TICK = 60  # s; a failed generation is retried on the next tick


class FfprobeProber:
    """Real durations; the service puts library.CachedProber in front."""

    def duration(self, path):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=True, timeout=120).stdout
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
    # the login install.sh stores in /etc/portlandtv/ffplayout.env (the unit's EnvironmentFile)
    login = [os.environ.get(k) for k in ("FFPLAYOUT_URL", "FFPLAYOUT_USER", "FFPLAYOUT_PASSWORD")]
    client = ffplayout.Client(*login) if all(login) else ffplayout.Unconfigured()
    service = Service(args.config, args.playlist_dir, FfprobeProber(), Clock(), client)

    def loop():
        last = None
        while True:
            service.tick()
            if (service.error, service.push_error) != last:  # journal only on change
                print(f"generation error: {service.error}" if service.error else "generation ok",
                      f"; ffplayout push problem: {service.push_error}" if service.push_error
                      else "", sep="", file=sys.stderr, flush=True)
                last = service.error, service.push_error
            time.sleep(TICK)

    threading.Thread(target=loop, daemon=True).start()
    create_app(service).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
