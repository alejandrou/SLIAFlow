from typing import Annotated

import slicer
from slicer.parameterNodeWrapper import (
    Choice,
    Default,
    WithinRange,
    parameterNodeWrapper,
)

# Choice values are persisted in the MRML parameter node, so they must remain
# stable and language independent. User-facing labels are kept in the UI.
LIVE_SOURCE_LAPTOP = "Laptop Camera"
LIVE_SOURCE_IGTL = "AcquisitionSystemApp LiveView"
LIVE_SOURCE_CHOICES = [LIVE_SOURCE_LAPTOP, LIVE_SOURCE_IGTL]

RESULT_MAP_TMD = "tmdMap"
RESULT_MAP_MV_CLASS = "majorityVotingMap"
RESULT_MAP_MV_PROB = "majorityVotingProbabilityMap"
RESULT_MAP_SVM_PROB = "svmProbability"
RESULT_MAP_KNN_PROB = "knnProbability"
RESULT_MAP_CHOICES = [
    RESULT_MAP_TMD,
    RESULT_MAP_MV_CLASS,
    RESULT_MAP_MV_PROB,
    RESULT_MAP_SVM_PROB,
    RESULT_MAP_KNN_PROB,
]

RESULT_MAP_DEVICE_NAMES = {
    RESULT_MAP_TMD: "UC1_TMD",
    RESULT_MAP_MV_CLASS: "UC1_MV_CLASS",
    RESULT_MAP_MV_PROB: "UC1_MV_PROB",
    RESULT_MAP_SVM_PROB: "UC1_SVM_PROB",
    RESULT_MAP_KNN_PROB: "UC1_KNN_PROB",
}

RESULT_SOURCE_ROLE_ATTRIBUTE = "SLIAFlow.ResultMap"
RESULT_SOURCE_ORIGIN_ATTRIBUTE = "SLIAFlow.DataOrigin"
RESULT_SOURCE_DEVICE_ATTRIBUTE = "SLIAFlow.DeviceName"
RESULT_SOURCE_GENUINE_ORIGIN = "external-genuine"
RESULT_SOURCE_SIMULATED_ORIGIN = "simulated"
RESULT_SOURCE_DETAIL_ATTRIBUTE = "SLIAFlow.SimulationDetail"

# Displayed over any simulated result. Kept next to the origin values it
# qualifies so the marker cannot drift away from the boundary it marks.
SIMULATED_BANNER_MESSAGE = "SIMULATED - NOT A GENUINE UC1 RESULT"

# A simulated result now has two possible producers. The arithmetic stand-in is
# not a classifier, so "not a genuine UC1 result" is exactly right for it. The
# genuine UC1 pipeline run on an invented scene is the other: the algorithm is
# real and only the input was made up, so that same sentence would be a false
# statement displayed in red over the view. Both are barred from clinical
# reading, and both keep a banner; only the wording differs, chosen from the
# detail the producer puts on the wire.
SIMULATED_DETAIL_REAL_PIPELINE_PREFIX = "real UC1 pipeline"
SIMULATED_BANNER_MESSAGE_REAL_PIPELINE = (
    "SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT"
)


def simulatedBannerMessage(detail: str | None) -> str:
    """Return the banner headline that matches a simulation detail string.

    Anything unrecognised falls back to the stronger stand-in wording. A
    producer that stops describing itself must not quietly get the softer
    banner.
    """
    if detail is None:
        return SIMULATED_BANNER_MESSAGE
    prefix = SIMULATED_DETAIL_REAL_PIPELINE_PREFIX.lower()
    if detail.strip().lower().startswith(prefix):
        return SIMULATED_BANNER_MESSAGE_REAL_PIPELINE
    return SIMULATED_BANNER_MESSAGE


@parameterNodeWrapper
class SLIAFlowParameterNode:
    """Persisted SLIAFlow references and presentation selections."""

    liveVolume: slicer.vtkMRMLVectorVolumeNode
    resultSourceVolume: slicer.vtkMRMLVolumeNode
    resultVolume: slicer.vtkMRMLScalarVolumeNode
    liveSource: Annotated[
        str, Choice(LIVE_SOURCE_CHOICES), Default(LIVE_SOURCE_LAPTOP)
    ]
    cameraIndex: Annotated[int, WithinRange(0, 99), Default(0)]
    resultMap: Annotated[
        str, Choice(RESULT_MAP_CHOICES), Default(RESULT_MAP_TMD)
    ]
    resultClass: Annotated[int, WithinRange(1, 4), Default(1)]
