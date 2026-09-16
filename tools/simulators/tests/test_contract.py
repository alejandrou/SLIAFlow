"""Producer/consumer seam tests."""

from __future__ import annotations

import contextlib
import importlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import contract, envi
from tests import support


class DatasetRefTest(unittest.TestCase):

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.workingRoot = Path(self._temporaryDirectory.name)
        self.addCleanup(self._temporaryDirectory.cleanup)

    def test_datasetRefIsReadFromARecordedCaseFolder(self):
        caseFolder = support.writeRecordedCaseFixture(self.workingRoot / "004-02")

        loadedRef = contract.loadDataset(caseFolder)

        self.assertEqual(loadedRef, envi.loadDataset(caseFolder))
        self.assertTrue(loadedRef.recorded)
        self.assertEqual(loadedRef.folder, caseFolder)
        self.assertEqual(
            (loadedRef.bands, loadedRef.lines, loadedRef.samples),
            (
                support.TINY_DATASET_BANDS,
                support.TINY_DATASET_LINES,
                support.TINY_DATASET_SAMPLES,
            ),
        )


class Uc1MapsTest(unittest.TestCase):

    def test_everyMapDefaultsToAbsent(self):
        maps = contract.Uc1Maps()

        for fieldName in contract.UC1_MAP_FIELD_NAMES:
            with self.subTest(fieldName=fieldName):
                self.assertIsNone(getattr(maps, fieldName))

    def test_aProducerMayPopulateOneMapOnly(self):
        # SLIA-013's real UC1 binary surfaces only the classification map. An
        # absent map means "this producer did not produce this map"; a consumer
        # must never substitute zeros for it.
        classMap = numpy.ones((2, 3), dtype=numpy.uint8)
        maps = contract.Uc1Maps(majorityVotingMap=classMap)

        self.assertIs(maps.majorityVotingMap, classMap)
        self.assertIsNone(maps.tmdMap)
        self.assertIsNone(maps.majorityVotingProbabilityMap)
        self.assertIsNone(maps.svmProbability)
        self.assertIsNone(maps.knnProbability)


class ClassifierProtocolTest(unittest.TestCase):

    def test_aDatasetFolderProducerSatisfiesTheProtocol(self):
        # The real producer is an executable that opens the dataset folder
        # itself, so the protocol has to accept a DatasetRef rather than a cube.
        class FolderPathClassifier:
            def classify(self, dataset: contract.DatasetRef) -> contract.Uc1Maps:
                assert dataset.folder is not None
                return contract.Uc1Maps()

        self.assertIsInstance(FolderPathClassifier(), contract.Classifier)

    def test_anArrayOnlyProducerDoesNotSatisfyTheProtocol(self):
        class CubeOnlyClassifier:
            def classifyCube(self, cube):
                return contract.Uc1Maps()

        self.assertNotIsInstance(CubeOnlyClassifier(), contract.Classifier)


class Uc1RgbMetadataTest(unittest.TestCase):

    def test_uc1RgbMetadataCarriesNoResultRole(self):
        # A result role would make the background discoverable as a result.
        # The expected keys are the wire names in
        # docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md, restated here.
        metadata = contract.uc1RgbMetadata(
            contract.DATA_ORIGIN_SIMULATED, simulationDetail="real UC1 pipeline",
            captureId="3f2a",
        )

        self.assertEqual(
            metadata,
            {
                "SLIAFlow.DeviceName": "UC1_RGB",
                "SLIAFlow.DataOrigin": "simulated",
                "SLIAFlow.SimulationDetail": "real UC1 pipeline",
                "SLIAFlow.CaptureId": "3f2a",
            },
        )
        self.assertNotIn(contract.METADATA_RESULT_MAP_KEY, metadata)
        with self.assertRaises(ValueError):
            contract.uc1RgbMetadata("camera", captureId="3f2a")

    def test_captureIdIsRequiredOnMapAndBackground(self):
        # ADR-0002: every map carries a capture ID, background or not. The
        # connector never removes an attribute a later message omits, so a map
        # sent without one would keep the previous run's and match that run's
        # retained background.
        rgbMetadata = contract.uc1RgbMetadata(
            contract.DATA_ORIGIN_SIMULATED, "real UC1 pipeline", captureId="3f2a"
        )
        mapMetadata = contract.resultMapMetadata(
            "majorityVotingMap", contract.DATA_ORIGIN_SIMULATED, "real UC1 pipeline",
            captureId="3f2a",
        )
        self.assertEqual(rgbMetadata["SLIAFlow.CaptureId"], "3f2a")
        self.assertEqual(mapMetadata["SLIAFlow.CaptureId"], "3f2a")

        builders = {
            "UC1_RGB": lambda **keywords: contract.uc1RgbMetadata(
                contract.DATA_ORIGIN_SIMULATED, **keywords
            ),
            "map": lambda **keywords: contract.resultMapMetadata(
                "majorityVotingMap", contract.DATA_ORIGIN_SIMULATED, **keywords
            ),
        }
        for name, build in builders.items():
            with self.subTest(name, captureId="absent"), self.assertRaises(TypeError):
                build()
            for captureId in ("", "   ", None):
                with self.subTest(name, captureId=captureId), self.assertRaises(ValueError):
                    build(captureId=captureId)

    def test_newCaptureIdIsNonEmptyAndNeverRepeats(self):
        captureIds = [contract.newCaptureId() for _ in range(100)]

        self.assertTrue(all(captureId.strip() for captureId in captureIds))
        self.assertEqual(len(set(captureIds)), len(captureIds))


class RetiredGeneratorsTest(unittest.TestCase):
    """SLIA-025: nothing in the package makes up a scene, a cube or a map."""

    RETIRED_MODULES = ("stratum_sim.tissue", "stratum_sim.uc1_sim")
    RETIRED_NAMES = {
        "frames": ("SyntheticFrameSource", "createFrameSource"),
        "spectra": ("reflectanceCube", "referenceCubes", "rawFromReflectance"),
        "envi": ("writeDataset", "writeSvmModel", "DATASET_MARKER"),
        "uc1_maps": ("deriveMaps", "ArithmeticClassifier", "validateMaps"),
    }

    def test_noGeneratorRemainsInThePackage(self):
        for moduleName in self.RETIRED_MODULES:
            with self.subTest(module=moduleName), self.assertRaises(ModuleNotFoundError):
                importlib.import_module(moduleName)

        for moduleName, names in self.RETIRED_NAMES.items():
            module = importlib.import_module(f"stratum_sim.{moduleName}")
            for name in names:
                with self.subTest(module=moduleName, name=name):
                    self.assertFalse(hasattr(module, name))

    def test_theArithmeticStandInIsNotASimulator(self):
        from stratum_sim import __main__ as entryPoint

        self.assertNotIn("uc1", entryPoint.SIMULATOR_NAMES)
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(entryPoint.main(["uc1"]), 1)
        self.assertIn("Unknown simulator 'uc1'", stderr.getvalue())
