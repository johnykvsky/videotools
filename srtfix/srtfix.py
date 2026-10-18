#!/usr/bin/env python3
"""
srtfix.py - Utility to inspect and fix .srt subtitles:
  - Shift timings by +/- seconds
  - Detect the likely FPS an .srt file was created for
  - Convert timings from a given source FPS to a target FPS
  - Detect character encoding and optionally convert to UTF-8 (without BOM)
"""

import math
import os
import re
import sys
from typing import List, Optional, Tuple

TIMESTAMP_LINE_RE = re.compile(
    r"^(\d{2,}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2}),(\d{3})(.*)$"
)
NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
FPS_FORMAT_RE = re.compile(r"^\d{1,2}(?:[.,]\d{1,3})?$")

UTF8_BOM = b"\xef\xbb\xbf"
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"

POLISH_CHARS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

MIN_FPS = 1.0
MAX_FPS = 99.999

CANDIDATE_FPS = [
    (24000 / 1001, "23.976"),
    (24.0, "24.0"),
    (25.0, "25.0"),
    (30000 / 1001, "29.97"),
    (30.0, "30.0"),
    (50.0, "50.0"),
    (60000 / 1001, "59.94"),
    (60.0, "60.0"),
]


def to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (
        int(hours) * 3600000
        + int(minutes) * 60000
        + int(seconds) * 1000
        + int(millis)
    )


def format_ms(total_ms: int) -> str:
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_number(val: float) -> str:
    if val.is_integer():
        return str(int(val))
    return f"{val:g}"


