"""Time UC1 on the configured cube, one change at a time, and find the largest cube it takes.

The measurement tool of SLIA-034 (results in docs/development/uc1_performance.md).
It never runs in the product build `build/uc1/UC1/`: every trial gets its own
folder under `build/uc1/trials/<trial>/`, laid out as UC1 expects,

    <trial>/gpu_single_bsq/source/   the binary, parameters.txt, output/
    <trial>/svm_model/               a copy of the staged model

so a trial can change `parameters.txt` or run a variant binary built by
`build-uc1.ps1 -Variant` without touching what SLIAFlow runs. UC1 is given the
configured cube mapped onto the model bands, written once into
`build/uc1/trials/input/<cube>/` by SLIAFlow's own mapping
(`SLIAFlowUc1Input`), so the input is the one a Capture produces.

For every run it records the wall time of the UC1 process, UC1's own CSV
timings (the intermediate build prints `<stage> , <ms> ,ms`), `Time
simulation`, the K-means iterations, the rise of the GPU's used memory over its
idle level (device-wide: this WDDM driver reports no per-process figure) and
the process's peak working set and peak commit. The first run of a trial is a
warm-up and is not counted.

Commands:

    measure-uc1.py run baseline
    measure-uc1.py run kmeans-k12 --set kmeans_k=12
    measure-uc1.py run cuda-eager --env CUDA_MODULE_LOADING=EAGER
    measure-uc1.py run pca-single --binary build/uc1/variants/pca-single/gpu_single_bsq/source/stratum.opt.intermediate.exe
    measure-uc1.py sizes
    measure-uc1.py sizes --repeat 3 2300x2300 2430x2430
    measure-uc1.py report
    measure-uc1.py recheck

UC1 exits 0 even when a CUDA call fails, so every run's outputs are checked
(present, the cube's size, more than one colour) and a trial stops at the
first run that fails the check. `run` compares the trial's outputs with the
`baseline` trial's (`--baseline` names another): pixels that differ, and the
exact pixel count per class of every kept run. It writes
`build/uc1/trials/results/<trial>.json`. `sizes` tiles the mapped cube to
growing sizes under `build/uc1/trials/cubes/`, runs UC1 on each (`--repeat`
times) up to the first size that fails, and deletes every tiled cube and its
outputs. `report` prints the results as Markdown tables. `recheck` checks and
compares again the outputs the trials kept, after a change to the checks.

Written for SLIAFlow. It never writes into `input/`, `workspace/components/` or
`build/uc1/UC1/`, and holds `build/uc1/UC1/.uc1-runner.lock` while UC1 runs, so
it never measures alongside a Capture.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import dataclasses
import hashlib
import importlib
import importlib.util
import itertools
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "UC1"
PRODUCT_SOURCE = PRODUCT_ROOT / "gpu_single_bsq" / "source"
PRODUCT_BINARY = PRODUCT_SOURCE / "stratum.opt.intermediate.exe"
PRODUCT_PARAMETERS = PRODUCT_SOURCE / "parameters.txt"
PRODUCT_MODEL = PRODUCT_ROOT / "svm_model"
LOCK_PATH = PRODUCT_ROOT / ".uc1-runner.lock"
TRIALS_ROOT = REPOSITORY_ROOT / "build" / "uc1" / "trials"
TRIAL_INPUT_ROOT = TRIALS_ROOT / "input"
CUBES_ROOT = TRIALS_ROOT / "cubes"
RESULTS_ROOT = TRIALS_ROOT / "results"
SLIAFLOW_LIBRARY = REPOSITORY_ROOT / "extensions" / "SLIAFlow" / "SLIAFlow" / "SLIAFlowLib"
# SLIAFlowLogic.CALIBRATED_CUBE_RELATIVE_PATH: the cube every Capture runs on.
CONFIGURED_CUBE = REPOSITORY_ROOT / "input" / "002-04" / "LCTF_Calibrated_Cube_Single.hdr"
BASELINE_TRIAL = "baseline"

# parameters.txt, in the order main.cu reads it.
PARAMETER_NAMES = (
    "hysime", "pca_bands", "pca_epsilon", "classes", "min_probability", "max_probability",
    "svm_iterations", "svm_epsilon", "lambda", "knn_neighbours", "knn_window",
    "distance_metric", "kmeans_k", "kmeans_min_error", "kmeans_max_iterations",
)
PARAMETERS_BY_NAME = set(PARAMETER_NAMES)

OUTPUTS = ("CalibratedImage_BIP.bmp", "pca.bmp", "svm.bmp", "knn.bmp", "kmeans.bmp", "imageRGB.bmp")
# The release binary writes only the final class map.
RELEASE_OUTPUTS = ("imageRGB.bmp",)
# Identical from run to run on the unpatched and the patched build (SLIA-033).
DETERMINISTIC_OUTPUTS = OUTPUTS[:4]
# K-means, and the majority vote that uses it, differ a little on every run.
KMEANS_OUTPUTS = OUTPUTS[4:]
# Outputs whose colours are classes: counted per colour.
CLASS_OUTPUTS = ("svm.bmp", "knn.bmp", "imageRGB.bmp")
# UC1's class colours as #RRGGBB (SLIAFlowCube.GROUND_TRUTH_CLASSES).
CLASS_NAMES = {"#00ff00": "normal", "#ff0000": "tumour", "#0000ff": "hypervascularized",
               "#000000": "background", "#ffffff": "unlabelled"}

STAGE_LINE = re.compile(r"^(?P<stage>[^,]+?) , (?P<ms>[0-9.]+) ,ms\s*$")
SIMULATION_LINE = re.compile(r"Time simulation ---> (?P<ms>[0-9.]+) ms")
KMEANS_ITERATIONS_LINE = re.compile(r"KMeansIterations: (?P<n>[0-9]+)")
KMEANS_ERROR_LINE = re.compile(r"KMeansError: (?P<e>[0-9.eE+-]+)")

RUN_TIMEOUT_SEC = 120
SIZE_TIMEOUT_SEC = 900
# nvidia-smi's own loop; it delivers a sample about every 60 ms on this laptop.
GPU_SAMPLE_MS = 50
# Idle GPU memory is the median of the samples taken in this time before start.
GPU_IDLE_SEC = 1.0
# samples x lines, in the order they are run: growing pixel counts. 4096 x 2160
# is the raw LCTF frame (ADR-0004 context).
SIZE_LADDER = ((1080, 1080), (1620, 1620), (2160, 2160), (2700, 2700), (4096, 2160), (3240, 3240))
MIB = 1024 * 1024


# ----------------------------------------------------------------------------
# SLIAFlow's mapping, loaded without its package, which needs Slicer
# ----------------------------------------------------------------------------

def sliaflowModule(name: str):
    """One SLIAFlowLib module, imported without SLIAFlowLib/__init__.py.

    The package's __init__ imports the Slicer module classes; the cube and
    mapping modules need only NumPy. Loading them this way keeps one mapping,
    the one SLIAFlow runs, instead of a copy here.
    """
    if "SLIAFlowLib" not in sys.modules:
        package = types.ModuleType("SLIAFlowLib")
        package.__path__ = [str(SLIAFLOW_LIBRARY)]
        sys.modules["SLIAFlowLib"] = package
    return importlib.import_module(f"SLIAFlowLib.{name}")


def checkUc1Module():
    """check-uc1.py, for its BMP reader."""
    spec = importlib.util.spec_from_file_location("check_uc1", Path(__file__).with_name("check-uc1.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describeConfiguredInput():
    cubeModule = sliaflowModule("SLIAFlowCalibratedCube")
    inputModule = sliaflowModule("SLIAFlowUc1Input")
    cube = cubeModule.loadCalibratedCube(CONFIGURED_CUBE)
    return inputModule, inputModule.describeUc1Input(cube, TRIAL_INPUT_ROOT)


def prepareConfiguredInput():
    """The mapped configured cube under build/uc1/trials/input, written if absent."""
    inputModule, uc1Input = describeConfiguredInput()
    data = uc1Input.folder / inputModule.INPUT_DATA_FILE_NAME
    expected = uc1Input.samples * uc1Input.lines * uc1Input.bands * 4
    if not data.is_file() or data.stat().st_size != expected:
        started = time.perf_counter()
        inputModule.writeUc1Input(uc1Input)
        print(f"Wrote the mapped cube {uc1Input.folder} in {time.perf_counter() - started:.2f} s")
    return inputModule, uc1Input


# ----------------------------------------------------------------------------
# Machine state
# ----------------------------------------------------------------------------

class SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.wintypes.DWORD), ("BatteryFullLifeTime", ctypes.wintypes.DWORD),
    ]


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def machineState() -> dict:
    status = SystemPowerStatus()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    power = {0: "battery", 1: "mains"}.get(status.ACLineStatus, "unknown")
    scheme = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True)
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,pstate,temperature.gpu,clocks.sm,"
         "clocks.max.sm,power.draw,memory.used,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True)
    table = subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout
    processes = sorted(set(re.findall(r"([^\\/\s]+\.exe)", table)))
    memory = ctypes.c_ulonglong * 8  # MEMORYSTATUSEX: length, load, then sizes.
    status64 = memory()
    status64[0] = ctypes.sizeof(status64)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status64))
    return {
        "power": power,
        "batteryPercent": status.BatteryLifePercent,
        "powerScheme": scheme.stdout.strip().split("(")[-1].rstrip(")") if scheme.stdout else "",
        "gpu": gpu.stdout.strip(),
        "gpuProcesses": processes,
        "hostMemoryTotalMiB": round(status64[1] / MIB),
        "hostMemoryFreeMiB": round(status64[2] / MIB),
    }


class GpuMemorySampler:
    """Device-wide used GPU memory, sampled by nvidia-smi in its own loop."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, int]] = []
        self._process = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
             "-lms", str(GPU_SAMPLE_MS)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        for line in self._process.stdout:
            line = line.strip()
            if line.isdigit():
                self.samples.append((time.perf_counter(), int(line)))

    def stop(self) -> None:
        self._process.terminate()
        self._process.wait()
        self._reader.join(timeout=2)

    def idleAndPeak(self, start: float, end: float) -> tuple[int | None, int | None]:
        idle = [value for when, value in self.samples if start - GPU_IDLE_SEC <= when < start]
        during = [value for when, value in self.samples if start <= when <= end]
        return (int(statistics.median(idle)) if idle else None,
                max(during) if during else None)


