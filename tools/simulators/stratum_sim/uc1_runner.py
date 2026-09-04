"""Run the genuine UC1 CUDA pipeline and recover its one contract map.

Nothing here computes a classification. The calibration, PCA, SVM, KNN, K-means
and majority voting are the vendored UC1 code, compiled unmodified and executed
on the local GPU; this module stages the run, reads back what the binary wrote,
and sends it. Only the scene is synthetic.

The binary yields exactly one of the five contract maps. `main.cu` writes
`output/rgb/{red,green,blue}.txt` and `output/<dataset>/imageRGB.bmp` and
nothing else; `tmdMap`, `majorityVotingProbabilityMap`, `svmProbability` and
`knnProbability` are computed on the device and then discarded. So this producer
populates `majorityVotingMap` and leaves the other four `None`, and never mixes
its output with the arithmetic stand-in's in one session. A real map beside four
invented ones would imply UC1 produced all five.

Two properties of the binary shape everything below.

It is CWD-bound. `fopen("parameters.txt")` and `fopen("../../svm_model/*.bin")`
resolve against the working directory, not against the dataset argument, so the
process must run with its CWD at the staged `gpu_single_bsq/source/` and the
model directory exactly two levels above it.

Its output paths are fixed and shared. Every run of every dataset writes the
same three `output/rgb/*.txt` names, so an existence check cannot tell this
run's output from a previous run's, and a crashed run that leaves last week's
files behind would pass one. Freshness is checked against a timestamp taken
immediately before the process starts, and a stale file is a failure rather than
a result.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy

from . import bmp, config, contract, envi, igtl_transport, tissue, uc1_maps

# The palette inverse is SLIA-012's forward table read backwards. It is imported
# rather than restated so the two directions cannot drift apart.
RGB_TO_CLASS = bmp.RGB_TO_CLASS

# The detail names the scene as well as the pipeline, because they are separate
# claims and only one of them is about the algorithm. A phantom built to have
# the spectral shape of tissue is a different kind of input from a scene mixed
# from camera colour curves, and a result node that cannot say which it was
# leaves a viewer to assume. `SIMULATION_DETAIL` remains the string for any
# dataset that is not a phantom.
SIMULATION_DETAIL = "real UC1 pipeline, synthetic input"
SIMULATION_DETAIL_PHANTOM = "real UC1 pipeline, synthetic tissue phantom"

CYCLE_BANNER = (
    "REAL UC1 OUTPUT cycle {cycle}: genuine UC1 pipeline on a synthetic cube "
    "({detail}). Only majorityVotingMap is produced; the other four maps are "
    "not sent."
)

DEFAULT_PORT = contract.UC1_MAP_PORT
DEFAULT_INTERVAL_SEC = 1.0

BUILD_ROOT_RELATIVE_PATH = Path("build") / "uc1" / "UC1"
SOURCE_RELATIVE_PATH = Path("gpu_single_bsq") / "source"
SVM_MODEL_DIRECTORY_NAME = "svm_model"
EXECUTABLE_NAME = "stratum.opt.exe"

# The staged model is the one shipped with the vendored pipeline, and it is
# sized for exactly this many bands. `main.cu` reads `numberOfBands` from the
# dataset header and then reads that many float32 weights per binary classifier
# out of `w_vector.bin` with no bounds check at all: a dataset with more bands
# reads past the end of the file into whatever `fread` leaves in the buffer, and
# one with fewer silently classifies against a truncated model. Both produce a
# map that looks exactly like a result.
#
# The acquisition stand-in documents any band count of 8 or more and writes an
# `svm_model/` sized for whatever it generated - but into the dataset folder,
# which is not where UC1 looks. So the mismatch is reachable from documented
# settings, and the runner refuses it rather than trusting the operator to have
# noticed.
UC1_MODEL_BAND_COUNT = 93

# Byte sizes the five model files must have for that band count. float32
# throughout, except `label.bin`, which `main.cu` reads with `fread(&int, ...)`.
MODEL_FILE_SIZES: dict[str, int] = {
    envi.WEIGHT_VECTOR_FILE_NAME: UC1_MODEL_BAND_COUNT * envi.SVM_BINARY_CLASSIFIER_COUNT * 4,
    envi.PROBABILITY_A_FILE_NAME: envi.SVM_BINARY_CLASSIFIER_COUNT * 4,
    envi.PROBABILITY_B_FILE_NAME: envi.SVM_BINARY_CLASSIFIER_COUNT * 4,
    envi.RHO_FILE_NAME: envi.SVM_BINARY_CLASSIFIER_COUNT * 4,
    envi.LABEL_FILE_NAME: envi.SVM_CLASS_COUNT * 4,
}
OUTPUT_DIRECTORY_NAME = "output"
RGB_DIRECTORY_NAME = "rgb"
CHANNEL_FILE_NAMES = ("red.txt", "green.txt", "blue.txt")
CLASS_IMAGE_FILE_NAME = "imageRGB.bmp"
LOCK_FILE_NAME = ".uc1-runner.lock"
BUILD_SCRIPT_HINT = "scripts\\development\\build-uc1.ps1"

# `main.cu` prints this on a truncated output path and then carries on, so the
# run exits 0 with no image written. It has to be read off stderr.
PATH_TOO_LONG_MARKER = "Path too long"

# How many offending pixels an unmapped-colour report names before it stops.
REPORTED_OFFENDER_LIMIT = 5


class Uc1RunnerError(RuntimeError):
    """The genuine UC1 run could not be completed or trusted."""


class Uc1BuildMissingError(Uc1RunnerError):
    """The staged build is absent or incomplete."""


class Uc1BusyError(Uc1RunnerError):
    """Another runner holds the staged build."""


class Uc1ProcessFailedError(Uc1RunnerError):
    """The UC1 process reported a failure."""


class Uc1OutputMissingError(Uc1RunnerError):
    """The UC1 process did not write an expected output file."""


class Uc1StaleOutputError(Uc1RunnerError):
    """An output file predates this run, so it belongs to an earlier one."""


class Uc1PaletteError(Uc1RunnerError):
    """The recovered image holds a colour that is not in the UC1 palette."""


class Uc1ModelMismatchError(Uc1RunnerError):
    """The dataset and the staged SVM model disagree about the band count."""


@dataclass(frozen=True)
class ProcessResult:
    """What the runner needs from a finished process.

    A small record rather than `subprocess.CompletedProcess` so that a test can
    reproduce a crash, a truncated path or a stale output without a GPU.
    """

    returncode: int
    stdout: str = ""
    stderr: str = ""


ProcessRunner = Callable[[list[str], Path], ProcessResult]


def runSubprocess(command: list[str], cwd: Path) -> ProcessResult:
    """Run the UC1 binary with the load-bearing working directory."""
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return ProcessResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def defaultBuildRoot(repositoryRoot: Path | None = None) -> Path:
    """Return the staged build root, under the already-ignored `build/`."""
    root = repositoryRoot or config.repositoryRootFromHere()
    return root / BUILD_ROOT_RELATIVE_PATH


class Uc1Build:
    """The staged UC1 tree, laid out the way the hardcoded paths require.

    The binary is never run from `workspace/components/`: it writes its output
    into the source tree it runs from, which would put generated files inside
    the vendored reference copy. Staging is mandatory, not a convenience.
    """

    def __init__(self, root: Path, executableName: str = EXECUTABLE_NAME) -> None:
        self.root = Path(root)
        self.executableName = executableName

    @property
    def sourceDirectory(self) -> Path:
        return self.root / SOURCE_RELATIVE_PATH

    @property
    def svmModelDirectory(self) -> Path:
        return self.root / SVM_MODEL_DIRECTORY_NAME

    @property
    def executablePath(self) -> Path:
        return self.sourceDirectory / self.executableName

    @property
    def outputDirectory(self) -> Path:
        return self.sourceDirectory / OUTPUT_DIRECTORY_NAME

    @property
    def rgbOutputDirectory(self) -> Path:
        return self.outputDirectory / RGB_DIRECTORY_NAME

    @property
    def lockPath(self) -> Path:
        return self.root / LOCK_FILE_NAME

    def datasetOutputDirectory(self, datasetName: str) -> Path:
        """Where `main.cu` writes `imageRGB.bmp` for this dataset.

        `parse_arguments` derives the name from the folder basename, so a
        `sim-YYYYMMDD-HHMMSS` dataset keeps its runs self-labelling on disk.
        """
        return self.outputDirectory / datasetName

    def channelPaths(self) -> tuple[Path, ...]:
        return tuple(self.rgbOutputDirectory / name for name in CHANNEL_FILE_NAMES)

    def assertUsable(self) -> None:
        """Name what is missing rather than failing later inside the process."""
        if not self.executablePath.is_file():
            raise Uc1BuildMissingError(
                f"{self.executableName} is not in {self.sourceDirectory}. "
                f"Build it with {BUILD_SCRIPT_HINT}."
            )
        if not self.svmModelDirectory.is_dir():
            raise Uc1BuildMissingError(
                f"{SVM_MODEL_DIRECTORY_NAME} is not in {self.root}. UC1 opens the model as the "
                f"literal relative path ../../{SVM_MODEL_DIRECTORY_NAME}/*.bin, so it must sit "
                f"exactly two levels above {self.sourceDirectory}. "
                f"Re-stage the build with {BUILD_SCRIPT_HINT}."
            )

    def assertModelIsIntact(self) -> None:
        """Check the five model files are present and exactly the expected size.

        A short or absent file is not a crash: `fread` returns fewer elements
        than asked for and `main.cu` never checks the count, so the classifier
        would run against whatever was already in the buffer. Sizes are checked
        rather than hashes because the point is the band count the model encodes,
        not the identity of the weights - the build script's SHA-256 assertion
        already covers identity.
        """
        for fileName, expectedSize in MODEL_FILE_SIZES.items():
            path = self.svmModelDirectory / fileName
            if not path.is_file():
                raise Uc1ModelMismatchError(
                    f"{path} is missing. Re-stage the build with {BUILD_SCRIPT_HINT}."
                )
            actualSize = path.stat().st_size
            if actualSize != expectedSize:
                raise Uc1ModelMismatchError(
                    f"{path} is {actualSize} bytes but the staged model must be {expectedSize} "
                    f"for {UC1_MODEL_BAND_COUNT} bands and "
                    f"{envi.SVM_BINARY_CLASSIFIER_COUNT} binary classifiers. UC1 reads this file "
                    "without checking how much it got, so a wrong size classifies against "
                    f"uninitialised weights. Re-stage the build with {BUILD_SCRIPT_HINT}."
                )

    def assertDatasetMatchesModel(self, dataset: contract.DatasetRef) -> None:
        """Refuse a dataset whose band count the staged model cannot serve."""
        if dataset.bands != UC1_MODEL_BAND_COUNT:
            raise Uc1ModelMismatchError(
                f"{dataset.folder} declares {dataset.bands} bands, but the staged SVM model in "
                f"{self.svmModelDirectory} is sized for {UC1_MODEL_BAND_COUNT}. UC1 reads "
                f"{envi.WEIGHT_VECTOR_FILE_NAME} using the header's band count and never checks "
                "how much it read, so this run would classify against truncated or "
                "uninitialised weights and still produce a map that looks like a result. "
                f"Regenerate the dataset with bands={UC1_MODEL_BAND_COUNT}. The dataset's own "
                f"{envi.SVM_MODEL_DIRECTORY_NAME}/ is not a substitute: UC1 opens the model as "
                f"../../{SVM_MODEL_DIRECTORY_NAME}/*.bin relative to its working directory, not "
                "relative to the dataset."
            )

    @contextlib.contextmanager
    def exclusiveLock(self) -> Iterator[Path]:
        """Hold the staged build for one runner at a time.

        `output/rgb/*.txt` are three fixed names shared by every dataset, so two
        runners in one staged build would interleave writes into the same three
        files and each would then read the other's output. The lock file is also
        the freshness reference: it is stamped immediately before the process
        starts, on the same volume and the same clock as the outputs.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lockPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise Uc1BusyError(
                f"{self.lockPath} exists, so another UC1 runner holds {self.root}. "
                f"Wait for it to finish, or delete {LOCK_FILE_NAME} if no runner is active."
            ) from error

        try:
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.close(descriptor)
            yield self.lockPath
        finally:
            with contextlib.suppress(OSError):
                self.lockPath.unlink()


