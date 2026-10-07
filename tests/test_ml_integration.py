import json
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
    image = tmp_path / "source.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    return database.enqueue(event_id="door-event-1", image=image, mode=mode)


def complete(database: Database, capture_id: str) -> dict[str, Any]:
    job = database.claim(capture_id)
    assert job is not None
    folder = Path(job["artifact_directory"])
    folder.mkdir(parents=True)
    (folder / "mask.json").write_text("{}")
    result = {
        "schema_version": 1,
        "capture_id": capture_id,
        "event_id": job["event_id"],
        "mode": job["mode"],
        "objects": [{"category": "milk", "polygon": [[0, 0]]}],
    }
    database.complete(job, result)
    return job


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
    assert len({record["input"]["capture_id"] for record in records}) == 2
    assert database.purge(1) == 0
    assert all(Path(record["input"]["image_path"]).is_file() for record in records)


def test_retention_keeps_three_successful_runs_and_never_deletes_sources(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    acquisition = complete(database, enqueue(database, tmp_path, "acquisition"))
    jobs = [complete(database, enqueue(database, tmp_path)) for _ in range(5)]
    pending = enqueue(database, tmp_path)
    failed = database.claim(enqueue(database, tmp_path))
    assert failed is not None
    database.fail(failed, "deliberate failure")
    assert database.purge(3) == 2
    assert database.purge(3) == 0
    assert not Path(jobs[0]["artifact_directory"]).exists()
    assert all(Path(job["artifact_directory"]).exists() for job in jobs[2:])
    assert Path(acquisition["artifact_directory"]).exists()
    assert (tmp_path / "source.ppm").exists()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 6
        result = json.loads(
            connection.execute(
                "SELECT result_json FROM predictions WHERE run_id = ?", (jobs[0]["run_id"],)
            ).fetchone()[0]
        )
        assert result["objects"] == [{"category": "milk"}]
        assert result["artifacts_purged"]
        assert (
            connection.execute(
                "SELECT status FROM captures WHERE capture_id = ?", (pending,)
            ).fetchone()[0]
            == "pending"
        )


def test_claim_is_exclusive_and_result_ids_must_match(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path)
    job = database.claim(capture)
    assert job is not None
    assert Database(database.root).claim(capture) is None
    with pytest.raises(ValueError, match="event_id"):
        database.complete(job, {"capture_id": capture, "event_id": "wrong"})
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_subprocess_contract_without_loading_or_training_models(tmp_path: Path) -> None:
    repository = tmp_path / "ml repo with spaces"
    repository.mkdir()
    (repository / "main.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "args = sys.argv\n"
        "request = json.loads(Path(args[args.index('--request') + 1]).read_text())\n"
        "assert request['capture_id'] == args[args.index('--record-id') + 1]\n"
        "assert '--managed-retention' in args\n"
        "request['mode'] = 'acquisition' if '--data-aquisition' in args else 'production'\n"
        "request['objects'] = [{'category': 'apple'}]\n"
        "Path(args[args.index('--output') + 1]).write_text(json.dumps(request))\n"
    )
    database = Database(tmp_path / "database")
    capture = enqueue(database, tmp_path, "acquisition")
    config = MLConfig(enabled=True, python=Path(sys.executable), repository=repository)
    worker = InferenceWorker(database, config)
    assert worker.process_one(capture)
    assert not worker.process_one(capture)
    with database.connect() as connection:
        result = connection.execute("SELECT result_json FROM acquisition_records").fetchone()[0]
        assert json.loads(result)["objects"][0]["category"] == "apple"


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
        assert Path(json.loads(row["input_json"])["image_path"]).exists()
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_raw_attachments_are_copied_and_sensor_settings_preserved(tmp_path: Path) -> None:
    database = Database(tmp_path / "database")
    raw = tmp_path / "radar.bin"
    raw.write_bytes(b"radar-data")
    image = tmp_path / "image.png"
    image.write_bytes(b"placeholder")
    capture = database.enqueue(
        event_id="event",
        image=image,
        mode="acquisition",
        metadata={"radar_mode": "profile-2"},
        attachments=[{"sensor": "radar", "path": str(raw)}],
    )
    raw.unlink()
    job = database.claim(capture)
    assert job is not None
    payload = json.loads(job["input_json"])
    assert Path(payload["attachments"][0]["path"]).read_bytes() == b"radar-data"
    assert payload["sensor_metadata"]["radar_mode"] == "profile-2"


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
    (directory / "mask.json").unlink()
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
    path.write_text('[system]\n[ml]\nrepository="ml"\n')
    config = load_config(path)
    assert config.ml.repository == tmp_path / "ml"
    service = MLService(replace(config.ml, database_directory=tmp_path / "database"))
    assert not service.worker.process_one()
