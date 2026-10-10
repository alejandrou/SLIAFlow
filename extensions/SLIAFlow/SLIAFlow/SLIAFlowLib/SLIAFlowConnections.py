"""What arrives on each port of IUMA's acquisition app (SLIA-035, SLIA-036).

SLIAFlow connects to the app's three OpenIGTLink servers as a client
(ADR-0004 decision 2) and shows, per port, whether it is connected and what
arrives, in the product's own words.

`ChannelMonitor` turns a connection's state and the messages it received into
one row of text, from times it is given. It touches neither Slicer nor a
socket, so every rule about states and rates is testable on its own. For the
HS Cube port, what the cube holds comes from the reader's assembler.

`SLIAFlowConnections` owns the module's client connectors
(`vtkMRMLIGTLConnectorNode`) and feeds the monitors. The connectors stay in the
scene, stopped, while SLIAFlow is disconnected, so that OpenIGTLinkIF lists the
app's ports as IUMA's team saw them (owner request, 2026-09-25).

The HS Cube port is read by SLIAFlow's own `HsCubeReader` (SLIA-036), not by
its connector: OpenIGTLinkIF does not say which band of the app's cube a
message is, and drops bands it cannot pull in time. Its connector is still
listed, but never started, because the app serves one client per port and the
reader is that client (owner decision, 2026-10-06).

What the connectors rely on was read in the pinned SlicerOpenIGTLink source
(commit 85e5f764), not assumed:

- the connector invokes `DeviceModifiedEvent` once per imported message, after
  the image and the message's metadata (as `OpenIGTLink.<key>` attributes) are
  on the incoming node. The node's own `Modified` is held back until the next
  periodic process, so observing the node would merge messages;
- the same event is invoked when a device is removed, so an event counts as a
  message only when an incoming node's data actually changed;
- messages under one device name that arrive faster than OpenIGTLinkIF pulls
  them (a 5 ms timer, a buffer of 3) overwrite each other. What the monitors
  count is what reached the node.

No socket of SLIAFlow's own probes the app's ports: the app serves one client
per port, and a probe connection would be that client.

The LiveView port's frames can be shown in the live pane (SLIA-037):
`takeLiveViewFrame` copies the newest frame the connector delivered and has
not handed over yet, so that the connector's own node never reaches a view.
"""

import datetime
import time
from collections import deque
from dataclasses import dataclass

from .SLIAFlowReceivedCube import (
    CUBE_IDLE_SEC,
    CubeProgress,
    HsCubeReader,
    allocateNumpyCube,
)

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
# band count of IUMA's LCTF captures (ADR-0004 context).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = {CHANNEL_LIVE_VIEW: 18944, CHANNEL_STEREO: 18945, CHANNEL_HS_CUBE: 18946}
DEFAULT_EXPECTED_BANDS = 109

# vtkMRMLIGTLConnectorNode's state enum, mirrored from its header so that the
# monitor runs without OpenIGTLink: StateOff, StateWaitConnection, StateConnected.
CONNECTOR_STATE_OFF = 0
CONNECTOR_STATE_WAITING = 1
CONNECTOR_STATE_CONNECTED = 2

# Incoming metadata as the connector puts it on the node: "OpenIGTLink." + key.
# The band keys are the stand-in's (tools/simulators contract.py); the real app
# sends no metadata (SLIA-030).
DATA_ORIGIN_ATTRIBUTE = "OpenIGTLink.SLIAFlow.DataOrigin"
BAND_NUMBER_ATTRIBUTE = "OpenIGTLink.SLIAFlow.BandNumber"
WAVELENGTH_ATTRIBUTE = "OpenIGTLink.SLIAFlow.WavelengthNm"
SIMULATION_DETAIL_ATTRIBUTE = "OpenIGTLink.SLIAFlow.SimulationDetail"
SENDER_METADATA_ATTRIBUTES = (DATA_ORIGIN_ATTRIBUTE, BAND_NUMBER_ATTRIBUTE, WAVELENGTH_ATTRIBUTE,
                              SIMULATION_DETAIL_ATTRIBUTE)
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
class LiveViewFrame:
    """One LiveView frame from the app, copied off the connector's node (SLIA-037)."""

    # (1, lines, samples, 3) RGB uint8, row 0 the top of the picture.
    pixels: object
    simulated: bool
    # The sender's own detail when its message carried one (the stand-in).
    simulationDetail: str | None
    host: str
    port: int
    receivedAt: datetime.datetime


