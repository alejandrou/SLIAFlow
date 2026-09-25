"""Run the staged UC1 intermediate build on the configured cube, from inside Slicer.

Nothing here computes a classification. `stratum.opt.intermediate.exe` is the
vendored UC1 pipeline plus the documented patches `scripts/development/build-uc1.ps1`
applies (docs/development/uc1_changes.md). This module writes the cube UC1 is to
read (`SLIAFlowUc1Input`), starts the binary as a background `QProcess` with no
shell, waits for it, and reads back the five images it wrote. The checks
around the run are the ones `tools/simulators/stratum_sim/uc1_runner.py` learned
the hard way, restated here because a Slicer module cannot import that tooling:

- The binary is bound to its working directory. It opens the SVM model as the
  literal relative path `../../svm_model/*.bin` and writes `output/<case>/`
  relative to where it runs, so it must run from the staged
  `gpu_single_bsq/source`.
- Its output names are fixed and shared, so an existence check cannot tell this
  run's images from an earlier run's. Outputs are cleared before the run, and
  every file must be newer than a timestamp taken immediately before the
  process starts.
- `MAX_PATH_LENGTH` is 128. The stage writers print `Path too long` and carry on,
  and `data_loader.cpp` truncates the input paths without printing anything, so
  both are checked before the run and the marker is read off both streams.
- A short or missing model file is not a crash: `fread` returns less and the
  classifier runs on whatever was in the buffer. Model file sizes are checked.
- The standalone Python runner uses the same staged build, so the build is held
  with the same `.uc1-runner.lock` for the whole run.
"""

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .SLIAFlowBmpReader import BmpFormatError, readUc1Bmp
from .SLIAFlowCalibratedCube import CalibratedCubeError
from .SLIAFlowUc1Input import (
    INPUT_DATA_FILE_NAME,
    INPUT_HEADER_FILE_NAME,
    UC1_MODEL_BAND_COUNT,
    assertUc1InputUnchanged,
    writeUc1Input,
)

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

EXECUTABLE_NAME = "stratum.opt.intermediate.exe"
BUILD_ROOT_RELATIVE_PATH = Path("build") / "uc1" / "UC1"
SOURCE_RELATIVE_PATH = Path("gpu_single_bsq") / "source"
SVM_MODEL_DIRECTORY_NAME = "svm_model"
OUTPUT_DIRECTORY_NAME = "output"
RGB_DIRECTORY_NAME = "rgb"
CHANNEL_FILE_NAMES = ("red.txt", "green.txt", "blue.txt")
LOCK_FILE_NAME = ".uc1-runner.lock"
BUILD_SCRIPT_HINT = "scripts\\development\\build-uc1.ps1"

# The five images SLIAFlow shows, from the snprintf formats in
# functions_cuda.cu (pca, svm, knn, kmeans) and main.cu (imageRGB).
# CalibratedImage_BIP.bmp is written without row padding and is never read.
OUTPUT_FILE_NAMES = ("pca.bmp", "svm.bmp", "knn.bmp", "kmeans.bmp", "imageRGB.bmp")
LONGEST_OUTPUT_FILE_NAME = "CalibratedImage_BIP.bmp"
# The mapped cube SLIAFlow writes into the folder UC1 is given. A calibrated
# float32 cube needs no references (patch 0002).
INPUT_DIRECTORY_NAME = "input"
INPUT_FILE_NAMES = (INPUT_DATA_FILE_NAME, INPUT_HEADER_FILE_NAME)

# data_loader.hpp. snprintf into this many bytes keeps at most 127 characters.
MAX_PATH_LENGTH = 128
PATH_TOO_LONG_MARKER = "Path too long"

# SLIA-027, decided by the project owner. A run on the 1080 x 1080 LCTF cube
# took 2.7 s at SLIA-033, including process start and CUDA setup.
RUN_TIMEOUT_SEC = 60
KILL_WAIT_MS = 5000

