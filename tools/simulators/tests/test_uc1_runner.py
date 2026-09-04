"""Tests for the genuine UC1 runner.

These run against recorded `output/rgb/*.txt` fixtures rather than the GPU, so
they need no CUDA toolkit and no device. The process itself is injected through
`processRunner`, which is the seam that lets a test reproduce a crashed run, a
stale output and an unmapped colour without owning a graphics card.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import numpy

from stratum_sim import bmp, contract, envi, spectra, tissue, uc1_maps, uc1_runner
from tests import support

# A 2x3 class map, one of every class plus a repeat, used as the recorded run.
FIXTURE_CLASS_MAP = numpy.array([[1, 2, 3], [4, 1, 2]], dtype=numpy.uint8)

STALE_SECONDS = 3600.0


def writeChannelFiles(directory: Path, rgb: numpy.ndarray) -> None:
    """Write the three channel files exactly as `writeMatrixRGB` writes them.

    Tab-separated integers, one row per line, with a trailing tab on each row.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for index, fileName in enumerate(uc1_runner.CHANNEL_FILE_NAMES):
        rows = ["".join(f"{int(value)}\t" for value in rgb[row, :, index]) for row in
                range(rgb.shape[0])]
        (directory / fileName).write_text("\n".join(rows) + "\n", encoding="ascii")


def makeStagedBuild(root: Path, modelBands: int = uc1_runner.UC1_MODEL_BAND_COUNT
                    ) -> uc1_runner.Uc1Build:
    """Create the staged layout the runner expects, with a placeholder binary.

    `svm_model/` sits exactly two levels above the source directory because
    `main.cu` opens the model as the literal relative path
    `../../svm_model/*.bin`, resolved against the working directory.

    The placeholder model files are written at their real byte sizes, not empty.
    An empty `w_vector.bin` is exactly the state the runner now refuses, so a
    fixture that used one would make every other test pass through the refusal
    path instead of the path it means to exercise.
    """
    build = uc1_runner.Uc1Build(root)
    build.sourceDirectory.mkdir(parents=True, exist_ok=True)
    build.executablePath.write_bytes(b"not a real binary")
    build.svmModelDirectory.mkdir(parents=True, exist_ok=True)
    for modelFileName, size in uc1_runner.MODEL_FILE_SIZES.items():
        if modelFileName == envi.WEIGHT_VECTOR_FILE_NAME:
            size = modelBands * envi.SVM_BINARY_CLASSIFIER_COUNT * 4
        (build.svmModelDirectory / modelFileName).write_bytes(bytes(size))
    return build


def makeMarkedDataset(
    datasetFolder: Path,
    samples: int,
    lines: int,
    bands: int = uc1_runner.UC1_MODEL_BAND_COUNT,
) -> contract.DatasetRef:
    """Write a small marked dataset with the shape the fixtures describe.

    The band count defaults to the one the staged SVM model is sized for. A
    fixture with a convenient four bands would exercise a configuration the real
    binary cannot serve, and would hide the failure it produces on the GPU: UC1
    reads `numberOfBands` weights per classifier out of a file sized for 93 and
    never checks how many it got.
    """
    shape = (bands, lines, samples)
    envi.writeDataset(
        datasetFolder,
        numpy.full(shape, 2500, dtype=numpy.uint16),
        numpy.full(shape, 5000, dtype=numpy.uint16),
        numpy.full(shape, 1000, dtype=numpy.uint16),
        numpy.linspace(400.482, 1000.73, bands, dtype=numpy.float64),
    )
    return contract.loadDataset(datasetFolder)


