# Other tools for a verbatim-Repeat channel

Ticket: #3. Map: #1. ErsatzTV and Tunarr are covered by other tickets and are left out here.
Researched 2026-11-08 against project repos, docs, source code and release notes.

## Answer

No surveyed tool does must-have 2 (a **Repeat** replays the exact items aired earlier that Broadcast Day) out of the box.
Every turnkey pseudo-TV scheduler fills each slot independently, so a show scheduled three times a day advances three episodes.

The best fit is a **hybrid**: **ffplayout** as the playout engine, plus a small script of our own that writes each Broadcast Day's playlist.
ffplayout already covers linear playout, a 06:00 day start, filler padding, HLS for VLC, local files and offline running.
The script only has to do the part no tool does: fill Slots once per day, advance them daily, and write the same items N times at fixed clock times with filler between.

| Tool | Verdict |
|---|---|
| **ffplayout** | **Best engine.** Plays one JSON playlist per day, with `day_start` and filler built in, and outputs HLS. It has no series/Repeat logic, so we generate the playlist. |
| FieldStation42 | Close in spirit but no. It plays local folders offline, but each slot pulls the next episode (no Repeats), and it plays to a local MPV window, not a stream VLC can open. |
| dizqueTV | No. Plex is a hard dependency and it has no same-day Repeat concept. |
| Pseudo Channel | No. It is unmaintained (last push 2022), needs Plex, and drives a Plex client. |
| Liquidsoap | Building block, not a product. It is a scripting language that can produce HLS video, so we would write the scheduler in it. |
| CasparCG | Overkill. It is a broadcast graphics/playout server that needs a separate scheduling client. |

## Must-haves recap (from #1)

1. A Day Schedule of Blocks, each with a repeat count.
2. A Repeat replays the exact items aired earlier that Broadcast Day.
3. Slots are filled once per Broadcast Day and advance daily.
4. Repeats start at fixed clock times, and gaps are padded with Filler.
5. A configurable Broadcast Day start (default 06:00).
6. True linear playback.
7. Plain `Show/Season NN/` folders, no Plex/Jellyfin.
8. Offline at runtime.
9. Plays in VLC.

Nice to have: Generated Filler (schedule and "next up" cards).

## Candidates

### ffplayout: the best engine, needs a playlist generator

