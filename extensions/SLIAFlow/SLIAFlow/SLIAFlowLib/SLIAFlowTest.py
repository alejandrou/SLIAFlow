import contextlib
import importlib
import io
import time
import unittest
from pathlib import Path

import numpy as np
import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleTest
from vtk.util.numpy_support import vtk_to_numpy

from .SLIAFlowLogic import SLIAFlowLogic
from .SLIAFlowParameterNode import (
    ACQUISITION_PORT,
    CONNECTION_CONNECTING,
    CONNECTION_DISCONNECTED,
    CONNECTION_DISPLAYING,
    CONNECTION_INVALID,
    CONNECTION_RECEIVING,
    CONNECTOR_ACQUISITION,
    CONNECTOR_UC1,
    IGTL_HOST,
    LIVE_SOURCE_CHOICES,
    LIVE_SOURCE_IGTL,
    LIVE_SOURCE_LAPTOP,
    LIVE_VIEW_DEVICE_NAME,
    RESULT_MAP_CHOICES,
    RESULT_MAP_DEVICE_NAMES,
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_MV_CLASS,
    RESULT_MAP_SVM_PROB,
    RESULT_MAP_TMD,
    RESULT_SOURCE_DETAIL_ATTRIBUTE,
    RESULT_SOURCE_DEVICE_ATTRIBUTE,
    RESULT_SOURCE_GENUINE_ORIGIN,
    RESULT_SOURCE_ORIGIN_ATTRIBUTE,
    RESULT_SOURCE_ROLE_ATTRIBUTE,
    RESULT_SOURCE_SIMULATED_ORIGIN,
    SIMULATED_BANNER_MESSAGE,
    SIMULATED_BANNER_MESSAGE_REAL_PIPELINE,
    UC1_PORT,
    WIRE_ATTRIBUTE_PREFIX,
    simulatedBannerMessage,
)

# The package re-exports the parameter-node class under the same name as its
# module, so `from . import SLIAFlowParameterNode` would bind the class.
parameterModule = importlib.import_module(".SLIAFlowParameterNode", __package__)


