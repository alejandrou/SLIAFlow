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
from itertools import pairwise
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

# The phantom geometry as `docs/development/synthetic_tissue_phantom.md`
# states it, in fractions of the frame. Duplicated here on purpose: the
# document is the contract a reader is given, so this fails when the code and
# the document drift apart rather than when the code merely changes.
DOCUMENTED_FIELD_CENTRE = (0.50, 0.50)
DOCUMENTED_FIELD_RADII = (0.40, 0.42)
DOCUMENTED_TUMOUR_CENTRE = (0.36, 0.58)
DOCUMENTED_TUMOUR_RADII = (0.15, 0.17)
DOCUMENTED_VESSEL_TRACK_COUNT = 3

# Per-region component counts are a resolution artifact and are deliberately
# not pinned: the vessel label alone falls into 15 components at 24x32, 2 at
# 48x64 and 3 at 96x128, so an exact count would fail any change that made the
# phantom cleaner. What is asserted instead is the structure the scene is drawn
# with. A component below this size is a rasterisation sliver, not a drawn area.
MINIMUM_COHERENT_COMPONENT_PIXELS = 8
# Every drawn region covers a macroscopic part of the frame. The smallest at
# 48x64 is the vessel label, at 5.8 %.
MINIMUM_REGION_AREA_FRACTION = 0.01
# Rasterising five drawn boundaries onto a small grid leaves a few slivers
# where a vessel track clips the field or the tumour edge: 10 pixels of 3072 at
# 48x64, and under 0.02 % of the frame at every larger preset. Scattering a
# region across the frame exceeds this by two orders of magnitude, which
# `test_theCoherenceRulesRejectAScatteredMap` holds these rules to.
MAXIMUM_SLIVER_FRACTION = 0.01
# A sliver appears only where two drawn boundaries cross, so it always touches
# both of the labels that made it. A small component walled in by a single
# other label was not drawn by any boundary: it is scatter.
MINIMUM_SLIVER_BORDERING_LABELS = 2


def bandIndex(wavelengthsNm: numpy.ndarray, targetNm: float) -> int:
    return int(numpy.argmin(numpy.abs(wavelengthsNm - targetNm)))


def neighbours(shape: tuple[int, int], line: int, sample: int):
    """The four edge-sharing neighbours of a pixel that lie inside the frame."""
    for neighbourLine, neighbourSample in (
        (line - 1, sample),
        (line + 1, sample),
        (line, sample - 1),
        (line, sample + 1),
    ):
        if 0 <= neighbourLine < shape[0] and 0 <= neighbourSample < shape[1]:
            yield neighbourLine, neighbourSample


def fourConnectedComponents(mask: numpy.ndarray) -> list[list[tuple[int, int]]]:
    """Group a mask into components, largest first, using edge-sharing neighbours."""
    selected = numpy.asarray(mask, dtype=bool)
    visited = numpy.zeros(selected.shape, dtype=bool)
    components = []

    for start in numpy.argwhere(selected):
        start = (int(start[0]), int(start[1]))
        if visited[start]:
            continue
        visited[start] = True
        pending = [start]
        member = [start]
        while pending:
            line, sample = pending.pop()
            for neighbour in neighbours(selected.shape, line, sample):
                if selected[neighbour] and not visited[neighbour]:
                    visited[neighbour] = True
                    pending.append(neighbour)
                    member.append(neighbour)
        components.append(member)

    return sorted(components, key=len, reverse=True)


def componentSizes(mask: numpy.ndarray) -> list[int]:
    return [len(component) for component in fourConnectedComponents(mask)]


def slivers(regionMap: numpy.ndarray) -> list[list[tuple[int, int]]]:
    """Components too small to read as a drawn area, whatever their label."""
    return [
        component
        for value in tissue.REGION_VALUES
        for component in fourConnectedComponents(regionMap == value)
        if len(component) < MINIMUM_COHERENT_COMPONENT_PIXELS
    ]