def processPeakMemory(process: subprocess.Popen) -> tuple[float | None, float | None]:
    """Peak working set and peak commit of a finished process, in MiB."""
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    handle = getattr(process, "_handle", None)
    if handle is None or not ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(int(handle)), ctypes.byref(counters), counters.cb):
        return None, None
    return counters.PeakWorkingSetSize / MIB, counters.PeakPagefileUsage / MIB


# ----------------------------------------------------------------------------
# Trial folders and runs
# ----------------------------------------------------------------------------

def readParameters(path: Path) -> dict[str, str]:
    values = path.read_text(encoding="ascii").split()
    if len(values) != len(PARAMETER_NAMES):
        raise SystemExit(f"ERROR: {path} holds {len(values)} values, not {len(PARAMETER_NAMES)}.")
    return dict(zip(PARAMETER_NAMES, values, strict=True))


def prepareTrialFolder(trial: str, binary: Path, parameters: dict[str, str]) -> Path:
    """A fresh folder laid out as UC1 expects, with this trial's binary and parameters."""
    root = TRIALS_ROOT / trial
    shutil.rmtree(root, ignore_errors=True)
    source = root / "gpu_single_bsq" / "source"
    (source / "output" / "rgb").mkdir(parents=True)
    shutil.copy2(binary, source / binary.name)
    shutil.copytree(PRODUCT_MODEL, root / "svm_model")
    (source / "parameters.txt").write_text(
        "".join(f"{parameters[name]}\n" for name in PARAMETER_NAMES), encoding="ascii")
    return source


