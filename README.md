# Smart Fridge Edge System

Software running on the Raspberry Pi in the smart-fridge prototype. It handles
door events, coordinates sensors, stores synchronized measurements, and later
calls a separately trained machine-learning model for inference.

Model training and large datasets belong in a separate `smart-fridge-ml`
repository. This repository only consumes an exported, versioned model.

## Architecture

```text
Door sensor -> Orchestrator/state machine -> Cameras/radar/lighting
                              |             -> Event storage
                              +------------- -> Inference adapter (later)
```

The current implementation uses simulated hardware. This lets us develop and
test the event logic before the physical components arrive.

## Development setup

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
```

Activate the environment, then install the project:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Install the repository's Git hooks once per clone:

```bash
pre-commit install --install-hooks
```

This installs three hook stages:

- `pre-commit`: fixes formatting where possible and validates Python, JSON,
  YAML, TOML, line endings, merge markers, file size and private keys.
- `commit-msg`: rejects commit messages that do not follow Conventional
  Commits.
- `pre-push`: validates the branch name, runs Mypy and runs Pytest before code
  is sent to GitHub.

If a formatting hook changes a file, the commit is deliberately stopped. Review
the changes, stage them with `git add .`, and commit again. Bypassing hooks with
`--no-verify` should be reserved for exceptional recovery work; GitHub CI still
performs the same validation.

Run the demonstration:

```bash
smart-fridge
```

Run quality checks:

```bash
ruff format --check .
ruff check .
mypy src
pytest
```

Run all fast file checks manually with:

```bash
pre-commit run --all-files
```

## Git workflow

- `main` is the integration branch. Completed feature branches are merged here.
- `prod` contains only versions that the group has tested and demonstrated as
  complete working snapshots.
- Create work from `main` in branches such as `feature/door-events` or
  `fix/camera-timeout`.
- Open a pull request into `main`; merge only when CI passes and another member
  has reviewed the change.
- When a revision on `main` has been tested as a complete system, promote that
  exact revision to `prod` through a pull request.
- Tag every promoted production revision: `v0.1.0`, `v0.2.0`, and so on. Tags make
  the individual working versions permanent and easy to restore.
- Never develop features directly on `prod`.

Commit examples:

```text
feat(orchestrator): add door-event state machine
feat(camera): capture image after door closes
fix(radar): handle serial timeout
test(orchestrator): verify failed capture recovery
docs(hardware): add wiring diagram
```

The intended flow is:

```text
type/* -> main -> prod -> version tag
```

Use `type/short-kebab-description` for development branches. Allowed types are
`feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`, and `experiment`.
Examples include `fix/door-sensor` and `feat/camera-capture`.

GitHub Actions runs on every pushed branch and every pull request. CI verifies
the files, commit-message convention, static types and tests. Unlike local
hooks, CI does not rewrite files: it reports failures so the author can correct
and push them.

## First milestones

1. Simulated door event creates a complete event record.
2. Real door sensor replaces the simulation.
3. One camera captures a stable post-close image.
4. A second camera and controlled lighting are added.
5. Radar is tested independently and then synchronized.
6. A versioned exported model is integrated for inference.
