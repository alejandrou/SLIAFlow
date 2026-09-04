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

# The four provenance keys, in the order the contract document lists them.
# Translation, discovery and the origin gate all walk this one tuple, so a key
# added to the contract cannot be handled in one place and forgotten in
# another.
RESULT_SOURCE_ATTRIBUTES = (
    RESULT_SOURCE_ROLE_ATTRIBUTE,
    RESULT_SOURCE_DEVICE_ATTRIBUTE,
    RESULT_SOURCE_ORIGIN_ATTRIBUTE,
    RESULT_SOURCE_DETAIL_ATTRIBUTE,
)

# Only these two origins exist. Absent, empty or anything else is invalid and
# is never widened into a default.
RECOGNIZED_ORIGINS = (RESULT_SOURCE_GENUINE_ORIGIN, RESULT_SOURCE_SIMULATED_ORIGIN)

# vtkMRMLIGTLConnectorNode copies every incoming metadata entry onto the MRML
# node as "OpenIGTLink." + key, with no condition around it, so the wire key
# SLIAFlow.DataOrigin arrives as OpenIGTLink.SLIAFlow.DataOrigin and the bare
# spelling never appears. Producers keep sending the bare names; reconciling
# the two spellings is the receiver's business.
WIRE_ATTRIBUTE_PREFIX = "OpenIGTLink."

# OpenIGTLink endpoints. Both a stand-in and the genuine UC1 runner use the UC1
# endpoint, so an endpoint carries no provenance information whatsoever.
IGTL_HOST = "127.0.0.1"
ACQUISITION_PORT = 18944
UC1_PORT = 18945
LIVE_VIEW_DEVICE_NAME = "LiveView"

CONNECTOR_ACQUISITION = "acquisition"
CONNECTOR_UC1 = "uc1"
CONNECTOR_ROLES = (CONNECTOR_ACQUISITION, CONNECTOR_UC1)

# The connection vocabulary the panel exposes. "receiving" means the socket is
# connected; "displaying" and "invalid" describe what was made of the data and
# are therefore stronger than the socket state that produced them.
CONNECTION_DISCONNECTED = "disconnected"
CONNECTION_CONNECTING = "connecting"
CONNECTION_RECEIVING = "receiving"
CONNECTION_INVALID = "invalid"
CONNECTION_DISPLAYING = "displaying"
CONNECTION_STATES = (
    CONNECTION_DISCONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_RECEIVING,
    CONNECTION_INVALID,
    CONNECTION_DISPLAYING,
)

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
    liveSourceVolume: slicer.vtkMRMLVolumeNode
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
