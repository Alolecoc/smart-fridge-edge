"""Queue processing and periodic retention started by the edge entry point."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from smart_fridge.config import MLConfig
from smart_fridge.database import Database
from smart_fridge.inference import InferenceWorker


class MLService:
    def __init__(self, config: MLConfig) -> None:
        self.config = config
        self.database = Database(config.database_directory)
        self.worker = InferenceWorker(self.database, config)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._maintenance, daemon=True, name="fridge-retention"
        )

    def start(self) -> None:
        self.maintain()
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join()

    def maintain(self) -> None:
        try:
            cutoff = datetime.now(UTC) - timedelta(seconds=self.config.timeout_seconds + 60)
            self.database.recover(cutoff.isoformat())
            if self.config.mode == "production":
                self.database.purge(self.config.retention_runs)
        except Exception:
            logging.getLogger(__name__).exception("database maintenance failed; data retained")

    def _maintenance(self) -> None:
        while not self.stop_event.wait(self.config.purge_interval_seconds):
            self.maintain()
