import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_fridge.hardware.simulated import (
    SimulatedDoorSensor,
    SimulatedLighting,
    SimulatedRecorder,
    SimulatedThermalNode,
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


class FailingThermalNode(SimulatedThermalNode):
    def start(self, event_id: str, destination: Path) -> None:
        raise RuntimeError("thermal unavailable")


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


def test_thermal_uses_same_event_and_finishes_with_cameras(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    thermal = SimulatedThermalNode()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [SimulatedRecorder()],
        tmp_path,
        thermal=thermal,
    )

    door.open = True
    system.poll()
    assert thermal.active_event == system.event_id
    door.open = False
    result = system.poll()

    assert result is not None and result.thermal_summary is not None
    assert result.thermal_summary.is_file()
    assert json.loads(result.thermal_summary.read_text())["event_id"] == result.event_id
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["thermal"]["status"] == "captured"
    assert thermal.starts == thermal.stops == 1


def test_thermal_failure_does_not_stop_rgb_recording(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    recorder = SimulatedRecorder()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [recorder],
        tmp_path,
        thermal=FailingThermalNode(),
    )

    door.open = True
    system.poll()
    assert system.state is SystemState.RECORDING
    assert recorder.recording is not None
    door.open = False
    result = system.poll()

    assert result is not None and len(result.recordings) == 1
    assert result.errors == ("thermal: thermal unavailable",)
    assert json.loads(result.metadata_path.read_text())["status"] == "partial"


def test_close_time_is_sensor_time_not_postprocessing_time(tmp_path: Path) -> None:
    times = iter(
        [
            datetime(2026, 11, 16, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 16, 10, 0, 1, tzinfo=UTC),
            datetime(2026, 11, 16, 10, 0, 2, tzinfo=UTC),
            datetime(2026, 11, 16, 10, 5, 0, tzinfo=UTC),
        ]
    )
    door = SimulatedDoorSensor(open=True)
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [SimulatedRecorder()],
        tmp_path,
        clock=lambda: next(times),
    )
    system.poll()
    door.open = False
    result = system.poll()
    assert result is not None
    assert result.door_closed_at == datetime(2026, 11, 16, 10, 0, 2, tzinfo=UTC)


def test_recording_carries_rotation_to_background_processor(tmp_path: Path) -> None:
    door = SimulatedDoorSensor(open=True)
    recorder = SimulatedRecorder(rotation=90)
    system = Orchestrator(door, SimulatedLighting(), [recorder], tmp_path)
    system.poll()
    door.open = False
    result = system.poll()
    assert result is not None
    assert result.recordings[0].rotation == 90
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["recordings"][0]["rotation"] == 90


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
