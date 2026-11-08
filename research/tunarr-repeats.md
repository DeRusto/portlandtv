# Can Tunarr do verbatim same-day Repeats?

Ticket: [#5](https://github.com/DeRusto/portlandtv/issues/5). Map: [#1](https://github.com/DeRusto/portlandtv/issues/1).
Researched 2026-11-08 against Tunarr `main` and the latest release, v2026.11.1 (2026-11-02).

## Verdict: partially

Tunarr can now air the **exact same items** again later the same day while advancing to new
episodes the next day. The feature that does it is **Slot Linking**, in a group that **mixes
"continue" and "rerun" link modes**, inside the **Time Slots** editor. It first shipped in
**v1.3.0 (2026-05-19)**. If the earlier attempt used an older build, the feature did not exist yet.
Even on a newer build it is easy to miss: it sits behind a small "Link to existing slot" control in
each slot's dialog.

Two must-haves break or only half-fit:

- **#5 (Broadcast Day starts at 06:00):** the "day" a Repeat replays from always starts at the
  server's local **midnight**. The replay memory is wiped at 00:00, so a Repeat cannot cross
  midnight. A Day Schedule that starts at 06:00 works only if every Repeat ends by 24:00.
- **#1 (a Block with a repeat count):** Tunarr has no Block object and no "×3" setting. You build a
  Block by hand, one time slot per Slot per airing. A "Create Rerun Blocks" tool for exactly this
  exists in the code, but it is an unfinished stub and is hidden in the UI.

Smaller gaps: there is no name editor (you fix names with `tvshow.nfo` or by renaming the folder),
and Tunarr generates no now/next cards.

## How the mechanism works (from source)

- Every slot has its own episode cursor by default. "Linking" slots puts them in one **iteration
  group** with a shared cursor ([slot-linking.md][doc-link]).
- In a **mixed** group, each *continue* slot gets a `RecordingProgramIterator`. It plays the next
  episodes and records every item it plays into a **per-period buffer**. Each *rerun* slot gets its
  own `ReplayProgramIterator`, which replays that buffer from the start, in order
  ([ProgramIterator.ts][src-iter], [slotSchedulerUtil.ts `createSlotIterators`][src-util]).
  The UI's help text reads: "This slot replays content aired by continue slots earlier in the period."
  ([SlotLinkingControl.tsx][src-ui]).
- When a rerun slot runs out of recorded items, its **Overflow Behavior** setting decides what
  happens next: `flex` (the default) pads with Flex, and `continue` pulls new episodes
  ([CommonSlots.ts][src-types], `rerunOverflow`).
- The buffer and every replay cursor are reset whenever the generator crosses a period boundary.
  The boundary is `startTime.startOf(schedule.period)`, and the period is `day` or `week`, in the
  server's local time zone ([TimeSlotService.ts][src-ts], lines ~175 and ~216-223). So the
  Broadcast Day is midnight to midnight and cannot be set.
- Mixed modes are allowed only for **time-slot** schedules. Random-slot schedules reject them, and
  every group needs at least one continue slot ([slotGroupValidator.ts][src-val]).
- A group where every slot uses "rerun" behaves differently. It is the older `RerunProgramIterator`,
  which plays one episode in every member slot and then advances. That suits a one-episode Slot,
  but a mixed group is the one that copies a whole multi-episode Slot verbatim.
- Release history: slot linking came in PR #1838 (commit 32229e80, 2026-04-29), and mixed link
  modes in commit 807b4f64 (2026-05-01). Both shipped in **v1.3.0 (2026-05-19)**, and v1.3.1 and
  v1.3.3 fixed linking bugs ([releases][rel]). Upstream issue [#616 "Time slot rerun functionality"][i616]
  asked for this exact feature and was closed as implemented by #1838.

## Exact configuration (an 8h Block shown 3 times)

The example Block runs 00:00-08:00 and repeats at 08:00 and 16:00, so it fits inside the
midnight-to-midnight day. Each Slot of the Block (for example Show A at 00:00, Show B at 00:30, ...)
becomes one link group:

1. Add each show folder as a Local Media Source of type Shows, then scan it (see below).
2. Open the channel, then **Tools → Time Slots**. Set Period = **Day**, Pad Times = 30 min (or 5 or
   15), and keep Days to schedule (`maxDays`, default 365) as it is.
3. For each Slot in the original airing, add a time slot (for example 00:00, Show A, Order = Next).
   Leave its link mode at **Continue**. This slot advances one or more episodes each day.
4. For each Repeat, add a time slot at the same offset in the Repeat window (08:00 and 16:00 for
   Show A). In its dialog, use **Link to existing slot**, pick the 00:00 Show A slot, and set link
   mode = **Rerun** and Overflow Behavior = **Fill with Flex**.
5. Do the same for Show B (00:30, 08:30, 16:30) and every other Slot. One Block of 16 half-hour
   Slots × 3 airings comes to 48 time slots, all entered by hand.
6. Use the same Pad Times, Max Lateness and Max Overflow for the original and its reruns. Then the
   replayed items fit their windows the same way, and each rerun starts at a fixed clock time
   ([time-slots.md][doc-ts]).
7. Set a filler list on the channel (and optionally fallback filler per slot) for the Flex gaps
   ([flex.md][doc-flex]).
8. Preview the lineup before saving and check that 08:00 and 16:00 repeat the 00:00 items exactly.

**With a 06:00 Broadcast Day:** pick Block lengths and counts that end by 24:00, for example 6h × 3
(06:00, 12:00, 18:00). Fill 00:00-06:00 with separate content or Flex. An 8h × 3 schedule from 06:00
breaks: the third airing (22:00-06:00) loses its buffer at midnight. Reading the code, it then airs
Flex until 06:00 with `flex` overflow, or new episodes with `continue` overflow, which also throws
off the next day's recording. *(Worked out from reading the source, not tested.)*

An untested alternative: run Tunarr with a `TZ` whose midnight falls at 06:00 Portland time. The
IANA `Etc/` zones stop at ±12h, so this needs a POSIX TZ string, and it would show wrong local
times in XMLTV. It is not recommended without a test.

## Must-have scorecard

| # | Must-have | Tunarr | Notes |
|---|-----------|--------|-------|
| 1 | Blocks with a repeat count | Partial | No Block object. Built by hand from linked time slots. The "Create Rerun Blocks" modal is a stub (`rerunBlockProgramming = () => console.log('To do')`) and its menu item is commented out ([AddRerunBlockModal.tsx][src-modal], [ChannelProgrammingOrganizeOptions.tsx][src-org]) |
| 2 | Repeat replays the exact items | Yes | Mixed continue/rerun link group (v1.3.0+) |
| 3 | Slots filled once per day, advance daily | Yes | The continue slot's cursor carries on across days. The lineup is pre-generated for `maxDays` (default 365) and then loops, and it is rebuilt deterministically from the stored seed after scans ([schedules-reshuffle-on-loop.md][plan-loop]) |
| 4 | Repeats at fixed clock times, Flex padding | Yes | Time Slots plus Pad Times, Max Lateness and Max Overflow |
| 5 | Broadcast Day start configurable (06:00) | **No** | The period is fixed to local midnight. Workaround: make every Repeat end by 24:00 |
| 6 | True linear (join mid-program) | Yes | Position = `(now - startTime) % duration` ([plan-loop]) |
| 7 | Plain `Show/Season NN/` folders, no Plex/Jellyfin, name editor | Partial | Local Media Sources need no media server. Without NFO files, the show name comes from the folder and the episode number from the file name ([local/shows.md][doc-local]). No UI name editor found, so fix names with `tvshow.nfo` `<title>` or by renaming the folder |
| 8 | Offline Linux laptop | Likely yes | Docker image (ffmpeg included) or Linux x64 binaries plus your own ffmpeg ([installation.md][doc-install]). Local scanning reads files and NFOs only. Pull or install while online. A fully offline run was not tested |
| 9 | Plays in VLC | Yes | `http://HOST:8000/api/channels/m3u` (all channels), or per channel `/stream/channels/:id.m3u8` (HLS) and `/stream/channels/:id.ts` (MPEG-TS) ([clients/index.md][doc-clients], [streamApi.ts][src-stream]). VLC is named as a supported client |

## Filler and generated graphics

- Filler: build filler lists from any library. An "Other Videos" local folder works well for
  bumpers and ads. Head, pre, post, tail, mid-roll and fallback filler can be set per slot
  ([concepts.md][doc-concepts]). Filler for Flex is chosen at **stream time**, so the filler around
  a Repeat is not verbatim. Only the programs are.
- Generated Filler: **none**. Tunarr offers a channel watermark ([watermarks.md][doc-wm]) and a
  fallback still or uploaded image for Flex with no filler. It does not render schedule displays or
  "next up" cards. You would have to pre-render them yourself and add them as a filler folder.
- Tunarr always re-encodes through ffmpeg ([faq.md][doc-faq]), so plan for CPU load on the laptop.

## Coming soon (not usable yet)

The "infinite schedules" redesign would replace the time-slot and random-slot schedulers. Its plan
gives each placement a `rerun` option ("repeat the slot's most recent program") and IANA time zones.
The source PR #1927 "can't land as it stands", and the work is planned as 11 slices behind a feature
flag ([infinite-schedules README][arch-inf], last updated 2026-10-12). Do not count on it.

## Sources

[doc-link]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/scheduling/slot-linking.md
[doc-ts]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/scheduling/time-slots.md
[doc-concepts]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/scheduling/concepts.md
[doc-flex]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/channels/flex.md
[doc-local]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/media_sources/local/shows.md
[doc-install]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/getting-started/installation.md
[doc-clients]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/clients/index.md
[doc-wm]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/configure/channels/watermarks.md
[doc-faq]: https://github.com/chrisbenincasa/tunarr/blob/main/docs/misc/faq.md
[src-iter]: https://github.com/chrisbenincasa/tunarr/blob/main/server/src/services/scheduling/ProgramIterator.ts
[src-util]: https://github.com/chrisbenincasa/tunarr/blob/main/server/src/services/scheduling/slotSchedulerUtil.ts
[src-ts]: https://github.com/chrisbenincasa/tunarr/blob/main/server/src/services/scheduling/TimeSlotService.ts
[src-val]: https://github.com/chrisbenincasa/tunarr/blob/main/server/src/services/scheduling/slotGroupValidator.ts
[src-types]: https://github.com/chrisbenincasa/tunarr/blob/main/types/src/api/CommonSlots.ts
[src-ui]: https://github.com/chrisbenincasa/tunarr/blob/main/web/src/components/slot_scheduler/SlotLinkingControl.tsx
[src-modal]: https://github.com/chrisbenincasa/tunarr/blob/main/web/src/components/programming_controls/AddRerunBlockModal.tsx
[src-org]: https://github.com/chrisbenincasa/tunarr/blob/main/web/src/components/channel_config/ChannelProgrammingOrganizeOptions.tsx
[src-stream]: https://github.com/chrisbenincasa/tunarr/blob/main/server/src/api/streamApi.ts
[plan-loop]: https://github.com/chrisbenincasa/tunarr/blob/main/plans/schedules-reshuffle-on-loop.md
[arch-inf]: https://github.com/chrisbenincasa/tunarr/blob/main/architecture/infinite-schedules/README.md
[rel]: https://github.com/chrisbenincasa/tunarr/releases/tag/v1.3.0
[i616]: https://github.com/chrisbenincasa/tunarr/issues/616

- Docs: [slot-linking][doc-link], [time-slots][doc-ts], [concepts][doc-concepts], [flex][doc-flex], [local shows][doc-local], [installation][doc-install], [clients][doc-clients], [watermarks][doc-wm], [faq][doc-faq]
- Source: [ProgramIterator.ts][src-iter], [slotSchedulerUtil.ts][src-util], [TimeSlotService.ts][src-ts], [slotGroupValidator.ts][src-val], [CommonSlots.ts][src-types], [SlotLinkingControl.tsx][src-ui], [AddRerunBlockModal.tsx][src-modal], [ChannelProgrammingOrganizeOptions.tsx][src-org], [streamApi.ts][src-stream]
- Plans and releases: [schedules-reshuffle-on-loop.md][plan-loop], [infinite-schedules README][arch-inf], [v1.3.0 release][rel], [issue #616][i616]

Not checked: nothing was run. The midnight-truncation behaviour and offline startup come from
reading the source and docs, not from a test. Prove both on the laptop with the lineup preview
before you adopt Tunarr.
