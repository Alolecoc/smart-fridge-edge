"""Invoke the ML repository through a versioned JSON file contract."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from smart_fridge.config import MLConfig
from smart_fridge.database import Database

MODE_FLAGS = {"production": "--production", "acquisition": "--data-aquisition", "test": "--test"}


class InferenceWorker:
    def __init__(self, database: Database, config: MLConfig) -> None:
        self.database = database
        self.config = config

    def process_one(self, capture_id: str | None = None) -> bool:
        """Claim one row, call ML without a shell, and validate its result."""
        if not self.config.enabled:
            return False
        job = self.database.claim(capture_id)
        if job is None:
            return False
        try:
            result = self._invoke(job)
            self.database.complete(job, result)
            for warning in result.get("warnings", []):
                logging.getLogger(__name__).warning("%s: %s", job["capture_id"], warning)
        except Exception as error:
            self.database.fail(job, str(error))
            # Keep the daemon alive so another capture can still be processed.
            logging.getLogger(__name__).exception("inference failed for %s", job["capture_id"])
        return True

    def _invoke(self, job: dict[str, Any]) -> dict[str, Any]:
        folder = Path(job["artifact_directory"])
        folder.mkdir(parents=True, exist_ok=False)
        request = folder / "request.json"
        output = folder / "result.json"
        request.write_text(job["input_json"], encoding="utf-8")
        command = [
            str(self.config.python),
            str(self.config.repository / "main.py"),
            MODE_FLAGS[job["mode"]],
            "--record-id",
            job["capture_id"],
            "--request",
            str(request),
            "--output",
            str(output),
            "--config",
            str(self.config.model_config),
            "--models-dir",
            str(self.config.models_directory),
            "--managed-retention",
        ]
        # Logs live with this run; neither logs nor output can grow in RAM forever.
        with (folder / "inference.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                command,
                cwd=self.config.repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=self.config.timeout_seconds,
                check=True,
            )
        if output.is_symlink() or not output.is_file() or output.stat().st_size > 20_000_000:
            raise ValueError("missing, unsafe or oversized ML result")
        document: Any = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("ML result must be an object")
        return document
