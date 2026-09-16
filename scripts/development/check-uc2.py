"""Check that the patched UC2 build does what docs/development/uc2_changes.md says.

Three checks on the staged `uc2_bvmap.exe` built by `build-uc2.ps1`:

1. Calibrated cube `002-04` (patches 0001 and 0002). UC2 is given the folder
   `input/002-04`, finds `LCTF_Calibrated_Cube_Single.hdr` there, and must
   write `002-04-BVMap.png` of the cube's lines and samples. That PNG must be
   pixel-identical to a NumPy replica of UC2's own steps (`computeBVmapLCTF`,
   `clip_array`, `normalize_rgb_array`) run on the three bands nearest 480, 540
   and 710 nm. The replica chooses its bands by wavelength from the header, so
   it also confirms that the fixed indices 4, 16 and 50 in patch 0002 are those
   bands.
2. Reference case `020-01`, uint16 with references (patch 0001 leaves it
   alone). Its folder has no calibrated cube, so UC2 must take its delivered
   path and write a PNG with the SHA-256 the unpatched build wrote on
   2026-10-05.
3. Short calibrated cube (patch 0002). A `LCTF_Calibrated_Cube_Single.dat`
   holding only the first five bands of `002-04`, with `002-04`'s header, must
   be refused: exit nonzero, `Error reading band`, and no PNG.

Usage:

    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc2.py

It never writes into `input/` or `workspace/components/`; everything it writes
is under `build/uc2/check/`. It holds `.uc2-runner.lock` for the whole check,
as SLIAFlow does for a run.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np

REPOSITORY = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPOSITORY / "build" / "uc2"
EXECUTABLE = BUILD_ROOT / "source" / "uc2_bvmap.exe"
LOCK = BUILD_ROOT / ".uc2-runner.lock"
CHECK_ROOT = BUILD_ROOT / "check"

CALIBRATED_FOLDER = REPOSITORY / "input" / "002-04"
CALIBRATED_STEM = "LCTF_Calibrated_Cube_Single"
REFERENCE_FOLDER = REPOSITORY / "input" / "reference_hsi_brain_db" / "020-01"

# What patch 0002 hard-codes, and the wavelengths its comments give them.
PATCH_BANDS = {"blue": (4, 480.0), "green": (16, 540.0), "red": (50, 710.0)}
# The fixed parameters in main.c, case 4 as in case 12.
HIGH_IN = np.float32(0.15)
HIGH_OUT = np.float32(0.8)
B_VALUE = np.float32(3)

# The unpatched build (vendored 1b5e9ae, compiled as build-uc2.ps1 does) on
# 020-01, 2026-10-05. docs/development/uc2_changes.md.
REFERENCE_PNG_SHA256 = "C1C7B940A3340ED8A66381692D1AFA231E3883560EBB4972AD3D583D26E01D9A"

SHORT_CUBE_BANDS = 5
RUN_TIMEOUT_SEC = 60


class CheckFailed(Exception):
    pass


# --- Reading what UC2 reads and writes ----------------------------------------

def readHeader(path: Path) -> dict:
    text = path.read_text(encoding="ascii", errors="replace")
    values = {}
    for key in ("samples", "lines", "bands", "data type", "header offset"):
        match = re.search(rf"^\s*{key}\s*=\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
        if match:
            values[key] = int(match.group(1))
    block = re.search(r"^\s*wavelength\s*=\s*\{([^}]*)\}", text, re.MULTILINE | re.IGNORECASE)
    values["wavelengths"] = [float(entry) for entry in block.group(1).split(",")] if block else []
    return values


def readBand(dataPath: Path, header: dict, band: int) -> np.ndarray:
    pixels = header["lines"] * header["samples"]
    offset = header.get("header offset", 0) + band * pixels * 4
    values = np.fromfile(dataPath, dtype="<f4", count=pixels, offset=offset)
    if values.size != pixels:
        raise CheckFailed(f"{dataPath} has no band {band}")
    return values.reshape(header["lines"], header["samples"])


def decodePng(path: Path) -> np.ndarray:
    """An 8-bit RGB, non-interlaced PNG as (rows, columns, 3) uint8, top row first.

    Enough for what stb_image_write writes; anything else is refused.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise CheckFailed(f"{path.name} is not a PNG")
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
        raise CheckFailed(f"{path.name} is depth {depth}, colour type {colour}, interlace "
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
                    raise CheckFailed(f"{path.name} row {row} has filter type {kind}")
                out[index] = (line[index] + predictor) & 255
        image[row] = out
        previous = out
    return image.reshape(height, width, 3)


# --- The replica ----------------------------------------------------------------

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


# --- Running UC2 ----------------------------------------------------------------

def runUc2(name: str, folder: Path) -> tuple[subprocess.CompletedProcess, Path, float]:
    runDirectory = CHECK_ROOT / name
    if runDirectory.exists():
        shutil.rmtree(runDirectory)
    runDirectory.mkdir(parents=True)
    started = time.monotonic()
    completed = subprocess.run(
        [str(EXECUTABLE), folder.as_posix()], cwd=runDirectory, capture_output=True,
        text=True, timeout=RUN_TIMEOUT_SEC,
    )
    return completed, runDirectory / f"{folder.name}-BVMap.png", time.monotonic() - started


def checkCalibratedCube() -> list[str]:
    header = readHeader(CALIBRATED_FOLDER / f"{CALIBRATED_STEM}.hdr")
    wavelengths = header["wavelengths"]
    for colour, (index, nanometres) in PATCH_BANDS.items():
        nearest = min(range(len(wavelengths)), key=lambda band: abs(wavelengths[band] - nanometres))
        if nearest != index or abs(wavelengths[index] - nanometres) > 0.01:
            raise CheckFailed(f"patch 0002's {colour} band {index} is {wavelengths[index]} nm; "
                              f"the band at {nanometres} nm is {nearest}")
    completed, png, elapsed = runUc2("002-04", CALIBRATED_FOLDER)
    if completed.returncode != 0 or not png.is_file():
        raise CheckFailed(f"UC2 on 002-04 exited {completed.returncode} without "
                          f"{png.name}: {completed.stdout[-300:]}")
    image = decodePng(png)
    if image.shape != (header["lines"], header["samples"], 3):
        raise CheckFailed(f"{png.name} is {image.shape}, the cube is "
                          f"{header['lines']} x {header['samples']}")
    dataPath = CALIBRATED_FOLDER / f"{CALIBRATED_STEM}.dat"
    blue, green, red = (readBand(dataPath, header, PATCH_BANDS[colour][0])
                        for colour in ("blue", "green", "red"))
    expected = replicateBvMap(blue, green, red)
    differing = int(np.count_nonzero(np.any(image != expected, axis=-1)))
    if differing:
        raise CheckFailed(f"{png.name}: {differing} pixel(s) differ from the NumPy replica")
    saturated = ", ".join(f"{channel} at 255 {100 * np.mean(image[..., index] == 255):.1f}%"
                          for index, channel in enumerate("RGB"))
    return [f"002-04: exit 0, {elapsed:.2f} s",
            f"  {png.name}  {image.shape[1]} x {image.shape[0]}, identical to the NumPy replica "
            f"(bands 4, 16, 50 = 480, 540, 710 nm)",
            f"  {saturated}"]


def checkReferenceCase() -> list[str]:
    completed, png, elapsed = runUc2("020-01", REFERENCE_FOLDER)
    if completed.returncode != 0 or not png.is_file():
        raise CheckFailed(f"UC2 on 020-01 exited {completed.returncode} without {png.name}")
    digest = hashlib.sha256(png.read_bytes()).hexdigest().upper()
    if digest != REFERENCE_PNG_SHA256:
        raise CheckFailed(f"{png.name} is {digest[:8]}..., the unpatched build wrote "
                          f"{REFERENCE_PNG_SHA256[:8]}...")
    return [f"020-01: exit 0, {elapsed:.2f} s",
            f"  {png.name}  identical to the unpatched build  {digest[:8]}..."]


def checkShortCube() -> list[str]:
    folder = CHECK_ROOT / "short-input" / "short-cube"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    headerPath = CALIBRATED_FOLDER / f"{CALIBRATED_STEM}.hdr"
    header = readHeader(headerPath)
    shutil.copyfile(headerPath, folder / headerPath.name)
    bandBytes = header["lines"] * header["samples"] * 4
    with open(CALIBRATED_FOLDER / f"{CALIBRATED_STEM}.dat", "rb") as source:
        (folder / f"{CALIBRATED_STEM}.dat").write_bytes(source.read(SHORT_CUBE_BANDS * bandBytes))
    completed, png, elapsed = runUc2("short-cube", folder)
    output = completed.stdout + completed.stderr
    if completed.returncode == 0 or "Error reading band" not in output or png.exists():
        raise CheckFailed(f"the short cube was not refused: exit {completed.returncode}, "
                          f"PNG {'written' if png.exists() else 'absent'}")
    message = next(line for line in output.splitlines() if "Error reading band" in line)
    return [f"short-cube: exit {completed.returncode}, {elapsed:.2f} s, no PNG",
            f"  {message.strip()}"]


def main() -> int:
    if not EXECUTABLE.is_file():
        print(f"FAIL: {EXECUTABLE} is missing. Build it with scripts\\development\\build-uc2.ps1.")
        return 1
    try:
        descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"FAIL: {LOCK} exists; a UC2 run holds the build.")
        return 1
    os.close(descriptor)
    failures = 0
    try:
        for check in (checkCalibratedCube, checkReferenceCase, checkShortCube):
            try:
                print("\n".join(check()))
            except (CheckFailed, subprocess.TimeoutExpired, OSError) as error:
                failures += 1
                print(f"FAIL ({check.__name__}): {error}")
    finally:
        LOCK.unlink()
    print("PASS" if failures == 0 else f"FAIL: {failures} check(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
