import datetime
import importlib
import uuid
from pathlib import Path

import numpy as np
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic
from vtk.util import numpy_support

from .SLIAFlowCasePool import (
    CUBE_FILE_STEM,
    GROUND_TRUTH_CLASSES,
    GROUND_TRUTH_FILE_NAME,
    UNLABELLED_CLASS_ID,
    CasePool,
    readCube,
    readGroundTruth,
)
from .SLIAFlowParameterNode import (
    CAPTURE_ID_ATTRIBUTE,
    DATA_ORIGIN_ATTRIBUTE,
    OUTPUT_FILE_ATTRIBUTE,
    OWNER_ATTRIBUTE,
    RECORDED_CASE_ATTRIBUTE,
    SIMULATED_ORIGIN,
    SIMULATION_DETAIL_ATTRIBUTE,
    SLIAFlowParameterNode,
    recordedCaseDetail,
)
from .SLIAFlowUc1Run import OUTPUT_FILE_NAMES, Uc1Build, Uc1Run, findRepositoryRoot


class SLIAFlowLogic(ScriptedLoadableModuleLogic):
    """Own the camera, the capture snapshot, the UC1 run and its output nodes."""

    OPENCV_REQUIREMENT = "opencv-python-headless==5.0.0.93"
    CAMERA_WIDTH_PX = 640
    CAMERA_HEIGHT_PX = 480
    CAMERA_TIMER_INTERVAL_MS = 66
    # The panels show a volume by name, so the name is the thing itself and
    # nothing else: the camera stream, or the output file it was decoded from.
    LIVE_VOLUME_NAME = "LiveView"
    # Row-major IJK-to-RAS directions. See _applyLiveVolumeGeometry.
    LIVE_VOLUME_DIRECTIONS = ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0))

    # Where a capture's files live, relative to the repository root.
    CAPTURES_RELATIVE_PATH = Path("workspace") / "captures"
    INPUT_RELATIVE_PATH = Path("input") / "bin" / "bin"
    SNAPSHOT_PREFIX = "output_laptop_camera_"
    SNAPSHOT_TIME_FORMAT = "%Y%m%d-%H%M%S"

    OUTPUT_OWNER = "Uc1Output"
    OUTPUT_VOLUME_NAME_FORMAT = "{fileName}"
    OUTPUT_COMPONENTS = 3

    CUBE_OWNER = "RecordedCube"
    CUBE_VOLUME_NAME = f"{CUBE_FILE_STEM}.dat"

    GROUND_TRUTH_OWNER = "RecordedGroundTruth"
    GROUND_TRUTH_VOLUME_NAME = GROUND_TRUTH_FILE_NAME
    GROUND_TRUTH_COLOR_NODE_NAME = "gtMap classes"

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
        # The run environment. None means the repository this module is in and
        # a real QProcess; a test points both somewhere else.
        self._repositoryRootOverride = None
        self._processFactory = None
        self._casePool = None
        self.currentRun: Uc1Run | None = None

    @staticmethod
    def openCVAvailable(importer=importlib.import_module) -> bool:
        try:
            importer("cv2")
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def frameToRGBKJI(bgrFrame):
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
            capture.set(cv2Module.CAP_PROP_FRAME_WIDTH, self.CAMERA_WIDTH_PX)
            capture.set(cv2Module.CAP_PROP_FRAME_HEIGHT, self.CAMERA_HEIGHT_PX)
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
            frameCallback(self.frameToRGBKJI(bgrFrame))
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
    def _applyLiveVolumeGeometry(liveNode) -> None:
        """Give an image volume upright, unmirrored directions.

        OpenCV row 0 is the top of the picture, and so is row 0 of a decoded UC1
        output image. An Axial slice draws +R to the screen left and +A to the
        screen top, so identity directions show the image rotated 180 degrees.
        RAS directions diag(-1, -1, 1) draw i left to right and j top to bottom,
        upright and unmirrored (SLIA-026). Set only when different, because this
        runs for every camera frame.
        """
        directions = SLIAFlowLogic.LIVE_VOLUME_DIRECTIONS
        current = vtk.vtkMatrix4x4()
        liveNode.GetIJKToRASDirectionMatrix(current)
        if all(
            current.GetElement(row, column) == directions[row][column]
            for row in range(3)
            for column in range(3)
        ):
            return
        liveNode.SetIJKToRASDirections(*(value for line in directions for value in line))

    @staticmethod
    def getOrCreateLiveVolume(parameterNode):
        try:
            liveNode = parameterNode.liveVolume
        except TypeError:
            parameterNode.parameterNode.SetNodeReferenceID("liveVolume", None)
            liveNode = None
        if liveNode is not None and liveNode.IsA("vtkMRMLVectorVolumeNode"):
            # A node created before SLIA-026 still has identity directions.
            SLIAFlowLogic._applyLiveVolumeGeometry(liveNode)
            return liveNode

        liveNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVectorVolumeNode",
            slicer.mrmlScene.GenerateUniqueName(SLIAFlowLogic.LIVE_VOLUME_NAME),
        )
        liveNode.SetAttribute("SLIAFlow.Owner", "LaptopCamera")
        liveNode.SetSaveWithScene(False)
        SLIAFlowLogic._applyLiveVolumeGeometry(liveNode)
        liveNode.CreateDefaultDisplayNodes()
        parameterNode.liveVolume = liveNode
        return liveNode

    def getParameterNode(self) -> SLIAFlowParameterNode:
        return SLIAFlowParameterNode(super().getParameterNode())

    # ------------------------------------------------------------------
    # Run environment (SLIA-027)
    # ------------------------------------------------------------------

    def setRunEnvironment(self, repositoryRoot=None, processFactory=None) -> None:
        """Point runs at another repository tree and process type, or back.

        Any run in progress is cancelled first, and the case pool is rebuilt,
        so nothing from the previous environment carries over.
        """
        self.cancelRun()
        self._repositoryRootOverride = None if repositoryRoot is None else Path(repositoryRoot)
        self._processFactory = processFactory
        self._casePool = None

    @property
    def repositoryRoot(self) -> Path:
        if self._repositoryRootOverride is not None:
            return self._repositoryRootOverride
        return findRepositoryRoot(Path(__file__))

    @property
    def capturesDirectory(self) -> Path:
        return self.repositoryRoot / self.CAPTURES_RELATIVE_PATH

    @property
    def inputRoot(self) -> Path:
        return self.repositoryRoot / self.INPUT_RELATIVE_PATH

    @property
    def uc1Build(self) -> Uc1Build:
        return Uc1Build.forRepository(self.repositoryRoot)

    @property
    def casePool(self) -> CasePool:
        """One shuffled queue of recorded cases for the whole Slicer session."""
        if self._casePool is None:
            self._casePool = CasePool(self.inputRoot)
        return self._casePool

    @staticmethod
    def newCaptureId() -> str:
        """One opaque ID per capture, in the form contract.newCaptureId makes."""
        return uuid.uuid4().hex

    # ------------------------------------------------------------------
    # Capture snapshot
    # ------------------------------------------------------------------

    def saveSnapshot(self, rgbKjiFrame, now=None) -> Path:
        """Save the frozen LiveView frame as a PNG, top row first.

        The name carries the second the capture was taken. A second capture in
        the same second gets `-2`, then `-3`, so no snapshot is overwritten.
        The snapshot records the simulated acquisition; UC1 never reads it.
        """
        frame = np.asarray(rgbKjiFrame)
        if frame.ndim == 4 and frame.shape[0] == 1:
            frame = frame[0]
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(_("A snapshot must be an HxWx3 uint8 RGB frame."))

        directory = self.capturesDirectory
        directory.mkdir(parents=True, exist_ok=True)
        stamp = (now or datetime.datetime.now()).strftime(self.SNAPSHOT_TIME_FORMAT)
        path = directory / f"{self.SNAPSHOT_PREFIX}{stamp}.png"
        suffix = 2
        while path.exists():
            path = directory / f"{self.SNAPSHOT_PREFIX}{stamp}-{suffix}.png"
            suffix += 1

        height, width = frame.shape[:2]
        # vtkPNGWriter writes image row y = 0 as the bottom of the picture, and
        # the frame's row 0 is its top, so the rows are reversed for VTK.
        pixels = np.ascontiguousarray(frame[::-1]).reshape(-1, 3)
        scalars = numpy_support.numpy_to_vtk(pixels, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        scalars.SetNumberOfComponents(3)
        image = vtk.vtkImageData()
        image.SetDimensions(width, height, 1)
        image.GetPointData().SetScalars(scalars)
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputData(image)
        writer.Write()
        if writer.GetErrorCode() != 0 or not path.is_file():
            raise OSError(_("The capture snapshot could not be written to {path}.").format(path=path))
        return path

    # ------------------------------------------------------------------
    # UC1 run
    # ------------------------------------------------------------------

    def startUc1Run(self, case, onFinished, onStage=None) -> Uc1Run:
        """Start UC1 on one recorded case. Raises Uc1RunError if refused.

        `onFinished` receives the Uc1RunResult after `currentRun` is cleared.
        """
        if self.currentRun is not None:
            raise RuntimeError(_("A UC1 run is already in progress."))

        def finished(result) -> None:
            self.currentRun = None
            onFinished(result)

        run = Uc1Run(
            self.uc1Build,
            case,
            finished,
            processFactory=self._processFactory,
            onStage=onStage,
        )
        self.currentRun = run
        try:
            run.start()
        except Exception:
            self.currentRun = None
            raise
        return run

    def cancelRun(self) -> None:
        """Kill and wait for an owned UC1 process, and release the build lock."""
        run, self.currentRun = self.currentRun, None
        if run is not None:
            run.cancel()

    # ------------------------------------------------------------------
    # Output nodes
    # ------------------------------------------------------------------

    @classmethod
    def outputNode(cls, fileName: str):
        """The module-owned volume holding one output image, or None."""
        for node in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode"):
            if (
                node.GetAttribute(OWNER_ATTRIBUTE) == cls.OUTPUT_OWNER
                and node.GetAttribute(OUTPUT_FILE_ATTRIBUTE) == fileName
            ):
                return node
        return None

    @classmethod
    def acceptOutputs(cls, case, captureId: str, outputs: dict) -> dict:
        """Put the five validated images of one run into the output nodes.

        All five are checked, then written into five new nodes. Only when all
        five are complete do they replace the previous result's nodes, so an
        error at any point leaves the previous result whole. Pixels are copied
        exactly as decoded; the volume is given LiveView's upright directions.
        """
        if not captureId:
            raise ValueError(_("An output set needs a capture ID."))
        if set(outputs) != set(OUTPUT_FILE_NAMES):
            raise ValueError(_("An output set needs exactly {expected}, got {actual}.").format(
                expected=", ".join(OUTPUT_FILE_NAMES), actual=", ".join(outputs)
            ))
        expectedShape = (case.lines, case.samples, cls.OUTPUT_COMPONENTS)
        images = {}
        for fileName in OUTPUT_FILE_NAMES:
            image = np.asarray(outputs[fileName])
            if image.dtype != np.uint8 or image.shape != expectedShape:
                raise ValueError(_("{file} is {shape} {dtype}, not {expected} uint8.").format(
                    file=fileName, shape=image.shape, dtype=image.dtype, expected=expectedShape
                ))
            images[fileName] = np.ascontiguousarray(image[np.newaxis, ...])

        detail = recordedCaseDetail(case.name)
        nodes = {}
        try:
            for fileName, values in images.items():
                # Not yet owned: outputNode() keeps finding the previous result.
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
                nodes[fileName] = node
                node.SetSaveWithScene(False)
                slicer.util.updateVolumeFromArray(node, values)
                cls._applyLiveVolumeGeometry(node)
                node.SetAttribute(OUTPUT_FILE_ATTRIBUTE, fileName)
                node.SetAttribute(DATA_ORIGIN_ATTRIBUTE, SIMULATED_ORIGIN)
                node.SetAttribute(RECORDED_CASE_ATTRIBUTE, case.name)
                node.SetAttribute(SIMULATION_DETAIL_ATTRIBUTE, detail)
                node.SetAttribute(CAPTURE_ID_ATTRIBUTE, captureId)
                if node.GetDisplayNode() is None:
                    node.CreateDefaultDisplayNodes()
                displayNode = node.GetDisplayNode()
                if displayNode is not None:
                    displayNode.SetSaveWithScene(False)
        except Exception:
            for node in nodes.values():
                cls._removeVolumeNode(node)
            raise

        cls.removeOutputNodes()
        for fileName, node in nodes.items():
            # The previous nodes are gone, so the plain name is free again;
            # GenerateUniqueName would count up with every capture.
            node.SetName(cls.OUTPUT_VOLUME_NAME_FORMAT.format(fileName=fileName))
            node.SetAttribute(OWNER_ATTRIBUTE, cls.OUTPUT_OWNER)
        return nodes

    # ------------------------------------------------------------------
    # The recorded cube behind a capture
    # ------------------------------------------------------------------

    @classmethod
    def cubeNode(cls):
        """The module-owned volume holding the displayed cube, or None."""
        for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"):
            if node.GetAttribute(OWNER_ATTRIBUTE) == cls.CUBE_OWNER:
                return node
        return None

    @classmethod
    def acceptCube(cls, case, captureId: str):
        """Put one recorded case's acquired cube into the module-owned volume.

        The volume's third axis is the band, so a slice view scrolls the cube
        band by band. The cube is the input of the run, not its result: it
        carries the same origin and case attributes as the outputs so that no
        panel can present it as something acquired here and now.
        """
        if not captureId:
            raise ValueError(_("A cube needs a capture ID."))
        bands = readCube(case)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        try:
            node.SetSaveWithScene(False)
            slicer.util.updateVolumeFromArray(node, bands)
            cls._applyLiveVolumeGeometry(node)
            node.SetAttribute(DATA_ORIGIN_ATTRIBUTE, SIMULATED_ORIGIN)
            node.SetAttribute(RECORDED_CASE_ATTRIBUTE, case.name)
            node.SetAttribute(SIMULATION_DETAIL_ATTRIBUTE, recordedCaseDetail(case.name))
            node.SetAttribute(CAPTURE_ID_ATTRIBUTE, captureId)
            if node.GetDisplayNode() is None:
                node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetSaveWithScene(False)
                # Band brightness varies over the spectrum; one window and level
                # for the whole cube keeps the bands comparable as they scroll.
                displayNode.AutoWindowLevelOn()
        except Exception:
            cls._removeVolumeNode(node)
            raise

        cls.removeCubeNode()
        # The previous node is gone, so the plain name is free again.
        node.SetName(cls.CUBE_VOLUME_NAME)
        node.SetAttribute(OWNER_ATTRIBUTE, cls.CUBE_OWNER)
        return node

    @classmethod
    def removeCubeNode(cls) -> None:
        node = cls.cubeNode()
        if node is not None:
            cls._removeVolumeNode(node)

    # ------------------------------------------------------------------
    # The recorded case's own ground truth
    # ------------------------------------------------------------------

    @classmethod
    def groundTruthNode(cls):
        """The module-owned label map holding the displayed ground truth, or None."""
        for node in slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode"):
            if node.GetAttribute(OWNER_ATTRIBUTE) == cls.GROUND_TRUTH_OWNER:
                return node
        return None

    @classmethod
    def groundTruthColorNode(cls):
        """The module-owned colour table for the gtMap classes, created on first use.

        One table is enough for every case, so it outlives any one result and is
        looked up by owner rather than rebuilt. Class 0 is the absence of a
        label over most of the image, so it is given zero opacity: the label
        layer then shows only what a person actually labelled, and the result
        underneath stays visible everywhere else.
        """
        for node in slicer.util.getNodesByClass("vtkMRMLColorTableNode"):
            if node.GetAttribute(OWNER_ATTRIBUTE) == cls.GROUND_TRUTH_OWNER:
                return node
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode")
        node.SetSaveWithScene(False)
        node.SetTypeToUser()
        node.SetHideFromEditors(False)
        node.SetNumberOfColors(len(GROUND_TRUTH_CLASSES))
        for classId, className, (red, green, blue) in GROUND_TRUTH_CLASSES:
            opacity = 0.0 if classId == UNLABELLED_CLASS_ID else 1.0
            node.SetColor(classId, className, red / 255.0, green / 255.0, blue / 255.0, opacity)
        node.SetName(cls.GROUND_TRUTH_COLOR_NODE_NAME)
        node.SetAttribute(OWNER_ATTRIBUTE, cls.GROUND_TRUTH_OWNER)
        return node

    @classmethod
    def acceptGroundTruth(cls, case, captureId: str):
        """Put one recorded case's ground truth into the module-owned label map.

        This is the database's labelling, read from the case folder; it is not a
        UC1 output and was not computed here. It is a label map rather than a
        third colour image so that Slicer treats it as a layer: it can sit on
        the Label layer over svm.bmp or knn.bmp with the layer's own opacity and
        outline controls, which is the comparison it exists for.

        It carries the same origin, case and capture attributes as the outputs,
        so no panel can present it as something acquired here and now, and a
        stale ground truth is spotted the same way a stale result is.
        """
        if not captureId:
            raise ValueError(_("A ground truth needs a capture ID."))
        labels = readGroundTruth(case)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        try:
            node.SetSaveWithScene(False)
            # One slice, so the label map lies in the same plane as the outputs.
            slicer.util.updateVolumeFromArray(node, labels[np.newaxis, ...].astype(np.int16))
            cls._applyLiveVolumeGeometry(node)
            node.SetAttribute(DATA_ORIGIN_ATTRIBUTE, SIMULATED_ORIGIN)
            node.SetAttribute(RECORDED_CASE_ATTRIBUTE, case.name)
            node.SetAttribute(SIMULATION_DETAIL_ATTRIBUTE, recordedCaseDetail(case.name))
            node.SetAttribute(CAPTURE_ID_ATTRIBUTE, captureId)
            if node.GetDisplayNode() is None:
                node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetSaveWithScene(False)
                displayNode.SetAndObserveColorNodeID(cls.groundTruthColorNode().GetID())
        except Exception:
            cls._removeVolumeNode(node)
            raise

        cls.removeGroundTruthNode()
        # The previous node is gone, so the plain name is free again.
        node.SetName(cls.GROUND_TRUTH_VOLUME_NAME)
        node.SetAttribute(OWNER_ATTRIBUTE, cls.GROUND_TRUTH_OWNER)
        return node

    @classmethod
    def removeGroundTruthNode(cls) -> None:
        node = cls.groundTruthNode()
        if node is not None:
            cls._removeVolumeNode(node)

    @classmethod
    def removeOutputNodes(cls) -> None:
        for fileName in OUTPUT_FILE_NAMES:
            node = cls.outputNode(fileName)
            if node is not None:
                cls._removeVolumeNode(node)

    @staticmethod
    def _removeVolumeNode(node) -> None:
        displayNodes = [node.GetNthDisplayNode(index) for index in range(node.GetNumberOfDisplayNodes())]
        for displayNode in displayNodes:
            if displayNode is not None:
                slicer.mrmlScene.RemoveNode(displayNode)
        slicer.mrmlScene.RemoveNode(node)
