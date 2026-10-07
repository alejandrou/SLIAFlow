---
id: SLIA-037
title: LiveView from IUMA's acquisition app in the live pane
status: completed
branch: feature/SLIA-037-app-liveview-in-the-live-pane
priority: low
depends_on: SLIA-036
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-037 - LiveView from IUMA's acquisition app in the live pane

## Goal

The operator can choose the app's LiveView stream (18944) instead of the laptop
camera as the picture in the live pane, and Capture freezes that picture as it
does the camera's.

## Context

*Created on 2026-10-06 from `SLIA-030` phase B*, which planned it next to
receiving the cube (`SLIA-036`). The owner split it off because the app sends
no LiveView frames without its cameras (`SLIA-030` manual step A3), so it cannot
be checked by hand until the hardware is available. The stand-in for the app
sends LiveView frames, so everything except the real picture is checked
without the hardware.

What SLIAFlow does today:

- `SLIA-035` connects a client connector to 18944 and shows its rate in the
  Connections table. The connector puts each frame on its own incoming
  `vtkMRMLVectorVolumeNode` (device `LiveView`, RGB uint8, 3 components, one
  slice). Nothing shows that node in a panel.
- Criterion 10 of `SLIA-035` keeps any received frame out of the laptop camera
  volume: that volume is named `Laptop camera`, so the connector cannot adopt
  it by name. `test_liveViewMessageDoesNotLandInTheCameraVolume` guards it.
- The live pane shows only the laptop camera. **Start** opens it (OpenCV),
  every frame is written into the `Laptop camera` volume, and **Capture** is
  enabled once a frame is on screen. Capture freezes the pane, saves the frame
  as `workspace\captures\output_laptop_camera_<time>.png`, and the pane resumes
  when UC1 and UC2 end.