def prepareOutputDirectories(build: Uc1Build, datasetName: str) -> None:
    """Clear this run's output paths, then re-create the directories.

    The binary creates neither directory, and it never deletes. Both halves
    matter: without the deletion a crashed run's leftovers would be read back as
    this run's result, and without the creation the writes silently fail.
    """
    for path in build.channelPaths():
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    datasetOutput = build.datasetOutputDirectory(datasetName)
    if datasetOutput.is_dir():
        shutil.rmtree(datasetOutput)

    build.rgbOutputDirectory.mkdir(parents=True, exist_ok=True)
    datasetOutput.mkdir(parents=True, exist_ok=True)


def parseChannelFile(path: Path) -> numpy.ndarray:
    """Read one tab-separated channel file written by `writeMatrixRGB`."""
    try:
        values = numpy.loadtxt(path, dtype=numpy.int64, ndmin=2)
    except ValueError as error:
        raise Uc1OutputMissingError(f"{path} is not a readable channel file: {error}.") from error
    if values.size == 0:
        raise Uc1OutputMissingError(f"{path} is empty.")
    return values


def readChannels(build: Uc1Build, lines: int, samples: int) -> numpy.ndarray:
    """Read the three channel files into one (lines, samples, 3) array."""
    channels = [parseChannelFile(path) for path in build.channelPaths()]
    expectedShape = (lines, samples)
    for name, channel in zip(CHANNEL_FILE_NAMES, channels, strict=True):
        if channel.shape != expectedShape:
            raise Uc1OutputMissingError(
                f"{name} has shape {channel.shape} but the dataset header describes "
                f"{expectedShape}."
            )
    return numpy.stack(channels, axis=-1)


