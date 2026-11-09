"""After the door closes: find motion, cut segments and queue them for ML."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from smart_fridge.config import SegmentationConfig
from smart_fridge.database import Database
from smart_fridge.orchestrator import EventResult, Recording
from smart_fridge.segmentation import cut_segment, find_segments, motion_samples, video_duration


class EventProcessor:
    def __init__(self, database: Database, segmentation: SegmentationConfig, mode: str) -> None:
        self.database = database
        self.segmentation = segmentation
        self.mode = mode
        self.logger = logging.getLogger(__name__)

    def process(self, event: EventResult, keep_sources: bool = False) -> list[str]:
        """Queue every moving segment of every camera; returns the capture IDs."""
        metadata: dict[str, Any] = json.loads(event.metadata_path.read_text(encoding="utf-8"))
        metadata["mode"] = self.mode
        self.database.record_event(event.event_id, metadata)
        # Acquisition and test keep whole recordings for later study; production keeps
        # only the queued segments, which the retention policy purges.
        keep = self.mode != "production"
        archive = self.database.root / "recordings" / event.event_id
        captures: list[str] = []
        for recording in event.recordings:
            path = recording.path
            try:
                if keep and not keep_sources:
                    archive.mkdir(parents=True, exist_ok=True)
                    path = Path(shutil.move(recording.path, archive / recording.path.name))
                captures += self._queue_recording(event, recording, path, keep, keep_sources)
            except Exception as error:
                self.logger.exception("could not segment %s", recording.camera)
                # Never lose the footage when segmentation fails.
                if not keep_sources and path.parent != archive:
                    archive.mkdir(parents=True, exist_ok=True)
                    path = Path(shutil.move(path, archive / path.name))
                self.database.add_recording(
                    event_id=event.event_id,
                    camera=recording.camera,
                    started_at=recording.started_at.isoformat(),
                    path=path,
                    kept=True,
                    status="failed",
                    error=str(error)[:4000],
                )
        # Only staging remains here: kept footage was moved to the archive above.
        shutil.rmtree(event.event_directory, ignore_errors=True)
        self.logger.info("queued %d segments", len(captures), extra={"event_id": event.event_id})
        return captures

    def _queue_recording(
        self, event: EventResult, recording: Recording, path: Path, keep: bool, keep_sources: bool
    ) -> list[str]:
        config = self.segmentation
        duration = video_duration(path)
        samples = motion_samples(path, config.analysis_fps)
        segments = find_segments(samples, duration, config)
        start_offset = max(0.0, (recording.started_at - event.door_opened_at).total_seconds())
        work = event.event_directory / f"{recording.camera}-segments"
        captures = []
        rows = []
        for index, (start, end) in enumerate(segments):
            clip = cut_segment(path, start, end, work / f"{index:03d}.mp4")
            capture_id = self.database.enqueue_video(
                event_id=event.event_id,
                video=clip,
                camera=recording.camera,
                mode=self.mode,
                captured_at=(recording.started_at + timedelta(seconds=start)).isoformat(),
                offset_seconds=start_offset + start,
                segment={"index": index, "start": start, "end": end, "recording": path.name},
                move=True,
            )
            captures.append(capture_id)
            rows.append({"capture_id": capture_id, "start": start, "end": end})
        values = [value for _, value in samples]
        self.database.add_recording(
            event_id=event.event_id,
            camera=recording.camera,
            started_at=recording.started_at.isoformat(),
            path=path if keep or keep_sources else None,
            kept=keep or keep_sources,
            status="segmented",
            duration_seconds=round(duration, 3),
            segments=rows,
            motion={
                "threshold": config.motion_threshold,
                "max": round(max(values, default=0.0), 3),
                "mean": round(sum(values) / len(values), 3) if values else 0.0,
                "samples": len(values),
            },
        )
        if not keep and not keep_sources:
            path.unlink(missing_ok=True)
        return captures
