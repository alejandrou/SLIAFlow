"""OpenIGTLink transport tests.

These are the tests that keep provenance on the wire. A pyigtl message left at
its default header version packs to a well-formed message whose metadata
unpacks to an empty dictionary, so a send that drops every provenance attribute
looks exactly like a successful one.
"""

from __future__ import annotations

import contextlib
import io
import socket
import sys
import time
import unittest
from importlib import metadata

import numpy
import pyigtl

from stratum_sim import contract, igtl_transport
from tests import support

TEST_SAMPLES = 8
TEST_LINES = 4

# Long enough for the watch to print once its 2 s grace period (SLIA-018) and
# polling have passed, with room for a slow test machine.
CLIENT_WATCH_DEADLINE_SEC = 10.0

# More than twice the 2 s grace period, so a warning that was going to fire has
# had the chance to.
QUIET_OBSERVATION_SEC = 5.0

# The LiveView period at 20 Hz. pyigtl learns that a served client has gone only
# when a send to it fails, so the tests that need that keep sending.
SEND_PERIOD_SEC = 0.05

WATCH_DEVICE_NAME = "ClientWatch"

needsWindowsTcpTable = unittest.skipUnless(
    sys.platform == "win32",
    "Confirming that a waiting client is still attached reads the Windows TCP table.",
)


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