def recoverClassMap(rgb: numpy.ndarray) -> numpy.ndarray:
    """Invert the shared UC1 palette, refusing to guess at an unknown colour.

    A nearest-colour fallback would turn a pipeline that wrote something
    unexpected into a plausible-looking class map, which is the one outcome this
    runner must not produce.
    """
    rgb = numpy.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or 0 in rgb.shape[:2]:
        raise Uc1PaletteError(
            f"Expected a non-empty (lines, samples, 3) image, got shape {rgb.shape}."
        )

    classMap = numpy.zeros(rgb.shape[:2], dtype=numpy.uint8)
    matched = numpy.zeros(rgb.shape[:2], dtype=bool)
    for colour, classValue in RGB_TO_CLASS.items():
        current = numpy.all(rgb == colour, axis=2)
        classMap[current] = classValue
        matched |= current

    if not numpy.all(matched):
        offenders = numpy.argwhere(~matched)
        reported = [
            f"({int(line)}, {int(sample)}) = "
            f"({int(rgb[line, sample, 0])}, {int(rgb[line, sample, 1])}, "
            f"{int(rgb[line, sample, 2])})"
            for line, sample in offenders[:REPORTED_OFFENDER_LIMIT]
        ]
        raise Uc1PaletteError(
            f"{len(offenders)} pixel(s) carry a colour that is not in the UC1 palette "
            f"{sorted(RGB_TO_CLASS)}. First offenders (line, sample) = (R, G, B): "
            f"{'; '.join(reported)}. The palette inverse never resolves an unknown colour "
            "to the nearest known one."
        )
    return classMap


