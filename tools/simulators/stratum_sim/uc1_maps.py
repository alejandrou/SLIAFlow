"""This is not a classifier. It is a fixed arithmetic rule with hand-chosen constants, written so that a demo pipeline has something to draw. It was not fitted to data, it was never validated, and its output has no diagnostic meaning whatsoever.

The rule exists only to exercise the producer/consumer seam before the genuine
UC1 binary is connected. It deliberately has no learned parameters and makes no
claim about brain tissue or clinical use.
"""

from __future__ import annotations

from typing import Iterable

import numpy

from . import contract

NON_CLASSIFIER_NOTICE = (
    "This is not a classifier. It is a fixed arithmetic rule with hand-chosen "
    "constants, written so that a demo pipeline has something to draw. It was not "
    "fitted to data, it was never validated, and its output has no diagnostic "
    "meaning whatsoever."
)

# All coefficients and biases used by the arithmetic rule live here. They are
# intentionally named as arbitrary constants so a future reader cannot mistake
# them for parameters learned from data.
ARBITRARY_CONSTANTS = {
    "description": "arithmetic stand-in; not a classifier",
    "rednessWeights": (-0.08, 0.16, -0.04, 0.02),
    "luminanceWeights": (0.01, 0.0, 0.015, -0.03),
    "biases": (0.4, -0.8, -0.4, 1.2),
    # `knnProbability` is not a second algorithm. It is this same logit vector
    # divided by this temperature before the same softmax, so the two
    # "probability" maps differ only in how sharply one arithmetic rule is
    # peaked. Naming them after SVM and k-NN mirrors the contract's device
    # names; neither map is produced by the method its name refers to.
    "knnTemperature": 1.6,
}

CLASS_COUNT = len(ARBITRARY_CONSTANTS["biases"])
# The UC1 class values, in the order `functions_cuda.cu` assigns them: 1 normal,
# 2 tumour, 3 hypervascularised, 4 background.
CLASS_VALUES = (1, 2, 3, 4)
REDNESS_MINIMUM_NM = 600.0
REDNESS_MAXIMUM_NM = 700.0
GREEN_MINIMUM_NM = 500.0
GREEN_MAXIMUM_NM = 560.0


class MapContractError(ValueError):
    """The stand-in produced data outside the SLIAFlow image contract."""


class SimulatedMarkerRequiredError(ValueError):
    """The arithmetic stand-in was pointed at an unmarked dataset."""


def _asCalibratedCube(calibratedCube: numpy.ndarray) -> numpy.ndarray:
    calibratedCube = numpy.asarray(calibratedCube)
    if calibratedCube.ndim != 3 or 0 in calibratedCube.shape:
        raise ValueError(
            "calibratedCube must be a non-empty (bands, lines, samples) array, "
            f"got shape {calibratedCube.shape}."
        )
    if not numpy.issubdtype(calibratedCube.dtype, numpy.number):
        raise ValueError(f"calibratedCube must be numeric, got {calibratedCube.dtype}.")
    if not numpy.all(numpy.isfinite(calibratedCube)):
        raise ValueError("calibratedCube must contain only finite values.")
    return calibratedCube.astype(numpy.float32, copy=False)


def _asWavelengths(wavelengthsNm: Iterable[float], bandCount: int) -> numpy.ndarray:
    wavelengths = numpy.asarray(tuple(wavelengthsNm), dtype=numpy.float64)
    if wavelengths.ndim != 1 or wavelengths.size != bandCount:
        raise ValueError(
            f"Expected one wavelength per band ({bandCount}), got shape {wavelengths.shape}."
        )
    if not numpy.all(numpy.isfinite(wavelengths)):
        raise ValueError("wavelengthsNm must contain only finite values.")
    return wavelengths


def rednessIndex(calibratedCube: numpy.ndarray, wavelengthsNm: Iterable[float]) -> numpy.ndarray:
    """Return red-band mean minus green-band mean for every pixel."""
    cube = _asCalibratedCube(calibratedCube)
    wavelengths = _asWavelengths(wavelengthsNm, cube.shape[0])
    redBands = (wavelengths >= REDNESS_MINIMUM_NM) & (wavelengths <= REDNESS_MAXIMUM_NM)
    greenBands = (wavelengths >= GREEN_MINIMUM_NM) & (wavelengths <= GREEN_MAXIMUM_NM)
    if not numpy.any(redBands) or not numpy.any(greenBands):
        raise ValueError(
            "The calibrated cube needs at least one band in both 600-700 nm and 500-560 nm."
        )
    return (
        cube[redBands].mean(axis=0, dtype=numpy.float32)
        - cube[greenBands].mean(axis=0, dtype=numpy.float32)
    ).astype(numpy.float32)


def luminance(calibratedCube: numpy.ndarray) -> numpy.ndarray:
    """Return the mean calibrated value over every band for every pixel."""
    cube = _asCalibratedCube(calibratedCube)
    return cube.mean(axis=0, dtype=numpy.float32).astype(numpy.float32)


