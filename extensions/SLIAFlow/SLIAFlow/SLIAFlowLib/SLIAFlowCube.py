"""Read ENVI headers, and the ground truth that may lie beside a cube.

The cube itself is read by `SLIAFlowCalibratedCube`, and handed to UC1 by
`SLIAFlowUc1Input` (SLIA-033). What remains here is shared by both: the ENVI
header parser, and the ground-truth map (`gtMap`) a cube may carry.

A ground truth is offered only for a cube that has one (ADR-0004 decision 8).
IUMA's `002-04` has none; the recorded cases of the HSI Human Brain Database
do, as a `gtMap` pair in the case folder, and a cube laid out the same way is
read the same way. It is someone's labelling of the scene, not a UC1 output, and
it is only ever shown beside a result, never fed into a run. Nothing here writes
next to the cube.
"""

from pathlib import Path

import numpy as np

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

# gtMap is one band of uint16 class IDs (ENVI data type 12), stored bil.
ENVI_DATA_TYPE_UINT16 = "12"
BYTES_PER_SAMPLE = 2
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


class GroundTruthError(ValueError):
    """The gtMap beside a cube cannot be laid over that cube's result."""


def parseEnviHeader(text: str) -> dict[str, str]:
    """Return an ENVI header's key/value entries, lower-case keys.

    The brace-delimited wavelength block is consumed and not returned: a
    header may close it on its last value line and put `lines` and `samples`
    after it, so it must be skipped exactly, not line by line.
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


def hasGroundTruth(folder) -> bool:
    """Whether a cube in `folder` carries a ground truth to offer.

    Either file of the pair is enough to offer it: a pair with one half missing
    is then refused by `readGroundTruth` with the reason, rather than silently
    not offered.
    """
    folder = Path(folder)
    return (folder / GROUND_TRUTH_HEADER_FILE_NAME).is_file() or (
        folder / GROUND_TRUTH_FILE_NAME).is_file()


def _groundTruthHeaderDimensions(path: Path, samples: int, lines: int) -> None:
    """Check gtMap.hdr against the cube it is to be laid over.

    gtMap has its own header, so its geometry is read from it rather than
    assumed from the cube, and then required to agree. A ground truth that does
    not agree cannot be laid over a result at all, so it is refused instead of
    being stretched or cropped to fit.
    """
    if not path.is_file():
        raise GroundTruthError(_("{file} is missing.").format(file=path.name))
    values = parseEnviHeader(path.read_text(encoding="ascii", errors="replace"))
    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise GroundTruthError(_("{file} does not declare {keys}.").format(
            file=path.name, keys=", ".join(missing)))
    try:
        mapSamples, mapLines, bands = (int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise GroundTruthError(_("{file} has a dimension that is not an integer.").format(
            file=path.name)) from error
    if bands != GROUND_TRUTH_BAND_COUNT:
        raise GroundTruthError(
            _("{file} declares {bands} bands, not {expected}: it is not a single map of "
              "labels.").format(file=path.name, bands=bands, expected=GROUND_TRUTH_BAND_COUNT))
    if (mapSamples, mapLines) != (samples, lines):
        raise GroundTruthError(_(
            "{file} describes {samples} x {lines} but the cube is {cubeSamples} x {cubeLines} "
            "(samples x lines)."
        ).format(file=path.name, samples=mapSamples, lines=mapLines, cubeSamples=samples,
                 cubeLines=lines))
    if values.get("data type") != ENVI_DATA_TYPE_UINT16:
        raise GroundTruthError(_("{file} declares data type {value}, not 12 (uint16).").format(
            file=path.name, value=values.get("data type")))
    if values.get("interleave", "").lower() != ENVI_INTERLEAVE_BIL:
        raise GroundTruthError(_("{file} declares interleave {value}, not {expected}.").format(
            file=path.name, value=values.get("interleave"), expected=ENVI_INTERLEAVE_BIL))
    if values.get("byte order") != "0":
        raise GroundTruthError(
            _("{file} declares byte order {value}, not 0 (little-endian).").format(
                file=path.name, value=values.get("byte order")))
    if values.get("header offset", "0") != "0":
        raise GroundTruthError(_("{file} declares a header offset of {value}, not 0.").format(
            file=path.name, value=values.get("header offset")))


def readGroundTruth(folder, samples: int, lines: int) -> np.ndarray:
    """Return the gtMap in `folder` as a (lines, samples) uint16 array of class IDs.

    `samples` and `lines` are the cube's, which the map must match. One band of
    bil is a plain row-major image, so the bytes are reshaped and never
    rearranged, which puts row 0 at the top -- the same way `readUc1Bmp` hands
    back a decoded output, so the two line up pixel for pixel.

    A class ID outside the legend would index past the colour table, so the
    values are checked rather than clamped.
    """
    folder = Path(folder)
    headerPath = folder / GROUND_TRUTH_HEADER_FILE_NAME
    _groundTruthHeaderDimensions(headerPath, samples, lines)
    path = folder / GROUND_TRUTH_FILE_NAME
    if not path.is_file():
        raise GroundTruthError(_("{file} is missing.").format(file=path.name))
    expectedBytes = samples * lines * BYTES_PER_SAMPLE
    actualBytes = path.stat().st_size
    if actualBytes != expectedBytes:
        raise GroundTruthError(
            _("{file} is {actual} bytes but {header} describes {expected}.").format(
                file=path.name, actual=actualBytes, header=headerPath.name,
                expected=expectedBytes))
    # Byte order 0, checked just above.
    labels = np.fromfile(path, dtype="<u2").reshape(lines, samples)
    highest = int(labels.max()) if labels.size else 0
    if highest > HIGHEST_GROUND_TRUTH_CLASS_ID:
        raise GroundTruthError(
            _("{file} holds class ID {classId}, but {header} only legends 0 to {highest}.").format(
                file=path.name, classId=highest, header=headerPath.name,
                highest=HIGHEST_GROUND_TRUTH_CLASS_ID))
    return labels
