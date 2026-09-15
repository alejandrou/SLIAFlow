"""Guards that run at the acquisition level rather than inside one module.

The configuration validator predicts whether a dataset can satisfy the contract.
These cover what happens to the prediction afterwards: the measured rank has to
be enforced, not merely printed, and the reported frame rate has to divide by
the intervals it actually spans.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy
import pyigtl

from stratum_sim import acquisition_sim, capture_client, config, contract, spectra
from tests import support


def buildRankReport(rank: int) -> spectra.SpectralRankReport:
    return spectra.SpectralRankReport(
        rank=rank,
        conditionNumber=1.0,
        largestSingularValue=1.0,
        smallestRetainedSingularValue=1.0,
    )


class SpectralRankGuardTest(unittest.TestCase):

    def test_aDegenerateDatasetIsNotAllowedToLookSuccessful(self):
        # Printing the rank and exiting 0 would let a dataset no consumer can
        # use pass for a good one.
        with self.assertRaises(acquisition_sim.SpectralRankTooLowError) as refused:
            acquisition_sim.assertSpectralRankIsSufficient(
                buildRankReport(spectra.MINIMUM_SPECTRAL_RANK - 1)
            )
        self.assertIn(str(spectra.MINIMUM_SPECTRAL_RANK), str(refused.exception))

    def test_theFloorItselfPasses(self):
        acquisition_sim.assertSpectralRankIsSufficient(
            buildRankReport(spectra.MINIMUM_SPECTRAL_RANK)
        )


class EnqueueRateTest(unittest.TestCase):

    def test_theRateDividesByIntervalsNotByFrames(self):
        # n frames span n-1 intervals. Ten frames one tenth of a second apart
        # took 0.9 s, so the rate is 10 fps, not the 11.1 that dividing by the
        # frame count would report.
        frameCount = 10
        measurementStart = 100.0
        measurementEnd = 100.9

        # Patch the simulator's own reference to the clock. Patching
        # `acquisition_sim.time.perf_counter` would reach into the stdlib
        # module every other test in the process is sharing.
        fixedClock = SimpleNamespace(perf_counter=lambda: measurementEnd)
        with mock.patch.object(acquisition_sim, "time", fixedClock):
            rate = acquisition_sim.enqueueRate(frameCount, measurementStart)

        expectedRate = (frameCount - 1) / (measurementEnd - measurementStart)
        self.assertEqual(rate, expectedRate)
        self.assertLess(rate, frameCount / (measurementEnd - measurementStart))

    def test_noMeasurementIsReportedAsZeroRatherThanGuessed(self):
        self.assertEqual(acquisition_sim.enqueueRate(0, None), 0.0)
        self.assertEqual(acquisition_sim.enqueueRate(1, 100.0), 0.0)


# The port table in `docs/architecture/WP5_MS5_DEMO_PLAN.md` is the authority for
# these numbers, not the code under test.
DOCUMENTED_LIVE_VIEW_PORT = 18944
DOCUMENTED_HS_CUBE_PORT = 18947
DOCUMENTED_CONTROL_PORT = 18950
DOCUMENTED_RESERVED_PORTS = (18948, 18949)

# The control-channel wording `SLIA-022` writes the Slicer side against, as the
# SLIA-023 card and `tools/simulators/README.md` state it.
TRIGGER_DEVICE_NAME = "CaptureTrigger"
CAPTURE_COMMAND = "CAPTURE"
HS_CUBE_DEVICE_NAME = "HSCube"

CASE_NAME = "004-02"
# The cube's detail, in the form the WP5 plan's provenance section requires.
EXPECTED_CUBE_DETAIL = "acquisition stand-in, recorded HSI case 004-02 (simulated acquisition)"
# LiveView and the cube are unrelated in a recorded session, so LiveView names
# its own source - the laptop camera - and never the case.
EXPECTED_LIVE_VIEW_DETAIL = "acquisition stand-in, laptop camera"

WIRE_TIMEOUT_SEC = 20.0


def freeLocalPort() -> int:
    """Return a port nothing holds at this moment.

    Another process could take it before the stand-in binds it. On one test
    machine that race is theoretical, and a clash fails the test rather than
    passing it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeServer:
    """An `ImageStreamServer` that records what it was asked to send."""

    def __init__(self, port: int, incomingStrings=()) -> None:
        self.port = port
        self.isConnected = True
        self.images = []
        self.strings = []
        self._incoming = list(incomingStrings)

    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *_arguments) -> None:
        return None

    def sendImage(self, image, deviceName, metadata) -> bool:
        self.images.append((numpy.array(image, copy=True), deviceName, dict(metadata)))
        return True

    def sendString(self, text, deviceName) -> bool:
        self.strings.append((deviceName, text))
        return True

    def receiveStrings(self, deviceName) -> list[str]:
        received = [text for name, text in self._incoming if name == deviceName]
        self._incoming = []
        return received


