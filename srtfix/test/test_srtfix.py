#!/usr/bin/env python3
"""
Unit and integration tests for srtfix.py using sample.srt and temporary files.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TEST_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import srtfix

SCRIPT_PATH = os.path.join(PROJECT_DIR, "srtfix.py")
SAMPLE_SRT = os.path.join(TEST_DIR, "sample.srt")
TEST_SRT = os.path.join(TEST_DIR, "test.srt")


class TestSrtfixUnit(unittest.TestCase):
    def test_to_ms_and_format_ms(self):
        ms = srtfix.to_ms("01", "02", "03", "456")
        self.assertEqual(ms, 3723456)
        self.assertEqual(srtfix.format_ms(ms), "01:02:03,456")
        self.assertEqual(srtfix.format_ms(0), "00:00:00,000")

    def test_build_default_output_path(self):
        self.assertEqual(
            srtfix.build_default_output_path("test.srt", -32),
            "test_min32s.srt",
        )
        self.assertEqual(
            srtfix.build_default_output_path("test.srt", 5),
            "test_plus5s.srt",
        )
        self.assertEqual(
            srtfix.build_default_output_path("/path/to/movie.srt", -12.5),
            "/path/to/movie_min12.5s.srt",
        )
        self.assertEqual(
            srtfix.build_default_output_path("test.srt", fps_from=24.0, fps_to=25.0),
            "test_fps24to25.srt",
        )
        self.assertEqual(
            srtfix.build_default_output_path(
                "test.srt", offset_seconds=-10, fps_from=24.0, fps_to=23.946
            ),
            "test_fps24to23.946_min10s.srt",
        )


class TestSrtfixCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="srtfix_test_")
        self.sample_copy = os.path.join(self.temp_dir, "sample.srt")
        shutil.copyfile(SAMPLE_SRT, self.sample_copy)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, SCRIPT_PATH, *args],
            capture_output=True,
            text=True,
        )

    def test_negative_shift_creates_min_file_and_keeps_original(self):
        with open(self.sample_copy, "rb") as f:
            original_bytes = f.read()

        res = self.run_cli(self.sample_copy, "-32")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("Success! 3 subtitles shifted by -32s.", res.stdout)
        self.assertNotIn("Detected encoding:", res.stdout)

        expected_out = os.path.join(self.temp_dir, "sample_min32s.srt")
        self.assertTrue(os.path.isfile(expected_out))

        with open(self.sample_copy, "rb") as f:
            self.assertEqual(f.read(), original_bytes)

        with open(expected_out, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("00:00:03,500 --> 00:00:06,250", content)
        self.assertIn("00:00:30,100 --> 00:00:33,900", content)
        self.assertIn("01:59:26,000 --> 01:59:29,500", content)
        self.assertIn("ąęćłńóśźż", content)

    def test_positive_shift_creates_plus_file(self):
        res = self.run_cli(self.sample_copy, "+5")
        self.assertEqual(res.returncode, 0, msg=res.stderr)

        expected_out = os.path.join(self.temp_dir, "sample_plus5s.srt")
        self.assertTrue(os.path.isfile(expected_out))

        with open(expected_out, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("00:00:40,500 --> 00:00:43,250", content)
        self.assertIn("02:00:03,000 --> 02:00:06,500", content)

    def test_decimal_shift_with_comma_or_dot(self):
        res = self.run_cli(self.sample_copy, "-0,5")
        self.assertEqual(res.returncode, 0, msg=res.stderr)

        expected_out = os.path.join(self.temp_dir, "sample_min0.5s.srt")
        self.assertTrue(os.path.isfile(expected_out))

        with open(expected_out, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("00:00:35,000 --> 00:00:37,750", content)

    def test_abort_when_subtitles_fall_before_zero(self):
        res = self.run_cli(self.sample_copy, "-40")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(
            "Operation aborted: 1 subtitle would fall before 00:00:00,000", res.stdout
        )
        self.assertIn("Subtitle #1: 00:00:35,500 --> 00:00:38,250", res.stdout)
        self.assertIn("Please kindly review your initial timing correction", res.stdout)

        expected_out = os.path.join(self.temp_dir, "sample_min40s.srt")
        self.assertFalse(os.path.exists(expected_out))

    def test_abort_counts_multiple_negative_subtitles(self):
        res = self.run_cli(self.sample_copy, "-70")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(
            "Operation aborted: 2 subtitles would fall before 00:00:00,000", res.stdout
        )

    def test_custom_output_flag_and_crlf_preservation(self):
        crlf_file = os.path.join(self.temp_dir, "crlf_sample.srt")
        with open(self.sample_copy, "r", encoding="utf-8") as f:
            text = f.read().replace("\n", "\r\n")
        with open(crlf_file, "w", encoding="utf-8", newline="") as f:
            f.write(text)

        custom_out = os.path.join(self.temp_dir, "custom_output.srt")
        res = self.run_cli(crlf_file, "+10", "-o", custom_out)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertTrue(os.path.isfile(custom_out))

        with open(custom_out, "rb") as f:
            raw = f.read()
        self.assertIn(b"\r\n", raw)

    def test_cp1250_detection_and_conversion_to_utf8_without_bom(self):
        cp1250_file = os.path.join(self.temp_dir, "polish_cp1250.srt")
        polish_text = (
            "1\n"
            "00:00:15,000 --> 00:00:18,000\n"
            "Zażółć gęślą jaźń — ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż.\n\n"
            "2\n"
            "00:00:25,500 --> 00:00:28,000\n"
            "Druga linia napisów w kodowaniu CP1250.\n"
        )
        with open(cp1250_file, "wb") as f:
            f.write(polish_text.encode("cp1250"))

        res_keep = self.run_cli(cp1250_file, "-5")
        self.assertEqual(res_keep.returncode, 0, msg=res_keep.stderr)
        self.assertIn("Detected encoding: CP1250 (Windows-1250)", res_keep.stdout)
        self.assertNotIn("Info: Input file", res_keep.stdout)

        out_keep = os.path.join(self.temp_dir, "polish_cp1250_min5s.srt")
        self.assertTrue(os.path.isfile(out_keep))
        with open(out_keep, "rb") as f:
            raw_keep = f.read()
        with self.assertRaises(UnicodeDecodeError):
            raw_keep.decode("utf-8")
        self.assertIn("Zażółć gęślą jaźń", raw_keep.decode("cp1250"))

        res_utf8 = self.run_cli(cp1250_file, "+10", "--utf8")
        self.assertEqual(res_utf8.returncode, 0, msg=res_utf8.stderr)
        self.assertIn("Detected encoding: CP1250 (Windows-1250)", res_utf8.stdout)
        self.assertIn(
            "Converted encoding from CP1250 (Windows-1250) to UTF-8 (without BOM).",
            res_utf8.stdout,
        )

        out_utf8 = os.path.join(self.temp_dir, "polish_cp1250_plus10s.srt")
        self.assertTrue(os.path.isfile(out_utf8))
        with open(out_utf8, "rb") as f:
            raw_utf8 = f.read()

        self.assertFalse(raw_utf8.startswith(b"\xef\xbb\xbf"))
        decoded_utf8 = raw_utf8.decode("utf-8")
        self.assertIn("00:00:25,000 --> 00:00:28,000", decoded_utf8)
        self.assertIn("Zażółć gęślą jaźń — ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż.", decoded_utf8)

    def test_utf8_bom_detection_and_conversion_to_utf8_without_bom(self):
        bom_file = os.path.join(self.temp_dir, "bom_sample.srt")
        with open(self.sample_copy, "rb") as f:
            raw_sample = f.read()
        with open(bom_file, "wb") as f:
            f.write(b"\xef\xbb\xbf" + raw_sample)

        res = self.run_cli(bom_file, "+2", "-u")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("Detected encoding: UTF-8 with BOM", res.stdout)
        self.assertIn(
            "Converted encoding from UTF-8 with BOM to UTF-8 (without BOM).",
            res.stdout,
        )

        out_bom = os.path.join(self.temp_dir, "bom_sample_plus2s.srt")
        with open(out_bom, "rb") as f:
            out_bytes = f.read()
        self.assertFalse(out_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertIn("ąęćłńóśźż", out_bytes.decode("utf-8"))

    def test_detect_fps_option(self):
        if os.path.isfile(TEST_SRT):
            res_test = self.run_cli(TEST_SRT, "--detect-fps")
            self.assertEqual(res_test.returncode, 0, msg=res_test.stderr)
            self.assertIn("Detected FPS: 24.0 FPS", res_test.stdout)

        fps25_file = os.path.join(self.temp_dir, "fps25.srt")
        lines = []
        for idx in range(1, 30):
            start_ms = idx * 40 * 13
            end_ms = start_ms + 40 * 28
            lines.append(
                f"{idx}\n{srtfix.format_ms(start_ms)} --> {srtfix.format_ms(end_ms)}\nLine {idx}\n\n"
            )
        with open(fps25_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

        res_25 = self.run_cli(fps25_file, "--detect-fps")
        self.assertEqual(res_25.returncode, 0, msg=res_25.stderr)
        self.assertIn("Detected FPS: 25.0 FPS", res_25.stdout)

    def test_fps_conversion_with_dots_and_combined_with_shift_and_utf8(self):
        cp1250_fps_file = os.path.join(self.temp_dir, "movie.srt")
        srt_text = (
            "1\n"
            "00:01:40,000 --> 00:02:05,000\n"
            "Zażółć gęślą jaźń.\n"
        )
        with open(cp1250_fps_file, "wb") as f:
            f.write(srt_text.encode("cp1250"))

        res_fps = self.run_cli(cp1250_fps_file, "--fps", "25.0", "23.946")
        self.assertEqual(res_fps.returncode, 0, msg=res_fps.stderr)
        out_fps = os.path.join(self.temp_dir, "movie_fps25to23.946.srt")
        self.assertTrue(os.path.isfile(out_fps))
        with open(out_fps, "r", encoding="cp1250") as f:
            self.assertIn("00:01:44,402 --> 00:02:10,502", f.read())

        res_all = self.run_cli(
            cp1250_fps_file, "-16", "--fps", "24.0", "25.0", "--utf8"
        )
        self.assertEqual(res_all.returncode, 0, msg=res_all.stderr)
        self.assertIn(
            "Success! 1 subtitles converted FPS from 24 to 25, and shifted by -16s.",
            res_all.stdout,
        )
        self.assertIn(
            "Converted encoding from CP1250 (Windows-1250) to UTF-8 (without BOM).",
            res_all.stdout,
        )

        out_all = os.path.join(self.temp_dir, "movie_fps24to25_min16s.srt")
        self.assertTrue(os.path.isfile(out_all))
        with open(out_all, "rb") as f:
            raw_all = f.read()
        self.assertFalse(raw_all.startswith(b"\xef\xbb\xbf"))
        decoded = raw_all.decode("utf-8")
        self.assertIn("00:01:20,000 --> 00:01:44,000", decoded)
        self.assertIn("Zażółć gęślą jaźń.", decoded)

    def test_input_validation_errors(self):
        # 1) Unknown option flag
        res_unknown = self.run_cli(self.sample_copy, "--unknown-flag")
        self.assertNotEqual(res_unknown.returncode, 0)
        self.assertIn("Error: Unknown option or invalid argument '--unknown-flag'", res_unknown.stderr)

        # 2) Invalid offset string (non-numeric or NaN/inf)
        res_bad_offset = self.run_cli(self.sample_copy, "abc")
        self.assertNotEqual(res_bad_offset.returncode, 0)
        self.assertIn("Error: Invalid offset 'abc'", res_bad_offset.stderr)

        res_nan = self.run_cli(self.sample_copy, "nan")
        self.assertNotEqual(res_nan.returncode, 0)
        self.assertIn("Error: Invalid offset 'nan'", res_nan.stderr)

        # 3) Invalid FPS values (non-numeric, <= 0, out of range, or identical)
        res_fps_text = self.run_cli(self.sample_copy, "--fps", "24.0", "fast")
        self.assertNotEqual(res_fps_text.returncode, 0)
        self.assertIn("Error: Invalid target FPS (<to_fps>) value 'fast'", res_fps_text.stderr)

        res_fps_neg = self.run_cli(self.sample_copy, "--fps", "-24", "25")
        self.assertNotEqual(res_fps_neg.returncode, 0)
        self.assertIn("FPS must be greater than 0", res_fps_neg.stderr)

        res_fps_too_many_decimals = self.run_cli(
            self.sample_copy, "--fps", "25.123123123", "24.0"
        )
        self.assertNotEqual(res_fps_too_many_decimals.returncode, 0)
        self.assertIn("Maximum allowed format is xx.xxx", res_fps_too_many_decimals.stderr)

        res_fps_too_many_digits = self.run_cli(self.sample_copy, "--fps", "24", "120.5")
        self.assertNotEqual(res_fps_too_many_digits.returncode, 0)
        self.assertIn("Maximum allowed format is xx.xxx", res_fps_too_many_digits.stderr)

        res_fps_same = self.run_cli(self.sample_copy, "--fps", "25.0", "25")
        self.assertNotEqual(res_fps_same.returncode, 0)
        self.assertIn("Error: Source FPS and target FPS are identical", res_fps_same.stderr)

        # 4) Missing action when only file is passed
        res_no_action = self.run_cli(self.sample_copy)
        self.assertNotEqual(res_no_action.returncode, 0)
        self.assertIn("Error: No action specified", res_no_action.stderr)

        # 5) Passing a directory or non-existent file
        res_dir = self.run_cli(self.temp_dir, "+5")
        self.assertNotEqual(res_dir.returncode, 0)
        self.assertIn("is a directory, not a file", res_dir.stderr)

        # 6) Empty file or file without timestamps
        empty_file = os.path.join(self.temp_dir, "empty.srt")
        open(empty_file, "w").close()
        res_empty = self.run_cli(empty_file, "+5")
        self.assertNotEqual(res_empty.returncode, 0)
        self.assertIn("is empty", res_empty.stderr)

        # 7) Malformed timestamp in .srt (end time earlier than start time)
        bad_srt = os.path.join(self.temp_dir, "bad.srt")
        with open(bad_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:20,000 --> 00:00:10,000\nReversed timing\n")
        res_bad_srt = self.run_cli(bad_srt, "+5")
        self.assertNotEqual(res_bad_srt.returncode, 0)
        self.assertIn("end time is earlier than start time", res_bad_srt.stderr)


if __name__ == "__main__":
    unittest.main()
