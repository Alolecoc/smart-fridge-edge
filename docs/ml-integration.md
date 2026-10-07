# Live system, ML integration and SQLite

The edge application owns the door, the cameras, SQLite and every stored file. The ML
repository (`grocery-product-detection`) is a subprocess in this chain: it receives one
JSON request per video segment and returns JSON. It never opens the edge database.
There are no PyTorch dependencies here.

For the full Raspberry Pi setup, see `../grocery-product-detection/HOW-TO.md`.

## What happens on a door event

1. **Door opens** (GPIO switch, debounced): every camera in `[cameras]` starts recording
   (`rpicam-vid` for Pi camera modules, `ffmpeg` for USB cameras).
2. **Door closes**: recording continues for `wait_after_close_seconds`, then stops.
   A door left open longer than `max_recording_seconds` is cut there.
3. **Segmentation** (background thread): ffmpeg measures frame-to-frame change. Moments
   above `motion_threshold` are padded, merged and cut into segments. With no motion at
   all, the whole recording is queued (`whole_clip_without_motion`).
4. **Queue**: each segment becomes a `captures` row with a schema 2 request
   (`camera`, `video_path`, `offset_seconds` from the door opening).
5. **ML** (background thread): `main.py` tracks objects, decides in/out with the zones
   drawn in the review tool and classifies them. The result is validated and stored.

```bash
python run.py --config config/pi.toml --run            # production
python run.py --config config/pi.toml --run --test     # also publish to the review tool
python run.py --config config/pi.toml --run --data-aquisition
```

| Mode | ML flag | Full recordings | Segment files | Review tool |
| --- | --- | --- | --- | --- |
| `production` | `--production` | deleted after cutting | newest `retention_runs` kept | no |
| `test` | `--test` | kept in `database/recordings/` | newest `retention_runs` kept | every clip + prediction |
| `acquisition` | `--data-aquisition` | kept | kept, plus `acquisition_records` | no |

## Commands

| Command | Purpose |
| --- | --- |
| `--run` | Live system (needs `simulated_hardware = false`) |
| `--serve` | Only process queued segments and cleanup |
| `--submit clip.mp4 --camera fridge [--event-id ID]` | Segment and queue a recorded clip like a door event |
| `--capture-id ID` | Process one pending segment now |
| `--check-door [--pin N]` | Print the door switch level live, to find the pin and `open_level` |
| `--check-cameras` | Record 3 s from every camera |
| `--analyse-motion clip.mp4` | Print motion levels and the resulting segments, to tune `motion_threshold` |
| `--export-acquisition file.json` | Export acquisition results |

## Storage

`database/fridge.sqlite3` (WAL, foreign keys) holds everything:

| Table | Purpose |
| --- | --- |
| `events` | Door event ID; metadata JSON with open/close times, cameras, mode, errors |
| `recordings` | One full recording per camera: duration, motion statistics, segments, kept path |
| `captures` | One queued segment: mode, request JSON (camera, offset, segment times), status |
| `inference_runs` | One ML attempt: start/end, status, error, artifact directory |
| `predictions` | The full ML result JSON (tracks, movements, models, zones, warnings) |
| `movements` | One row per item moved: event, camera, track, `in`/`out`, category, confidence, event time |
| `acquisition_records` | Persistent input/result copies in acquisition mode |

What went in or out during a door event:

```sql
SELECT camera, direction, category, confidence, start_seconds
FROM movements WHERE event_id = ? ORDER BY start_seconds;
```

Files: `database/captures/<capture-id>/clip.mp4` (segments),
`database/runs/<run-id>/` (request, result, log, ML working copy and crops),
`database/recordings/<event-id>/` (full recordings in test/acquisition mode).
The database version is stored in `PRAGMA user_version`; older databases from the
image-based integration are migrated automatically.

The edge invokes the ML process without a shell:

```text
<ml-python> <ml-repo>/main.py --production|--test|--data-aquisition
  --record-id <capture-id> --request <absolute-request.json>
  --output <absolute-result.json> --config <video.yaml>
  --models-dir <model-root> --managed-retention
```

Requests and results follow the ML repository's `documentation/CONTRACT.md` (schema 2).
The edge rejects mismatched IDs/modes, wrong schema and malformed movements. A failed or
timed-out process records an error without discarding the segment.

## Retention

`retention_runs = 3` keeps the files of the newest three successful production/test
**segments** across all cameras and events. Older segment and run folders are deleted;
their movements, categories and result JSON stay in SQLite and are marked `purged_at`.
Acquisition, pending and failed captures are never purged. Cleanup runs at startup,
after each ML run and every `purge_interval_seconds`. Jobs still marked running after
`timeout_seconds` plus 60 seconds are marked failed and not retried silently.

## Validation

`scripts/run_pre_push.py` runs Mypy and Pytest. The tests cover the recording state
machine, debouncing, motion segmentation with real ffmpeg clips, the live loop from door
open to stored movements (with a fake ML process), the subprocess contract for every
mode, retention, the database migration and config validation. They do not use physical
cameras, GPIO or the Hailo accelerator.
