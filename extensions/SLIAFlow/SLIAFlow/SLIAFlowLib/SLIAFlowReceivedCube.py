"""Receive the HS cube IUMA's acquisition app sends, band by band (SLIA-036).

What the app sends on its HS Cube port was measured on 2026-09-27
(docs/hardware/acquisition_app_and_hardware.md section 4.1): header version 1,
no metadata, timestamp 0, and one IMAGE per band. Every IMAGE declares the
whole cube, (samples, lines, bands), and carries one band as the sub-volume
(samples, lines, 1) at offset (0, 0, band - 1). Nothing marks the end of a cube.

OpenIGTLinkIF assembles such sub-volumes into one volume that it never clears,
does not say which band arrived, and keeps only 3 messages per device, emptied
on the main thread. So SLIAFlow reads this port itself:

- `HsCubeReader` is a socket thread, the port's one client. It reads every
  message whole, checks its CRC, and hands it to a `CubeAssembler`. It never
  touches MRML; the main thread polls it.
- `CubeAssembler` puts each band at its offset in a buffer allocated at the
  cube's first band, and hands over a cube only once it holds every band.
  The buffer is allocated by a function the caller gives, so that in Slicer it
  is the `vtkImageData` the volume node will use, and a cube is never copied.

Nothing here imports `slicer`, so parsing and assembly are tested on their own.
"""

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

# vtkMRMLIGTLConnectorNode's states, as SLIAFlowConnections mirrors them, so
# that the HS Cube row reads the reader as it reads a connector.
STATE_OFF = 0
STATE_WAITING = 1
STATE_CONNECTED = 2

HEADER_SIZE = 58
_HEADER = struct.Struct("> H 12s 20s I I Q Q")
_EXTENDED_HEADER = struct.Struct("> H H I I")
_METADATA_ENTRY = struct.Struct("> H H I")
# Version, components, scalar type, endianness, coordinate system, size[3], the
# matrix columns t, s, n and the centre c, then the sub-volume offset[3] and size[3].
_IMAGE_HEADER = struct.Struct("> H B B B B 3H 12f 3H 3H")
_SCALAR_TYPES = {5: np.dtype("uint16"), 10: np.dtype("float32")}
# OpenIGTLink's byte orders of an IMAGE's pixels; any other code is undefined.
_BYTE_ORDERS = {1: ">", 2: "<"}
# The header versions OpenIGTLink defines, and the one IMAGE header version.
_HEADER_VERSIONS = (1, 2)
_IMAGE_HEADER_VERSION = 1

# The stand-in's metadata (tools/simulators contract.py), sent at header
# version 2 only. The app sends none.
BAND_NUMBER_KEY = "SLIAFlow.BandNumber"
WAVELENGTH_KEY = "SLIAFlow.WavelengthNm"
DATA_ORIGIN_KEY = "SLIAFlow.DataOrigin"
SIMULATION_DETAIL_KEY = "SLIAFlow.SimulationDetail"
SIMULATED_ORIGIN = "simulated"

# Silence this long ends a cube: longer than the app's pause of up to 5 s at
# the VIS/NIR crossover (acquisition_app_and_hardware.md 2.2).
CUBE_IDLE_SEC = 10.0
RETRY_SEC = 1.0
CONNECT_TIMEOUT_SEC = 2.0
READ_POLL_SEC = 0.25
# No IMAGE of the app comes near this: a raw band is 17.7 MB. A header that
# declares more is not a message this reader can trust, and it cannot skip it.
MAX_BODY_BYTES = 1 << 30

# ----------------------------------------------------------------------
# CRC-64/ECMA-182, as OpenIGTLink computes it: polynomial 0x42F0E1EBA9EA3693,
# initial value 0, not reflected, no final XOR. Slicer's Python has no CRC-64
# and the pinned OpenIGTLink.dll does not export igtl_crc64, so it is computed
# with numpy: the data is split into rows that are all run eight bytes at a
# time side by side, and the rows' CRCs are then joined. Joining works because
# with initial value 0 and no final XOR the CRC is linear: the CRC of A then B
# is the CRC of A followed by len(B) zero bytes, XOR the CRC of B.
# ----------------------------------------------------------------------

