"""Tests for the OpenIGTLink protocol recorder (SLIA-030).

Reference messages are packed by pyigtl, an implementation independent of the
recorder's own parser. Every cube here is a test fixture: a few values in a
temporary folder that stand for no imagery.
"""

from __future__ import annotations

import json
import select
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy
import pyigtl
from pyigtl.messages import CRC64

from stratum_sim import contract, igtl_recorder, iuma_app_standin

from .test_iuma_app_standin import FIXTURE_WAVELENGTHS, freeBasePort, writeFixtureCube

WAIT_SEC = 10.0


def packedImage(image, *, deviceName="HsCube", headerVersion=1, metadata=None,
                matrix=None, coordinateSystem="lps") -> bytes:
    message = pyigtl.ImageMessage(image=image, device_name=deviceName,
                                  ijk_to_world_matrix=numpy.eye(4) if matrix is None else matrix,
                                  world_coordinate_system=coordinateSystem, timestamp=1700000000.25)
    message.header_version = headerVersion
    message.metadata = dict(metadata or {})
    return message.pack()


def rawMessage(messageType: str, content: bytes, *, deviceName="HsCube") -> bytes:
    """A header version 1 message of any type, packed by hand."""
    header = struct.pack("> H 12s 20s I I Q Q", 1, messageType.encode("ascii"),
                         deviceName.encode("ascii"), 0, 0, len(content), CRC64(content))
    return header + content


def splitMessage(packed: bytes):
    header = igtl_recorder.parseHeader(packed[:igtl_recorder.HEADER_SIZE])
    return header, packed[igtl_recorder.HEADER_SIZE:]


def waitFor(condition, timeoutSec: float = WAIT_SEC) -> bool:
    deadline = time.monotonic() + timeoutSec
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class _RawServer:
    """A one-client TCP server that sends given bytes and records what it receives."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.received = bytearray()
        self.connected = threading.Event()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", port))
        self._listener.listen(1)
        self._client = None
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        try:
            self._client, _address = self._listener.accept()
        except OSError:
            return
        self.connected.set()

    def send(self, data: bytes) -> None:
        self._client.sendall(data)

    def drain(self, seconds: float) -> None:
        """Collect anything the client sends for `seconds`."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _w, _x = select.select([self._client], [], [], 0.05)
            if ready:
                chunk = self._client.recv(65536)
                if not chunk:
                    return
                self.received.extend(chunk)

    def close(self) -> None:
        for sock in (self._client, self._listener):
            if sock is not None:
                sock.close()


