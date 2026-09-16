"""UC1's calibration arithmetic, re-implemented for the colour background.

UC1 computes `100 * (raw - dark) / (white - dark)` on the GPU and never hands
the calibrated cube back. `UC1_RGB` needs three calibrated bands of the same
cube, so the formula is restated here, guard included, rather than approximated.
"""

from __future__ import annotations

import numpy


def calibrate(
    rawCube: numpy.ndarray, darkCube: numpy.ndarray, whiteCube: numpy.ndarray
) -> numpy.ndarray:
    """Re-implement UC1's calibration, guard included.

    `functions_cuda.cu` computes `100 * (raw - dark) / (white - dark)` and
    substitutes 0 when the denominator is zero.
    """
    span = whiteCube.astype(numpy.float32) - darkCube.astype(numpy.float32)
    numerator = 100.0 * (rawCube.astype(numpy.float32) - darkCube.astype(numpy.float32))
    safeSpan = numpy.where(span != 0.0, span, 1.0)
    return numpy.where(span != 0.0, numerator / safeSpan, 0.0).astype(numpy.float32)
