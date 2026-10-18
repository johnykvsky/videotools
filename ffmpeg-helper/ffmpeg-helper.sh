#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ffmpeg-helper.sh --set-default <track_number> <input_file> [-o <output_file>]
  ffmpeg-helper.sh --default-eng <input_file> [-o <output_file>]
  ffmpeg-helper.sh --keep-eng    <input_file> [-o <output_file>]
  ffmpeg-helper.sh --info        <input_file>

Commands (with or without leading '--'):
  --set-default <N>, set-default <N>, -d <N>
      Set audio track <N> (1-based, required) as the default audio track and
      clear the default flag on all other audio tracks.
      Requires more than 1 audio track in the file.

  --default-eng, default-eng, -e
      Find the audio track labeled as English (language=eng) and make it the
      default audio track (keeping all tracks in the file).
      Shows an error if there is only 1 track, tracks are unlabeled, or no 'eng' track exists.

  --keep-eng, keep-eng, -k
      Remove all audio tracks except those labeled as English (language=eng),
      while preserving video, subtitles, and other streams, and mark the kept
      English audio track as default.
      Shows an error if audio tracks are unlabeled or no 'eng' track exists.

  --info, info, -i
      Display all audio tracks and their language/default status.

Options:
  -o, --output <file>   Custom output file path (default: <input_stem>_modified.<ext>)
  -h, --help            Show this help message

Examples:
  ./ffmpeg-helper.sh --set-default 2 movie.mp4
  ./ffmpeg-helper.sh --set-default 3 movie.mp4 -o movie_track3.mp4
  ./ffmpeg-helper.sh --default-eng movie.mp4
  ./ffmpeg-helper.sh --keep-eng movie.mp4
  ./ffmpeg-helper.sh --info movie.mp4
EOF
}

error() {
    echo "Error: $*" >&2
    exit 1
}

check_dependencies() {
    command -v ffmpeg >/dev/null 2>&1 || error "'ffmpeg' is not installed or not in PATH."
    command -v ffprobe >/dev/null 2>&1 || error "'ffprobe' is not installed or not in PATH."
}

# Build default output filename: input.mp4 -> input_modified.mp4
default_output_path() {
    local input="$1"
    local dir base ext stem
    dir="$(dirname -- "$input")"
    base="$(basename -- "$input")"
    if [[ "$base" == *.* ]]; then
        ext=".${base##*.}"
        stem="${base%.*}"
    else
        ext=""
        stem="$base"
    fi
    if [[ "$dir" == "." ]]; then
        echo "${stem}_modified${ext}"
    else
        echo "${dir}/${stem}_modified${ext}"
    fi
}

# Print human-readable list of audio tracks using ffprobe
print_audio_tracks() {
    local input="$1"
    local idx=0
    while IFS= read -r stream_idx; do
        [[ -z "$stream_idx" ]] && continue
        local codec disp_default lang title
        codec="$(ffprobe -v error -select_streams "a:${idx}" -show_entries stream=codec_name -of default=nw=1:nk=1 -- "$input" | head -n 1)"
        disp_default="$(ffprobe -v error -select_streams "a:${idx}" -show_entries stream_disposition=default -of default=nw=1:nk=1 -- "$input" | head -n 1)"
        lang="$(ffprobe -v error -select_streams "a:${idx}" -show_entries stream_tags=language -of default=nw=1:nk=1 -- "$input" | head -n 1)"
        title="$(ffprobe -v error -select_streams "a:${idx}" -show_entries stream_tags=title -of default=nw=1:nk=1 -- "$input" | head -n 1)"

        [[ -z "$codec" ]] && codec="unknown"
        if [[ -z "$lang" || "$lang" == "und" ]]; then
            lang="(unlabeled)"
        fi
        local def_str=""
        [[ "$disp_default" == "1" ]] && def_str=" [DEFAULT]"
        local title_str=""
        [[ -n "$title" ]] && title_str=" - \"${title}\""

        printf "  Track #%d (ffmpeg a:%d, stream #%s): codec=%s, language=%s%s%s\n" \
            "$((idx + 1))" "$idx" "$stream_idx" "$codec" "$lang" "$def_str" "$title_str"
        idx=$((idx + 1))
    done < <(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 -- "$input")
}

