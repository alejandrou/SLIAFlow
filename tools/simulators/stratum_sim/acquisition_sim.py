"""The acquisition stand-in: write one ENVI dataset, then stream LiveView.

This process stands where `AcquisitionSystemApp` stands. It writes a real
ENVI/BSQ dataset the genuine UC1 binary can consume, and it serves an RGB
`LiveView` stream on the port the real application serves it on.

Nothing produced here is clinical data.
"""

from __future__ import annotations

import argparse
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

# Frames measured before the achieved rate is reported. Throughput is an
# acceptance criterion, not an assumption: CRC over a 640x480x3 frame is not
# free, which is why the default preset is the small one.
RATE_MEASUREMENT_FRAME_COUNT = 30


class SpectralRankTooLowError(RuntimeError):
    """The dataset was written, but it is spectrally degenerate."""


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


def streamLiveView(simulatorConfig: config.SimulatorConfig, frameSource) -> float:
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

    with igtl_transport.ImageStreamServer(port=simulatorConfig.liveViewPort) as server, (
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
        description="Write a simulated ENVI dataset and stream a LiveView frame.",
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
            "synthetic frame. Only 'channel' can carry motion or a webcam."
        ),
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
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    arguments = buildArgumentParser().parse_args(argv)

    # `datasetFolder` names one folder rather than the root the folder is
    # created under, so it is not a configuration setting and is kept out of the
    # overrides the loader validates.
    commandLineOnly = ("dataset_only", "datasetFolder")
    overrides = {
        key: value
        for key, value in vars(arguments).items()
        if key not in commandLineOnly and value is not None
    }
    try:
        simulatorConfig = config.loadSimulatorConfig(overrides=overrides)
    except config.ConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

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
        streamLiveView(simulatorConfig, frameSource)
    finally:
        closeSource = getattr(frameSource, "close", None)
        if callable(closeSource):
            closeSource()

    print(f"  Dataset left intact at {datasetRef.folder}")
    return 0
