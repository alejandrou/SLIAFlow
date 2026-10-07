"""Tests for the stand-in for IUMA's acquisition app (SLIA-035, SLIA-036).

Every cube here is a test fixture: a few float32 or uint16 values in a
temporary folder that stand for no imagery. The messages are read off a raw
socket rather than through `pyigtl.OpenIGTLinkClient`, which keeps only the
latest message per device name and would hide exactly the dropped or doubled
bands these tests look for. HsCube messages are described by the recorder's
parser: pyigtl refuses to unpack a sub-volume, which is how the app sends a band.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy
import pyigtl

from stratum_sim import contract, igtl_recorder, igtl_transport, iuma_app_standin

SIMULATORS_ROOT = Path(__file__).resolve().parents[1]

# The app's device names and port offsets, from
# docs/hardware/acquisition_app_and_hardware.md section 4 (independent of the
# stand-in's own constants, so the two cannot drift together).
APP_DEVICE_NAMES = {0: "LiveView", 1: "Steroscopic", 2: "HsCube"}

FIXTURE_SAMPLES = 4
FIXTURE_LINES = 3
FIXTURE_WAVELENGTHS = (460.0, 465.0, 470.0, 475.0, 480.0)


# ENVI data types: 4 is float32 (IUMA's calibrated cube), 12 is uint16 (its raw
# cube), 2 is int16 (neither).
_ENVI_DTYPES = {4: "<f4", 12: "<u2", 2: "<i2"}


def writeFixtureCube(folder: Path, *, dataType: int = 4, name: str = "cube") -> tuple[Path, numpy.ndarray]:
    """Write a small ENVI BSQ cube and return its header and its (bands, lines, samples) values."""
    bands = len(FIXTURE_WAVELENGTHS)
    counts = numpy.arange(bands * FIXTURE_LINES * FIXTURE_SAMPLES).reshape(
        bands, FIXTURE_LINES, FIXTURE_SAMPLES)
    dtype = numpy.dtype(_ENVI_DTYPES[dataType])
    values = (counts / 100.0).astype(dtype) if dtype.kind == "f" else (counts * 7).astype(dtype)
    header = folder / f"{name}.hdr"
    header.write_text(
        "ENVI\n"
        f"samples = {FIXTURE_SAMPLES}\nlines = {FIXTURE_LINES}\nbands = {bands}\n"
        f"header offset = 0\nfile type = ENVI Standard\ndata type = {dataType}\n"
        "interleave = bsq\nbyte order = 0\n"
        "wavelength = {" + ", ".join(f"{value:g}" for value in FIXTURE_WAVELENGTHS) + "}\n",
        encoding="ascii",
    )
    values.tofile(folder / f"{name}.dat")
    return header, values


def freeBasePort() -> int:
    """A port P such that P, P + 1 and P + 2 are free at this moment."""
    for _attempt in range(50):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            base = probe.getsockname()[1]
        if base + 2 > 65535:
            continue
        held = []
        try:
            for offset in range(3):
                candidate = socket.socket()
                held.append(candidate)
                candidate.bind(("127.0.0.1", base + offset))
        except OSError:
            continue
        finally:
            for candidate in held:
                candidate.close()
        return base
    raise AssertionError("No three consecutive free local ports were found.")


def receiveMessages(port: int, count: int, timeoutSec: float = 10.0) -> list:
    """Read `count` whole messages off the port, in arrival order."""
    deadline = time.monotonic() + timeoutSec
    messages = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeoutSec) as stream:
        stream.settimeout(0.5)

        def receiveExactly(size: int) -> bytes:
            data = b""
            while len(data) < size:
                if time.monotonic() > deadline:
                    raise AssertionError(
                        f"Timed out on port {port} after {len(messages)} of {count} messages.")
                try:
                    chunk = stream.recv(size - len(data))
                except socket.timeout:
                    continue
                if not chunk:
                    raise AssertionError(f"Port {port} closed after {len(messages)} messages.")
                data += chunk
            return data

        while len(messages) < count:
            headerFields = pyigtl.MessageBase.parse_header(
                receiveExactly(pyigtl.MessageBase.IGTL_HEADER_SIZE))
            body = receiveExactly(headerFields["body_size"])
            message = pyigtl.MessageBase.create_message(headerFields["message_type"])
            message.unpack(headerFields, body)
            messages.append(message)
    return messages


def receiveRecords(port: int, count: int, timeoutSec: float = 10.0) -> list:
    """Read `count` whole messages off the port and describe each with the recorder.

    Returns (record, pixels) pairs in arrival order.
    """
    deadline = time.monotonic() + timeoutSec
    records = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeoutSec) as stream:
        stream.settimeout(0.5)

        def receiveExactly(size: int) -> bytes:
            data = bytearray()
            while len(data) < size:
                if time.monotonic() > deadline:
                    raise AssertionError(
                        f"Timed out on port {port} after {len(records)} of {count} messages.")
                try:
                    chunk = stream.recv(size - len(data))
                except socket.timeout:
                    continue
                if not chunk:
                    raise AssertionError(f"Port {port} closed after {len(records)} messages.")
                data += chunk
            return bytes(data)

        while len(records) < count:
            header = igtl_recorder.parseHeader(receiveExactly(igtl_recorder.HEADER_SIZE))
            records.append(igtl_recorder.describeMessage(header, receiveExactly(header["bodySize"])))
    return records


class CubeReaderTest(unittest.TestCase):

    def test_readsAFloat32BsqCubeAsStored(self):
        with tempfile.TemporaryDirectory() as folder:
            header, values = writeFixtureCube(Path(folder))
            cube = iuma_app_standin.readCube(header)
            self.assertEqual(cube.bands.shape, values.shape)
            numpy.testing.assert_array_equal(numpy.asarray(cube.bands), values)
            self.assertEqual(cube.wavelengths, FIXTURE_WAVELENGTHS)
            self.assertEqual(cube.name, Path(folder).name)

    def test_readsAUint16BsqCubeAsStored(self):
        """The app's raw cube is uint16 (acquisition_app_and_hardware.md 4.1)."""
        with tempfile.TemporaryDirectory() as folder:
            header, values = writeFixtureCube(Path(folder), dataType=12)
            cube = iuma_app_standin.readCube(header)
            self.assertEqual(cube.bands.dtype, numpy.dtype("<u2"))
            numpy.testing.assert_array_equal(numpy.asarray(cube.bands), values)

    def test_refusesACubeThatIsNeitherFloat32NorUint16(self):
        with tempfile.TemporaryDirectory() as folder:
            header, _values = writeFixtureCube(Path(folder), dataType=2)
            with self.assertRaises(iuma_app_standin.CubeError) as raised:
                iuma_app_standin.readCube(header)
            self.assertIn("data type", str(raised.exception))

    def test_refusesADataFileOfTheWrongSize(self):
        with tempfile.TemporaryDirectory() as folder:
            header, _values = writeFixtureCube(Path(folder))
            with open(header.with_suffix(".dat"), "ab") as stream:
                stream.write(b"\0\0\0\0")
            with self.assertRaises(iuma_app_standin.CubeError):
                iuma_app_standin.readCube(header)


