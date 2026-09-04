"""Tests for the UC1-compatible bitmap writer and class palette."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import bmp

BMP_FILE_HEADER_BYTES = 14
BMP_INFO_HEADER_BYTES = 40
BMP_PIXEL_OFFSET = BMP_FILE_HEADER_BYTES + BMP_INFO_HEADER_BYTES


class BmpWriterTest(unittest.TestCase):
    def test_bmpMatchesHandComputedReference(self) -> None:
        # Source rows are top-to-bottom. The C writer stores the bottom row
        # first and writes each pixel as B, G, R.
        red = numpy.array([[255, 0], [0, 0]], dtype=numpy.uint8)
        green = numpy.array([[0, 255], [0, 0]], dtype=numpy.uint8)
        blue = numpy.array([[0, 0], [255, 0]], dtype=numpy.uint8)

        with tempfile.TemporaryDirectory() as temporaryDirectory:
            outputPath = Path(temporaryDirectory) / "reference.bmp"
            bmp.writeBMP(outputPath, red, green, blue)
            actual = outputPath.read_bytes()

        # The C code's file-size field counts the pixel bytes alone:
        # 54 + 3*2*2 = 66, while the file is 70 bytes because each 2-pixel row
        # of 6 bytes is padded to an 8-byte boundary.
        declaredPixelBytes = 3 * red.shape[0] * red.shape[1]
        expectedFileHeader = struct.pack(
            "<2sIHHI",
            b"BM",
            BMP_PIXEL_OFFSET + declaredPixelBytes,
            0,
            0,
            BMP_PIXEL_OFFSET,
        )
        expectedInfoHeader = struct.pack(
            "<IiiHHIIiiII",
            BMP_INFO_HEADER_BYTES,
            red.shape[1],
            red.shape[0],
            1,
            24,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        expectedPixels = bytes.fromhex(
            "ff 00 00 00 00 00 00 00 "
            "00 00 ff 00 ff 00 00 00"
        )
        self.assertEqual(actual, expectedFileHeader + expectedInfoHeader + expectedPixels)

    def test_classMapBmpUsesThePaletteOnTheContractShape(self) -> None:
        # The class map arrives from the contract as (1, lines, samples), so
        # the writer has to accept that shape and not only a bare 2-D image.
        classMap = numpy.array([[[1, 2], [3, 4]]], dtype=numpy.uint8)

        with tempfile.TemporaryDirectory() as temporaryDirectory:
            outputPath = Path(temporaryDirectory) / "classes.bmp"
            bmp.writeClassMapBMP(outputPath, classMap)
            actual = outputPath.read_bytes()

        # Bottom row first, each pixel B, G, R, two padding bytes per row:
        # class 3 blue then class 4 black, then class 1 green then class 2 red.
        expectedPixels = bytes.fromhex(
            "ff 00 00 00 00 00 00 00 "
            "00 ff 00 00 00 ff 00 00"
        )
        self.assertEqual(len(actual), BMP_PIXEL_OFFSET + len(expectedPixels))
        self.assertEqual(actual[BMP_PIXEL_OFFSET:], expectedPixels)

    def test_paletteRoundTripsForAllClasses(self) -> None:
        classMap = numpy.array([[1, 2], [3, 4]], dtype=numpy.uint8)

        rgb = bmp.classMapToRgb(classMap)
        roundTripped = bmp.rgbToClassMap(rgb)

        self.assertTrue(numpy.array_equal(roundTripped, classMap))
        self.assertEqual(
            bmp.CLASS_TO_RGB,
            {
                1: (0, 255, 0),
                2: (255, 0, 0),
                3: (0, 0, 255),
                4: (0, 0, 0),
            },
        )


if __name__ == "__main__":
    unittest.main()