- The operator panel already has a `Live source:` row, a fixed label reading
  `AcquisitionSystemApp LiveView (laptop camera)`.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md` ("The live pane accepts
  either the laptop camera or the received `LiveView` stream") already sets the
  rules this task follows: switching releases the source left, a lost
  connection does not blank a pane holding a frame that really arrived but says
  it is no longer updated, and a frame arriving while the camera is selected
  reaches no view.
- `SLIA-036` owner decision 2 sets the wording of a received origin: host and
  port, reception time, what the app serves there, and that the sender may have
  captured it live or replayed it, which SLIAFlow cannot tell apart. Data whose
  messages say `SLIAFlow.DataOrigin = simulated` (the stand-in) stays
  `simulated`.

The measured facts of the real stream are few: the app serves `LiveView` on
18944 as RGB 8-bit, 3 channels (hardware document section 4), and sent nothing
without cameras. Frame size (up to 4096 x 3000), rate and orientation are not
measured.

## Requirements

### The choice

- A **Live source** choice in the operator panel, saved in the parameter node
  as `liveSource`: `Laptop camera` (the default, today's behaviour) or
  `LiveView from the app`. It replaces the fixed `Live source:` label.
- **Start** starts the chosen source and **Stop** stops it. With the app
  chosen, Start needs no camera support (OpenCV) and opens no camera.
- Changing the choice stops the source that was running and empties the pane
  to its waiting message. It cannot be changed while a capture runs.

### LiveView from the app

- While it runs, every new frame that reaches the LiveView connector's incoming
  node is copied into a module-owned volume, `LiveView from the app`, and that
  volume is shown in the live pane. A frame is taken once: an unchanged node is
  not news.
- It never lands in the `Laptop camera` volume. With `Laptop camera` chosen no
  frame from the app reaches any view, and no app volume is made.
- The app volume gets SLIAFlow's upright directions, as the camera volume and
  received cube do; the frame's row 0 is the top of the picture.
- Only an RGB uint8 frame of one slice is shown. Anything else is not shown,
  the pane keeps what it had, and the Status line names what arrived.
- With the app chosen and no frame yet, the pane says it is waiting for
  LiveView from the app and to connect under Connections.
- **Connection lost.** When the LiveView connector is no longer connected (the
  app left, or Disconnect), a frame on screen stays, and a caption on the pane
  says it is no longer updated. The next frame from a new connection replaces
  it and removes that mark.
- A caption at the top of the live pane, clear of the text Slicer writes bottom left, names the source: `LiveView
  received from the app`, or for stand-in data `LiveView from the stand-in for
  the app, simulated`. The laptop camera has no caption, as today.

### Capture

- Capture is enabled while either source runs and has shown a frame, as for the
  camera today.
- With the app chosen, Capture freezes the app's frame exactly as it freezes
  the camera's: frames arriving meanwhile are not shown, and the pane resumes
  when the capture ends.
- The snapshot is `workspace\captures\output_app_liveview_<time>.png`, the
  frozen frame top row first. The laptop camera's name is unchanged.
- Capture on a frame marked no longer updated is refused before anything is
  frozen or saved, and the Status line says why.
- The Cube source choice and what Capture runs are unchanged.

### Provenance

- The app volume carries `SLIAFlow.Owner = AppLiveView`,
  `SLIAFlow.DataOrigin = received` and a `SLIAFlow.SimulationDetail` of the
  `SLIA-036` owner decision 2 form: `LiveView colour frame received over
  OpenIGTLink from <host>:<port>, the port IUMA's AcquisitionSystemApp serves
  its LiveView on, at <time>; the sender may have captured it live or replayed
  it, which SLIAFlow cannot tell apart`.
- A frame whose message says `SLIAFlow.DataOrigin = simulated` keeps
  `simulated`, with the stand-in's own detail followed by the reception detail,
  as for a stand-in cube.

### Lifetime

- Stop, changing the source, leaving the module, scene close, module cleanup
  (Reload) and quit stop the app LiveView and remove its volume.
- Disconnect alone does not stop it: the pane keeps the last frame, marked as
  no longer updated.

## Out of scope

- Stereo display (`Steroscopic`, 18945).
- Camera control or any message sent to the app.
- Measuring the real stream's size, rate and orientation (manual step 6, with
  the hardware).
- Downscaling or skipping frames for speed.
- Retiring `allowSharedPort` and `prepareFrameForWire` (`SLIA-009`).

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowConnections.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/README.md`
- `docs/development/openigtlink_setup.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/active/SLIA-037-app-liveview-in-the-live-pane.md`

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1 -Configure` and never edited by hand.

## Relevant skills and references

- Slicer skill: `vtkMRMLIGTLConnectorNode` incoming nodes,
  `vtkMRMLVectorVolumeNode`, slice composite nodes, `slicer.util.arrayFromVolume`
  and `updateVolumeFromArray`.
- `tasks/completed/SLIA-030-external-openigtlink-links.md`
- `tasks/completed/SLIA-035-connections-panel.md` (criterion 10)
- `tasks/completed/SLIA-036-receive-app-hs-cube.md` (owner decision 2)
- `docs/hardware/acquisition_app_and_hardware.md` section 4
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`, the live pane rules

## Implementation plan

1. `SLIAFlowTest`, tests first (below), and seen failing against the current
   module.
2. `SLIAFlowConnections.takeLiveViewFrame()`: whether the LiveView connector is
   connected, and the newest frame not yet taken, copied, with its origin and
   detail, or the reason it cannot be shown.
3. Parameter node `liveSource`; the UI combo box in place of the fixed label.
4. Logic: `startAppLiveView` / `stopAppLiveView` on a timer, `liveActive`,
   `acceptAppLiveViewFrame` (the module-owned volume, geometry, provenance),
   `appLiveViewNode`, `removeAppLiveViewNode`, and a snapshot prefix.
5. Widget: Start and Stop for the chosen source, the source change, the pane's
   waiting message and caption, the no-longer-updated mark, Capture on the app
   frame, lifetime.
6. Documentation; `build-sliaflow.ps1 -Configure`; quality checks and Slicer
   tests, headless and headful.

## Acceptance criteria

1. **Choice.** `liveSource` defaults to `Laptop camera`. The operator panel
   offers both sources with a stated reason, and the choice is saved.
