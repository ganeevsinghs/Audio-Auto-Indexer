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

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# --------------------------- Data structures ---------------------------


@dataclass
class Segment:
    label: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


# --------------------------- Utilities ---------------------------


def fail(message: str, exit_code: int = 1) -> None:
    print(f"Error: {message}")
    sys.exit(exit_code)


def find_main_audio_file(audio_dir: Path) -> Path:
    if not audio_dir.exists() or not audio_dir.is_dir():
        fail(f"Audio directory not found: {audio_dir}")

    supported_extensions = {
        ".mp3",
        ".wav",
        ".flac",
        ".m4a",
        ".aac",
        ".ogg",
        ".wma",
        ".aiff",
        ".aif",
        ".alac",
        ".mka",
        ".mp4",
        ".m4b",
    }

    candidates: List[Path] = [
        p
        for p in audio_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported_extensions
    ]

    if not candidates:
        fail(
            f"No audio files found in {audio_dir}. Supported extensions: "
            + ", ".join(sorted(supported_extensions))
        )

    if len(candidates) == 1:
        return candidates[0]

    # Prefer files named like main/input/master, otherwise pick the largest by size
    preferred_names = {"main", "input", "master", "audio", "song", "track", "full"}
    for c in candidates:
        if c.stem.lower() in preferred_names:
            return c

    candidates_sorted = sorted(candidates, key=lambda p: p.stat().st_size, reverse=True)
    return candidates_sorted[0]


def check_tool_available(tool_name: str) -> None:
    from shutil import which

    if which(tool_name) is None:
        fail(
            f"{tool_name} is not installed or not on PATH. Please install it and try again."
        )


def run_command(command: List[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stdout = e.stdout.decode(errors="ignore") if e.stdout else ""
        stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
        msg = f"Command failed: {' '.join(command)}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        fail(msg)


def probe_duration_seconds(input_file: Path) -> float:
    # Use ffprobe to get duration in seconds (float)
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_file),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
        fail(f"ffprobe failed to read duration: {stderr}")

    out = result.stdout.decode().strip()
    try:
        return float(out)
    except ValueError:
        fail(f"Could not parse ffprobe duration output: '{out}'")
        return 0.0  # unreachable


def parse_time_to_seconds(text: str, total_duration: Optional[float]) -> float:
    t = text.strip().lower()
    if t == "start":
        return 0.0
    if t == "end":
        if total_duration is None:
            fail("Encountered 'end' keyword but total duration is unknown.")
        return float(total_duration)

    # Accept HH:MM:SS(.ms), MM:SS(.ms), or SS(.ms)
    if ":" in t:
        parts = t.split(":")
        if len(parts) > 3:
            fail(f"Invalid timestamp format: '{text}'")
        # Pad to [HH, MM, SS]
        parts = ["0"] * (3 - len(parts)) + parts
        hh, mm, ss = parts
        try:
            hours = int(hh)
            minutes = int(mm)
            seconds = float(ss)
        except ValueError:
            fail(f"Invalid timestamp numeric parts: '{text}'")
        return hours * 3600 + minutes * 60 + seconds
    else:
        # Plain seconds (possibly with fraction)
        try:
            return float(t)
        except ValueError:
            fail(f"Invalid timestamp: '{text}'")
            return 0.0  # unreachable


def sanitize_label(label: str) -> str:
    cleaned = label.strip()
    if not cleaned:
        return ""
    # Replace forbidden characters for filenames
    forbidden = "<>:\"/\\|?*\n\r\t"
    for ch in forbidden:
        cleaned = cleaned.replace(ch, " ")
    cleaned = " ".join(cleaned.split())  # collapse whitespace
    return cleaned[:80]


def read_segments(timestamps_path: Path, total_duration: float) -> List[Segment]:
    if not timestamps_path.exists():
        fail(f"Timestamps file not found: {timestamps_path}")

    segments: List[Segment] = []
    with timestamps_path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            try:
                tokens = shlex.split(line)
            except ValueError as e:
                fail(f"Line {line_number}: could not parse: {e}\nLine: {raw_line}")

            if len(tokens) == 2:
                # START END
                start_text, end_text = tokens
                label = ""
            elif len(tokens) >= 3:
                # NAME START END (ignore extra tokens by joining them into the name)
                *name_parts, start_text, end_text = tokens
                label = " ".join(name_parts)
            else:
                fail(
                    f"Line {line_number}: expected 'NAME START END' or 'START END'. Got: {raw_line}"
                )

            start_seconds = parse_time_to_seconds(start_text, total_duration)
            end_seconds = parse_time_to_seconds(end_text, total_duration)

            if end_seconds <= start_seconds:
                fail(
                    f"Line {line_number}: end (" 
                    f"{end_seconds:.3f}s) must be greater than start ({start_seconds:.3f}s)"
                )

            segments.append(
                Segment(label=sanitize_label(label), start_seconds=start_seconds, end_seconds=end_seconds)
            )

    if not segments:
        fail("No segments found in timestamps file.")

    return segments


def format_time_ffmpeg(seconds: float) -> str:
    # Keep sub-second precision if present
    return f"{seconds:.3f}"


def export_segments(
    input_audio: Path, output_dir: Path, segments: List[Segment]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    count = len(segments)
    index_width = max(2, len(str(count)))

    for index, seg in enumerate(segments, start=1):
        index_str = str(index).zfill(index_width)
        base_name = index_str
        if seg.label:
            base_name += f" - {seg.label}"
        outfile = output_dir / f"{base_name}.mp3"

        # ffmpeg precise trim with re-encode to mp3 192k
        # Use audio filter to ensure proper format conversion and avoid encoding errors
        # The aformat filter ensures proper sample format to prevent libmp3lame padding issues
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_audio),
            "-ss",
            format_time_ffmpeg(seg.start_seconds),
            "-t",
            format_time_ffmpeg(seg.duration_seconds),
            "-vn",
            "-af",
            "aformat=s16p:44100",
            "-acodec",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-map_metadata",
            "-1",
            "-y",
            str(outfile),
        ]

        print(f"Exporting {outfile.name} ({seg.start_seconds:.3f}s -> {seg.end_seconds:.3f}s)...")
        run_command(cmd)


# --------------------------- Main entry ---------------------------


def main(argv: List[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir

    timestamps_path = project_root / "timestamps.txt"
    audio_dir = project_root / "audio"
    output_dir = project_root / "splittracks"

    check_tool_available("ffmpeg")
    check_tool_available("ffprobe")

    input_audio = find_main_audio_file(audio_dir)
    print(f"Using input audio: {input_audio}")

    total_duration = probe_duration_seconds(input_audio)
    print(f"Input duration: {total_duration:.3f} seconds")

    segments = read_segments(timestamps_path, total_duration)
    export_segments(input_audio, output_dir, segments)

    print(f"Done. Exported {len(segments)} track(s) to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


