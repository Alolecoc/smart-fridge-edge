"""Small dependency-free browser viewer for live thermal frames."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from smart_fridge.config import ThermalConfig
from smart_fridge.hardware.thermal_serial import SerialThermalNode

LIVE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smart Fridge thermal live</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #07111f; color: #eef6ff; }
    main { width: min(94vw, 980px); margin: 30px auto; }
    h1 { margin-bottom: 5px; }
    .sub { color: #9bb0c8; margin-top: 0; }
    canvas { width: 100%; aspect-ratio: 4 / 3; image-rendering: pixelated;
      background: #020713; border: 1px solid #29415d; border-radius: 14px; }
    .panel { display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
      padding: 16px 0; }
    .stat { min-width: 120px; }
    .value { font-size: 1.35rem; font-weight: 700; }
    label { color: #b8c9dc; }
    input[type=number] { width: 65px; padding: 5px; background: #10233a;
      color: white; border: 1px solid #35506d; border-radius: 6px; }
    #status { color: #7dd3fc; }
    .scale { height: 16px; border-radius: 8px;
      background: linear-gradient(90deg, rgb(0,40,255), rgb(0,220,255),
      rgb(255,235,0), rgb(255,100,0), rgb(255,0,0)); }
  </style>
</head>
<body><main>
  <h1>Thermal camera · live</h1>
  <p class="sub">Blue is cold, red is hot. The circle shows the detected warm-region centre.</p>
  <canvas id="view" width="32" height="24"></canvas>
  <div class="scale"></div>
  <div class="panel">
    <div class="stat"><label>Minimum</label><div class="value" id="min">–</div></div>
    <div class="stat"><label>Mean</label><div class="value" id="mean">–</div></div>
    <div class="stat"><label>Maximum</label><div class="value" id="max">–</div></div>
    <div class="stat"><label>Frame</label><div class="value" id="seq">–</div></div>
    <label><input id="auto" type="checkbox" checked> automatic scale</label>
    <label>cold <input id="low" type="number" value="10" step="1"> °C</label>
    <label>hot <input id="high" type="number" value="40" step="1"> °C</label>
  </div>
  <p id="status">Waiting for the first frame…</p>
</main>
<script>
const canvas = document.getElementById('view');
const context = canvas.getContext('2d');
const image = context.createImageData(32, 24);
let previousSequence = -1;

function colour(value) {
  const stops = [[0,[0,40,255]],[.25,[0,220,255]],[.5,[255,235,0]],
                 [.75,[255,100,0]],[1,[255,0,0]]];
  const t = Math.max(0, Math.min(1, value));
  for (let index = 1; index < stops.length; index++) {
    if (t <= stops[index][0]) {
      const [leftT, left] = stops[index - 1];
      const [rightT, right] = stops[index];
      const mix = (t - leftT) / (rightT - leftT);
      return left.map((channel, i) => Math.round(channel + (right[i] - channel) * mix));
    }
  }
  return stops.at(-1)[1];
}

function draw(frame) {
  const temperatures = frame.raw_u16.map(raw => raw / 128 - 64);
  const automatic = document.getElementById('auto').checked;
  const low = automatic ? frame.min_c : Number(document.getElementById('low').value);
  const high = automatic ? frame.max_c : Number(document.getElementById('high').value);
  temperatures.forEach((temperature, index) => {
    const rgb = colour((temperature - low) / Math.max(.01, high - low));
    image.data.set([...rgb, 255], index * 4);
  });
  context.putImageData(image, 0, 0);
  if (frame.hand && frame.centroid_x >= 0) {
    context.beginPath();
    context.arc(frame.centroid_x, frame.centroid_y, 2, 0, Math.PI * 2);
    context.strokeStyle = 'white';
    context.lineWidth = .35;
    context.stroke();
  }
  document.getElementById('min').textContent = frame.min_c.toFixed(1) + ' °C';
  document.getElementById('mean').textContent = frame.mean_c.toFixed(1) + ' °C';
  document.getElementById('max').textContent = frame.max_c.toFixed(1) + ' °C';
  document.getElementById('seq').textContent = frame.seq;
  document.getElementById('status').textContent =
    frame.hand ? `Warm region detected · ${frame.area} pixels` : 'No warm region detected';
  previousSequence = frame.seq;
}

async function update() {
  try {
    const response = await fetch('/api/frame', {cache: 'no-store'});
    if (response.status === 200) {
      const frame = await response.json();
      if (frame.seq !== previousSequence) draw(frame);
    }
  } catch (_) {
    document.getElementById('status').textContent = 'Connection lost; retrying…';
  }
  setTimeout(update, 150);
}
update();
</script></body></html>
"""


class ThermalLiveServer(ThreadingHTTPServer):
    """HTTP server carrying the thermal node used by request handlers."""

    daemon_threads = True

    def __init__(
        self, address: tuple[str, int], node: SerialThermalNode, page: str = LIVE_PAGE
    ) -> None:
        super().__init__(address, ThermalLiveHandler)
        self.node = node
        self.page = page.encode("utf-8")


class ThermalLiveHandler(BaseHTTPRequestHandler):
    """Serve the viewer and its latest-frame endpoint."""

    server: ThermalLiveServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", self.server.page)
            return
        if self.path == "/api/frame":
            frame = self.server.node.latest_frame()
            if frame is None:
                self._send(204, "application/json", b"")
            else:
                self._send(
                    200,
                    "application/json",
                    json.dumps(frame, separators=(",", ":")).encode("utf-8"),
                )
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run_thermal_live(config: ThermalConfig, host: str, port: int) -> None:
    """Capture thermal frames and expose the latest one until interrupted."""
    if not config.enabled:
        raise SystemExit("thermal is disabled in the selected configuration")
    node = SerialThermalNode(config)
    event_id = f"thermal-live-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    with tempfile.TemporaryDirectory(prefix="smart-fridge-thermal-live-") as directory:
        try:
            node.status()
            node.start(event_id, Path(directory))
            server = ThermalLiveServer((host, port), node)
            print(f"Thermal live viewer: http://smartfridge:{port}")
            print("Press Ctrl+C to stop.")
            try:
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
                node.stop(event_id)
        finally:
            node.close()
