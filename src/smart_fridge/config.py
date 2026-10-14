from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MLConfig:
    enabled: bool = False
    repository: Path = Path("../grocery-product-detection")
    python: Path = Path("../grocery-product-detection/.venv/bin/python")
    model_config: Path = Path("../grocery-product-detection/configs/inference.yaml")
    models_directory: Path = Path("../grocery-product-detection/models")
    database_directory: Path = Path("database")
    mode: str = "production"
    retention_runs: int = 3
    purge_interval_seconds: float = 60.0
    timeout_seconds: float = 600.0


@dataclass(frozen=True)
class AppConfig:
    data_directory: Path
    wait_after_close_seconds: float
    log_level: str
    simulated_hardware: bool
    camera_count: int
    ml: MLConfig = field(default_factory=MLConfig)


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        document = tomllib.load(config_file)

    system = document.get("system")
    if not isinstance(system, dict):
        raise ValueError("configuration must contain a [system] table")

    ml = document.get("ml", {})
    if not isinstance(ml, dict):
        raise ValueError("ml must be a table")
    # ML paths are anchored at the repository, independent of the caller's cwd.
    root = path.resolve().parent.parent
    defaults = MLConfig()
    ml_config = MLConfig(
        enabled=bool(ml.get("enabled", defaults.enabled)),
        repository=(root / str(ml.get("repository", defaults.repository))).resolve(),
        python=(root / str(ml.get("python", defaults.python))).resolve(),
        model_config=(root / str(ml.get("model_config", defaults.model_config))).resolve(),
        models_directory=(
            root / str(ml.get("models_directory", defaults.models_directory))
        ).resolve(),
        database_directory=(
            root / str(ml.get("database_directory", defaults.database_directory))
        ).resolve(),
        mode=str(ml.get("mode", defaults.mode)),
        retention_runs=int(ml.get("retention_runs", defaults.retention_runs)),
        purge_interval_seconds=float(
            ml.get("purge_interval_seconds", defaults.purge_interval_seconds)
        ),
        timeout_seconds=float(ml.get("timeout_seconds", defaults.timeout_seconds)),
    )
    config = AppConfig(
        data_directory=Path(str(system.get("data_directory", "data/events"))),
        wait_after_close_seconds=float(system.get("wait_after_close_seconds", 0.0)),
        log_level=str(system.get("log_level", "INFO")).upper(),
        simulated_hardware=bool(system.get("simulated_hardware", True)),
        camera_count=int(system.get("camera_count", 1)),
        ml=ml_config,
    )
    _validate(config)
    return config


def _validate(config: AppConfig) -> None:
    import math

    if config.ml.mode not in {"production", "acquisition"}:
        raise ValueError("ml.mode must be production or acquisition")
    if config.ml.retention_runs < 1:
        raise ValueError("retention_runs must be at least 1")
    for value in (config.ml.purge_interval_seconds, config.ml.timeout_seconds):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("ML intervals must be finite and positive")
    if config.wait_after_close_seconds < 0:
        raise ValueError("wait_after_close_seconds cannot be negative")
    if config.camera_count < 1:
        raise ValueError("camera_count must be at least 1")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"unsupported log level: {config.log_level}")
