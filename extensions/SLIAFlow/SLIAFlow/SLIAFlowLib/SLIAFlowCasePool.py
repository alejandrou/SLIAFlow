"""Choose which recorded HSI case a capture sends to UC1.

The acquisition is simulated: each Capture stands for a hyperspectral cube, and
the cube is a recorded case of the HSI Human Brain Database, read where it lies
in `input/bin/bin`. Nothing here writes to that folder. Choosing a case reads
only headers and file sizes; `readCube` reads the pixels of one chosen case, so
that the HS Cube panel can show the cube the capture stands for.

A case is used only when UC1 can run on it without silently reading the wrong
thing. `main.cu` trusts the header's band count when it reads the SVM model and
never checks how much it read, and it reads the three data files without
checking their sizes. So the checks are the ones `tools/simulators/stratum_sim`
applies in `envi.loadDataset`, `envi.assertDataFilesMatchHeader`,
`uc1_runner.assertRecordedCase` and `uc1_runner.Uc1Build.assertDatasetMatchesModel`,
restated here because a Slicer module cannot import that tooling.
"""

import logging
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The staged SVM model is sized for this many bands (uc1_runner.UC1_MODEL_BAND_COUNT).
UC1_MODEL_BAND_COUNT = 93

# Cases that are never picked, and why. `058-02` is the largest recorded case
# and has not been verified on this GPU yet.
DEFERRED_CASES = ("058-02",)
DEFERRED_REASON = "deferred until SLIA-029 verifies it"

# The three ENVI pairs UC1 opens, by stem.
CASE_FILE_STEMS = ("raw", "darkReference", "whiteReference")
# The one of them that is the acquired cube rather than a calibration reference.
CUBE_FILE_STEM = "raw"
# ENVI data type 12 is uint16, which is what UC1 reads.
ENVI_DATA_TYPE_UINT16 = "12"
BYTES_PER_SAMPLE = 2

# envi.RECORDED_DATASET_MARKER and envi.GROUND_TRUTH_HEADER_FILE_NAME: the
# database stamps its name into gtMap.hdr and nowhere else.
RECORDED_DATASET_MARKER = "HSI Human Brain Database"
GROUND_TRUTH_HEADER_FILE_NAME = "gtMap.hdr"
GROUND_TRUTH_FILE_NAME = "gtMap"

# gtMap is one band of labels rather than a cube, so it is stored bil, not bsq.
ENVI_INTERLEAVE_BIL = "bil"
GROUND_TRUTH_BAND_COUNT = 1

# The `Class ID (n)` legend gtMap.hdr carries, with the colour `writeKNNBMP`
# paints that same class with in svm.bmp and knn.bmp (FOUR_COLORS_MAP,
# BitmapWriter.hpp). The two are indexed alike, so a ground-truth pixel and a
# classified pixel of the same class are the same colour, and the label layer
# can be read against the result underneath it without a second legend.
#
# kmeans.bmp is painted from a different table with arbitrary cluster numbers
# and pca.bmp is not a classification, so neither is comparable this way.
GROUND_TRUTH_CLASSES = (
    (0, "Pixel Not Labeled", (255, 255, 255)),
    (1, "Normal Tissue", (0, 255, 0)),
    (2, "Tumor Tissue", (255, 0, 0)),
    (3, "Hypervascularized Tissue", (0, 0, 255)),
    (4, "Background", (0, 0, 0)),
)
HIGHEST_GROUND_TRUTH_CLASS_ID = max(classId for classId, _name, _colour in GROUND_TRUTH_CLASSES)

# Most of a recorded case is left unlabelled: across the 61 cases in
# `input/bin/bin`, between 0.0% and 16.2% of pixels carry a class. Class 0 is
# the absence of a label, not a class the classifiers can be scored against.
UNLABELLED_CLASS_ID = 0


@dataclass(frozen=True)
class RecordedCase:
    name: str
    folder: Path
    samples: int
    lines: int
    bands: int


class IncompatibleCaseError(ValueError):
    """The folder is not a recorded case UC1 can run on."""


class NoCompatibleCaseError(RuntimeError):
    """No recorded case in the input folder can be used."""


def parseEnviHeader(text: str) -> dict[str, str]:
    """Return an ENVI header's key/value entries, lower-case keys.

    The brace-delimited wavelength block is consumed and not returned: a
    recorded case closes it on its last value line and puts `lines` and
    `samples` after it, so it must be skipped exactly, not line by line.
    """
    values: dict[str, str] = {}
    insideBlock = False
    for rawLine in text.splitlines():
        line = rawLine.split(";", 1)[0].strip()
        if not line:
            continue
        if insideBlock:
            insideBlock = "}" not in line
            continue
        separatorIndex = line.find("=")
        if separatorIndex < 0:
            continue
        key = line[:separatorIndex].strip().lower()
        value = line[separatorIndex + 1:].strip()
        if value.startswith("{"):
            insideBlock = "}" not in value
            continue
        values[key] = value
    return values


