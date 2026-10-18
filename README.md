# videotools

A collection of command-line utilities for inspecting and manipulating `.srt` subtitle files and audio tracks in video containers without re-encoding.

---

## Tools Overview

| Directory | Script(s) | Purpose |
| :--- | :--- | :--- |
| [`ffmpeg-helper/`](ffmpeg-helper/) | `ffmpeg-helper.py`, `ffmpeg-helper.sh` | Inspect audio tracks, switch the default audio stream, or strip non-English audio tracks using `ffmpeg` / `ffprobe` stream copy. |
| [`srtfix/`](srtfix/) | `srtfix.py` | Shift `.srt` subtitle timings, detect or convert subtitle frame rates (FPS), and detect/convert character encodings to UTF-8. |

---

## 1. ffmpeg-helper (`ffmpeg-helper.py` / `ffmpeg-helper.sh`)

`ffmpeg-helper` provides both a Python implementation (`ffmpeg-helper.py`) and an equivalent Bash implementation (`ffmpeg-helper.sh`) to inspect and manage audio tracks in multi-track media files (`.mp4`, `.mkv`, etc.). All modifications use `-c copy` so video, audio, and subtitle streams are remuxed losslessly without re-encoding.

### Requirements
- `ffmpeg` and `ffprobe` installed and available in `PATH`
- Python 3.9+ (for `ffmpeg-helper.py`) or Bash (for `ffmpeg-helper.sh`)

### Features
- **Inspect audio tracks (`--info` / `-i`)**: Lists all audio tracks with their 1-based track number, `ffmpeg` stream index, codec, language tag, title, and `[DEFAULT]` disposition status.
- **Set default audio track by number (`--set-default <N>` / `-d <N>`)**: Marks 1-based audio track `<N>` as the default and clears the default flag on all other audio tracks.
- **Set English audio track as default (`--default-eng` / `-e`)**: Finds the first audio track labeled `language=eng` and marks it as default while keeping all other audio tracks intact.
- **Keep only English audio (`--keep-eng` / `-k`)**: Removes all audio tracks except those labeled `language=eng`, preserves video and subtitle streams, and marks the kept English audio track as default.

### Usage

```bash
# Python version
./ffmpeg-helper/ffmpeg-helper.py (--info | --set-default TRACK_NUM | --default-eng | --keep-eng) <input_file> [-o <output_file>]

# Bash version (also accepts subcommands without leading '--', e.g. 'info', 'set-default')
./ffmpeg-helper/ffmpeg-helper.sh (--info | --set-default TRACK_NUM | --default-eng | --keep-eng) <input_file> [-o <output_file>]
```

#### Options
| Option | Description |
| :--- | :--- |
| `-i`, `--info` | Display all audio tracks and their language/default status. |
| `-d <N>`, `--set-default <N>` | Set 1-based audio track `<N>` as default and clear default on other audio tracks (requires at least 2 audio tracks). |
| `-e`, `--default-eng` | Find the English (`eng`) audio track and make it default while keeping all tracks (requires at least 2 audio tracks). |
| `-k`, `--keep-eng` | Remove all non-English audio tracks, keeping only `eng` audio track(s) and setting as default. |
| `-o <file>`, `--output <file>` | Custom output file path (default: `<input_stem>_modified.<ext>`). |
| `-h`, `--help` | Show help message and exit. |

#### Examples

```bash
# Inspect audio tracks in a video file
./ffmpeg-helper/ffmpeg-helper.py --info movie.mp4

# Set audio track #2 as the default track (writes to movie_modified.mp4)
./ffmpeg-helper/ffmpeg-helper.py --set-default 2 movie.mp4

# Set the English audio track as default and save to a custom path
./ffmpeg-helper/ffmpeg-helper.py --default-eng movie.mp4 -o movie_eng_default.mp4

# Strip all non-English audio tracks and keep only English
./ffmpeg-helper/ffmpeg-helper.sh --keep-eng movie.mp4
```

---

## 2. srtfix (`srtfix.py`)

`srtfix.py` is a zero-dependency Python 3 utility for inspecting and fixing `.srt` subtitle files. It handles constant time offsets, frame-rate drift (FPS conversion and detection), and legacy character encodings (with automatic detection for UTF-8, UTF-8 with BOM, UTF-16, CP1250, ISO-8859-2, CP1252, and Latin-1, including heuristic scoring for Polish diacritics).

### Requirements
- Python 3 (standard library only, no external packages required)

### Features
- **Time Shifting (`[offset_seconds]`)**: Shifts all subtitle timestamps forward (`+5`, `12.5`) or backward (`-32`, `-1.25`). Automatically validates that no subtitle is shifted before `00:00:00,000` and reports the maximum safe backward shift if aborted.
- **FPS Detection (`--detect-fps` / `-d`)**: Analyzes subtitle timestamps against standard frame rates (`23.976`, `24.0`, `25.0`, `29.97`, `30.0` FPS) to determine the frame grid the `.srt` file was authored for.
- **FPS Conversion (`--fps <from_fps> <to_fps>`)**: Rescales subtitle timings from `<from_fps>` to `<to_fps>` (e.g., converting `24.0` or `23.976` FPS subtitles to match a `25.0` FPS PAL release). Can be combined with a time offset in a single pass.
- **Encoding Detection & UTF-8 Conversion (`--utf8` / `-u`)**: Detects non-UTF-8 or BOM-prefixed encodings (such as `CP1250`, `ISO-8859-2`, `UTF-16`, or `UTF-8 with BOM`) and converts the output file to clean UTF-8 without BOM.

### Usage

```bash
./srtfix/srtfix.py <input.srt> [offset_seconds] [options]
```

#### Arguments & Options
| Argument / Option | Description |
| :--- | :--- |
| `<input.srt>` | Path to the input `.srt` subtitle file. |
| `[offset_seconds]` | Optional time shift in seconds (e.g., `-32`, `+5`, `-12.5`). Accepts `.` or `,` as decimal separator. |
| `-d`, `--detect-fps` | Detect and display the likely FPS the `.srt` file was created for. |
| `--fps <from_fps> <to_fps>` | Scale subtitle timings from `<from_fps>` to `<to_fps>` (format `xx.xxx`, range `1`–`99.999`). |
| `-u`, `--utf8`, `--to-utf8` | Convert output file character encoding to UTF-8 (without BOM). |
| `-o <file>`, `--output <file>` | Custom output file path. If omitted, a descriptive filename is generated automatically (e.g., `movie_min32s.srt`, `movie_fps24to25.srt`, `movie_utf8.srt`). |
| `-h`, `--help` | Show help message and exit. |

#### Examples

```bash
# Detect character encoding and the FPS a subtitle file was created for
./srtfix/srtfix.py movie.srt --detect-fps

# Shift subtitles backward by 32 seconds (writes to movie_min32s.srt)
./srtfix/srtfix.py movie.srt -32

# Shift subtitles forward by 2.5 seconds
./srtfix/srtfix.py movie.srt +2.5

# Convert timings from 24 FPS to 25 FPS (writes to movie_fps24to25.srt)
./srtfix/srtfix.py movie.srt --fps 24.0 25.0

# Combine FPS conversion, time shift, and encoding conversion to UTF-8
./srtfix/srtfix.py movie.srt -32 --fps 24.0 23.976 --utf8 -o movie_fixed.srt
```

---

## Running Tests

Both tools include test suites using Python's built-in `unittest` framework:

```bash
# Run ffmpeg-helper tests
python3 -m unittest discover -s ffmpeg-helper/test

# Run srtfix tests
python3 -m unittest discover -s srtfix/test
```
