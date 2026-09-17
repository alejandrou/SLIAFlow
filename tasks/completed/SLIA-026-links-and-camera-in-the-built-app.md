---
id: SLIA-026
title: Make link waiting explain itself and show the laptop camera upright
status: completed
branch: feature/SLIA-026-links-and-camera-in-the-built-app
priority: high
depends_on: SLIA-022, SLIA-025
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-026 - Make link waiting explain itself and show the laptop camera upright

## Goal

Fix two faults the project owner saw on 2026-09-17 while running the built
launcher `build\SLIAFlow\SlicerWithSLIAFlow.exe`:

1. After **Connect links**, all five links stay `connecting` indefinitely, and
   nothing in the panel says why or what to start.
2. The laptop camera image in the LiveView pane is upside down.

## Context

### What was checked, and what was ruled out

The investigation checked for a different or stale Slicer first, because the
owner suspected that a Slicer somewhere in a temp folder was being used for
testing.

- **No other Slicer is running or installed in temp.** The only SLIAFlow
  processes were the owner's chain:
  `build\SLIAFlow\SlicerWithSLIAFlow.exe` -> `apps\SR\Slicer-build\Slicer.exe`
  -> `apps\SR\Slicer-build\bin\Release\SlicerApp-real.exe`. `%TEMP%` and
  `%LOCALAPPDATA%` contain no Slicer executable. The only other Slicer-based
  installs are `C:\Program Files\StaRT 0.4.0-2026-03-24` and
  `StaRT 0.5.0-2026-05-29`, which are unrelated to this project.
- **The automated tests use the same Slicer binary.**
  `scripts\development\run-slicer-tests.ps1` runs `config/local.json`'s
  `slicerExecutable`, `C:/stratum/apps/SR/Slicer-build/Slicer.exe`. Its default
  `-SlicerFrom Source` mode loads the module from `extensions\SLIAFlow\SLIAFlow`
  instead of `build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules`. The binary is
  the same; only the module location differs.
- **The build copy is not stale.** Every `.py` file and `SLIAFlow.ui` under
  `build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules` is byte-identical to
  `extensions\SLIAFlow\SLIAFlow` (checked with `diff -q`).

So the built app runs current code. Both faults are also present in the source
tree.

### Fault 1 - links stay `connecting` forever

**Cause: nothing is listening.** Every SLIAFlow link is a
`vtkMRMLIGTLConnectorNode` in **client** mode (`SetTypeClient`,
`SLIAFlowLogic.getOrCreateConnector`). A client connects only when a server
listens on the port. While the owner's Slicer was running,
`Get-NetTCPConnection -LocalPort 18944,18945,18946,18947,18948,18950` returned
no listener, and no Python producer process existed. The connector therefore
stays in `StateWaitConnection`, which the panel correctly reports as
`connecting`.

The servers are the Python producers in `tools\simulators`, and they run only
under `scripts\development\run-end-to-end-session.ps1 -Case <case>`:

| Port | Producer | When it listens |
| ---: | --- | --- |
| 18944 LiveView | acquisition stand-in | when the session starts |
| 18947 HS Cube | acquisition stand-in | when the session starts |
| 18950 Control | acquisition stand-in | when the session starts |
| 18945 UC1 | genuine UC1 runner | only after the first capture reports READY |
| 18946 UC2 | none exists (`SLIA-021`) | never |

This is the documented behaviour. `SLIA-022`'s manual step 3 records "Press
Connect links with no producer running -> five labels in `connecting`". The
earlier statement to the owner that pressing Connect links is enough, with no
setup, was **wrong**. It worked in verification only because the session script
was already running.

Nevertheless, the panel is not doing its job. It shows a `connecting` state that
never changes and never names the missing producer or the command that starts
it. In addition, two traps are not mentioned anywhere in the panel:

- **UC2 (18946) can never connect**, because no producer exists yet, and **UC1
  (18945) connects only after a capture**. So even a correct session leaves two
  labels on `connecting` at first, which looks like the same fault.
- **Camera contention.** The acquisition stand-in opens camera index 0 for
  LiveView. In the screenshot, SLIAFlow's own **Laptop Camera** source was
  running, which also holds index 0. With that source running, starting the
  session makes the stand-in fail on the camera and exit, so 18944, 18947 and
  18950 never listen. The Live source must be left off, or switched to the
  network stream, before the session starts.

### Fault 2 - the laptop camera is upside down