class StillFrameSource:
    """A `FrameSource` test double that hands back one black frame.

    It stands in for the laptop camera, which a test must not open. It is not a
    scene: the frames are only there so the LiveView loop has something to send.
    """

    def __init__(self, samples: int, lines: int) -> None:
        self._frame = numpy.zeros((lines, samples, 3), dtype=numpy.uint8)

    def read(self) -> numpy.ndarray:
        return self._frame


class CaptureControllerTest(unittest.TestCase):
    """The capture's timing, with the clock passed in rather than waited for."""

    CASE_FOLDER = Path("recorded-root") / CASE_NAME

    def makeController(self, delaySec: float) -> acquisition_sim.CaptureController:
        return acquisition_sim.CaptureController(
            CASE_NAME,
            self.CASE_FOLDER,
            delayMinSec=delaySec,
            delayMaxSec=delaySec,
            rng=numpy.random.default_rng(0),
        )

    def test_triggerPublishesCubeAfterDelay(self):
        controller = self.makeController(5.0)
        self.assertEqual(controller.statusText, "IDLE")

        reply = controller.handleCommand(CAPTURE_COMMAND, now=100.0)
        self.assertTrue(reply.startswith("CAPTURING capture=1 "), reply)

        self.assertFalse(controller.advance(now=104.99))
        self.assertTrue(controller.statusText.startswith("CAPTURING capture=1 "))

        self.assertTrue(controller.advance(now=105.0))
        self.assertEqual(
            controller.statusText,
            f"READY capture=1 case={CASE_NAME} folder={self.CASE_FOLDER}",
        )
        # Exactly once: a second completion of the same capture would reach a
        # consumer as a second capture.
        self.assertFalse(controller.advance(now=106.0))

    def test_triggerDuringCaptureIsIgnored(self):
        controller = self.makeController(5.0)
        controller.handleCommand(CAPTURE_COMMAND, now=100.0)

        self.assertEqual(
            controller.handleCommand(CAPTURE_COMMAND, now=101.0),
            "IGNORED capture 1 already in progress",
        )

        completions = [controller.advance(now=moment) for moment in (104.0, 105.0, 106.0, 112.0)]
        # The delay still runs from the first trigger, and the ignored one was
        # not queued behind it.
        self.assertEqual(completions, [False, True, False, False])
        self.assertTrue(controller.statusText.startswith("READY capture=1 "))

    def test_unknownCommandIsRefusedByName(self):
        controller = self.makeController(5.0)

        self.assertEqual(
            controller.handleCommand("SHUTTER", now=100.0), "REFUSED unknown command SHUTTER"
        )
        self.assertEqual(controller.statusText, "IDLE")


