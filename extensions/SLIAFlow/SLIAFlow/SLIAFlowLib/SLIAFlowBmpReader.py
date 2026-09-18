"""Read the 24-bit BMPs the vendored UC1 pipeline writes, and refuse anything else.

Every image SLIAFlow displays from a UC1 run is written by `writeBMP` in
`gpu_single_bsq/source/BitmapWriter.cpp`: a 14-byte file header, a 40-byte
info header, then bottom-up rows of B, G, R bytes, each row padded with zero
bytes to a multiple of four.

Two fields of that header are not trustworthy and are never read here.
`writeBMP` stores `bfSize = 54 + 3 * w * h`, which leaves out the padding bytes
it then writes, and it leaves `biSizeImage` at zero. A correct 345-pixel-wide
output is therefore larger than its own `bfSize`. The layout is checked against
the actual length of the file instead, which is also what catches the unpadded
rows `saveBIPtoBMP` writes.

Decoding is lossless: rows are put top first and B, G, R becomes R, G, B.
Nothing else is done to a pixel.
"""

import struct
from pathlib import Path

import numpy as np

FILE_HEADER_BYTES = 14
INFO_HEADER_BYTES = 40
PIXEL_OFFSET = FILE_HEADER_BYTES + INFO_HEADER_BYTES
BITS_PER_PIXEL = 24
PLANES = 1
# BI_RGB: uncompressed.
COMPRESSION_NONE = 0


class BmpFormatError(ValueError):
    """The bytes are not the uncompressed 24-bit padded BMP UC1 writes."""


def rowPadding(samples: int) -> int:
    """The zero bytes `writeBMP` appends to each row of `samples` pixels."""
    return (4 - (samples * 3) % 4) % 4


def expectedFileBytes(samples: int, lines: int) -> int:
    return PIXEL_OFFSET + lines * (3 * samples + rowPadding(samples))


def decodeUc1Bmp(data: bytes, samples: int, lines: int) -> np.ndarray:
    """Return the image as a (lines, samples, 3) uint8 RGB array, top row first.

    `samples` and `lines` are the recorded case's, from its ENVI header. An
    image of any other size is refused rather than displayed.
    """
    if len(data) < PIXEL_OFFSET:
        raise BmpFormatError(
            f"The file is {len(data)} bytes, shorter than the {PIXEL_OFFSET}-byte BMP header."
        )
    signature, _fileSizeField, _reserved1, _reserved2, pixelOffset = struct.unpack_from(
        "<2sIHHI", data, 0
    )
    infoHeaderSize, width, height, planes, bitCount, compression = struct.unpack_from(
        "<IiiHHI", data, FILE_HEADER_BYTES
    )
    if signature != b"BM":
        raise BmpFormatError(f"The file does not start with the BMP signature BM ({signature!r}).")
    if pixelOffset != PIXEL_OFFSET:
        raise BmpFormatError(
            f"The pixel data starts at byte {pixelOffset}, not at {PIXEL_OFFSET} as UC1 writes it."
        )
    if infoHeaderSize != INFO_HEADER_BYTES:
        raise BmpFormatError(
            f"The info header is {infoHeaderSize} bytes, not the {INFO_HEADER_BYTES} UC1 writes."
        )
    if planes != PLANES:
        raise BmpFormatError(f"The image declares {planes} planes, not {PLANES}.")
    if bitCount != BITS_PER_PIXEL:
        raise BmpFormatError(f"The image is {bitCount}-bit, not {BITS_PER_PIXEL}-bit.")
    if compression != COMPRESSION_NONE:
        raise BmpFormatError(f"The image is compressed (method {compression}), not uncompressed.")
    if height <= 0 or width <= 0:
        raise BmpFormatError(
            f"The image is {width} x {height}; UC1 writes a positive width and a positive, "
            "bottom-up height."
        )
    if (width, height) != (samples, lines):
        raise BmpFormatError(
            f"The image is {width} x {height} but the case is {samples} x {lines} "
            "(samples x lines)."
        )
    expected = expectedFileBytes(samples, lines)
    if len(data) != expected:
        raise BmpFormatError(
            f"The file is {len(data)} bytes but a {samples} x {lines} 24-bit BMP with padded "
            f"rows is {expected} bytes. Unpadded or truncated rows are not decoded."
        )

    stride = 3 * samples + rowPadding(samples)
    rows = np.frombuffer(data, dtype=np.uint8, count=lines * stride, offset=PIXEL_OFFSET)
    pixels = rows.reshape(lines, stride)[:, : 3 * samples].reshape(lines, samples, 3)
    return np.ascontiguousarray(pixels[::-1, :, ::-1])


def readUc1Bmp(path, samples: int, lines: int) -> np.ndarray:
    return decodeUc1Bmp(Path(path).read_bytes(), samples, lines)
