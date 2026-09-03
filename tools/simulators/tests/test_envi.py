"""ENVI dataset writer tests, checked against the consumers' own parsing rules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import envi
from tests import support

TEST_SAMPLES = 8
TEST_LINES = 4
TEST_BANDS = 6
BYTES_PER_SAMPLE = 2


def buildTinyCubes() -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    shape = (TEST_BANDS, TEST_LINES, TEST_SAMPLES)
    voxelCount = TEST_BANDS * TEST_LINES * TEST_SAMPLES

    darkCube = numpy.full(shape, 1200, dtype=numpy.uint16)
    whiteCube = numpy.full(shape, 51200, dtype=numpy.uint16)
    rawCube = (
        numpy.arange(voxelCount, dtype=numpy.uint16).reshape(shape) % 40000 + 1200
    ).astype(numpy.uint16)
    wavelengthsNm = numpy.linspace(400.482, 1000.73, TEST_BANDS)
    return rawCube, whiteCube, darkCube, wavelengthsNm


class DatasetWriterTest(unittest.TestCase):

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.workingRoot = Path(self._temporaryDirectory.name)
        self.addCleanup(self._temporaryDirectory.cleanup)

    def writeTinyDataset(self, datasetFolder: Path):
        rawCube, whiteCube, darkCube, wavelengthsNm = buildTinyCubes()
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
        rawCube, _, _, _ = buildTinyCubes()
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
        rawCube, whiteCube, darkCube, wavelengthsNm = buildTinyCubes()

        # UC1 builds "<folder>/whiteReference.dat" with snprintf into a
        # 128-byte buffer, so an over-long folder path is truncated in silence.
        longFolder = self.workingRoot
        while len(str((longFolder / envi.WHITE_REFERENCE_FILE_NAME).resolve())) < support.UC1_MAX_PATH_LENGTH:
            longFolder = longFolder / "deeper-than-uc1-can-address"
        with self.assertRaises(envi.DatasetWriteError) as overLongPath:
            envi.writeDataset(longFolder, rawCube, whiteCube, darkCube, wavelengthsNm)
        self.assertIn("128", str(overLongPath.exception))

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
        rawCube, whiteCube, darkCube, wavelengthsNm = buildTinyCubes()

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
