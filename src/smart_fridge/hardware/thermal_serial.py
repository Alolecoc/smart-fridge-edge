"""USB-serial client for the ESP thermal node."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import serial  # type: ignore[import-untyped]
from serial.tools import list_ports  # type: ignore[import-untyped]

from smart_fridge.config import ThermalConfig

PROTOCOL_PREFIX = "SF1 "


def discover_port(configured: str) -> str:
    """Resolve an explicit port or select one likely USB UART deterministically."""
    if configured != "auto":
        return configured
    candidates = sorted(
        (
            port
            for port in list_ports.comports()
            if port.device.startswith("/dev/ttyUSB")
            or port.device.startswith("/dev/ttyACM")
            or "USB" in (port.description or "").upper()
        ),
        key=lambda port: port.device,
    )
    if not candidates:
        raise RuntimeError("no ESP USB serial port found")
    if len(candidates) > 1:
        names = ", ".join(port.device for port in candidates)
        raise RuntimeError(f"multiple USB serial ports found ({names}); configure thermal.port")
    return str(candidates[0].device)


class SerialThermalNode:
    """Control one ESP node and persist its newline-delimited frame stream."""

    def __init__(self, config: ThermalConfig) -> None:
        self.config = config
        self.port = discover_port(config.port)
        self.logger = logging.getLogger(__name__)
        self.serial = serial.Serial(self.port, config.baudrate, timeout=0.2, write_timeout=1.0)
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_reader = threading.Event()
        self.lock = threading.Lock()
        self.active_event: str | None = None
        self.frames_file: TextIO | None = None
        self.frame_count = 0
        self.dropped = 0
        self._latest_frame: dict[str, Any] | None = None
        self.last_status: dict[str, object] = {"state": "connected", "port": self.port}
        self.reader = threading.Thread(target=self._read_loop, name="thermal-serial", daemon=True)
        self.reader.start()

    def start(self, event_id: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.active_event is not None:
                raise RuntimeError(f"thermal node is already capturing {self.active_event}")
            self.frames_file = (destination / "frames.jsonl").open("w", encoding="utf-8")
            self.active_event = event_id
            self.frame_count = 0
            self.dropped = 0
        try:
            response = self._command(
                "start",
                self.config.start_timeout_seconds,
                event_id=event_id,
                max_duration_ms=round(self.config.max_capture_seconds * 1000),
            )
            if response.get("type") != "started":
                raise RuntimeError(self._response_error(response, "thermal start failed"))
        except BaseException:
            self._close_capture()
            raise
        self.logger.info("thermal capture STARTED on %s", self.port, extra={"event_id": event_id})

    def stop(self, event_id: str) -> Path:
        with self.lock:
            if self.active_event != event_id or self.frames_file is None:
                raise RuntimeError("thermal node is not capturing this event")
            destination = Path(self.frames_file.name).parent
        try:
            response = self._command("stop", self.config.stop_timeout_seconds, event_id=event_id)
            if response.get("type") != "finished":
                raise RuntimeError(self._response_error(response, "thermal stop failed"))
            summary = {
                **response,
                "port": self.port,
                "frames_received": self.frame_count,
                "frames_dropped": self.dropped,
            }
            path = destination / "summary.json"
            path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        finally:
            self._close_capture()
        self.logger.info("thermal capture STOPPED", extra={"event_id": event_id})
        return path

    def status(self) -> dict[str, object]:
        response = self._command("status", self.config.start_timeout_seconds)
        self.last_status = {**response, "port": self.port}
        return self.last_status

    def latest_frame(self) -> dict[str, Any] | None:
        """Return a snapshot of the most recently received thermal frame."""
        with self.lock:
            return dict(self._latest_frame) if self._latest_frame is not None else None

    def close(self) -> None:
        self._close_capture()
        self.stop_reader.set()
        self.reader.join(timeout=1.0)
        self.serial.close()

    def _command(self, command: str, timeout: float, **fields: object) -> dict[str, Any]:
        request_id = uuid4().hex[:12]
        message = {"v": 1, "command": command, "request_id": request_id, **fields}
        encoded = (PROTOCOL_PREFIX + json.dumps(message, separators=(",", ":")) + "\n").encode()
        deadline = time.monotonic() + timeout
        next_write = 0.0
        deferred: list[dict[str, Any]] = []
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                now = time.monotonic()
                if now >= next_write:
                    self.serial.write(encoded)
                    self.serial.flush()
                    next_write = now + 0.5
                try:
                    response = self.responses.get(
                        timeout=min(remaining, max(0.0, next_write - now))
                    )
                except queue.Empty:
                    continue
                if response.get("request_id") == request_id:
                    return response
                deferred.append(response)
        finally:
            for response in deferred:
                self.responses.put(response)
        raise TimeoutError(f"thermal {command} timed out after {timeout:g} s")

    def _read_loop(self) -> None:
        while not self.stop_reader.is_set():
            try:
                raw = self.serial.readline()
            except serial.SerialException:
                self.logger.exception("thermal serial connection failed")
                return
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith(PROTOCOL_PREFIX):
                self.logger.debug("ESP: %s", line)
                continue
            try:
                message = json.loads(line[len(PROTOCOL_PREFIX) :])
            except json.JSONDecodeError:
                self.logger.warning("ignored malformed thermal protocol line")
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "frame":
                self._write_frame(message)
            else:
                self.responses.put(message)

    def _write_frame(self, message: dict[str, Any]) -> None:
        with self.lock:
            if self.frames_file is None or message.get("event_id") != self.active_event:
                self.dropped += 1
                return
            self.frames_file.write(json.dumps(message, separators=(",", ":")) + "\n")
            self.frames_file.flush()
            self._latest_frame = dict(message)
            self.frame_count += 1

    def _close_capture(self) -> None:
        with self.lock:
            if self.frames_file is not None:
                self.frames_file.close()
            self.frames_file = None
            self.active_event = None

    @staticmethod
    def _response_error(response: dict[str, Any], fallback: str) -> str:
        return str(response.get("message") or response.get("code") or fallback)
