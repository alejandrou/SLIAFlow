"""Synthetic hyperspectral scene synthesis and UC1's calibration arithmetic.

The scene only has to be non-degenerate, not realistic. What has to be exact is
the calibration relationship: UC1 computes `100 * (raw - dark) / (white - dark)`
on the GPU, so this module generates the references first and inverts that
formula to obtain `raw`, rather than generating `raw` and hoping.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy

# Read from `VNIRwhiteReferenceUHDrN.hdr`: the real Headwall grid runs from
# 400.482 nm to 1000.73 nm. 93 bands over that span is a step of 6.5244 nm.
SENSOR_FIRST_WAVELENGTH_NM = 400.482
SENSOR_LAST_WAVELENGTH_NM = 1000.73
DEFAULT_BAND_COUNT = 93

# Gaussian response curves standing in for the camera's colour channels.
BLUE_CENTRE_NM, BLUE_WIDTH_NM = 470.0, 45.0
GREEN_CENTRE_NM, GREEN_WIDTH_NM = 540.0, 45.0
RED_CENTRE_NM, RED_WIDTH_NM = 620.0, 55.0

# A broad envelope over the near infrared, driven by scene luminance.
NEAR_INFRARED_START_NM = 700.0
NEAR_INFRARED_END_NM = 1000.0
NEAR_INFRARED_GAIN = 0.6

# Narrow features at distinct centres, each carrying its own spatial weight.
TEXTURE_FIRST_CENTRE_NM = 435.0
TEXTURE_LAST_CENTRE_NM = 975.0
TEXTURE_WIDTH_NM = 12.0
TEXTURE_GAIN = 0.15
DEFAULT_TEXTURE_FEATURE_COUNT = 6

# The three channel Gaussians are driven by the B, G and R planes. The infrared
# envelope is driven by luminance, and luminance is a fixed linear combination
# of those three planes, so the envelope adds a curve but no new direction: the
# channel-only scene has a band covariance of rank 3, not 4. Each texture
# feature carries an independently generated weight map, so each one does add a
# direction. The floor below therefore sits above anything the channel basis
# alone can reach, which is what makes the rank check non-vacuous.
CHANNEL_BASIS_RANK = 3
MINIMUM_SPECTRAL_RANK = 8

# Singular values below this fraction of the largest one are not scene
# structure. The threshold is measured, not chosen for comfort: rounding `raw`
# to uint16 lifts every direction of the calibrated cube's band covariance to
# about 8e-11 of the largest singular value, so `matrix_rank` at its default
# tolerance reports full rank - 93 - for any scene at all, including one mixed
# from three curves. The smallest genuine direction measured here sits at
# 5.45e-6. A threshold of 1e-8 leaves roughly three orders of margin on each
# side of that gap.
SIGNIFICANT_VARIANCE_RELATIVE_TOLERANCE = 1e-8

# Rec.601 luma weights, in the B, G, R order the frames arrive in.
LUMINANCE_WEIGHTS_BGR = (0.114, 0.587, 0.299)

# Peak reflectance of the synthesised scene, as a fraction. Staying below 1.0
# keeps `raw` comfortably inside the uint16 range after the calibration
# inversion, and keeps the calibrated percentage inside 0 to 100.
PEAK_REFLECTANCE = 0.9

# Reference levels in sensor counts. The white-minus-dark span is large so that
# rounding `raw` to uint16 costs far less than the round-trip tolerance, and it
# is strictly positive everywhere so UC1's `white != 0` guard never fires.
DARK_BASE_COUNTS = 1200
DARK_JITTER_COUNTS = 60
WHITE_MINUS_DARK_COUNTS = 50000
WHITE_SPAN_JITTER_COUNTS = 1500

UINT16_MAXIMUM = 65535


@dataclass(frozen=True)
class SpectralRankReport:
    """What `numpy.linalg.matrix_rank` measured on a cube's band covariance."""

    rank: int
    conditionNumber: float
    largestSingularValue: float
    smallestRetainedSingularValue: float


def bandWavelengthsNm(bandCount: int = DEFAULT_BAND_COUNT) -> numpy.ndarray:
    """Return the band centre wavelengths, linearly spaced over the sensor range."""
    if bandCount < 2:
        raise ValueError(f"bandCount must be at least 2, not {bandCount}.")
    return numpy.linspace(
        SENSOR_FIRST_WAVELENGTH_NM, SENSOR_LAST_WAVELENGTH_NM, bandCount, dtype=numpy.float64
    )


