"""Check that the patched UC1 build still writes what it wrote on 002-04, and that each patch does its job.

Four checks on the staged `stratum.opt.intermediate.exe` built by
`build-uc1.ps1` (see docs/development/uc1_changes.md):

1. Mapped cube 002-04. IUMA's calibrated cube `input/002-04` is mapped onto
   the 93 model bands as ADR-0004 decision 4 states it - 460-900 nm one to one,
   440-455 nm from the 460 nm band, 905-1000 nm dropped - computed here from
   the header's wavelengths, not taken from SLIAFlow, and written as a float32
   cube where UC1 is given its input. UC1 must exit 0 and write its six images,
   each of the cube's samples x lines.
   - `pca.bmp`, `svm.bmp`, `knn.bmp` and `CalibratedImage_BIP.bmp` must have the
     SHA-256 the build wrote on 2026-10-07 (RECORDED_SHA256). It wrote these same
     four hashes in five of five runs, so any difference is a change.
   - `kmeans.bmp` and `imageRGB.bmp` vary from run to run (K-means). They must
     differ from the saved run in `--baseline` in at most
     MAX_KMEANS_DIFFERING_FRACTION of pixels. The saved run is accepted only if
     its two files have the SHA-256 recorded here (RECORDED_BASELINE_SHA256), so
     a folder saved from another build, or the output under test, is refused.
   - Float32 path (patch 0002). UC1 multiplies the cube by 100 and transposes it
     to band interleaved, which is what `CalibratedImage_BIP.bmp` shows: it must
     be byte for byte the image predicted here from the cube, with UC1's own BMP
     scaling.
   - Equal bands (patch 0003). The mapping makes model bands 1-5 equal, so
     UC1's Jacobi step meets equal diagonal entries; unpatched, it divides by
     zero and `pca.bmp` is black. `pca.bmp` shows 255 times the first principal
     component of the normalised cube, clipped to 0-255. NumPy computes that
     component here in double precision, independently of UC1's Jacobi
     rotations, and every pixel must be within MAX_PCA_LEVEL_DIFFERENCE grey
     level of it. An eigenvector's sign is arbitrary, so the sign that fits
     better is taken.
2. Band guard. UC1 is started on a header declaring 109 bands. It must exit
   nonzero, say "Band guard", and create no output folder.
3. Short float32 cube (patch 0002). The mapped cube one value shorter than its
   header describes must be refused, with no output folder.
4. Missing weights (patch 0001). Run from a folder whose `../../svm_model`
   does not exist, UC1 must refuse with the band guard's message.

After a deliberate change - a new patch, GPU, driver or nvcc - review the
difference, then record the build's run again with `--save-baseline`: it runs
check 1, saves the six images in `--baseline`, which must not exist yet or be
empty, and prints the hashes to put in RECORDED_SHA256 and
RECORDED_BASELINE_SHA256. It deletes nothing: the owner removes an old saved
run. `--baseline` must lie outside the repository or under `build/`, and not in
the UC1 build tree.

Usage:

    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc1.py
    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc1.py --baseline D:/elsewhere
    .\\.venv\\Scripts\\python.exe scripts\\development\\check-uc1.py --save-baseline --baseline build/uc1/baseline-new

Written for SLIAFlow. It never writes into `input/` or `workspace/components/`.
It holds `.uc1-runner.lock` for the whole check, as SLIAFlow does for a run.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
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
CUBE_FOLDER = REPOSITORY_ROOT / "input" / "002-04"
CUBE_STEM = "LCTF_Calibrated_Cube_Single"
DEFAULT_BASELINE = REPOSITORY_ROOT / "build" / "uc1" / "baseline-002-04"
RUN_TIMEOUT_SEC = 120

# SHA-256 of the build's outputs on the mapped 002-04 cube: build-uc1.ps1 with
# patches 0001-0003, run on 2026-10-07 (recorded in
# docs/development/uc1_changes.md). The authority is that run, not the build
# under test.
RECORDED_SHA256 = {
    "pca.bmp": "b4f62bfb71b450f5ec8c6b2c0ee5ae038e769f59d47e9455482dee487f0432cc",
    "svm.bmp": "c0a5eb4a29a556ffbaac6d06bb318d7e61099fb67755878512347ca06bf07464",
    "knn.bmp": "c9769b093eb99fdc2c969cc27d0ba830c0da96cce1db6079bf4dfa7b7f40cd66",
    "CalibratedImage_BIP.bmp": "ea59726ac65cd1ce9516d6c1231e7e63a792a4dad4c526ff500e1f6222deef81",
}
KMEANS_OUTPUTS = ("kmeans.bmp", "imageRGB.bmp")
# SHA-256 of the saved run in DEFAULT_BASELINE, from the same build on 2026-10-07.
RECORDED_BASELINE_SHA256 = {
    "kmeans.bmp": "e8efc5377595fac243529127c4110c63f8111e3aa57ae51348f0c1e4f121734c",
    "imageRGB.bmp": "0fed1c7a24acfc87a8b4dc133802e00d3e23fbb73f6e5573d6b3172620769fc1",
}
OUTPUTS = (*RECORDED_SHA256, *KMEANS_OUTPUTS)
# Three times the largest difference seen between two of five runs on
# 2026-10-07: 0.0068 % of kmeans.bmp, 0.0015 % of imageRGB.bmp.
MAX_KMEANS_DIFFERING_FRACTION = 0.0002

# The staged SVM model is sized for 93 bands at 440-900 nm in 5 nm steps.
MODEL_WAVELENGTHS_NM = tuple(440 + 5 * band for band in range(93))
# IUMA's LCTF grid, which the mapping is defined for.
LCTF_WAVELENGTHS_NM = tuple(460 + 5 * band for band in range(109))
WAVELENGTH_TOLERANCE_NM = 0.01
WAVELENGTHS_PER_HEADER_LINE = 6

GUARD_CASE_NAME = "band-guard-check"
GUARD_FOLDER = BUILD_ROOT / "input" / GUARD_CASE_NAME
GUARD_BAND_COUNT = 109
GUARD_MARKER = "Band guard"
# The guard refuses in about 0.1 s, before any image is read.
GUARD_TIMEOUT_SEC = 20

MAPPED_CASE_NAME = "check-002-04"
SHORT_READ_CASE_NAME = "short-read-check"
# `../../svm_model` from here does not exist; UC1 also needs parameters.txt here.
NO_MODEL_DIRECTORY = BUILD_ROOT / "no-model-check" / "run" / "source"
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


def readCubeHeader(path: Path) -> dict:
    """samples, lines, bands, data type, interleave and wavelengths of an ENVI header."""
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


def writeMappedCube() -> tuple[Path, np.ndarray]:
    """Write 002-04 on the model bands where UC1 is given its input.

    Returns the folder and the mapped cube, (bands, lines, samples) float32,
    read back from what was written.
    """
    header = readCubeHeader(CUBE_FOLDER / f"{CUBE_STEM}.hdr")
    expected = {"data type": "4", "interleave": "bsq", "byte order": "0", "header offset": "0"}
    actual = {key: (header[key] or "").lower() for key in expected}
    if actual != expected:
        raise ValueError(f"{CUBE_STEM}.hdr declares {actual}, not {expected}")
    samples, lines, bands = (int(header[key]) for key in ("samples", "lines", "bands"))
    sources = modelBandSources(header["wavelengths"])
    cube = np.memmap(CUBE_FOLDER / f"{CUBE_STEM}.dat", "<f4", "r", shape=(bands, lines, samples))
    folder = BUILD_ROOT / "input" / MAPPED_CASE_NAME
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "raw.dat", "wb") as target:
        for source in sources:
            target.write(np.ascontiguousarray(cube[source]).tobytes())
    del cube
    rows = [", ".join(str(value) for value in
                      MODEL_WAVELENGTHS_NM[index:index + WAVELENGTHS_PER_HEADER_LINE])
            for index in range(0, len(MODEL_WAVELENGTHS_NM), WAVELENGTHS_PER_HEADER_LINE)]
    (folder / "raw.hdr").write_text(
        f"ENVI\nsamples = {samples}\nlines = {lines}\nbands = {len(sources)}\n"
        "header offset = 0\ndata type = 4\ninterleave = bsq\nbyte order = 0\n"
        "wavelength = {" + ",\n".join(rows) + "}\n",
        encoding="ascii",
    )
    mapped = np.memmap(folder / "raw.dat", "<f4", "r", shape=(len(sources), lines, samples))
    return folder, mapped


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


def checkPca(output: Path, reflectance: np.ndarray) -> list[str]:
    written = output / "pca.bmp"
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


def runMappedCube(folder: Path, reflectance: np.ndarray) -> tuple[Path, list[str]]:
    """Run UC1 on the mapped cube; return its output folder and why the run failed, if it did."""
    output = freshOutput(MAPPED_CASE_NAME)
    runStart = time.time()
    result, elapsed = runUc1(folder)
    if result is None:
        return output, [f"UC1 did not finish on {MAPPED_CASE_NAME} within {RUN_TIMEOUT_SEC} s"]
    print(f"Mapped cube 002-04: exit {result.returncode}, {elapsed:.2f} s")
    if result.returncode != 0:
        return output, [f"UC1 exited with {result.returncode} on {MAPPED_CASE_NAME}: "
                        f"{result.stderr.strip()[-300:]}"]
    _bands, lines, samples = reflectance.shape
    failures = []
    for fileName in OUTPUTS:
        path = output / fileName
        if not path.is_file() or path.stat().st_mtime < runStart - 1:
            failures.append(f"{fileName} was not written by this run")
        elif readBmp(path).shape != (lines, samples, 3):
            failures.append(f"{fileName} is {readBmp(path).shape[:2]}, not the cube's "
                            f"{lines} x {samples}")
    if not failures:
        print(f"  six images written, each {samples} x {lines}")
    return output, failures


def compareWithRecordedRun(output: Path, baseline: Path) -> list[str]:
    failures = []
    for fileName, expected in RECORDED_SHA256.items():
        actual = hashlib.sha256((output / fileName).read_bytes()).hexdigest()
        same = actual == expected
        print(f"  {fileName:<24} {'identical' if same else 'DIFFERENT'}  {actual}")
        if not same:
            failures.append(f"{fileName} differs from the run recorded on 2026-10-07 ({actual})")

    for fileName in KMEANS_OUTPUTS:
        reference = baseline / fileName
        if not reference.is_file():
            failures.append(f"{reference} is missing, so {fileName} cannot be compared. "
                            "Record it with --save-baseline")
            continue
        saved = hashlib.sha256(reference.read_bytes()).hexdigest()
        if saved != RECORDED_BASELINE_SHA256[fileName]:
            failures.append(f"{reference} is not the run recorded on 2026-10-07 ({saved}), "
                            "so it cannot be compared with")
            continue
        current, saved = readBmp(output / fileName), readBmp(reference)
        if current.shape != saved.shape:
            failures.append(f"{fileName} is {current.shape}, the saved run {saved.shape}")
            continue
        fraction = float(np.any(current != saved, axis=2).mean())
        within = fraction <= MAX_KMEANS_DIFFERING_FRACTION
        print(f"  {fileName:<24} {fraction:.4%} of pixels differ from the saved run "
              f"({'within' if within else 'OVER'} {MAX_KMEANS_DIFFERING_FRACTION:.2%})")
        if not within:
            failures.append(f"{fileName}: {fraction:.4%} of pixels differ, over "
                            f"{MAX_KMEANS_DIFFERING_FRACTION:.2%}")
    return failures


def checkPatchedPaths(output: Path, reflectance: np.ndarray) -> list[str]:
    failures = []
    written = output / "CalibratedImage_BIP.bmp"
    actual, predicted = readBmp(written), predictCalibratedBmp(reflectance)
    same = actual.shape == predicted.shape and bool(np.array_equal(actual, predicted))
    detail = ("identical" if same else
              f"{np.any(actual != predicted, axis=2).sum()} pixels differ"
              if actual.shape == predicted.shape else f"{actual.shape}, not {predicted.shape}")
    print(f"  {written.name:<24} {'identical to the prediction' if same else detail}")
    if not same:
        failures.append(f"{written.name} of {MAPPED_CASE_NAME} is not the predicted image: "
                        f"{detail}")
    return failures + checkPca(output, reflectance)


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
    output = freshOutput(GUARD_CASE_NAME)
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


def checkShortRead(mappedFolder: Path) -> list[str]:
    folder = BUILD_ROOT / "input" / SHORT_READ_CASE_NAME
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mappedFolder / "raw.hdr", folder / "raw.hdr")
    shutil.copyfile(mappedFolder / "raw.dat", folder / "raw.dat")
    with open(folder / "raw.dat", "r+b") as data:
        data.truncate((folder / "raw.dat").stat().st_size - np.dtype("<f4").itemsize)
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


def baselineLocationProblem(baseline: Path) -> str | None:
    """Why `baseline` may not hold a saved run, or None.

    A saved run lies outside the repository or under `build/`, never in the UC1
    build tree, where the output under test is written, and never in a folder
    that holds the repository.
    """
    folder = baseline.resolve()
    if folder == REPOSITORY_ROOT or folder in REPOSITORY_ROOT.parents:
        return f"{folder} holds the repository"
    if folder == BUILD_ROOT or BUILD_ROOT in folder.parents:
        return f"{folder} is in the UC1 build tree {BUILD_ROOT}"
    if REPOSITORY_ROOT in folder.parents and REPOSITORY_ROOT / "build" not in folder.parents:
        return f"{folder} is in the repository but not under build/"
    return None


def saveBaseline(output: Path, baseline: Path) -> list[str]:
    """Copy the six images into a new or empty `baseline`. Nothing is deleted."""
    if baseline.exists() and (not baseline.is_dir() or any(baseline.iterdir())):
        return [f"{baseline} already holds files. Save into a new folder; an old saved run "
                "is removed by the owner, not by this script"]
    baseline.mkdir(parents=True, exist_ok=True)
    for fileName in OUTPUTS:
        shutil.copyfile(output / fileName, baseline / fileName)
    print(f"Saved this run's images in {baseline}. After review, put these in check-uc1.py:")
    for name, files in (("RECORDED_SHA256", RECORDED_SHA256),
                        ("RECORDED_BASELINE_SHA256", KMEANS_OUTPUTS)):
        print(f"  {name}:")
        for fileName in files:
            digest = hashlib.sha256((baseline / fileName).read_bytes()).hexdigest()
            print(f'    "{fileName}": "{digest}",')
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="folder holding a saved run's kmeans.bmp and imageRGB.bmp on 002-04")
    parser.add_argument("--save-baseline", action="store_true",
                        help="run on 002-04 and save that run in --baseline instead of checking")
    arguments = parser.parse_args()

    problem = baselineLocationProblem(arguments.baseline)
    if problem:
        print(f"ERROR: --baseline {arguments.baseline}: {problem}.")
        return 1
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
        mappedFolder, reflectance = writeMappedCube()
        output, failures = runMappedCube(mappedFolder, reflectance)
        if arguments.save_baseline:
            if not failures:
                failures += saveBaseline(output, arguments.baseline)
        else:
            if not failures:
                failures += compareWithRecordedRun(output, arguments.baseline)
                failures += checkPatchedPaths(output, reflectance)
            failures += checkBandGuard()
            failures += checkShortRead(mappedFolder)
            failures += checkMissingWeights(mappedFolder)
    finally:
        LOCK_PATH.unlink(missing_ok=True)

    print()
    for failure in failures:
        print(f"FAIL: {failure}")
    print("PASS" if not failures else f"{len(failures)} check(s) failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
