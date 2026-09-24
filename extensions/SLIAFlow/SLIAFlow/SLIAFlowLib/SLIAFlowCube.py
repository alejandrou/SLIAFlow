"""Describe and read the one cube a capture sends to UC1.

The acquisition is simulated: each Capture stands for a hyperspectral cube, and
the cube is the one configured folder (`SLIAFlowLogic.cubeFolder`), read where
it lies under `input/`. Until SLIA-033 that folder is a recorded case of the HSI
Human Brain Database kept as the UC1 reference (ADR-0004 decision 1). Nothing
here writes to it. Describing the cube reads only headers and file sizes;
`readCube` reads its pixels, so that the HS Cube panel can show the cube the
capture stands for.

A case is used only when UC1 can run on it without silently reading the wrong
thing. `main.cu` trusts the header's band count when it reads the SVM model and
never checks how much it read, and it reads the three data files without
checking their sizes. So the checks are the ones `tools/simulators/stratum_sim`
applies in `envi.loadDataset`, `envi.assertDataFilesMatchHeader`,
`uc1_runner.assertRecordedCase` and `uc1_runner.Uc1Build.assertDatasetMatchesModel`,
restated here because a Slicer module cannot import that tooling.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

# The staged SVM model is sized for this many bands (uc1_runner.UC1_MODEL_BAND_COUNT).
UC1_MODEL_BAND_COUNT = 93

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

# Most of a recorded case is left unlabelled: across the 61 cases of the
# database, between 0.0% and 16.2% of pixels carry a class. Class 0 is
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
        raise IncompatibleCaseError(_("{file} is missing.").format(file=path.name))
    values = parseEnviHeader(path.read_text(encoding="ascii", errors="replace"))
    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise IncompatibleCaseError(_("{file} does not declare {keys}.").format(
            file=path.name, keys=", ".join(missing)))
    try:
        dimensions = tuple(int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise IncompatibleCaseError(_("{file} has a dimension that is not an integer.").format(
            file=path.name)) from error
    if any(value <= 0 for value in dimensions):
        raise IncompatibleCaseError(_("{file} declares a dimension that is not positive.").format(
            file=path.name))
    if values.get("data type") != ENVI_DATA_TYPE_UINT16:
        raise IncompatibleCaseError(_("{file} declares data type {value}, not 12 (uint16).").format(
            file=path.name, value=values.get("data type")))
    if values.get("interleave", "").lower() != "bsq":
        raise IncompatibleCaseError(_("{file} declares interleave {value}, not bsq.").format(
            file=path.name, value=values.get("interleave")))
    if values.get("byte order") != "0":
        raise IncompatibleCaseError(
            _("{file} declares byte order {value}, not 0 (little-endian).").format(
                file=path.name, value=values.get("byte order")))
    if values.get("header offset", "0") != "0":
        raise IncompatibleCaseError(_("{file} declares a header offset of {value}, not 0.").format(
            file=path.name, value=values.get("header offset")))
    return dimensions


def loadRecordedCase(folder) -> RecordedCase:
    """Describe a case folder UC1 can run on, or say why it cannot."""
    folder = Path(folder)
    if not folder.is_dir():
        raise IncompatibleCaseError(_("{folder} is not a folder.").format(folder=folder))

    dimensions = None
    firstHeader = None
    for stem in CASE_FILE_STEMS:
        headerPath = folder / f"{stem}.hdr"
        current = _headerDimensions(headerPath)
        if dimensions is None:
            dimensions, firstHeader = current, headerPath.name
        elif current != dimensions:
            raise IncompatibleCaseError(_(
                "{file} describes {samples} x {lines} x {bands} but {firstFile} describes "
                "{firstSamples} x {firstLines} x {firstBands} (samples x lines x bands)."
            ).format(file=headerPath.name, samples=current[0], lines=current[1],
                     bands=current[2], firstFile=firstHeader, firstSamples=dimensions[0],
                     firstLines=dimensions[1], firstBands=dimensions[2]))
    samples, lines, bands = dimensions

    if bands != UC1_MODEL_BAND_COUNT:
        raise IncompatibleCaseError(_(
            "The case has {bands} bands, but the staged SVM model is sized for {modelBands}. "
            "UC1 would classify against truncated or uninitialised weights."
        ).format(bands=bands, modelBands=UC1_MODEL_BAND_COUNT))

    expectedBytes = samples * lines * bands * BYTES_PER_SAMPLE
    for stem in CASE_FILE_STEMS:
        dataPath = folder / f"{stem}.dat"
        if not dataPath.is_file():
            raise IncompatibleCaseError(_("{file} is missing.").format(file=dataPath.name))
        actualBytes = dataPath.stat().st_size
        if actualBytes != expectedBytes:
            raise IncompatibleCaseError(
                _("{file} is {actual} bytes but the headers describe {expected}.").format(
                    file=dataPath.name, actual=actualBytes, expected=expectedBytes))

    groundTruthHeader = folder / GROUND_TRUTH_HEADER_FILE_NAME
    if not groundTruthHeader.is_file() or RECORDED_DATASET_MARKER not in groundTruthHeader.read_text(
        encoding="ascii", errors="replace"
    ):
        raise IncompatibleCaseError(_(
            "The folder does not identify as a case of the {dataset}: its {header} does not "
            "carry that marker."
        ).format(dataset=RECORDED_DATASET_MARKER, header=GROUND_TRUTH_HEADER_FILE_NAME))

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
            _("{file} is {actual} bytes but the headers describe {expected}.").format(
                file=path.name, actual=actualBytes, expected=expectedBytes))
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
        raise IncompatibleCaseError(_("{file} is missing.").format(file=path.name))
    values = parseEnviHeader(path.read_text(encoding="ascii", errors="replace"))
    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise IncompatibleCaseError(_("{file} does not declare {keys}.").format(
            file=path.name, keys=", ".join(missing)))
    try:
        samples, lines, bands = (int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise IncompatibleCaseError(_("{file} has a dimension that is not an integer.").format(
            file=path.name)) from error
    if bands != GROUND_TRUTH_BAND_COUNT:
        raise IncompatibleCaseError(
            _("{file} declares {bands} bands, not {expected}: it is not a single map of "
              "labels.").format(file=path.name, bands=bands, expected=GROUND_TRUTH_BAND_COUNT))
    if (samples, lines) != (case.samples, case.lines):
        raise IncompatibleCaseError(_(
            "{file} describes {samples} x {lines} but the case is {caseSamples} x {caseLines} "
            "(samples x lines)."
        ).format(file=path.name, samples=samples, lines=lines, caseSamples=case.samples,
                 caseLines=case.lines))
    if values.get("data type") != ENVI_DATA_TYPE_UINT16:
        raise IncompatibleCaseError(_("{file} declares data type {value}, not 12 (uint16).").format(
            file=path.name, value=values.get("data type")))
    if values.get("interleave", "").lower() != ENVI_INTERLEAVE_BIL:
        raise IncompatibleCaseError(_("{file} declares interleave {value}, not {expected}.").format(
            file=path.name, value=values.get("interleave"), expected=ENVI_INTERLEAVE_BIL))
    if values.get("byte order") != "0":
        raise IncompatibleCaseError(
            _("{file} declares byte order {value}, not 0 (little-endian).").format(
                file=path.name, value=values.get("byte order")))
    if values.get("header offset", "0") != "0":
        raise IncompatibleCaseError(_("{file} declares a header offset of {value}, not 0.").format(
            file=path.name, value=values.get("header offset")))
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
        raise IncompatibleCaseError(_("{file} is missing.").format(file=path.name))
    expectedBytes = samples * lines * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise IncompatibleCaseError(
            _("{file} is {actual} bytes but {header} describes {expected}.").format(
                file=path.name, actual=actualBytes, header=headerPath.name,
                expected=expectedBytes))
    # Byte order 0, checked just above.
    labels = np.fromfile(path, dtype="<u2").reshape(lines, samples)
    highest = int(labels.max()) if labels.size else 0
    if highest > HIGHEST_GROUND_TRUTH_CLASS_ID:
        raise IncompatibleCaseError(
            _("{file} holds class ID {classId}, but {header} only legends 0 to {highest}.").format(
                file=path.name, classId=highest, header=headerPath.name,
                highest=HIGHEST_GROUND_TRUTH_CLASS_ID))
    return labels


def assertCaseUnchanged(case: RecordedCase) -> None:
    """Re-read the case folder and refuse the run if it no longer matches.

    The cube is described when Capture is pressed, and its pixels are read for
    the HS Cube panel before the run starts. The folder lies outside the
    repository and nothing here owns it, so it can be edited, truncated or
    copied over in between, and UC1 reads the sizes from the headers without
    checking what it got. Re-reading the folder immediately before the run is
    the only point at which the description the operator was shown is known to
    still be the cube on disk.

    The run is refused rather than run on whatever the folder now holds: that
    would stamp the result with a cube the operator never saw described.
    """
    current = loadRecordedCase(case.folder)
    if current != case:
        raise IncompatibleCaseError(_(
            "Recorded case {case} changed on disk since Capture was pressed: it was "
            "{samples} x {lines} x {bands} and is now {nowSamples} x {nowLines} x {nowBands} "
            "(samples x lines x bands). Press Capture again to run on the case as it is now."
        ).format(case=case.name, samples=case.samples, lines=case.lines, bands=case.bands,
                 nowSamples=current.samples, nowLines=current.lines, nowBands=current.bands))
