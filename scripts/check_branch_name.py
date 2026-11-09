"""Validate development branch names."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

PERMANENT_BRANCHES = {"main", "prod"}
BRANCH_PATTERN = re.compile(
    r"^(?:feat|fix|chore|docs|test|refactor|ci|experiment)/[a-z0-9][a-z0-9-]*$"
)


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def is_valid(branch: str) -> bool:
    return branch in PERMANENT_BRANCHES or bool(BRANCH_PATTERN.fullmatch(branch))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("branch", nargs="?", default=None)
    args = parser.parse_args()
    branch = args.branch or current_branch()

    if is_valid(branch):
        return 0

    print(
        f"Invalid branch name: {branch}\n"
        "Expected main, prod, or type/short-kebab-description.\n"
        "Example: fix/door-sensor\n"
        "Allowed types: feat, fix, chore, docs, test, refactor, ci, experiment",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
