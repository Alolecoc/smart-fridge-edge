import argparse
import logging
import queue
import signal
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from smart_fridge.config import AppConfig, load_config
from smart_fridge.events import EventProcessor
from smart_fridge.hardware.interfaces import DoorSensor, VideoRecorder
from smart_fridge.hardware.simulated import (
    SimulatedDoorSensor,
    SimulatedLighting,
    SimulatedRecorder,
)
from smart_fridge.logging_setup import configure_logging
from smart_fridge.orchestrator import DebouncedDoor, EventResult, Orchestrator, Recording
from smart_fridge.segmentation import find_segments, motion_samples, video_duration
from smart_fridge.service import MLService


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart fridge edge orchestrator.")
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).resolve().parents[2] / "config/default.toml"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--run",
        action="store_true",
        help="Live system: record while the door is open, segment, queue and run ML.",
    )
    action.add_argument(
        "--serve", action="store_true", help="Only process queued segments and run cleanup."
    )
    action.add_argument(
        "--submit", type=Path, help="Segment and queue an existing clip, as after a door event."
    )
    action.add_argument("--capture-id", help="Process this existing pending capture once.")
    action.add_argument(
        "--export-acquisition", type=Path, help="Export saved acquisition results for review."
    )
    action.add_argument(
        "--check-door", action="store_true", help="Print the door switch level live."
    )
    action.add_argument(
        "--check-cameras", action="store_true", help="Record 3 s from every camera."
    )
    action.add_argument(
        "--analyse-motion", type=Path, help="Print motion levels and segments of a clip."
    )
    parser.add_argument("--event-id", help="Door event for --submit.")
    parser.add_argument("--camera", help="Camera name for --submit (fridge or door).")
    parser.add_argument("--pin", type=int, help="BCM GPIO pin for --check-door.")
    parser.add_argument("--seconds", type=float, default=60.0, help="Duration of --check-door.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--data-aquisition", "--data-acquisition", dest="acquisition", action="store_true"
    )
    mode.add_argument("--production", action="store_true")
    mode.add_argument(
        "--test",
        action="store_true",
        help="Production, and every clip and prediction is also shown in the review tool.",
    )
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    if arguments.acquisition or arguments.production or arguments.test:
        selected = (
            "acquisition" if arguments.acquisition else "test" if arguments.test else "production"
        )
        config = replace(config, ml=replace(config.ml, mode=selected))
    configure_logging(config.log_level)

    if arguments.check_door:
        check_door(config, arguments.pin, arguments.seconds)
        return
    if arguments.check_cameras:
        check_cameras(config)
        return
    if arguments.analyse_motion:
        analyse_motion(config, arguments.analyse_motion)
        return

    service = MLService(config.ml)
    if arguments.export_acquisition:
        service.database.export_acquisition(arguments.export_acquisition)
        return
    if arguments.submit:
        if not arguments.camera:
            parser.error("--submit requires --camera")
        submit(config, service, arguments.submit, arguments.camera, arguments.event_id)
        return
    if arguments.run:
        if not config.ml.enabled:
            parser.error("--run needs [ml] enabled, for example --config config/pi.toml")
        run_live(config, service)
        return
    if arguments.serve or arguments.capture_id:
        if not config.ml.enabled:
            parser.error("enable [ml] or use --config config/ml.toml")
        service.start()
        signal.signal(signal.SIGTERM, lambda *_: service.stop_event.set())
        try:
            if arguments.capture_id:
                if not service.worker.process_one(arguments.capture_id):
                    parser.error("capture is not pending or does not exist")
                service.maintain()
                with service.database.connect() as connection:
                    status = connection.execute(
                        "SELECT status FROM captures WHERE capture_id = ?",
                        (arguments.capture_id,),
                    ).fetchone()[0]
                if status != "completed":
                    raise SystemExit(1)
            else:
                service.process_queue()
        except KeyboardInterrupt:
            pass
        finally:
            service.stop()
        return
    simulate_one_event(config)


def make_hardware(config: AppConfig) -> tuple[DoorSensor, list[VideoRecorder]]:
    """Real GPIO door and cameras on the Pi, or simulated ones for development."""
    if config.simulated_hardware:
        return SimulatedDoorSensor(), [SimulatedRecorder(name=c.name) for c in config.cameras]
    from smart_fridge.hardware.raspberry_pi import GpioDoorSensor, ProcessRecorder

    return GpioDoorSensor(config.door), [ProcessRecorder(camera) for camera in config.cameras]


