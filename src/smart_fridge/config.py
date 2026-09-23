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


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        document = tomllib.load(config_file)

    system = document.get("system")
    if not isinstance(system, dict):
        raise ValueError("configuration must contain a [system] table")

    config = AppConfig(
        data_directory=Path(str(system.get("data_directory", "data/events"))),
        wait_after_close_seconds=float(system.get("wait_after_close_seconds", 0.0)),
        log_level=str(system.get("log_level", "INFO")).upper(),
        simulated_hardware=bool(system.get("simulated_hardware", True)),
        camera_count=int(system.get("camera_count", 1)),
    )
    _validate(config)
    return config


def _validate(config: AppConfig) -> None:
    if config.wait_after_close_seconds < 0:
        raise ValueError("wait_after_close_seconds cannot be negative")
    if config.camera_count < 1:
        raise ValueError("camera_count must be at least 1")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"unsupported log level: {config.log_level}")
