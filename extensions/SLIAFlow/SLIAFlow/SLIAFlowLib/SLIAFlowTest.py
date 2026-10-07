import contextlib
import datetime
import importlib
import io
import os
import time
import types
import unittest
from pathlib import Path

import numpy as np
import slicer
import vtk
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleTest

from .SLIAFlowLogic import SLIAFlowLogic

# The package re-exports the parameter-node class under the same name as its
# module, so `from . import SLIAFlowParameterNode` would bind the class.
parameterModule = importlib.import_module(".SLIAFlowParameterNode", __package__)


# The command-line runner, scripts/development/run-slicer-tests.ps1, calls
# runCommandLineTests from its --python-code. The fragments exist only in that
# code, so Reload and Test and a normal session can never see a selection.


def selectTestNames(testNames, fragments) -> list:
    """Return the names that contain any fragment, in the order given.

    Raises ValueError naming every fragment that matches no name, so a typo
    fails the run instead of giving a green run of fewer tests.
    """
    if not fragments or any(not fragment for fragment in fragments):
        raise ValueError(f"The test selection has an empty fragment: {list(fragments)!r}.")
    unmatched = [
        fragment for fragment in fragments if not any(fragment in name for name in testNames)
    ]
    if unmatched:
        raise ValueError(
            "These test-name fragments match no test: "
            + ", ".join(repr(fragment) for fragment in unmatched)
            + "."
        )
    return [name for name in testNames if any(fragment in name for fragment in fragments)]


def commandLineSuite(module, testCaseClass, fragments):
    """Return the suite to run and, for a partial run, the line that says so.

    Without fragments this loads the module as slicer.testing.runUnitTest does,
    so a full run counts exactly what it counted before.
    """
    loader = unittest.TestLoader()
    if not fragments:
        return loader.loadTestsFromModule(module), None
    allNames = loader.getTestCaseNames(testCaseClass)
    names = selectTestNames(allNames, fragments)
    partialRun = (
        f"Partial run: {len(names)} of {len(allNames)} {testCaseClass.__name__} tests "
        f"matching {', '.join(fragments)}"
    )
    return unittest.TestSuite(testCaseClass(name) for name in names), partialRun


class LiveTextTestResult(unittest.TextTestResult):
    """Name each test on a complete line before its body runs.

    unittest finishes its own line for a test only after the test, and the
    runner reads Slicer's output line by line, so a hung test would otherwise
    stay unnamed.
    """

    def startTest(self, test) -> None:
        self.stream.writeln(f"Started: {test.id()}")
        self.stream.flush()
        super().startTest(test)


