"""Real Raspberry Pi hardware: a GPIO door switch and rpicam/USB video recorders."""

from __future__ import annotations

import importlib
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from smart_fridge.config import CameraConfig, DoorConfig


class GpioDoorSensor:
    """Read a door switch through gpiozero (python3-gpiozero on Raspberry Pi OS)."""

    def __init__(self, config: DoorConfig) -> None:
        if config.gpio_pin is None:
            raise ValueError(
                "set [door] gpio_pin in the config; use --check-door --pin N to find it"
            )
        gpiozero: Any = importlib.import_module("gpiozero")
        self.open_level = config.open_level
        # Debouncing is done by DebouncedDoor, which also works for simulated doors.
        self.device: Any = gpiozero.DigitalInputDevice(config.gpio_pin, pull_up=config.pull_up)

    def level(self) -> str:
        """The raw electrical level: high or low."""
        # gpiozero's value is the logical value, inverted when the pull-up is active.
        logical = bool(self.device.value)
        high = logical != bool(self.device.pull_up)
        return "high" if high else "low"

    def is_open(self) -> bool:
        return self.level() == self.open_level

    def close(self) -> None:
        self.device.close()


class ProcessRecorder:
    """Record one camera with rpicam-vid (CSI camera) or ffmpeg (USB camera)."""

    def __init__(self, config: CameraConfig) -> None:
        self.name = config.name
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.destination: Path | None = None
        self.log: Any = None

    def command(self, destination: Path) -> list[str]:
        camera = self.config
        if camera.kind == "rpicam":
            executable = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
            if executable is None:
                raise RuntimeError("rpicam-vid is missing; install rpicam-apps")
            return [
                executable,
                "--camera",
                str(camera.index),
                "-t",
                "0",
                "--width",
                str(camera.width),
                "--height",
                str(camera.height),
                "--framerate",
                str(camera.fps),
                "--codec",
                "libav",
                "--nopreview",
                "-o",
                str(destination),
            ]
        if camera.kind == "v4l2":
            executable = shutil.which("ffmpeg")
            if executable is None:
                raise RuntimeError("ffmpeg is missing")
            return [
                executable,
                "-nostdin",
                "-y",
                "-f",
                "v4l2",
                "-framerate",
                str(camera.fps),
                "-video_size",
                f"{camera.width}x{camera.height}",
                "-i",
                camera.device,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ]
        raise ValueError(f"camera kind {camera.kind} cannot record")

    def start(self, destination: Path) -> None:
        if self.process is not None:
            raise RuntimeError(f"{self.name} is already recording")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.log = destination.with_suffix(".log").open("wb")
        self.destination = destination
        self.process = subprocess.Popen(
            self.command(destination), stdout=self.log, stderr=subprocess.STDOUT
        )
        # Fail now, not at door close, if the camera is missing or busy.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._close_log()
                self.process = None
                raise RuntimeError(f"{self.name} camera failed to start; see {self.log.name}")
            time.sleep(0.05)

    def stop(self) -> Path:
        if self.process is None or self.destination is None:
            raise RuntimeError(f"{self.name} is not recording")
        process, destination = self.process, self.destination
        self.process = self.destination = None
        if process.poll() is None:
            # SIGINT lets rpicam-vid and ffmpeg finish the MP4 file properly.
            os.kill(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._close_log()
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(
                f"{self.name} produced no video; see {destination.with_suffix('.log')}"
            )
        return destination

    def _close_log(self) -> None:
        if self.log is not None:
            self.log.close()