def borderingLabels(regionMap: numpy.ndarray, component: list[tuple[int, int]]) -> set[int]:
    """The labels a component touches, excluding its own."""
    own = int(regionMap[component[0]])
    return {
        int(regionMap[neighbour])
        for line, sample in component
        for neighbour in neighbours(regionMap.shape, line, sample)
        if int(regionMap[neighbour]) != own
    }


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

        blood, saturation, amplitude, power = numpy.broadcast_arrays(
            blood, saturation, amplitude, power
        )

        reflectance = tissue.tissueReflectance(
            self.wavelengthsNm,
            blood,
            saturation,
            0.75,
            amplitude,
            power,
        )

        self.assertEqual(reflectance.shape, blood.shape + (self.wavelengthsNm.size,))
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

    def test_theCraniotomyFieldAndTheDrapeAreEachOneConnectedArea(self):
        self.assertEqual(self.regionMap.shape, (TEST_LINES, TEST_SAMPLES))
        self.assertEqual(self.regionMap.dtype, numpy.uint8)
        self.assertEqual(set(numpy.unique(self.regionMap).tolist()), set(tissue.REGION_VALUES))

        # The tumour blob and the vessel tracks are drawn inside the field, so
        # however they are labelled the non-drape pixels remain one area and
        # the drape remains the single area surrounding it. Both follow from
        # how the scene is drawn and hold at every frame size, unlike the count
        # of areas each individual label happens to break into.
        self.assertEqual(len(componentSizes(self.regionMap != tissue.REGION_DRAPE)), 1)
        self.assertEqual(len(componentSizes(self.regionMap == tissue.REGION_DRAPE)), 1)

    def test_everyRegionIsDrawnAsAreasRatherThanScatteredPixels(self):
        # What the phantom promises is that a region can be told from noise by
        # eye: each label owns a macroscopic area, and only a boundary-sized
        # remainder is left in slivers.
        frameArea = float(TEST_LINES * TEST_SAMPLES)
        for value in tissue.REGION_VALUES:
            with self.subTest(region=tissue.REGION_NAMES[value]):
                sizes = componentSizes(self.regionMap == value)
                self.assertGreaterEqual(max(sizes) / frameArea, MINIMUM_REGION_AREA_FRACTION)

        sliverComponents = slivers(self.regionMap)
        sliverArea = sum(len(component) for component in sliverComponents)
        self.assertLessEqual(sliverArea / frameArea, MAXIMUM_SLIVER_FRACTION)
        for component in sliverComponents:
            self.assertGreaterEqual(
                len(borderingLabels(self.regionMap, component)),
                MINIMUM_SLIVER_BORDERING_LABELS,
                "A small area walled in by one other label is scatter, not geometry",
            )

    def test_theCoherenceRulesRejectAScatteredMap(self):
        # Both rules above have to be able to fail, or they would license any
        # map. Sprinkling one label over the frame is the salt-and-pepper
        # result the phantom exists to avoid: it breaks the sliver budget
        # outright, and each dropped pixel is walled in by the label it landed
        # on, which is what separates scatter from a rasterised boundary.
        scattered = self.regionMap.copy()
        scattered[::4, ::4] = tissue.REGION_TUMOUR
        sliverComponents = slivers(scattered)
        sliverArea = sum(len(component) for component in sliverComponents)

        self.assertGreater(sliverArea / float(scattered.size), MAXIMUM_SLIVER_FRACTION)
        self.assertTrue(
            any(
                len(borderingLabels(scattered, component))
                < MINIMUM_SLIVER_BORDERING_LABELS
                for component in sliverComponents
            )
        )

    def test_theVesselLabelIsNeverMoreAreasThanThereAreDrawnTracks(self):
        # Three tracks are drawn, each a single curve clipped to the field, so
        # the label cannot exceed three areas however they overlap. Two of them
        # meet at this frame size, which is why the count is bounded, not fixed.
        self.assertEqual(len(tissue.VESSEL_TRACKS), DOCUMENTED_VESSEL_TRACK_COUNT)
        vesselAreas = componentSizes(self.regionMap == tissue.REGION_VESSEL)

        self.assertGreaterEqual(len(vesselAreas), 1)
        self.assertLessEqual(len(vesselAreas), DOCUMENTED_VESSEL_TRACK_COUNT)

    def test_interiorRegionsLieInsideTheEllipsesTheDocumentPublishes(self):
        # Rebuild both ellipses from the geometry the phantom document
        # publishes, instead of treating distance from the image edge as a
        # proxy for containment.
        x = numpy.linspace(0.0, 1.0, TEST_SAMPLES, dtype=numpy.float64)[None, :]
        y = numpy.linspace(0.0, 1.0, TEST_LINES, dtype=numpy.float64)[:, None]

        def ellipse(centre, radii):
            return ((x - centre[0]) / radii[0]) ** 2 + ((y - centre[1]) / radii[1]) ** 2 <= 1.0

        field = ellipse(DOCUMENTED_FIELD_CENTRE, DOCUMENTED_FIELD_RADII)
        blob = ellipse(DOCUMENTED_TUMOUR_CENTRE, DOCUMENTED_TUMOUR_RADII)
        interior = numpy.isin(self.regionMap, (tissue.REGION_TUMOUR, tissue.REGION_VESSEL))

        self.assertFalse(bool((interior & ~field).any()))
        self.assertTrue(bool((self.regionMap[~field] == tissue.REGION_DRAPE).all()))
        # The tracks are painted over the blob, so the label is what the blob
        # keeps: a subset of the documented ellipse, never anything outside it.
        self.assertFalse(bool(((self.regionMap == tissue.REGION_TUMOUR) & ~blob).any()))

    def test_phantomCubeClearsTheSpectralRankFloor(self):
        # The whole point of the within-region modulation. Four regions of
        # constant spectra would be rank 4, below the floor, and K-means would
        # have four points to cluster.
        cube = tissue.phantomReflectanceCube(self.regionMap, self.wavelengthsNm)
        self.assertEqual(cube.shape, (spectra.DEFAULT_BAND_COUNT, TEST_LINES, TEST_SAMPLES))

        report = spectra.spectralRankReport(cube * 100.0)
        self.assertGreaterEqual(report.rank, spectra.MINIMUM_SPECTRAL_RANK)

    def test_everyRegionHasADistinctNormalizedSpectralShape(self):
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
        # The requirement is qualitative: at the haemoglobin-sensitive green
        # band, normalized reflectance follows the independently defined optical
        # loading from green drape through cortex and tumour to vessel. This
        # gives every construction region a distinct shape without inventing a
        # numerical separation floor.
        green = bandIndex(self.wavelengthsNm, GREEN_BAND_NM)
        shapeByRegion = {
            value: shapes[index, green]
            for index, value in enumerate(tissue.REGION_VALUES)
        }
        expectedOrder = (
            tissue.REGION_DRAPE,
            tissue.REGION_CORTEX,
            tissue.REGION_TUMOUR,
            tissue.REGION_VESSEL,
        )
        for higher, lower in pairwise(expectedOrder):
            self.assertGreater(shapeByRegion[higher], shapeByRegion[lower])

    def test_renderedFrameMatchesAnIndependentSmallProjectionOracle(self):
        wavelengthsNm = numpy.array([450.0, 550.0, 650.0], dtype=numpy.float64)
        cube = numpy.array(
            [
                [[0.10, 0.20], [0.30, 0.40]],
                [[0.50, 0.40], [0.30, 0.20]],
                [[0.20, 0.30], [0.40, 0.50]],
            ],
            dtype=numpy.float32,
        )
        # Fixed values were evaluated independently from the documented BGR
        # Gaussian responses, per-channel normalization, and peak scaling.
        expected = numpy.array(
            [
                [[92, 235, 160], [126, 198, 177]],
                [[160, 162, 195], [193, 126, 212]],
            ],
            dtype=numpy.uint8,
        )

        frame = tissue.renderFrameBgr(cube, wavelengthsNm)

        numpy.testing.assert_array_equal(frame, expected)

    def test_renderedFrameChangesAtThePixelWhoseCubeVoxelChanges(self):
        wavelengthsNm = numpy.array([450.0, 550.0, 650.0], dtype=numpy.float64)
        cube = numpy.array(
            [
                [[0.10, 0.20], [0.30, 0.40]],
                [[0.50, 0.40], [0.30, 0.20]],
                [[0.20, 0.30], [0.40, 0.50]],
            ],
            dtype=numpy.float32,
        )
        baseline = tissue.renderFrameBgr(cube, wavelengthsNm)
        perturbedCube = cube.copy()
        perturbedCube[1, 0, 1] += 0.05

        perturbed = tissue.renderFrameBgr(perturbedCube, wavelengthsNm)

        # The renderer scales by the whole frame's peak, so locality only holds
        # while the perturbed voxel is not the brightest thing in the frame. It
        # is not here, and a perturbation that did move the peak would
        # legitimately change every pixel. Assert that precondition rather than
        # leaving the test resting on an unstated property of the fixture.
        self.assertEqual(
            numpy.unravel_index(int(perturbed.argmax()), perturbed.shape),
            numpy.unravel_index(int(baseline.argmax()), baseline.shape),
        )

        self.assertFalse(numpy.array_equal(perturbed[0, 1], baseline[0, 1]))
        numpy.testing.assert_array_equal(perturbed[0, 0], baseline[0, 0])
        numpy.testing.assert_array_equal(perturbed[1], baseline[1])

    def test_renderedPhantomKeepsTheExpectedSceneLevelGreenOrdering(self):
        cube = tissue.phantomReflectanceCube(self.regionMap, self.wavelengthsNm)
        frame = tissue.renderFrameBgr(cube, self.wavelengthsNm)

        # The drape reflects far more green than the blood-loaded vessels do, so
        # preserve this as a secondary scene-level property.
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