# Byte sizes of the staged model for UC1_MODEL_BAND_COUNT bands and six binary
# classifiers (uc1_runner.MODEL_FILE_SIZES): float32 throughout, except
# label.bin, which holds four int32 class labels.
SVM_BINARY_CLASSIFIER_COUNT = 6
SVM_CLASS_COUNT = 4
MODEL_FILE_SIZES = {
    "w_vector.bin": UC1_MODEL_BAND_COUNT * SVM_BINARY_CLASSIFIER_COUNT * 4,
    "ProbA.bin": SVM_BINARY_CLASSIFIER_COUNT * 4,
    "ProbB.bin": SVM_BINARY_CLASSIFIER_COUNT * 4,
    "rho.bin": SVM_BINARY_CLASSIFIER_COUNT * 4,
    "label.bin": SVM_CLASS_COUNT * 4,
}

# QProcess enum values, mirrored so the logic can be driven by a stand-in.
PROCESS_NOT_RUNNING = 0
PROCESS_CRASH_EXIT = 1
PROCESS_FAILED_TO_START = 0

REPOSITORY_MARKER_FILE = "AGENTS.md"
REPOSITORY_MARKER_DIRECTORY = Path("extensions") / "SLIAFlow"


class Uc1RunError(RuntimeError):
    """The UC1 run could not be started, completed or trusted."""


def findRepositoryRoot(start) -> Path:
    """Find the repository from a file inside it.

    `slicer.app.applicationDirPath` is the Slicer build's `bin/Release`, not the
    repository, and the module runs both from `extensions/SLIAFlow/SLIAFlow` and
    from the copy under `build/SLIAFlow`. Both sit inside the repository, so
    its root is found by walking up from this module's own location.
    """
    path = Path(start).resolve()
    for candidate in (path, *path.parents):
        if (candidate / REPOSITORY_MARKER_FILE).is_file() and (
            candidate / REPOSITORY_MARKER_DIRECTORY
        ).is_dir():
            return candidate
    raise Uc1RunError(_(
        "No SLIAFlow repository contains {path}: no parent folder holds both {markerFile} and "
        "{markerDirectory}."
    ).format(path=path, markerFile=REPOSITORY_MARKER_FILE,
             markerDirectory=REPOSITORY_MARKER_DIRECTORY))


