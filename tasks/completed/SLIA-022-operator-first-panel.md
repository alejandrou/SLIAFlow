---
id: SLIA-022
title: Six-panel operator surface with a capture button
status: active
branch: feature/SLIA-022-operator-first-panel
priority: high
depends_on: SLIA-016, SLIA-023
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001]
---

# SLIA-022 - Six-panel operator surface with a capture button

## Goal

Replace the two-pane engineering console with the six-view operator surface the
WP5 demonstrator needs: a layer list with show, hide and opacity, one honest
statement of connection state per link, a capture button, a band browser for the
received cube, and a black panel with a written reason wherever a producer does
not exist yet.

## Context

Originally raised by the project owner after the `SLIA-014` session: too many
buttons and too many swaps for two obvious images, and some controls with no
evident purpose. Counted from
`extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui` on `main` at `a45e5ac`:
eight push buttons, two combo boxes, two spin boxes and one check box - thirteen
interactive controls - alongside twenty-one labels, to put two images on screen.

`docs/architecture/WP5_MS5_DEMO_PLAN.md` widens this card. The screen it has to
produce is:

```
+----------------+----------------+----------------+
| LiveView       | Stereoscopic   | HS Cube        |
| laptop camera  | BLACK          | band browser   |
|                | "no producer"  |                |
+----------------+----------------+----------------+
| Relative StO2  | Enhanced       | Tumour         |
| BLACK          | Vascularization| Delineation    |
| "no algorithm" | UC2            | UC1            |
+----------------+----------------+----------------+
```

Two panels are deliberately black, with their reason written on them and a port
reserved, so that the day UPM delivers depth and ULPGC delivers the
optical-parameter algorithm, a process is started on that port and the panel
lights up with no change inside `extensions/`.

A single `Result map` combo box can only show one thing at a time, so it cannot
express a screen on which a UC1 and a UC2 result are both present.

### What exists today, read on 2026-09-15

- `SLIAFlowWidget` registers layout 701: two slice views, `SLIAFlowLive`
  (`Live Image`) and `SLIAFlowResult` (`UC1 Result`).
- Two module-owned client connectors, acquisition (18944) and UC1 (18945), each
  with a Connect and a Disconnect button and a state label. `SLIA-016`'s link
  history (`_linkDropped`, `_linkDropSnapshots`) keeps a retained image stale
  until the reconnected socket delivers new data.
- The UC1 result is validated, copied into a module-owned presentation volume,
  and bound as the background of `SLIAFlowResult`. A simulated result needs the
  transient demo-mode opt-in and is withheld if its banner cannot be drawn.
- `SLIA-023` publishes `HSCube` on 18947 and the control channel on 18950
  (`CaptureTrigger` in, `CaptureReply` and `CaptureStatus` out, exact wording in
  `tools/simulators/README.md`). Nothing in SLIAFlow consumes either yet.
- The pinned SlicerOpenIGTLink build wraps
  `vtkMRMLIGTLConnectorNode.RegisterOutgoingMRMLNode(node, devType)` and
  `PushNode(node)` (read from
  `build/SlicerOpenIGTLink/inner-build/OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNodePython.cxx`).
  Its C++ source is not on this machine, so the STRING-to-`vtkMRMLTextNode`
  mapping is taken from SlicerOpenIGTLink's documented behaviour and confirmed
  in manual step 4, not assumed by any automated test.

## The decisions this card was blocked on, now answered

**`ADR-0001` is accepted.** The project owner accepted it on 2026-09-15 when
activating this card.

**Does the laptop-camera path retire? No, and it keeps its own panel.** The
LiveView panel is the camera's panel. `SLIA-009`'s camera-only demonstration
keeps working. The camera index spin box and the OpenCV install button move to a
developer section.

Only one process can hold the laptop camera. If the acquisition stand-in streams
the webcam on `LiveView`, SLIAFlow's own camera path must not also open it. The
panel has one live source at a time and the live-source selector says which.

**Which layers, over which background?** Answered by the project owner on
2026-09-15, applying `ADR-0001` rule 3: a result is composited only over a
background from its own producer on its own connection. `UC2_BV` comes from a
different producer on 18946, so it is never drawn over `UC1_RGB`. Each result
therefore has its own panel:

- the UC1 result in Tumour Delineation;
- `UC2_BV` in Enhanced Vascularization.

The `UC1_RGB` background, the size comparison and the camera-never-a-background
guard stay in `SLIA-024`. This card's earlier wording - "at least three layers",
"both results present over one background" - contradicted the accepted ADR and
is corrected here.

**How are the links brought up?** Answered by the project owner on 2026-09-15:
one Connect links toggle connects or disconnects all five links, and each link
has one state label. Nothing opens a socket until the operator asks.

## Requirements

### Layout

