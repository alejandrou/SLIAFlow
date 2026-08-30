import importlib
import logging
import unittest
from typing import Annotated, Any
from xml.sax.saxutils import escape

import slicer
import vtk
from slicer import vtkMRMLScalarVolumeNode, vtkMRMLVectorVolumeNode
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

    liveVolume: vtkMRMLVectorVolumeNode
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
        self.initializeParameterNode()
        self._setCameraSupportState(self.logic.openCVAvailable())

    def cleanup(self) -> None:
        self._stopCamera(clearLiveView=True)
        self._deactivatePresentation(restore=True)
        self.setParameterNode(None)
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self._activatePresentation()
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

    def _configureFutureControls(self) -> None:
        controlNames = (
            "liveSourceSelector",
            "resultMapSelector",
            "resultClassSpinBox",
        )
        for controlName in controlNames:
            control = getattr(self.ui, controlName, None)
            if control is not None:
                control.setEnabled(False)

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
            # Scene close and module reload can tear the view down first.
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
        """Report whether a layout identifier can be restored on module exit.

        Slicer sets the view arrangement to `SlicerLayoutNone` while it tears
        views down, for example between the start and the end of a scene close.
        Recording that transient value as the operator's previous layout would
        blank the whole main window when SLIAFlow later restores it.
        """
        if layout is None:
            return False
        return int(layout) != slicer.vtkMRMLLayoutNode.SlicerLayoutNone

    def _rememberLayoutBeforeSceneClose(self) -> None:
        """Keep the operator's layout while a scene close blanks the views.

        A scene close re-creates the layout node, so the arrangement is already
        `SlicerLayoutNone` by the time the presentation is rebuilt on the end
        of the close. The arrangement seen when the close started is the one
        the operator should be returned to.
        """
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
        if not self._isRestorableLayout(previousLayout):
            previousLayout = None

        self._removeWaitingAnnotation()
        if layoutManager is not None:
            layoutNode = layoutManager.layoutLogic().GetLayoutNode()
            if int(layoutNode.GetViewArrangement()) == self.CUSTOM_LAYOUT_ID:
                self._clearPresentation(layoutManager)
                if restore:
                    # Without a recorded layout the operator would be left in
                    # the SLIAFlow two-pane layout after leaving the module, so
                    # fall back to Slicer's conventional layout.
                    layoutManager.setLayout(
                        previousLayout
                        if previousLayout is not None
                        else slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView
                    )

        self._previousLayout = None if restore else previousLayout
        if restore:
            self._layoutBeforeSceneClose = None
        self._presentationActive = False


