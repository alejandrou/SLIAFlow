"""SLIAFlow scripted-module entry point."""

from SLIAFlowLib import (
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
            "the STRATUM demonstrator. This module provides the six-panel WP5 "
            "operator surface. On Capture it runs the prebuilt UC1 pipeline on a "
            "recorded public HSI case, with a simulated acquisition, and shows "
            "its output images as written. It does not interpret diagnostic "
            "images."
        )
        self.parent.acknowledgementText = _(
            "Prototype software only. Not clinically validated. Do not use with "
            "private or identifiable patient data."
        )


__all__ = [
    "SLIAFlow",
    "SLIAFlowLogic",
    "SLIAFlowParameterNode",
    "SLIAFlowTest",
    "SLIAFlowWidget",
]
