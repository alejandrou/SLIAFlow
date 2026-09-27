---
id: SLIA-035
title: Connections panel - see the acquisition app's ports and what each one carries
status: active
branch: feature/SLIA-035-connections-panel
priority: medium
depends_on: SLIA-028, SLIA-032
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-035 - Connections panel - see the acquisition app's ports and what each one carries

## Goal

Give SLIAFlow a **Connections** section that shows, for each port of IUMA's
acquisition app, whether it is connected and what is arriving, the way IUMA's
team saw it in Slicer's OpenIGTLinkIF module, but in the product's own terms. It
is the tool used in `SLIA-030` to measure the app's protocol and receive its
cube.

## Context

Requested by the project owner on 2026-09-24: IUMA could see the ports and what
they carried from OpenIGTLinkIF inside Slicer, and the owner wants that in
SLIAFlow too.

OpenIGTLinkIF shows a list of connectors, each with its state, and under each
the devices that arrived: name, message type and the Slicer node they went to.
It is a technician's view: it does not know what a cube is or how many bands
are missing.

IUMA's app serves (`docs/hardware/acquisition_app_and_hardware.md` section 4):

| Port | Device name | Content |
| --- | --- | --- |
| 18944 | `LiveView` | colour camera frames, IMAGE, RGB uint8 |
| 18945 | `Steroscopic` (spelled so in the app) | colour and mono frames side by side, IMAGE, RGB uint8 |
| 18946 | `HsCube` | one IMAGE per band; raw uint16 today, calibrated float32 per IUMA |

`SLIA-026` showed that link rows for producers that never exist read as
"connecting forever" and confuse the operator. `SLIA-027` removed the old link
rows and the connectors for that reason.

### What the specification found in the code (2026-09-25)

Checked in the pinned SlicerOpenIGTLink source
(`workspace/dependencies/SlicerOpenIGTLink`, commit `85e5f764`) and the
OpenIGTLinkIO it builds (`build/SlicerOpenIGTLink/OpenIGTLinkIO`), not assumed:

- **Events and methods.** `vtkMRMLIGTLConnectorNode` has `ConnectedEvent`
  (118944), `DisconnectedEvent` (118945), `ActivatedEvent` (118946),
  `DeactivatedEvent` (118947), `NewDeviceEvent` (118949) and
  `DeviceModifiedEvent` (118950); states `StateOff`, `StateWaitConnection`,
  `StateConnected`; `SetTypeClient(host, port)`, `Start()`, `Stop()`,
  `GetState()`, `GetNumberOfIncomingMRMLNodes()`, `GetIncomingMRMLNode(i)`.
  Confirmed at runtime: the class loads and the event ids match.
- **One event per imported message.** For every message pulled from the
  receive buffer, the connector writes the image into the incoming node, copies
  each metadata entry onto it as `OpenIGTLink.<key>`, and then invokes
  `DeviceModifiedEvent` (`ProcessIODeviceEvents`). The node's own `Modified`
  is held back by `StartModify` until the next `PeriodicProcess`, so observing
  the node would coalesce messages; observing the connector does not.
  `DeviceModifiedEvent` is also invoked when a device is removed (the STATUS
  device the connector sends on connect), so an event is counted as a message
  only when an incoming node's image actually changed.
- **Bands can be lost inside Slicer.** Each device has a circular buffer of 3
  (`IGTLCB_CIRC_BUFFER_SIZE`) and OpenIGTLinkIF pulls it on a 5 ms timer, so
  messages under one device name that arrive faster than they are pulled are
  overwritten. The panel counts what reached the node, which is what a
  receiver built on a connector would get.
- **A client connector never logs a failed attempt.** It retries every 100 ms
  and calls `ConnectToServer(..., logErrorIfServerConnectionFailed=false)`.
- **`Stop()` blocks while a connection attempt is in progress.** Measured on
  this laptop with nothing listening: 1.0 to 2.1 s per waiting connector
  (Windows spends about 2 s refusing a connection to a closed local port); a
  connected connector stops in 15 ms. Three waiting connectors can hold the UI
  for up to about 6 s on Disconnect, scene close or module exit.
- **The connector adopts an existing node by name.** For a 3-component IMAGE
  named `LiveView` it takes the first `vtkMRMLVectorVolumeNode` in the scene
  with that name. SLIAFlow's laptop camera volume is named `LiveView`, so the
  app's frames would be written into the camera volume, and removing the
  connector's nodes would remove the camera volume.
- **The dependency is not built in.** `SLIA-027` set `EXTENSION_DEPENDS` to
  `NA`, so neither `SlicerWithSLIAFlow.exe` nor the Source test run loads
  OpenIGTLinkIF today. Measured: `Slicer.exe` loads it with
  `--launcher-additional-settings build\SlicerOpenIGTLink\inner-build\AdditionalLauncherSettings.ini`
  and that build's module directories.
- **How a band identifies itself is unknown.** The vendored
  `AcquisitionSystemApp` source is older than the installed app and sends its
  cube over a custom JPEG 2000 socket, not OpenIGTLink; the binary contains no
  per-band metadata strings (`SLIA-030` context). The stand-in therefore
  invents band metadata, labelled as its own assumption, and the panel must
  also work when a message does not say which band it is.

## Requirements

### Connections section