- Repo: https://github.com/ffplayout/ffplayout. Rust, GPL-3.0, ~600 stars, last push 2026-11-07; v2.7.1 released 2026-10-28, v2.8.0 in beta.
- It plays "a *JSON* playlist for each day, keeping the current playlist editable", and is "mostly designed to run as a system service on Linux" ([README](https://github.com/ffplayout/ffplayout/blob/master/README.md)).
- The playlist is a flat list of `{in, out, duration, source}` items (README example). **Nothing stops the same `source` from appearing three times in a day**, so verbatim Repeats are just a generated playlist. Covers 1, 2 and 3 if we write the generator.
- "set a custom day start, for example from 06:00 to 06:00", and "when playlist is not 24 hours long, loop fillers until time is full". It also says to "replace missing playlist or clip with single filler or multiple fillers from folder". Covers 5, and partly 4. The generator must insert filler items itself between Blocks so each Repeat lands on its clock time, because items play back to back.
- Output modes are "stream, desktop, HLS"; "HLS is the default output mode", written to `/public/<channel>/live/...m3u8` ([docs/output.md](https://github.com/ffplayout/ffplayout/blob/master/docs/output.md)). VLC opens an HLS URL (9). Playout is clock-driven, so tuning in joins mid-program (6).
- Sources are plain file paths, with no media-server dependency (7, partly). It has no library scanner or name editor; we would write that.
- Its built-in [template generator](https://github.com/ffplayout/ffplayout/blob/master/docs/playlist_gen.md) fills time ranges from folders, with or without shuffle. It has no "next episode" state and no repeat, so it does not replace our generator.
- It can [run an external task when a clip starts](https://github.com/ffplayout/ffplayout/blob/master/docs/external_tasks.md), and it can show [scheduled image/video graphics per clip](https://github.com/ffplayout/ffplayout/blob/master/docs/playlist_graphics.md) (experimental). These are possible hooks for Generated Filler. The simpler path is to render "next up" stills or clips ahead of time and list them as playlist items.
- Offline (8): it needs only FFmpeg libraries ("no special tools beyond FFmpeg libraries"). It ships as release packages; install while online.
- Caveat: ffplayout needs FFmpeg 7.0+ development libraries and recommends "at least 4 dedicated threads and 3GB RAM for 720p". Check that the laptop can keep up. The web frontend is optional ("run playout in foreground mode without frontend").

### FieldStation42: a local-folder TV simulator with no Repeats

- Repo: https://github.com/shane-mason/FieldStation42. Python, MPL-2.0, ~1.7k stars, very active (last push 2026-11-08).
- It runs on "Raspberry Pi, any Linux machine, or Windows via WSL" and needs Python 3.10+ and **MPV** (README). Content comes from a per-channel `content_dir` catalog of tag folders (e.g. `catalog/nbc_catalog`), with no Plex/Jellyfin ([confs/examples/traditional_network.json](https://github.com/shane-mason/FieldStation42/blob/main/confs/examples/traditional_network.json)). So 7 and 8 are met, but folders are organized by tag, not `Show/Season NN`.
- Scheduling is hour slots per weekday, each naming `tags`, with `day_templates`, `continued` slots, and **sequences** for in-order episodes ([docs/STATION_CONFIG_README.md](https://github.com/shane-mason/FieldStation42/blob/main/docs/STATION_CONFIG_README.md)).
- **No verbatim Repeats (fails 2).** Each sequence slot calls `SequenceAPI.get_next_in_sequence`, which advances a stored `current_index` ([fs42/liquid_schedule.py](https://github.com/shane-mason/FieldStation42/blob/main/fs42/liquid_schedule.py), [fs42/sequence_api.py](https://github.com/shane-mason/FieldStation42/blob/main/fs42/sequence_api.py)). The same sequence in the 06:00, 14:00 and 22:00 slots therefore plays three different episodes. Its "marathon" feature repeats the slot *config* for following hours, not the aired items (`assert buffer == [{"tags": "drama", ...}] * 2` in [test/test_marathon_agent.py](https://github.com/shane-mason/FieldStation42/blob/main/test/test_marathon_agent.py)).
- **No stream output (fails 9).** It plays into a local MPV window as the "TV". Its `streaming` network type *ingests* HLS/m3u8 feeds; it does not produce one. The code search showed no HLS or streaming output.
- Nice touches: a `guide` channel type ("Interactive program guide display"), bumps, commercials and an on-screen display. It is good to borrow ideas from for Generated Filler.

### dizqueTV: needs Plex

- Repo: https://github.com/vexorian/dizquetv. Node, Zlib license, still maintained: 1.6.0 (2025-12-01) and 1.7.0 (2025-12-15) are "edge" releases, and 1.5.5 is the stable one.
- It creates "live TV channel streams from media on your Plex servers" (README). The 1.7.0 notes describe the server proxying to "the Plex server(s)" and syncing filler from Plex collections. **Plex is a hard dependency (fails 7)**, and Plex needs its own library/metadata setup, which works against 8.
- Output is a fake HDHomeRun tuner and an M3U URL for IPTV players (VLC could open it). Filler can play "at specific times". 1.6.0 added "custom start and/or end time" per program. Neither feature gives same-day Repeats of daily-advancing content.

### Pseudo Channel: unmaintained, needs Plex

- Repos: https://github.com/justinemter/pseudo-channel (last push 2022-12-08) and its successor https://github.com/FakeTV/pseudo-channel (last push 2023-03-16).
- It requires a Plex Media Server via python-plexapi and *controls a Plex client* (e.g. RasPlex) at scheduled times, so it is not a stream VLC can tune into. A daily schedule is generated at midnight from `pseudo_schedule.xml`, and `strict-time` entries hold exact times. Series advance episode by episode, with no Repeat concept (README). Fails 2, 7 and 9, and it is stale.

### Others considered

- **Liquidsoap** (https://github.com/savonet/liquidsoap, GPL-2.0, very active): a stream-automation language. Its HLS output carries video through `%ffmpeg(... %video(codec="libx264" ...))` ([HLS output docs](https://www.liquidsoap.info/doc-dev/hls_output.html)). Clock-time switching and playlists are first-class, so it is a credible build-path engine. But we would program the scheduler in its own language, which is more than "write a JSON file per day".
- **CasparCG Server** (https://github.com/CasparCG/server, GPL-3.0, active): a pro broadcast playout and graphics server driven over AMCP by a separate client. It has no library or daily scheduler of its own, and is heavier than needed.
- **PseudoTV Live** (Kodi add-on): plays inside Kodi, not VLC, and is built on Kodi's library. Not checked further.
- **Owncast** (https://github.com/owncast/owncast): a self-hosted live-stream server that takes RTMP in and serves HLS out. It could sit behind any ffmpeg scheduler, but it schedules nothing itself and is not needed if ffplayout already writes HLS.

## Build-path building blocks

- **ffplayout as the playout layer** (above). The cheapest way to get must-haves 4, 5, 6, 8 and 9 for free. Our code becomes: library scan and name editor, Slot fill and daily advance, then writing `YYYY-MM-DD.json` with each Block's items repeated N times and padded with filler to the next clock time.
- **ffmpeg concat demuxer + `-re` + HLS muxer**: the do-it-yourself version of the same thing. You write a concat list (`file '...'`, with optional `inpoint`/`outpoint` for joining mid-file), read it in real time with `-re`, and output `-f hls -hls_flags delete_segments`. Caveats: the concat demuxer needs uniform codecs across files or a re-encode, and it has no clock sync, so restarting mid-day means computing the offset yourself. See the [ffmpeg formats docs: concat](https://ffmpeg.org/ffmpeg-formats.html#concat-1) and [hls](https://ffmpeg.org/ffmpeg-formats.html#hls-2). ffplayout exists largely to solve these caveats (conforming, clock sync, filler).
- **Liquidsoap**: a scriptable engine with clock-time switches and HLS video output (above).
- **Generated Filler**: render "next up" or schedule cards ahead of time as stills or short clips (e.g. ffmpeg `drawtext`, or render HTML to PNG and then use ffmpeg `-loop 1`), and list them as playlist items. ffplayout plays images as sources ("image source (will loop until out duration is reached)").
- **Idea from FieldStation42**: its `guide` channel and bump folders are a working reference for schedule displays.

## Not verified

- No tool was installed or run. Everything above comes from docs, source and release notes.
- ffplayout's exact behaviour with a hand-written playlist that is shorter or longer than 24h was not tested ("trim last clip", "loop fillers" are claims from the README). Nor was its CPU load on the laptop.
- The FieldStation42 wiki (hosted on fieldstation42.com and the GitHub wiki) was unreachable during research. The conclusions rest on its repo docs and source.
