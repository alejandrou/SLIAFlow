"""Describe and read IUMA's calibrated LCTF cube for display.

The HS Cube panel shows the calibrated cube IUMA's acquisition app will send
(ADR-0004 decision 1): reflectance as ENVI float32, band sequential, one
wavelength per band. Until SLIA-030 receives it, it is read from the configured
header under `input/`, where `002-04` lies. Nothing here writes to it.

The checks are the ones ADR-0004 decision 6 lists for a float32 cube: the header
and data file agree (data type 4, bsq, byte order 0, no header offset, size),
and the wavelengths are present, one per band. The 109 -> 93 band mapping of
decision 4 is UC1's check and belongs to SLIA-033; this module only displays.

The values are handed back as stored: no resampling, smoothing or rescaling.
"""

import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .SLIAFlowCube import parseEnviHeader

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

# ENVI data type 4 is float32, which is what IUMA's calibration writes.
ENVI_DATA_TYPE_FLOAT32 = "4"
BYTES_PER_SAMPLE = 4
# The data file is the header's stem with one of these, tried in this order:
# 002-04 uses .dat, the acquisition app writes .raw (section 3.4 of
# docs/hardware/acquisition_app_and_hardware.md).
DATA_FILE_SUFFIXES = (".dat", ".raw")
# `wavelength units` may be absent (the acquisition app does not write it) or
# say nanometres; any other unit would put the spectrum on the wrong axis.
NANOMETRE_UNITS = ("nanometers", "nanometres", "nm")


@dataclass(frozen=True)
class CalibratedCube:
    name: str
    headerPath: Path
    dataPath: Path
    samples: int
    lines: int
    bands: int
    wavelengths: tuple

    @property
    def expectedBytes(self) -> int:
        return self.samples * self.lines * self.bands * BYTES_PER_SAMPLE


class CalibratedCubeError(ValueError):
    """The header does not describe a calibrated cube this module can show."""


def _wavelengthBlock(text: str):
    """Return the entries of the header's `wavelength = {...}` block, or None.

    `parseEnviHeader` skips brace blocks, and this one spans several lines, so
    it is matched as a whole. `wavelength units` is a different key and does
    not match. Empty entries are kept, so a stray comma is refused as a
    wavelength that is not a number rather than silently dropped.
    """
    match = _WAVELENGTH_BLOCK.search(text)
    if match is None:
        return None
    return [entry.strip() for entry in match.group(1).split(",")]


_WAVELENGTH_BLOCK = re.compile(r"^\s*wavelength\s*=\s*\{([^}]*)\}", re.IGNORECASE | re.MULTILINE)