class RecorderParsingTest(unittest.TestCase):

    def test_headerVersion1ImageIsDescribed(self):
        image = numpy.arange(12, dtype=numpy.uint16).reshape(1, 3, 4)
        header, body = splitMessage(packedImage(image))
        record, pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["headerVersion"], 1)
        self.assertEqual(record["messageType"], "IMAGE")
        self.assertEqual(record["deviceName"], "HsCube")
        self.assertAlmostEqual(record["timestamp"], 1700000000.25, places=3)
        self.assertEqual(record["bodySize"], len(body))
        self.assertTrue(record["crcMatches"])
        self.assertEqual(record["metadata"], {})
        image_ = record["image"]
        self.assertEqual(image_["components"], 1)
        self.assertEqual(image_["scalarType"], "uint16")
        self.assertEqual(image_["endianness"], "little")
        self.assertEqual(image_["size"], [4, 3, 1])
        self.assertEqual((image_["minimum"], image_["maximum"]), (0, 11))
        self.assertAlmostEqual(image_["mean"], 5.5)
        self.assertEqual(pixels.shape, (3, 4))

    def test_headerVersion2MetadataIsRecorded(self):
        image = numpy.zeros((1, 2, 2), dtype=numpy.float32)
        metadata = {"SLIAFlow.BandNumber": "7", "Wavelength": "490"}
        header, body = splitMessage(packedImage(image, headerVersion=2, metadata=metadata))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["headerVersion"], 2)
        self.assertEqual(record["metadata"], metadata)
        self.assertEqual(record["image"]["scalarType"], "float32")
        self.assertEqual(record["extendedHeader"]["metadataCount"], 2)
        self.assertTrue(record["crcMatches"])

    def test_imageGeometryIsRecorded(self):
        matrix = numpy.array([[0, -2.0, 0, 10.0],
                              [0.5, 0, 0, 20.0],
                              [0, 0, 3.0, 30.0],
                              [0, 0, 0, 1]])
        image = numpy.zeros((1, 3, 5, 3), dtype=numpy.uint8)
        header, body = splitMessage(packedImage(image, matrix=matrix, coordinateSystem="ras",
                                                deviceName="LiveView"))
        record, pixels = igtl_recorder.describeMessage(header, body)
        image_ = record["image"]
        self.assertEqual(image_["components"], 3)
        self.assertEqual(image_["coordinateSystem"], "RAS")
        self.assertEqual(image_["size"], [5, 3, 1])
        numpy.testing.assert_allclose(image_["spacing"], [0.5, 2.0, 3.0], atol=1e-6)
        numpy.testing.assert_allclose(image_["origin"], [10.0, 20.0, 30.0], atol=1e-4)
        numpy.testing.assert_allclose(image_["direction"],
                                      [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-6)
        self.assertEqual(image_["subvolumeOffset"], [0, 0, 0])
        self.assertEqual(image_["subvolumeSize"], [5, 3, 1])
        self.assertIsNone(pixels, "Only single-component images are compared with a cube")

    def test_appSlabGeometryIsRecorded(self):
        """IUMA's app's form: the whole cube's size, one band as the sub-volume, timestamp 0.

        Packed by hand from the IMAGE layout in the OpenIGTLink specification,
        as the app sends it (docs/hardware/acquisition_app_and_hardware.md 4.1):
        header version 1, uint16 little endian, identity directions, LPS, the
        centre of the whole cube, band 3 of 5 at offset (0, 0, 2).
        """
        samples, lines, bands, offset = 4, 3, 5, 2
        band = numpy.arange(samples * lines, dtype="<u2").reshape(lines, samples) + 100
        centre = ((samples - 1) / 2.0, (lines - 1) / 2.0, (bands - 1) / 2.0)
        content = struct.pack("> H B B B B 3H 12f 3H 3H", 1, 1, 5, 2, 2,
                              samples, lines, bands,
                              1, 0, 0, 0, 1, 0, 0, 0, 1, *centre,
                              0, 0, offset, samples, lines, 1) + band.tobytes()
        header, body = splitMessage(rawMessage("IMAGE", content))
        record, pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["headerVersion"], 1)
        self.assertEqual(record["timestamp"], 0)
        self.assertTrue(record["crcMatches"])
        self.assertEqual(record["metadata"], {})
        image_ = record["image"]
        self.assertEqual(image_["size"], [samples, lines, bands])
        self.assertEqual(image_["subvolumeOffset"], [0, 0, offset])
        self.assertEqual(image_["subvolumeSize"], [samples, lines, 1])
        self.assertEqual(image_["scalarType"], "uint16")
        self.assertEqual(image_["coordinateSystem"], "LPS")
        numpy.testing.assert_allclose(image_["spacing"], [1.0, 1.0, 1.0])
        numpy.testing.assert_allclose(image_["origin"], [0.0, 0.0, 0.0], atol=1e-4)
        numpy.testing.assert_array_equal(pixels, band)

    def test_badCrcIsMarked(self):
        image = numpy.arange(4, dtype=numpy.uint16).reshape(1, 2, 2)
        packed = bytearray(packedImage(image))
        packed[-1] ^= 0xFF
        header, body = splitMessage(bytes(packed))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertFalse(record["crcMatches"])

    def test_nonImageMessageIsLoggedByTypeAndSize(self):
        message = pyigtl.StringMessage("end of cube", device_name="HsCube")
        header, body = splitMessage(message.pack())
        record, pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["messageType"], "STRING")
        self.assertEqual(record["bodySize"], len(body))
        self.assertTrue(record["crcMatches"])
        self.assertNotIn("image", record)
        self.assertIsNone(pixels)

    def test_stringMessageTextIsRecorded(self):
        message = pyigtl.StringMessage("end of cube", device_name="HsCube")
        header, body = splitMessage(message.pack())
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["text"], "end of cube")

    def test_statusMessageIsRecorded(self):
        content = struct.pack("> H q 20s", 1, 7, b"Capture") + b"transmission ended\0"
        header, body = splitMessage(rawMessage("STATUS", content))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["status"], {"code": 1, "subcode": 7, "errorName": "Capture"})
        self.assertEqual(record["text"], "transmission ended")

    def test_otherMessageContentIsPreviewed(self):
        content = bytes(range(100))
        header, body = splitMessage(rawMessage("CAPABILITY", content))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual(record["contentHead"], content[:igtl_recorder.CONTENT_HEAD_BYTES].hex())
        self.assertLess(igtl_recorder.CONTENT_HEAD_BYTES, len(content))

    def test_nonFiniteFloatsGiveStrictJson(self):
        image = numpy.array([[[1.0, numpy.nan], [numpy.inf, -2.0]]], dtype=numpy.float32)
        header, body = splitMessage(packedImage(image))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertEqual((record["image"]["minimum"], record["image"]["maximum"]), (-2.0, 1.0))
        self.assertAlmostEqual(record["image"]["mean"], -0.5)
        self.assertEqual(record["image"]["nonFiniteCount"], 2)
        json.loads(igtl_recorder.jsonLine(record), parse_constant=self.fail)

    def test_allNonFiniteBandGivesNoStatistics(self):
        image = numpy.full((1, 2, 2), numpy.nan, dtype=numpy.float32)
        header, body = splitMessage(packedImage(image))
        record, _pixels = igtl_recorder.describeMessage(header, body)
        self.assertIsNone(record["image"]["minimum"])
        self.assertEqual(record["image"]["nonFiniteCount"], 4)
        json.loads(igtl_recorder.jsonLine(record), parse_constant=self.fail)


