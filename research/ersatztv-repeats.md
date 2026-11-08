# Can ErsatzTV do verbatim same-day Repeats?

Ticket: #2 (map #1). Researched 2026-11-08 against ErsatzTV **v26.12.0** (repo `ErsatzTV/legacy`, which `ErsatzTV/ErsatzTV` now redirects to) and the official docs at ersatztv.org (source: `ErsatzTV/ErsatzTV.org`, folder `docs-legacy/`).

## Verdict: partially. A workaround meets every must-have, but there is no native Repeat

ErsatzTV has no "replay this Block's items" feature. No scheduler (classic, block, sequential/YAML, scripted) can replay items aired earlier in the day. But **how it stores playout history** gives a reliable workaround: **clone the Block once per Repeat.** Every clone advances once per day, in lockstep, so each Repeat airs the same episodes as the first airing.

What breaks, or only half works:
- **Must-have 1 (repeat count):** there is no repeat-count field. You emulate it by cloning the Block N times. After any change to a Slot you must edit all N copies identically, or the Repeats drift apart.
- **Must-have 2 holds only for deterministic playback orders** (`Chronological` and `Season, Episode`). It fails for `Shuffle`/`Random`, because the seed includes the BlockId (see below).
- **Must-have 7 (name editor):** I found no UI metadata editor in the docs. Names come from folder or file names, or from NFO sidecar files. You fix a name by renaming the folder or writing a `tvshow.nfo`.

## Why there is no native Repeat

