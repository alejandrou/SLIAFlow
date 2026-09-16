"""The acquisition stand-in: stream LiveView and publish a recorded cube on capture.

This process stands where `AcquisitionSystemApp` stands. It writes nothing. It
reads one case of the public HSI Human Brain Database where it lies, serves the
laptop camera as `LiveView` on the port the real application serves it on, and
on a capture trigger holds a capture delay and then publishes that case's cube -
imitating what the rig does, not inventing what it sees.

Nothing produced here is a clinical result.
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
import time
from pathlib import Path

import numpy

from . import config, contract, envi, frames, igtl_transport

logger = logging.getLogger(__name__)

RECORDED_NOTICE = (
    "RECORDED PUBLIC DATA, SIMULATED ACQUISITION, NON-CLINICAL USE. The cube is case "
    "{case} of the public, anonymized HSI Human Brain Database published by ULPGC "
    "(https://hsibraindatabase.iuma.ulpgc.es/). It is read where it lies and never "
    "written. Only the acquisition event is simulated: the LiveView source stands in "
    "for the rig's camera and a trigger stands in for its shutter. Nothing derived "
    "from it here is a clinical result or carries diagnostic meaning."
)

# LiveView and the cube are unrelated, so LiveView's detail names its own source
# and never the case. The laptop camera is the only source there is.
RECORDED_LIVE_VIEW_DETAIL = "acquisition stand-in, laptop camera"
RECORDED_DETAIL_PRODUCER = "acquisition stand-in"

# How often the control channel repeats its state while a client is connected.
# Load-bearing, not cosmetic: pyigtl 0.3.4 treats an empty `recv` as "no message"
# rather than as end of stream, so the handler of a client that has left keeps
# looping until a send to it fails, and the next client waits in the accept
# backlog until then. Measured on 2026-09-13: with no send, a second and third
# one-shot client were never served; with a send every 0.5 s, each was served
# within 0.2 s.
CONTROL_STATUS_INTERVAL_SEC = 0.5


class RecordedCaseError(RuntimeError):
    """The named case is not a recorded database case this stand-in may read."""


def recordedNotice(caseName: str) -> str:
    """The notice a session prints before it opens anything."""
    return RECORDED_NOTICE.format(case=caseName)


class CaptureController:
    """The capture's state, advanced by the caller's clock.

    It holds no socket and never sleeps, so the timing a trigger promises is
    tested by passing moments in rather than by waiting for them. The delay is a
    deadline, which is what lets LiveView keep streaming through a capture and a
    second trigger be answered at once.
    """

    def __init__(
        self,
        caseName: str,
        caseFolder: Path,
        delayMinSec: float,
        delayMaxSec: float,
        rng: numpy.random.Generator,
    ) -> None:
        self.caseName = caseName
        self.caseFolder = Path(caseFolder)
        self.captureNumber = 0
        self._delayMinSec = delayMinSec
        self._delayMaxSec = delayMaxSec
        self._rng = rng
        self._delaySec = 0.0
        self._completesAt: float | None = None

    @property
    def capturing(self) -> bool:
        return self._completesAt is not None

    @property
    def statusText(self) -> str:
        """The state repeated on `CaptureStatus`."""
        if self.capturing:
            return self._capturingText()
        if self.captureNumber == 0:
            return "IDLE"
        # `folder=` stays last: a path may contain spaces, so it is the rest of
        # the line.
        return (
            f"READY capture={self.captureNumber} case={self.caseName} "
            f"folder={self.caseFolder}"
        )

    def _capturingText(self) -> str:
        return (
            f"CAPTURING capture={self.captureNumber} case={self.caseName} "
            f"delay={self._delaySec:.1f}"
        )

    def handleCommand(self, text: str, now: float) -> str:
        """Act on one received command and return the one reply to it."""
        command = text.strip()
        if command != contract.CAPTURE_COMMAND:
            return f"REFUSED unknown command {command}"
        if self.capturing:
            # Answered and dropped. A queued trigger would start a capture at a
            # moment nobody chose.
            return f"IGNORED capture {self.captureNumber} already in progress"

        self.captureNumber += 1
        self._delaySec = float(self._rng.uniform(self._delayMinSec, self._delayMaxSec))
        self._completesAt = now + self._delaySec
        return self._capturingText()

    def advance(self, now: float) -> bool:
        """Return True exactly once per capture, at the first moment it is complete."""
        if self._completesAt is None or now < self._completesAt:
            return False
        self._completesAt = None
        return True


def loadRecordedCase(simulatorConfig: config.SimulatorConfig) -> envi.DatasetRef:
    """Open the configured case read-only, refusing anything that is not a database case.

    Every check runs here, before any port is opened, so a wrong case name stops
    the session rather than leaving it serving LiveView with nothing to capture.
    """
    caseFolder = Path(simulatorConfig.recordedRoot) / simulatorConfig.case
    if not caseFolder.is_dir():
        raise RecordedCaseError(
            f"There is no case folder {caseFolder}. Check case and recordedRoot."
        )

    dataset = envi.loadDataset(caseFolder)
    if not dataset.recorded:
        raise RecordedCaseError(
            f"{dataset.folder} does not identify as a case of the "
            f"{envi.RECORDED_DATASET_MARKER}: its {envi.GROUND_TRUTH_HEADER_FILE_NAME} does not "
            "carry the marker. The acquisition stand-in reads approved database cases only."
        )
    envi.assertDataFilesMatchHeader(dataset)
    return dataset


def serveRecordedCapture(
    simulatorConfig: config.SimulatorConfig,
    frameSource,
    dataset: envi.DatasetRef,
    serverFactory=igtl_transport.ImageStreamServer,
    stopWhen=None,
    rng: numpy.random.Generator | None = None,
) -> CaptureController:
    """Stream LiveView, answer capture triggers, and publish the case's cube on each.

    Everything runs on one thread against one clock. Three ports are opened -
    LiveView, HSCube and Control - and no other: the stereoscopic and StO2 ports
    stay reserved.

    The cube is read fresh from disk when each capture completes and is sent
    once, to the HSCube client connected then or to the next one to connect.
    Nothing is written anywhere.
    """
    controller = CaptureController(
        simulatorConfig.case,
        dataset.folder,
        simulatorConfig.captureDelayMinSec,
        simulatorConfig.captureDelayMaxSec,
        rng if rng is not None else numpy.random.default_rng(),
    )
    liveViewMetadata = contract.liveViewMetadata(
        RECORDED_LIVE_VIEW_DETAIL,
        deviceName=simulatorConfig.liveViewDeviceName,
    )
    cubeMetadata = contract.hsCubeMetadata(
        dataset, contract.recordedCaseDetail(RECORDED_DETAIL_PRODUCER, simulatorConfig.case)
    )
    framePeriodSec = 1.0 / simulatorConfig.targetFrameRate

    pendingCube: numpy.ndarray | None = None
    reportedWaitingForCubeClient = False
    announcedStatus: str | None = None
    statusSentAt: float | None = None

    with (
        serverFactory(port=simulatorConfig.liveViewPort) as liveViewServer,
        serverFactory(port=simulatorConfig.hsCubePort) as cubeServer,
        serverFactory(port=simulatorConfig.controlPort) as controlServer,
        igtl_transport.InterruptFlag() as interrupt,
    ):
        print(
            f"  LiveView server listening on 127.0.0.1:{simulatorConfig.liveViewPort} "
            f"as device '{simulatorConfig.liveViewDeviceName}'."
        )
        print(
            f"  HSCube server listening on 127.0.0.1:{simulatorConfig.hsCubePort} "
            f"as device '{contract.HS_CUBE_DEVICE_NAME}'."
        )
        print(
            f"  Control server listening on 127.0.0.1:{simulatorConfig.controlPort}: send "
            f"'{contract.CAPTURE_COMMAND}' as '{contract.CAPTURE_TRIGGER_DEVICE_NAME}'; the "
            f"reply arrives as '{contract.CAPTURE_REPLY_DEVICE_NAME}' and the state as "
            f"'{contract.CAPTURE_STATUS_DEVICE_NAME}'."
        )
        print("  Waiting for a capture trigger. Press Ctrl-C to stop.")

        while not interrupt.requested and not (stopWhen is not None and stopWhen()):
            cycleStart = time.perf_counter()

            frameBgr = frameSource.read()
            if frameBgr is not None:
                liveViewServer.sendImage(
                    igtl_transport.prepareFrameForWire(frameBgr, simulatorConfig.rotate180),
                    simulatorConfig.liveViewDeviceName,
                    liveViewMetadata,
                )

            for command in controlServer.receiveStrings(contract.CAPTURE_TRIGGER_DEVICE_NAME):
                reply = controller.handleCommand(command, time.perf_counter())
                print(f"  Trigger {command.strip()!r}: {reply}")
                controlServer.sendString(reply, contract.CAPTURE_REPLY_DEVICE_NAME)

            if controller.advance(time.perf_counter()):
                pendingCube = envi.loadRawCube(dataset)
                reportedWaitingForCubeClient = False
                print(f"  Capture {controller.captureNumber} complete: {controller.statusText}")

            if pendingCube is not None:
                if cubeServer.isConnected and cubeServer.sendImage(
                    pendingCube, contract.HS_CUBE_DEVICE_NAME, cubeMetadata
                ):
                    print(
                        f"  HSCube for capture {controller.captureNumber} queued on "
                        f"127.0.0.1:{simulatorConfig.hsCubePort}: shape {pendingCube.shape}, "
                        f"{pendingCube.dtype}."
                    )
                    pendingCube = None
                elif not reportedWaitingForCubeClient:
                    print(
                        f"  No client on 127.0.0.1:{simulatorConfig.hsCubePort} yet; the cube "
                        "goes to the next one that connects. The folder is ready either way."
                    )
                    reportedWaitingForCubeClient = True

            status = controller.statusText
            now = time.perf_counter()
            if (
                status != announcedStatus
                or statusSentAt is None
                or now - statusSentAt >= CONTROL_STATUS_INTERVAL_SEC
            ):
                controlServer.sendString(status, contract.CAPTURE_STATUS_DEVICE_NAME)
                announcedStatus = status
                statusSentAt = now

            remaining = framePeriodSec - (time.perf_counter() - cycleStart)
            if remaining > 0.0:
                time.sleep(remaining)

    return controller


def buildArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim acquisition",
        description=(
            "Stream LiveView from the laptop camera and publish a recorded case's cube on "
            "each capture trigger, without writing anything."
        ),
    )
    parser.add_argument("--preset", choices=sorted(config.FRAME_PRESETS), default=None)
    parser.add_argument(
        "--case",
        dest="case",
        default=None,
        help="Recorded case folder name under --recorded-root, for example 004-02. Required.",
    )
    parser.add_argument(
        "--recorded-root",
        dest="recordedRoot",
        default=None,
        help="Where recorded cases live. Defaults to input/bin/bin. Read, never written.",
    )
    parser.add_argument("--cube-port", dest="hsCubePort", type=int, default=None)
    parser.add_argument("--control-port", dest="controlPort", type=int, default=None)
    parser.add_argument("--capture-delay-min", dest="captureDelayMinSec", type=float, default=None)
    parser.add_argument("--capture-delay-max", dest="captureDelayMaxSec", type=float, default=None)
    parser.add_argument(
        "--instant-capture",
        dest="instantCapture",
        action="store_true",
        help="Complete a capture as soon as it is triggered: both delay bounds at 0.",
    )
    parser.add_argument("--port", dest="liveViewPort", type=int, default=None)
    parser.add_argument("--frame-rate", dest="targetFrameRate", type=float, default=None)
    parser.add_argument(
        "--no-rotate180",
        dest="rotate180",
        action="store_const",
        const=False,
        default=None,
        help="Send frames unrotated. The real application rotates, so this is for debugging only.",
    )
    parser.add_argument(
        "--allow-shared-port",
        dest="allowSharedPort",
        action="store_true",
        help=(
            "Serve ports another producer is serving. Both must be started with this "
            "switch; without it an occupied port is refused."
        ),
    )
    return parser


def servedPortSettings(simulatorConfig: config.SimulatorConfig) -> dict[str, int]:
    """Every port the stand-in opens a server on, by the setting that names it."""
    names = ("liveViewPort", "hsCubePort", "controlPort")
    return {name: getattr(simulatorConfig, name) for name in names}


def servedPorts(simulatorConfig: config.SimulatorConfig) -> tuple[int, ...]:
    """Every port the stand-in opens a server on."""
    return tuple(servedPortSettings(simulatorConfig).values())


def repeatedServedPortMessage(simulatorConfig: config.SimulatorConfig) -> str | None:
    """The refusal of one port configured for two channels, or `None` when all differ.

    Each port is probed on its own, and a port given twice passes both probes.
    """
    settingsByPort: dict[int, list[str]] = {}
    for name, port in servedPortSettings(simulatorConfig).items():
        settingsByPort.setdefault(port, []).append(name)
    clashes = [
        f"{', '.join(names[:-1])} and {names[-1]} are {'all' if len(names) > 2 else 'both'} {port}"
        for port, names in settingsByPort.items()
        if len(names) > 1
    ]
    if not clashes:
        return None
    return (
        "; ".join(clashes)
        + ". Each channel needs a port of its own, or a client of one channel would reach the "
        "server of another. Give them different ports in config/local.json or with --port, "
        "--cube-port and --control-port. --allow-shared-port shares a port between producers, "
        "never between one producer's own channels."
    )


def commandLineOverrides(arguments: argparse.Namespace) -> dict:
    """Turn parsed arguments into the settings that override `config/local.json`."""
    commandLineOnly = ("instantCapture", "allowSharedPort")
    overrides = {
        key: value
        for key, value in vars(arguments).items()
        if key not in commandLineOnly and value is not None
    }
    if arguments.instantCapture:
        overrides.update(captureDelayMinSec=0.0, captureDelayMaxSec=0.0)
    return overrides


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    arguments = buildArgumentParser().parse_args(argv)
    overrides = commandLineOverrides(arguments)
    try:
        simulatorConfig = config.loadSimulatorConfig(overrides=overrides)
    except config.ConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if simulatorConfig.case is None:
        print(
            "ERROR: The acquisition stand-in reads one recorded case, so it needs one: pass "
            "--case with the case folder name under recordedRoot, for example --case 004-02, "
            "or set case in config/local.json.",
            file=sys.stderr,
        )
        return 1

    # Before the case and the camera: a refusal that waited for the bind would
    # arrive after the camera had been taken from SLIAFlow.
    repeatedPorts = repeatedServedPortMessage(simulatorConfig)
    if repeatedPorts is not None:
        print(f"ERROR: {repeatedPorts}", file=sys.stderr)
        return 1
    try:
        for port in servedPorts(simulatorConfig):
            igtl_transport.assertPortCanBeServed(port, allowSharedPort=arguments.allowSharedPort)
    except igtl_transport.PortRefusedError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    serverFactory = functools.partial(
        igtl_transport.ImageStreamServer, allowSharedPort=arguments.allowSharedPort
    )

    return runRecordedStandIn(simulatorConfig, serverFactory)


def runRecordedStandIn(
    simulatorConfig: config.SimulatorConfig,
    serverFactory=igtl_transport.ImageStreamServer,
) -> int:
    """Open the case, then the camera, then serve. Nothing is written."""
    print(recordedNotice(simulatorConfig.case))
    print()

    try:
        dataset = loadRecordedCase(simulatorConfig)
    except (RecordedCaseError, envi.DatasetReadError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    wavelengthRange = (
        f"{dataset.wavelengthsNm[0]:g}-{dataset.wavelengthsNm[-1]:g} nm"
        if dataset.wavelengthsNm
        else "no wavelengths in the header"
    )
    print(
        f"Acquisition stand-in: recorded case '{simulatorConfig.case}' "
        f"({dataset.samples}x{dataset.lines}, {dataset.bands} bands, {wavelengthRange}), "
        f"LiveView from the laptop camera (index {simulatorConfig.webcamIndex}) at preset "
        f"'{simulatorConfig.presetName}', capture delay {simulatorConfig.captureDelayMinSec:g}"
        f"-{simulatorConfig.captureDelayMaxSec:g} s, "
        f"pyigtl {igtl_transport.installedPyigtlVersion()}."
    )
    print(f"  Case folder, read-only: {dataset.folder}")

    try:
        frameSource = frames.WebcamFrameSource(
            simulatorConfig.webcamIndex, simulatorConfig.samples, simulatorConfig.lines
        )
    except (ImportError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        controller = serveRecordedCapture(
            simulatorConfig, frameSource, dataset, serverFactory=serverFactory
        )
    except igtl_transport.PortRefusedError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        closeSource = getattr(frameSource, "close", None)
        if callable(closeSource):
            closeSource()

    print(
        f"  Stopped after {controller.captureNumber} capture(s). "
        f"Case folder left untouched at {dataset.folder}"
    )
    return 0
