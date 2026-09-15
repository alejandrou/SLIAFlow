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

import ctypes
import logging
import os
import select
import signal
import socket
import sys
import threading
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

# How often the client watch looks at its port.
CLIENT_WATCH_POLL_SEC = 0.1

# How long a connection must stay queued behind the served client before the TCP
# table is asked whether it really is a second client. A departed client is let
# go within one pyigtl read of its close; before that check existed the slowest
# measured release was 1.01 s, at UC1's 1.0 s interval. Either way an ordinary
# reconnection clears first.
WAITING_CLIENT_GRACE_SEC = 2.0

# A stopped watch finishes its current poll; this bounds the wait for one that
# does not.
CLIENT_WATCH_JOIN_TIMEOUT_SEC = 5.0

# Windows IP Helper values for `GetExtendedTcpTable`.
_AF_INET = 2
_TCP_TABLE_OWNER_PID_ALL = 5
_MIB_TCP_STATE_ESTAB = 5
_NO_ERROR = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_TCP_TABLE_READ_ATTEMPTS = 4


class _TcpRowOwnerPid(ctypes.Structure):
    """`MIB_TCPROW_OWNER_PID`: six DWORDs, the ports in network byte order."""

    _fields_ = [
        ("state", ctypes.c_uint32),
        ("localAddr", ctypes.c_uint32),
        ("localPort", ctypes.c_uint32),
        ("remoteAddr", ctypes.c_uint32),
        ("remotePort", ctypes.c_uint32),
        ("owningPid", ctypes.c_uint32),
    ]


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


def establishedServerConnectionCount(port: int) -> int | None:
    """Count this process's established IPv4 connections whose local port is `port`.

    Those rows are the server side of every client attached to a producer on
    that port, the one being served and any queued behind it. A client that
    gave up while queued has no `ESTABLISHED` row, although the listening socket
    goes on reporting its connection as pending.

    Only rows owned by this process count, so the clients of another producer
    bound to the same port are not mistaken for this one's. The table is read
    through the IP Helper API rather than by parsing `netstat`, whose state names
    are translated on localised Windows. Returns `None` where it cannot be read.
    """
    if sys.platform != "win32":
        return None

    getExtendedTcpTable = ctypes.windll.iphlpapi.GetExtendedTcpTable
    getExtendedTcpTable.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint32,
    ]
    getExtendedTcpTable.restype = ctypes.c_uint32

    # The table can grow between asking for its size and reading it.
    size = ctypes.c_uint32(0)
    for _attempt in range(_TCP_TABLE_READ_ATTEMPTS):
        buffer = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(ctypes.c_uint32)))
        result = getExtendedTcpTable(
            buffer, ctypes.byref(size), False, _AF_INET, _TCP_TABLE_OWNER_PID_ALL, 0
        )
        if result == _NO_ERROR:
            break
        if result != _ERROR_INSUFFICIENT_BUFFER:
            return None
    else:
        return None

    # `MIB_TCPTABLE_OWNER_PID` is a DWORD row count followed by the rows.
    rowCount = ctypes.c_uint32.from_buffer(buffer).value
    rows = (_TcpRowOwnerPid * rowCount).from_buffer(buffer, ctypes.sizeof(ctypes.c_uint32))
    processId = os.getpid()
    return sum(
        1
        for row in rows
        if row.state == _MIB_TCP_STATE_ESTAB
        and row.owningPid == processId
        and socket.ntohs(row.localPort & 0xFFFF) == port
    )


def hasQueuedConnection(listeningSocket: socket.socket) -> bool:
    """Whether a connection is waiting in the listening socket's accept backlog."""
    readable, _writable, _errored = select.select([listeningSocket], [], [], 0)
    return bool(readable)


def waitingClientWarning(address: str, attachedCount: int) -> str:
    """The operator-facing warning for clients starved behind the one being served."""
    return (
        f"WARNING: {address} has {attachedCount} clients attached, and a producer serves one "
        "client at a time. The client being served receives everything; every other attached "
        "client shows as connected and receives nothing until the one being served is closed. "
        "Close the other client - most often a Slicer left open from an earlier session."
    )


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


