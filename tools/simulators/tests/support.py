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

TINY_DATASET_SAMPLES = 8
TINY_DATASET_LINES = 4
TINY_DATASET_BANDS = 6


UC1_SVM_MODEL_PATH = UC1_PARAMETERS_PATH.parents[2] / "svm_model"

# The staged build root the build script writes, used by the tests that exercise
# the real binary. Absent until `scripts/development/build-uc1.ps1` has run.
STAGED_UC1_BUILD_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "UC1"


def buildTinyCubes() -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """Build the small ENVI fixture shared by writer and contract tests."""
    shape = (TINY_DATASET_BANDS, TINY_DATASET_LINES, TINY_DATASET_SAMPLES)
    voxelCount = numpy.prod(shape)
    darkCube = numpy.full(shape, 1200, dtype=numpy.uint16)
    whiteCube = numpy.full(shape, 51200, dtype=numpy.uint16)
    rawCube = (
        numpy.arange(voxelCount, dtype=numpy.uint16).reshape(shape) % 40000 + 1200
    ).astype(numpy.uint16)
    wavelengthsNm = numpy.linspace(400.482, 1000.73, TINY_DATASET_BANDS)
    return rawCube, whiteCube, darkCube, wavelengthsNm


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


def vendoredSvmModelDirectory() -> Path | None:
    """Return the vendored `svm_model/`, or None when the tree is not present."""
    return UC1_SVM_MODEL_PATH if UC1_SVM_MODEL_PATH.is_dir() else None


def stagedUc1Executable() -> Path | None:
    """Return the staged UC1 binary, or None when the build has not been run.

    Tests that need the GPU use this to skip rather than fail: a fresh clone has
    no `build/`, and the CUDA toolchain is not a checkout prerequisite.
    """
    executable = STAGED_UC1_BUILD_ROOT / "gpu_single_bsq" / "source" / "stratum.opt.exe"
    return executable if executable.is_file() else None


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