class RecordedRun:
    """A stand-in for the real process, writing whichever outputs a test needs."""

    def __init__(
        self,
        build: uc1_runner.Uc1Build,
        datasetName: str,
        rgb: numpy.ndarray | None,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        ageSeconds: float = 0.0,
        writeClassImage: bool = True,
    ) -> None:
        self.build = build
        self.datasetName = datasetName
        self.rgb = rgb
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.ageSeconds = ageSeconds
        self.writeClassImage = writeClassImage
        self.commands: list[list[str]] = []
        self.workingDirectories: list[Path] = []

    def __call__(self, command: list[str], cwd: Path) -> uc1_runner.ProcessResult:
        self.commands.append(list(command))
        self.workingDirectories.append(Path(cwd))

        if self.rgb is not None:
            writeChannelFiles(self.build.rgbOutputDirectory, self.rgb)
            if self.writeClassImage:
                datasetOutput = self.build.datasetOutputDirectory(self.datasetName)
                datasetOutput.mkdir(parents=True, exist_ok=True)
                bmp.writeBMP(
                    datasetOutput / uc1_runner.CLASS_IMAGE_FILE_NAME,
                    self.rgb[..., 0],
                    self.rgb[..., 1],
                    self.rgb[..., 2],
                )
            if self.ageSeconds:
                self._backdateOutputs()

        return uc1_runner.ProcessResult(self.returncode, self.stdout, self.stderr)

    def _backdateOutputs(self) -> None:
        """Make this run's files look like a previous run's leftovers."""
        datasetOutput = self.build.datasetOutputDirectory(self.datasetName)
        paths = [self.build.rgbOutputDirectory / name for name in uc1_runner.CHANNEL_FILE_NAMES]
        paths.append(datasetOutput / uc1_runner.CLASS_IMAGE_FILE_NAME)
        for path in paths:
            if path.is_file():
                stamp = path.stat().st_mtime - self.ageSeconds
                os.utime(path, (stamp, stamp))


class Uc1RunnerTestCase(unittest.TestCase):
    """Set up a staged build and a marked dataset shaped like the fixture."""

    def setUp(self) -> None:
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        root = Path(self._temporaryDirectory.name)
        self.build = makeStagedBuild(root / "build" / "uc1" / "UC1")
        lines, samples = FIXTURE_CLASS_MAP.shape
        self.dataset = makeMarkedDataset(root / "sim-20260903-000000", samples, lines)
        self.datasetName = self.dataset.folder.name
        self.rgb = bmp.classMapToRgb(FIXTURE_CLASS_MAP)

    def tearDown(self) -> None:
        self._temporaryDirectory.cleanup()

    def classifyWith(self, process: RecordedRun, **keywords) -> contract.Uc1Maps:
        classifier = uc1_runner.RealUc1Classifier(
            build=self.build, processRunner=process, **keywords
        )
        return classifier.classify(self.dataset)

    def outputPath(self, fileName: str) -> Path:
        if fileName == uc1_runner.CLASS_IMAGE_FILE_NAME:
            return self.build.datasetOutputDirectory(self.datasetName) / fileName
        return self.build.rgbOutputDirectory / fileName

    def processWithOutputMutation(
        self, fileName: str, mutation: Callable[[Path], None]
    ) -> Callable[[list[str], Path], uc1_runner.ProcessResult]:
        recordedRun = RecordedRun(self.build, self.datasetName, self.rgb)

        def run(command: list[str], cwd: Path) -> uc1_runner.ProcessResult:
            result = recordedRun(command, cwd)
            mutation(self.outputPath(fileName))
            return result

        return run


class RecoveredMapTest(Uc1RunnerTestCase):
    def test_recoveredClassMapMatchesContract(self) -> None:
        process = RecordedRun(self.build, self.datasetName, self.rgb)

        maps = self.classifyWith(process)

        lines, samples = FIXTURE_CLASS_MAP.shape
        classMap = maps.majorityVotingMap
        self.assertEqual(classMap.shape, (1, lines, samples))
        self.assertEqual(classMap.dtype, numpy.uint8)
        self.assertTrue(set(numpy.unique(classMap).tolist()).issubset({1, 2, 3, 4}))
        self.assertTrue(numpy.array_equal(classMap[0], FIXTURE_CLASS_MAP))

        # The real binary computes and then discards the other four. An absent
        # map must stay absent; a zero-filled map would be a fabricated result.
        self.assertEqual(maps.presentMapNames(), ("majorityVotingMap",))
        for name in ("tmdMap", "majorityVotingProbabilityMap", "svmProbability",
                     "knnProbability"):
            self.assertIsNone(getattr(maps, name))

        # The pipeline takes the dataset folder and nothing else, and it is
        # CWD-bound: `parameters.txt` and `../../svm_model/*.bin` are both
        # resolved against the staged source directory.
        self.assertEqual(len(process.commands), 1)
        self.assertEqual(
            process.commands[0],
            [str(self.build.executablePath), str(self.dataset.folder)],
        )
        self.assertEqual(process.workingDirectories[0], self.build.sourceDirectory)

    def test_recoveredMapPassesTheSharedContractCheck(self) -> None:
        process = RecordedRun(self.build, self.datasetName, self.rgb)

        maps = self.classifyWith(process)

        uc1_maps.validateMajorityVotingMap(maps.majorityVotingMap)


