import logging
from typing import Any
from xml.sax.saxutils import escape

import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

from .SLIAFlowLogic import SLIAFlowLogic
from .SLIAFlowParameterNode import (
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_SVM_PROB,
    SLIAFlowParameterNode,
)


class SLIAFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Present the live image and the validated UC1 result side by side."""

    CUSTOM_LAYOUT_ID = 701
    LIVE_VIEW_NAME = "SLIAFlowLive"
    RESULT_VIEW_NAME = "SLIAFlowResult"
    VIEW_NAMES = (LIVE_VIEW_NAME, RESULT_VIEW_NAME)
    LIVE_VIEW_LABEL = _("Live Image")
    RESULT_VIEW_LABEL = _("UC1 Result")
    WAITING_RESULT_MESSAGE = _("Waiting for genuine UC1 result")
    LAYOUT_CONFLICT_STATUS = _(
        "SLIAFlow could not activate layout 701 because another layout uses "
        "that reserved identifier."
    )
    LAYOUT_UNAVAILABLE_STATUS = _(
        "The SLIAFlow two-pane layout is not available in this Slicer window."
    )
    CAMERA_SUPPORT_MISSING_STATUS = _(
        "Camera support is not installed. Choose Install Camera Support, then "
        "restart Slicer."
    )
    CAMERA_READY_STATUS = _(
        "Camera support is ready. Press Start to show the laptop camera."
    )
    CAMERA_INSTALLING_STATUS = _("Installing camera support...")
    CAMERA_INSTALL_RESTART_MESSAGE = _(
        "Camera support was installed. Restart Slicer before starting the camera."
    )
    CAMERA_INSTALL_FAILED_STATUS = _(
        "Camera support installation failed. Check the Python console for the "
        "package installation error."
    )
    RESULT_WAITING_STATUS = _("Waiting for genuine UC1 result.")
    RESULT_INVALID_STATUS = _("Invalid genuine UC1 result.")
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
        self._layoutBeforeSceneClose: int | None = None
        self._presentationActive = False
        self._waitingAnnotationActor = None
        self._waitingAnnotationRenderer = None
        self._cameraSupportAvailable = False
        self._cameraRestartRequired = False

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
        self.ui.installCameraSupportButton.connect(
            "clicked()", self._installCameraSupport
        )
        self.ui.startButton.connect("clicked()", self._startCamera)
        self.ui.stopButton.connect("clicked()", self._onStopCamera)
        self.ui.resultMapSelector.connect(
            "currentIndexChanged(int)", self._onResultSelectionChanged
        )
        self.ui.resultClassSpinBox.connect(
            "valueChanged(int)", self._onResultSelectionChanged
        )
        self.ui.refreshResultButton.connect(
            "clicked()", self._refreshResultPresentation
        )
        self.initializeParameterNode()
        self._setCameraSupportState(self.logic.openCVAvailable())
        self._setResultStatus("WARN", self.RESULT_WAITING_STATUS)

    def cleanup(self) -> None:
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        if self.logic is not None and self._parameterNode is not None:
            self.logic.clearResultReferences(self._parameterNode)
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self._activatePresentation()
        if self.logic is not None:
            self._setCameraSupportState(self.logic.openCVAvailable())

    def exit(self) -> None:
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self._rememberLayoutBeforeSceneClose()
        self._stopCamera(clearLiveView=True)
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
            self._configureResultControls()

    def _onResultSelectionChanged(self, caller=None, event=None) -> None:
        if self._parameterNode is not None and self.logic is not None:
            resultMap = self.ui.resultMapSelector.currentText
            if resultMap in self.logic.supportedResultMaps():
                self._parameterNode.resultMap = resultMap
            self._parameterNode.resultClass = int(self.ui.resultClassSpinBox.value)
        self._configureResultControls()
        if self._presentationActive:
            self._refreshResultPresentation()

    def _configureResultControls(self) -> None:
        liveSourceSelector = getattr(self.ui, "liveSourceSelector", None)
        if liveSourceSelector is not None:
            liveSourceSelector.setEnabled(False)

        resultMapSelector = getattr(self.ui, "resultMapSelector", None)
        if resultMapSelector is not None:
            resultMapSelector.setEnabled(self._presentationActive)

        resultClassSpinBox = getattr(self.ui, "resultClassSpinBox", None)
        if resultClassSpinBox is not None:
            resultMap = (
                self._parameterNode.resultMap
                if self._parameterNode is not None
                else None
            )
            resultClassSpinBox.setEnabled(
                self._presentationActive
                and resultMap in (RESULT_MAP_SVM_PROB, RESULT_MAP_KNN_PROB)
            )

        refreshButton = getattr(self.ui, "refreshResultButton", None)
        if refreshButton is not None:
            refreshButton.setEnabled(self._presentationActive)
        self._refreshCameraControls()

    def _refreshCameraControls(self) -> None:
        if self.logic is None:
            return
        cameraActive = self.logic.cameraActive
        self.ui.installCameraSupportButton.setEnabled(
            not self._cameraSupportAvailable
            and not self._cameraRestartRequired
            and not cameraActive
        )
        self.ui.cameraIndexSpinBox.setEnabled(
            self._cameraSupportAvailable and not cameraActive
        )
        self.ui.startButton.setEnabled(
            self._cameraSupportAvailable and not cameraActive
        )
        self.ui.stopButton.setEnabled(cameraActive)

    def _setCameraSupportState(self, available: bool) -> None:
        if self._cameraRestartRequired:
            self._cameraSupportAvailable = False
            self._refreshCameraControls()
            self._setStatus(self.CAMERA_INSTALL_RESTART_MESSAGE)
            return
        self._cameraSupportAvailable = bool(available)
        self._refreshCameraControls()
        if self.logic is not None and self.logic.cameraActive:
            return
        self._setStatus(
            self.CAMERA_READY_STATUS
            if self._cameraSupportAvailable
            else self.CAMERA_SUPPORT_MISSING_STATUS
        )

    def _installCameraSupport(self) -> None:
        if self.logic is None:
            return
        self.ui.installCameraSupportButton.setEnabled(False)
        self._setStatus(self.CAMERA_INSTALLING_STATUS)
        slicer.app.processEvents()
        try:
            slicer.util.pip_install(self.logic.OPENCV_REQUIREMENT)
        except Exception:
            logging.exception("Failed to install SLIAFlow camera support")
            self._setStatus(self.CAMERA_INSTALL_FAILED_STATUS)
            self.ui.installCameraSupportButton.setEnabled(True)
            return
        self._cameraRestartRequired = True
        self._cameraSupportAvailable = False
        self._refreshCameraControls()
        self._setStatus(self.CAMERA_INSTALL_RESTART_MESSAGE)
        slicer.util.infoDisplay(
            self.CAMERA_INSTALL_RESTART_MESSAGE,
            windowTitle=_("Restart Slicer"),
        )

    def _startCamera(self) -> None:
        if self.logic is None or self._parameterNode is None:
            return
        self._clearLiveView()
        cameraIndex = int(self._parameterNode.cameraIndex)
        started = self.logic.startCamera(
            cameraIndex,
            self._displayCameraFrame,
            self._handleCameraError,
        )
        self._refreshCameraControls()
        if started:
            self._setStatus(
                _("Laptop camera {cameraIndex} is live.").format(
                    cameraIndex=cameraIndex
                )
            )

    def _onStopCamera(self) -> None:
        self._stopCamera(clearLiveView=True)
        self._setStatus(self.CAMERA_READY_STATUS)

    def _handleCameraError(self, message: str) -> None:
        self._stopCamera(clearLiveView=True)
        self._setStatus(message)

    def _stopCamera(self, clearLiveView: bool, layoutManager=None) -> None:
        if self.logic is not None:
            self.logic.stopCamera()
        if clearLiveView:
            self._clearLiveView(layoutManager=layoutManager)
        self._refreshCameraControls()

    def _clearLiveView(self, layoutManager=None) -> None:
        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        try:
            sliceWidget = layoutManager.sliceWidget(self.LIVE_VIEW_NAME)
            if sliceWidget is None:
                return
            self._clearSliceLayers(sliceWidget)
            sliceView = sliceWidget.sliceView()
            if sliceView is not None:
                sliceView.forceRender()
        except RuntimeError:
            return

    def _displayCameraFrame(self, rgbKjiFrame, layoutManager=None) -> None:
        if self.logic is None or self._parameterNode is None:
            return
        liveNode = self.logic.getOrCreateLiveVolume(self._parameterNode)
        slicer.util.updateVolumeFromArray(liveNode, rgbKjiFrame)

        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        liveWidget = layoutManager.sliceWidget(self.LIVE_VIEW_NAME)
        if liveWidget is None:
            return
        liveLogic = liveWidget.sliceLogic()
        liveComposite = liveLogic.GetSliceCompositeNode()
        if liveComposite.GetBackgroundVolumeID() != liveNode.GetID():
            liveComposite.SetBackgroundVolumeID(liveNode.GetID())
            liveComposite.SetForegroundVolumeID(None)
            liveComposite.SetLabelVolumeID(None)
            liveLogic.FitSliceToBackground()
        liveView = liveWidget.sliceView()
        if liveView is not None:
            liveView.forceRender()

    def _setStatus(self, message: str) -> None:
        statusLabel = getattr(self.ui, "statusLabel", None)
        if statusLabel is not None:
            statusLabel.setText(message)

    def _setResultStatus(self, status: str, message: str, sourceName=None) -> None:
        resultStatusLabel = getattr(self.ui, "resultStatusLabel", None)
        if resultStatusLabel is not None:
            resultStatusLabel.setText(_("{0}: {1}").format(status, message))
            colors = {
                "PASS": "#1B5E20",
                "WARN": "#8A6D1D",
                "FAIL": "#8B1E1E",
            }
            resultStatusLabel.setStyleSheet(
                "color: {0}; font-weight: bold;".format(
                    colors.get(status, "#333333")
                )
            )
        sourceValueLabel = getattr(self.ui, "resultSourceValueLabel", None)
        if sourceValueLabel is not None:
            sourceValueLabel.setText(sourceName or _("None"))

    def _refreshResultPresentation(self, caller=None, event=None) -> dict:
        if self.logic is None or self._parameterNode is None:
            return {"summaryStatus": "WARN", "summaryMessage": "No parameter node."}

        report = self.logic.presentSelectedResult(self._parameterNode)
        if report["summaryStatus"] == "PASS":
            self._displayResultVolume()
            self._setResultStatus(
                "PASS",
                report["summaryMessage"],
                report.get("sourceNodeName"),
            )
        else:
            self.logic.clearResultReferences(self._parameterNode)
            self._clearResultView()
            if report["summaryStatus"] == "FAIL":
                self._setResultStatus(
                    "FAIL",
                    f"{self.RESULT_INVALID_STATUS} {report['summaryMessage']}",
                )
            else:
                self._setResultStatus("WARN", report["summaryMessage"])
        return report

    def _clearResultView(self, layoutManager=None) -> None:
        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        try:
            resultWidget = layoutManager.sliceWidget(self.RESULT_VIEW_NAME)
            if resultWidget is None:
                return
            self._clearSliceLayers(resultWidget)
            self._showWaitingAnnotation(resultWidget)
            resultView = resultWidget.sliceView()
            if resultView is not None:
                resultView.forceRender()
        except RuntimeError:
            return

    def _displayResultVolume(self, layoutManager=None) -> None:
        if self._parameterNode is None:
            return
        resultNode = self._parameterNode.resultVolume
        if resultNode is None:
            return
        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        resultWidget = layoutManager.sliceWidget(self.RESULT_VIEW_NAME)
        if resultWidget is None:
            return
        resultLogic = resultWidget.sliceLogic()
        resultComposite = resultLogic.GetSliceCompositeNode()
        if resultComposite.GetBackgroundVolumeID() != resultNode.GetID():
            resultComposite.SetBackgroundVolumeID(resultNode.GetID())
            resultComposite.SetForegroundVolumeID(None)
            resultComposite.SetLabelVolumeID(None)
            resultLogic.FitSliceToBackground()
        self._removeWaitingAnnotation()
        resultView = resultWidget.sliceView()
        if resultView is not None:
            resultView.forceRender()

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

    @staticmethod
    def _isRestorableLayout(layout) -> bool:
        if layout is None:
            return False
        return int(layout) != slicer.vtkMRMLLayoutNode.SlicerLayoutNone

    def _rememberLayoutBeforeSceneClose(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        layout = int(layoutNode.GetViewArrangement())
        if layout != self.CUSTOM_LAYOUT_ID and self._isRestorableLayout(layout):
            self._layoutBeforeSceneClose = layout

    def _activatePresentation(self) -> bool:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return False

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        if not self._registerCustomLayout(layoutNode):
            return False

        currentLayout = int(layoutNode.GetViewArrangement())
        candidateLayout = currentLayout
        if not self._isRestorableLayout(candidateLayout):
            candidateLayout = self._layoutBeforeSceneClose
        if (
            not self._presentationActive
            and self._previousLayout is None
            and candidateLayout is not None
            and candidateLayout != self.CUSTOM_LAYOUT_ID
            and self._isRestorableLayout(candidateLayout)
        ):
            self._previousLayout = candidateLayout

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
        self._configureResultControls()
        self._refreshResultPresentation()
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
                continue

    def _deactivatePresentation(self, restore: bool) -> None:
        layoutManager = slicer.app.layoutManager()
        previousLayout = self._previousLayout
        if not self._isRestorableLayout(previousLayout):
            previousLayout = None

        self._removeWaitingAnnotation()
        if layoutManager is not None:
            layoutNode = layoutManager.layoutLogic().GetLayoutNode()
            if int(layoutNode.GetViewArrangement()) == self.CUSTOM_LAYOUT_ID:
                self._clearPresentation(layoutManager)
                if restore:
                    layoutManager.setLayout(
                        previousLayout
                        if previousLayout is not None
                        else slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView
                    )

        self._previousLayout = None if restore else previousLayout
        if restore:
            self._layoutBeforeSceneClose = None
        self._presentationActive = False
        if hasattr(self, "ui"):
            self._configureResultControls()