def parseStdout(stdout: str) -> dict:
    stages: dict[str, float] = {}
    simulation = iterations = error = None
    for line in stdout.splitlines():
        match = STAGE_LINE.match(line.strip())
        if match:
            stages[match["stage"].strip()] = float(match["ms"])
        if (found := SIMULATION_LINE.search(line)):
            simulation = float(found["ms"])
        if (found := KMEANS_ITERATIONS_LINE.search(line)):
            iterations = int(found["n"])
        if (found := KMEANS_ERROR_LINE.search(line)):
            error = float(found["e"])
    return {"stagesMs": stages, "simulationMs": simulation,
            "kmeansIterations": iterations, "kmeansError": error}


def runUc1(source: Path, binaryName: str, inputFolder: Path, environment: dict[str, str],
           timeoutSec: float) -> dict:
    """One UC1 run, with its timings and memory; its outputs stay in output/<cube>."""
    output = source / "output" / inputFolder.name
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    sampler = GpuMemorySampler()
    time.sleep(GPU_IDLE_SEC + 0.2)
    env = dict(os.environ)
    env.update(environment)
    started = time.perf_counter()
    process = subprocess.Popen([str(source / binaryName), str(inputFolder)], cwd=source, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, errors="replace")
    timedOut = False
    try:
        stdout, stderr = process.communicate(timeout=timeoutSec)
    except subprocess.TimeoutExpired:
        timedOut = True
        process.kill()
        stdout, stderr = process.communicate()
    ended = time.perf_counter()
    time.sleep(0.2)
    sampler.stop()
    idle, peak = sampler.idleAndPeak(started, ended)
    peakWorkingSet, peakCommit = processPeakMemory(process)
    result = {
        "exitCode": process.returncode,
        "timedOut": timedOut,
        "wallSec": ended - started,
        "gpuIdleMiB": idle,
        "gpuPeakMiB": peak,
        "gpuRiseMiB": None if idle is None or peak is None else peak - idle,
        "hostPeakWorkingSetMiB": peakWorkingSet,
        "hostPeakCommitMiB": peakCommit,
        "outputsWritten": sorted(path.name for path in output.glob("*.bmp")),
        "stderrTail": stderr.strip().splitlines()[-3:],
        "stdoutTail": stdout.strip().splitlines()[-3:],
    }
    result.update(parseStdout(stdout))
    return result


