import unittest

import numpy as np
import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleTest

from .SLIAFlowLogic import SLIAFlowLogic
from .SLIAFlowParameterNode import (
    LIVE_SOURCE_CHOICES,
    LIVE_SOURCE_LAPTOP,
    RESULT_MAP_CHOICES,
    RESULT_MAP_DEVICE_NAMES,
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_MV_CLASS,
    RESULT_MAP_SVM_PROB,
    RESULT_MAP_TMD,
    RESULT_SOURCE_DEVICE_ATTRIBUTE,
    RESULT_SOURCE_GENUINE_ORIGIN,
    RESULT_SOURCE_ORIGIN_ATTRIBUTE,
    RESULT_SOURCE_ROLE_ATTRIBUTE,
)


class SLIAFlowTest(ScriptedLoadableModuleTest):
    """Focused regression tests for the SLIAFlow presentation boundary."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.moduleTestNames = unittest.TestLoader().getTestCaseNames(type(self))

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

    def tearDown(self) -> None:
        super().tearDown()
        backup = getattr(self, "_widgetStateBackup", None)
        widget = self._moduleWidgetOrNone()
        if backup is None or widget is None:
            return
        for name in self.WIDGET_STATE_FIELDS:
            setattr(widget, name, backup[name])
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
    def _validResultValues(resultMap: str):
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
        refreshButton = slicer.util.findChild(representation, "refreshResultButton")
        status = slicer.util.findChild(representation, "statusLabel")

        self.assertIsNotNone(liveSource)
        self.assertFalse(liveSource.isEnabled())
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

    @staticmethod
    def _settleEventLoop(iterations: int = 20) -> None:
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