def logits(redness: numpy.ndarray, luminanceValues: numpy.ndarray) -> numpy.ndarray:
    """Feed the two scalar feature maps to four fixed arithmetic logits."""
    redness = numpy.asarray(redness, dtype=numpy.float32)
    luminanceValues = numpy.asarray(luminanceValues, dtype=numpy.float32)
    if redness.shape != luminanceValues.shape:
        raise ValueError(
            f"redness and luminance must have equal shapes, got "
            f"{redness.shape} and {luminanceValues.shape}."
        )
    if redness.ndim != 2 or 0 in redness.shape:
        raise ValueError(f"Feature maps must be non-empty 2-D arrays, got {redness.shape}.")

    rednessWeights = numpy.asarray(ARBITRARY_CONSTANTS["rednessWeights"], dtype=numpy.float32)
    luminanceWeights = numpy.asarray(
        ARBITRARY_CONSTANTS["luminanceWeights"], dtype=numpy.float32
    )
    biases = numpy.asarray(ARBITRARY_CONSTANTS["biases"], dtype=numpy.float32)
    return (
        redness[..., numpy.newaxis] * rednessWeights
        + luminanceValues[..., numpy.newaxis] * luminanceWeights
        + biases
    ).astype(numpy.float32)


def _softmax(values: numpy.ndarray) -> numpy.ndarray:
    shifted = values - numpy.max(values, axis=-1, keepdims=True)
    exponentials = numpy.exp(shifted.astype(numpy.float64))
    probabilities = exponentials / numpy.sum(exponentials, axis=-1, keepdims=True)
    return probabilities.astype(numpy.float32)


def deriveMaps(
    calibratedCube: numpy.ndarray, wavelengthsNm: Iterable[float]
) -> contract.Uc1Maps:
    """Derive all five mutually consistent maps from a calibrated cube."""
    cube = _asCalibratedCube(calibratedCube)
    wavelengths = _asWavelengths(wavelengthsNm, cube.shape[0])
    redness = rednessIndex(cube, wavelengths)
    luminanceValues = luminance(cube)
    z = logits(redness, luminanceValues)

    svmProbability = _softmax(z)[numpy.newaxis, ...]
    # The same `z`, the same softmax, one temperature apart. See the note beside
    # `knnTemperature`: this is one rule read twice, not two algorithms.
    knnProbability = _softmax(z / float(ARBITRARY_CONSTANTS["knnTemperature"]))[
        numpy.newaxis, ...
    ]
    mean = (svmProbability + knnProbability) / 2

    maps = contract.Uc1Maps(
        tmdMap=mean[..., 1].astype(numpy.float32),
        majorityVotingMap=(numpy.argmax(mean, axis=-1).astype(numpy.uint8) + 1),
        majorityVotingProbabilityMap=numpy.max(mean, axis=-1).astype(numpy.float32),
        svmProbability=svmProbability.astype(numpy.float32),
        knnProbability=knnProbability.astype(numpy.float32),
    )
    return maps


def _requirePresentMaps(maps: contract.Uc1Maps) -> tuple[numpy.ndarray, ...]:
    if not isinstance(maps, contract.Uc1Maps):
        raise MapContractError(f"Expected contract.Uc1Maps, got {type(maps).__name__}.")
    absent = [name for name in contract.UC1_MAP_FIELD_NAMES if getattr(maps, name) is None]
    if absent:
        raise MapContractError(
            f"The stand-in must produce all five maps; absent: {', '.join(absent)}."
        )
    present = tuple(getattr(maps, name) for name in contract.UC1_MAP_FIELD_NAMES)
    if not all(isinstance(array, numpy.ndarray) for array in present):
        raise MapContractError("Every present map must be a NumPy array.")
    return present


def _requireFloatProbability(
    array: numpy.ndarray, name: str, expectedShape: tuple[int, ...]
) -> None:
    if array.shape != expectedShape or array.dtype != numpy.float32:
        raise MapContractError(
            f"{name} must have shape {expectedShape} and dtype float32, "
            f"got {array.shape} and {array.dtype}."
        )
    if not numpy.all(numpy.isfinite(array)):
        raise MapContractError(f"{name} contains non-finite values.")
    if not numpy.all((array >= 0.0) & (array <= 1.0)):
        raise MapContractError(f"{name} contains values outside [0, 1].")