def _assertFresh(paths: tuple[Path, ...], runStartTime: float) -> None:
    """Reject an output that predates this run rather than accepting it."""
    for path in paths:
        if not path.is_file():
            raise Uc1OutputMissingError(
                f"{path} was not written. The UC1 process exited without producing it."
            )
        if path.stat().st_size == 0:
            raise Uc1OutputMissingError(f"{path} is empty.")
        modifiedTime = path.stat().st_mtime
        if modifiedTime < runStartTime:
            raise Uc1StaleOutputError(
                f"{path} was last written {runStartTime - modifiedTime:.3f} s before this run "
                "started, so it belongs to an earlier run. UC1 writes the same three output "
                "names for every dataset, so an existence check cannot tell them apart. "
                "A stale file is a failure, never a result."
            )


class RealUc1Classifier:
    """Implement the SLIA-011 `Classifier` seam with the genuine UC1 binary.

    `classify` uses `dataset.folder` and never calls `loadCalibratedCube()`. The
    binary opens `raw.dat`, `whiteReference.dat`, `darkReference.dat` and
    `raw.hdr` itself and calibrates on the GPU, so this producer cannot be
    expressed as a function of an already-calibrated cube. That is why the
    protocol takes a dataset descriptor rather than an array.
    """

    def __init__(
        self,
        build: Uc1Build | None = None,
        requireSimulatedMarker: bool = True,
        processRunner: ProcessRunner = runSubprocess,
    ) -> None:
        self.build = build if build is not None else Uc1Build(defaultBuildRoot())
        self.requireSimulatedMarker = requireSimulatedMarker
        self.processRunner = processRunner

    def classify(self, dataset: contract.DatasetRef) -> contract.Uc1Maps:
        """Run the pipeline and return the one map it actually produces."""
        if self.requireSimulatedMarker and not dataset.simulated:
            raise uc1_maps.SimulatedMarkerRequiredError(
                f"Refusing to run UC1 on {dataset.folder}: raw.hdr lacks the "
                f"{uc1_maps.enviMarkerName()} marker. Pass --force-unmarked only for an "
                "explicitly approved synthetic test dataset."
            )

        self.build.assertUsable()
        self.build.assertModelIsIntact()
        self.build.assertDatasetMatchesModel(dataset)
        datasetName = dataset.folder.name

        with self.build.exclusiveLock() as lockPath:
            prepareOutputDirectories(self.build, datasetName)

            # Stamp the lock immediately before the process starts. It is the
            # freshness reference for every output: same clock, same volume, and
            # no extra file left behind.
            os.utime(lockPath, None)
            runStartTime = lockPath.stat().st_mtime

            command = [str(self.build.executablePath), str(dataset.folder)]
            result = self.processRunner(command, self.build.sourceDirectory)
            self._reportProcessOutput(result)
            self._assertProcessSucceeded(result, command)

            classImagePath = self.build.datasetOutputDirectory(datasetName) / CLASS_IMAGE_FILE_NAME
            _assertFresh((*self.build.channelPaths(), classImagePath), runStartTime)
            rgb = readChannels(self.build, dataset.lines, dataset.samples)

        classMap = recoverClassMap(rgb)[numpy.newaxis, ...]
        uc1_maps.validateMajorityVotingMap(classMap)

        # Four fields stay None on purpose. UC1 computes and discards those maps,
        # and a consumer must be able to read "not produced" rather than a zero
        # -filled map that looks like a result.
        return contract.Uc1Maps(majorityVotingMap=classMap)

    def _reportProcessOutput(self, result: ProcessResult) -> None:
        """Echo UC1's own log, prefixed so it is never mistaken for this module's.

        The pipeline prints its stage timings, its K-means iteration count and
        its convergence error. That is the only direct evidence an operator has
        that the real thing ran, so it is shown rather than swallowed.
        """
        for stream, label in ((result.stdout, "uc1"), (result.stderr, "uc1!")):
            for line in stream.splitlines():
                if line.strip():
                    print(f"  [{label}] {line.rstrip()}")

    def _assertProcessSucceeded(self, result: ProcessResult, command: list[str]) -> None:
        """Fail loudly on every failure mode, and never fall back to a stand-in.

        A silent fallback would be the worst outcome this runner could have: the
        operator would believe the real pipeline ran when it did not.
        """
        if result.returncode != 0:
            raise Uc1ProcessFailedError(
                f"UC1 exited with code {result.returncode}. Command: {' '.join(command)}. "
                f"stderr: {result.stderr.strip() or '(empty)'}"
            )
        if PATH_TOO_LONG_MARKER in result.stderr or PATH_TOO_LONG_MARKER in result.stdout:
            raise Uc1ProcessFailedError(
                f"UC1 reported {PATH_TOO_LONG_MARKER!r} and then continued with a truncated "
                f"output path, so it exited 0 without writing the image. MAX_PATH_LENGTH is 128 "
                "and the staged output path counts towards it. Use a shorter dataset name or a "
                "shorter build root."
            )


