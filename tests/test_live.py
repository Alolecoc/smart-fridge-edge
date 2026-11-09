import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from test_ml_integration import FAKE_ML
from test_segmentation import make_clip, needs_ffmpeg

from smart_fridge.config import MLConfig, SegmentationConfig, load_config
from smart_fridge.hardware.interfaces import VideoRecorder
from smart_fridge.hardware.simulated import SimulatedDoorSensor, SimulatedRecorder
from smart_fridge.main import run_live
from smart_fridge.service import MLService


@needs_ffmpeg
def test_door_event_is_recorded_segmented_and_predicted(tmp_path: Path) -> None:
    repository = tmp_path / "ml"
    repository.mkdir()
    (repository / "main.py").write_text(FAKE_ML)
    sample = make_clip(tmp_path / "sample.mp4")
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/ml.toml")
    config = replace(
        config,
        ml=MLConfig(
            enabled=True,
            repository=repository,
            python=Path(sys.executable),
            database_directory=tmp_path / "database",
            mode="test",
            purge_interval_seconds=60,
        ),
        door=replace(config.door, debounce_seconds=0.0, poll_interval_seconds=0.01),
        segmentation=SegmentationConfig(),
    )
    door = SimulatedDoorSensor()
    recorders: list[VideoRecorder] = [
        SimulatedRecorder("fridge", sample=sample),
        SimulatedRecorder("door", sample=sample),
    ]
    service = MLService(config.ml)
    stop = threading.Event()
    thread = threading.Thread(target=run_live, args=(config, service, (door, recorders), stop))
    thread.start()

    def movements() -> int:
        with service.database.connect() as connection:
            count: int = connection.execute("SELECT COUNT(*) FROM movements").fetchone()[0]
        return count

    try:
        time.sleep(0.1)
        door.open = True
        time.sleep(0.1)
        door.open = False
        deadline = time.monotonic() + 30
        while movements() < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        stop.set()
        thread.join(timeout=30)
    assert not thread.is_alive()
    with service.database.connect() as connection:
        cameras = {row[0] for row in connection.execute("SELECT camera FROM movements")}
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        statuses = {row[0] for row in connection.execute("SELECT status FROM captures")}
        recordings = connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
    assert cameras == {"fridge", "door"}
    assert events == 1 and recordings == 2
    assert statuses == {"completed"}
    assert not list((tmp_path / "database/staging").iterdir())
