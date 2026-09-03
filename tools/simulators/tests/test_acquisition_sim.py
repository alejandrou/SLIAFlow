"""Guards that run at the acquisition level rather than inside one module.

The configuration validator predicts whether a dataset can satisfy the contract.
These cover what happens to the prediction afterwards: the measured rank has to
be enforced, not merely printed, and the reported frame rate has to divide by
the intervals it actually spans.
"""

from __future__ import annotations

import time
import unittest

from stratum_sim import acquisition_sim, spectra


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
        measurementStart = time.perf_counter() - 0.9

        rate = acquisition_sim.enqueueRate(frameCount, measurementStart)

        self.assertAlmostEqual(rate, (frameCount - 1) / 0.9, places=1)
        self.assertLess(rate, frameCount / 0.9)

    def test_noMeasurementIsReportedAsZeroRatherThanGuessed(self):
        self.assertEqual(acquisition_sim.enqueueRate(0, None), 0.0)
        self.assertEqual(
            acquisition_sim.enqueueRate(1, time.perf_counter()), 0.0
        )


if __name__ == "__main__":
    unittest.main()
