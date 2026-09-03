"""OpenIGTLink sending, with provenance that actually reaches the wire.

Every message this module builds is set to header version 2. That is measured,
not assumed. On pyigtl 0.3.4 a freshly constructed `ImageMessage` has
`header_version = 1`; packing the four provenance keys at version 1 emits a
`logger.warning` reading "Metadata will not be packed" and then returns a
well-formed 146-byte message whose metadata unpacks to `{}`. The identical
message at version 2 packs to 316 bytes and round-trips all four keys. So a
version-1 send drops every provenance attribute silently, behind a
successful-looking send and a warning on the wrong side of the wire.

`metadata` is not a constructor argument: `ImageMessage.__init__` takes only
`image`, `ijk_to_world_matrix`, `world_coordinate_system`, `timestamp` and
`device_name`. Both `metadata` and `header_version` are plain attributes
assigned after construction, and they are assigned in exactly one place here so
that no producer can forget either.
"""

from __future__ import annotations

import logging
import signal
import time
from importlib import metadata as importlib_metadata

import numpy
import pyigtl

logger = logging.getLogger(__name__)

IGTL_HEADER_VERSION_WITH_METADATA = 2

# `OpenIGTLinkServer.cpp` serves LiveView from a server socket on this address;
# SLIAFlow connects to it as a client.
DEFAULT_LIVE_VIEW_PORT = 18944

RECONNECT_DELAY_SEC = 1.0


def installedPyigtlVersion() -> str:
    """Return the installed pyigtl version from distribution metadata.

    `pyigtl/_version.py` was not bumped for the 0.3.4 release, so
    `pyigtl.__version__` reports 0.3.2. A check written against that attribute
    would record a version that is simply false, and would keep passing while
    doing so.
    """
    return importlib_metadata.version("pyigtl")


def prepareFrameForWire(frameBgr: numpy.ndarray, rotate180: bool) -> numpy.ndarray:
    """Turn an (lines, samples, 3) BGR frame into pyigtl's (k, j, i, components).

    `GUI.cpp` calls `std::reverse` over the whole `Format24bppRgb` buffer, which
    in one pass flips the rows, flips the columns and swaps BGR to RGB. The
    channel swap happens whether or not the rotation is wanted, so it is applied
    unconditionally here and only the spatial flip is optional.
    """
    if frameBgr.ndim != 3 or frameBgr.shape[2] != 3:
        raise ValueError(f"Expected an (lines, samples, 3) BGR frame, got {frameBgr.shape}.")

    frameRgb = frameBgr[..., ::-1]
    if rotate180:
        frameRgb = frameRgb[::-1, ::-1]

    return numpy.ascontiguousarray(frameRgb, dtype=numpy.uint8)[numpy.newaxis, ...]


def buildImageMessage(
    image: numpy.ndarray, deviceName: str, metadata: dict[str, str]
) -> pyigtl.ImageMessage:
    """Build an image message that carries its metadata.

    The identity `ijk_to_world_matrix` and the default LPS coordinate system
    reproduce the C++ sender field for field: dimensions `{w, h, 1}`, spacing
    `{1, 1, 1}`, identity matrix, LPS.
    """
    message = pyigtl.ImageMessage(
        image=image,
        ijk_to_world_matrix=numpy.eye(4),
        world_coordinate_system="lps",
        device_name=deviceName,
    )
    message.header_version = IGTL_HEADER_VERSION_WITH_METADATA
    message.metadata = dict(metadata)
    return message


def buildStringMessage(text: str, deviceName: str) -> pyigtl.StringMessage:
    """Build the optional wire-level simulator notice message."""
    return pyigtl.StringMessage(string=text, device_name=deviceName)


class InterruptFlag:
    """Turn Ctrl-C into a clean shutdown rather than a traceback.

    This must be installed *after* the OpenIGTLink server exists.
    `pyigtl.OpenIGTLinkServer.__init__` registers its own SIGINT and SIGTERM
    handlers, which close the socket and then re-send the signal to the default
    handler, so a flag installed before the server is silently replaced and the
    shutdown message never runs.

    SIGBREAK is handled alongside SIGINT where it exists: on Windows Ctrl-C and
    Ctrl-Break arrive as different signals, and both mean stop.
    """

    def __init__(self) -> None:
        self.requested = False
        self._previousHandlers: dict[int, object] = {}

        for signalName in ("SIGINT", "SIGBREAK"):
            signalNumber = getattr(signal, signalName, None)
            if signalNumber is not None:
                self._previousHandlers[signalNumber] = signal.signal(signalNumber, self._handle)

    def __enter__(self) -> InterruptFlag:
        return self

    def __exit__(self, exceptionType, exceptionValue, traceback) -> None:
        self.restore()

    def _handle(self, signalNumber, stackFrame) -> None:
        self.requested = True

    def restore(self) -> None:
        for signalNumber, previousHandler in self._previousHandlers.items():
            signal.signal(signalNumber, previousHandler)
        self._previousHandlers.clear()


class ImageStreamServer:
    """A server socket that sends image messages, as the C++ sender does.

    The real acquisition application listens and SLIAFlow connects, so the
    stand-in listens too. Swapping one for the other is stopping this process
    and starting that one on the same port.
    """

    def __init__(self, port: int = DEFAULT_LIVE_VIEW_PORT) -> None:
        self.port = port
        self._server: pyigtl.OpenIGTLinkServer | None = None

    def __enter__(self) -> ImageStreamServer:
        self.start()
        return self

    def __exit__(self, exceptionType, exceptionValue, traceback) -> None:
        self.stop()

    def start(self) -> None:
        if self._server is None:
            self._server = pyigtl.OpenIGTLinkServer(port=self.port, local_server=True)

    def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._server = None

    @property
    def isConnected(self) -> bool:
        return self._server is not None and bool(self._server.is_connected())

    def sendImage(self, image: numpy.ndarray, deviceName: str, metadata: dict[str, str]) -> bool:
        """Queue one image message for sending.

        `True` means the message was accepted onto the server's writer thread,
        not that a client received it: `send_message(wait=False)` returns as soon
        as the message is queued. A rate measured from this return value is
        therefore an upper bound on delivered throughput.

        A failed send restarts the server socket rather than raising: a client
        that disconnects mid-demonstration must not take the producer down.
        """
        if self._server is None:
            raise RuntimeError("The image stream server was not started.")
        if not self._server.is_connected():
            return False

        message = buildImageMessage(image, deviceName, metadata)
        return self._sendMessage(message)

    def sendString(self, text: str, deviceName: str) -> bool:
        """Queue a string message, returning whether a client was connected."""
        if self._server is None:
            raise RuntimeError("The image stream server was not started.")
        if not self._server.is_connected():
            return False

        return self._sendMessage(buildStringMessage(text, deviceName))

    def _sendMessage(self, message: pyigtl.MessageBase) -> bool:
        try:
            self._server.send_message(message, wait=False)
        except (OSError, RuntimeError) as error:
            logger.warning("Send failed (%s); restarting the server socket.", error)
            self.stop()
            time.sleep(RECONNECT_DELAY_SEC)
            self.start()
            return False
        return True
