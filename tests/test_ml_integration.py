import json
import sqlite3
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from smart_fridge.config import MLConfig, load_config
from smart_fridge.database import Database
from smart_fridge.inference import InferenceWorker
from smart_fridge.service import MLService


def enqueue(database: Database, tmp_path: Path, mode: str = "production") -> str:
    clip = tmp_path / "source.mp4"
    clip.write_bytes(b"video")
    return database.enqueue_video(
        event_id="door-event-1", video=clip, camera="fridge", mode=mode, offset_seconds=1.5
    )


def ml_result(job: dict[str, Any], movements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "capture_id": job["capture_id"],
        "event_id": job["event_id"],
        "mode": job["mode"],
        "camera": "fridge",
        "tracks": [{"id": "1", "category": "milk", "crop_file": "track-1.jpg"}],
        "movements": movements
        if movements is not None
        else [
            {
                "track_id": "1",
                "direction": "in",
                "category": "milk",
                "classification_confidence": 0.8,
                "start": 2.0,
                "end": 3.0,
            }
        ],
        "source": "/somewhere/clip.mp4",
    }


def complete(database: Database, capture_id: str) -> dict[str, Any]:
    job = database.claim(capture_id)
    assert job is not None
    folder = Path(job["artifact_directory"])
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_text("working copy")
    database.complete(job, ml_result(job))
    return job


def test_video_request_and_movements_are_stored(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path)
    job = database.claim(capture)
    assert job is not None
    request = json.loads(job["input_json"])
    assert request["schema_version"] == 2
    assert request["camera"] == "fridge" and request["offset_seconds"] == 1.5
    assert Path(request["video_path"]).read_bytes() == b"video"
    assert (tmp_path / "source.mp4").exists()  # Copied, not moved, by default.
    database.complete(job, ml_result(job))
    with database.connect() as connection:
        movement = connection.execute("SELECT * FROM movements").fetchone()
        assert (movement["direction"], movement["category"], movement["camera"]) == (
            "in",
            "milk",
            "fridge",
        )
        assert movement["event_id"] == "door-event-1"
        status = connection.execute("SELECT status FROM captures").fetchone()[0]
        assert status == "completed"


