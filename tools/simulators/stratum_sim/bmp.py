"""Write the UC1 majority-voting palette as a byte-compatible 24-bit BMP."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy

# This is one definition, read from gpu_single_bsq/source/functions_cuda.cu.
# The exported forward and inverse dictionaries below are derived from it so
# the SLIA-013 palette inverse cannot drift from the stand-in's forward table.
CLASS_PALETTE = (
    (1, (0, 255, 0)),
    (2, (255, 0, 0)),
    (3, (0, 0, 255)),
    (4, (0, 0, 0)),
)
CLASS_TO_RGB = dict(CLASS_PALETTE)
RGB_TO_CLASS = {rgb: classValue for classValue, rgb in CLASS_PALETTE}


def _asTwoDimensional(array: numpy.ndarray, name: str) -> numpy.ndarray:
    array = numpy.asarray(array)
    if array.ndim == 3 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 2 or 0 in array.shape:
        raise ValueError(f"{name} must be a non-empty 2-D image, got shape {array.shape}.")
    return array


def classMapToRgb(classMap: numpy.ndarray) -> numpy.ndarray:
    """Convert a 2-D or one-slice UC1 class map to an RGB uint8 image."""
    classMap = _asTwoDimensional(classMap, "classMap")
    if not numpy.issubdtype(classMap.dtype, numpy.integer):
        raise ValueError(f"classMap must have an integer dtype, got {classMap.dtype}.")

    presentClasses = set(numpy.unique(classMap).tolist())
    unknownClasses = sorted(presentClasses - set(CLASS_TO_RGB))
    if unknownClasses:
        raise ValueError(f"classMap contains unsupported class values: {unknownClasses}.")

    rgb = numpy.empty((*classMap.shape, 3), dtype=numpy.uint8)
    for classValue, colour in CLASS_PALETTE:
        rgb[classMap == classValue] = colour
    return rgb


def rgbToClassMap(rgb: numpy.ndarray) -> numpy.ndarray:
    """Convert an RGB uint8 image made with :func:`classMapToRgb` to classes."""
    rgb = numpy.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or 0 in rgb.shape[:2]:
        raise ValueError(f"rgb must have a non-empty (lines, samples, 3) shape, got {rgb.shape}.")

    classMap = numpy.zeros(rgb.shape[:2], dtype=numpy.uint8)
    matched = numpy.zeros(rgb.shape[:2], dtype=bool)
    for colour, classValue in RGB_TO_CLASS.items():
        current = numpy.all(rgb == colour, axis=2)
        classMap[current] = classValue
        matched |= current

    if not numpy.all(matched):
        unknownColours = numpy.unique(rgb[~matched], axis=0).tolist()
        raise ValueError(f"rgb contains unsupported colours: {unknownColours}.")
    return classMap


def _channelAsImage(channel: numpy.ndarray, name: str) -> numpy.ndarray:
    channel = _asTwoDimensional(channel, name)
    if not numpy.issubdtype(channel.dtype, numpy.number):
        raise ValueError(f"{name} must contain numeric values, got {channel.dtype}.")
    if not numpy.all(numpy.isfinite(channel)):
        raise ValueError(f"{name} must contain only finite values.")
    return channel


def _cByteValue(value: numpy.generic | int | float) -> int:
    """Match the C writer's upper clamp and unsigned-byte conversion."""
    integer = int(value)
    if integer > 255:
        return 255
    # The C implementation only clamps values above 255. On the Windows
    # two's-complement targets this is the corresponding unsigned conversion
    # for a negative value.
    return integer % 256


def writeBMP(
    outputPath: Path | str,
    red: numpy.ndarray,
    green: numpy.ndarray,
    blue: numpy.ndarray,
) -> None:
    """Write red, green and blue channels using UC1's ``writeBMP`` layout.

    The input arrays are top-to-bottom 2-D images. The file is a 24-bit
    bottom-up BMP with B, G, R pixels and four-byte row padding.
    """
    red = _channelAsImage(red, "red")
    green = _channelAsImage(green, "green")
    blue = _channelAsImage(blue, "blue")
    if not (red.shape == green.shape == blue.shape):
        raise ValueError(
            f"red, green and blue must have equal shapes, got "
            f"{red.shape}, {green.shape} and {blue.shape}."
        )

    height, width = red.shape
    # This intentionally mirrors the C code's `filesize = 54 + 3*w*h`.
    # It omits the row padding even though the bytes are written below.
    fileSizeField = 54 + 3 * width * height
    fileHeader = struct.pack("<2sIHHI", b"BM", fileSizeField, 0, 0, 54)
    infoHeader = struct.pack(
        "<IiiHHIIIIII",
        40,
        width,
        height,
        1,
        24,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    rowPadding = (4 - (width * 3) % 4) % 4
    pixelBytes = bytearray()
    for row in range(height - 1, -1, -1):
        for column in range(width):
            pixelBytes.extend(
                (
                    _cByteValue(blue[row, column]),
                    _cByteValue(green[row, column]),
                    _cByteValue(red[row, column]),
                )
            )
        pixelBytes.extend(b"\x00" * rowPadding)

    Path(outputPath).write_bytes(fileHeader + infoHeader + pixelBytes)


def writeClassMapBMP(outputPath: Path | str, classMap: numpy.ndarray) -> None:
    """Write a class map through the shared UC1 palette."""
    rgb = classMapToRgb(classMap)
    writeBMP(outputPath, rgb[..., 0], rgb[..., 1], rgb[..., 2])


__all__ = [
    "CLASS_PALETTE",
    "CLASS_TO_RGB",
    "RGB_TO_CLASS",
    "classMapToRgb",
    "rgbToClassMap",
    "writeBMP",
    "writeClassMapBMP",
]
