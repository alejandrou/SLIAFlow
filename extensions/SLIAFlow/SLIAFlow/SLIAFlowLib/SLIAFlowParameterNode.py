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
