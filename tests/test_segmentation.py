import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_fridge.config import SegmentationConfig
from smart_fridge.database import Database
from smart_fridge.events import EventProcessor
from smart_fridge.orchestrator import EventResult, Recording
from smart_fridge.segmentation import find_segments, parse_motion

SETTINGS = SegmentationConfig(
    motion_threshold=3.0, padding_seconds=1.0, merge_gap_seconds=1.5, min_segment_seconds=0.5
)
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def samples(active: set[float], duration: float = 20.0) -> list[tuple[float, float]]:
    return [
        (step / 10, 10.0 if round(step / 10, 1) in active else 0.2)
        for step in range(int(duration * 10))
    ]


def test_parse_ffmpeg_motion_output() -> None:
    output = (
        "frame:0    pts:1       pts_time:0.1\nlavfi.signalstats.YAVG=0.5\n"
        "frame:1    pts:2       pts_time:0.2\nlavfi.signalstats.YAVG=12.25\n"
    )
    assert parse_motion(output) == [(0.1, 0.5), (0.2, 12.25)]


def test_two_separate_movements_become_two_padded_segments() -> None:
    active = {round(2 + i / 10, 1) for i in range(10)} | {round(12 + i / 10, 1) for i in range(5)}
    assert find_segments(samples(active), 20.0, SETTINGS) == [(1.0, 3.9), (11.0, 13.4)]


def test_close_movements_merge_and_edges_are_clipped() -> None:
    active = {0.0, 0.1, 2.0, 2.1, 19.9}
    assert find_segments(samples(active), 20.0, SETTINGS) == [(0.0, 3.1), (18.9, 20.0)]


def test_no_motion_queues_whole_clip_or_nothing() -> None:
    assert find_segments(samples(set()), 20.0, SETTINGS) == [(0.0, 20.0)]
    quiet = SegmentationConfig(whole_clip_without_motion=False)
    assert find_segments(samples(set()), 20.0, quiet) == []


def make_clip(path: Path) -> Path:
    """2 s still, 2 s moving, 2 s still: one movement in the middle."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=320x240:d=6:r=30",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=80x80:d=6:r=30",
            "-filter_complex",
            "[0][1]overlay=x='if(between(t,2,4),(t-2)*100,0)':y=80",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@needs_ffmpeg
def test_recording_is_cut_queued_and_logged(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    staging = tmp_path / "staging" / "event-1"
    staging.mkdir(parents=True)
    clip = make_clip(staging / "fridge.mp4")
    metadata = staging / "metadata.json"
    metadata.write_text('{"event_id": "event-1"}')
    opened = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    event = EventResult(
        event_id="event-1",
        event_directory=staging,
        metadata_path=metadata,
        door_opened_at=opened,
        door_closed_at=opened,
        recordings=(Recording("fridge", clip, opened),),
    )
    captures = EventProcessor(database, SETTINGS, "test").process(event)

    assert len(captures) == 1
    assert not staging.exists()
    with database.connect() as connection:
        capture = connection.execute("SELECT * FROM captures").fetchone()
        recording = connection.execute("SELECT * FROM recordings").fetchone()
    payload = capture["input_json"]
    assert '"camera": "fridge"' in payload and '"schema_version": 2' in payload
    assert capture["mode"] == "test"
    assert recording["status"] == "segmented" and recording["kept"] == 1
    assert Path(recording["path"]).is_file()  # Test mode keeps the full recording.
    start = float(payload.split('"offset_seconds": ')[1].split(",")[0])
    assert 0.5 <= start <= 2.0


@needs_ffmpeg
def test_production_deletes_the_full_recording_after_cutting(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    staging = tmp_path / "staging" / "event-2"
    staging.mkdir(parents=True)
    clip = make_clip(staging / "door.mp4")
    metadata = staging / "metadata.json"
    metadata.write_text("{}")
    opened = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    event = EventResult(
        "event-2", staging, metadata, opened, opened, (Recording("door", clip, opened),)
    )
    assert len(EventProcessor(database, SETTINGS, "production").process(event)) == 1
    assert not (database.root / "recordings").exists()
    with database.connect() as connection:
        assert connection.execute("SELECT kept FROM recordings").fetchone()[0] == 0
