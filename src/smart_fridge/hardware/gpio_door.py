from __future__ import annotations

from typing import Protocol


class DoorSwitch(Protocol):
    @property
    def is_pressed(self) -> bool:
        """Return whether the reed switch is electrically closed."""

    def close(self) -> None:
        """Release GPIO resources."""


class GpioDoorSensor:
    """Read a normally-open reed switch connected between a GPIO pin and GND."""

    def __init__(
        self,
        pin: int,
        *,
        bounce_time_seconds: float = 0.05,
        switch: DoorSwitch | None = None,
    ) -> None:
        if switch is None:
            from gpiozero import Button  # type: ignore[import-untyped]

            switch = Button(pin, pull_up=True, bounce_time=bounce_time_seconds)
        self._switch = switch

    def is_open(self) -> bool:
        # Magnet near: reed switch closes to GND and is_pressed is True.
        return not self._switch.is_pressed

    def close(self) -> None:
        self._switch.close()