class Uc1Build:
    """The staged UC1 tree, laid out the way the binary's relative paths require."""

    def __init__(self, root) -> None:
        self.root = Path(root)

    @classmethod
    def forRepository(cls, repositoryRoot) -> "Uc1Build":
        return cls(Path(repositoryRoot) / BUILD_ROOT_RELATIVE_PATH)

    @property
    def sourceDirectory(self) -> Path:
        return self.root / SOURCE_RELATIVE_PATH

    @property
    def svmModelDirectory(self) -> Path:
        return self.root / SVM_MODEL_DIRECTORY_NAME

    @property
    def executablePath(self) -> Path:
        return self.sourceDirectory / EXECUTABLE_NAME

    @property
    def outputDirectory(self) -> Path:
        return self.sourceDirectory / OUTPUT_DIRECTORY_NAME

    @property
    def rgbOutputDirectory(self) -> Path:
        return self.outputDirectory / RGB_DIRECTORY_NAME

    @property
    def lockPath(self) -> Path:
        return self.root / LOCK_FILE_NAME

    @property
    def inputDirectory(self) -> Path:
        """Where the cube UC1 reads is written, one folder per cube (gitignored)."""
        return self.root / INPUT_DIRECTORY_NAME

    def caseOutputDirectory(self, caseName: str) -> Path:
        return self.outputDirectory / caseName

    def assertRunnable(self, case) -> None:
        """Name what is missing or unsafe before anything is started.

        `case` is the `Uc1Input` of the run: the configured cube and the folder
        its mapped copy is written to.
        """
        # The cube was described when Capture was pressed, not now. Re-read it
        # here, the last moment before the lock is taken, so a cube that was
        # edited or truncated since is refused instead of run on.
        try:
            assertUc1InputUnchanged(case)
        except (CalibratedCubeError, OSError) as error:
            raise Uc1RunError(str(error)) from error
        if not self.executablePath.is_file():
            raise Uc1RunError(_("{executable} is not in {directory}. Build it with {script}.").format(
                executable=EXECUTABLE_NAME, directory=self.sourceDirectory, script=BUILD_SCRIPT_HINT
            ))
        if not self.svmModelDirectory.is_dir():
            raise Uc1RunError(_(
                "{model} is not in {root}. UC1 opens it as ../../{model} from {directory}. "
                "Re-stage the build with {script}."
            ).format(model=SVM_MODEL_DIRECTORY_NAME, root=self.root,
                     directory=self.sourceDirectory, script=BUILD_SCRIPT_HINT))
        for fileName, expectedSize in MODEL_FILE_SIZES.items():
            path = self.svmModelDirectory / fileName
            actualSize = path.stat().st_size if path.is_file() else None
            if actualSize != expectedSize:
                if actualSize is None:
                    found = _("missing")
                else:
                    found = _("{size} bytes").format(size=actualSize)
                raise Uc1RunError(_(
                    "The SVM model file {file} is {found}, but must be {expected} bytes for "
                    "{bands} bands. UC1 would classify against uninitialised weights. Re-stage "
                    "the build with {script}."
                ).format(file=fileName, found=found, expected=expectedSize,
                         bands=UC1_MODEL_BAND_COUNT, script=BUILD_SCRIPT_HINT))
        if case.bands != UC1_MODEL_BAND_COUNT:
            raise Uc1RunError(_(
                "Cube {case} is mapped to {bands} bands, but the staged SVM model is sized for "
                "{modelBands}."
            ).format(case=case.name, bands=case.bands, modelBands=UC1_MODEL_BAND_COUNT))
        # UC1 builds each path as "<argument>/<file>" and "output/<case>/<file>".
        paths = [f"{case.folder}/{fileName}" for fileName in INPUT_FILE_NAMES]
        paths.append(f"{OUTPUT_DIRECTORY_NAME}/{case.name}/{LONGEST_OUTPUT_FILE_NAME}")
        for path in paths:
            if len(path) >= MAX_PATH_LENGTH:
                raise Uc1RunError(_(
                    "The path {path} is {length} characters. UC1 keeps at most {limit} "
                    "({bufferSize}-byte buffers) and would read or write a truncated path without "
                    "failing. Move the repository, or give the cube's folder a shorter name."
                ).format(path=path, length=len(path), limit=MAX_PATH_LENGTH - 1,
                         bufferSize=MAX_PATH_LENGTH))

    def acquireLock(self) -> None:
        """Hold the staged build for this run, or refuse. Never takes over a lock."""
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lockPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise Uc1RunError(_(
                "{lock} exists, so another UC1 run holds {root}. Wait for it to finish. If no UC1 "
                "run is active, delete {lockName} and press Capture again."
            ).format(lock=self.lockPath, root=self.root, lockName=LOCK_FILE_NAME)) from error
        try:
            try:
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            finally:
                os.close(descriptor)
        except OSError as error:
            # The file exists but this run never became its holder: the caller
            # sets _lockHeld only once acquireLock returns, so nothing would
            # release it and every later Capture would refuse against a lock
            # no run is behind. Remove what this call created before refusing.
            # This is not the stale-lock case, which is deliberately left for
            # the operator: here the holder is known and is this process.
            self.releaseLock()
            raise Uc1RunError(_(
                "The UC1 build lock {lock} could not be written: {error}"
            ).format(lock=self.lockPath, error=error)) from error

    def stampLock(self) -> float:
        """Stamp the held lock now and return the time as the freshness reference.

        Same clock and same volume as the outputs, as in uc1_runner.py.
        """
        os.utime(self.lockPath, None)
        return self.lockPath.stat().st_mtime

    def releaseLock(self) -> None:
        try:
            self.lockPath.unlink()
        except OSError:
            pass

    def prepareOutputs(self, case) -> None:
        """Remove this case's previous outputs and the shared channel files."""
        caseOutput = self.caseOutputDirectory(case.name)
        if caseOutput.is_dir():
            shutil.rmtree(caseOutput)
        for fileName in CHANNEL_FILE_NAMES:
            try:
                (self.rgbOutputDirectory / fileName).unlink()
            except FileNotFoundError:
                pass
        self.rgbOutputDirectory.mkdir(parents=True, exist_ok=True)

    def prepareInput(self, case) -> None:
        """Write the mapped cube UC1 is given, or refuse the run saying why."""
        try:
            writeUc1Input(case)
        except CalibratedCubeError as error:
            raise Uc1RunError(str(error)) from error