def acquireLock() -> None:
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"ERROR: {LOCK_PATH} exists, so a UC1 run holds the build. Wait for it.") from None
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.close(descriptor)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ----------------------------------------------------------------------------
# Output comparison
# ----------------------------------------------------------------------------

def classCounts(pixels: np.ndarray) -> dict[str, int]:
    """The exact number of pixels per colour, largest first, colours as #RRGGBB."""
    flat = pixels.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-counts)
    # BMP stores blue, green, red.
    return {f"#{int(c[2]):02x}{int(c[1]):02x}{int(c[0]):02x}": int(n)
            for c, n in zip(colours[order], counts[order], strict=True)}


def differingPixels(first: np.ndarray, second: np.ndarray) -> int | None:
    if first.shape != second.shape:
        return None
    return int(np.any(first != second, axis=2).sum())


def differing(first: np.ndarray, second: np.ndarray) -> float | None:
    count = differingPixels(first, second)
    return None if count is None else count / (first.shape[0] * first.shape[1])


def expectedOutputs(binaryName: str) -> tuple[str, ...]:
    return OUTPUTS if "intermediate" in binaryName else RELEASE_OUTPUTS


def outputProblems(folder: Path, expected: tuple[str, ...], samples: int, lines: int,
                   readBmp) -> list[str]:
    """Why a run's outputs cannot be a classification of the cube, or nothing.

    UC1 checks almost none of its CUDA calls and exits 0 after a failed
    allocation, so the exit code proves nothing. Each expected image must
    exist, be a BMP of the cube's size and hold more than one colour: a failed
    run writes black or single-colour images (Size limit in
    uc1_performance.md). This catches a step that did not run, not a subtly
    wrong one; that is what the comparison with the baseline is for.
    """
    problems = []
    for name in expected:
        path = folder / name
        if not path.is_file():
            problems.append(f"{name} missing")
            continue
        try:
            image = readBmp(path)
        except ValueError as error:
            problems.append(str(error))
            continue
        if image.shape[:2] != (lines, samples):
            problems.append(f"{name} is {image.shape[1]} x {image.shape[0]}, not {samples} x {lines}")
        elif not np.any(image != image[0, 0]):
            problems.append(f"{name} is a single colour")
    return problems


def runFolders(trial: str) -> list[Path]:
    return sorted((TRIALS_ROOT / trial / "runs").glob("run-*"))


def countRange(counts: list[dict[str, int]]) -> dict[str, list[int]]:
    """For each colour, the fewest and most pixels it had over the runs."""
    colours = list(dict.fromkeys(colour for run in counts for colour in run))
    return {colour: [min(run.get(colour, 0) for run in counts), max(run.get(colour, 0) for run in counts)]
            for colour in colours}


