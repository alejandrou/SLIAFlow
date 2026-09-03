"""Shared helpers for the simulator tests.

The UC1 re-implementations here exist so the tests check the written dataset
against the consumer's own parsing rules rather than against the writer's idea
of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

# The vendored UC1 tree lives under the ignored `workspace/`, so it is absent on
# a fresh clone. Tests that read it degrade to a skip rather than a failure.
UC1_PARAMETERS_PATH = (
    REPOSITORY_ROOT
    / "workspace"
    / "components"
    / "UC1_Brain_Tumor-GPU_optimization"
    / "UC1_Brain_Tumor-GPU_optimization"
    / "gpu_single_bsq"
    / "source"
    / "parameters.txt"
)

# `main.cu` reads parameters.txt with successive fscanf calls in a fixed order:
# checkHySime, then numberOfPcaBands, then pca_epsilon, then numberOfClasses.
PCA_BAND_COUNT_VALUE_INDEX = 1

# `data_loader.cpp` reads header lines with `fgets(line, MAX_PATH_LENGTH, file)`
# and `MAX_PATH_LENGTH` is 128, so a longer line is split mid-parse.
UC1_MAX_PATH_LENGTH = 128


def readUc1PcaBandCount() -> int | None:
    """Return the PCA component count UC1 requests, or None when unavailable."""
    if not UC1_PARAMETERS_PATH.is_file():
        return None
    values = UC1_PARAMETERS_PATH.read_text(encoding="ascii").split()
    if len(values) <= PCA_BAND_COUNT_VALUE_INDEX:
        return None
    return int(float(values[PCA_BAND_COUNT_VALUE_INDEX]))


def parseHeaderTheWayUc1Does(headerPath: Path) -> dict[str, int]:
    """Re-implement the three-key header scan in `data_loader.cpp`.

    The loop reads at most `MAX_PATH_LENGTH` bytes per line and stops as soon as
    three of `bands`, `lines` and `samples` have been matched, so a key that
    only appears after the wavelength block is never reached.
    """
    found: dict[str, int] = {}
    patterns = {
        "bands": re.compile(r"^bands = ([+-]?\d+)"),
        "lines": re.compile(r"^lines = ([+-]?\d+)"),
        "samples": re.compile(r"^samples = ([+-]?\d+)"),
    }

    with headerPath.open("rb") as headerFile:
        while len(found) < 3:
            line = headerFile.readline(UC1_MAX_PATH_LENGTH - 1)
            if not line:
                break
            text = line.decode("ascii", errors="replace")
            for key, pattern in patterns.items():
                if key in found:
                    continue
                match = pattern.match(text)
                if match is not None:
                    found[key] = int(match.group(1))
                    break
    return found


def parseHeaderTheWayHsCubeLoaderDoes(headerPath: Path) -> dict[str, str]:
    """Re-implement the key/value scan in `HSCubeLoader.cpp`.

    Everything from a `;` onwards is a comment, and each remaining `key = value`
    line contributes one entry.
    """
    values: dict[str, str] = {}
    for rawLine in headerPath.read_text(encoding="ascii").splitlines():
        commentIndex = rawLine.find(";")
        line = rawLine if commentIndex < 0 else rawLine[:commentIndex]
        separatorIndex = line.find("=")
        if separatorIndex < 0:
            continue
        key = line[:separatorIndex].strip().lower()
        value = line[separatorIndex + 1:].strip()
        if key:
            values[key] = value
    return values


def makeTestFrame(samples: int, lines: int) -> numpy.ndarray:
    """Build a deterministic BGR frame with all three channels distinguishable."""
    x = numpy.linspace(0.0, 1.0, samples, dtype=numpy.float32)[None, :]
    y = numpy.linspace(0.0, 1.0, lines, dtype=numpy.float32)[:, None]
    blue = x + 0.0 * y
    green = y + 0.0 * x
    red = 0.5 * (x + y[::-1])
    frame = numpy.stack([blue, green, red], axis=-1)
    return numpy.clip(frame * 255.0, 0.0, 255.0).astype(numpy.uint8)