def collectOutputs(build: Uc1Build, case, runStartTime: float) -> dict:
    """Read all five outputs of one run, or refuse the run as a whole.

    Returned in OUTPUT_FILE_NAMES order as (lines, samples, 3) uint8 RGB arrays,
    top row first.
    """
    outputs = {}
    outputDirectory = build.caseOutputDirectory(case.name)
    for fileName in OUTPUT_FILE_NAMES:
        path = outputDirectory / fileName
        if not path.is_file():
            raise Uc1RunError(_("UC1 did not write {file} for cube {case} ({path}).").format(
                file=fileName, case=case.name, path=path
            ))
        modifiedTime = path.stat().st_mtime
        if modifiedTime < runStartTime:
            raise Uc1RunError(_(
                "{file} for cube {case} was last written {seconds} s before this run "
                "started, so it belongs to an earlier run."
            ).format(file=fileName, case=case.name, seconds=f"{runStartTime - modifiedTime:.1f}"))
        try:
            outputs[fileName] = readUc1Bmp(path, case.samples, case.lines)
        except (BmpFormatError, OSError) as error:
            # The reader's own detail names header fields and byte counts; it
            # is kept as written, inside a translated sentence.
            raise Uc1RunError(_("{file} for cube {case} is not a valid UC1 image: {error}").format(
                file=fileName, case=case.name, error=error
            )) from error
    return outputs


