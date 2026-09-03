"""ENVI/BSQ dataset writing and reading, shaped by what the consumers accept.

One dataset has three consumers: the genuine UC1 binary, the real acquisition
application's simulated-capture mode, and our own stand-in classifier. Their
parsers disagree about almost everything except the few keys below, so the
header is written to satisfy the strictest reading of each.
"""

from __future__ import annotations

import datetime
import struct
from pathlib import Path

import numpy

from .contract import DatasetRef

RAW_DATA_FILE_NAME = "raw.dat"
WHITE_REFERENCE_FILE_NAME = "whiteReference.dat"
DARK_REFERENCE_FILE_NAME = "darkReference.dat"
HEADER_FILE_NAME = "raw.hdr"

# `data_loader.hpp` defines MAX_PATH_LENGTH as 128, and the same buffer is used
# both for the constructed file paths and for each header line read by fgets.
UC1_MAX_PATH_LENGTH = 128

# ENVI data type 12 is uint16, which is what both consumers require.
ENVI_DATA_TYPE_UINT16 = 12
BYTES_PER_SAMPLE = 2

DATASET_MARKER = "STRATUM SIMULATED CUBE"
DATASET_FOLDER_PREFIX = "sim-"
DATASET_FOLDER_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# An SVM model sized for this dataset's band count. For four classes there are
# (4 * 3) / 2 = 6 one-against-one binary classifiers, and `w_vector.bin` holds
# one float32 weight per band per classifier.
#
# It is written *inside* the dataset folder, which is not where UC1 looks:
# `main.cu` opens the five model files as the literal relative paths
# `../../svm_model/*.bin`, resolved against the binary's working directory and
# not against the dataset argument at all. So a dataset with a non-default band
# count needs its model placed where that relative path lands before UC1 can
# read it. Keeping the model with the dataset it was sized for is the honest
# arrangement; reconciling it with UC1's working directory is SLIA-013's job,
# where the binary is actually invoked.
SVM_MODEL_DIRECTORY_NAME = "svm_model"
SVM_CLASS_COUNT = 4
SVM_BINARY_CLASSIFIER_COUNT = (SVM_CLASS_COUNT * (SVM_CLASS_COUNT - 1)) // 2
WEIGHT_VECTOR_FILE_NAME = "w_vector.bin"
PROBABILITY_A_FILE_NAME = "ProbA.bin"
PROBABILITY_B_FILE_NAME = "ProbB.bin"
RHO_FILE_NAME = "rho.bin"
LABEL_FILE_NAME = "label.bin"

WAVELENGTH_FORMAT = "{:.4f}"


class DatasetWriteError(RuntimeError):
    """The dataset was not written, because writing it would not be safe."""


class DatasetReadError(RuntimeError):
    """The folder is not a dataset this module can read back."""


def datasetFolderName(moment: datetime.datetime | None = None) -> str:
    """Return the `sim-YYYYMMDD-HHMMSS` folder name for a moment in time."""
    stamp = (moment or datetime.datetime.now()).strftime(DATASET_FOLDER_TIMESTAMP_FORMAT)
    return f"{DATASET_FOLDER_PREFIX}{stamp}"


def uc1WhiteReferencePathLength(datasetFolder: Path) -> int:
    """Return the byte length UC1's snprintf would need for the white reference.

    `parse_arguments` builds `"%s/whiteReference.dat"` into a 128-byte buffer.
    Anything longer is truncated in silence, and the pipeline then fails on a
    path that looks almost right.
    """
    return len(f"{datasetFolder.resolve()}/{WHITE_REFERENCE_FILE_NAME}".encode("utf-8"))


