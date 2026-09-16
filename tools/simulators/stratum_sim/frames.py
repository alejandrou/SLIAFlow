"""The LiveView frame source for the acquisition stand-in: the laptop camera.

`SLIAFlowLogic.startCamera` also opens camera index 0, and Windows fails the
second open, so this source and the SLIAFlow live pane cannot both run.
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


class WebcamFrameSource:
    """A real camera, resized to the configured frame size.

    OpenCV is imported here rather than at module scope so the rest of the
    package, and its tests, never need it.
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
