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

from smart_fridge.hardware.interfaces import DoorSensor, Lighting, VideoRecorder


class SystemState(Enum):
    IDLE = auto()
    RECORDING = auto()
    WAITING_FOR_CLOSE = auto()
    ERROR = auto()


@dataclass(frozen=True)
class Recording:
    camera: str
    path: Path
    started_at: datetime


@dataclass(frozen=True)
class EventResult:
    event_id: str
    event_directory: Path
    metadata_path: Path
    door_opened_at: datetime
    door_closed_at: datetime
    recordings: tuple[Recording, ...]
    errors: tuple[str, ...] = ()


class DebouncedDoor:
    """Report a new door state only after it has been stable for `seconds`."""

    def __init__(
        self,
        door: DoorSensor,
        seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.door = door
        self.seconds = seconds
        self.monotonic = monotonic
        self.state = door.is_open()
        self.candidate = self.state
        self.since = monotonic()

    def is_open(self) -> bool:
        raw = self.door.is_open()
        current = self.monotonic()
        if raw != self.candidate:
            self.candidate, self.since = raw, current
        if raw != self.state and current - self.since >= self.seconds:
            self.state = raw
        return self.state


class Orchestrator:
    """Record every camera while the door is open, without depending on concrete hardware."""

    def __init__(
        self,
        door: DoorSensor,
        lighting: Lighting,
        recorders: Sequence[VideoRecorder],
        data_directory: Path,
        wait_after_close_seconds: float = 0.0,
        max_recording_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.door = door
        self.lighting = lighting
        self.recorders = recorders
        self.data_directory = data_directory
        self.wait_after_close_seconds = wait_after_close_seconds
        self.max_recording_seconds = max_recording_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.state = SystemState.IDLE
        self.event_id: str | None = None
        self.event_directory: Path | None = None
        self.door_opened_at: datetime | None = None
        self.recording_since = 0.0
        self.active: list[tuple[VideoRecorder, datetime]] = []
        self.logger = logging.getLogger(__name__)

    def poll(self) -> EventResult | None:
        """Advance the state machine once based on the current door state."""
        door_open = self.door.is_open()
        if self.state is SystemState.IDLE and door_open:
            self._start_recording()
            return None
        if self.state is SystemState.RECORDING:
            if not door_open:
                self.logger.info("door closed", extra={"event_id": self.event_id})
                if self.wait_after_close_seconds:
                    self.sleeper(self.wait_after_close_seconds)
                return self.finish("door closed")
            if self.monotonic() - self.recording_since >= self.max_recording_seconds:
                result = self.finish("maximum recording length reached")
                self.state = SystemState.WAITING_FOR_CLOSE
                return result
        if self.state is SystemState.WAITING_FOR_CLOSE and not door_open:
            self.state = SystemState.IDLE
        return None

    def reset(self) -> None:
        """Return to IDLE after an error once the door is closed again."""
        if self.state is SystemState.ERROR and not self.door.is_open():
            self.state = SystemState.IDLE

    def _start_recording(self) -> None:
        self.door_opened_at = self.clock()
        self.event_id = f"{self.door_opened_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        self.event_directory = self.data_directory / self.event_id
        self.event_directory.mkdir(parents=True, exist_ok=False)
        self.recording_since = self.monotonic()
        self.logger.info("door opened; recording", extra={"event_id": self.event_id})
        self.lighting.turn_on()
        try:
            for recorder in self.recorders:
                started_at = self.clock()
                recorder.start(self.event_directory / f"{recorder.name}.mp4")
                self.active.append((recorder, started_at))
        except Exception as error:
            for recorder, _ in self.active:
                try:
                    recorder.stop()
                except Exception:
                    self.logger.exception("could not stop %s", recorder.name)
            self.active = []
            self.lighting.turn_off()
            self.state = SystemState.ERROR
            self._write_metadata(self.clock(), [], [str(error)], "failed")
            self.logger.exception("recording failed to start", extra={"event_id": self.event_id})
            raise
        self.state = SystemState.RECORDING

    def finish(self, reason: str) -> EventResult:
        """Stop every camera; a camera that fails does not discard the others."""
        assert self.event_id is not None and self.event_directory is not None
        assert self.door_opened_at is not None
        recordings: list[Recording] = []
        errors: list[str] = []
        for recorder, started_at in self.active:
            try:
                recordings.append(Recording(recorder.name, recorder.stop(), started_at))
            except Exception as error:
                errors.append(f"{recorder.name}: {error}")
                self.logger.exception("camera %s failed", recorder.name)
        self.active = []
        self.lighting.turn_off()
        closed_at = self.clock()
        status = "recorded" if recordings and not errors else "partial" if recordings else "failed"
        metadata_path = self._write_metadata(closed_at, recordings, errors, status, reason)
        self.logger.info("recording stopped (%s)", reason, extra={"event_id": self.event_id})
        result = EventResult(
            event_id=self.event_id,
            event_directory=self.event_directory,
            metadata_path=metadata_path,
            door_opened_at=self.door_opened_at,
            door_closed_at=closed_at,
            recordings=tuple(recordings),
            errors=tuple(errors),
        )
        self.state = SystemState.IDLE
        return result

    def _write_metadata(
        self,
        closed_at: datetime,
        recordings: list[Recording],
        errors: list[str],
        status: str,
        reason: str = "",
    ) -> Path:
        assert self.event_directory is not None and self.door_opened_at is not None
        document: dict[str, object] = {
            "event_id": self.event_id,
            "door_opened_at": self.door_opened_at.isoformat(),
            "door_closed_at": closed_at.isoformat(),
            "stop_reason": reason,
            "status": status,
            "cameras": [recorder.name for recorder in self.recorders],
            "recordings": [
                {
                    "camera": item.camera,
                    "file": item.path.name,
                    "started_at": item.started_at.isoformat(),
                }
                for item in recordings
            ],
            "errors": errors,
        }
        path = self.event_directory / "metadata.json"
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary_path.replace(path)
        return path
