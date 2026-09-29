import json
from pathlib import Path

import pytest

from smart_fridge.hardware.simulated import (
    SimulatedCamera,
    SimulatedDoorSensor,
    SimulatedLighting,
)
from smart_fridge.orchestrator import Orchestrator, SystemState


class FailingCamera:
    def capture(self, destination: Path) -> None:
        raise RuntimeError("simulated camera failure")


def test_door_open_then_close_captures_one_event(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    camera = SimulatedCamera()
    system = Orchestrator(door, lighting, [camera], tmp_path)

    door.open = True
    assert system.poll() is None
    assert system.state is SystemState.DOOR_OPEN

    door.open = False
    result = system.poll()

    assert result is not None
    assert result.event_directory.exists()
    assert (result.event_directory / "camera-1.txt").exists()
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["event_id"] == result.event_id
    assert metadata["status"] == "captured"
    assert metadata["sensors"] == ["camera-1"]
    assert metadata["outputs"] == ["camera-1.txt"]
    assert metadata["door_opened_at"] is not None
    assert metadata["door_closed_at"] is not None
    assert metadata["completed_at"] is not None
    assert camera.capture_count == 1
    assert lighting.enabled is False
    assert system.state is SystemState.IDLE


def test_idle_poll_does_nothing(tmp_path: Path) -> None:
    system = Orchestrator(
        SimulatedDoorSensor(open=False),
        SimulatedLighting(),
        [SimulatedCamera()],
        tmp_path,
    )

    assert system.poll() is None
    assert system.state is SystemState.IDLE


def test_waits_after_door_closes_before_capture(tmp_path: Path) -> None:
    waits: list[float] = []
    door = SimulatedDoorSensor()
    system = Orchestrator(
        door,
        SimulatedLighting(),
        [SimulatedCamera()],
        tmp_path,
        wait_after_close_seconds=1.5,
        sleeper=waits.append,
    )

    door.open = True
    system.poll()
    door.open = False
    system.poll()

    assert waits == [1.5]


def test_capture_failure_writes_metadata_and_enters_error(tmp_path: Path) -> None:
    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    system = Orchestrator(door, lighting, [FailingCamera()], tmp_path)

    door.open = True
    system.poll()
    door.open = False

    with pytest.raises(RuntimeError, match="simulated camera failure"):
        system.poll()

    event_directories = list(tmp_path.iterdir())
    assert len(event_directories) == 1
    metadata = json.loads((event_directories[0] / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error"] == "simulated camera failure"
    assert lighting.enabled is False
    assert system.state is SystemState.ERROR
