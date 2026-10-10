"""A stand-in for IUMA's acquisition app, for testing SLIAFlow's Connections section.

It is not IUMA's AcquisitionSystemApp and says so in everything it prints and
sends. It serves the app's three OpenIGTLink ports (SLIA-035,
docs/hardware/acquisition_app_and_hardware.md section 4):

- P, `LiveView`: a colour preview of the cube, RGB uint8;
- P + 1, `Steroscopic` (spelled as the app spells it): that preview and one band
  in grey, side by side, RGB uint8;
- P + 2, `HsCube`: the cube band by band while a client is connected, as the
  app sends it (SLIA-036): every IMAGE declares the whole cube and carries one
  band as the sub-volume at offset (0, 0, band - 1).

By default the bands go out at header version 2 with the stand-in's metadata,
so that its data stays marked simulated. `--app-header` sends header version 1,
no metadata and timestamp 0, exactly as the app does. The cube is IUMA's
calibrated float32 cube, or a uint16 cube such as the raw cube the app sends
today.

What it assumes about the real app is listed in tools/simulators/README.md and
was checked against the app in SLIA-030. Run it from tools/simulators:

    ..\\..\\.venv\\Scripts\\python.exe -m stratum_sim.iuma_app_standin

The cube is read, never written. Nothing here imports `slicer`.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy

from . import contract, igtl_transport

STAND_IN_PREFIX = "[stand-in]"

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# The reference cube of ADR-0004 decision 1.
# The capture SLIAFlow starts on (ADR-0006), in the nested folder IUMA delivers.
DEFAULT_CUBE_HEADER = (REPOSITORY_ROOT / "input" / "S-N-002-04" / "S-N-002-04"
                       / "LCTF_Calibrated_Cube_Single.hdr")

DEFAULT_FRAME_RATE = 10.0
DEFAULT_BAND_INTERVAL_SEC = 0.1
DEFAULT_CUBE_INTERVAL_SEC = 30.0

# The colour preview uses the bands nearest these as red, green and blue, as the
# HS Cube panel's own preview does, with reflectance 0 to 1 mapped to 0 to 255.
PREVIEW_WAVELENGTHS_NM = (650.0, 550.0, 470.0)
# The grey half of the stereo frame, standing for the app's mono camera.
MONO_WAVELENGTH_NM = 650.0

# How often a waiting loop looks again.
POLL_SEC = 0.01

# ENVI data types: 4 is float32, IUMA's calibrated cube (ADR-0004 decision 6);
# 12 is uint16, the raw cube the app sends today (acquisition_app_and_hardware.md 4.1).
_ENVI_TYPES = {"4": numpy.dtype("<f4"), "12": numpy.dtype("<u2")}
_DATA_FILE_SUFFIXES = (".dat", ".raw")
_WAVELENGTH_BLOCK = re.compile(r"^\s*wavelength\s*=\s*\{([^}]*)\}", re.IGNORECASE | re.MULTILINE)
_HEADER_LINE = re.compile(r"^\s*([^=]+?)\s*=\s*([^{].*?)\s*$")
_BAND_ITEM = re.compile(r"^(\d+)(?:-(\d+))?$")


class CubeError(ValueError):
    """The header does not describe a cube the stand-in can send."""


@dataclass(frozen=True)
class StandInCube:
    name: str
    headerPath: Path
    # (bands, lines, samples) float32 or uint16, read-only, as stored.
    bands: numpy.ndarray
    wavelengths: tuple

    @property
    def bandCount(self) -> int:
        return self.bands.shape[0]


def readCube(headerPath) -> StandInCube:
    """Read an ENVI float32 or uint16 BSQ little-endian cube with one wavelength per band.

    A deliberately small reader: the stand-in runs outside Slicer, so it cannot
    use SLIAFlow's own, and it needs only the formats of IUMA's calibrated and
    raw cubes.
    """
    headerPath = Path(headerPath)
    if not headerPath.is_file():
        raise CubeError(f"{headerPath} is missing.")
    text = headerPath.read_text(encoding="ascii", errors="replace")
    values = {}
    for line in text.splitlines():
        match = _HEADER_LINE.match(line)
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    try:
        samples, lines, bandCount = (int(values[key]) for key in ("samples", "lines", "bands"))
    except (KeyError, ValueError) as error:
        raise CubeError(f"{headerPath.name} does not declare samples, lines and bands.") from error
    dataType = values.get("data type")
    if dataType not in _ENVI_TYPES:
        raise CubeError(f"{headerPath.name} declares data type {dataType}, not 4 (float32) "
                        "or 12 (uint16).")
    dtype = _ENVI_TYPES[dataType]
    for key, expected in (("interleave", "bsq"), ("byte order", "0"), ("header offset", "0")):
        found = values.get(key, "0" if key == "header offset" else None)
        if found is None or found.lower() != expected:
            raise CubeError(f"{headerPath.name} declares {key} {found}, not {expected}.")
    block = _WAVELENGTH_BLOCK.search(text)
    try:
        wavelengths = tuple(float(entry) for entry in block.group(1).split(",")) if block else ()
    except ValueError as error:
        raise CubeError(f"{headerPath.name} lists a wavelength that is not a number.") from error
    if len(wavelengths) != bandCount:
        raise CubeError(f"{headerPath.name} lists {len(wavelengths)} wavelengths for "
                        f"{bandCount} bands.")
    dataPath = next((headerPath.with_suffix(suffix) for suffix in _DATA_FILE_SUFFIXES
                     if headerPath.with_suffix(suffix).is_file()), None)
    if dataPath is None:
        raise CubeError(f"{headerPath.name} has no .dat or .raw file beside it.")
    expectedBytes = samples * lines * bandCount * dtype.itemsize
    if dataPath.stat().st_size != expectedBytes:
        raise CubeError(f"{dataPath.name} is {dataPath.stat().st_size} bytes but "
                        f"{headerPath.name} describes {expectedBytes}.")
    # Read whole rather than mapped: a mapped file cannot be deleted on Windows
    # while the mapping lives, and a calibrated capture is over half a gigabyte.
    bands = numpy.fromfile(dataPath, dtype=dtype).reshape(bandCount, lines, samples)
    bands.flags.writeable = False
    return StandInCube(headerPath.parent.name, headerPath.resolve(), bands, wavelengths)


def parseBandList(text: str) -> set[int]:
    """Parse band numbers from 1, with ranges: `5,17,80-84`."""
    bands: set[int] = set()
    if not text.strip():
        return bands
    for item in text.split(","):
        match = _BAND_ITEM.match(item.strip())
        if match is None:
            raise ValueError(f"{item!r} is not a band number or a range such as 80-84.")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last < first:
            raise ValueError(f"{item!r} is not a range of band numbers from 1.")
        bands.update(range(first, last + 1))
    return bands


def formatBandList(bands) -> str:
    """Band numbers with runs as ranges: `5, 17, 80-84`."""
    ordered = sorted(bands)
    runs = []
    for band in ordered:
        if runs and band == runs[-1][1] + 1:
            runs[-1][1] = band
        else:
            runs.append([band, band])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in runs)


def nearestBand(wavelengths, nanometres: float) -> int:
    return min(range(len(wavelengths)), key=lambda index: (abs(wavelengths[index] - nanometres),
                                                          index))


def _fullScale(cube: StandInCube) -> float:
    """Reflectance 1 for a calibrated cube; the brightest count for a raw one."""
    if cube.bands.dtype.kind == "f":
        return 1.0
    return float(max(int(cube.bands.max()), 1))


def _toUint8(values: numpy.ndarray, fullScale: float = 1.0) -> numpy.ndarray:
    scaled = numpy.nan_to_num(values.astype(numpy.float32)) / fullScale
    return (numpy.clip(scaled, 0.0, 1.0) * 255.0 + 0.5).astype(numpy.uint8)


def colourPreview(cube: StandInCube) -> numpy.ndarray:
    """(lines, samples, 3) RGB uint8 from the bands nearest 650, 550 and 470 nm."""
    fullScale = _fullScale(cube)
    channels = [_toUint8(cube.bands[nearestBand(cube.wavelengths, nm)], fullScale)
                for nm in PREVIEW_WAVELENGTHS_NM]
    return numpy.ascontiguousarray(numpy.stack(channels, axis=-1))


def stereoFrame(cube: StandInCube) -> numpy.ndarray:
    """The colour preview on the left and the 650 nm band in grey on the right."""
    mono = _toUint8(cube.bands[nearestBand(cube.wavelengths, MONO_WAVELENGTH_NM)],
                    _fullScale(cube))
    return numpy.ascontiguousarray(numpy.concatenate(
        [colourPreview(cube), numpy.repeat(mono[..., numpy.newaxis], 3, axis=-1)], axis=1))


def simulationDetail(cube: StandInCube) -> str:
    calibration = ("calibrated by IUMA" if cube.bands.dtype.kind == "f"
                   else "raw and uncalibrated")
    return (f"stand-in for IUMA's acquisition app, recorded IUMA LCTF capture {cube.name}, "
            f"{calibration} (simulated acquisition)")


class StandIn:
    """Three servers, one per port of the app, each fed by its own thread."""

    def __init__(self, cube: StandInCube, *, basePort: int = contract.APP_BASE_PORT,
                 frameRate: float = DEFAULT_FRAME_RATE,
                 bandInterval: float = DEFAULT_BAND_INTERVAL_SEC,
                 cubeInterval: float = DEFAULT_CUBE_INTERVAL_SEC,
                 dropBands=(), appHeader: bool = False, report=None) -> None:
        if frameRate <= 0:
            raise ValueError("The frame rate must be positive.")
        if bandInterval < 0 or cubeInterval < 0:
            raise ValueError("Intervals cannot be negative.")
        self.cube = cube
        self.basePort = basePort
        self.frameInterval = 1.0 / frameRate
        self.bandInterval = bandInterval
        self.cubeInterval = cubeInterval
        self.dropBands = frozenset(dropBands)
        # Header version 1, no metadata and timestamp 0, as the app sends.
        self.appHeader = appHeader
        self._report = report or (lambda line: None)
        self._detail = simulationDetail(cube)
        self._stopRequested = threading.Event()
        self._servers: list[igtl_transport.ImageStreamServer] = []
        self._threads: list[threading.Thread] = []

    def portOf(self, deviceName: str) -> int:
        return self.basePort + contract.APP_DEVICE_NAMES.index(deviceName)

    def start(self) -> None:
        preview = colourPreview(self.cube)
        feeds = (
            (contract.LIVE_VIEW_DEVICE_NAME, lambda server: self._sendFrames(
                server, contract.LIVE_VIEW_DEVICE_NAME, preview)),
            (contract.STEREO_DEVICE_NAME, lambda server: self._sendFrames(
                server, contract.STEREO_DEVICE_NAME, stereoFrame(self.cube))),
            (contract.HS_CUBE_DEVICE_NAME, self._sendCubes),
        )
        try:
            for deviceName, feed in feeds:
                server = igtl_transport.ImageStreamServer(port=self.portOf(deviceName))
                server.start()
                self._servers.append(server)
                thread = threading.Thread(target=feed, args=(server,), name=deviceName,
                                          daemon=True)
                self._threads.append(thread)
                self._report(f"{deviceName} on 127.0.0.1:{server.port}")
        except Exception:
            self.stop()
            raise
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stopRequested.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
        for server in self._servers:
            server.stop()
        self._threads.clear()
        self._servers.clear()

    def _waitUntilWritten(self, server, writtenBefore: int) -> bool:
        """Wait until the message queued last was written in full; False if the client left.

        Written means handed to the connection whole. Whether the client then
        read it, TCP does not tell a sender.
        """
        while server.writtenMessageCount <= writtenBefore:
            if self._stopRequested.is_set() or not server.isConnected:
                return False
            time.sleep(POLL_SEC)
        return True

    def _sendFrames(self, server, deviceName: str, frame: numpy.ndarray) -> None:
        image = frame[numpy.newaxis, ...]
        metadata = contract.liveViewMetadata(self._detail, deviceName=deviceName)
        # Frames are due on a fixed clock, so the time a send takes does not
        # lower the rate; a frame still queued is not piled on but skipped.
        due = time.monotonic()
        while True:
            due = max(due + self.frameInterval, time.monotonic() - self.frameInterval)
            if self._stopRequested.wait(max(0.0, due - time.monotonic())):
                return
            if server.isConnected and not server.pendingMessageCount:
                server.sendImage(image, deviceName, metadata)

    def _waitForClient(self, server) -> bool:
        while not server.isConnected:
            if self._stopRequested.wait(POLL_SEC):
                return False
        return True

    def _sendCubes(self, server) -> None:
        cube = self.cube
        while self._waitForClient(server):
            self._report(f"HsCube: a client connected; sending cube {cube.name}, "
                         f"{cube.bandCount} bands.")
            sent = []
            for index in range(cube.bandCount):
                bandNumber = index + 1
                if self._stopRequested.is_set() or not server.isConnected:
                    break
                if bandNumber in self.dropBands:
                    continue
                if self.appHeader:
                    form = {"metadata": {}, "headerVersion": 1, "timestamp": 0.0}
                else:
                    form = {"metadata": contract.hsCubeBandMetadata(
                        self._detail, bandNumber, cube.wavelengths[index])}
                writtenBefore = server.writtenMessageCount
                if not (server.sendImageSlab(
                            numpy.ascontiguousarray(cube.bands[index]),
                            bandCount=cube.bandCount, bandIndex=index,
                            deviceName=contract.HS_CUBE_DEVICE_NAME, **form)
                        and self._waitUntilWritten(server, writtenBefore)):
                    break
                sent.append(bandNumber)
                if self._stopRequested.wait(self.bandInterval):
                    break
            line = f"HsCube: sent {len(sent)} of {cube.bandCount} bands"
            if self.dropBands:
                line += f"; left out {formatBandList(self.dropBands)} on purpose"
            self._report(line + ".")
            # The next cube follows after the interval, or as soon as a new
            # client replaces one that left.
            deadline = time.monotonic() + self.cubeInterval
            while server.isConnected and time.monotonic() < deadline:
                if self._stopRequested.wait(POLL_SEC):
                    return


class _PrefixedLines:
    """A text stream that starts every line it writes with the stand-in label."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._atLineStart = True
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            for piece in text.splitlines(keepends=True):
                if self._atLineStart and piece.strip():
                    self._stream.write(f"{STAND_IN_PREFIX} ")
                self._stream.write(piece)
                self._atLineStart = piece.endswith("\n")
            self._stream.flush()
        return len(text)

    def flush(self) -> None:
        self._stream.flush()


