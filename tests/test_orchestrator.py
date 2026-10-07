import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_fridge.hardware.simulated import (
    SimulatedDoorSensor,
    SimulatedLighting,
    SimulatedRecorder,
)
from smart_fridge.orchestrator import DebouncedDoor, Orchestrator, SystemState


class FailingRecorder:
    name = "door"

    def start(self, destination: Path) -> None:
        raise RuntimeError("simulated camera failure")

    def stop(self) -> Path:
        raise AssertionError("never started")


class BrokenStopRecorder(SimulatedRecorder):
    def stop(self) -> Path:
        self.recording = None
        raise RuntimeError("file not finalized")


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_records_every_camera_while_the_door_is_open(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    fridge, door_camera = SimulatedRecorder("fridge"), SimulatedRecorder("door")
    system = Orchestrator(door, lighting, [fridge, door_camera], tmp_path)

    door.open = True
    assert system.poll() is None
    assert system.state is SystemState.RECORDING
    assert fridge.recording is not None and door_camera.recording is not None
    assert lighting.enabled

    door.open = False
    result = system.poll()

    assert result is not None
    assert [item.camera for item in result.recordings] == ["fridge", "door"]
    assert all(item.path.is_file() for item in result.recordings)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "recorded"
    assert metadata["stop_reason"] == "door closed"
    assert [item["file"] for item in metadata["recordings"]] == ["fridge.mp4", "door.mp4"]
    assert metadata["door_opened_at"] <= metadata["door_closed_at"]
    assert result.door_opened_at <= result.recordings[0].started_at
    assert not lighting.enabled
    assert system.state is SystemState.IDLE


def test_idle_poll_does_nothing(tmp_path: Path) -> None:
    system = Orchestrator(
        SimulatedDoorSensor(), SimulatedLighting(), [SimulatedRecorder()], tmp_path
    )
    assert system.poll() is None
    assert system.state is SystemState.IDLE
    assert not list(tmp_path.iterdir())


def test_keeps_recording_after_close_when_configured(tmp_path: Path) -> None:
    waits: list[float] = []
    door = SimulatedDoorSensor()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [SimulatedRecorder()],
        tmp_path,
        wait_after_close_seconds=0.5,
        sleeper=waits.append,
    )
    door.open = True
    system.poll()
    door.open = False
    assert system.poll() is not None
    assert waits == [0.5]


def test_long_open_door_stops_recording_and_waits_for_close(tmp_path: Path) -> None:
    clock = FakeClock()
    door = SimulatedDoorSensor(open=True)
    recorder = SimulatedRecorder()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [recorder],
        tmp_path,
        max_recording_seconds=60,
        monotonic=clock,
    )
    system.poll()
    clock.value = 61
    result = system.poll()
    assert result is not None
    assert system.state is SystemState.WAITING_FOR_CLOSE
    assert system.poll() is None
    assert recorder.recordings == 1
    door.open = False
    system.poll()
    assert system.state is SystemState.IDLE


def test_camera_that_fails_to_start_stops_the_others(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    working = SimulatedRecorder("fridge")
    system = Orchestrator(door, lighting, [working, FailingRecorder()], tmp_path)

    door.open = True
    with pytest.raises(RuntimeError, match="simulated camera failure"):
        system.poll()
    assert working.recording is None
    assert system.state is SystemState.ERROR
    metadata = json.loads(next(tmp_path.glob("*/metadata.json")).read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert not lighting.enabled
    system.reset()
    assert system.state is SystemState.ERROR  # Door is still open.
    door.open = False
    system.reset()
    assert system.state is SystemState.IDLE


def test_one_broken_camera_keeps_the_other_recording(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [SimulatedRecorder("fridge"), BrokenStopRecorder("door")],
        tmp_path,
    )
    door.open = True
    system.poll()
    door.open = False
    result = system.poll()
    assert result is not None
    assert [item.camera for item in result.recordings] == ["fridge"]
    assert result.errors and "door" in result.errors[0]
    assert json.loads(result.metadata_path.read_text())["status"] == "partial"


def test_debounce_ignores_short_glitches() -> None:
    clock = FakeClock()
    raw = SimulatedDoorSensor()
    door = DebouncedDoor(raw, 0.1, monotonic=clock)
    raw.open = True
    assert not door.is_open()
    clock.value = 0.05
    raw.open = False
    assert not door.is_open()
    raw.open = True
    clock.value = 0.1
    assert not door.is_open()
    clock.value = 0.2
    assert door.is_open()


def test_event_ids_sort_by_time(tmp_path: Path) -> None:
    times = iter(datetime(2026, 10, 7, 12, 0, second, tzinfo=UTC) for second in range(10))
    door = SimulatedDoorSensor(open=True)
    system = Orchestrator(
        door, SimulatedLighting(), [SimulatedRecorder()], tmp_path, clock=lambda: next(times)
    )
    system.poll()
    door.open = False
    result = system.poll()
    assert result is not None
    assert result.event_id.startswith("20261007T120000Z-")