def simulationDetailForDataset(dataset: contract.DatasetRef) -> str:
    """Name the scene the pipeline was fed, read from the dataset itself.

    A phantom dataset carries the record the acquisition stand-in wrote beside
    it. Reading the folder rather than taking a flag means the detail cannot
    disagree with the data: there is no argument to forget to pass.
    """
    phantomRecord = dataset.folder / tissue.REGION_LEGEND_FILE_NAME
    return SIMULATION_DETAIL_PHANTOM if phantomRecord.is_file() else SIMULATION_DETAIL


def mapMessages(
    maps: contract.Uc1Maps,
    simulationDetail: str = SIMULATION_DETAIL,
) -> Iterator[tuple[numpy.ndarray, str, dict[str, str]]]:
    """Yield the maps this producer actually produced, with full provenance.

    An absent map is skipped rather than substituted, so a real-UC1 session
    sends `UC1_MV_CLASS` and no other UC1 device name.
    """
    for mapName in maps.presentMapNames():
        metadata = contract.resultMapMetadata(
            mapName,
            contract.DATA_ORIGIN_SIMULATED,
            simulationDetail=simulationDetail,
        )
        yield (
            getattr(maps, mapName),
            metadata[contract.METADATA_DEVICE_NAME_KEY],
            metadata,
        )


