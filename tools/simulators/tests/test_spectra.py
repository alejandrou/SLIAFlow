"""Spectral synthesis and calibration tests."""

from __future__ import annotations

import unittest

import numpy

from stratum_sim import spectra
from tests import support

TEST_SAMPLES = 32
TEST_LINES = 24
TEST_SEED = 20260902

# UC1's calibration output is a percentage, so "one part in 2000" is 0.05 on the
# 0-to-100 scale the pipeline actually sees.
CALIBRATION_TOLERANCE_PERCENT = 100.0 / 2000.0

# Public Headwall sensor sampling contract documented for this simulator.
HEADWALL_FIRST_WAVELENGTH_NM = 400.482
HEADWALL_LAST_WAVELENGTH_NM = 1000.73
HEADWALL_BAND_COUNT = 93


def buildCalibratedCube(textureFeatureCount: int) -> numpy.ndarray:
    wavelengthsNm = spectra.bandWavelengthsNm(spectra.DEFAULT_BAND_COUNT)
    frame = support.makeTestFrame(TEST_SAMPLES, TEST_LINES)

    reflectance = spectra.reflectanceCube(
        frame,
        wavelengthsNm,
        textureFeatureCount=textureFeatureCount,
        rng=numpy.random.default_rng(TEST_SEED),
    )
    referenceRng = numpy.random.default_rng(TEST_SEED)
    darkCube, whiteCube = spectra.referenceCubes(
        referenceRng, spectra.DEFAULT_BAND_COUNT, TEST_LINES, TEST_SAMPLES
    )
    rawCube = spectra.rawFromReflectance(
        reflectance, darkCube, whiteCube, noiseCounts=0, rng=referenceRng
    )
    return spectra.calibrate(rawCube, darkCube, whiteCube)


class CalibrationTest(unittest.TestCase):

    def test_calibrationRoundTripRecoversReflectance(self):
        wavelengthsNm = spectra.bandWavelengthsNm(spectra.DEFAULT_BAND_COUNT)
        frame = support.makeTestFrame(TEST_SAMPLES, TEST_LINES)

        reflectance = spectra.reflectanceCube(
            frame,
            wavelengthsNm,
            textureFeatureCount=spectra.DEFAULT_TEXTURE_FEATURE_COUNT,
            rng=numpy.random.default_rng(TEST_SEED),
        )
        referenceRng = numpy.random.default_rng(TEST_SEED)
        darkCube, whiteCube = spectra.referenceCubes(
            referenceRng, spectra.DEFAULT_BAND_COUNT, TEST_LINES, TEST_SAMPLES
        )

        # UC1 divides by `white - dark` behind a `white != 0` guard, so a single
        # voxel where the references touch would silently zero that spectrum.
        self.assertTrue(bool(numpy.all(whiteCube.astype(numpy.int64) > darkCube.astype(numpy.int64))))

        rawCube = spectra.rawFromReflectance(
            reflectance, darkCube, whiteCube, noiseCounts=0, rng=referenceRng
        )
        calibrated = spectra.calibrate(rawCube, darkCube, whiteCube)

        largestError = float(numpy.max(numpy.abs(calibrated - 100.0 * reflectance)))
        self.assertLess(largestError, CALIBRATION_TOLERANCE_PERCENT)


class SpectralRankTest(unittest.TestCase):

    def test_bandCovarianceRankClearsPcaComponentCount(self):
        calibrated = buildCalibratedCube(spectra.DEFAULT_TEXTURE_FEATURE_COUNT)
        report = spectra.spectralRankReport(calibrated)

        # A nonzero band count proves nothing: a scene mixed from a handful of
        # basis curves has every band nonzero and a covariance whose rank equals
        # the basis size. The rank is therefore measured, never inferred.
        self.assertGreaterEqual(report.rank, spectra.MINIMUM_SPECTRAL_RANK)
        self.assertTrue(numpy.isfinite(report.conditionNumber))
        self.assertGreater(report.conditionNumber, 0.0)

        pcaBandCount = support.readUc1PcaBandCount()
        if pcaBandCount is None:
            self.skipTest("The vendored UC1 parameters.txt is not present in this checkout")
        self.assertGreaterEqual(report.rank, pcaBandCount)

    def test_channelOnlyBasisIsRankDeficient(self):
        # The luminance weight driving the NIR envelope is a fixed linear
        # combination of the B, G and R weights, so the envelope contributes a
        # curve but no new direction. This records why texture features exist.
        calibrated = buildCalibratedCube(0)
        report = spectra.spectralRankReport(calibrated)

        self.assertEqual(report.rank, spectra.CHANNEL_BASIS_RANK)
        self.assertLess(report.rank, spectra.MINIMUM_SPECTRAL_RANK)


class BandGridTest(unittest.TestCase):

    def test_bandGridMatchesTheHeadwallRange(self):
        expected = numpy.linspace(
            HEADWALL_FIRST_WAVELENGTH_NM,
            HEADWALL_LAST_WAVELENGTH_NM,
            HEADWALL_BAND_COUNT,
            dtype=numpy.float64,
        )

        actual = spectra.bandWavelengthsNm(HEADWALL_BAND_COUNT)

        numpy.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)
        self.assertEqual(spectra.DEFAULT_BAND_COUNT, HEADWALL_BAND_COUNT)
