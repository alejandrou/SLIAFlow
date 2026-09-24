import contextlib
import importlib
import io
import time
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
        self.assertEqual(
            sorted(control.objectName for control in interactive),
            sorted(("startButton", "stopButton", "captureButton", "resultOutputSelector",
                    "cubeDisplaySelector")),
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
    # envi.RECORDED_DATASET_MARKER, carried by a recorded case's gtMap.hdr.
    RECORDED_DATASET_MARKER = "HSI Human Brain Database"
    # SLIA-027: the run timeout and the wording.
    UC1_RUN_TIMEOUT_SEC = 60
    STALE_RESULT_LINE = "PREVIOUS RESULT - not from the current capture"
    STALE_STATUS_FRAGMENT = "not from the current capture"
    # contract.recordedCaseDetail("real UC1 pipeline", case).
    RECORDED_DETAIL_FORMAT = "real UC1 pipeline, recorded HSI case {case} (simulated acquisition)"
    RESULT_STATUS_FORMAT = "Recorded case {case} - simulated acquisition"
    SNAPSHOT_NAME_PATTERN = r"^output_laptop_camera_\d{8}-\d{6}(-\d+)?\.png$"

    @staticmethod
    def _helperModule(name: str):
        """Import a SLIA-027 helper module lazily.

        A module-level import would stop the whole test class from loading if
        the module were missing; this way each test fails on its own.
        """
        return importlib.import_module(f".{name}", __package__)

    @staticmethod
    def _enviHeaderText(samples, lines, bands, *, dataType=12, interleave="bsq",
                        byteOrder=0, headerOffset=0):
        # Laid out like a recorded case's header: the wavelength block first,
        # closed on its last value line, with samples and lines after it.
        wavelengths = ", ".join(str(440 + 5 * index) for index in range(bands))
        return (
            "ENVI\n"
            f"bands = {bands}\n"
            f"data type = {dataType}\n"
            f"interleave = {interleave}\n"
            f"header offset = {headerOffset}\n"
            "wavelength units = Nanometers\n"
            f"byte order = {byteOrder}\n"
            f"wavelength = {{{wavelengths}}}\n"
            f"lines = {lines}\n"
            f"samples = {samples}\n"
        )

    def _writeFixtureCase(self, inputRoot: Path, name: str, *, samples=4, lines=3,
                          bands=UC1_MODEL_BAND_COUNT, omit=(), headerOverrides=None,
                          dataBytes=None, marker=True, groundTruthOverrides=None,
                          groundTruthLabels=None) -> Path:
        """Write a placeholder case folder laid out like a recorded case."""
        folder = inputRoot / name
        folder.mkdir(parents=True, exist_ok=True)
        headerOverrides = headerOverrides or {}
        for stem in ("raw", "darkReference", "whiteReference"):
            header = dict(samples=samples, lines=lines, bands=bands)
            header.update(headerOverrides.get(stem, {}))
            options = {
                key: header.pop(key)
                for key in ("dataType", "interleave", "byteOrder", "headerOffset")
                if key in header
            }
            if f"{stem}.hdr" not in omit:
                (folder / f"{stem}.hdr").write_text(
                    self._enviHeaderText(header["samples"], header["lines"], header["bands"],
                                         **options),
                    encoding="ascii",
                )
            if f"{stem}.dat" not in omit:
                size = samples * lines * bands * 2 if dataBytes is None else dataBytes
                (folder / f"{stem}.dat").write_bytes(b"\0" * size)
        classes = self._helperModule("SLIAFlowCube").GROUND_TRUTH_CLASSES
        groundTruth = "ENVI\ndescription = {test fixture"
        if marker:
            groundTruth += f", {self.RECORDED_DATASET_MARKER}"
        groundTruth += "}\n"
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

    def _makeFixtureRepository(self, root: Path, caseNames=("004-02",), **caseOptions) -> dict:
        """A repository-shaped placeholder tree: markers, input cases, staged build."""
        (root / "AGENTS.md").write_text("test fixture\n", encoding="ascii")
        (root / "extensions" / "SLIAFlow").mkdir(parents=True)
        inputRoot = root / "input" / "reference_hsi_brain_db"
        inputRoot.mkdir(parents=True)
        for name in caseNames:
            self._writeFixtureCase(inputRoot, name, **caseOptions)
        calibratedHeader, calibratedValues = self._writeFixtureCalibratedCube(
            root / "input" / self.CALIBRATED_CUBE_NAME)
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
            "inputRoot": inputRoot,
            "buildRoot": buildRoot,
            "source": source,
            "executable": source / "stratum.opt.intermediate.exe",
            "lock": buildRoot / ".uc1-runner.lock",
            "captures": root / "workspace" / "captures",
            "calibratedHeader": calibratedHeader,
            "calibratedValues": calibratedValues,
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
        # fixture cube lies at input/reference_hsi_brain_db/<case> under this.
        root = Path(tempfile.mkdtemp(prefix="slia-fx-"))
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _startRun(self, fixture, caseName="004-02", **runOptions):
        """Start a Uc1Run on a fixture case with a fake process."""
        cubeModule = self._helperModule("SLIAFlowCube")
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        case = cubeModule.loadRecordedCase(fixture["inputRoot"] / caseName)
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
            inputRoot = root / "input" / "reference_hsi_brain_db"
            labels = [1, 2, 3, 4, 0, 0, 0, 0, 0, 0, 0, 0]
            self._writeFixtureCase(inputRoot, "004-02", samples=4, lines=3,
                                   groundTruthLabels=labels)
            case = cubeModule.loadRecordedCase(inputRoot / "004-02")
            groundTruth = cubeModule.readGroundTruth(case)
            self.assertEqual(groundTruth.shape, (case.lines, case.samples))
            self.assertEqual(groundTruth.dtype, np.dtype("uint16"))
            self.assertEqual(groundTruth[0].tolist(), [1, 2, 3, 4])
            self.assertEqual(groundTruth[1].tolist(), [0, 0, 0, 0])

    def test_groundTruthIsRefusedRatherThanReshaped(self) -> None:
        """A gtMap that does not describe this case is refused, not fitted to it."""
        cubeModule = self._helperModule("SLIAFlowCube")
        rejections = {
            # gtMap.hdr carries the marker loadRecordedCase needs, so it is
            # removed after the case loads rather than never written.
            "no gtMap.hdr": (dict(), "gtMap.hdr", "is missing"),
            "no gtMap": (dict(omit=("gtMap",)), None, "is missing"),
            "other dimensions": (
                dict(groundTruthOverrides={"samples": 9}), None, "but the case is"),
            "more than one band": (
                dict(groundTruthOverrides={"bands": 2}), None, "single map of labels"),
            "wrong data type": (
                dict(groundTruthOverrides={"dataType": "4"}), None, "not 12 (uint16)"),
            "wrong interleave": (
                dict(groundTruthOverrides={"interleave": "bsq"}), None, "not bil"),
            "wrong byte order": (
                dict(groundTruthOverrides={"byteOrder": "1"}), None, "not 0 (little-endian)"),
            "a header offset": (
                dict(groundTruthOverrides={"headerOffset": "64"}), None, "header offset"),
            "a class outside the legend": (
                dict(groundTruthLabels=[5] + [0] * 11), None, "only legends"),
            "a short gtMap": (
                dict(groundTruthLabels=[1, 2, 3]), None, "bytes but"),
        }
        for reason, (options, removeAfterLoad, message) in rejections.items():
            with self.subTest(reason=reason):
                with self._fixtureDirectory() as root:
                    inputRoot = root / "input" / "reference_hsi_brain_db"
                    # loadRecordedCase reads only raw/dark/white and the marker,
                    # so the case still loads and only readGroundTruth refuses.
                    folder = self._writeFixtureCase(inputRoot, "004-02", samples=4, lines=3,
                                                    **options)
                    case = cubeModule.loadRecordedCase(folder)
                    if removeAfterLoad is not None:
                        (folder / removeAfterLoad).unlink()
                    with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                        cubeModule.readGroundTruth(case)
                    self.assertIn(message, str(raised.exception))

    def test_groundTruthReadingDoesNotWriteToInput(self) -> None:
        """Reading a ground truth leaves the case folder byte for byte as it was."""
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            inputRoot = root / "input" / "reference_hsi_brain_db"
            self._writeFixtureCase(inputRoot, "004-02", samples=4, lines=3)
            folder = inputRoot / "004-02"
            before = {path.name: (path.stat().st_size, path.read_bytes())
                      for path in sorted(folder.iterdir())}
            case = cubeModule.loadRecordedCase(folder)
            cubeModule.readGroundTruth(case)
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

    # --- The configured cube (SLIA-031, ADR-0004 decision 1) ---------------

    def test_cubeFolderRejectsIncompatibleContents(self) -> None:
        """A cube folder UC1 would misread is refused, each time with a reason."""
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            good = cubeModule.loadRecordedCase(self._writeFixtureCase(root, "good"))
            self.assertEqual((good.samples, good.lines, good.bands), (4, 3, self.UC1_MODEL_BAND_COUNT))
            defects = {
                "missing-header": dict(omit=("darkReference.hdr",)),
                "missing-data": dict(omit=("whiteReference.dat",)),
                "samples-disagree": dict(headerOverrides={"whiteReference": {"samples": 5}}),
                "wrong-bands": dict(bands=92),
                "wrong-data-type": dict(headerOverrides={"raw": {"dataType": 4}}),
                "wrong-interleave": dict(headerOverrides={"raw": {"interleave": "bip"}}),
                "wrong-byte-order": dict(headerOverrides={"darkReference": {"byteOrder": 1}}),
                "header-offset": dict(headerOverrides={"raw": {"headerOffset": 10}}),
                "wrong-data-size": dict(dataBytes=10),
                "not-recorded": dict(marker=False),
            }
            for name, options in defects.items():
                with self.subTest(defect=name):
                    folder = self._writeFixtureCase(root, name, **options)
                    with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                        cubeModule.loadRecordedCase(folder)
                    self.assertTrue(str(raised.exception).strip(),
                                    f"{name} was refused without a reason")
            with self.assertRaises(cubeModule.IncompatibleCaseError):
                cubeModule.loadRecordedCase(root / "absent")

    def test_cubeReadingDoesNotWriteToInput(self) -> None:
        """Describing, reading and re-checking a cube leaves input/ as it was."""
        cubeModule = self._helperModule("SLIAFlowCube")

        def snapshot(root):
            return sorted(
                (str(path.relative_to(root)), path.is_dir(), path.stat().st_size,
                 path.stat().st_mtime_ns)
                for path in root.rglob("*")
            )

        calibratedModule = self._helperModule("SLIAFlowCalibratedCube")
        with self._fixtureDirectory() as root:
            folder = self._writeFixtureCase(root, "004-02")
            broken = self._writeFixtureCase(root, "broken", dataBytes=3)
            calibratedHeader, _values = self._writeFixtureCalibratedCube(root / "002-04")
            brokenCalibrated, _values = self._writeFixtureCalibratedCube(
                root / "broken-calibrated", dataBytes=5)
            before = snapshot(root)
            case = cubeModule.loadRecordedCase(folder)
            cubeModule.readGroundTruth(case)
            cubeModule.assertCaseUnchanged(case)
            with self.assertRaises(cubeModule.IncompatibleCaseError):
                cubeModule.loadRecordedCase(broken)
            calibrated = calibratedModule.loadCalibratedCube(calibratedHeader)
            calibratedModule.readCalibratedCube(calibrated)
            with self.assertRaises(calibratedModule.CalibratedCubeError):
                calibratedModule.loadCalibratedCube(brokenCalibrated)
            self.assertEqual(snapshot(root), before)

    def test_moduleHasNoCasePool(self) -> None:
        """One configured cube: no pool, no shuffling, no deferred-case list."""
        with self.assertRaises(ModuleNotFoundError):
            self._helperModule("SLIAFlowCasePool")
        cubeModule = self._helperModule("SLIAFlowCube")
        for name in ("CasePool", "discoverCases", "DEFERRED_CASES", "DEFERRED_REASON",
                     "NoCompatibleCaseError", "random"):
            self.assertFalse(hasattr(cubeModule, name), f"SLIAFlowCube still has {name}")
        logic = SLIAFlowLogic()
        for name in ("casePool", "inputRoot", "INPUT_RELATIVE_PATH"):
            self.assertFalse(hasattr(logic, name), f"SLIAFlowLogic still has {name}")

    def test_captureUsesTheConfiguredCube(self) -> None:
        """Every Capture runs UC1 on the one configured cube folder, and no other.

        The default is the reference case the project owner chose at the
        specification of SLIA-031: input/reference_hsi_brain_db/020-01.
        """
        with self._captureSession() as session:
            widget = session["widget"]
            root = session["root"]
            reference = self._writeFixtureCase(root / "input" / "reference_hsi_brain_db", "020-01")
            archive = root / "input" / "archive_hsi_brain_db_93_bands" / "bin"
            archived = self._writeFixtureCase(archive, "053-01")
            self._writeFixtureCase(archive, "056-01")

            widget.logic.cubeFolder = None
            self.assertEqual(widget.logic.cubeFolder,
                             root / "input" / "reference_hsi_brain_db" / "020-01")
            self._startFakeCamera(session)
            for configured in (reference, reference, archived, archived):
                if configured == archived:
                    widget.logic.cubeFolder = archived
                self._showFrame(session, 40)
                widget._onCaptureClicked()
                case, _ = self._finishCapture(session)
                self.assertEqual(case.folder, configured.resolve())
                self.assertEqual(session["processes"][-1].arguments, [str(configured.resolve())])
            self.assertEqual(len(session["processes"]), 4)

    def test_configuredCubeIsRefusedWithItsReason(self) -> None:
        """A cube folder that cannot be used ends the Capture, naming it and why."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            configured = session["cube"]
            missing = session["root"] / "input" / "reference_hsi_brain_db" / "absent"
            for label, prepare, folder, reason in (
                ("missing", lambda: None, missing, "is not a folder"),
                ("inconsistent",
                 lambda: (configured / "raw.dat").write_bytes(b"\0" * 10),
                 configured, "raw.dat is 10 bytes"),
            ):
                with self.subTest(defect=label):
                    prepare()
                    widget.logic.cubeFolder = folder
                    self._showFrame(session, 50)
                    widget._onCaptureClicked()
                    status = widget.ui.statusLabel.text
                    self.assertIn(str(folder), status)
                    self.assertIn(reason, status)
                    self.assertEqual(session["processes"], [], "UC1 started on a refused cube")
                    self.assertIsNone(widget.logic.currentRun)
                    self.assertFalse(widget.captureInProgress)
                    self.assertFalse(widget.liveViewFrozen, "LiveView stayed frozen")

    def test_cubeRefusalReasonsAreTranslated(self) -> None:
        """The reason a cube is refused is translated, not only the sentence around it.

        The status bar shows the reason after the translated "The configured
        cube ... cannot be used" prefix, so an untranslated reason would still
        reach the operator in English. Every refusal the module raises is
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
        for module, errorName in ((cubeModule, "IncompatibleCaseError"),
                                  (calibratedModule, "CalibratedCubeError")):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                raises, untranslated = 0, []
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                            and getattr(node.exc.func, "id", None) == errorName):
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
            for name, options in (("missing-header", dict(omit=("darkReference.hdr",))),
                                  ("wrong-bands", dict(bands=92)),
                                  ("wrong-data-size", dict(dataBytes=10)),
                                  ("not-recorded", dict(marker=False))):
                with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                    cubeModule.loadRecordedCase(self._writeFixtureCase(root, name, **options))
                messages[name] = str(raised.exception)
            with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                cubeModule.loadRecordedCase(root / "absent")
            messages["absent"] = str(raised.exception)

            folder = self._writeFixtureCase(root, "changed")
            case = cubeModule.loadRecordedCase(folder)
            self._writeFixtureCase(root, "changed", samples=5)
            with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                cubeModule.assertCaseUnchanged(case)
            messages["changed on disk"] = str(raised.exception)
            (folder / "gtMap").unlink()
            with self.assertRaises(cubeModule.IncompatibleCaseError) as raised:
                cubeModule.readGroundTruth(cubeModule.loadRecordedCase(folder))
            messages["ground truth missing"] = str(raised.exception)

            for name, options in (("calibrated uint16", dict(dataType=12)),
                                  ("calibrated short", dict(dataBytes=10)),
                                  ("calibrated no wavelengths", dict(wavelengths=None, bands=109))):
                header, _values = self._writeFixtureCalibratedCube(root / name, **options)
                with self.assertRaises(calibratedModule.CalibratedCubeError) as raised:
                    calibratedModule.loadCalibratedCube(header)
                messages[name] = str(raised.exception)

        for label, message in messages.items():
            with self.subTest(refusal=label):
                self.assertTrue(message.startswith(marker), f"Not translated: {message!r}")

    def test_runEnvironmentChangeRestoresTheDefaultCube(self) -> None:
        """A cube folder chosen in one run environment does not carry into the next."""
        logic = SLIAFlowLogic()
        with self._fixtureDirectory() as first, self._fixtureDirectory() as second:
            try:
                logic.setRunEnvironment(repositoryRoot=first)
                logic.cubeFolder = first / "input" / "elsewhere"
                logic.setRunEnvironment(repositoryRoot=second)
                self.assertEqual(logic.cubeFolder, second / logic.CUBE_RELATIVE_PATH)
                logic.cubeFolder = second / "input" / "elsewhere"
                logic.setRunEnvironment()
                self.assertEqual(logic.cubeFolder,
                                 logic.repositoryRoot / logic.CUBE_RELATIVE_PATH)
            finally:
                logic.cubeFolder = None
                logic.setRunEnvironment()

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
            fixture = self._makeFixtureRepository(fixtureRoot, caseNames=())
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
            leftover = fixture["source"] / "output" / "004-02" / "pca.bmp"
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
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)

            def refused(expectedFragment, caseName="004-02", inputRoot=None):
                folder = (inputRoot or fixture["inputRoot"]) / caseName
                case = cubeModule.loadRecordedCase(folder)
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
                deepInput = root / ("d" * 60) / ("e" * 60)
                self._writeFixtureCase(deepInput, "004-02")
                refused("128", inputRoot=deepInput)

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

    def test_caseChangedOnDiskIsRefusedRatherThanRunOn(self) -> None:
        """The case is re-read immediately before the run, not trusted from Capture.

        Capture describes the configured cube, then reads its pixels for the
        HS Cube panel before the run starts. The folder lies outside the
        repository and nothing here owns it, so it can be edited or truncated
        in between, and UC1 reads the sizes from the headers without checking
        what it got. The run is refused rather than moved to another case: a
        silent replacement would stamp the result with a case the operator
        never saw chosen.
        """
        uc1Run = self._helperModule("SLIAFlowUc1Run")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)

            # Still a valid case, but no longer the one that was chosen.
            run, case, build, processes, results = self._startRun(fixture)
            self._writeFixtureCase(fixture["inputRoot"], case.name, samples=6, lines=5)
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn("changed on disk", str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a case that had changed")
            self.assertFalse(fixture["lock"].is_file(), "A refused run left the build locked")

            # A case that no longer loads at all.
            run, case, build, processes, results = self._startRun(fixture)
            (fixture["inputRoot"] / case.name / "darkReference.dat").write_bytes(b"")
            with self.assertRaises(uc1Run.Uc1RunError) as raised:
                run.start()
            self.assertIn("darkReference.dat", str(raised.exception))
            self.assertEqual(processes, [], "UC1 was started on a truncated case")
            self.assertFalse(fixture["lock"].is_file(), "A refused run left the build locked")

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
        cubeModule = self._helperModule("SLIAFlowCube")
        with self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            case = cubeModule.loadRecordedCase(fixture["inputRoot"] / "004-02")
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
    def _captureSession(self, caseName="004-02"):
        """The module widget wired to a fixture repository, a fake camera and fake UC1.

        The configured cube is the fixture case `caseName`. With `None` no case
        is written, so the configured folder does not exist.
        """
        _, widget = self._moduleRepresentationAndWidget()
        widget.initializeParameterNode()
        with self._fixtureDirectory() as root:
            caseNames = () if caseName is None else (caseName,)
            fixture = self._makeFixtureRepository(root, caseNames=caseNames)
            factory, processes = self._fakeProcessFactory()
            widget.logic.setRunEnvironment(repositoryRoot=root, processFactory=factory)
            cube = fixture["inputRoot"] / (caseName or "004-02")
            widget.logic.cubeFolder = cube
            capture = self._FakeCameraCapture()
            timer = self._FakeCameraTimer()
            session = dict(fixture, widget=widget, processes=processes, capture=capture,
                           timer=timer, cube=cube)
            try:
                yield session
            finally:
                widget._cancelCapture()
                widget._stopCamera(clearLiveView=True)
                widget.logic.removeOutputNodes()
                widget._forgetCube()
                widget.logic.cubeFolder = None
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
                        self.assertEqual(
                            node.GetAttribute("SLIAFlow.SimulationDetail"),
                            self.RECORDED_DETAIL_FORMAT.format(case=case.name),
                        )
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
                self._writeFixtureCase(session["inputRoot"], "004-02", samples=12, lines=5)
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
        cubeModule = self._helperModule("SLIAFlowCube")
        messages = {}
        with mock.patch.object(slicer.i18n, "translate", translate), \
                self._fixtureDirectory() as root:
            fixture = self._makeFixtureRepository(root)
            case = cubeModule.loadRecordedCase(fixture["inputRoot"] / "004-02")

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
                self._captureSession(caseName=None) as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            with self.subTest(failure="configured cube refused"):
                status = widget.ui.statusLabel.text
                self.assertIn(marker + "The configured cube", status)
                self.assertIn(marker + f"{widget.logic.cubeFolder} is not a folder", status)

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
            widget.CAPTURE_DONE_STATUS.format(case="004-02", snapshot="output.png")
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
        values unchanged, while UC1 still runs on the reference case folder
        until SLIA-033. Its third axis is the band, which is what makes the
        panel scrollable, and it carries ADR-0004 decision 7 provenance.
        """
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            case = widget.logic.currentRun.case
            self.assertEqual(case.folder, session["cube"].resolve(),
                             "UC1 left the reference case before SLIA-033")
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
        with self._captureSession() as session:
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
        with self._captureSession() as session:
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
        with self._captureSession() as session:
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
        with self._captureSession() as session:
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
        with self._captureSession() as session:
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
        with self._captureSession() as session:
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
        """The cube does not need UC1: a refused UC1 case still shows it."""
        with self._captureSession() as session:
            widget = session["widget"]
            self._startFakeCamera(session)
            missing = session["root"] / "input" / "reference_hsi_brain_db" / "absent"
            widget.logic.cubeFolder = missing
            self._showFrame(session, 30)
            widget._onCaptureClicked()
            self.assertIn("is not a folder", widget.ui.statusLabel.text)
            self.assertEqual(session["processes"], [], "UC1 started on a refused case")
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
        """HS Cube names its cube and Tumour Delineation its case, in operator words."""
        with self._capturedPresentation() as (session, layoutManager):
            widget = session["widget"]
            caseName = session["cube"].name
            self._waitForCaption(widget, layoutManager, widget.CUBE_VIEW_NAME,
                                 (self.CALIBRATED_CUBE_NAME,))
            self._waitForCaption(widget, layoutManager, widget.RESULT_VIEW_NAME, (caseName,))
            self.assertNotIn(self.CALIBRATED_CUBE_NAME,
                             widget.panelCaption(widget.RESULT_VIEW_NAME))
            for viewName in (widget.CUBE_VIEW_NAME, widget.RESULT_VIEW_NAME):
                lowered = widget.panelCaption(viewName).lower()
                for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
                    with self.subTest(view=viewName, word=word):
                        self.assertNotIn(word, lowered)

    def test_unreadableCubeIsExplainedOnThePanel(self) -> None:
        """A cube that cannot be shown says why on HS Cube, and UC1 still runs."""
        def truncate(session):
            data = session["calibratedHeader"].with_suffix(".dat")
            data.write_bytes(data.read_bytes()[:-4])

        with self._capturedPresentation(finish=False, prepare=truncate) as (session, _layout):
            widget = session["widget"]
            self.assertIsNone(widget.logic.cubeNode())
            self.assertEqual(len(session["processes"]), 1, "UC1 did not run without the cube")
            message = widget.panelMessage(widget.CUBE_VIEW_NAME)
            self.assertIn(f"{self.CALIBRATED_CUBE_STEM}.dat", message)
            self.assertIn("bytes", message)
            for word in self.PANEL_TEXT_FORBIDDEN_WORDS:
                self.assertNotIn(word, message.lower())
