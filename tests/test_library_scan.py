import json
import os
import shutil
import tempfile
import unittest

import yaml

from portlandtv import library
from tests.fakes import FakeProber
from tests.harness import Channel, utc

DAY1, DAY2 = utc(2026, 11, 9, 12, 0), utc(2026, 11, 10, 12, 0)


def schedule(show, slots):
    return {"day_schedule": [{"length": "24h", "repeat": 1,
                              "slots": [{"rule": {"show": show}}] * slots}]}


class LibraryScanTest(unittest.TestCase):
    def channel(self, files, slots, show="Show", **kw):
        s = Channel(schedule(show, slots), files, **kw)
        self.addCleanup(s.close)
        return s

    def aired(self, s, date):
        return [os.path.relpath(i["source"], s.root).replace(os.sep, "/")
                for i in s.playlist(date)["program"] if not i["source"].endswith(".png")]

    def test_only_known_extensions_and_no_hidden_files(self):
        s = self.channel([
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
        s = self.channel([
            "Show/Season 1/Show - S01E01.mkv",
            "Show/Season 1/Show - S01E01-sample.mkv", "Show/Season 1/Show - S01E01.sample.mkv",
            "Show/Season 1/Show - S01E02-trailer.mp4", "Show/Season 1/Show - S01E02-featurette.mp4",
            "Show/Season 1/behind the scenes/a.mkv", "Show/Season 1/SAMPLES/b.mkv",
            "Show/Extras/c.mkv", "Show/Featurettes/d.mkv", "Show/Deleted Scenes/e.mkv",
            "Show/Interviews/f.mkv", "Show/Scenes/g.mkv", "Show/Shorts/h.mkv",
            "Show/Trailers/i.mkv", "Show/Other/j.mkv", "Show/Sample/k.mkv",
            "Show/Season 00/Show - S00E01.mkv", "Show/Specials/Show - S00E02.mkv",
            "Show/Season 2/Show - S02E01.mkv",
            "Show/Season 2/trailer.mkv", "Show/Season 2/sample.mp4",
        ], slots=3)
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/Season 1/Show - S01E01.mkv", "shows/Show/Season 2/Show - S02E01.mkv",
            "shows/Show/Season 1/Show - S01E01.mkv"])

    def test_season_placement_and_natural_sort(self):
        s = self.channel([
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
        s = self.channel(
            ["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
            slots=3, more_shows={"drive2": [
                "Show/Season 01/show.s01e02.720p.mkv", "Show/Season 01/show.s01e03.mkv"]})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), [
            "shows/Show/Season 1/Show - S01E01.mkv", "shows/Show/Season 1/Show - S01E02.mkv",
            "drive2/Show/Season 01/show.s01e03.mkv"])

    def test_unplayable_files_are_left_out_and_reported(self):
        s = self.channel(
            ["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv",
             "Show/Season 1/Show - S01E03.mkv"],
            slots=1, durations={"Show - S01E01.mkv": None,
                                "Show - S01E02.mkv": RuntimeError("ffprobe: invalid data")})
        s.tick(DAY1)
        self.assertEqual(self.aired(s, "2026-11-09"), ["shows/Show/Season 1/Show - S01E03.mkv"])
        self.assertEqual(sorted(s.service.unplayable),
                         [s.path("Show/Season 1/Show - S01E01.mkv"),
                          s.path("Show/Season 1/Show - S01E02.mkv")])

    def test_a_probe_that_fails_is_retried_on_the_next_build(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv"], slots=1,
                         durations={"Show - S01E01.mkv": RuntimeError("ffprobe: timed out")})
        s.tick(DAY1)
        s.prober.table.clear()
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"), ["shows/Show/Season 1/Show - S01E01.mkv"])
        self.assertEqual(s.service.unplayable, [])

    def test_a_missing_movies_or_filler_library_is_a_generation_error(self):
        for kind in ("movies", "filler"):
            with self.subTest(kind):
                s = self.channel(["Show/Season 1/Show - S01E01.mkv"], slots=1)
                raw = yaml.safe_load(open(s.config_path))
                gone = os.path.join(s.root, "gone")
                raw["libraries"].append({"path": gone, "kind": kind})
                with open(s.config_path, "w") as f:
                    yaml.safe_dump(raw, f)
                s.tick(DAY1)
                self.assertIn(gone, s.service.error)
                self.assertIsNone(s.playlist("2026-11-09"))

    def test_unplayable_filler_is_left_out_and_reported(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv"], slots=1,
                         filler=["broken.mp4", ".hidden.mp4", "ok.mp4"],
                         durations={"broken.mp4": None})
        s.tick(DAY1)
        sources = [i["source"] for i in s.playlist("2026-11-09")["program"]]
        self.assertIn(os.path.join(s.filler, "ok.mp4"), sources)
        self.assertNotIn(os.path.join(s.filler, "broken.mp4"), sources)
        self.assertNotIn(os.path.join(s.filler, ".hidden.mp4"), sources)
        self.assertEqual(s.service.unplayable, [os.path.join(s.filler, "broken.mp4")])

    def test_durations_cached_so_only_new_or_changed_files_are_probed(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
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

    def test_a_scan_cut_short_keeps_the_durations_it_probed(self):
        with tempfile.TemporaryDirectory() as root:
            paths = [os.path.join(root, f"{n}.mkv") for n in range(library.SAVE_EVERY)]
            for p in paths:
                open(p, "w").close()
            cache = os.path.join(root, "durations.json")
            first = library.CachedProber(FakeProber(), cache)
            for p in paths:
                first.duration(p)  # never saved by hand: the page load was abandoned
            again = FakeProber()
            for p in paths:
                library.CachedProber(again, cache).duration(p)
            self.assertEqual(again.calls, [])

    def test_progress_survives_a_crash_between_the_day_record_and_the_state(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv",
                          "Show/Season 1/Show - S01E03.mkv"], slots=1)
        s.tick(DAY1)
        # the day record was written, then the process died before state.json was
        with open(s.service.paths.state, "w") as f:
            json.dump(s.read_json("days/2026-11-09.json")["state_before"], f)
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"), ["shows/Show/Season 1/Show - S01E02.mkv"])

    def test_progress_stores_path_and_key(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv", "Show/Season 2/Show - S02E05.mkv"],
                         slots=2)
        s.tick(DAY1)
        self.assertEqual(s.read_json("state.json")["shows"]["Show"],
                         {"path": s.path("Show/Season 2/Show - S02E05.mkv"), "key": [2, 5]})

    def test_deleted_or_renamed_last_episode_resumes_at_next_by_key(self):
        files = ["Show/Season 1/Show - S01E0%d.mkv" % n for n in (1, 2, 3, 4)]
        s = self.channel(files, slots=2)
        s.tick(DAY1)  # airs E01, E02
        os.rename(s.path(files[1]), s.path("Show/Season 1/Show 1x02 (renamed) S01E02.mkv"))
        os.remove(s.path(files[0]))
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"), ["shows/" + files[2], "shows/" + files[3]])

    def test_renamed_show_folder_is_a_new_show_from_e01(self):
        s = self.channel(["Show/Season 1/Show - S01E01.mkv", "Show/Season 1/Show - S01E02.mkv"],
                         slots=1)
        s.tick(DAY1)
        os.rename(s.path("Show"), s.path("New Name"))
        with open(s.config_path, "w") as f:
            yaml.safe_dump({"libraries": [{"path": s.library, "kind": "shows"}],
                            **schedule("New Name", 1)}, f)
        s.tick(DAY2)
        self.assertEqual(self.aired(s, "2026-11-10"),
                         ["shows/New Name/Season 1/Show - S01E01.mkv"])


class CatalogueTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for rel in ("shows/Show/Show - S01E01.mkv", "shows/Show/Show - S01E02.mkv",
                    "movies/Good.mkv", "movies/Bad.mkv", "filler/ok.mp4", "filler/broken.mp4"):
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        self.libs = [{"path": os.path.join(self.root, k), "kind": k}
                     for k in ("shows", "movies", "filler")]

    def scan(self, libs, measure=True):
        prober = FakeProber({"Show - S01E02.mkv": None, "Bad.mkv": None, "broken.mp4": None})
        cache = library.CachedProber(prober, os.path.join(self.root, "durations.json"), measure)
        return library.catalogue(libs, cache)

    def rel(self, paths):
        return sorted(os.path.relpath(p, self.root).replace(os.sep, "/") for p in paths)

    def test_unplayable_files_of_every_kind_are_left_out_and_listed(self):
        found = self.scan(self.libs)
        self.assertEqual({n: self.rel(e) for n, e in found.shows.items()},
                         {"Show": ["shows/Show/Show - S01E01.mkv"]})
        self.assertEqual(self.rel(found.movies), ["movies/Good.mkv"])
        self.assertEqual(self.rel(found.filler), ["filler/ok.mp4"])
        self.assertEqual(self.rel(found.unplayable), ["filler/broken.mp4", "movies/Bad.mkv",
                                                      "shows/Show/Show - S01E02.mkv"])

    def test_files_not_measured_yet_are_playable(self):
        found = self.scan(self.libs, measure=False)
        self.assertEqual(len(found.shows["Show"]) + len(found.movies) + len(found.filler), 6)
        self.assertEqual(found.unplayable, [])

    def test_missing_folders_are_listed_and_empty_paths_skipped(self):
        gone = os.path.join(self.root, "gone")
        found = self.scan(self.libs + [{"path": gone, "kind": "shows"},
                                       {"path": "", "kind": "movies"}])
        self.assertEqual(found.missing, [gone])
        self.assertEqual(list(found.shows), ["Show"])


if __name__ == "__main__":
    unittest.main()
