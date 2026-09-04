"""OpenIGTLink transport tests.

These are the tests that keep provenance on the wire. A pyigtl message left at
its default header version packs to a well-formed message whose metadata
unpacks to an empty dictionary, so a send that drops every provenance attribute
looks exactly like a successful one.
"""

from __future__ import annotations

import unittest
from importlib import metadata

import numpy
import pyigtl

from stratum_sim import contract, igtl_transport
from tests import support

TEST_SAMPLES = 8
TEST_LINES = 4


def buildTestFrameRgb() -> numpy.ndarray:
    frame = numpy.arange(TEST_LINES * TEST_SAMPLES * 3, dtype=numpy.uint8)
    return frame.reshape((1, TEST_LINES, TEST_SAMPLES, 3))


def packAndUnpack(message: pyigtl.MessageBase) -> pyigtl.MessageBase:
    packed = message.pack()
    headerSize = pyigtl.MessageBase.IGTL_HEADER_SIZE
    headerFields = pyigtl.MessageBase.parse_header(packed[:headerSize])
    received = pyigtl.MessageBase.create_message(headerFields["message_type"])
    received.unpack(headerFields, packed[headerSize:])
    return received


class MetadataRoundTripTest(unittest.TestCase):

    def test_metadataSurvivesPackUnpackRoundTrip(self):
        metadata = contract.liveViewMetadata("acquisition stand-in, synthetic scene")
        message = igtl_transport.buildImageMessage(
            buildTestFrameRgb(), deviceName="LiveView", metadata=metadata
        )

        self.assertEqual(message.header_version, igtl_transport.IGTL_HEADER_VERSION_WITH_METADATA)

        received = packAndUnpack(message)

        self.assertEqual(received.device_name, "LiveView")
        self.assertEqual(received.metadata, metadata)
        for key, value in metadata.items():
            with self.subTest(key=key):
                self.assertEqual(received.metadata.get(key), value)

    def test_defaultHeaderVersionSilentlyDropsMetadata(self):
        # This is the failure mode the requirement exists to prevent: the send
        # succeeds, the message is well formed, and the provenance is gone.
        message = pyigtl.ImageMessage(image=buildTestFrameRgb(), device_name="LiveView")
        message.metadata = dict(contract.liveViewMetadata("arithmetic stand-in"))

        self.assertEqual(message.header_version, 1)
        with self.assertLogs("pyigtl.messages", level="WARNING"):
            received = packAndUnpack(message)
        self.assertEqual(received.metadata, {})


class ImageMessageShapeTest(unittest.TestCase):

    def test_imageMessageMirrorsTheCppSender(self):
        message = igtl_transport.buildImageMessage(
            buildTestFrameRgb(), deviceName="LiveView", metadata={}
        )
        received = packAndUnpack(message)

        # OpenIGTLinkServer.cpp sends dimensions {w, h, 1}, three uint8
        # components, identity matrix, LPS. pyigtl carries the same content in
        # a (k, j, i, components) array.
        self.assertEqual(received.image.shape, (1, TEST_LINES, TEST_SAMPLES, 3))
        self.assertEqual(received.image.dtype, numpy.uint8)
        self.assertEqual(received.world_coordinate_system, "lps")
        numpy.testing.assert_allclose(received.ijk_to_world_matrix, numpy.eye(4), atol=1e-6)

    def test_frameIsPreparedAsKjiComponentsAndRotates(self):
        frameBgr = numpy.zeros((TEST_LINES, TEST_SAMPLES, 3), dtype=numpy.uint8)
        frameBgr[0, 0] = (10, 20, 30)

        prepared = igtl_transport.prepareFrameForWire(frameBgr, rotate180=False)
        self.assertEqual(prepared.shape, (1, TEST_LINES, TEST_SAMPLES, 3))
        # BGR in, RGB out.
        numpy.testing.assert_array_equal(prepared[0, 0, 0], numpy.array([30, 20, 10], dtype=numpy.uint8))

        rotated = igtl_transport.prepareFrameForWire(frameBgr, rotate180=True)
        numpy.testing.assert_array_equal(
            rotated[0, TEST_LINES - 1, TEST_SAMPLES - 1], numpy.array([30, 20, 10], dtype=numpy.uint8)
        )


class DependencyConsistencyTest(unittest.TestCase):

    def test_installedPyigtlMatchesTheSimulatorManifest(self):
        # pyigtl/_version.py was not bumped for the 0.3.4 release, so
        # `pyigtl.__version__` reports 0.3.2 and a check against it would record
        # a version that is simply false while continuing to pass.
        requirement = support.pinnedRequirement(
            support.REPOSITORY_ROOT / "tools" / "simulators" / "requirements.txt",
            "pyigtl",
        )
        _packageName, expectedVersion = requirement.split("==", 1)
        self.assertEqual(igtl_transport.installedPyigtlVersion(), expectedVersion)
        self.assertEqual(metadata.version("pyigtl"), expectedVersion)
