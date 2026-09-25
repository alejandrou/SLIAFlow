from typing import Annotated

import slicer
from slicer.parameterNodeWrapper import (
    Choice,
    Default,
    WithinRange,
    parameterNodeWrapper,
)

from .SLIAFlowCube import GROUND_TRUTH_FILE_NAME
from .SLIAFlowUc1Run import OUTPUT_FILE_NAMES

# The Tumour Delineation panel shows one UC1 output image at a time, chosen by
# its exact file name. A run opens on the calibrated RGB image, which is the
# one output that is a picture of the case rather than a classification of it.
DEFAULT_RESULT_OUTPUT = "imageRGB.bmp"

# The cube's own labelling is a sixth thing the panel can show, and the only
# one UC1 did not produce. It is not a background of its own: it is a label
# layer laid over whichever output was chosen last, which is the comparison it
# exists for. It is offered only for a cube that has one (ADR-0004 decision 8).
GROUND_TRUTH_VIEW_NAME = GROUND_TRUTH_FILE_NAME
RESULT_VIEW_NAMES = (*OUTPUT_FILE_NAMES, GROUND_TRUTH_VIEW_NAME)

# Provenance on every module-owned output node (ADR-0003 decision 5).
OWNER_ATTRIBUTE = "SLIAFlow.Owner"
DATA_ORIGIN_ATTRIBUTE = "SLIAFlow.DataOrigin"
SIMULATION_DETAIL_ATTRIBUTE = "SLIAFlow.SimulationDetail"
CAPTURE_ID_ATTRIBUTE = "SLIAFlow.CaptureId"
RECORDED_CASE_ATTRIBUTE = "SLIAFlow.RecordedCase"
OUTPUT_FILE_ATTRIBUTE = "SLIAFlow.OutputFile"
# The acquisition is simulated: the cube is read from disk, not captured now.
SIMULATED_ORIGIN = "simulated"
# contract.recordedCaseDetail's producer name for the genuine UC1 pipeline.
SIMULATION_DETAIL_PRODUCER = "real UC1 pipeline"

# The calibrated cube's wavelengths in nm, comma-separated, on the cube volume
# itself, so a spectrum is always plotted against the grid of the cube it reads.
WAVELENGTHS_ATTRIBUTE = "SLIAFlow.WavelengthsNm"


def calibratedCubeDetail(cubeName: str) -> str:
    """The simulation detail of IUMA's calibrated cube read from disk (ADR-0004 decision 7)."""
    return (f"recorded IUMA LCTF capture {cubeName}, calibrated by IUMA "
            "(simulated acquisition)")


def uc1ResultDetail(cubeName: str) -> str:
    """The simulation detail of a UC1 output: the pipeline, then the cube it ran on."""
    return f"{SIMULATION_DETAIL_PRODUCER}, {calibratedCubeDetail(cubeName)}"


@parameterNodeWrapper
class SLIAFlowParameterNode:
    """Persisted SLIAFlow references and presentation selections."""

    liveVolume: slicer.vtkMRMLVectorVolumeNode
    cameraIndex: Annotated[int, WithinRange(0, 99), Default(0)]
    resultOutput: Annotated[
        str, Choice(list(RESULT_VIEW_NAMES)), Default(DEFAULT_RESULT_OUTPUT)
    ]
