from scripts.check_commit_message import is_valid


def test_valid_conventional_commit_messages() -> None:
    assert is_valid("feat(orchestrator): add door-event state machine")
    assert is_valid("fix: handle camera timeout")
    assert is_valid("refactor(sensor-api)!: change capture contract")


def test_invalid_commit_messages() -> None:
    assert not is_valid("updated files")
    assert not is_valid("Fix: use an unsupported uppercase type")
    assert not is_valid("feat: Uppercase description")
