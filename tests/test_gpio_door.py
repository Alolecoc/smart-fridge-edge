from dataclasses import dataclass

from smart_fridge.hardware.gpio_door import GpioDoorSensor


@dataclass
class FakeSwitch:
    is_pressed: bool
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def test_magnet_near_means_door_closed() -> None:
    switch = FakeSwitch(is_pressed=True)
    sensor = GpioDoorSensor(17, switch=switch)

    assert sensor.is_open() is False


def test_magnet_away_means_door_open() -> None:
    switch = FakeSwitch(is_pressed=False)
    sensor = GpioDoorSensor(17, switch=switch)

    assert sensor.is_open() is True


def test_close_releases_gpio_resources() -> None:
    switch = FakeSwitch(is_pressed=True)
    sensor = GpioDoorSensor(17, switch=switch)

    sensor.close()

    assert switch.closed is True
