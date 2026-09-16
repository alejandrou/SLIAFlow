import logging
import time
from typing import Any
from xml.sax.saxutils import escape

import qt
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

from .SLIAFlowLogic import SLIAFlowLogic
from .SLIAFlowParameterNode import (
    ACQUISITION_PORT,
    CAPTURE_REPLY_DEVICE_NAME,
    CAPTURE_STATUS_DEVICE_NAME,
    CONNECTION_CONNECTING,
    CONNECTION_DISCONNECTED,
    CONNECTION_DISPLAYING,
    CONNECTION_INVALID,
    CONNECTION_RECEIVING,
    CONNECTOR_ACQUISITION,
    CONNECTOR_CONTROL,
    CONNECTOR_HS_CUBE,
    CONNECTOR_ROLES,
    CONNECTOR_UC1,
    CONNECTOR_UC2,
    CONTROL_PORT,
    HS_CUBE_PORT,
    IGTL_HOST,
    LIVE_SOURCE_CHOICES,
    LIVE_SOURCE_IGTL,
    LIVE_SOURCE_LAPTOP,
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_SVM_PROB,
    RESULT_SOURCE_SIMULATED_ORIGIN,
    STEREOSCOPIC_PORT,
    STO2_PORT,
    UC2_DEVICE_NAME,
    UC2_PORT,
    UC2_SIMULATED_BANNER_MESSAGE,
    SLIAFlowParameterNode,
    simulatedBannerMessage,
)


def _sliceViewItem(viewName: str, viewLabel: str) -> str:
    return (
        "<item>"
        f'<view class="vtkMRMLSliceNode" singletontag="{viewName}">'
        '<property name="orientation" action="default">Axial</property>'
        f'<property name="viewlabel" action="default">{escape(viewLabel)}</property>'
        "</view>"
        "</item>"
    )


def _layoutDescription(rows) -> str:
    """Two rows of views, each row one horizontal layout inside a vertical one."""
    return (
        '<layout type="vertical" split="true">'
        + "".join(
            '<item><layout type="horizontal" split="true">'
            + "".join(_sliceViewItem(name, label) for name, label in row)
            + "</layout></item>"
            for row in rows
        )
        + "</layout>"
    )


class SLIAFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Present the six-panel WP5 operator surface."""

    # 702 rather than the two-pane 701, so that a Reload in a session whose
    # layout node still holds 701's old description does not collide with it.
    CUSTOM_LAYOUT_ID = 702
    LIVE_VIEW_NAME = "SLIAFlowLive"
    STEREO_VIEW_NAME = "SLIAFlowStereoscopic"
    CUBE_VIEW_NAME = "SLIAFlowCube"
    STO2_VIEW_NAME = "SLIAFlowStO2"
    VASCULAR_VIEW_NAME = "SLIAFlowVascularization"
    RESULT_VIEW_NAME = "SLIAFlowResult"
    LIVE_VIEW_LABEL = _("LiveView")
    STEREO_VIEW_LABEL = _("Stereoscopic")
    CUBE_VIEW_LABEL = _("HS Cube")
    STO2_VIEW_LABEL = _("Relative StO2")
    VASCULAR_VIEW_LABEL = _("Enhanced Vascularization")
    RESULT_VIEW_LABEL = _("Tumour Delineation")
    # The target screen in docs/architecture/WP5_MS5_DEMO_PLAN.md.
    VIEW_ROWS = (
        (
            (LIVE_VIEW_NAME, LIVE_VIEW_LABEL),
            (STEREO_VIEW_NAME, STEREO_VIEW_LABEL),
            (CUBE_VIEW_NAME, CUBE_VIEW_LABEL),
        ),
        (
            (STO2_VIEW_NAME, STO2_VIEW_LABEL),
            (VASCULAR_VIEW_NAME, VASCULAR_VIEW_LABEL),
            (RESULT_VIEW_NAME, RESULT_VIEW_LABEL),
        ),
    )
    VIEW_NAMES = tuple(name for row in VIEW_ROWS for name, _label in row)
    # A reserved panel says what is missing and which port waits for it, so it
    # can never be mistaken for a panel that is black because something broke.
    RESERVED_PANEL_REASONS = {
        STEREO_VIEW_NAME: _(
            "No producer yet: stereoscopic depth from UPM.\n"
            "Port {port} is reserved for it."
        ).format(port=STEREOSCOPIC_PORT),
        STO2_VIEW_NAME: _(
            "No algorithm yet: relative StO2 from ULPGC.\n"
            "Port {port} is reserved for it."
        ).format(port=STO2_PORT),
    }
    CUBE_WAITING_MESSAGE = _(
        "Waiting for the HS cube on port {port}.\nPress Capture."
    ).format(port=HS_CUBE_PORT)
    UC2_WAITING_MESSAGE = _(
        "Waiting for the UC2 blood-vessel map on port {port}."
    ).format(port=UC2_PORT)
    # The LiveView panel says what it is waiting for in the panel itself. A
    # status line elsewhere in the module leaves a black panel looking exactly
    # like one that is black because something broke.
    LIVE_WAITING_MESSAGE = _(
        "Waiting for the LiveView image.\n"
        "Start the laptop camera, or press Connect links for the stream on "
        "port {port}."
    ).format(port=ACQUISITION_PORT)
    HIDDEN_LAYER_MESSAGE = _("{layer} is hidden in the layer list.")
    LAYER_UC1 = "uc1"
    LAYER_UC2 = "uc2"
    LAYER_ROWS = (
        (LAYER_UC1, _("Tumour delineation (UC1)"), RESULT_VIEW_NAME),
        (LAYER_UC2, _("Enhanced vascularization (UC2)"), VASCULAR_VIEW_NAME),
    )
    LINK_STATE_LABELS = {
        CONNECTOR_ACQUISITION: "acquisitionStateValueLabel",
        CONNECTOR_UC1: "uc1StateValueLabel",
        CONNECTOR_UC2: "uc2StateValueLabel",
        CONNECTOR_HS_CUBE: "hsCubeStateValueLabel",
        CONNECTOR_CONTROL: "controlStateValueLabel",
    }
    CAPTURE_NEEDS_CONTROL_LINK_STATUS = _(
        "Capture needs the control link to the acquisition stand-in on "
        "{host}:{port}. Press Connect links."
    ).format(host=IGTL_HOST, port=CONTROL_PORT)
    CAPTURE_NO_ANSWER_STATUS = _(
        "The control link is connected. The stand-in has not reported a state yet."
    )
    UC2_STALE_STATUS = _(
        "The UC2 link is not connected. The last valid map is still shown and "
        "is not being updated."
    )
    UC2_INVALID_STATUS = _("Invalid UC2 map.")
    UC2_INVALID_SIMULATED_STATUS = _("Invalid simulated UC2 map.")
    UC2_INVALID_PROVENANCE_STATUS = _(
        "Unrecognized UC2 provenance. The data arrived but does not say what it "
        "is, so it is not displayed."
    )
    WAITING_RESULT_MESSAGE = _("Waiting for genuine UC1 result")
    LAYOUT_CONFLICT_STATUS = _(
        "SLIAFlow could not activate layout 701 because another layout uses "
        "that reserved identifier."
    )
    LAYOUT_UNAVAILABLE_STATUS = _(
        "The SLIAFlow six-panel layout is not available in this Slicer window."
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
    RESULT_BACKGROUND_NONE_STATUS = _("None")
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
    RESULT_INVALID_PROVENANCE_STATUS = _(
        "Unrecognized UC1 provenance. The data arrived but does not say what "
        "it is, so it is not displayed."
    )
    RESULT_STALE_STATUS = _(
        "The UC1 link is not connected. The last valid result is still shown "
        "and is not being updated."
    )
    LIVE_STALE_STATUS = _(
        "The acquisition link is not connected. The last received frame is "
        "still shown and is not being updated."
    )
    OPENIGTLINK_UNAVAILABLE_STATUS = _(
        "This Slicer build has no OpenIGTLink support, so the network links "
        "are unavailable. The laptop camera still works."
    )
    LIVE_VIEW_WAITING_STATUS = _("Waiting for the LiveView stream.")
    # DeviceModifiedEvent fires once per received frame. Revalidating and
    # re-presenting the result map at the sender's frame rate would spend the
    # UI thread on work whose answer cannot change that fast, so result
    # refreshes triggered by the wire are throttled. A refresh the operator
    # asks for is never throttled.
    RESULT_REFRESH_INTERVAL_SEC = 0.2
    # How often the connector's own state is read, because the event that
    # announces a lost link never arrives. See _pollLinkStates. One second is
    # far below the point where an operator would read a dead label as live,
    # and the poll is three attribute reads per link.
    LINK_STATE_POLL_INTERVAL_SEC = 1.0
    BANNER_UNAVAILABLE_STATUS = _(
        "The SIMULATED banner could not be drawn, so the simulated result was "
        "withheld."
    )
    CUSTOM_LAYOUT_DESCRIPTION = _layoutDescription(VIEW_ROWS)

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
        self._connectionStates = dict.fromkeys(CONNECTOR_ROLES, CONNECTION_DISCONNECTED)
        # One callback per role per observed event, created once and kept. See
        # _connectorCallbacks: the identity of the callback is what carries the
        # event, and it is also the key the observation bookkeeping uses.
        self._connectorEventCallbacks: dict[str, dict] = {}
        # Whether anything valid has ever reached each pane. It decides what a
        # disconnection looks like: a stale last image, or black.
        self._resultEverDisplayed = False
        self._liveViewEverDisplayed = False
        self._uc2EverDisplayed = False
        self._lastUc2Simulated = False
        # Panel text other than the result view's waiting annotation: reserved
        # reasons, waiting text and hidden-layer text, one actor per view.
        self._panelAnnotationActors: dict[str, Any] = {}
        self._panelAnnotationRenderers: dict[str, Any] = {}
        self._panelMessages: dict[str, str] = {}
        self._uc2BannerActor = None
        self._uc2DetailActor = None
        self._uc2BannerRenderer = None
        # Layer display state. Transient, like demo mode: it decides how a
        # result is drawn, never whether it is shown under its banner.
        self._layerVisible = {layer: True for layer, _label, _view in self.LAYER_ROWS}
        self._layerOpacity = {layer: 1.0 for layer, _label, _view in self.LAYER_ROWS}
        self._layerStatusText = {layer: "" for layer, _label, _view in self.LAYER_ROWS}
        self._cubeBandCount = 0
        self._cubeWavelengths = None
        self._cubeWavelengthReason = ""
        # Whether a link that had connected or presented data was then lost.
        # A connector that only ever waited leaves no history. Connector state is the
        # authority for what the wire is doing now; this history keeps a
        # retained node stale until a later received node update proves that
        # the current connection has delivered new data.
        # The HS cube and control links retain no presented image, so they
        # carry no stale history.
        self._linkDropped = {
            CONNECTOR_ACQUISITION: False,
            CONNECTOR_UC1: False,
            CONNECTOR_UC2: False,
        }
        # A reconnect must not promote the node left by the previous socket.
        # Store its identity and modification time at disconnect so that an
        # actual update from the new socket can clear _linkDropped without
        # mistaking a map selection change for new wire data.
        self._linkDropSnapshots = {
            CONNECTOR_ACQUISITION: None,
            CONNECTOR_UC1: None,
            CONNECTOR_UC2: None,
        }
        self._lastResultSimulated = False
        self._lastResultRefreshTime = 0.0
        # Set when a wire event arrived inside the throttle window and a
        # trailing refresh is owed to it.
        self._pendingResultRefresh = False
        # Runs while any link is up. See _pollLinkStates for why a panel that
        # observes six connector events still has to read the state itself.
        self._linkStateTimer = None

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
        self.ui.liveSourceSelector.connect(
            "currentIndexChanged(int)", self._onLiveSourceChanged
        )
        self.ui.connectLinksButton.connect("toggled(bool)", self._onConnectLinksToggled)
        self.ui.captureButton.connect("clicked()", self._onCaptureClicked)
        self.ui.bandSlider.connect("valueChanged(int)", self._setCubeBand)
        self._setupLayerTable()
        demoModeCheckBox = getattr(self.ui, "demoModeCheckBox", None)
        if demoModeCheckBox is not None:
            demoModeCheckBox.connect("toggled(bool)", self._onDemoModeToggled)
        self._resetDemoMode()
        self.initializeParameterNode()
        self._setCameraSupportState(self.logic.openCVAvailable())
        self._setResultStatus("WARN", self.RESULT_WAITING_STATUS)
        self._refreshConnectionControls()

    def cleanup(self) -> None:
        self._pendingResultRefresh = False
        self._resetDemoMode()
        self._disconnectAllLinks()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        if self.logic is not None and self._parameterNode is not None:
            self.logic.clearResultReferences(self._parameterNode)
            self.logic.clearResultBackgroundReferences(self._parameterNode)
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self._resetDemoMode()
        self.initializeParameterNode()
        self._activatePresentation()
        if self.logic is not None:
            self._setCameraSupportState(self.logic.openCVAvailable())

    def exit(self) -> None:
        self._pendingResultRefresh = False
        self._disconnectAllLinks()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self._resetDemoMode()
        self._disconnectAllLinks()
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
        # The live source is switchable whenever there is a second source to
        # switch to. It does not depend on the result presentation, which is a
        # different pane fed by a different link.
        liveSourceSelector = getattr(self.ui, "liveSourceSelector", None)
        if liveSourceSelector is not None:
            liveSourceSelector.setEnabled(
                self.logic is not None and self.logic.openIGTLinkAvailable()
            )

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
            self._removeUc2Banner()
        self._updateDemoModeIndicator()
        if self._presentationActive:
            self._refreshResultPresentation()
            self._refreshUc2Presentation()

    def _resetDemoMode(self) -> None:
        """Return demo mode to off without re-entering the toggle handler."""
        self._demoModeEnabled = False
        self._removeSimulatedBanner()
        self._removeUc2Banner()
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
        cameraSelected = self._liveSource() == LIVE_SOURCE_LAPTOP
        self.ui.installCameraSupportButton.setEnabled(
            not self._cameraSupportAvailable
            and not self._cameraRestartRequired
            and not cameraActive
        )
        self.ui.cameraIndexSpinBox.setEnabled(
            self._cameraSupportAvailable and cameraSelected and not cameraActive
        )
        self.ui.startButton.setEnabled(
            self._cameraSupportAvailable and cameraSelected and not cameraActive
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
            self._showPanelMessage(
                self.LIVE_VIEW_NAME, self.LIVE_WAITING_MESSAGE, layoutManager
            )
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
        self._removePanelMessage(self.LIVE_VIEW_NAME)
        liveView = liveWidget.sliceView()
        if liveView is not None:
            liveView.forceRender()

    # ------------------------------------------------------------------
    # OpenIGTLink links
    # ------------------------------------------------------------------

    def _liveSource(self) -> str:
        if self._parameterNode is None:
            return LIVE_SOURCE_LAPTOP
        return self._parameterNode.liveSource

    def _onLiveSourceChanged(self, caller=None, event=None) -> None:
        """Switch the live pane between the camera and the received stream.

        The camera is released on the way out rather than left running behind
        a pane it no longer feeds, and the pane is cleared, so a frame from the
        previous source can never be read as the new one.
        """
        selector = getattr(self.ui, "liveSourceSelector", None)
        if self._parameterNode is not None and selector is not None:
            selected = selector.currentText
            if selected in LIVE_SOURCE_CHOICES:
                self._parameterNode.liveSource = selected
        source = self._liveSource()
        if source == LIVE_SOURCE_LAPTOP:
            self._stopCamera(clearLiveView=True)
            self._liveViewEverDisplayed = False
            # The pane lets go of the stream it is leaving. The link itself is
            # the operator's, held by its own button, and is not torn down by
            # a change of pane source.
            if self._parameterNode is not None:
                self._parameterNode.parameterNode.SetNodeReferenceID(
                    "liveSourceVolume", None
                )
            self._setStatus(
                self.CAMERA_READY_STATUS
                if self._cameraSupportAvailable
                else self.CAMERA_SUPPORT_MISSING_STATUS
            )
        else:
            self._stopCamera(clearLiveView=True)
            self._liveViewEverDisplayed = False
            self._setStatus(self.LIVE_VIEW_WAITING_STATUS)
            self._displayLiveViewNode()
        self._refreshCameraControls()
        self._refreshConnectionControls()

    def _connectLink(self, role: str) -> str:
        """Start one module-owned client connector and observe it."""
        if self.logic is None:
            return CONNECTION_DISCONNECTED
        connector = self.logic.getOrCreateConnector(role)
        if connector is None:
            self._setConnectionState(role, CONNECTION_DISCONNECTED)
            self._setStatus(self.OPENIGTLINK_UNAVAILABLE_STATUS)
            return CONNECTION_DISCONNECTED
        self._observeConnector(role, connector)
        state = self.logic.startConnector(role)
        self._setConnectionState(role, state or CONNECTION_CONNECTING)
        self._startLinkStatePolling()
        return state

    def _disconnectLink(self, role: str) -> None:
        if self.logic is None:
            return
        connector = self.logic.connectorNode(role)
        if connector is not None:
            self._removeConnectorObservers(role)
        self.logic.stopConnector(role)
        self._onLinkDisconnected(role)
        self._stopLinkStatePollingIfIdle()

    def _onConnectLinksToggled(self, checked=None) -> None:
        """Start or stop every link at once; one control for five links."""
        if checked is None:
            button = getattr(self.ui, "connectLinksButton", None)
            checked = False if button is None else button.checked
        for role in CONNECTOR_ROLES:
            if checked:
                self._connectLink(role)
            else:
                self._disconnectLink(role)
        self._refreshConnectionControls()

    def _disconnectAllLinks(self) -> None:
        if self.logic is None:
            return
        for role in CONNECTOR_ROLES:
            connector = self.logic.connectorNode(role)
            hadSession = connector is not None and self._linkHadSession(role)
            if connector is not None:
                self._removeConnectorObservers(role)
            self.logic.stopConnector(role)
            self._connectionStates[role] = CONNECTION_DISCONNECTED
            if hadSession and role in self._linkDropped:
                self._linkDropped[role] = True
                self._rememberLinkDrop(role)
        self._stopLinkStatePolling()
        if hasattr(self, "ui"):
            self._refreshConnectionControls()

    def _observedConnectorEvents(self) -> tuple:
        logic = self.logic
        return (
            logic.CONNECTOR_CONNECTED_EVENT,
            logic.CONNECTOR_DISCONNECTED_EVENT,
            logic.CONNECTOR_ACTIVATED_EVENT,
            logic.CONNECTOR_DEACTIVATED_EVENT,
            logic.CONNECTOR_NEW_DEVICE_EVENT,
            logic.CONNECTOR_DEVICE_MODIFIED_EVENT,
        )

    def _connectorCallbacks(self, role: str) -> dict:
        """One callback per observed event, because the argument cannot say which.

        VTK calls a Python observer with the event as a string, and
        `vtkCommand::GetStringFromEventId` has no case for the connector's
        custom ids (118944 and up), so all six arrive as `"NoEvent"`. A single
        callback shared by six events therefore cannot tell a lost socket from
        a received frame, and the loss branch was unreachable in a real Slicer:
        a stopped producer left the panel reporting `displaying` indefinitely.
        Which callback VTK called is the one thing that still identifies the
        event, so each event gets its own.

        They are built once and kept because the observation bookkeeping is
        keyed by the callback object: a fresh closure per call would register a
        duplicate observer every time and remove none of them.
        """
        callbacks = self._connectorEventCallbacks.get(role)
        if callbacks is None:
            callbacks = {
                event: (
                    lambda caller=None, vtkEvent=None, role=role, event=event: (
                        self._onConnectorEvent(role, event)
                    )
                )
                for event in self._observedConnectorEvents()
            }
            self._connectorEventCallbacks[role] = callbacks
        return callbacks

    def _observeConnector(self, role: str, connector) -> None:
        for event, callback in self._connectorCallbacks(role).items():
            if not self.hasObserver(connector, event, callback):
                self.addObserver(connector, event, callback)

    def _removeConnectorObservers(self, role: str) -> None:
        for callback in self._connectorCallbacks(role).values():
            self.removeObservers(callback)

    def _onConnectorEvent(self, role: str, event=None) -> None:
        if self.logic is None:
            return
        # A client that loses its peer reports WaitConnection with
        # DisconnectedEvent; a stopped connector reports Off with
        # DeactivatedEvent. Both are losses, and both are handled before the
        # panel state is overwritten so the loss can see what the link was.
        if event in (
            self.logic.CONNECTOR_DISCONNECTED_EVENT,
            self.logic.CONNECTOR_DEACTIVATED_EVENT,
        ):
            self._onLinkDisconnected(role)
            return
        self._setConnectionState(role, self.logic.connectorState(role))
        # A connected event only says that the socket is back. The node left
        # in the scene is not a new message, so leave it stale until a device
        # modification event arrives for a new frame/result.
        if event in (
            self.logic.CONNECTOR_CONNECTED_EVENT,
            self.logic.CONNECTOR_ACTIVATED_EVENT,
        ):
            return
        if role == CONNECTOR_ACQUISITION:
            if self._liveSource() == LIVE_SOURCE_IGTL:
                self._displayLiveViewNode()
            return
        # UC2 and the cube arrive once per capture, so they are not throttled.
        if role == CONNECTOR_UC2:
            if self._presentationActive:
                self._refreshUc2Presentation()
            return
        if role == CONNECTOR_HS_CUBE:
            if self._presentationActive:
                self._refreshCubePresentation()
            return
        if role == CONNECTOR_CONTROL:
            self._refreshCaptureState()
            return
        now = time.monotonic()
        if now - self._lastResultRefreshTime < self.RESULT_REFRESH_INTERVAL_SEC:
            self._schedulePendingResultRefresh(now)
            return
        self._lastResultRefreshTime = now
        if self._presentationActive:
            self._refreshResultPresentation()

    def _schedulePendingResultRefresh(self, now: float) -> None:
        """Owe the dropped event a refresh at the end of the throttle window.

        Throttling may not lose the last event of a burst. A one-shot send, or
        the tail of a multi-map cycle, would otherwise leave the pane waiting
        on data that had in fact already arrived, until the operator refreshed
        by hand.
        """
        if self._pendingResultRefresh:
            return
        self._pendingResultRefresh = True
        remaining = self.RESULT_REFRESH_INTERVAL_SEC - (
            now - self._lastResultRefreshTime
        )
        qt.QTimer.singleShot(
            max(1, int(remaining * 1000.0)), self._onPendingResultRefresh
        )

    def _onPendingResultRefresh(self) -> None:
        if not self._pendingResultRefresh:
            return
        self._pendingResultRefresh = False
        if self.logic is None or not self._presentationActive:
            return
        self._lastResultRefreshTime = time.monotonic()
        self._refreshResultPresentation()

    def _pollLinkStates(self) -> None:
        """Notice a lost peer, which the connector cannot announce.

        `igtlioConnector`'s receiver thread sets the state to WaitConnection
        and then only *queues* DisconnectedEvent, because it is not on the main
        thread. That queue is drained by `ImportEventsFromEventBuffer`, which
        is reached only from `PeriodicProcess`, and
        `vtkSlicerOpenIGTLinkIFLogic::CallConnectorTimerHander` skips every
        connector whose state is not StateConnected. The state has already left
        StateConnected by the time the pump next runs, so the loss of a link is
        the one event that link can never deliver, and a stopped producer left
        the label reading `displaying` indefinitely.

        The state itself stays truthful, so it is read directly. The observers
        remain the fast path for everything they do deliver; this only catches
        what they cannot.
        """
        if self.logic is None:
            return
        for role in CONNECTOR_ROLES:
            if self.logic.connectorNode(role) is None:
                continue
            state = self.logic.connectorState(role)
            reported = self.connectionState(role)
            if state == reported:
                continue
            if state == CONNECTION_RECEIVING and reported in (
                CONNECTION_DISPLAYING,
                CONNECTION_INVALID,
            ):
                # Both are refinements of a connected socket, and both say
                # more about the data than the socket state can. They are not
                # disagreements with it.
                continue
            if reported in (
                CONNECTION_RECEIVING,
                CONNECTION_DISPLAYING,
                CONNECTION_INVALID,
            ):
                # The panel claimed a live link and the socket says otherwise.
                # This is the loss, reported through the same path the event
                # would have taken, so the retained image and its stale
                # wording are decided in exactly one place.
                self._onLinkDisconnected(role)
                continue
            self._setConnectionState(role, state)

    def _startLinkStatePolling(self) -> None:
        if self._linkStateTimer is not None:
            return
        timer = qt.QTimer()
        timer.setInterval(int(self.LINK_STATE_POLL_INTERVAL_SEC * 1000.0))
        timer.connect("timeout()", self._pollLinkStates)
        timer.start()
        self._linkStateTimer = timer

    def _stopLinkStatePolling(self) -> None:
        timer, self._linkStateTimer = self._linkStateTimer, None
        if timer is None:
            return
        timer.stop()
        timer.disconnect("timeout()", self._pollLinkStates)

    def _stopLinkStatePollingIfIdle(self) -> None:
        """Stop polling once the last link is gone, not before."""
        if self.logic is None:
            self._stopLinkStatePolling()
            return
        if any(self.logic.connectorNode(role) is not None for role in CONNECTOR_ROLES):
            return
        self._stopLinkStatePolling()

    def _linkConnected(self, role: str) -> bool:
        """Whether this link's connector currently reports StateConnected.

        `displaying` and `invalid` are claims about a live link. Without a
        connected connector there is nothing to make them about, so the panel
        keeps reporting the connector's `disconnected` or `connecting` state
        however often the retained scene node is rediscovered.
        """
        return (
            self.logic is not None
            and self.logic.connectorState(role) == CONNECTION_RECEIVING
        )

    def _linkSelectionKey(self, role: str):
        if role == CONNECTOR_UC1 and self._parameterNode is not None:
            return self._parameterNode.resultMap
        return None

    def _linkSourceNode(self, role: str):
        if self.logic is None:
            return None
        if role == CONNECTOR_ACQUISITION:
            return self.logic.findLiveViewNode()
        if role == CONNECTOR_UC2:
            return self.logic.findReceivedNode(UC2_DEVICE_NAME)
        if self._parameterNode is None:
            return None
        descriptor = self.logic.resultDescriptor(self._parameterNode.resultMap)
        if descriptor is None:
            return None
        return self.logic.findReceivedNode(descriptor.deviceName)

    def _linkSourceSignature(self, role: str):
        node = self._linkSourceNode(role)
        if node is None:
            return None
        try:
            return node.GetID(), int(node.GetMTime())
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return None

    def _rememberLinkDrop(self, role: str) -> None:
        self._linkDropSnapshots[role] = (
            self._linkSelectionKey(role),
            self._linkSourceSignature(role),
        )

    def _linkHadSession(self, role: str) -> bool:
        """Whether losing this link now leaves presented data stale.

        A link that reached StateConnected, or a pane that is holding an image,
        has something a loss makes stale. A connector that only ever waited has
        delivered nothing, so a result shown later was not captioned by it.
        This is judged from the panel's own record, so it must be asked before
        the loss overwrites the panel state.
        """
        if role not in self._linkDropped:
            return False
        retainedPresentation = {
            CONNECTOR_ACQUISITION: self._liveViewEverDisplayed,
            CONNECTOR_UC1: self._resultEverDisplayed,
            CONNECTOR_UC2: self._uc2EverDisplayed,
        }[role]
        return retainedPresentation or self.connectionState(role) in (
            CONNECTION_RECEIVING,
            CONNECTION_DISPLAYING,
            CONNECTION_INVALID,
        )

    def _recordUnobservedLinkDrop(self, role: str) -> None:
        """Preserve stale history if a refresh sees the socket drop first.

        The connector normally emits DisconnectedEvent before a refresh runs,
        but a refresh can be queued in the same event-loop turn. The previous
        panel state is enough to distinguish a link that had been connected
        from a pre-existing scene node that never belonged to a link.
        """
        if role not in self._linkDropped:
            return
        if self._linkConnected(role) or self.connectionState(role) not in (
            CONNECTION_RECEIVING,
            CONNECTION_DISPLAYING,
            CONNECTION_INVALID,
        ):
            return
        self._linkDropped[role] = True
        self._rememberLinkDrop(role)

    def _linkHasFreshData(self, role: str) -> bool:
        """Clear stale history only after a connected link changes its node.

        OpenIGTLink reuses the same MRML node for subsequent messages. A node
        already present when the socket reconnects is therefore not enough to
        prove that the new socket has delivered anything. Comparing the node
        ID and MTime also prevents an update for another selected result map
        from reviving this map's old image.
        """
        if not self._linkDropped.get(role, False) or not self._linkConnected(role):
            return not self._linkDropped.get(role, False)
        snapshot = self._linkDropSnapshots.get(role)
        if snapshot is None:
            return False
        selectionKey, sourceSignature = snapshot
        currentKey = self._linkSelectionKey(role)
        currentSignature = self._linkSourceSignature(role)
        if currentKey != selectionKey:
            self._linkDropSnapshots[role] = (currentKey, currentSignature)
            return False
        if currentSignature is None or currentSignature == sourceSignature:
            return False
        self._linkDropped[role] = False
        self._linkDropSnapshots[role] = None
        return True

    def _onLinkDisconnected(self, role: str) -> None:
        """Report the loss without throwing away what was already valid.

        A disconnection is not a reason to blank a pane that is showing a
        result that really was received and really did validate. It is a reason
        to say the image is no longer being updated. Only a pane that never had
        a valid image returns to black.
        """
        hadSession = self._linkHadSession(role)
        state = (
            self.logic.connectorState(role)
            if self.logic is not None
            else CONNECTION_DISCONNECTED
        )
        self._setConnectionState(role, state)
        if hadSession:
            self._linkDropped[role] = True
            self._rememberLinkDrop(role)
        if role == CONNECTOR_UC1:
            if self._resultEverDisplayed:
                self._setResultStatus("WARN", self._staleResultStatus())
            else:
                self._clearResultView()
                self._setResultStatus("WARN", self.RESULT_WAITING_STATUS)
            return
        if role == CONNECTOR_UC2:
            if self._uc2EverDisplayed:
                self._setLayerStatus(self.LAYER_UC2, "WARN", self._staleUc2Status())
            else:
                self._clearUc2View()
                self._setLayerStatus(self.LAYER_UC2, "WARN", self.UC2_WAITING_MESSAGE)
            return
        if role in (CONNECTOR_HS_CUBE, CONNECTOR_CONTROL):
            return
        if self._liveSource() != LIVE_SOURCE_IGTL:
            return
        if self._liveViewEverDisplayed:
            self._setStatus(self.LIVE_STALE_STATUS)
        else:
            self._clearLiveView()
            self._setStatus(self.LIVE_VIEW_WAITING_STATUS)

    def _staleResultStatus(self) -> str:
        """The stale caption, still saying what the retained image is.

        A simulated image that stops being updated is still simulated. The
        banner stays on it, and the status has to keep agreeing with the
        banner.
        """
        if self._lastResultSimulated:
            return self.SIMULATED_STATUS_PREFIX + self.RESULT_STALE_STATUS
        return self.RESULT_STALE_STATUS

    def _setConnectionState(self, role: str, state: str) -> None:
        newState = state or CONNECTION_DISCONNECTED
        changed = self._connectionStates.get(role) != newState
        self._connectionStates[role] = newState
        # Rebuilding the controls is useful when the state changes, or when
        # the connector was removed while the label stayed the same. Avoid
        # doing it for every validation refresh that reasserts the same state.
        if changed or self.logic is None or self.logic.connectorNode(role) is None:
            self._refreshConnectionControls()

    def connectionState(self, role: str) -> str:
        """The state this panel is currently reporting for one link."""
        return self._connectionStates.get(role, CONNECTION_DISCONNECTED)

    def _refreshConnectionControls(self) -> None:
        if not hasattr(self, "ui") or self.logic is None:
            return
        available = self.logic.openIGTLinkAvailable()
        unavailableLabel = getattr(self.ui, "openIGTLinkUnavailableLabel", None)
        if unavailableLabel is not None:
            unavailableLabel.setVisible(not available)
        anyConnector = any(
            self.logic.connectorNode(role) is not None for role in CONNECTOR_ROLES
        )
        button = getattr(self.ui, "connectLinksButton", None)
        if button is not None:
            blocked = button.blockSignals(True)
            button.setChecked(anyConnector)
            button.blockSignals(blocked)
            button.setEnabled(available or anyConnector)
            button.setText(_("Disconnect links") if anyConnector else _("Connect links"))
        for role, valueLabel in self.LINK_STATE_LABELS.items():
            label = getattr(self.ui, valueLabel, None)
            if label is not None:
                label.setText(self.connectionState(role))
        self._refreshCaptureControls()

    def _displayLiveViewNode(self, layoutManager=None) -> dict:
        """Bind the received LiveView node to the left pane, and nowhere else.

        Nothing is bound before it is known to be displayable, and the result
        pane is never touched from here: a live frame is not a result and must
        not be able to appear as one.
        """
        if self.logic is None or self._parameterNode is None:
            return {"summaryStatus": "WARN", "summaryMessage": "No parameter node."}
        liveNode = self.logic.findLiveViewNode()
        report = self.logic.validateLiveViewNode(liveNode)
        connectorState = self.logic.connectorState(CONNECTOR_ACQUISITION)
        self._recordUnobservedLinkDrop(CONNECTOR_ACQUISITION)
        self._linkHasFreshData(CONNECTOR_ACQUISITION)
        if report["summaryStatus"] != "PASS":
            self._parameterNode.parameterNode.SetNodeReferenceID(
                "liveSourceVolume", None
            )
            self._setConnectionState(
                CONNECTOR_ACQUISITION,
                CONNECTION_INVALID
                if (
                    report["summaryStatus"] == "FAIL"
                    and self._linkConnected(CONNECTOR_ACQUISITION)
                    and not self._linkDropped[CONNECTOR_ACQUISITION]
                )
                else connectorState,
            )
            self._setStatus(
                self.LIVE_VIEW_WAITING_STATUS
                if report["summaryStatus"] == "WARN"
                else report["summaryMessage"]
            )
            return report

        # Matched by device name, then held by its stable MRML node ID. The
        # reference is recorded before any view work, because which node the
        # stream resolved to is a fact about the scene and not about whether
        # this Slicer session happens to have a layout.
        self._parameterNode.liveSourceVolume = liveNode
        self._setConnectionState(
            CONNECTOR_ACQUISITION,
            CONNECTION_DISPLAYING
            if (
                self._linkConnected(CONNECTOR_ACQUISITION)
                and not self._linkDropped[CONNECTOR_ACQUISITION]
            )
            else connectorState,
        )

        # Stale is a fact about the link's history, not about this pane: a
        # source toggle resets _liveViewEverDisplayed but does not make the
        # retained frame any newer.
        stalePresentation = self._linkDropped[CONNECTOR_ACQUISITION]
        self._liveViewEverDisplayed = True
        if stalePresentation:
            self._setStatus(self.LIVE_STALE_STATUS)
        else:
            self._setStatus(report["summaryMessage"])

        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return report
        liveWidget = layoutManager.sliceWidget(self.LIVE_VIEW_NAME)
        if liveWidget is None:
            return report
        liveLogic = liveWidget.sliceLogic()
        liveComposite = liveLogic.GetSliceCompositeNode()
        if liveComposite.GetBackgroundVolumeID() != liveNode.GetID():
            liveComposite.SetBackgroundVolumeID(liveNode.GetID())
            liveComposite.SetForegroundVolumeID(None)
            liveComposite.SetLabelVolumeID(None)
            liveLogic.FitSliceToBackground()
        self._removePanelMessage(self.LIVE_VIEW_NAME)
        liveView = liveWidget.sliceView()
        if liveView is not None:
            liveView.forceRender()
        return report

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
        self._setLayerStatus(self.LAYER_UC1, status, message)

    def _refreshResultPresentation(self, caller=None, event=None) -> dict:
        if self.logic is None or self._parameterNode is None:
            return {"summaryStatus": "WARN", "summaryMessage": "No parameter node."}

        connectorState = self.logic.connectorState(CONNECTOR_UC1)
        self._recordUnobservedLinkDrop(CONNECTOR_UC1)
        self._linkHasFreshData(CONNECTOR_UC1)
        linkConnected = self._linkConnected(CONNECTOR_UC1)
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
                self._clearResultBackground()
                self._clearResultView()
                self._setResultStatus("FAIL", self.BANNER_UNAVAILABLE_STATUS)
                return dict(
                    report,
                    summaryStatus="FAIL",
                    summaryMessage=self.BANNER_UNAVAILABLE_STATUS,
                )
            # The background is decided after the map passed and before the
            # flush, so the first frame of a map that has a background already
            # shows it. Every outcome but a composite leaves the map as it was.
            backgroundReport = self.logic.presentResultBackground(self._parameterNode)
            self._setResultBackgroundStatus(backgroundReport["summaryMessage"])
            # The single flush of the view. _displayResultVolume renders once
            # the banner state and the volume state already agree, so neither
            # can be painted without the other.
            self._displayResultVolume()
            self._resultEverDisplayed = True
            self._lastResultSimulated = simulated
            message = report["summaryMessage"]
            if simulated:
                message = self.SIMULATED_STATUS_PREFIX + message
            # Browsing to a map with no data resets _resultEverDisplayed, so
            # the link history alone decides whether this result is stale.
            stalePresentation = self._linkDropped[CONNECTOR_UC1]
            if linkConnected and not stalePresentation:
                self._setResultStatus("PASS", message, report.get("sourceNodeName"))
                self._setConnectionState(CONNECTOR_UC1, CONNECTION_DISPLAYING)
            elif stalePresentation:
                # The image is real and still worth showing, but nothing is
                # feeding it any more, and rediscovering it on a later refresh
                # does not change that.
                self._setResultStatus(
                    "WARN", self._staleResultStatus(), report.get("sourceNodeName")
                )
                self._setConnectionState(CONNECTOR_UC1, connectorState)
            else:
                # No link was ever established, so this result did not arrive
                # over one and its status makes no claim about one.
                self._setResultStatus("PASS", message, report.get("sourceNodeName"))
                self._setConnectionState(CONNECTOR_UC1, connectorState)
        else:
            self.logic.clearResultReferences(self._parameterNode)
            self._clearResultBackground()
            self._clearResultView()
            self._resultEverDisplayed = False
            if report["summaryStatus"] == "FAIL":
                if report.get("provenance") == "unrecognized":
                    invalidStatus = self.RESULT_INVALID_PROVENANCE_STATUS
                elif simulated:
                    invalidStatus = self.RESULT_INVALID_SIMULATED_STATUS
                else:
                    invalidStatus = self.RESULT_INVALID_STATUS
                self._setResultStatus(
                    "FAIL",
                    f"{invalidStatus} {report['summaryMessage']}",
                )
                self._setConnectionState(
                    CONNECTOR_UC1,
                    CONNECTION_INVALID
                    if (
                        linkConnected
                        and not self._linkDropped[CONNECTOR_UC1]
                    )
                    else connectorState,
                )
            else:
                self._setResultStatus("WARN", report["summaryMessage"])
                self._setConnectionState(CONNECTOR_UC1, connectorState)
        return report

    def resultBackgroundStatus(self) -> str:
        """The background line the operator reads under the result source."""
        label = getattr(getattr(self, "ui", None), "resultBackgroundValueLabel", None)
        return "" if label is None else label.text

    def _setResultBackgroundStatus(self, message: str) -> None:
        label = getattr(getattr(self, "ui", None), "resultBackgroundValueLabel", None)
        if label is not None:
            label.setText(message)

    def _clearResultBackground(self) -> None:
        if self.logic is not None and self._parameterNode is not None:
            self.logic.clearResultBackgroundReferences(self._parameterNode)
        self._setResultBackgroundStatus(self.RESULT_BACKGROUND_NONE_STATUS)

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
            self._removePanelMessage(self.RESULT_VIEW_NAME)
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
        resultWidget = self._sliceWidgetOrNone(self.RESULT_VIEW_NAME, layoutManager)
        if resultWidget is None:
            return
        self._removeWaitingAnnotation()
        try:
            backgroundNode = self._parameterNode.resultBackgroundVolume
        except (KeyError, TypeError):
            backgroundNode = None
        backgroundID = None if backgroundNode is None else backgroundNode.GetID()
        if self._bindLayer(resultWidget, resultNode.GetID(), self.LAYER_UC1, backgroundID):
            self._removePanelMessage(self.RESULT_VIEW_NAME)
        else:
            self._showPanelMessage(
                self.RESULT_VIEW_NAME,
                self.HIDDEN_LAYER_MESSAGE.format(layer=self._layerLabel(self.LAYER_UC1)),
                layoutManager,
            )
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
        self._refreshUc2Presentation()
        self._refreshCubePresentation()
        self._refreshCaptureControls()
        return True

    @staticmethod
    def _clearSliceLayers(sliceWidget) -> None:
        compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
        compositeNode.SetBackgroundVolumeID(None)
        compositeNode.SetForegroundVolumeID(None)
        compositeNode.SetLabelVolumeID(None)

    @staticmethod
    def _sliceViewRenderer(sliceWidget):
        """The renderer now on screen for one panel, or None.

        A view that cannot supply a renderer yields None rather than raising:
        the callers draw text on a panel, and failing to decorate a panel must
        not take down the presentation that owns it. Where the text is a
        requirement rather than a decoration - a reserved panel's reason -
        the caller checks the return value and refuses instead.
        """
        sliceView = sliceWidget.sliceView()
        if sliceView is None:
            return None
        renderWindow = getattr(sliceView, "renderWindow", None)
        if renderWindow is None:
            return None
        renderWindow = renderWindow()
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

        # The headline depends on the detail, so it is re-asserted rather than
        # written once: a session that switches producers must not keep the
        # previous producer's wording over the new one's map.
        headline = simulatedBannerMessage(detail)
        if self._simulatedBannerActor is None:
            self._simulatedBannerActor = self._createBannerActor(
                headline,
                self.SIMULATED_BANNER_FONT_SIZE,
                self.SIMULATED_BANNER_POSITION,
                bold=True,
            )
        else:
            self._simulatedBannerActor.SetInput(headline)

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
            view for row in self.VIEW_ROWS for view in row
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
            elif viewName in self.RESERVED_PANEL_REASONS:
                if not self._showPanelMessage(
                    viewName, self.RESERVED_PANEL_REASONS[viewName], layoutManager
                ):
                    return False
            elif viewName == self.CUBE_VIEW_NAME:
                self._showPanelMessage(viewName, self.CUBE_WAITING_MESSAGE, layoutManager)
            elif viewName == self.VASCULAR_VIEW_NAME:
                self._showPanelMessage(viewName, self.UC2_WAITING_MESSAGE, layoutManager)
            elif viewName == self.LIVE_VIEW_NAME:
                self._showPanelMessage(viewName, self.LIVE_WAITING_MESSAGE, layoutManager)

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
        self._removeUc2Banner()
        self._removeAllPanelMessages()
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

    # ------------------------------------------------------------------
    # Panel text (SLIA-022)
    # ------------------------------------------------------------------

    @staticmethod
    def _sliceWidgetOrNone(viewName: str, layoutManager=None):
        if layoutManager is None:
            layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return None
        try:
            return layoutManager.sliceWidget(viewName)
        except RuntimeError:
            return None

    def panelMessage(self, viewName: str) -> str:
        """The text this panel is currently asked to carry, or an empty string."""
        return self._panelMessages.get(viewName, "")

    @staticmethod
    def _createPanelMessageActor(message: str):
        actor = vtk.vtkTextActor()
        actor.SetInput(message)
        actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        actor.SetPosition(0.5, 0.5)
        textProperty = actor.GetTextProperty()
        textProperty.SetFontSize(14)
        textProperty.SetColor(1.0, 1.0, 1.0)
        textProperty.SetJustificationToCentered()
        textProperty.SetVerticalJustificationToCentered()
        return actor

    def _showPanelMessage(self, viewName: str, message: str, layoutManager=None) -> bool:
        """Write text on one panel. Returns whether it reached a renderer."""
        self._panelMessages[viewName] = message
        actor = self._panelAnnotationActors.get(viewName)
        if actor is None:
            actor = self._createPanelMessageActor(message)
            self._panelAnnotationActors[viewName] = actor
        else:
            actor.SetInput(message)
        sliceWidget = self._sliceWidgetOrNone(viewName, layoutManager)
        if sliceWidget is None:
            return False
        renderer = self._sliceViewRenderer(sliceWidget)
        placed = self._placeAnnotationActor(
            renderer, actor, self._panelAnnotationRenderers.get(viewName)
        )
        if placed is not None:
            self._panelAnnotationRenderers[viewName] = placed
        return placed is not None

    def _removePanelMessage(self, viewName: str) -> None:
        self._panelMessages.pop(viewName, None)
        actor = self._panelAnnotationActors.pop(viewName, None)
        renderer = self._panelAnnotationRenderers.pop(viewName, None)
        if actor is None or renderer is None:
            return
        try:
            renderer.RemoveActor2D(actor)
        except (RuntimeError, ValueError):
            pass

    def _removeAllPanelMessages(self) -> None:
        for viewName in list(self._panelAnnotationActors):
            self._removePanelMessage(viewName)
        self._panelMessages.clear()

    # ------------------------------------------------------------------
    # Layers (SLIA-022)
    #
    # Each result layer lives in its own panel (ADR-0001 rule 3). Show, hide
    # and opacity change only the slice composite node; no pixel of a result
    # is changed, and the banner follows the presentation, not the layer.
    # ------------------------------------------------------------------

    def _layerRow(self, layer: str) -> int:
        for row, (rowLayer, _label, _viewName) in enumerate(self.LAYER_ROWS):
            if rowLayer == layer:
                return row
        raise ValueError(f"Unknown layer: {layer}")

    def _layerLabel(self, layer: str) -> str:
        return self.LAYER_ROWS[self._layerRow(layer)][1]

    def layerState(self, layer: str) -> tuple[bool, float]:
        self._layerRow(layer)
        return self._layerVisible[layer], self._layerOpacity[layer]

    def layerStatus(self, layer: str) -> str:
        """The status text shown for one layer in the layer list."""
        table = getattr(getattr(self, "ui", None), "layerTable", None)
        if table is not None:
            item = table.item(self._layerRow(layer), 1)
            if item is not None:
                return item.text()
        return self._layerStatusText.get(layer, "")

    def _setLayerStatus(self, layer: str, status: str, message: str) -> None:
        text = _("{0}: {1}").format(status, message)
        self._layerStatusText[layer] = text
        table = getattr(getattr(self, "ui", None), "layerTable", None)
        if table is None:
            return
        item = table.item(self._layerRow(layer), 1)
        if item is None:
            return
        blocked = table.blockSignals(True)
        item.setText(text)
        item.setToolTip(text)
        table.blockSignals(blocked)

    def _setupLayerTable(self) -> None:
        table = getattr(self.ui, "layerTable", None)
        if table is None:
            return
        table.setColumnCount(2)
        table.setRowCount(len(self.LAYER_ROWS))
        table.setHorizontalHeaderLabels([_("Layer"), _("Status")])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        blocked = table.blockSignals(True)
        for row, (layer, label, _viewName) in enumerate(self.LAYER_ROWS):
            layerItem = qt.QTableWidgetItem(label)
            layerItem.setFlags(
                qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable
            )
            layerItem.setCheckState(
                qt.Qt.Checked if self._layerVisible[layer] else qt.Qt.Unchecked
            )
            table.setItem(row, 0, layerItem)
            statusItem = qt.QTableWidgetItem(self._layerStatusText[layer])
            statusItem.setFlags(qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)
            table.setItem(row, 1, statusItem)
        table.blockSignals(blocked)
        table.resizeColumnToContents(0)
        table.connect("itemChanged(QTableWidgetItem*)", self._onLayerItemChanged)
        table.connect("currentCellChanged(int,int,int,int)", self._onLayerSelectionChanged)
        table.setCurrentCell(0, 0)
        slider = getattr(self.ui, "layerOpacitySlider", None)
        if slider is not None:
            slider.connect("valueChanged(int)", self._onLayerOpacitySliderChanged)

    def _selectedLayer(self) -> str:
        table = getattr(getattr(self, "ui", None), "layerTable", None)
        row = -1 if table is None else int(table.currentRow())
        if 0 <= row < len(self.LAYER_ROWS):
            return self.LAYER_ROWS[row][0]
        return self.LAYER_UC1

    def _onLayerItemChanged(self, item=None) -> None:
        if item is None or item.column() != 0:
            return
        row = item.row()
        if not 0 <= row < len(self.LAYER_ROWS):
            return
        self.setLayerVisible(self.LAYER_ROWS[row][0], item.checkState() == qt.Qt.Checked)

    def _onLayerSelectionChanged(self, *args) -> None:
        self._syncOpacitySlider()

    def _onLayerOpacitySliderChanged(self, value) -> None:
        self.setLayerOpacity(self._selectedLayer(), float(value) / 100.0)

    def _syncOpacitySlider(self) -> None:
        slider = getattr(getattr(self, "ui", None), "layerOpacitySlider", None)
        if slider is None:
            return
        blocked = slider.blockSignals(True)
        slider.setValue(int(round(self._layerOpacity[self._selectedLayer()] * 100.0)))
        slider.blockSignals(blocked)

    def setLayerVisible(self, layer: str, visible: bool, layoutManager=None) -> None:
        row = self._layerRow(layer)
        self._layerVisible[layer] = bool(visible)
        table = getattr(getattr(self, "ui", None), "layerTable", None)
        item = None if table is None else table.item(row, 0)
        if item is not None:
            blocked = table.blockSignals(True)
            item.setCheckState(qt.Qt.Checked if visible else qt.Qt.Unchecked)
            table.blockSignals(blocked)
        self._applyLayer(layer, layoutManager)

    def setLayerOpacity(self, layer: str, opacity: float, layoutManager=None) -> None:
        self._layerRow(layer)
        self._layerOpacity[layer] = min(1.0, max(0.0, float(opacity)))
        if self._selectedLayer() == layer:
            self._syncOpacitySlider()
        self._applyLayer(layer, layoutManager)

    def _applyLayer(self, layer: str, layoutManager=None) -> None:
        if layer == self.LAYER_UC1:
            self._displayResultVolume(layoutManager=layoutManager)
        else:
            self._displayUc2Volume(layoutManager=layoutManager)

    def _bindLayer(
        self, sliceWidget, nodeID: str, layer: str, backgroundID: str | None = None
    ) -> bool:
        """Bind one layer's node to its panel. Returns False when hidden.

        With no background, full opacity uses the background slot, exactly as
        before SLIA-022, and lower opacity uses the foreground slot over an
        empty background, so the layer fades to black.

        With a background - only ever the same cube's colour image, which the
        logic has already matched to the map by provenance and size (SLIA-024)
        - the background slot holds that image and the layer is always the
        foreground, at the layer's opacity: 0 shows the image alone and 1 the
        map alone.
        """
        visible, opacity = self.layerState(layer)
        sliceLogic = sliceWidget.sliceLogic()
        composite = sliceLogic.GetSliceCompositeNode()
        if not visible:
            composite.SetBackgroundVolumeID(None)
            composite.SetForegroundVolumeID(None)
            composite.SetLabelVolumeID(None)
            return False
        if backgroundID is not None:
            if composite.GetBackgroundVolumeID() != backgroundID:
                composite.SetBackgroundVolumeID(backgroundID)
                sliceLogic.FitSliceToBackground()
            composite.SetForegroundVolumeID(nodeID)
            composite.SetForegroundOpacity(opacity)
        elif opacity >= 1.0:
            if composite.GetBackgroundVolumeID() != nodeID:
                composite.SetBackgroundVolumeID(nodeID)
                sliceLogic.FitSliceToBackground()
            composite.SetForegroundVolumeID(None)
        else:
            composite.SetBackgroundVolumeID(None)
            composite.SetForegroundVolumeID(nodeID)
            composite.SetForegroundOpacity(opacity)
        composite.SetLabelVolumeID(None)
        return True

    # ------------------------------------------------------------------
    # Enhanced Vascularization: the UC2 layer (SLIA-022)
    # ------------------------------------------------------------------

    def _staleUc2Status(self) -> str:
        if self._lastUc2Simulated:
            return self.SIMULATED_STATUS_PREFIX + self.UC2_STALE_STATUS
        return self.UC2_STALE_STATUS

    def _refreshUc2Presentation(self, caller=None, event=None, layoutManager=None) -> dict:
        if self.logic is None or self._parameterNode is None:
            return {"summaryStatus": "WARN", "summaryMessage": "No parameter node."}

        connectorState = self.logic.connectorState(CONNECTOR_UC2)
        self._recordUnobservedLinkDrop(CONNECTOR_UC2)
        self._linkHasFreshData(CONNECTOR_UC2)
        linkConnected = self._linkConnected(CONNECTOR_UC2)
        report = self.logic.presentUc2(
            self._parameterNode, allowSimulated=self._demoModeEnabled
        )
        simulated = report.get("dataOrigin") == RESULT_SOURCE_SIMULATED_ORIGIN
        if report["summaryStatus"] == "PASS":
            # As for UC1: the banner is in place before the map is bound, and a
            # banner that cannot be drawn withholds the map.
            if not self._updateUc2Banner(
                simulated, report.get("simulationDetail"), layoutManager
            ):
                self.logic.clearUc2References(self._parameterNode)
                self._clearUc2View(layoutManager)
                self._uc2EverDisplayed = False
                self._setLayerStatus(self.LAYER_UC2, "FAIL", self.BANNER_UNAVAILABLE_STATUS)
                return dict(
                    report,
                    summaryStatus="FAIL",
                    summaryMessage=self.BANNER_UNAVAILABLE_STATUS,
                )
            self._displayUc2Volume(layoutManager)
            self._uc2EverDisplayed = True
            self._lastUc2Simulated = simulated
            message = report["summaryMessage"]
            if simulated:
                message = self.SIMULATED_STATUS_PREFIX + message
            stalePresentation = self._linkDropped[CONNECTOR_UC2]
            if linkConnected and not stalePresentation:
                self._setLayerStatus(self.LAYER_UC2, "PASS", message)
                self._setConnectionState(CONNECTOR_UC2, CONNECTION_DISPLAYING)
            elif stalePresentation:
                self._setLayerStatus(self.LAYER_UC2, "WARN", self._staleUc2Status())
                self._setConnectionState(CONNECTOR_UC2, connectorState)
            else:
                self._setLayerStatus(self.LAYER_UC2, "PASS", message)
                self._setConnectionState(CONNECTOR_UC2, connectorState)
            return report

        self.logic.clearUc2References(self._parameterNode)
        self._clearUc2View(layoutManager)
        self._uc2EverDisplayed = False
        if report["summaryStatus"] == "FAIL":
            if report.get("provenance") == "unrecognized":
                invalidStatus = self.UC2_INVALID_PROVENANCE_STATUS
            elif simulated:
                invalidStatus = self.UC2_INVALID_SIMULATED_STATUS
            else:
                invalidStatus = self.UC2_INVALID_STATUS
            self._setLayerStatus(
                self.LAYER_UC2, "FAIL", f"{invalidStatus} {report['summaryMessage']}"
            )
            self._setConnectionState(
                CONNECTOR_UC2,
                CONNECTION_INVALID
                if linkConnected and not self._linkDropped[CONNECTOR_UC2]
                else connectorState,
            )
        else:
            self._setLayerStatus(self.LAYER_UC2, "WARN", report["summaryMessage"])
            self._setConnectionState(CONNECTOR_UC2, connectorState)
        return report

    def _clearUc2View(self, layoutManager=None) -> None:
        self._removeUc2Banner()
        vascularWidget = self._sliceWidgetOrNone(self.VASCULAR_VIEW_NAME, layoutManager)
        if vascularWidget is None:
            return
        try:
            self._clearSliceLayers(vascularWidget)
            self._showPanelMessage(
                self.VASCULAR_VIEW_NAME, self.UC2_WAITING_MESSAGE, layoutManager
            )
            vascularView = vascularWidget.sliceView()
            if vascularView is not None:
                vascularView.forceRender()
        except RuntimeError:
            return

    def _displayUc2Volume(self, layoutManager=None) -> None:
        if self._parameterNode is None:
            return
        try:
            uc2Node = self._parameterNode.uc2Volume
        except (KeyError, TypeError):
            uc2Node = None
        if uc2Node is None:
            return
        vascularWidget = self._sliceWidgetOrNone(self.VASCULAR_VIEW_NAME, layoutManager)
        if vascularWidget is None:
            return
        if self._bindLayer(vascularWidget, uc2Node.GetID(), self.LAYER_UC2):
            self._removePanelMessage(self.VASCULAR_VIEW_NAME)
        else:
            self._showPanelMessage(
                self.VASCULAR_VIEW_NAME,
                self.HIDDEN_LAYER_MESSAGE.format(layer=self._layerLabel(self.LAYER_UC2)),
                layoutManager,
            )
        vascularView = vascularWidget.sliceView()
        if vascularView is not None:
            vascularView.forceRender()

    def _updateUc2Banner(self, simulated: bool, detail=None, layoutManager=None) -> bool:
        """Bring the UC2 panel's banner into agreement with the origin shown.

        Returns False only when a banner is required on a panel that exists
        and cannot be drawn.
        """
        if not simulated:
            self._removeUc2Banner()
            return True
        vascularWidget = self._sliceWidgetOrNone(self.VASCULAR_VIEW_NAME, layoutManager)
        if vascularWidget is None:
            self._removeUc2Banner()
            return True
        renderer = self._sliceViewRenderer(vascularWidget)
        if renderer is None:
            self._removeUc2Banner()
            return False

        if self._uc2BannerActor is None:
            self._uc2BannerActor = self._createBannerActor(
                UC2_SIMULATED_BANNER_MESSAGE,
                self.SIMULATED_BANNER_FONT_SIZE,
                self.SIMULATED_BANNER_POSITION,
                bold=True,
            )
        if not detail:
            if self._uc2DetailActor is not None and self._uc2BannerRenderer is not None:
                try:
                    self._uc2BannerRenderer.RemoveActor2D(self._uc2DetailActor)
                except (RuntimeError, ValueError):
                    pass
            self._uc2DetailActor = None
        elif self._uc2DetailActor is None:
            self._uc2DetailActor = self._createBannerActor(
                detail,
                self.SIMULATED_DETAIL_FONT_SIZE,
                self.SIMULATED_DETAIL_POSITION,
                bold=False,
            )
        else:
            self._uc2DetailActor.SetInput(detail)

        previousRenderer = self._uc2BannerRenderer
        self._uc2BannerRenderer = self._placeAnnotationActor(
            renderer, self._uc2BannerActor, previousRenderer
        )
        if self._uc2DetailActor is not None:
            self._placeAnnotationActor(renderer, self._uc2DetailActor, previousRenderer)
        return self._uc2BannerRenderer is not None

    def _removeUc2Banner(self) -> None:
        renderer = self._uc2BannerRenderer
        actors = (self._uc2BannerActor, self._uc2DetailActor)
        self._uc2BannerRenderer = None
        self._uc2BannerActor = None
        self._uc2DetailActor = None
        if renderer is None:
            return
        for actor in actors:
            if actor is None:
                continue
            try:
                renderer.RemoveActor2D(actor)
            except (RuntimeError, ValueError):
                pass

    # ------------------------------------------------------------------
    # Capture (SLIA-022)
    # ------------------------------------------------------------------

    def _controlLinkConnected(self) -> bool:
        return (
            self.logic is not None
            and self.logic.connectorState(CONNECTOR_CONTROL) == CONNECTION_RECEIVING
        )

    def _refreshCaptureControls(self) -> None:
        if not hasattr(self, "ui") or self.logic is None:
            return
        button = getattr(self.ui, "captureButton", None)
        if button is not None:
            button.setEnabled(self._controlLinkConnected())
        self._refreshCaptureState()

    def _refreshCaptureState(self) -> None:
        """Quote what the stand-in last said, under a word the operator reads."""
        label = getattr(getattr(self, "ui", None), "captureStatusLabel", None)
        if label is None or self.logic is None:
            return
        if not self._controlLinkConnected():
            label.setText(self.CAPTURE_NEEDS_CONTROL_LINK_STATUS)
            return
        lines = []
        status = self.logic.captureText(CAPTURE_STATUS_DEVICE_NAME)
        if status is not None:
            lines.append(
                _("Stand-in: {0}").format(self.logic.describeCaptureMessage(status))
            )
        reply = self.logic.captureText(CAPTURE_REPLY_DEVICE_NAME)
        if reply is not None:
            lines.append(
                _("Last answer: {0}").format(self.logic.describeCaptureMessage(reply))
            )
        label.setText("\n".join(lines) if lines else self.CAPTURE_NO_ANSWER_STATUS)

    def _onCaptureClicked(self) -> None:
        if self.logic is None:
            return
        self.logic.sendCaptureTrigger()
        self._refreshCaptureControls()

    # ------------------------------------------------------------------
    # HS Cube band browser (SLIA-022)
    #
    # The cube is shown as received. Browsing moves the slice, and nothing is
    # computed from the data.
    # ------------------------------------------------------------------

    def _refreshCubePresentation(self, caller=None, event=None, layoutManager=None) -> dict:
        if self.logic is None or self._parameterNode is None:
            return {"summaryStatus": "WARN", "summaryMessage": "No parameter node."}
        cubeNode = self.logic.findCubeNode()
        report = self.logic.validateCubeNode(cubeNode)
        slider = getattr(self.ui, "bandSlider", None)
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME, layoutManager)

        if report["summaryStatus"] != "PASS":
            self._parameterNode.parameterNode.SetNodeReferenceID("cubeSourceVolume", None)
            self._cubeBandCount = 0
            self._cubeWavelengths = None
            self._cubeWavelengthReason = ""
            if slider is not None:
                blocked = slider.blockSignals(True)
                slider.setRange(0, 0)
                slider.setEnabled(False)
                slider.blockSignals(blocked)
            self._setCubeBand(0, layoutManager)
            if cubeWidget is not None:
                try:
                    self._clearSliceLayers(cubeWidget)
                    self._showPanelMessage(
                        self.CUBE_VIEW_NAME,
                        self.CUBE_WAITING_MESSAGE
                        if report["summaryStatus"] == "WARN"
                        else report["summaryMessage"],
                        layoutManager,
                    )
                except RuntimeError:
                    pass
            return report

        self._parameterNode.cubeSourceVolume = cubeNode
        self._cubeBandCount = int(report["bandCount"])
        self._cubeWavelengths = report.get("wavelengths")
        self._cubeWavelengthReason = (
            "" if self._cubeWavelengths is not None else report["summaryMessage"]
        )
        band = 0 if slider is None else min(int(slider.value), self._cubeBandCount - 1)
        if slider is not None:
            blocked = slider.blockSignals(True)
            slider.setRange(0, self._cubeBandCount - 1)
            slider.setValue(band)
            slider.setEnabled(True)
            slider.blockSignals(blocked)
        if cubeWidget is not None:
            try:
                cubeLogic = cubeWidget.sliceLogic()
                composite = cubeLogic.GetSliceCompositeNode()
                if composite.GetBackgroundVolumeID() != cubeNode.GetID():
                    composite.SetBackgroundVolumeID(cubeNode.GetID())
                    composite.SetForegroundVolumeID(None)
                    composite.SetLabelVolumeID(None)
                    cubeLogic.FitSliceToBackground()
                self._removePanelMessage(self.CUBE_VIEW_NAME)
            except RuntimeError:
                pass
        self._setCubeBand(band, layoutManager)
        return report

    def _setCubeBand(self, band=0, layoutManager=None) -> None:
        label = getattr(getattr(self, "ui", None), "bandValueLabel", None)
        if self._cubeBandCount <= 0:
            if label is not None:
                label.setText(_("No HS cube received."))
                label.setToolTip("")
            return
        lastBand = self._cubeBandCount - 1
        band = max(0, min(int(band), lastBand))
        slider = getattr(self.ui, "bandSlider", None)
        if slider is not None and int(slider.value) != band:
            blocked = slider.blockSignals(True)
            slider.setValue(band)
            slider.blockSignals(blocked)
        if label is not None:
            if self._cubeWavelengths is not None:
                label.setText(
                    _("Band {band} (0 to {last}): {wavelength} nm").format(
                        band=band,
                        last=lastBand,
                        wavelength=f"{self._cubeWavelengths[band]:g}",
                    )
                )
                label.setToolTip("")
            else:
                label.setText(
                    _("Band {band} (0 to {last}): wavelength not available").format(
                        band=band, last=lastBand
                    )
                )
                label.setToolTip(self._cubeWavelengthReason)

        cubeNode = None if self._parameterNode is None else self._parameterNode.cubeSourceVolume
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME, layoutManager)
        if cubeNode is None or cubeWidget is None:
            return
        try:
            ijkToRas = vtk.vtkMatrix4x4()
            cubeNode.GetIJKToRASMatrix(ijkToRas)
            ras = ijkToRas.MultiplyPoint((0.0, 0.0, float(band), 1.0))
            cubeWidget.mrmlSliceNode().JumpSliceByOffsetting(ras[0], ras[1], ras[2])
            cubeView = cubeWidget.sliceView()
            if cubeView is not None:
                cubeView.forceRender()
        except (AttributeError, RuntimeError):
            return
