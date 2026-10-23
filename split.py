#!/usr/bin/env python3
"""
Split the main audio file in the `audio/` folder into numbered MP3 tracks (192kbps)
based on `timestamps.txt` in the project root, and save them to `splittracks/`.

Accepted timestamp formats for start/end:
 - SS
 - SS.mmm
 - MM:SS
 - MM:SS.mmm
 - HH:MM:SS
 - HH:MM:SS.mmm
 - The special keywords: "start" (0s) and "end" (full length of input)

Accepted line formats in `timestamps.txt` (use quotes around names with spaces):
 - NAME START END
 - START END

Examples:
 Intro 0:00 0:30
 "Verse 1" 0:30 1:12.500
 1:12.5 2:05.2
 ganeev start end

Requires ffmpeg and ffprobe to be installed and available on PATH.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from splitter import (
    SplitError,
    SUPPORTED_AUDIO_EXTENSIONS,
    check_tool_available,
    export_segments,
    probe_duration_seconds,
    read_segments,
)


def fail(message: str, exit_code: int = 1) -> None:
    print(f"Error: {message}")
    raise SystemExit(exit_code)


def find_main_audio_file(audio_dir: Path) -> Path:
    if not audio_dir.exists() or not audio_dir.is_dir():
        fail(f"Audio directory not found: {audio_dir}")

    candidates = [
        p
        for p in audio_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]

    if not candidates:
        fail(
            f"No audio files found in {audio_dir}. Supported extensions: "
            + ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        )

    if len(candidates) == 1:
        return candidates[0]

    preferred_names = {"main", "input", "master", "audio", "song", "track", "full"}
    for c in candidates:
        if c.stem.lower() in preferred_names:
            return c

    candidates_sorted = sorted(candidates, key=lambda p: p.stat().st_size, reverse=True)
    return candidates_sorted[0]


def main(argv: List[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir

    timestamps_path = project_root / "timestamps.txt"
    audio_dir = project_root / "audio"
    output_dir = project_root / "splittracks"

    try:
        check_tool_available("ffmpeg")
        check_tool_available("ffprobe")

        input_audio = find_main_audio_file(audio_dir)
        print(f"Using input audio: {input_audio}")

        total_duration = probe_duration_seconds(input_audio)
        print(f"Input duration: {total_duration:.3f} seconds")

        segments = read_segments(timestamps_path, total_duration)

        def on_progress(index, count, seg, outfile):
            print(
                f"Exporting {outfile.name} ({seg.start_seconds:.3f}s -> {seg.end_seconds:.3f}s)..."
            )

        export_segments(input_audio, output_dir, segments, on_progress=on_progress)
        print(f"Done. Exported {len(segments)} track(s) to: {output_dir}")
        return 0
    except SplitError as e:
        fail(str(e))
        return 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
