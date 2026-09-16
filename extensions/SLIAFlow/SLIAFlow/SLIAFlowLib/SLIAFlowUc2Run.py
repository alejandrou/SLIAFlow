"""Run the staged UC2 blood-vessel enhancement on the configured cube, from inside Slicer.

Nothing here computes an enhancement. `uc2_bvmap.exe` is the vendored UC2
component plus the documented patches `scripts/development/build-uc2.ps1`
applies (docs/development/uc2_changes.md). This module starts it as a
background `QProcess` with no shell on the configured cube's folder, waits for
it, and reads back the one PNG it writes. The checks around the run are the
ones docs/development/uc2_local_build.md records:

- UC2 is given a folder, not a file. Patch 0001 makes it read
  `LCTF_Calibrated_Cube_Single.hdr` and `.dat` from that folder when the header
  is there, so the configured cube must have exactly those names.
- Patch 0002 reads three fixed band indices, which are 480, 540 and 710 nm only
  on the LCTF grid. A cube whose wavelengths at those indices differ is refused
  before UC2 starts, rather than enhanced on the wrong bands.
- The PNG lands in the process working directory, named after the folder, so
  it is removed before the run and must be newer than the run's start.
- UC2 exits 0 after several failures, so its error lines are read off both
  streams whatever the exit code.
- The staged build is held with `.uc2-runner.lock` for the whole run, as
  `check-uc2.py` does.

UC2 only reads the cube; nothing is written into its folder.
"""

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .SLIAFlowCalibratedCube import CalibratedCubeError, loadCalibratedCube
from .SLIAFlowUc1Run import OwnedProcess, ProcessOutcome

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

EXECUTABLE_NAME = "uc2_bvmap.exe"
# build-uc2.ps1 copies the MSYS2 runtime beside the binary; without it the
# process fails to start.
RUNTIME_DLL_NAME = "msys-2.0.dll"
BUILD_ROOT_RELATIVE_PATH = Path("build") / "uc2"
SOURCE_DIRECTORY_NAME = "source"
RUN_DIRECTORY_NAME = "run"
LOCK_FILE_NAME = ".uc2-runner.lock"
BUILD_SCRIPT_HINT = "scripts\\development\\build-uc2.ps1"

# The names patch 0001 looks for in the folder UC2 is given.
CALIBRATED_HEADER_NAME = "LCTF_Calibrated_Cube_Single.hdr"
CALIBRATED_DATA_NAME = "LCTF_Calibrated_Cube_Single.dat"
# png_writer.c writes "<output folder>/<folder name>-BVMap.png".
OUTPUT_FILE_SUFFIX = "-BVMap.png"

# Patch 0002's fixed band indices, in the order UC2 reads them, and the
# wavelengths its comments give them on the LCTF grid.
UC2_BANDS = ((4, 480.0), (16, 540.0), (50, 710.0))
WAVELENGTH_TOLERANCE_NM = 0.01
# The fixed visualisation parameters in main.c. UC2 takes no others.
UC2_PARAMETERS = (("high_in", "0.15"), ("high_out", "0.8"), ("gamma", "1"), ("bValue", "3"))

# params.h, for the folder and file paths; png_writer.c, for the output path.
MAX_PATH_LENGTH = 512
MAX_OUTPUT_PATH_LENGTH = 256

# Lines UC2 prints on a failure it does not always exit nonzero for.
ERROR_MARKERS = (
    "Usage:",
    "Error: Directory path is too long!",
    "Error: File path is too long!",
    "Error opening",
    "Error reading",
    "Failed to open file",
    "Unknown format.",
    "Failed to save the image.",
)

# UC2 reads three bands and wrote its map in about 0.3 s on 002-04 (SLIA-021).
RUN_TIMEOUT_SEC = 30
PNG_COMPONENTS = 3


class Uc2RunError(RuntimeError):
    """The UC2 run could not be started, completed or trusted."""


