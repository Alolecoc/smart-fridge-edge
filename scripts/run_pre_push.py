"""Run the slower checks used by the pre-push hook."""

from __future__ import annotations

import subprocess
import sys


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def main() -> int:
    try:
        run("-m", "mypy", "src")
        run("-m", "pytest")
    except subprocess.CalledProcessError as error:
        return error.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