class SLIAFlowLogic(ScriptedLoadableModuleLogic):
    """Own camera resources and SLIAFlow state without requiring a widget."""

    OPENCV_REQUIREMENT = "opencv-python-headless==5.0.0.93"
    CAMERA_WIDTH_PX = 640
    CAMERA_HEIGHT_PX = 480
    CAMERA_TIMER_INTERVAL_MS = 66
    LIVE_VOLUME_NAME = "SLIAFlow Laptop Camera"
    CAMERA_UNAVAILABLE_MESSAGE = _(
        "No camera could be opened. Check the camera index, Windows camera "
        "permissions, and whether another application is using the camera."
    )
    CAMERA_READ_ERROR_MESSAGE = _(
        "The camera stopped providing valid frames. Check the device connection "
        "and whether another application is using the camera."
    )
    CAMERA_SUPPORT_MISSING_MESSAGE = _(
        "Camera support is not installed. Choose Install Camera Support, then "
        "restart Slicer."
    )

    def __init__(self) -> None:
        super().__init__()
        self._cameraCapture = None
        self._cameraTimer = None
        self._cameraTimeoutCallback = None
        self._frameCallback = None
        self._errorCallback = None

    @staticmethod
    def openCVAvailable(importer=importlib.import_module) -> bool:
        try:
            importer("cv2")
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def frameToRGBKJI(bgrFrame):
        import numpy as np

        frame = np.asarray(bgrFrame)
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("OpenCV camera frames must be HxWx3 uint8 arrays")
        return np.ascontiguousarray(frame[:, :, ::-1][np.newaxis, ...])

    @property
    def cameraActive(self) -> bool:
        return self._cameraCapture is not None and self._cameraTimer is not None

    def startCamera(
        self,
        cameraIndex,
        frameCallback,
        errorCallback,
        *,
        cv2Module=None,
        captureFactory=None,
        timerFactory=None,
    ) -> bool:
        self.stopCamera()

        if cv2Module is None:
            try:
                cv2Module = importlib.import_module("cv2")
            except (ImportError, OSError):
                errorCallback(self.CAMERA_SUPPORT_MISSING_MESSAGE)
                return False
        if captureFactory is None:
            captureFactory = cv2Module.VideoCapture

        capture = None
        for backend in (
            cv2Module.CAP_MSMF,
            cv2Module.CAP_DSHOW,
            None,
        ):
            try:
                candidate = (
                    captureFactory(cameraIndex, backend)
                    if backend is not None
                    else captureFactory(cameraIndex)
                )
            except Exception:
                continue
            try:
                opened = bool(candidate.isOpened())
            except Exception:
                opened = False
            if opened:
                capture = candidate
                break
            try:
                candidate.release()
            except Exception:
                pass

        if capture is None:
            errorCallback(self.CAMERA_UNAVAILABLE_MESSAGE)
            return False

        try:
            capture.set(
                cv2Module.CAP_PROP_FRAME_WIDTH, self.CAMERA_WIDTH_PX
            )
            capture.set(
                cv2Module.CAP_PROP_FRAME_HEIGHT, self.CAMERA_HEIGHT_PX
            )
            if timerFactory is None:
                import qt

                timer = qt.QTimer()
            else:
                timer = timerFactory()

            self._cameraCapture = capture
            self._cameraTimer = timer
            self._frameCallback = frameCallback
            self._errorCallback = errorCallback
            self._cameraTimeoutCallback = self._onCameraTimeout
            timer.connect("timeout()", self._cameraTimeoutCallback)
            timer.setInterval(self.CAMERA_TIMER_INTERVAL_MS)
            timer.start()
        except Exception:
            try:
                capture.release()
            except Exception:
                pass
            self._cameraCapture = None
            self._cameraTimer = None
            self._cameraTimeoutCallback = None
            self._frameCallback = None
            self._errorCallback = None
            errorCallback(self.CAMERA_UNAVAILABLE_MESSAGE)
            return False
        return True

    def _onCameraTimeout(self) -> None:
        capture = self._cameraCapture
        frameCallback = self._frameCallback
        errorCallback = self._errorCallback
        if capture is None or frameCallback is None or errorCallback is None:
            return

        try:
            frameRead, bgrFrame = capture.read()
            if not frameRead or bgrFrame is None:
                raise RuntimeError("Camera read failed")
            rgbKjiFrame = self.frameToRGBKJI(bgrFrame)
            frameCallback(rgbKjiFrame)
        except Exception:
            self.stopCamera()
            errorCallback(self.CAMERA_READ_ERROR_MESSAGE)

    def stopCamera(self) -> None:
        timer = self._cameraTimer
        capture = self._cameraCapture
        timeoutCallback = self._cameraTimeoutCallback
        self._cameraTimer = None
        self._cameraCapture = None
        self._cameraTimeoutCallback = None
        self._frameCallback = None
        self._errorCallback = None

        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            if timeoutCallback is not None:
                try:
                    timer.disconnect("timeout()", timeoutCallback)
                except Exception:
                    pass
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass

    @staticmethod
    def getOrCreateLiveVolume(parameterNode):
        try:
            liveNode = parameterNode.liveVolume
        except TypeError:
            # SLIA-004 typed this reference as a scalar volume. Clear any
            # legacy reference before replacing it with the camera vector node.
            parameterNode.parameterNode.SetNodeReferenceID("liveVolume", None)
            liveNode = None
        if liveNode is not None and liveNode.IsA("vtkMRMLVectorVolumeNode"):
            return liveNode

        liveNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVectorVolumeNode",
            slicer.mrmlScene.GenerateUniqueName(SLIAFlowLogic.LIVE_VOLUME_NAME),
        )
        liveNode.SetAttribute("SLIAFlow.Owner", "LaptopCamera")
        liveNode.SetSaveWithScene(False)
        liveNode.CreateDefaultDisplayNodes()
        parameterNode.liveVolume = liveNode
        return liveNode

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

    # These tests drive the live module widget of the entered module, so each
    # one must hand the widget back exactly as it found it. Otherwise a test
    # that simulates missing camera support or leaves the presentation
    # deactivated both breaks the next test and leaves the operator with a
    # module whose controls no longer match reality after Reload and Test.
    WIDGET_STATE_FIELDS = (
        "_previousLayout",
        "_layoutBeforeSceneClose",
        "_presentationActive",
        "_cameraSupportAvailable",
        "_cameraRestartRequired",
    )

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()
        self._widgetStateBackup = None
        widget = self._moduleWidgetOrNone()
        if widget is None:
            return
        backup = {name: getattr(widget, name) for name in self.WIDGET_STATE_FIELDS}
        statusLabel = getattr(widget.ui, "statusLabel", None)
        backup["status"] = None if statusLabel is None else statusLabel.text
        self._widgetStateBackup = backup

    def tearDown(self) -> None:
        super().tearDown()
        backup = getattr(self, "_widgetStateBackup", None)
        widget = self._moduleWidgetOrNone()
        if backup is None or widget is None:
            return
        for name in self.WIDGET_STATE_FIELDS:
            setattr(widget, name, backup[name])
        widget._refreshCameraControls()
        if backup["status"] is not None:
            widget._setStatus(backup["status"])

    @staticmethod
    def _moduleRepresentationAndWidget():
        module = slicer.app.moduleManager().module("SLIAFlow")
        representation = module.widgetRepresentation()
        return representation, representation.self()

    @classmethod
    def _moduleWidgetOrNone(cls):
        try:
            widget = cls._moduleRepresentationAndWidget()[1]
        except (AttributeError, RuntimeError):
            # The module widget is unavailable in a headless Slicer session.
            return None
        return widget if getattr(widget, "ui", None) is not None else None

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
        installButton = slicer.util.findChild(
            representation, "installCameraSupportButton"
        )
        resultMap = slicer.util.findChild(representation, "resultMapSelector")
        resultClass = slicer.util.findChild(representation, "resultClassSpinBox")
        status = slicer.util.findChild(representation, "statusLabel")

        for control in (
            liveSource,
            resultMap,
            resultClass,
        ):
            self.assertIsNotNone(control)
            self.assertFalse(control.isEnabled())

        for control in (cameraIndex, startButton, stopButton, installButton):
            self.assertIsNotNone(control)

        cameraSupportAvailable = widget.logic.openCVAvailable()
        self.assertEqual(cameraIndex.isEnabled(), cameraSupportAvailable)
        self.assertEqual(startButton.isEnabled(), cameraSupportAvailable)
        self.assertFalse(stopButton.isEnabled())
        self.assertEqual(installButton.isEnabled(), not cameraSupportAvailable)

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
        if cameraSupportAvailable:
            self.assertIn("ready", status.text.lower())
        else:
            self.assertIn("install camera support", status.text.lower())

    def test_cameraFrameConversion(self) -> None:
        import numpy as np

        bgrFrame = np.array(
            [
                [[1, 2, 3], [4, 5, 6]],
                [[7, 8, 9], [10, 11, 12]],
            ],
            dtype=np.uint8,
        )

        rgbKjiFrame = SLIAFlowLogic.frameToRGBKJI(bgrFrame)

        self.assertEqual(rgbKjiFrame.shape, (1, 2, 2, 3))
        self.assertEqual(rgbKjiFrame.dtype, np.uint8)
        np.testing.assert_array_equal(
            rgbKjiFrame[0],
            np.array(
                [
                    [[3, 2, 1], [6, 5, 4]],
                    [[9, 8, 7], [12, 11, 10]],
                ],
                dtype=np.uint8,
            ),
        )
        self.assertTrue(rgbKjiFrame.flags.c_contiguous)

    def test_cameraBackendFallbackAndLifecycle(self) -> None:
        import numpy as np

        class FakeTimer:
            def __init__(self) -> None:
                self.callback = None
                self.interval = None
                self.started = False

            def connect(self, signal, callback) -> None:
                self.assertTimeoutSignal(signal)
                self.callback = callback

            def disconnect(self, signal, callback) -> None:
                self.assertTimeoutSignal(signal)
                if self.callback == callback:
                    self.callback = None

            @staticmethod
            def assertTimeoutSignal(signal) -> None:
                if signal != "timeout()":
                    raise AssertionError(f"Unexpected signal: {signal}")

            def fire(self) -> None:
                if self.callback is not None:
                    self.callback()

            def setInterval(self, interval) -> None:
                self.interval = interval

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.started = False

        class FakeCapture:
            def __init__(self, opened, frame=None) -> None:
                self.opened = opened
                self.frame = frame
                self.released = False
                self.settings = []

            def isOpened(self) -> bool:
                return self.opened

            def set(self, propertyId, value) -> None:
                self.settings.append((propertyId, value))

            def read(self):
                return self.frame is not None, self.frame

            def release(self) -> None:
                self.released = True

        class FakeCV2:
            CAP_MSMF = 10
            CAP_DSHOW = 20
            CAP_PROP_FRAME_WIDTH = 30
            CAP_PROP_FRAME_HEIGHT = 40

        createdCaptures = []
        openedStates = iter((False, False, True))
        bgrFrame = np.array([[[11, 22, 33]]], dtype=np.uint8)

        def captureFactory(*arguments):
            capture = FakeCapture(next(openedStates), bgrFrame)
            capture.arguments = arguments
            createdCaptures.append(capture)
            return capture

        timer = FakeTimer()
        frames = []
        errors = []
        logic = SLIAFlowLogic()

        self.assertTrue(
            logic.startCamera(
                2,
                frames.append,
                errors.append,
                cv2Module=FakeCV2,
                captureFactory=captureFactory,
                timerFactory=lambda: timer,
            )
        )
        self.assertEqual(
            [capture.arguments for capture in createdCaptures],
            [(2, FakeCV2.CAP_MSMF), (2, FakeCV2.CAP_DSHOW), (2,)],
        )
        self.assertTrue(createdCaptures[0].released)
        self.assertTrue(createdCaptures[1].released)
        self.assertFalse(createdCaptures[2].released)
        self.assertEqual(
            createdCaptures[2].settings,
            [
                (FakeCV2.CAP_PROP_FRAME_WIDTH, logic.CAMERA_WIDTH_PX),
                (FakeCV2.CAP_PROP_FRAME_HEIGHT, logic.CAMERA_HEIGHT_PX),
            ],
        )
        self.assertEqual(timer.interval, logic.CAMERA_TIMER_INTERVAL_MS)
        self.assertTrue(timer.started)
        self.assertTrue(logic.cameraActive)

        timer.fire()
        self.assertEqual(errors, [])
        self.assertEqual(len(frames), 1)
        np.testing.assert_array_equal(frames[0], np.array([[[[33, 22, 11]]]]))

        logic.stopCamera()
        self.assertFalse(timer.started)
        self.assertTrue(createdCaptures[2].released)
        self.assertFalse(logic.cameraActive)
        logic.stopCamera()

        openedStates = iter((True,))
        secondTimer = FakeTimer()
        self.assertTrue(
            logic.startCamera(
                2,
                frames.append,
                errors.append,
                cv2Module=FakeCV2,
                captureFactory=captureFactory,
                timerFactory=lambda: secondTimer,
            )
        )
        self.assertTrue(logic.cameraActive)
        logic.stopCamera()
        self.assertFalse(secondTimer.started)
        self.assertTrue(createdCaptures[3].released)
        self.assertFalse(logic.cameraActive)

        openedStates = iter((True,))
        failingTimer = FakeTimer()
        self.assertTrue(
            logic.startCamera(
                2,
                frames.append,
                errors.append,
                cv2Module=FakeCV2,
                captureFactory=captureFactory,
                timerFactory=lambda: failingTimer,
            )
        )
        createdCaptures[4].frame = None
        failingTimer.fire()
        self.assertFalse(logic.cameraActive)
        self.assertFalse(failingTimer.started)
        self.assertTrue(createdCaptures[4].released)
        self.assertEqual(errors, [logic.CAMERA_READ_ERROR_MESSAGE])

        openedStates = iter((True,))
        self.assertTrue(
            logic.startCamera(
                2,
                frames.append,
                errors.append,
                cv2Module=FakeCV2,
                captureFactory=captureFactory,
            )
        )
        self.assertTrue(logic.cameraActive)
        logic.stopCamera()
        self.assertTrue(createdCaptures[5].released)
        self.assertFalse(logic.cameraActive)

    def test_cameraSupportAndFailureStates(self) -> None:
        class MissingCV2Importer:
            def __call__(self, moduleName):
                raise ImportError(moduleName)

        class ClosedCapture:
            def isOpened(self) -> bool:
                return False

            def release(self) -> None:
                pass

        class FakeCV2:
            CAP_MSMF = 10
            CAP_DSHOW = 20
            CAP_PROP_FRAME_WIDTH = 30
            CAP_PROP_FRAME_HEIGHT = 40

        self.assertEqual(
            SLIAFlowLogic.OPENCV_REQUIREMENT,
            "opencv-python-headless==5.0.0.93",
        )
        self.assertFalse(
            SLIAFlowLogic.openCVAvailable(importer=MissingCV2Importer())
        )

        errors = []
        logic = SLIAFlowLogic()
        self.assertFalse(
            logic.startCamera(
                99,
                lambda frame: None,
                errors.append,
                cv2Module=FakeCV2,
                captureFactory=lambda *arguments: ClosedCapture(),
            )
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("camera", errors[0].lower())
        self.assertIn("permissions", errors[0].lower())

        representation, widget = self._moduleRepresentationAndWidget()
        installButton = slicer.util.findChild(
            representation, "installCameraSupportButton"
        )
        self.assertIsNotNone(installButton)
        widget._setCameraSupportState(False)
        self.assertTrue(installButton.isEnabled())
        self.assertFalse(
            slicer.util.findChild(representation, "startButton").isEnabled()
        )
        status = slicer.util.findChild(representation, "statusLabel")
        self.assertIn("install camera support", status.text.lower())

    def test_cameraFrameUpdatesOnlyLiveView(self) -> None:
        import numpy as np

        class FakeCompositeNode:
            def __init__(self) -> None:
                self.backgroundVolumeId = None
                self.foregroundVolumeId = None
                self.labelVolumeId = None

            def SetBackgroundVolumeID(self, nodeId) -> None:
                self.backgroundVolumeId = nodeId

            def SetForegroundVolumeID(self, nodeId) -> None:
                self.foregroundVolumeId = nodeId

            def SetLabelVolumeID(self, nodeId) -> None:
                self.labelVolumeId = nodeId

            def GetBackgroundVolumeID(self):
                return self.backgroundVolumeId

            def GetForegroundVolumeID(self):
                return self.foregroundVolumeId

            def GetLabelVolumeID(self):
                return self.labelVolumeId

        class FakeSliceLogic:
            def __init__(self) -> None:
                self.compositeNode = FakeCompositeNode()
                self.fitCount = 0

            def GetSliceCompositeNode(self):
                return self.compositeNode

            def FitSliceToBackground(self) -> None:
                self.fitCount += 1

        class FakeSliceView:
            def __init__(self) -> None:
                self.renderCount = 0

            def forceRender(self) -> None:
                self.renderCount += 1

        class FakeSliceWidget:
            def __init__(self) -> None:
                self.logic = FakeSliceLogic()
                self.view = FakeSliceView()

            def sliceLogic(self):
                return self.logic

            def sliceView(self):
                return self.view

        class FakeLayoutManager:
            def __init__(self, widgetUnderTest) -> None:
                self.widgets = {
                    widgetUnderTest.LIVE_VIEW_NAME: FakeSliceWidget(),
                    widgetUnderTest.RESULT_VIEW_NAME: FakeSliceWidget(),
                }

            def sliceWidget(self, viewName):
                return self.widgets.get(viewName)

        representation, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        layoutManager = FakeLayoutManager(widget)
        waitingActor = widget._waitingAnnotationActor
        waitingRenderer = widget._waitingAnnotationRenderer
        rgbKjiFrame = np.array(
            [[[[255, 0, 0], [0, 255, 0]]]], dtype=np.uint8
        )
        try:
            widget._displayCameraFrame(rgbKjiFrame, layoutManager=layoutManager)
            liveNode = widget._parameterNode.liveVolume
            self.assertIsNotNone(liveNode)
            self.assertTrue(liveNode.IsA("vtkMRMLVectorVolumeNode"))
            self.assertEqual(
                widget._parameterNode.parameterNode.GetNodeReferenceID(
                    "liveVolume"
                ),
                liveNode.GetID(),
            )
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(liveNode), rgbKjiFrame
            )

            liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            liveComposite = liveWidget.sliceLogic().GetSliceCompositeNode()
            resultComposite = resultWidget.sliceLogic().GetSliceCompositeNode()
            self.assertEqual(liveComposite.GetBackgroundVolumeID(), liveNode.GetID())
            self.assertEqual(liveWidget.sliceLogic().fitCount, 1)
            self.assertIsNone(resultComposite.GetBackgroundVolumeID())
            self.assertIsNone(resultComposite.GetForegroundVolumeID())
            self.assertIsNone(resultComposite.GetLabelVolumeID())
            self.assertIs(widget._waitingAnnotationActor, waitingActor)
            self.assertIs(widget._waitingAnnotationRenderer, waitingRenderer)

            widget._stopCamera(clearLiveView=True, layoutManager=layoutManager)
            self.assertIsNone(liveComposite.GetBackgroundVolumeID())
        finally:
            widget._stopCamera(clearLiveView=True, layoutManager=layoutManager)

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

    def test_layoutRestoreIgnoresTransientEmptyLayout(self) -> None:
        widget = self._moduleRepresentationAndWidget()[1]
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.assertFalse(widget._activatePresentation())
            return

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        emptyLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutNone
        conventionalLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView
        restoreLayout = int(layoutNode.GetViewArrangement())
        if restoreLayout in (emptyLayout, widget.CUSTOM_LAYOUT_ID):
            restoreLayout = conventionalLayout

        initialLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutInitialView

        try:
            widget._deactivatePresentation(restore=False)
            widget._previousLayout = None
            widget._layoutBeforeSceneClose = None

            # Slicer passes through the empty layout while it tears views
            # down, for instance between the start and the end of a scene
            # close. Entering the presentation then must not adopt it.
            layoutManager.setLayout(emptyLayout)
            self.assertTrue(widget._activatePresentation())
            self.assertIsNone(widget._previousLayout)

            widget._deactivatePresentation(restore=True)
            self.assertEqual(
                int(layoutNode.GetViewArrangement()),
                conventionalLayout,
                "Leaving the module must never restore the empty layout",
            )

            # A scene close blanks the arrangement before the presentation is
            # rebuilt, so the layout seen when the close started is restored.
            widget._deactivatePresentation(restore=False)
            widget._previousLayout = None
            widget._layoutBeforeSceneClose = initialLayout
            layoutManager.setLayout(emptyLayout)
            self.assertTrue(widget._activatePresentation())
            self.assertEqual(widget._previousLayout, initialLayout)

            widget._deactivatePresentation(restore=True)
            self.assertEqual(
                int(layoutNode.GetViewArrangement()),
                initialLayout,
                "A scene close must not lose the operator's layout",
            )
        finally:
            widget._deactivatePresentation(restore=True)
            if int(layoutNode.GetViewArrangement()) != restoreLayout:
                layoutManager.setLayout(restoreLayout)

    def test_parameterNodeStoresVolumeReferencesByID(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()

        liveVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVectorVolumeNode", "Shared volume name"
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

        legacyScalarVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Legacy live volume"
        )
        parameterNode.SetNodeReferenceID(
            "liveVolume", legacyScalarVolume.GetID()
        )
        migratedLiveVolume = logic.getOrCreateLiveVolume(parameters)
        self.assertTrue(migratedLiveVolume.IsA("vtkMRMLVectorVolumeNode"))
        self.assertNotEqual(migratedLiveVolume.GetID(), legacyScalarVolume.GetID())
        self.assertEqual(
            parameterNode.GetNodeReferenceID("liveVolume"),
            migratedLiveVolume.GetID(),
        )
