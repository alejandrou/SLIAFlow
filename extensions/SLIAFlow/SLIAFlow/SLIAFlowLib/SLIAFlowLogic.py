import importlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic

from .SLIAFlowParameterNode import (
    ACQUISITION_PORT,
    CONNECTION_CONNECTING,
    CONNECTION_DISCONNECTED,
    CONNECTION_RECEIVING,
    CONNECTOR_ACQUISITION,
    CONNECTOR_ROLES,
    CONNECTOR_UC1,
    IGTL_HOST,
    LIVE_VIEW_DEVICE_NAME,
    RECOGNIZED_ORIGINS,
    RESULT_MAP_CHOICES,
    RESULT_MAP_DEVICE_NAMES,
    RESULT_MAP_KNN_PROB,
    RESULT_MAP_MV_CLASS,
    RESULT_MAP_MV_PROB,
    RESULT_MAP_SVM_PROB,
    RESULT_MAP_TMD,
    RESULT_SOURCE_ATTRIBUTES,
    RESULT_SOURCE_DETAIL_ATTRIBUTE,
    RESULT_SOURCE_DEVICE_ATTRIBUTE,
    RESULT_SOURCE_GENUINE_ORIGIN,
    RESULT_SOURCE_ORIGIN_ATTRIBUTE,
    RESULT_SOURCE_ROLE_ATTRIBUTE,
    RESULT_SOURCE_SIMULATED_ORIGIN,
    UC1_PORT,
    WIRE_ATTRIBUTE_PREFIX,
    SLIAFlowParameterNode,
)


@dataclass(frozen=True)
class ResultMapDescriptor:
    key: str
    deviceName: str
    displayLabel: str
    components: int
    scalarType: int
    isClassMap: bool


