# PortlandTV

A linear TV Channel for the USS Portland, played from your own Libraries of shows and movies on an offline Linux laptop and watched in VLC.

A Broadcast Day is made of Blocks, and each Block airs several times a day as verbatim Repeats. An 8 h Block aired 3 times plays at 06:00, 14:00 and 22:00 UTC with exactly the same programmes each time, so people on any watch rotation see the same episodes. The next day, the shows advance.

PortlandTV is a small Python service that runs beside [ffplayout](https://github.com/ffplayout/ffplayout). ffplayout plays the playlists out and streams HLS. PortlandTV decides what airs and gives you a web UI to edit it (see [ADR 0001](docs/adr/0001-ffplayout-plus-generator.md)). The words used here (Block, Slot, Airing, Break, Filler and so on) are defined in [GLOSSARY.md](GLOSSARY.md).

## What you need

- An **amd64** laptop running Debian 13 or Ubuntu, with `sudo`.
- An internet connection **for the install only**. After that the laptop runs fully offline.
- Your media in folders the laptop can read: shows, movies, and optionally short Filler clips.

Everything runs in **UTC**. The installer sets the laptop's time zone to UTC, and every time in the schedule is UTC.

## Install

### 1. Download

```bash
git clone https://github.com/DeRusto/portlandtv.git
cd portlandtv
```

No git? Download the ZIP from the GitHub page (**Code → Download ZIP**), unzip it and `cd` into the folder.

### 2. Run the installer

```bash
sudo ./install.sh
```

It:

- sets the time zone to UTC;
- installs FFmpeg, `python3-yaml`, `python3-flask`, `python3-pil` and the DejaVu fonts from apt;
- downloads ffplayout 2.7.1, checks its checksum and installs it;
- sets ffplayout up with a login for PortlandTV, saved in `/etc/portlandtv/ffplayout.env`;
- copies the app to `/opt/portlandtv` and starts the `portlandtv` systemd service.

On the first run there is no schedule yet, so it ends with a note asking you to write one.

### 3. Write your schedule

Create `/var/lib/portlandtv/portlandtv.yaml`:

```bash
sudo nano /var/lib/portlandtv/portlandtv.yaml
```

Start from this and change the paths and show names to yours. Show names are the show folder names.

```yaml
day_start: "06:00"            # UTC; every Broadcast Day is exactly 24 h

libraries:
  - {path: /media/tv, kind: shows}        # one folder per show, e.g. /media/tv/Show A/Season 01/...
  - {path: /media/movies, kind: movies}
  - {path: /media/filler, kind: filler}   # short clips for the Breaks (optional)

show_groups:                  # named lists of shows that share a Slot, back to back
  Cartoons: [Show C, Show D]

show_list:                    # what "Distribute…" shares out across the week
  - show: Show A
  - group: Cartoons

day_schedule:                 # length × repeat of all Blocks must total exactly 24 h
  - length: 8h
    repeat: 3
    slots:
      - rule: {movie: random}             # fixed: the same rule every day
      - rule: {show: Show B}
      - weekdays:                         # distributed: a rule per weekday (a missing day is empty)
          mon: {show: Show A}
          tue: {show: Show A}
          sun: {group: Cartoons}
```

Then give the file to the service user, make sure that user can read your media, and re-run the installer so ffplayout gets your `day_start` and Filler folder:

```bash
sudo chown ffpu:ffpu /var/lib/portlandtv/portlandtv.yaml
```

```bash
sudo ./install.sh
```

The service user is `ffpu`, which the ffplayout package creates. If your media is on an external drive, mount it so that `ffpu` can read it.

### 4. Watch and edit

- **Watch:** in VLC, open **Media → Open Network Stream** and enter `http://<laptop-ip>:8787/public/1/live/stream.m3u8`.
- **Edit:** open `http://<laptop-ip>:8080` from any device on the home network. There is no login. From there you can edit Blocks, Slots, Weekday Rules, the Show List and the Libraries, and run **Distribute…**. The **Problems** panel lists anything wrong, such as empty cells, missing shows, unplayable files or generation errors.

A saved edit takes effect at the next Broadcast Day, so today's Repeats stay identical. **Save and rebuild today from now** applies it straight away instead.

## Upgrade

```bash
git pull
```

```bash
sudo ./install.sh
```

The installer is safe to re-run. It keeps your schedule, show positions and the ffplayout login.

## Where things live

| Path | What |
|------|------|
| `/var/lib/portlandtv/portlandtv.yaml` | Your schedule. Readable and safe to edit by hand. Back it up. |
| `/var/lib/portlandtv/` | Also the machine-owned files beside it: show positions (`state.json`), per-day records (`days/`), cards (`cards/`), the duration cache. |
| `/var/lib/ffplayout/playlists/` | The daily playlists ffplayout plays. |
| `/opt/portlandtv/` | The installed app. |
| `/etc/portlandtv/ffplayout.env` | The ffplayout login the service uses. |

Logs:

```bash
journalctl -u portlandtv -f
```

## Development

The code is plain Python 3 with no pip dependencies. Run the tests on Linux (or WSL) with the apt packages above installed:

```bash
python3 -m unittest
```

The tests drive the service and the web app through fakes for ffprobe, the clock and ffplayout, so they need no media and no ffplayout.

## License

[AGPL-3.0](LICENSE)