class BandListTest(unittest.TestCase):

    def test_bandNumbersAndRangesAreParsed(self):
        self.assertEqual(iuma_app_standin.parseBandList("5,17,80-84"),
                         {5, 17, 80, 81, 82, 83, 84})
        self.assertEqual(iuma_app_standin.parseBandList(""), set())

    def test_malformedBandListsAreRefused(self):
        for text in ("0", "5-3", "a", "3,,4", "-2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                iuma_app_standin.parseBandList(text)


class StandInWireTest(unittest.TestCase):
    """What a client of each port receives from a running stand-in."""

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.header, self.values = writeFixtureCube(Path(self._folder.name))
        self.basePort = freeBasePort()
        self.standIn = iuma_app_standin.StandIn(
            iuma_app_standin.readCube(self.header),
            basePort=self.basePort,
            frameRate=20.0,
            bandInterval=0.02,
            cubeInterval=60.0,
            dropBands={3},
        )
        self.standIn.start()

    def tearDown(self):
        self.standIn.stop()
        self._folder.cleanup()

    def test_hsCubeSendsWholeCubeSubVolumes(self):
        """Each band as the app sends it: the whole cube declared, the band at its offset.

        The app's form is measured (acquisition_app_and_hardware.md 4.1). By
        default the stand-in also sends header version 2 with its metadata, so
        that its data stays marked simulated.
        """
        records = receiveRecords(self.basePort + 2, count=4)
        bands = len(FIXTURE_WAVELENGTHS)
        offsets = [record["image"]["subvolumeOffset"][2] for record, _pixels in records]
        self.assertEqual(offsets, [0, 1, 3, 4], "Band 3 was to be left out")
        for (record, pixels), offset in zip(records, offsets, strict=True):
            with self.subTest(band=offset + 1):
                self.assertEqual(record["deviceName"], APP_DEVICE_NAMES[2])
                self.assertTrue(record["crcMatches"])
                self.assertEqual(record["headerVersion"], 2)
                image = record["image"]
                self.assertEqual(image["size"], [FIXTURE_SAMPLES, FIXTURE_LINES, bands])
                self.assertEqual(image["subvolumeOffset"], [0, 0, offset])
                self.assertEqual(image["subvolumeSize"], [FIXTURE_SAMPLES, FIXTURE_LINES, 1])
                self.assertEqual(image["scalarType"], "float32")
                self.assertEqual(image["components"], 1)
                numpy.testing.assert_array_equal(pixels, self.values[offset])
                metadata = record["metadata"]
                self.assertEqual(metadata[contract.METADATA_BAND_NUMBER_KEY], str(offset + 1))
                self.assertEqual(float(metadata[contract.METADATA_WAVELENGTH_KEY]),
                                 FIXTURE_WAVELENGTHS[offset])
                self.assertEqual(metadata[contract.METADATA_DATA_ORIGIN_KEY], "simulated")
                self.assertIn("stand-in", metadata[contract.METADATA_SIMULATION_DETAIL_KEY])

    def test_liveViewAndStereoAreRgbFrames(self):
        for offset, width in ((0, FIXTURE_SAMPLES), (1, 2 * FIXTURE_SAMPLES)):
            with self.subTest(port=self.basePort + offset):
                message = receiveMessages(self.basePort + offset, count=1)[0]
                self.assertEqual(message.device_name, APP_DEVICE_NAMES[offset])
                self.assertIsInstance(message, pyigtl.ImageMessage)
                self.assertEqual(message.image.dtype, numpy.uint8)
                self.assertEqual(message.image.shape, (1, FIXTURE_LINES, width, 3))
                self.assertEqual(message.metadata[contract.METADATA_DATA_ORIGIN_KEY], "simulated")
                self.assertIn("stand-in", message.metadata[contract.METADATA_SIMULATION_DETAIL_KEY])


class StandInAppFormTest(unittest.TestCase):
    """The stand-in sending exactly what the app sends, and the app's raw pixel type."""

    def _sendOneCube(self, *, dataType=4, appHeader=False):
        with tempfile.TemporaryDirectory() as folder:
            header, values = writeFixtureCube(Path(folder), dataType=dataType)
            basePort = freeBasePort()
            standIn = iuma_app_standin.StandIn(
                iuma_app_standin.readCube(header), basePort=basePort, bandInterval=0.0,
                cubeInterval=60.0, appHeader=appHeader)
            standIn.start()
            try:
                records = receiveRecords(basePort + 2, count=len(FIXTURE_WAVELENGTHS))
            finally:
                standIn.stop()
        return records, values

    def test_appHeaderSendsVersion1WithoutMetadata(self):
        records, values = self._sendOneCube(appHeader=True)
        for offset, (record, pixels) in enumerate(records):
            with self.subTest(band=offset + 1):
                self.assertEqual(record["headerVersion"], 1)
                self.assertEqual(record["metadata"], {})
                self.assertEqual(record["timestamp"], 0)
                self.assertTrue(record["crcMatches"])
                self.assertEqual(record["image"]["subvolumeOffset"], [0, 0, offset])
                numpy.testing.assert_array_equal(pixels, values[offset])

    def test_uint16CubeIsSentAsUint16(self):
        records, values = self._sendOneCube(dataType=12, appHeader=True)
        for offset, (record, pixels) in enumerate(records):
            with self.subTest(band=offset + 1):
                self.assertEqual(record["image"]["scalarType"], "uint16")
                self.assertEqual(record["image"]["endianness"], "little")
                numpy.testing.assert_array_equal(pixels, values[offset])

    def test_appHeaderIsOfferedOnTheCommandLine(self):
        arguments = iuma_app_standin._parseArguments(["--app-header"])
        self.assertTrue(arguments.app_header)
        self.assertFalse(iuma_app_standin._parseArguments([]).app_header)


class _FailingSocket:
    def sendall(self, data):
        raise ConnectionResetError("The client left during the write.")


class _AcceptingSocket:
    def __init__(self):
        self.data = b""

    def sendall(self, data):
        self.data += data


class _ClientLeavesDuringTheWrite:
    """A HsCube server whose client leaves while the first band is written.

    pyigtl takes a message off its queue before writing it, so nothing is
    pending afterwards, although nothing was written.
    """

    pendingMessageCount = 0
    writtenMessageCount = 0

    def __init__(self):
        self.isConnected = True

    def sendImageSlab(self, band, **_message):
        self.isConnected = False
        return True


class BandDeliveryTest(unittest.TestCase):
    """A band counts as sent only once it was written to the connection in full."""

    def test_aBandWhoseWriteFailedIsNotReportedAsSent(self):
        with tempfile.TemporaryDirectory() as folder:
            header, _values = writeFixtureCube(Path(folder))
            lines = []
            standIn = iuma_app_standin.StandIn(iuma_app_standin.readCube(header),
                                               bandInterval=0.0, cubeInterval=0.0)

            def report(line):
                lines.append(line)
                if line.startswith("HsCube: sent"):
                    standIn.stop()

            standIn._report = report
            standIn._sendCubes(_ClientLeavesDuringTheWrite())
        self.assertIn(f"HsCube: sent 0 of {len(FIXTURE_WAVELENGTHS)} bands.", lines)


class ImageStreamServerDeliveryTest(unittest.TestCase):
    """What the transport tells a producer about the messages it queued."""

    def setUp(self):
        self.server = igtl_transport.ImageStreamServer(port=freeBasePort())
        self.server.start()
        self.addCleanup(self.server.stop)
        self.pyigtlServer = self.server._server

    def _queue(self):
        message = igtl_transport.buildImageMessage(
            numpy.zeros((1, FIXTURE_LINES, FIXTURE_SAMPLES), dtype=numpy.float32), "HsCube", {})
        self.pyigtlServer.send_message(message, wait=False)

    def test_onlyAWriteThatCompletedCountsAsWritten(self):
        self._queue()
        with self.assertRaises(ConnectionResetError):
            self.pyigtlServer._send_queued_message_from_socket(_FailingSocket())
        # The queue is empty all the same: pyigtl took the message off first.
        self.assertEqual(self.server.pendingMessageCount, 0)
        self.assertEqual(self.server.writtenMessageCount, 0)

        self._queue()
        accepting = _AcceptingSocket()
        self.assertTrue(self.pyigtlServer._send_queued_message_from_socket(accepting))
        self.assertTrue(accepting.data)
        self.assertEqual(self.server.writtenMessageCount, 1)

    def test_messagesQueuedForAClientThatLeftAreNotKeptForTheNext(self):
        self._queue()
        self._queue()
        self.assertEqual(self.server.pendingMessageCount, 2)
        # What pyigtl calls when a read or a write to its client fails.
        self.pyigtlServer._communication_error_occurred()
        self.assertEqual(self.server.pendingMessageCount, 0)


class StandInOutputTest(unittest.TestCase):

    def test_everyLineItPrintsSaysItIsAStandIn(self):
        with tempfile.TemporaryDirectory() as folder:
            header, _values = writeFixtureCube(Path(folder))
            basePort = freeBasePort()
            completed = subprocess.run(
                [sys.executable, "-m", "stratum_sim.iuma_app_standin", "--cube", str(header),
                 "--base-port", str(basePort), "--duration", "1"],
                cwd=SIMULATORS_ROOT, capture_output=True, text=True, timeout=60,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "The stand-in printed nothing")
        for line in lines + [line for line in completed.stderr.splitlines() if line.strip()]:
            with self.subTest(line=line):
                self.assertTrue(line.startswith("[stand-in]"), line)
        banner = " ".join(lines[:3])
        self.assertIn("stand-in for IUMA's acquisition app", banner)
        self.assertIn("not IUMA's app", banner)
        for offset, deviceName in APP_DEVICE_NAMES.items():
            self.assertIn(f"{deviceName} on 127.0.0.1:{basePort + offset}", completed.stdout)


if __name__ == "__main__":
    unittest.main()