_POLYNOMIAL = 0x42F0E1EBA9EA3693
_MASK = (1 << 64) - 1
# Below this many bytes the plain byte loop is fast enough.
_VECTOR_MIN_BYTES = 1 << 16
_VECTOR_ROWS = 8192


def _byteTable() -> list:
    table = []
    for byte in range(256):
        crc = byte << 56
        for _bit in range(8):
            crc = ((crc << 1) ^ _POLYNOMIAL) & _MASK if crc & (1 << 63) else (crc << 1) & _MASK
        table.append(crc)
    return table


_TABLE = _byteTable()
# _SLICES[k][b]: the CRC of byte b followed by k zero bytes, for eight bytes a step.
_SLICES = [np.array(_TABLE, dtype=np.uint64)]
for _k in range(1, 8):
    _previous = _SLICES[-1]
    _SLICES.append((_previous << np.uint64(8))
                   ^ _SLICES[0][(_previous >> np.uint64(56)).astype(np.intp)])
_ZERO_SHIFT_TABLES: dict = {}


def _crcBytes(data, crc: int = 0) -> int:
    for byte in bytes(data):
        crc = ((crc << 8) & _MASK) ^ _TABLE[((crc >> 56) ^ byte) & 0xFF]
    return crc


def _shiftTables(zeroBytes: int) -> list:
    """Per byte of a CRC, what it becomes after `zeroBytes` zero bytes: 8 tables of 256."""
    tables = _ZERO_SHIFT_TABLES.get(zeroBytes)
    if tables is not None:
        return tables
    # The map is linear: build it on the 64 single bits, square it to the length.
    oneZero = [_crcBytes(b"\0", 1 << bit) for bit in range(64)]

    def apply(matrix, value):
        result, bit = 0, 0
        while value:
            if value & 1:
                result ^= matrix[bit]
            value >>= 1
            bit += 1
        return result

    matrix = [1 << bit for bit in range(64)]
    power, remaining = oneZero, zeroBytes
    while remaining:
        if remaining & 1:
            matrix = [apply(power, column) for column in matrix]
        remaining >>= 1
        if remaining:
            power = [apply(power, column) for column in power]
    tables = [[apply(matrix, value << (8 * position)) for value in range(256)]
              for position in range(8)]
    _ZERO_SHIFT_TABLES[zeroBytes] = tables
    return tables


