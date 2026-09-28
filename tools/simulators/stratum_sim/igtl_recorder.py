"""Record what an OpenIGTLink server sends, message by message (SLIA-030).

Written to measure IUMA's acquisition app before SLIAFlow's receiver is built on
it. It connects as a client to each given port, sends nothing, and logs every
message whole with its own header parser: `pyigtl.OpenIGTLinkClient` keeps only
the latest message per device name and would hide lost or doubled bands.

Per message it logs the header, the version-2 metadata, the IMAGE header and
the pixel minimum, maximum and mean, never the pixels. With a compare cube it
also names the cube band a single-component image equals, as stored or flipped,
which gives band order and orientation without any band metadata. Reading and
describing run on separate threads, so arrival times stay the sender's while a
band is being matched. Run it from tools/simulators:

    ..\\..\\.venv\\Scripts\\python.exe -m stratum_sim.igtl_recorder --compare-cube <header>

Nothing here imports `slicer`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import struct
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import numpy
from pyigtl.messages import CRC64

from . import igtl_transport

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "workspace" / "igtl-recordings"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (18944, 18945, 18946)

HEADER_SIZE = 58
_HEADER = struct.Struct("> H 12s 20s I I Q Q")
_EXTENDED_HEADER = struct.Struct("> H H I I")
_METADATA_ENTRY = struct.Struct("> H H I")
# OpenIGTLink IMAGE header: version, components, scalar type, endianness,
# coordinate system, size[3], matrix columns t, s, n and the centre c, then the
# sub-volume offset[3] and size[3].
_IMAGE_HEADER = struct.Struct("> H B B B B 3H 12f 3H 3H")

SCALAR_TYPES = {
    2: numpy.int8, 3: numpy.uint8, 4: numpy.int16, 5: numpy.uint16,
    6: numpy.int32, 7: numpy.uint32, 10: numpy.float32, 11: numpy.float64,
}
_ENDIANNESS = {1: "big", 2: "little", 3: "native"}
_COORDINATE_SYSTEMS = {1: "RAS", 2: "LPS"}
_IANA_ASCII = 3
_IANA_UTF8 = 106

# ENVI data types the compare cube may have: IUMA's raw and calibrated cubes.
_ENVI_TYPES = {"12": numpy.dtype("<u2"), "4": numpy.dtype("<f4")}
_ENVI_DATA_SUFFIXES = (".raw", ".dat", "")
_HEADER_LINE = re.compile(r"^\s*([^=]+?)\s*=\s*([^{].*?)\s*$")

RETRY_SEC = 1.0
CONNECT_TIMEOUT_SEC = 2.0
READ_POLL_SEC = 0.5
RECEIVE_BUFFER_BYTES = 8 * 1024 * 1024
# Frames are reported every this many messages; bands are reported one by one.
FRAME_REPORT_EVERY = 100
# Messages read but not yet described. Past this the readers wait, which slows
# the sender, and the summary says so.
MAX_BACKLOG_BYTES = 3 * 1024**3
# Compared images further apart than this belong to separate captures.
DEFAULT_CAPTURE_GAP_SEC = 5.0
# How much of a message that is neither IMAGE, STRING nor STATUS is logged, in hex.
CONTENT_HEAD_BYTES = 64
_STATUS_HEADER = struct.Struct("> H q 20s")
_SUMMARY_TEXT_CHARS = 80


def parseHeader(data: bytes) -> dict:
    """The 58-byte OpenIGTLink header as a dictionary."""
    version, messageType, deviceName, seconds, fraction, bodySize, crc = _HEADER.unpack(data)
    return {
        "headerVersion": version,
        "messageType": messageType.rstrip(b"\0").decode("ascii", "replace"),
        "deviceName": deviceName.rstrip(b"\0").decode("utf-8", "replace"),
        "timestamp": seconds + fraction / 2**32,
        "bodySize": bodySize,
        "crc": crc,
    }


def _decodeText(value: bytes, encoding: int) -> str:
    if encoding == _IANA_ASCII:
        return value.decode("ascii", "replace")
    if encoding == _IANA_UTF8:
        return value.decode("utf-8", "replace")
    return value.decode("latin-1")


def _splitVersion2Body(body: bytes, record: dict) -> bytes:
    """Record the extended header and metadata; return the message content."""
    extendedSize, metadataHeaderSize, metadataSize, messageId = _EXTENDED_HEADER.unpack_from(body)
    metadata = {}
    trailer = metadataHeaderSize + metadataSize
    if trailer:
        region = body[len(body) - trailer:]
        count = struct.unpack_from("> H", region)[0]
        offset = metadataHeaderSize
        for index in range(count):
            keySize, encoding, valueSize = _METADATA_ENTRY.unpack_from(region, 2 + index * 8)
            key = region[offset:offset + keySize].decode("utf-8", "replace")
            offset += keySize
            metadata[key] = _decodeText(region[offset:offset + valueSize], encoding)
            offset += valueSize
    record["extendedHeader"] = {
        "size": extendedSize, "metadataHeaderSize": metadataHeaderSize,
        "metadataSize": metadataSize, "messageId": messageId, "metadataCount": len(metadata),
    }
    record["metadata"] = metadata
    return body[extendedSize:len(body) - trailer]


def _describeImage(content: bytes, record: dict):
    fields = _IMAGE_HEADER.unpack_from(content)
    version, components, scalarCode, endianCode, coordinateCode = fields[:5]
    size = numpy.array(fields[5:8])
    axes = numpy.array(fields[8:17], dtype=numpy.float64).reshape(3, 3).T  # columns t, s, n
    centre = numpy.array(fields[17:20], dtype=numpy.float64)
    spacing = numpy.linalg.norm(axes, axis=0)
    direction = axes / numpy.where(spacing == 0, 1.0, spacing)
    origin = centre - axes.dot((size - 1) / 2.0)
    image = {
        "version": version,
        "components": components,
        "scalarType": numpy.dtype(SCALAR_TYPES[scalarCode]).name if scalarCode in SCALAR_TYPES
        else f"unknown ({scalarCode})",
        "endianness": _ENDIANNESS.get(endianCode, f"unknown ({endianCode})"),
        "coordinateSystem": _COORDINATE_SYSTEMS.get(coordinateCode, f"unknown ({coordinateCode})"),
        "size": [int(value) for value in size],
        "spacing": [round(float(value), 6) for value in spacing],
        "origin": [round(float(value), 4) for value in origin],
        "direction": [[round(float(value), 6) for value in row] for row in direction],
        "subvolumeOffset": list(fields[20:23]),
        "subvolumeSize": list(fields[23:26]),
    }
    record["image"] = image
    if scalarCode not in SCALAR_TYPES:
        return None
    dtype = numpy.dtype(SCALAR_TYPES[scalarCode]).newbyteorder(">" if endianCode == 1 else "<")
    pixelBytes = content[_IMAGE_HEADER.size:]
    subvolume = numpy.array(fields[23:26])
    expected = int(numpy.prod(subvolume)) * components * dtype.itemsize
    image["pixelBytes"] = len(pixelBytes)
    if len(pixelBytes) != expected:
        image["pixelBytesExpected"] = expected
        return None
    values = numpy.frombuffer(pixelBytes, dtype=dtype)
    finite = values
    if dtype.kind == "f":
        finite = values[numpy.isfinite(values)]
        image["nonFiniteCount"] = int(values.size - finite.size)
    image["minimum"] = image["maximum"] = image["mean"] = None
    if finite.size:
        cast = int if dtype.kind in "iu" else float
        image["minimum"] = cast(finite.min())
        image["maximum"] = cast(finite.max())
        image["mean"] = float(finite.mean(dtype=numpy.float64))
    if components == 1 and subvolume[2] == 1:
        return values.reshape(int(subvolume[1]), int(subvolume[0]))
    return None


def describeMessage(header: dict, body: bytes):
    """Describe one message; also return a single-component 2D image's pixels, or None."""
    record = {key: header[key] for key in
              ("headerVersion", "messageType", "deviceName", "timestamp", "bodySize")}
    record["crcMatches"] = CRC64(body) == header["crc"]
    record["metadata"] = {}
    content = body
    try:
        if header["headerVersion"] >= 2:
            content = _splitVersion2Body(body, record)
        if header["messageType"] == "IMAGE":
            return record, _describeImage(content, record)
        if header["messageType"] == "STRING":
            encoding, length = struct.unpack_from("> H H", content)
            record["text"] = _decodeText(content[4:4 + length], encoding)
        elif header["messageType"] == "STATUS":
            code, subcode, errorName = _STATUS_HEADER.unpack_from(content)
            record["status"] = {"code": code, "subcode": subcode,
                                "errorName": errorName.rstrip(b"\0").decode("latin-1")}
            text = content[_STATUS_HEADER.size:].split(b"\0", 1)[0]
            record["text"] = text.decode("utf-8", "replace")
        else:
            record["contentHead"] = bytes(content[:CONTENT_HEAD_BYTES]).hex()
    except (struct.error, ValueError, UnicodeError) as error:
        record["parseError"] = str(error)
    return record, None


