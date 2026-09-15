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
import errno
import logging
import os
import select
import signal
import socket
import sys
import threading
import time
from importlib import metadata as importlib_metadata
from pathlib import Path

import numpy
import pyigtl

from . import contract

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
_MIB_TCP_STATE_LISTEN = 2
_MIB_TCP_STATE_ESTAB = 5
_NO_ERROR = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_TCP_TABLE_READ_ATTEMPTS = 4
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_IMAGE_NAME_CHARS = 1024

# The bind failures that mean another socket already holds the address, measured on
# Windows 11 for SLIA-017: WSAEADDRINUSE when this server does not share its port,
# WSAEACCES when it asks to share a port whose holder did not.
_PORT_HELD_WINERRORS = (10048, 10013)
_PORT_HELD_ERRNOS = (errno.EADDRINUSE, errno.EACCES)


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


def _readTcpTable() -> ctypes.Array | None:
    """Read the IPv4 TCP table with owning PIDs, or `None` where it cannot be read.

    The table is read through the IP Helper API rather than by parsing `netstat`,
    whose state names are translated on localised Windows.
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
    return (_TcpRowOwnerPid * rowCount).from_buffer(buffer, ctypes.sizeof(ctypes.c_uint32))


def establishedServerConnectionCount(port: int) -> int | None:
    """Count this process's established IPv4 connections whose local port is `port`.

    Those rows are the server side of every client attached to a producer on
    that port, the one being served and any queued behind it. A client that
    gave up while queued has no `ESTABLISHED` row, although the listening socket
    goes on reporting its connection as pending.

    Only rows owned by this process count, so the clients of another producer
    bound to the same port are not mistaken for this one's. Returns `None` where
    the table cannot be read.
    """
    rows = _readTcpTable()
    if rows is None:
        return None

    processId = os.getpid()
    return sum(
        1
        for row in rows
        if row.state == _MIB_TCP_STATE_ESTAB
        and row.owningPid == processId
        and socket.ntohs(row.localPort & 0xFFFF) == port
    )


def listeningProcessIds(port: int) -> list[int]:
    """The PIDs of every process listening on IPv4 `port`, empty where unreadable.

    Only `LISTEN` rows count. A producer that stopped a moment ago leaves
    `TIME_WAIT` rows on its port, owned by PID 0, and those hold nothing.
    """
    rows = _readTcpTable()
    if rows is None:
        return []
    return sorted(
        {
            row.owningPid
            for row in rows
            if row.state == _MIB_TCP_STATE_LISTEN and socket.ntohs(row.localPort & 0xFFFF) == port
        }
    )


def processImageName(processId: int) -> str | None:
    """The executable file name of a process, or `None` where it cannot be read."""
    if sys.platform != "win32":
        return None

    # A private handle on kernel32, so the argument types set here do not leak into
    # `ctypes.windll.kernel32` for every other caller in the process.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, processId)
    if not handle:
        return None
    try:
        name = ctypes.create_unicode_buffer(_PROCESS_IMAGE_NAME_CHARS)
        size = ctypes.c_uint32(_PROCESS_IMAGE_NAME_CHARS)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return None
        return Path(name.value).name
    finally:
        kernel32.CloseHandle(handle)


class PortRefusedError(OSError):
    """A producer was asked to serve a port it must not serve (SLIA-017)."""


def _describeProcess(processId: int) -> str:
    description = f"PID {processId} ({processImageName(processId) or 'executable unknown'})"
    if processId == os.getpid():
        description += ", this producer's own process"
    return description


def portInUseMessage(port: int, holderIds: list[int], allowSharedPort: bool = False) -> str:
    """The operator-facing refusal of a port another socket is listening on.

    The PID named is the interpreter that owns the socket, the one `netstat`
    shows. Started through the repository `.venv` launcher, that is a child of the
    PID `Start-Process` reports, so the stop command names it rather than the
    launcher.
    """
    if holderIds:
        holders = ", ".join(_describeProcess(processId) for processId in holderIds)
    else:
        holders = "another process that could not be identified"
    message = f"127.0.0.1:{port} is already being served by {holders}. "
    if allowSharedPort:
        message += (
            "This producer was started with --allow-shared-port, but the one already serving "
            "the port was not started with --allow-shared-port, and a port is shared only when "
            "both producers are. Stop the other producer, or pass a different port."
        )
    else:
        message += (
            "A second producer on it would not take it over: both would listen, and a client "
            "would reach whichever one accepted. Stop the other producer, or pass a different "
            "port. Two producers share a port only when both are started with --allow-shared-port."
        )
    otherIds = [processId for processId in holderIds if processId != os.getpid()]
    if otherIds and sys.platform == "win32":
        message += f" To stop it: Stop-Process -Id {','.join(str(pid) for pid in otherIds)}"
    return message


def sharedPortWarning(port: int, otherIds: list[int]) -> str:
    """The warning a producer prints once it serves a port with `--allow-shared-port`."""
    if otherIds:
        others = ", ".join(_describeProcess(processId) for processId in otherIds)
        return (
            f"WARNING: 127.0.0.1:{port} is shared with {others}, started with "
            "--allow-shared-port too. A client reaches whichever producer accepts it, so what it "
            "receives can come from either. Stop one of them unless that is what you want."
        )
    return (
        f"WARNING: 127.0.0.1:{port} is served with --allow-shared-port. Another producer started "
        "with the same switch will join it without an error, and a client will then reach "
        "either one."
    )


def reservedPortMessage(port: int) -> str:
    """The operator-facing refusal of a reserved port, naming its channel."""
    return (
        f"127.0.0.1:{port} is reserved for {contract.RESERVED_PORTS[port]}, which has no "
        "producer yet, and nothing may listen on it: its panel has to be black because nothing "
        "listens, and for no other reason. Pass a different port. --allow-shared-port does not "
        "apply to a reserved port."
    )


def _meansPortIsHeld(error: OSError) -> bool:
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        return winerror in _PORT_HELD_WINERRORS
    return error.errno in _PORT_HELD_ERRNOS


def assertPortCanBeServed(port: int, allowSharedPort: bool = False) -> None:
    """Refuse, before a producer does any work, a port it must not serve.

    This is advisory. Another producer can take the port between this check and
    the bind, and the bind in `ImageStreamServer.start` is what enforces the
    refusal. The check exists so that a producer with a GPU run or a camera ahead
    of its server fails before that work rather than after it.

    The probe binds the way the server will, and never listens. Without
    `SO_REUSEADDR`, Windows refuses it while any socket listens on the address and
    allows it over `TIME_WAIT`. With `SO_REUSEADDR`, for `allowSharedPort`, Windows
    refuses it over a holder that did not set the option (`WinError 10013`) and
    allows it over one that did, which is exactly the rule the shared bind obeys.
    Measured on Windows 11 for SLIA-017, across two processes; the holder went on
    accepting clients after the probe.
    """
    if port in contract.RESERVED_PORTS:
        raise PortRefusedError(reservedPortMessage(port))

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if allowSharedPort:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError as error:
        if not _meansPortIsHeld(error):
            raise
        raise PortRefusedError(
            portInUseMessage(port, listeningProcessIds(port), allowSharedPort=allowSharedPort)
        ) from error
    finally:
        probe.close()


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

    It also does not share its port. pyigtl sets `allow_reuse_address` on
    `socketserver.TCPServer` before binding, and on Windows `SO_REUSEADDR` lets a
    second server bind a port another is listening on: both listen, and a client
    reaches whichever accepts. This class attribute is found before pyigtl's, so
    that bind is refused instead (SLIA-017). Windows rebinds over `TIME_WAIT`
    without `SO_REUSEADDR`, so a restart on the same port is unaffected.
    """

    allow_reuse_address = False

    def _receive_message_from_socket(self, ssocket: socket.socket) -> bool:
        try:
            peeked = ssocket.recv(1, socket.MSG_PEEK)
        except socket.timeout:
            return False
        if not peeked:
            raise ConnectionAbortedError("The client closed the connection.")
        return super()._receive_message_from_socket(ssocket)


