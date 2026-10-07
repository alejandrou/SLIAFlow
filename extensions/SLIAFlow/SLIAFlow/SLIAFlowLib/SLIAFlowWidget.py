import logging
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import qt
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

from .SLIAFlowCalibratedCube import CalibratedCubeError
from .SLIAFlowConnections import CHANNEL_HS_CUBE, CHANNEL_LIVE_VIEW, CHANNEL_STEREO
from .SLIAFlowLogic import SLIAFlowLogic
from .SLIAFlowParameterNode import (
    CAPTURE_ID_ATTRIBUTE,
    CUBE_SOURCE_APP,
    CUBE_SOURCES,
    DATA_ORIGIN_ATTRIBUTE,
    DEFAULT_RESULT_OUTPUT,
    GROUND_TRUTH_VIEW_NAME,
    RECEIVED_CUBE_NAME,
    RECORDED_CASE_ATTRIBUTE,
    RESULT_VIEW_NAMES,
    SIMULATED_ORIGIN,
    SIMULATION_DETAIL_ATTRIBUTE,
    WAVELENGTHS_ASSUMED_ATTRIBUTE,
    SLIAFlowParameterNode,
)
from .SLIAFlowUc1Run import OUTPUT_FILE_NAMES, Uc1Run, Uc1RunError
from .SLIAFlowUc2Run import Uc2RunError, uc2ParametersText


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
    """Present the six-panel WP5 operator surface and run a capture end to end."""

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
    # A panel with nothing to show says why, so it can never be mistaken for a
    # panel that is black because something broke.
    RESERVED_PANEL_REASONS = {
        STEREO_VIEW_NAME: _("Waiting for stereoscopic depth."),
        CUBE_VIEW_NAME: _("Waiting for the hyperspectral cube."),
        STO2_VIEW_NAME: _("Waiting for relative StO2."),
        VASCULAR_VIEW_NAME: _("Waiting for enhanced vascularization."),
    }
    LIVE_WAITING_MESSAGE = _("Waiting for the camera image.\nPress Start.")
    WAITING_RESULT_MESSAGE = _(
        "Waiting for the tumour delineation.\nPress Start, then Capture."
    )
    # Drawn at the top of Tumour Delineation over a result that is not from the
    # capture in progress, or from the capture that just failed.
    STALE_RESULT_MESSAGE = _("PREVIOUS RESULT - not from the current capture")
    STALE_LINE_FONT_SIZE = 14
    STALE_LINE_POSITION = (0.5, 0.97)
    STALE_LINE_BACKGROUND = (0.45, 0.3, 0.0)

    LAYOUT_CONFLICT_STATUS = _(
        "SLIAFlow could not activate its layout because another layout uses "
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

    CAPTURE_NO_FRAME_STATUS = _(
        "Capture needs a LiveView frame. Wait for the camera image, then press Capture."
    )
    CAPTURE_CAPTURING_STATUS = _("Capturing: LiveView is frozen and the frame is being saved.")
    CAPTURE_RUNNING_STATUS = _("Running UC1 on {cube} ({origin})...")
    CAPTURE_VALIDATING_STATUS = _("Validating the UC1 outputs for {cube}...")
    # ADR-0004 decision 5: UC1's model was trained on another camera, so a
    # result on the LCTF cube shows what the pipeline does, not how right it is.
    # Every status that describes a result on screen says so, stale ones too.
    CAPTURE_DONE_STATUS = _(
        "Done: UC1 results for {cube} are shown. They are not validated: UC1's "
        "model was trained on another camera. Snapshot saved as {snapshot}."
    )
    CAPTURE_FAILED_STATUS = _("Failed: {message} Press Capture to try again.")
    CAPTURE_FAILED_CASE_STATUS = _("Failed on {cube}: {message} Press Capture to try again.")
    # SLIA-036: Capture on the last cube from the app needs one.
    CAPTURE_NO_RECEIVED_CUBE_STATUS = _(
        "Capture uses the last cube from the app, and no complete cube has been received. "
        "Connect under Connections, or choose Cube on disk."
    )
    RESULT_NONE_STATUS = _("No UC1 result yet. Press Capture.")
    RESULT_STATUS = _(
        "{Cube} - {origin}. Showing {file}. UC1 results on this cube are not validated."
    )
    RESULT_STALE_STATUS = _(
        "Previous result: {cube}, {origin}. It is not from "
        "the current capture. UC1 results on this cube are not validated."
    )
    RESULT_SOURCE_TEXT = _("{file}, {cube}, capture {captureId}")
    GROUND_TRUTH_STATUS = _(
        "{Cube} - {origin}. Showing {file} under the recorded "
        "ground truth. UC1 results on this cube are not validated."
    )
    GROUND_TRUTH_SOURCE_TEXT = _("{file} under {groundTruth}, {cube}, capture {captureId}")
    GROUND_TRUTH_MISSING_STATUS = _(
        "{Cube} - {origin}. Showing {file}. Its ground truth "
        "could not be read. UC1 results on this cube are not validated."
    )
    NO_GROUND_TRUTH_STATUS = _(
        "{Cube} - {origin}. Showing {file}. This cube has no ground "
        "truth. UC1 results on this cube are not validated."
    )
    # SLIA-036: how the texts name a cube, and where it came from.
    RECORDED_CUBE_PHRASE = _("recorded cube {case}")
    RECEIVED_CUBE_PHRASE = _("the cube received from the app")
    STAND_IN_CUBE_PHRASE = _("the stand-in's cube received on the app's port")
    SIMULATED_ORIGIN_PHRASE = _("simulated acquisition")
    RECEIVED_ORIGIN_PHRASE = _("received from the app, captured live or replayed")
    # The label layer is drawn over the result, so it is half transparent: both
    # the labelled class and the classification under it stay readable.
    GROUND_TRUTH_LABEL_OPACITY = 0.5

    # SLIA-032: what HS Cube shows, and the captions that say which cube each
    # panel shows. View text names the input only (owner rule, 2026-09-18).
    CUBE_DISPLAY_BANDS = 0
    CUBE_DISPLAY_PREVIEW = 1
    CUBE_DISPLAY_ENTRIES = (_("Bands"), _("Colour preview"))
    CUBE_CAPTION = _("Recorded cube {cube}, calibrated reflectance")
    BAND_CAPTION = _("Band {band} of {bands} - {wavelength:g} nm")
    BAND_OUTSIDE_CAPTION = _("Between bands: scroll to a band of the cube")
    PREVIEW_CAPTION = _(
        "R {red:g} nm, G {green:g} nm, B {blue:g} nm - band composite, not a photograph"
    )
    # SLIA-036: a cube received from the app says so, says when it is raw, and
    # says that its wavelengths are assumed or unknown.
    RECEIVED_CUBE_CAPTION = _("Cube received from the app - {kind}")
    STAND_IN_CUBE_CAPTION = _("Cube from the stand-in for the app, simulated - {kind}")
    RAW_KIND = _("raw counts, uncalibrated")
    CALIBRATED_KIND = _("calibrated reflectance")
    ASSUMED_BAND_CAPTION = _(
        "Band {band} of {bands} - {wavelength:g} nm, assumed: the app sends no wavelengths"
    )
    UNKNOWN_WAVELENGTH_BAND_CAPTION = _("Band {band} of {bands} - wavelength not sent")
    RAW_PREVIEW_CAPTION = _("Scaled to the cube's brightest count")
    RECEIVED_WAITING_MESSAGE = _(
        "Waiting for a complete cube from the app.\nConnect under Connections."
    )
    RESULT_CAPTION = _("Result for {cube}")
    CUBE_UNREADABLE_MESSAGE = _("The hyperspectral cube could not be shown.\n{reason}")
    CAPTION_FONT_SIZE = 13
    # Top of HS Cube; bottom of Tumour Delineation, whose top carries the stale
    # line, and of Enhanced Vascularization, to match it.
    CAPTION_POSITIONS = {CUBE_VIEW_NAME: (0.5, 0.97), RESULT_VIEW_NAME: (0.5, 0.03),
                         VASCULAR_VIEW_NAME: (0.5, 0.03)}

    # SLIA-021: the UC2 blood-vessel map in Enhanced Vascularization. The panel
    # names the cube; the Status panel says how the map was made and why one
    # is missing. The map is a display enhancement, rescaled per channel within
    # each image, so it is never kept across captures.
    VASCULAR_CAPTION = _("Enhanced vascularization for {cube}")
    VASCULAR_FAILED_MESSAGE = _(
        "The enhanced vascularization could not be computed.\nThe Status panel says why."
    )
    VASCULAR_NONE_STATUS = _("No enhanced vascularization yet. Press Capture.")
    VASCULAR_RUNNING_STATUS = _("Computing the enhanced vascularization of {cube} (UC2)...")
    VASCULAR_STATUS = _(
        "Enhanced vascularization of {cube} - {origin}. UC2 "
        "blood-vessel enhancement with fixed {parameters}. A display enhancement, not a "
        "measurement: colours are rescaled within each image and are not comparable between "
        "captures. Not validated."
    )
    VASCULAR_FAILED_STATUS = _("Enhanced vascularization (UC2) failed: {message}")
    SPECTRUM_PROMPT = _("Click a pixel of HS Cube to plot its stored values.")
    SPECTRUM_LABEL = _(
        "Pixel column {column}, row {row} of {cube}: stored values, not an analysis."
    )
    SPECTRUM_NO_WAVELENGTHS_LABEL = _(
        "This cube carries no wavelengths, so its spectrum cannot be plotted against them."
    )
    SPECTRUM_OUTSIDE_LABEL = _(
        "That click was outside the cube. Click a pixel of HS Cube to plot its stored values."
    )
    CUSTOM_LAYOUT_DESCRIPTION = _layoutDescription(VIEW_ROWS)

    # SLIA-035: the Connections section.
    CONNECTIONS_REFRESH_MS = 500
    CONNECT_TEXT = _("Connect")
    DISCONNECT_TEXT = _("Disconnect")
    OPENIGTLINKIF_MODULE = "OpenIGTLinkIF"
    OPENIGTLINKIF_UNAVAILABLE_STATUS = _(
        "OpenIGTLinkIF could not be opened: {reason}"
    )
    CONNECTION_SETTING_CONTROLS = (
        "connectionsHostLineEdit",
        "liveViewPortSpinBox",
        "stereoPortSpinBox",
        "hsCubePortSpinBox",
        "expectedBandsSpinBox",
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
        self._staleLineActor = None
        self._staleLineRenderer = None
        self._cameraSupportAvailable = False
        self._cameraRestartRequired = False
        # Panel text other than the result view's waiting annotation, one actor
        # per view.
        self._panelAnnotationActors: dict[str, Any] = {}
        self._panelAnnotationRenderers: dict[str, Any] = {}
        self._panelMessages: dict[str, str] = {}
        # Capture state. A frame must have reached LiveView since the camera
        # started before it can be captured.
        self._frameDisplayed = False
        self._captureInProgress = False
        self._liveViewFrozen = False
        self._captureCaseName: str | None = None
        self._captureId: str | None = None
        self._captureSnapshotName: str | None = None
        # The accepted result on screen, and whether it is from an earlier
        # capture than the one in progress or the one that failed.
        self._resultCaseName: str | None = None
        # Whether the cube behind the result on screen has a gtMap beside it.
        self._resultHasGroundTruth = False
        self._resultCaptureId: str | None = None
        # The result capture the Tumour Delineation view was last framed for.
        self._fittedCaptureId: str | None = None
        # The recorded cube on screen, and the capture the HS Cube view was
        # last framed for.
        self._cubeCaptureId: str | None = None
        self._fittedCubeCaptureId: str | None = None
        # Why the last Capture's cube could not be shown, for the HS Cube panel.
        self._cubeError: str | None = None
        # SLIA-021. A capture ends once both runs are done: UC1, whose side is
        # pending from Capture until it succeeds, fails or is refused, and UC2,
        # pending only while its process runs.
        self._uc1Pending = False
        self._uc2Pending = False
        # The UC2 map on screen, the capture it belongs to and was last framed
        # for, the cube a running UC2 works on, and why the last run gave none.
        self._vascularCaseName: str | None = None
        self._vascularCaptureId: str | None = None
        self._fittedVascularCaptureId: str | None = None
        self._vascularRunningCase: str | None = None
        self._vascularError: str | None = None
        self._cubeDisplay = self.CUBE_DISPLAY_BANDS
        # Captions naming what a panel shows, one actor per view.
        self._panelCaptionActors: dict[str, Any] = {}
        self._panelCaptionRenderers: dict[str, Any] = {}
        self._panelCaptions: dict[str, str] = {}
        # The HS Cube slice node and interactor observed while presenting.
        self._observedCubeSliceNode = None
        self._observedCubeInteractor = None
        self._spectrumPlotWidget = None
        self._resultStale = False
        # True only while connectGui refills the output combo box.
        self._bindingResultSelector = False
        # The output on the background layer. Choosing gtMap lays the ground
        # truth over this one rather than replacing it, so it is remembered
        # across a gtMap selection.
        self._backgroundOutput = DEFAULT_RESULT_OUTPUT
        # SLIA-035. The settings last given to the connections, so that an
        # unchanged setting does not rebuild the rows and lose their errors.
        self._appliedConnectionSettings = None
        self._connectionsTimer = None
        self._observedParameterNode = None
        # SLIA-036. A cube completed while a capture runs on the last one is
        # held until the capture ends. The provenance of the cube the current
        # capture runs on, and whether a received one was the stand-in's; the
        # shown result and map keep their own, as the next capture changes it.
        self._heldReceivedCube = None
        self._captureProvenance = None
        self._receivedRunSimulated = False
        self._resultSimulated = False
        self._vascularSimulated = False
        # The run cube outlived a Disconnect only because a capture used it.
        self._removeRunCubeAfterCapture = False

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
        self.ui.captureButton.connect("clicked()", self._onCaptureClicked)
        self.ui.resultOutputSelector.connect(
            "currentIndexChanged(int)", self._onResultOutputChanged
        )
        for entry in self.CUBE_DISPLAY_ENTRIES:
            self.ui.cubeDisplaySelector.addItem(entry)
        self.ui.cubeDisplaySelector.connect(
            "currentIndexChanged(int)", self._onCubeDisplayChanged
        )
        self.ui.cubeSourceSelector.connect("currentIndexChanged(int)", self._onCubeSourceChanged)
        self._spectrumPlotWidget = slicer.qMRMLPlotWidget()
        self._spectrumPlotWidget.setMRMLScene(slicer.mrmlScene)
        self.ui.spectrumPlotContainer.layout().addWidget(self._spectrumPlotWidget)
        self.ui.spectrumLabel.setText(self.SPECTRUM_PROMPT)
        self.ui.connectButton.connect("clicked()", self._onConnectClicked)
        self.ui.openIGTLinkIFButton.connect("clicked()", self._onOpenInOpenIGTLinkIFClicked)
        header = self.ui.connectionsTable.horizontalHeader()
        header.setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self._connectionsTimer = qt.QTimer()
        self._connectionsTimer.setInterval(self.CONNECTIONS_REFRESH_MS)
        self._connectionsTimer.connect("timeout()", self._refreshConnections)
        # Module cleanup is not guaranteed to run before the process exits, and
        # a UC1 process or a connector left behind would outlive the module.
        slicer.app.connect("aboutToQuit()", self._onAboutToQuit)
        self.initializeParameterNode()
        self._setCameraSupportState(self.logic.openCVAvailable())
        self._updateResultStatus()
        self._updateVascularStatus()
        # Reload sets up a new widget but does not enter it, although the
        # module is still the selected one (slicer.util.reloadScriptedModule).
        if getattr(self.parent, "isEntered", False):
            self.enter()

    def cleanup(self) -> None:
        try:
            slicer.app.disconnect("aboutToQuit()", self._onAboutToQuit)
        except Exception:
            pass
        self._cancelCapture()
        # Releasing the connections also forgets the received cube.
        self._releaseConnections()
        if self._connectionsTimer is not None:
            self._connectionsTimer.stop()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self._forgetResult()
        self._forgetCube()
        self._forgetVascularMap()
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self._activatePresentation()
        if self.logic is not None:
            self._setCameraSupportState(self.logic.openCVAvailable())

    def exit(self) -> None:
        # The connections are left as they are, so that OpenIGTLinkIF, or any
        # module listing connectors, shows them (SLIA-035, owner request).
        self._cancelCapture()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self._forgetResult()
        self._forgetCube()
        self._forgetVascularMap()
        self.setParameterNode(None)

    def onSceneStartClose(self, caller=None, event=None) -> None:
        self._releaseConnections()
        self._cancelCapture()
        self._rememberLayoutBeforeSceneClose()
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=False)
        self._forgetResult()
        self._forgetCube()
        self._forgetVascularMap()
        self.setParameterNode(None)
        # The panels are empty again, so the Status panel must not still read
        # the previous capture's result.
        if self.logic is not None:
            self._setCameraSupportState(self.logic.openCVAvailable())

    def onSceneEndClose(self, caller=None, event=None) -> None:
        # The closed scene took the connectors; the new one lists them again,
        # whichever module is on screen.
        if self.logic is not None:
            self.logic.connections.listConnectors()
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
            # connectGui refills the output combo box before it writes the
            # stored value back, and refilling emits currentIndexChanged. Left
            # unguarded, that first index is taken for an operator choice and
            # overwrites the selection with the first file name.
            self._bindingResultSelector = True
            try:
                self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            finally:
                self._bindingResultSelector = False
        self._configureResultControls()
        self._updateResultStatus()
        self._showResult()
        self._observeConnectionSettings()
        self._refreshConnections()
        if self._parameterNode is not None and self.logic is not None:
            # OpenIGTLinkIF lists the app's ports from the moment SLIAFlow opens.
            self.logic.connections.listConnectors()

    def _configureResultControls(self) -> None:
        for name in ("resultOutputSelector", "cubeDisplaySelector"):
            selector = getattr(getattr(self, "ui", None), name, None)
            if selector is not None:
                selector.setEnabled(self._presentationActive)
        self._refreshGroundTruthEntry()
        self._refreshCameraControls()

    def _refreshGroundTruthEntry(self) -> None:
        """Offer gtMap only while the result on screen has a ground truth.

        ADR-0004 decision 8. The entry stays in the list, because the parameter
        binding selects by position and removing it would shift every index.
        It is hidden from the popup and disabled, which also keeps the keyboard
        and the mouse wheel from choosing it. connectGui refills the box, so
        this runs again after every binding.
        """
        selector = getattr(getattr(self, "ui", None), "resultOutputSelector", None)
        if selector is None:
            return
        index = selector.findText(GROUND_TRUTH_VIEW_NAME)
        if index < 0:
            return
        offered = self._resultCaseName is not None and self._resultHasGroundTruth
        item = selector.model().item(index)
        if item is not None:
            item.setEnabled(offered)
        selector.view().setRowHidden(index, not offered)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _refreshCameraControls(self) -> None:
        if self.logic is None or not hasattr(self, "ui"):
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
        self.ui.startButton.setEnabled(self._cameraSupportAvailable and not cameraActive)
        self.ui.stopButton.setEnabled(cameraActive)
        self._refreshCaptureControls()

    def _setCameraSupportState(self, available: bool) -> None:
        if self._cameraRestartRequired:
            self._cameraSupportAvailable = False
            self._refreshCameraControls()
            self._setStatus(self.CAMERA_INSTALL_RESTART_MESSAGE)
            return
        self._cameraSupportAvailable = bool(available)
        self._refreshCameraControls()
        if self.logic is not None and (self.logic.cameraActive or self._captureInProgress):
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
        if not self._captureInProgress:
            self._setStatus(self.CAMERA_READY_STATUS)

    def _handleCameraError(self, message: str) -> None:
        self._stopCamera(clearLiveView=True)
        self._setStatus(message)

    def _stopCamera(self, clearLiveView: bool, layoutManager=None) -> None:
        if self.logic is not None:
            self.logic.stopCamera()
        self._frameDisplayed = False
        if clearLiveView:
            self._clearLiveView(layoutManager=layoutManager)
        self._refreshCameraControls()

    def _clearLiveView(self, layoutManager=None) -> None:
        self._frameDisplayed = False
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
        # Frozen by Capture: the frame on screen is the one that was captured,
        # and it stays there until the capture ends.
        if self._liveViewFrozen:
            return
        liveNode = self.logic.getOrCreateLiveVolume(self._parameterNode)
        slicer.util.updateVolumeFromArray(liveNode, rgbKjiFrame)
        if not self._frameDisplayed:
            self._frameDisplayed = True
            self._refreshCaptureControls()

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
    # Capture (SLIA-027, ADR-0003)
    #
    # Capture freezes LiveView and saves the frame, reads the configured cube, and
    # runs UC1 on it in the background. LiveView resumes when the run ends,
    # whether it succeeded or not. A failed run is not retried on another cube.
    # ------------------------------------------------------------------

    @property
    def captureInProgress(self) -> bool:
        return self._captureInProgress

    @property
    def liveViewFrozen(self) -> bool:
        return self._liveViewFrozen

    def _refreshCaptureControls(self) -> None:
        button = getattr(getattr(self, "ui", None), "captureButton", None)
        if button is None or self.logic is None:
            return
        button.setEnabled(self.logic.cameraActive and not self._captureInProgress)
        # The cube a capture runs on stays on HS Cube until the capture ends.
        self.ui.cubeSourceSelector.setEnabled(not self._captureInProgress)

    def _onCaptureClicked(self) -> None:
        if self.logic is None or self._parameterNode is None:
            return
        if self._captureInProgress or not self.logic.cameraActive:
            return
        liveNode = self._parameterNode.liveVolume
        if not self._frameDisplayed or liveNode is None or liveNode.GetImageData() is None:
            self._setStatus(self.CAPTURE_NO_FRAME_STATUS)
            return
        if self._cubeSourceIsApp() and self.logic.receivedCubeNode() is None:
            # Refused before anything is frozen or saved.
            self._setStatus(self.CAPTURE_NO_RECEIVED_CUBE_STATUS)
            return

        self._captureInProgress = True
        self._uc1Pending = True
        self._uc2Pending = False
        self._liveViewFrozen = True
        self._captureCaseName = None
        self._captureSnapshotName = None
        self._captureId = self.logic.newCaptureId()
        self._refreshCaptureControls()
        if self._resultCaseName is not None:
            self._resultStale = True
            self._updateResultStatus()
            self._updateStaleLine()
        # The previous map is not kept: it is rescaled within its own image and
        # says nothing about this capture.
        self._forgetVascularMap()
        self._showVascularMap()
        self._setStatus(self.CAPTURE_CAPTURING_STATUS)

        try:
            self._startCapture(liveNode)
        except Exception as error:
            # Whatever went wrong, LiveView must not stay frozen.
            logging.exception("SLIAFlow: capture %s could not be started", self._captureId)
            self.logic.cancelRun()
            self._uc2Pending = False
            self._updateVascularStatus()
            self._failCapture(_("The capture could not be started: {error}").format(error=error))

    def _startCapture(self, liveNode) -> None:
        frame = np.array(slicer.util.arrayFromVolume(liveNode), copy=True)
        try:
            self._captureSnapshotName = self.logic.saveSnapshot(frame).name
        except (OSError, ValueError, Uc1RunError) as error:
            self._failCapture(_("The capture snapshot could not be saved: {error}").format(error=error))
            return

        if self._cubeSourceIsApp():
            self._startCaptureOnReceivedCube()
            return
        self._captureProvenance = None
        # UC2 starts first: it is independent of UC1, and a UC1 refusal ends
        # UC1's side of the capture at once, which must not end it before UC2
        # has been started.
        self._startUc2()
        self._startUc1()
        # UC1 runs in its own process, so the cube is read while it runs. The
        # cube does not need UC1: it is shown whether or not the run started.
        self._showCapturedCube()

    def _startCaptureOnReceivedCube(self) -> None:
        """Run UC1 and UC2 on the last cube from the app, or say why they cannot (SLIA-036).

        The cube stays on HS Cube as received, now this capture's. A float32
        cube with wavelengths is written once for the runs; a raw one, or one
        without wavelengths, runs nothing.
        """
        node = self.logic.receivedCubeNode()
        node.SetAttribute(CAPTURE_ID_ATTRIBUTE, self._captureId)
        self._receivedRunSimulated = node.GetAttribute(DATA_ORIGIN_ATTRIBUTE) == SIMULATED_ORIGIN
        self._captureProvenance = (node.GetAttribute(DATA_ORIGIN_ATTRIBUTE),
                                   node.GetAttribute(SIMULATION_DETAIL_ATTRIBUTE))
        self._captureCaseName = RECEIVED_CUBE_NAME
        self._cubeError = None
        self._resetSpectrumLabel()
        self._showCube()
        try:
            cube = self.logic.writeReceivedCubeForRun(node)
        except (CalibratedCubeError, OSError) as error:
            self._failVascular(str(error))
            self._failCapture(str(error))
            return
        self._startUc2(cube)
        self._startUc1(cube)

    def _startUc1(self, cube=None) -> None:
        """Start UC1 on `cube` or the configured cube, or end the capture saying why."""
        try:
            case = (self.logic.loadConfiguredUc1Input() if cube is None
                    else self.logic.uc1InputFor(cube))
        except (CalibratedCubeError, Uc1RunError, OSError) as error:
            self._failCapture(str(error))
            return
        self._captureCaseName = case.name
        logging.info(
            "SLIAFlow: capture %s uses cube %s; snapshot %s",
            self._captureId, case.name, self._captureSnapshotName,
        )

        try:
            self.logic.startUc1Run(case, self._onUc1Finished, onStage=self._onUc1Stage)
        except (Uc1RunError, OSError) as error:
            self._failCapture(str(error))

    def _startUc2(self, cube=None) -> None:
        """Start UC2 on `cube` or the configured cube, or say on its own panel and line why not.

        UC2 is independent of UC1 (SLIA-021): its refusal or failure never ends
        the capture early, fails UC1 or touches the Tumour Delineation panel.
        """
        try:
            if cube is None:
                cube = self.logic.loadConfiguredCalibratedCube()
            self.logic.startUc2Run(cube, self._onUc2Finished)
        except (CalibratedCubeError, Uc2RunError, OSError) as error:
            self._failVascular(str(error))
            return
        except Exception as error:
            logging.exception("SLIAFlow: UC2 could not be started for capture %s", self._captureId)
            self._failVascular(_("It could not be started: {error}").format(error=error))
            return
        self._uc2Pending = True
        self._vascularRunningCase = cube.name
        self._updateVascularStatus()

    def _onUc2Finished(self, result) -> None:
        if not self._uc2Pending:
            return
        self._uc2Pending = False
        self._vascularRunningCase = None
        if not result.success:
            logging.warning("SLIAFlow: %s", result.message)
            self._failVascular(result.message)
        else:
            try:
                self.logic.acceptVascularMap(result.cube, self._captureId, result.image,
                                             provenance=self._captureProvenance)
            except Exception as error:
                logging.exception("SLIAFlow: the UC2 map of cube %s could not be shown",
                                  result.cube.name)
                self._failVascular(_("The map could not be shown: {error}").format(error=error))
            else:
                logging.info("SLIAFlow: %s", result.message)
                self._vascularCaseName = result.cube.name
                self._vascularSimulated = self._receivedRunSimulated
                self._vascularCaptureId = self._captureId
                self._vascularError = None
                self._updateVascularStatus()
                self._showVascularMap()
        self._finishCaptureIfIdle()

    def _failVascular(self, message: str) -> None:
        self._vascularError = message
        self._vascularRunningCase = None
        self._updateVascularStatus()
        self._showVascularMap()

    def _showCapturedCube(self) -> None:
        """Show the calibrated cube this capture stands for (SLIA-032).

        It is the cube UC1 runs on (SLIA-033), and both panels name it. The
        panel reads it separately from the run: if the cube cannot be shown,
        HS Cube says why, and a run already started goes on.
        """
        if self.logic is None:
            return
        try:
            cube = self.logic.loadConfiguredCalibratedCube()
            self.logic.acceptCube(cube, self._captureId)
            self._cubeError = None
            self._cubeCaptureId = self._captureId
            self._resetSpectrumLabel()
            self._showCube()
        except Exception as error:
            # Reading and drawing the cube are both only for the panel, so
            # neither may reach the caller and end the capture.
            logging.exception(
                "SLIAFlow: the calibrated cube %s could not be shown: %s",
                self.logic.calibratedCubeHeader, error,
            )
            self._forgetCube()
            self._cubeError = (
                str(error) if isinstance(error, CalibratedCubeError)
                else _("It could not be read: {error}").format(error=error)
            )
            self._showCube()

    def _showGroundTruth(self, case) -> None:
        """Load the cube's own labelling for the result just accepted.

        The ground truth is read once per result rather than per selection, and
        only after the outputs are accepted, so it always carries the capture ID
        of the result it can be laid over. It is not what the capture is for: if
        it cannot be read, the run still succeeded, the result is still shown,
        and choosing gtMap says the ground truth could not be read.
        """
        if self.logic is None:
            return
        try:
            self.logic.acceptGroundTruth(case, self._captureId)
        except Exception as error:
            logging.exception(
                "SLIAFlow: the ground truth of cube %s could not be shown: %s",
                case.name, error,
            )
            self.logic.removeGroundTruthNode()

    def _forgetCube(self) -> None:
        if self.logic is not None:
            self.logic.removeCubeNode()
        self._cubeCaptureId = None
        self._fittedCubeCaptureId = None
        self._cubeError = None
        self._resetSpectrumLabel()
        self._removePanelCaption(self.CUBE_VIEW_NAME)

    def _resetSpectrumLabel(self) -> None:
        label = getattr(getattr(self, "ui", None), "spectrumLabel", None)
        if label is not None:
            label.setText(self.SPECTRUM_PROMPT)

    def _cubeSourceIsApp(self) -> bool:
        return self._parameterNode is not None and self._parameterNode.cubeSource == CUBE_SOURCE_APP

    def _displayedCubeNode(self):
        """The cube HS Cube shows: the last one from the app, or the one read for the capture."""
        if self.logic is None:
            return None
        return self.logic.receivedCubeNode() if self._cubeSourceIsApp() else self.logic.cubeNode()

    def _onCubeSourceChanged(self, index=None) -> None:
        # This slot runs before the parameter-node binding's own, so the choice
        # is taken from the box; while connectGui refills it, it is not a choice.
        if self._bindingResultSelector:
            return
        selector = getattr(getattr(self, "ui", None), "cubeSourceSelector", None)
        if (self._parameterNode is not None and selector is not None
                and selector.currentText in CUBE_SOURCES):
            self._parameterNode.cubeSource = selector.currentText
        self._resetSpectrumLabel()
        self._showCube()

    def _onCubeDisplayChanged(self, index=None) -> None:
        selector = getattr(getattr(self, "ui", None), "cubeDisplaySelector", None)
        if selector is None:
            return
        self._cubeDisplay = (self.CUBE_DISPLAY_PREVIEW
                             if selector.currentIndex == self.CUBE_DISPLAY_PREVIEW
                             else self.CUBE_DISPLAY_BANDS)
        self._showCube()

    def _cubeDisplayNode(self, cubeNode):
        """The volume HS Cube shows for the chosen display: the cube or its preview.

        The preview is built from the cube on screen the first time it is asked
        for, and again for every new cube. If it cannot be built, the bands are
        shown rather than nothing.
        """
        if self._cubeDisplay != self.CUBE_DISPLAY_PREVIEW or self.logic is None:
            return cubeNode
        preview = self.logic.colourPreviewNode()
        if (preview is None or preview.GetAttribute(CAPTURE_ID_ATTRIBUTE)
                != cubeNode.GetAttribute(CAPTURE_ID_ATTRIBUTE)):
            try:
                preview = self.logic.acceptColourPreview(cubeNode)
            except Exception:
                logging.exception("SLIAFlow: the colour preview could not be built")
                return cubeNode
        return preview

    def _showCube(self, layoutManager=None) -> None:
        """Bind the cube or its preview to HS Cube, or say why the panel is empty."""
        if not self._presentationActive:
            return
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME, layoutManager)
        if cubeWidget is None:
            return
        node = self._displayedCubeNode()
        try:
            sliceLogic = cubeWidget.sliceLogic()
            composite = sliceLogic.GetSliceCompositeNode()
            if node is None:
                self._clearSliceLayers(cubeWidget)
                self._removePanelCaption(self.CUBE_VIEW_NAME)
                if self._cubeSourceIsApp():
                    message = self.RECEIVED_WAITING_MESSAGE
                elif self._cubeError:
                    message = self.CUBE_UNREADABLE_MESSAGE.format(reason=self._cubeError)
                else:
                    message = self.RESERVED_PANEL_REASONS[self.CUBE_VIEW_NAME]
                self._showPanelMessage(self.CUBE_VIEW_NAME, message, layoutManager)
            else:
                self._removePanelMessage(self.CUBE_VIEW_NAME)
                shown = self._cubeDisplayNode(node)
                # Every new cube, and every switch between the bands and the
                # preview, is framed for its own; a redraw of the same volume
                # keeps the operator's framing and the band they scrolled to.
                cubeCaptureId = node.GetAttribute(CAPTURE_ID_ATTRIBUTE)
                if (composite.GetBackgroundVolumeID() != shown.GetID()
                        or self._fittedCubeCaptureId != cubeCaptureId):
                    composite.SetBackgroundVolumeID(shown.GetID())
                    sliceLogic.FitSliceToBackground()
                    self._fittedCubeCaptureId = cubeCaptureId
                    if shown is node:
                        self._showMiddleBand(sliceLogic, node)
                composite.SetForegroundVolumeID(None)
                # The cube is shown alone. The ground truth is a labelling of
                # the image the outputs classify, not of the spectrum, and it
                # belongs on the result panel (_showResult). It could not be
                # read here in any case: the bands run along S, and a one-band
                # label map placed in that stack is off the plane the operator
                # is scrolling.
                composite.SetLabelVolumeID(None)
                self._updateCubeCaption(layoutManager)
            cubeView = cubeWidget.sliceView()
            if cubeView is not None:
                cubeView.forceRender()
        except RuntimeError:
            return

    def _updateCubeCaption(self, layoutManager=None) -> None:
        """Name the cube on HS Cube, with the band on screen or the preview's bands."""
        node = self._displayedCubeNode()
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME, layoutManager)
        if not self._presentationActive or node is None or cubeWidget is None:
            self._removePanelCaption(self.CUBE_VIEW_NAME)
            return
        composite = cubeWidget.sliceLogic().GetSliceCompositeNode()
        preview = self.logic.colourPreviewNode()
        raw = self._isRawCube(node)
        lines = [self._cubeCaptionLine(node, raw)]
        if preview is not None and composite.GetBackgroundVolumeID() == preview.GetID():
            red, green, blue = self.logic.previewWavelengths(preview)
            lines.append(self.PREVIEW_CAPTION.format(red=red, green=green, blue=blue))
            if raw:
                lines.append(self.RAW_PREVIEW_CAPTION)
        else:
            sliceToRas = cubeWidget.mrmlSliceNode().GetSliceToRAS()
            centre = [sliceToRas.GetElement(row, 3) for row in range(3)]
            band = self.logic.cubeBandAt(node, centre)
            wavelengths = self.logic.cubeWavelengths(node)
            bands = node.GetImageData().GetDimensions()[2]
            if band is None:
                lines.append(self.BAND_OUTSIDE_CAPTION)
            elif band >= len(wavelengths):
                lines.append(self.UNKNOWN_WAVELENGTH_BAND_CAPTION.format(band=band + 1,
                                                                         bands=bands))
            elif node.GetAttribute(WAVELENGTHS_ASSUMED_ATTRIBUTE):
                lines.append(self.ASSUMED_BAND_CAPTION.format(
                    band=band + 1, bands=bands, wavelength=wavelengths[band]))
            else:
                lines.append(self.BAND_CAPTION.format(
                    band=band + 1, bands=len(wavelengths), wavelength=wavelengths[band]))
        self._showPanelCaption(self.CUBE_VIEW_NAME, "\n".join(lines), layoutManager)

    @staticmethod
    def _isRawCube(node) -> bool:
        image = node.GetImageData() if node is not None else None
        return image is not None and image.GetScalarType() not in (vtk.VTK_FLOAT, vtk.VTK_DOUBLE)

    @staticmethod
    def _isReceivedCube(node) -> bool:
        return node is not None and node.GetAttribute(RECORDED_CASE_ATTRIBUTE) == RECEIVED_CUBE_NAME

    def _cubeCaptionLine(self, node, raw: bool) -> str:
        """The first caption line of HS Cube: which cube it is, and what its values are."""
        if not self._isReceivedCube(node):
            return self.CUBE_CAPTION.format(cube=node.GetAttribute(RECORDED_CASE_ATTRIBUTE))
        kind = self.RAW_KIND if raw else self.CALIBRATED_KIND
        if node.GetAttribute(DATA_ORIGIN_ATTRIBUTE) == SIMULATED_ORIGIN:
            return self.STAND_IN_CUBE_CAPTION.format(kind=kind)
        return self.RECEIVED_CUBE_CAPTION.format(kind=kind)

    def _cubeText(self, caseName, simulated=None) -> dict:
        """How the texts name the cube a capture ran on: `cube`, `Cube` and `origin`.

        A received cube is named for where it came from (SLIA-036). The cube on
        disk keeps the wording it always had.
        """
        if caseName == RECEIVED_CUBE_NAME:
            if simulated is None:
                simulated = self._receivedRunSimulated
            cube = self.STAND_IN_CUBE_PHRASE if simulated else self.RECEIVED_CUBE_PHRASE
            origin = self.SIMULATED_ORIGIN_PHRASE if simulated else self.RECEIVED_ORIGIN_PHRASE
        else:
            cube = self.RECORDED_CUBE_PHRASE.format(case=caseName)
            origin = self.SIMULATED_ORIGIN_PHRASE
        return {"cube": cube, "Cube": cube[:1].upper() + cube[1:], "origin": origin}

    def _onCubeSliceModified(self, caller=None, event=None) -> None:
        self._updateCubeCaption()

    # ------------------------------------------------------------------
    # Pixel spectrum (SLIA-032)
    # ------------------------------------------------------------------

    def _onCubeViewPressed(self, caller=None, event=None) -> None:
        """A left press on HS Cube plots the pixel under it. The press is not consumed."""
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME)
        if caller is None or cubeWidget is None or self.logic is None:
            return
        if self._displayedCubeNode() is None:
            return
        try:
            x, y = caller.GetEventPosition()
            xyz = cubeWidget.sliceView().convertDeviceToXYZ([x, y])
            self._pickCubePixelAtXYZ(list(xyz))
        except Exception:
            # A plot that cannot be drawn must not break the view's own interaction.
            logging.exception("SLIAFlow: the clicked pixel's spectrum could not be shown")

    def _pickCubePixelAtXYZ(self, xyz) -> None:
        """Plot the stored spectrum of the cube pixel drawn at slice-view XY `xyz`."""
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME)
        node = self._displayedCubeNode()
        if cubeWidget is None or node is None:
            return
        # As the Data Probe does: the background layer maps view XY to the IJK
        # of the volume it draws. The preview shares the cube's columns and rows.
        xyToIjk = cubeWidget.sliceLogic().GetBackgroundLayer().GetXYToIJKTransform()
        ijk = xyToIjk.TransformDoublePoint(list(xyz)[:3])
        column, row = int(round(ijk[0])), int(round(ijk[1]))
        try:
            chart = self.logic.showPixelSpectrum(node, column, row)
        except IndexError:
            self.ui.spectrumLabel.setText(self.SPECTRUM_OUTSIDE_LABEL)
            return
        except ValueError:
            self.ui.spectrumLabel.setText(self.SPECTRUM_NO_WAVELENGTHS_LABEL)
            return
        viewNode = self.logic.spectrumPlotViewNode()
        viewNode.SetPlotChartNodeID(chart.GetID())
        if self._spectrumPlotWidget is not None:
            if self._spectrumPlotWidget.mrmlPlotViewNode() is not viewNode:
                self._spectrumPlotWidget.setMRMLPlotViewNode(viewNode)
        self.ui.spectrumCollapsibleButton.collapsed = False
        simulated = node.GetAttribute(DATA_ORIGIN_ATTRIBUTE) == SIMULATED_ORIGIN
        self.ui.spectrumLabel.setText(self.SPECTRUM_LABEL.format(
            column=column, row=row,
            cube=self._cubeText(node.GetAttribute(RECORDED_CASE_ATTRIBUTE), simulated)["cube"]))

    def _observeCubeView(self, layoutManager=None) -> None:
        """Follow HS Cube's slice (for the band caption) and its clicks (for the spectrum)."""
        self._stopObservingCubeView()
        cubeWidget = self._sliceWidgetOrNone(self.CUBE_VIEW_NAME, layoutManager)
        if cubeWidget is None:
            return
        sliceNode = cubeWidget.mrmlSliceNode()
        self.addObserver(sliceNode, vtk.vtkCommand.ModifiedEvent, self._onCubeSliceModified)
        self._observedCubeSliceNode = sliceNode
        interactor = cubeWidget.sliceView().interactorStyle().GetInteractor()
        self.addObserver(interactor, vtk.vtkCommand.LeftButtonPressEvent, self._onCubeViewPressed)
        self._observedCubeInteractor = interactor

    def _stopObservingCubeView(self) -> None:
        if self._observedCubeSliceNode is not None:
            self.removeObserver(self._observedCubeSliceNode, vtk.vtkCommand.ModifiedEvent,
                                self._onCubeSliceModified)
            self._observedCubeSliceNode = None
        if self._observedCubeInteractor is not None:
            self.removeObserver(self._observedCubeInteractor, vtk.vtkCommand.LeftButtonPressEvent,
                                self._onCubeViewPressed)
            self._observedCubeInteractor = None

    @staticmethod
    def _showMiddleBand(sliceLogic, node) -> None:
        """Open the cube in the middle of its spectrum.

        The first band is the shortest wavelength and the darkest, so a cube
        opened at band 0 looks like a panel that failed rather than one the
        operator can scroll. The bands run along S, so the middle band is the
        middle of the volume's S bounds.
        """
        bounds = [0.0] * 6
        try:
            node.GetRASBounds(bounds)
            sliceLogic.SetSliceOffset((bounds[4] + bounds[5]) / 2.0)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _onUc1Stage(self, stage: str) -> None:
        if stage == Uc1Run.STAGE_RUNNING:
            self._setStatus(self.CAPTURE_RUNNING_STATUS.format(
                **self._cubeText(self._captureCaseName)))
        elif stage == Uc1Run.STAGE_VALIDATING:
            self._setStatus(self.CAPTURE_VALIDATING_STATUS.format(
                **self._cubeText(self._captureCaseName)))

    def _onUc1Finished(self, result) -> None:
        if not self._captureInProgress:
            return
        if not result.success:
            logging.warning("SLIAFlow: %s", result.message)
            self._failCapture(result.message)
            return
        try:
            self.logic.acceptOutputs(result.case, self._captureId, result.outputs,
                                     provenance=self._captureProvenance)
        except Exception as error:
            # acceptOutputs leaves the previous result whole; the capture must
            # still end, or Capture stays disabled and LiveView frozen.
            logging.exception("SLIAFlow: the outputs of cube %s could not be shown",
                              result.case.name)
            self._failCapture(_("The UC1 outputs could not be shown: {error}").format(error=error))
            return
        # A ground truth is offered only for a cube that has one (ADR-0004
        # decision 8); the previous result's is not left behind for this one.
        self._resultHasGroundTruth = result.case.hasGroundTruth
        if self._resultHasGroundTruth:
            self._showGroundTruth(result.case)
        elif self.logic is not None:
            self.logic.removeGroundTruthNode()
        self._resultCaseName = result.case.name
        self._resultSimulated = self._receivedRunSimulated
        self._resultCaptureId = self._captureId
        self._resultStale = False
        self._refreshGroundTruthEntry()
        logging.info("SLIAFlow: %s", result.message)
        self._setStatus(
            self.CAPTURE_DONE_STATUS.format(
                **self._cubeText(result.case.name), snapshot=self._captureSnapshotName
            )
        )
        self._endCapture()
        self._showResult()

    def _failCapture(self, message: str) -> None:
        if self._captureCaseName is not None:
            status = self.CAPTURE_FAILED_CASE_STATUS.format(
                **self._cubeText(self._captureCaseName), message=message
            )
        else:
            status = self.CAPTURE_FAILED_STATUS.format(message=message)
        self._setStatus(status)
        self._endCapture()

    def _endCapture(self) -> None:
        """UC1's side of the capture is over; end the capture unless UC2 still runs."""
        self._uc1Pending = False
        self._finishCaptureIfIdle()

    def _finishCaptureIfIdle(self) -> None:
        """Unfreeze LiveView and allow the next Capture once UC1 and UC2 are both done.

        The stale mark stays.
        """
        if not self._captureInProgress or self._uc1Pending or self._uc2Pending:
            return
        self._captureInProgress = False
        self._liveViewFrozen = False
        self._captureCaseName = None
        self._refreshCaptureControls()
        self._updateResultStatus()
        self._updateStaleLine()
        if self._removeRunCubeAfterCapture:
            self._removeRunCubeAfterCapture = False
            self._removeReceivedRunCube()
        held, self._heldReceivedCube = self._heldReceivedCube, None
        if held is not None:
            self._receiveCube(held)

    def _cancelCapture(self) -> None:
        """Kill the owned UC1 and UC2 runs and release their locks, without reporting them."""
        if self.logic is not None:
            self.logic.cancelRun()
        if self._uc2Pending:
            self._uc2Pending = False
            self._vascularRunningCase = None
            self._updateVascularStatus()
        if self._captureInProgress:
            self._endCapture()

    # ------------------------------------------------------------------
    # Tumour Delineation: one UC1 output at a time
    # ------------------------------------------------------------------

    def staleResultLine(self) -> str:
        """The line drawn over the result view, or an empty string."""
        return self.STALE_RESULT_MESSAGE if self._resultStale and self._resultCaseName else ""

    def _selectedView(self) -> str:
        """The entry chosen in the Delineation output box: an output, or gtMap."""
        if self._parameterNode is not None and self._parameterNode.resultOutput in RESULT_VIEW_NAMES:
            return self._parameterNode.resultOutput
        return DEFAULT_RESULT_OUTPUT

    def _groundTruthSelected(self) -> bool:
        return self._selectedView() == GROUND_TRUTH_VIEW_NAME

    def _groundTruthNode(self):
        """The ground truth of the result on screen, or None.

        A ground truth from any other capture is not returned. Laying one case's
        labelling over another case's result would read as agreement or
        disagreement that was never measured.
        """
        if self.logic is None or self._resultCaptureId is None:
            return None
        node = self.logic.groundTruthNode()
        if node is None or node.GetAttribute(CAPTURE_ID_ATTRIBUTE) != self._resultCaptureId:
            return None
        return node

    def _selectedOutput(self) -> str:
        """The output image on the background layer, whether or not gtMap is on."""
        view = self._selectedView()
        return view if view in OUTPUT_FILE_NAMES else self._backgroundOutput

    def _onResultOutputChanged(self, index=None) -> None:
        if self._bindingResultSelector:
            return
        selector = getattr(getattr(self, "ui", None), "resultOutputSelector", None)
        if self._parameterNode is not None and selector is not None:
            selected = selector.currentText
            if selected in RESULT_VIEW_NAMES:
                self._parameterNode.resultOutput = selected
                if selected in OUTPUT_FILE_NAMES:
                    self._backgroundOutput = selected
        self._updateResultStatus()
        self._showResult()

    def _forgetResult(self) -> None:
        """Remove the output nodes and everything that describes them."""
        if self.logic is not None:
            self.logic.removeOutputNodes()
            self.logic.removeGroundTruthNode()
        self._resultCaseName = None
        self._resultCaptureId = None
        self._resultHasGroundTruth = False
        self._fittedCaptureId = None
        self._resultStale = False
        self._removeStaleLine()
        self._removePanelCaption(self.RESULT_VIEW_NAME)
        if hasattr(self, "ui"):
            self._refreshGroundTruthEntry()
            self._updateResultStatus()

    def _updateResultStatus(self) -> None:
        label = getattr(getattr(self, "ui", None), "resultStatusLabel", None)
        sourceLabel = getattr(getattr(self, "ui", None), "resultSourceValueLabel", None)
        if self._resultCaseName is None:
            text, style, source = self.RESULT_NONE_STATUS, "", _("None")
        else:
            fileName = self._selectedOutput()
            groundTruthShown = self._groundTruthSelected() and self._groundTruthNode() is not None
            words = self._cubeText(self._resultCaseName, self._resultSimulated)
            if groundTruthShown:
                source = self.GROUND_TRUTH_SOURCE_TEXT.format(
                    file=fileName, groundTruth=GROUND_TRUTH_VIEW_NAME,
                    captureId=self._resultCaptureId, **words,
                )
            else:
                source = self.RESULT_SOURCE_TEXT.format(
                    file=fileName, captureId=self._resultCaptureId, **words
                )
            if self._resultStale:
                text = self.RESULT_STALE_STATUS.format(**words)
                style = "color: #8A6D1D; font-weight: bold;"
            elif groundTruthShown:
                text = self.GROUND_TRUTH_STATUS.format(file=fileName, **words)
                style = "font-weight: bold;"
            elif self._groundTruthSelected() and not self._resultHasGroundTruth:
                # A gtMap selection kept from an earlier cube: this one has none
                # to lay over, which is not the same as one that failed to read.
                text = self.NO_GROUND_TRUTH_STATUS.format(file=fileName, **words)
                style = "font-weight: bold;"
            elif self._groundTruthSelected():
                # gtMap was asked for and is not there: say so rather than
                # showing the result alone as though it had been laid over.
                text = self.GROUND_TRUTH_MISSING_STATUS.format(file=fileName, **words)
                style = "color: #8A6D1D; font-weight: bold;"
            else:
                text = self.RESULT_STATUS.format(file=fileName, **words)
                style = "font-weight: bold;"
        if label is not None:
            label.setText(text)
            label.setStyleSheet(style)
        if sourceLabel is not None:
            sourceLabel.setText(source)

    def _showResult(self, layoutManager=None) -> None:
        """Bind the selected output to Tumour Delineation, alone, or show waiting."""
        if not self._presentationActive:
            return
        resultWidget = self._sliceWidgetOrNone(self.RESULT_VIEW_NAME, layoutManager)
        if resultWidget is None:
            return
        node = None
        if self.logic is not None and self._resultCaseName is not None:
            node = self.logic.outputNode(self._selectedOutput())
        try:
            sliceLogic = resultWidget.sliceLogic()
            composite = sliceLogic.GetSliceCompositeNode()
            if node is None:
                self._clearSliceLayers(resultWidget)
                self._removePanelCaption(self.RESULT_VIEW_NAME)
                self._showWaitingAnnotation(resultWidget)
            else:
                self._removeWaitingAnnotation()
                # Until SLIA-033 the result is not from the cube HS Cube shows,
                # so the panel names its own.
                self._showPanelCaption(
                    self.RESULT_VIEW_NAME,
                    self.RESULT_CAPTION.format(
                        **self._cubeText(self._resultCaseName, self._resultSimulated)),
                    layoutManager,
                )
                boundBefore = composite.GetBackgroundVolumeID()
                composite.SetBackgroundVolumeID(node.GetID())
                # Cubes can differ in size, so every new result is framed
                # for its own; changing the selected output within one result
                # binds a same-sized image, so the framing is left alone and
                # the operator keeps the pan and zoom they were reading with.
                # An empty panel is refitted whatever the capture: a rebuilt
                # layout gives the view a default field of view that the
                # result would otherwise sit outside.
                if self._fittedCaptureId != self._resultCaptureId or not boundBefore:
                    sliceLogic.FitSliceToBackground()
                    self._fittedCaptureId = self._resultCaptureId
                composite.SetForegroundVolumeID(None)
                # The cube's own labelling belongs over the output it
                # is read against, on the Label layer, so the layer's opacity
                # slider and outline toggle work on it. _groundTruthNode()
                # returns it only when it carries this result's capture ID.
                groundTruthNode = (
                    self._groundTruthNode() if self._groundTruthSelected() else None
                )
                if groundTruthNode is None:
                    composite.SetLabelVolumeID(None)
                else:
                    composite.SetLabelVolumeID(groundTruthNode.GetID())
                    composite.SetLabelOpacity(self.GROUND_TRUTH_LABEL_OPACITY)
            self._updateStaleLine(layoutManager)
            resultView = resultWidget.sliceView()
            if resultView is not None:
                resultView.forceRender()
        except RuntimeError:
            return

    def _updateStaleLine(self, layoutManager=None) -> None:
        if not self.staleResultLine() or not self._presentationActive:
            self._removeStaleLine()
            return
        resultWidget = self._sliceWidgetOrNone(self.RESULT_VIEW_NAME, layoutManager)
        if resultWidget is None:
            return
        renderer = self._sliceViewRenderer(resultWidget)
        if renderer is None:
            return
        if self._staleLineActor is None:
            actor = vtk.vtkTextActor()
            actor.SetInput(self.STALE_RESULT_MESSAGE)
            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            actor.SetPosition(*self.STALE_LINE_POSITION)
            textProperty = actor.GetTextProperty()
            textProperty.SetFontSize(self.STALE_LINE_FONT_SIZE)
            textProperty.SetBold(True)
            textProperty.SetColor(1.0, 1.0, 1.0)
            textProperty.SetBackgroundColor(*self.STALE_LINE_BACKGROUND)
            textProperty.SetBackgroundOpacity(1.0)
            textProperty.SetJustificationToCentered()
            textProperty.SetVerticalJustificationToTop()
            self._staleLineActor = actor
        self._staleLineRenderer = self._placeAnnotationActor(
            renderer, self._staleLineActor, self._staleLineRenderer
        )
        resultView = resultWidget.sliceView()
        if resultView is not None:
            resultView.forceRender()

    def _removeStaleLine(self) -> None:
        renderer, self._staleLineRenderer = self._staleLineRenderer, None
        actor = self._staleLineActor
        if renderer is None or actor is None:
            return
        try:
            renderer.RemoveActor2D(actor)
        except (RuntimeError, ValueError):
            pass

    def _setStatus(self, message: str) -> None:
        statusLabel = getattr(getattr(self, "ui", None), "statusLabel", None)
        if statusLabel is not None:
            statusLabel.setText(message)

    # ------------------------------------------------------------------
    # Enhanced Vascularization: the UC2 map of this capture (SLIA-021)
    # ------------------------------------------------------------------

    def _vascularMapNode(self):
        """The UC2 map of the capture it was accepted for, or None.

        A map from any other capture is never returned, so the panel cannot
        show a previous capture's map as this one's.
        """
        if self.logic is None or self._vascularCaptureId is None:
            return None
        node = self.logic.vascularMapNode()
        if node is None or node.GetAttribute(CAPTURE_ID_ATTRIBUTE) != self._vascularCaptureId:
            return None
        return node

    def _showVascularMap(self, layoutManager=None) -> None:
        """Bind the map to Enhanced Vascularization, or say what the panel waits for."""
        if not self._presentationActive:
            return
        vascularWidget = self._sliceWidgetOrNone(self.VASCULAR_VIEW_NAME, layoutManager)
        if vascularWidget is None:
            return
        node = self._vascularMapNode()
        try:
            sliceLogic = vascularWidget.sliceLogic()
            composite = sliceLogic.GetSliceCompositeNode()
            if node is None:
                self._clearSliceLayers(vascularWidget)
                self._removePanelCaption(self.VASCULAR_VIEW_NAME)
                self._showPanelMessage(
                    self.VASCULAR_VIEW_NAME,
                    self.VASCULAR_FAILED_MESSAGE if self._vascularError
                    else self.RESERVED_PANEL_REASONS[self.VASCULAR_VIEW_NAME],
                    layoutManager,
                )
            else:
                self._removePanelMessage(self.VASCULAR_VIEW_NAME)
                # Every new map is framed for its own; a redraw of the same map
                # keeps the operator's pan and zoom.
                if (composite.GetBackgroundVolumeID() != node.GetID()
                        or self._fittedVascularCaptureId != self._vascularCaptureId):
                    composite.SetBackgroundVolumeID(node.GetID())
                    sliceLogic.FitSliceToBackground()
                    self._fittedVascularCaptureId = self._vascularCaptureId
                composite.SetForegroundVolumeID(None)
                composite.SetLabelVolumeID(None)
                self._showPanelCaption(
                    self.VASCULAR_VIEW_NAME,
                    self.VASCULAR_CAPTION.format(
                        **self._cubeText(self._vascularCaseName, self._vascularSimulated)),
                    layoutManager,
                )
            vascularView = vascularWidget.sliceView()
            if vascularView is not None:
                vascularView.forceRender()
        except RuntimeError:
            return

    def _updateVascularStatus(self) -> None:
        label = getattr(getattr(self, "ui", None), "vascularStatusLabel", None)
        if label is None:
            return
        if self._uc2Pending:
            text = self.VASCULAR_RUNNING_STATUS.format(**self._cubeText(self._vascularRunningCase))
        elif self._vascularError:
            text = self.VASCULAR_FAILED_STATUS.format(message=self._vascularError)
        elif self._vascularCaseName is not None:
            text = self.VASCULAR_STATUS.format(**self._cubeText(self._vascularCaseName,
                                                                 self._vascularSimulated),
                                               parameters=uc2ParametersText())
        else:
            text = self.VASCULAR_NONE_STATUS
        label.setText(text)

    def _forgetVascularMap(self) -> None:
        """Remove the map and everything that describes it."""
        if self.logic is not None:
            self.logic.removeVascularMapNode()
        self._vascularCaseName = None
        self._vascularCaptureId = None
        self._fittedVascularCaptureId = None
        self._vascularError = None
        self._removePanelCaption(self.VASCULAR_VIEW_NAME)
        self._updateVascularStatus()

    # ------------------------------------------------------------------
    # Connections (SLIA-035, ADR-0004 decision 2)
    #
    # One row per configured port of IUMA's acquisition app. The rows are built
    # by SLIAFlowConnections from the connectors' state and the nodes they fill;
    # this section only shows them and locks the settings while connected. The
    # connectors stay listed, stopped, while disconnected, whichever module is
    # on screen, and no connector outlives the scene or the module.
    # ------------------------------------------------------------------

    def _connectionSettings(self):
        parameters = self._parameterNode
        if parameters is None:
            return None
        return (
            parameters.igtlHost,
            ((CHANNEL_LIVE_VIEW, parameters.liveViewPort),
             (CHANNEL_STEREO, parameters.stereoPort),
             (CHANNEL_HS_CUBE, parameters.hsCubePort)),
            parameters.expectedBands,
        )

    def _applyConnectionSettings(self) -> None:
        """Give the parameter-node settings to the connections, while disconnected."""
        if self.logic is None or self.logic.connections.connected:
            return
        settings = self._connectionSettings()
        if settings is None or settings == self._appliedConnectionSettings:
            return
        host, ports, expectedBands = settings
        # Listed connectors are listed again for the new settings.
        self.logic.connections.configure(host, dict(ports), expectedBands)
        self._appliedConnectionSettings = settings

    def _observeConnectionSettings(self) -> None:
        node = self._parameterNode.parameterNode if self._parameterNode is not None else None
        if node is self._observedParameterNode:
            return
        if self._observedParameterNode is not None:
            self.removeObserver(self._observedParameterNode, vtk.vtkCommand.ModifiedEvent,
                                self._onConnectionSettingsModified)
        self._observedParameterNode = node
        if node is not None:
            self.addObserver(node, vtk.vtkCommand.ModifiedEvent,
                             self._onConnectionSettingsModified)

    def _onConnectionSettingsModified(self, caller=None, event=None) -> None:
        self._refreshConnections()

    def _refreshConnections(self) -> None:
        """Redraw the rows, the detail line and the controls from the connections."""
        if self.logic is None or not hasattr(self, "ui"):
            return
        self._applyConnectionSettings()
        connections = self.logic.connections
        rows = connections.rows()
        table = self.ui.connectionsTable
        if table.rowCount != len(rows):
            table.setRowCount(len(rows))
        for rowIndex, row in enumerate(rows):
            for column, text in enumerate((row.port, row.channel, row.state, row.lastMessage,
                                           row.received)):
                item = table.item(rowIndex, column)
                if item is None:
                    item = qt.QTableWidgetItem()
                    table.setItem(rowIndex, column, item)
                if item.text() != text:
                    item.setText(text)
        details = [f"{row.channel}: {row.detail}" for row in rows if row.detail]
        if not rows and connections.lastError:
            details.append(connections.lastError)
        self.ui.connectionsDetailLabel.setText("\n".join(details))
        cube = connections.takeCompletedCube()
        if cube is not None:
            self._receiveCube(cube)
        connected = connections.connected
        self.ui.connectButton.setText(self.DISCONNECT_TEXT if connected else self.CONNECT_TEXT)
        for name in self.CONNECTION_SETTING_CONTROLS:
            getattr(self.ui, name).setEnabled(not connected)

    def _onConnectClicked(self) -> None:
        if self.logic is None:
            return
        connections = self.logic.connections
        if connections.connected:
            if self._connectionsTimer is not None:
                self._connectionsTimer.stop()
            connections.disconnect()
            self._forgetReceivedCube()
            self._refreshConnections()
            return
        self._applyConnectionSettings()
        if connections.connect() and self._connectionsTimer is not None:
            self._connectionsTimer.start()
        self._refreshConnections()

    def _releaseConnections(self) -> None:
        """Stop and remove every module connector and what it received."""
        if self._connectionsTimer is not None:
            self._connectionsTimer.stop()
        if self.logic is not None:
            self.logic.connections.release()
        self._forgetReceivedCube()
        self._refreshConnections()

    def _receiveCube(self, cube) -> None:
        """Show a cube the app completed, or hold it while a capture runs on the last one."""
        if self.logic is None:
            return
        if self._captureInProgress and self._cubeSourceIsApp():
            self._heldReceivedCube = cube
            return
        try:
            self.logic.acceptReceivedCube(cube)
        except Exception:
            logging.exception("SLIAFlow: the cube received from the app could not be shown")
            return
        if self._cubeSourceIsApp():
            self._resetSpectrumLabel()
            self._showCube()

    def _forgetReceivedCube(self) -> None:
        """Remove the received cube, any held one, and the cube written for a run.

        The written cube stays while a capture still uses it, and is removed
        when that capture ends.
        """
        self._heldReceivedCube = None
        if self.logic is None:
            return
        self.logic.removeReceivedCubeNode()
        if self._captureInProgress:
            self._removeRunCubeAfterCapture = True
        else:
            self._removeReceivedRunCube()
        if self._cubeSourceIsApp():
            self._resetSpectrumLabel()
            self._showCube()

    def _removeReceivedRunCube(self) -> None:
        if self.logic is None:
            return
        try:
            self.logic.removeReceivedRunCube()
        except OSError:
            logging.exception("SLIAFlow: the cube written for a run could not be removed")

    def _onAboutToQuit(self) -> None:
        self._cancelCapture()
        self._releaseConnections()

    def _onOpenInOpenIGTLinkIFClicked(self) -> None:
        if slicer.app.moduleManager().module(self.OPENIGTLINKIF_MODULE) is None:
            self._setStatus(self.OPENIGTLINKIF_UNAVAILABLE_STATUS.format(
                reason=_("the module is not loaded in this Slicer.")))
            return
        try:
            slicer.util.selectModule(self.OPENIGTLINKIF_MODULE)
        except RuntimeError as error:
            self._setStatus(self.OPENIGTLINKIF_UNAVAILABLE_STATUS.format(reason=error))

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

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
        self._updateResultStatus()
        self._showResult(layoutManager)
        self._showCube(layoutManager)
        self._showVascularMap(layoutManager)
        self._observeCubeView(layoutManager)
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

        self._stopObservingCubeView()
        self._removeWaitingAnnotation()
        self._removeStaleLine()
        self._removeAllPanelMessages()
        self._removeAllPanelCaptions()
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
    # Panel text
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

    def panelCaption(self, viewName: str) -> str:
        """The caption naming what this panel shows, or an empty string."""
        return self._panelCaptions.get(viewName, "")

    def _showPanelCaption(self, viewName: str, caption: str, layoutManager=None) -> bool:
        """Write the line that names what a panel shows. Returns whether it reached a renderer."""
        self._panelCaptions[viewName] = caption
        actor = self._panelCaptionActors.get(viewName)
        if actor is None:
            actor = vtk.vtkTextActor()
            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            x, y = self.CAPTION_POSITIONS.get(viewName, (0.5, 0.97))
            actor.SetPosition(x, y)
            textProperty = actor.GetTextProperty()
            textProperty.SetFontSize(self.CAPTION_FONT_SIZE)
            textProperty.SetColor(1.0, 1.0, 1.0)
            # A dark band behind the text keeps it legible over a bright band.
            textProperty.SetBackgroundColor(0.0, 0.0, 0.0)
            textProperty.SetBackgroundOpacity(0.6)
            textProperty.SetJustificationToCentered()
            if y > 0.5:
                textProperty.SetVerticalJustificationToTop()
            else:
                textProperty.SetVerticalJustificationToBottom()
            self._panelCaptionActors[viewName] = actor
        if actor.GetInput() != caption:
            actor.SetInput(caption)
        sliceWidget = self._sliceWidgetOrNone(viewName, layoutManager)
        if sliceWidget is None:
            return False
        placed = self._placeAnnotationActor(
            self._sliceViewRenderer(sliceWidget), actor,
            self._panelCaptionRenderers.get(viewName),
        )
        if placed is None:
            return False
        self._panelCaptionRenderers[viewName] = placed
        sliceView = sliceWidget.sliceView()
        if sliceView is not None:
            sliceView.scheduleRender()
        return True

    def _removePanelCaption(self, viewName: str) -> None:
        self._panelCaptions.pop(viewName, None)
        actor = self._panelCaptionActors.pop(viewName, None)
        renderer = self._panelCaptionRenderers.pop(viewName, None)
        if actor is None or renderer is None:
            return
        try:
            renderer.RemoveActor2D(actor)
        except (RuntimeError, ValueError):
            pass

    def _removeAllPanelCaptions(self) -> None:
        for viewName in list(self._panelCaptionActors):
            self._removePanelCaption(viewName)
        self._panelCaptions.clear()
