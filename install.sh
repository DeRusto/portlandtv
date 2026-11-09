#!/usr/bin/env bash
# Sets up or upgrades PortlandTV on the laptop. Run while online, from the repo: sudo ./install.sh
# Safe to re-run: every step either checks first or overwrites with the same result.
set -euo pipefail

FFPLAYOUT_VERSION=2.7.1
DEB=ffplayout_v${FFPLAYOUT_VERSION}-1_amd64.deb
DEB_URL=https://github.com/ffplayout/ffplayout/releases/download/v${FFPLAYOUT_VERSION}/${DEB}
DEB_SHA256=ff6424404a7ae5cc0426e47a71da8c68cc6e09fa3b41e3b0b5f9fd6855eb868e

SVC_USER=ffpu                       # created by the ffplayout .deb (debian/postinst)
APP_DIR=/opt/portlandtv
DATA_DIR=/var/lib/portlandtv
CONFIG=$DATA_DIR/portlandtv.yaml    # the human-owned YAML; state and day files sit beside it
PLAYLISTS=/var/lib/ffplayout/playlists
STORAGE=/var/lib/ffplayout/tv-media
PUBLIC=/usr/share/ffplayout/public
LOGS=/var/log/ffplayout
ENV_DIR=/etc/portlandtv
ENV_FILE=$ENV_DIR/ffplayout.env     # the ffplayout login the portlandtv service uses
API=http://127.0.0.1:8787
SRC=$(cd "$(dirname "$0")" && pwd)

die() { echo "install.sh: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root: sudo $0"
[ "$(dpkg --print-architecture)" = amd64 ] || die "only amd64 is supported (the ffplayout .deb is amd64)"

echo "== Time zone: UTC"
timedatectl set-timezone UTC

echo "== Packages"
apt-get update
apt-get install -y ffmpeg python3-yaml python3-flask python3-pil fonts-dejavu-core curl
ff_version=$(ffmpeg -version | sed -n '1s/^ffmpeg version [^0-9]*\([0-9]*\.[0-9]*\).*/\1/p')
# The spec pins FFmpeg 7.1 (Debian 13's version); other distros ship others (Ubuntu 26.04 has 8.0).
# ffplayout 2.7.1 documents 7.1+ as supported, so this warns rather than fails; the ldd check below is the real gate.
[ "$ff_version" = 7.1 ] || echo "WARNING: FFmpeg is ${ff_version:-unknown}, not 7.1" >&2

echo "== ffplayout $FFPLAYOUT_VERSION"
case "$(dpkg-query -W -f='${Version}' ffplayout 2>/dev/null || true)" in
  "$FFPLAYOUT_VERSION" | "$FFPLAYOUT_VERSION"-*) echo "already installed" ;;
  *)
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fL -o "$tmp/$DEB" "$DEB_URL"
    echo "$DEB_SHA256  $tmp/$DEB" | sha256sum -c -
    chmod 755 "$tmp"  # apt's _apt sandbox user must read the .deb
    apt-get install -y "$tmp/$DEB"
    ;;
esac
if ldd /usr/bin/ffplayout | grep 'not found'; then
  die "ffplayout is missing shared libraries (above); install the FFmpeg version it was built against"
fi

# The .deb's unit listens on 127.0.0.1 only; VLC on other devices needs the HLS stream on the LAN.
# Unverified: the .deb's own ExecStart line (assets/ffplayout.service) was not read; this replaces it.
mkdir -p /etc/systemd/system/ffplayout.service.d
cat > /etc/systemd/system/ffplayout.service.d/portlandtv.conf <<EOF
[Service]
Environment=TZ=UTC
ExecStart=
ExecStart=/usr/bin/ffplayout --listen 0.0.0.0:8787
EOF