class _SharedPortServer(_DepartureAwareServer):
    """The same server, for a producer started with `--allow-shared-port`.

    Sharing needs both sides. Windows refuses a `SO_REUSEADDR` bind over a socket
    that did not set it, so this joins only a producer that also opted in.
    """

    allow_reuse_address = True


class ImageStreamServer:
    """A server socket that sends image messages, as the C++ sender does.

    The real acquisition application listens and SLIAFlow connects, so the
    stand-in listens too. Swapping one for the other is stopping this process
    and starting that one on the same port.

    A `ClientWatch` runs for as long as the server does, so every producer built
    on this class reports its clients and warns about a starved one.

    Starting refuses, with `PortRefusedError`, a reserved port and a port another
    socket is already listening on, unless `allowSharedPort` was asked for and
    the holder asked for it too. Every producer built on this class inherits
    that refusal.
    """

    def __init__(self, port: int = DEFAULT_LIVE_VIEW_PORT, allowSharedPort: bool = False) -> None:
        self.port = port
        self.allowSharedPort = allowSharedPort
        self._server: pyigtl.OpenIGTLinkServer | None = None
        self._clientWatch: ClientWatch | None = None
        # The other producers last warned about, so a send-failure restart that
        # finds the same ones does not repeat the warning.
        self._warnedSharers: list[int] | None = None

    def __enter__(self) -> ImageStreamServer:
        self.start()
        return self

    def __exit__(self, exceptionType, exceptionValue, traceback) -> None:
        self.stop()

    def start(self) -> None:
        if self._server is None:
            if self.port in contract.RESERVED_PORTS:
                raise PortRefusedError(reservedPortMessage(self.port))
            serverClass = _SharedPortServer if self.allowSharedPort else _DepartureAwareServer
            try:
                self._server = serverClass(port=self.port, local_server=True)
            except OSError as error:
                if not _meansPortIsHeld(error):
                    raise
                raise PortRefusedError(
                    portInUseMessage(
                        self.port,
                        listeningProcessIds(self.port),
                        allowSharedPort=self.allowSharedPort,
                    )
                ) from error
            if self.allowSharedPort:
                self._warnAboutSharing()
            self._clientWatch = ClientWatch(self._server, self.port)
            self._clientWatch.start()

    def _warnAboutSharing(self) -> None:
        # A producer that joins is told whom it joined. One that was there first
        # is not told later, so its own warning says that a join would be silent.
        otherIds = [pid for pid in listeningProcessIds(self.port) if pid != os.getpid()]
        if otherIds != self._warnedSharers:
            print(sharedPortWarning(self.port, otherIds), file=sys.stderr, flush=True)
            self._warnedSharers = otherIds

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
            try:
                self.start()
            except PortRefusedError as refusal:
                raise PortRefusedError(
                    f"The server on 127.0.0.1:{self.port} was restarted after a failed send and "
                    f"could not bind again, so this producer has stopped serving. {refusal}"
                ) from refusal
            return False
        return True
