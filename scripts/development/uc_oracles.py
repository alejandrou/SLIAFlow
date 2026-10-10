"""Independent oracles for UC1 and UC2 on IUMA's calibrated LCTF cubes.

Shared by `check-uc1.py`, `check-uc2.py` and `check-captures.py` (SLIA-040).
Each one restates what a document says the build does and computes it with
NumPy, without importing SLIAFlow, so that it can judge both the build and the
module:

- the band mapping of ADR-0004 decision 4, from the header's wavelengths, both
  to write a mapped cube and to compare one SLIAFlow wrote with it;
- `CalibratedImage_BIP.bmp`, predicted byte for byte (UC1 patch 0002);
- `pca.bmp`, from NumPy's first principal component (UC1 patch 0003);
- UC2's blood-vessel map, replicated step by step (UC2 patches 0001, 0002).

None of them depends on the cube's size or on its folder's name. Nothing here
writes outside the folder it is given.

Whether a cube is accepted at all is not restated here: `check-captures.py`
asks the module's own `loadCalibratedCube`, so that its report agrees with
what SLIAFlow refuses.
"""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import numpy as np

CUBE_STEM = "LCTF_Calibrated_Cube_Single"

# --- The cube and the band mapping (ADR-0004 decisions 4 and 6) ---------------

# The staged SVM model is sized for 93 bands at 440-900 nm in 5 nm steps.
MODEL_WAVELENGTHS_NM = tuple(440 + 5 * band for band in range(93))
# IUMA's LCTF grid, which the mapping is defined for.
LCTF_WAVELENGTHS_NM = tuple(460 + 5 * band for band in range(109))
WAVELENGTH_TOLERANCE_NM = 0.01
WAVELENGTHS_PER_HEADER_LINE = 6
# What a calibrated cube's header must declare (ADR-0004 decision 6). An absent
# header offset is 0, as ENVI defines it and SLIAFlowCalibratedCube reads it.
FLOAT32_LAYOUT = {"data type": "4", "interleave": "bsq", "byte order": "0", "header offset": "0"}
LAYOUT_DEFAULTS = {"header offset": "0"}
# The data file beside the header, tried in this order: IUMA's captures use
# .dat, the acquisition app writes .raw (SLIAFlowCalibratedCube reads both).
DATA_FILE_SUFFIXES = (".dat", ".raw")


