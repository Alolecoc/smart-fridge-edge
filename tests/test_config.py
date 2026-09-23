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