def buildHeaderText(samples: int, lines: int, bands: int, wavelengthsNm: numpy.ndarray) -> str:
    """Emit a header both consumers parse correctly.

    Three constraints drive the layout:

    - `samples`, `lines` and `bands` sit at column 0 before the wavelength
      block, because UC1's parser scans line by line and stops after three hits;
    - no line contains a `;`, because HSCubeLoader treats it as a comment start
      and would truncate the line carrying it;
    - every line stays under 128 bytes, because UC1 reads them with
      `fgets(line, MAX_PATH_LENGTH, file)` and a longer line is split mid-parse.
    """
    headerLines = [
        "ENVI",
        f"description = {{{DATASET_MARKER} - synthetic, non-clinical}}",
        f"samples = {samples}",
        f"lines = {lines}",
        f"bands = {bands}",
        "header offset = 0",
        "file type = ENVI Standard",
        f"data type = {ENVI_DATA_TYPE_UINT16}",
        "interleave = bsq",
        "byte order = 0",
        f"data file = {RAW_DATA_FILE_NAME}",
        "wavelength units = Nanometers",
        "wavelength = {",
    ]

    formatted = [WAVELENGTH_FORMAT.format(float(value)) for value in wavelengthsNm]
    headerLines.append(formatted[0])
    headerLines.extend(f",{value}" for value in formatted[1:])
    headerLines.append("}")

    return "\n".join(headerLines) + "\n"


def parseHeaderText(headerText: str) -> tuple[dict[str, str], tuple[float, ...]]:
    """Return the key/value entries and the wavelength list from a header."""
    values: dict[str, str] = {}
    wavelengths: list[float] = []
    insideWavelengthBlock = False

    for rawLine in headerText.splitlines():
        line = rawLine.split(";", 1)[0].strip()
        if not line:
            continue

        if insideWavelengthBlock:
            if line.startswith("}"):
                insideWavelengthBlock = False
                continue
            for token in line.lstrip(",").split(","):
                token = token.strip().rstrip("}")
                if token:
                    wavelengths.append(float(token))
            continue

        separatorIndex = line.find("=")
        if separatorIndex < 0:
            continue

        key = line[:separatorIndex].strip().lower()
        value = line[separatorIndex + 1:].strip()
        if key == "wavelength":
            insideWavelengthBlock = True
            remainder = value.lstrip("{").strip()
            if remainder:
                for token in remainder.split(","):
                    token = token.strip().rstrip("}")
                    if token:
                        wavelengths.append(float(token))
            continue
        values[key] = value

    return values, tuple(wavelengths)


def _assertShapesAgree(
    rawCube: numpy.ndarray, whiteCube: numpy.ndarray, darkCube: numpy.ndarray
) -> None:
    if rawCube.ndim != 3:
        raise DatasetWriteError(
            f"Expected a (bands, lines, samples) cube, got shape {rawCube.shape}."
        )
    if not (rawCube.shape == whiteCube.shape == darkCube.shape):
        raise DatasetWriteError(
            "The raw cube and both references must have the same shape, got "
            f"{rawCube.shape}, {whiteCube.shape} and {darkCube.shape}."
        )


def _assertTargetIsSafe(datasetFolder: Path) -> None:
    pathLength = uc1WhiteReferencePathLength(datasetFolder)
    if pathLength >= UC1_MAX_PATH_LENGTH:
        raise DatasetWriteError(
            f"The dataset path is too long for UC1: "
            f"'{datasetFolder.resolve()}/{WHITE_REFERENCE_FILE_NAME}' needs {pathLength} bytes "
            f"and UC1's MAX_PATH_LENGTH buffer is {UC1_MAX_PATH_LENGTH}. "
            "Choose a shorter dataset root."
        )

    if not datasetFolder.exists():
        return
    if not datasetFolder.is_dir():
        raise DatasetWriteError(f"Refusing to write to {datasetFolder}: it is not a directory.")

    existingHeader = datasetFolder / HEADER_FILE_NAME
    if existingHeader.is_file():
        headerText = existingHeader.read_text(encoding="ascii", errors="replace")
        if DATASET_MARKER not in headerText:
            raise DatasetWriteError(
                f"Refusing to overwrite {datasetFolder}: its {HEADER_FILE_NAME} does not carry "
                f"the '{DATASET_MARKER}' marker, so this simulator did not write it."
            )
        return

    # No header at all. An empty folder is a fresh target, but a folder holding
    # anything else is somebody's: the marker check cannot clear it, because
    # there is no marker to read, and `raw.dat`, `whiteReference.dat` and
    # `darkReference.dat` would be replaced regardless. `--dataset-folder`
    # accepts an arbitrary path, so this is reachable by a plain typo.
    occupants = sorted(entry.name for entry in datasetFolder.iterdir())
    if occupants:
        raise DatasetWriteError(
            f"Refusing to overwrite {datasetFolder}: it has no {HEADER_FILE_NAME} to carry the "
            f"'{DATASET_MARKER}' marker, and it is not empty (holds {', '.join(occupants[:5])}"
            f"{', ...' if len(occupants) > 5 else ''}). "
            "Choose an empty folder or one this simulator wrote."
        )


