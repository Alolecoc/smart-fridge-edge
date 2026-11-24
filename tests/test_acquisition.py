import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

from smart_fridge.config import CameraConfig, load_config
from smart_fridge.hardware.raspberry_pi import capture_still
from smart_fridge.hardware.simulated import SimulatedDoorSensor, SimulatedRecorder
from smart_fridge.main import capture_image, run_live
from smart_fridge.service import MLService


def test_acquisition_mode_does_not_record_door_events(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/ml.toml")
    config = replace(
        config,
        data_directory=tmp_path / "events",
        ml=replace(
            config.ml,
            enabled=False,
            mode="acquisition",
            database_directory=tmp_path / "database",
        ),
        door=replace(config.door, poll_interval_seconds=0.01),
        thermal=replace(config.thermal, enabled=False),
    )
    door = SimulatedDoorSensor(open=True)
    recorder = SimulatedRecorder()
    stop = threading.Event()
    service = MLService(config.ml)
    thread = threading.Thread(target=run_live, args=(config, service, (door, [recorder]), stop))
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert recorder.recording is None
    assert recorder.recordings == 0


def test_capture_still_uses_configured_rpicam(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "photo.jpg"
    monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    camera = CameraConfig(name="fridge", index=1, width=2304, height=1296)

    assert capture_still(camera, destination) == destination
    assert destination.read_bytes() == b"jpeg"


def test_capture_image_keeps_requested_paths(monkeypatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/ml.toml")
    config = replace(config, thermal=replace(config.thermal, enabled=True))
    destination = tmp_path / "chosen" / "photo.jpg"
    captured: list[Path] = []

    def fake_rgb(_camera, path: Path) -> Path:
        captured.append(path)
        path.write_bytes(b"rgb")
        return path

    def fake_thermal(_config, path: Path) -> Path:
        captured.append(path)
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr("smart_fridge.hardware.raspberry_pi.capture_still", fake_rgb)
    monkeypatch.setattr("smart_fridge.main.capture_thermal_frame", fake_thermal)

    capture_image(config, destination, "fridge")

    assert set(captured) == {destination, destination.with_suffix(".thermal.json")}