get_audio_track_count() {
    local input="$1"
    ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 -- "$input" | grep -c '^[0-9]' || true
}

# Helper to apply default disposition to 0-based audio track index and clear others
apply_default_disposition() {
    local input="$1"
    local output="$2"
    local count="$3"
    local target_zero_idx="$4"
    local track_num=$((target_zero_idx + 1))

    local disp_args=()
    for (( i = 0; i < count; i++ )); do
        if (( i == target_zero_idx )); then
            disp_args+=("-disposition:a:${i}" "default")
        else
            disp_args+=("-disposition:a:${i}" "0")
        fi
    done

    echo ""
    echo "Setting audio track #${track_num} (a:${target_zero_idx}) as default -> '$output'..."
    ffmpeg -i "$input" -map 0 -c copy "${disp_args[@]}" "$output"
    echo "Done! Saved to '$output'."
}

cmd_info() {
    local input="${1:-}"
    [[ -z "$input" ]] && error "Missing input file. Usage: $0 --info <input_file>"
    [[ -f "$input" ]] || error "Input file not found: '$input'"

    local count
    count="$(get_audio_track_count "$input")"
    echo "File: $input"
    echo "Audio tracks found: $count"
    if (( count > 0 )); then
        print_audio_tracks "$input"
    fi
}

cmd_set_default() {
    local track_num=""
    local input=""
    local output=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o|--output)
                [[ $# -lt 2 ]] && error "Option $1 requires an output file path."
                output="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                error "Unknown option: $1"
                ;;
            *)
                if [[ -z "$track_num" ]]; then
                    track_num="$1"
                elif [[ -z "$input" ]]; then
                    input="$1"
                else
                    error "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done

    if [[ -z "$track_num" || -z "$input" ]]; then
        error "Both <track_number> and <input_file> are required. Usage: $0 --set-default <track_number> <input_file> [-o <output_file>]"
    fi

    if ! [[ "$track_num" =~ ^[0-9]+$ ]] || (( track_num < 1 )); then
        error "Invalid track number '$track_num'. Must be a positive integer (e.g., --set-default 2 input.mp4)."
    fi

    [[ -f "$input" ]] || error "Input file not found: '$input'"
    [[ -z "$output" ]] && output="$(default_output_path "$input")"

    local count
    count="$(get_audio_track_count "$input")"

    if (( count == 0 )); then
        error "No audio tracks found in '$input'."
    elif (( count == 1 )); then
        echo "Audio tracks in '$input':" >&2
        print_audio_tracks "$input" >&2
        error "File '$input' only has 1 audio track. At least 2 audio tracks are required to change the default audio track."
    fi

    if (( track_num > count )); then
        echo "Audio tracks in '$input':" >&2
        print_audio_tracks "$input" >&2
        error "Requested audio track #${track_num}, but file only has ${count} audio tracks."
    fi

    echo "Audio tracks in '$input':"
    print_audio_tracks "$input"

    apply_default_disposition "$input" "$output" "$count" "$((track_num - 1))"
}

# Inspect language tags and find first 'eng' track index (0-based), or exit with a descriptive error
find_eng_track_or_fail() {
    local input="$1"
    local count="$2"
    local action_desc="$3"

    local eng_first_idx=-1
    local eng_count=0
    local labeled_count=0

    for (( i = 0; i < count; i++ )); do
        local lang
        lang="$(ffprobe -v error -select_streams "a:${i}" -show_entries stream_tags=language -of default=nw=1:nk=1 -- "$input" | head -n 1)"
        if [[ -n "$lang" && "$lang" != "und" ]]; then
            labeled_count=$((labeled_count + 1))
        fi
        if [[ "$lang" == "eng" ]]; then
            if (( eng_first_idx == -1 )); then
                eng_first_idx=$i
            fi
            eng_count=$((eng_count + 1))
        fi
    done

    if (( eng_count == 0 )); then
        echo "Audio tracks in '$input':" >&2
        print_audio_tracks "$input" >&2
        if (( labeled_count == 0 )); then
            error "None of the ${count} audio track(s) in '$input' have language labels. Cannot ${action_desc}."
        else
            error "No English ('eng') audio track found in '$input' (found ${labeled_count}/${count} labeled track(s), none with language='eng')."
        fi
    fi

    FOUND_ENG_IDX=$eng_first_idx
    FOUND_ENG_COUNT=$eng_count
}