def _toText(raw) -> str:
    """PythonQt returns a QByteArray or bytes, depending on the version."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    elif hasattr(raw, "data"):
        data = bytes(raw.data())
    else:
        data = bytes(raw)
    return data.decode("utf-8", "replace")


@dataclass(frozen=True)
class ProcessOutcome:
    exitCode: int | None
    crashed: bool
    timedOut: bool
    failedToStart: bool
    stdout: str
    stderr: str


class OwnedProcess:
    """One child process that this object starts, times out and always ends.

    `onFinished` is called once, with a ProcessOutcome, when the process exits,
    fails to start or times out. `kill` ends it without calling `onFinished`.
    """

    FINISHED_SIGNAL = "finished(int,QProcess::ExitStatus)"
    ERROR_SIGNAL = "errorOccurred(QProcess::ProcessError)"
    STDOUT_SIGNAL = "readyReadStandardOutput()"
    STDERR_SIGNAL = "readyReadStandardError()"

    def __init__(self, onFinished, *, processFactory=None, timeoutSec=RUN_TIMEOUT_SEC) -> None:
        self._onFinished = onFinished
        self._processFactory = processFactory
        self._timeoutSec = float(timeoutSec)
        self._process = None
        self._timer = None
        self._slots = {}
        self._stdout = ""
        self._stderr = ""

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self, program: str, arguments, workingDirectory: str) -> None:
        import qt

        if self._process is not None:
            raise Uc1RunError(_("This process is already running."))
        factory = self._processFactory if self._processFactory is not None else qt.QProcess
        process = factory()
        self._process = process
        self._stdout = ""
        self._stderr = ""
        # Bound methods are held so the same objects can be disconnected.
        self._slots = {
            self.FINISHED_SIGNAL: self._onProcessFinished,
            self.ERROR_SIGNAL: self._onProcessError,
            self.STDOUT_SIGNAL: self._readStdout,
            self.STDERR_SIGNAL: self._readStderr,
        }
        for signal, slot in self._slots.items():
            process.connect(signal, slot)
        process.setWorkingDirectory(workingDirectory)

        timer = qt.QTimer()
        timer.setSingleShot(True)
        timer.connect("timeout()", self._onTimeout)
        self._timer = timer
        timer.start(max(1, int(self._timeoutSec * 1000.0)))

        logging.info("SLIAFlow: starting %s %s in %s", program, " ".join(arguments), workingDirectory)
        process.start(program, list(arguments))

    def kill(self) -> None:
        self._end(kill=True)

    def _readStdout(self) -> None:
        if self._process is not None:
            self._stdout += self._logged(_toText(self._process.readAllStandardOutput()), "uc1")

    def _readStderr(self) -> None:
        if self._process is not None:
            self._stderr += self._logged(_toText(self._process.readAllStandardError()), "uc1!")

    @staticmethod
    def _logged(text: str, label: str) -> str:
        for line in text.splitlines():
            if line.strip():
                logging.info("SLIAFlow [%s] %s", label, line.rstrip())
        return text

    def _onProcessFinished(self, exitCode, exitStatus) -> None:
        if self._process is None:
            return
        crashed = int(exitStatus) == PROCESS_CRASH_EXIT
        self._complete(exitCode=None if crashed else int(exitCode), crashed=crashed)

    def _onProcessError(self, error) -> None:
        # A process that never started produces no finished signal. Every other
        # error is followed by finished, which reports it.
        if self._process is not None and int(error) == PROCESS_FAILED_TO_START:
            self._complete(exitCode=None, failedToStart=True)

    def _onTimeout(self) -> None:
        if self._process is not None:
            self._complete(exitCode=None, timedOut=True, kill=True)

    def _complete(self, *, exitCode, crashed=False, timedOut=False, failedToStart=False,
                  kill=False) -> None:
        self._end(kill=kill)
        outcome = ProcessOutcome(exitCode, crashed, timedOut, failedToStart, self._stdout, self._stderr)
        self._onFinished(outcome)

    def _end(self, *, kill: bool) -> None:
        """Stop the timer, drain and disconnect, and kill if asked. Idempotent."""
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.stop()
            try:
                timer.disconnect("timeout()", self._onTimeout)
            except Exception:
                pass
        process = self._process
        if process is None:
            return
        self._readStdout()
        self._readStderr()
        self._process = None
        for signal, slot in self._slots.items():
            try:
                process.disconnect(signal, slot)
            except Exception:
                pass
        self._slots = {}
        if kill and int(process.state()) != PROCESS_NOT_RUNNING:
            process.kill()
            process.waitForFinished(KILL_WAIT_MS)
        process.deleteLater()


@dataclass(frozen=True)
class Uc1RunResult:
    success: bool
    case: object
    message: str
    outputs: dict | None
    exitCode: int | None
    stdout: str
    stderr: str
    elapsedSec: float


class Uc1Run:
    """One UC1 run on the configured cube: input, checks, lock, process and outputs.

    `start` raises Uc1RunError when the run is refused, and nothing is left
    behind. Otherwise `onFinished` is called exactly once with a Uc1RunResult,
    unless `cancel` ends the run first. The lock is released before
    `onFinished` is called and on `cancel`.
    """

    STAGE_RUNNING = "running"
    STAGE_VALIDATING = "validating"

    def __init__(self, build: Uc1Build, case, onFinished, *, processFactory=None,
                 timeoutSec=RUN_TIMEOUT_SEC, onStage=None) -> None:
        self.build = build
        self.case = case
        self._onFinished = onFinished
        self._onStage = onStage
        self._processFactory = processFactory
        self._timeoutSec = timeoutSec
        self._process = None
        self._lockHeld = False
        self._runStartTime = None
        self._startedAt = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.running

    def start(self) -> None:
        self.build.assertRunnable(self.case)
        self.build.acquireLock()
        self._lockHeld = True
        try:
            self.build.prepareOutputs(self.case)
            # Written under the lock, so two runs never write one folder at once.
            self.build.prepareInput(self.case)
            self._runStartTime = self.build.stampLock()
            self._startedAt = time.monotonic()
            self._process = OwnedProcess(
                self._onProcessFinished,
                processFactory=self._processFactory,
                timeoutSec=self._timeoutSec,
            )
            self._stage(self.STAGE_RUNNING)
            self._process.start(
                str(self.build.executablePath),
                [str(self.case.folder)],
                str(self.build.sourceDirectory),
            )
        except OSError as error:
            self._abandon()
            raise Uc1RunError(_("The UC1 run on cube {case} could not be prepared: {error}").format(
                case=self.case.name, error=error
            )) from error
        except Exception:
            self._abandon()
            raise

    def cancel(self) -> None:
        """End the run without reporting it: kill and wait, then release the lock."""
        self._abandon()

    def _abandon(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.kill()
        self._releaseLock()

    def _releaseLock(self) -> None:
        if self._lockHeld:
            self._lockHeld = False
            self.build.releaseLock()

    def _stage(self, stage: str) -> None:
        if self._onStage is not None:
            self._onStage(stage)

    def _onProcessFinished(self, outcome: ProcessOutcome) -> None:
        if self._process is None:
            return
        self._process = None
        elapsed = time.monotonic() - (self._startedAt or time.monotonic())
        outputs = None
        try:
            message = self._processFailure(outcome)
            if message is None:
                self._stage(self.STAGE_VALIDATING)
                try:
                    outputs = collectOutputs(self.build, self.case, self._runStartTime)
                    message = _("UC1 finished on cube {case} in {seconds} s.").format(
                        case=self.case.name, seconds=f"{elapsed:.1f}"
                    )
                except Uc1RunError as error:
                    message = str(error)
        except Exception as error:
            # Validating the outputs reads the filesystem, so it can fail in
            # ways collectOutputs does not turn into a Uc1RunError: a denied
            # output folder, a volume that went away, a disc error. This is the
            # last point at which the run can be reported. An exception raised
            # out of the process-finished callback reaches Qt's signal
            # dispatch, which drops it, so onFinished would never run and the
            # module would stay in its capturing state with LiveView frozen for
            # the rest of the session. Report it as a failed run instead.
            logging.exception(
                "SLIAFlow: the outputs of cube %s could not be validated", self.case.name
            )
            outputs = None
            message = _(
                "UC1 finished on cube {case}, but its outputs could not be checked: "
                "{error}"
            ).format(case=self.case.name, error=error)
        finally:
            self._releaseLock()
        self._onFinished(Uc1RunResult(
            success=outputs is not None,
            case=self.case,
            message=message,
            outputs=outputs,
            exitCode=outcome.exitCode,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            elapsedSec=elapsed,
        ))

    def _processFailure(self, outcome: ProcessOutcome) -> str | None:
        name = self.case.name
        if outcome.failedToStart:
            return _(
                "UC1 could not be started for cube {case}. Check that {executable} exists "
                "and runs; build it with {script}."
            ).format(case=name, executable=self.build.executablePath, script=BUILD_SCRIPT_HINT)
        if outcome.timedOut:
            return _("UC1 timed out after {seconds} s on cube {case} and was stopped.").format(
                seconds=f"{self._timeoutSec:g}", case=name
            )
        if outcome.crashed:
            return _("UC1 crashed on cube {case}. {lastError}").format(
                case=name, lastError=self._lastErrorLine(outcome)
            ).strip()
        if outcome.exitCode != 0:
            return _("UC1 exited with code {code} on cube {case}. {lastError}").format(
                code=outcome.exitCode, case=name, lastError=self._lastErrorLine(outcome)
            ).strip()
        if PATH_TOO_LONG_MARKER in outcome.stdout or PATH_TOO_LONG_MARKER in outcome.stderr:
            return _(
                "UC1 reported '{marker}' on cube {case} and continued with a truncated "
                "path, so its outputs cannot be trusted. Paths are limited to {limit} characters."
            ).format(marker=PATH_TOO_LONG_MARKER, case=name, limit=MAX_PATH_LENGTH - 1)
        return None

    @staticmethod
    def _lastErrorLine(outcome: ProcessOutcome) -> str:
        lines = [line.strip() for line in outcome.stderr.splitlines() if line.strip()]
        return _("Last error output: {line}").format(line=lines[-1]) if lines else ""