class OutputValidationTest(Uc1RunnerTestCase):
    @staticmethod
    def requiredOutputNames() -> tuple[str, ...]:
        return (*uc1_runner.CHANNEL_FILE_NAMES, uc1_runner.CLASS_IMAGE_FILE_NAME)

    def test_eachRequiredOutputMustBeFresh(self) -> None:
        def backdate(path: Path) -> None:
            stamp = path.stat().st_mtime - STALE_SECONDS
            os.utime(path, (stamp, stamp))

        for fileName in self.requiredOutputNames():
            with self.subTest(fileName=fileName):
                process = self.processWithOutputMutation(fileName, backdate)
                with self.assertRaises(uc1_runner.Uc1StaleOutputError) as caught:
                    self.classifyWith(process)
                self.assertIn(fileName, str(caught.exception))

    def test_eachRequiredOutputMustExist(self) -> None:
        for fileName in self.requiredOutputNames():
            with self.subTest(fileName=fileName):
                process = self.processWithOutputMutation(fileName, Path.unlink)
                with self.assertRaises(uc1_runner.Uc1OutputMissingError) as caught:
                    self.classifyWith(process)
                self.assertIn(fileName, str(caught.exception))

    def test_eachChannelRejectsEmptyAndMalformedContent(self) -> None:
        corruptions = {
            "empty": b"",
            "malformed": b"not-a-number\n",
        }
        for fileName in uc1_runner.CHANNEL_FILE_NAMES:
            for corruption, content in corruptions.items():
                with self.subTest(fileName=fileName, corruption=corruption):
                    process = self.processWithOutputMutation(
                        fileName, lambda path, data=content: path.write_bytes(data)
                    )
                    with self.assertRaises(uc1_runner.Uc1OutputMissingError) as caught:
                        self.classifyWith(process)
                    self.assertIn(fileName, str(caught.exception))

    def test_eachChannelRejectsAnIndividualShapeMismatch(self) -> None:
        for fileName in uc1_runner.CHANNEL_FILE_NAMES:
            with self.subTest(fileName=fileName):
                process = self.processWithOutputMutation(
                    fileName, lambda path: path.write_text("1\t2\n", encoding="ascii")
                )
                with self.assertRaises(uc1_runner.Uc1OutputMissingError) as caught:
                    self.classifyWith(process)
                message = str(caught.exception)
                self.assertIn(fileName, message)
                self.assertIn("shape", message)

    def test_pathTooLongOnStderrFails(self) -> None:
        process = RecordedRun(
            self.build, self.datasetName, self.rgb, stderr="Path too long\n"
        )

        with self.assertRaises(uc1_runner.Uc1ProcessFailedError) as caught:
            self.classifyWith(process)

        self.assertIn(uc1_runner.PATH_TOO_LONG_MARKER, str(caught.exception))


class PaletteInverseTest(Uc1RunnerTestCase):
    def test_unmappedTripleIsReportedNotGuessed(self) -> None:
        unmapped = self.rgb.copy()
        unmapped[0, 1] = (128, 128, 0)
        unmapped[1, 2] = (10, 250, 10)
        process = RecordedRun(self.build, self.datasetName, unmapped)

        with self.assertRaises(uc1_runner.Uc1PaletteError) as caught:
            self.classifyWith(process)

        message = str(caught.exception)
        self.assertIn("2 pixel(s)", message)
        self.assertIn("(0, 1)", message)
        self.assertIn("(128, 128, 0)", message)

    def test_paletteInverseIsTheSharedTable(self) -> None:
        # One definition, read forward in SLIA-012 and backward here. A second
        # table written independently is the drift this shares away.
        self.assertIs(uc1_runner.RGB_TO_CLASS, bmp.RGB_TO_CLASS)


class ProcessFailureTest(Uc1RunnerTestCase):
    def test_nonZeroExitFailsLoudly(self) -> None:
        process = RecordedRun(
            self.build, self.datasetName, self.rgb, returncode=3, stderr="CUDA error 999\n"
        )

        with self.assertRaises(uc1_runner.Uc1ProcessFailedError) as caught:
            self.classifyWith(process)

        message = str(caught.exception)
        self.assertIn("code 3", message)
        self.assertIn("CUDA error 999", message)

        # The failure mode this card forbids: a runner that falls back to the
        # arithmetic stand-in would have returned five valid maps here, and the
        # operator would believe the real pipeline ran. The assertRaises above
        # proves that no map result was returned.