class SLIAFlowTest(ScriptedLoadableModuleTest):
    """Focused regression tests for the SLIAFlow presentation boundary."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.moduleTestNames = unittest.TestLoader().getTestCaseNames(type(self))

    def runTest(self, **kwargs) -> None:
        """Run every test through unittest, as the command-line runner does.

        Slicer's Reload and Test calls this on a single instance. The inherited
        loop called each test method directly, so the first ``skipTest`` left
        it as an exception and every later test silently did not run.
        """
        suite = unittest.TestSuite(type(self)(name) for name in self.moduleTestNames)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise AssertionError(
                f"{len(result.failures)} failed and {len(result.errors)} raised an "
                f"error out of {result.testsRun} tests; see the test output above."
            )

    WIDGET_STATE_FIELDS = (
        "_previousLayout",
        "_layoutBeforeSceneClose",
        "_presentationActive",
        "_demoModeEnabled",
        "_cameraSupportAvailable",
        "_cameraRestartRequired",
        "_resultEverDisplayed",
        "_liveViewEverDisplayed",
        "_uc2EverDisplayed",
        "_lastResultRefreshTime",
        "_pendingResultRefresh",
    )
    EVENT_LOOP_TIMEOUT_SEC = 2.0

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()
        self._widgetStateBackup = None
        widget = self._moduleWidgetOrNone()
        if widget is None:
            return
        backup = {name: getattr(widget, name) for name in self.WIDGET_STATE_FIELDS}
        statusLabel = getattr(widget.ui, "statusLabel", None)
        resultStatusLabel = getattr(widget.ui, "resultStatusLabel", None)
        resultSourceValueLabel = getattr(widget.ui, "resultSourceValueLabel", None)
        backup["status"] = None if statusLabel is None else statusLabel.text
        backup["resultStatus"] = (
            None if resultStatusLabel is None else resultStatusLabel.text
        )
        backup["resultSource"] = (
            None if resultSourceValueLabel is None else resultSourceValueLabel.text
        )
        self._widgetStateBackup = backup
        # Link history is deliberately preserved by production cleanup so a
        # retained image cannot become fresh merely because the module was
        # reopened. Each test still needs an isolated link session.
        for role in getattr(widget, "_linkDropped", {}):
            widget._linkDropped[role] = False
            widget._linkDropSnapshots[role] = None

    def tearDown(self) -> None:
        super().tearDown()
        backup = getattr(self, "_widgetStateBackup", None)
        widget = self._moduleWidgetOrNone()
        if backup is None or widget is None:
            return
        for name in self.WIDGET_STATE_FIELDS:
            setattr(widget, name, backup[name])
        widget._disconnectAllLinks()
        for role in widget._linkDropped:
            widget._linkDropped[role] = False
            widget._linkDropSnapshots[role] = None
        widget._refreshCameraControls()
        widget._configureResultControls()
        if backup["status"] is not None:
            widget._setStatus(backup["status"])
        if backup["resultStatus"] is not None:
            widget._setResultStatus("WARN", backup["resultStatus"])
        if backup["resultSource"] is not None:
            widget.ui.resultSourceValueLabel.setText(backup["resultSource"])

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
            return None
        return widget if getattr(widget, "ui", None) is not None else None

    @staticmethod
    def _createResultVolume(resultMap: str, values, *, marked: bool = True, name=None):
        values = np.ascontiguousarray(values)
        className = (
            "vtkMRMLVectorVolumeNode" if values.ndim == 4 else "vtkMRMLScalarVolumeNode"
        )
        deviceName = RESULT_MAP_DEVICE_NAMES[resultMap]
        volumeNode = slicer.mrmlScene.AddNewNodeByClass(
            className, name or deviceName
        )
        slicer.util.updateVolumeFromArray(volumeNode, values)
        if marked:
            volumeNode.SetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE, resultMap)
            volumeNode.SetAttribute(
                RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_GENUINE_ORIGIN
            )
            volumeNode.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, deviceName)
        return volumeNode

    @staticmethod
    def _createSimulatedResultVolume(resultMap: str, values, *, detail=None, name=None):
        """Create the kind of node an external stand-in producer would send."""
        values = np.ascontiguousarray(values)
        className = (
            "vtkMRMLVectorVolumeNode" if values.ndim == 4 else "vtkMRMLScalarVolumeNode"
        )
        deviceName = RESULT_MAP_DEVICE_NAMES[resultMap]
        volumeNode = slicer.mrmlScene.AddNewNodeByClass(className, name or deviceName)
        slicer.util.updateVolumeFromArray(volumeNode, values)
        volumeNode.SetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE, resultMap)
        volumeNode.SetAttribute(
            RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN
        )
        volumeNode.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, deviceName)
        if detail is not None:
            volumeNode.SetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE, detail)
        return volumeNode

    @staticmethod
    def _validResultValues(resultMap: str):
        # These are deterministic unit-test fixtures, not pipeline images. They
        # must never be used as evidence for the manual recorded-input check.
        if resultMap == RESULT_MAP_MV_CLASS:
            return np.array([[[1, 2], [3, 4]]], dtype=np.uint8)
        if resultMap in (RESULT_MAP_SVM_PROB, RESULT_MAP_KNN_PROB):
            return np.array(
                [
                    [
                        [[0.1, 0.2, 0.3, 0.4], [0.2, 0.3, 0.4, 0.5]],
                        [[0.3, 0.4, 0.5, 0.6], [0.4, 0.5, 0.6, 0.7]],
                    ]
                ],
                dtype=np.float32,
            )
        return np.array([[[0.1, 0.2], [0.3, 0.4]]], dtype=np.float32)

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
        # SLIA-022: the delineation layer defaults to the one map the genuine
        # UC1 runner sends, so a demonstrator session does not wait on UC1_TMD.
        # The module's parameter node outlives setUp's scene clear and carries
        # whatever an earlier test wrote, so the declared default is read from
        # a freshly wrapped node.
        freshParameters = parameterModule.SLIAFlowParameterNode(
            slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
        )
        self.assertEqual(freshParameters.resultMap, RESULT_MAP_MV_CLASS)
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
        refreshButton = slicer.util.findChild(representation, "refreshResultButton")
        status = slicer.util.findChild(representation, "statusLabel")

        self.assertIsNotNone(liveSource)
        self.assertEqual(
            liveSource.isEnabled(),
            widget.logic.openIGTLinkAvailable(),
            "Live-source switching must be offered wherever there is a second "
            "source to switch to",
        )
        self.assertIsNotNone(resultMap)
        self.assertEqual(resultMap.isEnabled(), widget._presentationActive)
        self.assertIsNotNone(resultClass)
        self.assertFalse(resultClass.isEnabled())
        self.assertIsNotNone(refreshButton)
        self.assertEqual(refreshButton.isEnabled(), widget._presentationActive)

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
        self.assertEqual(resultMap.currentText, parameters.resultMap)
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
        class FakeTimer:
            def __init__(self) -> None:
                self.callback = None
                self.interval = None
                self.started = False

            def connect(self, signal, callback) -> None:
                if signal != "timeout()":
                    raise AssertionError(f"Unexpected signal: {signal}")
                self.callback = callback

            def disconnect(self, signal, callback) -> None:
                if signal != "timeout()":
                    raise AssertionError(f"Unexpected signal: {signal}")
                if self.callback == callback:
                    self.callback = None

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
        timer.fire()
        self.assertEqual(errors, [])
        np.testing.assert_array_equal(frames[0], np.array([[[[33, 22, 11]]]]))
        logic.stopCamera()
        self.assertFalse(timer.started)
        self.assertTrue(createdCaptures[2].released)
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

    def test_openCvRequirementMatchesExtensionManifest(self) -> None:
        requirementsPath = Path(__file__).resolve().parents[1] / "Resources" / "requirements.txt"
        pins = [
            line.strip()
            for line in requirementsPath.read_text(encoding="utf-8").splitlines()
            if line.strip().lower().startswith("opencv-python-headless==")
        ]
        self.assertEqual(pins, [SLIAFlowLogic.OPENCV_REQUIREMENT])

    def test_cameraFrameUpdatesOnlyLiveView(self) -> None:
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

        _, widget = self._moduleRepresentationAndWidget()
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
        finally:
            widget._stopCamera(clearLiveView=True, layoutManager=layoutManager)

    def _waitForUi(self, predicate, description: str) -> None:
        deadline = time.monotonic() + self.EVENT_LOOP_TIMEOUT_SEC
        while time.monotonic() < deadline:
            slicer.app.processEvents()
            if predicate():
                return
        self.fail(
            f"Timed out after {self.EVENT_LOOP_TIMEOUT_SEC:.1f} s waiting for {description}."
        )

    def test_layoutDescriptionContract(self) -> None:
        from xml.etree import ElementTree

        widget = self._moduleRepresentationAndWidget()[1]
        layoutRoot = ElementTree.fromstring(widget.CUSTOM_LAYOUT_DESCRIPTION)
        # The WP5 demonstrator screen in docs/architecture/WP5_MS5_DEMO_PLAN.md:
        # two rows of three named views.
        self.assertEqual(layoutRoot.attrib["type"], "vertical")
        rows = layoutRoot.findall("./item/layout")
        self.assertEqual(
            [row.attrib["type"] for row in rows], ["horizontal", "horizontal"]
        )
        expectedLabels = [
            ["LiveView", "Stereoscopic", "HS Cube"],
            ["Relative StO2", "Enhanced Vascularization", "Tumour Delineation"],
        ]
        observedLabels = []
        singletonTags = []
        for row in rows:
            rowLabels = []
            for view in row.findall("./item/view"):
                viewLabelProperty = view.find("property[@name='viewlabel']")
                if viewLabelProperty is None:
                    raise AssertionError("A custom view is missing its view label property")
                viewLabel = viewLabelProperty.text
                if not isinstance(viewLabel, str):
                    self.fail("A custom view label is empty")
                rowLabels.append(viewLabel)
                singletonTags.append(view.attrib["singletontag"])
            observedLabels.append(rowLabels)
        self.assertEqual(observedLabels, expectedLabels)
        self.assertEqual(len(set(singletonTags)), 6)
        # The pane-isolation guards are written against these two tags, so the
        # live and delineation views keep them.
        self.assertEqual(singletonTags[0], widget.LIVE_VIEW_NAME)
        self.assertEqual(singletonTags[5], widget.RESULT_VIEW_NAME)
        self.assertEqual(widget.LIVE_VIEW_LABEL, "LiveView")
        self.assertEqual(widget.RESULT_VIEW_LABEL, "Tumour Delineation")

    def test_headlessPresentationFallback(self) -> None:
        if slicer.app.layoutManager() is not None:
            self.skipTest("This test covers only Slicer's no-main-window fallback")
        widget = self._moduleRepresentationAndWidget()[1]
        self.assertFalse(widget._activatePresentation())
        self.assertFalse(widget._presentationActive)

    def test_layoutContractAndLifecycle(self) -> None:
        widget = self._moduleRepresentationAndWidget()[1]

        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")

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

            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
            resultRenderer = widget._sliceViewRenderer(resultWidget)
            liveRenderer = widget._sliceViewRenderer(liveWidget)
            self.assertIsNotNone(resultRenderer)
            actor = widget._waitingAnnotationActor
            self.assertIsNotNone(actor)
            self.assertEqual(actor.GetInput(), widget.WAITING_RESULT_MESSAGE)
            self.assertFalse(liveRenderer.HasViewProp(actor))

            resultWidget.mrmlSliceNode().Modified()
            resultWidget.sliceLogic().GetSliceCompositeNode().Modified()
            self._waitForUi(
                lambda: bool(resultRenderer.HasViewProp(actor)),
                "the waiting annotation actor to reach the result renderer",
            )
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
            self.skipTest("Requires the maintained headful Slicer test target")

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
            layoutManager.setLayout(emptyLayout)
            self.assertTrue(widget._activatePresentation())
            self.assertIsNone(widget._previousLayout)

            widget._deactivatePresentation(restore=True)
            self.assertEqual(int(layoutNode.GetViewArrangement()), conventionalLayout)

            widget._deactivatePresentation(restore=False)
            widget._previousLayout = None
            widget._layoutBeforeSceneClose = initialLayout
            layoutManager.setLayout(emptyLayout)
            self.assertTrue(widget._activatePresentation())
            self.assertEqual(widget._previousLayout, initialLayout)

            widget._deactivatePresentation(restore=True)
            self.assertEqual(int(layoutNode.GetViewArrangement()), initialLayout)
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
            parameterNode.GetNodeReferenceID("liveVolume"), liveVolume.GetID()
        )
        self.assertEqual(
            parameterNode.GetNodeReferenceID("resultVolume"), resultVolume.GetID()
        )
        self.assertEqual(parameters.liveVolume.GetID(), liveVolume.GetID())
        self.assertEqual(parameters.resultVolume.GetID(), resultVolume.GetID())

        legacyScalarVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Legacy live volume"
        )
        parameterNode.SetNodeReferenceID("liveVolume", legacyScalarVolume.GetID())
        migratedLiveVolume = logic.getOrCreateLiveVolume(parameters)
        self.assertTrue(migratedLiveVolume.IsA("vtkMRMLVectorVolumeNode"))
        self.assertNotEqual(migratedLiveVolume.GetID(), legacyScalarVolume.GetID())
        self.assertEqual(
            parameterNode.GetNodeReferenceID("liveVolume"), migratedLiveVolume.GetID()
        )

    def test_resultPresentationForSupportedMapTypes(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()

        for resultMap in RESULT_MAP_CHOICES:
            sourceNode = self._createResultVolume(
                resultMap, self._validResultValues(resultMap)
            )
            parameters.resultMap = resultMap
            report = logic.presentSelectedResult(parameters)
            self.assertEqual(report["summaryStatus"], "PASS", report)
            self.assertEqual(parameters.resultSourceVolume.GetID(), sourceNode.GetID())
            resultNode = parameters.resultVolume
            self.assertIsNotNone(resultNode)
            displayNode = resultNode.GetDisplayNode()
            self.assertIsNotNone(displayNode)
            colorNode = displayNode.GetColorNode()
            self.assertIsNotNone(colorNode)
            self.assertEqual(colorNode.GetAttribute("SLIAFlow.Owner"), "ResultPresentation")
            self.assertFalse(displayNode.GetSaveWithScene())
            self.assertFalse(displayNode.GetAutoWindowLevel())
            windowLevelRange = (
                displayNode.GetWindowLevelMin(),
                displayNode.GetWindowLevelMax(),
            )
            if resultMap == RESULT_MAP_MV_CLASS:
                self.assertEqual(colorNode.GetClassName(), "vtkMRMLColorTableNode")
                self.assertEqual(colorNode.GetNumberOfColors(), 5)
                self.assertFalse(displayNode.GetInterpolate())
                self.assertEqual(windowLevelRange, (0.0, 4.0), resultMap)
            else:
                self.assertNotEqual(colorNode.GetClassName(), "vtkMRMLColorTableNode")
                transferFunction = colorNode.GetColorTransferFunction()
                self.assertIsNotNone(transferFunction)
                self.assertEqual(
                    transferFunction.GetSize(),
                    len(SLIAFlowLogic.PROBABILITY_COLOR_RAMP),
                )
                self.assertEqual(tuple(transferFunction.GetRange()), (0.0, 1.0))
                self.assertTrue(displayNode.GetInterpolate())
                self.assertEqual(windowLevelRange, (0.0, 1.0), resultMap)

    # The UC1 pipeline's own majority-voting palette, read from the source the
    # genuine binary is built from: majorityVoting in
    # gpu_single_bsq/source/functions_cuda.cu fills a B,G,R buffer, and
    # writeMatrixRGB in gpu_single_bsq/source/BitmapWriter.cpp writes it out
    # as R,G,B. Index 0 is SLIAFlow's own "no class" entry and stays invisible.
    UC1_CLASS_PALETTE = (
        ("Unused", (0.0, 0.0, 0.0, 0.0)),
        ("Normal", (0.0, 1.0, 0.0, 1.0)),
        ("Tumour", (1.0, 0.0, 0.0, 1.0)),
        ("Hypervascularized", (0.0, 0.0, 1.0, 1.0)),
        ("Background", (0.0, 0.0, 0.0, 1.0)),
    )

    def test_classColorTableMatchesUc1Palette(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        self._createResultVolume(
            RESULT_MAP_MV_CLASS, self._validResultValues(RESULT_MAP_MV_CLASS)
        )
        parameters.resultMap = RESULT_MAP_MV_CLASS
        report = logic.presentSelectedResult(parameters)
        self.assertEqual(report["summaryStatus"], "PASS", report)
        colorNode = parameters.resultVolume.GetDisplayNode().GetColorNode()
        self.assertEqual(colorNode.GetClassName(), "vtkMRMLColorTableNode")
        self.assertEqual(colorNode.GetNumberOfColors(), len(self.UC1_CLASS_PALETTE))

        for index, (expectedName, expectedRgba) in enumerate(self.UC1_CLASS_PALETTE):
            rgba = [0.0, 0.0, 0.0, 0.0]
            self.assertTrue(colorNode.GetColor(index, rgba), index)
            self.assertEqual(colorNode.GetColorName(index), expectedName, index)
            for component, (actual, expected) in enumerate(zip(rgba, expectedRgba, strict=True)):
                self.assertAlmostEqual(
                    actual,
                    expected,
                    places=6,
                    msg=f"entry {index} ({expectedName}) component {component}: "
                    f"got {tuple(rgba)}, expected {expectedRgba}",
                )

    def test_classMapSlicePipelineEmitsUc1Colors(self) -> None:
        # The colour table alone does not prove what a slice view draws:
        # window/level runs before the table, so a wrong range would paint
        # every class in a neighbour's colour. This reads the RGBA the display
        # node hands to the slice views.
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        self._createResultVolume(
            RESULT_MAP_MV_CLASS, self._validResultValues(RESULT_MAP_MV_CLASS)
        )
        parameters.resultMap = RESULT_MAP_MV_CLASS
        report = logic.presentSelectedResult(parameters)
        self.assertEqual(report["summaryStatus"], "PASS", report)
        resultNode = parameters.resultVolume
        connection = resultNode.GetDisplayNode().GetOutputImageDataConnection()
        producer = connection.GetProducer()
        producer.Update()
        output = producer.GetOutputDataObject(connection.GetIndex())
        emitted = vtk_to_numpy(output.GetPointData().GetScalars())
        classes = vtk_to_numpy(resultNode.GetImageData().GetPointData().GetScalars())
        self.assertEqual(sorted(set(classes.tolist())), [1, 2, 3, 4])
        self.assertEqual(emitted.shape, (classes.size, 4))

        for voxel, classValue in enumerate(classes.tolist()):
            name, expectedRgba = self.UC1_CLASS_PALETTE[classValue]
            self.assertEqual(
                tuple(int(component) for component in emitted[voxel]),
                tuple(round(component * 255) for component in expectedRgba),
                f"voxel {voxel}, class {classValue} ({name})",
            )

    def test_reloadAndTestRunsPastSkippedTests(self) -> None:
        # Slicer's Reload and Test calls runTest on a single instance rather
        # than going through a unittest runner. A skip must be reported and the
        # run must go on; a failure must still fail the run.
        ran = []

        class SkipThenPassProbe(ScriptedLoadableModuleTest):
            runTest = SLIAFlowTest.runTest

            def test_aSkips(self) -> None:
                ran.append("test_aSkips")
                self.skipTest("probe skip")

            def test_bPasses(self) -> None:
                ran.append("test_bPasses")

        class FailingProbe(ScriptedLoadableModuleTest):
            runTest = SLIAFlowTest.runTest

            def test_fails(self) -> None:
                self.fail("probe failure")

        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            try:
                SkipThenPassProbe().runTest()
            except unittest.SkipTest as error:
                self.fail(f"a skipped test ended the run early: {error}")
        self.assertEqual(ran, ["test_aSkips", "test_bPasses"], log.getvalue())
        self.assertIn("skipped 'probe skip'", log.getvalue())

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(AssertionError):
            FailingProbe().runTest()

    def test_resultValidationRejectsMalformedMaps(self) -> None:
        logic = SLIAFlowLogic()
        malformed = (
            (RESULT_MAP_TMD, np.array([[[0.5]]], dtype=np.float64)),
            (RESULT_MAP_TMD, np.array([[[np.nan]]], dtype=np.float32)),
            (RESULT_MAP_TMD, np.array([[[1.1]]], dtype=np.float32)),
            (RESULT_MAP_MV_CLASS, np.array([[[0]]], dtype=np.uint8)),
            (RESULT_MAP_SVM_PROB, np.zeros((1, 1, 1, 3), dtype=np.float32)),
        )
        for resultMap, values in malformed:
            sourceNode = self._createResultVolume(resultMap, values)
            nodeCount = slicer.mrmlScene.GetNumberOfNodes()
            report = logic.validateResultVolume(resultMap, sourceNode)
            self.assertEqual(report["summaryStatus"], "FAIL", report)
            self.assertEqual(slicer.mrmlScene.GetNumberOfNodes(), nodeCount)

        emptyNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Empty UC1_TMD"
        )
        self.assertEqual(
            logic.validateResultVolume(RESULT_MAP_TMD, emptyNode)["summaryStatus"],
            "FAIL",
        )

    def test_invalidResultLeavesResultViewEmpty(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._createResultVolume(
            RESULT_MAP_TMD, np.array([[[1.5]]], dtype=np.float32)
        )
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "FAIL", report)
        self.assertIsNone(widget._parameterNode.resultSourceVolume)
        self.assertIsNone(widget._parameterNode.resultVolume)
        self.assertIn("invalid", widget.ui.resultStatusLabel.text.lower())
        layoutManager = slicer.app.layoutManager()
        if layoutManager is not None:
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            if resultWidget is not None:
                compositeNode = resultWidget.sliceLogic().GetSliceCompositeNode()
                self.assertIsNone(compositeNode.GetBackgroundVolumeID())

    def test_vectorProbabilityClassSelection(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        for resultMap in (RESULT_MAP_SVM_PROB, RESULT_MAP_KNN_PROB):
            sourceValues = self._validResultValues(resultMap)
            sourceNode = self._createResultVolume(resultMap, sourceValues)
            parameters.resultMap = resultMap
            firstReport = logic.presentResult(
                resultMap, sourceNode, resultClass=3, parameterNode=parameters
            )
            self.assertEqual(firstReport["summaryStatus"], "PASS", firstReport)
            resultNode = parameters.resultVolume
            resultNodeID = resultNode.GetID()
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(resultNode), sourceValues[..., 2]
            )

            secondReport = logic.presentResult(
                resultMap, sourceNode, resultClass=1, parameterNode=parameters
            )
            self.assertEqual(secondReport["summaryStatus"], "PASS", secondReport)
            self.assertEqual(parameters.resultVolume.GetID(), resultNodeID)
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(parameters.resultVolume), sourceValues[..., 0]
            )
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(sourceNode), sourceValues
            )

    def test_parameterNodeStoresResultReferencesByID(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        sourceNode = self._createResultVolume(
            RESULT_MAP_TMD, self._validResultValues(RESULT_MAP_TMD)
        )
        parameters.resultMap = RESULT_MAP_TMD
        report = logic.presentSelectedResult(parameters)
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertEqual(
            parameters.parameterNode.GetNodeReferenceID("resultSourceVolume"),
            sourceNode.GetID(),
        )
        self.assertEqual(
            parameters.parameterNode.GetNodeReferenceID("resultVolume"),
            parameters.resultVolume.GetID(),
        )
        self.assertEqual(report["resultNodeID"], parameters.resultVolume.GetID())
        self.assertEqual(
            report["displayNodeID"],
            parameters.resultVolume.GetDisplayNode().GetID(),
        )

    def test_singleComponentMapIgnoresStaleClassSelection(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        self._createResultVolume(
            RESULT_MAP_SVM_PROB, self._validResultValues(RESULT_MAP_SVM_PROB)
        )
        tmdSource = self._createResultVolume(
            RESULT_MAP_TMD, self._validResultValues(RESULT_MAP_TMD)
        )

        parameters.resultMap = RESULT_MAP_SVM_PROB
        parameters.resultClass = 3
        vectorReport = logic.presentSelectedResult(parameters)
        self.assertEqual(vectorReport["summaryStatus"], "PASS", vectorReport)

        parameters.resultMap = RESULT_MAP_TMD
        report = logic.presentSelectedResult(parameters)
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertEqual(report["resultClass"], 1)
        self.assertEqual(parameters.resultSourceVolume.GetID(), tmdSource.GetID())
        np.testing.assert_array_equal(
            slicer.util.arrayFromVolume(parameters.resultVolume),
            self._validResultValues(RESULT_MAP_TMD),
        )

    def test_classControlOnlyForVectorProbabilityMaps(self) -> None:
        representation, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        resultClass = slicer.util.findChild(representation, "resultClassSpinBox")
        presentationActive = widget._presentationActive
        try:
            widget._presentationActive = True
            for resultMap, expected in (
                (RESULT_MAP_TMD, False),
                (RESULT_MAP_MV_CLASS, False),
                (RESULT_MAP_SVM_PROB, True),
                (RESULT_MAP_KNN_PROB, True),
            ):
                widget._parameterNode.resultMap = resultMap
                widget._configureResultControls()
                self.assertEqual(resultClass.isEnabled(), expected, resultMap)
        finally:
            widget._presentationActive = presentationActive
            widget._configureResultControls()

    def test_resultSourceDiscoveryRequiresGenuineMarker(self) -> None:
        logic = SLIAFlowLogic()
        unmarked = self._createResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            marked=False,
            name=RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD],
        )
        wrongOrigin = self._createResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            name="wrong-origin",
        )
        wrongOrigin.SetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE, "mock")
        wrongDevice = self._createResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            name="wrong-device",
        )
        wrongDevice.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, "not-UC1_TMD")
        genuine = self._createResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            name=RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD],
        )

        self.assertFalse(logic.isGenuineResultSource(RESULT_MAP_TMD, unmarked))
        self.assertFalse(logic.isGenuineResultSource(RESULT_MAP_TMD, wrongOrigin))
        self.assertFalse(logic.isGenuineResultSource(RESULT_MAP_TMD, wrongDevice))
        self.assertIs(logic.findResultSource(RESULT_MAP_TMD), genuine)

    def test_missingResultRestoresWaitingState(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "WARN", report)
        self.assertIsNone(widget._parameterNode.resultSourceVolume)
        self.assertIsNone(widget._parameterNode.resultVolume)
        self.assertIn("waiting", widget.ui.resultStatusLabel.text.lower())
        layoutManager = slicer.app.layoutManager()
        if layoutManager is not None:
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            if resultWidget is not None:
                compositeNode = resultWidget.sliceLogic().GetSliceCompositeNode()
                self.assertIsNone(compositeNode.GetBackgroundVolumeID())

    SIMULATION_DETAIL = "arithmetic stand-in, not a classifier"
    SIMULATION_DETAIL_REAL_PIPELINE = "real UC1 pipeline, synthetic tissue phantom"

    def test_bannerWordingFollowsTheProducer(self) -> None:
        self.assertEqual(
            simulatedBannerMessage(self.SIMULATION_DETAIL), SIMULATED_BANNER_MESSAGE
        )
        self.assertEqual(
            simulatedBannerMessage(self.SIMULATION_DETAIL_REAL_PIPELINE),
            SIMULATED_BANNER_MESSAGE_REAL_PIPELINE,
        )
        self.assertEqual(
            simulatedBannerMessage("real UC1 pipeline, synthetic input"),
            SIMULATED_BANNER_MESSAGE_REAL_PIPELINE,
        )
        # Anything that does not say what produced it keeps the stronger
        # wording. Softening the banner is never the default.
        self.assertEqual(simulatedBannerMessage(None), SIMULATED_BANNER_MESSAGE)
        self.assertEqual(simulatedBannerMessage(""), SIMULATED_BANNER_MESSAGE)
        self.assertEqual(
            simulatedBannerMessage("some other producer"), SIMULATED_BANNER_MESSAGE
        )

    def test_realPipelineResultIsBanneredWithoutCallingItUngenuine(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("This Slicer session has no layout manager")

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_MV_CLASS
        self._createSimulatedResultVolume(
            RESULT_MAP_MV_CLASS,
            self._validResultValues(RESULT_MAP_MV_CLASS),
            detail=self.SIMULATION_DETAIL_REAL_PIPELINE,
        )

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        try:
            self.assertTrue(widget._activatePresentation())
            widget._onDemoModeToggled(True)

            bannerActor = widget._simulatedBannerActor
            detailActor = widget._simulatedDetailActor
            self.assertIsNotNone(bannerActor)
            self.assertIsNotNone(detailActor)
            self.assertEqual(
                bannerActor.GetInput(), SIMULATED_BANNER_MESSAGE_REAL_PIPELINE
            )
            self.assertEqual(
                detailActor.GetInput(), self.SIMULATION_DETAIL_REAL_PIPELINE
            )
        finally:
            widget._deactivatePresentation(restore=True)
            widget._resetDemoMode()
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

    def test_simulatedSourceIsNotGenuine(self) -> None:
        logic = SLIAFlowLogic()
        simulated = self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
        )
        self.assertFalse(logic.isGenuineResultSource(RESULT_MAP_TMD, simulated))
        self.assertTrue(logic.isSimulatedResultSource(RESULT_MAP_TMD, simulated))
        self.assertIsNone(logic.findResultSource(RESULT_MAP_TMD))
        self.assertIs(
            logic.findResultSource(RESULT_MAP_TMD, allowSimulated=True), simulated
        )

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self.assertFalse(widget._demoModeEnabled)
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "WARN", report)
        self.assertIsNone(widget._parameterNode.resultSourceVolume)
        self.assertIsNone(widget._parameterNode.resultVolume)
        self.assertIn("waiting", widget.ui.resultStatusLabel.text.lower())
        self.assertIsNone(widget._simulatedBannerActor)

    def test_demoModeDiscoversSimulatedSource(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
        )

        self.assertEqual(
            widget._refreshResultPresentation()["summaryStatus"], "WARN"
        )

        widget._demoModeEnabled = True
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertEqual(report["dataOrigin"], RESULT_SOURCE_SIMULATED_ORIGIN)
        self.assertEqual(report["simulationDetail"], self.SIMULATION_DETAIL)
        self.assertIsNotNone(widget._parameterNode.resultVolume)
        self.assertIn("SIMULATED", widget.ui.resultStatusLabel.text)

    def test_genuinePreferredOverSimulated(self) -> None:
        logic = SLIAFlowLogic()
        self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
            name="simulated-tmd",
        )
        genuine = self._createResultVolume(
            RESULT_MAP_TMD, self._validResultValues(RESULT_MAP_TMD)
        )
        self.assertIs(logic.findResultSource(RESULT_MAP_TMD), genuine)
        self.assertIs(
            logic.findResultSource(RESULT_MAP_TMD, allowSimulated=True), genuine
        )

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        widget._demoModeEnabled = True
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertEqual(report["dataOrigin"], RESULT_SOURCE_GENUINE_ORIGIN)
        self.assertIsNone(report["simulationDetail"])
        self.assertIsNone(widget._simulatedBannerActor)
        self.assertNotIn("SIMULATED", widget.ui.resultStatusLabel.text)

    def test_simulatedResultStillValidatedAgainstContract(self) -> None:
        logic = SLIAFlowLogic()
        malformed = self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            np.array([[[1.5]]], dtype=np.float32),
            detail=self.SIMULATION_DETAIL,
        )
        self.assertTrue(logic.isSimulatedResultSource(RESULT_MAP_TMD, malformed))

        report = logic.presentSelectedResult(
            parameterNode=logic.getParameterNode(),
            resultMap=RESULT_MAP_TMD,
            allowSimulated=True,
        )
        self.assertEqual(report["summaryStatus"], "FAIL", report)
        self.assertEqual(
            report["summaryMessage"],
            logic.validateResultVolume(RESULT_MAP_TMD, malformed)["summaryMessage"],
            "Simulated data must fail the identical contract, with the identical message",
        )

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        widget._demoModeEnabled = True
        widgetReport = widget._refreshResultPresentation()
        self.assertEqual(widgetReport["summaryStatus"], "FAIL", widgetReport)
        self.assertIsNone(widget._simulatedBannerActor)
        self.assertIn("invalid", widget.ui.resultStatusLabel.text.lower())

    def test_simulationDetailNeverAffectsDiscovery(self) -> None:
        logic = SLIAFlowLogic()
        genuine = self._createResultVolume(
            RESULT_MAP_TMD, self._validResultValues(RESULT_MAP_TMD)
        )
        genuine.SetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE, "should be ignored")
        self.assertIs(logic.findResultSource(RESULT_MAP_TMD), genuine)
        self.assertIsNone(logic._simulationDetail(genuine))
        slicer.mrmlScene.RemoveNode(genuine)

        deviceName = RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD]
        originless = self._createResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            marked=False,
            name=deviceName,
        )
        originless.SetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_MAP_TMD)
        originless.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, deviceName)
        originless.SetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE, self.SIMULATION_DETAIL)
        self.assertIsNone(logic.findResultSource(RESULT_MAP_TMD))
        self.assertIsNone(logic.findResultSource(RESULT_MAP_TMD, allowSimulated=True))
        self.assertIsNone(logic._simulationDetail(originless))

        verbose = self._createSimulatedResultVolume(
            RESULT_MAP_MV_CLASS,
            self._validResultValues(RESULT_MAP_MV_CLASS),
            detail="real UC1 pipeline\n over a synthetic cube " + "x" * 120,
        )
        detail = logic._simulationDetail(verbose)
        self.assertNotIn("\n", detail)
        self.assertLessEqual(len(detail), logic.SIMULATION_DETAIL_MAX_CHARS)
        self.assertTrue(detail.startswith("real UC1 pipeline over a synthetic cube"))

    def test_demoModeIsNotPersisted(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        self.assertFalse(
            hasattr(widget._parameterNode, "demoMode"),
            "Demo mode must not become a persisted parameter-node field",
        )

        layoutManager = slicer.app.layoutManager()
        layoutNode = (
            None
            if layoutManager is None
            else layoutManager.layoutLogic().GetLayoutNode()
        )
        previousLayout = (
            None if layoutNode is None else int(layoutNode.GetViewArrangement())
        )
        checkBox = getattr(widget.ui, "demoModeCheckBox", None)
        self.assertIsNotNone(checkBox)
        try:
            widget._onDemoModeToggled(True)
            self.assertTrue(widget._demoModeEnabled)

            widget.enter()
            self.assertFalse(widget._demoModeEnabled)
            self.assertFalse(checkBox.isChecked())

            widget._onDemoModeToggled(True)
            widget.onSceneStartClose()
            self.assertFalse(widget._demoModeEnabled)
            self.assertFalse(checkBox.isChecked())
        finally:
            widget._deactivatePresentation(restore=True)
            widget._resetDemoMode()
            if layoutNode is not None and (
                int(layoutNode.GetViewArrangement()) != previousLayout
            ):
                layoutManager.setLayout(previousLayout)

    def test_simulatedProvenanceReachesResultNode(self) -> None:
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        parameters.resultMap = RESULT_MAP_TMD
        self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
            name="simulated-tmd",
        )

        report = logic.presentSelectedResult(
            parameterNode=parameters, resultMap=RESULT_MAP_TMD, allowSimulated=True
        )
        self.assertEqual(report["summaryStatus"], "PASS", report)
        resultNode = parameters.resultVolume
        self.assertEqual(
            resultNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            RESULT_SOURCE_SIMULATED_ORIGIN,
        )
        self.assertEqual(resultNode.GetName(), logic.SIMULATED_RESULT_VOLUME_NAME)

        genuine = self._createResultVolume(
            RESULT_MAP_TMD, self._validResultValues(RESULT_MAP_TMD)
        )
        genuineReport = logic.presentSelectedResult(
            parameterNode=parameters, resultMap=RESULT_MAP_TMD, allowSimulated=True
        )
        self.assertEqual(genuineReport["summaryStatus"], "PASS", genuineReport)
        self.assertIs(parameters.resultSourceVolume, genuine)
        self.assertEqual(
            parameters.resultVolume.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        self.assertEqual(
            parameters.resultVolume.GetName(),
            logic.RESULT_VOLUME_NAME,
            "A node that once carried simulated data must not keep the marker",
        )

    def test_simulatedResultShowsPersistentBanner(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("This Slicer session has no layout manager")

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
        )

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        try:
            self.assertTrue(widget._activatePresentation())
            widget._onDemoModeToggled(True)

            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            renderer = widget._sliceViewRenderer(resultWidget)
            self.assertIsNotNone(renderer)
            bannerActor = widget._simulatedBannerActor
            detailActor = widget._simulatedDetailActor
            self.assertIsNotNone(bannerActor)
            self.assertIsNotNone(detailActor)
            self.assertEqual(bannerActor.GetInput(), SIMULATED_BANNER_MESSAGE)
            self.assertEqual(detailActor.GetInput(), self.SIMULATION_DETAIL)
            self.assertTrue(renderer.HasViewProp(bannerActor))
            self.assertTrue(renderer.HasViewProp(detailActor))

            resultWidget.mrmlSliceNode().Modified()
            resultWidget.sliceLogic().GetSliceCompositeNode().Modified()
            # Refresh once, then wait only on what the renderer shows. Polling
            # `_refreshResultPresentation()` would re-assert the banner on
            # every turn of the loop, so the wait would be driving the state it
            # claims to be observing.
            self.assertEqual(
                widget._refreshResultPresentation()["summaryStatus"], "PASS"
            )
            self._waitForUi(
                lambda: bool(
                    widget._sliceViewRenderer(resultWidget).HasViewProp(
                        widget._simulatedBannerActor
                    )
                ),
                "the simulated banner to survive the slice view rebuild",
            )
            renderer = widget._sliceViewRenderer(resultWidget)
            self.assertTrue(renderer.HasViewProp(widget._simulatedBannerActor))
            self.assertTrue(renderer.HasViewProp(widget._simulatedDetailActor))

            widget._onDemoModeToggled(False)
            self.assertIsNone(widget._simulatedBannerActor)
            self.assertIsNone(widget._simulatedDetailActor)
            self.assertFalse(renderer.HasViewProp(bannerActor))
            self.assertFalse(renderer.HasViewProp(detailActor))
        finally:
            widget._deactivatePresentation(restore=True)
            widget._resetDemoMode()
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

    def test_presentedResultIsNotRediscoveredAsSource(self) -> None:
        """The module's own output must never re-enter discovery as a source.

        The presentation node carries the role, device and origin attributes
        copied from whatever it last displayed, so it satisfies every other
        condition in the source match. Only its SLIAFlow ownership keeps it
        out, and without that a stale presentation would be re-presented as an
        external result long after the real source left the scene.
        """
        logic = SLIAFlowLogic()
        parameters = logic.getParameterNode()
        for resultMap, allowSimulated, create in (
            (RESULT_MAP_TMD, False, self._createResultVolume),
            (RESULT_MAP_MV_CLASS, False, self._createResultVolume),
            (RESULT_MAP_SVM_PROB, False, self._createResultVolume),
            (RESULT_MAP_TMD, True, self._createSimulatedResultVolume),
        ):
            sourceNode = create(resultMap, self._validResultValues(resultMap))
            parameters.resultMap = resultMap
            report = logic.presentSelectedResult(
                parameterNode=parameters,
                resultMap=resultMap,
                allowSimulated=allowSimulated,
            )
            self.assertEqual(report["summaryStatus"], "PASS", report)
            resultNode = parameters.resultVolume
            self.assertIsNotNone(resultNode)
            self.assertFalse(
                logic.isGenuineResultSource(resultMap, resultNode),
                f"{resultMap}: the presentation node matched as a genuine source",
            )
            self.assertFalse(
                logic.isSimulatedResultSource(resultMap, resultNode),
                f"{resultMap}: the presentation node matched as a simulated source",
            )

            slicer.mrmlScene.RemoveNode(sourceNode)
            self.assertIsNone(
                logic.findResultSource(resultMap, allowSimulated=allowSimulated),
                f"{resultMap}: discovery found the module's own output",
            )
            staleReport = logic.presentSelectedResult(
                parameterNode=parameters,
                resultMap=resultMap,
                allowSimulated=allowSimulated,
            )
            self.assertEqual(
                staleReport["summaryStatus"],
                "WARN",
                f"{resultMap}: stale output was re-presented as a result",
            )
            self.assertIsNone(parameters.resultSourceVolume)

    def test_bannerFailureWithholdsSimulatedResult(self) -> None:
        """A banner that cannot be drawn withholds the result, not the banner.

        The result view exists here, so _displayResultVolume would paint the
        simulated map into it. If the banner cannot be attached to that view,
        displaying anyway is exactly the unmarked simulated output the
        medical-data policy forbids.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("This Slicer session has no layout manager")

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._createSimulatedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            detail=self.SIMULATION_DETAIL,
        )

        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        try:
            self.assertTrue(widget._activatePresentation())
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            self.assertIsNotNone(resultWidget)

            # The reported condition: the result view is on screen but has no
            # renderer yet to carry the banner.
            widget._sliceViewRenderer = lambda sliceWidget: None
            widget._demoModeEnabled = True
            report = widget._refreshResultPresentation()

            self.assertEqual(report["summaryStatus"], "FAIL", report)
            self.assertEqual(
                report["summaryMessage"], widget.BANNER_UNAVAILABLE_STATUS
            )
            self.assertIsNone(widget._simulatedBannerActor)
            self.assertIsNone(widget._simulatedDetailActor)
            self.assertIsNone(widget._parameterNode.resultSourceVolume)
            self.assertIsNone(
                resultWidget.sliceLogic()
                .GetSliceCompositeNode()
                .GetBackgroundVolumeID(),
                "The simulated map was displayed without its banner",
            )
            self.assertIn("withheld", widget.ui.resultStatusLabel.text.lower())
        finally:
            del widget._sliceViewRenderer
            widget._deactivatePresentation(restore=True)
            widget._resetDemoMode()
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

    # ----------------------------------------------------------------------
    # SLIA-008 - OpenIGTLink reception
    # ----------------------------------------------------------------------

    @staticmethod
    def _createReceivedVolume(deviceName, values, metadata, *, prefixed=True):
        """Create the node the connector would leave in the scene.

        `vtkMRMLIGTLConnectorNode` writes every incoming metadata entry as
        `"OpenIGTLink." + key`, so a test that stamps the bare names is testing
        a receiver that will never exist. The prefix is applied here for the
        same reason it is stripped in the module.
        """
        values = np.ascontiguousarray(values)
        className = (
            "vtkMRMLVectorVolumeNode" if values.ndim == 4 else "vtkMRMLScalarVolumeNode"
        )
        volumeNode = slicer.mrmlScene.AddNewNodeByClass(className, deviceName)
        slicer.util.updateVolumeFromArray(volumeNode, values)
        prefix = WIRE_ATTRIBUTE_PREFIX if prefixed else ""
        for key, value in metadata.items():
            volumeNode.SetAttribute(prefix + key, value)
        return volumeNode

    @classmethod
    def _receivedResultVolume(cls, resultMap, values, origin, *, detail=None, prefixed=True):
        metadata = {
            RESULT_SOURCE_ROLE_ATTRIBUTE: resultMap,
            RESULT_SOURCE_DEVICE_ATTRIBUTE: RESULT_MAP_DEVICE_NAMES[resultMap],
        }
        if origin is not None:
            metadata[RESULT_SOURCE_ORIGIN_ATTRIBUTE] = origin
        if detail is not None:
            metadata[RESULT_SOURCE_DETAIL_ATTRIBUTE] = detail
        return cls._createReceivedVolume(
            RESULT_MAP_DEVICE_NAMES[resultMap], values, metadata, prefixed=prefixed
        )

    @classmethod
    def _receivedLiveViewVolume(cls):
        frame = np.zeros((1, 4, 6, 3), dtype=np.uint8)
        frame[..., 0] = 200
        return cls._createReceivedVolume(
            LIVE_VIEW_DEVICE_NAME,
            frame,
            {
                RESULT_SOURCE_DEVICE_ATTRIBUTE: LIVE_VIEW_DEVICE_NAME,
                RESULT_SOURCE_ORIGIN_ATTRIBUTE: RESULT_SOURCE_SIMULATED_ORIGIN,
                RESULT_SOURCE_DETAIL_ATTRIBUTE: "acquisition stand-in, synthetic scene",
            },
        )

    class _FakeConnector:
        """A connector stand-in for a Slicer built without OpenIGTLink.

        The Source test target runs against the base Slicer build, which has no
        `vtkMRMLIGTLConnectorNode` at all, so connector lifecycle would
        otherwise be untestable exactly where it is most likely to leak.
        """

        def __init__(self) -> None:
            self.attributes = {}
            self.client = None
            self.saveWithScene = None
            self.state = 0
            self.startCount = 0
            self.stopCount = 0

        def SetAttribute(self, name, value):
            self.attributes[name] = value

        def GetAttribute(self, name):
            return self.attributes.get(name)

        def SetSaveWithScene(self, value):
            self.saveWithScene = value

        def SetTypeClient(self, hostname, port):
            self.client = (hostname, port)
            return 1

        def Start(self):
            self.startCount += 1
            self.state = 1
            return 1

        def Stop(self):
            self.stopCount += 1
            self.state = 0
            return 1

        def GetState(self):
            return self.state

    def test_prefixedAndBareWireAttributesBothTranslate(self) -> None:
        """Both spellings reach discovery; the prefixed one is authoritative.

        The prefixed spelling is what the pinned SlicerOpenIGTLink build
        produces, so it is the one that must work. The bare spelling is
        accepted as well so that the receiver keeps working if the pin ever
        moves to a build that behaves differently.
        """
        logic = SLIAFlowLogic()
        prefixedNode = self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        self.assertIsNone(
            prefixedNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            "The received node must start with only the prefixed spelling",
        )
        self.assertIsNone(
            logic.findResultSource(RESULT_MAP_TMD),
            "Discovery must read canonical attributes, which do not exist yet",
        )

        logic.normalizeReceivedProvenance()
        self.assertEqual(
            prefixedNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        self.assertEqual(
            prefixedNode.GetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE),
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD],
        )
        self.assertIs(logic.findResultSource(RESULT_MAP_TMD), prefixedNode)

        # A stale canonical value left by an earlier message never outranks
        # what the current message actually put on the wire.
        prefixedNode.SetAttribute(
            RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN
        )
        logic.normalizeReceivedProvenance(prefixedNode)
        self.assertEqual(
            prefixedNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        slicer.mrmlScene.RemoveNode(prefixedNode)

        bareNode = self._receivedResultVolume(
            RESULT_MAP_MV_CLASS,
            self._validResultValues(RESULT_MAP_MV_CLASS),
            RESULT_SOURCE_GENUINE_ORIGIN,
            prefixed=False,
        )
        logic.normalizeReceivedProvenance()
        self.assertIs(logic.findResultSource(RESULT_MAP_MV_CLASS), bareNode)

    def test_unknownProvenanceIsRejectedNotDefaulted(self) -> None:
        """Absent or unrecognized provenance is invalid in both directions.

        Treating a missing origin as genuine displays unmarked data of unknown
        origin; treating it as simulated invents a provenance the sender never
        claimed. Both are fabrications, so both must fail.
        """
        logic = SLIAFlowLogic()
        for origin in (None, "", "mock", "external_genuine"):
            with self.subTest(origin=origin):
                node = self._receivedResultVolume(
                    RESULT_MAP_TMD,
                    self._validResultValues(RESULT_MAP_TMD),
                    origin,
                )
                logic.normalizeReceivedProvenance()
                self.assertIsNone(logic.receivedOrigin(node))
                self.assertIsNone(logic.findResultSource(RESULT_MAP_TMD))
                self.assertIsNone(
                    logic.findResultSource(RESULT_MAP_TMD, allowSimulated=True)
                )
                self.assertIs(logic.unrecognizedProvenanceNode(RESULT_MAP_TMD), node)

                for allowSimulated in (False, True):
                    report = logic.presentSelectedResult(
                        parameterNode=logic.getParameterNode(),
                        resultMap=RESULT_MAP_TMD,
                        allowSimulated=allowSimulated,
                    )
                    self.assertEqual(report["summaryStatus"], "FAIL", report)
                    self.assertEqual(report["provenance"], "unrecognized", report)
                slicer.mrmlScene.RemoveNode(node)

        # A node that claims nothing at all is not a claim to reject. It keeps
        # the ordinary waiting state, so an unrelated scene volume that happens
        # to share the device name is not reported as a broken UC1 result.
        plain = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD]
        )
        slicer.util.updateVolumeFromArray(
            plain, self._validResultValues(RESULT_MAP_TMD)
        )
        self.assertIsNone(logic.unrecognizedProvenanceNode(RESULT_MAP_TMD))
        self.assertEqual(
            logic.presentSelectedResult(
                parameterNode=logic.getParameterNode(), resultMap=RESULT_MAP_TMD
            )["summaryStatus"],
            "WARN",
        )

    def test_receivedSimulatedNodeObeysDemoModeGate(self) -> None:
        """A simulated map arriving over the wire is still opt-in only.

        Nothing about having crossed a socket makes simulated data displayable.
        The gate is the SLIA-010 demo-mode opt-in and the banner, exactly as it
        is for a node created in the scene.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_SIMULATED_ORIGIN,
            detail=self.SIMULATION_DETAIL,
        )

        withDemoModeOff = widget._refreshResultPresentation()
        self.assertEqual(withDemoModeOff["summaryStatus"], "WARN", withDemoModeOff)
        self.assertIsNone(widget._parameterNode.resultVolume)

        widget._demoModeEnabled = True
        try:
            report = widget._refreshResultPresentation()
            self.assertEqual(report["summaryStatus"], "PASS", report)
            self.assertEqual(report["dataOrigin"], RESULT_SOURCE_SIMULATED_ORIGIN)
            self.assertEqual(report["simulationDetail"], self.SIMULATION_DETAIL)
            self.assertIn("SIMULATED", widget.ui.resultStatusLabel.text)
            if slicer.app.layoutManager() is not None:
                self.assertIsNotNone(
                    widget._simulatedBannerActor,
                    "A received simulated result was displayed without its banner",
                )
        finally:
            widget._resetDemoMode()

    def test_liveViewNodeBindsToLivePaneOnly(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.liveSource = LIVE_SOURCE_IGTL
        liveNode = self._receivedLiveViewVolume()

        report = widget._displayLiveViewNode()
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertIs(widget._parameterNode.liveSourceVolume, liveNode)
        # The live stream is not a result and must never be able to reach the
        # result pane or the result references.
        self.assertIsNone(widget._parameterNode.resultSourceVolume)
        self.assertIsNone(widget._parameterNode.resultVolume)

        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        widget._activatePresentation()
        try:
            widget._displayLiveViewNode()
            liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            if liveWidget is None or resultWidget is None:
                return
            self.assertEqual(
                liveWidget.sliceLogic().GetSliceCompositeNode().GetBackgroundVolumeID(),
                liveNode.GetID(),
            )
            self.assertNotEqual(
                resultWidget.sliceLogic()
                .GetSliceCompositeNode()
                .GetBackgroundVolumeID(),
                liveNode.GetID(),
                "The LiveView stream reached the result pane",
            )
        finally:
            widget._deactivatePresentation(restore=True)

    def test_resultNodeBindsToResultPaneOnly(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("This Slicer session has no layout manager")

        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        liveNode = self._receivedLiveViewVolume()
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED

        widget._activatePresentation()
        try:
            report = widget._refreshResultPresentation()
            self.assertEqual(report["summaryStatus"], "PASS", report)
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
            if resultWidget is None or liveWidget is None:
                return
            resultNode = widget._parameterNode.resultVolume
            self.assertEqual(
                resultWidget.sliceLogic()
                .GetSliceCompositeNode()
                .GetBackgroundVolumeID(),
                resultNode.GetID(),
            )
            self.assertNotEqual(
                liveWidget.sliceLogic().GetSliceCompositeNode().GetBackgroundVolumeID(),
                resultNode.GetID(),
                "The UC1 result reached the live pane",
            )
            self.assertNotEqual(
                resultWidget.sliceLogic()
                .GetSliceCompositeNode()
                .GetBackgroundVolumeID(),
                liveNode.GetID(),
            )
            self.assertEqual(
                widget.connectionState(CONNECTOR_UC1), CONNECTION_DISPLAYING
            )
        finally:
            widget._deactivatePresentation(restore=True)

    def test_invalidResultDoesNotReplaceLastValidState(self) -> None:
        """Invalid data and a lost link are reported, never presented.

        Two different failures are covered because they must not be confused.
        Data that arrives and fails the contract clears the pane; a link that
        drops leaves the last valid image where it is and says it is stale.
        Neither is ever reported as a successful result.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        sourceNode = self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED

        self.assertEqual(
            widget._refreshResultPresentation()["summaryStatus"], "PASS"
        )
        self.assertTrue(widget._resultEverDisplayed)
        displayedNodeID = widget._parameterNode.resultVolume.GetID()

        # An active client retries after a peer loss, so the connector reports
        # WAIT_CONNECTION rather than OFF while the retained result is stale.
        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DISCONNECTED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING
        )
        self.assertEqual(
            widget._parameterNode.resultVolume.GetID(),
            displayedNodeID,
            "A disconnection discarded a result that had already validated",
        )
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())
        self.assertNotIn("PASS", widget.ui.resultStatusLabel.text)

        # Data that arrives and fails the contract does not stay on screen.
        slicer.util.updateVolumeFromArray(
            sourceNode, np.array([[[7.5, 0.2], [0.3, 0.4]]], dtype=np.float32)
        )
        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "FAIL", report)
        self.assertFalse(widget._resultEverDisplayed)
        self.assertIsNone(widget._parameterNode.resultVolume)
        self.assertEqual(widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING)

        # And a link that drops with nothing valid ever shown returns to black.
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DISCONNECTED_EVENT
        )
        self.assertIn("waiting", widget.ui.resultStatusLabel.text.lower())
        layoutManager = slicer.app.layoutManager()
        if layoutManager is not None:
            resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
            if resultWidget is not None:
                self.assertIsNone(
                    resultWidget.sliceLogic()
                    .GetSliceCompositeNode()
                    .GetBackgroundVolumeID()
                )

    def test_reconnectDoesNotRedisplayRetainedResultBeforeNewData(self) -> None:
        """A reconnect stays stale until the received node changes."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        sourceNode = self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED

        self.assertEqual(
            widget._refreshResultPresentation()["summaryStatus"], "PASS"
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_DISPLAYING
        )

        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        unobservedReport = widget._refreshResultPresentation()
        self.assertEqual(unobservedReport["summaryStatus"], "PASS", unobservedReport)
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING
        )
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())
        self.assertNotIn("PASS", widget.ui.resultStatusLabel.text)

        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DISCONNECTED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING
        )
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())

        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_CONNECTED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_RECEIVING
        )

        retainedReport = widget._refreshResultPresentation()
        self.assertEqual(retainedReport["summaryStatus"], "PASS", retainedReport)
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_RECEIVING
        )
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())
        self.assertNotIn("PASS", widget.ui.resultStatusLabel.text)

        slicer.util.updateVolumeFromArray(
            sourceNode,
            self._validResultValues(RESULT_MAP_TMD) + np.float32(0.1),
        )
        widget._presentationActive = True
        widget._lastResultRefreshTime = 0.0
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DEVICE_MODIFIED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_DISPLAYING
        )
        self.assertIn("PASS", widget.ui.resultStatusLabel.text)

    def test_reconnectDoesNotRedisplayRetainedLiveFrameBeforeNewData(self) -> None:
        """The live path applies the same reconnect gate as the result path."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.liveSource = LIVE_SOURCE_IGTL
        liveNode = self._receivedLiveViewVolume()
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_ACQUISITION, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED

        firstReport = widget._displayLiveViewNode()
        self.assertEqual(firstReport["summaryStatus"], "PASS", firstReport)
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_DISPLAYING
        )
        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        widget._onConnectorEvent(
            CONNECTOR_ACQUISITION, widget.logic.CONNECTOR_DISCONNECTED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_CONNECTING
        )
        self.assertIn("not connected", widget.ui.statusLabel.text.lower())

        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        widget._onConnectorEvent(
            CONNECTOR_ACQUISITION, widget.logic.CONNECTOR_CONNECTED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_RECEIVING
        )

        retainedReport = widget._displayLiveViewNode()
        self.assertEqual(retainedReport["summaryStatus"], "PASS", retainedReport)
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_RECEIVING
        )
        self.assertIn("not connected", widget.ui.statusLabel.text.lower())

        frame = np.zeros((1, 4, 6, 3), dtype=np.uint8)
        frame[..., 1] = 180
        slicer.util.updateVolumeFromArray(liveNode, frame)
        widget._onConnectorEvent(
            CONNECTOR_ACQUISITION, widget.logic.CONNECTOR_DEVICE_MODIFIED_EVENT
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_DISPLAYING
        )
        self.assertNotIn("not connected", widget.ui.statusLabel.text.lower())

    def test_staleWordingSurvivesBrowsingAfterADrop(self) -> None:
        """Pane-level resets do not make a retained image fresh again.

        Browsing to a map with no data, or toggling the live source, resets
        the "ever displayed" flags. Coming back to the retained image over a
        dropped link must still say it is not being updated.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        widget._parameterNode.liveSource = LIVE_SOURCE_IGTL
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        self._receivedLiveViewVolume()
        connectors = {
            role: widget.logic.getOrCreateConnector(
                role, connectorFactory=lambda role: self._FakeConnector()
            )
            for role in (CONNECTOR_UC1, CONNECTOR_ACQUISITION)
        }
        for connector in connectors.values():
            connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "PASS")
        self.assertEqual(widget._displayLiveViewNode()["summaryStatus"], "PASS")

        for role, connector in connectors.items():
            connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
            widget._onConnectorEvent(role, widget.logic.CONNECTOR_DISCONNECTED_EVENT)

        widget._parameterNode.resultMap = RESULT_MAP_SVM_PROB
        self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "WARN")
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "PASS")
        self.assertEqual(widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING)
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())
        self.assertNotIn("PASS", widget.ui.resultStatusLabel.text)

        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_LAPTOP)
        widget._onLiveSourceChanged()
        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_IGTL)
        widget._onLiveSourceChanged()
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_CONNECTING
        )
        self.assertIn("not connected", widget.ui.statusLabel.text.lower())

    def test_waitingConnectorLeavesNoStaleHistory(self) -> None:
        """A connector that never connected does not caption a later result."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DISCONNECTED_EVENT
        )
        self.assertFalse(widget._linkDropped[CONNECTOR_UC1])

        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "PASS")
        self.assertEqual(widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING)
        self.assertIn("PASS", widget.ui.resultStatusLabel.text)

    def test_connectorLifecycleIsCleanAcrossTransitions(self) -> None:
        """Connectors are configured, stopped and dropped without leaking.

        The endpoints are asserted because both a stand-in and the genuine UC1
        runner listen on the UC1 port: the endpoint has to be right, and it
        still says nothing about provenance.
        """
        logic = SLIAFlowLogic()
        created = []

        def factory(role):
            connector = self._FakeConnector()
            created.append((role, connector))
            return connector

        acquisition = logic.getOrCreateConnector(
            CONNECTOR_ACQUISITION, connectorFactory=factory
        )
        uc1 = logic.getOrCreateConnector(CONNECTOR_UC1, connectorFactory=factory)
        self.assertEqual(acquisition.client, (IGTL_HOST, ACQUISITION_PORT))
        self.assertEqual(uc1.client, (IGTL_HOST, UC1_PORT))
        self.assertEqual(acquisition.saveWithScene, False)
        self.assertEqual(
            acquisition.GetAttribute("SLIAFlow.Owner"), logic.CONNECTOR_OWNER
        )
        self.assertIs(
            logic.getOrCreateConnector(CONNECTOR_UC1, connectorFactory=factory),
            uc1,
            "A second request created a second connector for the same role",
        )
        self.assertEqual(len(created), 2)

        self.assertEqual(logic.connectorState(CONNECTOR_UC1), CONNECTION_DISCONNECTED)
        self.assertEqual(
            logic.startConnector(CONNECTOR_UC1, connectorFactory=factory),
            CONNECTION_CONNECTING,
        )
        self.assertEqual(uc1.startCount, 1)
        uc1.state = logic.CONNECTOR_STATE_CONNECTED
        self.assertEqual(logic.connectorState(CONNECTOR_UC1), CONNECTION_RECEIVING)

        # Repeated stops are harmless, and a stopped role is genuinely gone.
        self.assertEqual(logic.stopConnector(CONNECTOR_UC1), CONNECTION_DISCONNECTED)
        self.assertEqual(uc1.stopCount, 1)
        self.assertIsNone(logic.connectorNode(CONNECTOR_UC1))
        self.assertEqual(logic.stopConnector(CONNECTOR_UC1), CONNECTION_DISCONNECTED)
        self.assertEqual(uc1.stopCount, 1)

        logic.stopAllConnectors()
        self.assertEqual(acquisition.stopCount, 1)
        self.assertIsNone(logic.connectorNode(CONNECTOR_ACQUISITION))
        logic.stopAllConnectors()

        self.assertRaises(ValueError, logic.getOrCreateConnector, "not-a-role")

        # An unknown or absent state is reported as disconnected rather than
        # guessed at.
        self.assertEqual(
            logic.connectorStateName(logic.CONNECTOR_STATE_OFF),
            CONNECTION_DISCONNECTED,
        )
        self.assertEqual(
            logic.connectorStateName(logic.CONNECTOR_STATE_WAIT_CONNECTION),
            CONNECTION_CONNECTING,
        )
        self.assertEqual(
            logic.connectorStateName(logic.CONNECTOR_STATE_CONNECTED),
            CONNECTION_RECEIVING,
        )
        for unknown in (None, 99, "connected"):
            self.assertEqual(
                logic.connectorStateName(unknown), CONNECTION_DISCONNECTED
            )

        if logic.openIGTLinkAvailable():
            connector = logic.getOrCreateConnector(CONNECTOR_UC1)
            self.assertIsNotNone(connector)
            connectorID = connector.GetID()
            logic.stopConnector(CONNECTOR_UC1)
            self.assertIsNone(
                slicer.mrmlScene.GetNodeByID(connectorID),
                "A module-owned connector was left in the scene",
            )
        else:
            self.assertIsNone(logic.getOrCreateConnector(CONNECTOR_UC1))

    def test_liveSourceSwitchingReleasesTheSourceItLeaves(self) -> None:
        """Switching sources never leaves the previous one feeding the pane."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        self._receivedLiveViewVolume()

        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_IGTL)
        widget._onLiveSourceChanged()
        self.assertEqual(widget._parameterNode.liveSource, LIVE_SOURCE_IGTL)
        self.assertFalse(widget.logic.cameraActive)
        self.assertFalse(widget.ui.startButton.enabled)
        self.assertIsNotNone(widget._parameterNode.liveSourceVolume)

        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_LAPTOP)
        widget._onLiveSourceChanged()
        self.assertEqual(widget._parameterNode.liveSource, LIVE_SOURCE_LAPTOP)
        self.assertFalse(widget.logic.cameraActive)
        self.assertFalse(widget._liveViewEverDisplayed)
        self.assertIsNone(
            widget._parameterNode.liveSourceVolume,
            "The pane kept hold of the stream it had switched away from",
        )

        # The link is a separate, operator-held resource. Changing which
        # source the pane shows releases the pane, not the connection, and a
        # frame arriving while the camera is selected must not reach the pane.
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_ACQUISITION, connectorFactory=lambda role: self._FakeConnector()
        )
        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_IGTL)
        widget._onLiveSourceChanged()
        widget.ui.liveSourceSelector.setCurrentText(LIVE_SOURCE_LAPTOP)
        widget._onLiveSourceChanged()
        self.assertIs(widget.logic.connectorNode(CONNECTOR_ACQUISITION), connector)
        widget._onConnectorEvent(
            CONNECTOR_ACQUISITION, widget.logic.CONNECTOR_DEVICE_MODIFIED_EVENT
        )
        self.assertIsNone(widget._parameterNode.liveSourceVolume)

    def test_provenanceMirrorsTheWireInsteadOfAccumulating(self) -> None:
        """A key the wire stops carrying stops authenticating the node.

        The connector writes the keys a message carries and removes none, so
        the same MRML node is updated in place message after message. If the
        translation only ever wrote, a value from an earlier message would go
        on vouching for data that no longer declares it - which is exactly the
        default-by-accident this card forbids, arriving by a slower route.
        """
        logic = SLIAFlowLogic()
        node = self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        logic.normalizeReceivedProvenance()
        self.assertIs(logic.findResultSource(RESULT_MAP_TMD), node)

        # The same node, updated by a later message that no longer declares an
        # origin.
        node.RemoveAttribute(WIRE_ATTRIBUTE_PREFIX + RESULT_SOURCE_ORIGIN_ATTRIBUTE)
        logic.normalizeReceivedProvenance()
        self.assertIsNone(node.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE))
        self.assertIsNone(logic.receivedOrigin(node))
        self.assertIsNone(logic.findResultSource(RESULT_MAP_TMD))
        self.assertIsNone(
            logic.findResultSource(RESULT_MAP_TMD, allowSimulated=True),
            "An origin the wire had stopped sending still passed discovery",
        )
        # It still claims the role, so it is reported invalid rather than as a
        # result that never arrived.
        self.assertIs(logic.unrecognizedProvenanceNode(RESULT_MAP_TMD), node)

        # A producer speaking the bare dialect writes no prefixed attribute at
        # all, so there is nothing to mirror and nothing is stripped.
        bareNode = self._receivedResultVolume(
            RESULT_MAP_MV_CLASS,
            self._validResultValues(RESULT_MAP_MV_CLASS),
            RESULT_SOURCE_GENUINE_ORIGIN,
            prefixed=False,
        )
        logic.normalizeReceivedProvenance()
        self.assertEqual(
            bareNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )

    def test_staleResultIsNotReportedAsDisplayingWithoutALink(self) -> None:
        """Rediscovering the retained node may not erase the disconnection.

        The received node stays in the scene after the link drops, so every
        later refresh - an operator refresh, a result change, a demo-mode
        toggle, re-entering the module - finds it again and validates it
        again. None of that is news from the wire, and none of it may report
        a link that no longer exists as displaying.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        self.assertEqual(
            widget._refreshResultPresentation()["summaryStatus"], "PASS"
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_DISPLAYING
        )
        displayedNodeID = widget._parameterNode.resultVolume.GetID()

        widget._disconnectLink(CONNECTOR_UC1)
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1), CONNECTION_DISCONNECTED
        )

        report = widget._refreshResultPresentation()
        self.assertEqual(report["summaryStatus"], "PASS", report)
        self.assertEqual(
            widget._parameterNode.resultVolume.GetID(),
            displayedNodeID,
            "A refresh after a disconnection discarded the last valid result",
        )
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1),
            CONNECTION_DISCONNECTED,
            "A refresh after a disconnection reported the link as displaying",
        )
        self.assertIn("not connected", widget.ui.resultStatusLabel.text.lower())
        self.assertNotIn("PASS", widget.ui.resultStatusLabel.text)

    def test_lostPeerIsNoticedWithoutADisconnectedEvent(self) -> None:
        """The one event a lost link cannot deliver is its own loss.

        `igtlioConnector`'s receiver thread sets the state to WaitConnection
        and only *queues* DisconnectedEvent, because it is not on the main
        thread. The queue is drained by `ImportEventsFromEventBuffer`, reached
        only from `PeriodicProcess`, and `CallConnectorTimerHander` skips every
        connector whose state is not StateConnected. By the time the pump next
        runs, the state has already left StateConnected, so the event that
        announces the loss is stranded and never invoked. A stopped producer
        therefore left the label reading `displaying` indefinitely, which is a
        panel claiming a live link that is gone.

        The connector's state is still truthful, so the panel polls it instead
        of trusting an event that cannot arrive.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "PASS")
        self.assertEqual(widget.connectionState(CONNECTOR_UC1), CONNECTION_DISPLAYING)
        displayedNodeID = widget._parameterNode.resultVolume.GetID()

        # A poll of a link that is still up may not invent a loss.
        widget._pollLinkStates()
        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1),
            CONNECTION_DISPLAYING,
            "Polling a connected link reported it as lost",
        )

        # The peer goes away. The receiver thread has changed the state; no
        # observer fires, exactly as in a real Slicer.
        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        widget._pollLinkStates()

        self.assertEqual(
            widget.connectionState(CONNECTOR_UC1),
            CONNECTION_CONNECTING,
            "A lost peer left the label claiming a live link",
        )
        self.assertEqual(
            widget._parameterNode.resultVolume.GetID(),
            displayedNodeID,
            "Noticing the loss discarded the last valid result",
        )
        self.assertIn(
            widget.RESULT_STALE_STATUS,
            widget.ui.resultStatusLabel.text,
            "A lost peer produced no stale-result wording",
        )

    def test_nonConnectedConnectorDoesNotReportInvalid(self) -> None:
        """A non-connected connector is not an invalid live link."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            np.array([[[7.5, 0.2], [0.3, 0.4]]], dtype=np.float32),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        for state, expected in (
            (widget.logic.CONNECTOR_STATE_OFF, CONNECTION_DISCONNECTED),
            (widget.logic.CONNECTOR_STATE_WAIT_CONNECTION, CONNECTION_CONNECTING),
        ):
            with self.subTest(state=state):
                connector.state = state
                report = widget._refreshResultPresentation()

                self.assertEqual(report["summaryStatus"], "FAIL", report)
                self.assertEqual(
                    widget.connectionState(CONNECTOR_UC1),
                    expected,
                    "A non-connected connector was reported as an invalid live link",
                )

    def test_acquisitionLinkReportsDisplayingAndInvalid(self) -> None:
        """Both links expose all five states, not just the socket's three."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.liveSource = LIVE_SOURCE_IGTL
        liveNode = self._receivedLiveViewVolume()
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_ACQUISITION, connectorFactory=lambda role: self._FakeConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED

        self.assertEqual(widget._displayLiveViewNode()["summaryStatus"], "PASS")
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_DISPLAYING
        )

        liveNode.SetAndObserveImageData(None)
        self.assertEqual(widget._displayLiveViewNode()["summaryStatus"], "FAIL")
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_INVALID
        )
        self.assertIsNone(widget._parameterNode.liveSourceVolume)

        # And with no link, a rediscovered node makes no claim about one.
        widget._disconnectLink(CONNECTOR_ACQUISITION)
        widget._displayLiveViewNode()
        self.assertEqual(
            widget.connectionState(CONNECTOR_ACQUISITION), CONNECTION_DISCONNECTED
        )

    def test_throttledResultEventStillGetsATrailingRefresh(self) -> None:
        """Throttling may delay the last event of a burst, never drop it.

        A one-shot send, or the tail of a five-map cycle, arrives inside the
        throttle window behind an earlier event. Without a trailing refresh the
        pane would sit waiting on data that had already arrived until the
        operator refreshed by hand.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_TMD
        widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeConnector()
        )
        widget._presentationActive = True

        # An earlier event has just been served; the window is open.
        widget._lastResultRefreshTime = time.monotonic()
        self._receivedResultVolume(
            RESULT_MAP_TMD,
            self._validResultValues(RESULT_MAP_TMD),
            RESULT_SOURCE_GENUINE_ORIGIN,
        )
        widget._onConnectorEvent(
            CONNECTOR_UC1, widget.logic.CONNECTOR_DEVICE_MODIFIED_EVENT
        )
        self.assertIsNone(
            widget._parameterNode.resultVolume,
            "The event inside the throttle window was not throttled",
        )
        self.assertTrue(
            widget._pendingResultRefresh,
            "A dropped wire event was owed a trailing refresh and did not get one",
        )

        widget._onPendingResultRefresh()
        self.assertFalse(widget._pendingResultRefresh)
        self.assertIsNotNone(
            widget._parameterNode.resultVolume,
            "The trailing refresh did not present the data that had arrived",
        )

    # ----------------------------------------------------------------------
    # SLIA-022 - six-panel operator surface
    #
    # Names this card introduces are read through `parameterModule` or the
    # widget inside each test, not imported at the top, so that against the
    # code before the card every test fails on its own missing behaviour
    # rather than the whole suite failing to import.
    # ----------------------------------------------------------------------

    # The UC2 banner headline, as the SLIA-022 card states it.
    UC2_BANNER_MESSAGE = "SIMULATED ACQUISITION - NOT A CLINICAL RESULT"
    # The recorded-case detail form of stratum_sim.contract.recordedCaseDetail.
    UC2_SIMULATION_DETAIL = (
        "real UC2 pipeline, recorded HSI case test (simulated acquisition)"
    )
    # Ports from the table in docs/architecture/WP5_MS5_DEMO_PLAN.md.
    LINK_PORTS = {
        "acquisition": 18944,
        "uc1": 18945,
        "uc2": 18946,
        "hsCube": 18947,
        "control": 18950,
    }
    LINK_STATE_LABELS = {
        "acquisition": "acquisitionStateValueLabel",
        "uc1": "uc1StateValueLabel",
        "uc2": "uc2StateValueLabel",
        "hsCube": "hsCubeStateValueLabel",
        "control": "controlStateValueLabel",
    }

    class _FakeObservableConnector(_FakeConnector):
        """A connector the widget can observe, and that records what it sends."""

        def __init__(self) -> None:
            super().__init__()
            self.observers = {}
            self.nextTag = 0
            self.registered = []
            self.pushed = []

        def AddObserver(self, event, callback, priority=0.0):
            self.nextTag += 1
            self.observers[self.nextTag] = (event, callback)
            return self.nextTag

        def RemoveObserver(self, tag):
            self.observers.pop(tag, None)

        def RegisterOutgoingMRMLNode(self, node, devType=None):
            self.registered.append((node, devType))
            return 1

        def PushNode(self, node):
            self.pushed.append((node, node.GetText(), int(node.GetMTime())))
            return 1

    class _FakeCompositeNode:
        def __init__(self) -> None:
            self.backgroundVolumeId = None
            self.foregroundVolumeId = None
            self.labelVolumeId = None
            self.foregroundOpacity = 0.0

        def SetBackgroundVolumeID(self, nodeId) -> None:
            self.backgroundVolumeId = nodeId

        def GetBackgroundVolumeID(self):
            return self.backgroundVolumeId

        def SetForegroundVolumeID(self, nodeId) -> None:
            self.foregroundVolumeId = nodeId

        def GetForegroundVolumeID(self):
            return self.foregroundVolumeId

        def SetLabelVolumeID(self, nodeId) -> None:
            self.labelVolumeId = nodeId

        def GetLabelVolumeID(self):
            return self.labelVolumeId

        def SetForegroundOpacity(self, opacity) -> None:
            self.foregroundOpacity = float(opacity)

        def GetForegroundOpacity(self):
            return self.foregroundOpacity

    class _FakeSliceLogic:
        def __init__(self, compositeNode) -> None:
            self.compositeNode = compositeNode

        def GetSliceCompositeNode(self):
            return self.compositeNode

        def FitSliceToBackground(self) -> None:
            pass

    class _FakeSliceWidget:
        def __init__(self, sliceLogic) -> None:
            self.logic = sliceLogic

        def sliceLogic(self):
            return self.logic

        def sliceView(self):
            return None

    class _FakeLayoutManager:
        """Slice widgets whose composite nodes can be read back in any Slicer."""

        def __init__(self, testCase, viewNames) -> None:
            self.composites = {name: testCase._FakeCompositeNode() for name in viewNames}
            self.widgets = {
                name: testCase._FakeSliceWidget(testCase._FakeSliceLogic(composite))
                for name, composite in self.composites.items()
            }

        def sliceWidget(self, viewName):
            return self.widgets.get(viewName)

    @staticmethod
    def _validUc2Values():
        # A deterministic test placeholder, not a pipeline image.
        return np.array(
            [[[[10, 20, 30], [40, 50, 60]], [[70, 80, 90], [100, 110, 120]]]],
            dtype=np.uint8,
        )

    @classmethod
    def _receivedUc2Volume(cls, values, origin, *, detail=None):
        metadata = {
            RESULT_SOURCE_ROLE_ATTRIBUTE: "bloodVesselMap",
            RESULT_SOURCE_DEVICE_ATTRIBUTE: "UC2_BV",
        }
        if origin is not None:
            metadata[RESULT_SOURCE_ORIGIN_ATTRIBUTE] = origin
        if detail is not None:
            metadata[RESULT_SOURCE_DETAIL_ATTRIBUTE] = detail
        return cls._createReceivedVolume("UC2_BV", values, metadata)

    def _fakeControlConnector(self, widget, state):
        connector = widget.logic.getOrCreateConnector(
            parameterModule.CONNECTOR_CONTROL,
            connectorFactory=lambda role: self._FakeObservableConnector(),
        )
        connector.state = state
        return connector

    def test_reservedPanelIsBlackWithStatedReason(self) -> None:
        """A panel with no producer is black and says what is missing, and where.

        Black because nothing exists and black because something broke must
        never look alike, so the reason is asserted on the renderer rather than
        taken from the widget's own bookkeeping.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")

        widget = self._moduleRepresentationAndWidget()[1]
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        try:
            self.assertTrue(widget._activatePresentation())
            for viewName, subject, port in (
                (widget.STEREO_VIEW_NAME, "stereoscopic", "18948"),
                (widget.STO2_VIEW_NAME, "sto2", "18949"),
            ):
                with self.subTest(view=viewName):
                    sliceWidget = layoutManager.sliceWidget(viewName)
                    self.assertIsNotNone(sliceWidget)
                    compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
                    self.assertIsNone(compositeNode.GetBackgroundVolumeID())
                    self.assertIsNone(compositeNode.GetForegroundVolumeID())
                    self.assertIsNone(compositeNode.GetLabelVolumeID())

                    actor = widget._panelAnnotationActors.get(viewName)
                    self.assertIsNotNone(actor, "The reserved panel carries no text")
                    sliceWidget.mrmlSliceNode().Modified()
                    self._waitForUi(
                        lambda sliceWidget=sliceWidget, actor=actor: bool(
                            widget._sliceViewRenderer(sliceWidget).HasViewProp(actor)
                        ),
                        f"the reserved-panel reason to reach {viewName}",
                    )
                    reason = actor.GetInput() or ""
                    self.assertIn(port, reason)
                    self.assertIn(subject, reason.lower())
                    self.assertIn("reserved", reason.lower())
        finally:
            widget._deactivatePresentation(restore=True)
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

    def test_layersAreIndependentlyControlled(self) -> None:
        """Showing, hiding or fading one layer never changes the other.

        Opacity is display state: the layer moves between the background slot
        and a faded foreground slot, and its pixels are never touched.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultMap = RESULT_MAP_MV_CLASS
        self._createResultVolume(
            RESULT_MAP_MV_CLASS, self._validResultValues(RESULT_MAP_MV_CLASS)
        )
        self._receivedUc2Volume(self._validUc2Values(), RESULT_SOURCE_GENUINE_ORIGIN)
        uc1Layer = widget.LAYER_UC1
        uc2Layer = widget.LAYER_UC2
        layoutManager = self._FakeLayoutManager(
            self, (widget.RESULT_VIEW_NAME, widget.VASCULAR_VIEW_NAME)
        )
        uc1Composite = layoutManager.composites[widget.RESULT_VIEW_NAME]
        uc2Composite = layoutManager.composites[widget.VASCULAR_VIEW_NAME]
        try:
            self.assertEqual(widget._refreshResultPresentation()["summaryStatus"], "PASS")
            self.assertEqual(widget._refreshUc2Presentation()["summaryStatus"], "PASS")
            uc1NodeID = widget._parameterNode.resultVolume.GetID()
            uc2NodeID = widget._parameterNode.uc2Volume.GetID()
            widget._displayResultVolume(layoutManager=layoutManager)
            widget._displayUc2Volume(layoutManager=layoutManager)
            self.assertEqual(uc1Composite.GetBackgroundVolumeID(), uc1NodeID)
            self.assertEqual(uc2Composite.GetBackgroundVolumeID(), uc2NodeID)

            widget.setLayerOpacity(uc1Layer, 0.4, layoutManager=layoutManager)
            self.assertIsNone(uc1Composite.GetBackgroundVolumeID())
            self.assertEqual(uc1Composite.GetForegroundVolumeID(), uc1NodeID)
            self.assertAlmostEqual(uc1Composite.GetForegroundOpacity(), 0.4, places=6)
            self.assertEqual(uc2Composite.GetBackgroundVolumeID(), uc2NodeID)
            self.assertIsNone(uc2Composite.GetForegroundVolumeID())

            widget.setLayerVisible(uc2Layer, False, layoutManager=layoutManager)
            self.assertIsNone(uc2Composite.GetBackgroundVolumeID())
            self.assertIsNone(uc2Composite.GetForegroundVolumeID())
            self.assertIn("hidden", widget.panelMessage(widget.VASCULAR_VIEW_NAME).lower())
            self.assertEqual(uc1Composite.GetForegroundVolumeID(), uc1NodeID)
            self.assertAlmostEqual(uc1Composite.GetForegroundOpacity(), 0.4, places=6)

            visible, opacity = widget.layerState(uc1Layer)
            self.assertTrue(visible)
            self.assertAlmostEqual(opacity, 0.4, places=6)
            visible, opacity = widget.layerState(uc2Layer)
            self.assertFalse(visible)
            self.assertAlmostEqual(opacity, 1.0, places=6)

            widget.setLayerVisible(uc2Layer, True, layoutManager=layoutManager)
            self.assertEqual(uc2Composite.GetBackgroundVolumeID(), uc2NodeID)
            widget.setLayerOpacity(uc1Layer, 1.0, layoutManager=layoutManager)
            self.assertEqual(uc1Composite.GetBackgroundVolumeID(), uc1NodeID)
            self.assertIsNone(uc1Composite.GetForegroundVolumeID())
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(widget._parameterNode.uc2Volume),
                self._validUc2Values(),
            )
        finally:
            for layer in (getattr(widget, "LAYER_UC1", None), getattr(widget, "LAYER_UC2", None)):
                if layer is not None:
                    widget.setLayerVisible(layer, True)
                    widget.setLayerOpacity(layer, 1.0)

    def test_uc2LayerObeysOriginGateAndPrecedence(self) -> None:
        """UC2 gets every guard the UC1 result has, not a softer copy of them."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        uc2Layer = widget.LAYER_UC2
        simulated = self._receivedUc2Volume(
            self._validUc2Values(),
            RESULT_SOURCE_SIMULATED_ORIGIN,
            detail=self.UC2_SIMULATION_DETAIL,
        )

        withDemoModeOff = widget._refreshUc2Presentation()
        self.assertEqual(withDemoModeOff["summaryStatus"], "WARN", withDemoModeOff)
        self.assertIsNone(widget._parameterNode.uc2Volume)

        layoutManager = slicer.app.layoutManager()
        layoutNode = (
            None if layoutManager is None else layoutManager.layoutLogic().GetLayoutNode()
        )
        previousLayout = None if layoutNode is None else int(layoutNode.GetViewArrangement())
        try:
            if layoutManager is not None:
                self.assertTrue(widget._activatePresentation())
            widget._demoModeEnabled = True
            report = widget._refreshUc2Presentation()
            self.assertEqual(report["summaryStatus"], "PASS", report)
            self.assertEqual(report["dataOrigin"], RESULT_SOURCE_SIMULATED_ORIGIN)
            self.assertEqual(report["simulationDetail"], self.UC2_SIMULATION_DETAIL)
            self.assertIn("SIMULATED", widget.layerStatus(uc2Layer))
            if layoutManager is not None:
                self.assertIsNotNone(
                    widget._uc2BannerActor,
                    "A simulated UC2 map was displayed without its banner",
                )
                self.assertEqual(widget._uc2BannerActor.GetInput(), self.UC2_BANNER_MESSAGE)

                # A banner that cannot be drawn withholds the map.
                widget._sliceViewRenderer = lambda sliceWidget: None
                try:
                    withheld = widget._refreshUc2Presentation()
                finally:
                    del widget._sliceViewRenderer
                self.assertEqual(withheld["summaryStatus"], "FAIL", withheld)
                self.assertIsNone(widget._parameterNode.uc2Volume)
                vascularWidget = layoutManager.sliceWidget(widget.VASCULAR_VIEW_NAME)
                self.assertIsNone(
                    vascularWidget.sliceLogic().GetSliceCompositeNode().GetBackgroundVolumeID(),
                    "The simulated UC2 map was displayed without its banner",
                )

            genuine = self._receivedUc2Volume(
                self._validUc2Values(), RESULT_SOURCE_GENUINE_ORIGIN
            )
            report = widget._refreshUc2Presentation()
            self.assertEqual(report["summaryStatus"], "PASS", report)
            self.assertEqual(report["dataOrigin"], RESULT_SOURCE_GENUINE_ORIGIN)
            self.assertIsNone(widget._uc2BannerActor)
            self.assertNotIn("SIMULATED", widget.layerStatus(uc2Layer))

            slicer.mrmlScene.RemoveNode(genuine)
            slicer.mrmlScene.RemoveNode(simulated)
            for origin in (None, "mock"):
                with self.subTest(origin=origin):
                    unknown = self._receivedUc2Volume(self._validUc2Values(), origin)
                    report = widget._refreshUc2Presentation()
                    self.assertEqual(report["summaryStatus"], "FAIL", report)
                    self.assertEqual(report.get("provenance"), "unrecognized", report)
                    self.assertIsNone(widget._parameterNode.uc2Volume)
                    slicer.mrmlScene.RemoveNode(unknown)
        finally:
            widget._resetDemoMode()
            if layoutManager is not None:
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_invalidUc2LayerLeavesPanelBlack(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        uc2Layer = widget.LAYER_UC2
        layoutManager = self._FakeLayoutManager(self, (widget.VASCULAR_VIEW_NAME,))
        composite = layoutManager.composites[widget.VASCULAR_VIEW_NAME]

        missing = widget._refreshUc2Presentation(layoutManager=layoutManager)
        self.assertEqual(missing["summaryStatus"], "WARN", missing)
        self.assertIn("waiting", widget.layerStatus(uc2Layer).lower())
        self.assertIsNone(composite.GetBackgroundVolumeID())

        source = self._receivedUc2Volume(self._validUc2Values(), RESULT_SOURCE_GENUINE_ORIGIN)
        self.assertEqual(
            widget._refreshUc2Presentation(layoutManager=layoutManager)["summaryStatus"],
            "PASS",
        )
        self.assertIsNotNone(composite.GetBackgroundVolumeID())

        for values in (
            np.zeros((1, 2, 2), dtype=np.uint8),
            np.zeros((1, 2, 2, 3), dtype=np.float32),
            np.zeros((1, 2, 2, 4), dtype=np.uint8),
        ):
            with self.subTest(shape=values.shape, dtype=str(values.dtype)):
                slicer.mrmlScene.RemoveNode(source)
                source = self._receivedUc2Volume(values, RESULT_SOURCE_GENUINE_ORIGIN)
                report = widget._refreshUc2Presentation(layoutManager=layoutManager)
                self.assertEqual(report["summaryStatus"], "FAIL", report)
                self.assertIsNone(widget._parameterNode.uc2Volume)
                self.assertIn("invalid", widget.layerStatus(uc2Layer).lower())
                self.assertIsNone(composite.GetBackgroundVolumeID())
                self.assertIsNone(composite.GetForegroundVolumeID())

    def test_connectLinksStartsAndStopsEveryLink(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        self.assertEqual(set(parameterModule.CONNECTOR_ROLES), set(self.LINK_PORTS))
        connectors = {
            role: widget.logic.getOrCreateConnector(
                role, connectorFactory=lambda role: self._FakeObservableConnector()
            )
            for role in self.LINK_PORTS
        }
        button = widget.ui.connectLinksButton

        widget._onConnectLinksToggled(True)
        for role, connector in connectors.items():
            with self.subTest(role=role, step="connect"):
                self.assertEqual(connector.client, (IGTL_HOST, self.LINK_PORTS[role]))
                self.assertEqual(connector.startCount, 1)
                label = getattr(widget.ui, self.LINK_STATE_LABELS[role])
                self.assertEqual(label.text, CONNECTION_CONNECTING)
        self.assertTrue(button.checked)

        widget._onConnectLinksToggled(False)
        for role, connector in connectors.items():
            with self.subTest(role=role, step="disconnect"):
                self.assertEqual(connector.stopCount, 1)
                self.assertIsNone(widget.logic.connectorNode(role))
                label = getattr(widget.ui, self.LINK_STATE_LABELS[role])
                self.assertEqual(label.text, CONNECTION_DISCONNECTED)
        self.assertFalse(button.checked)

    def test_captureDisabledWithoutControlLink(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        button = widget.ui.captureButton
        statusLabel = widget.ui.captureStatusLabel

        widget._refreshCaptureControls()
        self.assertFalse(button.enabled)
        self.assertIn("18950", statusLabel.text)

        connector = self._fakeControlConnector(widget, SLIAFlowLogic.CONNECTOR_STATE_OFF)
        for state in (
            SLIAFlowLogic.CONNECTOR_STATE_OFF,
            SLIAFlowLogic.CONNECTOR_STATE_WAIT_CONNECTION,
        ):
            with self.subTest(state=state):
                connector.state = state
                widget._refreshCaptureControls()
                self.assertFalse(button.enabled)
                self.assertIn("18950", statusLabel.text)
                widget._onCaptureClicked()
                self.assertEqual(connector.pushed, [], "A trigger went out over a link that is down")

        connector.state = SLIAFlowLogic.CONNECTOR_STATE_CONNECTED
        widget._refreshCaptureControls()
        self.assertTrue(button.enabled)
        self.assertNotIn("18950", statusLabel.text)

    def test_capturePressSendsOneTrigger(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        connector = self._fakeControlConnector(
            widget, SLIAFlowLogic.CONNECTOR_STATE_CONNECTED
        )

        widget._onCaptureClicked()
        widget._onCaptureClicked()

        self.assertEqual(len(connector.pushed), 2, connector.pushed)
        triggerNode = connector.pushed[0][0]
        self.assertIs(connector.pushed[1][0], triggerNode)
        self.assertTrue(triggerNode.IsA("vtkMRMLTextNode"))
        # Device name and command from the control-channel table in
        # tools/simulators/README.md.
        self.assertEqual(triggerNode.GetName(), "CaptureTrigger")
        self.assertEqual([text for _, text, _ in connector.pushed], ["CAPTURE", "CAPTURE"])
        self.assertEqual(connector.registered, [(triggerNode, "STRING")])
        self.assertFalse(triggerNode.GetSaveWithScene())
        self.assertEqual(
            connector.pushed[0][2],
            connector.pushed[1][2],
            "A press modified the trigger node, which a real connector sends again",
        )

    def test_captureStateReflectsStandInAnswers(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        self._fakeControlConnector(widget, SLIAFlowLogic.CONNECTOR_STATE_CONNECTED)
        statusLabel = widget.ui.captureStatusLabel

        def receive(deviceName, text):
            node = slicer.mrmlScene.GetFirstNodeByName(deviceName)
            if node is None:
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", deviceName)
            node.SetText(text)

        # The wording is the stand-in's, from tools/simulators/README.md.
        for deviceName, text, word in (
            ("CaptureStatus", "IDLE", "idle"),
            ("CaptureStatus", "CAPTURING capture=3 case=004-02 delay=5.9", "capturing"),
            ("CaptureStatus", "READY capture=3 case=004-02 folder=C:\\cases\\004 02", "ready"),
            ("CaptureReply", "IGNORED capture 3 already in progress", "ignored"),
            ("CaptureReply", "REFUSED unknown command CAPTUR", "refused"),
        ):
            with self.subTest(text=text):
                receive(deviceName, text)
                widget._refreshCaptureState()
                self.assertIn(word, statusLabel.text.lower())
                self.assertIn(text, statusLabel.text)

    def test_connectorEventsSurviveVtkStringDispatch(self) -> None:
        """A connector event dispatched the way VTK dispatches it still routes.

        VTK calls a Python observer with the event as a *string*
        (`vtkPythonCommand.cxx`: `Py_BuildValue("(Ns)", obj2, eventname)`), and
        `vtkCommand::GetStringFromEventId` has no case for the connector's
        custom ids, so every one of them arrives as `"NoEvent"`. An event id
        therefore cannot be recovered from the argument, and one callback
        shared by six events cannot tell them apart. Each observed event gets
        its own callback instead.

        This is the manual step 7 defect: with the loss branch unreachable, a
        stopped producer left the labels reading `displaying` indefinitely.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        connector = widget.logic.getOrCreateConnector(
            CONNECTOR_UC1, connectorFactory=lambda role: self._FakeObservableConnector()
        )
        connector.state = widget.logic.CONNECTOR_STATE_CONNECTED
        widget._observeConnector(CONNECTOR_UC1, connector)

        callbacks = {event: callback for event, callback in connector.observers.values()}
        self.assertIn(widget.logic.CONNECTOR_DISCONNECTED_EVENT, callbacks)
        self.assertEqual(
            len({id(callback) for callback in callbacks.values()}),
            len(callbacks),
            "Six events share one callback, so the event that fired is unknowable",
        )

        # A client that loses its peer keeps retrying, so the connector reports
        # WaitConnection rather than Off.
        connector.state = widget.logic.CONNECTOR_STATE_WAIT_CONNECTION
        losses = []
        originalHandler = widget._onLinkDisconnected

        def recordLoss(role):
            losses.append(role)
            return originalHandler(role)

        widget._onLinkDisconnected = recordLoss
        try:
            callbacks[widget.logic.CONNECTOR_DISCONNECTED_EVENT](connector, "NoEvent")
        finally:
            widget._onLinkDisconnected = originalHandler

        self.assertEqual(
            losses,
            [CONNECTOR_UC1],
            "A disconnection dispatched by VTK never reached the loss handler",
        )
        self.assertEqual(widget.connectionState(CONNECTOR_UC1), CONNECTION_CONNECTING)

    def test_captureTriggerDeclaresItsWireEncoding(self) -> None:
        """The trigger states an IANA encoding the receiver can actually decode.

        `igtlioStringConverter::toIGTL` copies `vtkMRMLTextNode`'s encoding
        number straight into the IGTL STRING encoding field, which carries an
        IANA MIB number. The VTK default is `VTK_ENCODING_US_ASCII`, and that
        constant is 1, not the IANA 3, so the value on the wire meant nothing:
        in manual step 4 the stand-in refused the trigger with "Unsupported
        encoding" and no capture ever started.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        connector = self._fakeControlConnector(
            widget, SLIAFlowLogic.CONNECTOR_STATE_CONNECTED
        )

        widget._onCaptureClicked()

        self.assertEqual(parameterModule.IGTL_ENCODING_US_ASCII, 3)
        triggerNode = connector.pushed[0][0]
        self.assertEqual(
            triggerNode.GetEncoding(),
            parameterModule.IGTL_ENCODING_US_ASCII,
            "The trigger went out under an encoding number the receiver rejects",
        )
        # Set before the node was ever registered, so a press still only pushes.
        self.assertEqual(connector.registered, [(triggerNode, "STRING")])

    def test_liveViewPanelSaysWhatItIsWaitingFor(self) -> None:
        """The LiveView panel is never black without saying why.

        Manual step 2: every other panel carried its reason in the viewport,
        and LiveView carried its waiting state only in the module's status
        line, where a panel that is black because something broke looks exactly
        the same.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        layoutManager = self._FakeLayoutManager(self, widget.VIEW_NAMES)

        widget._clearLiveView(layoutManager=layoutManager)
        waiting = widget.panelMessage(widget.LIVE_VIEW_NAME)
        self.assertTrue(waiting, "The LiveView panel is black with nothing written on it")
        self.assertIn("liveview", waiting.lower())

        # A frame takes the panel, so the waiting text goes with it.
        frame = np.zeros((1, 4, 6, 3), dtype=np.uint8)
        frame[..., 1] = 200
        widget._displayCameraFrame(frame, layoutManager=layoutManager)
        self.assertEqual(widget.panelMessage(widget.LIVE_VIEW_NAME), "")

    def test_bandBrowserReportsWavelength(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        wavelengthKey = WIRE_ATTRIBUTE_PREFIX + "SLIAFlow.WavelengthsNm"
        # (bands, lines, samples), as HSCube travels; a test placeholder.
        cube = np.arange(3 * 2 * 4, dtype=np.uint16).reshape(3, 2, 4)
        cubeNode = self._createReceivedVolume(
            "HSCube",
            cube,
            {
                RESULT_SOURCE_DEVICE_ATTRIBUTE: "HSCube",
                RESULT_SOURCE_ORIGIN_ATTRIBUTE: RESULT_SOURCE_SIMULATED_ORIGIN,
                RESULT_SOURCE_DETAIL_ATTRIBUTE: "acquisition stand-in, recorded HSI case test (simulated acquisition)",
                "SLIAFlow.WavelengthsNm": "440,445,450",
            },
        )

        report = widget._refreshCubePresentation()
        self.assertEqual(report["summaryStatus"], "PASS", report)
        slider = widget.ui.bandSlider
        self.assertEqual((slider.minimum, slider.maximum), (0, 2))
        for band, wavelength in ((2, "450"), (0, "440"), (1, "445")):
            with self.subTest(band=band):
                widget._setCubeBand(band)
                label = widget.ui.bandValueLabel.text
                self.assertIn(f"Band {band}", label)
                self.assertIn(f"{wavelength} nm", label)
        np.testing.assert_array_equal(slicer.util.arrayFromVolume(cubeNode), cube)

        # A wavelength that cannot be read is never guessed or stretched to fit.
        for badList in ("440,445", "440,abc,450", None):
            with self.subTest(wavelengths=badList):
                if badList is None:
                    cubeNode.RemoveAttribute(wavelengthKey)
                else:
                    cubeNode.SetAttribute(wavelengthKey, badList)
                report = widget._refreshCubePresentation()
                widget._setCubeBand(2)
                label = widget.ui.bandValueLabel.text
                self.assertIn("Band 2", label)
                self.assertNotIn("nm", label)
                self.assertIn("wavelength", report["summaryMessage"].lower())

    def test_operatorControlsHaveStatedReasons(self) -> None:
        representation, _ = self._moduleRepresentationAndWidget()
        operatorSection = slicer.util.findChild(representation, "operatorGroupBox")
        developerSection = slicer.util.findChild(representation, "developerCollapsibleButton")

        interactive = []
        for className in (
            "QPushButton",
            "QComboBox",
            "QSpinBox",
            "QCheckBox",
            "QSlider",
            "QTableWidget",
        ):
            interactive.extend(slicer.util.findChildren(operatorSection, className=className))
        # Thirteen controls before SLIA-022, counted from SLIAFlow.ui at a45e5ac.
        self.assertEqual(
            sorted(control.objectName for control in interactive),
            sorted(
                (
                    "liveSourceSelector",
                    "startButton",
                    "stopButton",
                    "connectLinksButton",
                    "captureButton",
                    "demoModeCheckBox",
                    "layerTable",
                    "layerOpacitySlider",
                    "bandSlider",
                )
            ),
        )
        for control in interactive:
            with self.subTest(control=control.objectName):
                self.assertTrue(control.toolTip.strip(), "An operator control gives no reason")

        for name in (
            "cameraIndexSpinBox",
            "installCameraSupportButton",
            "resultMapSelector",
            "resultClassSpinBox",
            "refreshResultButton",
        ):
            with self.subTest(developerControl=name):
                self.assertIsNotNone(slicer.util.findChild(developerSection, name))
