import os
import threading
import time
import unittest

import yaml

from tests.harness import Channel, utc
from tests.web_harness import Browser

FILES = ["Show A/Show A - S01E01.mkv", "Show A/Show A - S01E02.mkv",
         "Show A/Show A - S01E03.mkv", "Show B/b.s01e01.mp4"]
DURATIONS = {"Show A - S01E01.mkv": 1200.0, "Show A - S01E02.mkv": 1500.0,
             "Show A - S01E03.mkv": 1300.0, "b.s01e01.mp4": 1800.0}
CONFIG = {"day_start": "06:00", "day_schedule": [
    {"length": "8h", "repeat": 2, "slots": [{"rule": {"show": "Show A"}}]},
    {"length": "4h", "repeat": 2, "slots": [{"rule": {"show": "Show B"}}]},
]}


def wait_for(check, seconds=5):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


class WebTest(unittest.TestCase):
    def open(self, config=CONFIG):
        s = Channel(config, FILES, DURATIONS)
        self.addCleanup(s.close)
        b = Browser(s)
        b.get()
        return b

    def test_block_header_shows_length_repeat_and_airing_starts(self):
        html = self.open().html
        self.assertIn("8h × 2", html)
        self.assertIn("Airs 06:00, 14:00 UTC", html)
        self.assertIn("4h × 2", html)
        self.assertIn("Airs 22:00, 02:00 UTC", html)

    def test_page_assets_are_served_locally(self):
        b = self.open()
        self.assertNotRegex(b.html, r'(src|<link[^>]*href)="(https?:)?//')  # the stream link is not an asset
        for asset in ("/static/style.css", "/static/app.js"):
            self.assertIn(asset, b.html)
            self.assertEqual(b.client.get(asset).status_code, 200)

    def test_page_links_the_stream_on_the_host_it_was_opened_on(self):
        s = Channel(CONFIG, FILES, DURATIONS)
        self.addCleanup(s.close)
        b = Browser(s)
        html = b.client.get("/", base_url="http://192.168.1.20:8080").get_data(as_text=True)
        self.assertIn('href="http://192.168.1.20:8787/public/1/live/stream.m3u8"', html)

    def test_folder_picker_lists_subfolders_and_opens_the_nearest_real_folder(self):
        b = self.open()
        root = b.channel.root
        f = b.client.get("/folders", query_string={"path": root}).get_json()
        self.assertEqual(f["path"], root)
        self.assertEqual(f["parent"], os.path.dirname(root))
        self.assertIn({"name": "shows", "path": os.path.join(root, "shows")}, f["dirs"])
        typed = os.path.join(root, "shows", "not yet made", "deeper")
        self.assertEqual(b.client.get("/folders", query_string={"path": typed}).get_json()["path"],
                         os.path.join(root, "shows"))
        self.assertEqual([d["name"] for d in b.client.get(
            "/folders", query_string={"path": os.path.join(root, "shows")}).get_json()["dirs"]],
            ["Show A", "Show B"])

    def test_a_file_ffprobe_fails_on_is_not_measured_again_and_again(self):
        s = Channel(CONFIG, FILES, {**DURATIONS, "b.s01e01.mp4": OSError("corrupt")})
        self.addCleanup(s.close)
        b = Browser(s)
        b.get()
        b.get()
        self.assertEqual(s.prober.calls.count(s.path("Show B/b.s01e01.mp4")), 1)
        self.assertNotIn("Measuring video lengths", b.html)

    def test_the_page_opens_while_new_files_are_still_measured(self):
        s = Channel(CONFIG, FILES, DURATIONS)
        self.addCleanup(s.close)
        release, measure = threading.Event(), s.prober.duration
        s.prober.duration = lambda path: release.wait(5) and measure(path)
        self.addCleanup(release.set)
        s.service.measurer.start()
        b = Browser(s)
        b.get()  # returns although nothing is measured yet
        self.assertTrue(wait_for(lambda: s.service.measurer.left == 4))
        self.assertIn("Measuring video lengths: 4 files left", b.get())
        self.assertNotIn("typical 0h21", b.html)
        release.set()
        self.assertTrue(wait_for(lambda: s.service.measurer.left == 0))
        self.assertTrue(wait_for(lambda: "typical 0h21, max 0h25" in b.get()))
        self.assertNotIn("Measuring video lengths", b.html)
        self.assertTrue(s.service.measurer.idle.wait(5))  # no write into the removed temp dir

    def test_save_writes_the_edited_schedule(self):
        b = self.open()
        r = b.submit(changes={"b0.length": "6h", "b1.length": "6h"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([blk["length"] for blk in b.yaml()["day_schedule"]], ["6h", "6h"])
        self.assertEqual(b.yaml()["day_start"], "06:00")
        self.assertIn("Airs 18:00, 00:00 UTC", b.html)

    def test_save_refuses_a_schedule_that_is_not_24_h(self):
        b = self.open()
        before = b.yaml()
        r = b.submit(changes={"b0.length": "7h"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Not saved", b.html)
        self.assertIn("22 h", b.html)
        self.assertIn("Still to assign: 2h00", b.html)
        self.assertEqual(b.yaml(), before)
        # the draft survives the refusal
        self.assertEqual(b.fields()["b0.length"], "7h")

    def test_time_still_to_assign(self):
        b = self.open()
        self.assertIn("Still to assign: 0h00", b.html)
        b.submit("add-block")
        self.assertIn("Still to assign: −1h00", b.html)

    def test_blocks_added_and_removed(self):
        b = self.open()
        b.submit("add-block")
        b.submit("del-block:0", {"b2.length": "16h"})
        b.submit(changes={"b1.s0.rule": "show:Show A"})
        blocks = b.yaml()["day_schedule"]
        self.assertEqual([(x["length"], x["repeat"]) for x in blocks], [("4h", 2), ("16h", 1)])

    def test_slots_added_reordered_and_removed(self):
        b = self.open()
        b.submit("add-slot:0")
        b.submit("up-slot:0:1", {"b0.s1.rule": "show:Show B"})
        b.submit("add-slot:0")
        b.submit("del-slot:0:1", {"b0.s2.rule": "show:Show B"})
        b.submit()
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"],
                         [{"rule": {"show": "Show B"}}, {"rule": {"show": "Show B"}}])

    def test_rule_choices_cover_shows_show_groups_and_random_movie(self):
        b = self.open({**CONFIG, "show_groups": {"Cartoons": ["Show A", "Show B"]}})
        for value in ('value="show:Show A"', 'value="show:Show B"',
                      'value="group:Cartoons"', 'value="movie:random"'):
            self.assertIn(value, b.html)
        b.submit("add-slot:0", {"b0.s0.rule": "movie:random"})
        self.assertEqual(b.fields()["b0.s0.rule"], "movie:random")

    def test_typical_and_maximum_content_length(self):
        html = self.open().html
        self.assertIn("typical 0h21, max 0h25", html)  # Show A: median 1300 s, max 1500 s
        self.assertNotIn("exceeds", html)

    def test_warns_when_maximum_exceeds_the_block(self):
        b = self.open()
        b.submit("add-slot:1", {"b1.length": "45m", "b1.repeat": "1"})
        b.submit(changes={"b1.s1.rule": "show:Show A"})
        self.assertIn("typical 0h51, max 0h55. The maximum exceeds the Block.", b.html)

    def test_libraries_added_tagged_and_removed(self):
        b = self.open()
        movies = os.path.join(b.channel.root, "movies")
        os.mkdir(movies)
        b.submit("add-lib")
        b.submit("add-lib", {"lib1.path": movies, "lib1.kind": "movies"})
        b.submit("del-lib:2")
        b.submit()
        self.assertEqual(b.yaml()["libraries"], [
            {"path": b.channel.library, "kind": "shows"},
            {"path": movies, "kind": "movies"}])
        with open(b.channel.config_path) as f:
            text = f.read()
        self.assertIn("kind: movies", text)  # block style, hand-editable
        self.assertIn("length: 8h", text)

    def test_a_big_schedule_still_posts_as_the_browser_sends_it(self):
        week = {"weekdays": {d: {"show": "Show A"} for d in
                             ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}
        b = self.open({"day_start": "06:00", "day_schedule": [
            {"length": "1h", "repeat": 1, "slots": [week] * 6} for _ in range(24)]})
        data = {**b.fields(), "action": "add-lib"}
        self.assertGreater(len(data), 1000)  # Werkzeug's default limit
        r = b.client.post("/", data=data, content_type="multipart/form-data")  # as fetch(FormData)
        self.assertEqual(r.status_code, 200)

    def test_problems_lists_generation_error_and_missing_library(self):
        b = self.open()
        self.assertIn("Problems", b.html)
        self.assertIn("None.", b.html)
        gone = os.path.join(b.channel.root, "gone")
        b.submit("add-lib", {})
        b.submit(changes={"lib1.path": gone})
        b.channel.tick()
        b.get()
        self.assertIn(f"Library missing: {gone}", b.html)
        self.assertIn("Generation error:", b.html)

    def test_problems_lists_what_the_latest_day_record_flags(self):
        b = self.open({**CONFIG, "day_schedule": [
            CONFIG["day_schedule"][0],
            {"length": "4h", "repeat": 2, "slots": [{"rule": {"show": "Show C"}}]}]})
        b.channel.tick()
        b.get()
        self.assertIn("2026-11-09: Block 2 Slot 1: show &#39;Show C&#39; not found", b.html)
        b.channel.tick(utc(2026, 11, 10, 5, 30))  # tomorrow generated, today still airing
        b.get()
        self.assertIn("2026-11-09: Block 2 Slot 1", b.html)
        self.assertIn("2026-11-10: Block 2 Slot 1", b.html)
        b.channel.tick(utc(2026, 11, 10, 12, 0))  # yesterday's record no longer counts
        b.get()
        self.assertNotIn("2026-11-09: Block 2 Slot 1", b.html)

    def test_problems_lists_unplayable_files_and_filler_that_never_fits(self):
        s = Channel(CONFIG, FILES + ["Show A/Show A - S01E04.mkv"],
                    {**DURATIONS, "Show A - S01E04.mkv": None, "long.mp4": 30000.0},
                    filler=["long.mp4"])
        self.addCleanup(s.close)
        s.tick()
        b = Browser(s)
        b.get()
        self.assertIn("Unplayable: " + s.path("Show A/Show A - S01E04.mkv"), b.html)
        self.assertIn("Filler never fits: " + os.path.join(s.filler, "long.mp4"), b.html)

    def test_hand_edit_error_shows_until_a_fixed_save_and_retry(self):
        b = self.open()
        good = b.fields()
        with open(b.channel.config_path, "w") as f:
            f.write("day_schedule: [{length: 7h, repeat: 1, slots: []}]\n")
        b.channel.tick()
        b.get()
        self.assertIn("Generation error: Day Schedule totals 7 h", b.html)
        self.assertIsNone(b.channel.playlist("2026-11-09"))  # no fallback schedule

        r = b.client.post("/", data={**good, "action": "save"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        b.channel.tick()  # the service's next retry
        b.get()
        self.assertNotIn("Generation error", b.html)
        self.assertIsNotNone(b.channel.playlist("2026-11-09"))

    def test_day_start_is_edited_on_the_page(self):
        b = self.open()
        b.submit(changes={"day_start": "07:30"})
        self.assertEqual(b.yaml()["day_start"], "07:30")

    def test_values_the_service_cannot_honour_are_config_errors(self):
        def zero_block(raw):
            raw["day_schedule"].append({"length": "0h", "repeat": 1, "slots": []})

        for name, change in (
                ("seconds", lambda raw: raw.update(day_start="06:00:30")),
                ("one-digit hour", lambda raw: raw.update(day_start="6:00")),
                ("movie rule", lambda raw: raw["day_schedule"][0]["slots"].append(
                    {"rule": {"movie": "latest"}})),
                ("zero length", zero_block)):
            with self.subTest(name):
                b = self.open()
                raw = b.yaml()
                change(raw)
                with open(b.channel.config_path, "w") as f:
                    yaml.safe_dump(raw, f)
                b.channel.tick()
                self.assertIsNotNone(b.channel.service.error)
                self.assertIsNone(b.channel.playlist("2026-11-09"))

    def test_a_fresh_install_gets_a_base_config_and_the_page_opens(self):
        s = Channel(None)
        self.addCleanup(s.close)
        self.assertEqual(Browser(s).client.get("/").status_code, 200)
        with open(s.config_path) as f:
            raw = yaml.safe_load(f)
        self.assertEqual(raw, {"day_start": "06:00", "libraries": [], "show_groups": {},
                               "show_list": [], "day_schedule": []})
        s.tick()  # an empty schedule is an error to fix, never a made-up one
        self.assertIn("totals 0 h", s.service.error)
        self.assertIsNone(s.playlist("2026-11-09"))

    def test_a_post_from_another_site_is_refused(self):
        b = self.open()
        before = b.yaml()
        r = b.client.post("/", data={**b.fields(), "action": "save", "b0.repeat": "9"},
                          headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(b.yaml(), before)

    def test_badly_shaped_yaml_is_a_config_error_and_still_renders(self):
        b = self.open()
        with open(b.channel.config_path, "w") as f:
            f.write("libraries: [/media/shows]\nday_schedule: [24h]\n")
        b.channel.tick()
        self.assertIn("bad Library", b.channel.service.error)
        r = b.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("bad Library", r.get_data(as_text=True))

    def test_a_hand_edited_rule_with_two_keys_still_renders(self):
        b = self.open()
        with open(b.channel.config_path, "w") as f:
            f.write("day_schedule: [{length: 24h, repeat: 1,"
                    " slots: [{rule: {show: Show A, movie: random}}]}]\n")
        self.assertEqual(b.client.get("/").status_code, 200)


WEEK = {"day_start": "06:00", "day_schedule": [
    {"length": "8h", "repeat": 3, "slots": [
        {"rule": {"show": "Show A"}},
        {"weekdays": {"mon": {"show": "Show B"}, "sun": {"show": "Show A"}}}]}]}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class WeekGridTest(unittest.TestCase):
    open = WebTest.open

    def cells(self, b, slot="b0.s1"):
        f = b.fields()
        return [f[f"{slot}.{d}"] for d in DAYS]

    def test_fixed_slot_is_one_cell_and_distributed_slot_seven(self):
        b = self.open(WEEK)
        f = b.fields()
        self.assertEqual(f["b0.s0.rule"], "show:Show A")
        self.assertTrue(all(f"b0.s0.{d}" not in f for d in DAYS))
        self.assertEqual(self.cells(b), ["show:Show B", "", "", "", "", "", "show:Show A"])
        self.assertIn('colspan="7"', b.html)
        for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            self.assertIn(f"<th>{day}</th>", b.html)

    def test_editing_cells_saves_only_the_non_empty_weekdays(self):
        b = self.open(WEEK)
        b.submit(changes={"b0.s1.wed": "show:Show B", "b0.s1.sun": ""})
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"], [
            {"rule": {"show": "Show A"}},
            {"weekdays": {"mon": {"show": "Show B"}, "wed": {"show": "Show B"}}}])

    def test_fixed_to_distributed_copies_the_rule_to_all_seven_days(self):
        b = self.open(WEEK)
        b.submit("mode-slot:0:0")
        self.assertEqual(self.cells(b, "b0.s0"), ["show:Show A"] * 7)
        b.submit()
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"][0],
                         {"weekdays": {d: {"show": "Show A"} for d in DAYS}})

    def test_distributed_to_fixed_keeps_monday_after_a_confirm(self):
        b = self.open(WEEK)
        self.assertIn('value="mode-slot:0:1"\n                data-confirm=', b.html)
        b.submit("mode-slot:0:1")
        self.assertEqual(b.fields()["b0.s1.rule"], "show:Show B")
        b.submit()
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"][1], {"rule": {"show": "Show B"}})

    def test_new_distributed_slot_starts_empty_with_hatched_cells(self):
        b = self.open(WEEK)
        self.assertEqual(b.html.count('class="cell empty"'), 5)
        b.submit("add-dslot:0")
        self.assertEqual(self.cells(b, "b0.s2"), [""] * 7)
        self.assertEqual(b.html.count('class="cell empty"'), 12)
        b.submit()
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"][2], {"weekdays": {}})

    def test_an_empty_fixed_slot_saves_hatched_and_flagged_and_is_skipped(self):
        b = self.open(WEEK)
        b.submit("add-slot:0")
        r = b.submit()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b.yaml()["day_schedule"][0]["slots"][2], {})
        self.assertEqual(b.html.count('class="cell empty"'), 6)
        self.assertIn("Block 1 Slot 3 is empty every day: skipped", b.html)
        b.channel.tick()
        self.assertIsNone(b.channel.service.error)

    def test_fill_row_shows_content_and_breaks_per_weekday(self):
        # Show A median 1300 s, Show B 1800 s; 8h Block
        b = self.open(WEEK)
        self.assertIn("0h51 / 8h<br>Breaks 7h08", b.html)  # Mon: A + B = 3100 s
        self.assertIn("0h21 / 8h<br>Breaks 7h38", b.html)  # Tue: A only

    def test_overrun_and_empty_cells_reach_the_problems_panel(self):
        b = self.open({"day_schedule": [
            {"length": "30m", "repeat": 48, "slots": [
                {"rule": {"show": "Show A"}},
                {"weekdays": {"mon": {"show": "Show B"}, "tue": {"show": "Show B"},
                              "wed": {"show": "Show B"}, "thu": {"show": "Show B"},
                              "fri": {"show": "Show B"}}}]}]})
        self.assertIn('<td class="bad">0h51 / 30m<br>Breaks —</td>', b.html)
        self.assertIn("Block 1 Slot 2 is empty on Sat, Sun: skipped those days", b.html)
        self.assertIn("Block 1 content runs past its length on Mon, Tue, Wed, Thu, Fri",
                      b.html)