**Cause: the live volume has no image geometry.**
`SLIAFlowLogic.frameToRGBKJI` keeps OpenCV's row order, where row 0 is the top
of the picture. `getOrCreateLiveVolume` creates the `vtkMRMLVectorVolumeNode`
with the default identity IJK-to-RAS matrix, and `_configurePresentation` shows
every pane as an Axial slice. In an Axial slice view, +R is drawn to the screen
left and +A to the screen top, so with identity directions:

- increasing i (image columns, left to right) is drawn right to left; and
- increasing j (image rows, top to bottom) is drawn bottom to top.

Both axes are reversed, so the picture appears rotated 180 degrees, which is
what the screenshot shows.

The OpenIGTLink LiveView path does not have this fault. The stand-in sends an
identity matrix in **LPS** (`igtl_transport.py`), which Slicer converts to RAS
directions `diag(-1, -1, 1)`. With those directions, i is drawn left to right
and j top to bottom. This is why the network stream looked correct during
`SLIA-022` and `SLIA-024` verification while the direct camera path was never
checked for orientation: `SLIA-005` said it "preserves the raw frame
orientation", and `SLIA-022` placed orientation out of scope.

**Solution:** give the module-owned live volume the same geometry the wire
gives, IJK-to-RAS directions `diag(-1, -1, 1)`. Apply it every time
`getOrCreateLiveVolume` returns a node, including a reused node, so a scene that
already holds the old node is also corrected. Do not mirror the image as a
selfie view: the operator sees what the camera sees, which matches the stand-in.

## Requirements

### Link waiting

- When a link has been `connecting` for longer than a short grace period, which
  the task decides and records, its status line names what should serve that
  port and how to start it, for example:
  `connecting - nothing is listening on 127.0.0.1:18944. Start
  run-end-to-end-session.ps1 -Case <case>.`
- The UC1 link's waiting text says that the UC1 producer starts after the first
  capture.
- The UC2 link's waiting text says that no UC2 producer exists yet (`SLIA-021`),
  so it is expected to stay unconnected.
- When the Live source is **Laptop Camera** and the camera is running, pressing
  Connect links warns, without blocking, that the acquisition stand-in cannot
  open the same camera and that the camera should be stopped first.
- The wording names ports and commands only. It must not claim a producer is
  running, and must not change the `connecting`, `receiving` or `disconnected`
  state vocabulary that existing tests rely on.
- SLIAFlow does **not** start, stop or supervise producer processes. The
  producers stand where the real acquisition and UC1 components will stand, and
  launching them from Slicer would couple the module to the stand-in. If the
  owner wants one-click startup, that is a separate task.

### Camera orientation

- The laptop camera frame is shown upright and unmirrored in the LiveView pane:
  image top at the screen top, image left at the screen left.
- A live volume that already exists in the scene is corrected too, not only a
  new one.
- The OpenIGTLink LiveView path is unchanged.

## Out of scope

- Any change to `tools/simulators/`, the launcher script, ports or the
  OpenIGTLink contract.
- A UC2 producer (`SLIA-021`).
- Starting producers from Slicer.
- The stereoscopic (18948) and StO2 (18949) ports.
- Rewriting `SLIA-009`'s runbook. That card should reference this card's
  wording once this card is complete.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/README.md`
- `tasks/active/SLIA-026-links-and-camera-in-the-built-app.md`

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1` and is never edited by hand.

## Relevant skills and references

- Slicer skill: `vtkMRMLVolumeNode::SetIJKToRASDirections`, slice orientation
  conventions, `vtkMRMLIGTLConnectorNode` states.
- `tasks/completed/SLIA-005-laptop-camera.md`,
  `tasks/completed/SLIA-022-operator-first-panel.md` (manual step 3).
- `tools/simulators/README.md` (Ports; LiveView camera index 0).

## Implementation plan

1. Write failing tests for the live volume directions and for the waiting text
   of each role.
2. In `getOrCreateLiveVolume`, set IJK-to-RAS directions to `diag(-1, -1, 1)` on
   both the created node and the reused node.
3. Add the per-role "nothing is listening" text, driven by how long the
   connector has been in `StateWaitConnection`, and keep it separate from the
   state label.
4. Add the camera contention warning to the Connect links path.
5. Rebuild with `build-sliaflow.ps1`, then verify manually in
   `SlicerWithSLIAFlow.exe`, not only in the Source-mode test Slicer.

## Acceptance criteria

1. The laptop camera is upright and unmirrored in the LiveView pane of the built
   app.
2. The live volume's IJK-to-RAS directions are `diag(-1, -1, 1)`, for new and
   reused nodes.
3. With no producer running, each link names its port and what starts its
   producer after the grace period.
4. The UC1 and UC2 waiting texts state their special cases.
5. Pressing Connect links while the laptop camera is running shows the
   contention warning.