def readCubeHeader(path: Path) -> dict:
    """samples, lines, bands, data type, interleave and wavelengths of an ENVI header.

    The values are the header's text; `wavelengths` is a list of floats.
    """
    text = path.read_text(encoding="ascii", errors="replace")
    values = {}
    for key in ("samples", "lines", "bands", "data type", "interleave", "byte order",
                "header offset"):
        match = re.search(rf"^\s*{key}\s*=\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
        values[key] = match.group(1) if match else None
    block = re.search(r"^\s*wavelength\s*=\s*\{([^}]*)\}", text, re.MULTILINE | re.IGNORECASE)
    values["wavelengths"] = ([float(value) for value in block.group(1).split(",")]
                             if block else [])
    return values


def cubeShape(header: dict) -> tuple[int, int, int]:
    """(bands, lines, samples) of a header read by readCubeHeader."""
    return tuple(int(header[key]) for key in ("bands", "lines", "samples"))


def layoutDifference(header: dict) -> str | None:
    """How a header read by readCubeHeader departs from FLOAT32_LAYOUT, or None."""
    actual = {key: (header[key] or LAYOUT_DEFAULTS.get(key, "")).lower() for key in FLOAT32_LAYOUT}
    return None if actual == FLOAT32_LAYOUT else f"declares {actual}, not {FLOAT32_LAYOUT}"


def cubeDataPath(cubeFolder: Path) -> Path:
    """The calibrated cube's data file in `cubeFolder`: .dat if there is one, else .raw."""
    paths = [cubeFolder / f"{CUBE_STEM}{suffix}" for suffix in DATA_FILE_SUFFIXES]
    return next((path for path in paths if path.is_file()), paths[0])


def modelBandSources(wavelengths: list[float]) -> list[int]:
    """For each model band, the cube band that feeds it (ADR-0004 decision 4)."""
    onGrid = len(wavelengths) == len(LCTF_WAVELENGTHS_NM) and all(
        abs(actual - expected) <= WAVELENGTH_TOLERANCE_NM
        for actual, expected in zip(wavelengths, LCTF_WAVELENGTHS_NM, strict=True))
    if not onGrid:
        raise ValueError(f"{CUBE_STEM}.hdr is not on IUMA's LCTF grid, which the mapping is "
                         "defined for")
    return [LCTF_WAVELENGTHS_NM.index(max(wavelength, LCTF_WAVELENGTHS_NM[0]))
            for wavelength in MODEL_WAVELENGTHS_NM]


def writeMappedCube(cubeFolder: Path, target: Path) -> np.ndarray:
    """Write the cube in `cubeFolder` on the model bands into `target`, as UC1 reads it.

    Returns the mapped cube, (bands, lines, samples) float32, read back from
    what was written.
    """
    header = readCubeHeader(cubeFolder / f"{CUBE_STEM}.hdr")
    problem = layoutDifference(header)
    if problem is not None:
        raise ValueError(f"{CUBE_STEM}.hdr {problem}")
    bands, lines, samples = cubeShape(header)
    sources = modelBandSources(header["wavelengths"])
    cube = np.memmap(cubeDataPath(cubeFolder), "<f4", "r", shape=(bands, lines, samples))
    target.mkdir(parents=True, exist_ok=True)
    with open(target / "raw.dat", "wb") as data:
        for source in sources:
            data.write(np.ascontiguousarray(cube[source]).tobytes())
    del cube
    rows = [", ".join(str(value) for value in
                      MODEL_WAVELENGTHS_NM[index:index + WAVELENGTHS_PER_HEADER_LINE])
            for index in range(0, len(MODEL_WAVELENGTHS_NM), WAVELENGTHS_PER_HEADER_LINE)]
    (target / "raw.hdr").write_text(
        f"ENVI\nsamples = {samples}\nlines = {lines}\nbands = {len(sources)}\n"
        "header offset = 0\ndata type = 4\ninterleave = bsq\nbyte order = 0\n"
        "wavelength = {" + ",\n".join(rows) + "}\n",
        encoding="ascii",
    )
    return readMappedCube(target)


def readMappedCube(mappedFolder: Path) -> np.ndarray:
    """The mapped cube in `mappedFolder` as UC1 reads it: (bands, lines, samples) float32."""
    return np.memmap(mappedFolder / "raw.dat", "<f4", "r",
                     shape=cubeShape(readCubeHeader(mappedFolder / "raw.hdr")))


def mappedCubeDifference(cubeFolder: Path, mappedFolder: Path) -> str | None:
    """How the mapped cube in `mappedFolder` departs from the mapping of the cube in `cubeFolder`.

    None if it is that mapping. The mapping is restated here from the cube's
    header, so that a mapped cube SLIAFlow wrote is judged against something
    it did not compute: `raw.hdr`'s layout, dimensions and wavelengths, and
    `raw.dat` band by band, byte for byte.
    """
    header = readCubeHeader(cubeFolder / f"{CUBE_STEM}.hdr")
    problem = layoutDifference(header)
    if problem is not None:
        return f"{CUBE_STEM}.hdr {problem}"
    bands, lines, samples = cubeShape(header)
    sources = modelBandSources(header["wavelengths"])
    mappedHeader = readCubeHeader(mappedFolder / "raw.hdr")
    problem = layoutDifference(mappedHeader)
    if problem is not None:
        return f"raw.hdr {problem}"
    expectedShape = (len(sources), lines, samples)
    if cubeShape(mappedHeader) != expectedShape:
        return (f"raw.hdr describes {cubeShape(mappedHeader)}, not {expectedShape} "
                "(bands, lines, samples)")
    wavelengths = mappedHeader["wavelengths"]
    if len(wavelengths) != len(MODEL_WAVELENGTHS_NM) or any(
            abs(actual - expected) > WAVELENGTH_TOLERANCE_NM
            for actual, expected in zip(wavelengths, MODEL_WAVELENGTHS_NM, strict=True)):
        return "raw.hdr does not list the model's 93 wavelengths at 440-900 nm"
    dataPath = mappedFolder / "raw.dat"
    expectedBytes = len(sources) * lines * samples * 4
    if dataPath.stat().st_size != expectedBytes:
        return f"raw.dat is {dataPath.stat().st_size} bytes, not {expectedBytes}"
    # Compared as 32-bit words, so a NaN is equal to the same NaN.
    cube = np.memmap(cubeDataPath(cubeFolder), "<u4", "r", shape=(bands, lines, samples))
    mapped = np.memmap(dataPath, "<u4", "r", shape=expectedShape)
    for band, source in enumerate(sources):
        if not np.array_equal(mapped[band], cube[source]):
            return (f"model band {band + 1} ({MODEL_WAVELENGTHS_NM[band]} nm) is not cube band "
                    f"{source + 1} ({LCTF_WAVELENGTHS_NM[source]} nm)")
    return None


# --- UC1 ------------------------------------------------------------------------

# The bands and order UC1 writes CalibratedImage_BIP.bmp with (functions_cuda.cu).
CALIBRATED_BMP_BANDS = (54, 20, 8)
# UC1 normalises in float32 and stops its Jacobi rotations at a tolerance, so a
# pixel can round to the next grey level. On 2026-09-25 99.99 % were exact.
MAX_PCA_LEVEL_DIFFERENCE = 1
# Pixels per step when NumPy computes the principal component, to bound memory.
PCA_CHUNK_PIXELS = 1 << 17


def readBmp(path: Path) -> np.ndarray:
    """A 24-bit bottom-up BMP as a (rows, columns, 3) array, as stored.

    UC1 pads the rows of most outputs to 4 bytes but not those of
    CalibratedImage_BIP.bmp, so the row length is taken from the file size.
    """
    data = path.read_bytes()
    if data[:2] != b"BM" or int.from_bytes(data[28:30], "little") != 24:
        raise ValueError(f"{path.name} is not a 24-bit BMP")
    offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = abs(int.from_bytes(data[22:26], "little", signed=True))
    stride = (len(data) - offset) // height
    if stride not in (width * 3, (width * 3 + 3) // 4 * 4):
        raise ValueError(f"{path.name} holds {len(data) - offset} bytes for {height} rows of {width}")
    rows = np.frombuffer(data, np.uint8, count=stride * height, offset=offset)
    return rows.reshape(height, stride)[:, :width * 3].reshape(height, width, 3)


def predictCalibratedBmp(reflectance: np.ndarray) -> np.ndarray:
    """CalibratedImage_BIP.bmp as UC1 must write it from a float32 reflectance cube.

    Patch 0002 multiplies by 100 in float32. saveBIPtoBMP then scales each of
    three bands from its own minimum to its maximum, 255 * (x - min) / (max -
    min) in float32, truncates to a byte, and writes blue, green, red, bottom
    row first.
    """
    channels = []
    for band in reversed(CALIBRATED_BMP_BANDS):
        values = np.float32(100) * np.asarray(reflectance[band])
        low, high = values.min(), values.max()
        channels.append((np.float32(255) * (values - low) / (high - low)).astype(np.uint8))
    return np.stack(channels, axis=2)[::-1]


def calibratedBmpDifference(output: Path, reflectance: np.ndarray) -> str | None:
    """How CalibratedImage_BIP.bmp in `output` differs from the prediction, or None."""
    actual, predicted = readBmp(output / "CalibratedImage_BIP.bmp"), predictCalibratedBmp(reflectance)
    if actual.shape != predicted.shape:
        return f"{actual.shape}, not {predicted.shape}"
    if not np.array_equal(actual, predicted):
        return f"{np.any(actual != predicted, axis=2).sum()} pixels differ"
    return None


def predictPcaLevels(reflectance: np.ndarray) -> np.ndarray:
    """The first principal component UC1 draws in pca.bmp, times 255: (lines, samples).

    As UC1 prepares it: each pixel scaled from its own minimum to its maximum
    over the bands (normalizeImgKernel_optimized, in float32), each band's mean
    removed, and the covariance divided by the pixel count minus one. The
    eigenvector comes from NumPy, not from UC1's Jacobi rotations. The
    covariance is accumulated in double precision over chunks of pixels.
    """
    bands = reflectance.shape[0]
    flat = reflectance.reshape(bands, -1)
    count = flat.shape[1]

    def normalized(start):
        percent = np.float32(100) * np.asarray(flat[:, start:start + PCA_CHUNK_PIXELS])
        low, high = percent.min(axis=0), percent.max(axis=0)
        scaled = (percent - low) * (np.float32(1) / (high - low + np.float32(1e-8)))
        return scaled.astype(np.float64)

    total = np.zeros(bands)
    products = np.zeros((bands, bands))
    for start in range(0, count, PCA_CHUNK_PIXELS):
        chunk = normalized(start)
        total += chunk.sum(axis=1)
        products += chunk @ chunk.T
    mean = total / count
    covariance = (products - count * np.outer(mean, mean)) / (count - 1)
    _, vectors = np.linalg.eigh(covariance)
    component = vectors[:, -1]
    levels = np.empty(count)
    for start in range(0, count, PCA_CHUNK_PIXELS):
        chunk = normalized(start)
        levels[start:start + chunk.shape[1]] = 255 * (component @ (chunk - mean[:, None]))
    return levels.reshape(reflectance.shape[1:])


def pcaDifference(output: Path, reflectance: np.ndarray) -> tuple[int, float]:
    """(worst grey-level difference, fraction of exact pixels) of pca.bmp against NumPy.

    An eigenvector's sign is arbitrary, so the sign that fits better is taken.
    """
    # Grey, bottom row first; pcaValue is truncated towards zero, then clipped.
    actual = readBmp(output / "pca.bmp")[::-1, :, 0].astype(np.int64)
    levels = predictPcaLevels(reflectance)
    difference = min((np.abs(np.clip((sign * levels).astype(np.int64), 0, 255) - actual)
                      for sign in (1, -1)), key=lambda values: int(values.sum()))
    return int(difference.max()), float((difference == 0).mean())


# --- UC2 ------------------------------------------------------------------------

# What patch 0002 hard-codes, and the wavelengths its comments give them.
PATCH_BANDS = {"blue": (4, 480.0), "green": (16, 540.0), "red": (50, 710.0)}
# The fixed parameters in main.c, case 4 as in case 12.
HIGH_IN = np.float32(0.15)
HIGH_OUT = np.float32(0.8)
B_VALUE = np.float32(3)


def uc2BandProblem(wavelengths: list[float]) -> str | None:
    """Why patch 0002's fixed band indices are not 480, 540 and 710 nm on this cube, or None."""
    for colour, (index, nanometres) in PATCH_BANDS.items():
        if index >= len(wavelengths):
            return f"patch 0002's {colour} band {index} is beyond the cube's {len(wavelengths)}"
        nearest = min(range(len(wavelengths)), key=lambda band: abs(wavelengths[band] - nanometres))
        if nearest != index or abs(wavelengths[index] - nanometres) > 0.01:
            return (f"patch 0002's {colour} band {index} is {wavelengths[index]} nm; "
                    f"the band at {nanometres} nm is {nearest}")
    return None


def readBand(dataPath: Path, lines: int, samples: int, band: int) -> np.ndarray:
    pixels = lines * samples
    values = np.fromfile(dataPath, dtype="<f4", count=pixels, offset=band * pixels * 4)
    if values.size != pixels:
        raise ValueError(f"{dataPath} has no band {band}")
    return values.reshape(lines, samples)


def uc2Planes(cubeFolder: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The blue, green and red planes UC2 reads from the cube in `cubeFolder`."""
    header = readCubeHeader(cubeFolder / f"{CUBE_STEM}.hdr")
    _bands, lines, samples = cubeShape(header)
    dataPath = cubeFolder / f"{CUBE_STEM}.dat"
    return tuple(readBand(dataPath, lines, samples, PATCH_BANDS[colour][0])
                 for colour in ("blue", "green", "red"))


def decodePng(path: Path) -> np.ndarray:
    """An 8-bit RGB, non-interlaced PNG as (rows, columns, 3) uint8, top row first.

    Enough for what stb_image_write writes; anything else is refused.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    position, idat, header = 8, b"", None
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        position += 12 + length
    width, height, depth, colour, _compression, _filter, interlace = header
    if (depth, colour, interlace) != (8, 2, 0):
        raise ValueError(f"{path.name} is depth {depth}, colour type {colour}, interlace "
                         f"{interlace}; expected 8-bit RGB, not interlaced")
    raw = zlib.decompress(idat)
    stride = width * 3
    image = np.zeros((height, stride), dtype=np.uint8)
    previous = np.zeros(stride, dtype=np.int32)
    for row in range(height):
        start = row * (stride + 1)
        kind = raw[start]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=start + 1).astype(np.int32)
        out = np.zeros(stride, dtype=np.int32)
        if kind == 0:
            out = line
        elif kind == 2:
            out = (line + previous) & 255
        else:
            for index in range(stride):
                left = out[index - 3] if index >= 3 else 0
                up = previous[index]
                upLeft = previous[index - 3] if index >= 3 else 0
                if kind == 1:
                    predictor = left
                elif kind == 3:
                    predictor = (left + up) // 2
                elif kind == 4:
                    estimate = left + up - upLeft
                    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upLeft))
                    predictor = (left, up, upLeft)[distances.index(min(distances))]
                else:
                    raise ValueError(f"{path.name} row {row} has filter type {kind}")
                out[index] = (line[index] + predictor) & 255
        image[row] = out
        previous = out
    return image.reshape(height, width, 3)