class RecorderCompareCubeTest(unittest.TestCase):

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.folder = Path(self._folder.name)

    def tearDown(self):
        self._folder.cleanup()

    def test_eachBandIsMatchedInOrder(self):
        header, values = writeFixtureCube(self.folder)
        comparison = igtl_recorder.CubeComparison(header)
        for index in range(values.shape[0]):
            self.assertEqual(comparison.match(values[index]),
                             {"band": index + 1, "orientation": "as stored"})

    def test_flippedBandIsMatchedAsFlipped(self):
        header, values = writeFixtureCube(self.folder)
        comparison = igtl_recorder.CubeComparison(header)
        self.assertEqual(comparison.match(values[2][::-1, :]),
                         {"band": 3, "orientation": "flipped top to bottom"})
        self.assertEqual(comparison.match(values[1][:, ::-1]),
                         {"band": 2, "orientation": "flipped left to right"})
        self.assertEqual(comparison.match(values[0][::-1, ::-1]),
                         {"band": 1, "orientation": "rotated 180 degrees"})

    def test_unknownBandMatchesNothing(self):
        header, values = writeFixtureCube(self.folder)
        comparison = igtl_recorder.CubeComparison(header)
        self.assertIsNone(comparison.match(values[0] + 1000.0))
        self.assertIsNone(comparison.match(numpy.zeros((2, 2), dtype=numpy.float32)))

    def test_uint16CubeIsCompared(self):
        header, values = writeFixtureCube(self.folder, dataType=12, name="raw")
        raw = (values * 100).astype("<u2")
        raw.tofile(self.folder / "raw.dat")
        comparison = igtl_recorder.CubeComparison(header)
        self.assertEqual(comparison.match(raw[4]), {"band": 5, "orientation": "as stored"})
        # A float32 message is not the same data as a uint16 band.
        self.assertIsNone(comparison.match(raw[4].astype(numpy.float32)))