2. **Shown.** With `LiveView from the app` chosen and started, the stand-in's
   LiveView frames reach the live pane through a module-owned volume whose
   pixels equal the frame the connector received, upright.
3. **Kept apart.** No frame from the app ever lands in the `Laptop camera`
   volume. With `Laptop camera` chosen, frames from the app reach no view and
   no app volume exists.
4. **Capture.** Capture on the app's LiveView freezes it, saves
   `output_app_liveview_<time>.png` with the frozen frame, and the pane resumes
   after the capture, success or failure.
5. **Connection lost.** A frame on screen stays when the connection is lost and
   is marked as no longer updated; Capture on it is refused before anything is
   frozen or saved. A new frame removes the mark.
6. **Refused frames.** A frame that is not RGB uint8 of one slice is not shown,
   and the Status line names it.
7. **Provenance.** The app volume carries `DataOrigin = received` with the
   decision 2 detail; a stand-in frame stays `simulated` with the stand-in's
   detail first. The pane caption says which.
8. **Switching and lifetime.** Changing the source stops the one that ran.
   Stop, scene close and cleanup remove the app volume; Disconnect keeps the
   last frame marked as no longer updated.
9. **Unchanged.** The laptop camera path, its snapshot name and the Cube source
   behave as before.
10. **Real app.** With the app's cameras, the live pane shows the colour camera
    upright, in true colour, and Capture freezes it.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Choice | `SLIAFlowTest.test_liveSourceDefaultsToTheLaptopCamera`, `test_operatorControlsHaveStatedReasons` (changed: the new selector) | automated |
| 2 Shown | `SLIAFlowTest.test_appLiveViewFromTheStandInReachesTheLivePane` | automated |
| 3 Kept apart | `test_appLiveViewFromTheStandInReachesTheLivePane` (camera volume unchanged), `test_cameraSourceShowsNoFrameFromTheApp`, `test_liveViewMessageDoesNotLandInTheCameraVolume` (unchanged) | automated |
| 4 Capture | `SLIAFlowTest.test_captureFreezesTheAppLiveView`, `test_appLiveViewResumesAfterCaptureSuccessAndFailure` | automated |
| 5 Connection lost | `SLIAFlowTest.test_appLiveViewKeepsItsLastFrameWhenTheConnectionIsLost`, `test_captureRightAfterTheConnectionIsLostIsRefused`, `test_appLiveViewFrameOfALostConnectionIsNotNews` (review) | automated |
| 6 Refused frames | `SLIAFlowTest.test_appLiveViewRefusesAFrameItCannotShow`, `test_appLiveViewNamesAMessageThatIsNoImage` (review) | automated |
| 7 Provenance | `SLIAFlowTest.test_appLiveViewFrameProvenance`; the stand-in end to end in `test_appLiveViewFromTheStandInReachesTheLivePane` | automated |
| 7 Caption legible | `SLIAFlowTest.test_appLiveViewStaleCaptionIsNoWiderThanTheLiveOne` (manual step 3); manual steps 1 and 3 | automated (headful) and manual |
| 8 Switching and lifetime | `SLIAFlowTest.test_switchingTheLiveSourceStopsTheOneLeft`, `test_appLiveViewIsRemovedOnStopAndSceneClose` | automated |
| 9 Unchanged | the existing camera and capture tests, `test_snapshotNameIsUniqueWithinOneSecond` | automated |
| 10 Real app | Manual step 6 | manual (hardware) |
| 2-5 End to end | Manual steps 1-5 | manual |

Tests to add or change, and how each will be shown to fail first:

- Every new test is run against the module as committed on `main` with the new
  test file. They fail on the missing `liveSource` parameter, the missing
  `liveSourceSelector`, or the missing `startAppLiveView`.
- `test_operatorControlsHaveStatedReasons` fails on the missing selector.
- Frames given to the widget in the unit tests are placeholder fixtures packed
  by the test, standing for no imagery, and are handed in through the poll the
  logic takes, never through the module's own conversion. The stand-in test
  compares the module's volume with the connector's own incoming node.

## Manual verification