install -d -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR" "$PLAYLISTS" "$STORAGE" "$LOGS"
install -d -m 750 -g "$SVC_USER" "$ENV_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "== ffplayout first-time setup"
  password=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
  systemctl stop ffplayout || true
  # Unverified on a real box: -i only prompts for values not given here, so </dev/null fails fast
  # instead of hanging if 2.7.1 asks for something else. If an admin already exists (web setup was
  # done by hand), -u may not create ours; then add it with: ffplayout --user-set -u portlandtv ...
  runuser -u "$SVC_USER" -- /usr/bin/ffplayout -i \
    -u portlandtv -p "$password" -m portlandtv@localhost --two-factor false \
    --storage "$STORAGE" --playlists "$PLAYLISTS" --logs "$LOGS" --public "$PUBLIC" </dev/null
  # Written only after -i succeeds, so a failed setup is retried on the next run; temp file + rename,
  # so a failed write never leaves a partial file that would skip setup next time.
  (umask 027
   printf 'FFPLAYOUT_URL=%s\nFFPLAYOUT_USER=portlandtv\nFFPLAYOUT_PASSWORD=%s\n' "$API" "$password" > "$ENV_FILE.tmp")
  chgrp "$SVC_USER" "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
fi

systemctl daemon-reload
systemctl enable ffplayout
systemctl restart ffplayout
for _ in $(seq 30); do curl -fs -o /dev/null "$API/" && break; sleep 1; done

echo "== ffplayout channel config"
# Channel 1: UTC zone and our playlist folder. Playout config: a 24 h day from the YAML's day_start,
# no infinite looping, and the filler folder at the YAML's filler Library.
# Unverified: the JSON shapes (the PATCH body key `timezone` and the `playlist`/`storage` sections)
# come from ffplayout's Rust structs (db/models.rs Channel, utils/config.rs PlayoutConfig), not a live API.
set -a; . "$ENV_FILE"; set +a
CONFIG=$CONFIG PLAYLISTS=$PLAYLISTS python3 - <<'PY'
import json, os, urllib.request, yaml

api, cfg_path = os.environ["FFPLAYOUT_URL"], os.environ["CONFIG"]
raw = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as f:
        raw = yaml.safe_load(f) or {}
else:
    print(f"no {cfg_path} yet (the service creates it): using day_start 06:00 and no filler")
start = raw.get("day_start", "06:00")
if isinstance(start, int):  # unquoted HH:MM is a base-60 int in YAML 1.1
    start = f"{start // 60:02}:{start % 60:02}"
filler = next((lib["path"] for lib in raw.get("libraries") or [] if lib.get("kind") == "filler"), None)

def call(method, path, body=None, token=None):
    req = urllib.request.Request(api + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        text = r.read()
    try:
        return json.loads(text)
    except ValueError:  # writes answer with plain text (e.g. "Update Success"), or nothing
        return text.decode()

token = call("POST", "/auth/login", {"username": os.environ["FFPLAYOUT_USER"],
                                     "password": os.environ["FFPLAYOUT_PASSWORD"]})["access"]
channel = call("GET", "/api/channel/1", token=token)
channel.update(timezone="UTC", playlists=os.environ["PLAYLISTS"])
call("PATCH", "/api/channel/1", channel, token)

playout = call("GET", "/api/playout/config/1", token=token)
playout["playlist"].update(day_start=start + ":00", length="24:00:00", infinit=False)
if filler:
    playout["storage"]["filler"] = filler
else:
    print("no filler Library in the YAML: ffplayout's filler folder left as it is")
call("PUT", "/api/playout/config/1", playout, token)
print(f"day_start {start} UTC, length 24:00:00, infinit false, filler {filler}")
PY
systemctl restart ffplayout  # the PUT may report requires_restart

echo "== PortlandTV app"
install -d "$APP_DIR"
rm -rf "$APP_DIR/portlandtv"  # drop modules removed since the last install
cp -r "$SRC/portlandtv" "$APP_DIR/"
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +
install -m 644 "$SRC/deploy/portlandtv.service" /etc/systemd/system/portlandtv.service
systemctl daemon-reload
systemctl enable portlandtv
systemctl restart portlandtv

echo "Done. Build the schedule in the web UI: http://<this laptop's IP>:8080"
echo "      Stream: http://<this laptop's IP>:8787/public/1/live/stream.m3u8"
echo "After adding a filler Library, re-run this script so ffplayout uses that folder."