def test_event_grouping_and_separate_persistent_acquisition(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    first = enqueue(database, tmp_path, "acquisition")
    second = enqueue(database, tmp_path, "acquisition")
    complete(database, first)
    complete(database, second)
    export = tmp_path / "export.json"
    database.export_acquisition(export)
    records = json.loads(export.read_text())["records"]
    assert len(records) == 2
    assert {record["input"]["event_id"] for record in records} == {"door-event-1"}
    assert database.purge(1) == 0
    assert all(Path(record["input"]["video_path"]).is_file() for record in records)


def test_retention_keeps_three_runs_and_keeps_movements(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    acquisition = complete(database, enqueue(database, tmp_path, "acquisition"))
    jobs = [complete(database, enqueue(database, tmp_path)) for _ in range(3)]
    jobs += [complete(database, enqueue(database, tmp_path, "test")) for _ in range(2)]
    pending = enqueue(database, tmp_path)
    failed = database.claim(enqueue(database, tmp_path))
    assert failed is not None
    database.fail(failed, "deliberate failure")
    assert database.purge(3) == 2
    assert database.purge(3) == 0
    assert not Path(jobs[0]["artifact_directory"]).exists()
    assert all(Path(job["artifact_directory"]).exists() for job in jobs[2:])
    assert Path(acquisition["artifact_directory"]).exists()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM movements").fetchone()[0] == 6
        result = json.loads(
            connection.execute(
                "SELECT result_json FROM predictions WHERE run_id = ?", (jobs[0]["run_id"],)
            ).fetchone()[0]
        )
        assert result["artifacts_purged"] and "source" not in result
        assert result["tracks"] == [{"id": "1", "category": "milk"}]
        assert result["movements"][0]["category"] == "milk"
        assert (
            connection.execute(
                "SELECT status FROM captures WHERE capture_id = ?", (pending,)
            ).fetchone()[0]
            == "pending"
        )


def test_claim_is_exclusive_and_results_are_validated(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path)
    job = database.claim(capture)
    assert job is not None
    assert Database(database.root).claim(capture) is None
    with pytest.raises(ValueError, match="event_id"):
        database.complete(job, {**ml_result(job), "event_id": "wrong"})
    with pytest.raises(ValueError, match="movement"):
        database.complete(job, ml_result(job, [{"direction": "sideways", "category": "x"}]))
    with pytest.raises(ValueError, match="schema"):
        database.complete(job, {**ml_result(job), "schema_version": 1})
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


FAKE_ML = (
    "import json, sys\nfrom pathlib import Path\n"
    "args = sys.argv\n"
    "request = json.loads(Path(args[args.index('--request') + 1]).read_text())\n"
    "assert request['capture_id'] == args[args.index('--record-id') + 1]\n"
    "assert '--managed-retention' in args\n"
    "flags = {'--data-aquisition': 'acquisition', '--test': 'test', '--production': 'production'}\n"
    "request['mode'] = next(mode for flag, mode in flags.items() if flag in args)\n"
    "request['tracks'] = []\n"
    "request['movements'] = [{'direction': 'out', 'category': 'apple', 'start': 1, 'end': 2}]\n"
    "Path(args[args.index('--output') + 1]).write_text(json.dumps(request))\n"
)


@pytest.mark.parametrize("mode", ["acquisition", "test", "production"])
def test_subprocess_contract_for_every_mode(tmp_path: Path, mode: str) -> None:
    repository = tmp_path / "ml repo with spaces"
    repository.mkdir()
    (repository / "main.py").write_text(FAKE_ML)
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path, mode)
    config = MLConfig(enabled=True, python=Path(sys.executable), repository=repository)
    worker = InferenceWorker(database, config)
    assert worker.process_one(capture)
    assert not worker.process_one(capture)
    with database.connect() as connection:
        row = connection.execute("SELECT category, direction FROM movements").fetchone()
        assert tuple(row) == ("apple", "out")
        acquisition = connection.execute("SELECT COUNT(*) FROM acquisition_records").fetchone()
        assert acquisition[0] == (1 if mode == "acquisition" else 0)


def test_process_failure_is_recorded_without_losing_capture(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path)
    worker = InferenceWorker(
        database, MLConfig(enabled=True, repository=tmp_path, python=Path(sys.executable))
    )
    assert worker.process_one(capture)
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM captures").fetchone()
        assert row["status"] == "failed"
        assert Path(json.loads(row["input_json"])["video_path"]).exists()
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_version_1_database_is_migrated_for_test_mode(tmp_path: Path) -> None:
    folder = tmp_path / "database"
    folder.mkdir()
    with sqlite3.connect(folder / "fridge.sqlite3") as connection:
        connection.executescript("""
            CREATE TABLE events (event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL);
            CREATE TABLE captures (capture_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES events(event_id),
                mode TEXT NOT NULL CHECK(mode IN ('production', 'acquisition')),
                captured_at TEXT NOT NULL, created_at TEXT NOT NULL, input_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT, purged_at TEXT);
            INSERT INTO events VALUES ('old', '2026-10-05', '{}');
            INSERT INTO captures VALUES ('c1', 'old', 'production', '2026-10-05T00:00:00+00:00',
                '2026-10-05', '{}', 'completed', NULL, NULL);
        """)
    database = Database(folder)
    enqueue(database, tmp_path, "test")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 2
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_recovery_and_background_service_shutdown(tmp_path: Path) -> None:
    config = MLConfig(database_directory=tmp_path / "database", purge_interval_seconds=0.01)
    service = MLService(config)
    capture = enqueue(service.database, tmp_path)
    service.database.claim(capture)
    future = datetime.now(UTC) + timedelta(seconds=1)
    service.database.recover(future.isoformat())
    service.start()
    service.stop()
    assert not service.thread.is_alive()
    with service.database.connect() as connection:
        assert connection.execute("SELECT status FROM captures").fetchone()[0] == "failed"


def test_purge_refuses_symlinked_managed_directory(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    first = complete(database, enqueue(database, tmp_path))
    complete(database, enqueue(database, tmp_path))
    directory = Path(first["artifact_directory"])
    (directory / "video.mp4").unlink()
    directory.rmdir()
    external = tmp_path / "do-not-delete"
    external.mkdir()
    (external / "important").write_text("keep")
    directory.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="outside managed"):
        database.purge(1)
    assert (external / "important").read_text() == "keep"


def test_ml_config_paths_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "config" / "settings.toml"
    path.parent.mkdir()
    path.write_text('[system]\n[ml]\nrepository="../models-project"\nretention_runs=0')
    with pytest.raises(ValueError, match="retention_runs"):
        load_config(path)
    path.write_text('[system]\n[ml]\nrepository="ml"\nmode="test"\npython="venv/bin/python"\n')
    (tmp_path / "venv/bin").mkdir(parents=True)
    (tmp_path / "venv/bin/python").symlink_to(sys.executable)
    config = load_config(path)
    assert config.ml.repository == tmp_path / "ml"
    assert config.ml.python == tmp_path / "venv/bin/python"  # The venv link is kept.
    assert config.ml.mode == "test"
    service = MLService(replace(config.ml, database_directory=tmp_path / "database"))
    assert not service.worker.process_one()