class MarkerInterlockTest(Uc1RunnerTestCase):
    def test_unmarkedDatasetIsRefused(self) -> None:
        headerPath = self.dataset.folder / envi.HEADER_FILE_NAME
        headerPath.write_text(
            headerPath.read_text(encoding="ascii").replace(envi.DATASET_MARKER, "UNMARKED"),
            encoding="ascii",
        )
        self.dataset = contract.loadDataset(self.dataset.folder)
        process = RecordedRun(self.build, self.datasetName, self.rgb)

        with self.assertRaises(uc1_maps.SimulatedMarkerRequiredError) as caught:
            self.classifyWith(process)

        self.assertIn(envi.DATASET_MARKER, str(caught.exception))
        self.assertEqual(process.commands, [])

        maps = self.classifyWith(process, requireSimulatedMarker=False)
        self.assertEqual(maps.presentMapNames(), ("majorityVotingMap",))


class ExclusiveLockTest(Uc1RunnerTestCase):
    def test_secondRunnerIsRefusedWhileOneHoldsTheBuild(self) -> None:
        # `output/rgb/*.txt` are three fixed names shared by every dataset, so
        # two runners in one staged build would interleave writes into the same
        # three files and each would read the other's output.
        with self.build.exclusiveLock():
            process = RecordedRun(self.build, self.datasetName, self.rgb)
            with self.assertRaises(uc1_runner.Uc1BusyError) as caught:
                self.classifyWith(process)

        self.assertIn(uc1_runner.LOCK_FILE_NAME, str(caught.exception))

        # The lock is released on the way out, so the next run proceeds.
        maps = self.classifyWith(RecordedRun(self.build, self.datasetName, self.rgb))
        self.assertEqual(maps.presentMapNames(), ("majorityVotingMap",))


class WireMetadataTest(Uc1RunnerTestCase):
    def test_realRunnerSendsOnlyTheClassMapWithCompleteProvenance(self) -> None:
        maps = self.classifyWith(RecordedRun(self.build, self.datasetName, self.rgb))

        messages = list(uc1_runner.mapMessages(maps))

        self.assertEqual(len(messages), 1)
        image, deviceName, metadata = messages[0]
        self.assertEqual(deviceName, "UC1_MV_CLASS")
        self.assertTrue(numpy.array_equal(image, maps.majorityVotingMap))
        self.assertEqual(
            metadata,
            {
                contract.METADATA_RESULT_MAP_KEY: "majorityVotingMap",
                contract.METADATA_DEVICE_NAME_KEY: "UC1_MV_CLASS",
                contract.METADATA_DATA_ORIGIN_KEY: contract.DATA_ORIGIN_SIMULATED,
                contract.METADATA_SIMULATION_DETAIL_KEY: "real UC1 pipeline, synthetic input",
            },
        )
        self.assertEqual(uc1_runner.SIMULATION_DETAIL, "real UC1 pipeline, synthetic input")


class BuildLayoutTest(Uc1RunnerTestCase):
    def test_missingExecutableIsNamedRatherThanGuessed(self) -> None:
        self.build.executablePath.unlink()
        process = RecordedRun(self.build, self.datasetName, self.rgb)

        with self.assertRaises(uc1_runner.Uc1BuildMissingError) as caught:
            self.classifyWith(process)

        self.assertIn(uc1_runner.EXECUTABLE_NAME, str(caught.exception))
        self.assertIn("build-uc1.ps1", str(caught.exception))

    def test_previousOutputsAreRemovedBeforeTheRun(self) -> None:
        # A crashed run that leaves last week's files behind must not be able to
        # satisfy the next run, so the deletion happens before the process
        # starts rather than after it fails.
        writeChannelFiles(self.build.rgbOutputDirectory, bmp.classMapToRgb(FIXTURE_CLASS_MAP))
        datasetOutput = self.build.datasetOutputDirectory(self.datasetName)
        datasetOutput.mkdir(parents=True, exist_ok=True)
        (datasetOutput / "leftover.bmp").write_bytes(b"stale")

        seen: dict[str, bool] = {}

        def observe(command: list[str], cwd: Path) -> uc1_runner.ProcessResult:
            seen["channelsPresent"] = any(
                (self.build.rgbOutputDirectory / name).exists()
                for name in uc1_runner.CHANNEL_FILE_NAMES
            )
            seen["leftoverPresent"] = (datasetOutput / "leftover.bmp").exists()
            return RecordedRun(self.build, self.datasetName, self.rgb)(command, cwd)

        self.classifyWith(observe)

        self.assertFalse(seen["channelsPresent"])
        self.assertFalse(seen["leftoverPresent"])