- Block items always use Playout Mode "One", and each block item takes the **next** item from its enumerator ([docs: Block Schedules](https://ersatztv.org/docs/scheduling/block/)). `BlockPlayoutBuilder.cs` schedules one item per block item, then calls `enumerator.MoveNext(...)` and records a `PlayoutHistory` row.
- Sequential (YAML) schedules: every instruction (`all`, `count`, `duration`, `pad_to_next`, `pad_until`, `sequence` with `repeat: N`) draws the **next** items from a content enumerator ([docs: Playout Instructions](https://ersatztv.org/docs/scheduling/sequential/playout)). The top-level `repeat: true` only restarts the *instruction list*. It does not rewind content.
- Two features look like they help but don't. There is an undocumented YAML `rewind` instruction, a reset-only handler (`YamlPlayoutRewindHandler.cs`), but it only does `context.CurrentTime -= amount`, which moves the clock, not the content. `skip_items` and `skip_to_item` only go forward or to an absolute S/E, and are meant for `reset`.
- Scripted schedules: the OpenAPI (`ErsatzTV/wwwroot/openapi/scripted-schedule.json`) exposes `add_count`, `add_duration`, `add_show`, `peek_next/{content}`, `skip_items`, `skip_to_item`, `pad_until`, `wait_until`, `graphics_on`, and others. I found no endpoint to add a specific media item by id, and no read access to past playout items. A script could call `peek_next` and then `skip_to_item` to rewind a Show to an absolute season and episode. That is fragile and only works for episodic content.

## Why cloning works (the key mechanism)

`ErsatzTV.Core/Scheduling/HistoryDetails.cs`:

```csharp
public static string KeyForBlockItem(BlockItem blockItem) =>
    { blockItem.BlockId, blockItem.PlaybackOrder, blockItem.CollectionType,
      blockItem.CollectionId, ..., blockItem.SearchQuery }
```

`BlockPlayoutEnumerator.cs` (Chronological / SeasonEpisode) restores the position from history filtered by `h.BlockId == blockItem.BlockId && h.Key == historyKey`.

So **each Block keeps its own position per collection.** If Blocks `A`, `A rpt 1` and `A rpt 2` have identical items, and each airs exactly once per day, then:
- Day 1: all three start at their first item, so they air the same episodes.
- Each advances by the same count, because the same item durations hit the same block length and `StopScheduling` decisions. Day 2: all three air the next episodes.

**Copy Block** exists in the UI (`Pages/Blocks.razor`, `CopyBlockHandler.cs`). It copies the items, watermarks and graphics into a new Block with a new id, which means fresh history.

Shuffle caveat: `Shuffle` seeds with `playoutSeed + blockItem.BlockId`, so clones shuffle differently. Do not use Shuffle or Random in Slots.

The same trick works in **sequential YAML**: the history key is `{Key, Order}` (`KeyForYamlContent`). Define the same show under N content keys (`SHOW_A_1`, `SHOW_A_2`, `SHOW_A_3`) and use each one exactly once per day with `count: 1`.

## Exact configuration (Block schedule): Day Schedule of one 8h Block ×3, Broadcast Day at 06:00

1. **Libraries:** add a Local library of kind *Shows* that points at the `Show/Season NN/` folder. Optionally add a second local library (*Other Videos*) for filler. Make a Manual Collection or Smart Collection for the filler.
2. **Block** `Day A`: duration 480 min, Stop Scheduling = *Before Duration End*. This keeps fixed start times; the leftover is padded by filler. Add one block item per Slot, for example Television Show "Show A", playback order *Season, Episode*. Use *Chronological* for movies or other collections.
3. **Copy Block** twice: `Day A rpt 1` and `Day A rpt 2`. Do this before the playout's first build, or **reset the playout** after cloning so all three start from the same position.
4. **Template** `Daily`: `Day A` at 06:00, `Day A rpt 1` at 14:00, `Day A rpt 2` at 22:00. Templates are calendar-day based (`EffectiveBlock.cs` builds starts from midnight + `StartTime`). A 22:00 block of 480 min simply runs to 06:00, because its finish is computed as `Start + Minutes`. That gives an effective 06:00 Broadcast Day. Not tested: whether the template editor UI accepts a block that crosses midnight.
5. **Deco** with Default Filler = your filler collection and *Trim To Fit* on. Optionally set Dead Air Fallback. Put it on a deco template or the playout's default deco.
6. **Playout Template**: `Daily` for all days. Create the playout for the channel as type *Block*.
7. Verify on the playout detail page: the 06:00 / 14:00 / 22:00 runs list identical items, and the next day's 06:00 has the next episodes. *Troubleshooting → Block Playout History* shows the per-Block positions.

Must-have checklist with this setup:

| # | Must-have | Status |
|---|---|---|
| 1 | Blocks with repeat count | Emulated (N cloned Blocks) |
| 2 | Repeat = exact same items | Yes, for Season/Episode and Chronological orders |
| 3 | Slots fill once per day and advance daily | Yes (each clone airs once per day) |
| 4 | Repeats at fixed clock times; gaps padded with Filler | Yes (template start times, Stop Scheduling *Before Duration End*, Deco default filler) |
| 5 | Configurable Broadcast Day start | Yes, by where the first Block sits in the template |
| 6 | True linear playback | Yes (it is a live channel stream) |
| 7 | Plain folder, names from paths, no Plex/Jellyfin | Yes. Name editor: no (rename folders or use NFO) |
| 8 | Offline Linux at runtime | Likely yes (see below) |
| 9 | VLC | Yes |

## Other must-haves

- **Local folders without Plex/Jellyfin** ([docs: Local Shows](https://ersatztv.org/docs/media/local/shows)): layout `Show (Year)/Season 01/Show - S01E01.mkv`. Without NFOs, the show title and year come from the folder name, the season from the folder, and the episode number and title from the filename. NFO sidecars (`tvshow.nfo`, `<episode>.nfo`) override this. The page describes no online lookups.
- **Offline Linux:** native install means extracting the release, running `ErsatzTV`, and pointing it at the ErsatzTV FFmpeg/FFprobe builds. The UI is on port 8409 ([docs: Linux](https://ersatztv.org/docs/installation/linux)). Docker also works. Local libraries use only NFO and filename metadata. Not tested: an actual air-gapped run. The docs say nothing about runtime internet use either way.
- **VLC** (`ErsatzTV/Controllers/IptvController.cs`): `http://<host>:8409/iptv/channels.m3u` is the playlist, and `/iptv/xmltv.xml` is the guide. Per-channel streams are `/iptv/channel/{n}.ts` (MPEG-TS) and `/iptv/channel/{n}.m3u8` (HLS), plus `/iptv/hls-direct/{n}`. Streaming modes are HLS Segmenter, MPEG-TS, HLS Direct and MPEG-TS (Legacy) ([docs: Channels](https://ersatztv.org/docs/channels/)). VLC opens M3U and TS/HLS URLs directly.
- **Generated now/next graphics** ([docs: Graphics Engine](https://ersatztv.org/docs/advanced/graphics-engine/)): YAML graphics elements (image, text, subtitle/.ass, motion video, script) are overlaid on the stream. You attach them per block item or deco, or with `graphics_on` in YAML or scripted schedules. Text uses Scriban templates. With `epg_entries: N`, the template gets the next N XMLTV programmes: `Title`, `SubTitle`, `Description`, `Start`, `Stop`, and others (`TemplateDataRepository.cs`). It also gets `MediaItem_*` variables (`Title`, `ShowTitle`, `Duration`, and others). So an "Up next" overlay is possible. **Generated filler clips or stills** (a standalone schedule card as its own item) are not a feature. Workarounds: overlay text on a looping filler clip (graphics plus a filler collection), or pre-render cards externally into the filler folder.

## Risks and notes

- Drift: if someone edits one clone and not the others, or a Slot uses Shuffle, the Repeats silently stop matching. Changing a Block's items may invalidate its history (the key includes the collection), so after editing, reset the playout to resync.
- `ErsatzTV/next` (created 2026-03) is a separate rewrite with its own config model (lineup/channel/playout reference). I did not evaluate it. All of the above is about the current `legacy` app.
- Not tested hands-on. Everything here comes from docs and source reading.
