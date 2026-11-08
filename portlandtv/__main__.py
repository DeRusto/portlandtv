"""Service entrypoint: `python3 -m portlandtv CONFIG PLAYLIST_DIR` ticks the Scheduler forever."""
import subprocess
import sys
import time
from datetime import datetime, timezone

from portlandtv.service import Service

TICK_SECONDS = 60


class Prober:
    def duration(self, path):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout
        return float(out)


class Clock:
    def now(self):
        return datetime.now(timezone.utc)


def main(config_path, playlist_dir):
    # shortcut: no ffplayout client yet (#28 adds it, with the stored login from the environment)
    service = Service(config_path, playlist_dir, Prober(), Clock(), ffplayout=None)
    last = None
    while True:
        service.tick()
        if service.error != last:
            print(f"generation error: {service.error}" if service.error else "generation ok",
                  file=sys.stderr, flush=True)
            last = service.error
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main(*sys.argv[1:3])