def replicateBvMap(blue: np.ndarray, green: np.ndarray, red: np.ndarray) -> np.ndarray:
    """UC2's steps on its three calibrated planes, in float32 as the C code does them.

    computeBVmapLCTF takes plane 0 (blue) as the enhancer, as delivered. Its
    output planes are |I2 - red|, |I2 - green| and |b * I2 - blue|, which
    save_BVMap_as_png clips to [0, 1], normalises and writes as R, G and B.
    """
    zero, one = np.float32(0), np.float32(1)
    normalised = np.clip(blue / HIGH_IN, zero, one)
    # powf(normalised, 1) is normalised; low_in and low_out are 0.
    adjusted = np.clip(normalised * HIGH_OUT, zero, HIGH_OUT)
    complement = one - adjusted
    planes = [np.abs(complement - red), np.abs(complement - green),
              np.abs(complement * B_VALUE - blue)]
    planes = [np.clip(plane, zero, one) for plane in planes]
    # normalize_rgb_array starts every channel's minimum and maximum from the
    # first value of channel 0, not of its own channel.
    first = planes[0].flat[0]
    channels = []
    for plane in planes:
        low = min(first, plane.min())
        high = max(first, plane.max())
        channels.append(((plane - low) / (high - low) * np.float32(255)).astype(np.uint8))
    return np.stack(channels, axis=-1)