def _finiteOnly(value):
    if isinstance(value, float) and not numpy.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finiteOnly(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finiteOnly(item) for item in value]
    return value


def jsonLine(record: dict) -> str:
    """The record as strict JSON: a NaN or infinite number is written as null."""
    return json.dumps(_finiteOnly(record), allow_nan=False)


def _parseEnviHeader(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        match = _HEADER_LINE.match(line)
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    return values


# How a received image relates to the stored band: its name, and the transform
# that turns the received image back into the stored band.
_ORIENTATIONS = (
    ("as stored", lambda image: image),
    ("flipped top to bottom", lambda image: image[::-1, :]),
    ("flipped left to right", lambda image: image[:, ::-1]),
    ("rotated 180 degrees", lambda image: image[::-1, ::-1]),
)
_TRANSPOSED_ORIENTATIONS = (
    ("transposed", lambda image: image.T),
    ("rotated 90 degrees clockwise", lambda image: numpy.rot90(image, 1)),
    ("rotated 90 degrees counter-clockwise", lambda image: numpy.rot90(image, -1)),
    ("transposed across the other diagonal", lambda image: image[::-1, ::-1].T),
)


def _digest(image: numpy.ndarray) -> bytes:
    return hashlib.blake2b(numpy.ascontiguousarray(image).tobytes(), digest_size=16).digest()


class CubeComparison:
    """The bands of an ENVI BSQ cube, to name the band a received image equals."""

    def __init__(self, headerPath) -> None:
        headerPath = Path(headerPath)
        fields = _parseEnviHeader(headerPath.read_text(encoding="latin-1"))
        try:
            self.samples = int(fields["samples"])
            self.lines = int(fields["lines"])
            self.bands = int(fields["bands"])
            dataType = fields["data type"]
        except (KeyError, ValueError) as error:
            raise ValueError(f"{headerPath.name} lacks samples, lines, bands or data type") from error
        if dataType not in _ENVI_TYPES:
            raise ValueError(f"{headerPath.name}: data type {dataType} is not 12 (uint16) or 4 (float32)")
        if fields.get("interleave", "bsq").lower() != "bsq" or fields.get("byte order", "0") != "0":
            raise ValueError(f"{headerPath.name} is not a little-endian BSQ cube")
        self.dtype = _ENVI_TYPES[dataType]
        offset = int(fields.get("header offset", "0"))
        dataPath = next((headerPath.with_suffix(suffix) for suffix in _ENVI_DATA_SUFFIXES
                         if headerPath.with_suffix(suffix).is_file()
                         and headerPath.with_suffix(suffix) != headerPath), None)
        if dataPath is None:
            raise ValueError(f"No data file next to {headerPath.name}")
        bandBytes = self.samples * self.lines * self.dtype.itemsize
        if dataPath.stat().st_size < offset + bandBytes * self.bands:
            raise ValueError(f"{dataPath.name} is shorter than its header says")
        self.name = headerPath.stem
        self.dataPath = dataPath
        self._bandsByDigest: dict[bytes, list[int]] = {}
        with open(dataPath, "rb") as stream:
            stream.seek(offset)
            for number in range(1, self.bands + 1):
                band = numpy.fromfile(stream, dtype=self.dtype, count=self.samples * self.lines)
                self._bandsByDigest.setdefault(_digest(band), []).append(number)

    def match(self, pixels: numpy.ndarray) -> dict | None:
        """The band `pixels` equals and how it is oriented, or None."""
        pixels = numpy.asarray(pixels)
        if pixels.ndim != 2 or pixels.dtype.newbyteorder("=") != self.dtype.newbyteorder("="):
            return None
        pixels = pixels.astype(self.dtype, copy=False)
        if pixels.shape == (self.lines, self.samples):
            candidates = _ORIENTATIONS
        elif pixels.shape == (self.samples, self.lines):
            candidates = _TRANSPOSED_ORIENTATIONS
        else:
            return None
        for name, toStored in candidates:
            bands = self._bandsByDigest.get(_digest(toStored(pixels)))
            if bands:
                result = {"band": bands[0], "orientation": name}
                if len(bands) > 1:
                    result["sameAs"] = bands[1:]
                return result
        return None


def _quoted(text: str) -> str:
    if len(text) > _SUMMARY_TEXT_CHARS:
        text = text[:_SUMMARY_TEXT_CHARS] + "..."
    return json.dumps(text, ensure_ascii=False)


def _messageLabel(record: dict) -> str:
    label = f"{record['messageType']} '{record['deviceName']}'"
    return f"{label} {_quoted(record['text'])}" if "text" in record else label


def formatSequence(numbers) -> str:
    """Numbers in the given order, with runs that rise by one written a-b."""
    numbers = list(numbers)
    if not numbers:
        return "none"
    parts = []
    start = previous = numbers[0]
    for number in numbers[1:] + [None]:
        if number is not None and number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        if number is not None:
            start = previous = number
    return ", ".join(parts)


class Recorder:
    """One client per port, each reading every message; one thread describes them.

    Readers only read and time-stamp, so arrival times, rates and gaps are the
    sender's even when describing a message (CRC, statistics, band matching)
    takes longer than the next one takes to arrive.
    """

    def __init__(self, host: str, ports, outDir, *, comparison: CubeComparison | None = None,
                 report=print, captureGapSec: float = DEFAULT_CAPTURE_GAP_SEC) -> None:
        self.host = host
        self.ports = list(ports)
        self.outDir = Path(outDir)
        self.comparison = comparison
        self.captureGapSec = captureGapSec
        self._report = report
        self.records: list[dict] = []
        self.connections: dict[int, list[str]] = {port: [] for port in self.ports}
        self.heldBackSec: dict[int, float] = {port: 0.0 for port in self.ports}
        self._messageCounts: dict[int, int] = {port: 0 for port in self.ports}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._readers: list[threading.Thread] = []
        self._describer = None
        self._sockets: dict[int, socket.socket] = {}
        self._backlog: deque = deque()
        self._backlogBytes = 0
        self._readersDone = False
        self._backlogChanged = threading.Condition()
        self._log = None
        self._started = None
        self._summary = None

    def start(self) -> None:
        self.outDir.mkdir(parents=True, exist_ok=True)
        self._log = open(self.outDir / "messages.jsonl", "w", encoding="utf-8")
        self._started = datetime.now()
        self._describer = threading.Thread(target=self._describeAll, daemon=True,
                                           name="igtl-recorder-describer")
        self._describer.start()
        for port in self.ports:
            thread = threading.Thread(target=self._run, args=(port,), daemon=True,
                                      name=f"igtl-recorder-{port}")
            self._readers.append(thread)
            thread.start()

    def stop(self) -> str:
        """Stop reading, describe what was read, close the log and write the summary."""
        if self._summary is not None:
            return self._summary
        self._stop.set()
        with self._lock:
            sockets = list(self._sockets.values())
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self._backlogChanged:
            self._backlogChanged.notify_all()
        for thread in self._readers:
            thread.join(timeout=5.0)
        with self._backlogChanged:
            self._readersDone = True
            self._backlogChanged.notify_all()
        if self._describer is not None:
            self._describer.join()
        with self._lock:
            if self._log is not None:
                self._log.close()
                self._log = None
            self._summary = self.summary()
        (self.outDir / "summary.md").write_text(self._summary, encoding="utf-8")
        return self._summary

    def _run(self, port: int) -> None:
        announcedWaiting = False
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, port), timeout=CONNECT_TIMEOUT_SEC)
            except OSError:
                if not announcedWaiting:
                    self._report(f"{port}: nothing answers on {self.host}:{port}; trying every "
                                 f"{RETRY_SEC:g} s.")
                    announcedWaiting = True
                self._stop.wait(RETRY_SEC)
                continue
            announcedWaiting = False
            with self._lock:
                self._sockets[port] = sock
                self.connections[port].append(datetime.now().isoformat(timespec="milliseconds"))
            self._report(f"{port}: connected to {self.host}:{port}.")
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECEIVE_BUFFER_BYTES)
                sock.settimeout(READ_POLL_SEC)
                self._read(port, sock)
            except (OSError, ValueError) as error:
                if not self._stop.is_set():
                    self._report(f"{port}: connection lost ({error}).")
            finally:
                with self._lock:
                    self._sockets.pop(port, None)
                sock.close()
            if not self._stop.is_set():
                self._report(f"{port}: the server closed the connection.")
                self._stop.wait(RETRY_SEC)

    def _receiveExactly(self, sock: socket.socket, size: int) -> bytearray | None:
        buffer = bytearray(size)
        view = memoryview(buffer)
        received = 0
        while received < size:
            if self._stop.is_set():
                return None
            try:
                count = sock.recv_into(view[received:], size - received)
            except socket.timeout:
                continue
            if count == 0:
                return None
            received += count
        return buffer

    def _read(self, port: int, sock: socket.socket) -> None:
        while not self._stop.is_set():
            headerBytes = self._receiveExactly(sock, HEADER_SIZE)
            if headerBytes is None:
                return
            startedMonotonic = time.monotonic()
            header = parseHeader(bytes(headerBytes))
            body = self._receiveExactly(sock, header["bodySize"])
            if body is None:
                return
            arrivedMonotonic = time.monotonic()
            arrival = {"port": port,
                       "arrival": datetime.now().isoformat(timespec="milliseconds"),
                       "arrivalMonotonic": round(arrivedMonotonic, 4),
                       "bodyReadSec": round(arrivedMonotonic - startedMonotonic, 4)}
            with self._backlogChanged:
                heldBackFrom = time.monotonic()
                while self._backlogBytes > MAX_BACKLOG_BYTES and not self._stop.is_set():
                    self._backlogChanged.wait(READ_POLL_SEC)
                self.heldBackSec[port] += time.monotonic() - heldBackFrom
                self._backlog.append((arrival, header, body))
                self._backlogBytes += len(body)
                self._backlogChanged.notify_all()

    def _describeAll(self) -> None:
        while True:
            with self._backlogChanged:
                while not self._backlog and not self._readersDone:
                    self._backlogChanged.wait()
                if not self._backlog:
                    return
                arrival, header, body = self._backlog.popleft()
                self._backlogBytes -= len(body)
                self._backlogChanged.notify_all()
            waitSec = time.monotonic() - arrival["arrivalMonotonic"]
            record, pixels = describeMessage(header, body)
            record = {**arrival, "describeWaitSec": round(waitSec, 4), **record}
            if self.comparison is not None and pixels is not None:
                record["cubeMatch"] = self.comparison.match(pixels)
            port = arrival["port"]
            with self._lock:
                self.records.append(record)
                self._messageCounts[port] += 1
                count = self._messageCounts[port]
                if self._log is not None:
                    self._log.write(jsonLine(record) + "\n")
                    self._log.flush()
            self._announce(port, count, record)

    def _announce(self, port: int, count: int, record: dict) -> None:
        image = record.get("image")
        isBand = image is not None and image["components"] == 1
        isImage = record["messageType"] == "IMAGE"
        if not (isBand or not isImage or count == 1 or count % FRAME_REPORT_EVERY == 0):
            return
        text = f"{port}: message {count}, {record['messageType']} '{record['deviceName']}'"
        if image is not None:
            size = " x ".join(str(value) for value in image["size"][:2])
            text += f" {size} x {image['components']} {image['scalarType']}"
        if "text" in record:
            text += f" {_quoted(record['text'])}"
        if record["metadata"]:
            text += f", metadata {sorted(record['metadata'])}"
        if "cubeMatch" in record:
            match = record["cubeMatch"]
            text += (", matches no cube band" if match is None
                     else f", cube band {match['band']} {match['orientation']}")
        if not record["crcMatches"]:
            text += ", CRC DOES NOT MATCH"
        self._report(text + ".")

    def summary(self) -> str:
        records = list(self.records)
        lines = ["# OpenIGTLink recording", ""]
        started = self._started.isoformat(timespec="seconds") if self._started else "?"
        lines.append(f"Recorded from {self.host}, ports {', '.join(map(str, self.ports))}, "
                     f"started {started}, stopped {datetime.now().isoformat(timespec='seconds')}.")
        if self.comparison is not None:
            lines.append(f"Compare cube: {self.comparison.dataPath.name}, "
                         f"{self.comparison.samples} x {self.comparison.lines} x "
                         f"{self.comparison.bands} {self.comparison.dtype.name}.")
        lines.append(f"Messages: {len(records)}. No pixel data was written.")
        for port in self.ports:
            lines += ["", *self._portSummary(port, [r for r in records if r["port"] == port])]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _counts(values) -> str:
        counts = Counter(values)
        if not counts:
            return "none"
        return ", ".join(f"{value} ({count})" for value, count in counts.most_common())

    def _portSummary(self, port: int, records: list) -> list:
        lines = [f"## Port {port}", ""]
        connections = self.connections.get(port, [])
        lines.append(f"- Connected: {', '.join(connections) if connections else 'never'}")
        lines.append(f"- Messages: {len(records)}")
        if not records:
            return lines
        lines.append(f"- Device names: {self._counts(r['deviceName'] for r in records)}")
        lines.append(f"- Message types: {self._counts(r['messageType'] for r in records)}")
        lines.append(f"- Header versions: {self._counts(r['headerVersion'] for r in records)}")
        keys = sorted({key for r in records for key in r["metadata"]})
        lines.append(f"- Metadata keys: {', '.join(keys) if keys else 'none'}")
        lines.append(f"- CRC mismatches: {sum(1 for r in records if not r['crcMatches'])}")
        errors = [r for r in records if "parseError" in r]
        if errors:
            lines.append(f"- Parse errors: {len(errors)}, first: {errors[0]['parseError']}")
        images = [r["image"] for r in records if "image" in r]
        if images:
            def text(image, key):
                return json.dumps(image[key])
            for key in ("size", "components", "scalarType", "endianness", "coordinateSystem",
                        "spacing", "origin", "direction", "subvolumeOffset", "version"):
                lines.append(f"- Image {key}: {self._counts(text(image, key) for image in images)}")
        times = [r["arrivalMonotonic"] for r in records]
        if len(times) > 1:
            span = times[-1] - times[0]
            gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
            megabytes = sum(r["bodySize"] for r in records) / 1e6
            lines.append(f"- First to last message: {span:.2f} s, "
                         f"{(len(times) - 1) / span if span else 0:.2f} messages/s, "
                         f"{megabytes / span if span else 0:.1f} MB/s")
            lines.append(f"- Longest gap between messages: {max(gaps):.2f} s")
        lines.append("- Longest wait before a message was described: "
                     f"{max(r['describeWaitSec'] for r in records):.2f} s")
        heldBack = self.heldBackSec.get(port, 0.0)
        lines.append(f"- Reader held back by the describer: {heldBack:.1f} s"
                     + (" (more than the backlog allows was waiting, so the rate and gaps above "
                        "may be the recorder's, not the sender's)" if heldBack >= 0.05 else ""))
        others = [r for r in records if r["messageType"] != "IMAGE"]
        lines.append("- Messages other than IMAGE: "
                     + (self._counts(_messageLabel(r) for r in others) if others else "none"))
        matched = [r for r in records if "cubeMatch" in r]
        if matched:
            lines += self._bandSummary(records, matched, others, keys)
        return lines

    def _bandSummary(self, records: list, matched: list, others: list, keys: list) -> list:
        captures = [[matched[0]]]
        for earlier, later in zip(matched, matched[1:], strict=False):
            if later["arrivalMonotonic"] - earlier["arrivalMonotonic"] > self.captureGapSec:
                captures.append([])
            captures[-1].append(later)
        lines = [
            f"- Single-component images compared with the cube: {len(matched)}",
            f"- Captures (a new one starts after {self.captureGapSec:g} s without a compared "
            f"image): {len(captures)}",
        ]
        # Records are in arrival order; timestamps can tie.
        position = {id(record): index for index, record in enumerate(records)}
        for number, capture in enumerate(captures, start=1):
            end = position[id(captures[number][0])] if number < len(captures) else len(records)
            after = [r for r in records[position[id(capture[-1])] + 1:end]
                     if r["messageType"] != "IMAGE"]
            lines += ["", f"### Capture {number}", "", *self._captureSummary(capture, after)]
        if not others and not keys:
            lines += ["", "End of cube: only IMAGE messages without metadata arrived, so no "
                      "message marks where a cube ends."]
        return lines

    def _captureSummary(self, matched: list, after: list) -> list:
        bands = [r["cubeMatch"]["band"] for r in matched if r["cubeMatch"] is not None]
        unmatched = sum(1 for r in matched if r["cubeMatch"] is None)
        repeated = sorted(band for band, count in Counter(bands).items() if count > 1)
        outOfOrder = [f"band {later} after band {earlier}"
                      for earlier, later in zip(bands, bands[1:], strict=False) if later <= earlier]
        missing = sorted(set(range(1, self.comparison.bands + 1)) - set(bands))
        orientations = self._counts(r["cubeMatch"]["orientation"] for r in matched
                                    if r["cubeMatch"] is not None)
        lines = [
            f"- Compared images: {len(matched)}, from {matched[0]['arrival']}",
            f"- Bands matched, in arrival order: {formatSequence(bands)}",
            f"- Orientation: {orientations}",
            f"- Images that match no band: {unmatched}",
            f"- Missing bands: {formatSequence(missing)}",
            f"- Repeated bands: {formatSequence(repeated)}",
            f"- Out of order: {', '.join(outOfOrder) if outOfOrder else 'none'}",
        ]
        if len(matched) > 1:
            span = matched[-1]["arrivalMonotonic"] - matched[0]["arrivalMonotonic"]
            lines.append(f"- First to last compared image: {span:.2f} s, "
                         f"{(len(matched) - 1) / span if span else 0:.2f} images/s")
        lines.append("- Followed by: "
                     + ("; ".join(_messageLabel(r) for r in after) if after else "nothing"))
        return lines