def _gaussian(wavelengthsNm: numpy.ndarray, centreNm: float, widthNm: float) -> numpy.ndarray:
    return numpy.exp(-0.5 * ((wavelengthsNm - centreNm) / widthNm) ** 2)


def channelResponseCurves(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Return the (3, bands) blue, green and red response curves, in BGR order."""
    return numpy.stack(
        [
            _gaussian(wavelengthsNm, BLUE_CENTRE_NM, BLUE_WIDTH_NM),
            _gaussian(wavelengthsNm, GREEN_CENTRE_NM, GREEN_WIDTH_NM),
            _gaussian(wavelengthsNm, RED_CENTRE_NM, RED_WIDTH_NM),
        ]
    ).astype(numpy.float32)


def nearInfraredEnvelope(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Return a smooth (bands,) envelope rising across the near infrared."""
    span = NEAR_INFRARED_END_NM - NEAR_INFRARED_START_NM
    progress = numpy.clip((wavelengthsNm - NEAR_INFRARED_START_NM) / span, 0.0, 1.0)
    return (0.5 * (1.0 - numpy.cos(numpy.pi * progress))).astype(numpy.float32)


def textureFeatureCurves(wavelengthsNm: numpy.ndarray, featureCount: int) -> numpy.ndarray:
    """Return (featureCount, bands) narrow features at distinct band centres."""
    if featureCount <= 0:
        return numpy.zeros((0, wavelengthsNm.size), dtype=numpy.float32)

    centresNm = numpy.linspace(TEXTURE_FIRST_CENTRE_NM, TEXTURE_LAST_CENTRE_NM, featureCount)
    return numpy.stack(
        [_gaussian(wavelengthsNm, float(centreNm), TEXTURE_WIDTH_NM) for centreNm in centresNm]
    ).astype(numpy.float32)


def textureWeightMaps(
    rng: numpy.random.Generator, featureCount: int, lines: int, samples: int
) -> numpy.ndarray:
    """Return (featureCount, lines, samples) weights independent of the frame.

    Each map is a product of two sinusoids at randomly drawn spatial
    frequencies and phases. Distinct frequencies make the maps linearly
    independent, which is what turns each texture curve into a new direction in
    the band covariance rather than a rescaling of an existing one.
    """
    if featureCount <= 0:
        return numpy.zeros((0, lines, samples), dtype=numpy.float32)

    x = numpy.linspace(0.0, 1.0, samples, dtype=numpy.float32)[None, :]
    y = numpy.linspace(0.0, 1.0, lines, dtype=numpy.float32)[:, None]

    maps = numpy.empty((featureCount, lines, samples), dtype=numpy.float32)
    for featureIndex in range(featureCount):
        frequencyX, frequencyY = rng.uniform(0.7, 3.1, size=2)
        phaseX, phaseY = rng.uniform(0.0, 2.0 * numpy.pi, size=2)
        field = numpy.sin(2.0 * numpy.pi * frequencyX * x + phaseX) * numpy.sin(
            2.0 * numpy.pi * frequencyY * y + phaseY
        )
        maps[featureIndex] = 0.5 * (field + 1.0)
    return maps


def reflectanceCube(
    frameBgr: numpy.ndarray,
    wavelengthsNm: numpy.ndarray,
    textureFeatureCount: int = DEFAULT_TEXTURE_FEATURE_COUNT,
    rng: numpy.random.Generator | None = None,
) -> numpy.ndarray:
    """Build a (bands, lines, samples) reflectance cube from one BGR frame.

    The array is C-order, so `.tobytes()` is already BSQ: the BSQ index UC1 uses
    is `band * totalPixels + line * samples + sample`.
    """
    if frameBgr.ndim != 3 or frameBgr.shape[2] != 3:
        raise ValueError(f"Expected an (lines, samples, 3) BGR frame, got {frameBgr.shape}.")

    generator = rng if rng is not None else numpy.random.default_rng()
    lines, samples, _ = frameBgr.shape

    channelWeights = (frameBgr.astype(numpy.float32) / 255.0).transpose(2, 0, 1)
    luminance = numpy.tensordot(
        numpy.asarray(LUMINANCE_WEIGHTS_BGR, dtype=numpy.float32), channelWeights, axes=1
    )

    reflectance = numpy.einsum(
        "cb,cij->bij", channelResponseCurves(wavelengthsNm), channelWeights, optimize=True
    )
    reflectance += NEAR_INFRARED_GAIN * numpy.einsum(
        "b,ij->bij", nearInfraredEnvelope(wavelengthsNm), luminance, optimize=True
    )

    if textureFeatureCount > 0:
        reflectance += TEXTURE_GAIN * numpy.einsum(
            "fb,fij->bij",
            textureFeatureCurves(wavelengthsNm, textureFeatureCount),
            textureWeightMaps(generator, textureFeatureCount, lines, samples),
            optimize=True,
        )

    peak = float(reflectance.max())
    if peak <= 0.0:
        raise ValueError("The synthesised scene is empty; every band is zero everywhere.")
    return (reflectance * (PEAK_REFLECTANCE / peak)).astype(numpy.float32)


def referenceCubes(
    rng: numpy.random.Generator, bands: int, lines: int, samples: int
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return (dark, white) full reference cubes with `white > dark` everywhere.

    Both references are full cubes, not single frames, because that is what UC1
    reads: one dataset is three times the cube size.
    """
    shape = (bands, lines, samples)
    darkCube = (DARK_BASE_COUNTS + rng.integers(0, DARK_JITTER_COUNTS + 1, size=shape)).astype(
        numpy.uint16
    )
    span = WHITE_MINUS_DARK_COUNTS + rng.integers(0, WHITE_SPAN_JITTER_COUNTS + 1, size=shape)
    whiteCube = (darkCube.astype(numpy.int64) + span).astype(numpy.uint16)
    return darkCube, whiteCube


def rawFromReflectance(
    reflectance: numpy.ndarray,
    darkCube: numpy.ndarray,
    whiteCube: numpy.ndarray,
    noiseCounts: int = 0,
    rng: numpy.random.Generator | None = None,
) -> numpy.ndarray:
    """Invert UC1's calibration to obtain the raw counts it will read back.

    `noiseCounts` defaults to 0 so the round trip is exact. The spectral rank of
    the scene is achieved through the basis, never through noise, so the default
    can stay at zero.
    """
    span = whiteCube.astype(numpy.float64) - darkCube.astype(numpy.float64)
    raw = darkCube.astype(numpy.float64) + reflectance.astype(numpy.float64) * span

    if noiseCounts > 0:
        generator = rng if rng is not None else numpy.random.default_rng()
        raw = raw + generator.normal(0.0, float(noiseCounts), size=raw.shape)

    return numpy.rint(numpy.clip(raw, 0.0, UINT16_MAXIMUM)).astype(numpy.uint16)


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


def spectralRankReport(
    calibratedCube: numpy.ndarray,
    relativeTolerance: float = SIGNIFICANT_VARIANCE_RELATIVE_TOLERANCE,
) -> SpectralRankReport:
    """Measure the numerical rank of a cube's band covariance.

    The tolerance is scaled to the largest singular value rather than left at
    `matrix_rank`'s default, for the reason recorded on
    `SIGNIFICANT_VARIANCE_RELATIVE_TOLERANCE`: uint16 quantization alone makes
    the default report full rank for every scene.

    The condition number reported is taken over the retained subspace
    (largest divided by smallest retained singular value). The condition number
    of the full band covariance is not a useful number here: the covariance of a
    93-band cube spanned by a handful of curves is singular by construction, so
    that figure would describe the padding rather than the scene.
    """
    bands = calibratedCube.shape[0]
    flattened = calibratedCube.reshape(bands, -1).astype(numpy.float64)
    covariance = numpy.cov(flattened)

    singularValues = numpy.linalg.svd(covariance, compute_uv=False)
    rank = int(numpy.linalg.matrix_rank(covariance, tol=relativeTolerance * singularValues[0]))

    largest = float(singularValues[0])
    smallestRetained = float(singularValues[max(rank - 1, 0)])
    conditionNumber = largest / smallestRetained if smallestRetained > 0.0 else float("inf")

    return SpectralRankReport(
        rank=rank,
        conditionNumber=conditionNumber,
        largestSingularValue=largest,
        smallestRetainedSingularValue=smallestRetained,
    )
