import slicer
from slicer import vtkMRMLScalarVolumeNode
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.parameterNodeWrapper import parameterNodeWrapper
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin


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
            "the STRATUM demonstrator. This scaffold stores volume references "
            "but does not generate or interpret diagnostic images."
        )
        self.parent.acknowledgementText = _(
            "Prototype software only. Not clinically validated. Do not use with "
            "private or identifiable patient data."
        )


@parameterNodeWrapper
class SLIAFlowParameterNode:
    """MRML references persisted by the SLIAFlow module.

    The parameter-node wrapper serializes MRML nodes as node references. Slicer
    therefore persists their node IDs rather than relying on non-unique names.
    """

    liveVolume: vtkMRMLScalarVolumeNode
    resultVolume: vtkMRMLScalarVolumeNode


class SLIAFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Minimal widget used to verify module discovery and persistent state."""

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic: SLIAFlowLogic | None = None
        self._parameterNode: SLIAFlowParameterNode | None = None
        self._parameterNodeGuiTag: int | None = None

    def setup(self) -> None:
        super().setup()

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/SLIAFlow.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = SLIAFlowLogic()
        self.addObserver(
            slicer.mrmlScene,
            slicer.mrmlScene.StartCloseEvent,
            self.onSceneStartClose,
        )
        self.addObserver(
            slicer.mrmlScene,
            slicer.mrmlScene.EndCloseEvent,
            self.onSceneEndClose,
        )
        self.initializeParameterNode()

    def cleanup(self) -> None:
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller=None, event=None) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        if self.logic is None:
            return
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(
        self, parameterNode: SLIAFlowParameterNode | None
    ) -> None:
        if self._parameterNode is not None and self._parameterNodeGuiTag is not None:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)

        self._parameterNode = parameterNode
        self._parameterNodeGuiTag = None

        if self._parameterNode is not None:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)


class SLIAFlowLogic(ScriptedLoadableModuleLogic):
    """Provide access to SLIAFlow state without requiring a Qt widget."""

    def getParameterNode(self) -> SLIAFlowParameterNode:
        return SLIAFlowParameterNode(super().getParameterNode())


class SLIAFlowTest(ScriptedLoadableModuleTest):
    """Focused tests for the clean scripted-module scaffold."""

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()

    def runTest(self) -> None:
        self.setUp()
        self.test_moduleMetadataAndUi()
        self.setUp()
        self.test_parameterNodeStoresVolumeReferencesByID()

    def test_moduleMetadataAndUi(self) -> None:
        module = slicer.app.moduleManager().module("SLIAFlow")
        self.assertIsNotNone(module)
        self.assertEqual(module.title, "SLIAFlow")
        self.assertIn("STRATUM", module.categories)
        self.assertIn("non-clinical", module.helpText.lower())

        widget = module.widgetRepresentation()
        warning = slicer.util.findChild(widget, "prototypeWarningLabel")
        self.assertIsNotNone(warning)
        self.assertIn("not clinically validated", warning.text.lower())

    def test_parameterNodeStoresVolumeReferencesByID(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()

        liveVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Shared volume name"
        )
        resultVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Shared volume name"
        )
        parameters.liveVolume = liveVolume
        parameters.resultVolume = resultVolume

        self.assertNotEqual(liveVolume.GetID(), resultVolume.GetID())
        self.assertEqual(
            parameters.parameterNode.GetNodeReferenceID("liveVolume"),
            liveVolume.GetID(),
        )
        self.assertEqual(
            parameters.parameterNode.GetNodeReferenceID("resultVolume"),
            resultVolume.GetID(),
        )
        self.assertEqual(parameters.liveVolume.GetID(), liveVolume.GetID())
        self.assertEqual(parameters.resultVolume.GetID(), resultVolume.GetID())
