"""Run the non-clinical UC1 arithmetic stand-in and send five result maps."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import numpy

from . import contract, igtl_transport, uc1_maps

DEFAULT_PORT = contract.UC1_MAP_PORT
DEFAULT_INTERVAL_SEC = 1.0
SIMULATION_DETAIL = "arithmetic stand-in, not a classifier"
SIMULATION_NOTICE_DEVICE_NAME = "UC1_SIM_NOTICE"
SIMULATION_NOTICE = (
    "SIMULATED UC1 output: arithmetic stand-in, not a classifier. "
    "The maps were not fitted or clinically validated."
)

# The per-cycle stdout banner. It is a constant rather than an inline f-string
# so a test can assert what an operator actually reads on every cycle: the
# banner is one of the redundant, non-optional signals that these maps are not
# a classification.
CYCLE_BANNER = "SIMULATED UC1 OUTPUT cycle {cycle}: arithmetic stand-in, not a classifier."


def mapMessages(
    maps: contract.Uc1Maps,
) -> Iterator[tuple[numpy.ndarray, str, dict[str, str]]]:
    """Yield each map, device name and complete simulated wire metadata."""
    for mapName in contract.UC1_MAP_FIELD_NAMES:
        image = getattr(maps, mapName)
        metadata = contract.resultMapMetadata(
            mapName,
            contract.DATA_ORIGIN_SIMULATED,
            simulationDetail=SIMULATION_DETAIL,
        )
        yield image, metadata[contract.METADATA_DEVICE_NAME_KEY], metadata


def sendMaps(server: igtl_transport.ImageStreamServer, maps: contract.Uc1Maps) -> bool:
    """Send all five maps, validating the complete collection before each send."""
    uc1_maps.validateMaps(maps)
    for image, deviceName, metadata in mapMessages(maps):
        # Keep this immediately before every send. A future producer may mutate
        # one map while preparing another message; no invalid map may cross the
        # wire merely because an earlier map was valid.
        uc1_maps.validateMaps(maps)
        if not server.sendImage(image, deviceName, metadata):
            return False
    return True


def sendSimulationNotice(server: igtl_transport.ImageStreamServer) -> bool:
    """Send the optional human-readable provenance notice when connected."""
    return server.sendString(SIMULATION_NOTICE, SIMULATION_NOTICE_DEVICE_NAME)


def streamMaps(
    dataset: contract.DatasetRef,
    classifier: contract.Classifier,
    port: int = DEFAULT_PORT,
    cycles: int = 0,
    intervalSec: float = DEFAULT_INTERVAL_SEC,
    sendNotice: bool = False,
) -> int:
    """Serve the five maps until interrupted, or until ``cycles`` succeed."""
    if cycles < 0:
        raise ValueError(f"cycles must not be negative, not {cycles}.")
    if intervalSec < 0.0:
        raise ValueError(f"intervalSec must not be negative, not {intervalSec}.")

    maps = classifier.classify(dataset)
    uc1_maps.validateMaps(maps)
    completedCycles = 0
    noticeSent = False

    with (
        igtl_transport.ImageStreamServer(port=port) as server,
        igtl_transport.InterruptFlag() as interrupt,
    ):
        print(
            f"UC1 stand-in server listening on 127.0.0.1:{port}. "
            "Waiting for an OpenIGTLink client. Press Ctrl-C to stop."
        )
        while not interrupt.requested and (cycles == 0 or completedCycles < cycles):
            if server.isConnected:
                if sendNotice and not noticeSent:
                    noticeSent = sendSimulationNotice(server)
                if sendMaps(server, maps):
                    completedCycles += 1
                    print(CYCLE_BANNER.format(cycle=completedCycles))
            if cycles == 0 or completedCycles < cycles:
                time.sleep(intervalSec)

    print(f"UC1 stand-in stopped after {completedCycles} complete map cycle(s).")
    return completedCycles


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
        prog="python -m stratum_sim uc1",
        description=(
            "Send five synthetic UC1 maps over OpenIGTLink. This is an arithmetic "
            "stand-in, not a classifier."
        ),
    )
    parser.add_argument(
        "datasetFolder",
        type=Path,
        help="Folder containing the ENVI dataset written by the acquisition stand-in.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--cycles",
        type=_nonNegativeInteger,
        default=0,
        help="Complete this many five-map sends; 0 streams until Ctrl-C.",
    )
    parser.add_argument(
        "--interval",
        dest="intervalSec",
        type=_nonNegativeFloat,
        default=DEFAULT_INTERVAL_SEC,
        help="Seconds between map cycles.",
    )
    parser.add_argument(
        "--force-unmarked",
        dest="forceUnmarked",
        action="store_true",
        help="Allow an explicitly approved synthetic dataset without the marker.",
    )
    parser.add_argument(
        "--send-notice",
        dest="sendNotice",
        action="store_true",
        help="Also send a UC1_SIM_NOTICE STRING message when a client connects.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = buildArgumentParser().parse_args(argv)
    try:
        dataset = contract.loadDataset(arguments.datasetFolder)
        if arguments.forceUnmarked:
            print(
                "WARNING: --force-unmarked is enabled. Use only with an explicitly "
                "approved synthetic test dataset; output remains simulated and non-clinical."
            )
        classifier = uc1_maps.ArithmeticClassifier(
            requireSimulatedMarker=not arguments.forceUnmarked
        )
        streamMaps(
            dataset,
            classifier,
            port=arguments.port,
            cycles=arguments.cycles,
            intervalSec=arguments.intervalSec,
            sendNotice=arguments.sendNotice,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "CYCLE_BANNER",
    "DEFAULT_PORT",
    "SIMULATION_DETAIL",
    "SIMULATION_NOTICE",
    "SIMULATION_NOTICE_DEVICE_NAME",
    "buildArgumentParser",
    "main",
    "mapMessages",
    "sendMaps",
    "sendSimulationNotice",
    "streamMaps",
]


if __name__ == "__main__":
    raise SystemExit(main())
