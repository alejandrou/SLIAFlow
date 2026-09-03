"""Producer/consumer seam tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import contract, envi
from tests.test_envi import TEST_BANDS, TEST_LINES, TEST_SAMPLES, buildTinyCubes


class DatasetRefTest(unittest.TestCase):

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.workingRoot = Path(self._temporaryDirectory.name)
        self.addCleanup(self._temporaryDirectory.cleanup)

    def test_datasetRefRoundTripsFromWrittenFolder(self):
        datasetFolder = self.workingRoot / "sim-20260902-101112"
        rawCube, whiteCube, darkCube, wavelengthsNm = buildTinyCubes()

        writtenRef = envi.writeDataset(datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
        loadedRef = contract.loadDataset(datasetFolder)

        self.assertEqual(writtenRef, loadedRef)
        self.assertTrue(loadedRef.simulated)
        self.assertEqual(loadedRef.folder, datasetFolder.resolve())

        calibrated = loadedRef.loadCalibratedCube()
        self.assertEqual(calibrated.shape, (TEST_BANDS, TEST_LINES, TEST_SAMPLES))
        self.assertEqual(calibrated.dtype, numpy.float32)
        self.assertTrue(bool(numpy.all(numpy.isfinite(calibrated))))


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
