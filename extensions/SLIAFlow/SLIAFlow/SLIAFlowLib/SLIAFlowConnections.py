"""What arrives on each port of IUMA's acquisition app (SLIA-035).

SLIAFlow connects to the app's three OpenIGTLink servers as a client
(ADR-0004 decision 2) and shows, per port, whether it is connected and what
arrives, in the product's own words.

`ChannelMonitor` turns a connector's state and the messages it imported into
one row of text, from times it is given. It touches neither Slicer nor a
socket, so every rule about states, rates and bands is testable on its own.

`SLIAFlowConnections` owns the module's client connectors
(`vtkMRMLIGTLConnectorNode`) and feeds the monitors. The connectors stay in the
scene, stopped, while SLIAFlow is disconnected, so that OpenIGTLinkIF lists the
app's ports as IUMA's team saw them (owner request, 2026-09-25). What it relies
on was read in the pinned SlicerOpenIGTLink source (commit 85e5f764), not
assumed:

- the connector invokes `DeviceModifiedEvent` once per imported message, after
  the image and the message's metadata (as `OpenIGTLink.<key>` attributes) are
  on the incoming node. The node's own `Modified` is held back until the next
  periodic process, so observing the node would merge messages;
- the same event is invoked when a device is removed, so an event counts as a
  message only when an incoming node's data actually changed;
- messages under one device name that arrive faster than OpenIGTLinkIF pulls
  them (a 5 ms timer, a buffer of 3) overwrite each other. What the monitors
  count is what reached the node.

No socket of SLIAFlow's own touches the app's ports: the app serves one client
per port, and a probe connection would be that client.
"""

import time
from collections import deque
from dataclasses import dataclass

try:
    from slicer.i18n import tr as _
except ImportError:  # Outside Slicer, messages stay in English.
    def _(text):
        return text

CHANNEL_LIVE_VIEW = "LiveView"
CHANNEL_STEREO = "Stereo"
CHANNEL_HS_CUBE = "HS Cube"
CHANNELS = (CHANNEL_LIVE_VIEW, CHANNEL_STEREO, CHANNEL_HS_CUBE)

# IUMA's app (docs/hardware/acquisition_app_and_hardware.md section 4) and the
# band count of 002-04 (ADR-0004 decision 1).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = {CHANNEL_LIVE_VIEW: 18944, CHANNEL_STEREO: 18945, CHANNEL_HS_CUBE: 18946}
DEFAULT_EXPECTED_BANDS = 109

# vtkMRMLIGTLConnectorNode's state enum, mirrored from its header so that the
# monitor runs without OpenIGTLink: StateOff, StateWaitConnection, StateConnected.
CONNECTOR_STATE_OFF = 0
CONNECTOR_STATE_WAITING = 1
CONNECTOR_STATE_CONNECTED = 2

# Incoming metadata as the connector puts it on the node: "OpenIGTLink." + key.
# The band keys are the SLIA-035 stand-in's (tools/simulators contract.py); the
# real app's are measured in SLIA-030.
DATA_ORIGIN_ATTRIBUTE = "OpenIGTLink.SLIAFlow.DataOrigin"
BAND_NUMBER_ATTRIBUTE = "OpenIGTLink.SLIAFlow.BandNumber"
WAVELENGTH_ATTRIBUTE = "OpenIGTLink.SLIAFlow.WavelengthNm"
SENDER_METADATA_ATTRIBUTES = (DATA_ORIGIN_ATTRIBUTE, BAND_NUMBER_ATTRIBUTE, WAVELENGTH_ATTRIBUTE)
SIMULATED_ORIGIN = "simulated"
# The connector's OriginalNodeNameKey: the device name, kept if the node is renamed.
ORIGINAL_NODE_NAME_ATTRIBUTE = "OriginalNodeName"

