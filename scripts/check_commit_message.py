"""Validate commit subjects using the Conventional Commits convention."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
TYPE_PATTERN = "|".join(ALLOWED_TYPES)
SUBJECT_PATTERN = re.compile(
    rf"^(?:{TYPE_PATTERN})(?:\([a-z0-9][a-z0-9-]*\))?!?: [a-z0-9].{{2,71}}$"
)
IGNORED_PREFIXES = ("Merge ", "Revert ")
ZERO_SHA = "0" * 40


def is_valid(subject: str) -> bool:
    return subject.startswith(IGNORED_PREFIXES) or bool(SUBJECT_PATTERN.fullmatch(subject))


def validate(subjects: list[str]) -> int:
    invalid = [subject for subject in subjects if not is_valid(subject)]
    if not invalid:
        return 0

    print("Invalid commit message subject(s):", file=sys.stderr)
    for subject in invalid:
        print(f"  - {subject}", file=sys.stderr)
    print(
        "Expected: type(optional-scope): lowercase description\n"
        "Example: feat(orchestrator): add door-event state machine\n"
        f"Allowed types: {', '.join(ALLOWED_TYPES)}",
        file=sys.stderr,
    )
    return 1


def subjects_from_range(revision_range: str) -> list[str]:
    if revision_range.startswith(f"{ZERO_SHA}.."):
        revision_range = revision_range.split("..", maxsplit=1)[1]
    result = subprocess.run(
        ["git", "log", "--format=%s", revision_range],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("message_file", nargs="?", type=Path)
    parser.add_argument("--range", dest="revision_range")
    args = parser.parse_args()

    if args.revision_range:
        return validate(subjects_from_range(args.revision_range))
    if args.message_file:
        subject = args.message_file.read_text(encoding="utf-8").splitlines()[0]
        return validate([subject])

    parser.error("provide a commit-message file or --range")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
