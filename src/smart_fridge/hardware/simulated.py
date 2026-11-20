from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SimulatedDoorSensor:
    open: bool = False

    def is_open(self) -> bool:
        return self.open


@dataclass
class SimulatedLighting:
    enabled: bool = False

    def turn_on(self) -> None:
        self.enabled = True

    def turn_off(self) -> None:
        self.enabled = False


@dataclass
class SimulatedRecorder:
    """Writes a sample clip (or a placeholder file) instead of using a camera."""

    name: str = "fridge"
    sample: Path | None = None
    recording: Path | None = None
    recordings: int = 0
    rotation: int = 0

    def start(self, destination: Path) -> None:
        if self.recording is not None:
            raise RuntimeError(f"{self.name} is already recording")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.recording = destination

    def stop(self) -> Path:
        if self.recording is None:
            raise RuntimeError(f"{self.name} is not recording")
        path, self.recording = self.recording, None
        if self.sample is not None:
            shutil.copyfile(self.sample, path)
        else:
            path.write_bytes(b"simulated video\n")
        self.recordings += 1
        return path


@dataclass
class SimulatedThermalNode:
    """Thermal node used by tests and development without physical hardware."""

    active_event: str | None = None
    destination: Path | None = None
    starts: int = 0
    stops: int = 0

    def start(self, event_id: str, destination: Path) -> None:
        if self.active_event is not None:
            raise RuntimeError("thermal node is already capturing")
        destination.mkdir(parents=True, exist_ok=True)
        self.active_event = event_id
        self.destination = destination
        self.starts += 1
        (destination / "frames.jsonl").write_text(
            json.dumps({"type": "frame", "event_id": event_id, "seq": 0}) + "\n",
            encoding="utf-8",
        )

    def stop(self, event_id: str) -> Path:
        if self.active_event != event_id or self.destination is None:
            raise RuntimeError("thermal node is not capturing this event")
        summary = self.destination / "summary.json"
        summary.write_text(
            json.dumps({"event_id": event_id, "frames": 1, "dropped": 0}) + "\n",
            encoding="utf-8",
        )
        self.active_event = None
        self.destination = None
        self.stops += 1
        return summary

    def status(self) -> dict[str, object]:
        return {"state": "capturing" if self.active_event else "idle"}

    def close(self) -> None:
        return
