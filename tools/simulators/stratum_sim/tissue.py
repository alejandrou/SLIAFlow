"""A synthetic optical phantom whose spectra are shaped like brain reflectance.

This module exists because of a measured failure. The channel-driven scene in
`spectra.py` is spectrally rich - band covariance rank 9 - but its spectra are
built from camera colour curves, and UC1's linear SVM, trained on real in-vivo
brain reflectance, resolved every pixel of it to class 4, background. UC1
min-max normalizes each pixel across bands before the SVM, so only spectral
*shape* reaches the classifier. A scene whose shape is a mixture of three
Gaussians is not a shape that model has ever been asked about.

So the shape is built from tissue optics instead: haemoglobin absorption, a
scattering power law, and the diffusion-approximation reflectance of a
semi-infinite turbid medium. Vary the blood volume fraction, the oxygen
saturation and the scattering, and the spectra move the way tissue spectra
move.

**What this is not.** It is not patient data, not derived from patient data,
and not a tumour. The regions are drawn geometrically and their optical
parameters are chosen from published ranges; a region called "tumour" here is a
region where the blood volume fraction was set high and the saturation low,
nothing more. `regionMap` is a record of how the phantom was *built*, never a
ground truth for what the classifier ought to say. When UC1 disagrees with it -
and it does - the disagreement is reported, not corrected.

**What was deliberately not done.** The optical parameters were never fitted to
the classifier. The absorption model is chosen from the chromophores and the
region parameters from physiology; the shipped SVM weights were used only to
*characterise* the result afterwards, never as an optimisation target. Fitting
an input to a trained model's weights produces an adversarial example, which
would look like a working detector and mean less than nothing.

Sources: the chromophore band positions are the standard oxy- and
deoxyhaemoglobin features (Soret near 415 and 430 nm, the oxy alpha/beta pair
at 542 and 576 nm, the deoxy peak near 556 nm and its NIR peak near 758 nm,
the isosbestic crossing near 800 nm) and the water band near 975 nm. The band
amplitudes and widths here are analytic approximations at those positions, not
a transcribed extinction table: they reproduce the features, and they must not
be used for quantitative oximetry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy

from . import spectra

REGION_MAP_FILE_NAME = "phantom_regions.npy"
REGION_LEGEND_FILE_NAME = "phantom_regions.json"

# --- Chromophore absorption -------------------------------------------------
#
# Each entry is (centre nm, width nm, peak amplitude). Amplitudes for the two
# haemoglobins are decadic molar extinction coefficients in cm^-1/M; water is
# already an absorption coefficient in cm^-1 for pure water.

OXYHAEMOGLOBIN_BANDS = (
    (415.0, 12.0, 5.0e5),  # Soret
    (542.0, 14.0, 5.0e4),  # alpha
    (576.0, 13.0, 5.5e4),  # beta
    (900.0, 180.0, 1.1e3),  # the broad NIR rise past the isosbestic point
)
OXYHAEMOGLOBIN_FLOOR = 2.0e2

DEOXYHAEMOGLOBIN_BANDS = (
    (430.0, 14.0, 3.4e5),  # Soret, red-shifted relative to oxy
    (556.0, 26.0, 5.3e4),  # the single broad visible peak
    (650.0, 45.0, 3.5e3),  # the red shoulder that makes deoxygenated blood dark
    (758.0, 55.0, 1.6e3),  # the NIR deoxy peak
)
DEOXYHAEMOGLOBIN_FLOOR = 3.0e2

WATER_BANDS = ((975.0, 25.0, 0.45), (840.0, 30.0, 0.02))
WATER_FLOOR = 0.002

# 150 g/L of haemoglobin at 64500 g/mol.
WHOLE_BLOOD_HAEMOGLOBIN_MOLARITY = 2.33e-3

# Extinction coefficients are decadic; absorption coefficients are neperian.
NEPERIAN_PER_DECADIC = 2.303

# --- Scattering and reflectance ---------------------------------------------

SCATTERING_REFERENCE_NM = 500.0

# The internal-reflection parameter of the diffusion-approximation reflectance
# for a semi-infinite medium. 1.44 corresponds to a tissue-air boundary at
# refractive index 1.4; 1.0 would be an index-matched boundary.
INTERNAL_REFLECTION_PARAMETER = 1.44

# --- Region definitions -----------------------------------------------------

REGION_CORTEX = 1
REGION_TUMOUR = 2
REGION_VESSEL = 3
REGION_DRAPE = 4
REGION_VALUES = (REGION_CORTEX, REGION_TUMOUR, REGION_VESSEL, REGION_DRAPE)

REGION_NAMES = {
    REGION_CORTEX: "cortex",
    REGION_TUMOUR: "tumour-like",
    REGION_VESSEL: "vessel",
    REGION_DRAPE: "drape",
}


@dataclass(frozen=True)
class TissueOptics:
    """The optical parameters of one region of the phantom.

    Every field is a physical quantity with a physiological range, which is the
    point: the phantom is specified in the units tissue is measured in, so a
    reader can judge whether a region is plausible without reading any code.
    """

    bloodVolumeFraction: float
    oxygenSaturation: float
    waterFraction: float
    scatteringAmplitude: float  # reduced scattering at 500 nm, cm^-1
    scatteringPower: float  # the exponent b in a * (lambda / 500)^-b


# Parameters for exposed cortex under a surgical microscope, chosen from
# published ranges rather than fitted to anything. Cortex carries a few percent
# blood at high saturation; a tumour region carries more blood at lower
# saturation and scatters less; a surface vessel is mostly blood.
REGION_OPTICS: dict[int, TissueOptics] = {
    REGION_CORTEX: TissueOptics(0.030, 0.75, 0.75, 22.0, 1.3),
    REGION_TUMOUR: TissueOptics(0.060, 0.60, 0.80, 16.0, 1.0),
    REGION_VESSEL: TissueOptics(0.250, 0.85, 0.85, 15.0, 1.0),
}

# The drape is not tissue and is not modelled as tissue. A matte green surgical
# drape is a dyed fabric: a broad reflectance band around 530 nm over a low
# floor, with the gentle rise into the near infrared that woven synthetics
# have. Running the turbid-medium model at a near-zero blood volume would be
# the wrong physics for it and would produce a spectrum shaped like bloodless
# tissue, which is not what lies around a craniotomy.
DRAPE_FLOOR_REFLECTANCE = 0.06
DRAPE_BAND_CENTRE_NM = 530.0
DRAPE_BAND_WIDTH_NM = 70.0
DRAPE_BAND_REFLECTANCE = 0.28
DRAPE_NEAR_INFRARED_RISE = 0.35
DRAPE_RISE_START_NM = 600.0
DRAPE_RISE_END_NM = 1000.0

# Smooth within-region modulation, as a fraction of each nominal parameter.
# Without it every pixel of a region would carry the identical spectrum, the
# band covariance would collapse to one direction per region, and K-means would
# have nothing to cluster. Blood volume varies most, which is also true of real
# cortex.
BLOOD_MODULATION_DEPTH = 0.35
SATURATION_MODULATION_DEPTH = 0.12
SCATTERING_MODULATION_DEPTH = 0.20
MINIMUM_OXYGEN_SATURATION = 0.05

# Scene geometry, in fractions of the frame. The craniotomy field is an ellipse
# on the drape; the tumour-like region and the vessels lie inside it.
FIELD_CENTRE = (0.50, 0.50)
FIELD_RADII = (0.40, 0.42)
TUMOUR_CENTRE = (0.36, 0.58)
TUMOUR_RADII = (0.15, 0.17)
VESSEL_TRACKS = (
    # (phase, amplitude, half width, offset, slope)
    (0.7, 0.10, 0.022, 0.30, 0.16),
    (2.4, 0.07, 0.016, 0.55, -0.10),
    (4.1, 0.12, 0.018, 0.74, 0.08),
)
VESSEL_WAVE_NUMBER = 6.0

# Peak reflectance the rendered BGR frame is scaled to, so the LiveView pane
# uses its range without clipping the brightest region to pure white.
FRAME_PEAK_LEVEL = 235.0


def _bandSum(wavelengthsNm: numpy.ndarray, bands, floor: float) -> numpy.ndarray:
    total = numpy.full(wavelengthsNm.shape, float(floor), dtype=numpy.float64)
    for centreNm, widthNm, amplitude in bands:
        total += amplitude * numpy.exp(-0.5 * ((wavelengthsNm - centreNm) / widthNm) ** 2)
    return total


def oxyhaemoglobinExtinction(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Decadic molar extinction of HbO2, cm^-1/M, as an analytic approximation."""
    return _bandSum(wavelengthsNm, OXYHAEMOGLOBIN_BANDS, OXYHAEMOGLOBIN_FLOOR)