Commands from the repository root in PowerShell. Nothing else may be connected
to the stand-in's ports.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Start the stand-in: `cd tools\simulators; ..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin`. In SLIAFlow press **Connect**, set **Live source** to `LiveView from the app`, press **Start** | The live pane shows the stand-in's colour preview of the cube, upright, with the caption `LiveView from the stand-in for the app, simulated` legible at the top. The Connections LiveView row says `Receiving (stand-in)` | **Passed (2026-10-07, Slicer 5.13.0).** The pane displayed the simulated preview and legible caption; LiveView reported `Receiving (stand-in)` at about 10 fps. The app volume was 1080×1080×1 RGB uint8, marked `simulated`; no laptop camera volume was present. |
| 2 | Press **Capture** | The pane freezes while UC1 and UC2 run, then resumes. `workspace\captures` holds a new `output_app_liveview_<time>.png` showing the frozen frame | **Passed.** Capture froze the pane while running and resumed afterward; the app volume's image modification time advanced again. Saved a valid 1080×1080, 8-bit RGB PNG at `workspace\captures\output_app_liveview_20261007-141052.png` (1,876,361 bytes). The stand-in logged a transient HsCube send timeout on 18946 after 37/109 bands, then reconnected and sent the full cube; LiveView continued and Capture completed. |
| 3 | Stop the stand-in (Ctrl+C) | The last frame stays, and the caption says it is no longer updated. **Capture** is refused, and the Status line says why. Start the stand-in again: frames resume and the mark goes | **Passed (retested 2026-10-07, Slicer 5.13.0, fresh load).** Ctrl+C left the frame unchanged for 2 seconds; Capture was refused, did not freeze, and created no PNG. The two-line stale caption was legible at the top, clear of the pane label. Restart restored `Receiving (stand-in)` at about 10 fps, advanced the image, cleared the stale line, and changed Status to `LiveView from the app arrives again. Capture is available.` |
| 4 | Set **Live source** to `Laptop camera`, press **Start** | The app's frames stop, the laptop camera is shown with no caption, and the stand-in's frames never appear in the pane | **Passed.** With the stand-in still sending at about 9–10 fps, the selected pane background was `Laptop camera` (640×480 RGB), the caption was empty, and no app-owned volume existed. |
| 5 | Press **Stop**, then **Disconnect**, then close the scene | The pane returns to its waiting message; no `LiveView from the app` volume is left in the Data module | **Passed.** Stop returned the pane to its waiting message; Disconnect changed the LiveView row to `Not connected`; closing the scene removed the laptop camera volume as well. No app volume remained. |
| 6 | Hardware: start IUMA's `AcquisitionSystemApp` with its cameras. **Connect**, choose `LiveView from the app`, **Start**, then **Capture** | The colour camera is shown upright and in true colour, with `LiveView received from the app`. Note the frame size, the rate in the Connections row, and any stutter. Capture freezes it | **Not run.** IUMA's app and cameras were unavailable. The stand-in does not verify the real stream's colour order, row order, size, rate, or stutter. |

## Risks

- The app's frame size (up to 4096 x 3000, 36 MB as RGB) and rate are not
  measured. Each new frame is copied twice on the main thread, off the
  connector's node and into the module's volume: about 74 MB per frame at full
  size, before it is drawn, which may make the UI stutter. Manual step 6 records it. Downscaling is out of
  scope.
- The real stream's row order and colour order are not measured. The task
  takes row 0 as the top and the channels as RGB, as the app's documentation
  and the stand-in say. Manual step 6 checks it.
- OpenIGTLinkIF pulls messages on a 5 ms timer and keeps 3 per device, so the
  pane can show only what reached the connector's node (`SLIA-035`).

## Documentation impact

- `extensions/SLIAFlow/README.md`: the live source choice, Capture on the
  app's LiveView, the snapshot name, the provenance; the Connections section no
  longer says LiveView is not shown.
- `docs/development/openigtlink_setup.md`: the front note.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: only if the live pane
  rules change.

## Completion evidence

### Implementation (2026-10-07, branch `feature/SLIA-037-app-liveview-in-the-live-pane`)

