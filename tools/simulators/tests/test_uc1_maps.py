"""Class-map contract tests: the rules every majority-voting map is held to."""

from __future__ import annotations

import unittest

import numpy

from stratum_sim import uc1_maps


def validClassMap() -> numpy.ndarray:
    return numpy.array([[[1, 2], [3, 4]]], dtype=numpy.uint8)


class MajorityVotingMapContractTest(unittest.TestCase):

    def test_aMapOfTheFourClassesOnTheContractShapeIsAccepted(self) -> None:
        uc1_maps.validateMajorityVotingMap(validClassMap())
        uc1_maps.validateMajorityVotingMap(validClassMap(), expectedShape=(1, 2, 2))

    def test_contractCheckRejectsCorruptedMaps(self) -> None:
        corruptions = {
            "not an array": [[[1, 2], [3, 4]]],
            "no leading axis": validClassMap()[0],
            "empty": numpy.zeros((1, 0, 2), dtype=numpy.uint8),
            "wrong dtype": validClassMap().astype(numpy.int32),
            "class 0": numpy.array([[[0, 2], [3, 4]]], dtype=numpy.uint8),
            "class 5": numpy.array([[[1, 2], [3, 5]]], dtype=numpy.uint8),
        }
        for name, classMap in corruptions.items():
            with self.subTest(corruption=name):
                with self.assertRaises(uc1_maps.MapContractError):
                    uc1_maps.validateMajorityVotingMap(classMap)

    def test_anExpectedShapeIsEnforced(self) -> None:
        with self.assertRaises(uc1_maps.MapContractError):
            uc1_maps.validateMajorityVotingMap(validClassMap(), expectedShape=(1, 2, 3))

    def test_classValuesAreUc1sFour(self) -> None:
        # `functions_cuda.cu`: 1 normal, 2 tumour, 3 hypervascularised, 4 background.
        self.assertEqual(uc1_maps.CLASS_VALUES, (1, 2, 3, 4))


if __name__ == "__main__":
    unittest.main()
