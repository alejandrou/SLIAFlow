"""Check which of IUMA's captures under input/ run through UC1 and UC2 (SLIA-040).

For every capture SLIAFlow offers (`SLIAFlowCaptures.findCaptures`, the same
rule as the module), or only those named with `--capture`, five steps:

1. Cube. SLIAFlow's own `loadCalibratedCube` accepts the cube (path length,
   data type 4, bsq, byte order 0, no header offset, nanometres, one number per
   band, size), its `describeUc1Input` maps its wavelengths onto UC1's bands
   and accepts the capture's name, and `assertUc1PathsFit` finds UC1's paths
   for it short enough (ADR-0004 decisions 4 and 6). These are the checks
   SLIAFlow makes when Capture is pressed, not a copy of them, so a capture
   refused here is one SLIAFlow refuses before freezing, with the same reason.
2. UC1. SLIAFlow's own `writeUc1Input` maps the cube onto the 93 model bands
   under the staged build's input folder, re-reading it before and after the
   copy as before a run (`assertUc1InputUnchanged`). What it wrote must be,
   byte for byte, the mapping `uc_oracles.mappedCubeDifference` restates from
   the cube's header. UC1 is run on it, as SLIAFlow runs it, within the
   module's 60 s timeout. It must exit 0 and write its six images at the
   cube's samples x lines.
3. UC1 oracles. `CalibratedImage_BIP.bmp` must be the image predicted from the
   cube, and `pca.bmp` within one grey level of NumPy's first principal
   component (`uc_oracles.py`, as `check-uc1.py` checks them).
4. UC2. SLIAFlow's own checks before a UC2 run pass (`Uc2Build.assertRunnable`:
   file names, patch 0002's bands at 480, 540 and 710 nm, path lengths), and
   UC2, run on the capture's folder within the module's 30 s timeout, must
   write its PNG at the cube's size, pixel-identical to the NumPy replica.
5. The run times of UC1 and UC2.

PASS means that the pipelines ran and agree with an independent
recomputation. It says nothing about whether a classification is right: UC1's
model was trained on another camera (ADR-0004 decision 5).

K-means outputs change from run to run, so only their size is checked. The
recorded hashes of one cube stay with `check-uc1.py` and `check-uc2.py`.

Usage:

    .\\.venv\\Scripts\\python.exe scripts\\development\\check-captures.py
    .\\.venv\\Scripts\\python.exe scripts\\development\\check-captures.py --capture S-N-005-01
    .\\.venv\\Scripts\\python.exe scripts\\development\\check-captures.py --input D:\\delivery

`--input` checks the captures of another folder laid out as `input/`, such as a
delivery before it is copied in.

It prints a Markdown table at the end. A run over every capture in input/
(no `--capture`, no other `--input`) also writes it to
`build/captures/compatibility.md`, for docs/development/capture_compatibility.md;
a partial run leaves that report as it was.
It exits 1 if any capture fails a step. A capture that cannot be read is a
failing row, never the end of the check. It never writes into `input/` or
`workspace/components/`: the mapped cube goes to one reused folder under the
UC1 build, and UC2's PNG under `build/uc2/check/`. It holds `.uc1-runner.lock`
and `.uc2-runner.lock` for the whole check, as SLIAFlow does for a run.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import time
import types
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from uc_oracles import (
    MAX_PCA_LEVEL_DIFFERENCE,
    calibratedBmpDifference,
    decodePng,
    mappedCubeDifference,
    pcaDifference,
    readBmp,
    readMappedCube,
    replicateBvMap,
    uc2Planes,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# Which captures exist and which cubes are accepted are the module's own rules,
# so that this report agrees with SLIAFlow. SLIAFlowLib's __init__ imports
# Slicer, so the package is registered without running it, and only modules
# that need nothing from Slicer are imported from it.
_library = types.ModuleType("SLIAFlowLib")
_library.__path__ = [str(REPOSITORY_ROOT / "extensions" / "SLIAFlow" / "SLIAFlow" / "SLIAFlowLib")]
sys.modules["SLIAFlowLib"] = _library
from SLIAFlowLib.SLIAFlowCalibratedCube import (  # noqa: E402
    CalibratedCube,
    CalibratedCubeError,
    loadCalibratedCube,
)
from SLIAFlowLib.SLIAFlowCaptures import captureHeader, findCaptures  # noqa: E402
from SLIAFlowLib.SLIAFlowUc1Input import (  # noqa: E402
    Uc1Input,
    describeUc1Input,
    writeUc1Input,
)
from SLIAFlowLib.SLIAFlowUc1Run import Uc1RunError, assertUc1PathsFit  # noqa: E402
from SLIAFlowLib.SLIAFlowUc2Run import Uc2Build, Uc2RunError  # noqa: E402

INPUT_ROOT = REPOSITORY_ROOT / "input"
UC1_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "UC1"
UC1_SOURCE = UC1_ROOT / "gpu_single_bsq" / "source"
UC1_EXECUTABLE = UC1_SOURCE / "stratum.opt.intermediate.exe"
UC1_LOCK = UC1_ROOT / ".uc1-runner.lock"
# One folder for every capture, so that 16 captures leave one mapped cube.
MAPPED_CASE_NAME = "check-capture"
UC1_OUTPUTS = ("pca.bmp", "svm.bmp", "knn.bmp", "kmeans.bmp", "imageRGB.bmp",
               "CalibratedImage_BIP.bmp")
# SLIAFlowUc1Run.RUN_TIMEOUT_SEC and SLIAFlowUc2Run.RUN_TIMEOUT_SEC: a run the
# module would kill is a failure here too.
UC1_TIMEOUT_SEC = 60
UC2_TIMEOUT_SEC = 30

UC2_ROOT = REPOSITORY_ROOT / "build" / "uc2"
UC2_EXECUTABLE = UC2_ROOT / "source" / "uc2_bvmap.exe"
UC2_LOCK = UC2_ROOT / ".uc2-runner.lock"
UC2_RUN_DIRECTORY = UC2_ROOT / "check" / "capture"

REPORT = REPOSITORY_ROOT / "build" / "captures" / "compatibility.md"
STEPS = ("Cube", "UC1", "UC1 oracles", "UC2")
NOT_RUN = "not run"


@dataclass
class CaptureResult:
    id: str
    size: str = "-"
    steps: dict = field(default_factory=dict)
    uc1Seconds: float | None = None
    uc2Seconds: float | None = None

    @property
    def passed(self) -> bool:
        return all(self.steps.get(step, "").startswith("PASS") for step in STEPS)


def lastLines(text: str, count: int = 3) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " / ".join(lines[-count:]) or "no output"


def runUc1(folder: Path) -> tuple[subprocess.CompletedProcess | None, float]:
    started = time.perf_counter()
    try:
        result = subprocess.run([str(UC1_EXECUTABLE), str(folder)], cwd=UC1_SOURCE,
                                capture_output=True, text=True, errors="replace",
                                timeout=UC1_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        result = None
    return result, time.perf_counter() - started


def checkCube(result: CaptureResult, inputRoot: Path, captureId: str) -> Uc1Input:
    cube = loadCalibratedCube(captureHeader(inputRoot, captureId))
    result.size = f"{cube.lines} x {cube.samples}"
    uc1Input = describeUc1Input(cube, UC1_ROOT / "input")
    assertUc1PathsFit(uc1Input)
    result.steps["Cube"] = "PASS"
    return uc1Input


def checkUc1(result: CaptureResult, uc1Input: Uc1Input) -> tuple[Path, np.ndarray] | None:
    """Run UC1 on the cube as SLIAFlow maps it; its output folder and the mapped cube if it passes."""
    cube = uc1Input.cube
    # SLIAFlow's own writer, but into the one reused folder, not the capture's.
    mapped = replace(uc1Input, name=MAPPED_CASE_NAME,
                     folder=(UC1_ROOT / "input" / MAPPED_CASE_NAME).resolve())
    output = UC1_SOURCE / "output" / MAPPED_CASE_NAME
    shutil.rmtree(output, ignore_errors=True)
    writeUc1Input(mapped)
    difference = mappedCubeDifference(cube.headerPath.parent, mapped.folder)
    if difference is not None:
        result.steps["UC1"] = f"FAIL: SLIAFlow's mapped cube is not the expected mapping: {difference}"
        return None
    runStart = time.time()
    completed, elapsed = runUc1(mapped.folder)
    result.uc1Seconds = elapsed
    if completed is None:
        result.steps["UC1"] = f"FAIL: no exit within the module's {UC1_TIMEOUT_SEC} s; killed"
        return None
    if completed.returncode != 0:
        result.steps["UC1"] = (f"FAIL: exit {completed.returncode}: "
                               f"{lastLines(completed.stderr or completed.stdout)}")
        return None
    for fileName in UC1_OUTPUTS:
        path = output / fileName
        if not path.is_file() or path.stat().st_mtime < runStart - 1:
            result.steps["UC1"] = f"FAIL: {fileName} was not written by this run"
            return None
        shape = readBmp(path).shape
        if shape != (cube.lines, cube.samples, 3):
            result.steps["UC1"] = (f"FAIL: {fileName} is {shape[1]} x {shape[0]}, not the "
                                   f"cube's {cube.samples} x {cube.lines}")
            return None
    result.steps["UC1"] = "PASS"
    return output, readMappedCube(mapped.folder)


def checkUc1Oracles(result: CaptureResult, output: Path, reflectance: np.ndarray) -> None:
    problems = []
    detail = calibratedBmpDifference(output, reflectance)
    if detail is not None:
        problems.append(f"CalibratedImage_BIP.bmp is not the prediction: {detail}")
    worst, exact = pcaDifference(output, reflectance)
    if worst > MAX_PCA_LEVEL_DIFFERENCE:
        problems.append(f"pca.bmp is up to {worst} grey levels from NumPy, over "
                        f"{MAX_PCA_LEVEL_DIFFERENCE}")
    result.steps["UC1 oracles"] = ("FAIL: " + "; ".join(problems) if problems else
                                   f"PASS ({exact:.2%} of pca.bmp exact)")


def checkUc2(result: CaptureResult, cube: CalibratedCube) -> None:
    # What SLIAFlow refuses before a UC2 run is refused here, with its reason.
    Uc2Build(UC2_ROOT).assertRunnable(cube)
    cubeFolder = cube.headerPath.parent
    shutil.rmtree(UC2_RUN_DIRECTORY, ignore_errors=True)
    UC2_RUN_DIRECTORY.mkdir(parents=True)
    # Where SLIAFlow looks for the map, so a name UC2 does not write fails here too.
    png = UC2_RUN_DIRECTORY / Uc2Build.outputFileName(cube)
    started = time.perf_counter()
    try:
        completed = subprocess.run([str(UC2_EXECUTABLE), cubeFolder.as_posix()],
                                   cwd=UC2_RUN_DIRECTORY, capture_output=True, text=True,
                                   errors="replace", timeout=UC2_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        result.uc2Seconds = time.perf_counter() - started
        result.steps["UC2"] = f"FAIL: no exit within the module's {UC2_TIMEOUT_SEC} s; killed"
        return
    result.uc2Seconds = time.perf_counter() - started
    # UC2 exits 0 after several failures, so its output is read whatever the code.
    if completed.returncode != 0 or not png.is_file():
        result.steps["UC2"] = (f"FAIL: exit {completed.returncode}, "
                               f"{'PNG written' if png.is_file() else 'no PNG'}: "
                               f"{lastLines(completed.stdout + completed.stderr)}")
        return
    image = decodePng(png)
    if image.shape != (cube.lines, cube.samples, 3):
        result.steps["UC2"] = (f"FAIL: {png.name} is {image.shape[1]} x {image.shape[0]}, "
                               f"not the cube's {cube.samples} x {cube.lines}")
        return
    expected = replicateBvMap(*uc2Planes(cubeFolder))
    differing = int(np.count_nonzero(np.any(image != expected, axis=-1)))
    result.steps["UC2"] = (f"FAIL: {differing} pixel(s) differ from the NumPy replica"
                           if differing else "PASS")


def runStep(result: CaptureResult, step: str, check):
    """check()'s value, or None with the step failed by whatever it raised.

    A capture that cannot be read, or that breaks an oracle, fails this one
    step of this one capture; the other captures are still checked and the
    report is still written.
    """
    try:
        return check()
    except (CalibratedCubeError, Uc1RunError, Uc2RunError) as error:
        # The module's refusal, in the words the operator would see.
        result.steps[step] = f"FAIL: {error}"
    except Exception as error:
        result.steps[step] = f"FAIL: {type(error).__name__}: {error}"
    return None


def checkCapture(inputRoot: Path, captureId: str) -> CaptureResult:
    result = CaptureResult(captureId)
    uc1Input = runStep(result, "Cube", lambda: checkCube(result, inputRoot, captureId))
    if uc1Input is not None:
        uc1 = runStep(result, "UC1", lambda: checkUc1(result, uc1Input))
        if uc1 is not None:
            runStep(result, "UC1 oracles", lambda: checkUc1Oracles(result, *uc1))
        runStep(result, "UC2", lambda: checkUc2(result, uc1Input.cube))
    for step in STEPS:
        result.steps.setdefault(step, NOT_RUN)
    return result


def tableCell(text: str) -> str:
    return text.replace("|", "\\|")


def seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def markdownTable(results: list[CaptureResult], when: str) -> str:
    rows = ["| Capture | Lines x samples | Cube | UC1 | UC1 oracles | UC2 | UC1 s | UC2 s |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for result in results:
        rows.append("| " + " | ".join([
            result.id, result.size, *(tableCell(result.steps.get(step, NOT_RUN)) for step in STEPS),
            seconds(result.uc1Seconds), seconds(result.uc2Seconds)]) + " |")
    passed = sum(result.passed for result in results)
    return (f"Checked {when} with scripts/development/check-captures.py: {passed} of "
            f"{len(results)} captures pass every step.\n\n" + "\n".join(rows) + "\n")


def acquire(lock: Path) -> bool:
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.close(descriptor)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", action="append", default=None, metavar="ID",
                        help="check only this capture (repeatable); default: every capture")
    parser.add_argument("--input", type=Path, default=INPUT_ROOT, metavar="DIR",
                        help="the folder that holds the captures; default: input/")
    arguments = parser.parse_args()
    inputRoot = arguments.input.resolve()

    for executable, script in ((UC1_EXECUTABLE, "build-uc1.ps1"), (UC2_EXECUTABLE, "build-uc2.ps1")):
        if not executable.is_file():
            print(f"ERROR: {executable} is missing. Build it with scripts\\development\\{script}.")
            return 1
    captureIds = arguments.capture or [capture.id for capture in findCaptures(inputRoot)]
    if not captureIds:
        print(f"ERROR: {inputRoot} holds no capture.")
        return 1
    if not acquire(UC1_LOCK):
        print(f"ERROR: {UC1_LOCK} exists, so a UC1 run holds the build. Wait for it.")
        return 1
    if not acquire(UC2_LOCK):
        UC1_LOCK.unlink(missing_ok=True)
        print(f"ERROR: {UC2_LOCK} exists, so a UC2 run holds the build. Wait for it.")
        return 1

    print("PASS means the pipelines ran and agree with an independent recomputation; "
          "it says nothing about accuracy.\n")
    results = []
    try:
        for captureId in captureIds:
            started = time.perf_counter()
            result = checkCapture(inputRoot, captureId)
            results.append(result)
            print(f"{captureId} ({result.size}), {time.perf_counter() - started:.0f} s")
            for step in STEPS:
                print(f"  {step:<12} {result.steps.get(step, NOT_RUN)}")
    finally:
        UC1_LOCK.unlink(missing_ok=True)
        UC2_LOCK.unlink(missing_ok=True)

    table = markdownTable(results, datetime.date.today().isoformat())
    print()
    print(table)
    # The report is the whole of input/; a partial run would replace it with a few rows.
    if arguments.capture is None and inputRoot == INPUT_ROOT.resolve():
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(table, encoding="utf-8")
        print(f"Written to {REPORT}")
    else:
        print(f"Not written to {REPORT}: only a run over every capture in input/ writes it.")
    failed = [result.id for result in results if not result.passed]
    print("PASS" if not failed else f"FAIL: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
