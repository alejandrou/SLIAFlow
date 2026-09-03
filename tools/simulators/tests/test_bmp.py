"""Tests for the UC1-compatible bitmap writer and class palette."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import bmp


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

        # The C code's file-size field is 54 + 3*w*h = 66. It omits the two
        # padding bytes required at the end of each 2-pixel row.
        expectedHeader = bytes.fromhex(
            "42 4d 42 00 00 00 00 00 00 00 36 00 00 00"
        ) + bytes(
            [
                40,
                0,
                0,
                0,
                2,
                0,
                0,
                0,
                2,
                0,
                0,
                0,
                1,
                0,
                24,
                0,
            ]
            + [0] * 24
        )
        expectedPixels = bytes.fromhex(
            "ff 00 00 00 00 00 00 00 "
            "00 00 ff 00 ff 00 00 00"
        )
        self.assertEqual(actual, expectedHeader + expectedPixels)

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
        self.assertEqual(len(actual), 54 + len(expectedPixels))
        self.assertEqual(actual[54:], expectedPixels)

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
