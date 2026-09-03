"""STRATUM stand-in simulators.

These processes stand where the missing hyperspectral acquisition system and
the UC1 classifier stand. They exist so the genuine UC1 pipeline and SLIAFlow
have something valid to consume before any hardware arrives.

Everything produced here is synthetic and non-clinical. It is not patient data,
it is not derived from patient data, and no output of these processes carries
diagnostic meaning.

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
    "config",
    "contract",
    "envi",
    "frames",
    "igtl_transport",
    "spectra",
]
