"""Hand UC1 the configured calibrated cube, on the bands its SVM model was trained for.

UC1's model is sized for 93 bands at 440-900 nm; IUMA's calibrated LCTF cube
has 109 bands at 460-1000 nm. ADR-0004 decision 4 maps one onto the other
without retraining, and this module is the one place that mapping runs. It is
described in docs/development/uc1_changes.md:

- 460-900 nm feed model bands 5-93 one to one;
- model bands 1-4 (440-455 nm) take the 460 nm band;
- 905-1000 nm are dropped.

A cube not on the LCTF grid is refused rather than mapped by guesswork
(decision 6). At every run the mapped cube is written as `raw.dat` and
`raw.hdr` (ENVI float32, band sequential) into the staged build's gitignored
`input/<cube>` folder, which is the folder UC1 is given. UC1 finds its input by
those names, and nothing is ever written next to the cube under `input/`. The
patched UC1 reads a data type 4 cube as calibrated reflectance and skips its
own calibration (patch 0002).

The values are copied as stored, band by band; nothing is resampled or rescaled.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .SLIAFlowCalibratedCube import (
    BYTES_PER_SAMPLE,
    ENVI_DATA_TYPE_FLOAT32,
    CalibratedCube,
    CalibratedCubeError,
    loadCalibratedCube,
)
from .SLIAFlowCube import hasGroundTruth

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

# The staged SVM model is sized for this many bands, at 440-900 nm in 5 nm
# steps: the grid of the HSI Human Brain Database it was trained on.
UC1_MODEL_BAND_COUNT = 93
MODEL_WAVELENGTHS_NM = tuple(440.0 + 5.0 * band for band in range(UC1_MODEL_BAND_COUNT))
# IUMA's LCTF grid (ADR-0004 context): 109 bands at 460-1000 nm in 5 nm steps.
LCTF_WAVELENGTHS_NM = tuple(460.0 + 5.0 * band for band in range(109))
# Header wavelengths are written as whole numbers; this only absorbs rounding.
WAVELENGTH_TOLERANCE_NM = 0.01

# The names UC1 opens in the folder it is given (data_loader.cpp).
INPUT_DATA_FILE_NAME = "raw.dat"
INPUT_HEADER_FILE_NAME = "raw.hdr"
PARTIAL_SUFFIX = ".partial"
# Six wavelengths to a line: UC1 reads the header 127 characters at a time.
WAVELENGTHS_PER_HEADER_LINE = 6


class BandMappingError(CalibratedCubeError):
    """The cube's bands do not fit the band mapping UC1 is run with."""


def modelBandSources(wavelengths, fileName: str) -> tuple:
    """For each of the 93 model bands, the index of the cube band that feeds it.

    `fileName` names the cube in the refusal. The cube must be on the LCTF grid
    exactly: the mapping is defined for it and for nothing else.
    """
    wavelengths = tuple(float(value) for value in wavelengths)
    onGrid = len(wavelengths) == len(LCTF_WAVELENGTHS_NM) and all(
        abs(actual - expected) <= WAVELENGTH_TOLERANCE_NM
        for actual, expected in zip(wavelengths, LCTF_WAVELENGTHS_NM, strict=True)
    )
    if not onGrid:
        span = (_("{first:g} to {last:g} nm").format(first=wavelengths[0], last=wavelengths[-1])
                if wavelengths else _("no wavelengths"))
        raise BandMappingError(_(
            "{file} has {count} bands at {span}. UC1's band mapping is defined for IUMA's LCTF "
            "grid only: {expected} bands at 460 to 1000 nm in 5 nm steps."
        ).format(file=fileName, count=len(wavelengths), span=span,
                 expected=len(LCTF_WAVELENGTHS_NM)))
    lowest = LCTF_WAVELENGTHS_NM[0]
    return tuple(LCTF_WAVELENGTHS_NM.index(max(wavelength, lowest))
                 for wavelength in MODEL_WAVELENGTHS_NM)


@dataclass(frozen=True)
class Uc1Input:
    """What one UC1 run reads: the configured cube, mapped, in its own folder.

    `folder` is where the mapped cube is written and what UC1 is given;
    `samples`, `lines` and `bands` describe that mapped cube.
    """

    name: str
    folder: Path
    samples: int
    lines: int
    bands: int
    cube: CalibratedCube
    bandSources: tuple
    fileStamps: tuple

    @property
    def groundTruthFolder(self) -> Path:
        """Where a ground truth of this cube would lie: beside the cube itself."""
        return self.cube.headerPath.parent

    @property
    def hasGroundTruth(self) -> bool:
        return hasGroundTruth(self.groundTruthFolder)


def fileStamps(cube: CalibratedCube) -> tuple:
    """Size, last write time and file ID of the cube's header and data file.

    Together they change whenever a file is written to or replaced, including
    by a file of the same size: the write time when it is written in place, the
    file ID when another file is moved over it. The values themselves are not
    hashed: that would read the whole cube once more at every Capture.
    """
    return tuple((stat.st_size, stat.st_mtime_ns, stat.st_ino)
                 for stat in (cube.headerPath.stat(), cube.dataPath.stat()))


