"""Check that the patched UC2 build does what docs/development/uc2_changes.md says.

Two checks on the staged `uc2_bvmap.exe` built by `build-uc2.ps1`:

1. Calibrated cube `S-N-002-04` (patches 0001 and 0002), byte for byte the cube
   that was `input/002-04` until 2026-10-08. UC2 is given the folder
   `input/S-N-002-04/S-N-002-04`, finds `LCTF_Calibrated_Cube_Single.hdr`
   there, and must write `S-N-002-04-BVMap.png` of the cube's lines and samples.
   - That PNG must be pixel-identical to a NumPy replica of UC2's own steps
     (`computeBVmapLCTF`, `clip_array`, `normalize_rgb_array`) run on the three
     bands nearest 480, 540 and 710 nm (`uc_oracles.py`). The replica's bands
     are checked by wavelength against the header, so it also confirms that
     the fixed indices 4, 16 and 50 in patch 0002 are those bands.
   - It must also have the SHA-256 the build wrote on 2026-10-07
     (RECORDED_PNG_SHA256), which also covers how the PNG is encoded. The PNG
     holds no name, so the folder's new name leaves it unchanged.
2. Short calibrated cube (patch 0002). A `LCTF_Calibrated_Cube_Single.dat`
   holding only the first five bands of `S-N-002-04`, with its header, must
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
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from uc_oracles import (
    CUBE_STEM,
    cubeShape,
    decodePng,
    readCubeHeader,
    replicateBvMap,
    uc2BandProblem,
    uc2Planes,
)

REPOSITORY = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPOSITORY / "build" / "uc2"
EXECUTABLE = BUILD_ROOT / "source" / "uc2_bvmap.exe"
LOCK = BUILD_ROOT / ".uc2-runner.lock"
CHECK_ROOT = BUILD_ROOT / "check"

CALIBRATED_NAME = "S-N-002-04"
CALIBRATED_FOLDER = REPOSITORY / "input" / CALIBRATED_NAME / CALIBRATED_NAME

# The patched build (vendored 1b5e9ae plus patches 0001 and 0002, compiled as
# build-uc2.ps1 does) on 002-04, now S-N-002-04, 2026-10-07.
# docs/development/uc2_changes.md.
RECORDED_PNG_SHA256 = "605BF532810C85DC8752CB437E842CB1DC044225976CABF3EECC9FE7899E4CCD"

SHORT_CUBE_BANDS = 5
RUN_TIMEOUT_SEC = 60


class CheckFailed(ValueError):
    pass


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
    header = readCubeHeader(CALIBRATED_FOLDER / f"{CUBE_STEM}.hdr")
    problem = uc2BandProblem(header["wavelengths"])
    if problem:
        raise CheckFailed(problem)
    _bands, lines, samples = cubeShape(header)
    completed, png, elapsed = runUc2(CALIBRATED_NAME, CALIBRATED_FOLDER)
    if completed.returncode != 0 or not png.is_file():
        raise CheckFailed(f"UC2 on {CALIBRATED_NAME} exited {completed.returncode} without "
                          f"{png.name}: {completed.stdout[-300:]}")
    image = decodePng(png)
    if image.shape != (lines, samples, 3):
        raise CheckFailed(f"{png.name} is {image.shape}, the cube is {lines} x {samples}")
    expected = replicateBvMap(*uc2Planes(CALIBRATED_FOLDER))
    differing = int(np.count_nonzero(np.any(image != expected, axis=-1)))
    if differing:
        raise CheckFailed(f"{png.name}: {differing} pixel(s) differ from the NumPy replica")
    digest = hashlib.sha256(png.read_bytes()).hexdigest().upper()
    if digest != RECORDED_PNG_SHA256:
        raise CheckFailed(f"{png.name} is {digest[:8]}..., the build wrote "
                          f"{RECORDED_PNG_SHA256[:8]}... on 2026-10-07")
    saturated = ", ".join(f"{channel} at 255 {100 * np.mean(image[..., index] == 255):.1f}%"
                          for index, channel in enumerate("RGB"))
    return [f"{CALIBRATED_NAME}: exit 0, {elapsed:.2f} s",
            f"  {png.name}  {image.shape[1]} x {image.shape[0]}, identical to the NumPy replica "
            f"(bands 4, 16, 50 = 480, 540, 710 nm)",
            f"  {png.name}  identical to the run recorded on 2026-10-07  {digest[:8]}...",
            f"  {saturated}"]


def checkShortCube() -> list[str]:
    folder = CHECK_ROOT / "short-input" / "short-cube"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    headerPath = CALIBRATED_FOLDER / f"{CUBE_STEM}.hdr"
    _bands, lines, samples = cubeShape(readCubeHeader(headerPath))
    shutil.copyfile(headerPath, folder / headerPath.name)
    bandBytes = lines * samples * 4
    with open(CALIBRATED_FOLDER / f"{CUBE_STEM}.dat", "rb") as source:
        (folder / f"{CUBE_STEM}.dat").write_bytes(source.read(SHORT_CUBE_BANDS * bandBytes))
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
        for check in (checkCalibratedCube, checkShortCube):
            try:
                print("\n".join(check()))
            except (ValueError, subprocess.TimeoutExpired, OSError) as error:
                failures += 1
                print(f"FAIL ({check.__name__}): {error}")
    finally:
        LOCK.unlink()
    print("PASS" if failures == 0 else f"FAIL: {failures} check(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
