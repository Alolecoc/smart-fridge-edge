from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RpiCamera:
    """Capture still images through Raspberry Pi's rpicam-still command."""

    camera_index: int
    width: int = 2304
    height: int = 1296
    capture_delay_ms: int = 2000
    command_timeout_seconds: float = 20.0

    @property
    def file_extension(self) -> str:
        return ".jpg"

    def capture(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "rpicam-still",
            "--camera",
            str(self.camera_index),
            "--nopreview",
            "--timeout",
            str(self.capture_delay_ms),
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--output",
            str(destination),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                timeout=self.command_timeout_seconds,
            )
        except FileNotFoundError as error:
            raise RuntimeError("rpicam-still is not installed or not available on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"camera {self.camera_index} timed out after {self.command_timeout_seconds} seconds"
            ) from error
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"camera {self.camera_index} capture failed with exit code {error.returncode}"
            ) from error

        if not destination.is_file():
            raise RuntimeError(
                f"camera {self.camera_index} completed without creating {destination}"
            )