def _parseArguments(argv):
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim.igtl_recorder",
        description="Record every message an OpenIGTLink server sends. Connects as the client, "
                    "sends nothing, and writes no pixel data.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="server address (default 127.0.0.1)")
    parser.add_argument("--ports", default=",".join(map(str, DEFAULT_PORTS)),
                        help="comma-separated ports (default 18944,18945,18946)")
    parser.add_argument("--compare-cube", type=Path, default=None,
                        help="ENVI header of a uint16 or float32 BSQ cube to match bands against")
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default workspace\\igtl-recordings\\<time>)")
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after this many seconds (default: until Ctrl+C)")
    parser.add_argument("--capture-gap", type=float, default=DEFAULT_CAPTURE_GAP_SEC,
                        help="seconds without a compared image after which the next one starts "
                             "a new capture in the summary (default 5)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    arguments = _parseArguments(argv)
    try:
        ports = [int(value) for value in arguments.ports.split(",") if value.strip()]
    except ValueError:
        print(f"ERROR: --ports must be numbers separated by commas, not {arguments.ports!r}.")
        return 2
    out = arguments.out or DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    print("OpenIGTLink recorder: connects as the client, sends nothing, writes no pixel data.")
    print("Each port serves one client. Do not connect SLIAFlow to the same ports meanwhile.")
    comparison = None
    if arguments.compare_cube is not None:
        print(f"Reading compare cube {arguments.compare_cube} ...")
        started = time.perf_counter()
        try:
            comparison = CubeComparison(arguments.compare_cube)
        except (OSError, ValueError) as error:
            print(f"ERROR: {error}")
            return 2
        print(f"Compare cube read: {comparison.samples} x {comparison.lines} x "
              f"{comparison.bands} {comparison.dtype.name}, {time.perf_counter() - started:.1f} s.")
    recorder = Recorder(arguments.host, ports, out, comparison=comparison, report=print,
                        captureGapSec=arguments.capture_gap)
    recorder.start()
    print(f"Recording to {out}. Press Ctrl+C to stop.")
    with igtl_transport.InterruptFlag() as interrupt:
        deadline = None if arguments.duration is None else time.monotonic() + arguments.duration
        while not interrupt.requested and (deadline is None or time.monotonic() < deadline):
            time.sleep(0.1)
    summary = recorder.stop()
    print()
    print(summary)
    print(f"Log and summary written to {out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