def uc2ParametersText() -> str:
    """The fixed bands and parameters UC2 runs with, for the operator and the nodes."""
    bands = ", ".join(f"{nanometres:g}" for _index, nanometres in UC2_BANDS)
    parameters = ", ".join(f"{name} {value}" for name, value in UC2_PARAMETERS)
    return _("bands {bands} nm; {parameters}").format(bands=bands, parameters=parameters)


def readBvMapPng(path, lines: int, samples: int) -> np.ndarray:
    """Read UC2's PNG as (lines, samples, 3) uint8 RGB, top row first, or refuse it."""
    import vtk
    from vtk.util import numpy_support

    reader = vtk.vtkPNGReader()
    if not reader.CanReadFile(str(path)):
        raise Uc2RunError(_("{file} is not a PNG.").format(file=Path(path).name))
    reader.SetFileName(str(path))
    reader.Update()
    image = reader.GetOutput()
    if reader.GetErrorCode() != 0 or image is None or image.GetPointData().GetScalars() is None:
        raise Uc2RunError(_("{file} could not be decoded.").format(file=Path(path).name))
    columns, rows, depth = image.GetDimensions()
    components = image.GetNumberOfScalarComponents()
    if (image.GetScalarType() != vtk.VTK_UNSIGNED_CHAR or components != PNG_COMPONENTS
            or depth != 1 or (rows, columns) != (lines, samples)):
        raise Uc2RunError(_(
            "{file} is {columns} x {rows} with {components} channel(s), not the cube's "
            "{samples} x {lines} RGB."
        ).format(file=Path(path).name, columns=columns, rows=rows, components=components,
                 samples=samples, lines=lines))
    pixels = numpy_support.vtk_to_numpy(image.GetPointData().GetScalars())
    # vtkPNGReader puts the file's top row at image row y = rows - 1.
    return np.ascontiguousarray(pixels.reshape(rows, columns, PNG_COMPONENTS)[::-1])