class ModelCompatibilityTest(Uc1RunnerTestCase):
    """The staged model is sized for one band count and cannot say so itself."""

    def test_datasetWithADifferentBandCountIsRefusedBeforeTheProcessStarts(self) -> None:
        # 40 bands is inside everything the acquisition stand-in documents - the
        # floor is 8 - so this is reachable from a supported configuration, not
        # from a corrupted file. UC1 would read 40 weights per classifier out of
        # a file holding 93 and produce a map that looks exactly like a result.
        lines, samples = FIXTURE_CLASS_MAP.shape
        dataset = makeMarkedDataset(
            self.dataset.folder.parent / "sim-20260903-000001", samples, lines, bands=40
        )
        process = RecordedRun(self.build, dataset.folder.name, self.rgb)
        classifier = uc1_runner.RealUc1Classifier(build=self.build, processRunner=process)

        with self.assertRaises(uc1_runner.Uc1ModelMismatchError) as raised:
            classifier.classify(dataset)

        message = str(raised.exception)
        self.assertIn("40 bands", message)
        self.assertIn(str(uc1_runner.UC1_MODEL_BAND_COUNT), message)
        # Refused before anything ran: a partial run would leave outputs behind.
        self.assertEqual(process.commands, [])

    def test_datasetOwnSvmModelIsNotAcceptedAsASubstitute(self) -> None:
        # `envi.writeDataset` puts a correctly sized model inside the dataset
        # folder, which is not where UC1 looks. Its presence must not make the
        # band-count check pass.
        lines, samples = FIXTURE_CLASS_MAP.shape
        dataset = makeMarkedDataset(
            self.dataset.folder.parent / "sim-20260903-000002", samples, lines, bands=40
        )
        self.assertTrue((dataset.folder / envi.SVM_MODEL_DIRECTORY_NAME).is_dir())

        classifier = uc1_runner.RealUc1Classifier(
            build=self.build, processRunner=RecordedRun(self.build, dataset.folder.name, self.rgb)
        )
        with self.assertRaises(uc1_runner.Uc1ModelMismatchError):
            classifier.classify(dataset)

    def test_eachMissingModelFileIsNamed(self) -> None:
        for fileName, expectedSize in uc1_runner.MODEL_FILE_SIZES.items():
            with self.subTest(fileName=fileName):
                modelPath = self.build.svmModelDirectory / fileName
                modelPath.unlink()
                process = RecordedRun(self.build, self.datasetName, self.rgb)
                try:
                    with self.assertRaises(uc1_runner.Uc1ModelMismatchError) as raised:
                        self.classifyWith(process)
                    self.assertIn(fileName, str(raised.exception))
                    self.assertEqual(process.commands, [])
                finally:
                    modelPath.write_bytes(bytes(expectedSize))

    def test_eachWrongSizeModelFileIsNamed(self) -> None:
        # `main.cu` never checks how many elements `fread` returned, so a short
        # file classifies against whatever was already in the buffer.
        for fileName, expectedSize in uc1_runner.MODEL_FILE_SIZES.items():
            with self.subTest(fileName=fileName):
                modelPath = self.build.svmModelDirectory / fileName
                modelPath.write_bytes(bytes(expectedSize - 1))
                process = RecordedRun(self.build, self.datasetName, self.rgb)
                try:
                    with self.assertRaises(uc1_runner.Uc1ModelMismatchError) as raised:
                        self.classifyWith(process)
                    self.assertIn(fileName, str(raised.exception))
                    self.assertEqual(process.commands, [])
                finally:
                    modelPath.write_bytes(bytes(expectedSize))

    def test_theStagedModelShippedWithThePipelineHasTheExpectedSizes(self) -> None:
        # The sizes above are a claim about the vendored model, so it is checked
        # against the real one rather than only against a fixture this file
        # wrote. Skipped where the vendored tree is not in the checkout.
        vendoredModel = support.vendoredSvmModelDirectory()
        if vendoredModel is None:
            self.skipTest("The vendored UC1 svm_model is not present in this checkout")

        for fileName, expectedSize in uc1_runner.MODEL_FILE_SIZES.items():
            with self.subTest(fileName=fileName):
                self.assertEqual((vendoredModel / fileName).stat().st_size, expectedSize)