def _writeBsq(path: Path, cube: numpy.ndarray) -> None:
    """Write a (bands, lines, samples) uint16 cube as BSQ.

    The BSQ index UC1 uses is `band * totalPixels + line * samples + sample`,
    which is exactly this array's C-order layout, so no reordering is needed.
    """
    if cube.dtype != numpy.uint16:
        raise DatasetWriteError(f"Expected a uint16 cube, got {cube.dtype}.")
    path.write_bytes(numpy.ascontiguousarray(cube, dtype="<u2").tobytes())


def writeSvmModel(modelFolder: Path, bands: int) -> Path:
    """Write an SVM model sized for this cube's band count.

    UC1 reads `w_vector.bin` with an outer loop over the binary classifiers and
    an inner loop over the bands, so the file is classifier-major. The shipped
    model is 2232 bytes, which is 93 bands times 6 classifiers times 4 bytes -
    the second confirmation that the sensor has 93 bands.

    See the note on SVM_MODEL_DIRECTORY_NAME: UC1 opens this model by a fixed
    relative path, not from the dataset folder.
    """
    modelFolder.mkdir(parents=True, exist_ok=True)

    weights = numpy.linspace(
        -1.0, 1.0, SVM_BINARY_CLASSIFIER_COUNT * bands, dtype=numpy.float32
    ).reshape(SVM_BINARY_CLASSIFIER_COUNT, bands)
    weightVectorPath = modelFolder / WEIGHT_VECTOR_FILE_NAME
    weightVectorPath.write_bytes(numpy.ascontiguousarray(weights, dtype="<f4").tobytes())

    expectedBytes = bands * SVM_BINARY_CLASSIFIER_COUNT * 4
    actualBytes = weightVectorPath.stat().st_size
    if actualBytes != expectedBytes:
        raise DatasetWriteError(
            f"{WEIGHT_VECTOR_FILE_NAME} is {actualBytes} bytes but UC1 will read "
            f"{expectedBytes} (bands {bands} * {SVM_BINARY_CLASSIFIER_COUNT} classifiers * 4)."
        )

    probabilityA = numpy.full(SVM_BINARY_CLASSIFIER_COUNT, -1.0, dtype="<f4")
    probabilityB = numpy.zeros(SVM_BINARY_CLASSIFIER_COUNT, dtype="<f4")
    rho = numpy.zeros(SVM_BINARY_CLASSIFIER_COUNT, dtype="<f4")
    (modelFolder / PROBABILITY_A_FILE_NAME).write_bytes(probabilityA.tobytes())
    (modelFolder / PROBABILITY_B_FILE_NAME).write_bytes(probabilityB.tobytes())
    (modelFolder / RHO_FILE_NAME).write_bytes(rho.tobytes())
    (modelFolder / LABEL_FILE_NAME).write_bytes(
        struct.pack(f"<{SVM_CLASS_COUNT}i", *range(1, SVM_CLASS_COUNT + 1))
    )

    return weightVectorPath