- Register a six-view layout (id 702, so that a Reload in a session that already
  holds 701's two-pane description cannot collide with it) in two rows of three:
  LiveView, Stereoscopic, HS Cube; Relative StO2, Enhanced Vascularization,
  Tumour Delineation. Every view has its name on screen.
- The existing `SLIAFlowLive` and `SLIAFlowResult` views keep their singleton
  tags, so every binding guard written against them still applies. The result
  view's label becomes `Tumour Delineation`.
- A panel with no producer is black and carries a written reason naming what is
  missing and which port is reserved for it: Stereoscopic names UPM depth and
  18948, Relative StO2 names the ULPGC optical-parameter algorithm and 18949. It
  is never empty, never a spinner and never a placeholder image.
- A panel that has a producer but no data yet is black and says what it is
  waiting for, as the result view does today. A hidden layer's panel says it is
  hidden, so hidden, waiting and reserved never look alike.
- Leaving the module restores the previous layout, as today.

### Layer list

- A layer list holds one row per result layer: the UC1 result (Tumour
  Delineation) and `UC2_BV` (Enhanced Vascularization). Each row can be shown,
  hidden and faded without changing the other row.
- Opacity is display state only. Full opacity binds the layer as the panel's
  background, exactly as today; lower opacity binds it as the foreground over an
  empty background with that foreground opacity. No pixel of any result is
  changed.
- The layer list and its state are transient widget state and are not persisted.

### Enhanced Vascularization (`UC2_BV`)

- A received `UC2_BV` node is shown in its panel only after validation: a
  `vtkMRMLVectorVolumeNode` with image data, positive dimensions, three
  components and `uint8` scalars. It is copied into a module-owned presentation
  volume, as the UC1 result is.
- It obeys every safety behaviour the UC1 result obeys: a recognised origin is
  required and never defaulted; a genuine source wins over a simulated one;
  a simulated source is shown only under demo mode and under a banner in its own
  panel, and is withheld if that banner cannot be drawn; invalid or missing data
  leaves the panel black with an explicit status.
- The UC2 banner reads `SIMULATED ACQUISITION - NOT A CLINICAL RESULT`, with the
  producer's detail line beneath it. It does not reuse the UC1 wording, which
  names UC1.

### Links

- Five module-owned client connectors: LiveView 18944, UC1 18945, UC2 18946, HS
  Cube 18947, Control 18950. 18948 and 18949 are never connected.
- One Connect links toggle starts or stops all five. It is disabled, with its
  reason, when this Slicer has no OpenIGTLink.
- One state label per link, reporting the connector's state. The LiveView and
  UC1 labels keep `SLIA-016`'s displaying, invalid and stale behaviour
  unchanged; UC2 reports displaying and invalid the same way; HS Cube and Control
  report the connector state.

### Capture

- A capture button sends the text `CAPTURE` on a module-owned, never-saved
  `vtkMRMLTextNode` named `CaptureTrigger`, registered as an outgoing STRING on
  the control connector, with exactly one `PushNode` per press.
- The capture button is enabled only while the control link is connected;
  otherwise it is disabled and its status line says the control link on
  127.0.0.1:18950 is needed and to press Connect links.
- A capture state line reflects the latest `CaptureStatus` (idle, capturing,
  ready) and the latest `CaptureReply` (capturing, ignored, refused), quoting
  the stand-in's own words.

### HS Cube

- A received `HSCube` node is shown in the HS Cube panel, and a band slider
  browses it by band, showing the band index and its wavelength from
  `SLIAFlow.WavelengthsNm`.
- If the wavelength list is absent, unparsable, or does not have one value per
  band, the band is shown by index only and the panel status says why. A
  wavelength is never guessed.
- The cube is input, not a result. It is shown as received, with Slicer's
  display window/level; nothing is computed from it.

### Controls

- The operator section holds only controls an operator would recognise a reason
  for, each with that reason in its tooltip: live source, start camera, stop
  camera, Connect links, capture, demo mode, the layer list, the layer opacity
  slider and the band slider.
- The camera index, camera-support install, result-map selector, result class and
  refresh controls move to a collapsed Developer section. The four per-link
  Connect and Disconnect buttons are removed.
- The Tumour Delineation layer defaults to `majorityVotingMap`, the map the
  genuine UC1 runner sends. The role stays selectable in the Developer section.

### Preserved without exception

- The simulated banner, the transient never-persisted demo-mode opt-in,
  genuine-over-simulated precedence, provenance travelling with the data and
  never with the endpoint, and a black view with an explicit status when data is
  missing or invalid.
- SLIAFlow never creates a result. Neither the layer list nor the cube browser
  computes anything.

## Out of scope

- The `UC1_RGB` background, its size comparison, and the camera guard
  (`SLIA-024`).
- The UC2 producer, its build and its contract row (`SLIA-021`). This card shows
  `UC2_BV` when one arrives; there is no producer to run against yet.
- Colour bar, capture selection and result saving (EPIC 4).
- Orientation and the IJK-to-LPS mapping.
- Any change to producers, `tools/simulators/`, the launcher or the OpenIGTLink
  contract.
- Reworking `SLIA-009`'s runbook, which follows this card.
- Opening the stereoscopic or StO2 ports.
- Changing the existing banner wording or its tests. The UC1 fixture string
  `synthetic tissue phantom` belongs to `SLIA-025`.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `tasks/{backlog,active,review,completed}/SLIA-022-operator-first-panel.md`

Added while specifying: `SLIAFlow.py`, because its help text describes a
"two-pane presentation shell" that this card removes; and the ADR, to record its
acceptance.

## Relevant skills and references

- Slicer skill: layouts, slice composite nodes, OpenIGTLink connector nodes.
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, the target screen and port table
- `tools/simulators/README.md`, the control-channel wording and `HSCube` payload
- `SLIA-004`, `SLIA-005`, `SLIA-006`, `SLIA-010` and `SLIA-016` completion
  evidence
- `.ai/policies/algorithm-boundary-policy.md`

## Approved dependencies

None.

## Implementation plan

1. Record the safety suite, Ruff and the control count on the unchanged branch.
2. Write the new tests and record each one failing against the unchanged code.
3. Build the six-view layout with every panel black and its reason or waiting
   text written.
4. Add the connector roles, the Connect links toggle and the five state labels.
5. Add the layer list and the UC2 layer with its gate, banner and validation.
6. Add the control connector, the trigger node and the capture button.
7. Add the cube band browser.
8. Move the developer controls, re-count, and re-run every check.
9. Update the roadmap, the WP5 plan and the module help text.

## Acceptance criteria

1. Six named views in the stated layout; Stereoscopic and Relative StO2 are black
   and carry their written reason and reserved port.
2. The UC1 layer and the UC2 layer can each be shown, hidden and faded without
   changing the other, and a hidden layer's panel says it is hidden.
3. `UC2_BV` is shown only when valid, needs demo mode and a banner when
   simulated, loses to a genuine source, and leaves its panel black with a status
   when invalid or missing.
4. One Connect links control starts and stops all five links, and each link has
   one state label, with `SLIA-016`'s behaviour in place beneath.
5. The capture button is disabled with a reason when the control link is not
   connected, and sends exactly one trigger per press when it is.
6. The capture state line reflects the stand-in's status and reply.
7. The HS Cube panel browses bands and shows each band's wavelength, and refuses
   to show a wavelength it cannot read.
8. The operator section's interactive control count is materially reduced from
   thirteen, the count before and after is recorded, and every operator control
   has a tooltip reason.
9. Every existing safety test passes unmodified.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Six named views in two rows | `SLIAFlowTest.test_layoutDescriptionContract` (changed); Manual step 2 | automated + manual |
| 1. Reserved panels black with reason and port | `SLIAFlowTest.test_reservedPanelIsBlackWithStatedReason`; Manual step 2 | automated (headful) + manual |
| 2. Layers independent; hidden says hidden | `SLIAFlowTest.test_layersAreIndependentlyControlled`; Manual step 6 | automated + manual |
| 3. UC2 gate, precedence and banner | `SLIAFlowTest.test_uc2LayerObeysOriginGateAndPrecedence` | automated |
| 3. UC2 invalid or missing stays black | `SLIAFlowTest.test_invalidUc2LayerLeavesPanelBlack` | automated |
| 4. One control, five labels | `SLIAFlowTest.test_connectLinksStartsAndStopsEveryLink`; Manual steps 3 and 7 | automated + manual |
| 5. Capture disabled without control link | `SLIAFlowTest.test_captureDisabledWithoutControlLink`; Manual step 3 | automated + manual |
| 5. One trigger per press | `SLIAFlowTest.test_capturePressSendsOneTrigger`; Manual step 4 | automated + manual |
| 6. Capture state reflects the stand-in | `SLIAFlowTest.test_captureStateReflectsStandInAnswers`; Manual step 4 | automated + manual |
| 7. Band browser reports wavelength, refuses a bad list | `SLIAFlowTest.test_bandBrowserReportsWavelength`; Manual step 5 | automated + manual |
| 8. Control count and tooltip reasons | `SLIAFlowTest.test_operatorControlsHaveStatedReasons`; Manual step 1 | automated + manual |
| 9. Banner | `test_simulatedResultShowsPersistentBanner`, `test_realPipelineResultIsBanneredWithoutCallingItUngenuine`, `test_bannerFailureWithholdsSimulatedResult`, `test_bannerWordingFollowsTheProducer`, unmodified | automated |
| 9. Demo mode | `test_demoModeIsNotPersisted`, `test_demoModeDiscoversSimulatedSource`, `test_receivedSimulatedNodeObeysDemoModeGate`, unmodified | automated |
| 9. Precedence and provenance | `test_genuinePreferredOverSimulated`, `test_simulatedSourceIsNotGenuine`, `test_unknownProvenanceIsRejectedNotDefaulted`, `test_provenanceMirrorsTheWireInsteadOfAccumulating`, `test_simulationDetailNeverAffectsDiscovery`, unmodified | automated |
| 9. Invalid or missing data is black | `test_invalidResultLeavesResultViewEmpty`, `test_missingResultRestoresWaitingState`, `test_invalidResultDoesNotReplaceLastValidState`, `test_simulatedResultStillValidatedAgainstContract`, unmodified | automated |
| 9. Pane isolation and link state (`SLIA-008`, `SLIA-016`) | `test_liveViewNodeBindsToLivePaneOnly`, `test_resultNodeBindsToResultPaneOnly`, `test_staleResultIsNotReportedAsDisplayingWithoutALink`, `test_reconnect*`, `test_staleWordingSurvivesBrowsingAfterADrop`, unmodified | automated |

Tests to add or change, and how each one will be shown to fail first:

- Every new test is run against the unchanged code before any production edit,
  and its failure message is recorded in `## Completion evidence`. Against the
  unchanged code they fail on missing behaviour - no layer API, no capture
  button, no band browser, a two-view layout - which shows that each one is not
  vacuous.
- `test_reservedPanelIsBlackWithStatedReason` is also shown failing against a
  first implementation that leaves the reserved panels black but writes no
  reason on them.
- `test_capturePressSendsOneTrigger` is also shown failing against a mutation
  that both modifies the trigger node and pushes it, so a double send is shown
  to be caught.
- `test_uc2LayerObeysOriginGateAndPrecedence` is also shown failing against a
  mutation that lets a simulated `UC2_BV` through with demo mode off.
- Two existing tests change because they describe the two-pane surface this card
  removes, not a safety behaviour: `test_layoutDescriptionContract` (it asserts
  exactly two views) and `test_presentationParametersAndControls` (it asserts
  `tmdMap` as the default role). Both changes are recorded with the old and new
  assertion.
- No test in the safety rows above may be modified. If one needs modifying, a
  guard is being changed and the card stops.
- The unit-test images are deterministic test placeholders, not pipeline
  images, and are never evidence for a recorded-input check.

Checks: `.\scripts\development\run-python-quality.ps1`,
`.\scripts\development\run-slicer-tests.ps1`, and
`.\scripts\development\run-slicer-tests.ps1 -Headful`, each before and after.

## Manual verification

Performed in a real Slicer window during the recorded verification run, after
`.\scripts\development\build-sliaflow.ps1` or with the working tree loaded.
Project-owner sign-off remains required before completion.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Count the interactive controls in the SLIAFlow panel outside the collapsed Developer section, and hover each one | Nine controls, down from thirteen; each tooltip gives a reason an operator would accept | Observed 9 operator controls, down from 13; all 9 tooltips stated an operator-facing reason. |
| 2 | Open SLIAFlow with no producer running | Six panels named LiveView, Stereoscopic, HS Cube, Relative StO2, Enhanced Vascularization, Tumour Delineation; all black; Stereoscopic names UPM depth and port 18948; Relative StO2 names the ULPGC algorithm and port 18949; the other three say what they are waiting for | **PASS on rerun 2026-09-16:** with no producer running, all six named panels were black; LiveView carried the renderer-backed waiting text `Waiting for the LiveView image... port 18944`, and the reserved/waiting text for the other panels was present. |
| 3 | Press Connect links with no producer running | Five link labels, none reporting displaying; the capture button is disabled and the capture line says the control link on 18950 is needed | Observed five labels in `connecting`, none displaying; Capture stayed disabled and the line named 127.0.0.1:18950 and Connect links. |
| 4 | Run `.\scripts\development\run-end-to-end-session.ps1 -Case 004-02`, press Connect links, then press Capture once; after READY, press Capture twice in quick succession | Capture enables once the control link connects; the first press shows capturing, then ready, and the stand-in console logs exactly one trigger; of the next two presses the second is answered ignored on the capture line | **PASS on rerun 2026-09-16:** after rebuilding, the real trigger declared encoding `3` (IANA US-ASCII); the UI showed `CAPTURING` then `READY`. Two rapid Capture presses produced one new capture and `IGNORED capture 2 already in progress`; the acquisition log recorded exactly one `CAPTURE` and one ignored trigger. |
| 5 | After a READY, drag the band slider from one end to the other | The HS Cube panel image changes; band 0 reads 440 nm and band 92 reads 900 nm, and index and wavelength move together | Observed with the approved recorded-case trigger workaround: band 0 read 440 nm and band 92 read 900 nm; the slider max was 92 and the HS Cube view updated with the selected band. |
| 6 | With UC1 producing and demo mode on, untick the UC1 layer, tick it again, then move its opacity from 100 to 0 | Unticked, the Tumour Delineation panel says the layer is hidden; ticked, the map returns; opacity fades it to black; the banner stays on screen throughout; the Enhanced Vascularization panel does not change | Observed with the approved recorded case and simulated-result banner: hidden text appeared, re-ticking restored the map, opacity 0 blacked the panel while the banner remained, and the UC2 waiting state did not change. |
| 7 | Stop every producer | Every link label leaves displaying; no panel claims to be displaying new data; a retained result says it is not being updated | **PASS on Step 7-only rerun 2026-09-16:** after the recorded UC1 result was active under the visible simulated banner, the verified acquisition/UC1 producer listener processes were stopped. The listeners closed at 10:43:54.901 UTC; the real connector nodes reached `connecting` at 10:43:56.299 UTC (about 2.4 s after the stop command and 1.4 s after the ports closed). The visible labels changed from `displaying`/`receiving` to `connecting` at 10:43:56.803 UTC, about 0.5 s after the connector state change. Within the 20 s window, the result changed to `WARN: SIMULATED: The UC1 link is not connected. The last valid result is still shown and is not being updated.` No stale link label remained. |
| 8 | Leave the module | The previous Slicer layout is restored | Observed the standard Slicer four-view layout restored on leaving SLIAFlow. |

The UC2 panel cannot be exercised by hand until `SLIA-021` delivers its producer.
Its behaviour is covered by the automated tests above, and a manual step for it
belongs to `SLIA-021`.

## Risks

The largest risk is that simplification removes a guard. The demo-mode check box
is a safety interlock, and the result status is the only place an operator learns
that what they are looking at is stale. The rule that no existing safety test may
be modified exists to make that failure loud.

The UC2 panel duplicates the UC1 gate for a second role. A second copy of a guard
can drift from the first, so the UC2 tests assert the same four properties the
UC1 tests do rather than trusting shared code to carry them.

The STRING mapping and the connector's send-on-modify behaviour cannot be read
from source on this machine. The trigger is sent by an explicit `PushNode` and
its text is set once, before registration, so a press never also modifies the
node; manual step 4 confirms one trigger per press against the real stand-in.

A black panel with a reason is a promise about what is missing; a black panel
that is black because something broke is a defect. Reserved, waiting and hidden
each carry different text, and the reserved text is a tested requirement.

Opacity uses the foreground slot of an otherwise empty panel. `SLIA-024` puts
`UC1_RGB` in the background slot, so the foreground binding here is the one
that card composites over; it must not be read as permission to composite over
anything else.

Scope. Every EPIC 4 item is tempting while the panel is open. Colour bar,
capture selection and saving stay excluded.

## Documentation impact

- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: the user-visible
  behaviour section, the six-view layout, the five links, and the overlay
  rationale pointing at `ADR-0001`.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: the target screen implemented, with
  manual verification pending.
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`:
  accepted.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`: help text.

## Completion evidence

### Baseline on the unchanged branch, 2026-09-15

`feature/SLIA-022-operator-first-panel` from `main` at `a45e5ac`.

- `.\scripts\development\run-slicer-tests.ps1`: module loaded from
  `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`, `Ran 53 tests`,
  `OK (skipped=6)`, exit 0.
- `.\scripts\development\run-slicer-tests.ps1 -Headful`: `Ran 53 tests`,
  `OK (skipped=1)`, exit 0.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21,
  `extensions/SLIAFlow/SLIAFlow` (6 files) and `tools/simulators` (32 files)
  `All checks passed!`, exit 0.
- Interactive controls in `SLIAFlow.ui`: 13 (8 push buttons, 2 combo boxes,
  2 spin boxes, 1 check box).

### New and changed tests observed failing before the implementation

Only `SLIAFlowTest.py` changed; every production file was as on `main`.

`.\scripts\development\run-slicer-tests.ps1 -Headful`: `Ran 63 tests`,
`FAILED (failures=2, errors=10, skipped=1)`, exit 1. Headless: `Ran 63 tests`,
`FAILED (failures=2, errors=9, skipped=7)`, exit 1; the one difference is
`test_reservedPanelIsBlackWithStatedReason`, which is headful only. Every
existing safety test passed in both runs.

In that first run three tests reached `SLIAFlowParameterNode` as the class, not
the module, because `SLIAFlowLib/__init__.py` re-exports the class under the
module's name. The test file now imports the module with `importlib`, and the
headless run was repeated with production still unchanged: `Ran 63 tests`,
`FAILED (failures=3, errors=8, skipped=7)`, exit 1. The failures below are from
that repeat, and from the headful run for the headful-only test.

| Test | Failure against the unchanged code |
| --- | --- |
| `test_layoutDescriptionContract` (changed) | `AssertionError: 'horizontal' != 'vertical'` |
| `test_presentationParametersAndControls` (changed) | `AssertionError: 'tmdMap' != 'majorityVotingMap'` |
| `test_reservedPanelIsBlackWithStatedReason` | `AttributeError: 'SLIAFlowWidget' object has no attribute 'STEREO_VIEW_NAME'` |
| `test_layersAreIndependentlyControlled` | `AttributeError: 'SLIAFlowWidget' object has no attribute 'LAYER_UC1'` |
| `test_uc2LayerObeysOriginGateAndPrecedence` | `AttributeError: 'SLIAFlowWidget' object has no attribute 'LAYER_UC2'` |
| `test_invalidUc2LayerLeavesPanelBlack` | `AttributeError: 'SLIAFlowWidget' object has no attribute 'LAYER_UC2'` |
| `test_connectLinksStartsAndStopsEveryLink` | `AssertionError: Items in the second set but not the first:` (the roles `uc2`, `hsCube` and `control`) |
| `test_captureDisabledWithoutControlLink` | `AttributeError: '' object has no attribute 'captureButton'` |
| `test_capturePressSendsOneTrigger` | `AttributeError: module 'SLIAFlowLib.SLIAFlowParameterNode' has no attribute 'CONNECTOR_CONTROL'` |
| `test_captureStateReflectsStandInAnswers` | `AttributeError: module 'SLIAFlowLib.SLIAFlowParameterNode' has no attribute 'CONNECTOR_CONTROL'` |
| `test_bandBrowserReportsWavelength` | `AttributeError: 'SLIAFlowWidget' object has no attribute '_refreshCubePresentation'` |
| `test_operatorControlsHaveStatedReasons` | `RuntimeError: Widget with name='operatorGroupBox' does not exist.` |

### Changes to existing tests, recorded

- `test_layoutDescriptionContract`: it asserted exactly two views in a
  horizontal layout; it now asserts two rows of three named views, and that the
  live and delineation views keep the `SLIAFlowLive` and `SLIAFlowResult` tags
  every pane-isolation guard is written against.
- `test_presentationParametersAndControls`: it asserted `tmdMap` as the default
  role. It now asserts `majorityVotingMap` on a freshly wrapped parameter node,
  and that the selector shows the widget's own parameter. The first green run
  showed why: the module's parameter node outlives `setUp`'s scene clear, so the
  old assertion was reading `tmdMap` written by
  `test_parameterNodeStoresResultReferencesByID`, which runs just before it,
  not the declared default.
- Test support, not assertions: `_uc2EverDisplayed` joined
  `WIDGET_STATE_FIELDS`, and `setUp` and `tearDown` reset the link history of
  every link that has one rather than naming two.
- No safety test named in the test plan was modified.

### Regression guards observed failing against deliberate mutations

`scratchpad/run-mutations.ps1`: each mutation was applied to one production file,
the headful suite run, and the file restored from its original bytes and
verified by SHA-256 (`restored: True` for all four).

| Mutation | Test | Result |
| --- | --- | --- |
| reserved panels configured with empty text | `test_reservedPanelIsBlackWithStatedReason` | `AssertionError: '18948' not found in ''` and `'18949' not found in ''`, `FAILED (failures=2, skipped=1)` |
| `node.Modified(); connector.PushNode(node)` in `sendCaptureTrigger` | `test_capturePressSendsOneTrigger` | `AssertionError: 887980 != 887989 : A press modified the trigger node, which a real connector sends again`, `FAILED (failures=1, skipped=1)` |
| `findUc2Source(allowSimulated=True)` in `presentUc2` | `test_uc2LayerObeysOriginGateAndPrecedence` | `AssertionError: 'PASS' != 'WARN'`, `FAILED (failures=1, skipped=1)` |
| `Default(RESULT_MAP_TMD)` restored in the parameter node | `test_presentationParametersAndControls` | `AssertionError: 'tmdMap' != 'majorityVotingMap'`, `FAILED (failures=1, skipped=1)` |

### Required checks after the implementation

- `.\scripts\development\run-slicer-tests.ps1`: module loaded from
  `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`, `Ran 63 tests`,
  `OK (skipped=7)`, exit 0. The seventh skip is
  `test_reservedPanelIsBlackWithStatedReason`, which needs a window.
- `.\scripts\development\run-slicer-tests.ps1 -Headful`: `Ran 63 tests`,
  `OK (skipped=1)`, exit 0. The one skip is the no-main-window fallback test, as
  in the baseline.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21, both targets
  `All checks passed!`, exit 0.
- `git diff --check`: exit 0.
- Every changed path is in `Files allowed`. The card's move from `backlog/` to
  `active/` is staged, as the rename; nothing else is staged and nothing is
  committed.
- Interactive controls in the operator section: 9, down from 13. The camera
  index, camera-support install, result-map selector, result class and refresh
  controls are in the collapsed Developer section; the four per-link Connect and
  Disconnect buttons are gone.

### Not run, and why

- **Human project-owner sign-off for manual steps 1 to 8** remains pending. Codex
  performed a real headful Slicer run to exercise the table and recorded the
  observations above; that run does not replace the required human review.
- **The real OpenIGTLink connector in the automated suite.** The Source test
  target runs the base Slicer build, which has no `vtkMRMLIGTLConnectorNode`, so
  every connector in the automated tests is a test double. Manual step 4 did
  exercise the real connector and exposed the recorded STRING encoding failure;
  the required end-to-end capture acknowledgement therefore remains unverified.
- **`build-sliaflow.ps1` and `run-slicer-tests.ps1 -Target Build`** were run
  after the source checks; both the headless and headful compiled-copy suites
  passed. The real connector still required the manual run recorded below.
- **The UC2 panel by hand.** No UC2 producer exists until `SLIA-021`.

### Manual verification run, 2026-09-16

- The compiled launcher was rebuilt with
  `.\scripts\development\build-sliaflow.ps1`
  and exercised in a real headful Slicer window loaded from
  `C:\stratum\build\SLIAFlow`.
- Steps 1 to 3 and 8 were exercised with no producer, and steps 5 and 6 were
  exercised with the approved public recorded case `004-02` and the simulated
  acquisition path. The case folder was read-only; no case data was copied into
  the repository and no result image was captured without its visible banner.
- The local Slicer MCP bridge was used only for scene/UI inspection, controlled
  widget actions, and temporary screenshots. This use is recorded because the
  visual state could not be established from normal tests alone; it did not use
  private or identifiable medical data and it does not replace human manual
  verification.
- Step 4 exposed a real connector/stand-in interoperability failure: the
  `CaptureTrigger` STRING reached the stand-in but was rejected for an
  unsupported character encoding, so no capture status/reply arrived.
- Step 7 did not produce the required stale-link transition in this run after
  the producer processes were stopped. All producer processes and verification
  ports were cleaned up afterward.

### Defects found in manual verification, and their fixes

Four defects were found by the 2026-09-16 runs, all of them invisible to the
automated suite because every connector in it is a test double. Defects 1 to 3
came from the first run; defect 4 came from the rerun that verified them, which
showed defect 3 to have been only half of step 7's cause. Each fix was written
as a failing test first; the red runs are below.

**Defect 1 - the LiveView panel was black without saying why (step 2).** Every
other panel wrote its reason into the viewport; LiveView wrote its waiting state
only into the module's status line, so a panel that is black because nothing has
arrived looked exactly like one that is black because something broke. The panel
now carries `LIVE_WAITING_MESSAGE`, placed like the other waiting texts and
removed as soon as a frame binds, in both the camera and the stream path.

**Defect 2 - the capture trigger was refused for its encoding (step 4).**
`igtlioStringConverter::toIGTL` copies `vtkMRMLTextNode`'s encoding number
straight into the STRING message's encoding field, which carries an IANA MIB
character-set number. `vtkMRMLTextNode` defaults to `VTK_ENCODING_US_ASCII`, and
that VTK constant is **1**, which is not an IANA number; IANA 3 is US-ASCII. The
stand-in's pyigtl accepts only 3 and 106 and rejected every trigger, so no
capture ever started. The trigger node now declares
`IGTL_ENCODING_US_ASCII = 3` before it is registered, so a press still only
pushes. `CAPTURE` is pure ASCII, so 3 describes the bytes truthfully.

**Defect 3 - the link state never left `displaying` (step 7).** This is the
serious one. `_observeConnector` registered one callback for all six connector
events and `_onConnectorEvent` decided what had happened by comparing its
argument with the event ids. VTK passes the event to a Python observer as a
*string* (`vtkPythonCommand.cxx`: `Py_BuildValue("(Ns)", obj2, eventname)`), and
`vtkCommand::GetStringFromEventId` has no case for the connector's custom ids
(118944 and up), so all six arrive as `"NoEvent"`. The comparisons could never
match in a real Slicer, the loss branch was unreachable, and a stopped producer
left every label reporting `displaying`. The automated suite passed throughout
because it calls `_onConnectorEvent` directly with integers.

Each event now has its own callback, so which callback ran is what identifies
the event; the callbacks are built once per role and kept, because the
observation bookkeeping is keyed by the callback object. `_onConnectorEvent`
keeps its integer signature, so no existing test changed.

**Defect 4 - the loss of a link is the one event that link cannot deliver
(step 7).** Fixing the dispatch was necessary but not sufficient. The rerun
showed the connectors reaching `connecting` while the labels stayed
`displaying`, which means no event arrived at all. `igtlioConnector`'s receiver
thread sets `State = STATE_WAIT_CONNECTION` and then only *queues*
`DisconnectedEvent`, because it is not on the main thread
(`igtlioConnector.cxx`, `RequestInvokeEvent`). That queue is drained by
`ImportEventsFromEventBuffer`, which is reached only from `PeriodicProcess`, and
`vtkSlicerOpenIGTLinkIFLogic::CallConnectorTimerHander` skips every connector
whose state is not `StateConnected`. The state has already left `StateConnected`
by the time the 5 ms pump next runs, so the queued event is stranded and never
invoked. It is an ordering defect upstream, in code this card may not change,
and it strands precisely the events that report a link going away.

The panel therefore reads the connector's state itself, once a second, while any
link is up (`_pollLinkStates`). That state stays truthful throughout. A link
that has left `receiving` while the panel still claims `receiving`,
`displaying` or `invalid` is reported through `_onLinkDisconnected`, the same
path the event would have taken, so the retained image and its stale wording are
still decided in one place. `displaying` and `invalid` are treated as
refinements of a connected socket rather than disagreements with it, so a poll
never downgrades a live pane. The observers stay as the fast path for everything
they do deliver; the poll only catches what they cannot.

A smaller change came out of the first green run: `_sliceViewRenderer`
now returns `None` for a view that cannot supply a renderer instead of raising.
Writing text on a panel is a decoration, and failing to decorate must not take
down the presentation; where the text is a requirement rather than a decoration,
the reserved panel's reason, the caller still checks the return value and
refuses. No test was modified for it.

#### The four new tests, observed failing first

Run against the unchanged production code,
`.\scripts\development\run-slicer-tests.ps1`: `Ran 66 tests`,
`FAILED (failures=2, errors=1, skipped=7)`, exit 1. The other 63 passed.

| Test | Failure against the unfixed code |
| --- | --- |
| `test_connectorEventsSurviveVtkStringDispatch` | `AssertionError: 1 != 6 : Six events share one callback, so the event that fired is unknowable` |
| `test_captureTriggerDeclaresItsWireEncoding` | `AttributeError: module 'SLIAFlowLib.SLIAFlowParameterNode' has no attribute 'IGTL_ENCODING_US_ASCII'` |
| `test_liveViewPanelSaysWhatItIsWaitingFor` | `AssertionError: '' is not true : The LiveView panel is black with nothing written on it` |

`test_lostPeerIsNoticedWithoutADisconnectedEvent` was written after the rerun,
against code that already carried the first three fixes, and observed failing
the same way: `Ran 67 tests`, `FAILED (errors=1, skipped=7)`, exit 1, with
`AttributeError: 'SLIAFlowWidget' object has no attribute '_pollLinkStates'`.
The other 66 passed.

#### Checks after the fixes

- `.\scripts\development\run-slicer-tests.ps1`: `Ran 67 tests`, `OK (skipped=7)`,
  exit 0.
- `.\scripts\development\run-slicer-tests.ps1 -Headful`: `Ran 67 tests`,
  `OK (skipped=1)`, exit 0.
- `.\scripts\development\run-python-quality.ps1`: both targets
  `All checks passed!`, exit 0.
- `git diff --check`: exit 0.
- No safety test was modified, and no existing test was modified by these fixes.

#### Still not verified by automated tests

Defects 2, 3 and 4 are defects of the real connector, which no automated test in
this repository can exercise. Steps 2, 4 and 7 passed in the real Slicer reruns
recorded below. The automated test proves the panel acts on the state it reads;
it cannot prove that the real connector's state changes promptly when a producer
stops. The Step 7-only run measured that timing for this connector/build. If the
labels lag in a future environment, the remaining suspect is the connector's
own peer-loss detection latency, not the widget.

### Earlier manual verification rerun, 2026-09-16

- Rebuilt the compiled launcher with `.\scripts\development\build-sliaflow.ps1`
  and reran the real control path using public recorded case `004-02`.
- Step 4 passed: the trigger node declared IANA US-ASCII (`GetEncoding() == 3`);
  the UI showed `CAPTURING` and `READY`; two rapid presses yielded one new
  capture and `IGNORED capture 2 already in progress`. The acquisition log
  recorded one `CAPTURE` and one ignored trigger.
- Step 7 still failed: after the displayed recorded UC1 result was active under
  the simulated banner, producer listeners were stopped and the underlying
  connectors changed to `connecting`, but visible labels remained `displaying`
  or `receiving` for 20 seconds. No stale wording appeared. **This exposed
  defect 4:** the connectors' own state was correct throughout, so no
  `DisconnectedEvent` was ever delivered. Fixed by polling that state;
  re-verification pending.
- All producer processes, the Slicer process tree, and verification ports were
  cleaned up afterward.

- Step 2 also passed on rerun: the LiveView waiting message was present in the
  real panel annotation and the six-panel no-producer layout was restored.

### Manual verification rerun (Step 7 only), 2026-09-16

- Rebuilt the compiled launcher first with
  `.\scripts\development\build-sliaflow.ps1`.
- Used the approved public recorded case `004-02` only to establish the Step 7
  precondition: the genuine UC1 result was displayed with the visible simulated
  banner. Steps 2 and 4 were not repeated.
- Stopped only the verified listener processes for the acquisition/HSCube/control
  ports and the UC1 port. The acquisition/UC1 connector nodes reached
  `connecting` within about 2.4 seconds; the widget labels followed within about
  0.5 seconds and all five labels read `connecting`.
- The retained result changed to the required warning that the last valid result
  is still shown and is not being updated, within the 20-second observation
  window. No producer processes, Slicer processes, or verification listeners
  remained after cleanup.

## Review findings

Reserved for review.

## Human approval

Activated on 2026-09-15 under the project owner's instruction to start the next
task. `SLIA-022` was the only eligible `high` card, and it was blocked on
`ADR-0001`; the owner accepted the ADR, chose to keep each result in its own
panel with the overlay left to `SLIA-024`, and chose a single Connect links
control. Required again before completion.