def runCommandLineTests(module, testCaseClass, fragments) -> bool:
    """Run the module's tests, or the selected ones, and return whether all passed."""
    suite, partialRun = commandLineSuite(module, testCaseClass, fragments)
    if partialRun:
        print(partialRun, flush=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=LiveTextTestResult).run(suite)
    if partialRun:
        print(partialRun, flush=True)
    return result.wasSuccessful()


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
        "_cameraSupportAvailable",
        "_cameraRestartRequired",
    )
    EVENT_LOOP_TIMEOUT_SEC = 2.0

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()
        self._widgetStateBackup = None
        widget = self._moduleWidgetOrNone()
        if widget is None:
            return
        backup = {name: getattr(widget, name) for name in self.WIDGET_STATE_FIELDS}
        backup["status"] = widget.ui.statusLabel.text
        self._widgetStateBackup = backup

    def tearDown(self) -> None:
        super().tearDown()
        backup = getattr(self, "_widgetStateBackup", None)
        widget = self._moduleWidgetOrNone()
        if backup is None or widget is None:
            return
        for name in self.WIDGET_STATE_FIELDS:
            setattr(widget, name, backup[name])
        widget._configureResultControls()
        widget._updateResultStatus()
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
        self.assertEqual(parameters.cameraIndex, 0)
        # SLIA-027: after a run the Tumour Delineation panel shows imageRGB.bmp,
        # the majority-voting map. The module's parameter node outlives setUp's
        # scene clear and carries whatever an earlier test wrote, so the
        # declared default is read from a freshly wrapped node.
        freshParameters = parameterModule.SLIAFlowParameterNode(
            slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
        )
        self.assertEqual(freshParameters.resultOutput, "imageRGB.bmp")

        cameraIndex = slicer.util.findChild(representation, "cameraIndexSpinBox")
        startButton = slicer.util.findChild(representation, "startButton")
        stopButton = slicer.util.findChild(representation, "stopButton")
        captureButton = slicer.util.findChild(representation, "captureButton")
        installButton = slicer.util.findChild(
            representation, "installCameraSupportButton"
        )
        resultOutput = slicer.util.findChild(representation, "resultOutputSelector")
        status = slicer.util.findChild(representation, "statusLabel")

        for control in (cameraIndex, startButton, stopButton, captureButton,
                        installButton, resultOutput, status):
            self.assertIsNotNone(control)

        self.assertEqual(resultOutput.isEnabled(), widget._presentationActive)
        self.assertEqual(resultOutput.currentText, parameters.resultOutput)

        cameraSupportAvailable = widget.logic.openCVAvailable()
        self.assertEqual(cameraIndex.isEnabled(), cameraSupportAvailable)
        self.assertEqual(startButton.isEnabled(), cameraSupportAvailable)
        self.assertFalse(stopButton.isEnabled())
        self.assertFalse(captureButton.isEnabled())
        self.assertEqual(installButton.isEnabled(), not cameraSupportAvailable)
        self.assertEqual(cameraIndex.value, 0)
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

    def test_reloadWhileSelectedKeepsThePresentation(self) -> None:
        """Reload with SLIAFlow selected leaves the six-panel presentation on.

        Slicer's Reload calls cleanup() on the old widget and setup() on the
        new one, but not enter(), although the module stays entered
        (`slicer.util.reloadScriptedModule`). The developer workflow reloads
        with the module selected, so the new widget has to take over.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None or slicer.util.mainWindow() is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousModule = slicer.util.selectedModule() or "Data"
        previousLayout = int(layoutNode.GetViewArrangement())
        try:
            slicer.util.selectModule("SLIAFlow")
            widget = self._moduleRepresentationAndWidget()[1]
            self.assertTrue(widget._presentationActive)

            slicer.util.reloadScriptedModule("SLIAFlow")
            representation, reloaded = self._moduleRepresentationAndWidget()
            self.assertIsNot(reloaded, widget)
            self.assertTrue(representation.isEntered)
            self.assertFalse(widget._presentationActive)
            self.assertTrue(reloaded._presentationActive,
                            "The reloaded widget left the presentation off")
            self.assertEqual(int(layoutNode.GetViewArrangement()), reloaded.CUSTOM_LAYOUT_ID)
        finally:
            slicer.util.selectModule(previousModule)
            if previousModule != "SLIAFlow" and \
                    int(layoutNode.GetViewArrangement()) != previousLayout:
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

        decoy = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVectorVolumeNode", "Shared volume name"
        )
        liveVolume = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVectorVolumeNode", "Shared volume name"
        )
        parameters.liveVolume = liveVolume

        self.assertNotEqual(liveVolume.GetID(), decoy.GetID())
        parameterNode = parameters.parameterNode
        self.assertEqual(
            parameterNode.GetNodeReferenceID("liveVolume"), liveVolume.GetID()
        )
        self.assertEqual(parameters.liveVolume.GetID(), liveVolume.GetID())

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

    @staticmethod
    def _commandLineProbeModule():
        # A stand-in for the SLIAFlow module namespace: the test class the
        # runner selects from, and a second TestCase the loader also finds.
        module = types.ModuleType("SLIAFlowCommandLineProbe")

        class ProbeTest(unittest.TestCase):
            def test_aCube(self) -> None:
                pass

            def test_bLink(self) -> None:
                pass

        class OtherProbe(unittest.TestCase):
            def test_cCube(self) -> None:
                pass

        module.ProbeTest = ProbeTest
        module.OtherProbe = OtherProbe
        return module

    @staticmethod
    def _testMethodNames(suite) -> list:
        names = []
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                names += SLIAFlowTest._testMethodNames(test)
            else:
                names.append(test._testMethodName)
        return names

    def test_commandLineSelectionKeepsMatchingTestsInOrder(self) -> None:
        # run-slicer-tests.ps1 -Test: a name is kept when it contains any
        # fragment, case-sensitively, once, in the order it was given.
        names = ["test_aCube", "test_bLink", "test_cCubeLink", "test_dcube"]
        self.assertEqual(
            selectTestNames(names, ["Cube", "Link"]),
            ["test_aCube", "test_bLink", "test_cCubeLink"],
        )

    def test_commandLineSelectionNamesFragmentsMatchingNothing(self) -> None:
        # A typo must fail the run, never give a green run of fewer tests.
        names = ["test_aCube", "test_bLink"]
        with self.assertRaises(ValueError) as raised:
            selectTestNames(names, ["noSuch", "Cube", "cube"])
        message = str(raised.exception)
        self.assertIn("'noSuch'", message)
        self.assertIn("'cube'", message)
        self.assertNotIn("'Cube'", message)

        for fragments in ([], [""]):
            with self.subTest(fragments=fragments), self.assertRaises(ValueError):
                selectTestNames(names, fragments)

    def test_commandLineSuiteWithoutSelectionLoadsTheWholeModule(self) -> None:
        # Without -Test the runner must run what slicer.testing.runUnitTest
        # ran: every TestCase the loader finds in the module namespace.
        module = self._commandLineProbeModule()
        suite, partialRun = commandLineSuite(module, module.ProbeTest, [])
        self.assertEqual(
            sorted(self._testMethodNames(suite)), ["test_aCube", "test_bLink", "test_cCube"]
        )
        self.assertIsNone(partialRun)

    def test_commandLineSuiteSelectsOnlyFromTheTestClass(self) -> None:
        # OtherProbe stands for the imported ScriptedLoadableModuleTest base,
        # which a selection must not pull in.
        module = self._commandLineProbeModule()
        suite, partialRun = commandLineSuite(module, module.ProbeTest, ["Cube"])
        self.assertEqual(self._testMethodNames(suite), ["test_aCube"])
        self.assertEqual(partialRun, "Partial run: 1 of 2 ProbeTest tests matching Cube")

    def test_commandLineRunNamesEachTestBeforeItRuns(self) -> None:
        # unittest names a test on a line it finishes only after the test, and
        # the runner reads whole lines, so a hung test would stay unnamed.
        stream = io.StringIO()
        seen = {}

        class StartProbe(unittest.TestCase):
            def test_probe(self) -> None:
                seen["output"] = stream.getvalue()

        probe = StartProbe("test_probe")
        unittest.TextTestRunner(
            stream=stream, verbosity=2, resultclass=LiveTextTestResult
        ).run(probe)
        self.assertIn(f"Started: {probe.id()}\n", seen["output"])

    def test_reservedPanelIsBlackWithStatedReason(self) -> None:
        """A panel with nothing to show is black and says why.

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
            for viewName, fragments in (
                (widget.STEREO_VIEW_NAME, ("waiting", "stereoscopic")),
                (widget.STO2_VIEW_NAME, ("waiting", "sto2")),
                # The cube panel is black until a capture chooses a case.
                (widget.CUBE_VIEW_NAME, ("waiting", "hyperspectral cube")),
                (widget.VASCULAR_VIEW_NAME, ("waiting", "enhanced vascularization")),
            ):
                with self.subTest(view=viewName):
                    sliceWidget = layoutManager.sliceWidget(viewName)
                    self.assertIsNotNone(sliceWidget)
                    compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
                    self.assertIsNone(compositeNode.GetBackgroundVolumeID())
                    self.assertIsNone(compositeNode.GetForegroundVolumeID())
                    self.assertIsNone(compositeNode.GetLabelVolumeID())

                    actor = widget._panelAnnotationActors.get(viewName)
                    self.assertIsNotNone(actor, "The panel carries no text")
                    sliceWidget.mrmlSliceNode().Modified()
                    self._waitForUi(
                        lambda sliceWidget=sliceWidget, actor=actor: bool(
                            widget._sliceViewRenderer(sliceWidget).HasViewProp(actor)
                        ),
                        f"the panel reason to reach {viewName}",
                    )
                    reason = (actor.GetInput() or "").lower()
                    for fragment in fragments:
                        self.assertIn(fragment, reason)
        finally:
            widget._deactivatePresentation(restore=True)
            if int(layoutNode.GetViewArrangement()) != previousLayout:
                layoutManager.setLayout(previousLayout)

    # ----------------------------------------------------------------------
    # SLIA-026: waiting links say why, and the laptop camera is upright
    # ----------------------------------------------------------------------

    UPRIGHT_LIVE_DIRECTIONS = ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0))

    @staticmethod
    def _ijkToRasDirections(volumeNode):
        matrix = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASDirectionMatrix(matrix)
        return tuple(
            tuple(matrix.GetElement(row, column) for column in range(3))
            for row in range(3)
        )

    def test_liveVolumeIsDisplayedUpright(self) -> None:
        """The camera volume carries the geometry the OpenIGTLink stream carries.

        OpenCV row 0 is the top of the picture. With identity directions an
        Axial slice draws i right to left and j bottom to top, which shows the
        frame rotated 180 degrees. diag(-1, -1, 1) draws both the right way.
        """
        logic = SLIAFlowLogic()
        parameterNode = logic.getParameterNode()

        created = logic.getOrCreateLiveVolume(parameterNode)
        self.assertEqual(self._ijkToRasDirections(created), self.UPRIGHT_LIVE_DIRECTIONS)

        # A node left in the scene by an earlier version is corrected on reuse.
        created.SetIJKToRASDirections(1, 0, 0, 0, 1, 0, 0, 0, 1)
        reused = logic.getOrCreateLiveVolume(parameterNode)
        self.assertIs(reused, created)
        self.assertEqual(self._ijkToRasDirections(reused), self.UPRIGHT_LIVE_DIRECTIONS)

        # A frame update keeps the geometry.
        frame = np.zeros((1, 4, 6, 3), dtype=np.uint8)
        slicer.util.updateVolumeFromArray(reused, frame)
        self.assertEqual(
            self._ijkToRasDirections(logic.getOrCreateLiveVolume(parameterNode)),
            self.UPRIGHT_LIVE_DIRECTIONS,
        )

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
        # SLIA-027: Start, Stop, Capture and the five-output selector. The
        # links, demo mode, layers and band browser are gone (ADR-0003).
        # SLIA-032: what the HS Cube panel shows, bands or the colour preview.
        # SLIA-036: which cube HS Cube shows and Capture uses.
        self.assertEqual(
            sorted(control.objectName for control in interactive),
            sorted(("startButton", "stopButton", "captureButton", "resultOutputSelector",
                    "cubeDisplaySelector", "cubeSourceSelector")),
        )
        for control in interactive:
            with self.subTest(control=control.objectName):
                self.assertTrue(control.toolTip.strip(), "An operator control gives no reason")

        for name in ("cameraIndexSpinBox", "installCameraSupportButton"):
            with self.subTest(developerControl=name):
                self.assertIsNotNone(slicer.util.findChild(developerSection, name))

    # ----------------------------------------------------------------------
    # SLIA-027: capture and UC1 inside Slicer (ADR-0003)
    #
    # Every image and case folder below is a test fixture that stands for no
    # imagery, written to a temporary directory the test deletes. No test reads
    # input/ or the staged UC1 build.
    # ----------------------------------------------------------------------

    # The five images the intermediate build writes and SLIAFlow shows, from the
    # snprintf formats in gpu_single_bsq/source/functions_cuda.cu and main.cu,
    # in the order this task card lists them.
    UC1_OUTPUT_FILE_NAMES = ("pca.bmp", "svm.bmp", "knn.bmp", "kmeans.bmp", "imageRGB.bmp")
    # The staged SVM model's band count and file sizes, from uc1_runner.py
    # (UC1_MODEL_BAND_COUNT, MODEL_FILE_SIZES): six binary classifiers, float32
    # weights, int32 labels.
    UC1_MODEL_BAND_COUNT = 93
    UC1_MODEL_FILE_SIZES = {
        "w_vector.bin": 93 * 6 * 4,
        "ProbA.bin": 6 * 4,
        "ProbB.bin": 6 * 4,
        "rho.bin": 6 * 4,
        "label.bin": 4 * 4,
    }
    # SLIA-027: the run timeout and the wording.
    UC1_RUN_TIMEOUT_SEC = 60
    STALE_RESULT_LINE = "PREVIOUS RESULT - not from the current capture"
    STALE_STATUS_FRAGMENT = "not from the current capture"
    # ADR-0004 decision 7: the UC1 pipeline's producer name, then the cube's own
    # detail, in the wording the SLIA-032 card fixes for the cube.
    UC1_RESULT_DETAIL = ("real UC1 pipeline, recorded IUMA LCTF capture 002-04, calibrated by "
                         "IUMA (simulated acquisition)")
    RESULT_STATUS_FORMAT = "Recorded cube {case} - simulated acquisition"
    # ADR-0004 decision 5: results on the LCTF cube are behavioural only.
    NOT_VALIDATED_FRAGMENT = "not validated"
    SNAPSHOT_NAME_PATTERN = r"^output_laptop_camera_\d{8}-\d{6}(-\d+)?\.png$"

    @staticmethod
    def _helperModule(name: str):
        """Import a SLIA-027 helper module lazily.

        A module-level import would stop the whole test class from loading if
        the module were missing; this way each test fails on its own.
        """
        return importlib.import_module(f".{name}", __package__)

    def _writeFixtureGroundTruth(self, folder: Path, *, samples=4, lines=3, omit=(),
                                 groundTruthOverrides=None, groundTruthLabels=None) -> Path:
        """Write a placeholder gtMap pair beside a cube, laid out like a recorded case's."""
        folder.mkdir(parents=True, exist_ok=True)
        classes = self._helperModule("SLIAFlowCube").GROUND_TRUTH_CLASSES
        groundTruth = "ENVI\ndescription = {test fixture}\n"
        if "gtMap.hdr" not in omit:
            header = dict(samples=samples, lines=lines, bands=1, dataType="12",
                          interleave="bil", byteOrder="0", headerOffset="0")
            header.update(groundTruthOverrides or {})
            groundTruth += "".join(f"{key} = {value}\n" for key, value in (
                ("samples", header["samples"]), ("lines", header["lines"]),
                ("bands", header["bands"]), ("data type", header["dataType"]),
                ("byte order", header["byteOrder"]),
                ("interleave", header["interleave"]),
                ("header offset", header["headerOffset"]),
            ))
            groundTruth += "".join(f"Class ID ({classId}) = {className}\n"
                                   for classId, className, _colour in classes)
            (folder / "gtMap.hdr").write_text(groundTruth, encoding="ascii")
        if "gtMap" not in omit:
            if groundTruthLabels is None:
                # One pixel of each class and the rest unlabelled, which is
                # the shape of a recorded case: across the 61 cases of the
                # HSI Human Brain Database, 0.0% to 16.2% of pixels carry a class.
                labels = np.zeros(lines * samples, dtype="<u2")
                for index, (classId, _name, _colour) in enumerate(classes):
                    if index < labels.size:
                        labels[index] = classId
            else:
                labels = np.asarray(groundTruthLabels, dtype="<u2")
            (folder / "gtMap").write_bytes(labels.tobytes())
        return folder

    # The calibrated LCTF cube (SLIA-032). The layout, names and wavelength grid
    # are those of IUMA's LCTF_Calibrated_Cube_Single.hdr in input/002-04: ENVI
    # data type 4, bsq, byte order 0, 460-1000 nm in 5 nm steps.
    CALIBRATED_CUBE_NAME = "002-04"
    CALIBRATED_CUBE_STEM = "LCTF_Calibrated_Cube_Single"
    LCTF_WAVELENGTHS_NM = tuple(range(460, 1001, 5))
    # ADR-0004 decision 7, in the wording the SLIA-032 card fixes.
    CALIBRATED_DETAIL = (
        "recorded IUMA LCTF capture 002-04, calibrated by IUMA (simulated acquisition)"
    )
    # The SLIA-032 card: the bands nearest 650, 550 and 470 nm, as R, G and B,
    # on one fixed scale where reflectance 1.0 is full brightness.
    PREVIEW_WAVELENGTHS_NM = (650, 550, 470)

    def _writeFixtureCalibratedCube(self, folder: Path, *, samples=4, lines=3,
                                    wavelengths=LCTF_WAVELENGTHS_NM, bands=None, dataType=4,
                                    interleave="bsq", byteOrder=0, headerOffset=0,
                                    units="Nanometers", dataBytes=None, dataSuffix=".dat"):
        """Write a placeholder float32 cube laid out like IUMA's calibrated cube.

        Returns the header path and the values written, as (bands, lines,
        samples) float32. Every voxel differs, and some exceed 1.0, as the real
        cube's clipped [0, 1.5] range does. The values stand for no imagery.
        """
        folder.mkdir(parents=True, exist_ok=True)
        if bands is None:
            bands = len(self.LCTF_WAVELENGTHS_NM) if wavelengths is None else len(wavelengths)
        entries = [
            "ENVI",
            f"bands = {bands}",
            f"data type = {dataType}",
            f"interleave = {interleave}",
            f"header offset = {headerOffset}",
        ]
        if units is not None:
            entries.append(f"wavelength units = {units}")
        entries.append(f"byte order = {byteOrder}")
        if wavelengths is not None:
            # Six values to a line and the brace closed on the last one, as the
            # real header writes it.
            rows = [", ".join(f"{value:>4}" for value in wavelengths[index:index + 6])
                    for index in range(0, len(wavelengths), 6)]
            entries.append("wavelength = {" + ", \n".join(rows) + "}")
        entries += [f"lines = {lines}", f"samples = {samples}"]
        header = folder / f"{self.CALIBRATED_CUBE_STEM}.hdr"
        header.write_text("\n".join(entries) + "\n", encoding="ascii")

        count = bands * lines * samples
        values = ((np.arange(count, dtype=np.int64) % 97) / 64.0).astype(np.float32)
        values = values.reshape(bands, lines, samples)
        if dataSuffix is not None:
            data = values.astype("<f4").tobytes()
            if dataBytes is not None:
                data = (data + b"\0" * dataBytes)[:dataBytes]
            (folder / f"{self.CALIBRATED_CUBE_STEM}{dataSuffix}").write_bytes(data)
        return header, values

    # SLIA-033: where SLIAFlow writes the cube UC1 reads, under the staged build.
    UC1_INPUT_RELATIVE_PATH = Path("build") / "uc1" / "UC1" / "input"

    def _makeFixtureRepository(self, root: Path, *, cube=True, groundTruth=False) -> dict:
        """A repository-shaped placeholder tree: markers, the calibrated cube, staged build.

        The cube lies where the configured one does, input/002-04. With
        `groundTruth`, a gtMap pair lies beside it; `cube=False` writes no cube.
        """
        (root / "AGENTS.md").write_text("test fixture\n", encoding="ascii")
        (root / "extensions" / "SLIAFlow").mkdir(parents=True)
        cubeFolder = root / "input" / self.CALIBRATED_CUBE_NAME
        calibratedHeader = cubeFolder / f"{self.CALIBRATED_CUBE_STEM}.hdr"
        calibratedValues = None
        if cube:
            calibratedHeader, calibratedValues = self._writeFixtureCalibratedCube(cubeFolder)
        if groundTruth:
            self._writeFixtureGroundTruth(cubeFolder)
        buildRoot = root / "build" / "uc1" / "UC1"
        source = buildRoot / "gpu_single_bsq" / "source"
        (source / "output" / "rgb").mkdir(parents=True)
        (source / "stratum.opt.intermediate.exe").write_bytes(b"test fixture, never run")
        model = buildRoot / "svm_model"
        model.mkdir(parents=True)
        for fileName, size in self.UC1_MODEL_FILE_SIZES.items():
            (model / fileName).write_bytes(b"\0" * size)
        return {
            "root": root,
            "cubeFolder": cubeFolder,
            "buildRoot": buildRoot,
            "source": source,
            "executable": source / "stratum.opt.intermediate.exe",
            "lock": buildRoot / ".uc1-runner.lock",
            "captures": root / "workspace" / "captures",
            "calibratedHeader": calibratedHeader,
            "calibratedValues": calibratedValues,
            "runFolder": root / self.UC1_INPUT_RELATIVE_PATH / self.CALIBRATED_CUBE_NAME,
        }

    @staticmethod
    def _uc1BmpBytes(rgbTopFirst, *, padded=True) -> bytes:
        """Transcribe BitmapWriter.cpp writeBMP, header quirk included.

        writeBMP stores bfSize = 54 + 3 * w * h, which omits the row padding it
        then writes, and leaves every other info-header field but size, width,
        height, planes and bit count at zero. `padded=False` omits the padding,
        as saveBIPtoBMP does.
        """
        import struct

        rgb = np.asarray(rgbTopFirst, dtype=np.uint8)
        lines, samples = rgb.shape[:2]
        fileHeader = struct.pack("<2sIHHI", b"BM", 54 + 3 * samples * lines, 0, 0, 54)
        infoHeader = struct.pack("<IiiHHIIiiII", 40, samples, lines, 1, 24, 0, 0, 0, 0, 0, 0)
        padding = b"\0" * (((4 - (samples * 3) % 4) % 4) if padded else 0)
        rows = bytearray()
        for line in range(lines - 1, -1, -1):
            rows.extend(rgb[line, :, ::-1].tobytes())
            rows.extend(padding)
        return fileHeader + infoHeader + bytes(rows)

    @staticmethod
    def _fixtureImage(lines=3, samples=4, seed=0):
        # Distinct values per pixel and channel, so a flip or a channel swap
        # cannot go unnoticed. A test placeholder, not an algorithm output.
        values = (np.arange(lines * samples * 3, dtype=np.int64).reshape(lines, samples, 3) * 7
                  + seed * 13) % 256
        return values.astype(np.uint8)

    def _writeUc1Outputs(self, outputDirectory: Path, *, lines=3, samples=4, seed=0,
                         overrides=None) -> dict:
        outputDirectory.mkdir(parents=True, exist_ok=True)
        images = {}
        overrides = overrides or {}
        for index, fileName in enumerate(self.UC1_OUTPUT_FILE_NAMES):
            image = self._fixtureImage(lines, samples, seed + index)
            images[fileName] = image
            data = overrides.get(fileName, self._uc1BmpBytes(image))
            if data is not None:
                (outputDirectory / fileName).write_bytes(data)
        return images

    class _FakeUc1Process:
        """Records what a QProcess was asked to do, and plays back its signals."""

        NormalExit = 0
        CrashExit = 1
        FailedToStart = 0

        def __init__(self) -> None:
            self.slots = {}
            self.program = None
            self.arguments = None
            self.workingDirectory = None
            self.started = False
            self.killed = False
            self.waitedMs = None
            self.deleted = False
            self._stdout = b""
            self._stderr = b""
            self._exitCode = 0
            self._exitStatus = self.NormalExit
            self._running = False

        def connect(self, signal, slot) -> None:
            self.slots[signal] = slot

        def disconnect(self, signal, slot=None) -> None:
            self.slots.pop(signal, None)

        def setWorkingDirectory(self, directory) -> None:
            self.workingDirectory = directory

        def setProcessChannelMode(self, mode) -> None:
            pass

        def start(self, program, arguments) -> None:
            self.program = program
            self.arguments = list(arguments)
            self.started = True
            self._running = True

        def state(self) -> int:
            return 2 if self._running else 0

        def kill(self) -> None:
            self.killed = True
            self._running = False

        def waitForFinished(self, milliseconds=30000) -> bool:
            self.waitedMs = milliseconds
            return True

        def readAllStandardOutput(self):
            data, self._stdout = self._stdout, b""
            return data

        def readAllStandardError(self):
            data, self._stderr = self._stderr, b""
            return data

        def exitCode(self) -> int:
            return self._exitCode

        def exitStatus(self) -> int:
            return self._exitStatus

        def deleteLater(self) -> None:
            self.deleted = True

        def emitOutput(self, stdout=b"", stderr=b"") -> None:
            self._stdout += stdout
            self._stderr += stderr
            for signal in ("readyReadStandardOutput()", "readyReadStandardError()"):
                slot = self.slots.get(signal)
                if slot is not None:
                    slot()

        def emitFinished(self, exitCode=0, crashed=False) -> None:
            self._running = False
            self._exitCode = exitCode
            self._exitStatus = self.CrashExit if crashed else self.NormalExit
            slot = self.slots.get("finished(int,QProcess::ExitStatus)")
            if slot is not None:
                slot(exitCode, self._exitStatus)

        def emitFailedToStart(self) -> None:
            self._running = False
            slot = self.slots.get("errorOccurred(QProcess::ProcessError)")
            if slot is not None:
                slot(self.FailedToStart)

    def _fakeProcessFactory(self):
        processes = []

        def factory():
            process = self._FakeUc1Process()
            processes.append(process)
            return process

        return factory, processes

    @contextlib.contextmanager
    def _fixtureDirectory(self):
        import shutil
        import tempfile

        # A short prefix: UC1 keeps at most 127 characters of a path, and the
        # cube UC1 reads lies at build/uc1/UC1/input/<cube> under this.
        root = Path(tempfile.mkdtemp(prefix="slia-fx-"))
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _describeUc1Input(self, header, buildRoot):
        """What Capture hands UC1: the calibrated cube behind `header`, on the model bands."""
        calibratedModule = self._helperModule("SLIAFlowCalibratedCube")
        inputModule = self._helperModule("SLIAFlowUc1Input")
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        return inputModule.describeUc1Input(calibratedModule.loadCalibratedCube(header),
                                            uc1Run.Uc1Build(buildRoot).inputDirectory)

    def _startRun(self, fixture, header=None, **runOptions):
        """Prepare a Uc1Run on the fixture cube (or `header`) with a fake process."""
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        case = self._describeUc1Input(header or fixture["calibratedHeader"], fixture["buildRoot"])
        build = uc1Run.Uc1Build(fixture["buildRoot"])
        factory, processes = self._fakeProcessFactory()
        results = []
        run = uc1Run.Uc1Run(build, case, results.append, processFactory=factory, **runOptions)
        return run, case, build, processes, results

    # --- BMP reader -------------------------------------------------------

    def test_bmpReaderAcceptsPaddedWriterOutput(self) -> None:
        reader = self._helperModule("SLIAFlowBmpReader")
        # Widths 4, 5, 6 and 7 need 0, 1, 2 and 3 padding bytes per row.
        for samples in (4, 5, 6, 7):
            with self.subTest(samples=samples):
                image = self._fixtureImage(lines=3, samples=samples)
                data = self._uc1BmpBytes(image)
                decoded = reader.decodeUc1Bmp(data, samples, 3)
                self.assertEqual(decoded.dtype, np.uint8)
                self.assertEqual(decoded.shape, (3, samples, 3))
                np.testing.assert_array_equal(decoded, image)

    def test_bmpReaderRejectsUnpaddedRows(self) -> None:
        reader = self._helperModule("SLIAFlowBmpReader")
        image = self._fixtureImage(lines=3, samples=5)
        with self.assertRaises(reader.BmpFormatError) as raised:
            reader.decodeUc1Bmp(self._uc1BmpBytes(image, padded=False), 5, 3)
        self.assertIn("bytes", str(raised.exception))

    def test_bmpReaderRejectsWrongFormat(self) -> None:
        import struct

        reader = self._helperModule("SLIAFlowBmpReader")
        valid = bytearray(self._uc1BmpBytes(self._fixtureImage(lines=2, samples=4)))

        def patched(offset, fmt, value):
            data = bytearray(valid)
            struct.pack_into(fmt, data, offset, value)
            return bytes(data)

        cases = {
            "signature": patched(0, "<2s", b"XX"),
            "pixel offset": patched(10, "<I", 58),
            "info header size": patched(14, "<I", 108),
            "planes": patched(26, "<H", 2),
            "bit depth": patched(28, "<H", 32),
            "compression": patched(30, "<I", 1),
            "top-down height": patched(22, "<i", -2),
            "truncated header": bytes(valid[:40]),
        }
        for label, data in cases.items():
            with self.subTest(defect=label), self.assertRaises(reader.BmpFormatError):
                reader.decodeUc1Bmp(data, 4, 2)

    def test_bmpReaderRejectsWrongDimensions(self) -> None:
        reader = self._helperModule("SLIAFlowBmpReader")
        data = self._uc1BmpBytes(self._fixtureImage(lines=3, samples=4))
        for samples, lines in ((5, 3), (4, 2)):
            with self.subTest(expected=(samples, lines)):
                with self.assertRaises(reader.BmpFormatError) as raised:
                    reader.decodeUc1Bmp(data, samples, lines)
                self.assertIn(f"{samples} x {lines}", str(raised.exception))

    # ------------------------------------------------------------------
    # The recorded case's own ground truth
    # ------------------------------------------------------------------

    def test_groundTruthPaletteMatchesTheClassifierOutputs(self) -> None:
        """gtMap class IDs index FOUR_COLORS_MAP, so the colours mean one thing.

        `writeKNNBMP` (BitmapWriter.cpp) paints svm.bmp and knn.bmp straight
        from `FOUR_COLORS_MAP[classId]`, and gtMap.hdr legends the same IDs.
        If this table drifted from the UC1 source, a ground truth laid over a
        result would be read against a different legend from the one the
        classifier drew, so the two are pinned together here.
        """
        cubeModule = self._helperModule("SLIAFlowCube")
        self.assertEqual(
            cubeModule.GROUND_TRUTH_CLASSES,
            (
                (0, "Pixel Not Labeled", (255, 255, 255)),
                (1, "Normal Tissue", (0, 255, 0)),
                (2, "Tumor Tissue", (255, 0, 0)),
                (3, "Hypervascularized Tissue", (0, 0, 255)),
                (4, "Background", (0, 0, 0)),
            ),
            "FOUR_COLORS_MAP in BitmapWriter.hpp and the Class ID legend in gtMap.hdr",
        )
        self.assertEqual(cubeModule.UNLABELLED_CLASS_ID, 0)
        self.assertEqual(cubeModule.HIGHEST_GROUND_TRUTH_CLASS_ID, 4)

    def test_groundTruthIsReadTopRowFirst(self) -> None:
        """readGroundTruth returns (lines, samples) with row 0 at the top.

        One band of bil is a plain row-major image, and `readUc1Bmp` hands back
        a decoded output the same way round, so no flip is needed for the two to
        line up. A flip here would put the labels on the wrong tissue.
        """
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            labels = [1, 2, 3, 4, 0, 0, 0, 0, 0, 0, 0, 0]
            folder = self._writeFixtureGroundTruth(root / self.CALIBRATED_CUBE_NAME,
                                                   groundTruthLabels=labels)
            groundTruth = cubeModule.readGroundTruth(folder, samples=4, lines=3)
            self.assertEqual(groundTruth.shape, (3, 4))
            self.assertEqual(groundTruth.dtype, np.dtype("uint16"))
            self.assertEqual(groundTruth[0].tolist(), [1, 2, 3, 4])
            self.assertEqual(groundTruth[1].tolist(), [0, 0, 0, 0])

    def test_groundTruthIsRefusedRatherThanReshaped(self) -> None:
        """A gtMap that does not describe this cube is refused, not fitted to it."""
        cubeModule = self._helperModule("SLIAFlowCube")
        rejections = {
            "no gtMap.hdr": (dict(omit=("gtMap.hdr",)), "is missing"),
            "no gtMap": (dict(omit=("gtMap",)), "is missing"),
            "other dimensions": (dict(groundTruthOverrides={"samples": 9}), "but the cube is"),
            "more than one band": (dict(groundTruthOverrides={"bands": 2}), "single map of labels"),
            "wrong data type": (dict(groundTruthOverrides={"dataType": "4"}), "not 12 (uint16)"),
            "wrong interleave": (dict(groundTruthOverrides={"interleave": "bsq"}), "not bil"),
            "wrong byte order": (
                dict(groundTruthOverrides={"byteOrder": "1"}), "not 0 (little-endian)"),
            "a header offset": (dict(groundTruthOverrides={"headerOffset": "64"}), "header offset"),
            "a class outside the legend": (dict(groundTruthLabels=[5] + [0] * 11), "only legends"),
            "a short gtMap": (dict(groundTruthLabels=[1, 2, 3]), "bytes but"),
        }
        for reason, (options, message) in rejections.items():
            with self.subTest(reason=reason):
                with self._fixtureDirectory() as root:
                    folder = self._writeFixtureGroundTruth(root / self.CALIBRATED_CUBE_NAME,
                                                           **options)
                    with self.assertRaises(cubeModule.GroundTruthError) as raised:
                        cubeModule.readGroundTruth(folder, samples=4, lines=3)
                    self.assertIn(message, str(raised.exception))

    def test_groundTruthReadingDoesNotWriteToInput(self) -> None:
        """Reading a ground truth leaves the cube's folder byte for byte as it was."""
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            folder = root / self.CALIBRATED_CUBE_NAME
            self._writeFixtureCalibratedCube(folder)
            self._writeFixtureGroundTruth(folder)
            before = {path.name: (path.stat().st_size, path.read_bytes())
                      for path in sorted(folder.iterdir())}
            self.assertTrue(cubeModule.hasGroundTruth(folder))
            cubeModule.readGroundTruth(folder, samples=4, lines=3)
            after = {path.name: (path.stat().st_size, path.read_bytes())
                     for path in sorted(folder.iterdir())}
            self.assertEqual(before, after)

    def test_groundTruthIsASelectableViewAlongsideTheOutputs(self) -> None:
        """gtMap is a sixth entry in Delineation output, after the five outputs."""
        cubeModule = self._helperModule("SLIAFlowCube")
        self.assertEqual(parameterModule.GROUND_TRUTH_VIEW_NAME,
                         cubeModule.GROUND_TRUTH_FILE_NAME)
        self.assertEqual(
            parameterModule.RESULT_VIEW_NAMES,
            (*self.UC1_OUTPUT_FILE_NAMES, "gtMap"),
        )
        # The default stays an output: the panel opens on a result, not on a
        # ground truth laid over one.
        self.assertIn(parameterModule.DEFAULT_RESULT_OUTPUT, self.UC1_OUTPUT_FILE_NAMES)

    # --- The configured cube (SLIA-031, SLIA-033, ADR-0004 decisions 1, 4, 6) -

    # ADR-0004 decision 4, restated from its text rather than from the module:
    # the staged model's 93 bands lie at 440-900 nm in 5 nm steps (the band
    # grid of the HSI Human Brain Database it was trained on). 460-900 nm feed
    # them one to one, 440-455 nm take the 460 nm band, 905-1000 nm are dropped.
    MODEL_WAVELENGTHS_NM = tuple(range(440, 901, 5))
    LOWEST_LCTF_WAVELENGTH_NM = 460

    def test_bandMappingFeedsEachModelBandFromTheDocumentedSource(self) -> None:
        """Each of the 93 model bands is fed from the source band ADR-0004 names."""
        inputModule = self._helperModule("SLIAFlowUc1Input")
        self.assertEqual(len(self.MODEL_WAVELENGTHS_NM), self.UC1_MODEL_BAND_COUNT)
        self.assertEqual(inputModule.UC1_MODEL_BAND_COUNT, self.UC1_MODEL_BAND_COUNT)
        sources = inputModule.modelBandSources(
            tuple(float(value) for value in self.LCTF_WAVELENGTHS_NM), "the cube")
        self.assertEqual(len(sources), self.UC1_MODEL_BAND_COUNT)
        for modelBand, modelWavelength in enumerate(self.MODEL_WAVELENGTHS_NM):
            expected = max(modelWavelength, self.LOWEST_LCTF_WAVELENGTH_NM)
            with self.subTest(modelBand=modelBand + 1, wavelength=modelWavelength):
                self.assertEqual(self.LCTF_WAVELENGTHS_NM[sources[modelBand]], expected)
        used = set(sources)
        self.assertEqual(
            [self.LCTF_WAVELENGTHS_NM[index] for index in range(len(self.LCTF_WAVELENGTHS_NM))
             if index not in used],
            list(range(905, 1001, 5)),
            "Exactly 905-1000 nm are dropped",
        )

    def test_bandMappingRefusesACubeOffTheLctfGrid(self) -> None:
        """The mapping is defined for the LCTF grid only; anything else is refused."""
        inputModule = self._helperModule("SLIAFlowUc1Input")
        calibratedModule = self._helperModule("SLIAFlowCalibratedCube")
        oneOff = list(self.LCTF_WAVELENGTHS_NM)
        oneOff[40] += 1
        grids = {
            "the HSI 440-900 nm grid": tuple(range(440, 901, 5)),
            "460-900 nm only": tuple(range(460, 901, 5)),
            "shifted by 5 nm": tuple(range(465, 1006, 5)),
            "one band 1 nm off": tuple(oneOff),
        }
        for label, wavelengths in grids.items():
            with self.subTest(grid=label):
                with self.assertRaises(inputModule.BandMappingError) as raised:
                    inputModule.modelBandSources(tuple(float(value) for value in wavelengths),
                                                 "cube.hdr")
                self.assertIsInstance(raised.exception, calibratedModule.CalibratedCubeError)
                self.assertIn("cube.hdr", str(raised.exception))
                self.assertIn("460", str(raised.exception))

    def test_uc1InputIsTheMappedCubeWrittenOutsideInput(self) -> None:
        """UC1 reads the mapped cube from the build, and input/ is left as it was.

        The oracle is the fixture's own values taken at the ADR-0004 source
        bands: raw.dat must be exactly those bytes, band after band, and raw.hdr
        must describe a 93-band float32 cube UC1 reads as calibrated.
        """
        cubeModule = self._helperModule("SLIAFlowCube")

        def snapshot(folder):
            return sorted((str(path.relative_to(folder)), path.stat().st_size,
                           path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else b"")
                          for path in folder.rglob("*"))

        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root, groundTruth=True)
            inputFolder = root / "input"
            before = snapshot(inputFolder)
            run, case, build, processes, results = self._startRun(fixture)
            self.assertEqual(case.folder, fixture["runFolder"].resolve())
            run.start()
            try:
                self.assertEqual(processes[0].arguments, [str(fixture["runFolder"].resolve())])
                values = fixture["calibratedValues"]
                sourceBands = [self.LCTF_WAVELENGTHS_NM.index(
                    max(wavelength, self.LOWEST_LCTF_WAVELENGTH_NM))
                    for wavelength in self.MODEL_WAVELENGTHS_NM]
                expected = np.ascontiguousarray(values[sourceBands]).astype("<f4").tobytes()
                written = (fixture["runFolder"] / "raw.dat").read_bytes()
                self.assertEqual(len(written), len(expected))
                self.assertEqual(written, expected, "raw.dat is not the mapped cube")

                header = cubeModule.parseEnviHeader(
                    (fixture["runFolder"] / "raw.hdr").read_text(encoding="ascii"))
                self.assertEqual(
                    {key: header.get(key) for key in ("samples", "lines", "bands", "data type",
                                                      "interleave", "byte order",
                                                      "header offset")},
                    {"samples": "4", "lines": "3", "bands": "93", "data type": "4",
                     "interleave": "bsq", "byte order": "0", "header offset": "0"},
                )
            finally:
                run.cancel()
            self.assertEqual(snapshot(inputFolder), before, "Something was written into input/")

    def test_moduleHasNoCasePool(self) -> None:
        """One configured cube: no pool, no shuffling, no recorded case run in place."""
        with self.assertRaises(ModuleNotFoundError):
            self._helperModule("SLIAFlowCasePool")
        cubeModule = self._helperModule("SLIAFlowCube")
        for name in ("CasePool", "discoverCases", "DEFERRED_CASES", "DEFERRED_REASON",
                     "NoCompatibleCaseError", "random", "loadRecordedCase",
                     "assertCaseUnchanged", "RecordedCase"):
            self.assertFalse(hasattr(cubeModule, name), f"SLIAFlowCube still has {name}")
        logic = SLIAFlowLogic()
        for name in ("casePool", "inputRoot", "INPUT_RELATIVE_PATH", "cubeFolder",
                     "CUBE_RELATIVE_PATH", "loadConfiguredCube"):
            self.assertFalse(hasattr(logic, name), f"SLIAFlowLogic still has {name}")

    def test_captureRunsUc1OnTheConfiguredCalibratedCube(self) -> None:
        """Every Capture runs UC1 on the configured calibrated cube, and no other.

        The cube is the one the HS Cube panel shows (ADR-0004 decision 1),
        handed to UC1 as the mapped copy in the staged build's input folder.
        """
        with self._captureSession() as session:
            widget = session["widget"]
            root = session["root"]
            self.assertEqual(widget.logic.calibratedCubeHeader,
                             root / "input" / self.CALIBRATED_CUBE_NAME
                             / f"{self.CALIBRATED_CUBE_STEM}.hdr")
            other, _values = self._writeFixtureCalibratedCube(root / "input" / "other-cube")
            self._startFakeCamera(session)
            expectedFolders = [session["runFolder"]] * 2 + [
                root / self.UC1_INPUT_RELATIVE_PATH / "other-cube"] * 2
            for index, expectedFolder in enumerate(expectedFolders):
                if index == 2:
                    widget.logic.calibratedCubeHeader = other
                self._showFrame(session, 40)
                widget._onCaptureClicked()
                case, _ = self._finishCapture(session)
                self.assertEqual(case.folder, expectedFolder.resolve())
                self.assertEqual(session["processes"][-1].arguments,
                                 [str(expectedFolder.resolve())])
                self.assertTrue((expectedFolder / "raw.dat").is_file())
            self.assertEqual(len(session["processes"]), 4)

    def test_configuredCubeIsRefusedWithItsReason(self) -> None:
        """A cube UC1 cannot run on ends the Capture, naming it and why."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            root = session["root"]
            configured = session["calibratedHeader"]
            offGrid, _values = self._writeFixtureCalibratedCube(
                root / "input" / "off-grid", wavelengths=tuple(range(440, 901, 5)))
            missing = root / "input" / "absent" / f"{self.CALIBRATED_CUBE_STEM}.hdr"
            for label, prepare, header, reason in (
                ("missing", lambda: None, missing, "is missing"),
                ("off the LCTF grid", lambda: None, offGrid, "460"),
                ("inconsistent",
                 lambda: configured.with_suffix(".dat").write_bytes(b"\0" * 10),
                 configured, "is 10 bytes"),
            ):
                with self.subTest(defect=label):
                    prepare()
                    widget.logic.calibratedCubeHeader = header
                    self._showFrame(session, 50)
                    widget._onCaptureClicked()
                    status = widget.ui.statusLabel.text
                    self.assertIn(str(header), status)
                    self.assertIn(reason, status)
                    self.assertEqual(session["processes"], [], "UC1 started on a refused cube")
                    self.assertIsNone(widget.logic.currentRun)
                    self.assertFalse(widget.captureInProgress)
                    self.assertFalse(widget.liveViewFrozen, "LiveView stayed frozen")

    def test_runEnvironmentChangeRestoresTheDefaultCube(self) -> None:
        """A cube chosen in one run environment does not carry into the next."""
        logic = SLIAFlowLogic()
        with self._fixtureDirectory() as first, self._fixtureDirectory() as second:
            try:
                logic.setRunEnvironment(repositoryRoot=first)
                logic.calibratedCubeHeader = first / "input" / "elsewhere" / "cube.hdr"
                logic.setRunEnvironment(repositoryRoot=second)
                self.assertEqual(logic.calibratedCubeHeader,
                                 second / logic.CALIBRATED_CUBE_RELATIVE_PATH)
                logic.calibratedCubeHeader = second / "input" / "elsewhere" / "cube.hdr"
                logic.setRunEnvironment()
                self.assertEqual(logic.calibratedCubeHeader,
                                 logic.repositoryRoot / logic.CALIBRATED_CUBE_RELATIVE_PATH)
            finally:
                logic.calibratedCubeHeader = None
                logic.setRunEnvironment()

    def test_cubeRefusalReasonsAreTranslated(self) -> None:
        """The reason a cube is refused is translated, not only the sentence around it.

        The status bar shows the reason after the translated "The configured
        cube ... cannot be used" prefix, so an untranslated reason would still
        reach the operator in English. Every refusal the modules raise is
        checked in the source, and a sample of them is checked at run time.
        """
        import ast
        from unittest import mock

        import slicer.i18n

        marker = "[translated] "

        def translate(context, text):
            return marker + text

        cubeModule = self._helperModule("SLIAFlowCube")
        calibratedModule = self._helperModule("SLIAFlowCalibratedCube")
        inputModule = self._helperModule("SLIAFlowUc1Input")
        for module, errorNames in ((cubeModule, ("GroundTruthError",)),
                                   (calibratedModule, ("CalibratedCubeError",)),
                                   (inputModule, ("BandMappingError", "CalibratedCubeError"))):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                raises, untranslated = 0, []
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                            and getattr(node.exc.func, "id", None) in errorNames):
                        continue
                    raises += 1
                    message = node.exc.args[0] if node.exc.args else None
                    if (isinstance(message, ast.Call) and isinstance(message.func, ast.Attribute)
                            and message.func.attr == "format"):
                        message = message.func.value
                    if not (isinstance(message, ast.Call)
                            and getattr(message.func, "id", None) == "_"):
                        untranslated.append(node.lineno)
                self.assertGreater(raises, 0)
                self.assertEqual(untranslated, [],
                                 "Refusals raised without _() at these lines")

        messages = {}
        with mock.patch.object(slicer.i18n, "translate", translate), \
                self._fixtureDirectory() as root:
            folder = self._writeFixtureGroundTruth(root / "no-map", omit=("gtMap",))
            with self.assertRaises(cubeModule.GroundTruthError) as raised:
                cubeModule.readGroundTruth(folder, samples=4, lines=3)
            messages["ground truth missing"] = str(raised.exception)

            for name, options in (("calibrated uint16", dict(dataType=12)),
                                  ("calibrated short", dict(dataBytes=10)),
                                  ("calibrated no wavelengths", dict(wavelengths=None, bands=109))):
                header, _values = self._writeFixtureCalibratedCube(root / name, **options)
                with self.assertRaises(calibratedModule.CalibratedCubeError) as raised:
                    calibratedModule.loadCalibratedCube(header)
                messages[name] = str(raised.exception)

            header, _values = self._writeFixtureCalibratedCube(
                root / "off-grid", wavelengths=tuple(range(440, 901, 5)))
            with self.assertRaises(inputModule.BandMappingError) as raised:
                self._describeUc1Input(header, root / "build")
            messages["off the LCTF grid"] = str(raised.exception)

            header, _values = self._writeFixtureCalibratedCube(root / "changed")
            case = self._describeUc1Input(header, root / "build")
            self._writeFixtureCalibratedCube(root / "changed", samples=5)
            with self.assertRaises(calibratedModule.CalibratedCubeError) as raised:
                inputModule.assertUc1InputUnchanged(case)
            messages["changed on disk"] = str(raised.exception)

        for label, message in messages.items():
            with self.subTest(refusal=label):
                self.assertTrue(message.startswith(marker), f"Not translated: {message!r}")

    # --- UC1 run ----------------------------------------------------------

    def test_repositoryRootIsFoundFromModuleLocation(self) -> None:
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        moduleFile = Path(uc1Run.__file__).resolve()
        root = uc1Run.findRepositoryRoot(moduleFile)
        self.assertTrue((root / "AGENTS.md").is_file())
        self.assertTrue((root / "extensions" / "SLIAFlow").is_dir())
        self.assertIn(root, moduleFile.parents)
        self.assertNotEqual(
            root, Path(slicer.app.applicationDirPath()).resolve(),
            "The root must come from the module location, not the application directory",
        )

        with self._fixtureDirectory() as fixtureRoot:
            fixture = self._makeFixtureRepository(fixtureRoot, cube=False)
            nested = fixtureRoot / "build" / "SLIAFlow" / "lib" / "qt-scripted-modules" / "SLIAFlowLib"
            nested.mkdir(parents=True)
            # Resolved on both sides: the temporary folder may be an 8.3 short path.
            self.assertEqual(uc1Run.findRepositoryRoot(nested / "SLIAFlowUc1Run.py"),
                             fixture["root"].resolve())
            (fixtureRoot / "AGENTS.md").unlink()
            with self.assertRaises(uc1Run.Uc1RunError):
                uc1Run.findRepositoryRoot(nested / "SLIAFlowUc1Run.py")

    def test_uc1RunUsesProgramArgumentAndWorkingDirectory(self) -> None:
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        self.assertEqual(uc1Run.RUN_TIMEOUT_SEC, self.UC1_RUN_TIMEOUT_SEC)
        self.assertEqual(tuple(uc1Run.OUTPUT_FILE_NAMES), self.UC1_OUTPUT_FILE_NAMES)
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            leftover = fixture["source"] / "output" / self.CALIBRATED_CUBE_NAME / "pca.bmp"
            leftover.parent.mkdir(parents=True)
            leftover.write_bytes(b"left by an earlier run")
            (fixture["source"] / "output" / "rgb").rmdir()

            run, case, build, processes, results = self._startRun(fixture)
            run.start()
            try:
                self.assertEqual(len(processes), 1)
                process = processes[0]
                self.assertTrue(process.started)
                self.assertEqual(Path(process.program), fixture["executable"])
                self.assertEqual(process.arguments, [str(case.folder)])
                self.assertEqual(Path(process.workingDirectory), fixture["source"])
                for shell in ("cmd", "powershell", "pwsh", "bash", "/c"):
                    self.assertNotIn(shell, str(process.program).lower())
                self.assertTrue(fixture["lock"].is_file(), "The lock is not held during the run")
                self.assertTrue((fixture["source"] / "output" / "rgb").is_dir())
                self.assertFalse(leftover.exists(), "A previous run's output was not cleared")
                self.assertTrue(run.running)
            finally:
                run.cancel()
            self.assertFalse(fixture["lock"].exists())

    def test_uc1PreRunChecksRefuseBeforeStarting(self) -> None:
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)

            def refused(expectedFragment, header=None):
                case = self._describeUc1Input(header or fixture["calibratedHeader"],
                                              fixture["buildRoot"])
                factory, processes = self._fakeProcessFactory()
                run = uc1Run.Uc1Run(uc1Run.Uc1Build(fixture["buildRoot"]), case, lambda result: None,
                                    processFactory=factory)
                with self.assertRaises(uc1Run.Uc1RunError) as raised:
                    run.start()
                self.assertIn(expectedFragment, str(raised.exception))
                self.assertEqual(processes, [], "A process was created for a refused run")
                self.assertFalse(fixture["lock"].exists(), "A refused run left the lock behind")

            with self.subTest(defect="missing executable"):
                fixture["executable"].rename(fixture["executable"].with_suffix(".off"))
                refused("build-uc1.ps1")
                fixture["executable"].with_suffix(".off").rename(fixture["executable"])

            with self.subTest(defect="damaged model"):
                weights = fixture["buildRoot"] / "svm_model" / "w_vector.bin"
                weights.write_bytes(b"\0" * 10)
                refused("w_vector.bin")
                weights.write_bytes(b"\0" * self.UC1_MODEL_FILE_SIZES["w_vector.bin"])

            with self.subTest(defect="input path too long"):
                # The run folder is named after the cube, so a long cube name
                # makes the path UC1 is given too long for its buffers.
                header, _values = self._writeFixtureCalibratedCube(root / "input" / ("c" * 90))
                refused("128", header=header)
                self.assertFalse((root / self.UC1_INPUT_RELATIVE_PATH / ("c" * 90)).exists(),
                                 "The cube was written for a run that was refused")

    def test_uc1RunRefusesWhileLockIsHeld(self) -> None:
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            fixture["lock"].write_text("12345\n", encoding="ascii")
            run, case, build, processes, results = self._startRun(fixture)
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn(uc1Run.LOCK_FILE_NAME, str(raised.exception))
            self.assertEqual(processes, [])
            self.assertTrue(fixture["lock"].is_file(), "SLIAFlow deleted a lock it does not hold")

    def test_lockThatCannotBeWrittenIsNotLeftBehind(self) -> None:
        """A lock this run created but never owned is removed before refusing.

        The caller marks the lock as held only once acquireLock returns, so a
        lock left behind by a failed write would be released by nobody, and
        every later Capture would refuse against a holder that does not exist.
        This is not the stale-lock case, which is deliberately left alone: here
        the holder is known, and it is this process.
        """
        from unittest import mock

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            build = uc1Run.Uc1Build(fixture["buildRoot"])
            with mock.patch("os.write", side_effect=OSError("no space left on device")), \
                    self.assertRaises(uc1Run.Uc1RunError) as raised:
                build.acquireLock()
            self.assertIn(uc1Run.LOCK_FILE_NAME, str(raised.exception))
            self.assertFalse(fixture["lock"].is_file(),
                             "A lock nothing holds was left in the staged build")
            # The build is still usable: the next run takes the lock normally.
            build.acquireLock()
            self.assertTrue(fixture["lock"].is_file())
            build.releaseLock()

    def test_cubeChangedOnDiskIsRefusedRatherThanRunOn(self) -> None:
        """The cube is re-read immediately before the run, not trusted from Capture.

        Capture describes the configured cube, then the run maps it into the
        build. The cube lies outside the repository and nothing here owns it,
        so it can be edited or truncated in between, with or without changing
        its size. The run is refused rather than run on whatever the file now
        holds: that would stamp the result with a cube the operator never saw
        described.
        """
        from unittest import mock

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        inputModule = self._helperModule("SLIAFlowUc1Input")
        calibratedModule = self._helperModule("SLIAFlowCalibratedCube")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)

            # Still a valid cube, but no longer the one that was described.
            run, case, build, processes, results = self._startRun(fixture)
            self._writeFixtureCalibratedCube(fixture["cubeFolder"], samples=6, lines=5)
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn("changed on disk", str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a cube that had changed")
            self.assertFalse(fixture["lock"].is_file(), "A refused run left the build locked")
            self.assertFalse((fixture["runFolder"] / "raw.dat").exists(),
                             "A cube that had changed was written for UC1")

            # A cube that no longer loads at all.
            self._writeFixtureCalibratedCube(fixture["cubeFolder"])
            run, case, build, processes, results = self._startRun(fixture)
            fixture["calibratedHeader"].with_suffix(".dat").write_bytes(b"")
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn(f"{self.CALIBRATED_CUBE_STEM}.dat", str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a truncated cube")
            self.assertFalse(fixture["lock"].is_file(), "A refused run left the build locked")

            # Other values of the same size. The header still describes the
            # file exactly, so only the file's own stamps can tell. The write
            # time is set explicitly: a rewrite within one tick of the file
            # system clock would otherwise keep it, and this test would be
            # timing dependent.
            data = fixture["calibratedHeader"].with_suffix(".dat")
            self._writeFixtureCalibratedCube(fixture["cubeFolder"])
            run, case, build, processes, results = self._startRun(fixture)
            described = data.stat()
            data.write_bytes(bytes(reversed(data.read_bytes())))
            os.utime(data, ns=(described.st_atime_ns, described.st_mtime_ns + 1_000_000_000))
            self.assertEqual(data.stat().st_size, described.st_size)
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn("changed on disk", str(raised.exception))
            self.assertIn(data.name, str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a cube rewritten in place")
            self.assertFalse(fixture["lock"].is_file(), "A refused run left the build locked")

            # Another file of the same size, with the same write time, moved
            # over the cube, as a copy that keeps timestamps leaves it.
            self._writeFixtureCalibratedCube(fixture["cubeFolder"])
            run, case, build, processes, results = self._startRun(fixture)
            described = data.stat()
            replacement = data.with_name("replacement.bin")
            replacement.write_bytes(bytes(reversed(data.read_bytes())))
            os.utime(replacement, ns=(described.st_atime_ns, described.st_mtime_ns))
            os.replace(replacement, data)
            self.assertEqual((data.stat().st_size, data.stat().st_mtime_ns),
                             (described.st_size, described.st_mtime_ns))
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn("changed on disk", str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a cube replaced by another")

            # Written to while it was being copied for UC1: checked again after
            # the copy, and the half-made copy is removed.
            self._writeFixtureCalibratedCube(fixture["cubeFolder"])
            case = self._describeUc1Input(fixture["calibratedHeader"], fixture["buildRoot"])
            realStamps = inputModule.fileStamps
            calls = []

            def stampsThatChangeAfterTheCopy(cube):
                calls.append(cube)
                header, (size, writeTime, fileId) = realStamps(cube)
                if len(calls) > 1:
                    writeTime += 1  # The data file was written to during the copy.
                return header, (size, writeTime, fileId)

            with mock.patch.object(inputModule, "fileStamps", stampsThatChangeAfterTheCopy), \
                    self.assertRaises(calibratedModule.CalibratedCubeError) as raised:
                inputModule.writeUc1Input(case)
            self.assertEqual(len(calls), 2, "The cube was not checked again after the copy")
            self.assertIn("changed on disk", str(raised.exception))
            self.assertEqual(sorted(path.name for path in case.folder.iterdir()), [],
                             "A copy refused after it was made was left for UC1")

            # The cube as described still runs.
            run, case, build, processes, results = self._startRun(fixture)
            run.start()
            try:
                self.assertEqual(len(processes), 1, "UC1 was not started on an unchanged cube")
            finally:
                run.cancel()

    def test_unexpectedValidationFailureStillReportsTheRun(self) -> None:
        """An error the output checks did not foresee still ends the capture.

        The process-finished handler is a Qt slot: an exception raised out of
        it reaches the signal dispatch, which drops it, and the completion
        callback never runs. The module would stay in its capturing state, with
        LiveView frozen and Capture disabled, for the rest of the session. The
        run is reported as failed instead.
        """
        from unittest import mock

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            run, case, build, processes, results = self._startRun(fixture)
            run.start()
            self._writeUc1Outputs(build.caseOutputDirectory(case.name))
            with mock.patch.object(uc1Run, "collectOutputs",
                                   side_effect=PermissionError("the output folder is denied")):
                processes[0].emitFinished(0)
            self.assertEqual(len(results), 1,
                             "The run was never reported, so Capture stays busy for the session")
            self.assertFalse(results[0].success)
            self.assertIsNone(results[0].outputs)
            self.assertIn("could not be checked", results[0].message)
            self.assertFalse(run.running)
            self.assertFalse(fixture["lock"].is_file(), "The lock outlived the failed run")

    def test_uc1RunFailsOnExitCodeCrashOrPathTooLong(self) -> None:
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            scenarios = {
                "nonzero exit": (lambda process: process.emitFinished(3), "3"),
                "crash": (lambda process: process.emitFinished(0, crashed=True), "crash"),
                "failed to start": (lambda process: process.emitFailedToStart(), "start"),
                "path too long": (
                    lambda process: (process.emitOutput(stderr=b"Path too long\n"),
                                     process.emitFinished(0)),
                    "Path too long",
                ),
            }
            for label, (finish, fragment) in scenarios.items():
                with self.subTest(scenario=label):
                    run, case, build, processes, results = self._startRun(fixture)
                    run.start()
                    # Every output is present, fresh and valid, so only the
                    # process outcome can make this run fail.
                    self._writeUc1Outputs(build.caseOutputDirectory(case.name))
                    finish(processes[0])
                    self.assertEqual(len(results), 1)
                    self.assertFalse(results[0].success)
                    self.assertIn(fragment.lower(), results[0].message.lower())
                    self.assertIsNone(results[0].outputs)
                    self.assertFalse(run.running)
                    self.assertFalse(fixture["lock"].exists())

            run, case, build, processes, results = self._startRun(fixture)
            run.start()
            self._writeUc1Outputs(build.caseOutputDirectory(case.name))
            processes[0].emitOutput(stdout=b"Time simulation ---> 1.0 ms\n")
            processes[0].emitFinished(0)
            self.assertTrue(results[0].success, results[0].message)
            self.assertIn("Time simulation", results[0].stdout)

    def test_uc1RunTimesOutAndKillsProcess(self) -> None:
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            run, case, build, processes, results = self._startRun(fixture, timeoutSec=0.05)
            run.start()
            deadline = time.monotonic() + 5.0
            while not results and time.monotonic() < deadline:
                slicer.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(len(results), 1, "The timeout never ended the run")
            self.assertFalse(results[0].success)
            self.assertIn("timed out", results[0].message.lower())
            self.assertTrue(processes[0].killed)
            self.assertIsNotNone(processes[0].waitedMs)
            self.assertFalse(run.running)
            self.assertFalse(fixture["lock"].exists())

    def _slicerPythonOrSkip(self) -> Path:
        import sys

        candidates = []
        if Path(sys.executable).name.lower().startswith("python"):
            candidates.append(Path(sys.executable))
        applicationDirectory = Path(slicer.app.applicationDirPath())
        for directory in (applicationDirectory, applicationDirectory.parent,
                          Path(slicer.app.slicerHome) / "bin"):
            candidates.append(directory / "PythonSlicer.exe")
        python = next((path for path in candidates if path.is_file()), None)
        if python is None:
            self.skipTest("Slicer's Python executable could not be found to run a real QProcess")
        return python

    def _runRealProcess(self, uc1Run, python: Path, code: str):
        outcomes = []
        owned = uc1Run.OwnedProcess(outcomes.append, timeoutSec=30)
        with self._fixtureDirectory() as root:
            owned.start(str(python), ["-c", code], str(root))
            deadline = time.monotonic() + 30.0
            while not outcomes and time.monotonic() < deadline:
                slicer.app.processEvents()
                time.sleep(0.02)
        self.assertEqual(len(outcomes), 1, "The real process never reported finishing")
        self.assertFalse(owned.running)
        return outcomes[0]

    def test_realQProcessReportsOutputAndExitCode(self) -> None:
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        python = self._slicerPythonOrSkip()

        outcomes = []
        owned = uc1Run.OwnedProcess(outcomes.append, timeoutSec=30)
        with self._fixtureDirectory() as root:
            owned.start(
                str(python),
                ["-c", "import sys; print('uc1-out'); print('uc1-err', file=sys.stderr); sys.exit(3)"],
                str(root),
            )
            deadline = time.monotonic() + 30.0
            while not outcomes and time.monotonic() < deadline:
                slicer.app.processEvents()
                time.sleep(0.02)
        self.assertEqual(len(outcomes), 1, "The real process never reported finishing")
        outcome = outcomes[0]
        self.assertEqual(outcome.exitCode, 3)
        self.assertFalse(outcome.crashed)
        self.assertFalse(outcome.timedOut)
        self.assertIn("uc1-out", outcome.stdout)
        self.assertIn("uc1-err", outcome.stderr)
        self.assertFalse(owned.running)

    def test_uc1ProcessOpensNoConsoleWindowOfItsOwn(self) -> None:
        """UC1 is a console program; starting it must not open a console window.

        Qt 5.15 (qprocess_win.cpp) passes CREATE_NO_WINDOW when Slicer has no
        console, and otherwise lets the child share Slicer's. Either way the
        child's console window is none or Slicer's own, never a new one. The
        child here is a console program too, so it reports what UC1 would get.
        """
        import ctypes
        import re
        import sys

        if sys.platform != "win32":
            self.skipTest("Console windows are a Windows concern")
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        python = self._slicerPythonOrSkip()
        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        slicerConsole = kernel32.GetConsoleWindow() or 0

        outcome = self._runRealProcess(uc1Run, python, (
            "import ctypes; k = ctypes.windll.kernel32; k.GetConsoleWindow.restype = ctypes.c_void_p; "
            "print('console-window', k.GetConsoleWindow() or 0)"
        ))
        self.assertEqual(outcome.exitCode, 0, outcome.stderr)
        match = re.search(r"console-window (\d+)", outcome.stdout)
        self.assertIsNotNone(match, outcome.stdout)
        childConsole = int(match.group(1))
        if slicerConsole:
            self.assertEqual(childConsole, slicerConsole,
                             "The child opened a console window instead of sharing Slicer's")
        else:
            self.assertEqual(childConsole, 0, "The child opened a console window of its own")

    # --- Output validation ------------------------------------------------

    def test_outputsRefusedWhenMissingOrStale(self) -> None:
        import os

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            case = self._describeUc1Input(fixture["calibratedHeader"], fixture["buildRoot"])
            build = uc1Run.Uc1Build(fixture["buildRoot"])
            outputDirectory = build.caseOutputDirectory(case.name)
            runStart = time.time() - 60.0

            self._writeUc1Outputs(outputDirectory)
            collected = uc1Run.collectOutputs(build, case, runStart)
            self.assertEqual(tuple(collected), self.UC1_OUTPUT_FILE_NAMES)

            for fileName in self.UC1_OUTPUT_FILE_NAMES:
                with self.subTest(missing=fileName):
                    self._writeUc1Outputs(outputDirectory, overrides={fileName: None})
                    (outputDirectory / fileName).unlink(missing_ok=True)
                    with self.assertRaises(uc1Run.Uc1RunError) as raised:
                        uc1Run.collectOutputs(build, case, runStart)
                    self.assertIn(fileName, str(raised.exception))

                with self.subTest(stale=fileName):
                    self._writeUc1Outputs(outputDirectory)
                    old = runStart - 30.0
                    os.utime(outputDirectory / fileName, (old, old))
                    with self.assertRaises(uc1Run.Uc1RunError) as raised:
                        uc1Run.collectOutputs(build, case, runStart)
                    self.assertIn(fileName, str(raised.exception))
                    self.assertIn("earlier run", str(raised.exception))

                with self.subTest(malformed=fileName):
                    image = self._fixtureImage(lines=3, samples=5)
                    self._writeUc1Outputs(outputDirectory, overrides={
                        fileName: self._uc1BmpBytes(image, padded=False)})
                    with self.assertRaises(uc1Run.Uc1RunError) as raised:
                        uc1Run.collectOutputs(build, case, runStart)
                    self.assertIn(fileName, str(raised.exception))

    # --- Capture flow in the widget ---------------------------------------

    class _FakeCameraTimer:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, signal, callback) -> None:
            self.callback = callback

        def disconnect(self, signal, callback) -> None:
            self.callback = None

        def setInterval(self, interval) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def fire(self) -> None:
            if self.callback is not None:
                self.callback()

    class _FakeCameraCapture:
        def __init__(self) -> None:
            self.frame = None

        def isOpened(self) -> bool:
            return True

        def set(self, propertyId, value) -> None:
            pass

        def read(self):
            return self.frame is not None, self.frame

        def release(self) -> None:
            pass

    class _FakeCV2:
        CAP_MSMF = 10
        CAP_DSHOW = 20
        CAP_PROP_FRAME_WIDTH = 30
        CAP_PROP_FRAME_HEIGHT = 40

    @staticmethod
    def _bgrFrame(value):
        # A 3 x 4 test placeholder frame, distinct per pixel, in OpenCV's BGR.
        frame = np.zeros((3, 4, 3), dtype=np.uint8)
        frame[..., 0] = np.arange(12, dtype=np.uint8).reshape(3, 4) * 3 + value
        frame[..., 1] = value
        frame[..., 2] = 255 - value
        return frame

    @contextlib.contextmanager
    def _captureSession(self, *, cube=True, groundTruth=False, uc2=False):
        """The module widget wired to a fixture repository, a fake camera and fake UC1.

        The configured cube is the fixture calibrated cube at its default place,
        input/002-04. With `cube=False` it is not written, so the configured
        header does not exist; with `groundTruth` a gtMap lies beside it. With
        `uc2` a placeholder UC2 build is staged too, so Capture starts a fake
        UC2 process before the fake UC1 one; without it UC2 is refused before
        any process is created, and `processes` holds UC1's alone.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root, cube=cube, groundTruth=groundTruth)
            if uc2:
                fixture.update(self._makeFixtureUc2Build(root))
            factory, processes = self._fakeProcessFactory()
            widget.logic.setRunEnvironment(repositoryRoot=root, processFactory=factory)
            capture = self._FakeCameraCapture()
            timer = self._FakeCameraTimer()
            session = dict(fixture, widget=widget, processes=processes, capture=capture,
                           timer=timer, cube=fixture["cubeFolder"])
            try:
                yield session
            finally:
                widget._cancelCapture()
                widget._stopCamera(clearLiveView=True)
                widget._forgetResult()
                widget._forgetCube()
                widget._forgetVascularMap()
                widget.logic.calibratedCubeHeader = None
                widget.logic.setRunEnvironment(repositoryRoot=None, processFactory=None)

    def _startFakeCamera(self, session) -> None:
        widget = session["widget"]
        self.assertTrue(widget.logic.startCamera(
            0, widget._displayCameraFrame, widget._handleCameraError,
            cv2Module=self._FakeCV2, captureFactory=lambda *arguments: session["capture"],
            timerFactory=lambda: session["timer"],
        ))
        widget._refreshCameraControls()

    def _showFrame(self, session, value):
        session["capture"].frame = self._bgrFrame(value)
        session["timer"].fire()
        return session["capture"].frame[..., ::-1]

    def _liveArray(self, widget):
        return np.array(slicer.util.arrayFromVolume(widget._parameterNode.liveVolume))[0]

    def _finishCapture(self, session, *, seed=0, overrides=None, exitCode=0):
        widget = session["widget"]
        run = widget.logic.currentRun
        self.assertIsNotNone(run, "Capture did not start a UC1 run")
        case = run.case
        images = self._writeUc1Outputs(
            Path(session["source"]) / "output" / case.name,
            lines=case.lines, samples=case.samples, seed=seed, overrides=overrides,
        )
        session["processes"][-1].emitFinished(exitCode)
        return case, images

    def test_captureEnabledOnlyWhileCameraRunsAndIdle(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            button = widget.ui.captureButton
            self.assertFalse(button.enabled, "Capture is enabled with no camera running")
            self._startFakeCamera(session)
            self._showFrame(session, 10)
            self.assertTrue(button.enabled, "Capture is disabled while the camera runs")
            widget._onCaptureClicked()
            self.assertTrue(widget.captureInProgress)
            self.assertFalse(button.enabled, "Capture is enabled while a capture processes")
            self._finishCapture(session)
            self.assertFalse(widget.captureInProgress)
            self.assertTrue(button.enabled)
            widget._onStopCamera()
            self.assertFalse(button.enabled, "Capture stays enabled after the camera stops")

    def test_capturePressWhileBusyStartsNothing(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 10)
            widget._onCaptureClicked()
            run = widget.logic.currentRun
            widget._onCaptureClicked()
            widget.ui.captureButton.click()
            self.assertEqual(len(session["processes"]), 1)
            self.assertIs(widget.logic.currentRun, run)
            self.assertEqual(len(list(session["captures"].glob("*.png"))), 1)

    def test_captureFreezesLiveViewAndSavesUprightSnapshot(self) -> None:
        import re

        import qt

        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            frozenRgb = self._showFrame(session, 40)
            widget._onCaptureClicked()
            self.assertTrue(widget.liveViewFrozen)

            self._showFrame(session, 90)
            np.testing.assert_array_equal(self._liveArray(widget), frozenRgb,
                                          "LiveView kept updating after Capture")

            snapshots = list(session["captures"].glob("*.png"))
            self.assertEqual(len(snapshots), 1)
            self.assertRegex(snapshots[0].name, self.SNAPSHOT_NAME_PATTERN)
            # Read back with Qt's PNG reader, which is independent of the VTK
            # writer and reports row 0 as the top of the picture.
            image = qt.QImage(str(snapshots[0]))
            self.assertFalse(image.isNull())
            self.assertEqual((image.height(), image.width()), frozenRgb.shape[:2])
            for row in range(frozenRgb.shape[0]):
                for column in range(frozenRgb.shape[1]):
                    pixel = int(image.pixel(column, row))
                    observed = ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)
                    self.assertEqual(observed, tuple(int(v) for v in frozenRgb[row, column]),
                                     f"PNG pixel ({row}, {column})")
            self.assertTrue(re.match(self.SNAPSHOT_NAME_PATTERN, snapshots[0].name))

    def test_snapshotNameIsUniqueWithinOneSecond(self) -> None:
        import datetime

        with self._captureSession() as session:
            logic = session["widget"].logic
            frame = self._bgrFrame(5)[np.newaxis, ..., ::-1].copy()
            moment = datetime.datetime(2026, 9, 17, 14, 3, 7)
            paths = [logic.saveSnapshot(frame, now=moment) for _ in range(3)]
            self.assertEqual(
                [path.name for path in paths],
                [
                    "output_laptop_camera_20260917-140307.png",
                    "output_laptop_camera_20260917-140307-2.png",
                    "output_laptop_camera_20260917-140307-3.png",
                ],
            )
            for path in paths:
                self.assertEqual(path.parent, session["captures"])
                self.assertTrue(path.is_file())

    def test_liveViewResumesAfterSuccessAndFailure(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            for label, finish in (
                ("success", lambda: self._finishCapture(session)),
                ("failure", lambda: self._finishCapture(session, exitCode=1)),
            ):
                with self.subTest(outcome=label):
                    self._showFrame(session, 20)
                    widget._onCaptureClicked()
                    self.assertTrue(widget.liveViewFrozen)
                    finish()
                    self.assertFalse(widget.liveViewFrozen)
                    moving = self._showFrame(session, 150)
                    np.testing.assert_array_equal(self._liveArray(widget), moving,
                                                  f"LiveView did not resume after {label}")

    def test_captureWithoutAFrameIsRefused(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            widget._onCaptureClicked()
            self.assertFalse(widget.captureInProgress)
            self.assertIsNone(widget.logic.currentRun)
            self.assertEqual(session["processes"], [])
            self.assertFalse(session["captures"].exists() and any(session["captures"].iterdir()))
            self.assertIn("frame", widget.ui.statusLabel.text.lower())

    def test_resultsAcceptedOnlyWhenAllFiveValidate(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            firstCase, firstImages = self._finishCapture(session, seed=1)
            firstCapture = widget.logic.outputNode("imageRGB.bmp").GetAttribute("SLIAFlow.CaptureId")

            wrongSize = self._uc1BmpBytes(self._fixtureImage(lines=2, samples=4))
            self._showFrame(session, 31)
            widget._onCaptureClicked()
            failedCase = widget.logic.currentRun.case
            self._finishCapture(session, seed=2, overrides={"knn.bmp": wrongSize})

            self.assertIn("knn.bmp", widget.ui.statusLabel.text)
            self.assertIn(failedCase.name, widget.ui.statusLabel.text)
            for fileName in self.UC1_OUTPUT_FILE_NAMES:
                node = widget.logic.outputNode(fileName)
                self.assertEqual(node.GetAttribute("SLIAFlow.CaptureId"), firstCapture)
                self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"), firstCase.name)
                np.testing.assert_array_equal(
                    np.array(slicer.util.arrayFromVolume(node))[0], firstImages[fileName],
                    f"{fileName} was replaced by a run that did not validate",
                )
            self.assertIsNone(widget.logic.currentRun, "A replacement case was started")
            self.assertEqual(len(session["processes"]), 2)

    def test_outputVolumeIsUprightUnmirroredAndPixelIdentical(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            _, images = self._finishCapture(session, seed=4)
            for fileName in self.UC1_OUTPUT_FILE_NAMES:
                with self.subTest(output=fileName):
                    node = widget.logic.outputNode(fileName)
                    self.assertTrue(node.IsA("vtkMRMLVectorVolumeNode"))
                    array = np.array(slicer.util.arrayFromVolume(node))
                    self.assertEqual(array.dtype, np.uint8)
                    self.assertEqual(array.shape, (1, 3, 4, 3))
                    # Row 0 is the image top and column 0 its left edge, and the
                    # directions draw them that way, as for LiveView.
                    np.testing.assert_array_equal(array[0], images[fileName])
                    self.assertEqual(self._ijkToRasDirections(node), self.UPRIGHT_LIVE_DIRECTIONS)

    def test_outputNodesCarrySharedCaptureIdAndProvenance(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            captureIds = []
            for seed in (1, 2):
                self._showFrame(session, 30 + seed)
                widget._onCaptureClicked()
                case, _ = self._finishCapture(session, seed=seed)
                ids = set()
                for fileName in self.UC1_OUTPUT_FILE_NAMES:
                    with self.subTest(run=seed, output=fileName):
                        node = widget.logic.outputNode(fileName)
                        self.assertEqual(node.GetAttribute("SLIAFlow.OutputFile"), fileName)
                        self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"), case.name)
                        self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "simulated")
                        self.assertEqual(node.GetAttribute("SLIAFlow.SimulationDetail"),
                                         self.UC1_RESULT_DETAIL)
                        self.assertFalse(node.GetSaveWithScene())
                        ids.add(node.GetAttribute("SLIAFlow.CaptureId"))
                self.assertEqual(len(ids), 1, "The five outputs of one run carry different IDs")
                captureId = ids.pop()
                self.assertRegex(captureId or "", r"^[0-9a-f]{32}$")
                captureIds.append(captureId)
                self.assertIn(self.RESULT_STATUS_FORMAT.format(case=case.name),
                              widget.ui.resultStatusLabel.text)
            self.assertNotEqual(captureIds[0], captureIds[1], "A capture ID was reused")

    def test_previousResultIsMarkedStaleWhileProcessingAndAfterFailure(self) -> None:
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishCapture(session, seed=1)
            self.assertNotIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
            self.assertEqual(widget.staleResultLine(), "")

            widget._onCaptureClicked()
            self.assertIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
            self.assertEqual(widget.staleResultLine(), self.STALE_RESULT_LINE)

            self._finishCapture(session, exitCode=2)
            self.assertIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
            self.assertEqual(widget.staleResultLine(), self.STALE_RESULT_LINE)

            widget._onCaptureClicked()
            case, _ = self._finishCapture(session, seed=3)
            self.assertNotIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
            self.assertIn(self.RESULT_STATUS_FORMAT.format(case=case.name),
                          widget.ui.resultStatusLabel.text)
            self.assertEqual(widget.staleResultLine(), "")

    def test_cleanupKillsOwnedRunAndReleasesLock(self) -> None:
        for label in ("scene close", "module exit"):
            with self.subTest(trigger=label), self._captureSession() as session:
                widget = session["widget"]
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self.assertTrue(session["lock"].is_file())
                process = session["processes"][-1]
                if label == "scene close":
                    widget.onSceneStartClose()
                else:
                    widget.exit()
                self.assertTrue(process.killed, f"{label} left UC1 running")
                self.assertIsNotNone(process.waitedMs, f"{label} did not wait for UC1 to exit")
                self.assertFalse(session["lock"].exists(), f"{label} left the lock behind")
                self.assertFalse(widget.logic.cameraActive)
                self.assertFalse(widget.captureInProgress)
                self.assertIsNone(widget.logic.currentRun)
                for fileName in self.UC1_OUTPUT_FILE_NAMES:
                    self.assertIsNone(widget.logic.outputNode(fileName))
                widget.initializeParameterNode()

    def test_selectedOutputIsShownAloneWithStaleLineOnTheView(self) -> None:
        """What reaches the Tumour Delineation view, not what the widget records."""
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession() as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
                liveWidget = layoutManager.sliceWidget(widget.LIVE_VIEW_NAME)
                composite = resultWidget.sliceLogic().GetSliceCompositeNode()
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=1)

                selector = widget.ui.resultOutputSelector
                for fileName in ("imageRGB.bmp", "pca.bmp", "kmeans.bmp"):
                    with self.subTest(selected=fileName):
                        selector.setCurrentText(fileName)
                        node = widget.logic.outputNode(fileName)
                        self.assertEqual(composite.GetBackgroundVolumeID(), node.GetID())
                        self.assertIsNone(composite.GetForegroundVolumeID())
                        self.assertIsNone(composite.GetLabelVolumeID())
                liveComposite = liveWidget.sliceLogic().GetSliceCompositeNode()
                for fileName in self.UC1_OUTPUT_FILE_NAMES:
                    outputID = widget.logic.outputNode(fileName).GetID()
                    self.assertNotIn(outputID, (liveComposite.GetBackgroundVolumeID(),
                                                liveComposite.GetForegroundVolumeID()))

                renderer = widget._sliceViewRenderer(resultWidget)
                widget._onCaptureClicked()
                actor = widget._staleLineActor
                self.assertIsNotNone(actor, "No stale line was drawn while the capture processes")
                self.assertEqual(actor.GetInput(), self.STALE_RESULT_LINE)
                resultWidget.mrmlSliceNode().Modified()
                self._waitForUi(lambda: bool(renderer.HasViewProp(actor)),
                                "the stale line to reach the Tumour Delineation renderer")
                self.assertEqual(composite.GetBackgroundVolumeID(),
                                 widget.logic.outputNode("kmeans.bmp").GetID(),
                                 "The previous result left the view while the capture processes")

                self._finishCapture(session, seed=2)
                self.assertFalse(renderer.HasViewProp(actor), "The stale line outlived a new result")
            finally:
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_resultOfAnotherSizeIsFittedToTheView(self) -> None:
        """Each new result is framed for its own size, not the previous case's."""
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession() as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
                sliceNode = resultWidget.mrmlSliceNode()
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=1)
                firstFieldOfView = tuple(sliceNode.GetFieldOfView())

                # The configured cube is replaced on disk by a wider one.
                self._writeFixtureCalibratedCube(session["cubeFolder"], samples=12, lines=5)
                self._showFrame(session, 31)
                widget._onCaptureClicked()
                case, _ = self._finishCapture(session, seed=2)
                self.assertEqual((case.samples, case.lines), (12, 5))
                shownFieldOfView = tuple(sliceNode.GetFieldOfView())

                resultWidget.sliceLogic().FitSliceToBackground()
                fittedFieldOfView = tuple(sliceNode.GetFieldOfView())
                self.assertNotEqual(fittedFieldOfView, firstFieldOfView,
                                    "The two fixture cases need different framing")
                for shown, fitted in zip(shownFieldOfView, fittedFieldOfView, strict=True):
                    self.assertAlmostEqual(shown, fitted, places=3,
                                           msg="The new result kept the previous case's framing")
            finally:
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_switchingOutputWithinOneResultKeepsTheFraming(self) -> None:
        """All five outputs of one run are the same size, so none of them refits.

        The operator zooms into a region to read it, then steps through the
        stages of the same run. Refitting on every selection would throw that
        region away each time and make the stages impossible to compare.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession() as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
                sliceNode = resultWidget.mrmlSliceNode()
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=22)

                fitted = list(sliceNode.GetFieldOfView())
                sliceNode.SetFieldOfView(fitted[0] / 2.0, fitted[1] / 2.0, fitted[2])
                # Read back rather than trusting the request: the view keeps the
                # field of view consistent with its own aspect ratio.
                zoomed = list(sliceNode.GetFieldOfView())
                self.assertNotAlmostEqual(zoomed[0], fitted[0], places=3,
                                          msg="The zoom this test needs was not applied")

                for viewName in ("svm.bmp", "knn.bmp", "gtMap", "pca.bmp"):
                    widget._parameterNode.resultOutput = viewName
                    widget._onResultOutputChanged()
                    for shown, kept in zip(sliceNode.GetFieldOfView(), zoomed, strict=True):
                        self.assertAlmostEqual(
                            shown, kept, places=3,
                            msg=f"Choosing {viewName} refitted the view and lost the zoom")
            finally:
                widget._forgetResult()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_publishingErrorEndsCaptureAndKeepsPreviousResult(self) -> None:
        from unittest import mock

        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            firstCase, firstImages = self._finishCapture(session, seed=1)
            firstCapture = widget.logic.outputNode("imageRGB.bmp").GetAttribute("SLIAFlow.CaptureId")
            volumesBefore = {node.GetID() for node in
                             slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode")}

            self._showFrame(session, 31)
            widget._onCaptureClicked()
            original = slicer.util.updateVolumeFromArray
            calls = []

            def failOnThirdImage(node, array, *arguments, **options):
                calls.append(node)
                if len(calls) == 3:
                    raise RuntimeError("test: the MRML update failed")
                return original(node, array, *arguments, **options)

            with mock.patch.object(slicer.util, "updateVolumeFromArray", failOnThirdImage):
                self._finishCapture(session, seed=2)

            self.assertEqual(len(calls), 3, "The failure was not reached")
            self.assertFalse(widget.captureInProgress, "Capture stayed in progress")
            self.assertFalse(widget.liveViewFrozen, "LiveView stayed frozen")
            self.assertTrue(widget.ui.captureButton.enabled, "Capture stayed disabled")
            self.assertIn("test: the MRML update failed", widget.ui.statusLabel.text)
            self.assertEqual(widget.staleResultLine(), self.STALE_RESULT_LINE)
            for fileName in self.UC1_OUTPUT_FILE_NAMES:
                with self.subTest(output=fileName):
                    node = widget.logic.outputNode(fileName)
                    self.assertEqual(node.GetAttribute("SLIAFlow.CaptureId"), firstCapture)
                    self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"), firstCase.name)
                    np.testing.assert_array_equal(
                        np.array(slicer.util.arrayFromVolume(node))[0], firstImages[fileName],
                        f"{fileName} was partly replaced by a run that failed to publish",
                    )
            volumesAfter = {node.GetID() for node in
                            slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode")}
            self.assertEqual(volumesAfter, volumesBefore, "A failed publish left volumes behind")

            frame = self._showFrame(session, 32)
            np.testing.assert_array_equal(self._liveArray(widget), frame)

            widget._onCaptureClicked()
            case, images = self._finishCapture(session, seed=3)
            np.testing.assert_array_equal(
                np.array(slicer.util.arrayFromVolume(widget.logic.outputNode("svm.bmp")))[0],
                images["svm.bmp"],
            )
            self.assertEqual(widget.staleResultLine(), "")

    def test_surfacedFailureMessagesAreTranslated(self) -> None:
        """Every failure the operator reads goes through Slicer's translation."""
        from unittest import mock

        import slicer.i18n

        marker = "[translated] "

        def translate(context, text):
            return marker + text

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        messages = {}
        with mock.patch.object(slicer.i18n, "translate", translate), \
                self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            case = self._describeUc1Input(fixture["calibratedHeader"], fixture["buildRoot"])

            def refusal(label):
                run, *_ = self._startRun(fixture)
                with self.assertRaises(uc1Run.Uc1RunError) as raised:
                    run.start()
                messages[label] = str(raised.exception)

            fixture["executable"].rename(fixture["executable"].with_suffix(".off"))
            refusal("missing executable")
            fixture["executable"].with_suffix(".off").rename(fixture["executable"])
            weights = fixture["buildRoot"] / "svm_model" / "w_vector.bin"
            weights.write_bytes(b"\0" * 10)
            refusal("damaged model")
            weights.write_bytes(b"\0" * self.UC1_MODEL_FILE_SIZES["w_vector.bin"])
            fixture["lock"].write_text("12345\n", encoding="ascii")
            refusal("lock held")
            fixture["lock"].unlink()

            outcomes = {
                "exit code": lambda process: (process.emitOutput(stderr=b"boom\n"),
                                              process.emitFinished(3)),
                "crash": lambda process: process.emitFinished(0, crashed=True),
                "failed to start": lambda process: process.emitFailedToStart(),
                "path too long": lambda process: (process.emitOutput(stdout=b"Path too long\n"),
                                                  process.emitFinished(0)),
                "missing output": lambda process: process.emitFinished(0),
            }
            for label, finish in outcomes.items():
                run, _, build, processes, results = self._startRun(fixture)
                run.start()
                finish(processes[0])
                messages[label] = results[0].message

            build = uc1Run.Uc1Build(fixture["buildRoot"])
            outputDirectory = build.caseOutputDirectory(case.name)
            self._writeUc1Outputs(outputDirectory, overrides={
                "svm.bmp": self._uc1BmpBytes(self._fixtureImage(lines=2, samples=4))})
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                uc1Run.collectOutputs(build, case, time.time() - 60.0)
            messages["invalid output"] = str(raised.exception)

            run, _, build, processes, results = self._startRun(fixture, timeoutSec=0.05)
            run.start()
            deadline = time.monotonic() + 5.0
            while not results and time.monotonic() < deadline:
                slicer.app.processEvents()
                time.sleep(0.01)
            messages["timeout"] = results[0].message if results else ""

        for label, message in messages.items():
            with self.subTest(failure=label):
                self.assertTrue(message.startswith(marker), f"Not translated: {message!r}")

        with mock.patch.object(slicer.i18n, "translate", translate), \
                self._captureSession(cube=False) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            with self.subTest(failure="configured cube refused"):
                status = widget.ui.statusLabel.text
                self.assertIn(marker + "The configured cube", status)
                self.assertIn(marker + f"{self.CALIBRATED_CUBE_STEM}.hdr is missing", status)

    # --- Panel ------------------------------------------------------------

    def test_operatorPanelHasNoLinkDemoOrLayerControls(self) -> None:
        representation, _ = self._moduleRepresentationAndWidget()
        for name in (
            "liveSourceSelector",
            "connectLinksButton",
            "acquisitionStateValueLabel",
            "uc1StateValueLabel",
            "uc2StateValueLabel",
            "hsCubeStateValueLabel",
            "controlStateValueLabel",
            "linkWaitingLabel",
            "resultClassSpinBox",
            "demoModeCheckBox",
            "simulatedBannerLabel",
            "layerTable",
            "layerOpacitySlider",
            "bandSlider",
            "openIGTLinkUnavailableLabel",
            "resultBackgroundValueLabel",
        ):
            with self.subTest(control=name):
                # findChild raises for a missing name; findChildren reports none.
                self.assertEqual(slicer.util.findChildren(representation, name=name), [])

    def test_resultSelectorListsTheFiveOutputFilesAndTheGroundTruth(self) -> None:
        """The five UC1 outputs in the order UC1 writes them, then gtMap.

        gtMap comes last because it is the only entry UC1 did not produce, and
        the only one that is a layer over another rather than a picture of its
        own.
        """
        representation, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        selector = slicer.util.findChild(representation, "resultOutputSelector")
        self.assertIsNotNone(selector)
        self.assertEqual(
            tuple(selector.itemText(index) for index in range(selector.count)),
            (*self.UC1_OUTPUT_FILE_NAMES, "gtMap"),
        )

    def _groundTruthEntryOffered(self, widget) -> tuple:
        """(enabled, visible in the popup) of the gtMap entry in Delineation output."""
        selector = widget.ui.resultOutputSelector
        index = selector.findText("gtMap")
        self.assertGreaterEqual(index, 0, "The gtMap entry is not in the list at all")
        return bool(selector.model().item(index).isEnabled()), not selector.view().isRowHidden(index)

    def test_groundTruthEntryIsOfferedOnlyForACubeThatHasOne(self) -> None:
        """ADR-0004 decision 8: gtMap is offered only for a cube that carries one.

        002-04 has no gtMap. The entry stays in the list, because the panel's
        parameter binding selects by position, but it is hidden and cannot be
        chosen; a stored gtMap selection says the cube has no ground truth
        rather than that one could not be read.
        """
        for hasGroundTruth in (False, True):
            with self.subTest(groundTruth=hasGroundTruth), \
                    self._captureSession(groundTruth=hasGroundTruth) as session:
                widget = session["widget"]
                self.assertEqual(self._groundTruthEntryOffered(widget), (False, False),
                                 "gtMap is offered before there is a result")
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=15)
                self.assertEqual(self._groundTruthEntryOffered(widget),
                                 (hasGroundTruth, hasGroundTruth))
                try:
                    widget._parameterNode.resultOutput = "gtMap"
                    widget._onResultOutputChanged()
                    status = widget.ui.resultStatusLabel.text
                    if hasGroundTruth:
                        self.assertIsNotNone(widget._groundTruthNode())
                        self.assertIn("under the recorded ground truth", status)
                    else:
                        self.assertIsNone(widget.logic.groundTruthNode())
                        self.assertIn("has no ground truth", status)
                        self.assertNotIn("could not be read", status)
                        self.assertIn(widget._selectedOutput(), status)
                finally:
                    widget._parameterNode.resultOutput = parameterModule.DEFAULT_RESULT_OUTPUT
                    widget._onResultOutputChanged()
                widget._forgetResult()
                self.assertEqual(self._groundTruthEntryOffered(widget), (False, False),
                                 "gtMap is still offered after the result is gone")

    def test_resultStatusSaysLctfResultsAreNotValidated(self) -> None:
        """ADR-0004 decision 5: a UC1 result on the LCTF cube is behavioural only.

        Every line that describes a result on screen says so: a fresh one, one
        under its ground truth, one whose ground truth could not be read, and
        the previous result kept while a capture runs and after it fails.
        """
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            case, _ = self._finishCapture(session, seed=16)
            shown = {"capture status": widget.ui.statusLabel.text,
                     "result status": widget.ui.resultStatusLabel.text}
            try:
                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                self.assertIsNotNone(widget._groundTruthNode())
                shown["result under its ground truth"] = widget.ui.resultStatusLabel.text
                widget.logic.groundTruthNode().SetAttribute(
                    "SLIAFlow.CaptureId", "a-capture-that-is-not-this-one")
                widget._updateResultStatus()
                self.assertIn("could not be read", widget.ui.resultStatusLabel.text)
                shown["ground truth unreadable"] = widget.ui.resultStatusLabel.text

                widget._parameterNode.resultOutput = parameterModule.DEFAULT_RESULT_OUTPUT
                widget._onResultOutputChanged()
                widget._onCaptureClicked()
                self.assertIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
                shown["previous result while processing"] = widget.ui.resultStatusLabel.text
                self._finishCapture(session, exitCode=2)
                self.assertIn(self.STALE_STATUS_FRAGMENT, widget.ui.resultStatusLabel.text)
                shown["previous result after a failed capture"] = widget.ui.resultStatusLabel.text
            finally:
                widget._forgetResult()
            # Including the one for a cube without ground truth, which this
            # fixture's cube cannot reach.
            for name in ("CAPTURE_DONE_STATUS", "RESULT_STATUS", "RESULT_STALE_STATUS",
                         "GROUND_TRUTH_STATUS", "GROUND_TRUTH_MISSING_STATUS",
                         "NO_GROUND_TRUTH_STATUS"):
                # SLIA-036: the texts name the cube by a phrase; for the cube
                # on disk it is the wording they always had.
                shown[name] = getattr(widget, name).format(
                    cube=f"recorded cube {case.name}", Cube=f"Recorded cube {case.name}",
                    origin="simulated acquisition", file="svm.bmp", snapshot="snapshot.png")
        for label, text in shown.items():
            with self.subTest(status=label):
                self.assertIn(case.name, text)
                self.assertIn(self.NOT_VALIDATED_FRAGMENT, text)

    def test_bindingThePanelKeepsTheDeclaredDefaultOutput(self) -> None:
        """Manual step 6, 2026-09-17: the first result was shown as pca.bmp.

        connectGui builds the combo-box connector by clearing and refilling the
        box, which emits currentIndexChanged before the stored value is written
        back. The widget's own slot must not take that for an operator choice.
        """
        representation, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._parameterNode.resultOutput = parameterModule.DEFAULT_RESULT_OUTPUT
        # What opening the module, or reopening it after Close Scene, does.
        widget.setParameterNode(None)
        widget.initializeParameterNode()

        selector = slicer.util.findChild(representation, "resultOutputSelector")
        self.assertEqual(
            widget._parameterNode.resultOutput,
            parameterModule.DEFAULT_RESULT_OUTPUT,
            "Binding the panel overwrote the stored output selection",
        )
        self.assertEqual(selector.currentText, parameterModule.DEFAULT_RESULT_OUTPUT)
        self.assertEqual(widget._selectedOutput(), parameterModule.DEFAULT_RESULT_OUTPUT)

    def test_closingTheSceneClearsTheStatusPanel(self) -> None:
        """Manual step 11, 2026-09-17: the Done message outlived Close Scene."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        widget._setStatus(
            widget.CAPTURE_DONE_STATUS.format(cube="recorded cube 004-02", snapshot="output.png")
        )
        widget.onSceneStartClose()
        try:
            status = widget.ui.statusLabel.text
            self.assertNotIn("004-02", status, "Close Scene kept the previous result's status")
            self.assertEqual(
                status,
                widget.CAMERA_READY_STATUS
                if widget.logic.openCVAvailable()
                else widget.CAMERA_SUPPORT_MISSING_STATUS,
            )
        finally:
            widget.onSceneEndClose()
            widget.initializeParameterNode()

    # ----------------------------------------------------------------------
    # 2026-09-18: a panel says what it waits for, and a volume is its file
    # ----------------------------------------------------------------------

    # Words that belong to this repository, its partners or its plan, not to
    # what an operator is looking at.
    PANEL_TEXT_FORBIDDEN_WORDS = (
        "sliaflow", "slia-", "upm", "ulpgc", "uc1", "uc2", "port", "18948",
        "18949", "producer", "reserved", "task",
    )

    def test_panelTextNamesOnlyWhatThePanelWaitsFor(self) -> None:
        """Owner decision, 2026-09-18: the panels name the input, nothing else.

        A panel is read by someone standing in front of the screen. It tells
        them which input has not arrived; where the input comes from and which
        task will produce it are not theirs to read.
        """
        widget = self._moduleRepresentationAndWidget()[1]
        messages = dict(widget.RESERVED_PANEL_REASONS)
        messages[widget.LIVE_VIEW_NAME] = widget.LIVE_WAITING_MESSAGE
        messages[widget.RESULT_VIEW_NAME] = widget.WAITING_RESULT_MESSAGE
        self.assertEqual(set(messages), set(widget.VIEW_NAMES),
                         "A panel has no text of its own")

        for viewName, message in messages.items():
            with self.subTest(view=viewName):
                lowered = message.lower()
                self.assertIn("waiting for", lowered,
                              "The panel does not say what it is waiting for")
                for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
                    self.assertNotIn(word, lowered,
                                     f"The panel text carries {word!r}")

    def test_volumeNamesAreTheImageAndNothingElse(self) -> None:
        """A panel labels a volume by name, so the name is the file it holds."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishCapture(session, seed=6)

            for fileName in self.UC1_OUTPUT_FILE_NAMES:
                with self.subTest(output=fileName):
                    self.assertEqual(widget.logic.outputNode(fileName).GetName(), fileName)
            self.assertEqual(widget._parameterNode.liveVolume.GetName(),
                             widget.logic.LIVE_VOLUME_NAME)
            displayed = [widget._parameterNode.liveVolume, widget.logic.cubeNode()]
            displayed += [widget.logic.outputNode(name) for name in self.UC1_OUTPUT_FILE_NAMES]
            for node in displayed:
                self.assertNotIn("sliaflow", (node.GetName() or "").lower(),
                                 "A displayed volume is named after the module")

    def test_capturedCubeIsShownBandByBand(self) -> None:
        """The HS Cube panel shows the calibrated cube the capture stands for.

        SLIA-032: it is IUMA's calibrated float32 cube, shown with its stored
        values unchanged. Since SLIA-033 it is also the cube UC1 runs on. Its
        third axis is the band, which is what makes the panel scrollable, and it
        carries ADR-0004 decision 7 provenance.
        """
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            case = widget.logic.currentRun.case
            self.assertEqual(case.name, self.CALIBRATED_CUBE_NAME,
                             "UC1 ran on another cube than the one HS Cube shows")
            self.assertEqual(case.cube.headerPath, session["calibratedHeader"].resolve())
            try:
                node = widget.logic.cubeNode()
                self.assertIsNotNone(node, "No cube reached the scene")
                captureId = node.GetAttribute("SLIAFlow.CaptureId")
                self.assertTrue(captureId)
                self.assertEqual(node.GetName(), f"{self.CALIBRATED_CUBE_STEM}.dat")
                array = np.array(slicer.util.arrayFromVolume(node))
                expected = session["calibratedValues"]
                self.assertEqual(array.shape, expected.shape,
                                 "The cube's third axis is not the band")
                self.assertEqual(array.dtype, np.float32, "The stored float32 was converted")
                np.testing.assert_array_equal(array, expected)
                self.assertEqual(self._ijkToRasDirections(node), self.UPRIGHT_LIVE_DIRECTIONS)
                self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"),
                                 self.CALIBRATED_CUBE_NAME)
                self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "simulated")
                self.assertEqual(node.GetAttribute("SLIAFlow.SimulationDetail"),
                                 self.CALIBRATED_DETAIL)
                self.assertEqual(
                    tuple(float(value) for value in
                          node.GetAttribute("SLIAFlow.WavelengthsNm").split(",")),
                    tuple(float(value) for value in self.LCTF_WAVELENGTHS_NM),
                )
                self._finishCapture(session, seed=7)
                # The cube belongs to the capture the result belongs to.
                self.assertEqual(
                    widget.logic.outputNode("imageRGB.bmp").GetAttribute("SLIAFlow.CaptureId"),
                    captureId,
                )
            finally:
                widget._forgetCube()
            self.assertIsNone(widget.logic.cubeNode(), "The cube outlived the module")

    def test_groundTruthArrivesAsALabelLayerOverTheResult(self) -> None:
        """Choosing gtMap lays the case's labelling over the chosen output.

        It is a label map, not a third background, so the Label layer's own
        opacity and outline controls work on it and the result stays visible
        underneath. Class 0 is most of the image and is not a class, so it is
        given zero opacity in the colour table rather than painted white.
        """
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            case, _images = self._finishCapture(session, seed=11)
            try:
                node = widget.logic.groundTruthNode()
                self.assertIsNotNone(node, "No ground truth reached the scene")
                self.assertEqual(node.GetName(), "gtMap")
                self.assertTrue(node.IsA("vtkMRMLLabelMapVolumeNode"),
                                "The ground truth is not a label layer")
                array = np.array(slicer.util.arrayFromVolume(node))
                self.assertEqual(array.shape, (1, case.lines, case.samples))
                self.assertEqual(self._ijkToRasDirections(node),
                                 self.UPRIGHT_LIVE_DIRECTIONS,
                                 "The ground truth is not aligned with the result")
                # It belongs to the capture whose result it can be laid over.
                self.assertEqual(
                    node.GetAttribute("SLIAFlow.CaptureId"),
                    widget.logic.outputNode("imageRGB.bmp").GetAttribute("SLIAFlow.CaptureId"),
                )
                self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"), case.name)
                self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "simulated")

                colorNode = node.GetDisplayNode().GetColorNode()
                self.assertIsNotNone(colorNode, "The gtMap classes have no colour table")
                self.assertEqual(colorNode.GetNumberOfColors(),
                                 len(cubeModule.GROUND_TRUTH_CLASSES))
                for classId, className, (red, green, blue) in cubeModule.GROUND_TRUTH_CLASSES:
                    colour = [0.0] * 4
                    colorNode.GetColor(classId, colour)
                    self.assertEqual(colorNode.GetColorName(classId), className)
                    self.assertAlmostEqual(colour[0], red / 255.0, places=2)
                    self.assertAlmostEqual(colour[1], green / 255.0, places=2)
                    self.assertAlmostEqual(colour[2], blue / 255.0, places=2)
                expectedOpacity = [0.0] * 4
                colorNode.GetLookupTable().GetTableValue(
                    cubeModule.UNLABELLED_CLASS_ID, expectedOpacity)
                self.assertEqual(expectedOpacity[3], 0.0,
                                 "Unlabelled pixels would hide the result under white")
            finally:
                widget._forgetResult()
            self.assertIsNone(widget.logic.groundTruthNode(),
                              "The ground truth outlived the result")

    def test_groundTruthOverlaysTheOutputChosenLastRatherThanReplacingIt(self) -> None:
        """gtMap keeps the current output on the background layer.

        The comparison is between a classification and the labelling, so
        selecting gtMap must not take the classification off the screen.
        """
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishCapture(session, seed=12)
            try:
                widget._parameterNode.resultOutput = "svm.bmp"
                widget._onResultOutputChanged()
                self.assertEqual(widget._selectedOutput(), "svm.bmp")
                self.assertFalse(widget._groundTruthSelected())

                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                self.assertTrue(widget._groundTruthSelected())
                self.assertEqual(widget._selectedOutput(), "svm.bmp",
                                 "gtMap replaced the result instead of overlaying it")
                self.assertIn("svm.bmp", widget.ui.resultStatusLabel.text)

                widget._parameterNode.resultOutput = "knn.bmp"
                widget._onResultOutputChanged()
                self.assertFalse(widget._groundTruthSelected())
                self.assertEqual(widget._selectedOutput(), "knn.bmp")
            finally:
                widget._forgetResult()

    def test_groundTruthReachesTheResultPanelLabelLayer(self) -> None:
        """Choosing gtMap binds it to the Tumour Delineation Label layer.

        Everything else about the ground truth can be right -- the node class,
        its shape, its directions, its capture ID, its colour table -- while it
        is bound to no view at all, and the status line still says a comparison
        is on screen. This asserts the binding itself, on the panel the
        comparison is read on.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                resultWidget = layoutManager.sliceWidget(widget.RESULT_VIEW_NAME)
                composite = resultWidget.sliceLogic().GetSliceCompositeNode()
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=21)

                widget._parameterNode.resultOutput = "svm.bmp"
                widget._onResultOutputChanged()
                self.assertIsNone(composite.GetLabelVolumeID(),
                                  "An output selection left a label layer behind")

                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                groundTruth = widget.logic.groundTruthNode()
                self.assertIsNotNone(groundTruth, "No ground truth reached the scene")
                self.assertEqual(composite.GetLabelVolumeID(), groundTruth.GetID(),
                                 "gtMap is not on the Tumour Delineation Label layer")
                self.assertEqual(composite.GetBackgroundVolumeID(),
                                 widget.logic.outputNode("svm.bmp").GetID(),
                                 "gtMap replaced the output instead of overlaying it")
                self.assertAlmostEqual(composite.GetLabelOpacity(),
                                       widget.GROUND_TRUTH_LABEL_OPACITY, places=3)

                widget._parameterNode.resultOutput = "knn.bmp"
                widget._onResultOutputChanged()
                self.assertIsNone(composite.GetLabelVolumeID(),
                                  "gtMap stayed on the Label layer after it was deselected")
            finally:
                widget._forgetResult()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_cubePanelStaysAloneWhenGroundTruthIsSelected(self) -> None:
        """The cube is shown alone whatever the Delineation output box says.

        The ground truth belongs to the result panel. The cube's bands run
        along S, so a one-band label map placed in that stack is off the plane
        the operator scrolls: it would draw nothing and still be claimed.
        """
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                cubeWidget = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME)
                cubeComposite = cubeWidget.sliceLogic().GetSliceCompositeNode()
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=23)

                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                widget._showCube()
                self.assertIsNotNone(widget._groundTruthNode(),
                                     "This test needs a ground truth to be selectable")
                self.assertEqual(cubeComposite.GetBackgroundVolumeID(),
                                 widget.logic.cubeNode().GetID(),
                                 "The cube left its own panel")
                self.assertIsNone(cubeComposite.GetLabelVolumeID(),
                                  "The ground truth was laid over the cube")
                self.assertIsNone(cubeComposite.GetForegroundVolumeID())
            finally:
                widget._forgetResult()
                widget._forgetCube()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_groundTruthFromAnotherCaptureIsNotLaidOver(self) -> None:
        """A ground truth that is not this result's is not shown at all.

        Laying one case's labelling over another case's result would read as
        agreement or disagreement that was never measured.
        """
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishCapture(session, seed=13)
            try:
                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                self.assertIsNotNone(widget._groundTruthNode())
                widget.logic.groundTruthNode().SetAttribute(
                    "SLIAFlow.CaptureId", "a-capture-that-is-not-this-one")
                self.assertIsNone(widget._groundTruthNode(),
                                  "Another capture's ground truth was laid over the result")
                widget._updateResultStatus()
                self.assertIn("could not be read", widget.ui.resultStatusLabel.text)
            finally:
                widget._forgetResult()

    def test_unreadableGroundTruthDoesNotFailTheCapture(self) -> None:
        """Reading the ground truth is for the panel; the result does not need it."""
        with self._captureSession(groundTruth=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)

            def refuse(case, captureId):
                raise OSError("the ground truth could not be read")

            original = widget.logic.acceptGroundTruth
            widget.logic.acceptGroundTruth = refuse
            try:
                widget._onCaptureClicked()
                case, _images = self._finishCapture(session, seed=14)
            finally:
                widget.logic.acceptGroundTruth = original
            try:
                self.assertIsNone(widget.logic.groundTruthNode())
                self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"),
                                     "The result was lost with the ground truth")
                self.assertIn(case.name, widget.ui.statusLabel.text)
                widget._parameterNode.resultOutput = "gtMap"
                widget._onResultOutputChanged()
                self.assertIn("could not be read", widget.ui.resultStatusLabel.text)
            finally:
                widget._forgetResult()

    def test_unreadableCubeDoesNotFailTheCapture(self) -> None:
        """Reading the cube is for the panel; the run does not depend on it."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)

            def refuse(case, captureId):
                raise OSError("the cube file could not be read")

            original = widget.logic.acceptCube
            widget.logic.acceptCube = refuse
            try:
                widget._onCaptureClicked()
                self.assertTrue(widget.captureInProgress,
                                "An unreadable cube stopped the capture")
                self.assertIsNone(widget.logic.cubeNode())
                case, _images = self._finishCapture(session, seed=8)
            finally:
                widget.logic.acceptCube = original
            self.assertIn(case.name, widget.ui.statusLabel.text)
            self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"),
                                 "The result was lost with the cube")

    def test_cubeReachesTheCubePanelAndNowhereElse(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession() as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                cubeWidget = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME)
                composite = cubeWidget.sliceLogic().GetSliceCompositeNode()
                self.assertIsNone(composite.GetBackgroundVolumeID(),
                                  "The cube panel holds a volume before any capture")

                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishCapture(session, seed=9)

                node = widget.logic.cubeNode()
                self.assertEqual(composite.GetBackgroundVolumeID(), node.GetID())
                self.assertIsNone(composite.GetForegroundVolumeID())
                self.assertIsNone(composite.GetLabelVolumeID())
                self.assertEqual(widget.panelMessage(widget.CUBE_VIEW_NAME), "",
                                 "The waiting text stayed over the cube")
                for viewName in widget.VIEW_NAMES:
                    if viewName == widget.CUBE_VIEW_NAME:
                        continue
                    otherComposite = (
                        layoutManager.sliceWidget(viewName).sliceLogic().GetSliceCompositeNode()
                    )
                    self.assertNotIn(node.GetID(), (otherComposite.GetBackgroundVolumeID(),
                                                    otherComposite.GetForegroundVolumeID()),
                                     f"The cube reached {viewName}")
            finally:
                widget._forgetCube()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    # ----------------------------------------------------------------------
    # SLIA-032: the calibrated LCTF cube - bands, colour preview, pixel spectrum
    #
    # Every cube below is a placeholder fixture laid out like IUMA's calibrated
    # cube, written to a temporary directory. No test reads input/002-04.
    # ----------------------------------------------------------------------

    def test_calibratedCubeIsReadWithItsValuesUnchanged(self) -> None:
        """The reader hands back the stored float32 values and the header's wavelengths."""
        module = self._helperModule("SLIAFlowCalibratedCube")
        with self._fixtureDirectory() as root:
            header, values = self._writeFixtureCalibratedCube(root / self.CALIBRATED_CUBE_NAME)
            cube = module.loadCalibratedCube(header)
            self.assertEqual((cube.name, cube.samples, cube.lines, cube.bands),
                             (self.CALIBRATED_CUBE_NAME, 4, 3, len(self.LCTF_WAVELENGTHS_NM)))
            self.assertEqual(tuple(cube.wavelengths),
                             tuple(float(value) for value in self.LCTF_WAVELENGTHS_NM))

            array = module.readCalibratedCube(cube)
            self.assertEqual(array.dtype, np.float32)
            self.assertEqual(array.shape, values.shape)
            np.testing.assert_array_equal(array, values)

            # Read into a buffer the caller owns, as the volume's own is.
            buffer = np.zeros(values.shape, dtype=np.float32)
            self.assertIs(module.readCalibratedCube(cube, out=buffer), buffer)
            np.testing.assert_array_equal(buffer, values)

    def test_calibratedCubeRejectsIncompatibleContents(self) -> None:
        """A cube the display would misread is refused, each time naming the file."""
        module = self._helperModule("SLIAFlowCalibratedCube")
        full = len(self.LCTF_WAVELENGTHS_NM) * 3 * 4 * 4
        defects = {
            "uint16": dict(dataType=12),
            "bip": dict(interleave="bip"),
            "big-endian": dict(byteOrder=1),
            "header-offset": dict(headerOffset=10),
            "short-file": dict(dataBytes=full - 4),
            "long-file": dict(dataBytes=full + 4),
            "no-wavelengths": dict(wavelengths=None, bands=109),
            "too-few-wavelengths": dict(wavelengths=self.LCTF_WAVELENGTHS_NM[:-1], bands=109),
            # An empty entry beside 109 numbers is still not one number per band.
            "empty-wavelength-entry": dict(wavelengths=self.LCTF_WAVELENGTHS_NM[:50] + ("",)
                                           + self.LCTF_WAVELENGTHS_NM[50:], bands=109),
            "trailing-comma": dict(wavelengths=self.LCTF_WAVELENGTHS_NM + ("",), bands=109),
            "decreasing-wavelengths": dict(wavelengths=tuple(reversed(self.LCTF_WAVELENGTHS_NM))),
            "micrometres": dict(units="Micrometers"),
            "no-data-file": dict(dataSuffix=None),
        }
        with self._fixtureDirectory() as root:
            for name, options in defects.items():
                with self.subTest(defect=name):
                    header, _values = self._writeFixtureCalibratedCube(root / name, **options)
                    with self.assertRaises(module.CalibratedCubeError) as raised:
                        module.loadCalibratedCube(header)
                    self.assertIn(self.CALIBRATED_CUBE_STEM, str(raised.exception),
                                  f"{name} was refused without naming the file")
            with self.assertRaises(module.CalibratedCubeError):
                module.loadCalibratedCube(root / "absent" / f"{self.CALIBRATED_CUBE_STEM}.hdr")

            # A file cut short after the cube was described is refused again at
            # read time rather than reshaped.
            header, _values = self._writeFixtureCalibratedCube(root / "truncated-later")
            cube = module.loadCalibratedCube(header)
            cube.dataPath.write_bytes(b"\0" * 12)
            with self.assertRaises(module.CalibratedCubeError) as raised:
                module.readCalibratedCube(cube)
            self.assertIn("12 bytes", str(raised.exception))

    def test_colourPreviewUsesTheNamedBandsOnAFixedScale(self) -> None:
        """R, G and B are the bands nearest 650, 550 and 470 nm, on one fixed scale.

        The oracle is the card's rule, computed here from the fixture: the band
        index is (wavelength - 460) / 5 on the 002-04 grid, reflectance 0 is 0
        and 1.0 and above is 255, rounded half up.
        """
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            cubeNode = widget.logic.cubeNode()
            self.assertIsNotNone(cubeNode, "No cube reached the scene")
            preview = widget.logic.acceptColourPreview(cubeNode)
            try:
                array = np.array(slicer.util.arrayFromVolume(preview))
                values = session["calibratedValues"]
                self.assertEqual(array.dtype, np.uint8)
                self.assertEqual(array.shape, (1, values.shape[1], values.shape[2], 3))
                for channel, wavelength in enumerate(self.PREVIEW_WAVELENGTHS_NM):
                    band = (wavelength - self.LCTF_WAVELENGTHS_NM[0]) // 5
                    expected = np.floor(np.clip(values[band], 0.0, 1.0) * 255.0 + 0.5)
                    with self.subTest(channel="RGB"[channel], wavelength=wavelength):
                        np.testing.assert_array_equal(array[0, :, :, channel],
                                                      expected.astype(np.uint8))
                self.assertGreater(float(values.max()), 1.0,
                                   "The fixture does not exercise values above 1.0")
                self.assertEqual(self._ijkToRasDirections(preview), self.UPRIGHT_LIVE_DIRECTIONS)
                for attribute in ("SLIAFlow.DataOrigin", "SLIAFlow.RecordedCase",
                                  "SLIAFlow.SimulationDetail", "SLIAFlow.CaptureId"):
                    self.assertEqual(preview.GetAttribute(attribute),
                                     cubeNode.GetAttribute(attribute), attribute)
                self.assertIs(widget.logic.colourPreviewNode(), preview)
            finally:
                widget._forgetCube()
            self.assertIsNone(widget.logic.colourPreviewNode(),
                              "The colour preview outlived its cube")

    def _spectrumTableArrays(self, chartNode):
        series = chartNode.GetNthPlotSeriesNode(0)
        self.assertIsNotNone(series, "The chart has no series")
        table = series.GetTableNode()
        self.assertIsNotNone(table, "The series has no table")
        wavelengths = np.array(slicer.util.arrayFromTableColumn(table, series.GetXColumnName()))
        values = np.array(slicer.util.arrayFromTableColumn(table, series.GetYColumnName()))
        return table, wavelengths, values

    def test_pixelSpectrumIsTheStoredValues(self) -> None:
        """A pixel's spectrum is the stored values at that pixel, against the header grid."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            cubeNode = widget.logic.cubeNode()
            values = session["calibratedValues"]
            grid = np.array(self.LCTF_WAVELENGTHS_NM, dtype=np.float64)
            try:
                for column, row in ((0, 0), (3, 1), (2, 2)):
                    with self.subTest(column=column, row=row):
                        wavelengths, spectrum = widget.logic.pixelSpectrum(cubeNode, column, row)
                        np.testing.assert_array_equal(wavelengths, grid)
                        np.testing.assert_array_equal(spectrum, values[:, row, column])

                        chart = widget.logic.showPixelSpectrum(cubeNode, column, row)
                        table, plotted, plottedValues = self._spectrumTableArrays(chart)
                        np.testing.assert_array_equal(plotted, grid)
                        np.testing.assert_array_equal(plottedValues, values[:, row, column])
                        self.assertIn("nm", chart.GetXAxisTitle())
                        self.assertIn("Reflectance", chart.GetYAxisTitle())
                        self.assertEqual(table.GetAttribute("SLIAFlow.RecordedCase"),
                                         self.CALIBRATED_CUBE_NAME)
                        self.assertEqual(table.GetAttribute("SLIAFlow.DataOrigin"), "simulated")
                        self.assertEqual(table.GetAttribute("SLIAFlow.CaptureId"),
                                         cubeNode.GetAttribute("SLIAFlow.CaptureId"))
                with self.assertRaises(IndexError):
                    widget.logic.pixelSpectrum(cubeNode, 4, 0)
            finally:
                widget._forgetCube()

    def test_cubeIsShownEvenWhenUc1IsRefused(self) -> None:
        """The cube does not need UC1: a refused UC1 run still shows it."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            session["executable"].unlink()
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self.assertIn("build-uc1.ps1", widget.ui.statusLabel.text)
            self.assertEqual(session["processes"], [], "UC1 started without its executable")
            node = widget.logic.cubeNode()
            self.assertIsNotNone(node, "A refused UC1 case kept the cube off the panel")
            self.assertEqual(node.GetAttribute("SLIAFlow.CaptureId"), widget._captureId)

    @contextlib.contextmanager
    def _capturedPresentation(self, *, finish=True, prepare=None):
        """A capture session with the six-panel layout active and one Capture made."""
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession() as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                if prepare is not None:
                    prepare(session)
                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                if finish:
                    self._finishCapture(session, seed=31)
                yield session, layoutManager
            finally:
                widget._forgetResult()
                widget._forgetCube()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def _waitForCaption(self, widget, layoutManager, viewName, fragments):
        sliceWidget = layoutManager.sliceWidget(viewName)
        sliceWidget.mrmlSliceNode().Modified()
        self._waitForUi(
            lambda: all(fragment in widget.panelCaption(viewName) for fragment in fragments),
            f"the {viewName} caption to read {fragments!r}",
        )
        actor = widget._panelCaptionActors.get(viewName)
        self.assertIsNotNone(actor, f"{viewName} has no caption actor")
        self.assertEqual(actor.GetInput(), widget.panelCaption(viewName))
        self._waitForUi(
            lambda: bool(widget._sliceViewRenderer(sliceWidget).HasViewProp(actor)),
            f"the caption to reach the {viewName} renderer",
        )

    @staticmethod
    def _bandOffset(node, band):
        matrix = vtk.vtkMatrix4x4()
        node.GetIJKToRASMatrix(matrix)
        return matrix.MultiplyPoint((0.0, 0.0, float(band), 1.0))[2]

    def test_cubeCaptionNamesTheBandAndItsWavelength(self) -> None:
        """Scrolling HS Cube shows the band number and its wavelength on the view."""
        with self._capturedPresentation() as (session, layoutManager):
            widget = session["widget"]
            node = widget.logic.cubeNode()
            bands = len(self.LCTF_WAVELENGTHS_NM)
            middle = bands // 2
            # The panel opens at the middle band.
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, (
                f"Band {middle + 1} of {bands} - {self.LCTF_WAVELENGTHS_NM[middle]} nm",))
            sliceLogic = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME).sliceLogic()
            for band in (0, 38, bands - 1):
                with self.subTest(band=band):
                    sliceLogic.SetSliceOffset(self._bandOffset(node, band))
                    self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, (
                        f"Band {band + 1} of {bands} - {self.LCTF_WAVELENGTHS_NM[band]} nm",))

    def test_colourPreviewCaptionNamesItsWavelengths(self) -> None:
        """Colour preview replaces the bands on HS Cube and says what it is."""
        with self._capturedPresentation() as (session, layoutManager):
            widget = session["widget"]
            composite = layoutManager.sliceWidget(
                widget.CUBE_VIEW_NAME).sliceLogic().GetSliceCompositeNode()
            selector = widget.ui.cubeDisplaySelector
            self.assertEqual(selector.currentIndex, 0, "HS Cube does not open on the bands")
            try:
                selector.setCurrentIndex(1)
                preview = widget.logic.colourPreviewNode()
                self.assertIsNotNone(preview, "Choosing the colour preview built none")
                self.assertEqual(composite.GetBackgroundVolumeID(), preview.GetID())
                self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, (
                    "R 650 nm", "G 550 nm", "B 470 nm", "band composite, not a photograph",
                    self.CALIBRATED_CUBE_NAME))
                selector.setCurrentIndex(0)
                self.assertEqual(composite.GetBackgroundVolumeID(),
                                 widget.logic.cubeNode().GetID())
                self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, ("Band ",))
            finally:
                selector.setCurrentIndex(0)

    def test_clickedCubePixelIsThePixelUnderTheCursor(self) -> None:
        """A click on HS Cube plots the pixel drawn under it, and says whose values they are."""
        with self._capturedPresentation() as (session, layoutManager):
            widget = session["widget"]
            node = widget.logic.cubeNode()
            values = session["calibratedValues"]
            cubeWidget = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME)
            sliceView = cubeWidget.sliceView()
            cubeWidget.sliceLogic().SetSliceOffset(self._bandOffset(node, 10))
            matrix = vtk.vtkMatrix4x4()
            node.GetIJKToRASMatrix(matrix)

            def xyzOf(column, row):
                ras = matrix.MultiplyPoint((float(column), float(row), 10.0, 1.0))[:3]
                return list(sliceView.convertRASToXYZ(list(ras)))

            chart = None
            for column, row in ((0, 0), (3, 2), (1, 2)):
                with self.subTest(column=column, row=row):
                    widget._pickCubePixelAtXYZ(xyzOf(column, row))
                    chartID = widget._spectrumPlotWidget.mrmlPlotViewNode().GetPlotChartNodeID()
                    chart = slicer.mrmlScene.GetNodeByID(chartID)
                    self.assertIsNotNone(chart, "The plot shows no chart")
                    _table, _wavelengths, plotted = self._spectrumTableArrays(chart)
                    np.testing.assert_array_equal(plotted, values[:, row, column])
                    label = widget.ui.spectrumLabel.text
                    self.assertIn(self.CALIBRATED_CUBE_NAME, label)
                    self.assertIn("stored values", label)

            widget._pickCubePixelAtXYZ(xyzOf(-6, 1))
            self.assertIn("outside", widget.ui.spectrumLabel.text.lower())
            _table, _wavelengths, plotted = self._spectrumTableArrays(chart)
            np.testing.assert_array_equal(plotted, values[:, 2, 1],
                                          "A click outside the cube replaced the spectrum")

    def test_panelsNameTheCubeTheyShow(self) -> None:
        """HS Cube and Tumour Delineation both name the one cube, in operator words."""
        with self._capturedPresentation() as (session, layoutManager):
            widget = session["widget"]
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME,
                                 (self.CALIBRATED_CUBE_NAME,))
            self._waitForCaption(widget, layoutManager, widget.RESULT_VIEW_NAME,
                                 (self.CALIBRATED_CUBE_NAME,))
            for viewName in (widget.CUBE_VIEW_NAME, widget.RESULT_VIEW_NAME):
                lowered = widget.panelCaption(viewName).lower()
                for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
                    with self.subTest(view=viewName, word=word):
                        self.assertNotIn(word, lowered)

    def test_unreadableCubeIsExplainedOnThePanel(self) -> None:
        """A cube that cannot be read says why on HS Cube, and UC1 is not run on it."""
        def truncate(session):
            data = session["calibratedHeader"].with_suffix(".dat")
            data.write_bytes(data.read_bytes()[:-4])

        with self._capturedPresentation(finish=False, prepare=truncate) as (session, _layout):
            widget = session["widget"]
            self.assertIsNone(widget.logic.cubeNode())
            self.assertEqual(session["processes"], [], "UC1 ran on a cube that cannot be read")
            self.assertIn(f"{self.CALIBRATED_CUBE_STEM}.dat", widget.ui.statusLabel.text)
            message = widget.panelMessage(widget.CUBE_VIEW_NAME)
            self.assertIn(f"{self.CALIBRATED_CUBE_STEM}.dat", message)
            self.assertIn("bytes", message)
            for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
                self.assertNotIn(word, message.lower())

    # ----------------------------------------------------------------------
    # SLIA-035: the Connections section
    #
    # The state words, the defaults and the wording checked here are the ones
    # the SLIA-035 card specifies; they are written out rather than imported,
    # so the module and its tests cannot drift together. Every cube is a test
    # fixture that stands for no imagery.
    # ----------------------------------------------------------------------

    STATE_NOT_CONNECTED = "Not connected"
    STATE_WAITING = "Waiting for the app"
    STATE_NOT_RUNNING = "App not running"
    STATE_CONNECTED = "Connected"
    STATE_RECEIVING = "Receiving"
    STATE_CUBE_COMPLETE = "Cube complete"
    STATE_CUBE_INCOMPLETE = "Cube incomplete"
    STATE_ERROR = "Error"
    STAND_IN_MARK = " (stand-in)"
    # docs/hardware/acquisition_app_and_hardware.md section 4.
    APP_PORTS = {"LiveView": 18944, "Stereo": 18945, "HS Cube": 18946}
    # The band count of 002-04 (ADR-0004 decision 1).
    DEFAULT_EXPECTED_BANDS = 109
    # vtkMRMLIGTLConnectorNode.h at the pinned commit: StateOff, StateWaitConnection,
    # StateConnected; TypeNotDefined, TypeServer, TypeClient.
    IGTL_STATE_OFF, IGTL_STATE_WAITING, IGTL_STATE_CONNECTED = 0, 1, 2
    IGTL_TYPE_CLIENT = 2
    CONNECTION_TIMEOUT_SEC = 20.0

    def _connectionsModule(self):
        return self._helperModule("SLIAFlowConnections")

    def _observation(self, moment, *, name="HsCube", size=(4, 3, 1), components=1,
                     scalarType="float32", band=None, wavelength=None, simulated=False,
                     messageType="IMAGE"):
        return self._connectionsModule().MessageObservation(
            time=moment, deviceName=name, messageType=messageType, size=size,
            components=components, scalarType=scalarType, bandNumber=band,
            wavelengthNm=wavelength, simulated=simulated)

    def _monitor(self, channel="HS Cube", *, expectedBands=5, host="127.0.0.1", port=18946):
        return self._connectionsModule().ChannelMonitor(
            channel, host, port, expectedBands=expectedBands)

    def _connectedMonitor(self, channel="HS Cube", **options):
        monitor = self._monitor(channel, **options)
        monitor.setConnectorState(self.IGTL_STATE_CONNECTED, now=0.0)
        return monitor

    def _progress(self, received, declared=None, *, complete=False, incomplete=None,
                  previous=None):
        return self._helperModule("SLIAFlowReceivedCube").CubeProgress(
            received, declared, complete, incomplete, previous)

    # --- The row model, without a network --------------------------------

    def test_channelMonitorStatesFollowTheConnector(self) -> None:
        monitor = self._monitor("LiveView", port=18944)
        self.assertEqual(monitor.row(now=0.0).state, self.STATE_NOT_CONNECTED)

        monitor.setConnectorState(self.IGTL_STATE_WAITING, now=10.0)
        self.assertEqual(monitor.row(now=12.9).state, self.STATE_WAITING)
        row = monitor.row(now=13.0)
        self.assertEqual(row.state, self.STATE_NOT_RUNNING)
        self.assertIn("127.0.0.1:18944", row.detail)
        self.assertIn("keeps trying", row.detail)

        monitor.setConnectorState(self.IGTL_STATE_CONNECTED, now=14.0)
        self.assertEqual(monitor.row(now=14.0).state, self.STATE_CONNECTED)
        monitor.messageReceived(self._observation(15.0, name="LiveView", components=3,
                                                  scalarType="uint8"))
        self.assertEqual(monitor.row(now=16.9).state, self.STATE_RECEIVING)
        self.assertEqual(monitor.row(now=17.1).state, self.STATE_CONNECTED)

        # A lost connection is waiting again, timed from when it was lost.
        monitor.setConnectorState(self.IGTL_STATE_WAITING, now=20.0)
        self.assertEqual(monitor.row(now=21.0).state, self.STATE_WAITING)
        self.assertEqual(monitor.row(now=23.5).state, self.STATE_NOT_RUNNING)

        monitor.setConnectorState(self.IGTL_STATE_OFF, now=30.0)
        self.assertEqual(monitor.row(now=30.0).state, self.STATE_NOT_CONNECTED)

    def test_channelMonitorDescribesTheLastMessage(self) -> None:
        live = self._connectedMonitor("LiveView", port=18944)
        live.messageReceived(self._observation(10.0, name="LiveView", size=(1080, 1080, 1),
                                               components=3, scalarType="uint8"))
        row = live.row(now=10.3)
        self.assertEqual((row.port, row.channel), ("18944", "LiveView"))
        self.assertEqual(row.lastMessage, "LiveView - IMAGE 1080 x 1080 x 3 uint8 - 0.3 s ago")

        cube = self._connectedMonitor(expectedBands=109)
        cube.messageReceived(self._observation(10.0, size=(1080, 1080, 1), band=57,
                                               wavelength=740.0))
        self.assertEqual(cube.row(now=10.3).lastMessage,
                         "HsCube - IMAGE 1080 x 1080 float32 - band 57, 740 nm - 0.3 s ago")

    def test_channelMonitorMeasuresTheMessageRate(self) -> None:
        live = self._connectedMonitor("LiveView", port=18944)
        self.assertEqual(live.row(now=0.0).received, "-")
        for index in range(10):
            live.messageReceived(self._observation(index * 0.1, name="LiveView", components=3,
                                                   scalarType="uint8"))
        self.assertEqual(live.row(now=0.95).received, "10.0 frames/s")
        # Only the last 5 s count.
        self.assertEqual(live.row(now=7.0).received, "-")

        cube = self._connectedMonitor(expectedBands=109)
        for index in range(5):
            cube.messageReceived(self._observation(index * 0.5, band=index + 1))
        cube.setCubeProgress(self._progress(5, 109))
        self.assertEqual(cube.row(now=2.1).received, "5 / 109 bands - 2.0 bands/s")

    def test_channelMonitorFollowsTheCubeProgress(self) -> None:
        """SLIA-036: the HS Cube row says what the reader's assembler holds."""
        cube = self._connectedMonitor(expectedBands=109)
        row = cube.row(now=0.5)
        self.assertEqual((row.state, row.received), (self.STATE_CONNECTED, "0 / 109 bands"))

        # The band count the messages declare replaces the setting.
        cube.messageReceived(self._observation(1.0, band=7))
        cube.setCubeProgress(self._progress(7, 12))
        row = cube.row(now=1.5)
        self.assertEqual(row.state, self.STATE_RECEIVING)
        self.assertTrue(row.received.startswith("7 / 12 bands"), row.received)

        cube.setCubeProgress(self._progress(7, 12, incomplete="Missing bands: 3, 5, 9-11."))
        row = cube.row(now=16.0)
        self.assertEqual(row.state, self.STATE_CUBE_INCOMPLETE)
        self.assertIn("Missing bands: 3, 5, 9-11.", row.detail)

        cube.messageRefused(self._observation(17.0, name="HsCube", messageType="STRING",
                                              size=None, components=None, scalarType=None),
                            "a STRING message, not an IMAGE")
        row = cube.row(now=17.1)
        self.assertEqual(row.state, self.STATE_ERROR)
        self.assertIn("Refused a STRING message, not an IMAGE", row.detail)
        self.assertIn("unchanged", row.detail)

        # An accepted band clears the refusal; the cube thrown away is still named.
        cube.messageReceived(self._observation(18.0, band=1))
        cube.setCubeProgress(self._progress(1, 12, previous="Missing bands: 3."))
        row = cube.row(now=18.1)
        self.assertEqual(row.state, self.STATE_RECEIVING)
        self.assertIn("previous cube was incomplete", row.detail)
        self.assertIn("Missing bands: 3.", row.detail)

        cube.setCubeProgress(self._progress(12, 12, complete=True))
        row = cube.row(now=18.2)
        self.assertEqual(row.state, self.STATE_CUBE_COMPLETE)
        self.assertEqual(row.detail, "")
        self.assertTrue(row.received.startswith("12 / 12 bands"), row.received)

    def test_channelMonitorNamesMissingBandsWhenTheAppLeaves(self) -> None:
        """SLIA-036: a connection that closed mid-cube still names the bands the cube lacked."""
        cube = self._connectedMonitor(expectedBands=12)
        cube.messageReceived(self._observation(1.0, band=5))
        cube.setCubeProgress(self._progress(5, 12))
        # As the reader reports it: waiting again, the half cube thrown away.
        cube.setConnectorState(self.IGTL_STATE_WAITING, now=2.0)
        cube.setCubeProgress(self._progress(5, 12, incomplete="Missing bands: 6-12."))
        row = cube.row(now=2.5)
        self.assertEqual(row.state, self.STATE_WAITING)
        self.assertIn("last cube was incomplete", row.detail)
        self.assertIn("Missing bands: 6-12.", row.detail)
        row = cube.row(now=5.5)
        self.assertEqual(row.state, self.STATE_NOT_RUNNING)
        self.assertIn("Nothing answers on 127.0.0.1:18946", row.detail)
        self.assertIn("Missing bands: 6-12.", row.detail)

        # A connection that closed after a complete cube has nothing to add.
        complete = self._connectedMonitor(expectedBands=12)
        complete.setCubeProgress(self._progress(12, 12, complete=True))
        complete.setConnectorState(self.IGTL_STATE_WAITING, now=2.0)
        self.assertEqual(complete.row(now=2.5).detail, "")

    def test_channelMonitorMarksTheStandIn(self) -> None:
        live = self._connectedMonitor("LiveView", port=18944)
        live.messageReceived(self._observation(1.0, name="LiveView", components=3,
                                               scalarType="uint8", simulated=True))
        self.assertEqual(live.row(now=1.1).state, self.STATE_RECEIVING + self.STAND_IN_MARK)
        live.messageReceived(self._observation(2.0, name="LiveView", components=3,
                                               scalarType="uint8"))
        self.assertEqual(live.row(now=2.1).state, self.STATE_RECEIVING)

    def test_channelMonitorForgetsThePreviousConnection(self) -> None:
        cube = self._connectedMonitor(expectedBands=3)
        for band in (1, 2, 3):
            cube.messageReceived(self._observation(float(band), band=band, simulated=True))
        cube.setCubeProgress(self._progress(3, 3, complete=True))
        self.assertEqual(cube.row(now=3.1).state, self.STATE_CUBE_COMPLETE + self.STAND_IN_MARK)

        # A lost connection still shows what it last delivered.
        cube.setConnectorState(self.IGTL_STATE_WAITING, now=4.0)
        self.assertTrue(cube.row(now=4.1).received.startswith("3 / 3 bands"))

        # A new connection may be another sender, so nothing is carried over.
        cube.setConnectorState(self.IGTL_STATE_CONNECTED, now=8.0)
        row = cube.row(now=8.1)
        self.assertEqual(row.state, self.STATE_CONNECTED)
        self.assertEqual(row.lastMessage, "-")
        self.assertEqual(row.received, "0 / 3 bands")
        cube.messageReceived(self._observation(9.0, band=1))
        cube.setCubeProgress(self._progress(1, 3))
        row = cube.row(now=9.1)
        self.assertEqual(row.state, self.STATE_RECEIVING)
        self.assertEqual(row.received, "1 / 3 bands")

        live = self._connectedMonitor("LiveView", port=18944)
        live.messageReceived(self._observation(1.0, name="LiveView", components=3,
                                               scalarType="uint8", simulated=True))
        live.setConnectorState(self.IGTL_STATE_WAITING, now=2.0)
        live.setConnectorState(self.IGTL_STATE_CONNECTED, now=6.0)
        self.assertEqual(live.row(now=6.1).state, self.STATE_CONNECTED)

    def test_connectionsWithoutOpenIGTLinkSayWhy(self) -> None:
        connections = self._connectionsModule().SLIAFlowConnections(
            openIGTLinkAvailable=lambda: False)
        connections.configure("127.0.0.1", dict(self.APP_PORTS), self.DEFAULT_EXPECTED_BANDS)
        self.assertFalse(connections.connect())
        self.assertFalse(connections.connected)
        rows = connections.rows()
        self.assertEqual([row.channel for row in rows], list(self.APP_PORTS))
        for row in rows:
            with self.subTest(channel=row.channel):
                self.assertEqual(row.state, self.STATE_ERROR)
                self.assertIn("OpenIGTLink is not available", row.detail)

    def test_connectionsRefuseConflictingSettings(self) -> None:
        self.assertTrue(hasattr(slicer, "vtkMRMLIGTLConnectorNode"),
                        "OpenIGTLinkIF is not loaded; run-slicer-tests.ps1 must load it")
        connections = self._connectionsModule().SLIAFlowConnections()
        for host, ports, fragment in (
            ("127.0.0.1", {"LiveView": 18944, "Stereo": 18944, "HS Cube": 18946}, "18944"),
            ("  ", dict(self.APP_PORTS), "host"),
        ):
            with self.subTest(host=host, ports=ports):
                connections.configure(host, ports, self.DEFAULT_EXPECTED_BANDS)
                self.assertFalse(connections.connect())
                self.assertEqual(connections.connectorNodes(), [])
                self.assertEqual(
                    [node.GetName() for node in slicer.util.getNodesByClass("vtkMRMLIGTLConnectorNode")
                     if node.GetState() != self.IGTL_STATE_OFF], [])
                self.assertIn(self.STATE_ERROR, {row.state for row in connections.rows()})
                self.assertTrue(any(fragment in row.detail for row in connections.rows()))

    # --- Real connectors ---------------------------------------------------

    def test_openIGTLinkIFIsLoaded(self) -> None:
        """The connector tests below must run, never pass by being skipped."""
        self.assertTrue(hasattr(slicer, "vtkMRMLIGTLConnectorNode"),
                        "OpenIGTLinkIF is not loaded in this Slicer")
        self.assertIn("OpenIGTLinkIF", slicer.util.modulePath("OpenIGTLinkIF"))

    @staticmethod
    def _freeBasePort() -> int:
        """A port P such that P, P + 1 and P + 2 are free at this moment."""
        import socket
        for _attempt in range(50):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                base = probe.getsockname()[1]
            if base + 2 > 65535:
                continue
            held = []
            try:
                for offset in range(3):
                    candidate = socket.socket()
                    held.append(candidate)
                    candidate.bind(("127.0.0.1", base + offset))
            except OSError:
                continue
            finally:
                for candidate in held:
                    candidate.close()
            return base
        raise AssertionError("No three consecutive free local ports were found.")

    @contextlib.contextmanager
    def _runningVenvPython(self, arguments, description):
        """A process of the repository .venv Python, from once it printed "ready" to the block's end."""
        import subprocess
        import threading

        uc1Run = self._helperModule("SLIAFlowUc1Run")
        root = uc1Run.findRepositoryRoot(Path(__file__))
        python = root / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            self.fail(f"{description} runs under the repository .venv, and {python} is missing.")
        # Slicer's own PYTHONHOME and PYTHONPATH would make the .venv
        # interpreter load Slicer's standard library.
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("PYTHON")}
        environment["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [str(python)] + arguments, cwd=str(root / "tools" / "simulators"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = []
        reader = threading.Thread(target=lambda: output.extend(process.stdout), daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
            while not any("ready" in line for line in output):
                if process.poll() is not None or time.monotonic() > deadline:
                    self.fail(f"{description} did not start:\n" + "".join(output))
                time.sleep(0.05)
            yield output
        finally:
            process.terminate()
            process.wait(timeout=10)

    def _writeFixtureRawCube(self, folder: Path, *, bands=5, samples=4, lines=3):
        """A placeholder uint16 cube laid out like the raw cube the app sends today."""
        folder.mkdir(parents=True, exist_ok=True)
        values = ((np.arange(bands * lines * samples) * 37) % 4096).astype("<u2").reshape(
            bands, lines, samples)
        header = folder / "raw_data.hdr"
        header.write_text(
            "ENVI\n"
            f"samples = {samples}\nlines = {lines}\nbands = {bands}\nheader offset = 0\n"
            "data type = 12\ninterleave = bsq\nbyte order = 0\n"
            "wavelength = {" + ", ".join(str(value) for value in self.LCTF_WAVELENGTHS_NM[:bands])
            + "}\n", encoding="ascii")
        values.tofile(folder / "raw_data.dat")
        return header, values

    @contextlib.contextmanager
    def _runningStandIn(self, *, bands=5, dropBands="", bandInterval=0.05, frameRate=20,
                        appHeader=False, raw=False, basePort=None, samples=4, lines=3):
        """The stand-in for IUMA's app, from the repository .venv, on free ports.

        `appHeader` sends HsCube exactly as the app does (SLIA-036), `raw` a
        uint16 cube, and `basePort` reuses a port pair a test already knows.
        `samples` and `lines` size a calibrated cube.
        """
        with self._fixtureDirectory() as folder:
            if raw:
                header, values = self._writeFixtureRawCube(folder / "cube", bands=bands)
            else:
                header, values = self._writeFixtureCalibratedCube(
                    folder / "cube", wavelengths=self.LCTF_WAVELENGTHS_NM[:bands],
                    samples=samples, lines=lines)
            basePort = self._freeBasePort() if basePort is None else basePort
            arguments = ["-m", "stratum_sim.iuma_app_standin", "--cube", str(header),
                         "--base-port", str(basePort), "--frame-rate", str(frameRate),
                         "--band-interval", str(bandInterval), "--cube-interval", "600"]
            if dropBands:
                arguments += ["--drop-bands", dropBands]
            if appHeader:
                arguments.append("--app-header")
            with self._runningVenvPython(arguments, "The stand-in") as output:
                yield {"basePort": basePort, "values": values, "output": output}

    @contextlib.contextmanager
    def _connectionSettings(self, widget, **values):
        """Set the Connections settings for one test and put the previous ones back."""
        widget.initializeParameterNode()
        parameters = widget._parameterNode
        names = ("igtlHost", "liveViewPort", "stereoPort", "hsCubePort", "expectedBands")
        previous = {name: getattr(parameters, name) for name in names}
        connections = widget.logic.connections
        timings = {name: getattr(connections, name)
                   for name in ("notRunningGraceSec", "cubeIdleSec")}
        try:
            for name, value in values.items():
                if name in timings:
                    setattr(connections, name, value)
                else:
                    setattr(parameters, name, value)
            widget._refreshConnections()
            yield parameters
        finally:
            if connections.connected:
                widget._onConnectClicked()
            for name, value in timings.items():
                setattr(connections, name, value)
            widget.initializeParameterNode()
            for name, value in previous.items():
                setattr(widget._parameterNode, name, value)
            widget._refreshConnections()

    @staticmethod
    def _standInSettings(standIn, **values):
        base = standIn["basePort"]
        values.setdefault("liveViewPort", base)
        values.setdefault("stereoPort", base + 1)
        values.setdefault("hsCubePort", base + 2)
        values.setdefault("expectedBands", 5)
        return values

    @staticmethod
    def _connectionRows(widget) -> list:
        table = widget.ui.connectionsTable
        keys = ("port", "channel", "state", "lastMessage", "received")
        rows = []
        for row in range(table.rowCount):
            cells = [table.item(row, column) for column in range(len(keys))]
            rows.append({key: (cell.text() if cell is not None else "")
                         for key, cell in zip(keys, cells, strict=True)})
        return rows

    def _rowFor(self, widget, channel):
        for row in self._connectionRows(widget):
            if row["channel"] == channel:
                return row
        return None

    def _waitForRow(self, widget, channel, predicate, description):
        deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
        while time.monotonic() < deadline:
            slicer.app.processEvents()
            widget._refreshConnections()
            row = self._rowFor(widget, channel)
            if row is not None and predicate(row):
                return row
            time.sleep(0.01)
        self.fail(f"Timed out waiting for {description}; rows: {self._connectionRows(widget)}; "
                  f"detail: {widget.ui.connectionsDetailLabel.text}")

    @staticmethod
    def _moduleConnectors():
        return [node for node in slicer.util.getNodesByClass("vtkMRMLIGTLConnectorNode")
                if node.GetAttribute("SLIAFlow.Owner") == "Connections"]

    @staticmethod
    def _incomingNodeIds(connectors) -> list:
        return [connector.GetIncomingMRMLNode(index).GetID()
                for connector in connectors
                for index in range(connector.GetNumberOfIncomingMRMLNodes())]

    def test_connectionsCreateOneClientPerConfiguredPort(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn, stereoPort=0)):
            base = standIn["basePort"]
            rows = self._connectionRows(widget)
            self.assertEqual([(row["port"], row["channel"]) for row in rows],
                             [(str(base), "LiveView"), (str(base + 2), "HS Cube")])
            self.assertEqual({row["state"] for row in rows}, {self.STATE_NOT_CONNECTED})
            # Listed, stopped, before Connect, so that OpenIGTLinkIF shows the
            # ports while disconnected (owner request, 2026-09-25).
            listed = self._moduleConnectors()
            self.assertEqual(sorted(node.GetServerPort() for node in listed), [base, base + 2],
                             "The connectors are not listed before Connect")
            self.assertEqual({node.GetState() for node in listed}, {self.IGTL_STATE_OFF})
            self.assertEqual(
                sorted(node.GetName() for node in listed),
                [f"SLIAFlow HS Cube ({base + 2})", f"SLIAFlow LiveView ({base})"])

            widget._onConnectClicked()
            connectors = self._moduleConnectors()
            self.assertEqual({node.GetID() for node in connectors},
                             {node.GetID() for node in listed},
                             "Connect did not start the listed connectors")
            self.assertEqual(sorted(node.GetServerPort() for node in connectors),
                             [base, base + 2])
            for node in connectors:
                with self.subTest(port=node.GetServerPort()):
                    self.assertEqual(node.GetType(), self.IGTL_TYPE_CLIENT)
                    self.assertEqual(node.GetServerHostname(), "127.0.0.1")
                    self.assertFalse(node.GetSaveWithScene())
            # SLIA-036: SLIAFlow's own reader is the HS Cube port's one client.
            (cubeConnector,) = [node for node in connectors if node.GetServerPort() == base + 2]
            self.assertEqual(cubeConnector.GetState(), self.IGTL_STATE_OFF,
                             "Connect started the HS Cube connector")
            for control in ("connectionsHostLineEdit", "liveViewPortSpinBox",
                            "stereoPortSpinBox", "hsCubePortSpinBox", "expectedBandsSpinBox"):
                with self.subTest(control=control):
                    self.assertFalse(getattr(widget.ui, control).enabled,
                                     "A setting can be edited while connected")
            self.assertEqual(widget.ui.connectButton.text, "Disconnect")
            self._waitForRow(widget, "LiveView",
                             lambda row: row["state"].startswith(self.STATE_RECEIVING),
                             "LiveView to receive")

    def test_connectTakesOverAConnectorStartedInOpenIGTLinkIF(self) -> None:
        """A listed connector switched on in OpenIGTLinkIF does not make Connect fail."""
        _, widget = self._moduleRepresentationAndWidget()
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn, stereoPort=0, hsCubePort=0)):
            (listed,) = self._moduleConnectors()
            self.assertTrue(listed.Start())
            # As an operator would, Connect comes after the connector received
            # a frame. Stopped the instant it connected, OpenIGTLinkIO's Stop()
            # never returns (2026-10-06, the suite hung here).
            deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
            while (listed.GetNumberOfIncomingMRMLNodes() == 0
                   and time.monotonic() < deadline):
                slicer.app.processEvents()
                time.sleep(0.02)
            self.assertGreater(listed.GetNumberOfIncomingMRMLNodes(), 0,
                               "The connector started as in OpenIGTLinkIF received nothing")
            widget._onConnectClicked()
            row = self._waitForRow(widget, "LiveView",
                                   lambda row: row["state"] != self.STATE_WAITING,
                                   "LiveView to leave Waiting")
            self.assertTrue(row["state"].startswith(self.STATE_RECEIVING)
                            or row["state"].startswith(self.STATE_CONNECTED),
                            f"{row['state']}: {widget.ui.connectionsDetailLabel.text}")
            self.assertEqual(self._moduleConnectors(), [listed])

    def test_connectionsSayTheAppIsNotRunning(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        port = self._freeBasePort()
        with self._connectionSettings(widget, liveViewPort=port, stereoPort=0, hsCubePort=0,
                                      notRunningGraceSec=0.5):
            widget._onConnectClicked()
            self.assertEqual(self._rowFor(widget, "LiveView")["state"], self.STATE_WAITING)
            self._waitForRow(widget, "LiveView",
                             lambda row: row["state"] == self.STATE_NOT_RUNNING,
                             "LiveView to say the app is not running")
            self.assertIn(f"127.0.0.1:{port}", widget.ui.connectionsDetailLabel.text)

    def test_connectionsRowsFollowTheStandIn(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn)):
            widget._onConnectClicked()
            cube = self._waitForRow(
                widget, "HS Cube",
                lambda row: row["state"] == self.STATE_CUBE_COMPLETE + self.STAND_IN_MARK,
                "HS Cube to complete")
            self.assertTrue(cube["received"].startswith("5 / 5 bands"), cube["received"])
            self.assertTrue(cube["lastMessage"].startswith(
                "HsCube - IMAGE 4 x 3 float32 - band 5, 480 nm - "), cube["lastMessage"])
            for channel, expected in (("LiveView", "LiveView - IMAGE 4 x 3 x 3 uint8 - "),
                                      ("Stereo", "Steroscopic - IMAGE 8 x 3 x 3 uint8 - ")):
                with self.subTest(channel=channel):
                    row = self._waitForRow(
                        widget, channel,
                        lambda row: row["state"] == self.STATE_RECEIVING + self.STAND_IN_MARK
                        and row["received"].endswith("frames/s"),
                        f"{channel} to receive frames")
                    self.assertTrue(row["lastMessage"].startswith(expected), row["lastMessage"])

    def test_connectionsCountBandsTheStandInDrops(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        # 2 s of silence ends the cube: a band never takes that long to come
        # after the one before it, even on a loaded machine (1.0 was flaky).
        with self._runningStandIn(dropBands="3") as standIn, self._connectionSettings(
                widget, cubeIdleSec=2.0, **self._standInSettings(standIn)):
            widget._onConnectClicked()
            cube = self._waitForRow(
                widget, "HS Cube",
                lambda row: row["state"] == self.STATE_CUBE_INCOMPLETE + self.STAND_IN_MARK,
                "HS Cube to report an incomplete cube")
            self.assertTrue(cube["received"].startswith("4 / 5 bands"), cube["received"])
            self.assertIn("Missing bands: 3", widget.ui.connectionsDetailLabel.text)

    def test_connectionsForgetASenderThatLeft(self) -> None:
        """The stand-in leaves, and a sender in the app's own form takes its port.

        The new sender sends no metadata, so nothing the stand-in said, its
        simulated mark included, may carry over to it.
        """
        _, widget = self._moduleRepresentationAndWidget()
        standInRun = self._runningStandIn()
        standIn = standInRun.__enter__()
        try:
            basePort = standIn["basePort"]
            with self._connectionSettings(widget, **self._standInSettings(
                    standIn, liveViewPort=0, stereoPort=0)):
                widget._onConnectClicked()
                self._waitForRow(
                    widget, "HS Cube",
                    lambda row: row["state"] == self.STATE_CUBE_COMPLETE + self.STAND_IN_MARK,
                    "HS Cube to complete")
                standInRun.__exit__(None, None, None)
                standInRun = None
                self._waitForRow(
                    widget, "HS Cube",
                    lambda row: row["state"] in (self.STATE_WAITING, self.STATE_NOT_RUNNING),
                    "HS Cube to lose the stand-in")

                with self._runningStandIn(appHeader=True, basePort=basePort):
                    row = self._waitForRow(
                        widget, "HS Cube",
                        lambda row: row["state"].startswith(self.STATE_CUBE_COMPLETE),
                        "HS Cube to complete from the app-form sender")
                    self.assertEqual(row["state"], self.STATE_CUBE_COMPLETE,
                                     "The stand-in's mark outlived its connection")
                    self.assertTrue(row["lastMessage"].startswith(
                        "HsCube - IMAGE 4 x 3 float32 - band 5 - "), row["lastMessage"])
                    self.assertNotIn(" nm", row["lastMessage"])
        finally:
            if standInRun is not None:
                standInRun.__exit__(None, None, None)

    def test_hsCubeConnectorIsListedButNeverStarted(self) -> None:
        """SLIA-036: the app serves one client per port, and SLIAFlow's reader is it."""
        _, widget = self._moduleRepresentationAndWidget()
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn, liveViewPort=0, stereoPort=0)):
            (connector,) = self._moduleConnectors()
            self.assertEqual(connector.GetServerPort(), standIn["basePort"] + 2)
            widget._onConnectClicked()
            self._waitForRow(widget, "HS Cube",
                             lambda row: row["state"].startswith(self.STATE_CUBE_COMPLETE),
                             "HS Cube to complete")
            self.assertEqual(connector.GetState(), self.IGTL_STATE_OFF,
                             "The HS Cube connector was started")
            self.assertTrue(slicer.mrmlScene.IsNodePresent(connector), "The connector is not listed")
            # Ticked Active in OpenIGTLinkIF: SLIAFlow stops it and says why,
            # but not at once. OpenIGTLinkIO's Stop() never returns when called
            # just after the connector connected (2026-10-06, the suite hung).
            connector.Start()
            widget._refreshConnections()
            self.assertNotEqual(connector.GetState(), self.IGTL_STATE_OFF,
                                "Stopped at once, inside OpenIGTLinkIO's Stop() race")
            deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
            while (connector.GetState() != self.IGTL_STATE_OFF
                   and time.monotonic() < deadline):
                slicer.app.processEvents()
                widget._refreshConnections()
                time.sleep(0.05)
            self.assertEqual(connector.GetState(), self.IGTL_STATE_OFF)
            self.assertIn("stopped the HS Cube connector", widget.ui.connectionsDetailLabel.text)

    def test_connectionsCloseOnEveryPath(self) -> None:
        """Disconnect stops the listed connectors, scene close lists new ones, quit removes them."""
        _, widget = self._moduleRepresentationAndWidget()

        def disconnectButton():
            widget._onConnectClicked()

        def sceneClose():
            slicer.mrmlScene.Clear()
            widget.initializeParameterNode()

        def applicationQuit():
            widget._onAboutToQuit()

        for path in (disconnectButton, sceneClose, applicationQuit):
            with self.subTest(path=path.__name__), self._runningStandIn() as standIn, (
                    self._connectionSettings(widget, **self._standInSettings(standIn))):
                # The LiveView connector adopts a vector volume of its device's
                # name; the HS Cube port is read without any node (SLIA-036).
                existing = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "LiveView")
                existingId = existing.GetID()
                try:
                    self._assertConnectionsClose(widget, path, existingId,
                                                 keepsConnectors=path is disconnectButton,
                                                 closesScene=path is sceneClose)
                finally:
                    # The next path's own LiveView node must be the first by that name.
                    if slicer.mrmlScene.GetNodeByID(existingId) is not None:
                        slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetNodeByID(existingId))

    def _assertConnectionsClose(self, widget, path, existingId, *, keepsConnectors,
                                closesScene) -> None:
        """Connect to the stand-in, take `path`, and check what it left."""
        widget._onConnectClicked()
        self._waitForRow(widget, "HS Cube",
                         lambda row: row["state"].startswith(self.STATE_CUBE_COMPLETE),
                         "HS Cube to complete")
        self._waitForRow(widget, "LiveView",
                         lambda row: row["state"].startswith(self.STATE_RECEIVING),
                         "LiveView to receive")
        before = self._moduleConnectors()
        received = self._incomingNodeIds(before)
        self.assertIn(existingId, received, "The connector did not take the LiveView node")
        reader = widget.logic.connections.cubeReader
        self.assertIsNotNone(reader, "Connect started no HS Cube reader")
        path()
        self.assertFalse(widget.logic.connections.connected)
        self.assertIsNone(widget.logic.connections.cubeReader)
        self.assertFalse(reader.running, "The HS Cube reader outlived the connection")
        self.assertIsNone(widget.logic.receivedCubeNode(), "The received cube outlived it")
        after = self._moduleConnectors()
        self.assertEqual([node.GetName() for node in after
                          if node.GetState() != self.IGTL_STATE_OFF], [],
                         "A connector is still running")
        if keepsConnectors:
            self.assertEqual({node.GetID() for node in after}, {node.GetID() for node in before},
                             "Disconnect removed the listed connectors")
        elif closesScene:
            self.assertFalse(any(slicer.mrmlScene.IsNodePresent(node) for node in before),
                             "A connector outlived the scene")
            self.assertEqual(len(after), 3, "The connectors were not listed again")
        else:
            self.assertEqual(after, [], "A connector outlived the application")
        if not closesScene:
            kept = slicer.mrmlScene.GetNodeByID(existingId)
            self.assertIsNotNone(kept, "A node that existed before Connect was removed")
            for key in ("OpenIGTLink.SLIAFlow.DataOrigin",):
                self.assertIsNone(kept.GetAttribute(key),
                                  f"The kept node still carries the sender's {key}")
        for nodeId in set(received) - {existingId}:
            self.assertIsNone(slicer.mrmlScene.GetNodeByID(nodeId),
                              f"{nodeId}, received while connected, was left behind")
        widget._refreshConnections()
        for row in self._connectionRows(widget):
            self.assertEqual(row["state"], self.STATE_NOT_CONNECTED)

    def test_leavingSLIAFlowKeepsTheConnections(self) -> None:
        """Another module can show the connections while SLIAFlow is not on screen."""
        _, widget = self._moduleRepresentationAndWidget()
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn)):
            widget._onConnectClicked()
            self._waitForRow(widget, "LiveView",
                             lambda row: row["state"].startswith(self.STATE_RECEIVING),
                             "LiveView to receive")
            connectorIds = [node.GetID() for node in self._moduleConnectors()]
            widget.exit()
            self.assertEqual([node.GetID() for node in self._moduleConnectors()], connectorIds,
                             "Leaving SLIAFlow closed the connections")
            self.assertTrue(widget.logic.connections.connected)
            (liveView,) = [node for node in self._moduleConnectors()
                           if node.GetName().startswith("SLIAFlow LiveView")]
            self.assertEqual(liveView.GetState(), self.IGTL_STATE_CONNECTED)
            widget.enter()
            self._waitForRow(widget, "LiveView",
                             lambda row: row["state"].startswith(self.STATE_RECEIVING),
                             "LiveView to still receive on coming back")
            self.assertEqual([node.GetID() for node in self._moduleConnectors()], connectorIds)

    def test_igtModulesShowTheConnectors(self) -> None:
        """IGT > OpenIGTLinkIF lists the ports before Connect, and every module keeps them."""
        if slicer.util.mainWindow() is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        modulesMenu = slicer.util.moduleSelector().modulesMenu()

        def chooseFromModulesMenu(moduleName):
            modulesMenu.moduleAction(moduleName).trigger()
            self.assertEqual(slicer.util.selectedModule(), moduleName)

        def states():
            return sorted(node.GetState() for node in self._moduleConnectors())

        previousModule = slicer.util.selectedModule() or "Data"
        try:
            slicer.util.selectModule("SLIAFlow")
            _, widget = self._moduleRepresentationAndWidget()
            with self._runningStandIn() as standIn, self._connectionSettings(
                    widget, **self._standInSettings(standIn)):
                chooseFromModulesMenu("OpenIGTLinkIF")
                self.assertEqual(states(), [self.IGTL_STATE_OFF] * 3,
                                 "OpenIGTLinkIF does not list the ports while disconnected")
                chooseFromModulesMenu("SLIAFlow")
                widget._onConnectClicked()
                self._waitForRow(widget, "LiveView",
                                 lambda row: row["state"].startswith(self.STATE_RECEIVING),
                                 "LiveView to receive")
                chooseFromModulesMenu("OpenIGTLinkIF")
                self.assertEqual(len(self._moduleConnectors()), 3)
                self.assertIn(self.IGTL_STATE_CONNECTED, states())
                chooseFromModulesMenu("Data")
                self.assertTrue(widget.logic.connections.connected,
                                "Leaving OpenIGTLinkIF closed the connections")
                self.assertIn(self.IGTL_STATE_CONNECTED, states())
                chooseFromModulesMenu("SLIAFlow")
                widget._onConnectClicked()
                chooseFromModulesMenu("OpenIGTLinkIF")
                self.assertEqual(states(), [self.IGTL_STATE_OFF] * 3,
                                 "Disconnect did not leave the ports listed")
        finally:
            slicer.util.selectModule(previousModule)

    def test_liveViewMessageDoesNotLandInTheCameraVolume(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        camera = widget.logic.getOrCreateLiveVolume(widget._parameterNode)
        cameraFrame = np.full((1, 3, 4, 3), 7, dtype=np.uint8)
        slicer.util.updateVolumeFromArray(camera, cameraFrame)
        with self._runningStandIn() as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn, stereoPort=0, hsCubePort=0)):
            widget._onConnectClicked()
            self._waitForRow(widget, "LiveView",
                             lambda row: row["state"].startswith(self.STATE_RECEIVING),
                             "LiveView to receive")
            self.assertNotIn(camera.GetID(), self._incomingNodeIds(self._moduleConnectors()),
                             "The connector took the camera volume")
            np.testing.assert_array_equal(slicer.util.arrayFromVolume(camera), cameraFrame)

    # ----------------------------------------------------------------------
    # SLIA-036: the HS cube received from IUMA's acquisition app
    #
    # Every cube here is a placeholder fixture written by the test, standing
    # for no imagery. Messages are packed by the test's own code from the
    # OpenIGTLink IMAGE layout, in the form measured on the app
    # (docs/hardware/acquisition_app_and_hardware.md 4.1), with a bit-by-bit
    # CRC written here, never by the module under test.
    # ----------------------------------------------------------------------

    # CRC-64/ECMA-182, as OpenIGTLink computes it, and its published check value.
    CRC64_POLYNOMIAL = 0x42F0E1EBA9EA3693
    CRC64_CHECK = 0x6C40DF5F0B497347
    # The SLIA-036 card: the name a received cube runs under, and where Capture
    # writes it for UC1 and UC2 (owner decision 3).
    RECEIVED_CUBE_NAME = "received-from-app"
    RECEIVED_RUN_RELATIVE_PATH = Path("workspace") / "received-cube" / "received-from-app"
    CUBE_SOURCE_APP = "Last cube from the app"
    CUBE_SOURCE_DISK = "Cube on disk"
    RECEIVED_AT = datetime.datetime(2026, 10, 6, 14, 25, 30)

    def _receivedCubeModule(self):
        return self._helperModule("SLIAFlowReceivedCube")

    @classmethod
    def _bitwiseCrc64(cls, data: bytes) -> int:
        crc = 0
        for byte in data:
            crc ^= byte << 56
            for _bit in range(8):
                crc = ((crc << 1) ^ cls.CRC64_POLYNOMIAL) if crc & (1 << 63) else crc << 1
                crc &= (1 << 64) - 1
        return crc

    def _packedBand(self, band, *, bands, offset, headerVersion=1, metadata=None,
                    messageType="IMAGE", components=1, scalarCode=None, subvolume=None,
                    subvolumeOffset=None, bigEndian=False, endianCode=None, imageVersion=1,
                    crc=None, pixelBytes=None) -> bytes:
        """One band of a cube as the app sends it, packed from the OpenIGTLink layout."""
        import struct

        band = np.asarray(band)
        lines, samples = band.shape
        if scalarCode is None:
            scalarCode = 5 if band.dtype.kind == "u" else 10
        if endianCode is None:
            endianCode = 1 if bigEndian else 2
        if pixelBytes is None:
            pixelBytes = band.astype(band.dtype.newbyteorder(">" if bigEndian else "<")).tobytes()
        centre = ((samples - 1) / 2.0, (lines - 1) / 2.0, (bands - 1) / 2.0)
        content = struct.pack(
            "> H B B B B 3H 12f 3H 3H", imageVersion, components, scalarCode, endianCode, 2,
            samples, lines, bands, 1, 0, 0, 0, 1, 0, 0, 0, 1, *centre,
            *(subvolumeOffset or (0, 0, offset)), *(subvolume or (samples, lines, 1)),
        ) + pixelBytes
        if headerVersion >= 2:
            metadata = metadata or {}
            entries = b"".join(struct.pack("> H H I", len(key.encode()), 3, len(value.encode()))
                               for key, value in metadata.items())
            metadataHeader = struct.pack("> H", len(metadata)) + entries
            metadataBody = b"".join(key.encode() + value.encode() for key, value in metadata.items())
            body = (struct.pack("> H H I I", 12, len(metadataHeader), len(metadataBody), 0)
                    + content + metadataHeader + metadataBody)
        else:
            body = content
        header = struct.pack("> H 12s 20s I I Q Q", headerVersion, messageType.encode(), b"HsCube",
                             0, 0, len(body), self._bitwiseCrc64(body) if crc is None else crc)
        return header + body

    def _parsedBand(self, packed):
        module = self._receivedCubeModule()
        return module.parseBandMessage(module.parseHeader(packed[:58]), packed[58:])

    def _band(self, values, offset, *, bands, simulated=False):
        """A band as the parser hands it to the assembler."""
        values = np.asarray(values)
        lines, samples = values.shape
        metadata = {"SLIAFlow.DataOrigin": "simulated"} if simulated else {}
        return self._receivedCubeModule().BandMessage(
            "HsCube", 2 if simulated else 1, metadata, values.dtype, samples, lines, bands, offset,
            values)

    @staticmethod
    def _floatCubeValues(bands, *, lines=3, samples=4, shift=0.0):
        values = ((np.arange(bands * lines * samples) % 97) / 64.0 + shift).astype(np.float32)
        return values.reshape(bands, lines, samples)

    @staticmethod
    def _rawCubeValues(bands, *, lines=3, samples=4):
        values = ((np.arange(bands * lines * samples) * 37) % 4096).astype(np.uint16)
        return values.reshape(bands, lines, samples)

    @contextlib.contextmanager
    def _rawSender(self, data: bytes):
        """A local one-client server that sends `data` to the client, then stays open."""
        import socket
        import threading

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        clients = []

        def serve():
            try:
                client, _address = listener.accept()
            except OSError:
                return
            clients.append(client)
            client.sendall(data)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1]
        finally:
            for client in clients:
                client.close()
            listener.close()
            thread.join(5.0)

    def _pollUntil(self, reader, predicate, description):
        """Poll a reader until predicate(messages, completed); return both."""
        messages, completed = [], None
        deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
        while time.monotonic() < deadline:
            update = reader.poll()
            messages += update.messages
            completed = update.completed or completed
            if predicate(messages, completed):
                return messages, completed
            time.sleep(0.02)
        self.fail(f"Timed out waiting for {description} after {len(messages)} messages.")

    def test_receivedCubeCrcIsTheOpenIGTLinkCrc64(self) -> None:
        crc64 = self._receivedCubeModule().crc64
        self.assertEqual(crc64(b"123456789"), self.CRC64_CHECK)
        self.assertEqual(crc64(b""), 0)
        # Long enough for the vectorised path, and not a multiple of its rows.
        data = np.random.default_rng(36).integers(0, 256, 2**17 + 13, dtype=np.uint8).tobytes()
        self.assertEqual(crc64(data), self._bitwiseCrc64(data))

    def test_receivedCubeMessageIsParsedInBothHeaderVersions(self) -> None:
        raw = np.arange(12, dtype=np.uint16).reshape(3, 4) * 300
        band = self._parsedBand(self._packedBand(raw, bands=109, offset=56))
        self.assertEqual((band.headerVersion, band.metadata), (1, {}))
        self.assertEqual((band.samples, band.lines, band.bands), (4, 3, 109))
        self.assertEqual((band.offset, band.bandNumber), (56, 57))
        self.assertEqual(band.dtype.name, "uint16")
        self.assertFalse(band.simulated)
        np.testing.assert_array_equal(band.pixels, raw)
        bigEndian = self._parsedBand(self._packedBand(raw, bands=109, offset=0, bigEndian=True))
        np.testing.assert_array_equal(bigEndian.pixels, raw)

        calibrated = np.arange(12, dtype=np.float32).reshape(3, 4) / 8.0
        metadata = {"SLIAFlow.BandNumber": "3", "SLIAFlow.WavelengthNm": "470",
                    "SLIAFlow.DataOrigin": "simulated"}
        band = self._parsedBand(self._packedBand(calibrated, bands=5, offset=2, headerVersion=2,
                                                 metadata=metadata))
        self.assertEqual(band.headerVersion, 2)
        self.assertEqual(band.metadata, metadata)
        self.assertTrue(band.simulated)
        self.assertEqual(band.wavelengthNm, 470.0)
        self.assertEqual(band.dtype.name, "float32")
        np.testing.assert_array_equal(band.pixels, calibrated)

    def test_receivedCubeRefusesBadMessages(self) -> None:
        module = self._receivedCubeModule()
        band = np.zeros((3, 4), dtype=np.uint16)
        for defect, options, fragment in (
            ("bad CRC", {"crc": 1}, "CRC does not match"),
            ("another type", {"messageType": "STRING"}, "not an IMAGE"),
            ("three components", {"components": 3, "pixelBytes": band.tobytes() * 3},
             "3 components"),
            ("int16", {"scalarCode": 4}, "not uint16 or float32"),
            ("two bands at once", {"subvolume": (4, 3, 2)}, "not one whole band"),
            ("offset past the cube", {"subvolumeOffset": (0, 0, 5)}, "not one whole band"),
            ("part of a band", {"subvolume": (4, 2, 1), "pixelBytes": band[:2].tobytes()},
             "not one whole band"),
            ("short pixels", {"pixelBytes": band.tobytes()[:-2]}, "bytes of pixels"),
            ("band number disagrees", {"headerVersion": 2,
                                       "metadata": {"SLIAFlow.BandNumber": "4"}},
             "says it is band 4"),
            # Undefined in OpenIGTLink: read as little endian, 1 became 256.
            ("byte order code 0", {"endianCode": 0}, "byte order code 0"),
            ("byte order code 3", {"endianCode": 3}, "byte order code 3"),
            ("header version 0", {"headerVersion": 0}, "header version 0"),
            ("header version 3", {"headerVersion": 3}, "header version 3"),
            ("image header version 99", {"imageVersion": 99}, "image header version 99"),
            ("no pixels", {"band": np.zeros((2, 0), dtype=np.uint16), "bands": 1, "offset": 0},
             "no pixels"),
        ):
            with self.subTest(defect=defect):
                packing = {"band": band, "bands": 5, "offset": 2, **options}
                with self.assertRaises(module.RefusedMessage) as raised:
                    self._parsedBand(self._packedBand(**packing))
                self.assertIn(fragment, str(raised.exception))

        # Through the reader: a refused message leaves the cube being received as it was.
        values = np.arange(3 * 12, dtype=np.uint16).reshape(3, 3, 4)
        stream = (self._packedBand(values[0], bands=3, offset=0)
                  + self._packedBand(values[1] + 1, bands=3, offset=1, crc=1)
                  + self._packedBand(values[1], bands=3, offset=1)
                  + self._packedBand(values[2], bands=3, offset=2))
        with self._rawSender(stream) as port:
            reader = module.HsCubeReader("127.0.0.1", port)
            reader.start()
            try:
                messages, completed = self._pollUntil(
                    reader, lambda messages, completed: completed is not None, "the cube")
            finally:
                reader.stop()
        self.assertEqual([message.refusal is not None for message in messages],
                         [False, True, False, False])
        self.assertIn("CRC", messages[1].refusal)
        np.testing.assert_array_equal(completed.values, values)

    def test_receivedCubeAssemblesBandsByOffset(self) -> None:
        module = self._receivedCubeModule()
        for dtype in (np.uint16, np.float32):
            with self.subTest(dtype=np.dtype(dtype).name):
                cube = (np.arange(4 * 3 * 5).reshape(4, 3, 5) * 3).astype(dtype)
                assembler = module.CubeAssembler()
                assembler.connectionOpened()
                completed = [assembler.accept(self._band(cube[offset], offset, bands=4),
                                              now=float(index))
                             for index, offset in enumerate((2, 0, 3, 1))]
                self.assertEqual(completed[:3], [None, None, None])
                self.assertIsNotNone(completed[3], "Every band arrived and no cube was handed over")
                np.testing.assert_array_equal(completed[3].values, cube)
                self.assertEqual(completed[3].values.dtype, np.dtype(dtype))
                progress = assembler.progress()
                self.assertEqual((progress.bandsReceived, progress.bandsDeclared,
                                  progress.complete), (4, 4, True))
        assembler = module.CubeAssembler()
        assembler.connectionOpened()
        bigEndian = np.array([[1, 258]], dtype=">u2")
        completed = assembler.accept(self._band(bigEndian, 0, bands=1), now=0.0)
        np.testing.assert_array_equal(completed.values[0], [[1, 258]])
        self.assertTrue(completed.values.dtype.isnative)

    def test_receivedCubeStartsANewCube(self) -> None:
        module = self._receivedCubeModule()
        assembler = module.CubeAssembler()
        assembler.connectionOpened()
        cube = np.arange(5 * 12, dtype=np.uint16).reshape(5, 3, 4)
        for offset in (0, 1, 2):
            assembler.accept(self._band(cube[offset], offset, bands=5), now=float(offset))
        # An offset the cube already holds starts the next cube.
        assembler.accept(self._band(cube[1], 1, bands=5), now=3.0)
        progress = assembler.progress()
        self.assertEqual((progress.bandsReceived, progress.bandsDeclared, progress.complete),
                         (1, 5, False))
        self.assertEqual(progress.previousIncompleteDetail, "Missing bands: 4-5.")

        # A size or type that changes ends the cube and starts another.
        assembler.accept(self._band(cube[2], 2, bands=5), now=4.0)
        assembler.accept(self._band(cube[0].astype(np.float32), 0, bands=5), now=5.0)
        progress = assembler.progress()
        self.assertEqual(progress.bandsReceived, 1)
        self.assertIn("Missing bands: 1, 4-5.", progress.previousIncompleteDetail)
        self.assertIn("4 x 3 x 5 float32", progress.previousIncompleteDetail)
        completed = None
        for offset in range(1, 5):
            completed = assembler.accept(
                self._band(cube[offset].astype(np.float32), offset, bands=5), now=6.0 + offset)
        np.testing.assert_array_equal(completed.values, cube.astype(np.float32))

    def test_receivedCubeNamesMissingBands(self) -> None:
        module = self._receivedCubeModule()
        assembler = module.CubeAssembler(idleSec=10.0)
        assembler.connectionOpened()
        cube = np.arange(7 * 12, dtype=np.uint16).reshape(7, 3, 4)
        for offset in (0, 1, 3, 5):
            assembler.accept(self._band(cube[offset], offset, bands=7), now=float(offset))
        assembler.tick(now=14.9)
        self.assertIsNone(assembler.progress().incompleteDetail, "Ended before 10 s of silence")
        assembler.tick(now=15.0)
        self.assertEqual(assembler.progress().incompleteDetail, "Missing bands: 3, 5, 7.")
        self.assertFalse(assembler.assembling, "An incomplete cube was kept")

        # A sender that disconnects leaves its cube incomplete too.
        assembler.accept(self._band(cube[0], 0, bands=7), now=20.0)
        assembler.connectionLost()
        self.assertEqual(assembler.progress().incompleteDetail, "Missing bands: 2-7.")
        self.assertFalse(assembler.assembling)

    def test_receivedCubeLateConnectionMissesFirstBand(self) -> None:
        """Measured on the app: a client that joined late missed band 1 (SLIA-030)."""
        module = self._receivedCubeModule()
        assembler = module.CubeAssembler()
        assembler.connectionOpened()
        cube = np.arange(5 * 12, dtype=np.uint16).reshape(5, 3, 4)
        for offset in (1, 2, 4):
            assembler.accept(self._band(cube[offset], offset, bands=5), now=float(offset))
        assembler.connectionLost()
        self.assertEqual(assembler.progress().incompleteDetail,
                         "Missing bands: 1 (connected after the capture started), 4.")

    def test_receivedCubeLateConnectionNeverMixesTwoCubes(self) -> None:
        """A connection that joined mid-cube must not fill that cube's gaps from the next one."""
        module = self._receivedCubeModule()
        assembler = module.CubeAssembler(idleSec=10.0)
        assembler.connectionOpened()
        first = np.full((5, 3, 4), 1, dtype=np.uint16)
        second = np.full((5, 3, 4), 2, dtype=np.uint16)
        for offset in (3, 4):
            assembler.accept(self._band(first[offset], offset, bands=5), now=0.1 * offset)
        completed = None
        for offset in (0, 1, 2):
            completed = assembler.accept(self._band(second[offset], offset, bands=5),
                                         now=1.0 + 0.1 * offset)
        self.assertIsNone(completed, "Bands of two cubes were put together as one")
        progress = assembler.progress()
        self.assertEqual((progress.bandsReceived, progress.complete), (3, False))
        self.assertEqual(progress.previousIncompleteDetail,
                         "Missing bands: 1-3 (connected after the capture started).")
        # The next cube, received from its first band, completes.
        for offset in (3, 4):
            completed = assembler.accept(self._band(second[offset], offset, bands=5),
                                         now=2.0 + 0.1 * offset)
        np.testing.assert_array_equal(completed.values, second)

    def test_receivedCubeFromTheStandInInBothHeaderVersions(self) -> None:
        module = self._receivedCubeModule()
        for appHeader, raw in ((False, False), (True, False), (True, True)):
            with self.subTest(appHeader=appHeader, raw=raw), self._runningStandIn(
                    appHeader=appHeader, raw=raw) as standIn:
                reader = module.HsCubeReader("127.0.0.1", standIn["basePort"] + 2)
                reader.start()
                try:
                    _messages, completed = self._pollUntil(
                        reader, lambda messages, completed: completed is not None,
                        "the stand-in's cube")
                finally:
                    reader.stop()
                np.testing.assert_array_equal(completed.values, standIn["values"])
                self.assertEqual(completed.dtype.name, standIn["values"].dtype.name)
                # Only header version 2 carries the stand-in's simulated mark.
                self.assertEqual(completed.simulated, not appHeader)
                if not appHeader:
                    self.assertIn("stand-in", completed.simulationDetail)

    def test_receivedCubeSurvivesABusyMainThread(self) -> None:
        """No band is lost while the main thread is held for 2 s, as a UC1 load can."""
        module = self._receivedCubeModule()
        bands = 40
        # 20 bands/s, faster than the app's measured 8.8 bands/s.
        with self._runningStandIn(bands=bands, bandInterval=0.05, appHeader=True) as standIn:
            reader = module.HsCubeReader("127.0.0.1", standIn["basePort"] + 2)
            reader.start()
            try:
                first, _ = self._pollUntil(reader, lambda messages, completed: messages,
                                           "the first band")
                busyUntil = time.monotonic() + 2.0
                spins = 0
                while time.monotonic() < busyUntil:
                    spins += 1
                rest, completed = self._pollUntil(
                    reader, lambda messages, completed: completed is not None, "the whole cube")
            finally:
                reader.stop()
        self.assertGreater(spins, 0)
        self.assertEqual(len(first) + len(rest), bands)
        self.assertTrue(all(message.refusal is None for message in first + rest))
        np.testing.assert_array_equal(completed.values, standIn["values"])

    @staticmethod
    def _waitInTheEventLoop(predicate, timeoutSec: float, checkMs: int = 500) -> bool:
        """Wait inside Qt's event loop, as Slicer does when no Python runs; True if met.

        A loop of processEvents() and sleep() releases the GIL itself, and
        hides what another Python thread gets while Slicer is idle.
        """
        import qt

        loop = qt.QEventLoop()
        check = qt.QTimer()
        check.setInterval(checkMs)

        def onCheck():
            if predicate():
                loop.quit()

        check.connect("timeout()", onCheck)
        deadline = qt.QTimer()
        deadline.setSingleShot(True)
        deadline.setInterval(int(timeoutSec * 1000))
        deadline.connect("timeout()", loop.quit)
        check.start()
        deadline.start()
        try:
            loop.exec_()
        finally:
            check.stop()
            deadline.stop()
        return predicate()

    def test_receivedCubeArrivesWhileSlicerWaitsForEvents(self) -> None:
        """Bands of a real size arrive while the main thread waits in Qt's event loop.

        Slicer's main thread keeps Python's GIL there. The reader then ran a
        moment every few hundred milliseconds, and the app and the stand-in
        closed the connection after a few bands (SLIA-036 verification).
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        bands = 20
        # 1 MB a band: its CRC and copy take hundreds of GIL hand-overs.
        with self._runningStandIn(bands=bands, samples=512, lines=512,
                                  bandInterval=0) as standIn, self._connectionSettings(
                widget, **self._standInSettings(standIn, liveViewPort=0, stereoPort=0,
                                                expectedBands=bands)):
            widget._onConnectClicked()
            arrived = self._waitInTheEventLoop(
                lambda: widget.logic.receivedCubeNode() is not None, self.CONNECTION_TIMEOUT_SEC)
            self.assertTrue(arrived, f"No cube while Slicer waited for events; rows: "
                                     f"{self._connectionRows(widget)}; detail: "
                                     f"{widget.ui.connectionsDetailLabel.text}")
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(widget.logic.receivedCubeNode()), standIn["values"])
            widget._onConnectClicked()
            self.assertFalse(widget.logic.connections._gilYieldTimer.isActive(),
                             "The main thread still sleeps for a reader that was stopped")

    def test_imageSlabMessageIsAssembledByOpenIGTLinkIF(self) -> None:
        """The stand-in's app form is what OpenIGTLinkIF itself reads as one cube."""
        self.assertTrue(hasattr(slicer, "vtkMRMLIGTLConnectorNode"),
                        "OpenIGTLinkIF is not loaded; run-slicer-tests.ps1 must load it")
        with self._runningStandIn(appHeader=True, bandInterval=0.2) as standIn:
            connector = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLIGTLConnectorNode")
            connector.SetSaveWithScene(False)
            try:
                connector.SetTypeClient("127.0.0.1", standIn["basePort"] + 2)
                self.assertTrue(connector.Start())
                assembled = False
                deadline = time.monotonic() + self.CONNECTION_TIMEOUT_SEC
                while not assembled and time.monotonic() < deadline:
                    slicer.app.processEvents()
                    for index in range(connector.GetNumberOfIncomingMRMLNodes()):
                        node = connector.GetIncomingMRMLNode(index)
                        if node is None or node.GetImageData() is None:
                            continue
                        array = slicer.util.arrayFromVolume(node)
                        assembled = (array.shape == standIn["values"].shape
                                     and np.array_equal(array, standIn["values"]))
                    time.sleep(0.01)
                self.assertTrue(assembled, "OpenIGTLinkIF did not assemble the bands into the cube")
            finally:
                connector.Stop()
                incoming = [connector.GetIncomingMRMLNode(index)
                            for index in range(connector.GetNumberOfIncomingMRMLNodes())]
                for node in incoming:
                    if node is not None and slicer.mrmlScene.IsNodePresent(node):
                        slicer.mrmlScene.RemoveNode(node)
                slicer.mrmlScene.RemoveNode(connector)

    # --- The received cube in the module ------------------------------------

    def _receivedCube(self, values, *, simulated=False, detail=None):
        """A complete cube, in the image SLIAFlow assembles into, as the reader hands it over."""
        values = np.asarray(values)
        image, view = SLIAFlowLogic.allocateReceivedCube(*values.shape, values.dtype)
        view[...] = values
        return self._receivedCubeModule().AssembledCube(
            image, view, "HsCube", simulated, detail, host="127.0.0.1", port=18946,
            receivedAt=self.RECEIVED_AT)

    def _deliverReceivedCube(self, widget, cube):
        """Hand a completed cube to the widget the way the Connections timer does."""
        widget.logic.connections._completedCube = cube
        widget._refreshConnections()
        return widget.logic.receivedCubeNode()

    @contextlib.contextmanager
    def _widgetForReceivedCubes(self):
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        try:
            yield widget
        finally:
            widget._forgetReceivedCube()

    def test_receivedCubeProvenance(self) -> None:
        with self._widgetForReceivedCubes() as widget:
            node = self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(109)))
            self.assertIsNotNone(node, "The completed cube was not taken")
            self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "received")
            self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"), self.RECEIVED_CUBE_NAME)
            detail = node.GetAttribute("SLIAFlow.SimulationDetail")
            for fragment in ("calibrated float32 cube", "127.0.0.1:18946",
                             "IUMA's AcquisitionSystemApp", "2026-10-06 14:25:30",
                             "captured it live or replayed a stored cube",
                             "cannot tell apart"):
                with self.subTest(fragment=fragment):
                    self.assertIn(fragment, detail)
            self.assertNotIn("simulated", detail)

    def test_standInCubeStaysSimulated(self) -> None:
        detail = ("stand-in for IUMA's acquisition app, recorded IUMA LCTF capture cube, "
                  "calibrated by IUMA (simulated acquisition)")
        with self._widgetForReceivedCubes() as widget:
            node = self._deliverReceivedCube(widget, self._receivedCube(
                self._floatCubeValues(109), simulated=True, detail=detail))
            self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "simulated")
            self.assertTrue(node.GetAttribute("SLIAFlow.SimulationDetail").startswith(detail))

    def test_receivedRawCubeKeepsItsCounts(self) -> None:
        raw = self._rawCubeValues(109)
        with self._widgetForReceivedCubes() as widget:
            cube = self._receivedCube(raw)
            node = self._deliverReceivedCube(widget, cube)
            self.assertIs(node.GetImageData(), cube.owner, "The received cube was copied")
            array = slicer.util.arrayFromVolume(node)
            self.assertEqual(array.dtype, np.uint16)
            np.testing.assert_array_equal(array, raw)
            # Raw counts are previewed against the cube's brightest count, not reflectance 1.0.
            preview = widget.logic.acceptColourPreview(node)
            rgb = np.array(slicer.util.arrayFromVolume(preview))[0]
            fullScale = float(raw.max())
            for channel, nanometres in enumerate(self.PREVIEW_WAVELENGTHS_NM):
                band = self.LCTF_WAVELENGTHS_NM.index(nanometres)
                expected = np.floor(raw[band].astype(np.float64) * 255.0 / fullScale + 0.5)
                np.testing.assert_array_equal(rgb[..., channel], expected.astype(np.uint8))
            chart = widget.logic.showPixelSpectrum(node, 1, 2)
            self.assertEqual(chart.GetYAxisTitle(), "Raw count (uncalibrated)")

    def test_receivedCubeWavelengthsAreAssumedOnlyFor109Bands(self) -> None:
        with self._widgetForReceivedCubes() as widget:
            node = self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(109)))
            self.assertEqual(widget.logic.cubeWavelengths(node),
                             tuple(float(value) for value in self.LCTF_WAVELENGTHS_NM))
            self.assertIn("assumed", node.GetAttribute("SLIAFlow.WavelengthsAssumed"))

            node = self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(5)))
            self.assertEqual(widget.logic.cubeWavelengths(node), ())
            self.assertIsNone(node.GetAttribute("SLIAFlow.WavelengthsAssumed"))
            with self.assertRaises(ValueError):
                widget.logic.showPixelSpectrum(node, 0, 0)
            with self.assertRaises(ValueError):
                widget.logic.acceptColourPreview(node)

    def test_receivedCubeReplacesThePreviousOne(self) -> None:
        with self._widgetForReceivedCubes() as widget:
            first = self._receivedCube(self._floatCubeValues(5))
            firstId = self._deliverReceivedCube(widget, first).GetID()
            second = self._receivedCube(self._rawCubeValues(5))
            secondNode = self._deliverReceivedCube(widget, second)
            owned = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
                     if node.GetAttribute("SLIAFlow.Owner") == "ReceivedCube"]
            self.assertEqual([node.GetID() for node in owned], [secondNode.GetID()])
            self.assertIsNone(slicer.mrmlScene.GetNodeByID(firstId))
            # Nothing but this test still holds the first cube's memory.
            self.assertEqual(first.owner.GetReferenceCount(), 1)

    @contextlib.contextmanager
    def _appSourcePresentation(self):
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._widgetForReceivedCubes() as widget:
            previousSource = widget._parameterNode.cubeSource
            try:
                self.assertTrue(widget._activatePresentation())
                widget._parameterNode.cubeSource = self.CUBE_SOURCE_APP
                widget._onCubeSourceChanged()
                yield widget, layoutManager
            finally:
                widget.ui.cubeDisplaySelector.setCurrentIndex(0)
                widget._parameterNode.cubeSource = previousSource
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)

    def test_hsCubePanelWaitsForACubeFromTheApp(self) -> None:
        with self._appSourcePresentation() as (widget, layoutManager):
            composite = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME).sliceLogic() \
                .GetSliceCompositeNode()
            self.assertIn("Waiting for a complete cube from the app",
                          widget.panelMessage(widget.CUBE_VIEW_NAME))
            self.assertIsNone(composite.GetBackgroundVolumeID())
            widget._parameterNode.cubeSource = self.CUBE_SOURCE_DISK
            widget._onCubeSourceChanged()
            self.assertEqual(widget.panelMessage(widget.CUBE_VIEW_NAME),
                             "Waiting for the hyperspectral cube.")

    def test_receivedCubeIsShownInTheHsCubePanel(self) -> None:
        with self._appSourcePresentation() as (widget, layoutManager):
            composite = layoutManager.sliceWidget(widget.CUBE_VIEW_NAME).sliceLogic() \
                .GetSliceCompositeNode()
            node = self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(109)))
            self.assertEqual(composite.GetBackgroundVolumeID(), node.GetID())
            self.assertEqual(widget.panelMessage(widget.CUBE_VIEW_NAME), "")
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, (
                "Cube received from the app", "calibrated reflectance", "assumed"))
            widget.ui.cubeDisplaySelector.setCurrentIndex(widget.CUBE_DISPLAY_PREVIEW)
            preview = widget.logic.colourPreviewNode()
            self.assertIsNotNone(preview, "No colour preview was built for the received cube")
            self.assertEqual(composite.GetBackgroundVolumeID(), preview.GetID())
            widget.ui.cubeDisplaySelector.setCurrentIndex(widget.CUBE_DISPLAY_BANDS)

            rawNode = self._deliverReceivedCube(widget, self._receivedCube(self._rawCubeValues(109)))
            self.assertEqual(composite.GetBackgroundVolumeID(), rawNode.GetID())
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME, (
                "Cube received from the app", "raw counts, uncalibrated"))

            self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(5)))
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME,
                                 ("wavelength not sent",))

    # --- Capture on a received cube --------------------------------------------

    @contextlib.contextmanager
    def _appSourceCaptureSession(self, **options):
        with self._captureSession(**options) as session:
            widget = session["widget"]
            previousSource = widget._parameterNode.cubeSource
            widget._parameterNode.cubeSource = self.CUBE_SOURCE_APP
            session["runFolder"] = session["root"] / self.RECEIVED_RUN_RELATIVE_PATH
            try:
                yield session
            finally:
                widget._cancelCapture()
                widget._forgetReceivedCube()
                widget._parameterNode.cubeSource = previousSource

    def _captureReceivedCube(self, session, values):
        widget = session["widget"]
        node = self._deliverReceivedCube(widget, self._receivedCube(values))
        self._startFakeCamera(session)
        self._showFrame(session, 10)
        widget._onCaptureClicked()
        return node

    def _assertCaptureRuns(self, widget):
        self.assertTrue(widget.captureInProgress,
                        f"The capture ended at once: {widget.ui.statusLabel.text} / "
                        f"{widget.ui.vascularStatusLabel.text}")

    def test_captureWithoutAReceivedCubeIsRefused(self) -> None:
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 10)
            widget._onCaptureClicked()
            self.assertFalse(widget.captureInProgress)
            self.assertFalse(widget.liveViewFrozen)
            self.assertIn("no complete cube has been received", widget.ui.statusLabel.text)
            self.assertEqual(session["processes"], [])
            self.assertEqual(list(session["captures"].glob("*.png")), [], "A snapshot was saved")

    def test_captureOnAReceivedFloat32CubeRunsUc1AndUc2(self) -> None:
        calibrated = self._helperModule("SLIAFlowCalibratedCube")
        values = self._floatCubeValues(109)
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            node = self._captureReceivedCube(session, values)
            self._assertCaptureRuns(widget)
            self.assertEqual([Path(process.program).name for process in session["processes"]],
                             [self.UC2_EXECUTABLE_NAME, "stratum.opt.intermediate.exe"])
            runFolder = session["runFolder"]
            written = np.fromfile(runFolder / "LCTF_Calibrated_Cube_Single.dat",
                                  dtype="<f4").reshape(values.shape)
            np.testing.assert_array_equal(written, values)
            cube = calibrated.loadCalibratedCube(runFolder / "LCTF_Calibrated_Cube_Single.hdr")
            self.assertEqual(cube.wavelengths,
                             tuple(float(value) for value in self.LCTF_WAVELENGTHS_NM))
            self.assertEqual(self._uc2Process(session).arguments,
                             [runFolder.resolve().as_posix()])
            self.assertEqual(widget.logic.currentRun.case.name, self.RECEIVED_CUBE_NAME)
            # HS Cube keeps the received node, now this capture's.
            self.assertEqual(widget.logic.receivedCubeNode().GetID(), node.GetID())
            self.assertEqual(node.GetAttribute("SLIAFlow.CaptureId"), widget._captureId)

            self._finishUc2(session, seed=3)
            self._finishCapture(session, seed=4)
            self.assertFalse(widget.captureInProgress)
            self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"))
            self.assertIsNotNone(widget.logic.vascularMapNode())
            self.assertIn("the cube received from the app", widget.ui.statusLabel.text)
            self.assertIn("received from the app", widget.ui.resultStatusLabel.text)
            self.assertNotIn("recorded cube", widget.ui.resultStatusLabel.text.lower())

    def test_outputsOfAReceivedCubeCarryItsProvenance(self) -> None:
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            self._captureReceivedCube(session, self._floatCubeValues(109))
            self._assertCaptureRuns(widget)
            self._finishUc2(session, seed=3)
            self._finishCapture(session, seed=4)
            received = "calibrated float32 cube received over OpenIGTLink from 127.0.0.1:18946"
            outputs = [widget.logic.outputNode(name) for name in self.UC1_OUTPUT_FILE_NAMES]
            for node, producer in ([(node, "real UC1 pipeline") for node in outputs]
                                   + [(widget.logic.vascularMapNode(),
                                       "real UC2 blood-vessel enhancement")]):
                with self.subTest(node=node.GetName()):
                    self.assertEqual(node.GetAttribute("SLIAFlow.DataOrigin"), "received")
                    self.assertEqual(node.GetAttribute("SLIAFlow.RecordedCase"),
                                     self.RECEIVED_CUBE_NAME)
                    self.assertTrue(node.GetAttribute("SLIAFlow.SimulationDetail").startswith(
                        f"{producer}, {received}"), node.GetAttribute("SLIAFlow.SimulationDetail"))

    def test_resultKeepsTheOriginOfItsOwnCube(self) -> None:
        """A stand-in result stays described as the stand-in's after a capture on the app's fails."""
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            standIn = self._receivedCube(self._floatCubeValues(109), simulated=True,
                                         detail="stand-in fixture")
            self._deliverReceivedCube(widget, standIn)
            self._startFakeCamera(session)
            self._showFrame(session, 10)
            widget._onCaptureClicked()
            self._assertCaptureRuns(widget)
            self._finishUc2(session, seed=3)
            self._finishCapture(session, seed=4)
            self.assertIn("stand-in", widget.ui.resultStatusLabel.text)

            # The app's cube, with no wavelengths to map: the capture fails at once
            # and the stand-in's result stays shown.
            self._captureReceivedCube(session, self._floatCubeValues(5))
            self.assertFalse(widget.captureInProgress)
            self.assertIn("received from the app", widget.ui.statusLabel.text)
            self.assertIn("stand-in", widget.ui.resultStatusLabel.text)
            self.assertNotIn("received from the app", widget.ui.resultStatusLabel.text)

    def test_runCubeKeptByADisconnectIsRemovedWhenItsCaptureEnds(self) -> None:
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            self._captureReceivedCube(session, self._floatCubeValues(109))
            self._assertCaptureRuns(widget)
            runCube = session["runFolder"] / "LCTF_Calibrated_Cube_Single.dat"
            # Disconnect while UC1 and UC2 still read it.
            widget._forgetReceivedCube()
            self.assertTrue(runCube.exists(), "The cube a running capture reads was removed")
            self._finishUc2(session, seed=3)
            self.assertTrue(runCube.exists(), "Removed while UC1 still reads it")
            self._finishCapture(session, seed=4)
            self.assertFalse(widget.captureInProgress)
            self.assertFalse(runCube.exists(), "The run cube outlived its capture")
            self.assertFalse(runCube.with_suffix(".hdr").exists())

    def test_captureOnAReceivedUint16CubeRunsNothing(self) -> None:
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            node = self._captureReceivedCube(session, self._rawCubeValues(109))
            self.assertEqual(session["processes"], [], "A run was started on raw counts")
            self.assertFalse(widget.captureInProgress)
            self.assertFalse(widget.liveViewFrozen)
            for label in (widget.ui.statusLabel, widget.ui.vascularStatusLabel):
                with self.subTest(label=label.objectName):
                    self.assertIn("raw uint16", label.text)
                    self.assertIn("calibrated float32 stream", label.text)
            self.assertFalse((session["runFolder"] / "LCTF_Calibrated_Cube_Single.dat").exists())
            self.assertEqual(widget.logic.receivedCubeNode().GetID(), node.GetID(),
                             "The raw cube left HS Cube")

    def test_captureOnAReceivedCubeOfAnotherBandCountIsRefused(self) -> None:
        with self._appSourceCaptureSession(uc2=True) as session:
            widget = session["widget"]
            self._captureReceivedCube(session, self._floatCubeValues(5))
            self.assertEqual(session["processes"], [])
            self.assertFalse(widget.captureInProgress)
            self.assertIn("no wavelengths", widget.ui.statusLabel.text)
            self.assertIn("not classified", widget.ui.statusLabel.text)

    def test_cubeCompletedDuringACaptureWaitsForItsEnd(self) -> None:
        first = self._floatCubeValues(109)
        second = self._floatCubeValues(109, shift=0.5)
        with self._appSourceCaptureSession() as session:
            widget = session["widget"]
            node = self._captureReceivedCube(session, first)
            self._assertCaptureRuns(widget)
            self._deliverReceivedCube(widget, self._receivedCube(second))
            self.assertEqual(widget.logic.receivedCubeNode().GetID(), node.GetID(),
                             "A new cube replaced the one the capture runs on")
            np.testing.assert_array_equal(slicer.util.arrayFromVolume(node), first)
            self._finishCapture(session, seed=4)
            self.assertFalse(widget.captureInProgress)
            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(widget.logic.receivedCubeNode()), second)

    # --- Lifetime --------------------------------------------------------------------

    def test_receivedCubeIsFreedOnDisconnectAndSceneClose(self) -> None:
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        with self._fixtureDirectory() as root:
            widget.logic.setRunEnvironment(repositoryRoot=root)
            runCube = root / self.RECEIVED_RUN_RELATIVE_PATH / "LCTF_Calibrated_Cube_Single.dat"
            try:
                with self._runningStandIn() as standIn, self._connectionSettings(
                        widget, **self._standInSettings(standIn, liveViewPort=0, stereoPort=0)):
                    widget._onConnectClicked()
                    self._waitForRow(widget, "HS Cube",
                                     lambda row: row["state"].startswith(self.STATE_CUBE_COMPLETE),
                                     "HS Cube to complete")
                    self.assertIsNotNone(widget.logic.receivedCubeNode(),
                                         "The completed cube was not taken")
                    # As left by an earlier Capture on a received cube.
                    runCube.parent.mkdir(parents=True, exist_ok=True)
                    runCube.write_bytes(b"test fixture")
                    widget._onConnectClicked()
                    self.assertIsNone(widget.logic.receivedCubeNode(), "Disconnect kept the cube")
                    self.assertFalse(runCube.exists(), "Disconnect kept the cube written for a run")

                self._deliverReceivedCube(widget, self._receivedCube(self._floatCubeValues(5)))
                widget._heldReceivedCube = self._receivedCube(self._floatCubeValues(5))
                runCube.write_bytes(b"test fixture")
                slicer.mrmlScene.Clear()
                self.assertIsNone(widget._heldReceivedCube, "Scene close kept a held cube")
                self.assertFalse(runCube.exists(), "Scene close kept the cube written for a run")
            finally:
                widget.initializeParameterNode()
                widget.logic.setRunEnvironment(repositoryRoot=None)

    def test_readerStopsOnCleanup(self) -> None:
        """Reload calls cleanup() on the old widget: its HS Cube reader must not outlive it."""
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        names = ("liveViewPort", "stereoPort", "hsCubePort")
        previous = {name: getattr(widget._parameterNode, name) for name in names}
        try:
            widget._parameterNode.liveViewPort = 0
            widget._parameterNode.stereoPort = 0
            widget._parameterNode.hsCubePort = self._freeBasePort()
            widget._refreshConnections()
            widget._onConnectClicked()
            reader = widget.logic.connections.cubeReader
            self.assertIsNotNone(reader)
            self.assertTrue(reader.running)
            slicer.util.reloadScriptedModule("SLIAFlow")
            self.assertFalse(reader.running, "The HS Cube reader outlived the module")
        finally:
            if widget.logic.connections.connected:
                widget._onConnectClicked()
            _, current = self._moduleRepresentationAndWidget()
            current.initializeParameterNode()
            for name, value in previous.items():
                setattr(current._parameterNode, name, value)
            current._refreshConnections()

    # ----------------------------------------------------------------------
    # SLIA-021: the UC2 blood-vessel map in Enhanced Vascularization
    #
    # As for UC1, every cube, build and PNG below is a placeholder fixture in a
    # temporary directory. No test reads input/ or runs the staged UC2 build;
    # scripts/development/check-uc2.py runs the real build on 002-04.
    # ----------------------------------------------------------------------

    # Patch 0002's fixed band indices and the wavelengths they must be on the
    # cube, from docs/development/uc2_changes.md.
    UC2_BANDS = ((4, 480.0), (16, 540.0), (50, 710.0))
    UC2_RUN_TIMEOUT_SEC = 30
    UC2_EXECUTABLE_NAME = "uc2_bvmap.exe"
    UC2_MAP_NAME = "002-04-BVMap.png"
    UC2_DETAIL = (
        "real UC2 blood-vessel enhancement, recorded IUMA LCTF capture 002-04, calibrated by "
        "IUMA (simulated acquisition)"
    )

    def _makeFixtureUc2Build(self, root: Path) -> dict:
        """A placeholder staged UC2 build: the binary and its runtime, never run."""
        buildRoot = root / "build" / "uc2"
        source = buildRoot / "source"
        source.mkdir(parents=True)
        (source / self.UC2_EXECUTABLE_NAME).write_bytes(b"test fixture, never run")
        (source / "msys-2.0.dll").write_bytes(b"test fixture, never loaded")
        return {
            "uc2BuildRoot": buildRoot,
            "uc2Executable": source / self.UC2_EXECUTABLE_NAME,
            "uc2Runtime": source / "msys-2.0.dll",
            "uc2RunDirectory": buildRoot / "run",
            "uc2Lock": buildRoot / ".uc2-runner.lock",
        }

    @staticmethod
    def _uc2PngBytes(rgbTopFirst) -> bytes:
        """An 8-bit RGB PNG, top row first, as stb_image_write lays one out.

        Written here with zlib alone, so the reader is checked against neither
        VTK's nor Qt's own writer.
        """
        import struct
        import zlib

        rgb = np.asarray(rgbTopFirst, dtype=np.uint8)
        lines, samples = rgb.shape[:2]

        def chunk(kind: bytes, body: bytes) -> bytes:
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

        rows = b"".join(b"\0" + rgb[line].tobytes() for line in range(lines))
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", samples, lines, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows))
                + chunk(b"IEND", b""))

    def _uc2Fixture(self, root: Path) -> dict:
        fixture = self._makeFixtureRepository(root)
        fixture.update(self._makeFixtureUc2Build(root))
        return fixture

    def _startUc2Run(self, fixture, header=None, **runOptions):
        """Prepare a Uc2Run on the fixture cube (or `header`) with a fake process."""
        uc2Run = self._helperModule("SLIAFlowUc2Run")
        cube = self._helperModule("SLIAFlowCalibratedCube").loadCalibratedCube(
            header or fixture["calibratedHeader"])
        build = uc2Run.Uc2Build(fixture["uc2BuildRoot"])
        factory, processes = self._fakeProcessFactory()
        results = []
        run = uc2Run.Uc2Run(build, cube, results.append, processFactory=factory, **runOptions)
        return run, cube, build, processes, results

    def _uc2Process(self, session):
        """The fake UC2 process of the latest capture."""
        processes = [process for process in session["processes"]
                     if Path(process.program).name == self.UC2_EXECUTABLE_NAME]
        self.assertTrue(processes, "Capture did not start a UC2 process")
        return processes[-1]

    def _finishUc2(self, session, *, seed=0, exitCode=0, stdout=b"", writeMap=True):
        """Write the map the fake UC2 process stands for, then end that process."""
        run = session["widget"].logic.currentUc2Run
        self.assertIsNotNone(run, "Capture did not start a UC2 run")
        image = self._fixtureImage(lines=run.cube.lines, samples=run.cube.samples, seed=seed)
        if writeMap:
            run.build.outputPath(run.cube).write_bytes(self._uc2PngBytes(image))
        process = self._uc2Process(session)
        if stdout:
            process.emitOutput(stdout=stdout)
        process.emitFinished(exitCode)
        return image

    def test_uc2RunsTheStagedBuildOnTheCubeFolder(self) -> None:
        uc2Run = self._helperModule("SLIAFlowUc2Run")
        self.assertEqual(uc2Run.RUN_TIMEOUT_SEC, self.UC2_RUN_TIMEOUT_SEC)
        self.assertEqual(tuple(uc2Run.UC2_BANDS), self.UC2_BANDS)
        with self._fixtureDirectory() as root:
            fixture = self._uc2Fixture(root)
            fixture["uc2RunDirectory"].mkdir(parents=True)
            leftover = fixture["uc2RunDirectory"] / self.UC2_MAP_NAME
            leftover.write_bytes(b"left by an earlier run")
            cubeFiles = sorted(path.name for path in fixture["cubeFolder"].iterdir())

            run, cube, build, processes, results = self._startUc2Run(fixture)
            run.start()
            try:
                self.assertEqual(len(processes), 1)
                process = processes[0]
                self.assertTrue(process.started)
                self.assertEqual(Path(process.program), fixture["uc2Executable"])
                # The folder, not a file: patch 0001 finds the cube in it.
                self.assertEqual(process.arguments, [fixture["cubeFolder"].resolve().as_posix()])
                self.assertEqual(Path(process.workingDirectory), fixture["uc2RunDirectory"])
                for shell in ("cmd", "powershell", "pwsh", "bash", "/c"):
                    self.assertNotIn(shell, str(process.program).lower())
                self.assertTrue(fixture["uc2Lock"].is_file(), "The lock is not held during the run")
                self.assertFalse(leftover.exists(), "A previous run's map was not cleared")
                self.assertTrue(run.running)
            finally:
                run.cancel()
            self.assertFalse(fixture["uc2Lock"].exists())
            self.assertTrue(process.killed)
            self.assertEqual(results, [], "A cancelled run was reported")
            self.assertEqual(sorted(path.name for path in fixture["cubeFolder"].iterdir()),
                             cubeFiles, "UC2's run wrote into the cube's folder")

    def test_uc2PreRunChecksRefuseBeforeStarting(self) -> None:
        uc2Run = self._helperModule("SLIAFlowUc2Run")
        with self._fixtureDirectory() as root:
            fixture = self._uc2Fixture(root)

            def refused(expectedFragment, header=None, prepare=None):
                run, _cube, _build, processes, _results = self._startUc2Run(fixture, header)
                if prepare is not None:
                    prepare()
                with self.assertRaises(uc2Run.Uc2RunError) as raised:
                    run.start()
                self.assertIn(expectedFragment, str(raised.exception))
                self.assertEqual(processes, [], "A process was created for a refused run")
                return raised.exception

            with self.subTest(defect="missing executable"):
                fixture["uc2Executable"].rename(fixture["uc2Executable"].with_suffix(".off"))
                refused("build-uc2.ps1")
                fixture["uc2Executable"].with_suffix(".off").rename(fixture["uc2Executable"])
                self.assertFalse(fixture["uc2Lock"].exists(), "A refused run left the lock behind")

            with self.subTest(defect="missing runtime"):
                fixture["uc2Runtime"].rename(fixture["uc2Runtime"].with_suffix(".off"))
                refused("msys-2.0.dll")
                fixture["uc2Runtime"].with_suffix(".off").rename(fixture["uc2Runtime"])

            with self.subTest(defect="cube not on the LCTF grid"):
                # 440 nm first, as the HSI Human Brain Database grid: index 4 is
                # 460 nm, so UC2 would read the wrong bands.
                header, _values = self._writeFixtureCalibratedCube(
                    root / "input" / "off-grid", wavelengths=tuple(range(440, 440 + 5 * 109, 5)))
                refused("480", header=header)

            with self.subTest(defect="data file UC2 does not open"):
                header, _values = self._writeFixtureCalibratedCube(
                    root / "input" / "raw-suffix", dataSuffix=".raw")
                refused("LCTF_Calibrated_Cube_Single.dat", header=header)

            with self.subTest(defect="cube changed after Capture"):
                data = fixture["calibratedHeader"].with_suffix(".dat")
                original = data.read_bytes()
                try:
                    refused("bytes", prepare=lambda: data.write_bytes(original[:-4]))
                finally:
                    data.write_bytes(original)

            with self.subTest(defect="lock held"):
                fixture["uc2Lock"].write_text("12345\n", encoding="ascii")
                try:
                    refused(uc2Run.LOCK_FILE_NAME)
                    self.assertTrue(fixture["uc2Lock"].is_file(),
                                    "SLIAFlow deleted a lock it does not hold")
                finally:
                    fixture["uc2Lock"].unlink()

    def test_uc2MapIsReadTopRowFirstAndChecked(self) -> None:
        uc2Run = self._helperModule("SLIAFlowUc2Run")
        with self._fixtureDirectory() as root:
            image = self._fixtureImage(lines=3, samples=4, seed=5)
            path = root / self.UC2_MAP_NAME
            path.write_bytes(self._uc2PngBytes(image))
            np.testing.assert_array_equal(uc2Run.readBvMapPng(path, 3, 4), image,
                                          "The map is flipped, mirrored or channel-swapped")
            with self.subTest(defect="other size"):
                with self.assertRaises(uc2Run.Uc2RunError):
                    uc2Run.readBvMapPng(path, 4, 3)
            with self.subTest(defect="not a PNG"):
                other = root / "other.png"
                other.write_bytes(b"not a PNG")
                with self.assertRaises(uc2Run.Uc2RunError):
                    uc2Run.readBvMapPng(other, 3, 4)

    def test_uc2RunFailsOnExitCodeErrorLineOrMissingMap(self) -> None:
        """UC2 exits 0 after several failures, so its error lines are read too."""
        with self._fixtureDirectory() as root:
            fixture = self._uc2Fixture(root)
            for label, exitCode, stdout, writeMap, fragment in (
                ("error line, exit 0", 0, b"Error reading band 16 from 'x'\n", True,
                 "Error reading band"),
                ("exit code", 1, b"", True, "code 1"),
                ("no map", 0, b"Image successfully saved\n", False, "did not write"),
            ):
                with self.subTest(failure=label):
                    run, cube, build, processes, results = self._startUc2Run(fixture)
                    run.start()
                    if writeMap:
                        build.outputPath(cube).write_bytes(
                            self._uc2PngBytes(self._fixtureImage(lines=cube.lines,
                                                                 samples=cube.samples)))
                    processes[0].emitOutput(stdout=stdout)
                    processes[0].emitFinished(exitCode)
                    self.assertEqual(len(results), 1)
                    self.assertFalse(results[0].success)
                    self.assertIsNone(results[0].image)
                    self.assertIn(fragment, results[0].message)
                    self.assertFalse(fixture["uc2Lock"].exists())

            with self.subTest(outcome="success"):
                run, cube, build, processes, results = self._startUc2Run(fixture)
                run.start()
                image = self._fixtureImage(lines=cube.lines, samples=cube.samples, seed=2)
                build.outputPath(cube).write_bytes(self._uc2PngBytes(image))
                processes[0].emitFinished(0)
                self.assertTrue(results[0].success, results[0].message)
                np.testing.assert_array_equal(results[0].image, image)
                self.assertFalse(fixture["uc2Lock"].exists())

            with self.subTest(failure="stale map"):
                run, cube, build, processes, results = self._startUc2Run(fixture)
                run.start()
                path = build.outputPath(cube)
                path.write_bytes(self._uc2PngBytes(self._fixtureImage(lines=cube.lines,
                                                                      samples=cube.samples)))
                earlier = time.time() - 120.0
                os.utime(path, (earlier, earlier))
                processes[0].emitFinished(0)
                self.assertFalse(results[0].success)
                self.assertIn("earlier run", results[0].message)

    def test_captureShowsTheVascularMapAlongsideUc1(self) -> None:
        with self._captureSession(uc2=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            # UC2 starts first, and UC1 still runs as before.
            self.assertEqual([Path(process.program).name for process in session["processes"]],
                             [self.UC2_EXECUTABLE_NAME, "stratum.opt.intermediate.exe"])
            self.assertIn("002-04", widget.ui.vascularStatusLabel.text)
            captureId = widget._captureId

            image = self._finishUc2(session, seed=3)
            self.assertTrue(widget.captureInProgress, "The capture ended before UC1 finished")
            self.assertTrue(widget.liveViewFrozen)
            node = widget.logic.vascularMapNode()
            self.assertIsNotNone(node, "The UC2 map was not accepted")
            np.testing.assert_array_equal(np.array(slicer.util.arrayFromVolume(node))[0], image)
            self.assertEqual(self._ijkToRasDirections(node), self.UPRIGHT_LIVE_DIRECTIONS)
            self.assertEqual(node.GetName(), self.UC2_MAP_NAME)
            for attribute, expected in (
                ("SLIAFlow.DataOrigin", "simulated"),
                ("SLIAFlow.RecordedCase", self.CALIBRATED_CUBE_NAME),
                ("SLIAFlow.SimulationDetail", self.UC2_DETAIL),
                ("SLIAFlow.CaptureId", captureId),
            ):
                with self.subTest(attribute=attribute):
                    self.assertEqual(node.GetAttribute(attribute), expected)
            parameters = node.GetAttribute("SLIAFlow.Uc2Parameters")
            for fragment in ("480, 540, 710 nm", "high_in 0.15", "high_out 0.8", "gamma 1",
                             "bValue 3"):
                self.assertIn(fragment, parameters)
            status = widget.ui.vascularStatusLabel.text.lower()
            for fragment in ("002-04", "simulated acquisition", "high_in 0.15",
                             "not comparable between captures", self.NOT_VALIDATED_FRAGMENT):
                self.assertIn(fragment, status)

            self._finishCapture(session, seed=4)
            self.assertFalse(widget.captureInProgress)
            self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"))
            self.assertEqual(widget.logic.vascularMapNode().GetID(), node.GetID(),
                             "UC1 replaced the UC2 map")

            with self.subTest(order="UC1 first"):
                self._showFrame(session, 31)
                widget._onCaptureClicked()
                self.assertIsNone(widget.logic.vascularMapNode(),
                                  "The previous capture's map stayed during the new one")
                self._finishCapture(session, seed=5)
                self.assertTrue(widget.captureInProgress, "The capture ended before UC2 finished")
                self.assertTrue(widget.liveViewFrozen)
                self._finishUc2(session, seed=6)
                self.assertFalse(widget.captureInProgress)
                self.assertFalse(widget.liveViewFrozen)
                self.assertEqual(widget.logic.vascularMapNode().GetAttribute("SLIAFlow.CaptureId"),
                                 widget._captureId)

    def test_uc2FailureOrRefusalLeavesUc1Alone(self) -> None:
        widget = self._moduleRepresentationAndWidget()[1]
        # The panel names what failed and where to read why, nothing else.
        for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
            self.assertNotIn(word, widget.VASCULAR_FAILED_MESSAGE.lower())

        with self.subTest(case="UC2 fails"), self._captureSession(uc2=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishUc2(session, stdout=b"Error reading band 16 from 'x'\n")
            self.assertIsNone(widget.logic.vascularMapNode())
            self.assertIn("Error reading band", widget.ui.vascularStatusLabel.text)
            if widget._presentationActive:
                self.assertEqual(widget.panelMessage(widget.VASCULAR_VIEW_NAME),
                                 widget.VASCULAR_FAILED_MESSAGE)
            self.assertTrue(widget.captureInProgress)
            self._finishCapture(session, seed=1)
            self.assertFalse(widget.captureInProgress)
            self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"),
                                 "A UC2 failure failed UC1")
            self.assertIn("Done", widget.ui.statusLabel.text)

        with self.subTest(case="UC2 not built"), self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self.assertEqual(len(session["processes"]), 1, "A process was created for UC2")
            self.assertIn("build-uc2.ps1", widget.ui.vascularStatusLabel.text)
            self._finishCapture(session, seed=1)
            self.assertFalse(widget.captureInProgress)
            self.assertIsNotNone(widget.logic.outputNode("imageRGB.bmp"))

        with self.subTest(case="UC1 fails"), self._captureSession(uc2=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self._finishCapture(session, exitCode=1)
            self.assertIn("Failed", widget.ui.statusLabel.text)
            self.assertTrue(widget.captureInProgress, "A UC1 failure ended UC2's run")
            image = self._finishUc2(session, seed=2)
            self.assertFalse(widget.captureInProgress)
            np.testing.assert_array_equal(
                np.array(slicer.util.arrayFromVolume(widget.logic.vascularMapNode()))[0], image)

    def test_cancellingTheCaptureKillsUc2AndReleasesItsLock(self) -> None:
        with self._captureSession(uc2=True) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            process = self._uc2Process(session)
            self.assertTrue(session["uc2Lock"].is_file())
            widget._cancelCapture()
            self.assertTrue(process.killed)
            self.assertFalse(session["uc2Lock"].exists(), "The UC2 lock outlived the cancel")
            self.assertIsNone(widget.logic.currentUc2Run)
            self.assertFalse(widget.captureInProgress)
            self.assertFalse(widget.liveViewFrozen)
            self.assertNotIn("Computing", widget.ui.vascularStatusLabel.text)

    def test_vascularMapReachesItsPanelAndNowhereElse(self) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            self.skipTest("Requires the maintained headful Slicer test target")
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        previousLayout = int(layoutNode.GetViewArrangement())
        with self._captureSession(uc2=True) as session:
            widget = session["widget"]
            try:
                self.assertTrue(widget._activatePresentation())
                vascularWidget = layoutManager.sliceWidget(widget.VASCULAR_VIEW_NAME)
                composite = vascularWidget.sliceLogic().GetSliceCompositeNode()
                self.assertIsNone(composite.GetBackgroundVolumeID())

                self._startFakeCamera(session)
                self._showFrame(session, 30)
                widget._onCaptureClicked()
                self._finishUc2(session, seed=7)
                self._finishCapture(session, seed=8)

                node = widget.logic.vascularMapNode()
                self.assertEqual(composite.GetBackgroundVolumeID(), node.GetID())
                self.assertIsNone(composite.GetForegroundVolumeID())
                self.assertIsNone(composite.GetLabelVolumeID())
                self.assertEqual(widget.panelMessage(widget.VASCULAR_VIEW_NAME), "",
                                 "The waiting text stayed over the map")
                self.assertEqual(widget.panelCaption(widget.VASCULAR_VIEW_NAME),
                                 "Enhanced vascularization for recorded cube 002-04")
                for viewName in widget.VIEW_NAMES:
                    if viewName == widget.VASCULAR_VIEW_NAME:
                        continue
                    otherComposite = (
                        layoutManager.sliceWidget(viewName).sliceLogic().GetSliceCompositeNode()
                    )
                    self.assertNotIn(node.GetID(), (otherComposite.GetBackgroundVolumeID(),
                                                    otherComposite.GetForegroundVolumeID()),
                                     f"The map reached {viewName}")

                # A new capture takes the map down until its own arrives.
                self._showFrame(session, 31)
                widget._onCaptureClicked()
                self.assertIsNone(composite.GetBackgroundVolumeID())
                self.assertIn("waiting", widget.panelMessage(widget.VASCULAR_VIEW_NAME).lower())
            finally:
                widget._forgetVascularMap()
                widget._deactivatePresentation(restore=True)
                if int(layoutNode.GetViewArrangement()) != previousLayout:
                    layoutManager.setLayout(previousLayout)