def writeDataset(
    datasetFolder: Path,
    rawCube: numpy.ndarray,
    whiteCube: numpy.ndarray,
    darkCube: numpy.ndarray,
    wavelengthsNm: numpy.ndarray,
) -> DatasetRef:
    """Write a complete dataset and return a reference to it.

    The interlocks run before anything is created, so a refusal leaves the
    filesystem untouched.
    """
    datasetFolder = Path(datasetFolder)
    _assertShapesAgree(rawCube, whiteCube, darkCube)
    _assertTargetIsSafe(datasetFolder)

    bands, lines, samples = rawCube.shape
    if wavelengthsNm.size != bands:
        raise DatasetWriteError(
            f"The cube has {bands} bands but {wavelengthsNm.size} wavelengths were supplied."
        )

    headerText = buildHeaderText(samples, lines, bands, wavelengthsNm)
    for lineNumber, line in enumerate(headerText.splitlines(), start=1):
        if len(line.encode("utf-8")) >= UC1_MAX_PATH_LENGTH:
            raise DatasetWriteError(
                f"Header line {lineNumber} is {len(line)} bytes, and UC1 reads header lines into "
                f"a {UC1_MAX_PATH_LENGTH}-byte buffer."
            )

    datasetFolder.mkdir(parents=True, exist_ok=True)
    (datasetFolder / HEADER_FILE_NAME).write_text(headerText, encoding="ascii", newline="\n")
    _writeBsq(datasetFolder / RAW_DATA_FILE_NAME, rawCube)
    _writeBsq(datasetFolder / WHITE_REFERENCE_FILE_NAME, whiteCube)
    _writeBsq(datasetFolder / DARK_REFERENCE_FILE_NAME, darkCube)
    writeSvmModel(datasetFolder / SVM_MODEL_DIRECTORY_NAME, bands)

    _, roundTrippedWavelengths = parseHeaderText(headerText)
    return DatasetRef(
        folder=datasetFolder.resolve(),
        samples=samples,
        lines=lines,
        bands=bands,
        wavelengthsNm=roundTrippedWavelengths,
        simulated=True,
    )


def loadDataset(folder: Path) -> DatasetRef:
    """Build a DatasetRef from an existing dataset folder."""
    folder = Path(folder).resolve()
    headerPath = folder / HEADER_FILE_NAME
    if not headerPath.is_file():
        raise DatasetReadError(f"{folder} has no {HEADER_FILE_NAME}.")

    headerText = headerPath.read_text(encoding="ascii", errors="replace")
    values, wavelengths = parseHeaderText(headerText)

    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise DatasetReadError(f"{headerPath} is missing: {', '.join(missing)}.")

    return DatasetRef(
        folder=folder,
        samples=int(values["samples"]),
        lines=int(values["lines"]),
        bands=int(values["bands"]),
        wavelengthsNm=wavelengths,
        simulated=DATASET_MARKER in headerText,
    )


def _readBsq(path: Path, bands: int, lines: int, samples: int) -> numpy.ndarray:
    expectedBytes = bands * lines * samples * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise DatasetReadError(
            f"{path} is {actualBytes} bytes but the header describes {expectedBytes}."
        )
    return numpy.frombuffer(path.read_bytes(), dtype="<u2").reshape(bands, lines, samples)


def loadCalibratedCube(datasetRef: DatasetRef) -> numpy.ndarray:
    """Read a dataset and apply UC1's calibration to it."""
    # Imported here so `contract` stays free of a spectra dependency it does not
    # otherwise need.
    from . import spectra

    shape = (datasetRef.bands, datasetRef.lines, datasetRef.samples)
    rawCube = _readBsq(datasetRef.folder / RAW_DATA_FILE_NAME, *shape)
    whiteCube = _readBsq(datasetRef.folder / WHITE_REFERENCE_FILE_NAME, *shape)
    darkCube = _readBsq(datasetRef.folder / DARK_REFERENCE_FILE_NAME, *shape)
    return spectra.calibrate(rawCube, darkCube, whiteCube)
