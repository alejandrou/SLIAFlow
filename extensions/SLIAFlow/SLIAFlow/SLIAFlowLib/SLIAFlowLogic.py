import datetime
import importlib
import logging
import time
import uuid
from pathlib import Path

import numpy as np
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic
from vtk.util import numpy_support

from .SLIAFlowCalibratedCube import (
    CalibratedCube,
    CalibratedCubeError,
    loadCalibratedCube,
    nearestBand,
    readCalibratedCube,
)
from .SLIAFlowCube import (
    GROUND_TRUTH_CLASSES,
    GROUND_TRUTH_FILE_NAME,
    UNLABELLED_CLASS_ID,
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
    WAVELENGTHS_ATTRIBUTE,
    SLIAFlowParameterNode,
    calibratedCubeDetail,
    uc1ResultDetail,
)
from .SLIAFlowUc1Input import Uc1Input, describeUc1Input
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
    # The one cube every Capture shows in HS Cube and runs UC1 on (ADR-0004
    # decision 1): IUMA's calibrated float32 LCTF capture. UC1 reads it mapped
    # onto its model's bands (SLIA-033, `SLIAFlowUc1Input`).
    CALIBRATED_CUBE_RELATIVE_PATH = (
        Path("input") / "002-04" / "LCTF_Calibrated_Cube_Single.hdr"
    )
    SNAPSHOT_PREFIX = "output_laptop_camera_"
    SNAPSHOT_TIME_FORMAT = "%Y%m%d-%H%M%S"

    OUTPUT_OWNER = "Uc1Output"
    OUTPUT_VOLUME_NAME_FORMAT = "{fileName}"
    OUTPUT_COMPONENTS = 3

    CUBE_OWNER = "RecordedCube"

    # The colour preview: the bands nearest these wavelengths as R, G and B,
    # on one fixed scale where this reflectance is full brightness. A display
    # mapping of a derived picture, never of the cube's stored values.
    PREVIEW_OWNER = "CalibratedCubePreview"
    PREVIEW_WAVELENGTHS_NM = (650.0, 550.0, 470.0)
    PREVIEW_FULL_SCALE_REFLECTANCE = 1.0
    PREVIEW_WAVELENGTHS_ATTRIBUTE = "SLIAFlow.PreviewWavelengthsNm"
    PREVIEW_VOLUME_NAME_FORMAT = "{cube} colour preview"

    # One pixel's stored values against wavelength, for the module panel's plot.
    SPECTRUM_OWNER = "PixelSpectrum"
    SPECTRUM_WAVELENGTH_COLUMN = _("Wavelength (nm)")
    SPECTRUM_VALUE_COLUMN = _("Reflectance (stored value)")
    SPECTRUM_TITLE_FORMAT = _("{cube}, pixel column {column}, row {row}")

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
    CAMERA_DISPLAY_ERROR_MESSAGE = _(
        "The camera frame could not be drawn, so LiveView was stopped. The "
        "camera itself is fine. Reload the module, or switch to the SLIAFlow "
        "layout and start LiveView again."
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
        self._calibratedCubeHeaderOverride = None
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
            rgbFrame = self.frameToRGBKJI(bgrFrame)
        except Exception:
            logging.exception("SLIAFlow: the camera stopped providing valid frames")
            self.stopCamera()
            errorCallback(self.CAMERA_READ_ERROR_MESSAGE)
            return

        try:
            frameCallback(rgbFrame)
        except Exception:
            # Drawing the frame is not reading it. A closed view, a removed
            # node or a VTK error reported as a camera fault sends the operator
            # to the device, and none of the advice that comes with that
            # message can fix it. The traceback is logged because this branch
            # is the only record of what actually failed.
            logging.exception("SLIAFlow: the camera frame could not be displayed")
            self.stopCamera()
            errorCallback(self.CAMERA_DISPLAY_ERROR_MESSAGE)

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

        Any run in progress is cancelled first, and the calibrated cube returns
        to the new environment's default, so nothing from the previous
        environment carries over.
        """
        self.cancelRun()
        self._repositoryRootOverride = None if repositoryRoot is None else Path(repositoryRoot)
        self._processFactory = processFactory
        self._calibratedCubeHeaderOverride = None

    @property
    def repositoryRoot(self) -> Path:
        if self._repositoryRootOverride is not None:
            return self._repositoryRootOverride
        return findRepositoryRoot(Path(__file__))

    @property
    def capturesDirectory(self) -> Path:
        return self.repositoryRoot / self.CAPTURES_RELATIVE_PATH

    @property
    def calibratedCubeHeader(self) -> Path:
        """The header of the one cube every Capture shows in HS Cube and runs UC1 on.

        By default IUMA's 002-04 under the repository; assigning a header
        replaces it and assigning None restores the default.
        """
        if self._calibratedCubeHeaderOverride is not None:
            return self._calibratedCubeHeaderOverride
        return self.repositoryRoot / self.CALIBRATED_CUBE_RELATIVE_PATH

    @calibratedCubeHeader.setter
    def calibratedCubeHeader(self, header) -> None:
        self._calibratedCubeHeaderOverride = None if header is None else Path(header)

    def loadConfiguredCalibratedCube(self) -> CalibratedCube:
        """Describe the configured calibrated cube, or say why it cannot be shown.

        Read at every Capture, so a cube repaired or replaced on disk is picked
        up by the next one without restarting Slicer. The reason names the file
        and the defect only, so it can be written on the panel; the full path
        is `calibratedCubeHeader`.
        """
        try:
            return loadCalibratedCube(self.calibratedCubeHeader)
        except OSError as error:
            raise CalibratedCubeError(
                _("{file} could not be read: {reason}").format(
                    file=self.calibratedCubeHeader.name, reason=error.strerror or error)
            ) from error

    def loadConfiguredUc1Input(self) -> Uc1Input:
        """Describe what UC1 runs on, or say which cube it is and why it cannot be used.

        The configured calibrated cube, checked as for the HS Cube panel and
        then against the band mapping UC1 is run with (ADR-0004 decisions 4
        and 6). Nothing is written until the run starts.
        """
        header = self.calibratedCubeHeader
        try:
            return describeUc1Input(self.loadConfiguredCalibratedCube(),
                                    self.uc1Build.inputDirectory)
        except CalibratedCubeError as error:
            raise CalibratedCubeError(
                _("The configured cube {header} cannot be used: {reason}").format(
                    header=header, reason=error)
            ) from error

    @property
    def uc1Build(self) -> Uc1Build:
        return Uc1Build.forRepository(self.repositoryRoot)

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
        """Start UC1 on the configured cube (a Uc1Input). Raises Uc1RunError if refused.

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

        detail = uc1ResultDetail(case.name)
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
    def acceptCube(cls, cube: CalibratedCube, captureId: str):
        """Put the calibrated cube into the module-owned volume, values as stored.

        The volume's third axis is the band, so a slice view scrolls the cube
        band by band. The file is read straight into the volume's own float32
        buffer: no conversion, and no second copy of a cube that is about half a
        gigabyte. The cube is read from disk, so the acquisition is simulated
        and the node says so (ADR-0004 decision 7), with the wavelengths it
        was recorded at.
        """
        if not captureId:
            raise ValueError(_("A cube needs a capture ID."))
        started = time.perf_counter()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        try:
            node.SetSaveWithScene(False)
            image = vtk.vtkImageData()
            image.SetDimensions(cube.samples, cube.lines, cube.bands)
            image.AllocateScalars(vtk.VTK_FLOAT, 1)
            node.SetAndObserveImageData(image)
            readCalibratedCube(cube, out=slicer.util.arrayFromVolume(node))
            slicer.util.arrayFromVolumeModified(node)
            cls._applyLiveVolumeGeometry(node)
            cls._setCubeProvenance(node, cube.name, captureId)
            node.SetAttribute(WAVELENGTHS_ATTRIBUTE,
                              ",".join(f"{value:g}" for value in cube.wavelengths))
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
        node.SetName(cube.dataPath.name)
        node.SetAttribute(OWNER_ATTRIBUTE, cls.CUBE_OWNER)
        logging.info("SLIAFlow: cube %s (%d x %d x %d float32) read in %.2f s from %s",
                     cube.name, cube.samples, cube.lines, cube.bands,
                     time.perf_counter() - started, cube.dataPath)
        return node

    @staticmethod
    def _setCubeProvenance(node, cubeName: str, captureId: str) -> None:
        node.SetAttribute(DATA_ORIGIN_ATTRIBUTE, SIMULATED_ORIGIN)
        node.SetAttribute(RECORDED_CASE_ATTRIBUTE, cubeName)
        node.SetAttribute(SIMULATION_DETAIL_ATTRIBUTE, calibratedCubeDetail(cubeName))
        node.SetAttribute(CAPTURE_ID_ATTRIBUTE, captureId)

    @classmethod
    def removeCubeNode(cls) -> None:
        """Remove the cube and everything derived from it: preview and spectrum."""
        cls.removeColourPreviewNode()
        cls.removeSpectrumNodes()
        node = cls.cubeNode()
        if node is not None:
            cls._removeVolumeNode(node)

    @staticmethod
    def cubeWavelengths(node) -> tuple:
        """The wavelengths in nm a cube volume was recorded at, one per band."""
        text = node.GetAttribute(WAVELENGTHS_ATTRIBUTE) if node is not None else None
        if not text:
            return ()
        return tuple(float(value) for value in text.split(","))

    @staticmethod
    def cubeBandAt(node, ras) -> int | None:
        """The band a slice through RAS point `ras` shows, or None outside the cube."""
        if node is None or node.GetImageData() is None:
            return None
        rasToIjk = vtk.vtkMatrix4x4()
        node.GetRASToIJKMatrix(rasToIjk)
        band = int(round(rasToIjk.MultiplyPoint((*ras, 1.0))[2]))
        bands = node.GetImageData().GetDimensions()[2]
        return band if 0 <= band < bands else None

    # ------------------------------------------------------------------
    # The colour preview of the calibrated cube
    # ------------------------------------------------------------------

    @classmethod
    def colourPreviewNode(cls):
        """The module-owned colour preview of the cube, or None."""
        for node in slicer.util.getNodesByClass("vtkMRMLVectorVolumeNode"):
            if node.GetAttribute(OWNER_ATTRIBUTE) == cls.PREVIEW_OWNER:
                return node
        return None

    @classmethod
    def previewWavelengths(cls, previewNode) -> tuple:
        """The wavelengths in nm of the preview's R, G and B bands."""
        text = previewNode.GetAttribute(cls.PREVIEW_WAVELENGTHS_ATTRIBUTE) if previewNode else None
        return tuple(float(value) for value in text.split(",")) if text else ()

    @classmethod
    def acceptColourPreview(cls, cubeNode):
        """Build the cube's colour preview: three bands as R, G and B.

        Each channel is the band nearest its target wavelength. All three share
        one fixed display scale, reflectance 0 to PREVIEW_FULL_SCALE_REFLECTANCE,
        rounded half up to 0-255, so the colours compare across channels and
        across captures. It is a band composite, not a photograph, and it
        changes no stored value: the cube volume is only read.
        """
        wavelengths = cls.cubeWavelengths(cubeNode)
        if not wavelengths:
            raise ValueError(_("The cube carries no wavelengths to choose preview bands from."))
        bands = [nearestBand(wavelengths, target) for target in cls.PREVIEW_WAVELENGTHS_NM]
        cube = slicer.util.arrayFromVolume(cubeNode)
        channels = [
            np.floor(np.clip(cube[band], 0.0, cls.PREVIEW_FULL_SCALE_REFLECTANCE)
                     * (255.0 / cls.PREVIEW_FULL_SCALE_REFLECTANCE) + 0.5).astype(np.uint8)
            for band in bands
        ]
        rgb = np.stack(channels, axis=-1)[np.newaxis, ...]

        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
        try:
            node.SetSaveWithScene(False)
            slicer.util.updateVolumeFromArray(node, rgb)
            cls._applyLiveVolumeGeometry(node)
            for attribute in (DATA_ORIGIN_ATTRIBUTE, RECORDED_CASE_ATTRIBUTE,
                              SIMULATION_DETAIL_ATTRIBUTE, CAPTURE_ID_ATTRIBUTE):
                node.SetAttribute(attribute, cubeNode.GetAttribute(attribute))
            node.SetAttribute(cls.PREVIEW_WAVELENGTHS_ATTRIBUTE,
                              ",".join(f"{wavelengths[band]:g}" for band in bands))
            if node.GetDisplayNode() is None:
                node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetSaveWithScene(False)
        except Exception:
            cls._removeVolumeNode(node)
            raise

        cls.removeColourPreviewNode()
        node.SetName(cls.PREVIEW_VOLUME_NAME_FORMAT.format(cube=cubeNode.GetName()))
        node.SetAttribute(OWNER_ATTRIBUTE, cls.PREVIEW_OWNER)
        return node

    @classmethod
    def removeColourPreviewNode(cls) -> None:
        node = cls.colourPreviewNode()
        if node is not None:
            cls._removeVolumeNode(node)

    # ------------------------------------------------------------------
    # One pixel's spectrum
    # ------------------------------------------------------------------

    @classmethod
    def pixelSpectrum(cls, cubeNode, column: int, row: int):
        """Return (wavelengths in nm, stored values) of one pixel of the cube.

        The values are copied out of the volume exactly as stored. A pixel
        outside the cube raises IndexError rather than wrapping around.
        """
        cube = slicer.util.arrayFromVolume(cubeNode)
        _bands, lines, samples = cube.shape
        if not (0 <= column < samples and 0 <= row < lines):
            raise IndexError(f"Pixel ({column}, {row}) is outside a {samples} x {lines} cube.")
        wavelengths = np.array(cls.cubeWavelengths(cubeNode), dtype=np.float64)
        return wavelengths, np.array(cube[:, row, column], copy=True)

    @classmethod
    def _ownedNode(cls, className: str, owner: str):
        for node in slicer.util.getNodesByClass(className):
            if node.GetAttribute(OWNER_ATTRIBUTE) == owner:
                return node
        node = slicer.mrmlScene.AddNewNodeByClass(className)
        node.SetSaveWithScene(False)
        node.SetAttribute(OWNER_ATTRIBUTE, owner)
        return node

    @classmethod
    def showPixelSpectrum(cls, cubeNode, column: int, row: int):
        """Put one pixel's stored values into the module-owned plot, and return its chart."""
        wavelengths, values = cls.pixelSpectrum(cubeNode, column, row)
        table = vtk.vtkTable()
        wavelengthColumn = numpy_support.numpy_to_vtk(wavelengths, deep=True)
        wavelengthColumn.SetName(cls.SPECTRUM_WAVELENGTH_COLUMN)
        valueColumn = numpy_support.numpy_to_vtk(values.astype(np.float32), deep=True)
        valueColumn.SetName(cls.SPECTRUM_VALUE_COLUMN)
        table.AddColumn(wavelengthColumn)
        table.AddColumn(valueColumn)

        tableNode = cls._ownedNode("vtkMRMLTableNode", cls.SPECTRUM_OWNER)
        tableNode.SetAndObserveTable(table)
        for attribute in (DATA_ORIGIN_ATTRIBUTE, RECORDED_CASE_ATTRIBUTE,
                          SIMULATION_DETAIL_ATTRIBUTE, CAPTURE_ID_ATTRIBUTE):
            tableNode.SetAttribute(attribute, cubeNode.GetAttribute(attribute))
        title = cls.SPECTRUM_TITLE_FORMAT.format(
            cube=cubeNode.GetAttribute(RECORDED_CASE_ATTRIBUTE), column=column, row=row)
        tableNode.SetName(title)

        seriesNode = cls._ownedNode("vtkMRMLPlotSeriesNode", cls.SPECTRUM_OWNER)
        seriesNode.SetName(title)
        seriesNode.SetAndObserveTableNodeID(tableNode.GetID())
        seriesNode.SetXColumnName(cls.SPECTRUM_WAVELENGTH_COLUMN)
        seriesNode.SetYColumnName(cls.SPECTRUM_VALUE_COLUMN)
        seriesNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        seriesNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)

        chartNode = cls._ownedNode("vtkMRMLPlotChartNode", cls.SPECTRUM_OWNER)
        chartNode.SetName(title)
        if chartNode.GetPlotSeriesNodeID() != seriesNode.GetID():
            chartNode.RemoveAllPlotSeriesNodeIDs()
            chartNode.AddAndObservePlotSeriesNodeID(seriesNode.GetID())
        chartNode.SetTitle(title)
        chartNode.SetXAxisTitle(cls.SPECTRUM_WAVELENGTH_COLUMN)
        chartNode.SetYAxisTitle(cls.SPECTRUM_VALUE_COLUMN)
        chartNode.SetLegendVisibility(False)
        return chartNode

    @classmethod
    def spectrumPlotViewNode(cls):
        """The module-owned plot view the module panel's plot widget shows."""
        return cls._ownedNode("vtkMRMLPlotViewNode", cls.SPECTRUM_OWNER)

    @classmethod
    def removeSpectrumNodes(cls) -> None:
        """Remove the spectrum's chart, series and table; the plot view stays."""
        for className in ("vtkMRMLPlotChartNode", "vtkMRMLPlotSeriesNode", "vtkMRMLTableNode"):
            for node in list(slicer.util.getNodesByClass(className)):
                if node.GetAttribute(OWNER_ATTRIBUTE) == cls.SPECTRUM_OWNER:
                    slicer.mrmlScene.RemoveNode(node)

    # ------------------------------------------------------------------
    # The ground truth beside the cube, where it has one
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
        """Put the ground truth beside the cube into the module-owned label map.

        `case` is the run's Uc1Input. The ground truth is someone's labelling of
        the cube, read from the cube's own folder; it is not a UC1 output and
        was not computed here. It is a label map rather than a third colour
        image so that Slicer treats it as a layer: it can sit on the Label
        layer over svm.bmp or knn.bmp with the layer's own opacity and outline
        controls, which is the comparison it exists for.

        It carries the same origin, cube and capture attributes as the outputs,
        so no panel can present it as something acquired here and now, and a
        stale ground truth is spotted the same way a stale result is.
        """
        if not captureId:
            raise ValueError(_("A ground truth needs a capture ID."))
        labels = readGroundTruth(case.groundTruthFolder, case.samples, case.lines)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        try:
            node.SetSaveWithScene(False)
            # One slice, so the label map lies in the same plane as the outputs.
            slicer.util.updateVolumeFromArray(node, labels[np.newaxis, ...].astype(np.int16))
            cls._applyLiveVolumeGeometry(node)
            node.SetAttribute(DATA_ORIGIN_ATTRIBUTE, SIMULATED_ORIGIN)
            node.SetAttribute(RECORDED_CASE_ATTRIBUTE, case.name)
            node.SetAttribute(SIMULATION_DETAIL_ATTRIBUTE, calibratedCubeDetail(case.name))
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
