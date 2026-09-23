from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DoorSensor(Protocol):
    def is_open(self) -> bool:
        """Return the current door state."""


class Lighting(Protocol):
    def turn_on(self) -> None:
        """Turn on controlled refrigerator lighting."""

    def turn_off(self) -> None:
        """Turn off controlled refrigerator lighting."""


class Camera(Protocol):
    def capture(self, destination: Path) -> None:
        """Capture one image and save it at destination."""
