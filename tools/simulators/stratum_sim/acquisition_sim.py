"""The acquisition stand-in: write one ENVI dataset, then stream LiveView.

This process stands where `AcquisitionSystemApp` stands. It writes a real
ENVI/BSQ dataset the genuine UC1 binary can consume, and it serves an RGB
`LiveView` stream on the port the real application serves it on.

In scene mode `recorded` it writes nothing. It reads one case of the public HSI
Human Brain Database where it lies, streams LiveView, and on a capture trigger
holds a capture delay and then publishes that case's cube - imitating what the
rig does, not inventing what it sees.

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

from . import config, contract, envi, frames, igtl_transport, spectra, tissue

logger = logging.getLogger(__name__)

NON_CLINICAL_NOTICE = (
    "SIMULATED, NON-CLINICAL DATA. This process stands in for a hyperspectral "
    "camera. Nothing it produces is patient data, is derived from patient data, "
    "or carries diagnostic meaning."
)

PHANTOM_NOTICE = (
    "The scene is a synthetic optical phantom: its spectra are built from a "
    "haemoglobin absorption and scattering model so that they have the shape of "
    "tissue reflectance. The regions are drawn geometrically. A region named "
    "'tumour-like' is one where the blood volume fraction was set high and the "
    "saturation low - it is not a tumour, and any class a downstream classifier "
    "assigns to it is that classifier's output, not a detection."
)

# One string per scene mode. The two scenes are different enough that a single
# label would hide which one produced a dataset.
SIMULATION_DETAILS = {
    config.SCENE_MODE_TISSUE: "acquisition stand-in, synthetic tissue phantom",
    config.SCENE_MODE_CHANNEL: "acquisition stand-in, synthetic scene",
}

SIMULATION_DETAIL = SIMULATION_DETAILS[config.SCENE_MODE_CHANNEL]

# The recorded mode's notice replaces both notices above, which would be false
# over a recorded case: its cube is not synthetic, and it is derived from
# anonymized patient imagery.
RECORDED_NOTICE = (
    "RECORDED PUBLIC DATA, SIMULATED ACQUISITION, NON-CLINICAL USE. The cube is case "
    "{case} of the public, anonymized HSI Human Brain Database published by ULPGC "
    "(https://hsibraindatabase.iuma.ulpgc.es/). It is read where it lies and never "
    "written. Only the acquisition event is simulated: the LiveView source stands in "
    "for the rig's camera and a trigger stands in for its shutter. Nothing derived "
    "from it here is a clinical result or carries diagnostic meaning."
)

# In recorded mode LiveView and the cube are unrelated, so LiveView's detail names
# its own source and never the case. The laptop camera is the only source the mode
# accepts; `config.py` refuses any other.
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

# Frames measured before the achieved rate is reported. Throughput is an
# acceptance criterion, not an assumption: CRC over a 640x480x3 frame is not
# free, which is why the default preset is the small one.
RATE_MEASUREMENT_FRAME_COUNT = 30


class SpectralRankTooLowError(RuntimeError):
    """The dataset was written, but it is spectrally degenerate."""


class RecordedCaseError(RuntimeError):
    """The named case is not a recorded database case this stand-in may read."""


def recordedNotice(caseName: str) -> str:
    """The notice a recorded session prints instead of the two phantom-session ones."""
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
            "carry the marker. Scene mode 'recorded' reads approved database cases only."
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


def synthesizeDataset(
    simulatorConfig: config.SimulatorConfig, frameBgr: numpy.ndarray, datasetFolder: Path
) -> envi.DatasetRef:
    """Build and write the dataset for one frame of the synthetic scene."""
    wavelengthsNm = spectra.bandWavelengthsNm(simulatorConfig.bands)
    sceneRng = numpy.random.default_rng(simulatorConfig.seed)

    reflectance = spectra.reflectanceCube(
        frameBgr,
        wavelengthsNm,
        textureFeatureCount=simulatorConfig.textureFeatureCount,
        rng=sceneRng,
    )
    return _writeCubeAsDataset(simulatorConfig, reflectance, wavelengthsNm, datasetFolder)


def _writeCubeAsDataset(
    simulatorConfig: config.SimulatorConfig,
    reflectance: numpy.ndarray,
    wavelengthsNm: numpy.ndarray,
    datasetFolder: Path,
) -> envi.DatasetRef:
    """Invert UC1's calibration for a reflectance cube and write the dataset.

    The references are drawn once per process; per-frame noise, when it is
    enabled at all, comes from a seed that includes the frame index.
    """
    referenceRng = numpy.random.default_rng(simulatorConfig.seed)
    darkCube, whiteCube = spectra.referenceCubes(
        referenceRng, simulatorConfig.bands, simulatorConfig.lines, simulatorConfig.samples
    )
    rawCube = spectra.rawFromReflectance(
        reflectance,
        darkCube,
        whiteCube,
        noiseCounts=simulatorConfig.noiseCounts,
        rng=numpy.random.default_rng([simulatorConfig.seed, 0]),
    )
    datasetRef = envi.writeDataset(datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm)

    # Every dataset write clears any phantom record already in the folder, and
    # the phantom path then writes its own. `--dataset-folder` can point two
    # runs at one folder, and the ENVI writer replaces only the four files it
    # owns, so without this a channel dataset written over a phantom would keep
    # the phantom's region map and legend and appear to be described by them.
    removed = tissue.removePhantomRecord(datasetRef.folder)
    if removed:
        print(f"  Removed a stale phantom record: {', '.join(path.name for path in removed)}")

    return datasetRef


def synthesizePhantomDataset(
    simulatorConfig: config.SimulatorConfig, datasetFolder: Path
) -> tuple[envi.DatasetRef, numpy.ndarray, numpy.ndarray]:
    """Build the tissue phantom, write it, and return `(dataset, frame, regions)`.

    The order is the reverse of the channel scene's: the cube is built first
    from the optical model and the LiveView frame is rendered from it. So the
    pane and the dataset cannot drift apart - the frame is a projection of the
    exact array that was written.
    """
    wavelengthsNm = spectra.bandWavelengthsNm(simulatorConfig.bands)
    regionMap = tissue.phantomRegionMap(simulatorConfig.lines, simulatorConfig.samples)
    reflectance = tissue.phantomReflectanceCube(regionMap, wavelengthsNm)

    datasetRef = _writeCubeAsDataset(
        simulatorConfig, reflectance, wavelengthsNm, datasetFolder
    )
    tissue.writePhantomRecord(datasetRef.folder, regionMap)

    return datasetRef, tissue.renderFrameBgr(reflectance, wavelengthsNm), regionMap


def describeRegionMap(regionMap: numpy.ndarray) -> str:
    """One line naming each region of the phantom and how much of the frame it covers."""
    total = regionMap.size
    parts = []
    for value in tissue.REGION_VALUES:
        count = int((regionMap == value).sum())
        if count:
            parts.append(f"{tissue.REGION_NAMES[value]} {100.0 * count / total:.1f}%")
    return ", ".join(parts)


def reportSpectralRank(datasetRef: envi.DatasetRef) -> spectra.SpectralRankReport:
    """Measure and print the rank of the dataset as it was read back from disk.

    The measurement is taken on the round trip, not on the cube still in memory,
    because what a consumer gets is the bytes on disk.
    """
    report = spectra.spectralRankReport(datasetRef.loadCalibratedCube())
    print(
        f"  Band covariance rank: {report.rank} "
        f"(condition number over the retained subspace: {report.conditionNumber:.3e})"
    )
    return report


def assertSpectralRankIsSufficient(report: spectra.SpectralRankReport) -> None:
    """Fail rather than leave a degenerate dataset looking successful.

    The configuration validator predicts the rank from the settings; this checks
    the rank actually measured. Printing it and exiting 0 would let a dataset
    that no consumer can use pass for a good one, which is the failure mode this
    whole card exists to prevent.
    """
    if report.rank < spectra.MINIMUM_SPECTRAL_RANK:
        raise SpectralRankTooLowError(
            f"The dataset's band covariance is rank {report.rank}, below the required "
            f"{spectra.MINIMUM_SPECTRAL_RANK}. It is degenerate and must not be used as "
            "pipeline input. Delete the folder and generate it again."
        )


def enqueueRate(enqueuedFrameCount: int, measurementStart: float | None) -> float:
    """Frames per second over the intervals between enqueued frames.

    `measurementStart` is taken at the top of the cycle that enqueued the first
    counted frame, so n frames span n-1 intervals and dividing by n would report
    a rate the sender never reached. At the frame counts used here that
    difference is a few percent, which is the same order as the margin the
    target is being judged by.
    """
    if measurementStart is None or enqueuedFrameCount < 2:
        return 0.0
    elapsed = time.perf_counter() - measurementStart
    return (enqueuedFrameCount - 1) / elapsed if elapsed > 0.0 else 0.0


def streamLiveView(
    simulatorConfig: config.SimulatorConfig,
    frameSource,
    serverFactory=igtl_transport.ImageStreamServer,
) -> float:
    """Serve LiveView until interrupted. Returns the achieved enqueue rate.

    The rate returned is measured where the sender can measure it: frames handed
    to `send_message(wait=False)`, which queues them on the server's writer
    thread. It is an upper bound on what a client receives, so the number that
    settles the throughput criterion is the receiver-side one from
    `tests/liveview_client.py`.
    """
    metadata = contract.liveViewMetadata(
        SIMULATION_DETAILS[simulatorConfig.sceneMode],
        deviceName=simulatorConfig.liveViewDeviceName,
    )
    framePeriodSec = 1.0 / simulatorConfig.targetFrameRate

    sentFrameCount = 0
    measurementStart: float | None = None
    achievedFrameRate = 0.0
    reportedRate = False

    with serverFactory(port=simulatorConfig.liveViewPort) as server, (
        igtl_transport.InterruptFlag()
    ) as interrupt:
        print(
            f"  LiveView server listening on 127.0.0.1:{simulatorConfig.liveViewPort} "
            f"as device '{simulatorConfig.liveViewDeviceName}'. Press Ctrl-C to stop."
        )

        while not interrupt.requested:
            cycleStart = time.perf_counter()

            frameBgr = frameSource.read()
            if frameBgr is not None and server.sendImage(
                igtl_transport.prepareFrameForWire(frameBgr, simulatorConfig.rotate180),
                simulatorConfig.liveViewDeviceName,
                metadata,
            ):
                if measurementStart is None:
                    measurementStart = cycleStart
                sentFrameCount += 1

                if not reportedRate and sentFrameCount >= RATE_MEASUREMENT_FRAME_COUNT:
                    achievedFrameRate = enqueueRate(sentFrameCount, measurementStart)
                    print(
                        f"  Enqueue rate over the first {sentFrameCount} frames: "
                        f"{achievedFrameRate:.2f} fps "
                        f"(target {simulatorConfig.targetFrameRate:.2f} fps). "
                        "This counts frames queued for sending, so it is an upper bound; "
                        "the receiver-side rate is the one to trust."
                    )
                    reportedRate = True

                if simulatorConfig.frameCount and sentFrameCount >= simulatorConfig.frameCount:
                    break

            remaining = framePeriodSec - (time.perf_counter() - cycleStart)
            if remaining > 0.0:
                time.sleep(remaining)

    if not reportedRate:
        achievedFrameRate = enqueueRate(sentFrameCount, measurementStart)

    print(
        f"  LiveView stopped after {sentFrameCount} frames "
        f"({achievedFrameRate:.2f} fps enqueued)."
    )
    return achievedFrameRate


def buildArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim acquisition",
        description=(
            "Write a simulated ENVI dataset and stream a LiveView frame, or, in scene mode "
            "'recorded', stream LiveView and publish a recorded case's cube on each capture "
            "trigger without writing anything."
        ),
    )
    parser.add_argument("--preset", choices=sorted(config.FRAME_PRESETS), default=None)
    parser.add_argument("--frame-source", dest="frameSource", choices=config.FRAME_SOURCE_NAMES)
    parser.add_argument(
        "--scene-mode",
        dest="sceneMode",
        choices=config.SCENE_MODE_NAMES,
        default=None,
        help=(
            "'tissue' builds the cube from a haemoglobin and scattering model and renders "
            "the LiveView frame from it; 'channel' builds the cube from a camera or "
            "synthetic frame; 'recorded' reads --case and builds nothing."
        ),
    )
    parser.add_argument(
        "--case",
        dest="case",
        default=None,
        help="Recorded case folder name under --recorded-root, for scene mode 'recorded'.",
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
    parser.add_argument("--dataset-root", dest="datasetRoot", default=None)
    parser.add_argument(
        "--dataset-folder",
        dest="datasetFolder",
        default=None,
        help=(
            "Write into this exact folder instead of a new sim-YYYYMMDD-HHMMSS one. "
            "The overwrite interlock still applies: a folder whose raw.hdr lacks the "
            "simulated marker is refused."
        ),
    )
    parser.add_argument("--port", dest="liveViewPort", type=int, default=None)
    parser.add_argument("--frame-rate", dest="targetFrameRate", type=float, default=None)
    parser.add_argument("--frames", dest="frameCount", type=int, default=None)
    parser.add_argument("--seed", dest="seed", type=int, default=None)
    parser.add_argument("--noise-counts", dest="noiseCounts", type=int, default=None)
    parser.add_argument(
        "--no-rotate180",
        dest="rotate180",
        action="store_const",
        const=False,
        default=None,
        help="Send frames unrotated. The real application rotates, so this is for debugging only.",
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Write the dataset and exit without serving LiveView.",
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
    """Every port the configured scene opens a server on, by the setting that names it."""
    if simulatorConfig.sceneMode == config.SCENE_MODE_RECORDED:
        names = ("liveViewPort", "hsCubePort", "controlPort")
    else:
        names = ("liveViewPort",)
    return {name: getattr(simulatorConfig, name) for name in names}


def servedPorts(simulatorConfig: config.SimulatorConfig) -> tuple[int, ...]:
    """Every port the configured scene opens a server on."""
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
    # `datasetFolder` names one folder rather than the root the folder is
    # created under, so it is not a configuration setting and is kept out of the
    # overrides the loader validates.
    commandLineOnly = ("dataset_only", "datasetFolder", "instantCapture", "allowSharedPort")
    overrides = {
        key: value
        for key, value in vars(arguments).items()
        if key not in commandLineOnly and value is not None
    }
    if arguments.instantCapture:
        overrides.update(captureDelayMinSec=0.0, captureDelayMaxSec=0.0)
    # A recorded session takes the laptop camera, so asking for the mode is
    # enough. An explicit other source still reaches the loader and is refused.
    if arguments.sceneMode == config.SCENE_MODE_RECORDED:
        overrides.setdefault("frameSource", config.RECORDED_FRAME_SOURCE)
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

    # Before the dataset and the camera: a refusal that waited for the bind would
    # arrive after the camera had been taken from SLIAFlow.
    if not arguments.dataset_only:
        repeatedPorts = repeatedServedPortMessage(simulatorConfig)
        if repeatedPorts is not None:
            print(f"ERROR: {repeatedPorts}", file=sys.stderr)
            return 1
        try:
            for port in servedPorts(simulatorConfig):
                igtl_transport.assertPortCanBeServed(
                    port, allowSharedPort=arguments.allowSharedPort
                )
        except igtl_transport.PortRefusedError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
    serverFactory = functools.partial(
        igtl_transport.ImageStreamServer, allowSharedPort=arguments.allowSharedPort
    )

    if simulatorConfig.sceneMode == config.SCENE_MODE_RECORDED:
        return runRecordedStandIn(simulatorConfig, arguments, serverFactory)

    print(NON_CLINICAL_NOTICE)
    isPhantom = simulatorConfig.sceneMode == config.SCENE_MODE_TISSUE
    if isPhantom:
        print(PHANTOM_NOTICE)
    print()
    print(
        f"Acquisition stand-in: preset '{simulatorConfig.presetName}' "
        f"({simulatorConfig.samples}x{simulatorConfig.lines}), "
        f"{simulatorConfig.bands} bands, scene mode '{simulatorConfig.sceneMode}', "
        f"frame source '{simulatorConfig.frameSource}', "
        f"pyigtl {igtl_transport.installedPyigtlVersion()}."
    )

    datasetFolder = (
        Path(arguments.datasetFolder).expanduser()
        if arguments.datasetFolder
        else Path(simulatorConfig.datasetRoot) / envi.datasetFolderName()
    )

    if isPhantom:
        try:
            datasetRef, phantomFrame, regionMap = synthesizePhantomDataset(
                simulatorConfig, datasetFolder
            )
        except envi.DatasetWriteError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        frameSource = tissue.PhantomFrameSource(phantomFrame)
        print(f"  Phantom regions: {describeRegionMap(regionMap)}")
    else:
        try:
            frameSource = frames.createFrameSource(
                simulatorConfig.frameSource,
                simulatorConfig.samples,
                simulatorConfig.lines,
                simulatorConfig.seed,
                simulatorConfig.webcamIndex,
            )
        except (ImportError, RuntimeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

        firstFrame = frameSource.read()
        if firstFrame is None:
            print("ERROR: the frame source produced no frame.", file=sys.stderr)
            return 1

        try:
            datasetRef = synthesizeDataset(simulatorConfig, firstFrame, datasetFolder)
        except envi.DatasetWriteError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

    print(f"  Dataset written: {datasetRef.folder}")
    try:
        assertSpectralRankIsSufficient(reportSpectralRank(datasetRef))
    except SpectralRankTooLowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if arguments.dataset_only:
        return 0

    try:
        streamLiveView(simulatorConfig, frameSource, serverFactory)
    except igtl_transport.PortRefusedError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        closeSource = getattr(frameSource, "close", None)
        if callable(closeSource):
            closeSource()

    print(f"  Dataset left intact at {datasetRef.folder}")
    return 0


def runRecordedStandIn(
    simulatorConfig: config.SimulatorConfig,
    arguments,
    serverFactory=igtl_transport.ImageStreamServer,
) -> int:
    """Run scene mode 'recorded'. There is no dataset step, because nothing is written."""
    if arguments.dataset_only or arguments.datasetFolder:
        print(
            "ERROR: --dataset-only and --dataset-folder write a dataset, and scene mode "
            "'recorded' writes nothing. A recorded case is read where it lies.",
            file=sys.stderr,
        )
        return 1

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
        frameSource = frames.createFrameSource(
            simulatorConfig.frameSource,
            simulatorConfig.samples,
            simulatorConfig.lines,
            simulatorConfig.seed,
            simulatorConfig.webcamIndex,
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
