"""OpenIGTLink transport kept from the retired STRATUM stand-ins.

The acquisition stand-in and the UC1 runner that used to live here were retired
by SLIA-028: UC1 runs inside Slicer (ADR-0003) and IUMA's acquisition app is the
producer (ADR-0004). What remains is the transport - building IMAGE and STRING
messages that keep their metadata, refusing a port another process holds, and
watching clients - which SLIA-035 builds its imitation of IUMA's app on.

Nothing here imports `slicer`; it runs under the repository-root `.venv`.
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
    "contract",
    "igtl_transport",
]