class SLIAFlowLogic(ScriptedLoadableModuleLogic):
    """Own camera resources and validate/present genuine UC1 results."""

    OPENCV_REQUIREMENT = "opencv-python-headless==5.0.0.93"
    CAMERA_WIDTH_PX = 640
    CAMERA_HEIGHT_PX = 480
    CAMERA_TIMER_INTERVAL_MS = 66
    LIVE_VOLUME_NAME = "SLIAFlow Laptop Camera"
    RESULT_VOLUME_NAME = "SLIAFlow UC1 Result"
    SIMULATED_RESULT_VOLUME_NAME = "SLIAFlow UC1 Result (SIMULATED)"
    SIMULATION_DETAIL_MAX_CHARS = 80
    RESULT_OWNER = "ResultPresentation"
    COLOR_OWNER = "ResultPresentation"
    CONNECTOR_OWNER = "Connectors"
    CONNECTOR_ROLE_ATTRIBUTE = "SLIAFlow.Connector"
    CONNECTOR_NODE_CLASS = "vtkMRMLIGTLConnectorNode"
    CONNECTOR_NAMES = {
        CONNECTOR_ACQUISITION: "SLIAFlow Acquisition Link",
        CONNECTOR_UC1: "SLIAFlow UC1 Link",
    }
    CONNECTOR_ENDPOINTS = {
        CONNECTOR_ACQUISITION: (IGTL_HOST, ACQUISITION_PORT),
        CONNECTOR_UC1: (IGTL_HOST, UC1_PORT),
    }
    # vtkMRMLIGTLConnectorNode's state enum, mirrored so that the state
    # translation stays testable in a Slicer that has no OpenIGTLink build.
    # Read from OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNode.h at the pinned
    # commit: StateOff, StateWaitConnection, StateConnected, State_Last.
    CONNECTOR_STATE_OFF = 0
    CONNECTOR_STATE_WAIT_CONNECTION = 1
    CONNECTOR_STATE_CONNECTED = 2
    CONNECTOR_STATE_NAMES = {
        CONNECTOR_STATE_OFF: CONNECTION_DISCONNECTED,
        CONNECTOR_STATE_WAIT_CONNECTION: CONNECTION_CONNECTING,
        CONNECTOR_STATE_CONNECTED: CONNECTION_RECEIVING,
    }
    # The connector's event ids, mirrored from the same header for the same
    # reason: a Slicer without OpenIGTLink must still import this module.
    CONNECTOR_CONNECTED_EVENT = 118944
    CONNECTOR_DISCONNECTED_EVENT = 118945
    CONNECTOR_ACTIVATED_EVENT = 118946
    CONNECTOR_DEACTIVATED_EVENT = 118947
    CONNECTOR_NEW_DEVICE_EVENT = 118949
    CONNECTOR_DEVICE_MODIFIED_EVENT = 118950
    RESULT_CLASS_MIN = 1
    RESULT_CLASS_MAX = 4
    PROBABILITY_COLOR_RAMP = (
        (0.0, 0.0, 0.0, 0.4),
        (0.25, 0.0, 0.8, 1.0),
        (0.5, 0.1, 0.9, 0.1),
        (0.75, 1.0, 0.9, 0.0),
        (1.0, 0.9, 0.0, 0.0),
    )

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

    RESULT_MAP_DESCRIPTORS = {
        RESULT_MAP_TMD: ResultMapDescriptor(
            RESULT_MAP_TMD,
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD],
            "TMD probability",
            1,
            vtk.VTK_FLOAT,
            False,
        ),
        RESULT_MAP_MV_CLASS: ResultMapDescriptor(
            RESULT_MAP_MV_CLASS,
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_MV_CLASS],
            "Majority-voting class",
            1,
            vtk.VTK_UNSIGNED_CHAR,
            True,
        ),
        RESULT_MAP_MV_PROB: ResultMapDescriptor(
            RESULT_MAP_MV_PROB,
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_MV_PROB],
            "Majority-voting probability",
            1,
            vtk.VTK_FLOAT,
            False,
        ),
        RESULT_MAP_SVM_PROB: ResultMapDescriptor(
            RESULT_MAP_SVM_PROB,
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_SVM_PROB],
            "SVM probability",
            4,
            vtk.VTK_FLOAT,
            False,
        ),
        RESULT_MAP_KNN_PROB: ResultMapDescriptor(
            RESULT_MAP_KNN_PROB,
            RESULT_MAP_DEVICE_NAMES[RESULT_MAP_KNN_PROB],
            "KNN probability",
            4,
            vtk.VTK_FLOAT,
            False,
        ),
    }

    def __init__(self) -> None:
        super().__init__()
        self._cameraCapture = None
        self._cameraTimer = None
        self._cameraTimeoutCallback = None
        self._frameCallback = None
        self._errorCallback = None
        # Connectors are held by the logic instance rather than looked up from
        # the scene, so a test can inject a stand-in connector into a Slicer
        # build that has no OpenIGTLink, and so cleanup can never miss one.
        self._connectors: dict[str, Any] = {}

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
    def getOrCreateLiveVolume(parameterNode):
        try:
            liveNode = parameterNode.liveVolume
        except TypeError:
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

    @classmethod
    def supportedResultMaps(cls) -> tuple[str, ...]:
        return tuple(RESULT_MAP_CHOICES)

    @staticmethod
    def resultReferenceNames() -> tuple[str, str]:
        return ("resultSourceVolume", "resultVolume")

    @classmethod
    def resultDescriptor(cls, resultMap: str) -> ResultMapDescriptor | None:
        return cls.RESULT_MAP_DESCRIPTORS.get(resultMap)

    @classmethod
    def _simulationDetail(cls, volumeNode) -> str | None:
        """Return the display-only detail of an already-simulated node.

        The detail is read only once the origin is simulated, so it can never
        become part of what decides whether something is displayable. It is
        free text from outside SLIAFlow, so it is collapsed to a single line
        and truncated before it can reach a text actor.
        """
        if volumeNode is None:
            return None
        origin = volumeNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE)
        if origin != RESULT_SOURCE_SIMULATED_ORIGIN:
            return None
        detail = volumeNode.GetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE)
        if not detail:
            return None
        singleLine = " ".join(str(detail).split())
        if not singleLine:
            return None
        if len(singleLine) > cls.SIMULATION_DETAIL_MAX_CHARS:
            singleLine = (
                singleLine[: cls.SIMULATION_DETAIL_MAX_CHARS - 3].rstrip() + "..."
            )
        return singleLine

    @classmethod
    def _resultReport(
        cls,
        status: str,
        message: str,
        resultMap: str | None = None,
        sourceNode=None,
        descriptor: ResultMapDescriptor | None = None,
        **details,
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "summaryStatus": status,
            "summaryMessage": message,
            "resultMap": resultMap,
            "sourceNodeID": sourceNode.GetID() if sourceNode is not None else None,
            "sourceNodeName": sourceNode.GetName() if sourceNode is not None else None,
            "dataOrigin": (
                None
                if sourceNode is None
                else sourceNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE)
            ),
            "simulationDetail": cls._simulationDetail(sourceNode),
        }
        if descriptor is not None:
            report.update(
                {
                    "deviceName": descriptor.deviceName,
                    "displayMode": "discrete" if descriptor.isClassMap else "continuous",
                    "expectedComponents": descriptor.components,
                    "expectedScalarType": descriptor.scalarType,
                }
            )
        report.update(details)
        return report

    @classmethod
    def validateResultVolume(cls, resultMap: str, volumeNode) -> dict[str, Any]:
        """Validate an external result without changing MRML or display state."""
        descriptor = cls.resultDescriptor(resultMap)
        if descriptor is None:
            return cls._resultReport("FAIL", "Unsupported UC1 result map.", resultMap)
        if volumeNode is None:
            return cls._resultReport(
                "WARN", "No genuine UC1 result is available.", resultMap, descriptor=descriptor
            )
        if not volumeNode.IsA("vtkMRMLVolumeNode"):
            return cls._resultReport(
                "FAIL", "The selected UC1 result is not a volume node.", resultMap, descriptor=descriptor
            )
        expectedNodeClass = (
            "vtkMRMLVectorVolumeNode" if descriptor.components > 1 else "vtkMRMLScalarVolumeNode"
        )
        if not volumeNode.IsA(expectedNodeClass):
            return cls._resultReport(
                "FAIL",
                f"UC1 result requires a {expectedNodeClass}.",
                resultMap,
                volumeNode,
                descriptor,
            )

        imageData = volumeNode.GetImageData()
        if imageData is None or imageData.GetPointData().GetScalars() is None:
            return cls._resultReport(
                "FAIL",
                "The UC1 result has no image scalar data.",
                resultMap,
                volumeNode,
                descriptor,
            )

        dimensions = tuple(int(value) for value in imageData.GetDimensions())
        if len(dimensions) != 3 or any(value <= 0 for value in dimensions):
            return cls._resultReport(
                "FAIL",
                "UC1 result dimensions must be positive.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
            )

        components = int(imageData.GetNumberOfScalarComponents())
        if components != descriptor.components:
            return cls._resultReport(
                "FAIL",
                f"UC1 result requires {descriptor.components} component(s), got {components}.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
            )

        scalarType = int(imageData.GetScalarType())
        if scalarType != descriptor.scalarType:
            return cls._resultReport(
                "FAIL",
                "UC1 result has the wrong scalar type.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
                scalarType=scalarType,
            )

        try:
            values = np.asarray(slicer.util.arrayFromVolume(volumeNode))
        except Exception as exc:
            return cls._resultReport(
                "FAIL",
                f"UC1 result array could not be read: {exc}",
                resultMap,
                volumeNode,
                descriptor,
            )

        expectedDType = (
            np.dtype(np.uint8)
            if descriptor.scalarType == vtk.VTK_UNSIGNED_CHAR
            else np.dtype(np.float32)
        )
        if values.dtype != expectedDType:
            return cls._resultReport(
                "FAIL",
                f"UC1 result requires {expectedDType} values, got {values.dtype}.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
                scalarType=scalarType,
            )

        expectedDimensionCount = 4 if descriptor.components > 1 else 3
        if values.ndim != expectedDimensionCount or (
            descriptor.components > 1 and values.shape[-1] != descriptor.components
        ):
            return cls._resultReport(
                "FAIL",
                "UC1 result array shape does not match its component contract.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
            )

        if not np.all(np.isfinite(values)):
            return cls._resultReport(
                "FAIL",
                "UC1 result contains non-finite values.",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
            )

        if descriptor.isClassMap:
            if not np.all(np.isin(values, (1, 2, 3, 4))):
                return cls._resultReport(
                    "FAIL",
                    "UC1 class result values must be 1, 2, 3, or 4.",
                    resultMap,
                    volumeNode,
                    descriptor,
                    dimensions=dimensions,
                    components=components,
                )
        elif np.any(values < 0) or np.any(values > 1):
            return cls._resultReport(
                "FAIL",
                "UC1 probability values must be in the range [0, 1].",
                resultMap,
                volumeNode,
                descriptor,
                dimensions=dimensions,
                components=components,
            )

        return cls._resultReport(
            "PASS",
            "UC1 result passed the image contract.",
            resultMap,
            volumeNode,
            descriptor,
            dimensions=dimensions,
            components=components,
            scalarType=scalarType,
            valueRange=(float(np.min(values)), float(np.max(values))),
        )

    @classmethod
    def _matchesResultSource(
        cls, resultMap: str, volumeNode, requiredOrigin: str
    ) -> bool:
        descriptor = cls.resultDescriptor(resultMap)
        if descriptor is None or volumeNode is None:
            return False
        if not volumeNode.IsA("vtkMRMLVolumeNode"):
            return False
        # A result source comes from outside SLIAFlow. The presentation node
        # carries the role, device and origin attributes copied from whatever
        # it last displayed, so without this check the module would rediscover
        # its own output and re-present stale data as an external result.
        if volumeNode.GetAttribute("SLIAFlow.Owner") is not None:
            return False
        if volumeNode.GetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE) != resultMap:
            return False
        if volumeNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE) != requiredOrigin:
            return False
        deviceName = volumeNode.GetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE)
        if deviceName is not None:
            return deviceName == descriptor.deviceName
        return volumeNode.GetName() == descriptor.deviceName

    @classmethod
    def isGenuineResultSource(cls, resultMap: str, volumeNode) -> bool:
        return cls._matchesResultSource(
            resultMap, volumeNode, RESULT_SOURCE_GENUINE_ORIGIN
        )

    @classmethod
    def isSimulatedResultSource(cls, resultMap: str, volumeNode) -> bool:
        return cls._matchesResultSource(
            resultMap, volumeNode, RESULT_SOURCE_SIMULATED_ORIGIN
        )

    @classmethod
    def findResultSource(cls, resultMap: str, allowSimulated: bool = False):
        """Find a source for one map role, preferring a genuine one.

        The two passes are deliberate: a genuine source always wins, so a
        simulated node left in the scene can never displace a real result
        merely by being created later.
        """
        volumeNodes = slicer.util.getNodesByClass("vtkMRMLVolumeNode")
        for volumeNode in volumeNodes:
            if cls.isGenuineResultSource(resultMap, volumeNode):
                return volumeNode
        if not allowSimulated:
            return None
        for volumeNode in volumeNodes:
            if cls.isSimulatedResultSource(resultMap, volumeNode):
                return volumeNode
        return None

    # ------------------------------------------------------------------
    # OpenIGTLink reception
    #
    # Everything that knows a network exists lives in this section. Discovery,
    # validation and the SLIA-010 origin gate above it read canonical
    # SLIAFlow.* attributes and nothing else.
    # ------------------------------------------------------------------

    @classmethod
    def openIGTLinkAvailable(cls) -> bool:
        """Whether this Slicer build actually loaded the connector class."""
        return hasattr(slicer, cls.CONNECTOR_NODE_CLASS)

    @classmethod
    def normalizeReceivedProvenance(cls, volumeNode=None) -> int:
        """Translate incoming wire attributes onto the canonical names.

        `vtkMRMLIGTLConnectorNode` copies every incoming metadata entry onto
        the node as `"OpenIGTLink." + key`, unconditionally, so a message sent
        as `SLIAFlow.DataOrigin` arrives as `OpenIGTLink.SLIAFlow.DataOrigin`
        and the bare spelling never appears. Both spellings are accepted here:
        the prefixed one is what the pinned build produces and is the one that
        must work, and accepting the bare one as well costs a line and keeps
        the receiver working if the pin ever moves to a build that behaves
        differently.

        The prefixed value wins when both are present, because the bare one can
        only be a copy this method made from an earlier message.

        The translation mirrors the wire rather than accumulating from it. For
        a node whose producer speaks the prefixed dialect, a canonical
        attribute whose prefixed counterpart is absent is removed, so a value
        this method wrote for an earlier message can never go on
        authenticating a node the wire no longer describes. Nodes carrying no
        prefixed attribute at all are left alone, because for them the
        canonical name is the wire name and there is nothing to mirror.

        Module-owned nodes are skipped: the presentation volume carries copies
        of these attributes and never arrives from a wire.
        """
        nodes = (
            slicer.util.getNodesByClass("vtkMRMLVolumeNode")
            if volumeNode is None
            else [volumeNode]
        )
        translated = 0
        for node in nodes:
            if node is None or node.GetAttribute("SLIAFlow.Owner") is not None:
                continue
            wireValues = {
                attribute: node.GetAttribute(WIRE_ATTRIBUTE_PREFIX + attribute)
                for attribute in RESULT_SOURCE_ATTRIBUTES
            }
            speaksPrefixed = any(value is not None for value in wireValues.values())
            for attribute, wireValue in wireValues.items():
                current = node.GetAttribute(attribute)
                if wireValue is None:
                    if speaksPrefixed and current is not None:
                        node.RemoveAttribute(attribute)
                        translated += 1
                    continue
                if current == wireValue:
                    continue
                node.SetAttribute(attribute, wireValue)
                translated += 1
        return translated

    @staticmethod
    def receivedOrigin(volumeNode) -> str | None:
        """Return the node's origin only when it is one of the two recognized.

        Absent, empty or unrecognized provenance returns None. It is neither
        genuine nor simulated, and it is never widened into a default.
        """
        if volumeNode is None:
            return None
        origin = volumeNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE)
        return origin if origin in RECOGNIZED_ORIGINS else None

    @classmethod
    def findReceivedNode(cls, deviceName: str, nodeClass: str = "vtkMRMLVolumeNode"):
        """Find an externally produced node by its exact device name.

        The declared device attribute is authoritative; the node name is the
        fallback for a producer that has not sent one. Matching is exact, so a
        near-miss device name is not found rather than guessed at.
        """
        for node in slicer.util.getNodesByClass(nodeClass):
            if node.GetAttribute("SLIAFlow.Owner") is not None:
                continue
            cls.normalizeReceivedProvenance(node)
            declared = node.GetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE)
            if declared == deviceName:
                return node
            if declared is None and node.GetName() == deviceName:
                return node
        return None

    @classmethod
    def findLiveViewNode(cls):
        """Find the received `LiveView` node, whatever its provenance."""
        return cls.findReceivedNode(LIVE_VIEW_DEVICE_NAME)

    @classmethod
    def validateLiveViewNode(cls, volumeNode) -> dict[str, Any]:
        """Check that a received live frame can be shown, without interpreting it.

        The live pane is a camera image, not a result, so the UC1 result
        contract does not apply to it. What does apply is that nothing reaches
        a view before it is known to be displayable.
        """
        if volumeNode is None:
            return cls._resultReport("WARN", "No LiveView stream has been received.")
        if not volumeNode.IsA("vtkMRMLVolumeNode"):
            return cls._resultReport("FAIL", "The LiveView node is not a volume node.")
        imageData = volumeNode.GetImageData()
        if imageData is None or imageData.GetPointData().GetScalars() is None:
            return cls._resultReport(
                "FAIL",
                "The LiveView node has no image scalar data.",
                sourceNode=volumeNode,
            )
        if any(int(value) <= 0 for value in imageData.GetDimensions()):
            return cls._resultReport(
                "FAIL", "LiveView dimensions must be positive.", sourceNode=volumeNode
            )
        return cls._resultReport(
            "PASS", "Displaying the received LiveView stream.", sourceNode=volumeNode
        )

    @classmethod
    def unrecognizedProvenanceNode(cls, resultMap: str):
        """Return a received node that claims this role without a valid origin.

        Such a node is neither genuine nor simulated, so it is reported invalid
        rather than shown - and rather than reported as a source that has not
        arrived, which would read as a transport failure. A node that declares
        no provenance at all makes no claim and keeps the ordinary waiting
        state.
        """
        descriptor = cls.resultDescriptor(resultMap)
        if descriptor is None:
            return None
        for node in slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
            if node.GetAttribute("SLIAFlow.Owner") is not None:
                continue
            cls.normalizeReceivedProvenance(node)
            if not any(
                node.GetAttribute(attribute) for attribute in RESULT_SOURCE_ATTRIBUTES
            ):
                continue
            claimsRole = node.GetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE) == resultMap
            claimsDevice = (
                node.GetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE)
                == descriptor.deviceName
            )
            if not (claimsRole or claimsDevice):
                continue
            if cls.receivedOrigin(node) is None:
                return node
        return None

    # ------------------------------------------------------------------
    # Connector ownership
    # ------------------------------------------------------------------

    def connectorNode(self, role: str):
        return self._connectors.get(role)

    def _createConnectorNode(self, role: str):
        return slicer.mrmlScene.AddNewNodeByClass(
            self.CONNECTOR_NODE_CLASS,
            slicer.mrmlScene.GenerateUniqueName(self.CONNECTOR_NAMES[role]),
        )

    def getOrCreateConnector(self, role: str, *, connectorFactory=None):
        """Return the module-owned client connector for one role.

        Returns None when this Slicer has no OpenIGTLink build, so the module
        stays usable as a camera-only viewer instead of failing to load.
        """
        if role not in CONNECTOR_ROLES:
            raise ValueError(f"Unknown connector role: {role}")
        connector = self._connectors.get(role)
        if connector is not None:
            return connector
        if connectorFactory is None:
            if not self.openIGTLinkAvailable():
                return None
            connectorFactory = self._createConnectorNode
        connector = connectorFactory(role)
        if connector is None:
            return None
        host, port = self.CONNECTOR_ENDPOINTS[role]
        connector.SetAttribute("SLIAFlow.Owner", self.CONNECTOR_OWNER)
        connector.SetAttribute(self.CONNECTOR_ROLE_ATTRIBUTE, role)
        connector.SetSaveWithScene(False)
        connector.SetTypeClient(host, port)
        self._connectors[role] = connector
        return connector

    def startConnector(self, role: str, *, connectorFactory=None) -> str:
        connector = self.getOrCreateConnector(role, connectorFactory=connectorFactory)
        if connector is None:
            return CONNECTION_DISCONNECTED
        connector.Start()
        return self.connectorState(role)

    def stopConnector(self, role: str) -> str:
        """Stop and drop one connector, leaving nodes this module does not own.

        A connector created from the OpenIGTLinkIF panel belongs to whoever
        created it. Only a node carrying this module's connector ownership is
        removed from the scene.
        """
        connector = self._connectors.pop(role, None)
        if connector is None:
            return CONNECTION_DISCONNECTED
        try:
            connector.Stop()
        except Exception:
            pass
        try:
            if connector.GetAttribute("SLIAFlow.Owner") == self.CONNECTOR_OWNER:
                slicer.mrmlScene.RemoveNode(connector)
        except Exception:
            pass
        return CONNECTION_DISCONNECTED

    def stopAllConnectors(self) -> None:
        for role in list(self._connectors):
            self.stopConnector(role)

    @classmethod
    def connectorStateName(cls, stateValue) -> str:
        """Translate the connector's state enum into the panel vocabulary."""
        try:
            return cls.CONNECTOR_STATE_NAMES[int(stateValue)]
        except (TypeError, ValueError, KeyError):
            return CONNECTION_DISCONNECTED

    def connectorState(self, role: str) -> str:
        connector = self._connectors.get(role)
        if connector is None:
            return CONNECTION_DISCONNECTED
        try:
            return self.connectorStateName(connector.GetState())
        except Exception:
            return CONNECTION_DISCONNECTED

    @staticmethod
    def extractSelectedResultComponent(volumeNode, resultClass: int = 1):
        if volumeNode is None:
            return None
        try:
            values = np.asarray(slicer.util.arrayFromVolume(volumeNode))
        except Exception:
            return None
        if values.ndim == 4:
            if not 1 <= int(resultClass) <= values.shape[-1]:
                return None
            return np.array(values[..., int(resultClass) - 1], copy=True)
        if values.ndim == 3 and int(resultClass) == 1:
            return np.array(values, copy=True)
        return None

    @classmethod
    def _ownedNode(cls, className: str, owner: str, nodeName: str):
        for node in slicer.util.getNodesByClass(className):
            if node.GetAttribute("SLIAFlow.Owner") == owner:
                return node
        return slicer.mrmlScene.AddNewNodeByClass(
            className, slicer.mrmlScene.GenerateUniqueName(nodeName)
        )

    @classmethod
    def getOrCreateResultVolume(cls, parameterNode):
        try:
            resultNode = parameterNode.resultVolume
        except (KeyError, TypeError):
            resultNode = None
        if resultNode is None or not resultNode.IsA("vtkMRMLScalarVolumeNode"):
            resultNode = None
        if resultNode is None or resultNode.GetAttribute("SLIAFlow.Owner") != cls.RESULT_OWNER:
            resultNode = cls._ownedNode(
                "vtkMRMLScalarVolumeNode", cls.RESULT_OWNER, cls.RESULT_VOLUME_NAME
            )
            resultNode.SetAttribute("SLIAFlow.Owner", cls.RESULT_OWNER)
            resultNode.SetSaveWithScene(False)
            resultNode.CreateDefaultDisplayNodes()
            parameterNode.resultVolume = resultNode
        return resultNode

    @classmethod
    def _getOrCreateProbabilityColorNode(cls):
        colorNode = cls._ownedNode(
            "vtkMRMLProceduralColorNode", cls.COLOR_OWNER, "SLIAFlow Probability Colors"
        )
        colorNode.SetAttribute("SLIAFlow.Owner", cls.COLOR_OWNER)
        colorNode.SetAttribute("SLIAFlow.ColorRole", "probability")
        colorNode.SetSaveWithScene(False)
        colorNode.SetHideFromEditors(True)
        # A vtkMRMLProceduralColorNode is constructed with an empty transfer
        # function, so the ramp has to be written into the existing function
        # instead of only replacing a missing one.
        transferFunction = colorNode.GetColorTransferFunction()
        if transferFunction is None:
            transferFunction = vtk.vtkColorTransferFunction()
            colorNode.SetAndObserveColorTransferFunction(transferFunction)
        transferFunction.RemoveAllPoints()
        transferFunction.SetColorSpaceToRGB()
        for position, red, green, blue in cls.PROBABILITY_COLOR_RAMP:
            transferFunction.AddRGBPoint(position, red, green, blue)
        return colorNode

    @classmethod
    def _getOrCreateClassColorNode(cls):
        colorNode = cls._ownedNode(
            "vtkMRMLColorTableNode", cls.COLOR_OWNER, "SLIAFlow UC1 Class Colors"
        )
        colorNode.SetAttribute("SLIAFlow.Owner", cls.COLOR_OWNER)
        colorNode.SetAttribute("SLIAFlow.ColorRole", "class")
        colorNode.SetSaveWithScene(False)
        colorNode.SetHideFromEditors(True)
        colorNode.SetTypeToUser()
        colorNode.SetNumberOfColors(5)
        colors = (
            ("Unused", 0.0, 0.0, 0.0, 0.0),
            ("Normal", 0.1, 0.8, 0.2, 1.0),
            ("Tumour", 0.9, 0.1, 0.1, 1.0),
            ("Hypervascularized", 1.0, 0.65, 0.0, 1.0),
            ("Background", 0.2, 0.2, 0.2, 1.0),
        )
        for index, (name, red, green, blue, alpha) in enumerate(colors):
            colorNode.SetColor(index, name, red, green, blue, alpha)
        return colorNode

    @classmethod
    def _configureResultDisplay(cls, resultNode, descriptor: ResultMapDescriptor):
        displayNode = resultNode.GetDisplayNode()
        if displayNode is None:
            resultNode.CreateDefaultDisplayNodes()
            displayNode = resultNode.GetDisplayNode()
        colorNode = (
            cls._getOrCreateClassColorNode()
            if descriptor.isClassMap
            else cls._getOrCreateProbabilityColorNode()
        )
        displayNode.SetSaveWithScene(False)
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        # The scalar-volume slice pipeline maps voxels through window/level
        # before the colour node, so the contract range must be pinned there.
        # The display node scalar range never reaches that pipeline, and the
        # default automatic window/level would stretch a genuine [0,1] map to
        # its own extrema and misrepresent it.
        displayNode.SetAutoWindowLevel(False)
        displayNode.SetWindowLevelMinMax(
            0.0, float(cls.RESULT_CLASS_MAX) if descriptor.isClassMap else 1.0
        )
        if hasattr(displayNode, "SetInterpolate"):
            displayNode.SetInterpolate(not descriptor.isClassMap)
        return displayNode

    @classmethod
    def clearResultReferences(cls, parameterNode) -> None:
        parameterNode.parameterNode.SetNodeReferenceID("resultSourceVolume", None)
        parameterNode.parameterNode.SetNodeReferenceID("resultVolume", None)

    def presentResult(
        self,
        resultMap: str,
        sourceNode,
        resultClass: int = 1,
        parameterNode=None,
    ) -> dict[str, Any]:
        descriptor = self.resultDescriptor(resultMap)
        report = self.validateResultVolume(resultMap, sourceNode)
        if report["summaryStatus"] != "PASS":
            return report
        if descriptor.components > 1:
            if not (
                self.RESULT_CLASS_MIN <= int(resultClass) <= self.RESULT_CLASS_MAX
            ):
                return self._resultReport(
                    "FAIL",
                    "The selected UC1 probability class must be between 1 and 4.",
                    resultMap,
                    sourceNode,
                    descriptor,
                )
        else:
            # Single-component maps have no class component. A class still
            # selected from an earlier SVM/KNN role must not reject them.
            resultClass = self.RESULT_CLASS_MIN

        if parameterNode is None:
            parameterNode = self.getParameterNode()
        values = self.extractSelectedResultComponent(sourceNode, resultClass)
        if values is None:
            return self._resultReport(
                "FAIL",
                "The selected UC1 result component could not be extracted.",
                resultMap,
                sourceNode,
                descriptor,
            )

        resultNode = self.getOrCreateResultVolume(parameterNode)
        try:
            slicer.util.updateVolumeFromArray(resultNode, values)
            resultNode.CopyOrientation(sourceNode)
            resultNode.SetAttribute("SLIAFlow.ResultMap", resultMap)
            resultNode.SetAttribute("SLIAFlow.DeviceName", descriptor.deviceName)
            resultNode.SetAttribute("SLIAFlow.ResultClass", str(int(resultClass)))
            dataOrigin = sourceNode.GetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE)
            resultNode.SetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE, dataOrigin)
            # Renamed on every presentation, not only when simulated, so a node
            # that once carried simulated data cannot keep the marker while
            # displaying a genuine result.
            resultNode.SetName(
                self.SIMULATED_RESULT_VOLUME_NAME
                if dataOrigin == RESULT_SOURCE_SIMULATED_ORIGIN
                else self.RESULT_VOLUME_NAME
            )
            displayNode = self._configureResultDisplay(resultNode, descriptor)
        except Exception as exc:
            return self._resultReport(
                "FAIL",
                f"The validated UC1 result could not be displayed: {exc}",
                resultMap,
                sourceNode,
                descriptor,
            )

        parameterNode.resultSourceVolume = sourceNode
        parameterNode.resultVolume = resultNode
        return self._resultReport(
            "PASS",
            f"Displaying {descriptor.displayLabel} from {descriptor.deviceName}.",
            resultMap,
            sourceNode,
            descriptor,
            resultNodeID=resultNode.GetID(),
            displayNodeID=None if displayNode is None else displayNode.GetID(),
            resultClass=int(resultClass),
        )

    def presentSelectedResult(
        self,
        parameterNode=None,
        resultMap=None,
        resultClass=None,
        allowSimulated: bool = False,
    ):
        if isinstance(parameterNode, str):
            resultMap = parameterNode
            parameterNode = None
        if parameterNode is None:
            parameterNode = self.getParameterNode()
        if resultMap is None:
            resultMap = parameterNode.resultMap
        if resultClass is None:
            resultClass = parameterNode.resultClass

        # The single translation point. Everything below reads canonical
        # SLIAFlow.* attributes and never a wire-prefixed one, so discovery and
        # the origin gate stay unaware that a network exists.
        self.normalizeReceivedProvenance()

        sourceNode = self.findResultSource(resultMap, allowSimulated=allowSimulated)
        if sourceNode is None:
            self.clearResultReferences(parameterNode)
            descriptor = self.resultDescriptor(resultMap)
            claimedNode = self.unrecognizedProvenanceNode(resultMap)
            if claimedNode is not None:
                # Reporting this as "waiting" would read as a transport
                # failure. The data did arrive; it just does not say what it
                # is, and a missing attribute must never widen into a default.
                return self._resultReport(
                    "FAIL",
                    "A received node claims this UC1 role with absent or "
                    "unrecognized provenance.",
                    resultMap,
                    claimedNode,
                    descriptor,
                    provenance="unrecognized",
                )
            # The message names the provenance actually being waited for, so a
            # demo-mode operator is never told a simulated source is missing
            # under the word "genuine".
            accepted = "genuine or simulated" if allowSimulated else "genuine"
            deviceName = descriptor.deviceName if descriptor else "UC1"
            return self._resultReport(
                "WARN",
                f"Waiting for {accepted} {deviceName} result.",
                resultMap,
                descriptor=descriptor,
            )
        return self.presentResult(resultMap, sourceNode, resultClass, parameterNode)
