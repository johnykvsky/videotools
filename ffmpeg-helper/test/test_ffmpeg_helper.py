#!/usr/bin/env python3
"""Tests for ffmpeg-helper.py using test/sample_multitrack.mp4."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent
SCRIPT_PATH = ROOT_DIR / "ffmpeg-helper.py"
SAMPLE_MP4 = TEST_DIR / "sample_multitrack.mp4"


def probe_streams(file_path: Path) -> list[dict]:
    """Return all streams (video, audio, subtitle) from ffprobe as JSON dicts."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name:stream_disposition=default:stream_tags=language",
        "-of", "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)["streams"]


def run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


class TestFfmpegHelper(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SAMPLE_MP4.is_file(), f"Sample file missing: {SAMPLE_MP4}")
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_sample_file_structure(self) -> None:
        """Verify our sample MP4 has 1 video, 3 audio (pol, eng, jpn), and 2 subtitle (eng, pol) streams."""
        streams = probe_streams(SAMPLE_MP4)
        video = [s for s in streams if s["codec_type"] == "video"]
        audio = [s for s in streams if s["codec_type"] == "audio"]
        subs = [s for s in streams if s["codec_type"] == "subtitle"]

        self.assertEqual(len(video), 1)
        self.assertEqual([s["tags"]["language"] for s in audio], ["pol", "eng", "jpn"])
        self.assertEqual([s["disposition"]["default"] for s in audio], [1, 0, 0])
        self.assertEqual([s["tags"]["language"] for s in subs], ["eng", "pol"])

    def test_info_command(self) -> None:
        """--info should list all 3 audio tracks and their languages/default status."""
        res = run_helper("--info", str(SAMPLE_MP4))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Audio tracks found: 3", res.stdout)
        self.assertIn("Track #1 (ffmpeg a:0, stream #1): codec=aac, language=pol [DEFAULT]", res.stdout)
        self.assertIn("Track #2 (ffmpeg a:1, stream #2): codec=aac, language=eng", res.stdout)
        self.assertIn("Track #3 (ffmpeg a:2, stream #3): codec=aac, language=jpn", res.stdout)

    def test_set_default_track_2_and_3(self) -> None:
        """--set-default N should switch the default audio track while preserving all audio & subtitle tracks."""
        out_track2 = self.tmp_path / "out_track2.mp4"
        res2 = run_helper("--set-default", "2", str(SAMPLE_MP4), "-o", str(out_track2))
        self.assertEqual(res2.returncode, 0, res2.stderr)

        streams2 = probe_streams(out_track2)
        audio2 = [s for s in streams2 if s["codec_type"] == "audio"]
        subs2 = [s for s in streams2 if s["codec_type"] == "subtitle"]
        self.assertEqual([s["disposition"]["default"] for s in audio2], [0, 1, 0])
        self.assertEqual(len(subs2), 2, "Subtitles must be preserved")

        out_track3 = self.tmp_path / "out_track3.mp4"
        res3 = run_helper("--set-default", "3", str(SAMPLE_MP4), "-o", str(out_track3))
        self.assertEqual(res3.returncode, 0, res3.stderr)

        streams3 = probe_streams(out_track3)
        audio3 = [s for s in streams3 if s["codec_type"] == "audio"]
        self.assertEqual([s["disposition"]["default"] for s in audio3], [0, 0, 1])

    def test_default_eng(self) -> None:
        """--default-eng should find the 'eng' audio track and make it default while keeping all tracks."""
        out_file = self.tmp_path / "out_default_eng.mp4"
        res = run_helper("--default-eng", str(SAMPLE_MP4), "-o", str(out_file))
        self.assertEqual(res.returncode, 0, res.stderr)

        streams = probe_streams(out_file)
        audio = [s for s in streams if s["codec_type"] == "audio"]
        subs = [s for s in streams if s["codec_type"] == "subtitle"]

        self.assertEqual([s["tags"]["language"] for s in audio], ["pol", "eng", "jpn"])
        self.assertEqual([s["disposition"]["default"] for s in audio], [0, 1, 0])
        self.assertEqual([s["tags"]["language"] for s in subs], ["eng", "pol"])

    def test_keep_eng_preserves_subtitles_and_video(self) -> None:
        """--keep-eng should remove non-English audio tracks, set 'eng' as default, and keep all subtitles."""
        out_file = self.tmp_path / "out_keep_eng.mp4"
        res = run_helper("--keep-eng", str(SAMPLE_MP4), "-o", str(out_file))
        self.assertEqual(res.returncode, 0, res.stderr)

        streams = probe_streams(out_file)
        video = [s for s in streams if s["codec_type"] == "video"]
        audio = [s for s in streams if s["codec_type"] == "audio"]
        subs = [s for s in streams if s["codec_type"] == "subtitle"]

        self.assertEqual(len(video), 1)
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]["tags"]["language"], "eng")
        self.assertEqual(audio[0]["disposition"]["default"], 1)
        self.assertEqual([s["tags"]["language"] for s in subs], ["eng", "pol"])

    def test_errors_on_single_track_and_out_of_range(self) -> None:
        """--set-default should error if file has only 1 audio track or track number is out of range."""
        single_audio = self.tmp_path / "single_audio.mp4"
        run_helper("--keep-eng", str(SAMPLE_MP4), "-o", str(single_audio))

        res_single = run_helper("--set-default", "2", str(single_audio), "-o", str(self.tmp_path / "fail.mp4"))
        self.assertNotEqual(res_single.returncode, 0)
        self.assertIn("only has 1 audio track", res_single.stderr)

        res_oob = run_helper("--set-default", "5", str(SAMPLE_MP4), "-o", str(self.tmp_path / "fail2.mp4"))
        self.assertNotEqual(res_oob.returncode, 0)
        self.assertIn("Requested audio track #5, but file only has 3 audio tracks", res_oob.stderr)

    def test_errors_on_unlabeled_or_missing_eng_audio(self) -> None:
        """--keep-eng and --default-eng should error clearly when tracks are unlabeled or lack 'eng'."""
        # 1. File with unlabeled audio tracks
        unlabeled_mp4 = self.tmp_path / "unlabeled.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(SAMPLE_MP4),
                "-map", "0:v", "-map", "0:a:0", "-map", "0:a:1",
                "-metadata:s:a:0", "language=", "-metadata:s:a:1", "language=",
                "-c", "copy", str(unlabeled_mp4),
            ],
            check=True,
        )
        res_unlabeled = run_helper("--keep-eng", str(unlabeled_mp4), "-o", str(self.tmp_path / "fail.mp4"))
        self.assertNotEqual(res_unlabeled.returncode, 0)
        self.assertIn("have language labels", res_unlabeled.stderr)

        # 2. File with labeled non-English tracks (pol, jpn)
        no_eng_mp4 = self.tmp_path / "no_eng.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(SAMPLE_MP4),
                "-map", "0:v", "-map", "0:a:0", "-map", "0:a:2",
                "-c", "copy", str(no_eng_mp4),
            ],
            check=True,
        )
        res_no_eng = run_helper("--default-eng", str(no_eng_mp4), "-o", str(self.tmp_path / "fail2.mp4"))
        self.assertNotEqual(res_no_eng.returncode, 0)
        self.assertIn("No English ('eng') audio track found", res_no_eng.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