def _parseArguments(argv):
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim.iuma_app_standin",
        description="A stand-in for IUMA's acquisition app: serves its three OpenIGTLink ports "
                    "with a recorded cube. It is not IUMA's app.")
    parser.add_argument("--cube", type=Path, default=DEFAULT_CUBE_HEADER,
                        help="ENVI header of a float32 or uint16 BSQ cube (default: "
                             "S-N-002-04's calibrated cube)")
    parser.add_argument("--base-port", type=int, default=contract.APP_BASE_PORT,
                        help="LiveView port P; Steroscopic is P + 1 and HsCube P + 2")
    parser.add_argument("--frame-rate", type=float, default=DEFAULT_FRAME_RATE,
                        help="LiveView and Steroscopic frames per second")
    parser.add_argument("--band-interval", type=float, default=DEFAULT_BAND_INTERVAL_SEC,
                        help="seconds between two HsCube bands")
    parser.add_argument("--cube-interval", type=float, default=DEFAULT_CUBE_INTERVAL_SEC,
                        help="seconds between two cubes to a connected client")
    parser.add_argument("--drop-bands", default="",
                        help="band numbers from 1 to leave out, for example 5,17,80-84")
    parser.add_argument("--app-header", action="store_true",
                        help="send HsCube bands at header version 1 without metadata and with "
                             "timestamp 0, as IUMA's app does; the data is then not marked "
                             "simulated on the wire")
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after this many seconds (default: until Ctrl+C)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    # stderr too: pyigtl prints a traceback there when a client leaves.
    sys.stdout = _PrefixedLines(sys.stdout)
    sys.stderr = _PrefixedLines(sys.stderr)
    logging.basicConfig(stream=sys.stdout, level=logging.WARNING, format="%(message)s")
    arguments = _parseArguments(argv)
    try:
        dropBands = parseBandList(arguments.drop_bands)
        cube = readCube(arguments.cube)
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}")
        return 2
    outside = sorted(band for band in dropBands if band > cube.bandCount)
    if outside:
        print(f"ERROR: the cube has {cube.bandCount} bands; there is no band "
              f"{formatBandList(outside)}.")
        return 2

    print("This is a stand-in for IUMA's acquisition app, not IUMA's app.")
    print(f"It sends recorded cube {cube.name} ({cube.bands.shape[2]} x {cube.bands.shape[1]}, "
          f"{cube.bandCount} bands, {cube.bands.dtype.name}), marked as a simulated "
          "acquisition.")
    if arguments.app_header:
        print("HsCube goes out as the app sends it, without metadata, so SLIAFlow cannot tell "
              "it from the app.")
    standIn = StandIn(cube, basePort=arguments.base_port, frameRate=arguments.frame_rate,
                      bandInterval=arguments.band_interval,
                      cubeInterval=arguments.cube_interval, dropBands=dropBands,
                      appHeader=arguments.app_header, report=print)
    try:
        standIn.start()
    except igtl_transport.PortRefusedError as refusal:
        print(f"ERROR: {refusal}")
        return 1
    if dropBands:
        print(f"Bands left out of every cube: {formatBandList(dropBands)}.")
    print("ready. Press Ctrl+C to stop.")
    # After the servers exist: pyigtl installs its own signal handlers.
    with igtl_transport.InterruptFlag() as interrupt:
        deadline = None if arguments.duration is None else time.monotonic() + arguments.duration
        while not interrupt.requested and (deadline is None or time.monotonic() < deadline):
            time.sleep(0.1)
    standIn.stop()
    print("stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