def parse_finite_float(raw_str: str) -> Optional[float]:
    if not NUMBER_RE.match(raw_str.strip()):
        return None
    try:
        val = float(raw_str.strip().replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(val):
        return None
    return val


def validate_fps_value(raw_str: str, param_name: str) -> float:
    stripped = raw_str.strip()
    val = parse_finite_float(stripped)
    if val is None:
        print(
            f"Error: Invalid {param_name} value '{raw_str}'. Must be a valid number (e.g., 24.0, 25.0, 23.976).",
            file=sys.stderr,
        )
        sys.exit(1)
    if val <= 0:
        print(
            f"Error: Invalid {param_name} value '{raw_str}'. FPS must be greater than 0.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not FPS_FORMAT_RE.match(stripped):
        print(
            f"Error: Invalid {param_name} format '{raw_str}'. Maximum allowed format is xx.xxx (up to 2 digits before and 3 digits after the decimal point, e.g., 25, 25.0, 23.976).",
            file=sys.stderr,
        )
        sys.exit(1)
    if val < MIN_FPS or val > MAX_FPS:
        print(
            f"Error: Invalid {param_name} value '{raw_str}'. FPS must be between {MIN_FPS:g} and {MAX_FPS:g}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return val


def build_default_output_path(
    input_path: str,
    offset_seconds: Optional[float] = None,
    fps_from: Optional[float] = None,
    fps_to: Optional[float] = None,
    convert_utf8: bool = False,
) -> str:
    base, ext = os.path.splitext(input_path)
    if not ext:
        ext = ".srt"

    parts = []
    if fps_from is not None and fps_to is not None:
        parts.append(f"fps{format_number(fps_from)}to{format_number(fps_to)}")
    if offset_seconds is not None:
        prefix = "min" if offset_seconds < 0 else "plus"
        parts.append(f"{prefix}{format_number(abs(offset_seconds))}s")
    if not parts and convert_utf8:
        parts.append("utf8")
    if not parts:
        parts.append("fixed")

    return f"{base}_{'_'.join(parts)}{ext}"


def detect_and_read_srt(path: str) -> Tuple[str, str, str, bool]:
    """
    Reads an .srt file and detects its encoding.
    Returns (text_without_bom, codec_name, display_name, is_utf8_no_bom).
    """
    with open(path, "rb") as f:
        raw = f.read()

    if b"\x00" in raw and not (
        raw.startswith(UTF16_LE_BOM) or raw.startswith(UTF16_BE_BOM)
    ):
        raise ValueError(f"File '{path}' appears to be a binary file, not a valid .srt text file.")

    if raw.startswith(UTF8_BOM):
        try:
            return (
                raw[len(UTF8_BOM) :].decode("utf-8"),
                "utf-8-sig",
                "UTF-8 with BOM",
                False,
            )
        except UnicodeDecodeError:
            pass

    if raw.startswith(UTF16_LE_BOM) or raw.startswith(UTF16_BE_BOM):
        try:
            return raw.decode("utf-16"), "utf-16", "UTF-16", False
        except UnicodeDecodeError:
            pass

    try:
        return raw.decode("utf-8"), "utf-8", "UTF-8", True
    except UnicodeDecodeError:
        pass

    candidates = [
        ("cp1250", "CP1250 (Windows-1250)"),
        ("iso-8859-2", "ISO-8859-2 (Latin-2)"),
        ("cp1252", "CP1252 (Windows-1252)"),
        ("latin-1", "ISO-8859-1 (Latin-1)"),
    ]

    best_result = None
    best_score = -1

    for codec, label in candidates:
        try:
            decoded = raw.decode(codec)
        except UnicodeDecodeError:
            continue

        score = sum(1 for ch in decoded if ch in POLISH_CHARS)
        if score > best_score:
            best_score = score
            best_result = (decoded, codec, label, False)

    if best_result is not None:
        return best_result

    raise ValueError(f"Could not decode '{path}' with supported encodings.")


def extract_timestamps_ms(content: str) -> List[int]:
    timestamps = []
    for line in content.splitlines():
        match = TIMESTAMP_LINE_RE.match(line.strip())
        if match:
            h1, m1, s1, ms1, h2, m2, s2, ms2, _ = match.groups()
            timestamps.append(to_ms(h1, m1, s1, ms1))
            timestamps.append(to_ms(h2, m2, s2, ms2))
    return timestamps


def detect_srt_fps(timestamps_ms: List[int]) -> Tuple[Optional[str], float, str]:
    """
    Analyzes timestamp millisecond alignments against standard frame rates
    (accounting for any constant millisecond offset).
    Returns (detected_fps_label_or_None, match_ratio_0_to_1, explanation_str).
    """
    if not timestamps_ms:
        return None, 0.0, "No timestamps found."

    t0 = timestamps_ms[0]
    deltas_sec = [(t - t0) / 1000.0 for t in timestamps_ms]

    best_label = None
    best_ratio = 0.0

    primary_candidates = CANDIDATE_FPS[:5]

    for fps_val, label in primary_candidates:
        matched = 0
        for d_sec in deltas_sec:
            nearest_frames = round(d_sec * fps_val)
            err_ms = abs(d_sec - (nearest_frames / fps_val)) * 1000.0
            if err_ms <= 1.5:
                matched += 1
        ratio = matched / len(deltas_sec)

        if ratio > best_ratio + 0.02:
            best_ratio = ratio
            best_label = label

    unique_ms_count = len({t % 1000 for t in timestamps_ms})

    if best_ratio >= 0.80 and best_label is not None:
        return (
            best_label,
            best_ratio,
            f"{best_ratio * 100:.1f}% of timestamps align with {best_label} FPS frame grid "
            f"({unique_ms_count} unique millisecond values per second).",
        )

    return (
        None,
        best_ratio,
        f"Timestamps do not strongly snap to a single standard frame grid "
        f"(best match: {best_label} FPS at {best_ratio * 100:.1f}%, "
        f"{unique_ms_count} unique millisecond values).",
    )


def parse_args(argv):
    input_file = None
    offset_str = None
    output_file = None
    convert_utf8 = False
    detect_fps_flag = False
    fps_from = None
    fps_to = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print_usage()
            sys.exit(0)
        elif arg in ("-u", "--utf8", "--to-utf8"):
            convert_utf8 = True
        elif arg in ("--detect-fps", "-d"):
            detect_fps_flag = True
        elif arg == "--fps":
            if i + 2 >= len(argv):
                print(
                    "Error: --fps requires two arguments: <from_fps> <to_fps> (e.g., --fps 24.0 25.0).",
                    file=sys.stderr,
                )
                sys.exit(1)
            fps_from = validate_fps_value(argv[i + 1], "source FPS (<from_fps>)")
            fps_to = validate_fps_value(argv[i + 2], "target FPS (<to_fps>)")
            if fps_from == fps_to:
                print(
                    f"Error: Source FPS and target FPS are identical ({format_number(fps_from)}). Please provide two different FPS values.",
                    file=sys.stderr,
                )
                sys.exit(1)
            i += 3
            continue
        elif arg in ("-o", "--output"):
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                print("Error: -o/--output requires a non-empty file path.", file=sys.stderr)
                sys.exit(1)
            output_file = argv[i + 1]
            i += 2
            continue
        elif arg.startswith("-") and not NUMBER_RE.match(arg):
            print(
                f"Error: Unknown option or invalid argument '{arg}'.",
                file=sys.stderr,
            )
            print_usage()
            sys.exit(1)
        elif input_file is None:
            if NUMBER_RE.match(arg) and not os.path.exists(arg):
                print(
                    f"Error: Expected an input .srt file path first, but got number '{arg}'.",
                    file=sys.stderr,
                )
                print_usage()
                sys.exit(1)
            input_file = arg
        elif offset_str is None:
            offset_str = arg
        else:
            print(f"Error: Unexpected extra argument '{arg}'.", file=sys.stderr)
            print_usage()
            sys.exit(1)
        i += 1

    if input_file is None or not input_file.strip():
        print("Error: Missing input .srt file path.", file=sys.stderr)
        print_usage()
        sys.exit(1)

    offset_seconds = None
    if offset_str is not None:
        offset_seconds = parse_finite_float(offset_str)
        if offset_seconds is None:
            print(
                f"Error: Invalid offset '{offset_str}'. Please provide a valid number of seconds (e.g., -32, +5, or -12.5).",
                file=sys.stderr,
            )
            sys.exit(1)

    has_modification = (
        offset_seconds is not None or fps_from is not None or convert_utf8
    )
    if not detect_fps_flag and not has_modification:
        print(
            "Error: No action specified. Provide a time offset (e.g., -32), --fps, --utf8, or --detect-fps.",
            file=sys.stderr,
        )
        print_usage()
        sys.exit(1)

    return (
        input_file,
        offset_seconds,
        output_file,
        convert_utf8,
        detect_fps_flag,
        fps_from,
        fps_to,
    )


def print_usage():
    print(
        "Usage:\n"
        "  ./srtfix.py <input.srt> [offset_seconds] [options]\n\n"
        "Options:\n"
        "  -d, --detect-fps              Detect and display the FPS the .srt file was created for\n"
        "  --fps <from_fps> <to_fps>     Convert timings from <from_fps> to <to_fps> (e.g. --fps 24.0 25.0)\n"
        "  -u, --utf8                    Convert output file encoding to UTF-8 (without BOM)\n"
        "  -o, --output <file>           Custom output file path\n"
        "  -h, --help                    Show this help message\n\n"
        "Examples:\n"
        "  ./srtfix.py test.srt --detect-fps\n"
        "  ./srtfix.py test.srt -32\n"
        "  ./srtfix.py test.srt --fps 24.0 25.0\n"
        "  ./srtfix.py test.srt -32 --fps 24.0 23.976 --utf8"
    )


def main():
    (
        input_file,
        offset_seconds,
        output_file,
        convert_utf8,
        detect_fps_flag,
        fps_from,
        fps_to,
    ) = parse_args(sys.argv[1:])

    if os.path.isdir(input_file):
        print(f"Error: '{input_file}' is a directory, not a file.", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(input_file):
        print(f"Error: Input file '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)

    if os.path.getsize(input_file) == 0:
        print(f"Error: Input file '{input_file}' is empty.", file=sys.stderr)
        sys.exit(1)

    try:
        content, codec, encoding_label, is_utf8_no_bom = detect_and_read_srt(input_file)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not is_utf8_no_bom:
        print(f"Detected encoding: {encoding_label}")
        if not convert_utf8:
            print(
                "      (Tip: pass -u / --utf8 to convert the output file to UTF-8 without BOM)"
            )

    timestamps_ms = extract_timestamps_ms(content)
    if not timestamps_ms:
        print(
            f"Error: No valid .srt timestamps found in '{input_file}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if detect_fps_flag:
        detected_label, confidence, details = detect_srt_fps(timestamps_ms)
        if detected_label:
            print(f"Detected FPS: {detected_label} FPS ({details})")
        else:
            print(f"Detected FPS: Unknown / Unsnapped ({details})")

    has_modification = (
        offset_seconds is not None or fps_from is not None or convert_utf8
    )
    if not has_modification:
        return

    if output_file is None:
        output_file = build_default_output_path(
            input_file,
            offset_seconds=offset_seconds,
            fps_from=fps_from,
            fps_to=fps_to,
            convert_utf8=convert_utf8,
        )

    if os.path.isdir(output_file):
        print(
            f"Error: Output path '{output_file}' is a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    if os.path.abspath(input_file) == os.path.abspath(output_file):
        print(
            "Error: Output file cannot be the same as the original input file.",
            file=sys.stderr,
        )
        sys.exit(1)

    lines = content.splitlines(keepends=True)

    offset_ms = int(round((offset_seconds or 0.0) * 1000))
    fps_ratio = 1.0
    if fps_from is not None and fps_to is not None:
        fps_ratio = fps_from / fps_to

    negative_entries = []
    first_scaled_ms = None
    total_timestamps = 0
    new_lines = []

    current_sub_id = None
    for line_num, line in enumerate(lines, start=1):
        stripped = line.rstrip("\r\n")
        line_ending = line[len(stripped) :]

        if stripped.isdigit():
            current_sub_id = stripped

        match = TIMESTAMP_LINE_RE.match(stripped)
        if match:
            total_timestamps += 1
            h1, m1, s1, ms1, h2, m2, s2, ms2, trailing = match.groups()

            if int(m1) > 59 or int(s1) > 59 or int(m2) > 59 or int(s2) > 59:
                print(
                    f"Error: Malformed timestamp on line {line_num} ('{stripped}'): minutes and seconds must be 00-59.",
                    file=sys.stderr,
                )
                sys.exit(1)

            start_ms = to_ms(h1, m1, s1, ms1)
            end_ms = to_ms(h2, m2, s2, ms2)

            if end_ms < start_ms:
                print(
                    f"Error: Invalid timestamp range on line {line_num} ('{stripped}'): end time is earlier than start time.",
                    file=sys.stderr,
                )
                sys.exit(1)

            scaled_start_ms = int(round(start_ms * fps_ratio))
            scaled_end_ms = int(round(end_ms * fps_ratio))

            if first_scaled_ms is None or scaled_start_ms < first_scaled_ms:
                first_scaled_ms = scaled_start_ms

            new_start_ms = scaled_start_ms + offset_ms
            new_end_ms = scaled_end_ms + offset_ms

            if new_start_ms < 0 or new_end_ms < 0:
                negative_entries.append(
                    (current_sub_id or "?", format_ms(start_ms), format_ms(end_ms))
                )
            else:
                new_line = (
                    f"{format_ms(new_start_ms)} --> {format_ms(new_end_ms)}"
                    f"{trailing}{line_ending}"
                )
                new_lines.append(new_line)
        else:
            new_lines.append(line)

    if negative_entries:
        count = len(negative_entries)
        plural = "subtitle" if count == 1 else "subtitles"
        shift_desc = f"{offset_seconds:g}s" if offset_seconds is not None else "0s"
        print(
            f"Operation aborted: {count} {plural} would fall before 00:00:00,000 "
            f"with a {shift_desc} shift."
        )
        for sub_id, orig_start, orig_end in negative_entries[:5]:
            print(f"  - Subtitle #{sub_id}: {orig_start} --> {orig_end}")
        if count > 5:
            print(f"  ... and {count - 5} more.")
        if first_scaled_ms is not None:
            max_shift = first_scaled_ms / 1000.0
            print(
                f"\nThe earliest subtitle starts at {format_ms(first_scaled_ms)} "
                f"(maximum safe backward shift is -{max_shift:.3f}s)."
            )
        print("Please kindly review your initial timing correction and try again.")
        sys.exit(1)

    target_codec = "utf-8" if convert_utf8 else codec
    try:
        with open(output_file, "w", encoding=target_codec, newline="") as f:
            f.writelines(new_lines)
    except OSError as exc:
        print(
            f"Error: Could not write to output file '{output_file}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    actions = []
    if fps_from is not None and fps_to is not None:
        actions.append(
            f"converted FPS from {format_number(fps_from)} to {format_number(fps_to)}"
        )
    if offset_seconds is not None:
        sign = "+" if offset_seconds > 0 else ""
        actions.append(f"shifted by {sign}{offset_seconds:g}s")
    if not actions and convert_utf8:
        actions.append("processed")

    print(f"Success! {total_timestamps} subtitles {', and '.join(actions)}.")
    if convert_utf8 and not is_utf8_no_bom:
        print(f"Converted encoding from {encoding_label} to UTF-8 (without BOM).")
    print(f"Saved new file to: {output_file}")


if __name__ == "__main__":
    main()
