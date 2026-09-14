"""ENVI dataset writer tests, checked against the consumers' own parsing rules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stratum_sim import envi
from tests import support

TEST_SAMPLES = support.TINY_DATASET_SAMPLES
TEST_LINES = support.TINY_DATASET_LINES
TEST_BANDS = support.TINY_DATASET_BANDS
BYTES_PER_SAMPLE = 2


class DatasetWriterTest(unittest.TestCase):

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.workingRoot = Path(self._temporaryDirectory.name)
        self.addCleanup(self._temporaryDirectory.cleanup)

    def writeTinyDataset(self, datasetFolder: Path):
        rawCube, whiteCube, darkCube, wavelengthsNm = support.buildTinyCubes()
        return envi.writeDataset(datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm)

    def test_datasetRoundTripsThroughUc1HeaderSemantics(self):
        datasetFolder = self.workingRoot / "sim-20260902-101112"
        datasetRef = self.writeTinyDataset(datasetFolder)

        expectedBytes = TEST_SAMPLES * TEST_LINES * TEST_BANDS * BYTES_PER_SAMPLE
        for fileName in (
            envi.RAW_DATA_FILE_NAME,
            envi.WHITE_REFERENCE_FILE_NAME,
            envi.DARK_REFERENCE_FILE_NAME,
        ):
            with self.subTest(fileName=fileName):
                self.assertEqual((datasetFolder / fileName).stat().st_size, expectedBytes)

        parsed = support.parseHeaderTheWayUc1Does(datasetFolder / envi.HEADER_FILE_NAME)
        self.assertEqual(parsed, {"samples": TEST_SAMPLES, "lines": TEST_LINES, "bands": TEST_BANDS})

        self.assertEqual(datasetRef.samples, TEST_SAMPLES)
        self.assertEqual(datasetRef.lines, TEST_LINES)
        self.assertEqual(datasetRef.bands, TEST_BANDS)

        # BSQ index is `band * totalPixels + line * samples + sample`, which is
        # exactly the C-order layout of a (bands, lines, samples) array.
        rawCube, _, _, _ = support.buildTinyCubes()
        writtenBytes = (datasetFolder / envi.RAW_DATA_FILE_NAME).read_bytes()
        self.assertEqual(writtenBytes, rawCube.astype("<u2").tobytes())

    def test_headerSatisfiesBothConsumers(self):
        datasetFolder = self.workingRoot / "sim-20260902-101112"
        self.writeTinyDataset(datasetFolder)
        headerPath = datasetFolder / envi.HEADER_FILE_NAME
        headerText = headerPath.read_text(encoding="ascii")

        # HSCubeLoader strips everything after a `;`, so a single one anywhere
        # would silently truncate the line that carries it.
        self.assertNotIn(";", headerText)

        for lineNumber, line in enumerate(headerText.splitlines(), start=1):
            with self.subTest(lineNumber=lineNumber):
                self.assertLess(len(line.encode("ascii")), support.UC1_MAX_PATH_LENGTH)

        values = support.parseHeaderTheWayHsCubeLoaderDoes(headerPath)
        self.assertEqual(values["data type"], "12")
        self.assertEqual(values["interleave"], "bsq")
        self.assertEqual(values["data file"], envi.RAW_DATA_FILE_NAME)
        self.assertEqual(values["samples"], str(TEST_SAMPLES))
        self.assertEqual(values["lines"], str(TEST_LINES))
        self.assertEqual(values["bands"], str(TEST_BANDS))
        self.assertIn(envi.DATASET_MARKER, headerText)

        # The three keys UC1 scans for must precede the wavelength block,
        # because its parser stops after three hits.
        headerLines = headerText.splitlines()
        wavelengthIndex = next(
            index for index, line in enumerate(headerLines) if line.startswith("wavelength")
        )
        for key in ("samples", "lines", "bands"):
            with self.subTest(key=key):
                keyIndex = next(
                    index for index, line in enumerate(headerLines) if line.startswith(f"{key} = ")
                )
                self.assertLess(keyIndex, wavelengthIndex)

    def test_writerInterlocksRefuseUnsafeTargets(self):
        rawCube, whiteCube, darkCube, wavelengthsNm = support.buildTinyCubes()

        # UC1 builds "<folder>/whiteReference.dat" with snprintf into a
        # 128-byte buffer, so an over-long folder path is truncated in silence.
        longFolder = self.workingRoot
        while len(str((longFolder / envi.WHITE_REFERENCE_FILE_NAME).resolve())) < support.UC1_MAX_PATH_LENGTH:
            longFolder = longFolder / "deeper-than-uc1-can-address"
        with self.assertRaises(envi.DatasetWriteError) as overLongPath:
            envi.writeDataset(longFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
        self.assertIn(str(support.UC1_MAX_PATH_LENGTH), str(overLongPath.exception))

        # A folder whose header lacks the marker was not written by us.
        foreignFolder = self.workingRoot / "sim-20260902-131415"
        foreignFolder.mkdir()
        (foreignFolder / envi.HEADER_FILE_NAME).write_text(
            "ENVI\nsamples = 8\nlines = 4\nbands = 6\n", encoding="ascii"
        )
        with self.assertRaises(envi.DatasetWriteError) as unmarked:
            envi.writeDataset(foreignFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
        self.assertIn(envi.DATASET_MARKER, str(unmarked.exception))

        # Overwriting our own dataset is allowed.
        ownFolder = self.workingRoot / "sim-20260902-161718"
        self.writeTinyDataset(ownFolder)
        self.writeTinyDataset(ownFolder)

    def test_anOccupiedFolderWithNoHeaderIsRefused(self):
        rawCube, whiteCube, darkCube, wavelengthsNm = support.buildTinyCubes()

        # No raw.hdr means no marker to check, so the marker interlock cannot
        # clear this folder - and writing would replace raw.dat regardless.
        # `--dataset-folder` takes an arbitrary path, so a typo reaches here.
        occupiedFolder = self.workingRoot / "somebody-elses-work"
        occupiedFolder.mkdir()
        sentinelPath = occupiedFolder / envi.RAW_DATA_FILE_NAME
        sentinelPath.write_bytes(b"not ours")

        with self.assertRaises(envi.DatasetWriteError) as refused:
            envi.writeDataset(occupiedFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
        self.assertIn(envi.RAW_DATA_FILE_NAME, str(refused.exception))
        self.assertEqual(sentinelPath.read_bytes(), b"not ours")

        # An empty folder is a fresh target, not somebody's work.
        emptyFolder = self.workingRoot / "prepared-but-empty"
        emptyFolder.mkdir()
        self.writeTinyDataset(emptyFolder)
        self.assertTrue((emptyFolder / envi.HEADER_FILE_NAME).is_file())

    def test_weightVectorMatchesTheBandCount(self):
        datasetFolder = self.workingRoot / "sim-20260902-101112"
        self.writeTinyDataset(datasetFolder)

        weightVectorPath = (
            datasetFolder / envi.SVM_MODEL_DIRECTORY_NAME / envi.WEIGHT_VECTOR_FILE_NAME
        )
        expectedBytes = TEST_BANDS * envi.SVM_BINARY_CLASSIFIER_COUNT * 4
        self.assertEqual(weightVectorPath.stat().st_size, expectedBytes)

    def test_datasetFolderNameUsesTheAgreedStamp(self):
        import datetime

        moment = datetime.datetime(2026, 9, 2, 10, 11, 12)
        self.assertEqual(envi.datasetFolderName(moment), "sim-20260902-101112")


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
                "wavelength = {\n", "wavelength = {\nnot-a-wavelength\n", 1
            ),
            "samples": lambda text: text.replace(
                f"samples = {TEST_SAMPLES}\n", "samples = eight\n", 1
            ),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(corruption=name):
                datasetFolder = self.workingRoot / f"sim-20260913-{name}"
                self.writeTinyDataset(datasetFolder)
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
        self.assertFalse(datasetRef.simulated)
        self.assertTrue(datasetRef.approvedInput)
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
                self.assertFalse(datasetRef.approvedInput)

    def test_recordedCaseIsNeverAWriteTarget(self):
        caseFolder = support.writeRecordedCaseFixture(self.workingRoot / "004-02")
        before = support.folderFingerprint(caseFolder)
        rawCube, whiteCube, darkCube, wavelengthsNm = support.buildTinyCubes()

        with self.assertRaises(envi.DatasetWriteError) as refused:
            envi.writeDataset(caseFolder, rawCube, whiteCube, darkCube, wavelengthsNm)

        self.assertIn(envi.DATASET_MARKER, str(refused.exception))
        self.assertEqual(support.folderFingerprint(caseFolder), before)

    def writeTinyDataset(self, datasetFolder: Path):
        rawCube, whiteCube, darkCube, wavelengthsNm = support.buildTinyCubes()
        return envi.writeDataset(datasetFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