- A **Connections** collapsible section in the module panel, separate from the
  Operator group, with:
  - settings: host (default `127.0.0.1`), the LiveView, Stereo and HS Cube
    ports (defaults 18944, 18945, 18946; 0 means the channel is not used), and
    the expected band count (default 109, the band count of `002-04`). They are
    parameter-node values and can be edited only while disconnected;
  - a **Connect** button that becomes **Disconnect** while connected;
  - a table with one row per configured port, and only for configured ports:
    Port, Channel, State, Last message, Received;
  - a detail line under the table with the sentence the table has no room for
    (why a row says the app is not running, which bands are missing);
  - an **Open in OpenIGTLinkIF** button.
- Every control has a tooltip that says what it does.

### States, in plain words

| State | When |
| --- | --- |
| Not connected | the channel's connector is not started |
| Waiting for the app | the connector is trying and has tried for less than 3 s |
| App not running | the connector has tried for 3 s or more; the detail line says nothing answers on host:port, to start IUMA's app or the stand-in, and that SLIAFlow keeps trying |
| Connected | connected, and no message in the last 2 s |
| Receiving | connected, and a message in the last 2 s |
| Cube complete | HS Cube only: every expected band of the current cube arrived |
| Cube incomplete | HS Cube only: bands are missing and nothing arrived for 10 s |
| Error | the reason is given: OpenIGTLink is not available in this Slicer, the host is empty, two channels share a port, the connector could not start, or the HS Cube port received something other than single-component IMAGE bands |

A row whose last message carries `SLIAFlow.DataOrigin = simulated` adds
`(stand-in)` to its state, so the stand-in is never mistaken for the app.

### What each row shows

