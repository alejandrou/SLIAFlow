"""Standard-library test runner for the STRATUM stand-in simulators.

The Slicer test runner is deliberately not used. Nothing under ``stratum_sim``
imports ``slicer``; these are separate processes standing where the acquisition
and UC1 applications stand, so their tests must run under a plain interpreter.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIMULATORS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent


def main() -> int:
    if str(SIMULATORS_ROOT) not in sys.path:
        sys.path.insert(0, str(SIMULATORS_ROOT))

    suite = unittest.TestLoader().discover(
        str(TESTS_ROOT), pattern="test_*.py", top_level_dir=str(SIMULATORS_ROOT)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