def freeLocalPort() -> int:
    """Return a port nothing holds at this moment."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ClientWatchTest(unittest.TestCase):
    """What a producer tells the operator about the clients on its port.

    pyigtl serves one client at a time. A second client completes its handshake
    in the accept backlog, reports itself connected, and receives nothing. These
    tests attach real clients to a real server and read what the producer
    prints, because printed output is what reaches the operator. The expected
    lines are the ones the SLIA-018 card specifies.
    """

    def setUp(self) -> None:
        self.port = freeLocalPort()
        self.output = io.StringIO()
        self.clients: list[pyigtl.OpenIGTLinkClient] = []
        self.addCleanup(self.stopClients)

    def stopClients(self) -> None:
        for client in self.clients:
            client.stop()

    @property
    def servingOneLine(self) -> str:
        return f"127.0.0.1:{self.port}: serving 1 client."

    @property
    def servingNoneLine(self) -> str:
        return f"127.0.0.1:{self.port}: serving 0 clients."

    @contextlib.contextmanager
    def serving(self):
        with (
            contextlib.redirect_stdout(self.output),
            igtl_transport.ImageStreamServer(port=self.port) as server,
        ):
            yield server

    def attachClient(self) -> pyigtl.OpenIGTLinkClient:
        client = pyigtl.OpenIGTLinkClient(host="127.0.0.1", port=self.port)
        self.clients.append(client)
        return client

    def waitFor(self, condition, server=None, deadlineSec=CLIENT_WATCH_DEADLINE_SEC) -> bool:
        """Poll `condition` until it holds, sending on `server` meanwhile when given."""
        deadline = time.monotonic() + deadlineSec
        image = numpy.zeros((1, TEST_LINES, TEST_SAMPLES, 3), dtype=numpy.uint8)
        while time.monotonic() < deadline:
            if condition():
                return True
            if server is not None:
                server.sendImage(image, WATCH_DEVICE_NAME, {})
            time.sleep(SEND_PERIOD_SEC)
        return condition()

    def printed(self, text: str) -> bool:
        return text in self.output.getvalue()

    def test_theServedCountIsReportedWhenTheClientGoes(self):
        with self.serving() as server:
            client = self.attachClient()
            attached = self.waitFor(lambda: self.printed(self.servingOneLine))
            client.stop()
            released = self.waitFor(lambda: self.printed(self.servingNoneLine), server=server)

        output = self.output.getvalue()
        self.assertTrue(attached, f"No attach line was printed:\n{output}")
        self.assertTrue(released, f"No release line was printed:\n{output}")

    @needsWindowsTcpTable
    def test_aSecondAttachedClientIsWarnedAbout(self):
        with self.serving() as server:
            self.attachClient()
            self.assertTrue(self.waitFor(lambda: server.isConnected), "The first client was never served.")
            self.attachClient()
            warned = self.waitFor(lambda: self.printed("WARNING:"))

        output = self.output.getvalue()
        self.assertTrue(warned, f"No warning was printed for a second client:\n{output}")
        warnings = [line for line in output.splitlines() if line.startswith("WARNING:")]
        self.assertEqual(len(warnings), 1, output)
        warning = warnings[0]
        self.assertIn(f"127.0.0.1:{self.port} has 2 clients attached", warning)
        self.assertIn("receives nothing until", warning)
        self.assertIn("Close the other client", warning)
        # The second client is genuinely connected, the producer is not at
        # fault, and nothing was lost. The warning must not say otherwise.
        lowered = warning.lower()
        for claim in ("disconnected", "lost", "fault", "error", "fail"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, lowered)

    def test_aSingleClientDrawsNoWarning(self):
        with self.serving():
            self.attachClient()
            attached = self.waitFor(lambda: self.printed(self.servingOneLine))
            time.sleep(QUIET_OBSERVATION_SEC)

        output = self.output.getvalue()
        self.assertTrue(attached, f"The watch never reported the client, so its silence proves nothing:\n{output}")
        self.assertNotIn("WARNING:", output)

    @needsWindowsTcpTable
    def test_aClientReplacingOneThatLeftDrawsNoWarning(self):
        # Nothing is sent after the first client leaves, so only the server's
        # own check for a closed connection lets the replacement in. Until it
        # does, the replacement is queued behind a client that has gone.
        with self.serving():
            first = self.attachClient()
            attached = self.waitFor(lambda: self.printed(self.servingOneLine))
            first.stop()
            self.attachClient()
            time.sleep(QUIET_OBSERVATION_SEC)

        output = self.output.getvalue()
        self.assertTrue(attached, f"The watch never reported the first client, so its silence proves nothing:\n{output}")
        self.assertNotIn("WARNING:", output)

    def test_aClientReplacingOneThatLeftReceivesTheNextMessage(self):
        # The HSCube port between captures: nothing is sent after the served
        # client leaves, then one cube is. pyigtl on its own notices a departure
        # only when a send to it fails, so that one cube went to the departed
        # client and the replacement, queued behind it, received nothing.
        image = numpy.zeros((1, TEST_LINES, TEST_SAMPLES, 3), dtype=numpy.uint8)
        with self.serving() as server:
            first = self.attachClient()
            attached = self.waitFor(lambda: self.printed(self.servingOneLine))
            first.stop()
            released = self.waitFor(lambda: self.printed(self.servingNoneLine))
            replacement = self.attachClient()
            reattached = self.waitFor(lambda: self.output.getvalue().count(self.servingOneLine) == 2)
            queued = server.sendImage(image, WATCH_DEVICE_NAME, {})
            received = replacement.wait_for_message(WATCH_DEVICE_NAME, timeout=CLIENT_WATCH_DEADLINE_SEC)

        output = self.output.getvalue()
        self.assertTrue(attached, f"The watch never reported the first client:\n{output}")
        self.assertTrue(released, f"The departed client was not let go while nothing was sent:\n{output}")
        self.assertTrue(reattached, f"The replacement was never served:\n{output}")
        self.assertTrue(queued, "The message was not queued for the replacement.")
        self.assertIsNotNone(received, f"The replacement never received the message:\n{output}")

    @needsWindowsTcpTable
    def test_theWarningIsWithdrawnWhenTheWaitingClientLeaves(self):
        # On Windows a connection that gives up while queued stays queued, so
        # the listening socket alone would keep the warning up indefinitely.
        with self.serving() as server:
            self.attachClient()
            self.assertTrue(self.waitFor(lambda: server.isConnected), "The first client was never served.")
            waiting = self.attachClient()
            warned = self.waitFor(lambda: self.printed("WARNING:"))
            waiting.stop()
            withdrawn = self.waitFor(lambda: self.printed("the warning above no longer applies"))
            time.sleep(QUIET_OBSERVATION_SEC)

        output = self.output.getvalue()
        self.assertTrue(warned, f"No warning was printed for a second client:\n{output}")
        self.assertTrue(withdrawn, f"The warning was not withdrawn after the waiting client left:\n{output}")
        self.assertEqual(output.count("WARNING:"), 1, output)