class SceneProvenanceTest(Uc1RunnerTestCase):
    """A result node has to be able to say which scene the pipeline was fed."""

    def test_phantomDatasetIsNamedOnTheWire(self) -> None:
        tissue.writePhantomRecord(
            self.dataset.folder, tissue.phantomRegionMap(*FIXTURE_CLASS_MAP.shape)
        )
        maps = self.classifyWith(RecordedRun(self.build, self.datasetName, self.rgb))

        detail = uc1_runner.simulationDetailForDataset(self.dataset)
        self.assertEqual(detail, uc1_runner.SIMULATION_DETAIL_PHANTOM)
        self.assertIn("tissue phantom", detail)

        (_, _, metadata), = uc1_runner.mapMessages(maps, detail)
        self.assertEqual(metadata[contract.METADATA_SIMULATION_DETAIL_KEY], detail)
        # The origin never softens because the algorithm is genuine.
        self.assertEqual(
            metadata[contract.METADATA_DATA_ORIGIN_KEY], contract.DATA_ORIGIN_SIMULATED
        )

    def test_datasetWithoutAPhantomRecordKeepsTheOriginalDetail(self) -> None:
        self.assertEqual(
            uc1_runner.simulationDetailForDataset(self.dataset), uc1_runner.SIMULATION_DETAIL
        )
        self.assertEqual(uc1_runner.SIMULATION_DETAIL, "real UC1 pipeline, synthetic input")

    def test_theTwoDetailsAreDistinguishable(self) -> None:
        self.assertNotEqual(uc1_runner.SIMULATION_DETAIL, uc1_runner.SIMULATION_DETAIL_PHANTOM)

    def test_sendFailureDoesNotReportACompleteMapSet(self) -> None:
        maps = self.classifyWith(RecordedRun(self.build, self.datasetName, self.rgb))

        class RejectingServer:
            def __init__(self):
                self.calls = []

            def sendImage(self, image, deviceName, metadata):
                self.calls.append((image, deviceName, metadata))
                return False

        server = RejectingServer()
        self.assertFalse(uc1_runner.sendMaps(server, maps))
        self.assertEqual(len(server.calls), 1)

    def test_servicePropagatesBothDatasetSceneDetails(self) -> None:
        class Classifier:
            def __init__(self, maps):
                self.maps = maps

            def classify(self, _dataset):
                return self.maps

        class Context:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self.value

            def __exit__(self, *_args):
                return False

        class Server:
            isConnected = True

        class Interrupt:
            requested = False

        maps = self.classifyWith(RecordedRun(self.build, self.datasetName, self.rgb))
        for isPhantom, expectedDetail in (
            (False, uc1_runner.SIMULATION_DETAIL),
            (True, uc1_runner.SIMULATION_DETAIL_PHANTOM),
        ):
            with self.subTest(isPhantom=isPhantom):
                recordPaths = ()
                if isPhantom:
                    recordPaths = tissue.writePhantomRecord(
                        self.dataset.folder,
                        tissue.phantomRegionMap(*FIXTURE_CLASS_MAP.shape),
                    )
                observedDetails = []
                try:
                    with (
                        mock.patch.object(
                            uc1_runner.igtl_transport,
                            "ImageStreamServer",
                            return_value=Context(Server()),
                        ),
                        mock.patch.object(
                            uc1_runner.igtl_transport,
                            "InterruptFlag",
                            return_value=Context(Interrupt()),
                        ),
                        mock.patch.object(
                            uc1_runner,
                            "sendMaps",
                            side_effect=lambda _server, _maps, detail, observed=observedDetails: (
                                observed.append(detail) or True
                            ),
                        ),
                    ):
                        completed = uc1_runner.streamMaps(
                            self.dataset, Classifier(maps), cycles=1, intervalSec=0.0
                        )
                finally:
                    for recordPath in recordPaths:
                        recordPath.unlink(missing_ok=True)

                self.assertEqual(completed, 1)
                self.assertEqual(observedDetails, [expectedDetail])


