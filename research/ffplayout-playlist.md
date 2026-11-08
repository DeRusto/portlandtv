# What ffplayout needs from a generated playlist (#6)

Researched 2026-11-08 against the **v2.7.1** tag of [ffplayout/ffplayout](https://github.com/ffplayout/ffplayout/tree/v2.7.1) (latest stable; 2.8.0 is in beta). All source links are pinned to that tag. "Inferred" marks conclusions read from code paths but not run.

Context worth knowing first: 2.x is no longer an ffmpeg-CLI wrapper. The engine links the FFmpeg libraries directly through `ffmpeg-next` 9 ([engine Cargo.toml](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/engine/Cargo.toml)), and probing uses the same libraries (`ff_engine::probe_media`), not an `ffprobe` process ([player/utils/mod.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs)).

## 1. JSON playlist schema

Defined by `JsonPlaylist` in [json_serializer.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/json_serializer.rs) and `Media` in [player/utils/mod.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs) (lines ~245-301). Example in the [README](https://github.com/ffplayout/ffplayout/blob/v2.7.1/README.md#json-playlist-example).

Top level:

| Field | Required | Notes |
|---|---|---|
| `channel` | no | string, defaults to `"Channel 1"`; informational |
| `date` | **yes** | `YYYY-MM-DD`, the Broadcast Day. Playout compares it with the date it expects and reloads when they differ |
| `program` | **yes** | array of items; an empty array is logged as an error and replaced by a 60 s dummy |

Per item (`program[]`):

| Field | Required | Type | Notes |
|---|---|---|---|
| `in` | **yes** | f64 seconds | seek into the source |
| `out` | **yes** | f64 seconds | end point in the source. **Scheduled length is `out - in`**; `duration` is not used for timing |
| `duration` | **yes** | f64 seconds | full length of the source file. Validation re-probes it and corrects/logs if it is off by more than 1.2 s |
| `source` | **yes** | string (null allowed, becomes `""`) | absolute path, path relative to the channel storage root, or http(s) URL. Live URLs (rtmp/srt/udp/...) are experimental |
| `title` | no | string | |
| `audio` | no | string | separate audio file to play with the video |
| `ad` | no | bool | marks advertisements. Legacy `"category": "advertisement"` is still read as `ad: true` ([api.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/api.md#playlists-and-programme-data)). Any other `category` string becomes `ad: false` |
| `custom_filter` | no | string | still parsed and kept, but I found no code in the app or engine that applies it (see "Not verified") |

No `deny_unknown_fields`: extra keys are ignored on read and dropped if the playlist is saved back through the API/UI.

**Where files live:** `<channel playlists dir>/YYYY/MM/YYYY-MM-DD.json` ([read_json](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/json_serializer.rs), [utils/playlist.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/playlist.rs)). The `.deb` creates `/var/lib/ffplayout/playlists` ([debian/postinst](https://github.com/ffplayout/ffplayout/blob/v2.7.1/debian/postinst)); the actual path is whatever was chosen at first-time setup. The file date is the Broadcast Day: before `day_start`, playout looks for yesterday's file (`get_date` in player/utils/mod.rs). If the playlists path is set to a single `.json` file instead of a folder, that one file is replayed every day.

## 2. Short or long playlists

From [player/input/playlist.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/input/playlist.rs):

- **Too short:** when the list runs out before `day_start + length`, `fill_end` adds a placeholder for the remaining time. `gen_source` turns it into Filler. If `storage.filler` is a **folder**, it takes the next file from the folder's filler list, round-robin, and plays it for `min(remaining, file length)`. This repeats until the gap is under ~1 s, so fillers loop. The list is built once at channel start: a recursive walk filtered by `storage.extensions`, in natural sort order, or shuffled if `storage.shuffle` is on ([file/local.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/file/local.rs) `fill_filler_list`). If `filler` is a **single file**, that file is used. If the folder is empty or the file is missing, a black/silent dummy of up to 60 s is generated. A missing or unprobeable `source` mid-list is replaced the same way. The README describes this as "when playlist is not 24 hours long, loop fillers until time is full".
- **Too long:** no overrun into the next day. The clip that crosses the day boundary is trimmed to end exactly at it ("trim last clip, to get full 24 hours"; `handle_list_end`/`last_clip_end`). Later items are skipped ("Begin is over play time, skip"). Then the next date's file is loaded.
- **`length` / `infinit`:** `length` is a `hh:mm:ss` string. The default is `24:00:00`; a value without `:` also means 86400. `infinit: true` turns off the daily switch and loops the current playlist forever (`recalculate_begin`). We want `infinit: false` and `length: "24:00:00"` ([docs/README.md "Day-Long Playlists"](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/README.md)).
- **Drift guard:** each clip's planned start (the sum of `out - in` from `day_start`) is compared with the wall clock. A difference above `general.stop_threshold` (default **11 s**, [migrations/00003](https://github.com/ffplayout/ffplayout/blob/v2.7.1/migrations/00003_split_config.sql)) logs "Clip begin out of sync" and makes playout re-seek by clock. A difference of about one hour is treated as a DST change and applied as a time shift (`timed_source`).

## 3. Mid-day replace or edit

Polling, not a file watcher. (`file/watcher.rs` is only for folder mode.) At **every clip boundary**, `next()` calls `check_for_playlist` and then `load_or_update_playlist`, which compares the file's mtime with the one it loaded. If it changed, the file is re-read and `list_init` is set. `get_current_clip` then finds the item covering the current wall-clock time, and `init_clip` seeks into it by the elapsed time. Inferred consequences:

- The item that is playing **is not interrupted**. The new playlist takes effect when that item ends.
- After that, playout joins the new list at "now" and starts its current item part-way through. It does not start from the top.
- An edit that only changes items before "now" has no visible effect, apart from shifting what "now" lands on.
- Saving through `POST /api/playlist/{id}` writes the same file, so the same mtime path applies. `POST /api/control/{id}/playout {"control":"next"|"reset"}` can force a jump ([api.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/api.md#playout-control)).
- The generator should write to a temp file and `rename()` it into place, so playout never reads a half-written file. This is my recommendation; a parse error falls back to a 60 s dummy.

## 4. Configuring `day_start`, `length`, filler in 2.7.x

Configuration is in SQLite: tables `config_playlist(day_start, length, infinit)` and `config_storage(filler, extensions, shuffle)` ([migrations/00003_split_config.sql](https://github.com/ffplayout/ffplayout/blob/v2.7.1/migrations/00003_split_config.sql)). Defaults: `day_start` = **`05:59:25`** (not 06:00), `length` = `24:00:00`, `infinit` = 0, `filler` = `filler/filler.mp4`, `extensions` = `mp4;mkv;webm`. `filler` is resolved relative to the channel storage root (`norm_abs_path` in [utils/config.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/config.rs)). The channel `timezone` lives on the `channels` table.

A script can set it in three ways:

1. **API:** `POST /auth/login` returns a JWT. `GET /api/playout/config/{id}` and then `PUT` the whole object back, with `playlist.day_start`, `playlist.length`, `playlist.infinit`, `storage.filler`, `storage.extensions`, `storage.shuffle` edited. The response's `requires_restart` says whether you then need `POST /api/control/{id}/process {"command":"restart"}` ([api.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/api.md)).
2. **CLI with TOML:** `ffplayout --dump-config -c 1` writes `ffplayout_1.toml`. Edit it, then `ffplayout --import-config ffplayout_1.toml -c 1` ([args_parse.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/args_parse.rs), `PlayoutConfig::dump/import`). Restart the service afterwards (inferred).
3. **Paths:** storage, playlist, public and log paths can only be set at first-time setup (web, `POST /api/setup`, or `sudo -u ffpu ffplayout -i`). Change them later with `ffplayout -i` ([install.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/install.md)). `POST /api/setup` takes all paths in one call, which suits a scripted install.

`-s/--start hh:mm:ss` overrides `day_start` for one process run only.

## 5. HLS for VLC

HLS is the default output ([output.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/output.md#hls)). It writes `<public>/live/<hls_playlist_name>.m3u8` and segments `<name>_%d.ts`. Default name `stream`, 6 s segments, list size 600, 1280x720 at 25 fps, libx264 and AAC 128k ([migrations/00001](https://github.com/ffplayout/ffplayout/blob/v2.7.1/migrations/00001_create_tables.sql), [engine/output/hls.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/engine/src/output/hls.rs)). `master.m3u8` exists **only** when HLS variants or WebVTT subtitles are configured, so the docs' `master.m3u8` example does not apply to the default setup.

The built-in server serves it without auth at `/public/{channel-id}/live/...` ([api.md "Public HLS files"](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/api.md#public-hls-files), [routes/public.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/api/routes/public.rs)). The packaged systemd unit listens on `0.0.0.0:8787` ([assets/ffplayout.service](https://github.com/ffplayout/ffplayout/blob/v2.7.1/assets/ffplayout.service)). VLC URL:

```
http://<laptop-ip>:8787/public/1/live/stream.m3u8
```

Upstream recommends nginx for production delivery; the sample config aliases `/live/` to the public dir ([assets/ffplayout.conf](https://github.com/ffplayout/ffplayout/blob/v2.7.1/assets/ffplayout.conf)). For a LAN with a few VLC viewers the built-in route is probably enough (inferred).

## 6. Linux install for offline runtime

- **Supported path: `.deb` or `.rpm`** from the [v2.7.1 release](https://github.com/ffplayout/ffplayout/releases/tag/v2.7.1): `ffplayout_v2.7.1-1_amd64.deb` (~12 MB), `ffplayout-v2.7.1-1.x86_64.rpm`, plus `_server_`/`_desktop_` tarballs. [install.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docs/install.md) calls deb/rpm "the official and supported way". The frontend is embedded (`embed_frontend` feature in [release.yml](https://github.com/ffplayout/ffplayout/blob/v2.7.1/.github/workflows/release.yml)).
- **FFmpeg dependency:** the release binary is **dynamically linked** against FFmpeg 7.x dev libraries from `ppa:ubuntuhandbook1/ffmpeg7` on `ubuntu-latest`, with a check of libavformat >= 61 ([release.yml](https://github.com/ffplayout/ffplayout/blob/v2.7.1/.github/workflows/release.yml)). The deb only declares `libasound2t64` and suggests `ffmpeg` ([crates/app/Cargo.toml](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/Cargo.toml)), so you must install the libraries yourself. install.md asks for "FFmpeg 7.1+ runtime libraries and tools" (`ffmpeg`, `ffprobe`, `libavcodec`, `libavformat`, `libavutil`, `libswscale`, `libswresample`). Inferred: the soname must match the build (libavformat.so.61 = FFmpeg 7.x), so pick a distro that ships FFmpeg 7.1. Debian 13 does; Ubuntu 24.04's stock FFmpeg 6.1 does not. Check with `ldd /usr/bin/ffplayout`.
- **Docker:** 2.7.1 has no official runtime image. `docker/static.Dockerfile` is a build container that compiles a **statically linked FFmpeg 9.0** and produces a `.deb` with no FFmpeg runtime dependency ([docker/static.Dockerfile](https://github.com/ffplayout/ffplayout/blob/v2.7.1/docker/static.Dockerfile)). That is an option if the distro's FFmpeg is wrong. The old compose files are under `docker/old/`.
- **Fetch while online:** the `.deb`, the FFmpeg 7.1 runtime packages and their dependencies, and any fonts or media. Run first-time setup (`POST /api/setup` or `ffplayout -i`).
- **Runtime network:** in the fetched source, the only outbound HTTP (`reqwest`) is for remote playlist or media URLs (GET/HEAD) and the opt-in SMTP / HTTP-push notifications. I found no update check or telemetry. MoQ output is off unless added. Not exhaustive; see below.

## Generator constraints

- Times are f64 seconds. Wall-clock placement is cumulative `out - in` from `day_start`, so **errors accumulate**. Every item needs an exact probed length; anything over 11 s of drift makes playout re-sync by clock. Use real container durations (ffprobe `format.duration`), and set `duration` to the same value, because validation "corrects" it when it differs by more than 1.2 s.
- Items with `out - in < 1 s` are **skipped**. Never emit sub-second Filler.
- To land each Repeat on its fixed clock time, the generator should put explicit Filler items in the playlist rather than rely on ffplayout's end-of-day filler loop. That loop only pads the **end** of the day, not gaps between Blocks.
- Pick `day_start` = `06:00:00` explicitly; the default is `05:59:25`.
- **Images work as `source`** for Generated Filler stills. Recognised extensions: apng, avif, bmp, exr, gif, jpeg, jpg, png, psd, tga, tif, tiff, webp. The image is looped for `out` seconds (`is_image_source`, `add_probe`); with no `out` it defaults to 10 s. Set `in: 0`, `out: N`, `duration: N`. Images in the **filler folder** are only picked up if their extension is in `storage.extensions`.
- Media formats: anything the linked FFmpeg libraries decode. Output is conformed: scaling, letterbox, fps change, silence added for short audio, last frame held for short video ([README features](https://github.com/ffplayout/ffplayout/blob/v2.7.1/README.md)). There is a known issue with seeking into MPEG-TS **input** ([.dev/known_issues.md](https://github.com/ffplayout/ffplayout/blob/v2.7.1/.dev/known_issues.md)), so prefer mp4/mkv.
- No maximum item count was found.
- Validation flags clips whose audio and video stream lengths differ ([json_validate.rs](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/json_validate.rs)).
- Daylight saving: ffplayout works on local wall-clock seconds in the channel timezone and only detects ±1 h jumps. A DST Broadcast Day is 23 or 25 h; how the 24 h `length` behaves then is untested.

## Not verified

- `custom_filter`: parsed and round-tripped, but no consumer was found in the fetched app or engine files. Release builds use `--no-default-features --features embed_frontend` (no `ffmpeg-filter` feature). Assume it is **ignored** in 2.7.1 until tested.
- Exact FFmpeg soname requirement of the published `.deb`: inferred from the build workflow, not checked with `ldd`.
- No-phone-home: based on a grep of the files fetched (not the whole tree; a full clone timed out), plus Cargo dependencies. The embedded frontend was not checked for CDN assets.
- Mid-day reload, end-of-day trim and DST behaviour: read from code, not run.
