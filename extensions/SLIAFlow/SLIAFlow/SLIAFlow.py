"""SLIAFlow scripted-module entry point."""

from SLIAFlowLib import (
    LIVE_SOURCE_CHOICES,
    LIVE_SOURCE_IGTL,
    LIVE_SOURCE_LAPTOP,
    RESULT_MAP_CHOICES,
    RESULT_MAP_DEVICE_NAMES,
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_MV_CLASS,
    RESULT_MAP_MV_PROB,
    RESULT_MAP_SVM_PROB,
    RESULT_MAP_TMD,
    RESULT_SOURCE_DEVICE_ATTRIBUTE,
    RESULT_SOURCE_GENUINE_ORIGIN,
    RESULT_SOURCE_ORIGIN_ATTRIBUTE,
    RESULT_SOURCE_ROLE_ATTRIBUTE,
    ResultMapDescriptor,
    SLIAFlowLogic,
    SLIAFlowParameterNode,
    SLIAFlowTest,
    SLIAFlowWidget,
)
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import ScriptedLoadableModule


class SLIAFlow(ScriptedLoadableModule):
    """Register the SLIAFlow scripted module with 3D Slicer."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.parent.title = _("SLIAFlow")
        self.parent.categories = [
            translate("qSlicerAbstractCoreModule", "STRATUM")
        ]
        self.parent.dependencies = []
        self.parent.contributors = ["STRATUM project contributors"]
        self.parent.helpText = _(
            "SLIAFlow is the non-clinical 3D Slicer visualization component of "
            "the STRATUM demonstrator. This module provides a two-pane "
            "presentation shell but does not generate or interpret diagnostic "
            "images."
        )
        self.parent.acknowledgementText = _(
            "Prototype software only. Not clinically validated. Do not use with "
            "private or identifiable patient data."
        )


__all__ = [
    "LIVE_SOURCE_CHOICES",
    "LIVE_SOURCE_IGTL",
    "LIVE_SOURCE_LAPTOP",
    "RESULT_MAP_CHOICES",
    "RESULT_MAP_DEVICE_NAMES",
    "RESULT_MAP_KNN_PROB",
    "RESULT_MAP_MV_CLASS",
    "RESULT_MAP_MV_PROB",
    "RESULT_MAP_SVM_PROB",
    "RESULT_MAP_TMD",
    "RESULT_SOURCE_DEVICE_ATTRIBUTE",
    "RESULT_SOURCE_GENUINE_ORIGIN",
    "RESULT_SOURCE_ORIGIN_ATTRIBUTE",
    "RESULT_SOURCE_ROLE_ATTRIBUTE",
    "ResultMapDescriptor",
    "SLIAFlow",
    "SLIAFlowLogic",
    "SLIAFlowParameterNode",
    "SLIAFlowTest",
    "SLIAFlowWidget",
]
