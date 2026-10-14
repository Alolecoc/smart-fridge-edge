# ML integration and SQLite

The edge application owns SQLite and all persistent capture/result records. The ML
repository is a subprocess in this chain; it receives JSON files and returns JSON.
It neither opens nor writes the edge database. There are no PyTorch dependencies here.

## Setup and one-command startup

Keep the ML checkout next to this repository, or edit `[ml]` in `config/ml.toml`.
Set `repository`, `python`, `model_config` and `models_directory` to your deployment.
ML paths in this file resolve relative to the edge repository. The model directory
contains `yolo/` and `vit/`; the ML YAML selects individual checkpoints.

```bash
python run.py --config config/ml.toml --serve
```

This starts the persistent SQLite queue worker and scheduled cleanup. Stop with
Ctrl+C or SIGTERM. Captures can be submitted from another terminal:

```bash
python run.py --config config/ml.toml --submit /path/shelf1.jpg --event-id door-001
python run.py --config config/ml.toml --submit /path/shelf2.jpg --event-id door-001
```

Each submission prints a capture ID. Both images share the door event but have
different capture IDs. `--captured-at` accepts a timestamp with timezone; otherwise
the submission time is used. `--sensor`, `--metadata settings.json` and repeated
`--attachment /path/raw.bin` preserve sensor identity, settings and raw IR/radar
files. These files are copied before queueing, so their originals remain yours.

For acquisition, add `--data-aquisition` (or `--data-acquisition`) when submitting.
The row's mode is passed to ML; it is not changed by whichever worker processes it.
Use `--capture-id ID` instead of `--serve` to process a pending record once.

Without `--serve` or `--submit`, the existing one-door-event demo still runs. With
`config/ml.toml` it captures valid but plain simulated RGB images, registers them,
runs inference and starts/stops maintenance. With the original default config,
the old text-file sensor demo is unchanged. Real camera/door/radar adapters remain
future work; `--serve` currently processes submissions, not physical GPIO events.

## Storage

`database/fridge.sqlite3` is initialized automatically with WAL and foreign keys:

| Table | Purpose |
| --- | --- |
| `events` | Door event ID, timestamps/settings in event metadata |
| `captures` | Capture ID, event ID, mode, capture/create timestamps, input JSON, queue state |
| `inference_runs` | Run ID, capture/event IDs, start/end times, status, errors, artifact directory |
| `predictions` | Output classification JSON for each successful run |
| `acquisition_records` | Persistent acquisition input/output JSON, linked to event/capture/run |

Original pixels and raw sensor files are kept under `database/captures/<capture-id>`.
Requests, logs, masks, crops and result JSON live under `database/runs/<run-id>`.
Binary data is stored as files, not SQLite blobs. The database, files and their
backups belong together. Runtime data is ignored by Git.

The edge invokes the ML process without a shell:

```text
<ml-python> <ml-repo>/main.py --production|--data-aquisition
  --record-id <capture-id> --request <absolute-request.json>
  --output <absolute-result.json> --config <model-config>
  --models-dir <model-root> --managed-retention
```

Contract schema version is 1. Requests contain `capture_id`, `event_id`, `captured_at`,
`sensor`, absolute `image_path`, `sensor_metadata` and `attachments`. Results contain
the same IDs, `mode`, model timestamps, `objects` and category counts. Each object
has a category, box, polygon and scores. The edge rejects wrong IDs/modes or invalid
result structure; a failed/timed-out process records an error without discarding raw
files. Empty predictions are valid and do not imply an empty fridge.

## Retention

`retention_runs = 3` keeps artifacts for the newest **three successful production
image runs**, including the current run, across all cameras/events. This is not
three door events. Choose a higher number if several shelves must remain available.
Cleanup runs at startup, after processing, and every `purge_interval_seconds`.

Cleanup deletes only managed capture/run folders, never external source files.
It retains category/count history in SQLite, removes expired paths/polygons from
prediction JSON and marks records with `purged_at`. Acquisition, pending and failed
captures are excluded. Acquisition files and records persist until explicitly
managed by a person. Older failed logs/captures require manual attention.
Already purged input paths remain in `captures.input_json` as historical provenance;
check `purged_at` before attempting to open them.

ML's standalone retention is disabled by `--managed-retention`; only the edge owns
cleanup in this integration. The worker uses a configurable subprocess timeout.
Jobs still marked running after timeout plus 60 seconds are marked failed, not
silently retried. Resubmit a capture for an explicit new attempt.

## Review acquisition data

```bash
python run.py --config config/ml.toml --export-acquisition database/acquisition.json
```

In the ML checkout:

```bash
python -m utils.import_acquisition ../smart-fridge-edge/database/acquisition.json --split train
python annotation_tool/run.py
```

This imports existing predictions without another network run. The local review
workspace owns draft edits; the edge acquisition rows preserve the original raw
observations and predictions. Training is always a separate explicit ML command.

## Validation

Use the repository's existing pre-commit hooks and `scripts/run_pre_push.py`.
Tests cover grouping, subprocess handoff, failure retention, acquisition persistence,
safe purging and worker shutdown using small fake model outputs. They do not train
models or establish physical sensor/accelerator performance.
