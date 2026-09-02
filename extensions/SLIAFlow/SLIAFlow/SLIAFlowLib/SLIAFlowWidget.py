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
    RESULT_SOURCE_SIMULATED_ORIGIN,
    SIMULATED_BANNER_MESSAGE,
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
    SIMULATED_STATUS_PREFIX = _("SIMULATED: ")
    DEMO_MODE_ACTIVE_STATUS = _(
        "Demo mode is on. An externally produced simulated result may be "
        "displayed, always under the SIMULATED banner."
    )
    SIMULATED_BANNER_FONT_SIZE = 16
    SIMULATED_DETAIL_FONT_SIZE = 11
    SIMULATED_BANNER_POSITION = (0.5, 0.94)
    SIMULATED_DETAIL_POSITION = (0.5, 0.90)
    SIMULATED_BANNER_BACKGROUND = (0.45, 0.0, 0.0)
    RESULT_INVALID_STATUS = _("Invalid genuine UC1 result.")
    RESULT_INVALID_SIMULATED_STATUS = _("Invalid simulated UC1 result.")
    BANNER_UNAVAILABLE_STATUS = _(
        "The SIMULATED banner could not be drawn, so the simulated result was "
        "withheld."
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
        self._layoutBeforeSceneClose: int | None = None
        self._presentationActive = False
        self._waitingAnnotationActor = None
        self._waitingAnnotationRenderer = None
        # Demo mode is deliberately transient widget state and is never
        # written to the parameter node, so no saved scene can reopen with
        # simulated results already permitted.
        self._demoModeEnabled = False
        self._simulatedBannerActor = None
        self._simulatedDetailActor = None
        self._simulatedBannerRenderer = None
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
        demoModeCheckBox = getattr(self.ui, "demoModeCheckBox", None)
        if demoModeCheckBox is not None:
            demoModeCheckBox.connect("toggled(bool)", self._onDemoModeToggled)
        self._resetDemoMode()
        self.initializeParameterNode()
        self._setCameraSupportState(self.logic.openCVAvailable())
        self._setResultStatus("WARN", self.RESULT_WAITING_STATUS)

    def cleanup(self) -> None:
        self._resetDemoMode()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        if self.logic is not None and self._parameterNode is not None:
            self.logic.clearResultReferences(self._parameterNode)
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self._resetDemoMode()
        self.initializeParameterNode()
        self._activatePresentation()
        if self.logic is not None:
            self._setCameraSupportState(self.logic.openCVAvailable())

    def exit(self) -> None:
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self._resetDemoMode()
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

    def _onDemoModeToggled(self, enabled=None) -> None:
        checkBox = getattr(self.ui, "demoModeCheckBox", None)
        if enabled is None:
            enabled = False if checkBox is None else checkBox.isChecked()
        self._demoModeEnabled = bool(enabled)
        if not self._demoModeEnabled:
            self._removeSimulatedBanner()
        self._updateDemoModeIndicator()
        if self._presentationActive:
            self._refreshResultPresentation()

    def _resetDemoMode(self) -> None:
        """Return demo mode to off without re-entering the toggle handler."""
        self._demoModeEnabled = False
        self._removeSimulatedBanner()
        checkBox = getattr(getattr(self, "ui", None), "demoModeCheckBox", None)
        if checkBox is not None:
            blocked = checkBox.blockSignals(True)
            checkBox.setChecked(False)
            checkBox.blockSignals(blocked)
        self._updateDemoModeIndicator()

    def _updateDemoModeIndicator(self) -> None:
        label = getattr(getattr(self, "ui", None), "simulatedBannerLabel", None)
        if label is None:
            return
        label.setText(self.DEMO_MODE_ACTIVE_STATUS)
        label.setVisible(self._demoModeEnabled)

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

        report = self.logic.presentSelectedResult(
            self._parameterNode, allowSimulated=self._demoModeEnabled
        )
        simulated = report.get("dataOrigin") == RESULT_SOURCE_SIMULATED_ORIGIN
        if report["summaryStatus"] == "PASS":
            # The banner is asserted before the volume reaches the view, and
            # re-asserted on every PASS refresh because the slice view rebuilds
            # its actors. A banner that cannot be drawn is fatal rather than
            # cosmetic: an unbannered frame of simulated data is precisely what
            # the medical-data policy forbids, so the result is withheld.
            if not self._updateSimulatedBanner(
                simulated, report.get("simulationDetail")
            ):
                self.logic.clearResultReferences(self._parameterNode)
                self._clearResultView()
                self._setResultStatus("FAIL", self.BANNER_UNAVAILABLE_STATUS)
                return dict(
                    report,
                    summaryStatus="FAIL",
                    summaryMessage=self.BANNER_UNAVAILABLE_STATUS,
                )
            # The single flush of the view. _displayResultVolume renders once
            # the banner state and the volume state already agree, so neither
            # can be painted without the other.
            self._displayResultVolume()
            message = report["summaryMessage"]
            if simulated:
                message = self.SIMULATED_STATUS_PREFIX + message
            self._setResultStatus(
                "PASS",
                message,
                report.get("sourceNodeName"),
            )
        else:
            self.logic.clearResultReferences(self._parameterNode)
            self._clearResultView()
            if report["summaryStatus"] == "FAIL":
                invalidStatus = (
                    self.RESULT_INVALID_SIMULATED_STATUS
                    if simulated
                    else self.RESULT_INVALID_STATUS
                )
                self._setResultStatus(
                    "FAIL",
                    f"{invalidStatus} {report['summaryMessage']}",
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
            self._removeSimulatedBanner()
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

    @staticmethod
    def _placeAnnotationActor(renderer, actor, previousRenderer=None):
        """Attach one annotation actor to the renderer now on screen.

        A slice view rebuilds its renderer, so an actor can still be held by
        a renderer that is no longer displayed; it is detached from that one
        before being added to the current one.
        """
        if renderer is None or actor is None:
            return None
        if previousRenderer is not None and previousRenderer is not renderer:
            try:
                previousRenderer.RemoveActor2D(actor)
            except (RuntimeError, ValueError):
                pass
        if not renderer.HasViewProp(actor):
            renderer.AddActor2D(actor)
        return renderer

    @classmethod
    def _createBannerActor(cls, text, fontSize, position, bold):
        actor = vtk.vtkTextActor()
        actor.SetInput(text)
        actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        actor.SetPosition(position[0], position[1])
        textProperty = actor.GetTextProperty()
        textProperty.SetFontSize(fontSize)
        textProperty.SetBold(bool(bold))
        textProperty.SetColor(1.0, 1.0, 1.0)
        textProperty.SetBackgroundColor(*cls.SIMULATED_BANNER_BACKGROUND)
        textProperty.SetBackgroundOpacity(1.0)
        textProperty.SetFrame(1)
        textProperty.SetFrameColor(1.0, 1.0, 1.0)
        textProperty.SetJustificationToCentered()
        textProperty.SetVerticalJustificationToTop()
        return actor

    def _showSimulatedBanner(self, sliceWidget, detail=None) -> bool:
        """Draw the simulated banner, and its detail line when there is one.

        A vtkTextActor carries one text property for its whole string, so the
        smaller second line has to be a second actor. The two are placed,
        re-asserted and removed together, so the detail can never outlive the
        banner that qualifies it.
        """
        renderer = self._sliceViewRenderer(sliceWidget)
        if renderer is None:
            return False

        if self._simulatedBannerActor is None:
            self._simulatedBannerActor = self._createBannerActor(
                SIMULATED_BANNER_MESSAGE,
                self.SIMULATED_BANNER_FONT_SIZE,
                self.SIMULATED_BANNER_POSITION,
                bold=True,
            )

        if not detail:
            self._detachSimulatedDetail()
        elif self._simulatedDetailActor is None:
            self._simulatedDetailActor = self._createBannerActor(
                detail,
                self.SIMULATED_DETAIL_FONT_SIZE,
                self.SIMULATED_DETAIL_POSITION,
                bold=False,
            )
        else:
            self._simulatedDetailActor.SetInput(detail)

        previousRenderer = self._simulatedBannerRenderer
        self._simulatedBannerRenderer = self._placeAnnotationActor(
            renderer, self._simulatedBannerActor, previousRenderer
        )
        if self._simulatedDetailActor is not None:
            self._placeAnnotationActor(
                renderer, self._simulatedDetailActor, previousRenderer
            )
        return self._simulatedBannerRenderer is not None

    def _updateSimulatedBanner(
        self, simulated: bool, detail=None, layoutManager=None
    ) -> bool:
        """Bring the banner into agreement with the origin about to be shown.

        Nothing is rendered here. The caller flushes the view once, after the
        result volume is in place, so no frame can be painted with the banner
        state and the volume state disagreeing: neither a simulated map before
        its banner, nor a genuine map still under one.

        Returns whether the view now matches the requested state. False means
        the banner was required and could not be drawn.
        """
        if not simulated:
            self._removeSimulatedBanner()
            return True
        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        resultWidget = None
        if layoutManager is not None:
            try:
                resultWidget = layoutManager.sliceWidget(self.RESULT_VIEW_NAME)
            except RuntimeError:
                resultWidget = None
        if resultWidget is None:
            # There is no result view, so _displayResultVolume paints nothing
            # into one either. Nothing can be seen unbannered, so this is not
            # the failure the caller has to withhold a result over.
            self._removeSimulatedBanner()
            return True
        if not self._showSimulatedBanner(resultWidget, detail):
            self._removeSimulatedBanner()
            return False
        return True

    def _detachSimulatedDetail(self) -> None:
        renderer = self._simulatedBannerRenderer
        actor = self._simulatedDetailActor
        self._simulatedDetailActor = None
        if renderer is None or actor is None:
            return
        try:
            renderer.RemoveActor2D(actor)
        except (RuntimeError, ValueError):
            pass

    def _removeSimulatedBanner(self) -> None:
        renderer = self._simulatedBannerRenderer
        actors = (self._simulatedBannerActor, self._simulatedDetailActor)
        self._simulatedBannerRenderer = None
        self._simulatedBannerActor = None
        self._simulatedDetailActor = None
        if renderer is None:
            return
        for actor in actors:
            if actor is None:
                continue
            try:
                renderer.RemoveActor2D(actor)
            except (RuntimeError, ValueError):
                pass

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

        self._waitingAnnotationRenderer = self._placeAnnotationActor(
            renderer, self._waitingAnnotationActor, self._waitingAnnotationRenderer
        )
        return self._waitingAnnotationRenderer is not None

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
        self._removeSimulatedBanner()
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
