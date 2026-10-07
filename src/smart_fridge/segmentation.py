"""Cut a door-event recording into the clips where something moved."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from smart_fridge.config import SegmentationConfig

Segment = tuple[float, float]


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"{name} is missing; install ffmpeg")
    return executable


def video_duration(path: Path) -> float:
    """Length of the recording in seconds."""
    output = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json"]
        + [str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    duration = float(json.loads(output)["format"]["duration"])
    if duration <= 0:
        raise ValueError(f"{path} has no video")
    return duration


def motion_samples(path: Path, analysis_fps: float) -> list[tuple[float, float]]:
    """Mean absolute difference between consecutive small grey frames (0-255) over time."""
    filters = (
        f"fps={analysis_fps},scale=160:-2,format=gray,tblend=all_mode=difference,"
        "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"
    )
    output = subprocess.run(
        [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-i", str(path), "-an"]
        + ["-vf", filters, "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    ).stdout
    return parse_motion(output)


def parse_motion(output: str) -> list[tuple[float, float]]:
    """Pair each frame's pts_time line with the YAVG line ffmpeg prints after it."""
    samples: list[tuple[float, float]] = []
    time: float | None = None
    for line in output.splitlines():
        if "pts_time:" in line:
            time = float(line.split("pts_time:")[1].split()[0])
        elif line.startswith("lavfi.signalstats.YAVG=") and time is not None:
            samples.append((time, float(line.split("=", 1)[1])))
            time = None
    return samples


def find_segments(
    samples: list[tuple[float, float]], duration: float, config: SegmentationConfig
) -> list[Segment]:
    """Group moving moments, pad them, and merge segments that nearly touch."""
    active = [time for time, value in samples if value >= config.motion_threshold]
    if not active:
        return [(0.0, duration)] if config.whole_clip_without_motion else []
    ranges: list[list[float]] = []
    for time in active:
        if ranges and time - ranges[-1][1] <= config.merge_gap_seconds:
            ranges[-1][1] = time
        else:
            ranges.append([time, time])
    segments: list[list[float]] = []
    for start, end in ranges:
        start = max(0.0, start - config.padding_seconds)
        end = min(duration, end + config.padding_seconds)
        if segments and start - segments[-1][1] <= config.merge_gap_seconds:
            segments[-1][1] = max(segments[-1][1], end)
        else:
            segments.append([start, end])
    return [
        (round(start, 3), round(end, 3))
        for start, end in segments
        if end - start >= config.min_segment_seconds
    ]


def cut_segment(source: Path, start: float, end: float, destination: Path) -> Path:
    """Re-encode so the clip starts exactly at `start`; ML timing depends on it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(source)]
        + ["-t", f"{end - start:.3f}", "-map", "0:v:0", "-an", "-c:v", "libx264"]
        + ["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        + [str(destination)],
        check=True,
        timeout=600,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"could not cut {source} at {start:.1f}-{end:.1f} s")
    return destination