class RecordedCaptureTest(unittest.TestCase):
    """One instant capture of a recorded case, against recording servers."""

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporaryDirectory.cleanup)
        self.repositoryRoot = Path(self._temporaryDirectory.name).resolve()
        self.caseFolder = support.writeRecordedCaseFixture(
            self.repositoryRoot / "input" / "bin" / "bin" / CASE_NAME
        )
        self.simulatorConfig = config.loadSimulatorConfig(
            self.repositoryRoot,
            overrides={
                "sceneMode": "recorded",
                "case": CASE_NAME,
                # The session's setting. The camera itself is never opened:
                # the frames come from the `StillFrameSource` passed in below.
                "frameSource": "webcam",
                "captureDelayMinSec": 0.0,
                "captureDelayMaxSec": 0.0,
                "targetFrameRate": 100.0,
            },
        )

    def runOneCapture(self) -> dict[int, FakeServer]:
        servers: dict[int, FakeServer] = {}
        controlPort = self.simulatorConfig.controlPort
        cubePort = self.simulatorConfig.hsCubePort

        def serverFactory(port: int) -> FakeServer:
            incoming = [(TRIGGER_DEVICE_NAME, CAPTURE_COMMAND)] if port == controlPort else []
            servers[port] = FakeServer(port, incoming)
            return servers[port]

        deadline = time.monotonic() + WIRE_TIMEOUT_SEC

        def cubePublishedOrOutOfTime() -> bool:
            published = cubePort in servers and bool(servers[cubePort].images)
            return published or time.monotonic() > deadline

        dataset = acquisition_sim.loadRecordedCase(self.simulatorConfig)
        frameSource = StillFrameSource(self.simulatorConfig.samples, self.simulatorConfig.lines)
        acquisition_sim.serveRecordedCapture(
            self.simulatorConfig,
            frameSource,
            dataset,
            serverFactory=serverFactory,
            stopWhen=cubePublishedOrOutOfTime,
        )

        self.assertTrue(
            servers[cubePort].images,
            "The capture never published a cube, so nothing after it would prove anything.",
        )
        return servers

    def test_recordedSourceDoesNotWrite(self):
        before = support.folderFingerprint(self.caseFolder)

        self.runOneCapture()

        self.assertEqual(support.folderFingerprint(self.caseFolder), before)

    def test_standInOpensOnlyItsOwnPorts(self):
        servers = self.runOneCapture()

        self.assertEqual(
            set(servers),
            {DOCUMENTED_LIVE_VIEW_PORT, DOCUMENTED_HS_CUBE_PORT, DOCUMENTED_CONTROL_PORT},
        )
        for reservedPort in DOCUMENTED_RESERVED_PORTS:
            with self.subTest(reservedPort=reservedPort):
                self.assertNotIn(reservedPort, servers)

    def test_recordedNoticeNeverCallsTheCubeSynthetic(self):
        # The phantom's notice says the data is synthetic and not patient data.
        # Over a recorded case both claims are false, and false in the
        # direction that understates what is on screen.
        notice = acquisition_sim.recordedNotice(CASE_NAME)

        self.assertIn(CASE_NAME, notice)
        self.assertIn(support.RECORDED_DATABASE_MARKER, notice)
        lowered = notice.lower()
        self.assertIn("simulated", lowered)
        self.assertNotIn("synthetic", lowered)
        self.assertNotIn("not patient data", lowered)

    def test_recordedLiveViewIsLabelledAsTheLaptopCamera(self):
        servers = self.runOneCapture()

        liveViewImages = servers[DOCUMENTED_LIVE_VIEW_PORT].images
        self.assertTrue(liveViewImages, "No LiveView frame was sent.")
        detail = liveViewImages[0][2][contract.METADATA_SIMULATION_DETAIL_KEY]
        self.assertEqual(detail, EXPECTED_LIVE_VIEW_DETAIL)
        self.assertNotIn("synthetic", detail.lower())

    def test_recordedCommandLineTakesTheLaptopCameraByDefault(self):
        # The launcher passes `--frame-source webcam`; a person typing the
        # command should not have to, and must not get a generated scene.
        arguments = acquisition_sim.buildArgumentParser().parse_args(
            ["--scene-mode", "recorded", "--case", CASE_NAME]
        )

        self.assertEqual(acquisition_sim.commandLineOverrides(arguments)["frameSource"], "webcam")


