from __future__ import annotations

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