cmd_default_eng() {
    local input=""
    local output=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o|--output)
                [[ $# -lt 2 ]] && error "Option $1 requires an output file path."
                output="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                error "Unknown option: $1"
                ;;
            *)
                if [[ -z "$input" ]]; then
                    input="$1"
                else
                    error "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done

    [[ -z "$input" ]] && error "Missing input file. Usage: $0 --default-eng <input_file> [-o <output_file>]"
    [[ -f "$input" ]] || error "Input file not found: '$input'"
    [[ -z "$output" ]] && output="$(default_output_path "$input")"

    local count
    count="$(get_audio_track_count "$input")"

    if (( count == 0 )); then
        error "No audio tracks found in '$input'."
    elif (( count == 1 )); then
        echo "Audio tracks in '$input':" >&2
        print_audio_tracks "$input" >&2
        error "File '$input' only has 1 audio track. At least 2 audio tracks are required to change the default audio track."
    fi

    FOUND_ENG_IDX=-1
    FOUND_ENG_COUNT=0
    find_eng_track_or_fail "$input" "$count" "set English ('eng') as default"

    echo "Audio tracks in '$input':"
    print_audio_tracks "$input"

    apply_default_disposition "$input" "$output" "$count" "$FOUND_ENG_IDX"
}

cmd_keep_eng() {
    local input=""
    local output=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o|--output)
                [[ $# -lt 2 ]] && error "Option $1 requires an output file path."
                output="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                error "Unknown option: $1"
                ;;
            *)
                if [[ -z "$input" ]]; then
                    input="$1"
                else
                    error "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done

    [[ -z "$input" ]] && error "Missing input file. Usage: $0 --keep-eng <input_file> [-o <output_file>]"
    [[ -f "$input" ]] || error "Input file not found: '$input'"
    [[ -z "$output" ]] && output="$(default_output_path "$input")"

    local count
    count="$(get_audio_track_count "$input")"

    if (( count == 0 )); then
        error "No audio tracks found in '$input'."
    fi

    FOUND_ENG_IDX=-1
    FOUND_ENG_COUNT=0
    find_eng_track_or_fail "$input" "$count" "filter for English ('eng') audio"

    echo "Audio tracks in '$input':"
    print_audio_tracks "$input"
    echo ""
    echo "Keeping only English ('eng') audio track(s) (${FOUND_ENG_COUNT} found) and setting as default -> '$output'..."
    ffmpeg -i "$input" -map 0 -map -0:a -map 0:a:m:language:eng -c copy -disposition:a:0 default "$output"
    echo "Done! Saved to '$output'."
}

main() {
    check_dependencies

    if [[ $# -eq 0 ]]; then
        usage
        exit 1
    fi

    local subcommand="$1"
    shift

    case "$subcommand" in
        --set-default|set-default|-d)
            cmd_set_default "$@"
            ;;
        --default-eng|default-eng|-e)
            cmd_default_eng "$@"
            ;;
        --keep-eng|keep-eng|-k)
            cmd_keep_eng "$@"
            ;;
        --info|info|-i)
            cmd_info "$@"
            ;;
        -h|--help|help)
            usage
            exit 0
            ;;
        *)
            error "Unknown command '$subcommand'. Run '$0 --help' for usage."
            ;;
    esac
}

main "$@"
