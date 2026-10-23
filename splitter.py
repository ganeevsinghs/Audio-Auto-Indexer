#!/usr/bin/env python3
"""Shared audio splitting helpers used by the CLI and the web app."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Callable, List, Optional


SUPPORTED_AUDIO_EXTENSIONS = {
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


class SplitError(Exception):
    """Raised when splitting or timestamp parsing fails."""


@dataclass
class Segment:
    label: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass
class TimestampRow:
    name: str
    start_text: str
    end_text: str
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None


def check_tool_available(tool_name: str) -> None:
    if which(tool_name) is None:
        raise SplitError(
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
        raise SplitError(
            f"Command failed: {' '.join(command)}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        ) from e


def probe_duration_seconds(input_file: Path) -> float:
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
        raise SplitError(f"ffprobe failed to read duration: {stderr}") from e

    out = result.stdout.decode().strip()
    try:
        return float(out)
    except ValueError as e:
        raise SplitError(f"Could not parse ffprobe duration output: '{out}'") from e


def parse_time_to_seconds(text: str, total_duration: Optional[float] = None) -> float:
    t = text.strip().lower()
    if not t:
        raise SplitError("Timestamp is empty.")
    if t == "start":
        return 0.0
    if t == "end":
        if total_duration is None:
            raise SplitError("Encountered 'end' keyword but total duration is unknown.")
        return float(total_duration)

    if ":" in t:
        parts = t.split(":")
        if len(parts) > 3:
            raise SplitError(f"Invalid timestamp format: '{text}'")
        parts = ["0"] * (3 - len(parts)) + parts
        hh, mm, ss = parts
        try:
            hours = int(hh)
            minutes = int(mm)
            seconds = float(ss)
        except ValueError as e:
            raise SplitError(f"Invalid timestamp numeric parts: '{text}'") from e
        if minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
            if not (minutes >= 0 and seconds >= 0):
                raise SplitError(f"Invalid timestamp: '{text}'")
        return hours * 3600 + minutes * 60 + seconds

    try:
        return float(t)
    except ValueError as e:
        raise SplitError(f"Invalid timestamp: '{text}'") from e


def sanitize_label(label: str) -> str:
    cleaned = label.strip()
    if not cleaned:
        return ""
    forbidden = '<>:"/\\|?*\n\r\t'
    for ch in forbidden:
        cleaned = cleaned.replace(ch, " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:180]


def format_time_ffmpeg(seconds: float) -> str:
    return f"{seconds:.3f}"


def export_segment(
    input_audio: Path,
    outfile: Path,
    segment: Segment,
) -> Path:
    outfile.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_audio),
        "-ss",
        format_time_ffmpeg(segment.start_seconds),
        "-t",
        format_time_ffmpeg(segment.duration_seconds),
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
    run_command(cmd)
    return outfile


def export_segments(
    input_audio: Path,
    output_dir: Path,
    segments: List[Segment],
    on_progress: Optional[Callable[[int, int, Segment, Path], None]] = None,
) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = len(segments)
    index_width = max(2, len(str(count)))
    paths: List[Path] = []

    for index, seg in enumerate(segments, start=1):
        index_str = str(index).zfill(index_width)
        base_name = index_str
        if seg.label:
            base_name += f" - {seg.label}"
        outfile = output_dir / f"{base_name}.mp3"
        export_segment(input_audio, outfile, seg)
        paths.append(outfile)
        if on_progress:
            on_progress(index, count, seg, outfile)

    return paths


def parse_timestamp_text(text: str, total_duration: Optional[float] = None) -> List[TimestampRow]:
    rows: List[TimestampRow] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as e:
            raise SplitError(
                f"Line {line_number}: could not parse: {e}\nLine: {raw_line}"
            ) from e

        if len(tokens) == 2:
            start_text, end_text = tokens
            label = ""
        elif len(tokens) >= 3:
            *name_parts, start_text, end_text = tokens
            label = " ".join(name_parts)
        else:
            raise SplitError(
                f"Line {line_number}: expected 'NAME START END' or 'START END'. Got: {raw_line}"
            )

        start_seconds = parse_time_to_seconds(start_text, total_duration)
        end_seconds = parse_time_to_seconds(end_text, total_duration)
        if end_seconds <= start_seconds:
            raise SplitError(
                f"Line {line_number}: end ({end_seconds:.3f}s) must be greater than start "
                f"({start_seconds:.3f}s)"
            )

        rows.append(
            TimestampRow(
                name=sanitize_label(label),
                start_text=start_text,
                end_text=end_text,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        )

    if not rows:
        raise SplitError("No segments found in timestamps file.")

    return rows


def read_segments(timestamps_path: Path, total_duration: float) -> List[Segment]:
    if not timestamps_path.exists():
        raise SplitError(f"Timestamps file not found: {timestamps_path}")

    text = timestamps_path.read_text(encoding="utf-8")
    return [
        Segment(
            label=row.name,
            start_seconds=row.start_seconds or 0.0,
            end_seconds=row.end_seconds or 0.0,
        )
        for row in parse_timestamp_text(text, total_duration)
    ]
