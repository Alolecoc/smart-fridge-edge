# Thermal node integration

The thermal node is an ESP32-P4 connected to one M5Stack Thermal2 over I2C. It
streams 32x24 thermal frames to the Raspberry Pi over the same USB cable that
powers and flashes it.

## Event flow

1. The magnetic switch reports that the refrigerator door opened.
2. The orchestrator starts every RGB recorder and sends `start` with the same
   event ID to the thermal node.
3. The Pi saves incoming thermal frames to `thermal/frames.jsonl` while the RGB
   cameras record.
4. When the debounced door state closes, the orchestrator stops the RGB cameras
   and thermal node concurrently.
5. `thermal/summary.json` records frame counts and communication status.
6. Thermal files are copied into the managed capture as ML attachments before
   the staging directory is removed.

A missing or failed thermal node is non-fatal. The event continues with RGB and
is marked `partial` in its metadata so the failure remains visible.

## Raspberry Pi connection

Connect the ESP32-P4 USB-C data port to a Raspberry Pi USB-A port with a data
cable. Use a stable device path when possible:

```bash
ls -l /dev/serial/by-id/
```

Set that path under `[thermal]` in `config/pi.toml`. `port = "auto"` works only
when exactly one USB serial device is present.

```toml
[thermal]
enabled = true
port = "auto"
baudrate = 460800
start_timeout_seconds = 2.0
stop_timeout_seconds = 5.0
max_capture_seconds = 300.0
```

The service user must belong to `dialout`. After installation, stop the live
service before running the standalone port check:

```bash
smartfridge stop
smartfridge check thermal
```

## Serial protocol

Each machine-readable line begins with `SF1 ` followed by one compact JSON
object. The prefix lets the Pi ignore ESP boot messages sharing the UART.

Pi commands are `ping`, `status`, `start`, and `stop`. Each includes a unique
`request_id`; capture commands also include the shared `event_id`. Frames contain
elapsed microseconds, summary temperatures, a simple warm-region estimate, and
all 768 raw sensor values. The Pi retries commands during the timeout window so
an ESP that has just rebooted does not lose the first request.

## Files delivered to ML

Each managed capture request includes:

```text
attachments/
  frames.jsonl
  summary.json
```

The request JSON also includes the parsed summary under
`sensor_metadata.thermal`. RGB remains the primary input; thermal frames can be
aligned with video using their event ID and elapsed timestamps.
