"""Tests for the non-clinical UC1 arithmetic stand-in."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy

from stratum_sim import contract, envi, uc1_maps, uc1_sim


class Uc1MapTest(unittest.TestCase):
    def setUp(self) -> None:
        wavelengthsNm = numpy.array([450.0, 520.0, 620.0, 750.0], dtype=numpy.float64)
        calibratedCube = numpy.array(
            [
                [[10.0, 20.0], [30.0, 40.0]],
                [[20.0, 30.0], [40.0, 50.0]],
                [[60.0, 70.0], [80.0, 90.0]],
                [[40.0, 50.0], [60.0, 70.0]],
            ],
            dtype=numpy.float32,
        )
        self.maps = uc1_maps.deriveMaps(calibratedCube, wavelengthsNm)

    def test_derivedMapsAreSelfConsistent(self) -> None:
        maps = self.maps

        self.assertEqual(maps.svmProbability.shape, (1, 2, 2, 4))
        self.assertEqual(maps.knnProbability.shape, (1, 2, 2, 4))
        self.assertEqual(maps.tmdMap.shape, (1, 2, 2))
        self.assertEqual(maps.majorityVotingMap.shape, (1, 2, 2))
        self.assertEqual(maps.majorityVotingProbabilityMap.shape, (1, 2, 2))
        self.assertEqual(maps.svmProbability.dtype, numpy.float32)
        self.assertEqual(maps.knnProbability.dtype, numpy.float32)
        self.assertEqual(maps.tmdMap.dtype, numpy.float32)
        self.assertEqual(maps.majorityVotingProbabilityMap.dtype, numpy.float32)
        self.assertEqual(maps.majorityVotingMap.dtype, numpy.uint8)

        mean = (maps.svmProbability + maps.knnProbability) / 2
        expectedClasses = numpy.argmax(mean, axis=-1).astype(numpy.uint8) + 1
        self.assertTrue(numpy.allclose(maps.svmProbability.sum(axis=-1), 1.0, atol=1e-5))
        self.assertTrue(numpy.allclose(maps.knnProbability.sum(axis=-1), 1.0, atol=1e-5))
        self.assertTrue(numpy.array_equal(maps.majorityVotingMap, expectedClasses))
        self.assertTrue(
            numpy.allclose(maps.majorityVotingProbabilityMap, numpy.max(mean, axis=-1))
        )
        self.assertTrue(numpy.allclose(maps.tmdMap, mean[..., 1]))
        self.assertTrue(set(numpy.unique(maps.majorityVotingMap)).issubset({1, 2, 3, 4}))

    def test_contractCheckRejectsCorruptedMaps(self) -> None:
        validMaps = self.maps
        uc1_maps.validateMaps(validMaps)

        brokenMaps = []

        corruptedSvm = validMaps.svmProbability.copy()
        corruptedSvm[0, 0, 0, 0] = numpy.nan
        brokenMaps.append(("svm probability", replace(validMaps, svmProbability=corruptedSvm)))

        corruptedKnn = validMaps.knnProbability.copy()
        corruptedKnn[0, 0, 0, 0] = numpy.nan
        brokenMaps.append(("knn probability", replace(validMaps, knnProbability=corruptedKnn)))

        corruptedClass = validMaps.majorityVotingMap.copy()
        corruptedClass[0, 0, 0] = 5
        brokenMaps.append(("class map", replace(validMaps, majorityVotingMap=corruptedClass)))

        corruptedProbability = validMaps.majorityVotingProbabilityMap.copy()
        corruptedProbability[0, 0, 0] = 0.0
        brokenMaps.append(
            (
                "majority probability map",
                replace(validMaps, majorityVotingProbabilityMap=corruptedProbability),
            )
        )

        corruptedTmd = validMaps.tmdMap.copy()
        corruptedTmd[0, 0, 0] += numpy.float32(0.01)
        brokenMaps.append(("TMD map", replace(validMaps, tmdMap=corruptedTmd)))

        for name, maps in brokenMaps:
            with self.subTest(name=name):
                with self.assertRaises(uc1_maps.MapContractError):
                    uc1_maps.validateMaps(maps)

    def test_moduleDocstringStatesItIsNotAClassifier(self) -> None:
        # The whole sentence is asserted, not a prefix of it. "was never
        # validated" and "no diagnostic meaning whatsoever" are the two clauses
        # the medical-data policy actually turns on, and a prefix assertion
        # would keep passing with both of them deleted.
        expectedFirstLine = (
            "This is not a classifier. It is a fixed arithmetic rule with hand-chosen "
            "constants, written so that a demo pipeline has something to draw. It was not "
            "fitted to data, it was never validated, and its output has no diagnostic "
            "meaning whatsoever."
        )
        self.assertEqual(uc1_maps.__doc__.splitlines()[0], expectedFirstLine)
        self.assertEqual(uc1_maps.NON_CLASSIFIER_NOTICE, expectedFirstLine)
        self.assertIsInstance(uc1_maps.ARBITRARY_CONSTANTS, dict)
        self.assertIn("not a classifier", uc1_maps.ARBITRARY_CONSTANTS["description"])

        # The per-cycle stdout banner and the wire-level detail are two more of
        # the redundant "not a classifier" signals the task requires.
        self.assertIn("not a classifier", uc1_sim.CYCLE_BANNER.format(cycle=1))
        self.assertIn("SIMULATED", uc1_sim.CYCLE_BANNER.format(cycle=1))
        self.assertEqual(uc1_sim.SIMULATION_DETAIL, "arithmetic stand-in, not a classifier")
        self.assertIn("not a classifier", uc1_sim.SIMULATION_NOTICE)

    def test_unmarkedCubeIsRefusedWithoutForceFlag(self) -> None:
        with tempfile.TemporaryDirectory() as temporaryDirectory:
            datasetFolder = Path(temporaryDirectory) / "dataset"
            shape = (4, 2, 2)
            rawCube = numpy.full(shape, 2500, dtype=numpy.uint16)
            whiteCube = numpy.full(shape, 5000, dtype=numpy.uint16)
            darkCube = numpy.full(shape, 1000, dtype=numpy.uint16)
            wavelengthsNm = numpy.array([450.0, 520.0, 620.0, 750.0], dtype=numpy.float64)
            envi.writeDataset(datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
            headerPath = datasetFolder / envi.HEADER_FILE_NAME
            headerPath.write_text(
                headerPath.read_text(encoding="ascii").replace(envi.DATASET_MARKER, "UNMARKED"),
                encoding="ascii",
            )
            dataset = contract.loadDataset(datasetFolder)

            with self.assertRaises(uc1_maps.SimulatedMarkerRequiredError):
                uc1_maps.ArithmeticClassifier().classify(dataset)

            forcedMaps = uc1_maps.ArithmeticClassifier(requireSimulatedMarker=False).classify(
                dataset
            )
            uc1_maps.validateMaps(forcedMaps)


if __name__ == "__main__":
    unittest.main()