def validateMajorityVotingMap(
    majorityVotingMap: numpy.ndarray, expectedShape: tuple[int, ...] | None = None
) -> None:
    """Raise :class:`MapContractError` unless the class map satisfies the contract.

    This is separate from :func:`validateMaps` because the genuine UC1 binary
    produces this one map and nothing else, so a five-map check cannot be run
    over its output. Both producers are held to one definition of the class-map
    rules rather than to two that can drift apart.

    `expectedShape` is supplied when the map is checked alongside the other four
    and must agree with them. On its own, any `(1, lines, samples)` is accepted.
    """
    if not isinstance(majorityVotingMap, numpy.ndarray):
        raise MapContractError(
            f"majorityVotingMap must be a NumPy array, got {type(majorityVotingMap).__name__}."
        )

    shape = majorityVotingMap.shape
    if expectedShape is None:
        shapeIsValid = len(shape) == 3 and shape[0] == 1 and shape[1] > 0 and shape[2] > 0
    else:
        shapeIsValid = shape == expectedShape
    if not shapeIsValid or majorityVotingMap.dtype != numpy.uint8:
        expectation = expectedShape if expectedShape is not None else "(1, lines, samples)"
        raise MapContractError(
            f"majorityVotingMap must have shape {expectation} and dtype uint8, "
            f"got {shape} and {majorityVotingMap.dtype}."
        )
    if not numpy.all(numpy.isfinite(majorityVotingMap)):
        raise MapContractError("majorityVotingMap contains non-finite values.")
    if not set(numpy.unique(majorityVotingMap).tolist()).issubset(set(CLASS_VALUES)):
        raise MapContractError(
            f"majorityVotingMap contains a class outside {set(CLASS_VALUES)}."
        )


def validateMaps(maps: contract.Uc1Maps) -> None:
    """Raise :class:`MapContractError` unless all five maps satisfy the contract."""
    present = _requirePresentMaps(maps)
    (
        tmdMap,
        majorityVotingMap,
        majorityVotingProbabilityMap,
        svmProbability,
        knnProbability,
    ) = present

    probabilityShape = svmProbability.shape
    if (
        len(probabilityShape) != 4
        or probabilityShape[0] != 1
        or probabilityShape[1] <= 0
        or probabilityShape[2] <= 0
        or probabilityShape[3] != CLASS_COUNT
    ):
        raise MapContractError(
            "Probability maps must have shape (1, lines, samples, 4), "
            f"got {probabilityShape}."
        )
    expectedScalarShape = probabilityShape[:3]
    _requireFloatProbability(svmProbability, "svmProbability", probabilityShape)
    _requireFloatProbability(knnProbability, "knnProbability", probabilityShape)
    _requireFloatProbability(tmdMap, "tmdMap", expectedScalarShape)
    _requireFloatProbability(
        majorityVotingProbabilityMap,
        "majorityVotingProbabilityMap",
        expectedScalarShape,
    )

    validateMajorityVotingMap(majorityVotingMap, expectedShape=expectedScalarShape)

    for name, probability in (
        ("svmProbability", svmProbability),
        ("knnProbability", knnProbability),
    ):
        if not numpy.allclose(probability.sum(axis=-1), 1.0, atol=1e-5, rtol=0.0):
            raise MapContractError(f"{name} probability rows do not sum to 1 within 1e-5.")

    mean = (svmProbability + knnProbability) / 2
    expectedClasses = numpy.argmax(mean, axis=-1).astype(numpy.uint8) + 1
    if not numpy.array_equal(majorityVotingMap, expectedClasses):
        raise MapContractError("majorityVotingMap is not argmax(mean) + 1.")
    if not numpy.allclose(
        majorityVotingProbabilityMap, numpy.max(mean, axis=-1), atol=1e-5, rtol=0.0
    ):
        raise MapContractError("majorityVotingProbabilityMap is not max(mean).")
    if not numpy.allclose(tmdMap, mean[..., 1], atol=1e-5, rtol=0.0):
        raise MapContractError("tmdMap is not the tumour channel mean[..., 1].")


class ArithmeticClassifier:
    """Implement the SLIA-011 ``Classifier`` seam with fixed arithmetic."""

    def __init__(self, requireSimulatedMarker: bool = True) -> None:
        self.requireSimulatedMarker = requireSimulatedMarker

    def classify(self, dataset: contract.DatasetRef) -> contract.Uc1Maps:
        if self.requireSimulatedMarker and not dataset.simulated:
            raise SimulatedMarkerRequiredError(
                f"Refusing to classify {dataset.folder}: raw.hdr lacks the "
                f"{enviMarkerName()} marker. Pass --force-unmarked only for an explicitly "
                "approved synthetic test dataset."
            )
        maps = deriveMaps(dataset.loadCalibratedCube(), dataset.wavelengthsNm)
        validateMaps(maps)
        return maps


def enviMarkerName() -> str:
    """Return the marker name without importing ENVI at module import time."""
    from . import envi

    return envi.DATASET_MARKER


def classifyDataset(
    dataset: contract.DatasetRef, requireSimulatedMarker: bool = True
) -> contract.Uc1Maps:
    """Classify one dataset through the arithmetic stand-in."""
    return ArithmeticClassifier(requireSimulatedMarker=requireSimulatedMarker).classify(dataset)


__all__ = [
    "ARBITRARY_CONSTANTS",
    "CLASS_VALUES",
    "ArithmeticClassifier",
    "MapContractError",
    "NON_CLASSIFIER_NOTICE",
    "SimulatedMarkerRequiredError",
    "classifyDataset",
    "deriveMaps",
    "logits",
    "luminance",
    "rednessIndex",
    "validateMajorityVotingMap",
    "validateMaps",
]
