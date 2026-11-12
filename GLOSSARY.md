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
The sequence of Blocks, each with a length and a repeat count, that exactly fills one Broadcast Day on a Channel; the same Blocks run every Broadcast Day, though a distributed Slot's rule varies by weekday.
_Avoid_: Lineup, rotation

**Draft**:
The Day Schedule, Libraries, Show List and Show Groups as edited in the web UI, before they are saved.
_Avoid_: Form, pending config

**Review**:
What the web UI reports about a Draft: each Block's Airings and fill, the Show List's weeks left, and the Draft's problems.
_Avoid_: Report, validation

**Slot**:
A position in a Block defined by a rule (e.g. "next episode of Show A"), filled with a concrete item once per Broadcast Day. A **fixed** Slot has one rule all week; a **distributed** Slot has a weekday rule for each weekday.
_Avoid_: Entry, placeholder

**Weekday Rule**:
The rule a distributed Slot uses on one weekday, set by the Show List's distribution or by hand.
_Avoid_: Assignment, cell

**Show Group**:
An ordered list of shows that a Slot plays through one after another, as if they were one long show.
_Avoid_: Rotation, block

**Show List**:
The ordered list of shows and Show Groups that the app shares out across the weekdays, giving each an equal share of the distributed cells, taken in turn day by day. Grouping short shows so that each entry has about as many episodes left keeps them running out at about the same time.
_Avoid_: Lineup, rotation

**Broadcast Day**:
The 24-hour period, starting at a configured UTC clock time (no daylight-saving changes), over which a Day Schedule runs and Slots stay frozen; its weekday is that of the UTC date it starts on.
_Avoid_: Calendar day

**Filler**:
Short content that pads a Block so each Repeat starts at its fixed clock time.
_Avoid_: Padding, bumper

**Airing**:
One play of a Block within a Broadcast Day; the first is the original, the rest are its Repeats.
_Avoid_: Showing, run

**Break**:
The Filler that follows a Slot within an Airing, sized so the Airing ends exactly when the next begins.
_Avoid_: Gap, intermission, commercial break

**Generated Filler**:
Filler the app renders itself from the schedule, such as a "next up" card or a schedule display, as a still or clip.
_Avoid_: Bumper, interstitial

**Repeat**:
A replay of the exact same items a Block already aired earlier that day, not the next episodes in its series.
_Avoid_: Rerun, loop, rotation