def describeOutputs(trial: str, baseline: str, readBmp) -> dict:
    """The trial's outputs against the baseline trial's, and against themselves."""
    mine = runFolders(trial)
    theirs = runFolders(baseline)
    comparison = {}
    for name in OUTPUTS:
        mineImages = [readBmp(folder / name) for folder in mine if (folder / name).is_file()]
        theirImages = [readBmp(folder / name) for folder in theirs if (folder / name).is_file()]
        if not mineImages or not theirImages:
            comparison[name] = {"missing": True}
            continue
        entry: dict = {
            "hashesWithinTrial": len({sha256(folder / name) for folder in mine}),
        }
        if trial == baseline:
            pairs = [differingPixels(a, b) for a, b in itertools.combinations(mineImages, 2)]
        else:
            pairs = [differingPixels(a, b) for a in mineImages for b in theirImages]
        pairs = [pair for pair in pairs if pair is not None]
        pixels = mineImages[0].shape[0] * mineImages[0].shape[1]
        entry["pixels"] = pixels
        entry["differingPixelsVsBaseline"] = [min(pairs), max(pairs)] if pairs else None
        entry["differingVsBaseline"] = [min(pairs) / pixels, max(pairs) / pixels] if pairs else None
        if trial != baseline:
            entry["identicalToBaseline"] = sha256(mine[0] / name) == sha256(theirs[0] / name)
        if name in CLASS_OUTPUTS:
            counts = [classCounts(image) for image in mineImages]
            entry["classCountsPerRun"] = counts
            entry["classCountRange"] = countRange(counts)
        if name == "kmeans.bmp":
            entry["clusters"] = [len(classCounts(image)) for image in mineImages]
        if name == "pca.bmp" and mineImages[0].shape == theirImages[0].shape:
            entry["maxGreyLevelDifference"] = int(np.abs(
                mineImages[0][..., 0].astype(int) - theirImages[0][..., 0].astype(int)).max())
        comparison[name] = entry
    return comparison


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def summarise(values: list[float]) -> dict | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def commandRun(arguments) -> int:
    binary = Path(arguments.binary).resolve() if arguments.binary else PRODUCT_BINARY
    if not binary.is_file():
        print(f"ERROR: {binary} is missing. Build it with scripts\\development\\build-uc1.ps1.")
        return 1
    parameters = readParameters(PRODUCT_PARAMETERS)
    for assignment in arguments.set or []:
        name, _, value = assignment.partition("=")
        if name not in PARAMETERS_BY_NAME:
            print(f"ERROR: {name} is not a UC1 parameter. Known: {', '.join(PARAMETER_NAMES)}")
            return 1
        parameters[name] = value
    environment = dict(assignment.partition("=")[::2] for assignment in arguments.env or [])

    _, uc1Input = prepareConfiguredInput()
    source = prepareTrialFolder(arguments.trial, binary, parameters)
    runsRoot = TRIALS_ROOT / arguments.trial / "runs"
    state = machineState()
    print(f"Trial {arguments.trial}: {binary.name} ({sha256(binary)[:12]}), "
          f"{arguments.warmups} warm-up + {arguments.runs} runs on {uc1Input.folder}")
    print(f"  {state['power']}, {state['powerScheme']}, GPU {state['gpu']}")

    readBmp = checkUc1Module().readBmp
    expected = expectedOutputs(binary.name)
    runs = []
    acquireLock()
    try:
        for index in range(arguments.warmups + arguments.runs):
            result = runUc1(source, binary.name, uc1Input.folder, environment, RUN_TIMEOUT_SEC)
            counted = index >= arguments.warmups
            result["warmUp"] = not counted
            result["outputProblems"] = outputProblems(
                source / "output" / uc1Input.folder.name, expected,
                uc1Input.samples, uc1Input.lines, readBmp)
            runs.append(result)
            label = f"run {index - arguments.warmups + 1}" if counted else "warm-up"
            print(f"  {label}: exit {result['exitCode']}, {result['wallSec']:.2f} s wall, "
                  f"Time simulation {result['simulationMs']} ms, GPU +{result['gpuRiseMiB']} MiB, "
                  f"host peak {result['hostPeakWorkingSetMiB'] or 0:.0f} MiB")
            if result["exitCode"] != 0 or result["timedOut"]:
                print(f"ERROR: the run failed: {result['stderrTail'] or result['stdoutTail']}")
                return 1
            if result["outputProblems"]:
                # UC1 exits 0 after a failed CUDA call: the outputs are the only evidence.
                print(f"ERROR: the run exited 0 but its outputs are wrong: "
                      f"{'; '.join(result['outputProblems'])}")
                return 1
            if counted:
                kept = runsRoot / f"run-{index - arguments.warmups + 1}"
                shutil.rmtree(kept, ignore_errors=True)
                shutil.copytree(source / "output" / uc1Input.folder.name, kept)
    finally:
        LOCK_PATH.unlink(missing_ok=True)

    counted = [run for run in runs if not run["warmUp"]]
    stageNames = list(dict.fromkeys(name for run in counted for name in run["stagesMs"]))
    baseline = arguments.baseline
    comparison = None
    if runFolders(baseline):
        comparison = describeOutputs(arguments.trial, baseline, readBmp)
    record = {
        "trial": arguments.trial,
        "command": " ".join(sys.argv),
        "binary": str(binary.relative_to(REPOSITORY_ROOT)
                      if binary.is_relative_to(REPOSITORY_ROOT) else binary),
        "binarySha256": sha256(binary),
        "expectedOutputs": list(expected),
        "parameters": parameters,
        "environment": environment,
        "input": str(uc1Input.folder.relative_to(REPOSITORY_ROOT)),
        "inputSize": [uc1Input.samples, uc1Input.lines, uc1Input.bands],
        "machine": state,
        "measuredAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "wallSec": summarise([run["wallSec"] for run in counted]),
            "simulationMs": summarise([run["simulationMs"] for run in counted]),
            "stagesMs": {name: summarise([run["stagesMs"].get(name) for run in counted])
                         for name in stageNames},
            "gpuRiseMiB": summarise([run["gpuRiseMiB"] for run in counted]),
            "hostPeakWorkingSetMiB": summarise([run["hostPeakWorkingSetMiB"] for run in counted]),
            "hostPeakCommitMiB": summarise([run["hostPeakCommitMiB"] for run in counted]),
            "kmeansIterations": summarise([run["kmeansIterations"] for run in counted]),
        },
        "baseline": baseline,
        "outputs": comparison,
        "runs": runs,
    }
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    resultPath = RESULTS_ROOT / f"{arguments.trial}.json"
    resultPath.write_text(json.dumps(record, indent=2), encoding="utf-8")
    printTrial(record)
    print(f"Results: {resultPath}")
    return 0


