# PortlandTV

A self-hosted linear TV channel built from a personal library of shows and movies, where a day's programming can be replayed verbatim several times.

## Language

**Channel**:
A single continuous linear stream of programming that viewers tune into.
_Avoid_: Station, feed

**Library**:
A folder of shows or movies that a Channel draws programming from; a Channel may draw from several.
_Avoid_: Source, collection

**Block**:
An ordered run of programming items (e.g. 8 hours) that forms the unit of repetition.
_Avoid_: Playlist, segment

**Day Schedule**:
The sequence of Blocks, each with a length and a repeat count, that exactly fills one Broadcast Day on a Channel; the same Day Schedule runs every Broadcast Day.
_Avoid_: Lineup, rotation

**Slot**:
A position in a Block defined by a rule (e.g. "next episode of Show A"), filled with a concrete item once per Broadcast Day.
_Avoid_: Entry, placeholder

**Show Group**:
An ordered list of shows that a Slot plays through one after another, as if they were one long show.
_Avoid_: Rotation, block

**Broadcast Day**:
The 24-hour period, starting at a configured clock time, over which a Day Schedule runs and Slots stay frozen.
_Avoid_: Calendar day

**Filler**:
Short content that pads a Block so each Repeat starts at its fixed clock time.
_Avoid_: Padding, bumper

**Generated Filler**:
Filler the app renders itself from the schedule, such as a "next up" card or a schedule display, as a still or clip.
_Avoid_: Bumper, interstitial

**Repeat**:
A replay of the exact same items a Block already aired earlier that day, not the next episodes in its series.
_Avoid_: Rerun, loop, rotation
