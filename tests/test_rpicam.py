from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from smart_fridge.hardware.rpicam import RpiCamera


def test_capture_calls_rpicam_still(tmp_path: Path) -> None:
    output = tmp_path / "camera.jpg"

    def create_output(command: list[str], **_: object) -> Mock:
        output.write_bytes(b"jpeg")
        assert command == [
            "rpicam-still",
            "--camera",
            "1",
            "--nopreview",
            "--timeout",
            "1500",
            "--width",
            "2304",
            "--height",
            "1296",
            "--output",
            str(output),
        ]
        return Mock(returncode=0)

    camera = RpiCamera(camera_index=1, capture_delay_ms=1500)
    with patch("smart_fridge.hardware.rpicam.subprocess.run", side_effect=create_output) as run:
        camera.capture(output)

    run.assert_called_once_with(
        run.call_args.args[0],
        check=True,
        timeout=20.0,
    )


def test_capture_requires_output_file(tmp_path: Path) -> None:
    camera = RpiCamera(camera_index=0)

    with (
        patch("smart_fridge.hardware.rpicam.subprocess.run"),
        pytest.raises(RuntimeError, match="without creating"),
    ):
        camera.capture(tmp_path / "missing.jpg")
