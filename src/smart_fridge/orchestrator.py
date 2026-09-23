from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from uuid import uuid4

from smart_fridge.hardware.interfaces import Camera, DoorSensor, Lighting


class SystemState(Enum):
    IDLE = auto()
    DOOR_OPEN = auto()
    CAPTURING = auto()
    ERROR = auto()


@dataclass(frozen=True)
class EventResult:
    event_id: str
    event_directory: Path


class Orchestrator:
    """Coordinate one door event without depending on concrete hardware."""

    def __init__(
        self,
        door: DoorSensor,
        lighting: Lighting,
        cameras: list[Camera],
        data_directory: Path,
    ) -> None:
        self.door = door
        self.lighting = lighting
        self.cameras = cameras
        self.data_directory = data_directory
        self.state = SystemState.IDLE

    def poll(self) -> EventResult | None:
        """Advance the state machine once based on the current door state."""
        if self.state is SystemState.IDLE and self.door.is_open():
            self.state = SystemState.DOOR_OPEN
            return None

        if self.state is SystemState.DOOR_OPEN and not self.door.is_open():
            return self._capture_closed_state()

        return None

    def _capture_closed_state(self) -> EventResult:
        self.state = SystemState.CAPTURING
        event_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        event_directory = self.data_directory / event_id

        try:
            self.lighting.turn_on()
            for index, camera in enumerate(self.cameras):
                camera.capture(event_directory / f"camera-{index + 1}.txt")
        except Exception:
            self.state = SystemState.ERROR
            raise
        finally:
            self.lighting.turn_off()

        self.state = SystemState.IDLE
        return EventResult(event_id=event_id, event_directory=event_directory)
