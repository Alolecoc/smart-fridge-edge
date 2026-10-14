from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_directory: Path
    wait_after_close_seconds: float
    log_level: str
    simulated_hardware: bool
    camera_count: int
    camera_backend: str
    camera_indices: tuple[int, ...]
    camera_width: int
    camera_height: int
    camera_capture_delay_ms: int
    door_backend: str
    door_gpio_pin: int
    door_bounce_time_seconds: float
    door_poll_interval_seconds: float


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        document = tomllib.load(config_file)

    system = document.get("system")
    if not isinstance(system, dict):
        raise ValueError("configuration must contain a [system] table")

    camera = document.get("camera", {})
    if not isinstance(camera, dict):
        raise ValueError("[camera] must be a table")

    door = document.get("door", {})
    if not isinstance(door, dict):
        raise ValueError("[door] must be a table")

    camera_indices_value = camera.get("indices", list(range(int(system.get("camera_count", 1)))))
    if not isinstance(camera_indices_value, list) or not all(
        isinstance(index, int) for index in camera_indices_value
    ):
        raise ValueError("camera indices must be a list of integers")

    config = AppConfig(
        data_directory=Path(str(system.get("data_directory", "data/events"))),
        wait_after_close_seconds=float(system.get("wait_after_close_seconds", 0.0)),
        log_level=str(system.get("log_level", "INFO")).upper(),
        simulated_hardware=bool(system.get("simulated_hardware", True)),
        camera_count=int(system.get("camera_count", 1)),
        camera_backend=str(camera.get("backend", "simulated")).lower(),
        camera_indices=tuple(camera_indices_value),
        camera_width=int(camera.get("width", 2304)),
        camera_height=int(camera.get("height", 1296)),
        camera_capture_delay_ms=int(camera.get("capture_delay_ms", 2000)),
        door_backend=str(door.get("backend", "simulated")).lower(),
        door_gpio_pin=int(door.get("gpio_pin", 17)),
        door_bounce_time_seconds=float(door.get("bounce_time_seconds", 0.05)),
        door_poll_interval_seconds=float(door.get("poll_interval_seconds", 0.05)),
    )
    _validate(config)
    return config


def _validate(config: AppConfig) -> None:
    if config.wait_after_close_seconds < 0:
        raise ValueError("wait_after_close_seconds cannot be negative")
    if config.camera_count < 1:
        raise ValueError("camera_count must be at least 1")
    if config.camera_backend not in {"simulated", "rpicam"}:
        raise ValueError(f"unsupported camera backend: {config.camera_backend}")
    if not config.camera_indices:
        raise ValueError("camera indices must contain at least one camera")
    if any(index < 0 for index in config.camera_indices):
        raise ValueError("camera indices cannot be negative")
    if config.camera_width < 1 or config.camera_height < 1:
        raise ValueError("camera dimensions must be positive")
    if config.camera_capture_delay_ms < 0:
        raise ValueError("camera capture delay cannot be negative")
    if config.door_backend not in {"simulated", "gpio"}:
        raise ValueError(f"unsupported door backend: {config.door_backend}")
    if config.door_gpio_pin < 0:
        raise ValueError("door GPIO pin cannot be negative")
    if config.door_bounce_time_seconds < 0:
        raise ValueError("door bounce time cannot be negative")
    if config.door_poll_interval_seconds <= 0:
        raise ValueError("door poll interval must be positive")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"unsupported log level: {config.log_level}")