class RealBinaryIntegrationTest(unittest.TestCase):
    """Exercise the parts the injected process cannot reach.

    Every other test in this file replaces the process, which is what makes them
    fast and GPU-free - but it also means they never touch model loading, CUDA
    execution, UC1's own path handling, or the creation of real output files.
    This one runs the staged binary for real. It skips rather than fails where
    the build has not been run: `build/` is absent on a fresh clone and the CUDA
    toolchain is not a checkout prerequisite.

    It mutates the shared staged build, taking the same exclusive lock and
    clearing the same fixed output paths as any other run, so it cannot run
    beside a live sender - which is the behaviour the lock exists to enforce.
    """

    SAMPLES = 32
    LINES = 24

    @classmethod
    def setUpClass(cls) -> None:
        if support.stagedUc1Executable() is None:
            raise unittest.SkipTest(
                "The staged UC1 build is absent; run scripts/development/build-uc1.ps1"
            )

    def setUp(self) -> None:
        # Written under `build/` rather than the system temporary directory:
        # `data_loader.cpp` reads header and file paths into a 128-byte buffer,
        # and a temporary path is long enough to trip that on this machine.
        self.datasetFolder = (
            support.STAGED_UC1_BUILD_ROOT.parent / "integration" / "sim-20260101-000000"
        )
        if self.datasetFolder.exists():
            shutil.rmtree(self.datasetFolder)

        wavelengthsNm = spectra.bandWavelengthsNm(uc1_runner.UC1_MODEL_BAND_COUNT)
        regionMap = tissue.phantomRegionMap(self.LINES, self.SAMPLES)
        reflectance = tissue.phantomReflectanceCube(regionMap, wavelengthsNm)
        rng = numpy.random.default_rng(20260904)
        darkCube, whiteCube = spectra.referenceCubes(
            rng, uc1_runner.UC1_MODEL_BAND_COUNT, self.LINES, self.SAMPLES
        )
        rawCube = spectra.rawFromReflectance(reflectance, darkCube, whiteCube)
        self.dataset = envi.writeDataset(
            self.datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm
        )

        pathLength = envi.uc1WhiteReferencePathLength(self.dataset.folder)
        if pathLength >= envi.UC1_MAX_PATH_LENGTH:
            self.skipTest(
                f"The dataset path is {pathLength} characters, at or over UC1's "
                f"{envi.UC1_MAX_PATH_LENGTH}-byte buffer"
            )

    def tearDown(self) -> None:
        shutil.rmtree(self.datasetFolder.parent, ignore_errors=True)

    def test_stagedBinaryClassifiesARealDatasetOnTheGpu(self) -> None:
        build = uc1_runner.Uc1Build(support.STAGED_UC1_BUILD_ROOT)
        classifier = uc1_runner.RealUc1Classifier(build=build)

        maps = classifier.classify(self.dataset)

        classMap = maps.majorityVotingMap
        self.assertEqual(classMap.shape, (1, self.LINES, self.SAMPLES))
        self.assertEqual(classMap.dtype, numpy.uint8)
        self.assertTrue(set(numpy.unique(classMap).tolist()).issubset({1, 2, 3, 4}))
        uc1_maps.validateMajorityVotingMap(classMap)
        self.assertEqual(maps.presentMapNames(), ("majorityVotingMap",))

        # Real files, written by the real process, on this run's clock. The
        # injected process writes these too, so only here do they prove that
        # UC1's own output paths resolved.
        for path in (*build.channelPaths(),
                     build.datasetOutputDirectory(self.dataset.folder.name)
                     / uc1_runner.CLASS_IMAGE_FILE_NAME):
            self.assertTrue(path.is_file(), f"{path} was not written")
            self.assertGreater(path.stat().st_size, 0)

    def test_stagedModelIsTheOneTheRunnerRequires(self) -> None:
        # Model loading is silent in `main.cu`: a wrong-sized file produces no
        # diagnostic, only different numbers. The check is on the staged copy
        # the binary actually opens.
        uc1_runner.Uc1Build(support.STAGED_UC1_BUILD_ROOT).assertModelIsIntact()


if __name__ == "__main__":
    unittest.main()
