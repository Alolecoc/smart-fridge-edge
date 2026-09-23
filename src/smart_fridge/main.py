import argparse
from pathlib import Path

from smart_fridge.config import load_config
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

    if not config.simulated_hardware:
        raise RuntimeError("real hardware adapters have not been implemented yet")

    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    cameras = [SimulatedCamera() for _ in range(config.camera_count)]
    system = Orchestrator(
        door,
        lighting,
        cameras,
        config.data_directory,
        wait_after_close_seconds=config.wait_after_close_seconds,
    )

    print("Simulating one door event...")
    door.open = True
    system.poll()
    door.open = False
    result = system.poll()

    if result is not None:
        print(f"Captured event {result.event_id} in {result.event_directory}")


if __name__ == "__main__":
    main()