class RecordedCaptureWireTest(unittest.TestCase):
    """The control channel and the cube over real pyigtl sockets.

    The controller tests prove the timing; these prove the transport carries
    it, which with pyigtl 0.3.4 is not a given. A server that only receives
    never lets go of a client that has left, so the next trigger client would
    wait in the accept backlog for ever.
    """

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporaryDirectory.cleanup)
        repositoryRoot = Path(self._temporaryDirectory.name).resolve()
        self.caseFolder = support.writeRecordedCaseFixture(
            repositoryRoot / "input" / "bin" / "bin" / CASE_NAME
        )

        ports: set[int] = set()
        while len(ports) < 3:
            ports.add(freeLocalPort())
        liveViewPort, hsCubePort, controlPort = sorted(ports)

        self.simulatorConfig = config.loadSimulatorConfig(
            repositoryRoot,
            overrides={
                "sceneMode": "recorded",
                "case": CASE_NAME,
                "frameSource": "webcam",
                "captureDelayMinSec": 0.0,
                "captureDelayMaxSec": 0.0,
                "targetFrameRate": 50.0,
                "liveViewPort": liveViewPort,
                "hsCubePort": hsCubePort,
                "controlPort": controlPort,
            },
        )

    def serveUntilClientsFinish(self, clients: list[threading.Thread]) -> None:
        for client in clients:
            client.start()
        deadline = time.monotonic() + 2 * WIRE_TIMEOUT_SEC

        dataset = acquisition_sim.loadRecordedCase(self.simulatorConfig)
        frameSource = StillFrameSource(self.simulatorConfig.samples, self.simulatorConfig.lines)
        acquisition_sim.serveRecordedCapture(
            self.simulatorConfig,
            frameSource,
            dataset,
            stopWhen=lambda: (
                all(not client.is_alive() for client in clients) or time.monotonic() > deadline
            ),
        )

        for client in clients:
            client.join(timeout=WIRE_TIMEOUT_SEC)
        self.assertFalse(any(client.is_alive() for client in clients), "A client did not finish.")

    def test_captureOverTheWireDeliversCubeAndReadiness(self):
        results = {}
        printed: list[str] = []

        def trigger():
            results["exitCode"] = capture_client.sendCaptureTrigger(
                port=self.simulatorConfig.controlPort,
                timeoutSec=WIRE_TIMEOUT_SEC,
                output=printed.append,
            )

        def receiveCube():
            client = pyigtl.OpenIGTLinkClient(host="127.0.0.1", port=self.simulatorConfig.hsCubePort)
            try:
                results["cube"] = client.wait_for_message(HS_CUBE_DEVICE_NAME, timeout=WIRE_TIMEOUT_SEC)
            finally:
                client.stop()

        self.serveUntilClientsFinish(
            [threading.Thread(target=receiveCube, daemon=True), threading.Thread(target=trigger, daemon=True)]
        )

        self.assertEqual(results.get("exitCode"), 0, printed)
        self.assertTrue(
            any(
                "READY capture=1 " in line and line.endswith(f"folder={self.caseFolder}")
                for line in printed
            ),
            printed,
        )

        cube = results.get("cube")
        self.assertIsNotNone(cube, "No HSCube message arrived.")
        shape = (support.TINY_DATASET_BANDS, support.TINY_DATASET_LINES, support.TINY_DATASET_SAMPLES)
        expected = numpy.frombuffer(
            (self.caseFolder / "raw.dat").read_bytes(), dtype="<u2"
        ).reshape(shape)
        # One uint16 component per voxel, bands along k: the raw counts as
        # recorded, not a calibrated or rendered derivative of them.
        self.assertEqual((cube.image.dtype.kind, cube.image.dtype.itemsize), ("u", 2))
        self.assertEqual(cube.image.shape[:3], shape)
        self.assertEqual(cube.image.size, expected.size)
        numpy.testing.assert_array_equal(cube.image.reshape(shape), expected)

        self.assertEqual(cube.metadata.get("SLIAFlow.DeviceName"), HS_CUBE_DEVICE_NAME)
        self.assertEqual(cube.metadata.get("SLIAFlow.DataOrigin"), "simulated")
        self.assertEqual(cube.metadata.get("SLIAFlow.SimulationDetail"), EXPECTED_CUBE_DETAIL)
        self.assertEqual(cube.metadata.get("SLIAFlow.DatasetFolder"), str(self.caseFolder))
        self.assertEqual(
            len(cube.metadata.get("SLIAFlow.WavelengthsNm", "").split(",")),
            support.TINY_DATASET_BANDS,
        )

    def test_successiveTriggerClientsAreEachServed(self):
        exitCodes: list[int] = []
        printed: list[str] = []

        def triggerThreeTimes():
            for _ in range(3):
                exitCodes.append(
                    capture_client.sendCaptureTrigger(
                        port=self.simulatorConfig.controlPort,
                        timeoutSec=WIRE_TIMEOUT_SEC / 2,
                        output=printed.append,
                    )
                )

        self.serveUntilClientsFinish([threading.Thread(target=triggerThreeTimes, daemon=True)])

        self.assertEqual(exitCodes, [0, 0, 0], printed)

    def test_aTriggerDuringACaptureIsAnsweredIgnoredOverTheWire(self):
        # The launcher's trigger clients leave once a capture has started. That
        # is what lets a second press reach the stand-in during the delay at
        # all, because pyigtl serves one client at a time.
        self.simulatorConfig = dataclasses.replace(
            self.simulatorConfig, captureDelayMinSec=4.0, captureDelayMaxSec=4.0
        )
        exitCodes: list[int] = []
        printed: list[str] = []

        def triggerTwiceWithoutWaiting():
            for _ in range(2):
                exitCodes.append(
                    capture_client.sendCaptureTrigger(
                        port=self.simulatorConfig.controlPort,
                        timeoutSec=WIRE_TIMEOUT_SEC / 2,
                        output=printed.append,
                        waitForReady=False,
                    )
                )

        self.serveUntilClientsFinish([threading.Thread(target=triggerTwiceWithoutWaiting, daemon=True)])

        # The documented exit codes: 0, the first trigger started capture 1;
        # 2, the second arrived inside its 4 s delay and was ignored.
        self.assertEqual(exitCodes, [0, 2], printed)
        self.assertTrue(
            any("IGNORED capture 1 already in progress" in line for line in printed), printed
        )


