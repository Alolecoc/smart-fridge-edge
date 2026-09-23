from __future__ import annotations

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
class SimulatedCamera:
    capture_count: int = 0

    def capture(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("simulated image\n", encoding="utf-8")
        self.capture_count += 1
