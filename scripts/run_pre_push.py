"""Run the slower checks used by the pre-push hook."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = PROJECT_ROOT / "src"


def project_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing_python_path = environment.get("PYTHONPATH")
    paths = [str(SOURCE_DIRECTORY)]
    if existing_python_path:
        paths.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def run(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, *arguments],
        check=True,
        cwd=PROJECT_ROOT,
        env=project_environment(),
    )


def main() -> int:
    try:
        run("-m", "mypy", "src")
        # Use a fresh temporary directory because a shared Windows pytest temp
        # directory may have been created by another account or sandbox.
        with tempfile.TemporaryDirectory(prefix="smart-fridge-pytest-") as temp_directory:
            run(
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                temp_directory,
            )
    except subprocess.CalledProcessError as error:
        return error.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
