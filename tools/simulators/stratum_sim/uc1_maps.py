"""The class-map rules every UC1 majority-voting map must satisfy.

The genuine UC1 binary produces this one map of the five in the contract, and the
runner checks it here before each send, so a map that breaks the contract is
refused rather than drawn.
"""

from __future__ import annotations

import numpy

# The UC1 class values, in the order `functions_cuda.cu` assigns them: 1 normal,
# 2 tumour, 3 hypervascularised, 4 background.
CLASS_VALUES = (1, 2, 3, 4)


class MapContractError(ValueError):
    """A map is outside the SLIAFlow image contract."""


def validateMajorityVotingMap(
    majorityVotingMap: numpy.ndarray, expectedShape: tuple[int, ...] | None = None
) -> None:
    """Raise :class:`MapContractError` unless the class map satisfies the contract.

    `expectedShape` is supplied when the map has to agree with another image. On
    its own, any `(1, lines, samples)` is accepted.
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
    if not set(numpy.unique(majorityVotingMap).tolist()).issubset(set(CLASS_VALUES)):
        raise MapContractError(
            f"majorityVotingMap contains a class outside {set(CLASS_VALUES)}."
        )


__all__ = [
    "CLASS_VALUES",
    "MapContractError",
    "validateMajorityVotingMap",
]
