"""Measure how every UC1 BMP declares its own size, and what a stride-blind reader does with it.

The UC1 pipeline writes its images with two unrelated families of writer in
`gpu_single_bsq/source/BitmapWriter.cpp`. This script does not trust either one:
for each BMP it compares three independent numbers.

1. `bfSize`, the file size the BMP header itself declares.
2. The number of bytes the file actually occupies on disk.
3. The size the BMP format requires for the width, height and bit depth the
   same header declares, with each row rounded up to a multiple of 4 bytes.

Where those three disagree, the script says which of the two defects it found,
and then decodes the image twice - once honouring the row stride, once assuming
rows are exactly `width * 3` bytes - and measures the difference. Nothing here
imports `slicer`, `PIL`, `cv2` or any other image library: the BMP parsing, the
decoding and the PNG writing are all done from the standard library plus NumPy,
so the result cannot be an artefact of some library's own repair logic.

Usage:

    python scripts/development/inspect-uc1-bmp.py
    python scripts/development/inspect-uc1-bmp.py --sample-case 017-01
    python scripts/development/inspect-uc1-bmp.py --output-root D:/somewhere/output

Written for SLIAFlow. Read-only: it never writes into the UC1 output tree.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FILE_HEADER_BYTES = 14
INFO_HEADER_BYTES = 40
HEADER_BYTES = FILE_HEADER_BYTES + INFO_HEADER_BYTES

# The five images SLIAFlow offers in the Tumour Delineation panel, plus the one
# it deliberately does not offer. Kept in this order so the report reads the
# same way every time.
DISPLAYED_OUTPUTS = ("imageRGB.bmp", "pca.bmp", "svm.bmp", "knn.bmp", "kmeans.bmp")
EXCLUDED_OUTPUT = "CalibratedImage_BIP.bmp"
ALL_OUTPUTS = (*DISPLAYED_OUTPUTS, EXCLUDED_OUTPUT)

# Which BitmapWriter.cpp function produces each file. Established by reading the
# call sites in functions_cuda.cu and main.cu; quoted in the report so a reader
# can check the attribution without re-deriving it.
PRODUCING_WRITER = {
    "imageRGB.bmp": "writeMatrixRGB -> writeBMP",
    "pca.bmp": "savePCAOutputAsBMP -> writeBMP",
    "svm.bmp": "writeKNNBMP",
    "knn.bmp": "writeKNNBMP",
    "kmeans.bmp": "writeKmeansBMP",
    EXCLUDED_OUTPUT: "saveBIPtoBMP",
}

DEFAULT_OUTPUT_ROOT = Path("build/uc1/UC1/gpu_single_bsq/source/output")
DEFAULT_CASE_ROOT = Path("input")

# The UC1 output tree also accumulates folders from older runs of the retired
# simulator, which are not recorded cases and have no ENVI header to check
# against. A case is counted only when `<case-root>/**/<name>/raw.hdr` exists,
# which is the same rule the SLIAFlow case pool applies.
ENVI_HEADER_NAME = "raw.hdr"

# Verdicts, in increasing severity. A file is judged only against its own
# declared geometry, never against an expectation supplied from outside.
CONFORMANT = "conformant"
UNDERSTATED_BFSIZE = "understated-bfSize"
UNPADDED_ROWS = "unpadded-rows"
UNREADABLE = "unreadable"

VERDICT_MEANING = {
    CONFORMANT: "bfSize, the file on disk and the padded layout all agree.",
    UNDERSTATED_BFSIZE: (
        "The rows are padded correctly, so the pixels are where the BMP format says "
        "they are, but bfSize omits the padding bytes and so understates the file."
    ),
    UNPADDED_ROWS: (
        "The rows carry no padding at all. The file is shorter than the format "
        "requires and every row after the first starts at the wrong offset."
    ),
    UNREADABLE: "The file could not be parsed as an uncompressed 24-bit BMP.",
}


def row_padding(width: int) -> int:
    """The bytes a conformant 24-bit BMP appends to a row of `width` pixels."""
    return (4 - (width * 3) % 4) % 4


def conformant_size(width: int, height: int) -> int:
    return HEADER_BYTES + height * (3 * width + row_padding(width))


def unpadded_size(width: int, height: int) -> int:
    return HEADER_BYTES + height * 3 * width


@dataclass
class BmpFacts:
    """Everything measurable about one BMP, with no interpretation applied yet."""

    path: Path
    physical_bytes: int
    verdict: str = UNREADABLE
    note: str = ""
    width: int = 0
    height: int = 0
    bit_count: int = 0
    compression: int = 0
    pixel_offset: int = 0
    declared_bfsize: int = 0
    declared_bisizeimage: int = 0
    padding: int = 0
    # The geometry the case's own ENVI header gives, for cross-checking.
    case_samples: int = 0
    case_lines: int = 0

    @property
    def geometry_matches_case(self) -> bool:
        return (self.width, self.height) == (self.case_samples, self.case_lines)

    @property
    def stride(self) -> int:
        return 3 * self.width + self.padding

    @property
    def bfsize_error(self) -> int:
        """How many bytes bfSize is short by, measured against the real file."""
        return self.physical_bytes - self.declared_bfsize

    @property
    def missing_bytes(self) -> int:
        """How many bytes the file is short of a conformant layout."""
        return conformant_size(self.width, self.height) - self.physical_bytes


def read_bmp_facts(path: Path) -> BmpFacts:
    data = path.read_bytes()
    facts = BmpFacts(path=path, physical_bytes=len(data))
    if len(data) < HEADER_BYTES:
        facts.note = f"only {len(data)} bytes, shorter than a {HEADER_BYTES}-byte BMP header"
        return facts

    signature, bfsize, _r1, _r2, pixel_offset = struct.unpack_from("<2sIHHI", data, 0)
    info_size, width, height, _planes, bit_count, compression, bisizeimage = struct.unpack_from(
        "<IiiHHII", data, FILE_HEADER_BYTES
    )
    if signature != b"BM":
        facts.note = f"does not start with the BMP signature BM (found {signature!r})"
        return facts

    facts.width = width
    facts.height = height
    facts.bit_count = bit_count
    facts.compression = compression
    facts.pixel_offset = pixel_offset
    facts.declared_bfsize = bfsize
    facts.declared_bisizeimage = bisizeimage

    if info_size != INFO_HEADER_BYTES or bit_count != 24 or compression != 0:
        facts.note = (
            f"{info_size}-byte info header, {bit_count} bits per pixel, compression "
            f"{compression}; this script only judges uncompressed 24-bit BMPs"
        )
        return facts
    if width <= 0 or height <= 0:
        facts.note = f"declares {width} x {height}"
        return facts

    facts.padding = row_padding(width)
    if facts.physical_bytes == conformant_size(width, height):
        facts.verdict = (
            CONFORMANT if bfsize == facts.physical_bytes else UNDERSTATED_BFSIZE
        )
    elif facts.physical_bytes == unpadded_size(width, height):
        facts.verdict = UNPADDED_ROWS
    else:
        facts.note = (
            f"{facts.physical_bytes} bytes matches neither the padded layout "
            f"({conformant_size(width, height)}) nor an unpadded one "
            f"({unpadded_size(width, height)})"
        )
    return facts


def decode(data: bytes, width: int, height: int, stride: int) -> np.ndarray:
    """Decode with the row stride given, and nothing else.

    The only difference between the correct and the stride-blind reading of a UC1
    BMP is the value of `stride`, so both are produced by this one function. Rows
    come back top first and the BMP's B, G, R order becomes R, G, B.
    """
    needed = HEADER_BYTES + height * stride
    if len(data) < needed:
        raise ValueError(f"needs {needed} bytes for a stride of {stride}, has {len(data)}")
    rows = np.frombuffer(data, dtype=np.uint8, count=height * stride, offset=HEADER_BYTES)
    pixels = rows.reshape(height, stride)[:, : 3 * width].reshape(height, width, 3)
    return np.ascontiguousarray(pixels[::-1, :, ::-1])


def decode_both(facts: BmpFacts) -> tuple[np.ndarray, np.ndarray]:
    """The same file read correctly and read stride-blind."""
    data = facts.path.read_bytes()
    correct = decode(data, facts.width, facts.height, facts.stride)
    blind = decode(data, facts.width, facts.height, 3 * facts.width)
    return correct, blind


@dataclass
class Divergence:
    """What the stride-blind reading does to one image, in measured quantities."""

    differing_pixels: int
    total_pixels: int
    first_bad_row_from_bottom: int | None
    colours_only_in_blind: list[tuple[int, int, int]] = field(default_factory=list)
    colour_count_correct: int = 0
    colour_count_blind: int = 0

    @property
    def differing_share(self) -> float:
        return self.differing_pixels / self.total_pixels if self.total_pixels else 0.0


def measure_divergence(correct: np.ndarray, blind: np.ndarray) -> Divergence:
    differs = np.any(correct != blind, axis=2)
    # Row 0 of the arrays is the top of the image, which is the last row in the
    # file. Counting from the bottom names the row in the order it was written.
    bottom_up = differs[::-1]
    bad_rows = np.flatnonzero(bottom_up.any(axis=1))
    first_bad = int(bad_rows[0]) if bad_rows.size else None

    def palette(image: np.ndarray) -> set[tuple[int, int, int]]:
        flat = image.reshape(-1, 3)
        return {tuple(int(c) for c in rgb) for rgb in np.unique(flat, axis=0)}

    correct_palette = palette(correct)
    blind_palette = palette(blind)
    return Divergence(
        differing_pixels=int(differs.sum()),
        total_pixels=int(differs.size),
        first_bad_row_from_bottom=first_bad,
        colours_only_in_blind=sorted(blind_palette - correct_palette),
        colour_count_correct=len(correct_palette),
        colour_count_blind=len(blind_palette),
    )


def write_png(path: Path, image: np.ndarray, scale: int = 1) -> None:
    """Write an RGB uint8 array as a PNG, using only zlib and struct.

    A PNG is written rather than a BMP so that the very defect under study cannot
    creep into the evidence.
    """
    if scale > 1:
        image = np.repeat(np.repeat(image, scale, axis=0), scale, axis=1)
    height, width = image.shape[:2]
    raw = b"".join(b"\x00" + image[y].tobytes() for y in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def difference_mask(correct: np.ndarray, blind: np.ndarray) -> np.ndarray:
    """Black where the two readings agree, red where they do not."""
    differs = np.any(correct != blind, axis=2)
    mask = np.zeros_like(correct)
    mask[differs] = (255, 40, 40)
    return mask


def build_fixture(width: int, height: int) -> bytes:
    """A conformant BMP small enough to check by hand, containing no imagery.

    Each row is a single flat colour, so a reader that mistakes the stride
    produces visibly wrong rows rather than a subtle smear. Row i counting from
    the bottom of the file gets the colour (10 * i, 200, 255 - 10 * i).
    """
    padding = row_padding(width)
    body = bytearray()
    for i in range(height):
        red, green, blue = 10 * i, 200, 255 - 10 * i
        body += bytes([blue, green, red]) * width
        body += b"\x00" * padding
    size = HEADER_BYTES + len(body)
    header = struct.pack("<2sIHHI", b"BM", size, 0, 0, HEADER_BYTES) + struct.pack(
        "<IiiHHIIiiII", INFO_HEADER_BYTES, width, height, 1, 24, 0, 0, 2835, 2835, 0, 0
    )
    return bytes(header) + bytes(body)


def fixture_case(width: int, height: int) -> dict:
    """One hand-checkable fixture of the given width, measured both ways."""
    conformant = build_fixture(width, height)
    padding = row_padding(width)
    # The same pixel bytes with every row's padding removed: exactly what the
    # unpadded writer emits. The header is left untouched on purpose, so the file
    # claims a geometry its body no longer supports.
    stripped = bytearray(conformant[:HEADER_BYTES])
    for i in range(height):
        start = HEADER_BYTES + i * (3 * width + padding)
        stripped += conformant[start : start + 3 * width]

    correct = decode(conformant, width, height, 3 * width + padding)
    blind = decode(conformant, width, height, 3 * width)
    divergence = measure_divergence(correct, blind)
    return {
        "width": width,
        "height": height,
        "padding": padding,
        "stride": 3 * width + padding,
        "conformantBytes": len(conformant),
        "unpaddedBytes": len(stripped),
        "bytesLostToStripping": len(conformant) - len(stripped),
        "bfSizeTheUc1WritersWouldDeclare": HEADER_BYTES + 3 * width * height,
        "correctRowColours": [[int(c) for c in correct[row, 0]] for row in range(height)],
        "blindTopLeftColours": [[int(c) for c in blind[row, 0]] for row in range(height)],
        "differingPixels": divergence.differing_pixels,
        "totalPixels": divergence.total_pixels,
        "coloursOnlyInBlindReading": [list(c) for c in divergence.colours_only_in_blind],
        "arrays": (correct, blind),
    }


def fixture_demonstration(images_dir: Path, height: int = 5) -> dict:
    """Reproduce the defect on fixtures covering all four padding classes.

    Widths 4, 5, 6 and 7 need 0, 1, 2 and 3 padding bytes per row. Running all
    four is what shows why a quarter of the case pool looks perfectly fine: a
    width that needs no padding cannot expose the defect at all.
    """
    results = []
    for width in (4, 5, 6, 7):
        entry = fixture_case(width, height)
        correct, blind = entry.pop("arrays")
        write_png(images_dir / f"fixture-w{width}-correct.png", correct, scale=44)
        write_png(images_dir / f"fixture-w{width}-blind.png", blind, scale=44)
        write_png(
            images_dir / f"fixture-w{width}-diff.png",
            difference_mask(correct, blind),
            scale=44,
        )
        results.append(entry)
    return {"height": height, "cases": results}


def recorded_cases(case_root: Path) -> dict[str, tuple[int, int]]:
    """Every recorded case under `case_root`, as name -> (samples, lines).

    Read straight from the ENVI header, so the geometry each BMP declares can be
    checked against a source that is not the BMP itself.
    """
    cases: dict[str, tuple[int, int]] = {}
    if not case_root.is_dir():
        return cases
    for header in sorted(case_root.rglob(ENVI_HEADER_NAME)):
        text = header.read_text(errors="replace")
        found: dict[str, int] = {}
        for line in text.splitlines():
            key, _, value = line.partition("=")
            key = key.strip().lower()
            if key in ("samples", "lines"):
                try:
                    found[key] = int(value.strip())
                except ValueError:
                    pass
        if "samples" in found and "lines" in found:
            cases[header.parent.name] = (found["samples"], found["lines"])
    return cases


def scan(output_root: Path, cases: dict[str, tuple[int, int]]) -> list[BmpFacts]:
    """Inspect the outputs of every recorded case that has any.

    Folders in the output tree that are not recorded cases are skipped, so the
    counts here describe the case pool and nothing else.
    """
    facts: list[BmpFacts] = []
    for case_dir in sorted(p for p in output_root.iterdir() if p.is_dir()):
        if case_dir.name not in cases:
            continue
        for name in ALL_OUTPUTS:
            path = case_dir / name
            if path.is_file():
                item = read_bmp_facts(path)
                samples, lines = cases[case_dir.name]
                item.case_samples = samples
                item.case_lines = lines
                facts.append(item)
    return facts


def byte_identity_check(facts: BmpFacts) -> dict:
    """Prove that the stride-blind reading invents nothing and drops the tail.

    Both readings consume the same byte stream from the same offset. The blind
    reading takes the first `height * 3 * width` bytes of it in order; the correct
    one takes `height * stride`. So the blind reading's pixel bytes must be a
    prefix of the file's pixel region, and the bytes it never reaches are exactly
    the tail. This checks both statements on the real file.
    """
    data = facts.path.read_bytes()
    pixels = data[HEADER_BYTES:]
    blind_span = facts.height * 3 * facts.width
    correct_span = facts.height * facts.stride

    # Undo the presentation steps the decoder applies - the bottom-up row flip and
    # the BGR to RGB swap - and the stride-blind image must come back as exactly
    # the first `blind_span` bytes of the file's pixel region. That is the claim
    # being tested: the blind reader reorders and regroups bytes but originates
    # none of them, and it never reaches the tail.
    blind = decode(data, facts.width, facts.height, 3 * facts.width)
    replayed = blind[::-1, :, ::-1].tobytes()

    padding_offsets = [
        i * facts.stride + 3 * facts.width + k
        for i in range(facts.height)
        for k in range(facts.padding)
    ]
    return {
        "pixelRegionBytes": len(pixels),
        "bytesTheBlindReaderConsumes": blind_span,
        "bytesTheBlindReaderNeverReaches": correct_span - blind_span,
        "blindSpanIsAPrefixOfTheFile": replayed == pixels[:blind_span],
        "paddingBytesInsideTheBlindSpan": sum(1 for o in padding_offsets if o < blind_span),
        "everyPaddingByteIsZero": all(pixels[o] == 0 for o in padding_offsets),
    }


def summarise(all_facts: list[BmpFacts]) -> dict:
    by_verdict = Counter(f.verdict for f in all_facts)
    by_writer: dict[str, Counter] = {}
    for f in all_facts:
        writer = PRODUCING_WRITER.get(f.path.name, "unknown")
        by_writer.setdefault(writer, Counter())[f.verdict] += 1

    # One padding value per case: it is a property of the case width.
    padding_by_case: dict[str, int] = {}
    width_by_case: dict[str, int] = {}
    for f in all_facts:
        if f.verdict != UNREADABLE:
            padding_by_case[f.path.parent.name] = f.padding
            width_by_case[f.path.parent.name] = f.width

    padding_histogram = Counter(padding_by_case.values())
    affected = sum(n for pad, n in padding_histogram.items() if pad)
    displayed = [f for f in all_facts if f.path.name in DISPLAYED_OUTPUTS]
    mismatched = [f for f in all_facts if f.width and not f.geometry_matches_case]
    return {
        "filesInspected": len(all_facts),
        "casesInspected": len(padding_by_case),
        "displayedOutputsPresent": len(displayed),
        "geometryMismatchesAgainstEnviHeader": len(mismatched),
        "verdicts": {k: by_verdict[k] for k in sorted(by_verdict)},
        "verdictsByWriter": {
            w: {k: c[k] for k in sorted(c)} for w, c in sorted(by_writer.items())
        },
        "paddingHistogramByCase": {str(k): v for k, v in sorted(padding_histogram.items())},
        "casesNeedingPadding": affected,
        "casesNeedingPaddingShare": affected / len(padding_by_case) if padding_by_case else 0.0,
        "widthByCase": dict(sorted(width_by_case.items())),
    }


def render_case_panels(facts: BmpFacts, images_dir: Path) -> dict:
    """Write the comparison PNGs for one real output, and say what they show.

    Two quite different pairs come out of this, depending on which defect the
    file carries.

    Defect A (`understated-bfSize`, and the conformant files): the pixels are
    where the format says, so the pair is the correct reading against the
    stride-blind one.

    Defect B (`unpadded-rows`): the file is shorter than the format requires, so
    there is no correct reading to show. The pair is instead the image as UC1
    wrote it - which for this file means the unpadded stride - against what a
    standards-compliant reader produces when it applies the padded stride the
    header's geometry implies and zero-fills the bytes that are missing. For this
    one file the roles are reversed: it is the conforming reader that breaks.
    """
    data = facts.path.read_bytes()
    stem = f"{facts.path.parent.name}-{facts.path.stem}"
    written = {
        "case": facts.path.parent.name,
        "file": facts.path.name,
        "verdict": facts.verdict,
        "width": facts.width,
        "height": facts.height,
        "padding": facts.padding,
        "images": {},
    }

    if facts.verdict == UNPADDED_ROWS:
        as_written = decode(data, facts.width, facts.height, 3 * facts.width)
        padded = data + b"\x00" * max(0, conformant_size(facts.width, facts.height) - len(data))
        as_format = decode(padded, facts.width, facts.height, facts.stride)
        write_png(images_dir / f"{stem}-as-written.png", as_written)
        write_png(images_dir / f"{stem}-as-format.png", as_format)
        write_png(
            images_dir / f"{stem}-diff.png", difference_mask(as_written, as_format)
        )
        divergence = measure_divergence(as_written, as_format)
        written["images"] = {
            "asWritten": f"{stem}-as-written.png",
            "asFormatRequires": f"{stem}-as-format.png",
            "difference": f"{stem}-diff.png",
        }
        written["bytesZeroFilledToReachTheFormatSize"] = facts.missing_bytes
    else:
        correct, blind = decode_both(facts)
        write_png(images_dir / f"{stem}-correct.png", correct)
        write_png(images_dir / f"{stem}-naive.png", blind)
        write_png(images_dir / f"{stem}-diff.png", difference_mask(correct, blind))
        divergence = measure_divergence(correct, blind)
        written["images"] = {
            "correct": f"{stem}-correct.png",
            "naive": f"{stem}-naive.png",
            "difference": f"{stem}-diff.png",
        }

    written["differingPixels"] = divergence.differing_pixels
    written["totalPixels"] = divergence.total_pixels
    written["differingShare"] = divergence.differing_share
    written["colourCountCorrect"] = divergence.colour_count_correct
    written["colourCountOther"] = divergence.colour_count_blind
    written["coloursInvented"] = len(divergence.colours_only_in_blind)
    return written


def vertical_profile(facts: BmpFacts, samples: int = 9) -> list[dict]:
    """How far each row slips, and how much of it actually looks different.

    These are two different quantities and they do not behave the same way. The
    slip is pure arithmetic: row `r` counting up from the bottom of the file
    starts `padding * r` bytes too early, which is `padding * r / 3` pixels, and
    that grows without bound as the reader climbs the image. The share of pixels
    that end up *looking* different does not grow with it, because once the slip
    exceeds a row width it lands on other parts of the image that may happen to
    match. Reporting only the second number is what makes people describe the
    damage as a smooth gradient, which it is not.
    """
    correct, blind = decode_both(facts)
    differs = np.any(correct != blind, axis=2)
    # Row 0 of the arrays is the top of the image, which is the last row written.
    bottom_up = differs[::-1]
    height = facts.height
    indices = sorted({round(i * (height - 1) / (samples - 1)) for i in range(samples)})
    return [
        {
            "rowFromBottomOfFile": r,
            "slipInBytes": facts.padding * r,
            "slipInPixels": facts.padding * r / 3,
            "slipInWholeRows": facts.padding * r / 3 / facts.width,
            "pixelsDifferingInThisRow": float(bottom_up[r].mean()),
        }
        for r in indices
    ]


def aggregate_divergence(all_facts: list[BmpFacts]) -> dict:
    """Decode every displayed output twice and group the damage by padding class.

    This is the part that cannot be argued with from a single example: it is every
    image the operator can actually be shown, measured the same way.
    """
    per_class: dict[int, dict[str, list[float]]] = {}
    per_output: dict[str, dict[int, list[float]]] = {}
    checks = {"prefixHolds": 0, "allPaddingZero": 0, "filesChecked": 0}
    for facts in all_facts:
        if facts.path.name not in DISPLAYED_OUTPUTS:
            continue
        if facts.verdict not in (CONFORMANT, UNDERSTATED_BFSIZE):
            continue
        correct, blind = decode_both(facts)
        divergence = measure_divergence(correct, blind)
        bucket = per_class.setdefault(facts.padding, {"shares": [], "invented": []})
        bucket["shares"].append(divergence.differing_share)
        bucket["invented"].append(float(len(divergence.colours_only_in_blind)))
        per_output.setdefault(facts.path.name, {}).setdefault(facts.padding, []).append(
            divergence.differing_share
        )
        identity = byte_identity_check(facts)
        checks["filesChecked"] += 1
        checks["prefixHolds"] += int(identity["blindSpanIsAPrefixOfTheFile"])
        checks["allPaddingZero"] += int(identity["everyPaddingByteIsZero"])

    def stats(values: list[float]) -> dict:
        return {
            "files": len(values),
            "mean": sum(values) / len(values) if values else 0.0,
            "min": min(values) if values else 0.0,
            "max": max(values) if values else 0.0,
        }

    return {
        "byPaddingClass": {
            str(pad): {
                "differingShare": stats(data["shares"]),
                "coloursInvented": stats(data["invented"]),
            }
            for pad, data in sorted(per_class.items())
        },
        "byOutputAndPadding": {
            name: {str(pad): stats(shares) for pad, shares in sorted(by_pad.items())}
            for name, by_pad in sorted(per_output.items())
        },
        "byteIdentityChecks": checks,
    }


def markdown_report(
    output_root: Path,
    all_facts: list[BmpFacts],
    summary: dict,
    sample: dict | None,
    fixture: dict,
    aggregate: dict | None,
) -> str:
    lines: list[str] = []
    add = lines.append
    add("# UC1 BMP size declarations and what a stride-blind reader makes of them")
    add("")
    add(f"Output tree inspected: `{output_root}`")
    add(
        f"Recorded cases found: {summary.get('recordedCasesFound', summary['casesInspected'])}. "
        f"Cases with at least one output: {summary['casesInspected']}. "
        f"Files inspected: {summary['filesInspected']}."
    )
    add(
        f"Of the {summary.get('displayedOutputSlots', 0)} images SLIAFlow can display "
        f"({summary['casesInspected']} cases x {len(DISPLAYED_OUTPUTS)} outputs), "
        f"{summary['displayedOutputsPresent']} exist on disk."
    )
    add(
        "Images whose declared width and height disagree with the case's own ENVI header: "
        f"{summary['geometryMismatchesAgainstEnviHeader']}."
    )
    add("")
    add("## Verdict counts")
    add("")
    add("| Verdict | Files | Meaning |")
    add("| --- | --- | --- |")
    for verdict, count in summary["verdicts"].items():
        add(f"| `{verdict}` | {count} | {VERDICT_MEANING[verdict]} |")
    add("")
    add("## Verdict by producing writer")
    add("")
    add("| Writer in BitmapWriter.cpp | Files | Verdicts |")
    add("| --- | --- | --- |")
    for writer, counts in summary["verdictsByWriter"].items():
        total = sum(counts.values())
        detail = ", ".join(f"{v} x `{k}`" for k, v in counts.items())
        add(f"| `{writer}` | {total} | {detail} |")
    add("")
    add("## Row padding required, by case")
    add("")
    add("Padding is a property of the image width alone: a width whose `width * 3`")
    add("is already a multiple of 4 needs none, and no defect is observable on it.")
    add("")
    add("| Padding bytes per row | Cases |")
    add("| --- | --- |")
    for pad, count in summary["paddingHistogramByCase"].items():
        add(f"| {pad} | {count} |")
    add("")
    add(
        f"Cases where padding is required: {summary['casesNeedingPadding']} of "
        f"{summary['casesInspected']} ({summary['casesNeedingPaddingShare']:.2%})."
    )
    add("")
    if sample:
        add(f"## Worked example: case {sample['case']}")
        add("")
        add("| File | Writer | Verdict | Declared bfSize | On disk | Padded layout requires |")
        add("| --- | --- | --- | --- | --- | --- |")
        for row in sample["files"]:
            add(
                f"| `{row['file']}` | `{row['writer']}` | `{row['verdict']}` | "
                f"{row['declaredBfSize']} | {row['physicalBytes']} | {row['conformantBytes']} |"
            )
        add("")
        for row in sample["files"]:
            if not row.get("divergence"):
                continue
            d = row["divergence"]
            add(f"### `{row['file']}` read correctly versus read stride-blind")
            add("")
            add(f"- Pixels that differ: {d['differingPixels']} of {d['totalPixels']} "
                f"({d['differingShare']:.2%}).")
            add(f"- First row that differs, counting from the bottom of the file: "
                f"{d['firstBadRowFromBottom']}.")
            add(f"- Distinct colours: {d['colourCountCorrect']} read correctly, "
                f"{d['colourCountBlind']} read stride-blind.")
            if d["coloursOnlyInBlindReading"]:
                add(f"- Colours that exist only in the stride-blind reading: "
                    f"{len(d['coloursOnlyInBlindReading'])} of them.")
            if row.get("byteIdentity"):
                b = row["byteIdentity"]
                add(f"- Bytes the stride-blind reader never reaches: "
                    f"{b['bytesTheBlindReaderNeverReaches']}; padding bytes it consumes as "
                    f"pixel data instead: {b['paddingBytesInsideTheBlindSpan']}.")
            add("")
            if row.get("verticalProfile"):
                add("How far each row slips, against how much of it looks different:")
                add("")
                add("| Row, counting up from the bottom of the file | Slip (bytes) | "
                    "Slip (pixels) | Slip (whole rows) | Pixels differing in that row |")
                add("| --- | --- | --- | --- | --- |")
                for p in row["verticalProfile"]:
                    add(
                        f"| {p['rowFromBottomOfFile']} | {p['slipInBytes']} | "
                        f"{p['slipInPixels']:.1f} | {p['slipInWholeRows']:.2f} | "
                        f"{p['pixelsDifferingInThisRow']:.1%} |"
                    )
                add("")
    if aggregate:
        add("## Every displayed output, read both ways")
        add("")
        add("Grouped by the padding the case's width requires. A case that needs no")
        add("padding is unaffected, which is the control group.")
        add("")
        add("| Padding | Images | Pixels wrong, mean | Min | Max | Colours invented, mean |")
        add("| --- | --- | --- | --- | --- | --- |")
        for pad, data in aggregate["byPaddingClass"].items():
            share = data["differingShare"]
            invented = data["coloursInvented"]
            add(
                f"| {pad} | {share['files']} | {share['mean']:.2%} | {share['min']:.2%} | "
                f"{share['max']:.2%} | {invented['mean']:.2f} |"
            )
        add("")
        checks = aggregate["byteIdentityChecks"]
        add(
            f"On all {checks['filesChecked']} of those images, the bytes the stride-blind "
            f"reader consumes are a prefix of the file's pixel region "
            f"({checks['prefixHolds']} of {checks['filesChecked']}) and every padding byte "
            f"is zero ({checks['allPaddingZero']} of {checks['filesChecked']})."
        )
        add("")
    add("## Fixture check")
    add("")
    add(
        f"Four BMPs built by this script, each {fixture['height']} rows tall with one "
        "flat colour per row and containing no imagery. The four widths cover the four "
        "padding classes, which is what shows why some cases look perfectly fine."
    )
    add("")
    add("| Width | Padding | Stride | Conformant bytes | Unpadded bytes | `bfSize` UC1 "
        "would declare | Pixels wrong when read stride-blind | Colours invented |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in fixture["cases"]:
        add(
            f"| {entry['width']} | {entry['padding']} | {entry['stride']} | "
            f"{entry['conformantBytes']} | {entry['unpaddedBytes']} | "
            f"{entry['bfSizeTheUc1WritersWouldDeclare']} | "
            f"{entry['differingPixels']} of {entry['totalPixels']} | "
            f"{len(entry['coloursOnlyInBlindReading'])} |"
        )
    add("")
    for entry in fixture["cases"]:
        add(f"### Fixture, width {entry['width']}, padding {entry['padding']}")
        add("")
        add(f"- Rows read correctly, top first: {entry['correctRowColours']}.")
        add(f"- Same rows read stride-blind: {entry['blindTopLeftColours']}.")
        if entry["coloursOnlyInBlindReading"]:
            add(f"- Colours that exist only in the stride-blind reading: "
                f"{entry['coloursOnlyInBlindReading']}.")
        add("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"UC1 output tree to inspect (default {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--case-root",
        type=Path,
        default=DEFAULT_CASE_ROOT,
        help=(
            "tree searched for recorded cases and their ENVI headers "
            f"(default {DEFAULT_CASE_ROOT})"
        ),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("informe-uc1-bmp"),
        help="where the report, the JSON and the PNGs are written",
    )
    parser.add_argument(
        "--sample-case",
        default="017-01",
        help="case to work through image by image, with PNGs (default 017-01)",
    )
    parser.add_argument(
        "--case-images",
        nargs="*",
        default=[
            "007-01:imageRGB.bmp",
            "007-01:svm.bmp",
            "017-01:imageRGB.bmp",
            "017-01:svm.bmp",
            "017-01:kmeans.bmp",
            "017-01:CalibratedImage_BIP.bmp",
            "034-02:svm.bmp",
            "034-02:kmeans.bmp",
        ],
        metavar="CASE:FILE",
        help="real outputs to render as comparison PNGs; pass with no values to skip",
    )
    parser.add_argument(
        "--no-aggregate",
        action="store_true",
        help="skip decoding every displayed output twice, which is the slow part",
    )
    args = parser.parse_args(argv)

    output_root: Path = args.output_root
    if not output_root.is_dir():
        print(f"No UC1 output tree at {output_root}", file=sys.stderr)
        return 2

    report_dir: Path = args.report_dir
    images_dir = report_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    cases = recorded_cases(args.case_root)
    if not cases:
        print(f"No recorded cases with an ENVI header under {args.case_root}", file=sys.stderr)
        return 2

    all_facts = scan(output_root, cases)
    if not all_facts:
        print(f"No UC1 BMPs for any recorded case under {output_root}", file=sys.stderr)
        return 2
    summary = summarise(all_facts)
    summary["recordedCasesFound"] = len(cases)
    summary["casesWithNoOutputAtAll"] = len(cases) - summary["casesInspected"]
    summary["displayedOutputSlots"] = summary["casesInspected"] * len(DISPLAYED_OUTPUTS)

    sample: dict | None = None
    sample_dir = output_root / args.sample_case
    if sample_dir.is_dir():
        rows = []
        for facts in (f for f in all_facts if f.path.parent.name == args.sample_case):
            row = {
                "file": facts.path.name,
                "writer": PRODUCING_WRITER.get(facts.path.name, "unknown"),
                "verdict": facts.verdict,
                "width": facts.width,
                "height": facts.height,
                "padding": facts.padding,
                "stride": facts.stride,
                "declaredBfSize": facts.declared_bfsize,
                "declaredBiSizeImage": facts.declared_bisizeimage,
                "physicalBytes": facts.physical_bytes,
                "conformantBytes": conformant_size(facts.width, facts.height),
                "bfSizeError": facts.bfsize_error,
                "missingBytes": facts.missing_bytes,
                "note": facts.note,
            }
            if facts.verdict in (CONFORMANT, UNDERSTATED_BFSIZE):
                correct, blind = decode_both(facts)
                divergence = measure_divergence(correct, blind)
                row["divergence"] = {
                    "differingPixels": divergence.differing_pixels,
                    "totalPixels": divergence.total_pixels,
                    "differingShare": divergence.differing_share,
                    "firstBadRowFromBottom": divergence.first_bad_row_from_bottom,
                    "colourCountCorrect": divergence.colour_count_correct,
                    "colourCountBlind": divergence.colour_count_blind,
                    "coloursOnlyInBlindReading": [
                        list(c) for c in divergence.colours_only_in_blind
                    ],
                }
                row["byteIdentity"] = byte_identity_check(facts)
                if facts.padding:
                    row["verticalProfile"] = vertical_profile(facts)
                stem = f"{facts.path.parent.name}-{facts.path.stem}"
                write_png(images_dir / f"{stem}-correct.png", correct)
                write_png(images_dir / f"{stem}-naive.png", blind)
                write_png(images_dir / f"{stem}-diff.png", difference_mask(correct, blind))
            rows.append(row)
        sample = {"case": args.sample_case, "files": rows}

    case_panels = []
    for spec in args.case_images:
        case_name, _, file_name = spec.partition(":")
        path = output_root / case_name / file_name
        if not path.is_file():
            print(f"Skipping {spec}: no such output", file=sys.stderr)
            continue
        facts = read_bmp_facts(path)
        if facts.verdict == UNREADABLE:
            print(f"Skipping {spec}: {facts.note}", file=sys.stderr)
            continue
        samples, lines = cases.get(case_name, (0, 0))
        facts.case_samples, facts.case_lines = samples, lines
        case_panels.append(render_case_panels(facts, images_dir))

    fixture = fixture_demonstration(images_dir)
    aggregate = None if args.no_aggregate else aggregate_divergence(all_facts)

    payload = {
        "outputRoot": str(output_root),
        "summary": summary,
        "sample": sample,
        "casePanels": case_panels,
        "aggregate": aggregate,
        "fixture": fixture,
        "verdictMeaning": VERDICT_MEANING,
        "producingWriter": PRODUCING_WRITER,
        "files": [
            {
                "case": f.path.parent.name,
                "file": f.path.name,
                "verdict": f.verdict,
                "width": f.width,
                "height": f.height,
                "padding": f.padding,
                "declaredBfSize": f.declared_bfsize,
                "declaredBiSizeImage": f.declared_bisizeimage,
                "physicalBytes": f.physical_bytes,
                "conformantBytes": conformant_size(f.width, f.height) if f.width else 0,
                "bfSizeError": f.bfsize_error,
                "missingBytes": f.missing_bytes if f.width else 0,
                "note": f.note,
            }
            for f in all_facts
        ],
    }

    (report_dir / "uc1-bmp-report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    report = markdown_report(output_root, all_facts, summary, sample, fixture, aggregate)
    (report_dir / "uc1-bmp-report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"JSON:   {report_dir / 'uc1-bmp-report.json'}")
    print(f"Report: {report_dir / 'uc1-bmp-report.md'}")
    print(f"Images: {images_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