def crc64(data) -> int:
    """The OpenIGTLink CRC-64 of a bytes-like object."""
    buffer = np.frombuffer(memoryview(data).cast("B"), dtype=np.uint8)
    if buffer.size < _VECTOR_MIN_BYTES:
        return _crcBytes(buffer.tobytes())
    rowBytes = (buffer.size // _VECTOR_ROWS) // 8 * 8
    rows = buffer[:rowBytes * _VECTOR_ROWS].reshape(_VECTOR_ROWS, rowBytes)
    words = rows.view(">u8")
    crcs = np.zeros(_VECTOR_ROWS, dtype=np.uint64)
    byteMask = np.uint64(0xFF)
    shifts = [np.uint64(56 - 8 * position) for position in range(8)]
    for column in range(rowBytes // 8):
        mixed = crcs ^ words[:, column].astype(np.uint64)
        crcs = _SLICES[7][(mixed >> shifts[0]).astype(np.intp)]
        for position in range(1, 8):
            crcs ^= _SLICES[7 - position][((mixed >> shifts[position]) & byteMask).astype(np.intp)]
    tables = _shiftTables(rowBytes)
    crc = 0
    for rowCrc in crcs.tolist():
        shifted = 0
        for position in range(8):
            shifted ^= tables[position][(crc >> (8 * position)) & 0xFF]
        crc = shifted ^ rowCrc
    return _crcBytes(buffer[rowBytes * _VECTOR_ROWS:].tobytes(), crc)


# ----------------------------------------------------------------------
# Messages
# ----------------------------------------------------------------------


class RefusedMessage(ValueError):
    """A message the HS Cube port must not put into a cube. The text says what it was."""


@dataclass(frozen=True)
class MessageHeader:
    headerVersion: int
    messageType: str
    deviceName: str
    timestamp: float
    bodySize: int
    crc: int


def parseHeader(data) -> MessageHeader:
    version, messageType, deviceName, seconds, fraction, bodySize, crc = _HEADER.unpack(data)
    return MessageHeader(
        version,
        messageType.rstrip(b"\0").decode("ascii", "replace"),
        deviceName.rstrip(b"\0").decode("utf-8", "replace"),
        seconds + fraction / 2**32,
        bodySize,
        crc,
    )


@dataclass(frozen=True)
class BandMessage:
    """One band of a cube, as it arrived."""

    deviceName: str
    headerVersion: int
    metadata: dict
    # The pixel type as received; `pixels` may be in either byte order.
    dtype: np.dtype
    samples: int
    lines: int
    bands: int
    # The sub-volume's offset along the band axis: band `offset + 1`.
    offset: int
    pixels: np.ndarray = field(repr=False)

    @property
    def bandNumber(self) -> int:
        return self.offset + 1

    @property
    def simulated(self) -> bool:
        return self.metadata.get(DATA_ORIGIN_KEY) == SIMULATED_ORIGIN

    @property
    def wavelengthNm(self) -> float | None:
        try:
            return float(self.metadata[WAVELENGTH_KEY])
        except (KeyError, ValueError):
            return None


def _decodeText(value: bytes, encoding: int) -> str:
    if encoding == 3:  # IANA US-ASCII
        return value.decode("ascii", "replace")
    if encoding == 106:  # IANA UTF-8
        return value.decode("utf-8", "replace")
    return value.decode("latin-1")


def _splitVersion2(body: memoryview):
    """The content of a header version 2 body, and its metadata."""
    extendedSize, metadataHeaderSize, metadataSize, _messageId = _EXTENDED_HEADER.unpack_from(body)
    trailer = metadataHeaderSize + metadataSize
    metadata = {}
    if trailer:
        region = body[len(body) - trailer:]
        count = struct.unpack_from("> H", region)[0]
        position = metadataHeaderSize
        for index in range(count):
            keySize, encoding, valueSize = _METADATA_ENTRY.unpack_from(region, 2 + index * 8)
            key = bytes(region[position:position + keySize]).decode("utf-8", "replace")
            position += keySize
            metadata[key] = _decodeText(bytes(region[position:position + valueSize]), encoding)
            position += valueSize
    return body[extendedSize:len(body) - trailer], metadata


def parseBandMessage(header: MessageHeader, body) -> BandMessage:
    """Read one band, or raise RefusedMessage saying what the message was instead."""
    body = memoryview(body).cast("B")
    if crc64(body) != header.crc:
        raise RefusedMessage(_("a {type} message whose CRC does not match its content").format(
            type=header.messageType or "?"))
    if header.messageType != "IMAGE":
        raise RefusedMessage(_("a {type} message, not an IMAGE").format(
            type=header.messageType or "?"))
    if header.headerVersion not in _HEADER_VERSIONS:
        raise RefusedMessage(_("an IMAGE with header version {version}, not 1 or 2").format(
            version=header.headerVersion))
    try:
        content, metadata = _splitVersion2(body) if header.headerVersion >= 2 else (body, {})
        fields = _IMAGE_HEADER.unpack_from(content)
    except (struct.error, ValueError) as error:
        raise RefusedMessage(_("an IMAGE whose header could not be read ({error})").format(
            error=error)) from error
    imageVersion, components, scalarCode, endianness = fields[0:4]
    samples, lines, bands = fields[5:8]
    offset = tuple(fields[20:23])
    subvolume = tuple(fields[23:26])
    if imageVersion != _IMAGE_HEADER_VERSION:
        raise RefusedMessage(_("an IMAGE with image header version {version}, not 1").format(
            version=imageVersion))
    if components != 1:
        raise RefusedMessage(_("an IMAGE with {count} components, not one band").format(
            count=components))
    if scalarCode not in _SCALAR_TYPES:
        raise RefusedMessage(_("an IMAGE of scalar type {code}, not uint16 or float32").format(
            code=scalarCode))
    if endianness not in _BYTE_ORDERS:
        raise RefusedMessage(_(
            "an IMAGE with byte order code {code}, not 1 (big endian) or 2 (little endian)"
        ).format(code=endianness))
    if 0 in (samples, lines, bands):
        raise RefusedMessage(_("an IMAGE of {samples} x {lines} x {bands}, with no pixels").format(
            samples=samples, lines=lines, bands=bands))
    if (subvolume != (samples, lines, 1) or offset[:2] != (0, 0) or not 0 <= offset[2] < bands):
        raise RefusedMessage(_(
            "an IMAGE whose sub-volume {size} at {offset} is not one whole band of its "
            "{samples} x {lines} x {bands} cube"
        ).format(size=" x ".join(map(str, subvolume)), offset=offset, samples=samples,
                 lines=lines, bands=bands))
    dtype = _SCALAR_TYPES[scalarCode].newbyteorder(_BYTE_ORDERS[endianness])
    pixelBytes = content[_IMAGE_HEADER.size:]
    expected = samples * lines * dtype.itemsize
    if len(pixelBytes) != expected:
        raise RefusedMessage(_("an IMAGE with {actual} bytes of pixels for a band of {expected}")
                             .format(actual=len(pixelBytes), expected=expected))
    band = BandMessage(header.deviceName, header.headerVersion, metadata, dtype, samples, lines,
                       bands, offset[2],
                       np.frombuffer(pixelBytes, dtype=dtype).reshape(lines, samples))
    named = metadata.get(BAND_NUMBER_KEY)
    if named is not None and named.strip() != str(band.bandNumber):
        raise RefusedMessage(_(
            "an IMAGE that says it is band {named} but is band {band} by its offset"
        ).format(named=named, band=band.bandNumber))
    return band


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------


def allocateNumpyCube(bands: int, lines: int, samples: int, dtype):
    """The default buffer: a numpy array that is its own owner."""
    values = np.empty((bands, lines, samples), dtype=np.dtype(dtype).newbyteorder("="))
    return values, values


def formatBandRanges(bands) -> str:
    """Band numbers with runs as ranges: `5, 17, 80-84`."""
    runs = []
    for band in sorted(bands):
        if runs and band == runs[-1][1] + 1:
            runs[-1][1] = band
        else:
            runs.append([band, band])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in runs)


@dataclass
class AssembledCube:
    """A complete cube. `owner` holds the memory `values` views."""

    owner: object
    values: np.ndarray = field(repr=False)
    deviceName: str
    simulated: bool
    simulationDetail: str | None
    host: str = ""
    port: int = 0
    receivedAt: datetime | None = None

    @property
    def bands(self) -> int:
        return self.values.shape[0]

    @property
    def lines(self) -> int:
        return self.values.shape[1]

    @property
    def samples(self) -> int:
        return self.values.shape[2]

    @property
    def dtype(self) -> np.dtype:
        return self.values.dtype


@dataclass(frozen=True)
class CubeProgress:
    """What the HS Cube row says about the cube."""

    bandsReceived: int = 0
    # The band count the messages declare, once one arrived.
    bandsDeclared: int | None = None
    complete: bool = False
    # Why the current cube was thrown away, while no band of a new one arrived.
    incompleteDetail: str | None = None
    # Why the cube before the one being received was thrown away.
    previousIncompleteDetail: str | None = None


class CubeAssembler:
    """Bands into cubes, by sub-volume offset. Not thread-safe: the reader locks it."""

    MISSING_BANDS_DETAIL = _("Missing bands: {bands}.")
    LATE_BANDS = _("{bands} (connected after the capture started)")
    CHANGED_CUBE_DETAIL = _("The sender changed to a {cube} cube before this one was complete.")

    def __init__(self, allocate=allocateNumpyCube, idleSec: float = CUBE_IDLE_SEC) -> None:
        self._allocate = allocate
        self.idleSec = idleSec
        self._reset()
        self._firstOffsetSinceConnect = None
        self._connected = False
        self._progress = CubeProgress()

    def _reset(self) -> None:
        self._owner = None
        self._values = None
        self._form = None
        self._held: set = set()
        self._lastBandTime: float | None = None
        self._simulated = False
        self._detail = None
        self._deviceName = ""
        self._lateBands: set = set()

    @property
    def assembling(self) -> bool:
        return self._values is not None

    def progress(self) -> CubeProgress:
        return self._progress

    def connectionOpened(self) -> None:
        """A new connection may be another sender: nothing carries over."""
        self._reset()
        self._progress = CubeProgress()
        self._connected = True
        self._firstOffsetSinceConnect = None

    def connectionLost(self) -> None:
        if self.assembling:
            self._throwAway()
        self._connected = False

    def tick(self, now: float) -> None:
        """End a cube that has had no band for `idleSec`."""
        if self.assembling and now - self._lastBandTime >= self.idleSec:
            self._throwAway()

    def _missingDetail(self) -> str:
        bands = self._form[2]
        missing = {band for band in range(1, bands + 1) if band - 1 not in self._held}
        late = sorted(missing & self._lateBands)
        others = sorted(missing - self._lateBands)
        parts = []
        if late:
            parts.append(self.LATE_BANDS.format(bands=formatBandRanges(late)))
        if others:
            parts.append(formatBandRanges(others))
        return self.MISSING_BANDS_DETAIL.format(bands=", ".join(parts))

    def _throwAway(self, extra: str | None = None) -> str:
        detail = self._missingDetail()
        if extra:
            detail = f"{detail} {extra}"
        self._progress = CubeProgress(len(self._held), self._form[2], False, detail)
        self._reset()
        return detail

    def _startsNextCube(self, band: BandMessage) -> bool:
        """A band this connection missed, coming after the cube's last band and
        before any other missed band, is the next cube starting: filling the
        gap with it would put two captures into one cube. A cube sent in order
        always ends this way; one sent out of order that cannot be told from
        it is thrown away, never mixed."""
        return (band.bandNumber in self._lateBands
                and band.bands - 1 in self._held
                and not any(number - 1 in self._held for number in self._lateBands))

    def accept(self, band: BandMessage, now: float) -> AssembledCube | None:
        """Put a band into its cube; return the cube once it holds every band."""
        form = (band.samples, band.lines, band.bands, band.dtype.newbyteorder("="))
        previousDetail = None
        if self.assembling and (now - self._lastBandTime >= self.idleSec):
            previousDetail = self._throwAway()
        if self.assembling and form != self._form:
            previousDetail = self._throwAway(self.CHANGED_CUBE_DETAIL.format(
                cube=f"{band.samples} x {band.lines} x {band.bands} {form[3].name}"))
        elif self.assembling and (band.offset in self._held or self._startsNextCube(band)):
            previousDetail = self._throwAway()
        if not self.assembling:
            if previousDetail is None and self._progress.incompleteDetail and not self._progress.complete:
                previousDetail = self._progress.incompleteDetail
            self._owner, self._values = self._allocate(band.bands, band.lines, band.samples, form[3])
            self._form = form
            self._simulated = band.simulated
            self._detail = band.metadata.get(SIMULATION_DETAIL_KEY)
            self._deviceName = band.deviceName
            if self._connected and self._firstOffsetSinceConnect is None:
                self._firstOffsetSinceConnect = band.offset
                # Bands before the first one this connection saw went out
                # before it was there to read them.
                self._lateBands = set(range(1, band.offset + 1))
        self._values[band.offset] = band.pixels
        self._held.add(band.offset)
        self._lastBandTime = now
        if len(self._held) < band.bands:
            # The note stays until this cube ends, not only for its first band.
            self._progress = CubeProgress(
                len(self._held), band.bands,
                previousIncompleteDetail=previousDetail or self._progress.previousIncompleteDetail)
            return None
        cube = AssembledCube(self._owner, self._values, self._deviceName, self._simulated,
                             self._detail)
        self._progress = CubeProgress(band.bands, band.bands, True)
        self._reset()
        return cube


# ----------------------------------------------------------------------
# The socket thread
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReceivedMessage:
    """One message as the HS Cube row describes it."""

    time: float
    deviceName: str
    messageType: str
    # (samples, lines, 1) of a band, or None.
    size: tuple | None = None
    scalarType: str | None = None
    bandNumber: int | None = None
    wavelengthNm: float | None = None
    simulated: bool = False
    # What was refused, or None for a band that was accepted.
    refusal: str | None = None


@dataclass
class ReaderUpdate:
    """Everything since the last poll."""

    state: int
    stateSince: float
    messages: list
    progress: CubeProgress
    # The last cube completed since the last poll, or None.
    completed: AssembledCube | None


class _ConnectionClosed(Exception):
    pass


class HsCubeReader:
    """The HS Cube port's one client: reads, checks and assembles on its own thread."""

    def __init__(self, host: str, port: int, *, allocate=allocateNumpyCube,
                 idleSec: float = CUBE_IDLE_SEC, clock=time.monotonic) -> None:
        self.host = host
        self.port = int(port)
        self._clock = clock
        self._assembler = CubeAssembler(allocate, idleSec)
        self._lock = threading.Lock()
        self._stopRequested = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._state = STATE_OFF
        self._stateSince = clock()
        self._messages: list = []
        self._completed: AssembledCube | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stopRequested.clear()
        self._setState(STATE_WAITING)
        self._thread = threading.Thread(target=self._run, name=f"SLIAFlow HS Cube {self.port}",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeoutSec: float = 5.0) -> None:
        """Close the connection, wait for the thread, and drop every buffer."""
        self._stopRequested.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeoutSec)
            self._thread = None
        with self._lock:
            self._assembler.connectionLost()
            self._completed = None
            self._messages = []
        self._setState(STATE_OFF)

    def poll(self) -> ReaderUpdate:
        """What happened since the last poll. Called on the main thread."""
        with self._lock:
            self._assembler.tick(self._clock())
            update = ReaderUpdate(self._state, self._stateSince, self._messages,
                                  self._assembler.progress(), self._completed)
            self._messages = []
            self._completed = None
        return update

    def _setState(self, state: int) -> None:
        with self._lock:
            if state != self._state:
                self._state = state
                self._stateSince = self._clock()

    def _run(self) -> None:
        while not self._stopRequested.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT_SEC)
            except OSError:
                self._setState(STATE_WAITING)
                self._stopRequested.wait(RETRY_SEC)
                continue
            self._socket = sock
            with self._lock:
                self._assembler.connectionOpened()
            self._setState(STATE_CONNECTED)
            try:
                sock.settimeout(READ_POLL_SEC)
                self._readMessages(sock)
            except (OSError, _ConnectionClosed):
                pass
            finally:
                self._socket = None
                try:
                    sock.close()
                except OSError:
                    pass
                with self._lock:
                    self._assembler.connectionLost()
                self._setState(STATE_WAITING)
            if not self._stopRequested.is_set():
                self._stopRequested.wait(RETRY_SEC)

    def _receiveInto(self, sock, view: memoryview) -> None:
        received = 0
        while received < len(view):
            if self._stopRequested.is_set():
                raise _ConnectionClosed()
            try:
                count = sock.recv_into(view[received:])
            except socket.timeout:
                with self._lock:
                    self._assembler.tick(self._clock())
                continue
            if count == 0:
                raise _ConnectionClosed()
            received += count

    def _readMessages(self, sock) -> None:
        headerBytes = bytearray(HEADER_SIZE)
        body = bytearray()
        while not self._stopRequested.is_set():
            self._receiveInto(sock, memoryview(headerBytes))
            header = parseHeader(headerBytes)
            if header.bodySize > MAX_BODY_BYTES:
                self._refuse(header, _("a {type} message declaring {size} bytes, more than any "
                                       "band; the connection is closed").format(
                                           type=header.messageType or "?", size=header.bodySize))
                raise _ConnectionClosed()
            if len(body) != header.bodySize:
                body = bytearray(header.bodySize)
            self._receiveInto(sock, memoryview(body))
            now = self._clock()
            try:
                band = parseBandMessage(header, body)
            except RefusedMessage as refusal:
                self._refuse(header, str(refusal))
                continue
            with self._lock:
                completed = self._assembler.accept(band, now)
                self._messages.append(ReceivedMessage(
                    now, band.deviceName, "IMAGE", (band.samples, band.lines, 1),
                    band.dtype.name, band.bandNumber, band.wavelengthNm, band.simulated))
                if completed is not None:
                    completed.host, completed.port = self.host, self.port
                    completed.receivedAt = datetime.now()
                    # An unclaimed earlier cube is dropped, and freed with it.
                    self._completed = completed

    def _refuse(self, header: MessageHeader, reason: str) -> None:
        with self._lock:
            self._messages.append(ReceivedMessage(self._clock(), header.deviceName,
                                                  header.messageType, refusal=reason))
