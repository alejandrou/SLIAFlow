"""ENVI dataset reader tests, against the layout every recorded case has."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stratum_sim import envi
from tests import support

TEST_SAMPLES = support.TINY_DATASET_SAMPLES
TEST_LINES = support.TINY_DATASET_LINES
TEST_BANDS = support.TINY_DATASET_BANDS


# `input/bin/bin/004-02/raw.hdr`, verbatim. It holds dimensions and a wavelength
# list and no image content, and it is the authority for the layout a recorded
# header has: the block closed on its last value line, and `lines` and `samples`
# after the block.
RECORDED_004_02_RAW_HEADER = (
    "ENVI\n"
    "bands = 93\n"
    "data type = 12\n"
    "interleave = bsq\n"
    "header offset = 0\n"
    "wavelength units = Nanometers\n"
    "byte order = 0\n"
    "wavelength = {440, 445, 450, 455, 460, 465, \n"
    "470, 475, 480, 485, 490, 495, \n"
    "500, 505, 510, 515, 520, 525, \n"
    "530, 535, 540, 545, 550, 555, \n"
    "560, 565, 570, 575, 580, 585, \n"
    "590, 595, 600, 605, 610, 615, \n"
    "620, 625, 630, 635, 640, 645, \n"
    "650, 655, 660, 665, 670, 675, \n"
    "680, 685, 690, 695, 700, 705, \n"
    "710, 715, 720, 725, 730, 735, \n"
    "740, 745, 750, 755, 760, 765, \n"
    "770, 775, 780, 785, 790, 795, \n"
    "800, 805, 810, 815, 820, 825, \n"
    "830, 835, 840, 845, 850, 855, \n"
    "860, 865, 870, 875, 880, 885, \n"
    "890, 895,  900}\n"
    "lines = 389\n"
    "samples = 345\n"
)

# "440 to 900 nm in 5 nm steps", as the header above states it.
RECORDED_WAVELENGTHS_NM = tuple(float(value) for value in range(440, 901, 5))


class RecordedCaseTest(unittest.TestCase):
    """Recorded database cases: read them, identify them, never write them."""

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.workingRoot = Path(self._temporaryDirectory.name)
        self.addCleanup(self._temporaryDirectory.cleanup)

    def test_parsesHeaderWithTrailingBraceAndLateKeys(self):
        values, wavelengths = envi.parseHeaderText(RECORDED_004_02_RAW_HEADER)

        self.assertEqual(values["samples"], "345")
        self.assertEqual(values["lines"], "389")
        self.assertEqual(values["bands"], "93")
        self.assertEqual(wavelengths, RECORDED_WAVELENGTHS_NM)

    def test_unparsableHeaderRaisesDatasetReadError(self):
        # Every caller handles DatasetReadError. A bare ValueError from inside
        # the parser escapes all of them as a traceback.
        corruptions = {
            "wavelength": lambda text: text.replace(
                "wavelength = {", "wavelength = {not-a-wavelength, ", 1
            ),
            "samples": lambda text: text.replace(
                f"samples = {TEST_SAMPLES}\n", "samples = eight\n", 1
            ),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(corruption=name):
                datasetFolder = support.writeRecordedCaseFixture(
                    self.workingRoot / f"corrupt-{name}"
                )
                headerPath = datasetFolder / envi.HEADER_FILE_NAME
                original = headerPath.read_text(encoding="ascii")
                corrupted = corrupt(original)
                self.assertNotEqual(corrupted, original)
                headerPath.write_text(corrupted, encoding="ascii", newline="\n")

                with self.assertRaises(envi.DatasetReadError) as caught:
                    envi.loadDataset(datasetFolder)
                self.assertIn(envi.HEADER_FILE_NAME, str(caught.exception))

    def test_recordedCaseIsIdentifiedFromGtMapMarker(self):
        caseFolder = support.writeRecordedCaseFixture(self.workingRoot / "004-02")

        datasetRef = envi.loadDataset(caseFolder)

        self.assertTrue(datasetRef.recorded)
        self.assertEqual(
            (datasetRef.samples, datasetRef.lines, datasetRef.bands),
            (TEST_SAMPLES, TEST_LINES, TEST_BANDS),
        )
        self.assertEqual(datasetRef.wavelengthsNm, RECORDED_WAVELENGTHS_NM[:TEST_BANDS])

    def test_markerOutsideGtMapDoesNotIdentifyARecordedCase(self):
        withMarkerInRawHeader = support.writeRecordedCaseFixture(
            self.workingRoot / "marker-in-raw-header",
            groundTruthMarker="",
            rawHeaderDescription=support.RECORDED_DATABASE_MARKER,
        )
        withoutGroundTruthHeader = support.writeRecordedCaseFixture(
            self.workingRoot / "no-ground-truth-header",
            rawHeaderDescription=support.RECORDED_DATABASE_MARKER,
        )
        (withoutGroundTruthHeader / "gtMap.hdr").unlink()

        for caseFolder in (withMarkerInRawHeader, withoutGroundTruthHeader):
            with self.subTest(caseFolder=caseFolder.name):
                datasetRef = envi.loadDataset(caseFolder)
                self.assertFalse(datasetRef.recorded)
