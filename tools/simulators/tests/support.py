"""Shared helpers for the transport tests."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def pinnedRequirement(requirementsPath: Path, packageName: str) -> str:
    """Return one exact ``package==version`` pin from a requirements file."""
    prefix = f"{packageName.lower()}=="
    matches = [
        line.strip()
        for line in requirementsPath.read_text(encoding="utf-8").splitlines()
        if line.strip().lower().startswith(prefix)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected exactly one {packageName!r} pin in {requirementsPath}, found {matches}."
        )
    return matches[0]