def run_live(
    config: AppConfig,
    service: MLService,
    hardware: tuple[DoorSensor, list[VideoRecorder]] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Door loop in the main thread; segmentation and ML run in background threads."""
    logger = logging.getLogger("smart_fridge.live")
    if hardware is None:
        if config.simulated_hardware:
            raise SystemExit("--run needs real hardware: set simulated_hardware = false")
        hardware = make_hardware(config)
    raw_door, recorders = hardware
    door = DebouncedDoor(raw_door, config.door.debounce_seconds)
    system = Orchestrator(
        door,
        SimulatedLighting(),  # No controllable lighting is installed yet.
        recorders,
        config.ml.database_directory / "staging",
        wait_after_close_seconds=config.wait_after_close_seconds,
        max_recording_seconds=config.segmentation.max_recording_seconds,
    )
    processor = EventProcessor(service.database, config.segmentation, config.ml.mode)
    events: queue.Queue[EventResult | None] = queue.Queue()

    def process_events() -> None:
        while (event := events.get()) is not None:
            try:
                processor.process(event)
            except Exception:
                logger.exception("event %s could not be processed", event.event_id)

    service.start()
    segmentation = threading.Thread(target=process_events, name="segmentation", daemon=True)
    ml_queue = threading.Thread(target=service.process_queue, name="ml-queue", daemon=True)
    segmentation.start()
    ml_queue.start()
    if stop is None:
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set() if stop else None)
    logger.info(
        "live in %s mode with cameras %s; waiting for the door",
        config.ml.mode,
        ", ".join(recorder.name for recorder in recorders),
    )
    try:
        while not stop.is_set():
            try:
                result = system.poll()
                if result is not None:
                    events.put(result)
            except Exception:
                logger.exception("door event failed; waiting for the door to close")
                system.reset()
            stop.wait(config.door.poll_interval_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        # Close files cleanly if the service stops with the door open.
        if system.active:
            events.put(system.finish("service stopped"))
        events.put(None)
        segmentation.join()
        service.stop_event.set()
        ml_queue.join()
        service.stop()


def submit(
    config: AppConfig, service: MLService, clip: Path, camera: str, event_id: str | None
) -> None:
    """Treat an existing clip as one camera's recording of a door event."""
    if camera not in {c.name for c in config.cameras}:
        raise SystemExit(f"--camera must be one of {[c.name for c in config.cameras]}")
    opened = datetime.now(UTC)
    event_id = event_id or f"{opened:%Y%m%dT%H%M%SZ}-submitted"
    staging = config.ml.database_directory / "staging" / f"{event_id}-submit"
    staging.mkdir(parents=True, exist_ok=False)
    metadata = staging / "metadata.json"
    metadata.write_text(
        f'{{"event_id": "{event_id}", "door_opened_at": "{opened.isoformat()}", '
        f'"submitted_file": "{clip.name}"}}\n',
        encoding="utf-8",
    )
    event = EventResult(
        event_id=event_id,
        event_directory=staging,
        metadata_path=metadata,
        door_opened_at=opened,
        door_closed_at=opened,
        recordings=(Recording(camera, clip.resolve(), opened),),
    )
    processor = EventProcessor(service.database, config.segmentation, config.ml.mode)
    for capture_id in processor.process(event, keep_sources=True):
        print(capture_id)


def check_door(config: AppConfig, pin: int | None, seconds: float) -> None:
    """Show the raw level so the pin and open_level can be set correctly."""
    from smart_fridge.hardware.raspberry_pi import GpioDoorSensor

    door_config = replace(config.door, gpio_pin=pin if pin is not None else config.door.gpio_pin)
    sensor = GpioDoorSensor(door_config)
    print(
        f"GPIO{door_config.gpio_pin}, pull_up={door_config.pull_up}. "
        f"Open and close the door; open_level is currently '{door_config.open_level}'."
    )
    last = ""
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            level = sensor.level()
            if level != last:
                state = "OPEN" if level == door_config.open_level else "closed"
                print(f"{datetime.now():%H:%M:%S.%f}"[:-3], f"level={level} -> door {state}")
                last = level
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()


def check_cameras(config: AppConfig) -> None:
    """Record a short clip from each camera and report what was saved."""
    _, recorders = make_hardware(config)
    folder = config.ml.database_directory / "camera-check"
    folder.mkdir(parents=True, exist_ok=True)
    failures = 0
    for recorder in recorders:
        try:
            recorder.start(folder / f"{recorder.name}.mp4")
            time.sleep(3)
            path = recorder.stop()
            print(f"{recorder.name}: OK, {video_duration(path):.1f} s saved to {path}")
        except Exception as error:
            failures += 1
            print(f"{recorder.name}: FAILED - {error}")
    if failures:
        raise SystemExit(1)


def analyse_motion(config: AppConfig, clip: Path) -> None:
    """Help choose [segmentation] motion_threshold from a real recording."""
    settings = config.segmentation
    samples = motion_samples(clip, settings.analysis_fps)
    duration = video_duration(clip)
    for time_point, value in samples:
        bar = "#" * min(60, int(value * 4))
        marker = " <" if value >= settings.motion_threshold else ""
        print(f"{time_point:7.2f} s {value:7.2f} {bar}{marker}")
    print(
        f"threshold {settings.motion_threshold}: segments",
        find_segments(samples, duration, settings),
    )


def simulate_one_event(config: AppConfig) -> None:
    """Development demo without hardware: one door event with placeholder recordings."""
    door = SimulatedDoorSensor()
    recorders = [SimulatedRecorder(name=camera.name) for camera in config.cameras]
    system = Orchestrator(door, SimulatedLighting(), recorders, config.data_directory)
    print("Simulating one door event...")
    door.open = True
    system.poll()
    door.open = False
    result = system.poll()
    if result is not None:
        print(f"Recorded event {result.event_id} in {result.event_directory}")
        print("Use --submit clip.mp4 --camera fridge to run a real clip through the ML chain.")


if __name__ == "__main__":
    main()
