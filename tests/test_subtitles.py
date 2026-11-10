"""Subtitle extraction, with ffprobe and ffmpeg faked."""
import json
import os
import subprocess
import tempfile
import unittest

from portlandtv import subtitles


def stream(index, codec="subrip", language=None, forced=0):
    s = {"index": index, "codec_name": codec, "disposition": {"forced": forced}}
    if language:
        s["tags"] = {"language": language}
    return s


class FakeTools:
    """ffprobe answers `streams`; ffmpeg writes its output file, or fails with `error`.
    Every command is recorded in `.calls`."""

    def __init__(self, streams, error=None):
        self.streams, self.error, self.calls = streams, error, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": self.streams}), "")
        with open(cmd[-1], "w") as f:
            f.write("WEBVTT\n")
        if self.error:
            raise subprocess.CalledProcessError(1, cmd, "", f"partial output\n{self.error}\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")


class SubtitlesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.video = os.path.join(self.root, "Show - S01E01.mkv")
        open(self.video, "w").close()
        self.vtt = os.path.join(self.root, "Show - S01E01.vtt")

    def test_extracts_the_preferred_language_skipping_forced_and_picture_tracks(self):
        tools = FakeTools([stream(2, "hdmv_pgs_subtitle", "eng"), stream(3, language="eng", forced=1),
                           stream(4, language="fre"), stream(5, "ass", "eng")])
        self.assertEqual(subtitles.extract(self.video, "eng", tools), "extracted")
        self.assertIn("0:5", tools.calls[-1])
        self.assertTrue(os.path.exists(self.vtt))
        self.assertFalse(os.path.exists(self.vtt + ".part"))

    def test_falls_back_to_the_first_text_track(self):
        tools = FakeTools([stream(3, language="fre"), stream(4, language="ger")])
        subtitles.extract(self.video, "eng", tools)
        self.assertIn("0:3", tools.calls[-1])

    def test_videos_with_a_vtt_or_without_usable_subtitles_are_left_alone(self):
        tools = FakeTools([stream(2, "dvd_subtitle", "eng")])
        self.assertEqual(subtitles.extract(self.video, "eng", tools),
                         "no text subtitles (picture or forced only)")
        self.assertEqual(subtitles.extract(self.video, "eng", FakeTools([])), "no subtitles")
        self.assertFalse(os.path.exists(self.vtt))
        open(self.vtt, "w").close()
        tools = FakeTools([stream(3)])
        self.assertEqual(subtitles.extract(self.video, "eng", tools), "has .vtt")
        self.assertEqual(tools.calls, [])

    def test_a_failed_extraction_leaves_no_partial_file(self):
        tools = FakeTools([stream(3)], error="Invalid data found")
        self.assertEqual(subtitles.extract(self.video, "eng", tools), "failed: Invalid data found")
        self.assertEqual(os.listdir(self.root), ["Show - S01E01.mkv"])

    def test_command_reports_every_video_and_fails_if_any_did(self):
        os.makedirs(os.path.join(self.root, ".hidden"))
        open(os.path.join(self.root, ".hidden", "x.mkv"), "w").close()
        open(os.path.join(self.root, "notes.txt"), "w").close()
        self.assertEqual(subtitles.main([self.root], FakeTools([stream(3)])), 0)
        self.assertTrue(os.path.exists(self.vtt))
        self.assertEqual(subtitles.main([self.root, os.path.join(self.root, "nope")],
                                        FakeTools([stream(3)])), 1)


if __name__ == "__main__":
    unittest.main()
