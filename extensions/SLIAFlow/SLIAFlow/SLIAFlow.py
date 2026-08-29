import unittest
from typing import Annotated, Any
from xml.sax.saxutils import escape

import slicer
import vtk
from slicer import vtkMRMLScalarVolumeNode
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.parameterNodeWrapper import (
    Choice,
    Default,
    WithinRange,
    parameterNodeWrapper,
)
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin

# Choice values are persisted verbatim in the MRML parameter node and are the
# text shown by the combo boxes, so they must stay language independent. A
# translated value would fail Choice validation when a scene saved under one
# Slicer language is reopened under another.
LIVE_SOURCE_LAPTOP = "Laptop Camera"
LIVE_SOURCE_IGTL = "AcquisitionSystemApp LiveView"
LIVE_SOURCE_CHOICES = [LIVE_SOURCE_LAPTOP, LIVE_SOURCE_IGTL]
RESULT_MAP_TMD = "tmdMap"
RESULT_MAP_CHOICES = [
    RESULT_MAP_TMD,
    "majorityVotingMap",
    "svmProbability",
    "knnProbability",
]


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


@parameterNodeWrapper
class SLIAFlowParameterNode:
    """Persisted SLIAFlow references and presentation selections."""

    liveVolume: vtkMRMLScalarVolumeNode
    resultVolume: vtkMRMLScalarVolumeNode
    liveSource: Annotated[
        str, Choice(LIVE_SOURCE_CHOICES), Default(LIVE_SOURCE_LAPTOP)
    ]
    cameraIndex: Annotated[int, WithinRange(0, 99), Default(0)]
    resultMap: Annotated[
        str, Choice(RESULT_MAP_CHOICES), Default(RESULT_MAP_TMD)
    ]
    resultClass: Annotated[int, WithinRange(1, 4), Default(1)]


class SLIAFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Present the fixed two-pane SLIAFlow interface."""

    CUSTOM_LAYOUT_ID = 701
    LIVE_VIEW_NAME = "SLIAFlowLive"
    RESULT_VIEW_NAME = "SLIAFlowResult"
    VIEW_NAMES = (LIVE_VIEW_NAME, RESULT_VIEW_NAME)
    LIVE_VIEW_LABEL = _("Live Image")
    RESULT_VIEW_LABEL = _("UC1 Result")
    WAITING_RESULT_MESSAGE = _("Waiting for genuine UC1 result")
    FUTURE_CONTROLS_STATUS = _(
        "Camera capture and genuine UC1 result display are reserved for later "
        "tasks. This task only provides the two-pane presentation; no image "
        "data is captured or displayed."
    )
    LAYOUT_CONFLICT_STATUS = _(
        "SLIAFlow could not activate layout 701 because another layout uses "
        "that reserved identifier."
    )
    LAYOUT_UNAVAILABLE_STATUS = _(
        "The SLIAFlow two-pane layout is not available in this Slicer window."
    )
    CUSTOM_LAYOUT_DESCRIPTION = (
        '<layout type="horizontal" split="true">'
        "<item>"
        '<view class="vtkMRMLSliceNode" singletontag="SLIAFlowLive">'
        '<property name="orientation" action="default">Axial</property>'
        f'<property name="viewlabel" action="default">{escape(LIVE_VIEW_LABEL)}</property>'
        "</view>"
        "</item>"
        "<item>"
        '<view class="vtkMRMLSliceNode" singletontag="SLIAFlowResult">'
        '<property name="orientation" action="default">Axial</property>'
        f'<property name="viewlabel" action="default">{escape(RESULT_VIEW_LABEL)}</property>'
        "</view>"
        "</item>"
        "</layout>"
    )

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic: SLIAFlowLogic | None = None
        self._parameterNode: Any = None
        self._parameterNodeGuiTag: int | None = None
        self._previousLayout: int | None = None
        self._presentationActive = False
        self._waitingAnnotationActor = None
        self._waitingAnnotationRenderer = None

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
        self._configureFutureControls()
        self.initializeParameterNode()

    def cleanup(self) -> None:
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self._activatePresentation()

    def exit(self) -> None:
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self._deactivatePresentation(restore=False)
        self.setParameterNode(None)

    def onSceneEndClose(self, caller=None, event=None) -> None:
        if getattr(self.parent, "isEntered", False):
            self.initializeParameterNode()
            self._activatePresentation()

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

    def _configureFutureControls(self) -> None:
        controlNames = (
            "liveSourceSelector",
            "cameraIndexSpinBox",
            "startButton",
            "stopButton",
            "resultMapSelector",
            "resultClassSpinBox",
        )
        for controlName in controlNames:
            control = getattr(self.ui, controlName, None)
            if control is not None:
                control.setEnabled(False)

        statusLabel = getattr(self.ui, "statusLabel", None)
        if statusLabel is not None:
            statusLabel.setText(self.FUTURE_CONTROLS_STATUS)

    def _setStatus(self, message: str) -> None:
        statusLabel = getattr(self.ui, "statusLabel", None)
        if statusLabel is not None:
            statusLabel.setText(message)

    def _registerCustomLayout(self, layoutNode) -> bool:
        if not layoutNode.IsLayoutDescription(self.CUSTOM_LAYOUT_ID):
            if not layoutNode.AddLayoutDescription(
                self.CUSTOM_LAYOUT_ID, self.CUSTOM_LAYOUT_DESCRIPTION
            ):
                self._setStatus(self.LAYOUT_CONFLICT_STATUS)
                return False

        if (
            layoutNode.GetLayoutDescription(self.CUSTOM_LAYOUT_ID)
            != self.CUSTOM_LAYOUT_DESCRIPTION
        ):
            self._setStatus(self.LAYOUT_CONFLICT_STATUS)
            return False
        return True

    def _activatePresentation(self) -> bool:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return False

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        if not self._registerCustomLayout(layoutNode):
            return False

        currentLayout = int(layoutNode.GetViewArrangement())
        if (
            not self._presentationActive
            and currentLayout != self.CUSTOM_LAYOUT_ID
            and self._previousLayout is None
        ):
            self._previousLayout = currentLayout

        if currentLayout != self.CUSTOM_LAYOUT_ID:
            try:
                layoutManager.setLayout(self.CUSTOM_LAYOUT_ID)
            except RuntimeError:
                self._setStatus(self.LAYOUT_UNAVAILABLE_STATUS)
                self._previousLayout = None
                return False

        if not self._configurePresentation(layoutManager):
            self._setStatus(self.LAYOUT_UNAVAILABLE_STATUS)
            if (
                self._previousLayout is not None
                and int(layoutNode.GetViewArrangement()) == self.CUSTOM_LAYOUT_ID
            ):
                layoutManager.setLayout(self._previousLayout)
            self._previousLayout = None
            return False

        self._presentationActive = True
        self._configureFutureControls()
        return True

    @staticmethod
    def _clearSliceLayers(sliceWidget) -> None:
        compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
        compositeNode.SetBackgroundVolumeID(None)
        compositeNode.SetForegroundVolumeID(None)
        compositeNode.SetLabelVolumeID(None)

    @staticmethod
    def _sliceViewRenderer(sliceWidget):
        sliceView = sliceWidget.sliceView()
        if sliceView is None:
            return None
        renderWindow = sliceView.renderWindow()
        if renderWindow is None:
            return None
        return renderWindow.GetRenderers().GetFirstRenderer()

    def _showWaitingAnnotation(self, sliceWidget) -> bool:
        """Draw the waiting message with an actor owned by this module.

        The shared corner annotation cannot carry this message. DataProbe's
        slice view annotations reset all four corners of every slice view
        whenever the slice logic changes, so text placed there is blanked
        before the operator can read it.
        """
        renderer = self._sliceViewRenderer(sliceWidget)
        if renderer is None:
            return False

        if self._waitingAnnotationActor is None:
            actor = vtk.vtkTextActor()
            actor.SetInput(self.WAITING_RESULT_MESSAGE)
            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            actor.SetPosition(0.5, 0.5)
            textProperty = actor.GetTextProperty()
            textProperty.SetFontSize(14)
            textProperty.SetColor(1.0, 1.0, 1.0)
            textProperty.SetJustificationToCentered()
            textProperty.SetVerticalJustificationToCentered()
            self._waitingAnnotationActor = actor

        previousRenderer = self._waitingAnnotationRenderer
        if previousRenderer is not None and previousRenderer is not renderer:
            previousRenderer.RemoveActor2D(self._waitingAnnotationActor)
        self._waitingAnnotationRenderer = renderer

        if not renderer.HasViewProp(self._waitingAnnotationActor):
            renderer.AddActor2D(self._waitingAnnotationActor)
        return True

    def _removeWaitingAnnotation(self) -> None:
        renderer = self._waitingAnnotationRenderer
        actor = self._waitingAnnotationActor
        self._waitingAnnotationRenderer = None
        if renderer is None or actor is None:
            return
        try:
            renderer.RemoveActor2D(actor)
        except (RuntimeError, ValueError):
            # The view can be torn down while Slicer reloads the module.
            pass

    def _configurePresentation(self, layoutManager) -> bool:
        for viewName, viewLabel in (
            (self.LIVE_VIEW_NAME, self.LIVE_VIEW_LABEL),
            (self.RESULT_VIEW_NAME, self.RESULT_VIEW_LABEL),
        ):
            sliceWidget = layoutManager.sliceWidget(viewName)
            if sliceWidget is None:
                return False

            sliceNode = sliceWidget.mrmlSliceNode()
            sliceNode.SetLayoutLabel(viewLabel)
            sliceNode.SetOrientationToAxial()
            self._clearSliceLayers(sliceWidget)

            if viewName == self.RESULT_VIEW_NAME:
                if not self._showWaitingAnnotation(sliceWidget):
                    return False

            sliceView = sliceWidget.sliceView()
            if sliceView is None:
                return False
            sliceView.forceRender()
        return True

    def _clearPresentation(self, layoutManager) -> None:
        for viewName in self.VIEW_NAMES:
            try:
                sliceWidget = layoutManager.sliceWidget(viewName)
                if sliceWidget is None:
                    continue
                self._clearSliceLayers(sliceWidget)
                sliceView = sliceWidget.sliceView()
                if sliceView is not None:
                    sliceView.forceRender()
            except RuntimeError:
                # The layout can be torn down while Slicer is reloading.
                continue

    def _deactivatePresentation(self, restore: bool) -> None:
        layoutManager = slicer.app.layoutManager()
        previousLayout = self._previousLayout

        self._removeWaitingAnnotation()
        if layoutManager is not None:
            layoutNode = layoutManager.layoutLogic().GetLayoutNode()
            if int(layoutNode.GetViewArrangement()) == self.CUSTOM_LAYOUT_ID:
                self._clearPresentation(layoutManager)
                if restore and previousLayout is not None:
                    layoutManager.setLayout(previousLayout)

        self._previousLayout = None if restore else previousLayout
        self._presentationActive = False


class SLIAFlowLogic(ScriptedLoadableModuleLogic):
    """Provide access to SLIAFlow state without requiring a Qt widget."""

    def getParameterNode(self) -> SLIAFlowParameterNode:
        return SLIAFlowParameterNode(super().getParameterNode())


class SLIAFlowTest(ScriptedLoadableModuleTest):
    """Focused tests for the SLIAFlow presentation shell."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Slicer's Reload and Test button runs exactly the names listed in
        # moduleTestNames, while the command-line runner uses unittest
        # discovery. Deriving the list from the same loader keeps both paths on
        # the identical set, so a newly added test method cannot be executed by
        # one path and silently skipped by the other.
        self.moduleTestNames = unittest.TestLoader().getTestCaseNames(type(self))

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()

    @staticmethod
    def _moduleRepresentationAndWidget():
        module = slicer.app.moduleManager().module("SLIAFlow")
        representation = module.widgetRepresentation()
        return representation, representation.self()

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

    def test_presentationParametersAndControls(self) -> None:
        representation, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        parameters = widget._parameterNode
        self.assertIsNotNone(parameters)
        self.assertEqual(parameters.liveSource, LIVE_SOURCE_LAPTOP)
        self.assertEqual(parameters.cameraIndex, 0)
        self.assertEqual(parameters.resultMap, RESULT_MAP_TMD)
        self.assertEqual(parameters.resultClass, 1)

        liveSource = slicer.util.findChild(representation, "liveSourceSelector")
        cameraIndex = slicer.util.findChild(representation, "cameraIndexSpinBox")
        startButton = slicer.util.findChild(representation, "startButton")
        stopButton = slicer.util.findChild(representation, "stopButton")
        resultMap = slicer.util.findChild(representation, "resultMapSelector")
        resultClass = slicer.util.findChild(representation, "resultClassSpinBox")
        status = slicer.util.findChild(representation, "statusLabel")

        for control in (
            liveSource,
            cameraIndex,
            startButton,
            stopButton,
            resultMap,
            resultClass,
        ):
            self.assertIsNotNone(control)
            self.assertFalse(control.isEnabled())

        self.assertEqual(liveSource.currentText, LIVE_SOURCE_LAPTOP)
        self.assertEqual(
            [liveSource.itemText(index) for index in range(liveSource.count)],
            LIVE_SOURCE_CHOICES,
        )
        self.assertEqual(cameraIndex.value, 0)
        self.assertEqual(resultMap.currentText, RESULT_MAP_TMD)
        self.assertEqual(
            [resultMap.itemText(index) for index in range(resultMap.count)],
            RESULT_MAP_CHOICES,
        )
        self.assertEqual(resultClass.value, 1)
        self.assertIn("later tasks", status.text.lower())
        self.assertIn("no image data", status.text.lower())

    @staticmethod
    def _settleEventLoop(iterations: int = 20) -> None:
        """Let observers such as DataProbe react to the module-owned views."""
        for _iteration in range(iterations):
            slicer.app.processEvents()

    def test_layoutContractAndLifecycle(self) -> None:
        from xml.etree import ElementTree

        widget = self._moduleRepresentationAndWidget()[1]
        layoutRoot = ElementTree.fromstring(widget.CUSTOM_LAYOUT_DESCRIPTION)
        self.assertEqual(layoutRoot.attrib["type"], "horizontal")
        views = layoutRoot.findall(".//view")
        self.assertEqual(len(views), 2)
        self.assertEqual(
            [view.attrib["singletontag"] for view in views],
            [widget.LIVE_VIEW_NAME, widget.RESULT_VIEW_NAME],
        )
        viewLabels = []
        for view in views:
            viewLabelProperty = view.find("property[@name='viewlabel']")
            if viewLabelProperty is None:
                raise AssertionError("A custom view is missing its view label property")
            viewLabel = viewLabelProperty.text
            if not isinstance(viewLabel, str):
                self.fail("A custom view label is empty")
            viewLabels.append(viewLabel)
        self.assertEqual(
            viewLabels,
            [widget.LIVE_VIEW_LABEL, widget.RESULT_VIEW_LABEL],
        )

        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.assertFalse(widget._activatePresentation())
            self.assertFalse(widget._presentationActive)
            return

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        if int(layoutNode.GetViewArrangement()) == widget.CUSTOM_LAYOUT_ID:
            layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutInitialView)
        previousLayout = int(layoutNode.GetViewArrangement())

        try:
            self.assertTrue(widget._activatePresentation())
            self.assertEqual(
                int(layoutNode.GetViewArrangement()), widget.CUSTOM_LAYOUT_ID
            )
            layoutIndices = list(layoutNode.GetLayoutIndices())
            self.assertTrue(widget._activatePresentation())
            self.assertEqual(list(layoutNode.GetLayoutIndices()), layoutIndices)

            for viewName, viewLabel in (
                (widget.LIVE_VIEW_NAME, widget.LIVE_VIEW_LABEL),
                (widget.RESULT_VIEW_NAME, widget.RESULT_VIEW_LABEL),
            ):
                sliceWidget = layoutManager.sliceWidget(viewName)
                self.assertIsNotNone(sliceWidget)
                self.assertEqual(sliceWidget.mrmlSliceNode().GetName(), viewName)
                self.assertEqual(
                    sliceWidget.mrmlSliceNode().GetLayoutLabel(), viewLabel
                )
                compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
                self.assertIsNone(compositeNode.GetBackgroundVolumeID())
                self.assertIsNone(compositeNode.GetForegroundVolumeID())
                self.assertIsNone(compositeNode.GetLabelVolumeID())

            # The waiting message must survive the event loop. The shared
            # corner annotation does not: DataProbe blanks all four corners of
            # every slice view once its observers run, so this assertion only
            # holds for a module-owned actor.
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
            resultRenderer = widget._sliceViewRenderer(resultWidget)
            liveRenderer = widget._sliceViewRenderer(liveWidget)
            self.assertIsNotNone(resultRenderer)
            actor = widget._waitingAnnotationActor
            self.assertIsNotNone(actor)
            self.assertEqual(actor.GetInput(), widget.WAITING_RESULT_MESSAGE)
            self.assertFalse(liveRenderer.HasViewProp(actor))

            self._settleEventLoop()
            resultWidget.mrmlSliceNode().Modified()
            resultWidget.sliceLogic().GetSliceCompositeNode().Modified()
            self._settleEventLoop()

            self.assertTrue(resultRenderer.HasViewProp(actor))
            self.assertEqual(actor.GetInput(), widget.WAITING_RESULT_MESSAGE)

            widget._deactivatePresentation(restore=True)
            self.assertFalse(resultRenderer.HasViewProp(actor))
            self.assertFalse(widget._presentationActive)
            self.assertEqual(
                int(layoutNode.GetViewArrangement()),
                previousLayout,
                "Leaving the module must restore the previous Slicer layout",
            )
        finally:
            widget._deactivatePresentation(restore=True)
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

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
        parameterNode = parameters.parameterNode
        self.assertEqual(
            parameterNode.GetNodeReferenceID("liveVolume"),
            liveVolume.GetID(),
        )
        self.assertEqual(
            parameterNode.GetNodeReferenceID("resultVolume"),
            resultVolume.GetID(),
        )
        self.assertEqual(parameters.liveVolume.GetID(), liveVolume.GetID())
        self.assertEqual(parameters.resultVolume.GetID(), resultVolume.GetID())
