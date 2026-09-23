# Smart Fridge Development Guide

This guide explains how to set up the repository and contribute changes. Each
group member must complete the one-time setup on their own computer.

## One-time setup

### 1. Install the required software

Install:

- Git
- Python 3.11 or newer

Verify the installations in PowerShell:

```powershell
git --version
python --version
```

### 2. Clone the repository

```powershell
git clone https://github.com/Alolecoc/smart-fridge-edge.git
cd smart-fridge-edge
```

### 3. Configure your Git identity

Use your own name and an email address connected to your GitHub account:

```powershell
git config --global user.name "Your Name"
git config --global user.email "your-email@example.com"
```

### 4. Create and activate a virtual environment

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

The PowerShell prompt should now begin with `(.venv)`.

### 5. Install the project and development tools

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs the project together with Pre-commit, Ruff, Mypy and Pytest.

### 6. Install and test the Git hooks

```powershell
pre-commit install --install-hooks
pre-commit run --all-files --hook-stage pre-commit
pre-commit run --all-files --hook-stage pre-push
```

All checks should report `Passed`.

## Starting a task

Always create new work from the latest version of `main`:

```powershell
git switch main
git pull
git switch -c feat/short-task-name
```

Use one of these branch prefixes:

- `feat/` for new functionality
- `fix/` for bug fixes
- `chore/` for maintenance
- `docs/` for documentation
- `test/` for tests
- `refactor/` for internal restructuring
- `ci/` for CI/CD changes
- `experiment/` for experimental work

Examples:

```text
feat/camera-capture
fix/door-sensor
experiment/radar-placement
docs/hardware-setup
```

## Committing changes

Inspect and stage your changes:

```powershell
git status
git diff
git add .
```

Commit using the Conventional Commits format:

```powershell
git commit -m "feat: add camera capture"
```

A scope is optional:

```powershell
git commit -m "feat(camera): add image capture"
```

Common commit types are:

- `feat` for new functionality
- `fix` for a correction
- `docs` for documentation
- `test` for tests
- `refactor` for restructuring
- `chore` for maintenance
- `ci` for pipeline changes

### When a hook modifies a file

Pre-commit may automatically correct formatting or whitespace. When that
happens, the commit stops so that you can review the correction:

```powershell
git diff
git add .
git commit -m "feat: add camera capture"
```

Do not normally use `--no-verify`, because it bypasses the local checks.

## Pushing and opening a pull request

Push the task branch:

```powershell
git push -u origin feat/short-task-name
```

The pre-push hook checks:

- The branch name
- Static Python types with Mypy
- Automated tests with Pytest

GitHub Actions independently repeats the checks after the push.

When the branch is ready:

1. Open the repository on GitHub.
2. Create a pull request from your task branch into `main`.
3. Wait for CI to pass.
4. Ask another group member to review and approve it.
5. Merge only after approval and successful checks.

## Branch roles

- `main` contains integrated development work.
- `prod` contains only complete versions validated on the physical system.
- Version tags such as `v0.1.0` permanently identify working releases.

Do not develop directly on `main` or `prod`.

## Returning to another task

Activate the existing environment whenever you open a new PowerShell window:

```powershell
cd C:\path\to\smart-fridge-edge
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Then update `main` and create a new branch:

```powershell
git switch main
git pull
git switch -c fix/another-task
```
