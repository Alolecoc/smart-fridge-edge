from pathlib import Path

from smart_fridge.hardware.simulated import (
    SimulatedCamera,
    SimulatedDoorSensor,
    SimulatedLighting,
)
from smart_fridge.orchestrator import Orchestrator, SystemState


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