# The connector's DeviceTypeToNodeTagMap, read backwards: node tag -> message type.
MESSAGE_TYPE_BY_NODE_TAG = {
    "Volume": "IMAGE",
    "VectorVolume": "IMAGE",
    "StreamingVolume": "VIDEO",
    "IGTLStatus": "STATUS",
    "LinearTransform": "TRANSFORM",
    "Model": "POLYDATA",
    "FiberBundle": "POLYDATA",
    "Text": "STRING",
    "MarkupsFiducial": "POINT",
    "ImageMetaList": "IMGMETA",
    "LabelMetaList": "LBMETA",
    "IGTLTrackingDataSplitter": "TDATA",
}


@dataclass(frozen=True)
class MessageObservation:
    """One message as it reached its node."""

    time: float
    deviceName: str
    messageType: str
    # (i, j, k) of an image, or None.
    size: tuple | None = None
    components: int | None = None
    scalarType: str | None = None
    bandNumber: int | None = None
    wavelengthNm: float | None = None
    simulated: bool = False


@dataclass(frozen=True)
class ChannelRow:
    port: str
    channel: str
    state: str
    lastMessage: str
    received: str
    # The sentence the table has no room for, or "".
    detail: str


def formatBandRanges(bands) -> str:
    """Band numbers with runs as ranges: `5, 17, 80-84`."""
    runs = []
    for band in sorted(bands):
        if runs and band == runs[-1][1] + 1:
            runs[-1][1] = band
        else:
            runs.append([band, band])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in runs)