@dataclass(frozen=True)
class LiveViewUpdate:
    """Whether the LiveView port is connected, and the frame or refusal it brought, if any."""

    connected: bool
    frame: LiveViewFrame | None = None
    # The message that cannot be shown, described, or None.
    refusal: str | None = None


def liveViewRefusal(message: MessageObservation) -> str | None:
    """None for a frame the live pane shows, an RGB uint8 IMAGE of one slice; else the message."""
    size = message.size or ()
    if (message.messageType == "IMAGE" and message.components == 3
            and message.scalarType == "uint8" and len(size) == 3 and size[2] == 1):
        return None
    return ChannelMonitor._describe(message)


@dataclass(frozen=True)
class ChannelRow:
    port: str
    channel: str
    state: str
    lastMessage: str
    received: str
    # The sentence the table has no room for, or "".
    detail: str


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
    REFUSED_DETAIL = _(
        "Refused {message}. HS Cube takes one uint16 or float32 band per IMAGE, as the app "
        "sends it; the cube being received is unchanged."
    )
    PREVIOUS_INCOMPLETE_DETAIL = _("The previous cube was incomplete and was not used. {detail}")
    LAST_INCOMPLETE_DETAIL = _("The last cube was incomplete and was not used. {detail}")

    # A connector that has tried this long is taken to have nothing to reach.
    # A refused local connection takes about 2 s on Windows (measured, SLIA-035).
    NOT_RUNNING_GRACE_SEC = 3.0
    # Receiving means a message this recent.
    RECEIVING_WINDOW_SEC = 2.0
    # The rate is measured over this window.
    RATE_WINDOW_SEC = 5.0

    def __init__(self, channel: str, host: str, port: int, expectedBands: int | None = None,
                 *, notRunningGraceSec: float | None = None) -> None:
        self.channel = channel
        self.host = host
        self.port = int(port)
        self.expectedBands = expectedBands
        self.notRunningGraceSec = (self.NOT_RUNNING_GRACE_SEC if notRunningGraceSec is None
                                   else notRunningGraceSec)
        # A sentence about the port itself, added to the row's detail.
        self.note: str | None = None
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
        self._progress = CubeProgress()

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
        self._messageError = None

    def messageRefused(self, message: MessageObservation, reason: str) -> None:
        """A message the HS Cube reader refused: an error until a band is accepted."""
        self.messageReceived(message)
        self._messageError = self.REFUSED_DETAIL.format(message=reason)

    def setCubeProgress(self, progress: CubeProgress) -> None:
        """What the cube holds, as the reader's assembler counts it."""
        self._progress = progress

    @property
    def bandsReceived(self) -> int:
        return self._progress.bandsReceived

    @property
    def bandsExpected(self) -> int | None:
        """The band count the messages declare, or the setting until one arrived."""
        return self._progress.bandsDeclared or self.expectedBands

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
        if self.isCubeChannel and self._progress.complete:
            return self.STATE_CUBE_COMPLETE
        if self._last is not None and now - self._last.time < self.RECEIVING_WINDOW_SEC:
            return self.STATE_RECEIVING
        if self.isCubeChannel and self._progress.incompleteDetail:
            return self.STATE_CUBE_INCOMPLETE
        return self.STATE_CONNECTED

    def _detail(self, state: str) -> str:
        if state == self.STATE_ERROR:
            detail = self._error or self._messageError or ""
        elif state == self.STATE_NOT_RUNNING:
            detail = self.NOT_RUNNING_DETAIL.format(host=self.host, port=self.port)
        elif state == self.STATE_CUBE_INCOMPLETE:
            detail = self._progress.incompleteDetail or ""
        elif self.isCubeChannel and self._progress.previousIncompleteDetail:
            detail = self.PREVIOUS_INCOMPLETE_DETAIL.format(
                detail=self._progress.previousIncompleteDetail)
        else:
            detail = ""
        lost = ""
        if (self.isCubeChannel and self._progress.incompleteDetail
                and state in (self.STATE_WAITING, self.STATE_NOT_RUNNING)):
            # The connection closed with a cube half received: the waiting
            # state must not hide which bands it lacked.
            lost = self.LAST_INCOMPLETE_DETAIL.format(detail=self._progress.incompleteDetail)
        return " ".join(part for part in (detail, lost, self.note) if part)

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
                received=self.bandsReceived, expected=self.bandsExpected or "?")
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
    HS_CUBE_CONNECTOR_STOPPED_NOTE = _(
        "SLIAFlow stopped the HS Cube connector started in OpenIGTLinkIF: the app serves one "
        "client per port, and SLIAFlow reads this one itself."
    )
    # OpenIGTLinkIO's Stop() never returns if it is called just after the
    # connector connected, before its receiver thread first ran: that thread
    # then exits without removing its socket, which Stop() waits for. A
    # connector started elsewhere is stopped only once it has run this long.
    STARTED_CONNECTOR_STOP_DELAY_SEC = 1.0
    # Slicer's main thread keeps Python's GIL while it waits in Qt's event
    # loop, and hands it to another Python thread only while it runs Python
    # itself (discourse.slicer.org/t/32299). The reader then ran a moment every
    # few hundred milliseconds, and the app and the stand-in, whose sends time
    # out, closed the connection after a few bands (SLIA-036 verification).
    # While the reader runs, the main thread sleeps this long, which releases
    # the GIL, whenever its event loop has nothing else to do, as Slicer's
    # SimpleFilters module does.
    GIL_YIELD_SEC = 0.01

    def __init__(self, openIGTLinkAvailable=None, clock=time.monotonic) -> None:
        self._openIGTLinkAvailable = openIGTLinkAvailable or self._connectorClassLoaded
        self._clock = clock
        # Timings the monitors and the reader use; a test can shorten them.
        self.notRunningGraceSec = ChannelMonitor.NOT_RUNNING_GRACE_SEC
        self.cubeIdleSec = CUBE_IDLE_SEC
        # How the HS Cube reader allocates a cube. SLIAFlowLogic gives one that
        # allocates the vtkImageData the volume node then uses without a copy.
        self.allocateCube = allocateNumpyCube
        self.readerFactory = HsCubeReader
        self._reader: HsCubeReader | None = None
        self._gilYieldTimer = None
        self._completedCube = None
        # When the listed HS Cube connector was first seen started, or None.
        self._cubeConnectorStartedAt: float | None = None
        self._host = DEFAULT_HOST
        self._ports = dict(DEFAULT_PORTS)
        self._expectedBands = DEFAULT_EXPECTED_BANDS
        self._monitors: dict = {}
        self._connectors: dict = {}
        self._observerTags: list = []
        # Per incoming node ID, the modification time of the data last counted.
        self._countedData: dict = {}
        # The same for the LiveView frames handed to the live pane.
        self._liveViewTaken: dict = {}
        # VTK's modification time when the LiveView connection last began or
        # was lost: data no newer came from an earlier connection.
        self._liveViewSince = 0
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

    @property
    def cubeReader(self) -> HsCubeReader | None:
        """The HS Cube reader while connected, or None."""
        return self._reader

    def takeCompletedCube(self):
        """The last complete cube received since this was last called, or None.

        Only the latest is kept: one not taken before the next completes is
        dropped, and its memory with it.
        """
        cube, self._completedCube = self._completedCube, None
        return cube

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
        self._liveViewTaken = {}
        self._retireLiveViewFrames()
        host = self._host.strip()
        self._completedCube = None
        self._cubeConnectorStartedAt = None
        for channel, connector in self._connectors.items():
            monitor = self._monitors[channel]
            monitor.note = None
            # What the row describes is what the connector reaches, whatever
            # was changed on the listed connector in OpenIGTLinkIF, where its
            # Active checkbox may also have started it: Start() refuses a
            # running connector.
            if connector.GetState() != CONNECTOR_STATE_OFF:
                connector.Stop()
            connector.SetTypeClient(host, monitor.port)
            if channel == CHANNEL_HS_CUBE:
                # Listed, never started: the reader is the port's one client.
                self._reader = self.readerFactory(host, monitor.port, allocate=self.allocateCube,
                                                  idleSec=self.cubeIdleSec, clock=self._clock)
                self._reader.start()
                self._startGilYield()
                monitor.setConnectorState(CONNECTOR_STATE_WAITING, now)
                continue
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
        if self._reader is not None:
            self._stopGilYield()
            self._reader.stop()
            self._reader = None
        self._completedCube = None
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
        self._liveViewTaken = {}
        self._nodeIdsBeforeConnect = set()
        self._connected = False
        now = self._clock()
        for monitor in self._monitors.values():
            monitor.setConnectorState(CONNECTOR_STATE_OFF, now)

    def takeLiveViewFrame(self) -> LiveViewUpdate:
        """Whether LiveView is connected, and its newest frame not handed over yet, copied.

        A node whose data has not changed since it was last handed over is not
        a frame, and neither is one last changed before this connection began:
        a frame left from a lost connection, never taken, is not news from the
        next one, which may be another sender. A message the live pane cannot
        show, an image or not, comes back as a refusal.
        """
        connector = self._connectors.get(CHANNEL_LIVE_VIEW) if self._connected else None
        if connector is None or connector.GetState() != CONNECTOR_STATE_CONNECTED:
            if connector is not None:
                # Seen here first, the loss is followed up as the rows do:
                # its metadata goes and its frames are retired.
                self._follow(CHANNEL_LIVE_VIEW, connector, self._clock())
            return LiveViewUpdate(connected=False)
        newest, newestData, newestStamp = None, None, None
        for index in range(connector.GetNumberOfIncomingMRMLNodes()):
            node = connector.GetIncomingMRMLNode(index)
            if node is None:
                continue
            data, stamp = self._messageStamp(node)
            if data is None and node.IsA("vtkMRMLVolumeNode"):
                continue
            if stamp <= max(self._liveViewSince, self._liveViewTaken.get(node.GetID(), -1)):
                continue
            if newestStamp is None or stamp > newestStamp:
                newest, newestData, newestStamp = node, data, stamp
        if newest is None:
            return LiveViewUpdate(connected=True)
        self._liveViewTaken[newest.GetID()] = newestStamp
        observation = self._observation(newest, newestData, self._clock())
        refusal = liveViewRefusal(observation)
        if refusal is not None:
            return LiveViewUpdate(connected=True, refusal=refusal)
        import numpy
        import slicer
        monitor = self._monitors[CHANNEL_LIVE_VIEW]
        return LiveViewUpdate(connected=True, frame=LiveViewFrame(
            pixels=numpy.array(slicer.util.arrayFromVolume(newest), copy=True),
            simulated=observation.simulated,
            simulationDetail=newest.GetAttribute(SIMULATION_DETAIL_ATTRIBUTE),
            host=self._host.strip(), port=monitor.port, receivedAt=datetime.datetime.now()))

    def _retireLiveViewFrames(self) -> None:
        """Take every LiveView message received so far as from a connection that ended."""
        import vtk
        marker = vtk.vtkObject()
        marker.Modified()
        self._liveViewSince = marker.GetMTime()

    def _startGilYield(self) -> None:
        import qt
        if self._gilYieldTimer is None:
            self._gilYieldTimer = qt.QTimer()
            # 0: each time the event loop has handled what was pending.
            self._gilYieldTimer.setInterval(0)
            self._gilYieldTimer.connect("timeout()", self._yieldGil)
        self._gilYieldTimer.start()

    def _stopGilYield(self) -> None:
        if self._gilYieldTimer is not None:
            self._gilYieldTimer.stop()

    def _yieldGil(self) -> None:
        time.sleep(self.GIL_YIELD_SEC)

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
            if channel == CHANNEL_HS_CUBE:
                self._followReader(connector, now)
            else:
                self._follow(channel, connector, now)

    def _onConnectorEvent(self, caller, event) -> None:
        for channel, connector in self._connectors.items():
            if connector is caller and channel != CHANNEL_HS_CUBE:
                self._follow(channel, connector, self._clock())
                return

    def _followReader(self, connector, now: float) -> None:
        """Take the HS Cube reader's state, messages and cube progress."""
        monitor = self._monitors[CHANNEL_HS_CUBE]
        if connector is None or connector.GetState() == CONNECTOR_STATE_OFF:
            self._cubeConnectorStartedAt = None
        elif self._cubeConnectorStartedAt is None:
            self._cubeConnectorStartedAt = now
        elif now - self._cubeConnectorStartedAt >= self.STARTED_CONNECTOR_STOP_DELAY_SEC:
            connector.Stop()
            self._cubeConnectorStartedAt = None
            monitor.note = self.HS_CUBE_CONNECTOR_STOPPED_NOTE
        if self._reader is None:
            return
        update = self._reader.poll()
        monitor.setConnectorState(update.state, update.stateSince)
        for message in update.messages:
            observation = MessageObservation(
                time=message.time, deviceName=message.deviceName,
                messageType=message.messageType, size=message.size,
                components=1 if message.size else None, scalarType=message.scalarType,
                bandNumber=message.bandNumber, wavelengthNm=message.wavelengthNm,
                simulated=message.simulated)
            if message.refusal is None:
                monitor.messageReceived(observation)
            else:
                monitor.messageRefused(observation, message.refusal)
        monitor.setCubeProgress(update.progress)
        if update.completed is not None:
            self._completedCube = update.completed

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
            if channel == CHANNEL_LIVE_VIEW:
                # After the metadata removal, which changes a node without image data.
                self._retireLiveViewFrames()

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
