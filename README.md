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

On first start the service creates an empty schedule at `/var/lib/portlandtv/portlandtv.yaml`.

### 3. Build your schedule in the web UI

Open `http://<laptop-ip>:8080` from any device on the home network. There is no login.

1. Under **Libraries**, add your media folders and tag each one `shows`, `movies` or `filler`. Show names are the show folder names.
2. Set the Broadcast Day start (UTC).
3. Add Blocks and give each a length and a repeat count. All Blocks' length × repeat must total exactly 24 h. The page keeps your edits as a draft and shows the time still to assign.
4. Optionally make **Show Groups**: named lists of shows that share a Slot and play back to back. Renaming a group updates every Slot and Show List entry that uses it.
5. Add Slots to each Block: next episode of a show or a Show Group, or a random movie. Make a Slot **distributed** to give it a different rule for each weekday.
6. Optionally add shows and Show Groups to the **Show List** and use **Distribute…** to share them out across the week's distributed cells. Each entry gets an equal share, taken in turn day by day. In **Show List balance**, each entry is a column as tall as its episodes left: drag shows between columns to group them, or press **Auto-sort** to group short shows so that none outlasts the longest entry.
7. **Save.** Nothing, not even the Libraries, is saved until the schedule totals 24 h, so on a fresh install build it in one sitting.

Until the schedule totals 24 h, the **Problems** panel shows a generation error and nothing is generated; the service never makes up a schedule.

The service runs as `ffpu`, a user the ffplayout package creates. If your media is on an external drive, mount it so that `ffpu` can read it.

If you added a `filler` Library, re-run the installer once so ffplayout uses that folder for its own gaps:

```bash
sudo ./install.sh
```

#### Or edit the file by hand

The schedule is plain YAML and safe to edit by hand or to restore from a backup. A full example:

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

Edit it as the service user, so the file stays readable by the service:

```bash
sudo -u ffpu nano /var/lib/portlandtv/portlandtv.yaml
```

### 4. Watch

In VLC, open **Media → Open Network Stream** and enter `http://<laptop-ip>:8787/public/1/live/stream.m3u8`.

The **Problems** panel in the web UI lists anything wrong, such as empty cells, missing shows, unplayable files or generation errors. A saved edit takes effect at the next Broadcast Day, so today's Repeats stay identical. **Save and rebuild today from now** applies it straight away instead.

## Upgrade

```bash
git pull
```

```bash
sudo ./install.sh
```

The installer is safe to re-run. It keeps your schedule, show positions and the ffplayout login.

## Subtitles

ffplayout shows a video's subtitles in the HLS stream when a WebVTT file with the same name sits beside it (`Show - S01E01.vtt` next to `Show - S01E01.mkv`) and its `vtt_enable` playout option is on. To make those files from the subtitles inside your videos, run this from the repo as a user who can write to the media folders:

```bash
python3 -m portlandtv.subtitles /media/tv /media/movies
```

It takes the first English text subtitle track in each video, or the first text track if none is English (`--language fre` prefers French), and skips tracks marked forced-only. Picture subtitles from Blu-rays and DVDs can't be turned into text, so videos with only those are skipped. Videos that already have a `.vtt` are left alone, so it is safe to re-run after adding files.

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
