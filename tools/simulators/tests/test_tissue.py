"""Tests for the synthetic tissue phantom.

These check physics, not classifier agreement. Nothing here asserts that UC1
assigns a particular class to a particular region: what the shipped model says
about this phantom is a measurement recorded in the task evidence and in
`docs/development/synthetic_tissue_phantom.md`, and a test that pinned it would
turn a measurement into a target.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import acquisition_sim, config, envi, spectra, tissue
from tests import support

TEST_SAMPLES = 64
TEST_LINES = 48

# The oxy/deoxy extinction curves cross near 800 nm. The exact isosbestic point
# is quoted between 797 and 805 nm depending on the tabulation, so the window
# is wide enough not to pin a number the analytic approximation cannot own.
ISOSBESTIC_WINDOW_NM = (780.0, 820.0)

RED_BAND_NM = 660.0
GREEN_BAND_NM = 560.0


def bandIndex(wavelengthsNm: numpy.ndarray, targetNm: float) -> int:
    return int(numpy.argmin(numpy.abs(wavelengthsNm - targetNm)))


class ChromophoreTest(unittest.TestCase):

    def setUp(self):
        self.wavelengthsNm = spectra.bandWavelengthsNm(spectra.DEFAULT_BAND_COUNT)

    def test_haemoglobinCurvesCrossAtTheIsosbesticPoint(self):
        # Below the crossing deoxyhaemoglobin absorbs more; above it, less.
        # That reversal is the single most recognisable feature of the pair and
        # it is what makes oxygen saturation change the *shape* of a spectrum
        # rather than only its level - which is all UC1's SVM ever sees.
        oxy = tissue.oxyhaemoglobinExtinction(self.wavelengthsNm)
        deoxy = tissue.deoxyhaemoglobinExtinction(self.wavelengthsNm)
        difference = deoxy - oxy

        inWindow = (self.wavelengthsNm >= ISOSBESTIC_WINDOW_NM[0]) & (
            self.wavelengthsNm <= ISOSBESTIC_WINDOW_NM[1]
        )
        self.assertTrue(bool(inWindow.any()))
        self.assertGreater(float(difference[inWindow].max()), 0.0)
        self.assertLess(float(difference[inWindow].min()), 0.0)

    def test_deoxygenatedBloodAbsorbsMoreInTheRed(self):
        red = bandIndex(self.wavelengthsNm, RED_BAND_NM)
        oxygenated = tissue.absorptionCoefficient(self.wavelengthsNm, 0.05, 1.0, 0.75)
        deoxygenated = tissue.absorptionCoefficient(self.wavelengthsNm, 0.05, 0.0, 0.75)

        self.assertGreater(float(deoxygenated[red]), float(oxygenated[red]))

    def test_scatteringFollowsThePowerLaw(self):
        amplitude, power = 22.0, 1.3
        scattering = tissue.reducedScatteringCoefficient(self.wavelengthsNm, amplitude, power)

        reference = bandIndex(self.wavelengthsNm, tissue.SCATTERING_REFERENCE_NM)
        self.assertAlmostEqual(
            float(scattering[reference]),
            amplitude
            * (float(self.wavelengthsNm[reference]) / tissue.SCATTERING_REFERENCE_NM) ** -power,
            places=6,
        )
        # Monotonically decreasing with wavelength for any positive exponent.
        self.assertTrue(bool(numpy.all(numpy.diff(scattering) < 0.0)))


class ReflectanceTest(unittest.TestCase):

    def setUp(self):
        self.wavelengthsNm = spectra.bandWavelengthsNm(spectra.DEFAULT_BAND_COUNT)

    def test_moreBloodMeansLessReflectanceWhereHaemoglobinAbsorbs(self):
        green = bandIndex(self.wavelengthsNm, GREEN_BAND_NM)
        low = tissue.tissueReflectance(self.wavelengthsNm, 0.01, 0.75, 0.75, 22.0, 1.3)
        high = tissue.tissueReflectance(self.wavelengthsNm, 0.10, 0.75, 0.75, 22.0, 1.3)

        self.assertLess(float(high[green]), float(low[green]))

    def test_reflectanceStaysInsideTheUnitIntervalAcrossThePhysiologicalRange(self):
        # A reflectance above 1 or below 0 would be unphysical, and the
        # calibration inversion in `spectra.rawFromReflectance` would clip it
        # into uint16 silently rather than complain.
        blood = numpy.array([0.001, 0.01, 0.05, 0.15, 0.40])[:, None, None, None]
        saturation = numpy.array([0.0, 0.5, 1.0])[None, :, None, None]
        amplitude = numpy.array([8.0, 22.0, 40.0])[None, None, :, None]
        power = numpy.array([0.3, 1.0, 2.2])[None, None, None, :]

        reflectance = tissue.tissueReflectance(
            self.wavelengthsNm,
            numpy.broadcast_to(blood, (5, 3, 3, 3)),
            numpy.broadcast_to(saturation, (5, 3, 3, 3)),
            0.75,
            numpy.broadcast_to(amplitude, (5, 3, 3, 3)),
            numpy.broadcast_to(power, (5, 3, 3, 3)),
        )

        self.assertEqual(reflectance.shape, (5, 3, 3, 3, spectra.DEFAULT_BAND_COUNT))
        self.assertGreater(float(reflectance.min()), 0.0)
        self.assertLess(float(reflectance.max()), 1.0)

    def test_drapeIsNotModelledAsTissue(self):
        # A dyed fabric peaks where its dye reflects: the drape has a strict
        # local maximum in the green, lower on both sides. The turbid-medium
        # model cannot produce that at any blood volume - scattering falls with
        # wavelength, so 470 nm always outshines 530 nm, and haemoglobin only
        # deepens the visible trough. Running the tissue model at a near-zero
        # blood volume would therefore give the surround a spectrum shaped like
        # exsanguinated brain rather than like a drape.
        blue = bandIndex(self.wavelengthsNm, 470.0)
        green = bandIndex(self.wavelengthsNm, 530.0)
        red = bandIndex(self.wavelengthsNm, 620.0)

        drape = tissue.drapeReflectance(self.wavelengthsNm)
        self.assertGreater(float(drape[green]), float(drape[blue]))
        self.assertGreater(float(drape[green]), float(drape[red]))

        # No tissue parameters reproduce that, bloodless ones least of all.
        for bloodVolumeFraction in (0.002, 0.03, 0.25):
            reflectance = tissue.tissueReflectance(
                self.wavelengthsNm, bloodVolumeFraction, 0.75, 0.75, 22.0, 1.3
            )
            self.assertLess(float(reflectance[green]), float(reflectance[blue]))


class PhantomSceneTest(unittest.TestCase):

    def setUp(self):
        self.wavelengthsNm = spectra.bandWavelengthsNm(spectra.DEFAULT_BAND_COUNT)
        self.regionMap = tissue.phantomRegionMap(TEST_LINES, TEST_SAMPLES)

    def test_everyRegionIsPresentAndCoherent(self):
        self.assertEqual(self.regionMap.shape, (TEST_LINES, TEST_SAMPLES))
        self.assertEqual(self.regionMap.dtype, numpy.uint8)
        self.assertEqual(set(numpy.unique(self.regionMap).tolist()), set(tissue.REGION_VALUES))

        # Coherence, tested the way the acceptance criterion words it: each
        # region is a connected area, so most of a region's pixels have a
        # neighbour of the same region. Salt-and-pepper noise would not.
        for value in tissue.REGION_VALUES:
            selected = self.regionMap == value
            sameAsLeft = selected[:, 1:] & selected[:, :-1]
            self.assertGreater(sameAsLeft.sum(), 0.5 * selected.sum())

    def test_tumourAndVesselRegionsLieInsideTheCraniotomyField(self):
        # A tumour-like region floating on the drape would be nonsense, and it
        # would also let the phantom pass the "more than one class" criterion
        # for a reason that has nothing to do with tissue.
        interior = numpy.isin(self.regionMap, (tissue.REGION_TUMOUR, tissue.REGION_VESSEL))
        edge = numpy.zeros_like(self.regionMap, dtype=bool)
        edge[0, :] = edge[-1, :] = True
        edge[:, 0] = edge[:, -1] = True

        self.assertFalse(bool((interior & edge).any()))
        self.assertTrue(bool((self.regionMap[edge] == tissue.REGION_DRAPE).all()))

    def test_phantomCubeClearsTheSpectralRankFloor(self):
        # The whole point of the within-region modulation. Four regions of
        # constant spectra would be rank 4, below the floor, and K-means would
        # have four points to cluster.
        cube = tissue.phantomReflectanceCube(self.regionMap, self.wavelengthsNm)
        self.assertEqual(cube.shape, (spectra.DEFAULT_BAND_COUNT, TEST_LINES, TEST_SAMPLES))

        report = spectra.spectralRankReport(cube * 100.0)
        self.assertGreaterEqual(report.rank, spectra.MINIMUM_SPECTRAL_RANK)

    def test_regionsDoNotAllShareOneSpectrum(self):
        cube = tissue.phantomReflectanceCube(self.regionMap, self.wavelengthsNm)
        means = numpy.stack(
            [cube[:, self.regionMap == value].mean(axis=1) for value in tissue.REGION_VALUES]
        )
        # Compare shapes, not levels: min-max normalization across bands is
        # exactly what UC1 does before its SVM, so two regions that differ only
        # in brightness are the same region as far as the pipeline is concerned.
        shapes = (means - means.min(axis=1, keepdims=True)) / (
            means.max(axis=1, keepdims=True) - means.min(axis=1, keepdims=True)
        )
        for first in range(len(tissue.REGION_VALUES)):
            for second in range(first + 1, len(tissue.REGION_VALUES)):
                self.assertGreater(float(numpy.abs(shapes[first] - shapes[second]).max()), 0.02)

    def test_renderedFrameIsAProjectionOfTheCube(self):
        cube = tissue.phantomReflectanceCube(self.regionMap, self.wavelengthsNm)
        frame = tissue.renderFrameBgr(cube, self.wavelengthsNm)

        self.assertEqual(frame.shape, (TEST_LINES, TEST_SAMPLES, 3))
        self.assertEqual(frame.dtype, numpy.uint8)

        # The drape reflects far more green than the blood-loaded vessels do, so
        # if the frame really is the cube seen through the channel curves, the
        # ordering of the green plane has to follow the cube's.
        greenPlane = frame[..., 1].astype(numpy.float64)
        drapeGreen = greenPlane[self.regionMap == tissue.REGION_DRAPE].mean()
        vesselGreen = greenPlane[self.regionMap == tissue.REGION_VESSEL].mean()
        self.assertGreater(drapeGreen, vesselGreen)


class PhantomRecordTest(unittest.TestCase):

    def test_recordNamesEveryRegionAndCarriesTheNonClinicalNotice(self):
        regionMap = tissue.phantomRegionMap(TEST_LINES, TEST_SAMPLES)

        with tempfile.TemporaryDirectory() as temporaryRoot:
            folder = Path(temporaryRoot) / "sim-20260903-000000"
            mapPath, legendPath = tissue.writePhantomRecord(folder, regionMap)

            self.assertTrue(numpy.array_equal(numpy.load(mapPath), regionMap))
            legend = json.loads(legendPath.read_text(encoding="utf-8"))

        self.assertIn("not patient data", legend["notice"].lower())
        self.assertEqual(
            sorted(legend["regions"]), sorted(str(value) for value in tissue.REGION_VALUES)
        )
        self.assertEqual(
            legend["regions"][str(tissue.REGION_CORTEX)]["bloodVolumeFraction"],
            tissue.REGION_OPTICS[tissue.REGION_CORTEX].bloodVolumeFraction,
        )


class PhantomRecordLifetimeTest(unittest.TestCase):
    """A record left behind by an earlier write would describe the wrong data."""

    def makeConfig(self, temporaryRoot: Path, sceneMode: str) -> config.SimulatorConfig:
        return config.SimulatorConfig(
            repositoryRoot=Path.cwd(),
            sceneMode=sceneMode,
            datasetRoot=temporaryRoot,
            seed=20260904,
        )

    def test_channelWriteOverAPhantomFolderRemovesTheStaleRecord(self) -> None:
        # `--dataset-folder` points two runs at one folder, and the ENVI writer
        # replaces only the four files it owns. Without the removal the channel
        # dataset would keep the phantom's region map and legend, and anyone
        # reading them would believe they describe this cube - including which
        # regions are tumour-like.
        with tempfile.TemporaryDirectory() as temporaryRoot:
            folder = Path(temporaryRoot) / "sim-20260904-000000"

            phantomConfig = self.makeConfig(Path(temporaryRoot), config.SCENE_MODE_TISSUE)
            acquisition_sim.synthesizePhantomDataset(phantomConfig, folder)
            self.assertTrue((folder / tissue.REGION_MAP_FILE_NAME).is_file())
            self.assertTrue((folder / tissue.REGION_LEGEND_FILE_NAME).is_file())

            channelConfig = self.makeConfig(Path(temporaryRoot), config.SCENE_MODE_CHANNEL)
            acquisition_sim.synthesizeDataset(
                channelConfig,
                support.makeTestFrame(channelConfig.samples, channelConfig.lines),
                folder,
            )

            self.assertFalse((folder / tissue.REGION_MAP_FILE_NAME).exists())
            self.assertFalse((folder / tissue.REGION_LEGEND_FILE_NAME).exists())
            # The dataset itself is still there and readable.
            self.assertEqual(envi.loadDataset(folder).bands, channelConfig.bands)

    def test_removalReportsWhatItRemovedAndIsSafeWhenThereIsNothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporaryRoot:
            folder = Path(temporaryRoot) / "sim-20260904-000001"
            folder.mkdir()

            self.assertEqual(tissue.removePhantomRecord(folder), [])

            tissue.writePhantomRecord(folder, tissue.phantomRegionMap(TEST_LINES, TEST_SAMPLES))
            removed = tissue.removePhantomRecord(folder)

            self.assertEqual(
                sorted(path.name for path in removed),
                sorted((tissue.REGION_MAP_FILE_NAME, tissue.REGION_LEGEND_FILE_NAME)),
            )

    def test_aPhantomRewriteKeepsItsOwnRecord(self) -> None:
        with tempfile.TemporaryDirectory() as temporaryRoot:
            folder = Path(temporaryRoot) / "sim-20260904-000002"
            phantomConfig = self.makeConfig(Path(temporaryRoot), config.SCENE_MODE_TISSUE)

            acquisition_sim.synthesizePhantomDataset(phantomConfig, folder)
            acquisition_sim.synthesizePhantomDataset(phantomConfig, folder)

            self.assertTrue((folder / tissue.REGION_MAP_FILE_NAME).is_file())
            self.assertTrue((folder / tissue.REGION_LEGEND_FILE_NAME).is_file())


class SceneModeConfigurationTest(unittest.TestCase):

    def test_tissueSceneRefusesACameraRatherThanIgnoringIt(self):
        with self.assertRaises(config.ConfigurationError) as raised:
            config.SimulatorConfig(
                repositoryRoot=Path.cwd(),
                sceneMode=config.SCENE_MODE_TISSUE,
                frameSource="webcam",
            )
        self.assertIn(config.SCENE_MODE_CHANNEL, str(raised.exception))

    def test_channelSceneStillAcceptsACamera(self):
        simulatorConfig = config.SimulatorConfig(
            repositoryRoot=Path.cwd(),
            sceneMode=config.SCENE_MODE_CHANNEL,
            frameSource="webcam",
        )
        self.assertEqual(simulatorConfig.frameSource, "webcam")

    def test_unknownSceneModeIsRejected(self):
        with self.assertRaises(config.ConfigurationError):
            config.SimulatorConfig(repositoryRoot=Path.cwd(), sceneMode="phantasm")
