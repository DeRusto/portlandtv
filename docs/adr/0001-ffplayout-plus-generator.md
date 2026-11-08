# Build a schedule generator on top of ffplayout

No existing pseudo-TV tool does verbatim same-day Repeats natively, so PortlandTV uses ffplayout as its playout engine and adds a generator of its own that fills Slots once per Broadcast Day and writes each Block's items N times into ffplayout's daily JSON playlist. ffplayout already covers the per-day playlist, a configurable day start, filler padding, HLS to VLC and offline running, so only the scheduling logic is ours.

## Considered Options

- **ErsatzTV, one copied Block per Repeat:** works with no code, but every Day Schedule edit must be repeated in each copy, and a missed copy silently breaks the Repeat; the schedule must be editable at will.
- **Tunarr Slot Linking:** replays exact items, but its day resets at midnight (breaking the 06:00 Broadcast Day) and it has no Block × N.
- **Full custom build:** would rebuild the playout ffplayout already provides.