class Uc2Build:
    """The staged UC2 tree: the binary, its runtime, and the folder it writes into."""

    def __init__(self, root) -> None:
        self.root = Path(root)

    @classmethod
    def forRepository(cls, repositoryRoot) -> "Uc2Build":
        return cls(Path(repositoryRoot) / BUILD_ROOT_RELATIVE_PATH)

    @property
    def sourceDirectory(self) -> Path:
        return self.root / SOURCE_DIRECTORY_NAME

    @property
    def executablePath(self) -> Path:
        return self.sourceDirectory / EXECUTABLE_NAME

    @property
    def runDirectory(self) -> Path:
        return self.root / RUN_DIRECTORY_NAME

    @property
    def lockPath(self) -> Path:
        return self.root / LOCK_FILE_NAME

    def outputPath(self, cube) -> Path:
        return self.runDirectory / f"{cube.name}{OUTPUT_FILE_SUFFIX}"

    @staticmethod
    def argument(cube) -> str:
        """The folder UC2 is given, with forward slashes as `check-uc2.py` gives it."""
        return cube.headerPath.parent.as_posix()

    def assertRunnable(self, cube) -> None:
        """Name what is missing or unsafe before anything is started."""
        # The cube was described when Capture was pressed. Describe it again
        # now, so a cube edited or truncated since is refused, not run on.
        try:
            current = loadCalibratedCube(cube.headerPath)
        except (CalibratedCubeError, OSError) as error:
            raise Uc2RunError(str(error)) from error
        if current != cube:
            raise Uc2RunError(_(
                "{file} changed on disk after Capture was pressed. Press Capture again."
            ).format(file=cube.headerPath.name))
        if cube.headerPath.name != CALIBRATED_HEADER_NAME or cube.dataPath.name != CALIBRATED_DATA_NAME:
            raise Uc2RunError(_(
                "The blood-vessel enhancement reads {header} and {data} from the cube's folder, "
                "but the configured cube is {actualHeader} and {actualData}."
            ).format(header=CALIBRATED_HEADER_NAME, data=CALIBRATED_DATA_NAME,
                     actualHeader=cube.headerPath.name, actualData=cube.dataPath.name))
        for index, nanometres in UC2_BANDS:
            actual = cube.wavelengths[index] if index < len(cube.wavelengths) else None
            if actual is None or abs(actual - nanometres) > WAVELENGTH_TOLERANCE_NM:
                raise Uc2RunError(_(
                    "The blood-vessel enhancement reads band {index} as {expected:g} nm, but "
                    "band {index} of cube {cube} is {actual}. It is not run on other bands."
                ).format(index=index, expected=nanometres, cube=cube.name,
                         actual=_("missing") if actual is None else f"{actual:g} nm"))
        if not self.executablePath.is_file():
            raise Uc2RunError(_("{executable} is not in {directory}. Build it with {script}.").format(
                executable=EXECUTABLE_NAME, directory=self.sourceDirectory, script=BUILD_SCRIPT_HINT
            ))
        if not (self.sourceDirectory / RUNTIME_DLL_NAME).is_file():
            raise Uc2RunError(_(
                "{dll} is not beside {executable} in {directory}, so it cannot start. Rebuild "
                "with {script}."
            ).format(dll=RUNTIME_DLL_NAME, executable=EXECUTABLE_NAME,
                     directory=self.sourceDirectory, script=BUILD_SCRIPT_HINT))
        inputPath = f"{self.argument(cube)}/{CALIBRATED_HEADER_NAME}"
        outputPath = f"./{cube.name}{OUTPUT_FILE_SUFFIX}"
        for path, limit in ((inputPath, MAX_PATH_LENGTH), (outputPath, MAX_OUTPUT_PATH_LENGTH)):
            if len(path) >= limit:
                raise Uc2RunError(_(
                    "The path {path} is {length} characters; the blood-vessel enhancement keeps "
                    "at most {limit}. Move the repository, or give the cube's folder a shorter "
                    "name."
                ).format(path=path, length=len(path), limit=limit - 1))

    def acquireLock(self) -> None:
        """Hold the staged build for this run, or refuse. Never takes over a lock."""
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lockPath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise Uc2RunError(_(
                "{lock} exists, so another blood-vessel enhancement run holds {root}. Wait for it "
                "to finish. If none is running, delete {lockName} and press Capture again."
            ).format(lock=self.lockPath, root=self.root, lockName=LOCK_FILE_NAME)) from error
        try:
            try:
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            finally:
                os.close(descriptor)
        except OSError as error:
            # This call created the file and nothing else will release it.
            self.releaseLock()
            raise Uc2RunError(_("The UC2 build lock {lock} could not be written: {error}").format(
                lock=self.lockPath, error=error)) from error

    def stampLock(self) -> float:
        """Stamp the held lock now and return the time as the freshness reference."""
        os.utime(self.lockPath, None)
        return self.lockPath.stat().st_mtime

    def releaseLock(self) -> None:
        try:
            self.lockPath.unlink()
        except OSError:
            pass

    def prepareOutput(self, cube) -> None:
        """Remove this cube's previous map, so only this run's can be read."""
        self.runDirectory.mkdir(parents=True, exist_ok=True)
        try:
            self.outputPath(cube).unlink()
        except FileNotFoundError:
            pass


def collectOutput(build: Uc2Build, cube, runStartTime: float) -> np.ndarray:
    """Read the map of one run, or refuse it."""
    path = build.outputPath(cube)
    if not path.is_file():
        raise Uc2RunError(_("UC2 did not write {file} for cube {cube} ({path}).").format(
            file=path.name, cube=cube.name, path=path))
    modifiedTime = path.stat().st_mtime
    if modifiedTime < runStartTime:
        raise Uc2RunError(_(
            "{file} for cube {cube} was last written {seconds} s before this run started, so it "
            "belongs to an earlier run."
        ).format(file=path.name, cube=cube.name, seconds=f"{runStartTime - modifiedTime:.1f}"))
    try:
        return readBvMapPng(path, cube.lines, cube.samples)
    except OSError as error:
        raise Uc2RunError(_("{file} for cube {cube} could not be read: {error}").format(
            file=path.name, cube=cube.name, error=error)) from error


@dataclass(frozen=True)
class Uc2RunResult:
    success: bool
    cube: object
    message: str
    image: np.ndarray | None
    exitCode: int | None
    stdout: str
    stderr: str
    elapsedSec: float


