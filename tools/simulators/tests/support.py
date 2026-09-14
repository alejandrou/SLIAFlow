"""Shared helpers for the simulator tests.

The UC1 re-implementations here exist so the tests check the written dataset
against the consumer's own parsing rules rather than against the writer's idea
of them.
"""

from __future__ import annotations

import hashlib
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


# The marker the HSI Human Brain Database stamps into every case's `gtMap.hdr`.
# Read from all 61 cases in `input/bin/bin` on 2026-09-11 and again on
# 2026-09-13. It is not in `raw.hdr`.
RECORDED_DATABASE_MARKER = "HSI Human Brain Database"

# Every recorded case shares this grid: 440 to 900 nm in 5 nm steps, written six
# values to a line.
RECORDED_FIRST_WAVELENGTH_NM = 440
RECORDED_WAVELENGTH_STEP_NM = 5
RECORDED_VALUES_PER_WAVELENGTH_LINE = 6


def buildRecordedRawHeader(samples: int, lines: int, bands: int, description: str = "") -> str:
    """Reproduce the layout every recorded `raw.hdr` has.

    The two properties a reader has to survive are reproduced rather than
    tidied: the wavelength block is closed by a `}` on its last value line, and
    `lines` and `samples` come after the block. Value lines end in `", "` before
    the newline, as they do on disk.
    """
    wavelengths = [
        str(RECORDED_FIRST_WAVELENGTH_NM + RECORDED_WAVELENGTH_STEP_NM * index)
        for index in range(bands)
    ]
    rows = [
        ", ".join(wavelengths[start:start + RECORDED_VALUES_PER_WAVELENGTH_LINE])
        for start in range(0, bands, RECORDED_VALUES_PER_WAVELENGTH_LINE)
    ]

    headerLines = ["ENVI"]
    if description:
        headerLines.append(f"description = {{{description}}}")
    headerLines += [
        f"bands = {bands}",
        "data type = 12",
        "interleave = bsq",
        "header offset = 0",
        "wavelength units = Nanometers",
        "byte order = 0",
        "wavelength = {" + ", \n".join(rows) + "}",
        f"lines = {lines}",
        f"samples = {samples}",
    ]
    return "\n".join(headerLines) + "\n"


def buildRecordedGroundTruthHeader(samples: int, lines: int, marker: str) -> bytes:
    """Reproduce a recorded `gtMap.hdr`, including its CR-only line endings.

    An empty `marker` writes a description that does not identify the database,
    which is the shape of a folder that is not a database case.
    """
    description = (
        f"description = {{{marker} - https://hsibraindatabase.iuma.ulpgc.es/}}"
        if marker
        else "description = {unlabelled}"
    )
    fields = [
        "ENVI",
        description,
        f"samples = {samples}",
        f"lines = {lines}",
        "bands = 1",
        "data type = 12",
        "byte order = 0",
        "interleave = bil",
        "header offset = 0",
        "Class ID (0) = Pixel Not Labeled",
        "Class ID (1) = Normal Tissue",
        "Class ID (2) = Tumor Tissue",
        "Class ID (3) = Hypervascularized Tissue",
        "Class ID (4) = Background",
    ]
    return "\r".join(fields).encode("ascii")


def writeRecordedCaseFixture(
    caseFolder: Path,
    samples: int = TINY_DATASET_SAMPLES,
    lines: int = TINY_DATASET_LINES,
    bands: int = TINY_DATASET_BANDS,
    groundTruthMarker: str = RECORDED_DATABASE_MARKER,
    rawHeaderDescription: str = "",
) -> Path:
    """Write a tiny test folder laid out like a recorded database case.

    The arrays are counting placeholders, not imagery. Only the file set and the
    two header layouts copy a recorded case, because those are what the reader
    and the identification have to handle. Returns the resolved folder.
    """
    caseFolder = Path(caseFolder)
    caseFolder.mkdir(parents=True)

    shape = (bands, lines, samples)
    voxelCount = int(numpy.prod(shape))
    cubes = {
        "raw": numpy.arange(voxelCount, dtype=numpy.int64) % 40000 + 1200,
        "whiteReference": numpy.full(voxelCount, 51200),
        "darkReference": numpy.full(voxelCount, 1200),
    }
    headerBytes = buildRecordedRawHeader(samples, lines, bands, rawHeaderDescription).encode("ascii")
    for stem, values in cubes.items():
        (caseFolder / f"{stem}.hdr").write_bytes(headerBytes)
        (caseFolder / f"{stem}.dat").write_bytes(numpy.asarray(values, dtype="<u2").tobytes())

    (caseFolder / "gtMap").write_bytes(bytes(samples * lines * 2))
    (caseFolder / "gtMap.hdr").write_bytes(
        buildRecordedGroundTruthHeader(samples, lines, groundTruthMarker)
    )
    return caseFolder.resolve()


def folderFingerprint(folder: Path) -> dict[str, tuple[str, int, int]]:
    """Every file under a folder, with its SHA-256, size and modification time.

    The file list is part of the fingerprint, so an added or removed file
    changes it as surely as a rewritten or merely touched one.
    """
    folder = Path(folder)
    fingerprint = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            status = path.stat()
            fingerprint[path.relative_to(folder).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                status.st_size,
                status.st_mtime_ns,
            )
    return fingerprint
