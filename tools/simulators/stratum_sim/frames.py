"""Frame sources for the acquisition stand-in.

`synthetic` and `webcam` are interchangeable behind one protocol, so the rest of
the simulator never learns which one it is driving. `synthetic` is the default:
`SLIAFlowLogic.startCamera` also opens camera index 0, and Windows fails the
second open, so a webcam source and the SLIAFlow live pane cannot both run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy


@runtime_checkable
class FrameSource(Protocol):
    """Produce BGR frames of a fixed size.

    `read()` returns a (lines, samples, 3) uint8 BGR array, or `None` when no
    new frame is available. `None` is not an error: the sender only puts a frame
    on the wire when the sequence changes, exactly as the C++ sender does.
    """

    def read(self) -> numpy.ndarray | None:
        ...


class SyntheticFrameSource:
    """An animated scene with no camera behind it.

    Three drifting blobs, one per colour channel, over a slow gradient. The
    scene has to be non-degenerate, not realistic, so nothing here tries to look
    like tissue.
    """

    BLOB_RADIUS_FRACTION = 0.28
    DRIFT_PERIOD_FRAMES = 90.0
    BACKGROUND_LEVEL = 0.12

    def __init__(self, samples: int, lines: int, seed: int = 0) -> None:
        self.samples = samples
        self.lines = lines
        self.frameIndex = 0

        self._x = numpy.linspace(0.0, 1.0, samples, dtype=numpy.float32)[None, :]
        self._y = numpy.linspace(0.0, 1.0, lines, dtype=numpy.float32)[:, None]
        # Fixed per-channel phase offsets, so the three blobs never coincide and
        # the channel planes stay distinguishable.
        self._phases = numpy.random.default_rng(seed).uniform(0.0, 2.0 * numpy.pi, size=3)

    def read(self) -> numpy.ndarray:
        progress = 2.0 * numpy.pi * (self.frameIndex / self.DRIFT_PERIOD_FRAMES)
        radius = self.BLOB_RADIUS_FRACTION

        planes = []
        for channelIndex in range(3):
            phase = float(self._phases[channelIndex]) + progress
            centreX = 0.5 + 0.3 * numpy.cos(phase)
            centreY = 0.5 + 0.3 * numpy.sin(phase * 1.3)
            distanceSquared = (self._x - centreX) ** 2 + (self._y - centreY) ** 2
            blob = numpy.exp(-distanceSquared / (2.0 * radius**2))
            planes.append(self.BACKGROUND_LEVEL + (1.0 - self.BACKGROUND_LEVEL) * blob)

        frame = numpy.stack(numpy.broadcast_arrays(*planes), axis=-1)
        self.frameIndex += 1
        return numpy.clip(frame * 255.0, 0.0, 255.0).astype(numpy.uint8)


class WebcamFrameSource:
    """A real camera, resized to the configured frame size.

    OpenCV is imported here rather than at module scope so the synthetic path
    never needs it.
    """

    def __init__(self, cameraIndex: int, samples: int, lines: int) -> None:
        import cv2

        self._cv2 = cv2
        self.samples = samples
        self.lines = lines

        self._capture = cv2.VideoCapture(cameraIndex)
        if not self._capture.isOpened():
            raise RuntimeError(
                f"Camera index {cameraIndex} could not be opened. On Windows only one process "
                "can hold a camera, so close the SLIAFlow live pane before using this source."
            )

    def read(self) -> numpy.ndarray | None:
        succeeded, frame = self._capture.read()
        if not succeeded or frame is None:
            return None
        return resizeFrame(frame, self.samples, self.lines)

    def close(self) -> None:
        self._capture.release()


def resizeFrame(frameBgr: numpy.ndarray, samples: int, lines: int) -> numpy.ndarray:
    """Resize a BGR frame to (lines, samples, 3), using OpenCV when it is present."""
    if frameBgr.shape[0] == lines and frameBgr.shape[1] == samples:
        return frameBgr

    try:
        import cv2
    except ImportError:
        rowIndices = numpy.linspace(0, frameBgr.shape[0] - 1, lines).round().astype(int)
        columnIndices = numpy.linspace(0, frameBgr.shape[1] - 1, samples).round().astype(int)
        return frameBgr[rowIndices][:, columnIndices]

    return cv2.resize(frameBgr, (samples, lines), interpolation=cv2.INTER_AREA)


def createFrameSource(frameSource: str, samples: int, lines: int, seed: int, webcamIndex: int):
    """Build the configured frame source."""
    if frameSource == "synthetic":
        return SyntheticFrameSource(samples, lines, seed)
    if frameSource == "webcam":
        return WebcamFrameSource(webcamIndex, samples, lines)
    raise ValueError(f"Unknown frame source {frameSource!r}.")