Order of work: the tests were written first and run against the module as
committed on `main`, then the module was changed.

Decisions taken while implementing, within the requirements:

- The app's frames reach the widget through `SLIAFlowLogic.startAppLiveView`,
  which polls `SLIAFlowConnections.takeLiveViewFrame` on a 66 ms Qt timer, the
  camera's interval. A frame is taken when the connector node's image data is
  newer than the last one taken, so an unchanged node is never shown twice.
- `liveViewRefusal` decides what the pane can show from the same
  `MessageObservation` the Connections rows use.
- `OpenIGTLink.SLIAFlow.SimulationDetail` joins the sender metadata SLIAFlow
  removes when a connection is lost, so a stand-in's detail cannot pass to the
  next sender.
- OpenIGTLinkIO copies an IMAGE's pixels into `vtkImageData` with `memcpy`
  (`igtlioImageConverter.cxx`), so the message's row 0 is the volume's row 0,
  shown at the top by SLIAFlow's upright directions.
- With the app chosen, the module's ready status says to press Start for
  LiveView from the app rather than for the laptop camera.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md` was not changed: its
  live-pane rules are what this task implements.

### Seen failing first

The 10 new tests and the changed `test_operatorControlsHaveStatedReasons`, run
against the unchanged module (`run-slicer-tests.ps1 -Test liveSource,
AppLiveView,appLiveView,cameraSourceShowsNoFrame,switchingTheLiveSource,
operatorControlsHaveStatedReasons`, headless): 11 run, 1 failure, 10 errors,
exit 1.

- Nine errors: `AttributeError: 'SLIAFlowParameterNode' object has no
  attribute 'liveSource'. Did you mean: 'cubeSource'?`
- `test_switchingTheLiveSourceStopsTheOneLeft`: `AttributeError: '' object has
  no attribute 'liveSourceSelector'. Did you mean: 'cubeSourceSelector'?`
- `test_operatorControlsHaveStatedReasons`: `Lists differ` - the operator
  section had no `liveSourceSelector`.

With the implementation, the same selection: 11 run, OK.

### Checks

Final runs, after the last code change:

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | `Python quality checks passed.` (both targets) | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | 153 run, OK, 18 skipped (headful-only), 35.3 s | 0 |
| Slicer, Source, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | 153 run, OK, 1 skipped (headless-only), 82.1 s | 0 |
| Build | `.\scripts\development\build-sliaflow.ps1 -Configure` | build tree matches the working tree | 0 |
| Slicer, Build, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | loaded from `build\SLIAFlow`; 153 run, OK, 1 skipped, 79.4 s | 0 |
| Whitespace | `git diff --check` | nothing reported | 0 |

After the first step 3 fix, the first headless run took 56.8 s and failed one test
unrelated to LiveView, `test_receivedCubeArrivesWhileSlicerWaitsForEvents` ("No
cube while Slicer waited for events", 0 / 20 bands), exit 1. Run alone it
passed (exit 0), and the full headless rerun above passed. It is timing under
load, not this change.

The simulators were not changed, so their tests were not rerun.

### Not done

- Manual step 6 needs IUMA's `AcquisitionSystemApp` with its cameras. The real
  stream's size, rate, row order, colour order and stutter remain unverified
  (Risks).

## Review findings

### Review of the uncommitted changes (2026-10-07), and what was done

1. **High - an old frame shown as fresh after reconnection, with wrong
   provenance.** Confirmed: a frame delivered but not yet taken when the
   connection dropped was handed over on the next connection, and, its sender
   metadata removed on the loss, a stand-in frame came back `received`. Fixed:
   `SLIAFlowConnections` records VTK's modification time when the LiveView
   connection begins (Connect) or is seen lost (the rows' `_follow`, on the
   connector's events, or the live pane's own poll), and takes only data newer
   than that. A loss seen first by the poll is followed up as the rows do, so
   the metadata goes too. One frame a new sender delivers before the loss is
   seen can be skipped; the next is shown.
2. **Medium - Capture just after the loss, before the next poll.** Confirmed.
   Fixed: Capture polls the app's LiveView once (`SLIAFlowLogic.pollAppLiveView`)
   before deciding, so a loss, or a newer frame, is taken first.
3. **Medium - real orientation and colour unverified.** Agreed; unchanged. This
   is manual step 6 and is listed under Risks.
4. **Medium - full-size responsiveness.** Agreed that the documents understated
   it: each frame is copied twice (off the connector's node, then into the
   volume by `updateVolumeFromArray`, which deep-copies), about 74 MB at
   4096 x 3000. The README and Risks now say so. No optimisation before manual
   step 6 measures it.
5. **Low - non-image messages unnamed.** Confirmed. Fixed: every incoming node
   with a new message is considered; a TRANSFORM, STATUS or STRING is refused
   with its description, as an unsuitable image is.

Seen failing first, before the fixes (`run-slicer-tests.ps1 -Test
captureRightAfterTheConnectionIsLost,FrameOfALostConnection,NamesAMessageThatIsNoImage`,
headless): 3 run, 4 failures (two subtests), exit 1 -
`test_appLiveViewFrameOfALostConnectionIsNotNews` (both ways the loss is seen:
"The lost connection's last frame was handed over as new", the stand-in frame
with `simulated=False` in one),
`test_appLiveViewNamesAMessageThatIsNoImage` ("A TRANSFORM on the LiveView port
went unnamed"), `test_captureRightAfterTheConnectionIsLostIsRefused` ("Capture
ran on the frame of a connection already lost"). After the fixes, the 14
SLIA-037 tests: OK; full runs in Checks above.

### Manual step 3 retest (2026-10-07, Slicer 5.13.0)

With the latest source loaded in a fresh Slicer session, Ctrl+C left the frame
unchanged for 2 seconds. Capture was refused with the loss reason, did not
freeze, and created no PNG. The two-line stale caption was legible at the top
of the pane and clear of the `B: LiveView from the app` label. Restart restored
`Receiving (stand-in)` at about 10 fps, advanced the image, removed the stale
line, and changed Status to `LiveView from the app arrives again. Capture is
available.` Step 3 passed.

- New headful test `test_appLiveViewStaleCaptionIsNoWiderThanTheLiveOne`
  measures each caption line with the caption's own text property
  (`vtkTextRenderer`). Seen failing first against the one-line caption: 1 run,
  1 failure, exit 1, "607 not less than or equal to 314". After the fix it
  passes.
- `_appLiveSession` now turns on the six-panel layout when Slicer has one, so
  the caption assertions that the LiveView tests guard with
  `widget._presentationActive` run headful. Before this, they never ran. The
  12 LiveView tests, headful: OK, exit 0.
- Manual step 3 passed after the retest below.

### Second fix for manual step 3 (2026-10-07)

- **Overlap.** Slicer writes the volume names (`B: ...`) and the probe text in
  the slice view's bottom-left corner, so any caption at the bottom can meet
  them. The live pane's caption is now at the top, as HS Cube's is
  (`CAPTION_POSITIONS`). The stale mark stays its second line.
- **Status.** When a frame arrives after the mark, the Status line says
  `LiveView from the app arrives again. Capture is available.`, replacing the
  refusal.
- Tests, seen failing first (`-Headful -Test
  StaleCaptionIsNoWider,KeepsItsLastFrameWhenTheConnectionIsLost`): 2 run, 2
  failures, exit 1.
  - `test_appLiveViewStaleCaptionIsNoWiderThanTheLiveOne` now also renders the
    pane and requires the caption's drawn box to lie in the top half. Before the
    fix it failed with "The caption reaches the bottom half".
  - `test_appLiveViewKeepsItsLastFrameWhenTheConnectionIsLost` now requires the
    refusal to leave Status once frames resume. Before the fix it failed with
    "Status kept the refusal after LiveView resumed".
  - After the fix, the same selection: 2 run, OK, exit 0. Full runs are under
    Checks.
- Manual step 3 passed on retest (details above).

## Human approval

The project owner confirmed completion and authorized commit and push on
2026-10-07.
