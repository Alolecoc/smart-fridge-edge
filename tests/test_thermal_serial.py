import json
import queue
from pathlib import Path

import pytest

from smart_fridge.config import ThermalConfig
from smart_fridge.hardware.thermal_serial import PROTOCOL_PREFIX, SerialThermalNode


class FakeSerial:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.lines: queue.Queue[bytes] = queue.Queue()
        self.closed = False

    def write(self, encoded: bytes) -> int:
        request = json.loads(encoded.decode().removeprefix(PROTOCOL_PREFIX))
        response = {
            "v": 1,
            "type": {
                "start": "started",
                "stop": "finished",
                "status": "status",
            }[request["command"]],
            "request_id": request["request_id"],
        }
        if "event_id" in request:
            response["event_id"] = request["event_id"]
        if request["command"] == "start":
            self.lines.put((PROTOCOL_PREFIX + json.dumps(response) + "\n").encode())
            frame = {
                "v": 1,
                "type": "frame",
                "event_id": request["event_id"],
                "seq": 0,
            }
            self.lines.put((PROTOCOL_PREFIX + json.dumps(frame) + "\n").encode())
            return len(encoded)
        if request["command"] == "stop":
            response.update({"frames": 1, "dropped": 0})
        if request["command"] == "status":
            response["state"] = "idle"
        self.lines.put((PROTOCOL_PREFIX + json.dumps(response) + "\n").encode())
        return len(encoded)

    def flush(self) -> None:
        return

    def readline(self) -> bytes:
        try:
            return self.lines.get(timeout=0.05)
        except queue.Empty:
            return b""

    def close(self) -> None:
        self.closed = True


def test_serial_node_saves_frames_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSerial()
    monkeypatch.setattr(
        "smart_fridge.hardware.thermal_serial.serial.Serial", lambda *_a, **_k: fake
    )
    node = SerialThermalNode(ThermalConfig(enabled=True, port="COM-test"))
    try:
        node.start("event-1", tmp_path)
        summary = node.stop("event-1")
        assert json.loads(summary.read_text())["frames_received"] == 1
        frame = json.loads((tmp_path / "frames.jsonl").read_text())
        assert frame["event_id"] == "event-1" and frame["seq"] == 0
        assert node.status()["state"] == "idle"
    finally:
        node.close()
    assert fake.closed