def describeUc1Input(cube: CalibratedCube, inputRoot) -> Uc1Input:
    """Describe the run input for a calibrated cube, or refuse a cube off the grid."""
    sources = modelBandSources(cube.wavelengths, cube.headerPath.name)
    folder = (Path(inputRoot) / cube.name).resolve()
    return Uc1Input(cube.name, folder, cube.samples, cube.lines, len(sources), cube, sources,
                    fileStamps(cube))


def assertUc1InputUnchanged(uc1Input: Uc1Input) -> None:
    """Re-read the cube and refuse the run if it is no longer the one described.

    The cube is described when Capture is pressed and read again when the run
    starts. It lies outside the repository and nothing here owns it, so it can
    be edited, truncated or copied over in between, with or without changing
    its size. The run is refused rather than run on whatever the file now
    holds: that would stamp the result with a cube the operator never saw
    described.
    """
    described = uc1Input.cube
    current = loadCalibratedCube(described.headerPath)
    if (current.samples, current.lines, current.bands) != (
            described.samples, described.lines, described.bands):
        raise CalibratedCubeError(_(
            "Cube {cube} changed on disk since Capture was pressed: it was {samples} x {lines} x "
            "{bands} and is now {nowSamples} x {nowLines} x {nowBands} (samples x lines x bands). "
            "Press Capture again to run on the cube as it is now."
        ).format(cube=described.name, samples=described.samples, lines=described.lines,
                 bands=described.bands, nowSamples=current.samples, nowLines=current.lines,
                 nowBands=current.bands))
    rewritten = [path.name for path, before, now in zip(
        (described.headerPath, described.dataPath), uc1Input.fileStamps, fileStamps(current),
        strict=True) if before != now]
    if current != described and not rewritten:
        rewritten = [described.headerPath.name]
    if rewritten:
        raise CalibratedCubeError(_(
            "Cube {cube} changed on disk since Capture was pressed: {files} was written to "
            "since. Press Capture again to run on the cube as it is now."
        ).format(cube=described.name, files=_(" and ").join(rewritten)))


def _headerText(uc1Input: Uc1Input) -> str:
    # The dimensions and data type come first: UC1 reads them line by line, and
    # the long wavelength block after them is split into short lines.
    rows = [", ".join(f"{value:g}" for value in
                      MODEL_WAVELENGTHS_NM[index:index + WAVELENGTHS_PER_HEADER_LINE])
            for index in range(0, len(MODEL_WAVELENGTHS_NM), WAVELENGTHS_PER_HEADER_LINE)]
    return (
        "ENVI\n"
        f"description = {{{uc1Input.name} on the UC1 model bands, "
        "docs/development/uc1_changes.md}\n"
        f"samples = {uc1Input.samples}\n"
        f"lines = {uc1Input.lines}\n"
        f"bands = {uc1Input.bands}\n"
        "header offset = 0\n"
        f"data type = {ENVI_DATA_TYPE_FLOAT32}\n"
        "interleave = bsq\n"
        "byte order = 0\n"
        "wavelength units = Nanometers\n"
        "wavelength = {" + ",\n".join(rows) + "}\n"
    )


def writeUc1Input(uc1Input: Uc1Input) -> None:
    """Write the mapped cube UC1 reads, after checking the cube is the one described.

    Band sequential storage keeps each band contiguous, so every model band is
    one read of its source band and one write, byte for byte: byte order 0 was
    checked when the cube was described and is what the header declares. Each
    file is written under a temporary name and renamed into place, so a run
    never finds half a cube under the name it opens, and a refused copy leaves
    nothing behind.
    """
    assertUc1InputUnchanged(uc1Input)
    cube = uc1Input.cube
    bandBytes = cube.samples * cube.lines * BYTES_PER_SAMPLE
    folder = uc1Input.folder
    folder.mkdir(parents=True, exist_ok=True)

    dataPath = folder / INPUT_DATA_FILE_NAME
    partialData = folder / (INPUT_DATA_FILE_NAME + PARTIAL_SUFFIX)
    try:
        with open(cube.dataPath, "rb") as source, open(partialData, "wb") as target:
            for index in uc1Input.bandSources:
                source.seek(index * bandBytes)
                band = source.read(bandBytes)
                if len(band) != bandBytes:
                    raise CalibratedCubeError(_(
                        "{file} ended inside band {band} while it was written for UC1."
                    ).format(file=cube.dataPath.name, band=index + 1))
                target.write(band)
        # Checked again after the copy: a cube written to while it was read
        # would give UC1 bands from two different cubes.
        assertUc1InputUnchanged(uc1Input)
    except BaseException:
        partialData.unlink(missing_ok=True)
        raise
    os.replace(partialData, dataPath)

    headerPath = folder / INPUT_HEADER_FILE_NAME
    partialHeader = folder / (INPUT_HEADER_FILE_NAME + PARTIAL_SUFFIX)
    partialHeader.write_text(_headerText(uc1Input), encoding="ascii")
    os.replace(partialHeader, headerPath)