class StoppedInterrupt:
    """An `InterruptFlag` that has already been asked to stop."""

    requested = True

    def __enter__(self) -> StoppedInterrupt:
        return self

    def __exit__(self, *_arguments) -> None:
        return None


class AcquisitionPortTest(unittest.TestCase):
    """The stand-in's refusal of an occupied port, from its command line (SLIA-017)."""

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporaryDirectory.cleanup)
        repositoryRoot = Path(self._temporaryDirectory.name).resolve()
        support.writeRecordedCaseFixture(repositoryRoot / "input" / "bin" / "bin" / CASE_NAME)

        ports: set[int] = set()
        while len(ports) < 3:
            ports.add(freeLocalPort())
        self.liveViewPort, self.hsCubePort, self.controlPort = sorted(ports)

        self.simulatorConfig = config.loadSimulatorConfig(
            repositoryRoot,
            overrides={
                "sceneMode": "recorded",
                "case": CASE_NAME,
                "frameSource": "webcam",
                "captureDelayMinSec": 0.0,
                "captureDelayMaxSec": 0.0,
                "liveViewPort": self.liveViewPort,
                "hsCubePort": self.hsCubePort,
                "controlPort": self.controlPort,
            },
        )
        self.commandLine = ["--scene-mode", "recorded", "--case", CASE_NAME]

    def runMain(self, arguments, **patches) -> tuple[int, str]:
        errors = io.StringIO()
        with (
            mock.patch.object(
                acquisition_sim.config, "loadSimulatorConfig", return_value=self.simulatorConfig
            ),
            contextlib.ExitStack() as stack,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(errors),
        ):
            for target, attribute, patch in patches.values():
                stack.enter_context(mock.patch.object(target, attribute, **patch))
            exitCode = acquisition_sim.main(arguments)
        return exitCode, errors.getvalue()

    def test_anOccupiedPortExitsBeforeTheCameraOpens(self):
        # The cube port, the middle of the three, so that a check of LiveView
        # alone would not find it.
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", self.hsCubePort))
        holder.listen()

        # The override cannot join a holder that did not ask to share, so it has to
        # be refused before the camera too.
        for arguments in ([], ["--allow-shared-port"]):
            with self.subTest(arguments=arguments):
                camera = mock.Mock(side_effect=AssertionError("The camera was opened."))
                caseRead = mock.Mock(side_effect=AssertionError("The case was read."))
                exitCode, errors = self.runMain(
                    self.commandLine + arguments,
                    camera=(acquisition_sim.frames, "createFrameSource", {"new": camera}),
                    case=(acquisition_sim, "loadRecordedCase", {"new": caseRead}),
                )

                self.assertEqual(exitCode, 1, errors)
                self.assertIn(f"127.0.0.1:{self.hsCubePort}", errors)
                camera.assert_not_called()
                caseRead.assert_not_called()

    def test_aPortConfiguredForTwoChannelsExitsBeforeTheCameraOpens(self):
        # Probing each port on its own passes a port given twice, and the stand-in
        # then either failed on its second server after opening the camera or, with
        # the override, served two channels on one port.
        self.simulatorConfig = dataclasses.replace(
            self.simulatorConfig, controlPort=self.hsCubePort
        )
        for arguments in ([], ["--allow-shared-port"]):
            with self.subTest(arguments=arguments):
                camera = mock.Mock(side_effect=AssertionError("The camera was opened."))
                caseRead = mock.Mock(side_effect=AssertionError("The case was read."))
                exitCode, errors = self.runMain(
                    self.commandLine + arguments,
                    camera=(acquisition_sim.frames, "createFrameSource", {"new": camera}),
                    case=(acquisition_sim, "loadRecordedCase", {"new": caseRead}),
                )

                self.assertEqual(exitCode, 1, errors)
                self.assertIn("ERROR:", errors)
                self.assertIn(f"hsCubePort and controlPort are both {self.hsCubePort}", errors)
                camera.assert_not_called()
                caseRead.assert_not_called()

    def test_allowSharedPortReachesTheServers(self):
        for arguments, expected in (([], False), (["--allow-shared-port"], True)):
            with self.subTest(arguments=arguments):
                constructed: list[dict] = []

                def recordingServer(constructed=constructed, **serverArguments):
                    constructed.append(serverArguments)
                    return FakeServer(serverArguments["port"])

                exitCode, errors = self.runMain(
                    self.commandLine + arguments,
                    server=(
                        acquisition_sim.igtl_transport,
                        "ImageStreamServer",
                        {"side_effect": recordingServer},
                    ),
                    interrupt=(
                        acquisition_sim.igtl_transport,
                        "InterruptFlag",
                        {"return_value": StoppedInterrupt()},
                    ),
                    camera=(
                        acquisition_sim.frames,
                        "createFrameSource",
                        {
                            "return_value": StillFrameSource(
                                self.simulatorConfig.samples, self.simulatorConfig.lines
                            )
                        },
                    ),
                )

                self.assertEqual(exitCode, 0, errors)
                self.assertEqual(
                    sorted(serverArguments["port"] for serverArguments in constructed),
                    [self.liveViewPort, self.hsCubePort, self.controlPort],
                )
                for serverArguments in constructed:
                    self.assertIs(serverArguments.get("allowSharedPort", False), expected)


if __name__ == "__main__":
    unittest.main()
