"""Check that the patched UC1 build still behaves as the delivered one, and that each patch does its job.

Six checks on the staged `stratum.opt.intermediate.exe` built by
`build-uc1.ps1` (see docs/development/uc1_changes.md):

1. Reference case. UC1 runs on `input/reference_hsi_brain_db/020-01`, the
   recorded case its model was trained for, through the unchanged uint16 path.
   - `pca.bmp`, `svm.bmp`, `knn.bmp` and `CalibratedImage_BIP.bmp` must have the
     SHA-256 the unpatched build produced. The unpatched build gave these same
     four hashes in seven of seven runs, so any difference is a change.
   - `kmeans.bmp` and `imageRGB.bmp` vary from run to run even without any
     patch (K-means, up to 0.32 % and 0.19 % of pixels between two unpatched
     runs). They must differ from a saved unpatched run in at most
     MAX_KMEANS_DIFFERING_FRACTION of pixels.
2. Band guard. UC1 is started on a header declaring 109 bands. It must exit
   nonzero, say "Band guard", and create no output folder.
3. Float32 path (patch 0002). 020-01 is calibrated here the way UC1's uint16
   kernel does it, divided by 100 into reflectance and written as a float32
   cube. UC1 multiplies it by 100 again and transposes it to band
   interleaved, which is what `CalibratedImage_BIP.bmp` shows: it must be
   byte for byte the image predicted here from the cube, with UC1's own BMP
   scaling. Dividing and multiplying by 100 in float32 moves some values by
   one unit in the last place, so `pca.bmp`, `svm.bmp` and `knn.bmp` are held
   to the uint16 run of check 1 within MAX_FLOAT32_DIFFERING_FRACTION, not
   byte for byte.
   Its `pca.bmp` must also match the first principal component computed here
   (see check 4).
4. Equal bands (patch 0003). The float32 cube of check 3 with bands 1-4 set to
   band 5, as the band mapping does for an LCTF cube, so UC1's Jacobi step
   meets equal diagonal entries. Unpatched, it divides by zero and `pca.bmp` is
   black. `pca.bmp` shows 255 times the first principal component of the
   normalised cube, clipped to 0-255. NumPy computes that component here in
   double precision, independently of UC1's Jacobi rotations, and every pixel
   must be within MAX_PCA_LEVEL_DIFFERENCE grey level of it. An eigenvector's
   sign is arbitrary, so the sign that fits better is taken.
5. Short float32 cube (patch 0002). `raw.dat` one value shorter than its
   header describes must be refused, with no output folder.
6. Missing weights (patch 0001). Run from a folder whose `../../svm_model`
   does not exist, UC1 must refuse with the band guard's message.

Usage:

    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc1.py
    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc1.py --baseline D:/elsewhere

Written for SLIAFlow. It never writes into `input/` or `workspace/components/`.
It holds `.uc1-runner.lock` for the whole check, as SLIAFlow does for a run.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "UC1"
SOURCE_DIRECTORY = BUILD_ROOT / "gpu_single_bsq" / "source"
EXECUTABLE = SOURCE_DIRECTORY / "stratum.opt.intermediate.exe"
LOCK_PATH = BUILD_ROOT / ".uc1-runner.lock"
REFERENCE_CASE = REPOSITORY_ROOT / "input" / "reference_hsi_brain_db" / "020-01"
DEFAULT_BASELINE = REPOSITORY_ROOT / "build" / "uc1" / "reference-unpatched"
GUARD_CASE_NAME = "band-guard-check"
GUARD_FOLDER = BUILD_ROOT / "input" / GUARD_CASE_NAME
RUN_TIMEOUT_SEC = 120

# SHA-256 of the unpatched build's outputs on 020-01: the vendored UC1 staged
# and built by build-uc1.ps1 before any patch existed, run on 2026-09-24
# (recorded in docs/development/uc1_changes.md). The authority is that run, not
# the build under test.
UNPATCHED_REFERENCE_SHA256 = {
    "pca.bmp": "ee01256ba51b589f51d6a3a8d726685c04f08f25ccbb3bda857187809632e58c",
    "svm.bmp": "5f9548afcf87908115cdff408e263a30a24f4423340b99655d2f46c276f62a0f",
    "knn.bmp": "5aea0081152655c4ec4151abe59b97f3231818a2e351663a43178b2614a67910",
    "CalibratedImage_BIP.bmp": "810909a985f7bc0424e46fc8c225f7e797840c91b2d42812b5e74a7daedb2b89",
}
KMEANS_OUTPUTS = ("kmeans.bmp", "imageRGB.bmp")
# Three times the largest difference seen between two unpatched runs.
MAX_KMEANS_DIFFERING_FRACTION = 0.01

# The staged SVM model is sized for 93 bands; this is IUMA's LCTF band count.
GUARD_BAND_COUNT = 109
GUARD_MARKER = "Band guard"
# The guard refuses in about 0.1 s, before any image is read.
GUARD_TIMEOUT_SEC = 20

FLOAT32_CASE_NAME = "float32-check"
EQUAL_BANDS_CASE_NAME = "equal-bands-check"
SHORT_READ_CASE_NAME = "short-read-check"
# `../../svm_model` from here does not exist; UC1 also needs parameters.txt here.
NO_MODEL_DIRECTORY = BUILD_ROOT / "no-model-check" / "run" / "source"
# The bands and order UC1 writes CalibratedImage_BIP.bmp with (functions_cuda.cu).
CALIBRATED_BMP_BANDS = (54, 20, 8)
CLASSIFICATION_OUTPUTS = ("pca.bmp", "svm.bmp", "knn.bmp")
MAX_FLOAT32_DIFFERING_FRACTION = 0.001
# UC1 normalises in float32 and stops its Jacobi rotations at a tolerance, so a
# pixel can round to the next grey level. On 2026-09-25 99.99 % were exact.
MAX_PCA_LEVEL_DIFFERENCE = 1
# Model bands 1-4 (440-455 nm) take the band at 460 nm, model band 5.
EQUAL_BANDS = (0, 1, 2, 3)
EQUAL_BANDS_SOURCE = 4
WAVELENGTHS_PER_HEADER_LINE = 6


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


def differingFraction(first: Path, second: Path) -> float | None:
    """The fraction of pixels that differ between two BMPs, or None if their sizes differ."""
    one, other = readBmp(first), readBmp(second)
    if one.shape != other.shape:
        return None
    return float(np.any(one != other, axis=2).mean())


def calibrateLikeUc1(case: Path) -> np.ndarray:
    """The case calibrated as UC1's uint16 kernel does it, in percent: (bands, lines, samples).

    calibrateAndConvertToBIP_Tiled computes 100 * (raw - dark) / (white - dark)
    in float32, left to right, and 0 where white equals dark. The build does not
    use fast math, so the GPU rounds each step as NumPy does.
    """
    header = parseHeader(case / "raw.hdr")
    shape = (header["bands"], header["lines"], header["samples"])

    def load(name):
        return np.fromfile(case / name, np.uint16).astype(np.float32).reshape(shape)

    raw, dark, white = load("raw.dat"), load("darkReference.dat"), load("whiteReference.dat")
    span = white - dark
    with np.errstate(divide="ignore", invalid="ignore"):
        percent = (np.float32(100) * (raw - dark)) / span
    return np.where(span != 0, percent, np.float32(0)).astype(np.float32)


def parseHeader(path: Path) -> dict[str, int]:
    values = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("samples", "lines", "bands"):
            values[key.strip()] = int(value)
    return values


def predictCalibratedBmp(reflectance: np.ndarray) -> np.ndarray:
    """CalibratedImage_BIP.bmp as UC1 must write it from a float32 reflectance cube.

    Patch 0002 multiplies by 100 in float32. saveBIPtoBMP then scales each of
    three bands from its own minimum to its maximum, 255 * (x - min) / (max -
    min) in float32, truncates to a byte, and writes blue, green, red, bottom
    row first.
    """
    percent = np.float32(100) * reflectance
    channels = []
    for band in reversed(CALIBRATED_BMP_BANDS):
        values = percent[band]
        low, high = values.min(), values.max()
        channels.append((np.float32(255) * (values - low) / (high - low)).astype(np.uint8))
    return np.stack(channels, axis=2)[::-1]


def predictPcaLevels(reflectance: np.ndarray) -> np.ndarray:
    """The first principal component UC1 draws in pca.bmp, times 255: (lines, samples).

    As UC1 prepares it: each pixel scaled from its own minimum to its maximum
    over the bands (normalizeImgKernel_optimized, in float32), each band's mean
    removed, and the covariance divided by the pixel count minus one. The
    eigenvector comes from NumPy, not from UC1's Jacobi rotations.
    """
    bands = reflectance.shape[0]
    percent = (np.float32(100) * reflectance).reshape(bands, -1)
    low, high = percent.min(axis=0), percent.max(axis=0)
    normalized = (percent - low) * (np.float32(1) / (high - low + np.float32(1e-8)))
    centered = normalized.astype(np.float64)
    centered -= centered.mean(axis=1, keepdims=True)
    covariance = centered @ centered.T / (centered.shape[1] - 1)
    _, vectors = np.linalg.eigh(covariance)
    return (255 * (vectors[:, -1] @ centered)).reshape(reflectance.shape[1:])


def checkPca(output: Path, reflectance: np.ndarray) -> list[str]:
    written = output / "pca.bmp"
    if not written.is_file():
        return [f"pca.bmp was not written on {output.name}"]
    # Grey, bottom row first; pcaValue is truncated towards zero, then clipped.
    actual = readBmp(written)[::-1, :, 0].astype(np.int64)
    levels = predictPcaLevels(reflectance)
    difference = min((np.abs(np.clip((sign * levels).astype(np.int64), 0, 255) - actual)
                      for sign in (1, -1)), key=lambda values: int(values.sum()))
    worst, exact = int(difference.max()), float((difference == 0).mean())
    within = worst <= MAX_PCA_LEVEL_DIFFERENCE
    print(f"  {'pca.bmp':<24} {exact:.4%} of pixels equal to NumPy's first component, "
          f"at most {worst} grey level(s) off ({'within' if within else 'OVER'} "
          f"{MAX_PCA_LEVEL_DIFFERENCE})")
    if not within:
        return [f"pca.bmp of {output.name} is up to {worst} grey levels from NumPy's first "
                f"principal component, over {MAX_PCA_LEVEL_DIFFERENCE}"]
    return []


def writeFloat32Case(name: str, reflectance: np.ndarray) -> Path:
    """Write a float32 band sequential cube where UC1 is given its input; return the folder."""
    bands, lines, samples = reflectance.shape
    folder = BUILD_ROOT / "input" / name
    folder.mkdir(parents=True, exist_ok=True)
    reflectance.astype("<f4").tofile(folder / "raw.dat")
    wavelengths = [str(440 + 5 * band) for band in range(bands)]
    rows = [", ".join(wavelengths[index:index + WAVELENGTHS_PER_HEADER_LINE])
            for index in range(0, bands, WAVELENGTHS_PER_HEADER_LINE)]
    (folder / "raw.hdr").write_text(
        f"ENVI\nsamples = {samples}\nlines = {lines}\nbands = {bands}\nheader offset = 0\n"
        "data type = 4\ninterleave = bsq\nbyte order = 0\n"
        "wavelength = {" + ",\n".join(rows) + "}\n",
        encoding="ascii",
    )
    return folder


def freshOutput(name: str) -> Path:
    output = SOURCE_DIRECTORY / "output" / name
    shutil.rmtree(output, ignore_errors=True)
    return output


def runUc1(folder: Path, timeoutSec=RUN_TIMEOUT_SEC,
           cwd: Path = SOURCE_DIRECTORY) -> tuple[subprocess.CompletedProcess, float]:
    """Run UC1 on one folder. On a timeout the process is killed and None returned."""
    started = time.perf_counter()
    try:
        result = subprocess.run([str(EXECUTABLE), str(folder)], cwd=cwd,
                                capture_output=True, text=True, errors="replace",
                                timeout=timeoutSec)
    except subprocess.TimeoutExpired:
        result = None
    return result, time.perf_counter() - started


def checkReference(baseline: Path) -> list[str]:
    failures = []
    output = SOURCE_DIRECTORY / "output" / REFERENCE_CASE.name
    shutil.rmtree(output, ignore_errors=True)
    runStart = time.time()
    result, elapsed = runUc1(REFERENCE_CASE)
    if result is None:
        return [f"UC1 did not finish on {REFERENCE_CASE.name} within {RUN_TIMEOUT_SEC} s"]
    print(f"Reference case {REFERENCE_CASE.name}: exit {result.returncode}, {elapsed:.2f} s")
    if result.returncode != 0:
        return [f"UC1 exited with {result.returncode} on {REFERENCE_CASE.name}: "
                f"{result.stderr.strip()[-300:]}"]

    for fileName, expected in UNPATCHED_REFERENCE_SHA256.items():
        path = output / fileName
        if not path.is_file() or path.stat().st_mtime < runStart - 1:
            failures.append(f"{fileName} was not written by this run")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        same = actual == expected
        print(f"  {fileName:<24} {'identical' if same else 'DIFFERENT'}  {actual}")
        if not same:
            failures.append(f"{fileName} differs from the unpatched build ({actual})")

    for fileName in KMEANS_OUTPUTS:
        path = output / fileName
        reference = baseline / fileName
        if not path.is_file():
            failures.append(f"{fileName} was not written by this run")
            continue
        if not reference.is_file():
            failures.append(f"{reference} is missing, so {fileName} cannot be compared")
            continue
        current, saved = readBmp(path), readBmp(reference)
        if current.shape != saved.shape:
            failures.append(f"{fileName} is {current.shape}, the unpatched run {saved.shape}")
            continue
        fraction = float(np.any(current != saved, axis=2).mean())
        within = fraction <= MAX_KMEANS_DIFFERING_FRACTION
        print(f"  {fileName:<24} {fraction:.4%} of pixels differ from the unpatched run "
              f"({'within' if within else 'OVER'} {MAX_KMEANS_DIFFERING_FRACTION:.0%})")
        if not within:
            failures.append(f"{fileName}: {fraction:.4%} of pixels differ, over "
                            f"{MAX_KMEANS_DIFFERING_FRACTION:.0%}")
    return failures


def checkBandGuard() -> list[str]:
    # Only the header: the guard must refuse before any image is read.
    GUARD_FOLDER.mkdir(parents=True, exist_ok=True)
    wavelengths = ", ".join(str(460 + 5 * band) for band in range(GUARD_BAND_COUNT))
    (GUARD_FOLDER / "raw.hdr").write_text(
        "ENVI\nsamples = 4\nlines = 3\n"
        f"bands = {GUARD_BAND_COUNT}\ndata type = 4\ninterleave = bsq\nbyte order = 0\n"
        f"wavelength = {{{wavelengths}}}\n",
        encoding="ascii",
    )
    output = SOURCE_DIRECTORY / "output" / GUARD_CASE_NAME
    shutil.rmtree(output, ignore_errors=True)
    result, elapsed = runUc1(GUARD_FOLDER, GUARD_TIMEOUT_SEC)
    if result is None:
        # Without the guard, UC1 goes on to read a raw.dat that is not there
        # and computes on uninitialised memory; it was seen running past 120 s.
        return [f"UC1 did not refuse the {GUARD_BAND_COUNT}-band header within "
                f"{GUARD_TIMEOUT_SEC} s; it was killed"]
    message = next((line for line in result.stderr.splitlines() if GUARD_MARKER in line), "")
    print(f"Band guard, {GUARD_BAND_COUNT}-band header: exit {result.returncode}, {elapsed:.2f} s")
    print(f"  {message or '(no band guard message)'}")
    failures = []
    if result.returncode == 0:
        failures.append("UC1 exited 0 on a 109-band header")
    if not message:
        failures.append(f"UC1 did not print '{GUARD_MARKER}' on a 109-band header")
    if output.exists():
        failures.append(f"UC1 created {output} on a 109-band header")
    return failures


def runFloat32Case(name: str, reflectance: np.ndarray) -> tuple[Path, list[str]]:
    """Run UC1 on a float32 cube; return its output folder and why the run failed, if it did."""
    folder = writeFloat32Case(name, reflectance)
    output = freshOutput(name)
    result, elapsed = runUc1(folder)
    if result is None:
        return output, [f"UC1 did not finish on {name} within {RUN_TIMEOUT_SEC} s"]
    print(f"{name}: exit {result.returncode}, {elapsed:.2f} s")
    if result.returncode != 0:
        return output, [f"UC1 exited with {result.returncode} on {name}: "
                        f"{result.stderr.strip()[-300:]}"]
    return output, []


def compareOutputs(output: Path, against: Path, againstName: str, bound: float) -> list[str]:
    failures = []
    for fileName in CLASSIFICATION_OUTPUTS:
        if not (output / fileName).is_file() or not (against / fileName).is_file():
            failures.append(f"{fileName} is missing from {output.name} or {againstName}")
            continue
        fraction = differingFraction(output / fileName, against / fileName)
        if fraction is None:
            failures.append(f"{fileName} of {output.name} is not the size of {againstName}'s")
            continue
        within = fraction <= bound
        print(f"  {fileName:<24} {fraction:.4%} of pixels differ from {againstName} "
              f"({'within' if within else 'OVER'} {bound:.1%})")
        if not within:
            failures.append(f"{fileName} of {output.name}: {fraction:.4%} of pixels differ from "
                            f"{againstName}, over {bound:.1%}")
    return failures


def checkFloat32Path(referenceOutput: Path) -> tuple[list[str], np.ndarray]:
    reflectance = (calibrateLikeUc1(REFERENCE_CASE) / np.float32(100)).astype(np.float32)
    output, failures = runFloat32Case(FLOAT32_CASE_NAME, reflectance)
    if failures:
        return failures, reflectance

    written = output / "CalibratedImage_BIP.bmp"
    if not written.is_file():
        failures.append(f"{written.name} was not written on {FLOAT32_CASE_NAME}")
    else:
        actual, predicted = readBmp(written), predictCalibratedBmp(reflectance)
        same = actual.shape == predicted.shape and bool(np.array_equal(actual, predicted))
        detail = ("identical" if same else
                  f"{np.any(actual != predicted, axis=2).sum()} pixels differ"
                  if actual.shape == predicted.shape else f"{actual.shape}, not {predicted.shape}")
        print(f"  {written.name:<24} {'identical to the prediction' if same else detail}")
        if not same:
            failures.append(f"{written.name} of {FLOAT32_CASE_NAME} is not the predicted image: "
                            f"{detail}")
    failures += compareOutputs(output, referenceOutput, f"the uint16 run on {REFERENCE_CASE.name}",
                               MAX_FLOAT32_DIFFERING_FRACTION)
    failures += checkPca(output, reflectance)
    return failures, reflectance


def checkEqualBands(reflectance: np.ndarray) -> list[str]:
    cube = reflectance.copy()
    cube[list(EQUAL_BANDS)] = cube[EQUAL_BANDS_SOURCE]
    output, failures = runFloat32Case(EQUAL_BANDS_CASE_NAME, cube)
    if failures:
        return failures
    return checkPca(output, cube)


def checkShortRead(reflectance: np.ndarray) -> list[str]:
    folder = writeFloat32Case(SHORT_READ_CASE_NAME, reflectance)
    with open(folder / "raw.dat", "r+b") as data:
        data.truncate(reflectance.nbytes - reflectance.itemsize)
    output = freshOutput(SHORT_READ_CASE_NAME)
    result, elapsed = runUc1(folder)
    if result is None:
        return [f"UC1 did not refuse the short cube within {RUN_TIMEOUT_SEC} s; it was killed"]
    message = next((line for line in result.stderr.splitlines() if "header describes" in line), "")
    print(f"{SHORT_READ_CASE_NAME}: exit {result.returncode}, {elapsed:.2f} s")
    print(f"  {message or '(no short read message)'}")
    failures = []
    if result.returncode == 0:
        failures.append("UC1 exited 0 on a float32 cube one value short")
    if not message:
        failures.append("UC1 did not report the short float32 cube")
    if output.exists():
        failures.append(f"UC1 created {output} on a float32 cube one value short")
    return failures


def checkMissingWeights(inputFolder: Path) -> list[str]:
    NO_MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_DIRECTORY / "parameters.txt", NO_MODEL_DIRECTORY / "parameters.txt")
    output = NO_MODEL_DIRECTORY / "output"
    shutil.rmtree(output, ignore_errors=True)
    result, elapsed = runUc1(inputFolder, GUARD_TIMEOUT_SEC, cwd=NO_MODEL_DIRECTORY)
    if result is None:
        return [f"UC1 did not refuse to run without its weights within {GUARD_TIMEOUT_SEC} s"]
    message = next((line for line in result.stderr.splitlines()
                    if GUARD_MARKER in line and "cannot be opened" in line), "")
    print(f"Missing weights: exit {result.returncode}, {elapsed:.2f} s")
    print(f"  {message or '(no band guard message)'}")
    failures = []
    if result.returncode == 0:
        failures.append("UC1 exited 0 without its SVM weights")
    if not message:
        failures.append("UC1 did not say its SVM weights cannot be opened")
    if output.exists():
        failures.append(f"UC1 created {output} without its SVM weights")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="folder holding an unpatched run's kmeans.bmp and imageRGB.bmp")
    arguments = parser.parse_args()

    if not EXECUTABLE.is_file():
        print(f"ERROR: {EXECUTABLE} is missing. Build it with scripts\\development\\build-uc1.ps1.")
        return 1
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"ERROR: {LOCK_PATH} exists, so another UC1 run holds the build. Wait for it.")
        return 1
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        failures = checkReference(arguments.baseline) + checkBandGuard()
        float32Failures, reflectance = checkFloat32Path(
            SOURCE_DIRECTORY / "output" / REFERENCE_CASE.name)
        failures += float32Failures
        failures += checkEqualBands(reflectance)
        failures += checkShortRead(reflectance)
        failures += checkMissingWeights(BUILD_ROOT / "input" / FLOAT32_CASE_NAME)
    finally:
        LOCK_PATH.unlink(missing_ok=True)

    print()
    for failure in failures:
        print(f"FAIL: {failure}")
    print("PASS" if not failures else f"{len(failures)} check(s) failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
