from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
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
    metadata_path: Path


class Orchestrator:
    """Coordinate one door event without depending on concrete hardware."""

    def __init__(
        self,
        door: DoorSensor,
        lighting: Lighting,
        cameras: Sequence[Camera],
        data_directory: Path,
        wait_after_close_seconds: float = 0.0,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.door = door
        self.lighting = lighting
        self.cameras = cameras
        self.data_directory = data_directory
        self.wait_after_close_seconds = wait_after_close_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper
        self.state = SystemState.IDLE
        self.door_opened_at: datetime | None = None
        self.logger = logging.getLogger(__name__)

    def poll(self) -> EventResult | None:
        """Advance the state machine once based on the current door state."""
        if self.state is SystemState.IDLE and self.door.is_open():
            self.state = SystemState.DOOR_OPEN
            self.door_opened_at = self.clock()
            self.logger.info("door opened")
            return None

        if self.state is SystemState.DOOR_OPEN and not self.door.is_open():
            self.logger.info("door closed")
            return self._capture_closed_state()

        return None

    def _capture_closed_state(self) -> EventResult:
        self.state = SystemState.CAPTURING
        door_closed_at = self.clock()
        event_id = f"{door_closed_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        event_directory = self.data_directory / event_id
        metadata_path = event_directory / "metadata.json"
        outputs: list[str] = []
        event_directory.mkdir(parents=True, exist_ok=False)
        self.logger.info("capture started", extra={"event_id": event_id})

        try:
            if self.wait_after_close_seconds:
                self.sleeper(self.wait_after_close_seconds)
            self.lighting.turn_on()
            for index, camera in enumerate(self.cameras):
                output_name = f"camera-{index + 1}.txt"
                camera.capture(event_directory / output_name)
                outputs.append(output_name)
            completed_at = self.clock()
            self._write_metadata(
                metadata_path,
                event_id=event_id,
                status="captured",
                door_closed_at=door_closed_at,
                completed_at=completed_at,
                outputs=outputs,
            )
        except Exception as error:
            self.state = SystemState.ERROR
            self._write_metadata(
                metadata_path,
                event_id=event_id,
                status="failed",
                door_closed_at=door_closed_at,
                completed_at=self.clock(),
                outputs=outputs,
                error=str(error),
            )
            self.logger.exception("capture failed", extra={"event_id": event_id})
            raise
        finally:
            self.lighting.turn_off()

        self.state = SystemState.IDLE
        self.door_opened_at = None
        self.logger.info("capture completed", extra={"event_id": event_id})
        return EventResult(
            event_id=event_id,
            event_directory=event_directory,
            metadata_path=metadata_path,
        )

    def _write_metadata(
        self,
        path: Path,
        *,
        event_id: str,
        status: str,
        door_closed_at: datetime,
        completed_at: datetime,
        outputs: list[str],
        error: str | None = None,
    ) -> None:
        document: dict[str, object] = {
            "event_id": event_id,
            "door_opened_at": self._isoformat(self.door_opened_at),
            "door_closed_at": self._isoformat(door_closed_at),
            "completed_at": self._isoformat(completed_at),
            "status": status,
            "sensors": [f"camera-{index + 1}" for index in range(len(self.cameras))],
            "outputs": outputs,
        }
        if error is not None:
            document["error"] = error

        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
