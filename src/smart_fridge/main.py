import argparse
import time
from pathlib import Path

from smart_fridge.config import load_config
from smart_fridge.hardware.gpio_door import GpioDoorSensor
from smart_fridge.hardware.interfaces import Camera, DoorSensor
from smart_fridge.hardware.rpicam import RpiCamera
from smart_fridge.hardware.simulated import (
    SimulatedCamera,
    SimulatedDoorSensor,
    SimulatedLighting,
)
from smart_fridge.logging_setup import configure_logging
from smart_fridge.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    configure_logging(config.log_level)

    real_door: GpioDoorSensor | None = None
    door: DoorSensor
    if config.door_backend == "gpio":
        real_door = GpioDoorSensor(
            config.door_gpio_pin,
            bounce_time_seconds=config.door_bounce_time_seconds,
        )
        door = real_door
    else:
        door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    cameras: list[Camera]
    if config.camera_backend == "rpicam":
        cameras = [
            RpiCamera(
                camera_index=index,
                width=config.camera_width,
                height=config.camera_height,
                capture_delay_ms=config.camera_capture_delay_ms,
            )
            for index in config.camera_indices
        ]
    else:
        cameras = [SimulatedCamera() for _ in range(config.camera_count)]
    system = Orchestrator(
        door,
        lighting,
        cameras,
        config.data_directory,
        wait_after_close_seconds=config.wait_after_close_seconds,
    )

    if isinstance(door, SimulatedDoorSensor):
        print("Simulating one door event...")
        door.open = True
        system.poll()
        door.open = False
        result = system.poll()
        if result is not None:
            print(f"Captured event {result.event_id} in {result.event_directory}")
        return

    print(f"Monitoring door switch on GPIO {config.door_gpio_pin}; press Ctrl+C to stop.")
    try:
        while True:
            result = system.poll()
            if result is not None:
                print(f"Captured event {result.event_id} in {result.event_directory}")
            time.sleep(config.door_poll_interval_seconds)
    except KeyboardInterrupt:
        print("Stopping door monitoring.")
    finally:
        if real_door is not None:
            real_door.close()


if __name__ == "__main__":
    main()