- **Last message**: device name, message type (from the node class, by the
  connector's own device-type map), size (`W x H`, `x N` components), data type
  (`uint8`, `uint16`, `float32`, ...), the band and its wavelength when the
  message says them, and the time since it arrived.
- **Received**: the message rate over the last 5 s (`frames/s` for LiveView
  and Stereo, `bands/s` for HS Cube); for HS Cube, bands received out of
  expected in the current cube.
- **Missing bands** for HS Cube, on the detail line, as band numbers with
  ranges (`5, 17, 80-84`), when the messages carry a band number. When they do
  not, the count is still shown and the detail line says the messages do not
  say which band they are, so missing bands cannot be named.
- **Cube boundaries**: a new cube starts when a band number arrives that the
  current cube already has, when a message arrives after 10 s without any
  (longer than the app's 5 s VIS/NIR crossover), or, without band numbers, when
  a message arrives after the expected count was reached.

### Connectors

- One client `vtkMRMLIGTLConnectorNode` per configured port, named
  `SLIAFlow <channel> (<port>)`, marked with `SLIAFlow.Owner = Connections`,
  not saved with the scene.
- **Listed while disconnected** (owner decision, 2026-09-25). The connectors
  are in the scene, stopped, from the moment SLIAFlow opens, so OpenIGTLinkIF
  lists the app's ports as `OFF` before Connect, as IUMA's team saw them.
  Connect starts them and Disconnect stops them; a change of settings lists
  them again for the new ports. A stopped connector is shown as off, not as
  "connecting", so it is not the `SLIA-026` problem of rows that wait forever.
  The pinned connector creates a new node when the one a device wrote into was
  removed (`ProcessIncomingDeviceModifiedEvent`), so one connector can be
  stopped and started again.
- Built from the connector's state and events and the nodes it creates, as
  found above. No socket of SLIAFlow's own touches the app's ports: a probe
  connection would be taken by the app as its one client.
- **Removal.** Disconnect, scene close, module cleanup (Reload, application
  quit) stop every module connector and remove the incoming nodes those
  connectors created during this connection. Scene close, Reload and quit also
  remove the connectors; the new scene and the reloaded module list them again.
  A node that existed before Connect is never removed.
- **A new connection starts empty.** When a connector connects again, which may
  be another sender on the same port, its row forgets what the previous
  connection delivered. The connector copies a message's metadata onto its node
  as `OpenIGTLink.<key>` and never removes a key a later message leaves out, so
  whenever a connector is not connected, SLIAFlow removes the
  `OpenIGTLink.SLIAFlow.DataOrigin`, `.BandNumber` and `.WavelengthNm`
  attributes from its incoming nodes after counting their last messages, and
  Disconnect removes them from a kept node that existed before Connect.
- **Leaving SLIAFlow changes nothing** (owner decision, 2026-09-25). Switching
  to any module, by the **Open in OpenIGTLinkIF** button or the Modules menu,
  leaves the connections as they are, so OpenIGTLinkIF, or any module listing
  connectors such as OpenIGTLink Remote, shows them connected. This replaces
  the earlier rule that every module exit closed them, with OpenIGTLinkIF as the
  only exception: the owner opened **IGT > OpenIGTLink Remote**, found nothing
  listed, not even disconnected, and chose to have the ports always listed.
- The laptop camera volume is renamed `Laptop camera` so that no connector can
  adopt it; the LiveView pane still shows only the laptop camera.
- `extensions/SLIAFlow/CMakeLists.txt` declares
  `EXTENSION_DEPENDS "SlicerOpenIGTLink"` again (ADR-0004 decision 2). This is
  the existing pinned dependency of `SLIA-007`, not a new package. The module
  still loads without it, and its rows then say OpenIGTLink is not available.
- `run-slicer-tests.ps1 -Target Source` loads the pinned OpenIGTLinkIF build
  from `build\SlicerOpenIGTLink\inner-build`, and fails with a message naming
  that folder when it is missing, so connector tests never pass by skipping.

### Stand-in for IUMA's app

- `tools/simulators/stratum_sim/iuma_app_standin.py`, run with
  `python -m stratum_sim.iuma_app_standin` from `tools\simulators` under the
  repository `.venv`, built on the kept transport (`ImageStreamServer`).
- It serves base port P, P+1 and P+2 (default 18944) as `LiveView`,
  `Steroscopic` and `HsCube`, like the app.
- It reads `input\002-04\LCTF_Calibrated_Cube_Single.hdr` by default, or
  `--cube <header>`, with its own small ENVI float32 reader (it runs outside
  Slicer and cannot import `SLIAFlowLib`).
- `HsCube`: while a client is connected, sends the cube band by band as
  float32 single-component IMAGE messages (`--band-interval`, default 0.1 s),
  then again every `--cube-interval` seconds (default 30). `--drop-bands
  5,17,80-84` leaves those band numbers out.
- `LiveView`: a colour preview of the cube (bands nearest 650, 550 and 470 nm,
  reflectance 0-1 to 0-255) as RGB uint8 at `--frame-rate` (default 10).
  `Steroscopic`: that preview and the 650 nm band in grey, side by side.
- Every message carries `SLIAFlow.DataOrigin = simulated` and a
  `SLIAFlow.SimulationDetail` naming it a stand-in for IUMA's acquisition app
  and `002-04` a recorded IUMA LCTF capture. `HsCube` messages also carry
  `SLIAFlow.BandNumber` (1 to N) and `SLIAFlow.WavelengthNm`.
- Its console output starts with a banner saying it is a stand-in and not
  IUMA's app, and every line it prints is prefixed `[stand-in]`. Every document
  that mentions it calls it a stand-in.
- What it assumes about the real app is listed under **Stand-in assumptions**
  below and in `tools/simulators/README.md`, for `SLIA-030` to check.

## Out of scope

- Receiving and assembling the cube for display or UC1 (`SLIA-030`).
- Showing received images in the LiveView, Stereoscopic or HS Cube panes.
- Sending anything to the app.
- PLUS (`ADR-0004` decision 9).
- The reserved ports 18948 and 18949 in `stratum_sim.contract`; the stand-in
  uses 18944-18946 and does not touch them.
- Making `Stop()` non-blocking: that is inside OpenIGTLinkIO.

## Files allowed

- `extensions/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowConnections.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/README.md`
- `tools/simulators/stratum_sim/iuma_app_standin.py` (new)
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/stratum_sim/igtl_transport.py` (added during implementation:
  a read-only `pendingMessageCount`, because pyigtl's send queue is a
  `deque(maxlen=100)` that drops the oldest message silently, and the stand-in
  must not claim a band it never sent; after review, `writtenMessageCount` and
  dropping the queue when a client leaves, for the same reason)
- `tools/simulators/stratum_sim/__init__.py`
- `tools/simulators/tests/test_iuma_app_standin.py` (new)
- `tools/simulators/README.md`
- `scripts/development/run-slicer-tests.ps1`
- `docs/development/openigtlink_setup.md`
- `docs/development/testing_strategy.md`
- `tasks/active/SLIA-035-connections-panel.md`

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1 -Configure` and never edited by hand.

## Relevant skills and references

- Slicer skill: OpenIGTLinkIF, `vtkMRMLIGTLConnectorNode`, parameter node GUI
  binding, module cleanup. The connector facts above were read from the pinned
  source.
- `docs/hardware/acquisition_app_and_hardware.md`, sections 3.3, 4, 7 and 8.
- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md`.
- Pre-`SLIA-027` connector ownership in Git history (`2a81196^`,
  `SLIAFlowLogic.getOrCreateConnector`).
- `tools/simulators/stratum_sim/igtl_transport.py`.

## Implementation plan

1. Write the failing tests below: the model tests, the connector tests, the
   camera-name test, the runner guard, and the stand-in tests.
2. Restore `EXTENSION_DEPENDS`; make the Source test run load OpenIGTLinkIF.
3. `SLIAFlowConnections.py`: a Slicer-free `ChannelMonitor` (state, rate,
   bands, missing bands, cube boundaries, row text, from injected time and
   message observations) and `SLIAFlowConnections` (connectors, events,
   incoming-node tracking, removal).
4. Parameter node settings; the Connections section in `SLIAFlow.ui`; widget
   wiring, a 0.5 s refresh timer while connected, the connectors listed while
   disconnected and kept across module switches, and removal on scene close,
   Reload and quit.
5. Rename the camera volume.
6. The stand-in and its tests; contract keys.
7. Documentation; `build-sliaflow.ps1 -Configure`; checks.

## Acceptance criteria

1. With the stand-in running, each row shows the right state and the last
   message's device name, type, size, data type and age, and a rate.
2. The HS Cube row counts bands of the current cube, names the missing ones
   with ranges when the stand-in drops bands, and says Cube complete or Cube
   incomplete.
3. When messages carry no band number, the HS Cube row still counts and says
   missing bands cannot be named.
4. A new cube starts on a repeated band number, after 10 s of silence, or after
   a full count without band numbers.
5. With nothing running, a row says Waiting for the app, then App not running
   after 3 s with host and port on the detail line, and never stays on
   "waiting" alone; failed attempts write nothing to the log.
6. A row whose messages carry `SLIAFlow.DataOrigin = simulated` says
   `(stand-in)`.
7. One client connector per configured port and none for port 0; no row for
   port 0; settings are locked while connected; two channels on one port, or an
   empty host, is an Error that starts nothing.
8. No incoming node a module connector created survives Disconnect, scene
   close, Reload or application quit, and no connector is left running;
   Disconnect keeps the connectors listed and stopped, scene close and Reload
   list new ones, quit leaves none. A node that existed before Connect
   survives.
9. While disconnected, OpenIGTLinkIF lists one stopped connector per
   configured port. Leaving SLIAFlow for any module, by the button or the
   Modules menu, keeps the connections as they are, and returning to SLIAFlow
   finds them still receiving.
10. A LiveView message never lands in the laptop camera volume.
11. Without OpenIGTLink the module loads and its rows say OpenIGTLink is not
    available.
12. The Source test run loads OpenIGTLinkIF or fails saying why.
13. The stand-in serves P, P+1, P+2 with the app's device names, sends the cube
    band by band as float32 with band number and wavelength, leaves out the
    dropped bands, sends RGB uint8 LiveView and Stereo frames, and labels
    itself a stand-in in its output and its metadata.
14. The panel stays responsive while connectors wait, and the Stop cost is
    stated in the documentation.
15. The HS Cube row says Error, with the reason, when something other than a
    single-component IMAGE arrives on its port.
16. When a sender leaves and another connects to its port, nothing of the first
    carries over to the second: not the state, the band count, the band numbers
    nor the `(stand-in)` mark, on the row or on the received nodes. The
    stand-in reports a band as sent only once it was written to the connection
    in full.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Row details with the stand-in | `test_connectionsRowsFollowTheStandIn`; model `test_channelMonitorDescribesTheLastMessage`, `test_channelMonitorMeasuresTheMessageRate`; manual step 4 | automated, manual |
| 2 Band count, missing bands, complete, incomplete | `test_channelMonitorNamesMissingBands`, `test_connectionsCountBandsTheStandInDrops`; manual step 6 | automated, manual |
| 3 No band number | `test_channelMonitorCountsBandsItCannotName` | automated |
| 4 Cube boundaries | `test_channelMonitorStartsANewCube` | automated |
| 5 Nothing running | `test_channelMonitorStatesFollowTheConnector`, `test_connectionsSayTheAppIsNotRunning`; manual step 3 | automated, manual |
| 6 Stand-in marker | `test_channelMonitorMarksTheStandIn`; manual step 4 | automated, manual |
| 7 Connectors per configured port, settings | `test_connectionsCreateOneClientPerConfiguredPort`, `test_connectionsRefuseConflictingSettings`; manual step 7 | automated, manual |
| 8 Nothing received survives; nothing left running | `test_connectionsCloseOnEveryPath` (Disconnect, scene close, application quit); manual steps 9, 10 and 13 (Reload) | automated, manual |
| 9 Listed while disconnected; kept across modules | `test_connectionsCreateOneClientPerConfiguredPort` (listed before Connect), `test_leavingSLIAFlowKeepsTheConnections`, `test_igtModulesShowTheConnectors` (headful, through the Modules menu), `test_connectTakesOverAConnectorStartedInOpenIGTLinkIF`; manual steps 2, 8, 14 and 15 | automated, manual |
| 10 Camera volume not adopted | `test_liveViewMessageDoesNotLandInTheCameraVolume`; manual step 12 | automated, manual |
| 11 Without OpenIGTLink | `test_connectionsWithoutOpenIGTLinkSayWhy` | automated |
| 12 Runner loads OpenIGTLinkIF | `test_openIGTLinkIFIsLoaded`; runner output | automated |
| 13 Stand-in | `tools/simulators/tests/test_iuma_app_standin.py` | automated |
| 14 Responsive; Stop cost stated | manual step 3; documentation review | manual |
| 15 HS Cube refuses non-bands | `test_channelMonitorRefusesAnythingButBandsOnHsCube` | automated |
| 16 Nothing carries over between senders | `test_channelMonitorForgetsThePreviousConnection`, `test_connectionsForgetASenderThatLeft`, `test_connectionsLeaveNothingBehind` (kept node); `BandDeliveryTest`, `ImageStreamServerDeliveryTest`; manual step 6 | automated, manual |

Tests to add, and how each is shown to fail first:

- Model and connector tests in `SLIAFlowTest`: run against the tree before the
  change, where `SLIAFlowConnections` does not exist, and record the failure.
- `test_liveViewMessageDoesNotLandInTheCameraVolume`: run first with only the
  connections code in place and the camera volume still named `LiveView`; it
  must fail because the connector adopts the camera volume.
- `test_openIGTLinkIFIsLoaded`: run with the unchanged `run-slicer-tests.ps1`;
  it must fail because OpenIGTLinkIF is not loaded.
- Stand-in tests: run before `iuma_app_standin.py` exists.
- Tests that need a sender start the stand-in from the repository `.venv` on
  free local ports with a small placeholder cube written by the test (a test
  fixture that stands for no imagery). A missing `.venv` fails the test with its
  path rather than skipping it.

## Manual verification

Run in `build\SLIAFlow\SlicerWithSLIAFlow.exe` after
`scripts\development\build-sliaflow.ps1 -Configure`. Commands run from the
repository root in PowerShell.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `.\scripts\development\build-sliaflow.ps1 -Configure`, then start the launcher and open SLIAFlow | Every module file is `ok` in Verify. The six-panel layout appears | PASS (2026-09-25): configure/build exited 0; all module files were `ok`; the headful launcher opened SLIAFlow with the six-panel layout. |
| 2 | Expand **Connections** | Three rows: 18944 LiveView, 18945 Stereo, 18946 HS Cube, each `Not connected`. Host `127.0.0.1`, expected bands 109 | PASS: observed all three rows, host `127.0.0.1`, and 109 expected bands. |
| 3 | With neither IUMA's app nor the stand-in running, press **Connect** and wait 10 s. Meanwhile drag a slice view and open the Python console | Rows say `Waiting for the app`, then `App not running`; the detail line names `127.0.0.1` and the port and says SLIAFlow keeps trying. Slicer stays responsive. The Python console shows no repeated connection errors | PASS: rows reached `Waiting for the app`, then `App not running`, with the expected retry details; Slicer and console queries remained responsive and no repeated connection errors appeared. A separate slice drag was not performed. |
| 4 | In a second PowerShell: `cd tools\simulators; ..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin` | Its console starts with a banner saying it is a stand-in for IUMA's app. Within a few seconds LiveView and Stereo say `Receiving (stand-in)` with `IMAGE 1080 x 1080 x 3 uint8` and `IMAGE 2160 x 1080 x 3 uint8` and about 10 frames/s. HS Cube counts up to `109 / 109 bands` and says `Cube complete (stand-in)`, last message `HsCube - IMAGE 1080 x 1080 float32 - band 109, 1000 nm` | PASS: the documented command printed the stand-in banner and the full-size default cube produced the exact dimensions, formats, approximately 10 frames/s, and `109 / 109` complete bands. |
| 5 | Stop the stand-in with Ctrl+C | Rows go to `Waiting for the app`, then `App not running`, never stuck on `Connected` or `Receiving` | PASS with observation: after stopping the background process, rows reached `App not running` and were not stuck. The intermediate `Waiting for the app` state was too brief to capture in this non-interactive stop probe; the stand-in was terminated by `Stop-Process` because no interactive Ctrl+C console was attached. |
| 6 | Start the stand-in again with `--drop-bands 5,17,80-84` and wait for the cube to finish plus 10 s | HS Cube counts again from the first band, not from the previous cube's `109 / 109`; it ends on `Cube incomplete (stand-in)` and `102 / 109 bands`; the detail line names missing bands `5, 17, 80-84` | PASS: the incomplete-cube probe showed `102 / 109`, restarted from band 1, and named exactly `5, 17, 80-84`. |
| 7 | Press **Disconnect**. Set the Stereo port to 0 and press **Connect**. Try to edit the host while connected | Two rows, no Stereo row. The settings cannot be edited while connected | PASS: only LiveView and HS Cube remained; host and port controls were disabled while connected. |
| 8 | Press **Open in OpenIGTLinkIF** | OpenIGTLinkIF opens and lists the SLIAFlow connectors as connected, with LiveView and HsCube devices. Go back to SLIAFlow: the rows are still receiving | PASS: OpenIGTLinkIF listed the connected LiveView and HS Cube connectors/devices; returning to SLIAFlow preserved receiving state. |
| 9 | Changed 2026-09-25. Return to SLIAFlow and press **Disconnect**. In the Python console run `[(n.GetName(), n.GetState()) for n in slicer.util.getNodesByClass('vtkMRMLIGTLConnectorNode')]` (state 0 is off, 2 connected). Then press **Open in OpenIGTLinkIF** | The three `SLIAFlow ...` connectors, each with state 0; OpenIGTLinkIF lists them as off. The stand-in's images (`LiveView`, `Steroscopic`, `HsCube`) are gone from the Data module | Not yet run. Superseded record, against the earlier rule that leaving OpenIGTLinkIF removed the connectors: PASS, the query returned `[]`. |
| 10 | Changed 2026-09-25. Return to SLIAFlow, press **Connect**, then **File > Close Scene**. Run the console command of step 9 | Three connectors, each with state 0 (new ones, listed for the new scene); the rows say `Not connected` | Not yet run. Superseded record, against the earlier rule: PASS, the query returned `[]` and the rows were `Not connected`. |
| 11 | Optional, if IUMA's app can start on this laptop: stop the stand-in, start `AcquisitionSystemApp`, press **Connect** | Rows reach `Connected` (the app listens without hardware and sends nothing); without hardware no message arrives. Note anything unexpected for `SLIA-030` | SKIPPED (optional): no real IUMA `AcquisitionSystemApp` was available to launch on this laptop; the approved stand-in was used for the connection tests. |
| 12 | Start the laptop camera (**Start**), start the stand-in and press **Connect** | The LiveView pane keeps showing the laptop camera, never the stand-in's cube preview | PASS: the camera pane continued showing the laptop camera while the Connections panel received the stand-in stream; the stand-in node did not take over the camera volume. |
| 13 | Changed 2026-09-25. With Developer mode on, start the stand-in, press **Connect**, wait for `Receiving`, then press **Reload** in SLIAFlow's Reload & Test section. Run the console command of step 9 | Three connectors, each with state 0 (listed again by the reloaded module); after the reload the rows say `Not connected` | Not yet run. Superseded record, against the earlier rule: PASS, Reload cleared the connectors and the rows said `Not connected`; Reload and Test completed with `OK (skipped=1)`. |
| 14 | Changed 2026-09-25. While connected, switch to another module (for example Data) and run the console command of step 9; then come back to SLIAFlow | The previous layout is restored on leaving. In Data, the three connectors with state 2. Back in SLIAFlow, the rows are still `Receiving (stand-in)` | Not yet run. Superseded record, against the earlier rule: PASS, switching away removed the connectors and the rows said `Not connected` on return; the layout was restored (702). |
| 15 | Changed 2026-09-25 (owner request). Restart Slicer and open SLIAFlow without pressing Connect. Choose **IGT > OpenIGTLinkIF** from the Modules menu, then **IGT > OpenIGTLink Remote** and open its Connector list. Then, with the stand-in running, return to SLIAFlow, press **Connect**, wait for `Receiving`, and choose **IGT > OpenIGTLinkIF** again | Before Connect: OpenIGTLinkIF lists `SLIAFlow LiveView (18944)`, `SLIAFlow Stereo (18945)` and `SLIAFlow HS Cube (18946)` as off; OpenIGTLink Remote's list offers the same three. After Connect: OpenIGTLinkIF shows them on and connected, with their devices under each | Not yet run. |

## Risks

- **`Stop()` blocks up to about 2 s per waiting connector** (measured above).
  Disconnect, scene close, Reload and quit can pause the UI for up to about 6 s
  when the app is not running. It is inside OpenIGTLinkIO; the documentation
  states it, and step 3 checks the panel is responsive while connectors wait.
  Leaving SLIAFlow no longer stops anything, so it no longer pauses.
- Since leaving SLIAFlow keeps the connections, SLIAFlow stays the app's one
  client per port while the operator works in another module, until
  Disconnect. That is the owner's choice (2026-09-25).
- A listed connector started from OpenIGTLinkIF's own Active checkbox, while
  SLIAFlow is disconnected, connects, but SLIAFlow's rows do not follow it and
  still say `Not connected`; Connect in SLIAFlow takes it over.
- Restoring `EXTENSION_DEPENDS` makes the built launcher need the
  SlicerOpenIGTLink build again (`SLIA-007`); the module itself still loads
  without it.
- The stand-in can only imitate what we know of the app; see below.

## Stand-in assumptions

Each is to be checked against the real app in `SLIA-030`.

1. `HsCube` sends one IMAGE per band, single component, `(samples, lines, 1)`,
   spacing 1, identity matrix, LPS, bands in ascending wavelength, with no
   end-of-cube message.
2. Per-band metadata `SLIAFlow.BandNumber` and `SLIAFlow.WavelengthNm` is
   invented by the stand-in; the app's binary shows no per-band metadata.
3. Messages use header version 2 so metadata reaches the wire; the app's
   header version is unknown.
4. The cube is sent automatically while a client is connected; the real app
   sends it on Capture HSI or Send Capture.
5. LiveView and Stereo carry a colour preview of the cube at 1080 x 1080 and
   2160 x 1080, 10 frames/s; the app sends camera frames (up to 4096 x 3000)
   at an unmeasured rate.
6. The stand-in binds 127.0.0.1; the app binds 0.0.0.0.
7. One client per port at a time, like the app's server loop.
8. Today's app sends raw uint16 bands; the stand-in sends IUMA's calibrated
   float32 cube, the announced format.

## Documentation impact

- `extensions/SLIAFlow/README.md`: the Connections section, states, the stand-in,
  the OpenIGTLinkIF button, the Stop cost.
- `docs/development/openigtlink_setup.md`: used again for the connections panel;
  dependency restored; Source test run paths.
- `docs/development/testing_strategy.md`: the Source target loads OpenIGTLinkIF.
- `tools/simulators/README.md`: the stand-in, how to run it, its assumptions.

## Completion evidence

Implementation, automated checks, and manual verification, 2026-09-25, on
`feature/SLIA-035-connections-panel` (uncommitted). The manual result table
above records steps 1 to 14. The optional real-application check in step 11
was skipped because `AcquisitionSystemApp` was not available. After the owner's
decision to keep the connectors listed (below), steps 9, 10, 13 and 14 were
changed and their earlier PASS no longer covers the current behaviour; they and
step 15 have not been run against it.

### Manual verification evidence

- The headful launcher was `build\SLIAFlow\SlicerWithSLIAFlow.exe`, built by
  `build-sliaflow.ps1 -Configure`; the visible Slicer window and SLIAFlow panel
  were exercised.
- The local Slicer MCP server was used only for visible-window/widget and scene
  inspection that cannot be established from headless tests alone, including
  screenshots in `%TEMP%` and queries for connector/node state. No screenshot
  or local temporary fixture was added to the repository.
- Adversarial probes passed: empty host, duplicate LiveView/Stereo port,
  disabled Stereo, a wrong `STRING` message on `HsCube` (shown as `Error` with
  the expected explanation), dropped bands, sender stop/reconnect, OpenIGTLinkIF
  handoff, scene close, reload, module switching, and camera isolation.
- The Slicer window remained responsive during the no-sender retry probe. The
  only procedural limitation was that a separate slice drag was not performed,
  and the post-stop `Waiting for the app` transition was not captured after a
  non-interactive process termination; the final `App not running` state was
  verified.

### Tests seen failing first

Run against the tree before the implementation, with the new tests in place and
the unchanged `run-slicer-tests.ps1` (`$TEMP\slia035_before.txt`): 107 run,
74 passed, 15 skipped, 11 failures and 10 errors, every one in a new test.

- The nine `ChannelMonitor` / `SLIAFlowConnections` model tests:
  `ModuleNotFoundError` importing `SLIAFlowConnections`.
- `test_openIGTLinkIFIsLoaded`: `AssertionError: False is not true :
  OpenIGTLinkIF is not loaded in this Slicer`.
- `test_connectionsRefuseConflictingSettings`: failed on the same missing
  OpenIGTLinkIF.
- The connector tests: `AssertionError: The stand-in did not start` (no
  `stratum_sim.iuma_app_standin`).
- `test_liveViewMessageDoesNotLandInTheCameraVolume`, run again with the
  connections code in place and the camera volume still named `LiveView`:
  `AssertionError: 'vtkMRMLVectorVolumeNode1' unexpectedly found in
  ['vtkMRMLVectorVolumeNode1'] : The connector took the camera volume`.
- Stand-in tests (`tools\simulators\tests\run_tests.py`): `ImportError: cannot
  import name 'iuma_app_standin' from 'stratum_sim'`.

### Final runs

Rerun after the change to keep the connectors listed, below (the stand-in and
transport were not touched by it; their row is from the pre-review fixes):

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21: both targets `All checks passed!` | 0 |
| Stand-in and transport | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 35 run, OK (11 new) | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | loaded from `extensions\SLIAFlow\SLIAFlow`; OpenIGTLinkIF from `build\SlicerOpenIGTLink\inner-build`; 111 run, OK, 16 skipped (the layout, renderer and module-menu tests that need a window) | 0 |
| Slicer, Source, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | 111 run, OK, 1 skipped (`test_headlessPresentationFallback`, headless only) | 0 |
| Launcher | `.\scripts\development\build-sliaflow.ps1 -Configure` | every module file `ok` in Verify, `SLIAFlowConnections.py` included; `AdditionalLauncherSettings.ini` lists SlicerOpenIGTLink again | 0 |
| Slicer, Build | `.\scripts\development\run-slicer-tests.ps1 -Target Build` | loaded from `build\SLIAFlow`; 111 run, OK, 16 skipped | 0 |

`git diff --check` reports nothing. None of the three Slicer logs contains a
connector error (`Node is not found in IncomingMRMLIDToDeviceMap`, `Connector
is already running!`).

New `SLIAFlowTest` methods (22): `test_igtModulesShowTheConnectors`,
`test_leavingSLIAFlowKeepsTheConnections`,
`test_connectTakesOverAConnectorStartedInOpenIGTLinkIF`,
`test_connectionsCloseOnEveryPath`, `test_channelMonitorStatesFollowTheConnector`,
`test_channelMonitorDescribesTheLastMessage`,
`test_channelMonitorRefusesAnythingButBandsOnHsCube`,
`test_channelMonitorMeasuresTheMessageRate`,
`test_channelMonitorNamesMissingBands`,
`test_channelMonitorCountsBandsItCannotName`,
`test_channelMonitorStartsANewCube`, `test_channelMonitorMarksTheStandIn`,
`test_connectionsWithoutOpenIGTLinkSayWhy`,
`test_connectionsRefuseConflictingSettings`, `test_openIGTLinkIFIsLoaded`,
`test_connectionsCreateOneClientPerConfiguredPort`,
`test_connectionsSayTheAppIsNotRunning`, `test_connectionsRowsFollowTheStandIn`,
`test_connectionsCountBandsTheStandInDrops`,
`test_liveViewMessageDoesNotLandInTheCameraVolume`,
`test_channelMonitorForgetsThePreviousConnection`,
`test_connectionsForgetASenderThatLeft`.

### Pre-review findings addressed (2026-09-25)

Four findings were raised on the implementation before review. This is not the
independent AI review of the lifecycle, which has not taken place.

| # | Finding | Checked | Outcome |
| --- | --- | --- | --- |
| 1 | Band, wavelength and stand-in mark leak from one sender to the next, because the connector never removes a metadata key a later message omits | Confirmed in `vtkMRMLIGTLConnectorNode.cxx` (it only calls `SetAttribute`) and reproduced: after the stand-in left, its node still had `BandNumber = 5`, `WavelengthNm = 480`, `DataOrigin = simulated` | Fixed: while a connector is not connected, `SLIAFlowConnections` counts the last messages and then removes the three attributes from its incoming nodes; Disconnect removes them from a kept pre-existing node |
| 2 | A reconnected sender that has sent nothing shows the previous sender's `Cube complete (stand-in)` | Reproduced: `'Cube complete (stand-in)' != 'Connected'` | Fixed: `ChannelMonitor` forgets messages, bands and the message error when its connector enters Connected |
| 3 | The stand-in reports a band as sent when pyigtl's queue is empty, but pyigtl dequeues before `sendall`, so a failed write also empties it | Confirmed in `pyigtl/comm.py` and reproduced: `HsCube: sent 1 of 5 bands.` for a band whose write failed | Fixed: `writtenMessageCount` counts completed writes and the stand-in waits for it. Also found: pyigtl keeps what was queued for a client that left and writes it to the next client ahead of its cube; the queue is now dropped on departure |
| 4 | Manual lifecycle verification outstanding | Correct | Resolved: manual steps 1 to 14 were executed; see the Result column and manual verification evidence above. Steps 9, 10, 13 and 14 were changed afterwards (connectors kept listed) and are to be run again. |

How the fixes rely on OpenIGTLinkIO, read in the pinned source:
`vtkMRMLIGTLConnectorNode::GetState()` returns the socket thread's own state,
which turns Connected before anything is received, and `igtlioConnector::PeriodicProcess`
imports buffered messages before it invokes queued events. A new sender's first
message can therefore arrive before `ConnectedEvent`; the row forgets the
previous connection as soon as it reads the state, before that message is
counted. The device's own metadata is replaced per message, but OpenIGTLinkIO
has no Python wrapping here, so SLIAFlow cannot read it and uses the node
attributes.

Seen failing first, against the tree before these fixes:

- `test_channelMonitorForgetsThePreviousConnection`: `AssertionError: 'Cube
  complete (stand-in)' != 'Connected'`.
- `test_connectionsForgetASenderThatLeft`: `AssertionError: '5' is not None :
  The stand-in's metadata outlived its connection` (and `'480'`,
  `'simulated'`), then `'Cube complete (stand-in)' != 'Connected'`.
- `test_connectionsLeaveNothingBehind` (since replaced by
  `test_connectionsCloseOnEveryPath`, which keeps the check), with the new
  kept-node check and the Disconnect clearing disabled: `AssertionError: '5' is not None : The kept
  node still carries the sender's OpenIGTLink.SLIAFlow.BandNumber`.
- `BandDeliveryTest.test_aBandWhoseWriteFailedIsNotReportedAsSent`:
  `'HsCube: sent 0 of 5 bands.' not found in [..., 'HsCube: sent 1 of 5
  bands.']`.
- `ImageStreamServerDeliveryTest.test_onlyAWriteThatCompletedCountsAsWritten`:
  `AttributeError: 'ImageStreamServer' object has no attribute
  'writtenMessageCount'`.
- `ImageStreamServerDeliveryTest.test_messagesQueuedForAClientThatLeftAreNotKeptForTheNext`:
  `AssertionError: 2 != 0`.

Remaining limit: until the next sender's first message, the previous sender's
last image stays on its node without its band and origin attributes. Within one
connection, a sender that includes band metadata in some messages and omits it
in others would still leave the last value on the node; nothing suggests the
app does that.

### IGT > OpenIGTLinkIF from the Modules menu (owner request, 2026-09-25; superseded)

IUMA showed the owner their ports in OpenIGTLinkIF, reached through the IGT
menu. Only the button kept SLIAFlow's connectors, so `SLIAFlowWidget.exit()`
was first made to ask the module selector which module was being opened and to
keep the connectors for OpenIGTLinkIF. Seen failing first, headful:
`test_igtMenuOpenIGTLinkIFKeepsTheConnectors`: `AssertionError: 0 != 3 :
Choosing OpenIGTLinkIF from the menu closed the connections`. The next section
replaced this mechanism and the test.

### Connectors listed while disconnected (owner decision, 2026-09-25)

The owner then opened **IGT > OpenIGTLink Remote**, whose Connector list read
`None`, and reported that nothing was shown, "not even as disconnected".
Asked, the owner chose to have the ports always listed. Now:

- `SLIAFlowConnections.listConnectors()` puts one stopped client connector per
  configured port in the scene when the panel gets its parameter node (module
  opened, entered, Reload) and when the scene is reopened; `configure()` lists
  them again for new settings.
- Connect starts the listed connectors, Disconnect stops them and removes what
  they received, `release()` (scene close, Reload, quit) also removes them.
- `exit()` no longer touches the connections, and the hand-off to OpenIGTLinkIF
  (the module-selector watch, `_moduleBeingOpened`, `_onModuleSelected`) is
  gone. The button only selects OpenIGTLinkIF.
- A listed connector someone started from OpenIGTLinkIF's Active checkbox is
  stopped by Connect before Connect starts it. The pinned `igtlioConnector::Start()`
  refuses a running connector (`Connector is already running!`).

Seen failing first, headful, against the previous code
(`run_selected.py`, 5 tests): 6 failures.

- `test_connectionsCreateOneClientPerConfiguredPort`: `Lists differ: [] !=
  [52688, 52690] : The connectors are not listed before Connect`.
- `test_connectionsCloseOnEveryPath` (Disconnect): `Disconnect removed the
  listed connectors`. The scene-close and quit subtests then failed on a node
  the first subtest left behind, so the test now removes it in `finally`.
- `test_leavingSLIAFlowKeepsTheConnections`: `Lists differ: [] !=
  ['vtkMRMLIGTLConnectorNode1', ...] : Leaving SLIAFlow closed the
  connections`.
- `test_igtModulesShowTheConnectors`: `Lists differ: [] != [0, 0, 0] :
  OpenIGTLinkIF does not list the ports while disconnected`.
- `test_connectTakesOverAConnectorStartedInOpenIGTLinkIF`, with the stop
  before Start disabled: Connect was refused, and the Disconnect in the test's
  clean-up then hung in `connector.Stop()`. A 60 s `faulthandler` watchdog
  dumped the stack at `SLIAFlowConnections.disconnect`. The run had to be ended
  and its stand-in stopped by hand.

The first implementation also listed the connectors again right after quit,
from the refresh that follows the release. It was caught by
`test_connectionsCloseOnEveryPath` (`A connector outlived the application`),
and listing now happens only where the panel gets its parameter node.

Manual steps 9, 10, 13, 14 and 15 describe the new behaviour and have not been
run.

### Measurements

- `Stop()` with nothing listening, three client connectors: 1.0 to 2.1 s each
  while an attempt is in progress, 15 ms for a connected one.
- Full size, `002-04` from the stand-in to `SLIAFlowConnections` on all three
  ports in a headless Slicer: HS Cube `109 / 109 bands`, `Cube complete
  (stand-in)` in 15.3 s; LiveView 10.0 and Stereo 10.1 frames/s; the longest
  event-loop turn 32 ms; Disconnect with the ports connected 0.3 s.
- OpenIGTLinkIF's geometry warning (`vtkMRMLVolumeNode.cxx` line 712): 2 for
  100 LiveView frames, so once per received device, not per message.
- The stand-in first delivered 16.1 of 20 requested frames/s because it waited
  a whole interval after each send; it now schedules frames on a fixed clock
  and delivered 20.0.

### Found and fixed on the way

- `docs/development/testing_strategy.md` held a backspace character in
  `scripts\development\build-sliaflow.ps1` in `HEAD` (it read
  `developmentuild`); corrected while editing that file.

## Review findings

## Human approval
