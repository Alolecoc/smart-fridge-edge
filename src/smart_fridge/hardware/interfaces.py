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


class VideoRecorder(Protocol):
    """One camera that records while the door is open."""

    name: str

    def start(self, destination: Path) -> None:
        """Begin recording to destination; return once recording has started."""

    def stop(self) -> Path:
        """Finish the file cleanly and return its path."""