def writeTiledCube(inputModule, uc1Input, samples: int, lines: int) -> Path:
    """The mapped cube repeated to samples x lines, one band at a time, under CUBES_ROOT."""
    folder = CUBES_ROOT / f"tile-{samples}x{lines}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    bandValues = uc1Input.samples * uc1Input.lines
    repeats = (-(-lines // uc1Input.lines), -(-samples // uc1Input.samples))
    source = uc1Input.folder / inputModule.INPUT_DATA_FILE_NAME
    with open(source, "rb") as reader, open(folder / inputModule.INPUT_DATA_FILE_NAME, "wb") as writer:
        for _band in range(uc1Input.bands):
            band = np.fromfile(reader, dtype="<f4", count=bandValues)
            band = band.reshape(uc1Input.lines, uc1Input.samples)
            np.ascontiguousarray(np.tile(band, repeats)[:lines, :samples]).tofile(writer)
    tiled = dataclasses.replace(uc1Input, name=folder.name, folder=folder, samples=samples, lines=lines)
    # The header SLIAFlow writes for UC1, with the tiled dimensions.
    (folder / inputModule.INPUT_HEADER_FILE_NAME).write_text(
        inputModule._headerText(tiled), encoding="ascii")
    return folder


def tiledSvmDifference(output: Path, samples: int, lines: int, readBmp) -> float | None:
    """How far svm.bmp of a tiled cube is from the baseline's svm.bmp tiled the same way.

    UC1 checks almost none of its CUDA calls, so a failed allocation can still
    exit 0 and write an image. The SVM classifies each pixel on its own, so on
    a cube tiled from 002-04 its map must be the baseline's map tiled: a large
    difference is a failed run. writeTiledCube tiles the cube from its first
    line down, and UC1 writes the image's first line last (BMP rows are stored
    bottom-up, and readBmp returns them as stored), so both maps are turned
    top-down before the baseline's is tiled. Only that one orientation is
    compared: at sizes that are not a multiple of 1080 the other one is a
    shifted map, which must not pass.
    """
    reference = runFolders(BASELINE_TRIAL)
    produced = output / "svm.bmp"
    if not reference or not produced.is_file():
        return None
    base = readBmp(reference[0] / "svm.bmp")[::-1]
    image = readBmp(produced)[::-1]
    repeats = (-(-lines // base.shape[0]), -(-samples // base.shape[1]), 1)
    return differing(image, np.tile(base, repeats)[:lines, :samples])


# A tiled run whose svm.bmp differs from the tiled baseline in more than this
# share of pixels did not classify the cube: UC1 failed without saying so.
MAX_TILED_SVM_DIFFERENCE = 0.001


def commandSizes(arguments) -> int:
    readBmp = checkUc1Module().readBmp
    inputModule, uc1Input = prepareConfiguredInput()
    source = prepareTrialFolder("sizes", PRODUCT_BINARY, readParameters(PRODUCT_PARAMETERS))
    ladder = [tuple(int(v) for v in size.split("x")) for size in arguments.sizes] or SIZE_LADDER
    state = machineState()
    print(f"Size ladder on {PRODUCT_BINARY.name}: {state['power']}, {state['powerScheme']}, "
          f"host memory free {state['hostMemoryFreeMiB']} MiB of {state['hostMemoryTotalMiB']}")
    results = []
    acquireLock()
    try:
        for samples, lines in ladder:
            started = time.perf_counter()
            folder = writeTiledCube(inputModule, uc1Input, samples, lines)
            writeSec = time.perf_counter() - started
            cubeBytes = (folder / inputModule.INPUT_DATA_FILE_NAME).stat().st_size
            anyFailed = False
            try:
                for attempt in range(1, arguments.repeat + 1):
                    freeBefore = machineState()["hostMemoryFreeMiB"]
                    output = source / "output" / folder.name
                    result = runUc1(source, PRODUCT_BINARY.name, folder, {}, SIZE_TIMEOUT_SEC)
                    problems = outputProblems(output, OUTPUTS, samples, lines, readBmp)
                    svmDifference = tiledSvmDifference(output, samples, lines, readBmp)
                    shutil.rmtree(output, ignore_errors=True)
                    wrong = svmDifference is None or svmDifference > MAX_TILED_SVM_DIFFERENCE
                    failed = result["exitCode"] != 0 or result["timedOut"] or bool(problems) or wrong
                    anyFailed = anyFailed or failed
                    result.update({"samples": samples, "lines": lines, "attempt": attempt,
                                   "cubeBytes": cubeBytes, "cubeWriteSec": writeSec, "failed": failed,
                                   "outputProblems": problems,
                                   "svmDifferenceFromTiledBaseline": svmDifference,
                                   "hostMemoryFreeMiBBefore": freeBefore})
                    results.append(result)
                    svmText = "not compared" if svmDifference is None else f"{svmDifference * 100:.4f} %"
                    print(f"  {samples} x {lines} x {uc1Input.bands} ({cubeBytes / 2**30:.2f} GiB)"
                          f"{f' run {attempt}' if arguments.repeat > 1 else ''}: "
                          f"exit {result['exitCode']}{' (timed out)' if result['timedOut'] else ''}, "
                          f"{result['wallSec']:.1f} s wall, Time simulation {result['simulationMs']} ms, "
                          f"GPU +{result['gpuRiseMiB']} MiB (idle {result['gpuIdleMiB']}, "
                          f"peak {result['gpuPeakMiB']}), "
                          f"host peak {result['hostPeakWorkingSetMiB'] or 0:.0f} MiB "
                          f"(free before {freeBefore}), svm vs tiled baseline {svmText}"
                          f"{', ' + '; '.join(problems) if problems else ''}")
            finally:
                shutil.rmtree(folder, ignore_errors=True)
                shutil.rmtree(source / "output" / folder.name, ignore_errors=True)
            if anyFailed:
                print(f"  First failing size: {result['stderrTail'] or result['stdoutTail']}")
                break
    finally:
        LOCK_PATH.unlink(missing_ok=True)
        shutil.rmtree(CUBES_ROOT, ignore_errors=True)
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    # The default ladder is sizes.json; sizes asked for by name go beside it.
    resultName = "sizes" if not arguments.sizes else "sizes-" + "-".join(arguments.sizes)
    if arguments.repeat > 1:
        resultName += f"-x{arguments.repeat}"
    resultPath = RESULTS_ROOT / f"{resultName}.json"
    resultPath.write_text(json.dumps({"command": " ".join(sys.argv), "machine": state,
                                      "measuredAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                                      "sizes": results}, indent=2), encoding="utf-8")
    print(f"Tiled cubes deleted: {not CUBES_ROOT.exists()}. Results: {resultPath}")
    return 0


def formatRange(summary: dict | None, scale: float = 1.0, digits: int = 0) -> str:
    if summary is None:
        return "-"
    return (f"{summary['median'] * scale:.{digits}f} "
            f"({summary['min'] * scale:.{digits}f}-{summary['max'] * scale:.{digits}f})")


def outputVerdict(record: dict) -> str:
    """One line: which outputs differ from the baseline, and in what share of pixels.

    A deterministic output identical to the baseline, and stable over the
    trial's runs, is not mentioned. K-means outputs always are, as the range
    over every pair of runs; for the baseline itself that range is its own
    run-to-run spread.
    """
    outputs = record["outputs"]
    if outputs is None:
        return "not compared"
    ownSpread = record["trial"] == record["baseline"]
    notes = []
    for name in OUTPUTS:
        entry = outputs.get(name, {})
        short = name.removesuffix(".bmp")
        if entry.get("missing"):
            notes.append(f"{short} missing")
            continue
        span = entry.get("differingVsBaseline")
        if name in DETERMINISTIC_OUTPUTS:
            stable = entry["hashesWithinTrial"] == 1
            if stable and (ownSpread or entry.get("identicalToBaseline")):
                continue
            detail = f"{span[0] * 100:.2f}-{span[1] * 100:.2f} %" if span else "other size"
            notes.append(f"{short} {detail}{'' if stable else ', varies between runs'}")
        elif span:
            notes.append(f"{short} {span[0] * 100:.2f}-{span[1] * 100:.2f} %")
    return "; ".join(notes) if notes else "identical"


def printTrial(record: dict) -> None:
    summary = record["summary"]
    print(f"  wall {formatRange(summary['wallSec'], 1.0, 2)} s; Time simulation "
          f"{formatRange(summary['simulationMs'])} ms; GPU +{formatRange(summary['gpuRiseMiB'])} MiB; "
          f"host {formatRange(summary['hostPeakWorkingSetMiB'])} MiB")
    for name, stage in summary["stagesMs"].items():
        print(f"    {name:<20} {formatRange(stage, 1.0, 1)} ms")
    print(f"  outputs: {outputVerdict(record)}")


def commandReport(arguments) -> int:
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(RESULTS_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime)]
    trials = [record for record in records if "trial" in record]
    print("| Trial | Wall s | Time simulation ms | K-means ms | PCA ms | GPU MiB | Host MiB | Outputs |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for record in trials:
        summary = record["summary"]
        print(f"| {record['trial']} | {formatRange(summary['wallSec'], 1.0, 2)} | "
              f"{formatRange(summary['simulationMs'])} | "
              f"{formatRange(summary['stagesMs'].get('KMEANS'))} | "
              f"{formatRange(summary['stagesMs'].get('PCA'))} | "
              f"{formatRange(summary['gpuRiseMiB'])} | "
              f"{formatRange(summary['hostPeakWorkingSetMiB'])} | "
              f"{outputVerdict(record)} |")
    print()
    print("Pixels per class, median (fewest-most) over the kept runs:")
    print()
    print("| Trial | Image | " + " | ".join(CLASS_NAMES.values()) + " |")
    print("| --- | --- |" + " --- |" * len(CLASS_NAMES))
    for record in trials:
        for name in CLASS_OUTPUTS:
            entry = (record["outputs"] or {}).get(name, {})
            if "classCountsPerRun" not in entry:
                continue
            cells = []
            for colour in CLASS_NAMES:
                counts = [run.get(colour, 0) for run in entry["classCountsPerRun"]]
                low, high = min(counts), max(counts)
                cells.append("0" if high == 0 else f"{int(statistics.median(counts))}"
                             + ("" if low == high else f" ({low}-{high})"))
            print(f"| {record['trial']} | {name.removesuffix('.bmp')} | " + " | ".join(cells) + " |")
    for record in records:
        if "sizes" in record:
            print()
            print("| Size | Run | Cube GiB | Exit | Wall s | Time simulation ms | GPU idle MiB "
                  "| GPU peak MiB | Host MiB | Host free MiB | svm vs tiled baseline | Result |")
            print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for size in record["sizes"]:
                svm = size.get("svmDifferenceFromTiledBaseline")
                print(f"| {size['samples']} x {size['lines']} | {size.get('attempt', 1)} | "
                      f"{size['cubeBytes'] / 2**30:.2f} | "
                      f"{size['exitCode']} | {size['wallSec']:.1f} | {size['simulationMs']} | "
                      f"{size['gpuIdleMiB']} | {size['gpuPeakMiB']} | "
                      f"{size['hostPeakWorkingSetMiB'] or 0:.0f} | {size['hostMemoryFreeMiBBefore']} | "
                      f"{'-' if svm is None else f'{svm * 100:.4f} %'} | "
                      f"{'fails' if size['failed'] else 'runs'} |")
    return 0


def commandRecheck(arguments) -> int:
    """The output check and the baseline comparison again, on the runs every trial kept.

    Only the counted runs keep their outputs; a warm-up's are overwritten by
    the next run. Timings are left as they were measured.
    """
    readBmp = checkUc1Module().readBmp
    failures = 0
    for path in sorted(RESULTS_ROOT.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "trial" not in record:
            continue
        samples, lines, _bands = record["inputSize"]
        expected = tuple(record.get("expectedOutputs") or expectedOutputs(Path(record["binary"]).name))
        folders = runFolders(record["trial"])
        counted = [run for run in record["runs"] if not run["warmUp"]]
        if len(folders) != len(counted):
            print(f"{record['trial']}: {len(folders)} kept runs for {len(counted)} counted; not rechecked")
            failures += 1
            continue
        for run, folder in zip(counted, folders, strict=True):
            run["outputProblems"] = outputProblems(folder, expected, samples, lines, readBmp)
        record["expectedOutputs"] = list(expected)
        if runFolders(record["baseline"]):
            record["outputs"] = describeOutputs(record["trial"], record["baseline"], readBmp)
        record["recheckedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        problems = [f"{folder.name}: {'; '.join(run['outputProblems'])}"
                    for run, folder in zip(counted, folders, strict=True) if run["outputProblems"]]
        failures += bool(problems)
        print(f"{record['trial']}: {len(folders)} runs, {len(expected)} expected outputs each, "
              f"{'; '.join(problems) if problems else 'all present, right size, not single-colour'}; "
              f"outputs: {outputVerdict(record)}")
    return 1 if failures else 0



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="time one trial on the configured cube")
    run.add_argument("trial", help="short name; the trial folder and result file take it")
    run.add_argument("--binary", help="a UC1 binary other than the product's intermediate build")
    run.add_argument("--set", action="append", metavar="NAME=VALUE",
                     help=f"a parameters.txt value: {', '.join(PARAMETER_NAMES)}")
    run.add_argument("--env", action="append", metavar="NAME=VALUE",
                     help="an environment variable for the UC1 process")
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--warmups", type=int, default=1)
    run.add_argument("--baseline", default=BASELINE_TRIAL)

    sizes = commands.add_parser("sizes", help="run the tiled size ladder up to the first failure")
    sizes.add_argument("sizes", nargs="*", metavar="SAMPLESxLINES",
                       help="sizes to run instead of the default ladder")
    sizes.add_argument("--repeat", type=int, default=1,
                       help="runs per size; the ladder stops after a size with any failed run")

    commands.add_parser("report", help="print the results as Markdown tables")
    commands.add_parser("recheck", help="check and compare again the outputs every trial kept")

    arguments = parser.parse_args()
    if arguments.command == "run" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}", arguments.trial):
        parser.error("a trial name is letters, digits and hyphens, at most 32 characters")
    if arguments.command == "sizes" and arguments.repeat < 1:
        parser.error("--repeat is at least 1")
    handler = {"run": commandRun, "sizes": commandSizes, "report": commandReport,
               "recheck": commandRecheck}[arguments.command]
    return handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
