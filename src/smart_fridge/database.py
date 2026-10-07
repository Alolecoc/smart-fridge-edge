"""SQLite records and managed files owned only by the edge application."""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from smart_fridge.config import MODES

SCHEMA_VERSION = 2
DIRECTIONS = ("in", "out")


def now() -> str:
    return datetime.now(UTC).isoformat()


CAPTURES_TABLE = """
    CREATE TABLE IF NOT EXISTS captures (
        capture_id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL REFERENCES events(event_id),
        mode TEXT NOT NULL CHECK(mode IN ('production', 'acquisition', 'test')),
        captured_at TEXT NOT NULL, created_at TEXT NOT NULL,
        input_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', error TEXT,
        purged_at TEXT);
"""


class Database:
    def __init__(self, directory: Path) -> None:
        self.root = directory.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "fridge.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            if connection.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                self._migrate(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL);
                """
                + CAPTURES_TABLE
                + """
                CREATE TABLE IF NOT EXISTS recordings (
                    recording_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    camera TEXT NOT NULL, started_at TEXT NOT NULL,
                    duration_seconds REAL, path TEXT, kept INTEGER NOT NULL,
                    status TEXT NOT NULL, error TEXT, segments_json TEXT NOT NULL,
                    motion_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inference_runs (
                    run_id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    mode TEXT NOT NULL, started_at TEXT NOT NULL,
                    completed_at TEXT, status TEXT NOT NULL, error TEXT,
                    artifact_directory TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS predictions (
                    run_id TEXT PRIMARY KEY REFERENCES inference_runs(run_id),
                    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    created_at TEXT NOT NULL, result_json TEXT NOT NULL,
                    purged_at TEXT);
                CREATE TABLE IF NOT EXISTS movements (
                    movement_id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES inference_runs(run_id),
                    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    camera TEXT NOT NULL, track_id TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
                    category TEXT NOT NULL, confidence REAL,
                    start_seconds REAL NOT NULL, end_seconds REAL NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS acquisition_records (
                    run_id TEXT PRIMARY KEY REFERENCES inference_runs(run_id),
                    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    created_at TEXT NOT NULL, input_json TEXT NOT NULL,
                    result_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS captures_pending ON captures(status, created_at);
                CREATE INDEX IF NOT EXISTS captures_event ON captures(event_id);
                CREATE INDEX IF NOT EXISTS recordings_event ON recordings(event_id);
                CREATE INDEX IF NOT EXISTS movements_event ON movements(event_id);
                CREATE INDEX IF NOT EXISTS runs_retention
                    ON inference_runs(mode, status, completed_at);
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Version 1 captures only allowed production/acquisition; add test mode."""
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'captures'"
        ).fetchone()
        if exists is None:
            return
        connection.commit()
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.executescript(
            "BEGIN;"
            + CAPTURES_TABLE.replace("EXISTS captures", "EXISTS captures_new")
            + """
            INSERT INTO captures_new SELECT capture_id, event_id, mode, captured_at,
                created_at, input_json, status, error, purged_at FROM captures;
            DROP TABLE captures;
            ALTER TABLE captures_new RENAME TO captures;
            COMMIT;
            """
        )
        connection.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------
    # DOOR EVENTS, FULL RECORDINGS AND QUEUED SEGMENTS
    # ------------------------------------------------------------
    def record_event(self, event_id: str, metadata: dict[str, Any]) -> None:
        """Create or update the door event, keeping its open/close times and settings."""
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO events VALUES (?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET metadata_json = excluded.metadata_json""",
                (event_id, now(), json.dumps(metadata)),
            )

    def add_recording(
        self,
        *,
        event_id: str,
        camera: str,
        started_at: str,
        path: Path | None,
        kept: bool,
        status: str,
        duration_seconds: float | None = None,
        segments: list[dict[str, Any]] | None = None,
        motion: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> str:
        recording_id = uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    recording_id,
                    event_id,
                    camera,
                    started_at,
                    duration_seconds,
                    str(path) if path else None,
                    int(kept),
                    status,
                    error,
                    json.dumps(segments or []),
                    json.dumps(motion or {}),
                    now(),
                ),
            )
        return recording_id

    def enqueue_video(
        self,
        *,
        event_id: str,
        video: Path,
        camera: str,
        mode: str,
        captured_at: str | None = None,
        offset_seconds: float = 0.0,
        segment: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        move: bool = False,
    ) -> str:
        """Move or copy one clip into managed storage and queue it for ML (schema 2)."""
        if mode not in MODES or not event_id or not camera:
            raise ValueError("mode, event_id and camera are required")
        timestamp = captured_at or now()
        if datetime.fromisoformat(timestamp).tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        if not video.is_file():
            raise ValueError(f"missing video: {video}")
        if not math.isfinite(offset_seconds) or offset_seconds < 0:
            raise ValueError("offset_seconds must be a non-negative number")
        capture_id = uuid4().hex
        folder = self.root / "captures" / capture_id
        folder.mkdir(parents=True)
        try:
            target = folder / ("clip" + video.suffix.lower())
            (shutil.move if move else shutil.copy2)(video, target)
            payload = {
                "schema_version": 2,
                "capture_id": capture_id,
                "event_id": event_id,
                "captured_at": timestamp,
                "camera": camera,
                "video_path": str(target),
                "offset_seconds": round(offset_seconds, 3),
                "segment": segment or {},
                "sensor_metadata": metadata or {},
                "attachments": [],
            }
            with self.connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?)", (event_id, now(), "{}")
                )
                connection.execute(
                    """INSERT INTO captures
                    (capture_id, event_id, mode, captured_at, created_at, input_json)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (capture_id, event_id, mode, timestamp, now(), json.dumps(payload)),
                )
        except BaseException:
            shutil.rmtree(folder)
            raise
        return capture_id

    def claim(self, capture_id: str | None = None) -> dict[str, Any] | None:
        """Reserve a pending capture atomically, so workers cannot process it twice."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = "SELECT * FROM captures WHERE status = 'pending'"
            parameters = () if capture_id is None else (capture_id,)
            if capture_id is not None:
                query += " AND capture_id = ?"
            row = connection.execute(query + " ORDER BY created_at LIMIT 1", parameters).fetchone()
            if row is None:
                return None
            run_id = uuid4().hex
            folder = self.root / "runs" / run_id
            connection.execute(
                "UPDATE captures SET status = 'running' WHERE capture_id = ?", (row["capture_id"],)
            )
            connection.execute(
                """INSERT INTO inference_runs
                (run_id, capture_id, event_id, mode, started_at, status, artifact_directory)
                VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (run_id, row["capture_id"], row["event_id"], row["mode"], now(), str(folder)),
            )
            return {**dict(row), "run_id": run_id, "artifact_directory": str(folder)}

    def export_acquisition(self, destination: Path) -> None:
        """Export persistent predictions for review without giving ML write access to SQLite."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM acquisition_records ORDER BY created_at"
            ).fetchall()
        records = [
            {
                "run_id": row["run_id"],
                "input": json.loads(row["input_json"]),
                "result": json.loads(row["result_json"]),
            }
            for row in rows
        ]
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": 2, "records": records}, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)

    # ------------------------------------------------------------
    # ML RESULTS: FULL JSON IN predictions, ONE ROW PER MOVEMENT
    # ------------------------------------------------------------
    @staticmethod
    def validate_result(job: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("capture_id", "event_id", "mode"):
            if result.get(key) != job[key]:
                raise ValueError(f"ML result has a mismatched {key}")
        if result.get("schema_version") != 2:
            raise ValueError("invalid ML result schema")
        movements = result.get("movements")
        if not isinstance(movements, list) or not isinstance(result.get("tracks"), list):
            raise ValueError("ML result needs movements and tracks lists")
        for movement in movements:
            if (
                not isinstance(movement, dict)
                or movement.get("direction") not in DIRECTIONS
                or not isinstance(movement.get("category"), str)
                or not isinstance(movement.get("start"), int | float)
                or not isinstance(movement.get("end"), int | float)
            ):
                raise ValueError("invalid ML movement record")
        return movements

    def complete(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """Only accept results matching the reserved capture and door event."""
        movements = self.validate_result(job, result)
        camera = json.loads(job["input_json"]).get("camera", "")
        encoded = json.dumps(result, allow_nan=False)
        timestamp = now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE inference_runs SET status = 'completed',
                completed_at = ? WHERE run_id = ? AND status = 'running'""",
                (timestamp, job["run_id"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("run is no longer active")
            connection.execute(
                "UPDATE captures SET status = 'completed' WHERE capture_id = ?",
                (job["capture_id"],),
            )
            connection.execute(
                "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, NULL)",
                (job["run_id"], job["capture_id"], job["event_id"], timestamp, encoded),
            )
            for movement in movements:
                connection.execute(
                    """INSERT INTO movements (run_id, capture_id, event_id, camera, track_id,
                    direction, category, confidence, start_seconds, end_seconds, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job["run_id"],
                        job["capture_id"],
                        job["event_id"],
                        camera,
                        str(movement.get("track_id", "")),
                        movement["direction"],
                        movement["category"],
                        movement.get("classification_confidence"),
                        float(movement["start"]),
                        float(movement["end"]),
                        timestamp,
                    ),
                )
            if job["mode"] == "acquisition":
                connection.execute(
                    "INSERT INTO acquisition_records VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        job["run_id"],
                        job["capture_id"],
                        job["event_id"],
                        timestamp,
                        job["input_json"],
                        encoded,
                    ),
                )

    def fail(self, job: dict[str, Any], error: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE inference_runs SET status = 'failed', error = ?,
                completed_at = ? WHERE run_id = ? AND status = 'running'""",
                (error[:4000], now(), job["run_id"]),
            )
            if cursor.rowcount != 1:
                return
            connection.execute(
                "UPDATE captures SET status = 'failed', error = ? WHERE capture_id = ?",
                (error[:4000], job["capture_id"]),
            )

    def recover(self, before: str) -> None:
        """Mark abandoned jobs failed without discarding files or retrying silently."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT * FROM inference_runs
                WHERE status = 'running' AND started_at < ?""",
                (before,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE inference_runs SET status = 'failed', error =
                    'worker interrupted or timed out', completed_at = ? WHERE run_id = ?""",
                    (now(), row["run_id"]),
                )
                connection.execute(
                    "UPDATE captures SET status = 'failed' WHERE capture_id = ?",
                    (row["capture_id"],),
                )

    def purge(self, keep: int) -> int:
        """Prune owned files of older successful production/test runs, never acquisition."""
        if keep < 1:
            raise ValueError("retention_runs must be at least 1")
        count = 0
        # Serialize purge with other DB writers; a failed deletion rolls back
        # metadata and is safe to repeat because missing directories are allowed.
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT r.*, p.result_json FROM inference_runs r
                JOIN predictions p USING(run_id)
                WHERE r.mode IN ('production', 'test') AND r.status = 'completed'
                ORDER BY r.completed_at DESC, r.rowid DESC LIMIT -1 OFFSET ?""",
                (keep,),
            ).fetchall()
            for row in rows:
                if connection.execute(
                    "SELECT purged_at FROM predictions WHERE run_id = ?", (row["run_id"],)
                ).fetchone()[0]:
                    continue
                for kind, identifier in (("runs", row["run_id"]), ("captures", row["capture_id"])):
                    directory = self.root / kind / identifier
                    if (
                        directory.is_symlink()
                        or directory.parent.is_symlink()
                        or directory.resolve().parent != (self.root / kind).resolve()
                    ):
                        raise ValueError("refusing to purge outside managed storage")
                    if directory.exists():
                        shutil.rmtree(directory)
                # Movements, categories and track paths stay; only file paths are removed.
                result = json.loads(row["result_json"])
                result["artifacts_purged"] = True
                for key in ("source", "attachments"):
                    result.pop(key, None)
                for track in result.get("tracks", []):
                    track.pop("crop_file", None)
                connection.execute(
                    "UPDATE predictions SET result_json = ?, purged_at = ? WHERE run_id = ?",
                    (json.dumps(result), now(), row["run_id"]),
                )
                connection.execute(
                    "UPDATE captures SET purged_at = ? WHERE capture_id = ?",
                    (now(), row["capture_id"]),
                )
                count += 1
        return count
