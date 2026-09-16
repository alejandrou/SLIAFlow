"""UC1 calibration tests."""

from __future__ import annotations

import unittest

import numpy

from stratum_sim import spectra


class CalibrationTest(unittest.TestCase):

    def test_calibrationIsUc1sFormulaWithItsGuard(self):
        # `functions_cuda.cu`: 100 * (raw - dark) / (white - dark), and 0 where
        # white equals dark. The last voxel is that guard.
        rawCube = numpy.array([[[1200, 26200, 51200, 700]]], dtype=numpy.uint16)
        darkCube = numpy.full(rawCube.shape, 1200, dtype=numpy.uint16)
        whiteCube = numpy.array([[[51200, 51200, 51200, 1200]]], dtype=numpy.uint16)

        calibrated = spectra.calibrate(rawCube, darkCube, whiteCube)

        self.assertEqual(calibrated.dtype, numpy.float32)
        numpy.testing.assert_allclose(calibrated, [[[0.0, 50.0, 100.0, 0.0]]])

    def test_rawBelowDarkIsNotClippedByUnsignedArithmetic(self):
        # uint16 subtraction would wrap to a large positive count. UC1 works in
        # float, so a raw count below dark calibrates negative.
        rawCube = numpy.array([[[700]]], dtype=numpy.uint16)
        darkCube = numpy.array([[[1200]]], dtype=numpy.uint16)
        whiteCube = numpy.array([[[51200]]], dtype=numpy.uint16)

        calibrated = spectra.calibrate(rawCube, darkCube, whiteCube)

        numpy.testing.assert_allclose(calibrated, [[[-1.0]]])


if __name__ == "__main__":
    unittest.main()
