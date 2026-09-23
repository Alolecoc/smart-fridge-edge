from pathlib import Path

from smart_fridge.hardware.simulated import (
    SimulatedCamera,
    SimulatedDoorSensor,
    SimulatedLighting,
)
from smart_fridge.orchestrator import Orchestrator


def main() -> None:
    door = SimulatedDoorSensor()
    lighting = SimulatedLighting()
    camera = SimulatedCamera()
    system = Orchestrator(door, lighting, [camera], Path("data/events"))

    print("Simulating one door event...")
    door.open = True
    system.poll()
    door.open = False
    result = system.poll()

    if result is not None:
        print(f"Captured event {result.event_id} in {result.event_directory}")


if __name__ == "__main__":
    main()
