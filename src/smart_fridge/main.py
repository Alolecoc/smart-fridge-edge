import argparse
import json
import shutil
import signal
from dataclasses import replace
from pathlib import Path

from smart_fridge.config import load_config
from smart_fridge.hardware.simulated import (
    SimulatedCamera,
    SimulatedDoorSensor,
    SimulatedLighting,
)
from smart_fridge.logging_setup import configure_logging
from smart_fridge.orchestrator import Orchestrator
from smart_fridge.service import MLService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).resolve().parents[2] / "config/default.toml"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--serve",
        action="store_true",
        help="Process queued captures and run cleanup until stopped.",
    )
    action.add_argument("--submit", type=Path, help="Queue an existing RGB image and exit.")
    action.add_argument(
        "--export-acquisition", type=Path, help="Export saved acquisition results for review."
    )
    parser.add_argument("--event-id", help="Door event shared by this event's sensor captures.")
    parser.add_argument("--sensor", default="rgb-1")
    parser.add_argument("--captured-at", help="ISO timestamp with timezone; defaults to now.")
    parser.add_argument("--metadata", type=Path, help="JSON sensor settings to preserve.")
    parser.add_argument(
        "--attachment",
        type=Path,
        action="append",
        default=[],
        help="Copy a synchronized IR/radar raw file; may be repeated.",
    )
    action.add_argument("--capture-id", help="Process this existing pending SQLite capture once.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--data-aquisition", "--data-acquisition", dest="acquisition", action="store_true"
    )
    mode.add_argument("--production", action="store_true")
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    if arguments.acquisition or arguments.production:
        config = replace(
            config,
            ml=replace(config.ml, mode="acquisition" if arguments.acquisition else "production"),
        )
    configure_logging(config.log_level)

    service = MLService(config.ml)
    if arguments.export_acquisition:
        service.database.export_acquisition(arguments.export_acquisition)
        return
    if arguments.submit:
        if not arguments.event_id:
            parser.error("--submit requires --event-id")
        metadata = json.loads(arguments.metadata.read_text()) if arguments.metadata else {}
        if not isinstance(metadata, dict):
            parser.error("--metadata must contain a JSON object")
        print(
            service.database.enqueue(
                event_id=arguments.event_id,
                image=arguments.submit,
                mode=config.ml.mode,
                sensor=arguments.sensor,
                captured_at=arguments.captured_at,
                metadata=metadata,
                attachments=[{"path": str(path.resolve())} for path in arguments.attachment],
            )
        )
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
                while not service.stop_event.is_set():
                    if service.worker.process_one():
                        service.maintain()
                    else:
                        service.stop_event.wait(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            service.stop()
        return

    if not config.simulated_hardware:
        raise RuntimeError("real hardware adapters have not been implemented yet")

    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    cameras = [SimulatedCamera(as_image=config.ml.enabled) for _ in range(config.camera_count)]
    system = Orchestrator(
        door,
        lighting,
        cameras,
        config.ml.database_directory / "staging" if config.ml.enabled else config.data_directory,
        wait_after_close_seconds=config.wait_after_close_seconds,
        capture_suffix=".ppm" if config.ml.enabled else ".txt",
    )

    print("Simulating one door event...")
    door.open = True
    system.poll()
    door.open = False
    result = system.poll()

    if result is not None:
        print(f"Captured event {result.event_id} in {result.event_directory}")
        if config.ml.enabled:
            metadata = json.loads(result.metadata_path.read_text())
            service.start()
            try:
                for index, filename in enumerate(metadata["outputs"]):
                    capture_id = service.database.enqueue(
                        event_id=result.event_id,
                        image=result.event_directory / filename,
                        mode=config.ml.mode,
                        sensor=f"camera-{index + 1}",
                        captured_at=metadata["completed_at"],
                        event_metadata=metadata,
                    )
                    service.worker.process_one(capture_id)
                service.maintain()
                # Raw files have durable managed copies and event metadata is in SQLite.
                # Only this event's temporary staging directory is removed.
                shutil.rmtree(result.event_directory)
            finally:
                service.stop()


if __name__ == "__main__":
    main()
