"""Time SLIAFlow's Capture path on the configured cube, inside Slicer, without the window.

The Capture measurement of SLIA-034 (results in docs/development/uc1_performance.md).
It makes the calls SLIAFlowWidget makes when Capture is pressed, in the same
order, on a SLIAFlowLogic of its own, and times each step:

1. check    `loadConfiguredUc1Input`: the cube described and checked against
            the band mapping;
2. prepare  `startUc1Run` up to the process start: lock, previous outputs
            removed, the mapped 93-band cube written for UC1 (`Uc1Run` reports
            the running stage just before the process starts);
3. cube     `loadConfiguredCalibratedCube` and `acceptCube`, which the widget
            does on the main thread while UC1 runs, for the HS Cube panel;
4. uc1      the UC1 process, from the running stage to its exit;
5. validate the five outputs checked (`collectOutputs`);
6. accept   `acceptOutputs`: the five outputs read into volume nodes.

Capture to result is steps 1 to 6: SLIAFlow's own work, not the operator's
wait from click to screen. Three steps are neither made nor timed: the
snapshot of the LiveView frame (it needs the camera), putting the result in
the Tumour Delineation view and drawing the views (they need the window). The
first capture is a warm-up and is not counted.

Run with the configured Slicer and the module source, from the repository root:

    & <slicerExecutable> --no-splash --no-main-window `
        --additional-module-paths extensions\\SLIAFlow\\SLIAFlow `
        --python-script scripts\\development\\measure-capture.py --runs 5

The results are also written to build/uc1/trials/results/capture.json.
Slicer exits with 0 when every capture succeeded.
"""

import argparse
import json
import logging
import re
import statistics
import sys
import time
import traceback
from pathlib import Path

import slicer

SIMULATION_LINE = re.compile(r"Time simulation ---> (?P<ms>[0-9.]+) ms")
STEPS = ("check", "prepare", "cube", "uc1", "validate", "accept", "captureToResult")
RUN_TIMEOUT_SEC = 180


def captureOnce(logic, captureId: str) -> dict:
    """One Capture's worth of logic calls, timed; raises if the capture fails."""
    marks = {}
    finished = []

    def onStage(stage):
        marks[stage] = time.perf_counter()

    started = time.perf_counter()
    uc1Input = logic.loadConfiguredUc1Input()
    checked = time.perf_counter()
    logic.startUc1Run(uc1Input, finished.append, onStage=onStage)
    cubeStarted = time.perf_counter()
    cube = logic.loadConfiguredCalibratedCube()
    logic.acceptCube(cube, captureId)
    cubeEnded = time.perf_counter()

    deadline = time.perf_counter() + RUN_TIMEOUT_SEC
    while not finished:
        if time.perf_counter() > deadline:
            logic.cancelRun()
            raise RuntimeError(f"UC1 did not finish within {RUN_TIMEOUT_SEC} s")
        slicer.app.processEvents()
        time.sleep(0.002)
    result = finished[0]
    validated = time.perf_counter()
    if not result.success:
        raise RuntimeError(result.message)
    logic.acceptOutputs(result.case, captureId, result.outputs)
    accepted = time.perf_counter()

    running = marks["running"]
    exited = marks.get("validating", validated)
    simulation = SIMULATION_LINE.search(result.stdout or "")
    return {
        "check": checked - started,
        "prepare": running - checked,
        "cube": cubeEnded - cubeStarted,
        "uc1": exited - running,
        "validate": validated - exited,
        "accept": accepted - validated,
        "captureToResult": accepted - started,
        "uc1SimulationSec": float(simulation["ms"]) / 1000.0 if simulation else None,
        "outputs": sorted(result.outputs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    arguments, _ = parser.parse_known_args(sys.argv[1:])

    import SLIAFlowLib
    from SLIAFlowLib import SLIAFlowLogic

    logic = SLIAFlowLogic()
    print(f"SLIAFlow logic from {Path(SLIAFlowLib.__file__).parent}")
    print(f"Cube: {logic.calibratedCubeHeader}")
    print(f"UC1:  {logic.uc1Build.executablePath}")

    runs = []
    for index in range(arguments.warmups + arguments.runs):
        timings = captureOnce(logic, logic.newCaptureId())
        counted = index >= arguments.warmups
        timings["warmUp"] = not counted
        runs.append(timings)
        label = f"capture {index - arguments.warmups + 1}" if counted else "warm-up"
        print(f"  {label}: " + ", ".join(f"{step} {timings[step]:.2f} s" for step in STEPS)
              + f", UC1 Time simulation {timings['uc1SimulationSec']} s")

    counted = [run for run in runs if not run["warmUp"]]
    summary = {}
    for step in (*STEPS, "uc1SimulationSec"):
        values = [run[step] for run in counted if run[step] is not None]
        if values:
            summary[step] = {"median": statistics.median(values), "min": min(values),
                             "max": max(values)}
            print(f"  {step:<16} median {summary[step]['median']:.2f} s "
                  f"({summary[step]['min']:.2f}-{summary[step]['max']:.2f})")

    results = logic.repositoryRoot / "build" / "uc1" / "trials" / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "capture.json").write_text(json.dumps({
        "command": " ".join(sys.argv),
        "measuredAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "slicer": slicer.app.applicationVersion,
        "summary": summary,
        "runs": runs,
    }, indent=2), encoding="utf-8")
    print(f"Results: {results / 'capture.json'}")
    logic.removeOutputNodes()
    logic.removeCubeNode()
    return 0


try:
    status = main()
except Exception:
    logging.error("measure-capture failed:\n%s", traceback.format_exc())
    status = 1
slicer.util.exit(status)
