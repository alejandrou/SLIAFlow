from typing import Annotated

import slicer
from slicer.parameterNodeWrapper import (
    Choice,
    Default,
    WithinRange,
    parameterNodeWrapper,
)

from .SLIAFlowConnections import (
    CHANNEL_HS_CUBE,
    CHANNEL_LIVE_VIEW,
    CHANNEL_STEREO,
    DEFAULT_EXPECTED_BANDS,
    DEFAULT_HOST,
    DEFAULT_PORTS,
)
from .SLIAFlowUc1Run import OUTPUT_FILE_NAMES

# The Tumour Delineation panel shows one UC1 output image at a time, chosen by
# its exact file name. A run opens on the calibrated RGB image, which is the
# one output that is a picture of the case rather than a classification of it.
DEFAULT_RESULT_OUTPUT = "imageRGB.bmp"

# Provenance on every module-owned output node (ADR-0003 decision 5).
OWNER_ATTRIBUTE = "SLIAFlow.Owner"
DATA_ORIGIN_ATTRIBUTE = "SLIAFlow.DataOrigin"
SIMULATION_DETAIL_ATTRIBUTE = "SLIAFlow.SimulationDetail"
CAPTURE_ID_ATTRIBUTE = "SLIAFlow.CaptureId"
RECORDED_CASE_ATTRIBUTE = "SLIAFlow.RecordedCase"
OUTPUT_FILE_ATTRIBUTE = "SLIAFlow.OutputFile"
# The acquisition is simulated: the cube is read from disk, not captured now.
SIMULATED_ORIGIN = "simulated"
# SLIA-036: received from IUMA's acquisition app, which may have captured it
# live or replayed a stored cube (owner decision 3 of SLIA-030).
RECEIVED_ORIGIN = "received"
# contract.recordedCaseDetail's producer name for the genuine UC1 pipeline.
SIMULATION_DETAIL_PRODUCER = "real UC1 pipeline"
# The same for the vendored UC2 blood-vessel enhancement (SLIA-021).
UC2_SIMULATION_DETAIL_PRODUCER = "real UC2 blood-vessel enhancement"
# The fixed bands and parameters a UC2 map was made with, on the map's node.
UC2_PARAMETERS_ATTRIBUTE = "SLIAFlow.Uc2Parameters"

# The calibrated cube's wavelengths in nm, comma-separated, on the cube volume
# itself, so a spectrum is always plotted against the grid of the cube it reads.
WAVELENGTHS_ATTRIBUTE = "SLIAFlow.WavelengthsNm"
# SLIA-036: the app sends no wavelengths. On a received cube this says where its
# wavelengths came from instead.
WAVELENGTHS_ASSUMED_ATTRIBUTE = "SLIAFlow.WavelengthsAssumed"

# SLIA-036: which cube HS Cube shows and Capture uses. Stored as shown.
CUBE_SOURCE_DISK = "Cube on disk"
CUBE_SOURCE_APP = "Last cube from the app"
CUBE_SOURCES = (CUBE_SOURCE_DISK, CUBE_SOURCE_APP)
# The name UC1 and UC2 know a received cube by: the folder it is written to.
RECEIVED_CUBE_NAME = "received-from-app"


def calibratedCubeDetail(cubeName: str) -> str:
    """The simulation detail of IUMA's calibrated cube read from disk (ADR-0004 decision 7)."""
    return (f"recorded IUMA LCTF capture {cubeName}, calibrated by IUMA "
            "(simulated acquisition)")


def receivedCubeDetail(host: str, port: int, receivedAt, pixelType: str) -> str:
    """The detail of a cube received from the app's HS Cube port (SLIA-030 owner decision 3)."""
    when = receivedAt.strftime("%Y-%m-%d %H:%M:%S") if receivedAt is not None else "unknown"
    return (f"{pixelType} cube received over OpenIGTLink from {host}:{port}, the port IUMA's "
            f"AcquisitionSystemApp serves its HS cube on, at {when}; the sender may have "
            "captured it live or replayed a stored cube, which SLIAFlow cannot tell apart")


def uc1ResultDetail(cubeName: str, cubeDetail: str | None = None) -> str:
    """The simulation detail of a UC1 output: the pipeline, then the cube it ran on."""
    return f"{SIMULATION_DETAIL_PRODUCER}, {cubeDetail or calibratedCubeDetail(cubeName)}"


def uc2ResultDetail(cubeName: str, cubeDetail: str | None = None) -> str:
    """The simulation detail of a UC2 map: the component, then the cube it ran on."""
    return f"{UC2_SIMULATION_DETAIL_PRODUCER}, {cubeDetail or calibratedCubeDetail(cubeName)}"


@parameterNodeWrapper
class SLIAFlowParameterNode:
    """Persisted SLIAFlow references and presentation selections."""

    liveVolume: slicer.vtkMRMLVectorVolumeNode
    cameraIndex: Annotated[int, WithinRange(0, 99), Default(0)]
    resultOutput: Annotated[
        str, Choice(list(OUTPUT_FILE_NAMES)), Default(DEFAULT_RESULT_OUTPUT)
    ]
    # SLIA-035: where the Connections section connects. Port 0 leaves a channel out.
    igtlHost: Annotated[str, Default(DEFAULT_HOST)]
    liveViewPort: Annotated[int, WithinRange(0, 65535), Default(DEFAULT_PORTS[CHANNEL_LIVE_VIEW])]
    stereoPort: Annotated[int, WithinRange(0, 65535), Default(DEFAULT_PORTS[CHANNEL_STEREO])]
    hsCubePort: Annotated[int, WithinRange(0, 65535), Default(DEFAULT_PORTS[CHANNEL_HS_CUBE])]
    expectedBands: Annotated[int, WithinRange(1, 10000), Default(DEFAULT_EXPECTED_BANDS)]
    # SLIA-036.
    cubeSource: Annotated[str, Choice(list(CUBE_SOURCES)), Default(CUBE_SOURCE_DISK)]
