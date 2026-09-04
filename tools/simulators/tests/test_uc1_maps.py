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
        self.wavelengthsNm = wavelengthsNm
        self.calibratedCube = calibratedCube
        self.maps = uc1_maps.deriveMaps(self.calibratedCube, self.wavelengthsNm)

    def test_derivedMapsAreInternallyConsistent(self) -> None:
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

    def test_derivedMapsMatchIndependentArithmeticOracle(self) -> None:
        # These fixed values were evaluated independently from the documented
        # arithmetic rule; no expected value is derived from a returned map.
        expectedRedness = numpy.array([[40.0, 40.0], [40.0, 40.0]], dtype=numpy.float32)
        expectedLuminance = numpy.array(
            [[32.5, 42.5], [52.5, 62.5]], dtype=numpy.float32
        )
        expectedLogits = numpy.array(
            [
                [[-2.475, 5.6, -1.5125, 1.025], [-2.375, 5.6, -1.3625, 0.725]],
                [[-2.275, 5.6, -1.2125, 0.425], [-2.175, 5.6, -1.0625, 0.125]],
            ],
            dtype=numpy.float32,
        )
        expectedSvmProbability = numpy.array(
            [
                [
                    [
                        [0.0003077055, 0.9886968442, 0.0008056449, 0.0101898055],
                        [0.0003409120, 0.9911531887, 0.0009383513, 0.0075675480],
                    ],
                    [
                        [0.0003774355, 0.9929142802, 0.0010921457, 0.0056161385],
                        [0.0004176482, 0.9941461854, 0.0012704666, 0.0041656997],
                    ],
                ]
            ],
            dtype=numpy.float32,
        )
        expectedKnnProbability = numpy.array(
            [
                [
                    [
                        [0.0059782323, 0.9298282799, 0.0109100832, 0.0532834046],
                        [0.0064128667, 0.9369982361, 0.0120747790, 0.0445141181],
                    ],
                    [
                        [0.0068677379, 0.9426638839, 0.0133417376, 0.0371266406],
                        [0.0073444044, 0.9470138489, 0.0147206492, 0.0309210975],
                    ],
                ]
            ],
            dtype=numpy.float32,
        )
        expectedTumourProbability = numpy.array(
            [[[0.9592625621, 0.9640757124], [0.9677890821, 0.9705800172]]],
            dtype=numpy.float32,
        )
        expectedClasses = numpy.full((1, 2, 2), 2, dtype=numpy.uint8)

        redness = uc1_maps.rednessIndex(self.calibratedCube, self.wavelengthsNm)
        luminance = uc1_maps.luminance(self.calibratedCube)
        actualLogits = uc1_maps.logits(redness, luminance)

        numpy.testing.assert_allclose(redness, expectedRedness, rtol=0.0, atol=1e-6)
        numpy.testing.assert_allclose(luminance, expectedLuminance, rtol=0.0, atol=1e-6)
        numpy.testing.assert_allclose(actualLogits, expectedLogits, rtol=0.0, atol=1e-6)
        numpy.testing.assert_allclose(
            self.maps.svmProbability, expectedSvmProbability, rtol=0.0, atol=1e-6
        )
        numpy.testing.assert_allclose(
            self.maps.knnProbability, expectedKnnProbability, rtol=0.0, atol=1e-6
        )
        numpy.testing.assert_allclose(
            self.maps.tmdMap, expectedTumourProbability, rtol=0.0, atol=1e-6
        )
        numpy.testing.assert_array_equal(self.maps.majorityVotingMap, expectedClasses)
        numpy.testing.assert_allclose(
            self.maps.majorityVotingProbabilityMap,
            expectedTumourProbability,
            rtol=0.0,
            atol=1e-6,
        )

    def test_derivedMapsDependOnInputSpectrum(self) -> None:
        redDominantCube = numpy.array(
            [10.0, 20.0, 60.0, 40.0], dtype=numpy.float32
        ).reshape(4, 1, 1)
        greenDominantCube = numpy.array(
            [10.0, 60.0, 20.0, 40.0], dtype=numpy.float32
        ).reshape(4, 1, 1)

        self.assertEqual(
            float(uc1_maps.luminance(redDominantCube)[0, 0]),
            float(uc1_maps.luminance(greenDominantCube)[0, 0]),
        )
        self.assertEqual(
            float(uc1_maps.rednessIndex(redDominantCube, self.wavelengthsNm)[0, 0]),
            40.0,
        )
        self.assertEqual(
            float(uc1_maps.rednessIndex(greenDominantCube, self.wavelengthsNm)[0, 0]),
            -40.0,
        )

        redDominantMaps = uc1_maps.deriveMaps(redDominantCube, self.wavelengthsNm)
        greenDominantMaps = uc1_maps.deriveMaps(greenDominantCube, self.wavelengthsNm)

        self.assertFalse(
            numpy.allclose(
                redDominantMaps.svmProbability, greenDominantMaps.svmProbability
            )
        )
        self.assertFalse(
            numpy.allclose(
                redDominantMaps.knnProbability, greenDominantMaps.knnProbability
            )
        )
        self.assertEqual(int(redDominantMaps.majorityVotingMap[0, 0, 0]), 2)
        self.assertEqual(int(greenDominantMaps.majorityVotingMap[0, 0, 0]), 1)

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
        surfaces = {
            "module docstring": " ".join(uc1_maps.__doc__.split()),
            "operator notice": " ".join(uc1_maps.NON_CLASSIFIER_NOTICE.split()),
        }
        for surfaceName, normalizedText in surfaces.items():
            with self.subTest(surface=surfaceName):
                lowered = normalizedText.lower()
                self.assertIn("not a classifier", lowered)
                self.assertIn("was never validated", lowered)
                self.assertIn("no diagnostic meaning", lowered)

        # These two surfaces deliberately show the same policy text even if its
        # source formatting changes.
        self.assertEqual(surfaces["module docstring"].split(" The rule exists", 1)[0], surfaces["operator notice"])
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
