"""Direct tests for acquisition frame sources; no physical webcam is used."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy

from stratum_sim import frames


class SyntheticFrameSourceTest(unittest.TestCase):

    def test_seededSourcesProduceTheSameSequence(self):
        first = frames.SyntheticFrameSource(samples=12, lines=8, seed=37)
        second = frames.SyntheticFrameSource(samples=12, lines=8, seed=37)

        for _frameIndex in range(3):
            numpy.testing.assert_array_equal(first.read(), second.read())

    def test_frameMovesAndSatisfiesTheSourceProtocol(self):
        source = frames.SyntheticFrameSource(samples=12, lines=8, seed=37)

        first = source.read()
        second = source.read()

        self.assertIsInstance(source, frames.FrameSource)
        self.assertEqual(first.shape, (8, 12, 3))
        self.assertEqual(first.dtype, numpy.uint8)
        self.assertFalse(numpy.array_equal(first, second))


class ResizeFrameTest(unittest.TestCase):

    def test_matchingDimensionsReturnTheOriginalArray(self):
        frame = numpy.zeros((3, 5, 3), dtype=numpy.uint8)
        self.assertIs(frames.resizeFrame(frame, samples=5, lines=3), frame)

    def test_opencvReceivesWidthBeforeHeight(self):
        original = numpy.zeros((3, 5, 3), dtype=numpy.uint8)
        resized = numpy.ones((4, 7, 3), dtype=numpy.uint8)
        calls = []
        fakeCv2 = SimpleNamespace(
            INTER_AREA=17,
            resize=lambda frame, size, interpolation: (
                calls.append((frame, size, interpolation)) or resized
            ),
        )

        with mock.patch.dict(sys.modules, {"cv2": fakeCv2}):
            actual = frames.resizeFrame(original, samples=7, lines=4)

        self.assertIs(actual, resized)
        self.assertEqual(calls, [(original, (7, 4), fakeCv2.INTER_AREA)])

    def test_numpyFallbackUsesNearestSampleLocations(self):
        original = numpy.arange(4 * 6 * 3, dtype=numpy.uint8).reshape((4, 6, 3))
        expected = original[[0, 3]][:, [0, 2, 5]]

        with mock.patch.dict(sys.modules, {"cv2": None}):
            actual = frames.resizeFrame(original, samples=3, lines=2)

        numpy.testing.assert_array_equal(actual, expected)


class FakeCapture:

    def __init__(self, opened: bool, reads=()):
        self.opened = opened
        self.reads = list(reads)
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        return self.reads.pop(0)

    def release(self):
        self.released = True


class WebcamFrameSourceTest(unittest.TestCase):

    def fakeCv2(self, capture):
        return SimpleNamespace(VideoCapture=lambda _cameraIndex: capture)

    def test_closedCaptureIsRejected(self):
        capture = FakeCapture(opened=False)
        with mock.patch.dict(sys.modules, {"cv2": self.fakeCv2(capture)}):
            with self.assertRaises(RuntimeError) as raised:
                frames.WebcamFrameSource(cameraIndex=4, samples=8, lines=6)
        self.assertIn("4", str(raised.exception))

    def test_failedAndEmptyReadsReturnNone(self):
        capture = FakeCapture(opened=True, reads=((False, object()), (True, None)))
        with mock.patch.dict(sys.modules, {"cv2": self.fakeCv2(capture)}):
            source = frames.WebcamFrameSource(cameraIndex=0, samples=8, lines=6)
        self.assertIsNone(source.read())
        self.assertIsNone(source.read())

    def test_closeReleasesTheCapture(self):
        capture = FakeCapture(opened=True)
        with mock.patch.dict(sys.modules, {"cv2": self.fakeCv2(capture)}):
            source = frames.WebcamFrameSource(cameraIndex=0, samples=8, lines=6)
        source.close()
        self.assertTrue(capture.released)


class FrameSourceFactoryTest(unittest.TestCase):

    def test_factoryRoutesEverySupportedSourceAndRejectsUnknownNames(self):
        synthetic = object()
        webcam = object()
        with (
            mock.patch.object(frames, "SyntheticFrameSource", return_value=synthetic) as makeSynthetic,
            mock.patch.object(frames, "WebcamFrameSource", return_value=webcam) as makeWebcam,
        ):
            self.assertIs(frames.createFrameSource("synthetic", 8, 6, 37, 4), synthetic)
            self.assertIs(frames.createFrameSource("webcam", 8, 6, 37, 4), webcam)

        makeSynthetic.assert_called_once_with(8, 6, 37)
        makeWebcam.assert_called_once_with(4, 8, 6)
        with self.assertRaises(ValueError):
            frames.createFrameSource("telepathy", 8, 6, 37, 4)


if __name__ == "__main__":
    unittest.main()
