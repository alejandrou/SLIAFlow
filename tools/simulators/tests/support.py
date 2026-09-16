"""Shared helpers for the simulator tests.

Every dataset folder a test builds is laid out like a recorded case of the HSI
Human Brain Database and holds counting placeholders, not imagery. The one test
that needs a real cube reads `RECORDED_CASE_004_02` where it lies.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
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

TINY_DATASET_SAMPLES = 8
TINY_DATASET_LINES = 4
TINY_DATASET_BANDS = 6

# The recorded case the genuine UC1 integration test classifies. Read, never
# written; `input/` is the approved location in the medical-data policy.
RECORDED_CASE_004_02 = REPOSITORY_ROOT / "input" / "bin" / "bin" / "004-02"


UC1_SVM_MODEL_PATH = UC1_PARAMETERS_PATH.parents[2] / "svm_model"

# The staged build root the build script writes, used by the tests that exercise
# the real binary. Absent until `scripts/development/build-uc1.ps1` has run.
STAGED_UC1_BUILD_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "UC1"


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


# The marker the HSI Human Brain Database stamps into every case's `gtMap.hdr`.
# Read from all 61 cases in `input/bin/bin` on 2026-09-11 and again on
# 2026-09-13. It is not in `raw.hdr`.
RECORDED_DATABASE_MARKER = "HSI Human Brain Database"

# Every recorded case shares this grid: 440 to 900 nm in 5 nm steps, written six
# values to a line.
RECORDED_FIRST_WAVELENGTH_NM = 440
RECORDED_WAVELENGTH_STEP_NM = 5
RECORDED_VALUES_PER_WAVELENGTH_LINE = 6


def buildRecordedRawHeader(
    samples: int,
    lines: int,
    bands: int,
    description: str = "",
    wavelengthsNm: Sequence[float] | None = None,
) -> str:
    """Reproduce the layout every recorded `raw.hdr` has.

    The two properties a reader has to survive are reproduced rather than
    tidied: the wavelength block is closed by a `}` on its last value line, and
    `lines` and `samples` come after the block. Value lines end in `", "` before
    the newline, as they do on disk. The recorded grid is used unless a test
    names other wavelengths.
    """
    if wavelengthsNm is None:
        wavelengths = [
            str(RECORDED_FIRST_WAVELENGTH_NM + RECORDED_WAVELENGTH_STEP_NM * index)
            for index in range(bands)
        ]
    else:
        wavelengths = [f"{float(value):g}" for value in wavelengthsNm]
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
    wavelengthsNm: Sequence[float] | None = None,
    rawCube: numpy.ndarray | None = None,
    whiteLevel: int = 51200,
    darkLevel: int = 1200,
) -> Path:
    """Write a tiny test folder laid out like a recorded database case.

    The arrays are counting placeholders, not imagery, unless a test passes the
    exact `rawCube` and reference levels an arithmetic check needs. Only the file
    set and the two header layouts copy a recorded case, because those are what
    the reader and the identification have to handle. Returns the resolved folder.
    """
    caseFolder = Path(caseFolder)
    caseFolder.mkdir(parents=True)

    if wavelengthsNm is not None:
        bands = len(wavelengthsNm)
    shape = (bands, lines, samples)
    voxelCount = int(numpy.prod(shape))
    if rawCube is None:
        rawValues = numpy.arange(voxelCount, dtype=numpy.int64) % 40000 + 1200
    else:
        if rawCube.shape != shape:
            raise ValueError(f"rawCube has shape {rawCube.shape}, not {shape}.")
        rawValues = rawCube.reshape(-1)
    cubes = {
        "raw": rawValues,
        "whiteReference": numpy.full(voxelCount, whiteLevel),
        "darkReference": numpy.full(voxelCount, darkLevel),
    }
    headerBytes = buildRecordedRawHeader(
        samples, lines, bands, rawHeaderDescription, wavelengthsNm
    ).encode("ascii")
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
