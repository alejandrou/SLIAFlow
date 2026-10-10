"""Find IUMA's recorded captures under `input/` (ADR-0006 decision 1).

A capture is a folder of `input/` that holds IUMA's calibrated cube header,
`LCTF_Calibrated_Cube_Single.hdr`, either directly or in one nested folder of
the same name, which is how IUMA delivers them: `input/S-N-002-04/S-N-002-04/`.
Its ID is the folder name. Nothing else is a capture.

Only names are looked at here; whether the cube can be shown or run on is
`SLIAFlowCalibratedCube.loadCalibratedCube`'s to say. A capture at a path past
Windows' 259 characters is found too, so that it is listed and refused with
that reason rather than left out. Nothing is written.

This module imports nothing from Slicer or from its own package, so that
`scripts/development/check-captures.py` finds captures by the same rule.
"""

import os
from dataclasses import dataclass
from pathlib import Path

CALIBRATED_HEADER_NAME = "LCTF_Calibrated_Cube_Single.hdr"
# The capture every session starts on (SLIA-040 owner decision 1): the cube
# that was input/002-04 before 2026-10-08.
DEFAULT_CAPTURE_ID = "S-N-002-04"


@dataclass(frozen=True)
class Capture:
    id: str
    headerPath: Path


def _extended(path: Path) -> str:
    """`path` with Windows' extended-length prefix where it applies.

    Slicer's Python is not long-path aware, so without it a header past 259
    characters is not seen at all.
    """
    absolute = os.path.abspath(path)
    # A network path (\\server\share) takes another prefix; it is left as it is.
    if os.name != "nt" or absolute.startswith("\\\\"):
        return absolute
    return "\\\\?\\" + absolute


def _headerIn(folder: Path):
    """The capture header in `folder` itself or in its same-name folder, or None."""
    for candidate in (folder / CALIBRATED_HEADER_NAME, folder / folder.name / CALIBRATED_HEADER_NAME):
        if os.path.isfile(_extended(candidate)):
            return candidate
    return None


def findCaptures(inputRoot) -> tuple:
    """Every capture in `inputRoot`, in ID order. A missing folder holds none."""
    inputRoot = Path(inputRoot)
    if not inputRoot.is_dir():
        return ()
    captures = []
    for folder in sorted(inputRoot.iterdir(), key=lambda path: path.name):
        header = _headerIn(folder) if os.path.isdir(_extended(folder)) else None
        if header is not None:
            captures.append(Capture(folder.name, header))
    return tuple(captures)


def captureHeader(inputRoot, captureId: str) -> Path:
    """The header of capture `captureId`, or where it would lie if it is not there."""
    folder = Path(inputRoot) / captureId
    return _headerIn(folder) or folder / CALIBRATED_HEADER_NAME
