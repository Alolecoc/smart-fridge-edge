from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODES = ("production", "acquisition", "test")


@dataclass(frozen=True)
class MLConfig:
    enabled: bool = False
    repository: Path = Path("../grocery-product-detection")
    python: Path = Path("../grocery-product-detection/.venv/bin/python")
    model_config: Path = Path("../grocery-product-detection/configs/video.yaml")
    models_directory: Path = Path("../grocery-product-detection/models")
    database_directory: Path = Path("database")
    mode: str = "production"
    retention_runs: int = 3
    purge_interval_seconds: float = 60.0
    timeout_seconds: float = 600.0


@dataclass(frozen=True)
class DoorConfig:
    """A door switch on one BCM GPIO pin; None until the real pin is configured."""

    gpio_pin: int | None = None
    open_level: str = "high"
    pull_up: bool = True
    debounce_seconds: float = 0.1
    poll_interval_seconds: float = 0.05


@dataclass(frozen=True)
class CameraConfig:
    """One video camera. The name must match a camera in the ML video configuration."""

    name: str
    kind: str = "rpicam"
    index: int = 0
    device: str = "/dev/video0"
    width: int = 1280
    height: int = 720
    fps: int = 30


@dataclass(frozen=True)
class SegmentationConfig:
    """How a door-event recording is cut into clips where something moved."""

    analysis_fps: float = 10.0
    motion_threshold: float = 3.0
    padding_seconds: float = 1.0
    merge_gap_seconds: float = 1.5
    min_segment_seconds: float = 0.5
    whole_clip_without_motion: bool = True
    max_recording_seconds: float = 300.0


DEFAULT_CAMERAS: tuple[CameraConfig, ...] = (
    CameraConfig(name="fridge", index=0),
    CameraConfig(name="door", index=1),
)


@dataclass(frozen=True)
class AppConfig:
    data_directory: Path
    wait_after_close_seconds: float
    log_level: str
    simulated_hardware: bool
    camera_count: int
    ml: MLConfig = field(default_factory=MLConfig)
    door: DoorConfig = field(default_factory=DoorConfig)
    cameras: tuple[CameraConfig, ...] = DEFAULT_CAMERAS
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a table")
    return value


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        document = tomllib.load(config_file)

    system = document.get("system")
    if not isinstance(system, dict):
        raise ValueError("configuration must contain a [system] table")

    ml = _table(document, "ml")
    # ML paths are anchored at the repository, independent of the caller's cwd.
    root = path.resolve().parent.parent
    defaults = MLConfig()
    ml_config = MLConfig(
        enabled=bool(ml.get("enabled", defaults.enabled)),
        repository=(root / str(ml.get("repository", defaults.repository))).resolve(),
        # absolute(), not resolve(): a venv's python is a symlink to the system python,
        # and resolving it would silently drop the venv's packages.
        python=Path(os.path.normpath(root / str(ml.get("python", defaults.python)))),
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

    door = _table(document, "door")
    pin = door.get("gpio_pin")
    door_defaults = DoorConfig()
    door_config = DoorConfig(
        gpio_pin=None if pin is None else int(pin),
        open_level=str(door.get("open_level", door_defaults.open_level)).lower(),
        pull_up=bool(door.get("pull_up", door_defaults.pull_up)),
        debounce_seconds=float(door.get("debounce_seconds", door_defaults.debounce_seconds)),
        poll_interval_seconds=float(
            door.get("poll_interval_seconds", door_defaults.poll_interval_seconds)
        ),
    )

    cameras = _table(document, "cameras")
    camera_configs: tuple[CameraConfig, ...] = DEFAULT_CAMERAS
    if cameras:
        camera_configs = tuple(
            CameraConfig(
                name=name,
                kind=str(_table(cameras, name).get("kind", "rpicam")),
                index=int(_table(cameras, name).get("index", 0)),
                device=str(_table(cameras, name).get("device", "/dev/video0")),
                width=int(_table(cameras, name).get("width", 1280)),
                height=int(_table(cameras, name).get("height", 720)),
                fps=int(_table(cameras, name).get("fps", 30)),
            )
            for name in cameras
        )

    segmentation = _table(document, "segmentation")
    segment_defaults = SegmentationConfig()
    segmentation_config = SegmentationConfig(
        **{
            name: type(getattr(segment_defaults, name))(segmentation.get(name, value))
            for name, value in vars(segment_defaults).items()
        }
    )

    config = AppConfig(
        data_directory=Path(str(system.get("data_directory", "data/events"))),
        wait_after_close_seconds=float(system.get("wait_after_close_seconds", 0.0)),
        log_level=str(system.get("log_level", "INFO")).upper(),
        simulated_hardware=bool(system.get("simulated_hardware", True)),
        camera_count=int(system.get("camera_count", 1)),
        ml=ml_config,
        door=door_config,
        cameras=camera_configs,
        segmentation=segmentation_config,
    )
    _validate(config)
    return config


def _validate(config: AppConfig) -> None:
    if config.ml.mode not in MODES:
        raise ValueError("ml.mode must be production, acquisition or test")
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
    door = config.door
    if door.gpio_pin is not None and not 0 <= door.gpio_pin <= 27:
        raise ValueError("door.gpio_pin must be a BCM GPIO number from 0 to 27")
    if door.open_level not in {"high", "low"}:
        raise ValueError("door.open_level must be high or low")
    if door.debounce_seconds < 0 or door.poll_interval_seconds <= 0:
        raise ValueError("door timing values must be positive")
    names = [camera.name for camera in config.cameras]
    if not names or len(names) != len(set(names)):
        raise ValueError("configure at least one camera, each with a unique name")
    for camera in config.cameras:
        if camera.kind not in {"rpicam", "v4l2", "simulated"}:
            raise ValueError("camera kind must be rpicam, v4l2 or simulated")
        if min(camera.width, camera.height, camera.fps) < 1:
            raise ValueError("camera width, height and fps must be positive")
    segments = config.segmentation
    numbers = [value for value in vars(segments).values() if not isinstance(value, bool)]
    if any(not math.isfinite(value) or value < 0 for value in numbers):
        raise ValueError("segmentation values must be finite and non-negative")
    if segments.analysis_fps <= 0 or segments.max_recording_seconds <= 0:
        raise ValueError("analysis_fps and max_recording_seconds must be positive")