def deoxyhaemoglobinExtinction(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Decadic molar extinction of Hb, cm^-1/M, as an analytic approximation."""
    return _bandSum(wavelengthsNm, DEOXYHAEMOGLOBIN_BANDS, DEOXYHAEMOGLOBIN_FLOOR)


def waterAbsorption(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Absorption coefficient of pure water, cm^-1."""
    return _bandSum(wavelengthsNm, WATER_BANDS, WATER_FLOOR)


def absorptionCoefficient(
    wavelengthsNm: numpy.ndarray,
    bloodVolumeFraction: numpy.ndarray | float,
    oxygenSaturation: numpy.ndarray | float,
    waterFraction: numpy.ndarray | float,
) -> numpy.ndarray:
    """Return mu_a in cm^-1, broadcasting the parameters against the bands.

    Parameters may be scalars or arrays of any shape; the result is
    `(*parameterShape, bands)`.
    """
    blood = numpy.asarray(bloodVolumeFraction, dtype=numpy.float64)[..., None]
    saturation = numpy.asarray(oxygenSaturation, dtype=numpy.float64)[..., None]
    water = numpy.asarray(waterFraction, dtype=numpy.float64)[..., None]

    extinction = saturation * oxyhaemoglobinExtinction(wavelengthsNm) + (
        1.0 - saturation
    ) * deoxyhaemoglobinExtinction(wavelengthsNm)

    fromBlood = NEPERIAN_PER_DECADIC * extinction * blood * WHOLE_BLOOD_HAEMOGLOBIN_MOLARITY
    return fromBlood + water * waterAbsorption(wavelengthsNm)


def reducedScatteringCoefficient(
    wavelengthsNm: numpy.ndarray,
    scatteringAmplitude: numpy.ndarray | float,
    scatteringPower: numpy.ndarray | float,
) -> numpy.ndarray:
    """Return mu_s' in cm^-1 as `amplitude * (lambda / 500 nm)^-power`."""
    amplitude = numpy.asarray(scatteringAmplitude, dtype=numpy.float64)[..., None]
    power = numpy.asarray(scatteringPower, dtype=numpy.float64)[..., None]
    return amplitude * (wavelengthsNm / SCATTERING_REFERENCE_NM) ** (-power)


def diffuseReflectance(
    absorption: numpy.ndarray,
    reducedScattering: numpy.ndarray,
    internalReflection: float = INTERNAL_REFLECTION_PARAMETER,
) -> numpy.ndarray:
    """Diffusion-approximation reflectance of a semi-infinite turbid medium.

    A function of the transport albedo alone,
    `R = a' / (1 + 2k(1 - a') + (1 + 2k/3) * sqrt(3(1 - a')))`, which is
    monotone in the albedo and bounded in (0, 1). It is a coarse model - no
    layering, no boundary geometry, no source-detector separation - and it is
    used here for the one property that matters: it turns chromophore
    absorption into a reflectance shape the right way round.
    """
    albedo = reducedScattering / (reducedScattering + absorption)
    oneMinus = 1.0 - albedo
    k = float(internalReflection)
    denominator = 1.0 + 2.0 * k * oneMinus + (1.0 + 2.0 * k / 3.0) * numpy.sqrt(3.0 * oneMinus)
    return albedo / denominator


def tissueReflectance(
    wavelengthsNm: numpy.ndarray,
    bloodVolumeFraction: numpy.ndarray | float,
    oxygenSaturation: numpy.ndarray | float,
    waterFraction: numpy.ndarray | float,
    scatteringAmplitude: numpy.ndarray | float,
    scatteringPower: numpy.ndarray | float,
) -> numpy.ndarray:
    """Reflectance of a turbid tissue-like medium, shaped `(*parameters, bands)`."""
    absorption = absorptionCoefficient(
        wavelengthsNm, bloodVolumeFraction, oxygenSaturation, waterFraction
    )
    scattering = reducedScatteringCoefficient(
        wavelengthsNm, scatteringAmplitude, scatteringPower
    )
    return diffuseReflectance(absorption, scattering)


def drapeReflectance(wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Reflectance of the matte green surgical drape, shaped `(bands,)`."""
    band = DRAPE_BAND_REFLECTANCE * numpy.exp(
        -0.5 * ((wavelengthsNm - DRAPE_BAND_CENTRE_NM) / DRAPE_BAND_WIDTH_NM) ** 2
    )
    rise = numpy.clip(
        (wavelengthsNm - DRAPE_RISE_START_NM) / (DRAPE_RISE_END_NM - DRAPE_RISE_START_NM), 0.0, 1.0
    )
    return DRAPE_FLOOR_REFLECTANCE + band + DRAPE_NEAR_INFRARED_RISE * rise


def phantomRegionMap(lines: int, samples: int) -> numpy.ndarray:
    """Return the `(lines, samples)` uint8 map of how the phantom was built.

    This is a construction record, not a label set the classifier is graded
    against. The regions are drawn as an elliptical craniotomy field on drape,
    with a tumour-like blob and three vessel tracks inside the field. The
    tracks are painted last and cut the labels beneath them, so a label is
    several coherent areas rather than one; what matters is that they are areas
    at all, because a map made of areas can be told apart from noise by eye.
    `docs/development/synthetic_tissue_phantom.md` states the geometry and what
    is asserted of it.
    """
    if lines < 1 or samples < 1:
        raise ValueError(f"A phantom needs a positive size, not {lines}x{samples}.")

    x = numpy.linspace(0.0, 1.0, samples, dtype=numpy.float64)[None, :]
    y = numpy.linspace(0.0, 1.0, lines, dtype=numpy.float64)[:, None]

    def ellipse(centre, radii):
        return ((x - centre[0]) / radii[0]) ** 2 + ((y - centre[1]) / radii[1]) ** 2 <= 1.0

    regionMap = numpy.full((lines, samples), REGION_DRAPE, dtype=numpy.uint8)
    field = numpy.broadcast_to(ellipse(FIELD_CENTRE, FIELD_RADII), regionMap.shape)
    regionMap[field] = REGION_CORTEX

    tumour = numpy.broadcast_to(ellipse(TUMOUR_CENTRE, TUMOUR_RADII), regionMap.shape) & field
    regionMap[tumour] = REGION_TUMOUR

    for phase, amplitude, halfWidth, offset, slope in VESSEL_TRACKS:
        track = offset + amplitude * numpy.sin(VESSEL_WAVE_NUMBER * x + phase) + slope * x
        ridge = numpy.broadcast_to(numpy.abs(y - track) < halfWidth, regionMap.shape) & field
        regionMap[ridge] = REGION_VESSEL

    return regionMap


def _modulationField(
    lines: int, samples: int, depth: float, frequencies: tuple[float, float],
    phases: tuple[float, float]
) -> numpy.ndarray:
    """A smooth multiplicative field of mean 1, varying by `depth` either way."""
    x = numpy.linspace(0.0, 1.0, samples, dtype=numpy.float64)[None, :]
    y = numpy.linspace(0.0, 1.0, lines, dtype=numpy.float64)[:, None]
    field = numpy.sin(frequencies[0] * numpy.pi * x + phases[0]) * numpy.sin(
        frequencies[1] * numpy.pi * y + phases[1]
    )
    return numpy.broadcast_to(1.0 + depth * field, (lines, samples))


def phantomReflectanceCube(
    regionMap: numpy.ndarray, wavelengthsNm: numpy.ndarray
) -> numpy.ndarray:
    """Build the `(bands, lines, samples)` float32 reflectance cube for a region map.

    Within-region parameters are modulated by smooth fields, so each region
    spans a range of blood volumes, saturations and scattering strengths rather
    than repeating one spectrum. That is what gives the cube a band covariance
    of more than one direction per region, and it is measured by the caller
    rather than assumed here.
    """
    lines, samples = regionMap.shape
    bloodField = _modulationField(lines, samples, BLOOD_MODULATION_DEPTH, (4.1, 3.3), (0.7, 1.9))
    saturationField = _modulationField(
        lines, samples, SATURATION_MODULATION_DEPTH, (2.7, 5.1), (2.2, 0.4)
    )
    scatteringField = _modulationField(
        lines, samples, SCATTERING_MODULATION_DEPTH, (3.9, 2.3), (1.1, 3.0)
    )

    cube = numpy.zeros((wavelengthsNm.size, lines, samples), dtype=numpy.float32)

    for regionValue, optics in REGION_OPTICS.items():
        selected = regionMap == regionValue
        if not selected.any():
            continue
        reflectance = tissueReflectance(
            wavelengthsNm,
            optics.bloodVolumeFraction * bloodField[selected],
            numpy.clip(
                optics.oxygenSaturation * saturationField[selected],
                MINIMUM_OXYGEN_SATURATION,
                1.0,
            ),
            optics.waterFraction,
            optics.scatteringAmplitude * scatteringField[selected],
            optics.scatteringPower,
        )
        cube[:, selected] = reflectance.T.astype(numpy.float32)

    drape = regionMap == REGION_DRAPE
    if drape.any():
        cube[:, drape] = drapeReflectance(wavelengthsNm).astype(numpy.float32)[:, None]

    return cube


def renderFrameBgr(reflectanceCube: numpy.ndarray, wavelengthsNm: numpy.ndarray) -> numpy.ndarray:
    """Project the cube through the camera channel curves into a BGR frame.

    The LiveView pane and the dataset then show the same scene, because they
    are the same array: the frame is the cube integrated against the response
    curves `spectra.py` already defines, not a separate picture drawn to look
    similar.
    """
    responses = spectra.channelResponseCurves(wavelengthsNm).astype(numpy.float64)
    responses = responses / responses.sum(axis=1, keepdims=True)
    frame = numpy.einsum("cb,bij->ijc", responses, reflectanceCube.astype(numpy.float64))

    peak = float(frame.max())
    if peak <= 0.0:
        raise ValueError("The rendered phantom frame is black in every channel.")
    return numpy.clip(frame * (FRAME_PEAK_LEVEL / peak), 0.0, 255.0).astype(numpy.uint8)


class PhantomFrameSource:
    """A `FrameSource` that serves the rendered phantom.

    The phantom is a still scene, so every frame is identical. That is the
    trade for LiveView and the dataset being literally the same array; the
    channel scene in `frames.SyntheticFrameSource` is the one that moves.
    """

    def __init__(self, frameBgr: numpy.ndarray) -> None:
        self._frame = frameBgr

    def read(self) -> numpy.ndarray:
        return self._frame


def writePhantomRecord(datasetFolder: Path, regionMap: numpy.ndarray) -> tuple[Path, Path]:
    """Write the region map and its legend beside a dataset, and return both paths.

    Written as two extra files rather than into `raw.hdr`, because UC1's header
    parser reads fixed 128-byte lines and every key it does not know is a line
    it still has to fit. Neither file is read by UC1 or by SLIAFlow: they exist
    so that a person can check what the classifier was shown against how the
    scene was built, without re-deriving it from the code.
    """
    datasetFolder.mkdir(parents=True, exist_ok=True)
    mapPath = datasetFolder / REGION_MAP_FILE_NAME
    legendPath = datasetFolder / REGION_LEGEND_FILE_NAME

    numpy.save(mapPath, regionMap.astype(numpy.uint8))
    legendPath.write_text(json.dumps(regionLegend(), indent=2) + "\n", encoding="utf-8")
    return mapPath, legendPath


def removePhantomRecord(datasetFolder: Path) -> list[Path]:
    """Delete any phantom record in a folder, and return what was removed.

    Called before every dataset write, phantom or not. `--dataset-folder` lets
    one folder be written twice, and the ENVI writer replaces only the four
    files it owns - so a channel dataset written over a phantom would inherit
    the phantom's region map and legend and describe itself with them. Stale
    provenance that looks current is worse than none: the files say which
    regions are tumour-like, and someone would read them.
    """
    removed = []
    for fileName in (REGION_MAP_FILE_NAME, REGION_LEGEND_FILE_NAME):
        path = datasetFolder / fileName
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed


def regionLegend() -> dict[str, object]:
    """The phantom's construction record, for the sidecar written beside a dataset."""
    return {
        "notice": (
            "Synthetic optical phantom. Not patient data, not derived from patient data, "
            "and not a tumour. These regions record how the cube was built; they are not "
            "ground truth for any classifier and no agreement with a classifier's output "
            "is claimed."
        ),
        "regions": {
            str(value): {
                "name": REGION_NAMES[value],
                **(
                    {
                        "bloodVolumeFraction": REGION_OPTICS[value].bloodVolumeFraction,
                        "oxygenSaturation": REGION_OPTICS[value].oxygenSaturation,
                        "waterFraction": REGION_OPTICS[value].waterFraction,
                        "reducedScatteringAt500nmPerCm": REGION_OPTICS[value].scatteringAmplitude,
                        "scatteringPower": REGION_OPTICS[value].scatteringPower,
                    }
                    if value in REGION_OPTICS
                    else {"model": "matte green surgical drape, not a turbid medium"}
                ),
            }
            for value in REGION_VALUES
        },
    }
