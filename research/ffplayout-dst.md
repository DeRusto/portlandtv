# How ffplayout 2.7.1 handles the daylight-saving shift

Question (issue #12): when the clocks change, a **Broadcast Day** lasts 23 h or 25 h of wall-clock time. What does ffplayout 2.7.1 do on those days, and how should our generator write them so **Airings** still start at their clock times?

All source links point at tag `v2.7.1` (commit `2068b90`) of github.com/ffplayout/ffplayout. Paths below are relative to that tag.

## Short answer

- ffplayout reads the **wall clock** in a **per-channel IANA time zone**, so DST does affect it. Clip start times inside a playlist are **elapsed seconds**: `day_start` plus the running sum of clip lengths. When the two disagree by about 3600 s, ffplayout assumes the clocks changed. It records a `time_shift` and keeps playing without a cut.
- **Spring forward (23 h day):** playback carries on unbroken, an hour behind the clock. When the clock reaches `day_start` the clip that is playing is cut short, the rest of the playlist (about one hour) is dropped, and the next day starts on time. A 23 h playlist from us ends at exactly that moment, so nothing is dropped and Airings stay on their clock times.
- **Fall back (25 h day):** ffplayout loads the next playlist once **24 h of playlist time** have played. It never plays a 25th hour. By my reading of the code, the next day then starts an hour early and **stays an hour early, one day after another, until the next spring change**. I traced this by reading the code. I have not run it.
- Recommendation: give the ffplayout channel a **fixed-offset time zone (`Etc/GMT+8`, which is UTC-8 all year)** and let the generator handle DST. If you want something cheaper, first run the fall-back case with `--fake-time` (see Verification). If ffplayout gets back in sync by itself, a 23 h / 24 h playlist on the change days is enough.

## Facts from the source

### What "now" means: wall-clock time in the channel's time zone

- `time_now(timezone)` takes `Utc::now()` and converts it to the channel's `Tz`. With no time zone set it uses the OS zone (`iana_time_zone`), and if that fails, UTC. [`crates/app/src/utils/time_machine.rs` L53-75](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/time_machine.rs#L53-L75)
- `time_in_seconds(tz)` = `hour*3600 + minute*60 + second` of that local time. This is **local wall-clock seconds since midnight**, not elapsed time, so it jumps by ±3600 when DST starts or ends. [`crates/app/src/player/utils/mod.rs` L502-508](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs#L502-L508)
- `get_date` picks the playlist date from the same local time. Before `day_start` it uses yesterday's date, but only when `seek` is true (on startup or re-init). [`mod.rs` L510-530](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs#L510-L530)
- `day_start` and `length` are parsed as plain `HH:MM:SS` to seconds (`time_to_sec`; the time zone is only used for `"now"`). `length` with no `:` means 86400. [`crates/app/src/utils/config.rs` L1619-1625](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/config.rs#L1619-L1625), [`mod.rs` L570-579](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs#L570-L579)

### Time zone setting

- Each channel has a `timezone: Option<Tz>` ([`config.rs` L320-342](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/config.rs#L320-L342)). It is stored in the `channels` DB table. When that column is empty or unparseable, the OS zone is used ([`crates/app/src/db/models.rs` L76-90](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/db/models.rs#L76-L90)). You set it in the web UI (Channel config, which defaults to the browser's guess).
- It was added in PR #874 / commit `eb27cbb` "timezone per channel, fix #729" (Jan 2025). Before that, ffplayout used the system local time zone. Any IANA name parsed by `chrono_tz` works, including fixed-offset names such as `Etc/GMT+8` and `UTC`. A `TZ` environment variable only matters when the channel's time zone is empty, through `iana_time_zone`. I did not check how `iana_time_zone` treats `TZ` on Linux.

### What "where we are in the playlist" means: elapsed seconds

- When a playlist is loaded, each clip gets `begin = start_sec + Σ(previous out − seek)`. That is elapsed time from `day_start` and can go past 86400 for clips after midnight. [`crates/app/src/player/utils/json_serializer.rs` L76-97](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/json_serializer.rs#L76-L97)
- `get_delta(config, begin)` returns `delta = begin − now_wall` (with ±86400 wrap handling) and `total_delta` = wall seconds until the next `day_start` (`start − now` or `length + start − now`). [`mod.rs` L609-646](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/utils/mod.rs#L609-L646)

### Explicit DST handling: the "time change" branch

The check runs in `timed_source`, once per clip at the moment the clip starts, and only when `playlist.length` contains `:`:

```rust
// Handle summer/winter time changes.
// It only checks if the time change is one hour backwards or forwards.
if is_close(shifted_delta.abs(), 3600.0, self.config.general.stop_threshold) {
    warn!(... "A time change seemed to have occurred, apply time shift: ...");
    self.set_status(&None, time_shift + shifted_delta).await;
} else if self.manager.is_alive.load(Ordering::SeqCst) {
    error!(... "Clip begin out of sync for {delta:.3} seconds.");
    ... list_init = true; current_index = 0; node.skip = true;   // re-seek to wall clock
```

[`crates/app/src/player/input/playlist.rs` L496-570](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/input/playlist.rs#L496-L570)

- It is only reached when `|delta| > stop_threshold` (default **11 s**, `migrations/00001_create_tables.sql`). With `stop_threshold = 0` there is no sync checking at all.
- `shifted_delta = delta − time_shift`. `time_shift` only counts while `current_date == last_date` (L513-517).
- `time_shift` is saved to the DB (`channels.time_shift`) by `set_status` → `handles::update_stat`. It is reset to 0 the first time a playlist with a new date loads (L269-291). It is also applied when re-seeking after a restart or reload (`get_current_clip`, L320-333).
- This came from commit `3e6c198` "summer/winter time change awareness" (PR #817, 30 Oct 2024, the week Europe changed clocks). The author's comment admits it is a heuristic: "Production usage must be shown if this is sufficient". The test suite has no DST test (`crates/app/tests/playout_playlist.rs`).

### When ffplayout moves to the next day's playlist

`check_for_playlist` loads the next playlist when **any** of these is true ([`playlist.rs` L194-267](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/player/input/playlist.rs#L194-L267)):

1. `next_start >= length_sec`. `next_start` is the **playlist position** (`current.begin − start_sec + duration`, where `delta` here is ≈0 because `get_delta` is called with "now" as the begin). So after 24 h of playlist time it switches, whatever the clock says.
2. `total_delta` is within 2 s of 0 or of `length_sec`. This means the **wall clock** is at `day_start`.
3. The date has changed.

Other ways a day ends:

- **Cut:** when a clip starts and `total_delta` (wall seconds left until `day_start`) is shorter than the clip, `handle_list_end` cuts the clip to fit (L551-566, `last_clip_end` L51-82).
- **Pad:** if the playlist runs out before the wall-clock `day_start` and no new playlist was loaded, `fill_end` fills the gap with Filler (L802-814).

## What happens on each change day (traced from the code above)

Example: channel time zone `America/Los_Angeles`, `day_start = 06:00:00`, `length = 24:00:00`, the change at 02:00.

### Spring forward: 23 h day (e.g. Sat 2027-03-13 06:00 PST → Sun 06:00 PDT)

1. Up to 02:00 PST everything is in sync.
2. The clock jumps to 03:00 PDT. The next clip has `delta ≈ −3600`, so ffplayout logs the "time change" warning, sets `time_shift = −3600`, and **keeps playing without a break**. From here every clip airs one hour later on the clock than its `begin` says.
3. A 24 h playlist reaches wall 06:00 PDT after 23 h, with one hour of programming still unplayed. The clip playing then is cut to end at 06:00 (`handle_list_end`). Next, `total_delta ≈ 0`, so the next playlist loads. The new date resets `time_shift` to 0, and its first clip has `delta ≈ 0`. **Back in sync. Net effect: the last hour of the playlist is dropped, and everything between 02:00 and 06:00 aired an hour late.**
4. A **23 h playlist** from us: content after the jump was built for its real clock time, and the −3600 shift makes it play at that time. It runs out exactly at wall 06:00. `total_delta ≈ 0`, so the next day loads (or `fill_end` pads any rounding gap of more than 1 s). **Airings stay on their clock times.**

### Fall back: 25 h day (e.g. Sat 2027-11-06 06:00 PDT → Sun 06:00 PST)

1. The clock goes from 02:00 PDT back to 01:00 PST. The next clip has `delta ≈ +3600`, so ffplayout sets `time_shift = +3600` and keeps playing. Content now airs an hour **early** on the clock.
2. After 24 h of playlist time (wall **05:00 PST**), condition 1 (`next_start >= length_sec`) is met. `get_date(seek=false)` returns Sunday, and **Sunday's playlist loads an hour early**. `total_delta` is still ≈3600 at this point, so no padding is added.
3. Loading the new date resets `time_shift` to 0. Sunday's first clip then has `delta = 21600 − 18000 = +3600`, which matches the "time change" branch again, so `time_shift = +3600` comes straight back.
4. The same thing repeats every day: each playlist reaches 24 h of position at 05:00 and the next one starts at 05:00. **ffplayout stays an hour early until the spring change.** In spring, `delta − time_shift = 0 − 3600` matches the branch once more and the shift returns to 0.
5. A **25 h playlist** does not help. Condition 1 cuts it at 24 h of position, so the 25th hour never plays.

This is my reading of the code; I did not run it. If anything in steps 2–4 behaves differently in practice (for example the restart/`seek` path), that changes the recommendation below. See "Not verified".

## Known issues and discussions

- No issue mentions DST, daylight saving, or summer time (searched `daylight saving`, `DST`, `summer time`, `clock change`). The only DST work is PR **#817** (commit `3e6c198`), which has no description and no linked issue.
- **#729** "Add time zone for each channel" (feature, fixed in `eb27cbb`).
- **#877** "timezone problem v0.25.0-alpha1": playback ran hours ahead until the time zone was changed back and forth. Cause: a time zone change in the UI was not applied (fixed in `982c6f9`). Not related to DST.
- **#705**: playlists created after midnight but before `day_start` belong to the previous date. Not related to DST, but it confirms that a playlist's date is the date its `day_start` falls on.

## Options for our generator

Our Day Schedule always adds up to exactly 24 h.

| Option | Spring (23 h) | Fall (25 h) | Cost |
|---|---|---|---|
| **A. Local time zone, write 24 h every day (do nothing)** | Airings from 02:00 to 06:00 air 1 h late, the last hour is dropped, back in sync the next day | (per trace) everything is 1 h early until spring | none |
| **B. Local time zone, write 23 h on the spring day** (drop an hour of Filler or a Slot in the 02:00 hour), 24 h on the fall day | on clock time, ✔ | same as A: 1 h early, possibly for months, unless ffplayout re-syncs better than I traced (verify), or a manual Reset/restart after the change fixes it (not verified) | small |
| **C. Channel time zone `Etc/GMT+8` (fixed UTC-8), generator handles DST** | on clock time, ✔ | on clock time, ✔ | medium |
| **D. Channel time zone UTC** | as C | as C | as C, and the ffplayout UI shows UTC all year |
| **E. Fixed offset, Broadcast Day also fixed (accept a 1 h local shift in summer)** | — | — | trivial, but every Airing moves an hour on the local clock for half the year, which goes against "clock times" |

**Recommended: C.** ffplayout never sees a clock change. Every ffplayout day is exactly 24 h, and the DST heuristic never fires (the `|delta| ≈ 3600` branch needs a clock change to trigger). The generator works out what plays at each **absolute instant**, then writes it into 24 h ffplayout playlists that start at fixed 06:00 UTC-8:

- **Winter (PST):** an ffplayout day matches a Broadcast Day exactly. Nothing changes.
- **Summer (PDT):** an ffplayout day runs 07:00 PDT → 07:00 PDT. That is the last 23 h of Broadcast Day D followed by the first hour of Broadcast Day D+1. The generator must therefore have D+1's Slots ready one day early. If no Airing boundary falls at 07:00, the clip that crosses it is split between the two files with `seek`/`out`.
- **Change days:** the generator removes an hour (spring) or adds an hour (fall) of Filler or Slots in the local Broadcast Day. It decides this from the real elapsed length of that day, using `zoneinfo`.
- Costs: ffplayout's UI, logs, and playlist dates are in UTC-8, so in summer they read one hour behind local time. Playlist files no longer line up one-to-one with Broadcast Days for half the year. Setting the channel's time zone is a one-time UI/DB change.

**Cheaper alternative if verification goes well: B.** First test the fall-back day on the laptop with `--fake-time` (below). If ffplayout gets back in sync on Sunday by itself, B is enough. On the spring day, drop an hour of Filler (or the Airing in the hour that doesn't exist). On the fall day, write a normal 24 h playlist and accept that ffplayout silently skips the repeated hour. If it stays an hour early as traced, B also needs a scheduled channel Reset/restart after the fall change. That is fragile, so choose C.

## Verification recipe (not done)

ffplayout has a hidden `--fake-time <RFC3339>` flag. It moves the whole clock by a fixed offset from real time ([`time_machine.rs` L25-50](https://github.com/ffplayout/ffplayout/blob/v2.7.1/crates/app/src/utils/time_machine.rs#L25-L50)), so a DST change can be crossed in real time. On the laptop, use a test channel with time zone `America/Los_Angeles` and `day_start` around 01:58. Start with `--fake-time 2026-11-01T01:55:00-07:00` and two days of short playlists. Then watch the log for "A time change seemed to have occurred", which date's playlist loads, and when. Repeat with `2027-03-14T01:55:00-08:00`.

## Not verified

- The whole day-by-day trace above, especially the fall-back result (loads at 05:00, the +3600 shift comes back every day, stays early until spring). I traced it by reading the source. I did not run it: no Rust toolchain or ffmpeg here, and the repo has no DST test.
- How a restart or a UI "Reset" during the shifted period behaves (the `seek=true` path and `get_current_clip` with a saved `time_shift`).
- Whether a `TZ` environment variable or the systemd unit affects ffplayout when the channel's time zone is set. From the code it should not, because the channel's time zone wins. I did not read the systemd unit.
- Whether `Etc/GMT+8` round-trips through the ffplayout web UI's time zone picker (dayjs). The Rust side parses it with `chrono_tz`.