class ChannelMonitor:
    """One port of the app: its connector's state and what arrived on it."""

    STATE_NOT_CONNECTED = _("Not connected")
    STATE_WAITING = _("Waiting for the app")
    STATE_NOT_RUNNING = _("App not running")
    STATE_CONNECTED = _("Connected")
    STATE_RECEIVING = _("Receiving")
    STATE_CUBE_COMPLETE = _("Cube complete")
    STATE_CUBE_INCOMPLETE = _("Cube incomplete")
    STATE_ERROR = _("Error")
    STAND_IN_MARK = _(" (stand-in)")

    NOT_RUNNING_DETAIL = _(
        "Nothing answers on {host}:{port}. Start IUMA's acquisition app or the stand-in; "
        "SLIAFlow keeps trying."
    )
    MISSING_BANDS_DETAIL = _("Missing bands: {bands}.")
    UNNAMED_BANDS_DETAIL = _(
        "The messages do not say which band they are, so missing bands cannot be named."
    )
    NOT_A_BAND_DETAIL = _(
        "HS Cube expects one single-component IMAGE per band; it received {message}."
    )

    # A connector that has tried this long is taken to have nothing to reach.
    # A refused local connection takes about 2 s on Windows (measured, SLIA-035).
    NOT_RUNNING_GRACE_SEC = 3.0
    # Receiving means a message this recent.
    RECEIVING_WINDOW_SEC = 2.0
    # The rate is measured over this window.
    RATE_WINDOW_SEC = 5.0
    # Silence this long ends a cube. It is longer than the app's pause of up to
    # 5 s at the VIS/NIR crossover (acquisition_app_and_hardware.md 2.2).
    CUBE_IDLE_SEC = 10.0

    def __init__(self, channel: str, host: str, port: int, expectedBands: int | None = None,
                 *, notRunningGraceSec: float | None = None,
                 cubeIdleSec: float | None = None) -> None:
        self.channel = channel
        self.host = host
        self.port = int(port)
        self.expectedBands = expectedBands
        self.notRunningGraceSec = (self.NOT_RUNNING_GRACE_SEC if notRunningGraceSec is None
                                   else notRunningGraceSec)
        self.cubeIdleSec = self.CUBE_IDLE_SEC if cubeIdleSec is None else cubeIdleSec
        self._connectorState = CONNECTOR_STATE_OFF
        self._stateSince: float | None = None
        self._error: str | None = None
        self.reset()

    @property
    def isCubeChannel(self) -> bool:
        return self.channel == CHANNEL_HS_CUBE

    def reset(self) -> None:
        """Forget every message and error, as for a new Connect."""
        self._error = None
        self._forgetMessages()

    def _forgetMessages(self) -> None:
        self._messageError: str | None = None
        self._last: MessageObservation | None = None
        self._times: deque = deque()
        self._cubeBands: set = set()
        self._cubeUnnamed = 0
        self._lastBandTime: float | None = None

    def setError(self, reason: str | None) -> None:
        self._error = reason

    def setConnectorState(self, state: int, now: float) -> None:
        if state != self._connectorState:
            if state == CONNECTOR_STATE_CONNECTED:
                # A new connection may be another sender, so nothing the last
                # one delivered carries over. A lost one keeps showing it.
                self._forgetMessages()
            self._connectorState = state
            self._stateSince = now

    def messageReceived(self, message: MessageObservation) -> None:
        self._last = message
        self._times.append(message.time)
        while self._times and self._times[0] < message.time - self.RATE_WINDOW_SEC:
            self._times.popleft()
        if not self.isCubeChannel:
            return
        if message.messageType != "IMAGE" or message.components != 1:
            self._messageError = self.NOT_A_BAND_DETAIL.format(message=self._describe(message))
            return
        self._messageError = None
        if self._startsNewCube(message):
            self._cubeBands = set()
            self._cubeUnnamed = 0
        if message.bandNumber is None:
            self._cubeUnnamed += 1
        else:
            self._cubeBands.add(message.bandNumber)
        self._lastBandTime = message.time

    def _startsNewCube(self, message: MessageObservation) -> bool:
        if self._lastBandTime is None or message.time - self._lastBandTime >= self.cubeIdleSec:
            return True
        if message.bandNumber is not None:
            return message.bandNumber in self._cubeBands
        return bool(self.expectedBands) and self.bandsReceived >= self.expectedBands

    @property
    def bandsReceived(self) -> int:
        return len(self._cubeBands) + self._cubeUnnamed

    @property
    def bandsNamed(self) -> bool:
        """Whether every band of the current cube said which band it is."""
        return self._cubeUnnamed == 0

    def missingBands(self) -> list:
        if not self.expectedBands or not self.bandsNamed:
            return []
        return [band for band in range(1, self.expectedBands + 1) if band not in self._cubeBands]

    def _cubeComplete(self) -> bool:
        if not self.expectedBands or self.bandsReceived == 0:
            return False
        if self.bandsNamed:
            return not self.missingBands()
        return self.bandsReceived >= self.expectedBands

    def _cubeIncomplete(self, now: float) -> bool:
        return (self.bandsReceived > 0 and not self._cubeComplete()
                and now - self._lastBandTime >= self.cubeIdleSec)

    def _state(self, now: float) -> str:
        if self._error:
            return self.STATE_ERROR
        if self._connectorState == CONNECTOR_STATE_OFF:
            return self.STATE_NOT_CONNECTED
        if self._connectorState == CONNECTOR_STATE_WAITING:
            if self._stateSince is not None and now - self._stateSince >= self.notRunningGraceSec:
                return self.STATE_NOT_RUNNING
            return self.STATE_WAITING
        if self.isCubeChannel and self._messageError:
            return self.STATE_ERROR
        if self.isCubeChannel and self._cubeComplete():
            return self.STATE_CUBE_COMPLETE
        if self._last is not None and now - self._last.time < self.RECEIVING_WINDOW_SEC:
            return self.STATE_RECEIVING
        if self.isCubeChannel and self._cubeIncomplete(now):
            return self.STATE_CUBE_INCOMPLETE
        return self.STATE_CONNECTED

    def _detail(self, state: str) -> str:
        if state == self.STATE_ERROR:
            return self._error or self._messageError or ""
        if state == self.STATE_NOT_RUNNING:
            return self.NOT_RUNNING_DETAIL.format(host=self.host, port=self.port)
        if state == self.STATE_CUBE_INCOMPLETE:
            if not self.bandsNamed:
                return self.UNNAMED_BANDS_DETAIL
            return self.MISSING_BANDS_DETAIL.format(bands=formatBandRanges(self.missingBands()))
        return ""

    @staticmethod
    def _describe(message: MessageObservation) -> str:
        text = f"{message.deviceName} - {message.messageType}"
        if message.size:
            width, height = message.size[0], message.size[1]
            text += f" {width} x {height}"
            if len(message.size) > 2 and message.size[2] > 1:
                text += _(", {slices} slices").format(slices=message.size[2])
            if message.components and message.components > 1:
                text += f" x {message.components}"
        if message.scalarType:
            text += f" {message.scalarType}"
        if message.bandNumber is not None:
            text += _(" - band {band}").format(band=message.bandNumber)
            if message.wavelengthNm is not None:
                text += f", {message.wavelengthNm:g} nm"
        return text

    @staticmethod
    def _age(seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds < 60.0:
            return _("{seconds:.1f} s ago").format(seconds=seconds)
        return _("{minutes:.0f} min ago").format(minutes=seconds / 60.0)

    def _rate(self, now: float) -> str:
        recent = [moment for moment in self._times if now - self.RATE_WINDOW_SEC <= moment <= now]
        if len(recent) < 2 or recent[-1] <= recent[0]:
            return ""
        rate = (len(recent) - 1) / (recent[-1] - recent[0])
        unit = _("bands/s") if self.isCubeChannel else _("frames/s")
        return f"{rate:.1f} {unit}"

    def row(self, now: float) -> ChannelRow:
        state = self._state(now)
        detail = self._detail(state)
        if (self._last is not None and self._last.simulated
                and state in (self.STATE_CONNECTED, self.STATE_RECEIVING,
                              self.STATE_CUBE_COMPLETE, self.STATE_CUBE_INCOMPLETE)):
            state += self.STAND_IN_MARK
        lastMessage = "-" if self._last is None else (
            f"{self._describe(self._last)} - {self._age(now - self._last.time)}")
        rate = self._rate(now)
        if self.isCubeChannel:
            received = _("{received} / {expected} bands").format(
                received=self.bandsReceived, expected=self.expectedBands or "?")
            if rate:
                received += f" - {rate}"
        else:
            received = rate or "-"
        return ChannelRow(str(self.port), self.channel, state, lastMessage, received, detail)


class SLIAFlowConnections:
    """The module's client connectors to the app, one per configured port."""

    OWNER_ATTRIBUTE = "SLIAFlow.Owner"
    OWNER = "Connections"
    CONNECTOR_CLASS = "vtkMRMLIGTLConnectorNode"
    CONNECTOR_NAME_FORMAT = "SLIAFlow {channel} ({port})"

    OPENIGTLINK_MISSING_ERROR = _(
        "OpenIGTLink is not available in this Slicer, so SLIAFlow cannot connect."
    )
    EMPTY_HOST_ERROR = _(
        "The host is empty. Enter the address of the computer running the acquisition app."
    )
    SHARED_PORT_ERROR = _(
        "{channels} are all set to port {port}. Give each channel its own port."
    )
    NO_PORT_ERROR = _("No channel has a port. Give at least one channel a port other than 0.")
    START_FAILED_ERROR = _("The connector for {host}:{port} could not start.")

    def __init__(self, openIGTLinkAvailable=None, clock=time.monotonic) -> None:
        self._openIGTLinkAvailable = openIGTLinkAvailable or self._connectorClassLoaded
        self._clock = clock
        # Timings the monitors use; a test can shorten them.
        self.notRunningGraceSec = ChannelMonitor.NOT_RUNNING_GRACE_SEC
        self.cubeIdleSec = ChannelMonitor.CUBE_IDLE_SEC
        self._host = DEFAULT_HOST
        self._ports = dict(DEFAULT_PORTS)
        self._expectedBands = DEFAULT_EXPECTED_BANDS
        self._monitors: dict = {}
        self._connectors: dict = {}
        self._observerTags: list = []
        # Per incoming node ID, the modification time of the data last counted.
        self._countedData: dict = {}
        # Node IDs in the scene at Connect: never removed on Disconnect.
        self._nodeIdsBeforeConnect: set = set()
        self._connected = False
        self.lastError: str | None = None
        self.configure(DEFAULT_HOST, DEFAULT_PORTS, DEFAULT_EXPECTED_BANDS)

    @classmethod
    def _connectorClassLoaded(cls) -> bool:
        import slicer
        return hasattr(slicer, cls.CONNECTOR_CLASS)

    @property
    def connected(self) -> bool:
        return self._connected

    def configure(self, host: str, ports: dict, expectedBands: int) -> None:
        """Set the host, the port of each channel (0: not used) and the expected bands."""
        if self._connected:
            raise RuntimeError("Disconnect before changing the connection settings.")
        listed = bool(self._connectors)
        self._removeConnectors()
        self._host = host or ""
        self._ports = {channel: int(ports.get(channel, 0) or 0) for channel in CHANNELS}
        self._expectedBands = int(expectedBands)
        self._monitors = {
            channel: ChannelMonitor(channel, self._host.strip(), port,
                                    expectedBands=self._expectedBands)
            for channel, port in self._ports.items() if port > 0
        }
        if listed:
            self.listConnectors()

    def monitors(self) -> list:
        return list(self._monitors.values())

    def connectorNodes(self) -> list:
        return list(self._connectors.values())

    def settingsError(self) -> str | None:
        if not self._openIGTLinkAvailable():
            return self.OPENIGTLINK_MISSING_ERROR
        if not self._host.strip():
            return self.EMPTY_HOST_ERROR
        if not self._monitors:
            return self.NO_PORT_ERROR
        byPort: dict = {}
        for channel, port in self._ports.items():
            if port > 0:
                byPort.setdefault(port, []).append(channel)
        for port, channels in byPort.items():
            if len(channels) > 1:
                return self.SHARED_PORT_ERROR.format(channels=" and ".join(channels), port=port)
        return None

    def listConnectors(self) -> None:
        """Put one stopped client connector per configured port in the scene.

        Connectors already there for the current settings are kept; one
        removed from the scene, for example in OpenIGTLinkIF, is listed again.
        """
        if self._connected or not self._openIGTLinkAvailable():
            return
        import slicer
        scene = slicer.mrmlScene
        if (set(self._connectors) == set(self._monitors)
                and all(scene.IsNodePresent(node) for node in self._connectors.values())):
            return
        self._removeConnectors()
        host = self._host.strip()
        for channel, monitor in self._monitors.items():
            connector = scene.AddNewNodeByClass(
                self.CONNECTOR_CLASS,
                self.CONNECTOR_NAME_FORMAT.format(channel=channel, port=monitor.port))
            connector.SetAttribute(self.OWNER_ATTRIBUTE, self.OWNER)
            connector.SetSaveWithScene(False)
            connector.SetTypeClient(host, monitor.port)
            self._connectors[channel] = connector

    def _removeConnectors(self) -> None:
        """Remove the listed connectors from the scene."""
        if not self._connectors:
            return
        import slicer
        scene = slicer.mrmlScene
        for connector in self._connectors.values():
            # Stopped unless started from OpenIGTLinkIF's Active checkbox.
            connector.Stop()
            if scene.IsNodePresent(connector):
                scene.RemoveNode(connector)
        self._connectors = {}

    def connect(self) -> bool:
        """Start one client connector per configured port. False, with the reason, if refused."""
        if self._connected:
            return True
        now = self._clock()
        for monitor in self._monitors.values():
            monitor.reset()
            monitor.notRunningGraceSec = self.notRunningGraceSec
            monitor.cubeIdleSec = self.cubeIdleSec
            monitor.setConnectorState(CONNECTOR_STATE_OFF, now)
        self.lastError = self.settingsError()
        if self.lastError:
            for monitor in self._monitors.values():
                monitor.setError(self.lastError)
            return False

        import slicer
        scene = slicer.mrmlScene
        self.listConnectors()
        self._nodeIdsBeforeConnect = {
            scene.GetNthNode(index).GetID() for index in range(scene.GetNumberOfNodes())
        }
        self._countedData = {}
        host = self._host.strip()
        for channel, connector in self._connectors.items():
            monitor = self._monitors[channel]
            # What the row describes is what the connector reaches, whatever
            # was changed on the listed connector in OpenIGTLinkIF, where its
            # Active checkbox may also have started it: Start() refuses a
            # running connector.
            if connector.GetState() != CONNECTOR_STATE_OFF:
                connector.Stop()
            connector.SetTypeClient(host, monitor.port)
            for event in (connector.ConnectedEvent, connector.DisconnectedEvent,
                          connector.ActivatedEvent, connector.DeactivatedEvent,
                          connector.DeviceModifiedEvent):
                self._observerTags.append(
                    (connector, connector.AddObserver(event, self._onConnectorEvent)))
            if not connector.Start():
                monitor.setError(self.START_FAILED_ERROR.format(host=host, port=monitor.port))
            monitor.setConnectorState(connector.GetState(), now)
        self._connected = True
        return True

    def disconnect(self) -> None:
        """Stop every module connector, which stays listed, and remove the nodes they created.

        `Stop()` blocks while a connection attempt is in progress: up to about
        2 s per connector when nothing listens (measured, SLIA-035).
        """
        import slicer
        scene = slicer.mrmlScene
        for connector, tag in self._observerTags:
            connector.RemoveObserver(tag)
        self._observerTags = []
        received = []
        for connector in self._connectors.values():
            received += [connector.GetIncomingMRMLNode(index)
                         for index in range(connector.GetNumberOfIncomingMRMLNodes())]
            connector.Stop()
        for node in received:
            if node is None or not scene.IsNodePresent(node):
                continue
            if node.GetID() not in self._nodeIdsBeforeConnect:
                scene.RemoveNode(node)
            else:
                # Kept, it would pass the sender's metadata on to the next Connect.
                for name in SENDER_METADATA_ATTRIBUTES:
                    node.RemoveAttribute(name)
        self._countedData = {}
        self._nodeIdsBeforeConnect = set()
        self._connected = False
        now = self._clock()
        for monitor in self._monitors.values():
            monitor.setConnectorState(CONNECTOR_STATE_OFF, now)

    def release(self) -> None:
        """Disconnect, and remove the connectors from the scene too."""
        if self._connected:
            self.disconnect()
        self._removeConnectors()

    def rows(self, now: float | None = None) -> list:
        if now is None:
            now = self._clock()
        self.refresh(now)
        return [monitor.row(now) for monitor in self._monitors.values()]

    def refresh(self, now: float | None = None) -> None:
        """Follow every connector's state and pick up any message not yet counted."""
        if not self._connected:
            # A listed connector is stopped, and what it received was counted.
            return
        if now is None:
            now = self._clock()
        for channel, connector in self._connectors.items():
            self._follow(channel, connector, now)

    def _onConnectorEvent(self, caller, event) -> None:
        for channel, connector in self._connectors.items():
            if connector is caller:
                self._follow(channel, connector, self._clock())
                return

    def _follow(self, channel: str, connector, now: float) -> None:
        """Take the connector's state, count what arrived, and forget a sender that left.

        `GetState()` is the socket thread's own state, which turns Connected
        before anything is received. The connector imports messages before it
        invokes the events it queued, so a new sender's first message can
        arrive ahead of `ConnectedEvent`; taking the state first still forgets
        the previous connection before that message is counted.
        """
        state = connector.GetState()
        self._monitors[channel].setConnectorState(state, now)
        self._countNewMessages(channel, connector, now)
        if state != CONNECTOR_STATE_CONNECTED:
            self._forgetSenderMetadata(connector)

    def _forgetSenderMetadata(self, connector) -> None:
        """Remove the SLIAFlow metadata the last sender left on the incoming nodes.

        The connector copies a message's metadata onto its node but never
        removes a key that a later message leaves out, so the next sender on
        the port would otherwise inherit band numbers and the stand-in mark.
        The last sender's messages have been counted by then (`_follow`), and
        no other sender's can arrive before the connector is connected again.
        The last sender's image stays on its node, without that metadata.
        """
        for index in range(connector.GetNumberOfIncomingMRMLNodes()):
            node = connector.GetIncomingMRMLNode(index)
            if node is None:
                continue
            present = [name for name in SENDER_METADATA_ATTRIBUTES
                       if node.GetAttribute(name) is not None]
            for name in present:
                node.RemoveAttribute(name)
            if present and node.GetID() in self._countedData:
                # A node without image data is stamped with its own
                # modification time, which the removal advanced: not a message.
                self._countedData[node.GetID()] = self._messageStamp(node)[1]

    @staticmethod
    def _messageStamp(node) -> tuple:
        """The node's image data, if any, and the time its last message changed it."""
        data = node.GetImageData() if node.IsA("vtkMRMLVolumeNode") else None
        return data, (data.GetMTime() if data is not None else node.GetMTime())

    def _countNewMessages(self, channel: str, connector, now: float) -> None:
        monitor = self._monitors[channel]
        for index in range(connector.GetNumberOfIncomingMRMLNodes()):
            node = connector.GetIncomingMRMLNode(index)
            if node is None:
                continue
            data, modified = self._messageStamp(node)
            if self._countedData.get(node.GetID(), -1) >= modified:
                continue
            self._countedData[node.GetID()] = modified
            monitor.messageReceived(self._observation(node, data, now))

    @staticmethod
    def _observation(node, data, now: float) -> MessageObservation:
        deviceName = node.GetAttribute(ORIGINAL_NODE_NAME_ATTRIBUTE) or node.GetName() or ""
        messageType = MESSAGE_TYPE_BY_NODE_TAG.get(node.GetNodeTagName(), node.GetNodeTagName())
        size = components = scalarType = None
        if data is not None:
            size = tuple(data.GetDimensions())
            components = data.GetNumberOfScalarComponents()
            scalarType = _scalarTypeName(data)

        def number(attribute, kind):
            try:
                return kind(node.GetAttribute(attribute))
            except (TypeError, ValueError):
                return None

        return MessageObservation(
            time=now, deviceName=deviceName, messageType=messageType, size=size,
            components=components, scalarType=scalarType,
            bandNumber=number(BAND_NUMBER_ATTRIBUTE, int),
            wavelengthNm=number(WAVELENGTH_ATTRIBUTE, float),
            simulated=node.GetAttribute(DATA_ORIGIN_ATTRIBUTE) == SIMULATED_ORIGIN,
        )


def _scalarTypeName(imageData) -> str:
    import vtk
    names = {
        vtk.VTK_CHAR: "int8", vtk.VTK_SIGNED_CHAR: "int8", vtk.VTK_UNSIGNED_CHAR: "uint8",
        vtk.VTK_SHORT: "int16", vtk.VTK_UNSIGNED_SHORT: "uint16",
        vtk.VTK_INT: "int32", vtk.VTK_UNSIGNED_INT: "uint32",
        vtk.VTK_LONG_LONG: "int64", vtk.VTK_UNSIGNED_LONG_LONG: "uint64",
        vtk.VTK_FLOAT: "float32", vtk.VTK_DOUBLE: "float64",
    }
    return names.get(imageData.GetScalarType(), imageData.GetScalarTypeAsString())