def _headerDimensions(path: Path) -> tuple[int, int, int]:
    if not path.is_file():
        raise IncompatibleCaseError(f"{path.name} is missing.")
    values = parseEnviHeader(path.read_text(encoding="ascii", errors="replace"))
    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise IncompatibleCaseError(f"{path.name} does not declare {', '.join(missing)}.")
    try:
        dimensions = tuple(int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise IncompatibleCaseError(f"{path.name} has a dimension that is not an integer.") from error
    if any(value <= 0 for value in dimensions):
        raise IncompatibleCaseError(f"{path.name} declares a dimension that is not positive.")
    if values.get("data type") != ENVI_DATA_TYPE_UINT16:
        raise IncompatibleCaseError(
            f"{path.name} declares data type {values.get('data type')}, not 12 (uint16)."
        )
    if values.get("interleave", "").lower() != "bsq":
        raise IncompatibleCaseError(
            f"{path.name} declares interleave {values.get('interleave')}, not bsq."
        )
    if values.get("byte order") != "0":
        raise IncompatibleCaseError(
            f"{path.name} declares byte order {values.get('byte order')}, not 0 (little-endian)."
        )
    if values.get("header offset", "0") != "0":
        raise IncompatibleCaseError(
            f"{path.name} declares a header offset of {values.get('header offset')}, not 0."
        )
    return dimensions


def loadRecordedCase(folder) -> RecordedCase:
    """Describe a case folder UC1 can run on, or say why it cannot."""
    folder = Path(folder)
    if not folder.is_dir():
        raise IncompatibleCaseError(f"{folder} is not a folder.")

    dimensions = None
    firstHeader = None
    for stem in CASE_FILE_STEMS:
        headerPath = folder / f"{stem}.hdr"
        current = _headerDimensions(headerPath)
        if dimensions is None:
            dimensions, firstHeader = current, headerPath.name
        elif current != dimensions:
            raise IncompatibleCaseError(
                f"{headerPath.name} describes {current[0]} x {current[1]} x {current[2]} but "
                f"{firstHeader} describes {dimensions[0]} x {dimensions[1]} x {dimensions[2]} "
                "(samples x lines x bands)."
            )
    samples, lines, bands = dimensions

    if bands != UC1_MODEL_BAND_COUNT:
        raise IncompatibleCaseError(
            f"The case has {bands} bands, but the staged SVM model is sized for "
            f"{UC1_MODEL_BAND_COUNT}. UC1 would classify against truncated or uninitialised "
            "weights."
        )

    expectedBytes = samples * lines * bands * BYTES_PER_SAMPLE
    for stem in CASE_FILE_STEMS:
        dataPath = folder / f"{stem}.dat"
        if not dataPath.is_file():
            raise IncompatibleCaseError(f"{dataPath.name} is missing.")
        actualBytes = dataPath.stat().st_size
        if actualBytes != expectedBytes:
            raise IncompatibleCaseError(
                f"{dataPath.name} is {actualBytes} bytes but the headers describe {expectedBytes}."
            )

    groundTruthHeader = folder / GROUND_TRUTH_HEADER_FILE_NAME
    if not groundTruthHeader.is_file() or RECORDED_DATASET_MARKER not in groundTruthHeader.read_text(
        encoding="ascii", errors="replace"
    ):
        raise IncompatibleCaseError(
            f"The folder does not identify as a case of the {RECORDED_DATASET_MARKER}: its "
            f"{GROUND_TRUTH_HEADER_FILE_NAME} does not carry that marker."
        )

    return RecordedCase(folder.name, folder.resolve(), samples, lines, bands)


def readCube(case) -> np.ndarray:
    """Return a case's acquired cube as a (bands, lines, samples) uint16 array.

    `loadRecordedCase` has already checked the header and the file size, but the
    file lies outside this repository and may have changed since, so the size is
    checked again here rather than reshaping whatever is on disk. BSQ stores one
    whole band after another, which is already the band-major order a Slicer
    volume wants, so the bytes are reshaped and never rearranged.
    """
    path = Path(case.folder) / f"{CUBE_FILE_STEM}.dat"
    expectedBytes = case.samples * case.lines * case.bands * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise IncompatibleCaseError(
            f"{path.name} is {actualBytes} bytes but the headers describe {expectedBytes}."
        )
    # Byte order 0, checked when the case was accepted.
    values = np.fromfile(path, dtype="<u2")
    return values.reshape(case.bands, case.lines, case.samples)


def _groundTruthHeaderDimensions(path: Path, case) -> tuple[int, int]:
    """Check gtMap.hdr against the case, and return its (lines, samples).

    gtMap has its own header, so its geometry is read from it rather than
    assumed from raw.hdr, and then required to agree. A ground truth that does
    not agree cannot be laid over a result at all, so it is refused instead of
    being stretched or cropped to fit.
    """
    if not path.is_file():
        raise IncompatibleCaseError(f"{path.name} is missing.")
    values = parseEnviHeader(path.read_text(encoding="ascii", errors="replace"))
    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise IncompatibleCaseError(f"{path.name} does not declare {', '.join(missing)}.")
    try:
        samples, lines, bands = (int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise IncompatibleCaseError(f"{path.name} has a dimension that is not an integer.") from error
    if bands != GROUND_TRUTH_BAND_COUNT:
        raise IncompatibleCaseError(
            f"{path.name} declares {bands} bands, not {GROUND_TRUTH_BAND_COUNT}: it is not a "
            "single map of labels."
        )
    if (samples, lines) != (case.samples, case.lines):
        raise IncompatibleCaseError(
            f"{path.name} describes {samples} x {lines} but the case is "
            f"{case.samples} x {case.lines} (samples x lines)."
        )
    if values.get("data type") != ENVI_DATA_TYPE_UINT16:
        raise IncompatibleCaseError(
            f"{path.name} declares data type {values.get('data type')}, not 12 (uint16)."
        )
    if values.get("interleave", "").lower() != ENVI_INTERLEAVE_BIL:
        raise IncompatibleCaseError(
            f"{path.name} declares interleave {values.get('interleave')}, not "
            f"{ENVI_INTERLEAVE_BIL}."
        )
    if values.get("byte order") != "0":
        raise IncompatibleCaseError(
            f"{path.name} declares byte order {values.get('byte order')}, not 0 (little-endian)."
        )
    if values.get("header offset", "0") != "0":
        raise IncompatibleCaseError(
            f"{path.name} declares a header offset of {values.get('header offset')}, not 0."
        )
    return lines, samples


def readGroundTruth(case) -> np.ndarray:
    """Return a case's ground truth as a (lines, samples) uint16 array of class IDs.

    This is the database's own labelling, not anything UC1 produced: it is read
    only to be shown beside a result, never fed back into the run. One band of
    bil is a plain row-major image, so the bytes are reshaped and never
    rearranged, which puts row 0 at the top -- the same way `readUc1Bmp` hands
    back a decoded output, so the two line up pixel for pixel.

    A class ID outside the legend would index past the colour table, so the
    values are checked rather than clamped.
    """
    headerPath = Path(case.folder) / GROUND_TRUTH_HEADER_FILE_NAME
    lines, samples = _groundTruthHeaderDimensions(headerPath, case)
    path = Path(case.folder) / GROUND_TRUTH_FILE_NAME
    if not path.is_file():
        raise IncompatibleCaseError(f"{path.name} is missing.")
    expectedBytes = samples * lines * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise IncompatibleCaseError(
            f"{path.name} is {actualBytes} bytes but {headerPath.name} describes {expectedBytes}."
        )
    # Byte order 0, checked just above.
    labels = np.fromfile(path, dtype="<u2").reshape(lines, samples)
    highest = int(labels.max()) if labels.size else 0
    if highest > HIGHEST_GROUND_TRUTH_CLASS_ID:
        raise IncompatibleCaseError(
            f"{path.name} holds class ID {highest}, but {headerPath.name} only legends "
            f"0 to {HIGHEST_GROUND_TRUTH_CLASS_ID}."
        )
    return labels


def discoverCases(inputRoot, deferredCases=DEFERRED_CASES):
    """Return the usable cases, and a reason for every folder that was not used."""
    root = Path(inputRoot)
    cases: list[RecordedCase] = []
    rejected: dict[str, str] = {}
    if not root.is_dir():
        return cases, rejected
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in deferredCases:
            rejected[child.name] = DEFERRED_REASON
            continue
        try:
            cases.append(loadRecordedCase(child))
        except (IncompatibleCaseError, OSError) as error:
            rejected[child.name] = str(error)
    return cases, rejected


class CasePool:
    """Every usable case once, in a shuffled order, then a new shuffle.

    The folder is read again at every reshuffle, so a case added or repaired
    during the session joins the next round. The order lives only as long as
    the pool.
    """

    def __init__(self, inputRoot, deferredCases=DEFERRED_CASES, rng=None) -> None:
        self.inputRoot = Path(inputRoot)
        self.deferredCases = tuple(deferredCases)
        self.rejected: dict[str, str] = {}
        self._rng = rng if rng is not None else random.Random()
        self._queue: list[RecordedCase] = []
        self._lastName = None

    def nextCase(self) -> RecordedCase:
        if not self._queue:
            self._refill()
        case = self._queue.pop(0)
        self._lastName = case.name
        return case

    def _refill(self) -> None:
        cases, self.rejected = discoverCases(self.inputRoot, self.deferredCases)
        for name, reason in self.rejected.items():
            logging.info("SLIAFlow: recorded case %s is not used: %s", name, reason)
        if not cases:
            raise NoCompatibleCaseError(
                f"No compatible recorded case was found in {self.inputRoot}. Put the HSI Human "
                "Brain Database cases there; each needs raw, darkReference and whiteReference "
                f"with {UC1_MODEL_BAND_COUNT}-band uint16 BSQ headers."
            )
        order = list(cases)
        self._rng.shuffle(order)
        # A new round never starts with the case that ended the last one.
        if len(order) > 1 and order[0].name == self._lastName:
            order[0], order[1] = order[1], order[0]
        self._queue = order
