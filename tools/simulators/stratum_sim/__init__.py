"""STRATUM acquisition stand-in and genuine UC1 runner.

These processes stand where the missing hyperspectral acquisition system stands,
and run the genuine UC1 pipeline, so SLIAFlow has something real to consume
before any hardware arrives.

Every cube is a recorded case of the public, anonymized HSI Human Brain
Database, read where it lies. Only the acquisition event is simulated, and no
output of these processes carries diagnostic meaning.

The package deliberately lives outside `extensions/`: the seam between a
stand-in and the real component is the network boundary the architecture
already has, so replacing one with the other is stopping a process and starting
another on the same port.
"""

from __future__ import annotations

import sys

MINIMUM_PYTHON_VERSION = (3, 10)

if sys.version_info < MINIMUM_PYTHON_VERSION:  # pragma: no cover - guard, not behaviour
    raise RuntimeError(
        "stratum_sim requires Python "
        f"{MINIMUM_PYTHON_VERSION[0]}.{MINIMUM_PYTHON_VERSION[1]} or newer; "
        f"this interpreter is {sys.version_info[0]}.{sys.version_info[1]}. "
        "Use the repository-root .venv."
    )

__all__ = [
    "acquisition_sim",
    "bmp",
    "config",
    "contract",
    "envi",
    "frames",
    "igtl_transport",
    "spectra",
    "uc1_maps",
    "uc1_runner",
]
