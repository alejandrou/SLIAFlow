"""ENVI/BSQ dataset reading, and the identification of a recorded case.

Nothing here writes. Every dataset the tooling reads is a case of the public HSI
Human Brain Database, opened where it lies.
"""

from __future__ import annotations

from pathlib import Path

import numpy

from .contract import DatasetRef

RAW_DATA_FILE_NAME = "raw.dat"
WHITE_REFERENCE_FILE_NAME = "whiteReference.dat"
DARK_REFERENCE_FILE_NAME = "darkReference.dat"
HEADER_FILE_NAME = "raw.hdr"

# ENVI data type 12 is uint16, which is what UC1 requires.
BYTES_PER_SAMPLE = 2

# The HSI Human Brain Database stamps this into the description of every case's
# `gtMap.hdr`, and not into `raw.hdr`: all 61 cases in `input/bin/bin` were read on
# 2026-09-11 and 2026-09-13. Only that header is read for it. `gtMap` itself is
# the database's own labelling and is never opened here.
RECORDED_DATASET_MARKER = "HSI Human Brain Database"
GROUND_TRUTH_HEADER_FILE_NAME = "gtMap.hdr"

# The layout of UC1's SVM model. For four classes there are (4 * 3) / 2 = 6
# one-against-one binary classifiers, and `w_vector.bin` holds one float32
# weight per band per classifier. `main.cu` opens the five files as the literal
# relative paths `../../svm_model/*.bin`, resolved against the binary's working
# directory and not against the dataset argument; `uc1_runner` checks their
# sizes there.
SVM_MODEL_DIRECTORY_NAME = "svm_model"
SVM_CLASS_COUNT = 4
SVM_BINARY_CLASSIFIER_COUNT = (SVM_CLASS_COUNT * (SVM_CLASS_COUNT - 1)) // 2
WEIGHT_VECTOR_FILE_NAME = "w_vector.bin"
PROBABILITY_A_FILE_NAME = "ProbA.bin"
PROBABILITY_B_FILE_NAME = "ProbB.bin"
RHO_FILE_NAME = "rho.bin"
LABEL_FILE_NAME = "label.bin"


class DatasetReadError(RuntimeError):
    """The folder is not a dataset this module can read back."""


def parseHeaderText(headerText: str) -> tuple[dict[str, str], tuple[float, ...]]:
    """Return the key/value entries and the wavelength list from a header.

    Every recorded database case closes the block on its last value line
    (`890, 895,  900}`) and puts `lines` and `samples` after it. A header may
    also close it with a `}` on a line of its own. So the block ends on
    whichever line carries the brace, and key order does not matter.

    A wavelength that is not a number raises `DatasetReadError`, which every
    caller handles, rather than a bare `ValueError` that escapes all of them.
    """
    values: dict[str, str] = {}
    wavelengths: list[float] = []
    insideWavelengthBlock = False

    for rawLine in headerText.splitlines():
        line = rawLine.split(";", 1)[0].strip()
        if not line:
            continue

        if not insideWavelengthBlock:
            separatorIndex = line.find("=")
            if separatorIndex < 0:
                continue
            key = line[:separatorIndex].strip().lower()
            value = line[separatorIndex + 1:].strip()
            if key != "wavelength":
                values[key] = value
                continue
            insideWavelengthBlock = True
            line = value.lstrip("{")

        closesBlock = "}" in line
        for token in line.split("}", 1)[0].split(","):
            token = token.strip()
            if token:
                wavelengths.append(_parseWavelength(token))
        if closesBlock:
            insideWavelengthBlock = False

    return values, tuple(wavelengths)


def _parseWavelength(token: str) -> float:
    try:
        return float(token)
    except ValueError as error:
        raise DatasetReadError(f"wavelength {token!r} is not a number.") from error


def isRecordedDatabaseCase(folder: Path) -> bool:
    """Whether a folder is a case of the HSI Human Brain Database.

    Read from the data rather than from a flag, so there is nothing to pass and
    nothing to forget. Only the sibling `gtMap.hdr` counts: the marker anywhere
    else, `raw.hdr` included, identifies nothing.
    """
    groundTruthHeader = Path(folder) / GROUND_TRUTH_HEADER_FILE_NAME
    if not groundTruthHeader.is_file():
        return False
    headerText = groundTruthHeader.read_text(encoding="ascii", errors="replace")
    return RECORDED_DATASET_MARKER in headerText


def loadDataset(folder: Path) -> DatasetRef:
    """Build a DatasetRef from an existing dataset folder, reading headers only.

    `recorded` is set for a database case. Any other folder loads with it false,
    and it is each consumer's interlock that refuses it.
    """
    folder = Path(folder).resolve()
    headerPath = folder / HEADER_FILE_NAME
    if not headerPath.is_file():
        raise DatasetReadError(f"{folder} has no {HEADER_FILE_NAME}.")

    headerText = headerPath.read_text(encoding="ascii", errors="replace")
    try:
        values, wavelengths = parseHeaderText(headerText)
    except DatasetReadError as error:
        raise DatasetReadError(f"{headerPath} cannot be read: {error}") from error

    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise DatasetReadError(f"{headerPath} is missing: {', '.join(missing)}.")

    try:
        samples, lines, bands = (int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise DatasetReadError(f"{headerPath} has a dimension that is not an integer: {error}.") from error

    return DatasetRef(
        folder=folder,
        samples=samples,
        lines=lines,
        bands=bands,
        wavelengthsNm=wavelengths,
        recorded=isRecordedDatabaseCase(folder),
    )


def assertDataFilesMatchHeader(datasetRef: DatasetRef) -> None:
    """Check the three data files are the size the header describes, reading none of them."""
    expectedBytes = datasetRef.bands * datasetRef.lines * datasetRef.samples * BYTES_PER_SAMPLE
    for fileName in (RAW_DATA_FILE_NAME, WHITE_REFERENCE_FILE_NAME, DARK_REFERENCE_FILE_NAME):
        path = datasetRef.folder / fileName
        if not path.is_file():
            raise DatasetReadError(f"{path} is missing.")
        actualBytes = path.stat().st_size
        if actualBytes != expectedBytes:
            raise DatasetReadError(
                f"{path} is {actualBytes} bytes but the header describes {expectedBytes}."
            )


def loadRawCube(datasetRef: DatasetRef) -> numpy.ndarray:
    """Read the raw counts as a (bands, lines, samples) uint16 array.

    The file is opened for reading and nothing else. The array is a read-only
    view of the bytes as they are on disk: uncalibrated, unrotated, unscaled.
    """
    return _readBsq(
        datasetRef.folder / RAW_DATA_FILE_NAME,
        datasetRef.bands,
        datasetRef.lines,
        datasetRef.samples,
    )


def _readBsq(path: Path, bands: int, lines: int, samples: int) -> numpy.ndarray:
    expectedBytes = bands * lines * samples * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise DatasetReadError(
            f"{path} is {actualBytes} bytes but the header describes {expectedBytes}."
        )
    return numpy.frombuffer(path.read_bytes(), dtype="<u2").reshape(bands, lines, samples)