6. With `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer` running and the
   built app started by hand, LiveView, HS Cube and Control reach `receiving`
   without the waiting text.
7. Existing state vocabulary and tests are unchanged.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | Manual step 2 | manual |
| 2 | `SLIAFlowTest.test_liveVolumeIsDisplayedUpright` (new) | automated |
| 3 | `SLIAFlowTest.test_waitingLinkNamesItsProducer` (new) | automated |
| 4 | `SLIAFlowTest.test_uc1AndUc2WaitingTextExplainsTheirProducers` (new) | automated |
| 5 | `SLIAFlowTest.test_connectLinksWarnsWhileTheLaptopCameraHoldsIt` (added during implementation), manual step 3 | automated + manual |
| 6 | Manual step 4 | manual |
| 7 | Full `run-slicer-tests.ps1` run | automated |

Each new test is run first against the unchanged code and must fail: the
directions test because the matrix is identity, and the text tests because no
such text exists.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `build-sliaflow.ps1`, then start `build\SLIAFlow\SlicerWithSLIAFlow.exe` | SLIAFlow opens with six panes |  |
| 2 | Live source Laptop Camera, press Start, raise a hand on the right side of your body | The picture is upright, and the raised hand appears on the side the camera sees it |  |
| 3 | With the camera still running, press Connect links, wait past the grace period | Contention warning shown; each link names its port and producer |  |
| 4 | Stop the camera, disconnect links, run `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer`, press Connect links, press Capture | LiveView, HS Cube and Control reach `receiving`; UC1 connects after READY; UC2 keeps its "no producer yet" text; the network LiveView is also upright |  |

## Risks

- A console-launched session and the built app both dial the same ports. A
  second Slicer left running takes the one-client producers first; the session
  script already refuses to start in that case.
- The grace period must not flash the waiting text during a normal connect.

## Documentation impact

`extensions/SLIAFlow/README.md`: one short "links connect only when producers
are running" note with the session command, and the camera index 0 conflict.

## Implementation decisions

- **Grace period: 3.0 s** (`SLIAFlowWidget.LINK_WAITING_GRACE_SEC`). A listening
  producer on 127.0.0.1 connects on the first connector attempt, well inside a
  second; three polls of the existing 1 s link-state timer do not flash the text
  during a normal connect.
- **Where the text appears.** `SLIAFlow.ui` is not in `Files allowed`, so the
  waiting text is a `linkWaitingLabel` created in `SLIAFlowWidget.setup` and
  added to the existing Status group: one line per waiting link, prefixed with
  the link name, and hidden while empty. The per-link state labels keep only
  the `connecting`/`receiving`/`disconnected` vocabulary.
- **Command named.** `scripts\development\run-end-to-end-session.ps1 -Case <case>
  -NoSlicer`. The reader is already inside a Slicer, and without `-NoSlicer`
  the session starts a second one.
- **Camera contention warning** is shown under Status while any link exists, the
  Live source is Laptop Camera and the camera is running; it is also logged once
  per Connect links press. It never blocks connecting and disappears when the
  camera stops.
- **Live volume geometry** is applied by `SLIAFlowLogic._applyLiveVolumeGeometry`
  on create and on every reuse, and writes only when the directions differ,
  because `getOrCreateLiveVolume` runs for every camera frame.

## Completion evidence

### Automated (2026-09-17, branch `feature/SLIA-026-links-and-camera-in-the-built-app`)

| Check | Command | Result |
| --- | --- | --- |
| Red run, before implementation | `scripts\development\run-slicer-tests.ps1` | exit 1: 78 run, `test_liveVolumeIsDisplayedUpright` FAIL, the three text/warning tests ERROR (no such API); the other 67 ok, 7 skipped |
| Lint | `.venv\Scripts\ruff check extensions/SLIAFlow` | All checks passed |
| Whitespace | `git diff --check` | clean |
| Source, headless | `run-slicer-tests.ps1` | exit 0: Ran 78, OK (skipped=7, no layout manager) |
| Source, headful | `run-slicer-tests.ps1 -Headful` | exit 0: Ran 78, OK (skipped=1, headless-only test) |
| Rebuild | `scripts\development\build-sliaflow.ps1` | exit 0: build tree matches the working tree |
| Build, headful | `run-slicer-tests.ps1 -Target Build -Headful` | exit 0: module loaded from `build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules`; Ran 78, OK (skipped=1) |

`ruff format --check` reports files that would be reformatted, including
files this task did not touch (`SLIAFlow.py`, `SLIAFlowParameterNode.py`), so it
is not used as a gate here.

### Manual

Not yet performed. Steps 1-4 above are pending the project owner.

## Review findings

## Human approval
