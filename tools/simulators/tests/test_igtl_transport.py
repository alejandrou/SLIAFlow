"""OpenIGTLink transport tests.

These are the tests that keep provenance on the wire. A pyigtl message left at
its default header version packs to a well-formed message whose metadata
unpacks to an empty dictionary, so a send that drops every provenance attribute
looks exactly like a successful one.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import socket
import subprocess
import sys
import time
import unittest
from importlib import metadata
from pathlib import Path
from unittest import mock

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
        metadata = contract.liveViewMetadata("acquisition stand-in, laptop camera")
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
        message.metadata = dict(contract.liveViewMetadata("acquisition stand-in, laptop camera"))

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


# The port table in `docs/architecture/WP5_MS5_DEMO_PLAN.md` is the authority for
# these, not the code under test.
DOCUMENTED_RESERVED_CHANNELS = {18948: "Stereoscopic", 18949: "UC2_STO2"}

# Where the package the scan below reads lives. A module constant so that a
# scratch runner can point it at a copy when showing the scan fail.
STRATUM_SIM_PACKAGE_ROOT = Path(igtl_transport.__file__).resolve().parent

# A construction, a subclass or an import of pyigtl's server. `config.py` names the
# C++ file `OpenIGTLinkServer.cpp` in a comment, which is not a server.
PYIGTL_SERVER_REFERENCE = re.compile(r"\bOpenIGTLinkServer\b(?!\.cpp)")

SERVED_DEADLINE_SEC = 10.0


class PortRefusalTest(unittest.TestCase):
    """What a producer does when its port is already served (SLIA-017).

    pyigtl sets `SO_REUSEADDR`, and on Windows that lets a second server bind a
    port another one is listening on. These start real servers on a free local
    port and read the raised error, because its text is what reaches the
    operator. The expected wording is the SLIA-017 card's.
    """

    def setUp(self) -> None:
        self.port = freeLocalPort()
        self.address = f"127.0.0.1:{self.port}"
        self.servers: list[igtl_transport.ImageStreamServer] = []

        # The client watch prints attach and release lines from its own thread.
        silenced = contextlib.redirect_stdout(io.StringIO())
        silenced.__enter__()
        self.addCleanup(silenced.__exit__, None, None, None)
        self.addCleanup(self.stopServers)

    def stopServers(self) -> None:
        for server in reversed(self.servers):
            server.stop()

    def startServer(self, **arguments) -> igtl_transport.ImageStreamServer:
        server = igtl_transport.ImageStreamServer(port=self.port, **arguments)
        self.servers.append(server)
        server.start()
        return server

    def attachClient(self) -> pyigtl.OpenIGTLinkClient:
        client = pyigtl.OpenIGTLinkClient(host="127.0.0.1", port=self.port)
        self.addCleanup(client.stop)
        return client

    def waitFor(self, condition) -> bool:
        deadline = time.monotonic() + SERVED_DEADLINE_SEC
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(SEND_PERIOD_SEC)
        return condition()

    def test_aSecondServerOnAnOccupiedPortIsRefused(self):
        self.startServer()

        with self.assertRaises(OSError) as refused:
            self.startServer()

        self.assertIsInstance(refused.exception, igtl_transport.PortRefusedError)
        message = str(refused.exception)
        self.assertIn(self.address, message)
        self.assertIn("Stop the other producer", message)
        self.assertIn("different port", message)
        self.assertIn("--allow-shared-port", message)

    @needsWindowsTcpTable
    def test_theRefusalNamesTheProcessHoldingThePort(self):
        self.startServer()

        with self.assertRaises(OSError) as refused:
            self.startServer()

        message = str(refused.exception)
        self.assertIn(f"PID {os.getpid()}", message)
        # The venv's launcher and the interpreter it starts are both python.exe.
        self.assertIn(Path(sys.executable).name.lower(), message.lower())

    def test_aPortHeldByAnyListenerIsRefusedTheSameWay(self):
        # A listener that did not set SO_REUSEADDR already stopped pyigtl's bind,
        # as WinError 10013, whose text names neither the port nor the remedy.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()

        with self.assertRaises(OSError) as refused:
            self.startServer()

        message = str(refused.exception)
        self.assertIn(self.address, message)
        self.assertIn("Stop the other producer", message)

    def test_aReservedPortIsRefusedByNameWithoutBinding(self):
        for port, channel in DOCUMENTED_RESERVED_CHANNELS.items():
            for sharingArguments in ({}, {"allowSharedPort": True}):
                with (
                    self.subTest(port=port, **sharingArguments),
                    mock.patch.object(igtl_transport, "_DepartureAwareServer") as serverClass,
                    mock.patch.object(igtl_transport, "_SharedPortServer", create=True) as sharedClass,
                    mock.patch.object(igtl_transport, "ClientWatch"),
                ):
                    server = igtl_transport.ImageStreamServer(port=port, **sharingArguments)
                    with self.assertRaises(OSError) as refused:
                        server.start()

                    message = str(refused.exception)
                    self.assertIn(str(port), message)
                    self.assertIn(channel, message)
                    self.assertIn("reserved", message)
                    serverClass.assert_not_called()
                    sharedClass.assert_not_called()

            with self.subTest(port=port, check="early"):
                with self.assertRaises(OSError) as refused:
                    igtl_transport.assertPortCanBeServed(port, allowSharedPort=True)
                self.assertIn(channel, str(refused.exception))

    def test_twoProducersThatBothOptInShareAPort(self):
        self.startServer(allowSharedPort=True)
        self.startServer(allowSharedPort=True)

        self.attachClient()

        self.assertTrue(
            self.waitFor(lambda: any(server.isConnected for server in self.servers)),
            "Neither producer served the client.",
        )

    def test_theOverrideDoesNotJoinAProducerThatDidNotOptIn(self):
        self.startServer()

        with self.assertRaises(OSError) as refused:
            self.startServer(allowSharedPort=True)

        self.assertIn(self.address, str(refused.exception))

    def test_theEarlyCheckWithTheOverrideRefusesAProducerThatDidNotOptIn(self):
        # Without this the override skipped the early check, and `uc1-real` learnt
        # of the refusal only at the bind, after its GPU run.
        self.startServer()

        with self.assertRaises(igtl_transport.PortRefusedError) as refused:
            igtl_transport.assertPortCanBeServed(self.port, allowSharedPort=True)

        message = str(refused.exception)
        self.assertIn(self.address, message)
        self.assertIn("was not started with --allow-shared-port", message)
        self.assertIn("Stop the other producer", message)

    def test_theEarlyCheckWithTheOverrideAcceptsAProducerThatOptedIn(self):
        self.startServer(allowSharedPort=True)

        igtl_transport.assertPortCanBeServed(self.port, allowSharedPort=True)

    def test_aRestartThatFindsItsPortTakenSaysWhy(self):
        # The send-failure restart leaves the port free for one delay. A listener
        # that takes it then is refused at the restart's bind, and the operator is
        # told that this producer stopped serving, and why, rather than only that
        # some port is held.
        server = self.startServer()
        pyigtlServer = server._server
        takenBy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(takenBy.close)
        restartDelay = 0.0125
        realSleep = time.sleep

        def sleepTakingThePort(seconds):
            if seconds == restartDelay:
                takenBy.bind(("127.0.0.1", self.port))
                takenBy.listen()
            else:
                realSleep(seconds)

        with (
            mock.patch.object(igtl_transport, "RECONNECT_DELAY_SEC", restartDelay),
            mock.patch.object(igtl_transport.time, "sleep", side_effect=sleepTakingThePort),
            mock.patch.object(pyigtlServer, "is_connected", return_value=True),
            mock.patch.object(
                pyigtlServer, "send_message", side_effect=ConnectionResetError("The client left.")
            ),
            self.assertLogs(igtl_transport.logger, "WARNING"),
            self.assertRaises(igtl_transport.PortRefusedError) as refused,
        ):
            server.sendString("text", "Device")

        message = str(refused.exception)
        self.assertIn(self.address, message)
        self.assertIn("restarted after a failed send", message)
        self.assertIn("stopped serving", message)

    def test_aProducerRestartsOnItsOwnPortAfterServingAClient(self):
        # The previous clients leave TIME_WAIT rows on the port. A producer's own
        # restart, and a new run straight after the last, must not read them as
        # a holder.
        server = self.startServer()
        client = self.attachClient()
        self.assertTrue(self.waitFor(lambda: server.isConnected), "The client was never served.")
        server.stop()
        client.stop()

        restarted = self.startServer()

        self.assertFalse(restarted.isConnected)

    def test_onlyTheTransportConstructsAPyigtlServer(self):
        # A later producer, such as SLIA-021's UC2 runner, inherits the refusal
        # only by building its server through `ImageStreamServer`.
        offenders = [
            path.name
            for path in sorted(STRATUM_SIM_PACKAGE_ROOT.glob("*.py"))
            if path.name != "igtl_transport.py"
            and PYIGTL_SERVER_REFERENCE.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(offenders, [])


# A producer in its own interpreter: it serves until its standard input closes,
# and reports the PID of the interpreter that owns the socket, which with the venv
# launcher is not the PID `Popen` returns.
SEPARATE_PRODUCER_SCRIPT = """
import os, sys
from stratum_sim import igtl_transport
server = igtl_transport.ImageStreamServer(port=int(sys.argv[1]), allowSharedPort=sys.argv[2] == "shared")
server.start()
print(f"serving {os.getpid()}", flush=True)
sys.stdin.read()
server.stop()
"""

SEPARATE_PRODUCER_START_TIMEOUT_SEC = 20.0


@needsWindowsTcpTable
class SeparateProcessSharingTest(unittest.TestCase):
    """`--allow-shared-port` between two producer processes, as it is used (SLIA-017).

    Windows decides a shared bind per socket, whichever process owns it, but the
    in-process tests above cannot show that, nor that the holder is named by the
    PID of another process.
    """

    def setUp(self) -> None:
        self.port = freeLocalPort()
        self.address = f"127.0.0.1:{self.port}"

    def startSeparateProducer(self, sharing: bool) -> int:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(STRATUM_SIM_PACKAGE_ROOT.parent), environment.get("PYTHONPATH")])
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SEPARATE_PRODUCER_SCRIPT,
                str(self.port),
                "shared" if sharing else "exclusive",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=environment,
        )

        def stopSeparateProducer() -> None:
            process.stdin.close()
            try:
                process.wait(timeout=SEPARATE_PRODUCER_START_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()

        self.addCleanup(stopSeparateProducer)

        # The producer's client watch prints on the same stream.
        deadline = time.monotonic() + SEPARATE_PRODUCER_START_TIMEOUT_SEC
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                self.fail("The separate producer exited before it was serving.")
            if line.startswith("serving "):
                return int(line.split()[1])
        self.fail("The separate producer did not start serving in time.")

    def startServerHere(self) -> tuple[igtl_transport.ImageStreamServer, str]:
        server = igtl_transport.ImageStreamServer(port=self.port, allowSharedPort=True)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            server.start()
        self.addCleanup(server.stop)
        return server, errors.getvalue()

    def test_producersInSeparateProcessesShareWhenBothOptIn(self):
        holderId = self.startSeparateProducer(sharing=True)

        igtl_transport.assertPortCanBeServed(self.port, allowSharedPort=True)
        _server, errors = self.startServerHere()

        self.assertIn(os.getpid(), igtl_transport.listeningProcessIds(self.port))
        self.assertIn(holderId, igtl_transport.listeningProcessIds(self.port))
        # Sharing is on purpose, but a client now reaches either producer, and the
        # console of each has to say so.
        self.assertIn("WARNING:", errors)
        self.assertIn(self.address, errors)
        self.assertIn(f"PID {holderId}", errors)

    def test_aSeparateProducerThatDidNotOptInIsNotJoined(self):
        holderId = self.startSeparateProducer(sharing=False)

        with self.assertRaises(igtl_transport.PortRefusedError) as early:
            igtl_transport.assertPortCanBeServed(self.port, allowSharedPort=True)
        with self.assertRaises(igtl_transport.PortRefusedError) as bound:
            self.startServerHere()

        for refused in (early, bound):
            message = str(refused.exception)
            self.assertIn(f"PID {holderId}", message)
            self.assertIn("was not started with --allow-shared-port", message)
            self.assertIn(f"Stop-Process -Id {holderId}", message)
        self.assertEqual(igtl_transport.listeningProcessIds(self.port), [holderId])