class ClientWatch:
    """Tell the operator how many clients a producer serves, and when one is starved.

    pyigtl's server handles a connection on its serving thread and does not
    accept another until that one ends. A second client is therefore never an
    accepted connection the server could count: it completes its handshake in
    the accept backlog, reports itself connected, and receives nothing. What the
    server does own is its listening socket, which reports that queued
    connection without accepting it.

    On Windows the listening socket keeps reporting a queued connection after
    the client behind it has given up. So the listening socket raises the alarm
    and the TCP table confirms it before anything is printed; where the table
    cannot be read, nothing is claimed.

    Lines go to standard output, flushed, because that is the stream the session
    launcher shows under the producer's name.
    """

    def __init__(
        self,
        server: pyigtl.OpenIGTLinkServer,
        port: int,
        graceSec: float = WAITING_CLIENT_GRACE_SEC,
    ) -> None:
        self._server = server
        self._port = port
        self._graceSec = graceSec
        self._address = f"127.0.0.1:{port}"
        self._stopRequested = threading.Event()
        self._thread = threading.Thread(
            target=self._watch, name=f"ClientWatch-{port}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Stop watching. Must return before the pyigtl server closes its socket."""
        self._stopRequested.set()
        if self._thread.is_alive():
            self._thread.join(timeout=CLIENT_WATCH_JOIN_TIMEOUT_SEC)

    def _watch(self) -> None:
        serving = False
        queuedSince: float | None = None
        warned = False

        while not self._stopRequested.wait(CLIENT_WATCH_POLL_SEC):
            try:
                nowServing = bool(self._server.is_connected())
                queued = nowServing and hasQueuedConnection(self._server.socket)
            except (OSError, ValueError):
                return

            if nowServing != serving:
                serving = nowServing
                self._report(
                    f"{self._address}: serving 1 client."
                    if serving
                    else f"{self._address}: serving 0 clients."
                )

            now = time.monotonic()
            if not queued:
                queuedSince = None
            elif queuedSince is None:
                queuedSince = now

            if queuedSince is None or now - queuedSince < self._graceSec:
                attachedCount = 0
            else:
                attachedCount = establishedServerConnectionCount(self._port)
                if attachedCount is None:
                    continue

            if attachedCount >= 2 and not warned:
                self._report(waitingClientWarning(self._address, attachedCount))
                warned = True
            elif attachedCount < 2 and warned:
                self._report(
                    f"{self._address}: only one client is attached again; "
                    "the warning above no longer applies."
                )
                warned = False

    @staticmethod
    def _report(line: str) -> None:
        print(line, flush=True)


class _DepartureAwareServer(pyigtl.OpenIGTLinkServer):
    """pyigtl's server, letting a client go as soon as that client closes.

    pyigtl reads an orderly close - an empty read - as "no message yet", so on its
    own it learns that a client has gone only when a send to it fails. A port that
    sends rarely therefore went on serving a client that had left: on the HSCube
    port between captures the replacement waited unserved behind it, and the next
    cube was queued for the closed connection and never received.

    Before each read this peeks at one byte. An empty peek is the close, and
    raising ends pyigtl's handler exactly as a failed send does, so the next
    client is accepted. Everything else is pyigtl's own reading.
    """

    def _receive_message_from_socket(self, ssocket: socket.socket) -> bool:
        try:
            peeked = ssocket.recv(1, socket.MSG_PEEK)
        except socket.timeout:
            return False
        if not peeked:
            raise ConnectionAbortedError("The client closed the connection.")
        return super()._receive_message_from_socket(ssocket)


class ImageStreamServer:
    """A server socket that sends image messages, as the C++ sender does.

    The real acquisition application listens and SLIAFlow connects, so the
    stand-in listens too. Swapping one for the other is stopping this process
    and starting that one on the same port.

    A `ClientWatch` runs for as long as the server does, so every producer built
    on this class reports its clients and warns about a starved one.
    """

    def __init__(self, port: int = DEFAULT_LIVE_VIEW_PORT) -> None:
        self.port = port
        self._server: pyigtl.OpenIGTLinkServer | None = None
        self._clientWatch: ClientWatch | None = None

    def __enter__(self) -> ImageStreamServer:
        self.start()
        return self

    def __exit__(self, exceptionType, exceptionValue, traceback) -> None:
        self.stop()

    def start(self) -> None:
        if self._server is None:
            self._server = _DepartureAwareServer(port=self.port, local_server=True)
            self._clientWatch = ClientWatch(self._server, self.port)
            self._clientWatch.start()

    def stop(self) -> None:
        if self._clientWatch is not None:
            self._clientWatch.stop()
            self._clientWatch = None
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

    def receiveStrings(self, deviceName: str) -> list[str]:
        """Return the text of STRING messages received under one name since the last call.

        pyigtl keeps only the latest message per device name, so two messages
        under the same name between calls arrive as one; a command polled every
        frame loses nothing a person could press twice that fast. Messages under
        any other name are discarded.
        """
        if self._server is None:
            raise RuntimeError("The image stream server was not started.")
        return [
            message.string
            for message in self._server.get_latest_messages()
            if isinstance(message, pyigtl.StringMessage) and message.device_name == deviceName
        ]

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