class RecorderStandInTest(unittest.TestCase):

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.folder = Path(self._folder.name)
        self.out = self.folder / "recording"
        self.basePort = freeBasePort()
        self.ports = [self.basePort, self.basePort + 1, self.basePort + 2]
        self.recorder = None
        self.standIn = None

    def tearDown(self):
        if self.recorder is not None:
            self.recorder.stop()
        if self.standIn is not None:
            self.standIn.stop()
        self._folder.cleanup()

    def _startStandIn(self, dropBands=()):
        header, values = writeFixtureCube(self.folder)
        cube = iuma_app_standin.readCube(header)
        self.standIn = iuma_app_standin.StandIn(
            cube, basePort=self.basePort, frameRate=20.0, bandInterval=0.01,
            cubeInterval=3600.0, dropBands=set(dropBands), report=lambda _line: None)
        self.standIn.start()
        return header, values

    def _startRecorder(self, compareCube=None):
        comparison = None if compareCube is None else igtl_recorder.CubeComparison(compareCube)
        self.recorder = igtl_recorder.Recorder("127.0.0.1", self.ports, self.out,
                                               comparison=comparison, report=lambda _line: None)
        self.recorder.start()

    def _records(self, port=None, deviceName=None):
        return [record for record in self.recorder.records
                if (port is None or record["port"] == port)
                and (deviceName is None or record["deviceName"] == deviceName)]

    def test_recordsEveryBandAndFrameOfTheStandIn(self):
        header, values = self._startStandIn()
        self._startRecorder(compareCube=header)
        bandCount = len(FIXTURE_WAVELENGTHS)
        cubePort = self.basePort + 2
        self.assertTrue(waitFor(lambda: len(self._records(cubePort)) >= bandCount
                                and len(self._records(self.basePort)) >= 3
                                and len(self._records(self.basePort + 1)) >= 3),
                        "The recorder did not receive the stand-in's messages")
        bands = self._records(cubePort)[:bandCount]
        for number, record in enumerate(bands, start=1):
            self.assertEqual(record["deviceName"], contract.HS_CUBE_DEVICE_NAME)
            self.assertEqual(record["headerVersion"], 2)
            self.assertTrue(record["crcMatches"])
            self.assertEqual(record["image"]["scalarType"], "float32")
            # The app's form (SLIA-036): the whole cube, this band as its sub-volume.
            self.assertEqual(record["image"]["size"], [values.shape[2], values.shape[1], bandCount])
            self.assertEqual(record["image"]["subvolumeOffset"], [0, 0, number - 1])
            self.assertEqual(record["metadata"][contract.METADATA_BAND_NUMBER_KEY], str(number))
            self.assertEqual(record["cubeMatch"], {"band": number, "orientation": "as stored"})
        for port, deviceName in ((self.basePort, "LiveView"), (self.basePort + 1, "Steroscopic")):
            frame = self._records(port)[0]
            self.assertEqual(frame["deviceName"], deviceName)
            self.assertEqual(frame["image"]["components"], 3)
            self.assertEqual(frame["image"]["scalarType"], "uint8")
            self.assertNotIn("cubeMatch", frame)

    def test_summaryNamesMissingBands(self):
        header, _values = self._startStandIn(dropBands=(2, 4))
        self._startRecorder(compareCube=header)
        cubePort = self.basePort + 2
        self.assertTrue(waitFor(lambda: len(self._records(cubePort)) >= 3))
        time.sleep(0.3)
        self.recorder.stop()
        summary = (self.out / "summary.md").read_text(encoding="utf-8")
        self.assertIn(f"## Port {cubePort}", summary)
        self.assertIn("Bands matched, in arrival order: 1, 3, 5", summary)
        self.assertIn("Missing bands: 2, 4", summary)
        self.assertIn("Repeated bands: none", summary)
        self.assertIn("Out of order: none", summary)

    def test_writesNoPixelData(self):
        header, values = self._startStandIn()
        self._startRecorder(compareCube=header)
        self.assertTrue(waitFor(lambda: len(self._records(self.basePort + 2)) >= 5))
        self.recorder.stop()
        self.assertEqual(sorted(path.name for path in self.out.iterdir()),
                         ["messages.jsonl", "summary.md"])
        lines = (self.out / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            record = json.loads(line)
            self.assertLess(len(line), 4096, "A log line is large enough to hold pixels")
            self.assertNotIn("pixels", record)

    def test_recordsFromAServerThatStartsLater(self):
        port = freeBasePort()
        self.recorder = igtl_recorder.Recorder("127.0.0.1", [port], self.out,
                                               report=lambda _line: None)
        self.recorder.start()
        time.sleep(1.5)
        server = _RawServer(port)
        try:
            self.assertTrue(server.connected.wait(WAIT_SEC), "The recorder never tried again")
            image = numpy.arange(6, dtype=numpy.uint16).reshape(1, 2, 3)
            server.send(packedImage(image))
            self.assertTrue(waitFor(lambda: len(self.recorder.records) == 1))
        finally:
            self.recorder.stop()
            server.close()

    def test_sendsNothingToTheServer(self):
        port = freeBasePort()
        server = _RawServer(port)
        self.recorder = igtl_recorder.Recorder("127.0.0.1", [port], self.out,
                                               report=lambda _line: None)
        try:
            self.recorder.start()
            self.assertTrue(server.connected.wait(WAIT_SEC))
            server.send(packedImage(numpy.zeros((1, 2, 2), dtype=numpy.uint16)))
            self.assertTrue(waitFor(lambda: len(self.recorder.records) == 1))
            server.drain(1.0)
            self.recorder.stop()
            server.drain(0.5)
            self.assertEqual(bytes(server.received), b"")
        finally:
            server.close()


class _SlowComparison:
    """Stands in for a compare cube that takes `delaySec` per image."""

    def __init__(self, delaySec: float) -> None:
        self.delaySec = delaySec
        self.dataPath = Path("slow.raw")
        self.samples = self.lines = 2
        self.bands = 3
        self.dtype = numpy.dtype("<u2")

    def match(self, _pixels):
        time.sleep(self.delaySec)
        return None


class RecorderRawServerTest(unittest.TestCase):

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.folder = Path(self._folder.name)
        self.out = self.folder / "recording"
        self.port = freeBasePort()
        self.server = _RawServer(self.port)
        self.recorder = None

    def tearDown(self):
        if self.recorder is not None:
            self.recorder.stop()
        self.server.close()
        self._folder.cleanup()

    def _startRecorder(self, comparison, **options):
        self.recorder = igtl_recorder.Recorder("127.0.0.1", [self.port], self.out,
                                               comparison=comparison, report=lambda _line: None,
                                               **options)
        self.recorder.start()
        self.assertTrue(self.server.connected.wait(WAIT_SEC))

    def test_arrivalTimesDoNotWaitForSlowDescription(self):
        self._startRecorder(_SlowComparison(0.3))
        band = numpy.zeros((1, 2, 2), dtype=numpy.uint16)
        self.server.send(b"".join(packedImage(band) for _ in range(5)))
        self.assertTrue(waitFor(lambda: len(self.recorder.records) == 5))
        arrivals = sorted(record["arrivalMonotonic"] for record in self.recorder.records)
        self.assertLess(arrivals[-1] - arrivals[0], 0.3,
                        "Arrival times include the time spent describing earlier messages")
        waits = [record["describeWaitSec"] for record in self.recorder.records]
        self.assertGreater(max(waits), 0.9)
        summary = self.recorder.stop()
        self.assertIn("- Longest wait before a message was described: 1.", summary)
        self.assertIn("- Reader held back by the describer: 0.0 s", summary)

    def test_summarySplitsCapturesByGap(self):
        header, values = writeFixtureCube(self.folder)
        self._startRecorder(igtl_recorder.CubeComparison(header), captureGapSec=0.5)

        def sendBands(numbers):
            self.server.send(b"".join(packedImage(values[number - 1][numpy.newaxis])
                                      for number in numbers))

        sendBands((1, 2, 3, 4, 5))
        self.server.send(pyigtl.StringMessage("end of cube", device_name="HsCube").pack())
        self.assertTrue(waitFor(lambda: len(self.recorder.records) == 6))
        time.sleep(1.0)
        sendBands((1, 2, 4, 3, 5))
        self.assertTrue(waitFor(lambda: len(self.recorder.records) == 11))
        summary = self.recorder.stop()
        self.assertIn("- Captures (a new one starts after 0.5 s without a compared image): 2",
                      summary)
        first, second = summary.split("### Capture 1", 1)[1].split("### Capture 2", 1)
        self.assertIn("- Bands matched, in arrival order: 1-5", first)
        self.assertIn("- Repeated bands: none", first)
        self.assertIn("- Followed by: STRING 'HsCube' \"end of cube\"", first)
        self.assertIn("- Bands matched, in arrival order: 1-2, 4, 3, 5", second)
        self.assertIn("- Out of order: band 3 after band 4", second)
        self.assertIn("- Followed by: nothing", second)
        self.assertIn("STRING 'HsCube' \"end of cube\" (1)", summary)
        for line in (self.out / "messages.jsonl").read_text(encoding="utf-8").splitlines():
            json.loads(line, parse_constant=self.fail)


if __name__ == "__main__":
    unittest.main()
