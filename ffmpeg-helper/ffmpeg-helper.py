#!/usr/bin/env python3
"""FFmpeg Helper for inspecting, selecting default, and filtering audio tracks."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_dependencies() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            error(f"'{tool}' is not installed or not in PATH.")


def get_audio_tracks(input_path: Path) -> list[dict[str, Any]]:
    """Run a single ffprobe command and return parsed audio track metadata."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index,codec_name:stream_disposition=default:stream_tags=language,title",
        "-of", "json",
        str(input_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        error(f"ffprobe failed on '{input_path}':\n{res.stderr.strip()}")

    data = json.loads(res.stdout or "{}")
    tracks = []
    for idx, stream in enumerate(data.get("streams", [])):
        tags = stream.get("tags") or {}
        disp = stream.get("disposition") or {}
        raw_lang = tags.get("language", "").strip()
        lang = None if (not raw_lang or raw_lang == "und") else raw_lang
        tracks.append({
            "track_num": idx + 1,          # 1-based audio track number
            "audio_idx": idx,              # 0-based ffmpeg a:<idx>
            "stream_idx": stream.get("index", idx),
            "codec": stream.get("codec_name", "unknown"),
            "language": lang,
            "title": tags.get("title"),
            "is_default": disp.get("default", 0) == 1,
        })
    return tracks


def print_audio_tracks(input_path: Path, tracks: list[dict[str, Any]], file=sys.stdout) -> None:
    print(f"Audio tracks in '{input_path}':", file=file)
    for t in tracks:
        lang_str = t["language"] or "(unlabeled)"
        def_str = " [DEFAULT]" if t["is_default"] else ""
        title_str = f' - "{t["title"]}"' if t["title"] else ""
        print(
            f"  Track #{t['track_num']} (ffmpeg a:{t['audio_idx']}, stream #{t['stream_idx']}): "
            f"codec={t['codec']}, language={lang_str}{def_str}{title_str}",
            file=file,
        )


def apply_default_disposition(
    input_path: Path, output_path: Path, tracks: list[dict[str, Any]], target_zero_idx: int
) -> None:
    disp_args: list[str] = []
    for i in range(len(tracks)):
        disp_args.extend([f"-disposition:a:{i}", "default" if i == target_zero_idx else "0"])

    print(f"\nSetting audio track #{target_zero_idx + 1} (a:{target_zero_idx}) as default -> '{output_path}'...")
    cmd = ["ffmpeg", "-i", str(input_path), "-map", "0", "-c", "copy", *disp_args, str(output_path)]
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        sys.exit(res.returncode)
    print(f"Done! Saved to '{output_path}'.")


def ensure_eng_tracks(input_path: Path, tracks: list[dict[str, Any]], action_desc: str) -> list[dict[str, Any]]:
    eng_tracks = [t for t in tracks if t["language"] == "eng"]
    if not eng_tracks:
        print_audio_tracks(input_path, tracks, file=sys.stderr)
        labeled = [t for t in tracks if t["language"] is not None]
        if not labeled:
            error(f"None of the {len(tracks)} audio track(s) in '{input_path}' have language labels. Cannot {action_desc}.")
        else:
            error(
                f"No English ('eng') audio track found in '{input_path}' "
                f"(found {len(labeled)}/{len(tracks)} labeled track(s), none with language='eng')."
            )
    return eng_tracks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FFmpeg helper to inspect audio tracks, change default audio track, or keep only English audio."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--set-default", "-d",
        type=int,
        metavar="TRACK_NUM",
        help="Set 1-based audio track TRACK_NUM as default and clear default on other audio tracks",
    )
    group.add_argument(
        "--default-eng", "-e",
        action="store_true",
        help="Find the English ('eng') audio track and make it default (keeping all tracks)",
    )
    group.add_argument(
        "--keep-eng", "-k",
        action="store_true",
        help="Remove all audio tracks except English ('eng') and make it default",
    )
    group.add_argument(
        "--info", "-i",
        action="store_true",
        help="Display all audio tracks and their language/default status",
    )

    parser.add_argument("input", type=Path, help="Input media file")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Custom output file path (default: <input_stem>_modified.<ext>)",
    )

    args = parser.parse_args()
    check_dependencies()

    input_path: Path = args.input
    if not input_path.is_file():
        error(f"Input file not found: '{input_path}'")

    output_path: Path = args.output or input_path.with_stem(f"{input_path.stem}_modified")
    tracks = get_audio_tracks(input_path)

    if args.info:
        print(f"File: {input_path}")
        print(f"Audio tracks found: {len(tracks)}")
        if tracks:
            print_audio_tracks(input_path, tracks)
        return

    if not tracks:
        error(f"No audio tracks found in '{input_path}'.")

    if args.set_default is not None:
        track_num = args.set_default
        if track_num < 1:
            error(f"Invalid track number '{track_num}'. Must be a positive integer (1, 2, 3, ...).")
        if len(tracks) < 2:
            print_audio_tracks(input_path, tracks, file=sys.stderr)
            error(f"File '{input_path}' only has 1 audio track. At least 2 audio tracks are required to change the default audio track.")
        if track_num > len(tracks):
            print_audio_tracks(input_path, tracks, file=sys.stderr)
            error(f"Requested audio track #{track_num}, but file only has {len(tracks)} audio tracks.")

        print_audio_tracks(input_path, tracks)
        apply_default_disposition(input_path, output_path, tracks, track_num - 1)

    elif args.default_eng:
        if len(tracks) < 2:
            print_audio_tracks(input_path, tracks, file=sys.stderr)
            error(f"File '{input_path}' only has 1 audio track. At least 2 audio tracks are required to change the default audio track.")

        eng_tracks = ensure_eng_tracks(input_path, tracks, "set English ('eng') as default")
        print_audio_tracks(input_path, tracks)
        apply_default_disposition(input_path, output_path, tracks, eng_tracks[0]["audio_idx"])

    elif args.keep_eng:
        eng_tracks = ensure_eng_tracks(input_path, tracks, "filter for English ('eng') audio")
        print_audio_tracks(input_path, tracks)
        print(f"\nKeeping only English ('eng') audio track(s) ({len(eng_tracks)} found) and setting as default -> '{output_path}'...")
        cmd = [
            "ffmpeg", "-i", str(input_path),
            "-map", "0", "-map", "-0:a", "-map", "0:a:m:language:eng",
            "-c", "copy", "-disposition:a:0", "default",
            str(output_path),
        ]
        res = subprocess.run(cmd, check=False)
        if res.returncode != 0:
            sys.exit(res.returncode)
        print(f"Done! Saved to '{output_path}'.")


if __name__ == "__main__":
    main()
