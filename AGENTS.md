# Smart Fridge agent instructions

This repository contains the edge software for the Smart Fridge project.

Agents working in this repository must follow the existing project structure,
development workflow, naming conventions, Git rules, and automated checks.

## General principles

- Follow the existing architecture before introducing new abstractions.
- Keep changes focused on the requested task.
- Avoid unrelated refactoring.
- Prefer simple, readable solutions over unnecessary complexity.
- Do not weaken tests, linting, type checking, hooks, or CI just to make a task pass.
- Do not bypass project rules with `--no-verify`.
- Do not commit secrets, credentials, tokens, private keys, passwords, or production configuration.

## Repository structure

Production code belongs under:

`src/smart_fridge/`

Tests belong under:

`tests/`

Project scripts belong under:

`scripts/`

Configuration belongs under:

`config/`

Documentation belongs under:

`docs/`

Respect the existing module structure and avoid creating new top-level directories
unless there is a clear architectural reason.

## Python version

The project targets Python 3.11 or newer.

Development dependencies are defined in:

`pyproject.toml`

Install the project and development tools with:

`python -m pip install -e ".[dev]"`

## Python style and naming

Follow normal Python conventions and the existing codebase.

Use:

- `snake_case` for modules
- `snake_case` for functions
- `snake_case` for variables
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants

Production code should use type annotations.

The repository uses strict Mypy type checking.

Avoid:

- unnecessary global state
- hidden side effects
- deeply nested logic when simpler control flow is possible
- duplicated logic
- hardware-specific logic mixed into unrelated application logic

## Hardware code

Hardware-specific code belongs under:

`src/smart_fridge/hardware/`

Where practical, hardware access should be abstracted behind interfaces so that:

- automated tests can run without physical hardware
- CI can run without Raspberry Pi hardware
- Codex Cloud can run without GPIO, camera, SPI, or I2C devices
- simulated implementations can be used in tests and development

Do not assume Raspberry Pi hardware is available in CI or Codex Cloud.

If adding support for GPIO, camera, I2C, SPI, sensors, or other physical devices,
keep the hardware boundary explicit and testable.

## Branch workflow

Never develop directly on:

- `main`
- `prod`

Create new work from the latest `main`.

Use:

`git switch main`

`git pull`

`git switch -c <type>/<short-description>`

Allowed branch prefixes are:

- `feat/`
- `fix/`
- `chore/`
- `docs/`
- `test/`
- `refactor/`
- `ci/`
- `experiment/`

Branch names must use lowercase kebab-case after the prefix.

Examples:

- `feat/camera-capture`
- `fix/door-sensor`
- `docs/hardware-setup`
- `refactor/orchestrator-events`
- `test/camera-service`
- `ci/update-python-version`

Invalid examples:

- `Feature/CameraCapture`
- `my-branch`
- `camera_fix`
- `AlbinFlankLeon-patch-1`

Do not create new permanent branches without an explicit reason.

## Commit messages

Use Conventional Commits.

Valid examples:

- `feat: add camera capture`
- `feat(camera): add image capture`
- `fix(sensor): debounce door events`
- `test(orchestrator): add event tests`
- `docs: document raspberry pi setup`
- `ci: update github actions workflow`

Commit subjects should:

- start with an allowed Conventional Commit type
- use lowercase descriptions
- be concise and descriptive
- describe one logical change

Do not use vague commit messages such as:

- `update stuff`
- `fix things`
- `changes`
- `wip`

## Required checks

Before considering any task complete, run:

`pre-commit run --all-files --hook-stage pre-commit`

Then run:

`python scripts/run_pre_push.py`

All checks must pass.

The project uses:

- Pre-commit
- Ruff linting
- Ruff formatting
- Mypy strict type checking
- Pytest
- branch-name validation
- Conventional Commit validation

Do not disable or skip these checks.

If a formatter or hook modifies files, review the changes and run the checks again.

## Testing

Add or update tests when behavior changes.

Tests belong under:

`tests/`

Prefer deterministic tests.

Avoid tests that require:

- physical Raspberry Pi hardware
- network access
- a real camera
- a real GPIO sensor

unless the task explicitly concerns hardware integration testing.

Use simulated or mocked hardware where appropriate.

Run tests using:

`python scripts/run_pre_push.py`

## Pull requests

Do not push directly to `main` or `prod`.

Work on a feature branch and open a pull request into `main`.

Before opening a PR:

1. Review the diff.
2. Remove unrelated changes.
3. Run all required checks.
4. Confirm tests pass.
5. Confirm type checking passes.
6. Confirm formatting and linting pass.

A task is not considered complete until CI passes.

Keep pull requests focused on one task whenever possible.

## CI

GitHub Actions is the final automated verification layer.

Do not modify CI merely to make failing code pass.

If CI fails:

1. understand the failure
2. fix the underlying issue
3. rerun the relevant local checks
4. push the corrected change

Do not weaken CI rules unless the task explicitly requires a justified CI change.

## Documentation

Update documentation when behavior, setup, architecture, or developer workflow changes.

Relevant files include:

- `README.md`
- `README_DEVELOPMENT.md`
- `docs/`

Keep documentation consistent with the actual implementation.

## Security

Never commit:

- passwords
- API keys
- SSH private keys
- GitHub tokens
- Tailscale credentials
- access tokens
- private certificates
- production secrets
- `.env` files containing secrets

Do not print secrets in logs or test output.

Do not add credentials to source code.

## Dependency changes

Avoid adding new dependencies unless needed.

Before adding a dependency, consider whether the same result can be achieved with:

- the Python standard library
- an existing project dependency
- a small amount of clear local code

If a dependency is added:

- add it to the correct section of `pyproject.toml`
- explain why it is needed
- update tests if relevant

## Agent behavior

When working on a task:

1. Read this `AGENTS.md`.
2. Inspect the relevant existing code before editing.
3. Follow the existing architecture and naming.
4. Make the smallest coherent change that solves the task.
5. Add or update tests.
6. Run all required checks.
7. Review the final diff.
8. Report what changed and which checks were run.

If requirements are ambiguous, prefer preserving existing behavior and project conventions.

Do not invent new architecture, naming conventions, or workflows when the repository already defines them.

## Definition of done

A task is complete only when:

- the requested behavior is implemented
- tests are added or updated where appropriate
- formatting passes
- linting passes
- type checking passes
- automated tests pass
- the branch name is valid
- commit messages follow project rules
- the diff contains no unrelated changes
- no secrets or credentials were introduced
- CI is expected to pass