def loadCalibratedCube(headerPath) -> CalibratedCube:
    """Describe the calibrated cube a header names, or say why it cannot be shown."""
    headerPath = Path(headerPath)
    if not headerPath.is_file():
        raise CalibratedCubeError(_("{file} is missing.").format(file=headerPath.name))
    text = headerPath.read_text(encoding="ascii", errors="replace")
    values = parseEnviHeader(text)
    name = headerPath.name

    missing = [key for key in ("samples", "lines", "bands") if key not in values]
    if missing:
        raise CalibratedCubeError(_("{file} does not declare {keys}.").format(
            file=name, keys=", ".join(missing)))
    try:
        samples, lines, bands = (int(values[key]) for key in ("samples", "lines", "bands"))
    except ValueError as error:
        raise CalibratedCubeError(_("{file} has a dimension that is not an integer.").format(
            file=name)) from error
    if min(samples, lines, bands) <= 0:
        raise CalibratedCubeError(_("{file} declares a dimension that is not positive.").format(
            file=name))
    if values.get("data type") != ENVI_DATA_TYPE_FLOAT32:
        raise CalibratedCubeError(_("{file} declares data type {value}, not 4 (float32).").format(
            file=name, value=values.get("data type")))
    if values.get("interleave", "").lower() != "bsq":
        raise CalibratedCubeError(_("{file} declares interleave {value}, not bsq.").format(
            file=name, value=values.get("interleave")))
    if values.get("byte order") != "0":
        raise CalibratedCubeError(
            _("{file} declares byte order {value}, not 0 (little-endian).").format(
                file=name, value=values.get("byte order")))
    if values.get("header offset", "0") != "0":
        raise CalibratedCubeError(_("{file} declares a header offset of {value}, not 0.").format(
            file=name, value=values.get("header offset")))
    units = values.get("wavelength units")
    if units is not None and units.strip().lower() not in NANOMETRE_UNITS:
        raise CalibratedCubeError(_("{file} gives wavelengths in {units}, not nanometres.").format(
            file=name, units=units))

    entries = _wavelengthBlock(text)
    if entries is None:
        raise CalibratedCubeError(_("{file} lists no wavelengths.").format(file=name))
    try:
        wavelengths = tuple(float(entry) for entry in entries)
    except ValueError as error:
        raise CalibratedCubeError(_("{file} lists a wavelength that is not a number.").format(
            file=name)) from error
    if len(wavelengths) != bands:
        raise CalibratedCubeError(
            _("{file} lists {count} wavelengths for {bands} bands.").format(
                file=name, count=len(wavelengths), bands=bands))
    if not all(math.isfinite(value) for value in wavelengths) or any(
        later <= earlier for earlier, later in zip(wavelengths[:-1], wavelengths[1:], strict=True)
    ):
        raise CalibratedCubeError(
            _("{file} lists wavelengths that do not strictly increase.").format(file=name))

    dataPath = next(
        (headerPath.with_suffix(suffix) for suffix in DATA_FILE_SUFFIXES
         if headerPath.with_suffix(suffix).is_file()),
        None,
    )
    if dataPath is None:
        raise CalibratedCubeError(_("{file} has no data file ({suffixes}) beside it.").format(
            file=name, suffixes=", ".join(headerPath.stem + suffix
                                          for suffix in DATA_FILE_SUFFIXES)))
    cube = CalibratedCube(headerPath.parent.name, headerPath.resolve(), dataPath.resolve(),
                          samples, lines, bands, wavelengths)
    _assertDataSize(cube)
    return cube


def _assertDataSize(cube: CalibratedCube) -> None:
    actualBytes = cube.dataPath.stat().st_size
    if actualBytes != cube.expectedBytes:
        raise CalibratedCubeError(
            _("{file} is {actual} bytes but {header} describes {expected}.").format(
                file=cube.dataPath.name, actual=actualBytes, header=cube.headerPath.name,
                expected=cube.expectedBytes))


def readCalibratedCube(cube: CalibratedCube, out=None) -> np.ndarray:
    """Return the cube as a (bands, lines, samples) float32 array, values as stored.

    The file lies outside this repository and may have changed since it was
    described, so its size is checked again rather than reshaping whatever is
    on disk. BSQ stores one whole band after another, which is already the
    band-major order a Slicer volume wants, so the bytes are read in place and
    never rearranged. With `out`, they are read straight into that buffer (the
    volume's own), so the cube is never held twice.
    """
    _assertDataSize(cube)
    shape = (cube.bands, cube.lines, cube.samples)
    if out is None:
        out = np.empty(shape, dtype=np.float32)
    elif out.shape != shape or out.dtype != np.float32 or not out.flags.c_contiguous:
        raise ValueError(f"The buffer is {out.shape} {out.dtype}, not a contiguous {shape} float32.")
    with open(cube.dataPath, "rb") as stream:
        read = stream.readinto(memoryview(out).cast("B"))
    if read != cube.expectedBytes:
        raise CalibratedCubeError(
            _("{file} is {actual} bytes but {header} describes {expected}.").format(
                file=cube.dataPath.name, actual=read, header=cube.headerPath.name,
                expected=cube.expectedBytes))
    # Byte order 0, checked when the cube was described.
    if sys.byteorder != "little":
        out.byteswap(inplace=True)
    return out


def nearestBand(wavelengths, nanometres: float) -> int:
    """The index of the band whose wavelength is nearest; the lower one on a tie."""
    return min(range(len(wavelengths)), key=lambda index: (abs(wavelengths[index] - nanometres),
                                                          index))
