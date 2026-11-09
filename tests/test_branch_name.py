from scripts.check_branch_name import is_valid


def test_valid_branch_names() -> None:
    assert is_valid("main")
    assert is_valid("prod")
    assert is_valid("fix/door-sensor")
    assert is_valid("feat/camera-capture")
    assert is_valid("experiment/radar-placement")


def test_invalid_branch_names() -> None:
    assert not is_valid("new-stuff")
    assert not is_valid("feature/camera")
    assert not is_valid("fix/DoorSensor")
    assert not is_valid("fix/door_sensor")