def sendMaps(
    server: igtl_transport.ImageStreamServer,
    maps: contract.Uc1Maps,
    simulationDetail: str = SIMULATION_DETAIL,
) -> bool:
    """Send every produced map, re-checking the class map before each send."""
    for image, deviceName, metadata in mapMessages(maps, simulationDetail):
        uc1_maps.validateMajorityVotingMap(maps.majorityVotingMap)
        if not server.sendImage(image, deviceName, metadata):
            return False
    return True


def streamMaps(
    dataset: contract.DatasetRef,
    classifier: contract.Classifier,
    port: int = DEFAULT_PORT,
    cycles: int = 0,
    intervalSec: float = DEFAULT_INTERVAL_SEC,
) -> int:
    """Serve the recovered class map until interrupted, or until `cycles` succeed.

    The pipeline runs once, before the server opens. A GPU run per cycle would
    turn a display refresh into a minute of compute, and the dataset does not
    change between cycles.
    """
    if cycles < 0:
        raise ValueError(f"cycles must not be negative, not {cycles}.")

    simulationDetail = simulationDetailForDataset(dataset)
    if intervalSec < 0.0:
        raise ValueError(f"intervalSec must not be negative, not {intervalSec}.")

    maps = classifier.classify(dataset)
    uc1_maps.validateMajorityVotingMap(maps.majorityVotingMap)
    print(f"Recovered majorityVotingMap: {describeClassMap(maps.majorityVotingMap)}")
    warning = uniformClassWarning(maps.majorityVotingMap)
    if warning:
        print(warning, file=sys.stderr)
    completedCycles = 0

    with (
        igtl_transport.ImageStreamServer(port=port) as server,
        igtl_transport.InterruptFlag() as interrupt,
    ):
        print(
            f"Real UC1 server listening on 127.0.0.1:{port}. "
            "Waiting for an OpenIGTLink client. Press Ctrl-C to stop."
        )
        while not interrupt.requested and (cycles == 0 or completedCycles < cycles):
            if server.isConnected and sendMaps(server, maps, simulationDetail):
                completedCycles += 1
                print(CYCLE_BANNER.format(cycle=completedCycles, detail=simulationDetail))
            if cycles == 0 or completedCycles < cycles:
                time.sleep(intervalSec)

    print(f"Real UC1 sender stopped after {completedCycles} complete cycle(s).")
    return completedCycles


def describeClassMap(classMap: numpy.ndarray) -> str:
    """Summarise the recovered map for the operator, per class."""
    values, counts = numpy.unique(classMap, return_counts=True)
    total = int(classMap.size)
    parts = [
        f"{int(value)}: {int(count)} ({100.0 * int(count) / total:.1f}%)"
        for value, count in zip(values, counts, strict=True)
    ]
    return f"shape {classMap.shape}, dtype {classMap.dtype}, classes {{{', '.join(parts)}}}"


def uniformClassWarning(classMap: numpy.ndarray) -> str:
    """Return a warning when the pipeline resolved every pixel to one class.

    A single-class map is a valid contract map and a useless demonstration, and
    the two are easy to confuse when only the picture is looked at. It is
    reported rather than corrected: the classifier is never tuned, and a
    synthetic scene the model does not recognise is a fact about the scene.
    """
    values = numpy.unique(classMap)
    if values.size != 1:
        return ""
    return (
        f"WARNING: UC1 resolved every pixel to class {int(values[0])}. The run is genuine and "
        "the map is valid, but it shows nothing. This is a property of the synthetic scene, "
        "not of the pipeline; do not tune the classifier to change it."
    )


