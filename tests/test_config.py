from pathlib import Path

import pytest

from smart_fridge.config import load_config


def test_load_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[system]
data_directory = "measurements"
wait_after_close_seconds = 1.25
log_level = "debug"
simulated_hardware = true
camera_count = 2
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.data_directory == Path("measurements")
    assert config.wait_after_close_seconds == 1.25
    assert config.log_level == "DEBUG"
    assert config.simulated_hardware is True
    assert config.camera_count == 2


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("wait_after_close_seconds = -1", "cannot be negative"),
        ("camera_count = 0", "at least 1"),
        ('log_level = "VERBOSE"', "unsupported log level"),
    ],
)
def test_reject_invalid_config(tmp_path: Path, setting: str, message: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(f"[system]\n{setting}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_pi_hardware_sections(tmp_path: Path) -> None:
    path = tmp_path / "pi.toml"
    path.write_text(
        """
[system]
simulated_hardware = false
[door]
gpio_pin = 17
open_level = "LOW"
[cameras.fridge]
index = 0
[cameras.door]
kind = "v4l2"
device = "/dev/video2"
[segmentation]
motion_threshold = 2.5
whole_clip_without_motion = false
""".strip(),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.door.gpio_pin == 17 and config.door.open_level == "low"
    assert [camera.name for camera in config.cameras] == ["fridge", "door"]
    assert config.cameras[1].kind == "v4l2" and config.cameras[1].device == "/dev/video2"
    assert config.segmentation.motion_threshold == 2.5
    assert config.segmentation.whole_clip_without_motion is False


def test_repository_configs_are_valid() -> None:
    root = Path(__file__).resolve().parents[1] / "config"
    for name in ("default.toml", "ml.toml", "pi.toml"):
        load_config(root / name)
    pi = load_config(root / "pi.toml")
    assert pi.door.gpio_pin == 17  # The door switch on the fridge.
    assert [camera.name for camera in pi.cameras] == ["fridge", "door"]


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("[door]\ngpio_pin = 40", "BCM GPIO"),
        ('[door]\nopen_level = "sideways"', "open_level"),
        ('[cameras.fridge]\nkind = "webcam"', "camera kind"),
        ("[segmentation]\nmotion_threshold = -1", "segmentation"),
        ('[ml]\nmode = "demo"', "ml.mode"),
    ],
)
def test_reject_invalid_hardware_config(tmp_path: Path, setting: str, message: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(f"[system]\n{setting}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_config(path)