class Uc2Run:
    """One UC2 run on the configured cube: checks, lock, process and output.

    `start` raises Uc2RunError when the run is refused, and nothing is left
    behind. Otherwise `onFinished` is called exactly once with a Uc2RunResult,
    unless `cancel` ends the run first. The lock is released before
    `onFinished` is called and on `cancel`.
    """

    def __init__(self, build: Uc2Build, cube, onFinished, *, processFactory=None,
                 timeoutSec=RUN_TIMEOUT_SEC) -> None:
        self.build = build
        self.cube = cube
        self._onFinished = onFinished
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
        self.build.assertRunnable(self.cube)
        self.build.acquireLock()
        self._lockHeld = True
        try:
            self.build.prepareOutput(self.cube)
            self._runStartTime = self.build.stampLock()
            self._startedAt = time.monotonic()
            self._process = OwnedProcess(
                self._onProcessFinished,
                processFactory=self._processFactory,
                timeoutSec=self._timeoutSec,
                logLabel="uc2",
            )
            self._process.start(
                str(self.build.executablePath),
                [self.build.argument(self.cube)],
                str(self.build.runDirectory),
            )
        except OSError as error:
            self._abandon()
            raise Uc2RunError(_("The UC2 run on cube {cube} could not be prepared: {error}").format(
                cube=self.cube.name, error=error)) from error
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

    def _onProcessFinished(self, outcome: ProcessOutcome) -> None:
        if self._process is None:
            return
        self._process = None
        elapsed = time.monotonic() - (self._startedAt or time.monotonic())
        image = None
        try:
            message = self._processFailure(outcome)
            if message is None:
                try:
                    image = collectOutput(self.build, self.cube, self._runStartTime)
                    message = _("UC2 finished on cube {cube} in {seconds} s.").format(
                        cube=self.cube.name, seconds=f"{elapsed:.1f}")
                except Uc2RunError as error:
                    message = str(error)
        except Exception as error:
            # As in Uc1Run: an exception out of this callback is dropped by Qt,
            # and the capture would never end. Report it as a failed run.
            logging.exception("SLIAFlow: the UC2 output of cube %s could not be validated",
                              self.cube.name)
            image = None
            message = _("UC2 finished on cube {cube}, but its output could not be checked: "
                        "{error}").format(cube=self.cube.name, error=error)
        finally:
            self._releaseLock()
        self._onFinished(Uc2RunResult(
            success=image is not None,
            cube=self.cube,
            message=message,
            image=image,
            exitCode=outcome.exitCode,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            elapsedSec=elapsed,
        ))

    def _processFailure(self, outcome: ProcessOutcome) -> str | None:
        name = self.cube.name
        if outcome.failedToStart:
            return _(
                "UC2 could not be started for cube {cube}. Check that {executable} and {dll} "
                "exist; build them with {script}."
            ).format(cube=name, executable=self.build.executablePath, dll=RUNTIME_DLL_NAME,
                     script=BUILD_SCRIPT_HINT)
        if outcome.timedOut:
            return _("UC2 timed out after {seconds} s on cube {cube} and was stopped.").format(
                seconds=f"{self._timeoutSec:g}", cube=name)
        if outcome.crashed:
            return _("UC2 crashed on cube {cube}.").format(cube=name)
        markerLine = self._errorLine(outcome)
        if outcome.exitCode != 0:
            return _("UC2 exited with code {code} on cube {cube}. {line}").format(
                code=outcome.exitCode, cube=name, line=markerLine or "").strip()
        if markerLine:
            return _(
                "UC2 reported '{line}' on cube {cube} and exited 0, so its output cannot be "
                "trusted."
            ).format(line=markerLine, cube=name)
        return None

    @staticmethod
    def _errorLine(outcome: ProcessOutcome) -> str:
        """The first line on either stream carrying one of UC2's error messages."""
        for line in (outcome.stdout + "\n" + outcome.stderr).splitlines():
            if any(marker in line for marker in ERROR_MARKERS):
                return line.strip()
        return ""