def _nonNegativeInteger(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _nonNegativeFloat(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def buildArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim uc1-real",
        description=(
            "Run the genuine UC1 CUDA pipeline on a simulated dataset and send its "
            "majority-voting class map as UC1_MV_CLASS. The pipeline is real; the scene "
            "is synthetic. UC1 discards the other four contract maps, so they are never "
            "sent and never substituted."
        ),
    )
    parser.add_argument(
        "datasetFolder",
        type=Path,
        help="Folder containing the ENVI dataset written by the acquisition stand-in.",
    )
    parser.add_argument(
        "--build-root",
        dest="buildRoot",
        type=Path,
        default=None,
        help="Staged UC1 build root. Defaults to build/uc1/UC1.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--cycles",
        type=_nonNegativeInteger,
        default=0,
        help="Complete this many sends; 0 streams until Ctrl-C.",
    )
    parser.add_argument(
        "--interval",
        dest="intervalSec",
        type=_nonNegativeFloat,
        default=DEFAULT_INTERVAL_SEC,
        help="Seconds between sends.",
    )
    parser.add_argument(
        "--force-unmarked",
        dest="forceUnmarked",
        action="store_true",
        help="Allow an explicitly approved synthetic dataset without the marker.",
    )
    parser.add_argument(
        "--classify-only",
        dest="classifyOnly",
        action="store_true",
        help="Run the pipeline and report the recovered map without opening a server.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = buildArgumentParser().parse_args(argv)
    try:
        dataset = contract.loadDataset(arguments.datasetFolder)
        if arguments.forceUnmarked:
            print(
                "WARNING: --force-unmarked is enabled. Use only with an explicitly "
                "approved synthetic test dataset; the input remains synthetic and "
                "non-clinical, and so does the result."
            )
        buildRoot = arguments.buildRoot if arguments.buildRoot is not None else defaultBuildRoot()
        classifier = RealUc1Classifier(
            build=Uc1Build(buildRoot),
            requireSimulatedMarker=not arguments.forceUnmarked,
        )

        print(f"Dataset:    {dataset.folder}")
        print(f"Build root: {buildRoot}")
        print(
            f"Origin:     {contract.DATA_ORIGIN_SIMULATED} - "
            f"{simulationDetailForDataset(dataset)}"
        )

        if arguments.classifyOnly:
            maps = classifier.classify(dataset)
            print(f"Recovered majorityVotingMap: {describeClassMap(maps.majorityVotingMap)}")
            print("Maps produced by this run: " + ", ".join(maps.presentMapNames()))
            warning = uniformClassWarning(maps.majorityVotingMap)
            if warning:
                print(warning, file=sys.stderr)
            return 0

        streamMaps(
            dataset,
            classifier,
            port=arguments.port,
            cycles=arguments.cycles,
            intervalSec=arguments.intervalSec,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "BUILD_ROOT_RELATIVE_PATH",
    "CHANNEL_FILE_NAMES",
    "CLASS_IMAGE_FILE_NAME",
    "CYCLE_BANNER",
    "DEFAULT_PORT",
    "EXECUTABLE_NAME",
    "LOCK_FILE_NAME",
    "PATH_TOO_LONG_MARKER",
    "RGB_TO_CLASS",
    "SIMULATION_DETAIL",
    "SIMULATION_DETAIL_PHANTOM",
    "ProcessResult",
    "RealUc1Classifier",
    "Uc1Build",
    "Uc1BuildMissingError",
    "Uc1BusyError",
    "Uc1ModelMismatchError",
    "Uc1OutputMissingError",
    "Uc1PaletteError",
    "Uc1ProcessFailedError",
    "Uc1RunnerError",
    "Uc1StaleOutputError",
    "buildArgumentParser",
    "defaultBuildRoot",
    "describeClassMap",
    "main",
    "mapMessages",
    "simulationDetailForDataset",
    "parseChannelFile",
    "prepareOutputDirectories",
    "readChannels",
    "recoverClassMap",
    "runSubprocess",
    "sendMaps",
    "streamMaps",
    "uniformClassWarning",
]


if __name__ == "__main__":
    raise SystemExit(main())
