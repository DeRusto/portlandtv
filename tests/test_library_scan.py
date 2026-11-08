import os
import unittest

import yaml

from tests.harness import Station, utc

DAY1, DAY2 = utc(2026, 11, 9, 12, 0), utc(2026, 11, 10, 12, 0)


def schedule(show, slots):
    return {"day_schedule": [{"length": "24h", "repeat": 1,
                              "slots": [{"rule": {"show": show}}] * slots}]}


class LibraryScanTest(unittest.TestCase):
    def station(self, files, slots, show="Show", **kw):
        s = Station(schedule(show, slots), files, **kw)
        self.addCleanup(s.close)
        return s

    def aired(self, s, date):
        return [os.path.relpath(i["source"], s.root).replace(os.sep, "/")
                for i in s.playlist(date)["program"] if not i["source"].endswith(".png")]

    def test_only_known_extensions_and_no_hidden_files(self):
        s = self.station([
            "Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.M2TS",
            "Show/Season 1/Show - S01E03.flv", "Show/Season 1/Show - S01E04.wmv",
            "Show/Season 1/notes.txt", "Show/Season 1/cover.jpg",
            "Show/Season 1/.Show - S01E00.mkv", "Show/.hidden/Show - S01E05.mkv",
        ], slots=5)
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/Season 1/Show - S01E01.mkv", "shows/Show/Season 1/Show - S01E02.M2TS",
            "shows/Show/Season 1/Show - S01E03.flv", "shows/Show/Season 1/Show - S01E04.wmv",
            "shows/Show/Season 1/Show - S01E01.mkv"])  # 5th Slot wraps

    def test_extras_and_specials_are_skipped(self):
        s = self.station([
            "Show/Season 1/Show - S01E01.mkv",
            "Show/Season 1/Show - S01E01-sample.mkv", "Show/Season 1/Show - S01E01.sample.mkv",
            "Show/Season 1/Show - S01E02-trailer.mp4", "Show/Season 1/Show - S01E02-featurette.mp4",
            "Show/Season 1/behind the scenes/a.mkv", "Show/Season 1/SAMPLES/b.mkv",
            "Show/Extras/c.mkv", "Show/Featurettes/d.mkv", "Show/Deleted Scenes/e.mkv",
            "Show/Interviews/f.mkv", "Show/Scenes/g.mkv", "Show/Shorts/h.mkv",
            "Show/Trailers/i.mkv", "Show/Other/j.mkv", "Show/Sample/k.mkv",
            "Show/Season 00/Show - S00E01.mkv", "Show/Specials/Show - S00E02.mkv",
            "Show/Season 2/Show - S02E01.mkv",
        ], slots=3)
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/Season 1/Show - S01E01.mkv", "shows/Show/Season 2/Show - S02E01.mkv",
            "shows/Show/Season 1/Show - S01E01.mkv"])

    def test_season_placement_and_natural_sort(self):
        s = self.station([
            "Show/Season 10/x.mkv",
            "Show/Season 2/Disc 10/ep1.mkv", "Show/Season 2/Disc 9/ep2.mkv",
            "Show/Season 2/Disc 9/ep10.mkv",
            "Show/Show - S03E01.mkv",            # loose: season from SxxEyy
            "Show/Misc/Show - S04E01.mkv",       # not a season folder
            "Show/pilot.mkv",                    # no SxxEyy: Season 1
        ], slots=7)
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/pilot.mkv",
            "shows/Show/Season 2/Disc 9/ep2.mkv", "shows/Show/Season 2/Disc 9/ep10.mkv",
            "shows/Show/Season 2/Disc 10/ep1.mkv",
            "shows/Show/Show - S03E01.mkv", "shows/Show/Misc/Show - S04E01.mkv",
            "shows/Show/Season 10/x.mkv"])

    def test_same_named_shows_merge_across_libraries_without_duplicates(self):
        s = self.station(
            ["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
            slots=3, more_shows={"drive2": [
                "Show/Season 01/show.s01e02.720p.mkv", "Show/Season 01/show.s01e03.mkv"]})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/Season 1/Show - S01E01.mkv", "shows/Show/Season 1/Show - S01E02.mkv",
            "drive2/Show/Season 01/show.s01e03.mkv"])

    def test_unplayable_files_are_left_out_and_reported(self):
        s = self.station(
            ["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv",
             "Show/Season 1/Show - S01E03.mkv"],
            slots=1, durations={"Show - S01E01.mkv": None,
                                "Show - S01E02.mkv": RuntimeError("ffprobe: invalid data")})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), ["shows/Show/Season 1/Show - S01E03.mkv"])
        self.assertEqual(sorted(s.service.unplayable),
                         [s.path("Show/Season 1/Show - S01E01.mkv"),
                          s.path("Show/Season 1/Show - S01E02.mkv")])

    def test_durations_cached_so_only_new_or_changed_files_are_probed(self):
        s = self.station(["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
                         slots=1)
        s.tick(DAY1)
        self.assertEqual(sorted(set(s.prober.calls)),
                         [s.path("Show/Season 1/Show - S01E01.mkv"),
                          s.path("Show/Season 1/Show - S01E02.mkv")])
        s.prober.calls.clear()
        with open(s.path("Show/Season 1/Show - S01E02.mkv"), "w") as f:
            f.write("re-encoded")
        open(s.path("Show/Season 1/Show - S01E03.mkv"), "w").close()
        s.tick(DAY2)
        self.assertEqual(sorted(set(s.prober.calls)),
                         [s.path("Show/Season 1/Show - S01E02.mkv"),
                          s.path("Show/Season 1/Show - S01E03.mkv")])

    def test_progress_stores_path_and_key(self):
        s = self.station(["Show/Season 1/Show - S01E01.mkv", "Show/Season 2/Show - S02E05.mkv"],
                         slots=2)
        s.tick(DAY1)
        self.assertEqual(s.read_json("state.json")["shows"]["Show"],
                         {"path": s.path("Show/Season 2/Show - S02E05.mkv"), "key": [2, 5]})

    def test_deleted_or_renamed_last_episode_resumes_at_next_by_key(self):
        files = ["Show/Season 1/Show - S01E0%d.mkv" % n for n in (1, 2, 3, 4)]
        s = self.station(files, slots=2)
        s.tick(DAY1)  # airs E01, E02
        os.rename(s.path(files[1]), s.path("Show/Season 1/Show 1x02 (renamed) S01E02.mkv"))
        os.remove(s.path(files[0]))
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"), ["shows/" + files[2], "shows/" + files[3]])

    def test_renamed_show_folder_is_a_new_show_from_e01(self):
        s = self.station(["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
                         slots=1)
        s.tick(DAY1)
        os.rename(s.path("Show"), s.path("New Name"))
        with open(s.config_path, "w") as f:
            yaml.safe_dump({"libraries": [{"path": s.library, "kind": "shows"}],
                            **schedule("New Name", 1)}, f)
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"),
                         ["shows/New Name/Season 1/Show - S01E01.mkv"])


if __name__ == "__main__":
    unittest.main()
