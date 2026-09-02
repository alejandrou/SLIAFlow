---
id: SLIA-010
title: Simulated result origin, demo mode, and simulated banner
status: completed
branch: feature/SLIA-010-simulated-result-origin
priority: high
depends_on: SLIA-006
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-010 - Simulated result origin, demo mode, and simulated banner

## Goal

Allow SLIAFlow to display an explicitly simulated UC1 result behind a transient
operator opt-in and an unmissable on-view banner, without weakening the genuine
result boundary established by SLIA-006.

## Context

No hyperspectral camera is available, so the acquisition and UC1 boxes must be
stood in for by separate processes (SLIA-011 to SLIA-013). Those stand-ins are
useless if SLIAFlow can only ever display `external-genuine` data.

`.ai/policies/medical-data-policy.md` allows synthetic and mock data and requires
only that "Outputs must clearly identify mock or demo data and must not imply
clinical validity". The roadmap's "never present a simulated result" rule and
that allowance reconcile in one way: the simulated data is produced **outside**
SLIAFlow by processes standing where the real components stand, and SLIAFlow
displays it only under an explicit, non-persisted operator opt-in with a
permanent visual marker.

Real-algorithm-on-synthetic-input is still `simulated`. A genuine PCA/SVM/KNN run
over an invented brain is not a genuine clinical result, so the origin gate stays
binary and hard-coded. What varies is only the banner's second line, carried by a
display-only detail attribute, so a viewer can tell "real UC1 pipeline, synthetic
input" from "arithmetic stand-in, not a classifier". Both are fake; they are not
equally fake.

This task adds no new file to `SLIAFlowLib/`. `build-sliaflow.ps1` SHA-256
verifies the deployed tree and hard-fails on anything absent from
`MODULE_PYTHON_SCRIPTS`, and `slicer_add_python_unittest` only sees what
`SLIAFlow.py`'s `__all__` re-exports. Everything fits the four existing package
files plus the `.ui`, so there is no CMake change.

## Requirements

- Add `RESULT_SOURCE_SIMULATED_ORIGIN = "simulated"`,
  `RESULT_SOURCE_DETAIL_ATTRIBUTE = "SLIAFlow.SimulationDetail"`, and
  `SIMULATED_BANNER_MESSAGE = "SIMULATED - NOT A GENUINE UC1 RESULT"` to the
  parameter-node module and re-export them through `SLIAFlowLib/__init__.py` and
  `SLIAFlow.py`'s `__all__`.
- Keep `isGenuineResultSource` behaviour and signature unchanged, with
  `RESULT_SOURCE_GENUINE_ORIGIN` hard-coded at its call site. Factor the shared
  matching logic into a private `_matchesResultSource(resultMap, node,
  requiredOrigin)` classmethod that carries the existing checks verbatim.
- Add `isSimulatedResultSource` delegating to the same private helper with the
  simulated origin constant. Do not merge the two into one public parameterised
  entry point.
- Add `findResultSource(resultMap, allowSimulated=False)` performing two passes
  in which a genuine source always wins over a simulated one. The default keeps
  every existing caller's behaviour identical.
- Thread the same `allowSimulated=False` default through
  `presentSelectedResult`.
- Extend `_resultReport` with `dataOrigin` and `simulationDetail` so the widget
  never re-reads MRML to decide banner state.
- Stamp `SLIAFlow.DataOrigin` on the presented result node and name simulated
  result nodes `SLIAFlow UC1 Result (SIMULATED)`. This is safe because
  `_ownedNode` matches on `SLIAFlow.Owner`, not on the node name.
- Leave `validateResultVolume` untouched: simulated data passes through the
  identical image contract. Provenance and validation stay orthogonal.
- Treat `SLIAFlow.SimulationDetail` as free text, display-only. Read it only when
  the origin is already `simulated`, sanitize it to a single line, and truncate
  it to about 80 characters before it reaches a `vtkTextActor`. It must never
  appear in any conditional that decides whether something is displayable.
- Add a `demoModeCheckBox` (unchecked by default, with no `SlicerParameterName`)
  and a red `simulatedBannerLabel` (`visible=false`) to the module UI, and rename
  the refresh button text to `Refresh Result`.
- Keep demo mode as transient widget state, defaulting to `False` and reset in
  `enter()`, `onSceneStartClose()`, and `cleanup()`. Do not add a `demoMode`
  field to the parameter-node wrapper.
- Draw the banner in the result slice view whenever a displayed result's origin
  is simulated, as **two** `vtkTextActor`s rather than one. A `vtkTextActor`
  carries a single `vtkTextProperty` for its entire string, so one actor cannot
  render a second line at a smaller font size. Use a primary actor at normalized
  viewport `(0.5, 0.94)` carrying `SIMULATED_BANNER_MESSAGE` in bold 16pt white
  on an opaque dark-red background with a white frame, centred and
  top-justified, and a secondary actor directly beneath it at `(0.5, 0.90)` in
  11pt on the same background carrying the truncated simulation detail. Create
  the secondary actor only when a detail string is present.
- Treat the pair as one unit. Both are added, removed and re-asserted together,
  so the detail line can never outlive the banner that qualifies it and the
  banner can never appear without the detail that was available to it.
- Remove both actors in `_clearResultView` and `_deactivatePresentation`, when
  demo mode is switched off, and whenever a genuine result is displayed.
  Re-assert both on every PASS refresh, because the slice view rebuilds actors.
- Prefix the panel result status with `SIMULATED: ` for a simulated result.

## Out of scope

- Any generation of result data inside SLIAFlow, including a "simulate" button.
- Networking, connectors, or OpenIGTLink of any kind.
- The simulator processes themselves (SLIA-011 to SLIA-013).
- Changing the SLIAFlow class palette to match UC1's; that disagreement is
  recorded separately and must not be fixed here, because it would change
  verified SLIA-006 behaviour under an unrelated card.
- Persisting demo mode or any simulated provenance into a saved scene.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/development/simulated_result_verification.md`
- `tasks/{backlog,active,review,completed}/SLIA-010-simulated-result-origin.md`

## Relevant skills and references

- `.ai/policies/medical-data-policy.md` - the mock-data allowance and the
  "must clearly identify mock or demo data" requirement this task implements.
- `.ai/policies/algorithm-boundary-policy.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- Existing `_showWaitingAnnotation` and `_removeWaitingAnnotation` actor handling
  in `SLIAFlowWidget.py` lines 505-550, which the banner reuses.
- Slicer `vtkTextActor`, slice-view renderer, and MRML node attribute APIs.

## Implementation plan

1. Add the three constants and their re-exports; show the import-level tests red
   first.
2. Extract `_matchesResultSource` from the existing `isGenuineResultSource` body
   verbatim, then reimplement `isGenuineResultSource` as a one-line delegation
   with the genuine constant hard-coded, and add `isSimulatedResultSource`.
3. Add the `allowSimulated` flag to `findResultSource` and
   `presentSelectedResult` as a defaulted-false, genuine-first two-pass search.
4. Extend `_resultReport` with `dataOrigin` and `simulationDetail`, and stamp the
   origin and the simulated node name in `presentResult`.
5. Extract the shared actor placement in the widget into
   `_placeAnnotationActor(...)`, keeping two separately named actor attributes
   rather than a dict, because `test_layoutContractAndLifecycle` reads
   `widget._waitingAnnotationActor` directly.
6. Add the two banner actors, their shared lifecycle removals, and the
   PASS-refresh re-assertion, driven only by `report["dataOrigin"]`.
7. Add the demo-mode checkbox and banner label to the `.ui`, wire the checkbox
   manually as transient state, and prefix the status text.
8. Write the manual verification snippet into
   `docs/development/simulated_result_verification.md` and update the contract
   document and roadmap.

## Acceptance criteria

- A simulated-origin source is never discovered or displayed while demo mode is
  off; the result pane stays black with the waiting status.
- With demo mode on, a contract-valid simulated source is displayed, and the
  panel status and source labels identify it as simulated.
- The red banner and its smaller detail line are drawn across the top of the
  result view and are both re-asserted on every PASS refresh, so a slice-view
  rebuild can never leave simulated data on screen unbannered.
- When both a genuine and a simulated source exist for the same map role, the
  genuine one is displayed and no banner appears.
- Simulated data is validated against the identical SLIA-006 image contract; a
  malformed simulated map is rejected exactly as a malformed genuine one is.
- `SLIAFlow.SimulationDetail` never affects discovery: a node carrying the detail
  attribute with `external-genuine` origin is still found with
  `allowSimulated=False`, and a node carrying the detail attribute with no origin
  is never found at all.
- Demo mode is not persisted; leaving and re-entering the module, or closing the
  scene, returns it to off with a black result pane.
- The presented result node carries the simulated origin attribute and the
  `(SIMULATED)` name when the source was simulated.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A simulated source is not discovered or displayed with demo mode off | `SLIAFlowTest.test_simulatedSourceIsNotGenuine` | automated; manual step 1 |
| A simulated source is displayed with demo mode on | `SLIAFlowTest.test_demoModeDiscoversSimulatedSource` | automated; manual step 2 |
| The simulated banner is shown and persists across refresh | `SLIAFlowTest.test_simulatedResultShowsPersistentBanner` | automated; manual steps 2 and 3 |
| Genuine wins over simulated for the same role | `SLIAFlowTest.test_genuinePreferredOverSimulated` | automated; manual step 4 |
| Simulated data passes through the identical image contract | `SLIAFlowTest.test_simulatedResultStillValidatedAgainstContract` | automated |
| The simulation detail never affects discovery | `SLIAFlowTest.test_simulationDetailNeverAffectsDiscovery` | automated; manual step 4 |
| Demo mode is not persisted | `SLIAFlowTest.test_demoModeIsNotPersisted` | automated; manual step 5 |
| Simulated provenance reaches the presented result node | `SLIAFlowTest.test_simulatedProvenanceReachesResultNode` | automated; manual step 2 |
| The module's own output is never rediscovered as a source | `SLIAFlowTest.test_presentedResultIsNotRediscoveredAsSource` | automated |
| A banner that cannot be drawn withholds the result | `SLIAFlowTest.test_bannerFailureWithholdsSimulatedResult` | automated (GUI session only) |

Tests to add or change, and how each one will be shown to fail first:

- Add `test_simulatedSourceIsNotGenuine`; before implementation it fails with
  `ImportError` for `RESULT_SOURCE_SIMULATED_ORIGIN`.
- Add `test_demoModeDiscoversSimulatedSource` and
  `test_genuinePreferredOverSimulated`; before implementation they fail with
  `TypeError` because `findResultSource` takes no `allowSimulated` argument.
- Add `test_simulatedResultStillValidatedAgainstContract`; before implementation
  it fails because no simulated source can reach `validateResultVolume` through
  the presentation path.
- Add `test_simulatedResultShowsPersistentBanner`, using the existing
  `_settleEventLoop()` plus `Modified()` pattern; before implementation it fails
  with `AttributeError` for the missing banner actor attribute.
- Add `test_demoModeIsNotPersisted`; before implementation it fails with
  `AttributeError` for `_demoModeEnabled`.
- Add `test_simulatedProvenanceReachesResultNode`; before implementation it fails
  because `presentResult` does not stamp `SLIAFlow.DataOrigin`.
- Add `test_simulationDetailNeverAffectsDiscovery`; before implementation it
  fails with `ImportError` for `RESULT_SOURCE_DETAIL_ATTRIBUTE`.
- Add `_demoModeEnabled` to `WIDGET_STATE_FIELDS` so the suite's widget-state
  backup and restore covers it.
- Add `test_presentedResultIsNotRediscoveredAsSource` and
  `test_bannerFailureWithholdsSimulatedResult` after the code review below;
  both fail against the first implementation of this task, the first with the
  presentation node matching as a genuine source and the second with the
  simulated map painted into the result view with no banner.
- Run the new tests against the pre-change module before implementing, and record
  the actual failure output in `## Completion evidence`.
- Run `run-python-quality.ps1` and `run-slicer-tests.ps1` after implementation.

## Manual verification

Perform verification in the Slicer executable configured in `config/local.json`,
with Developer Mode enabled and no private or identifiable medical data.

Create the simulated source through the approved developer verification path
documented in `docs/development/simulated_result_verification.md`, using the
Python console. This must not become a user-interface affordance.

    import numpy as np, slicer
    from SLIAFlowLib import (RESULT_MAP_TMD, RESULT_MAP_DEVICE_NAMES,
                             RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_SOURCE_ORIGIN_ATTRIBUTE,
                             RESULT_SOURCE_DEVICE_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN,
                             RESULT_SOURCE_DETAIL_ATTRIBUTE)
    device = RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD]
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", device)
    slicer.util.updateVolumeFromArray(node, np.linspace(0, 1, 64*64, dtype=np.float32).reshape(1, 64, 64))
    node.SetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_MAP_TMD)
    node.SetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN)
    node.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, device)
    node.SetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE, "arithmetic stand-in, not a classifier")

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | With the simulated node in the scene and demo mode unchecked, press Refresh Result | The right pane stays black and the status reads `WARN: Waiting for genuine UC1_TMD result.` | |
| 2 | Tick the demo mode checkbox | The gradient appears with a red banner reading `SIMULATED - NOT A GENUINE UC1 RESULT` across the top and `arithmetic stand-in, not a classifier` on a smaller second line; the panel status and source label both say SIMULATED | |
| 3 | Press Refresh Result again while demo mode stays on | The banner is still present and legible; it is not lost when the slice view rebuilds | |
| 4 | Set the node origin to `external-genuine`, untick demo mode, press Refresh Result | The map displays with no banner and a normal status, even though the detail attribute is still set | |
| 5 | Switch to Welcome and return to SLIAFlow | Demo mode is unchecked, the result pane is black, and the waiting status is shown | |

The `Result` column is empty because this procedure was not run, not because
any step failed. The task was closed with the owner's explicit approval on
that basis; see `## Human approval`.

## Risks

Widening `findResultSource` is the one change that could fail open, because it
scans every volume node in the scene; anything setting three string attributes
would then land in the result pane. The defaulted-false flag, the hard-coded
genuine constant at the `isGenuineResultSource` call site, and the refusal to
collapse the two entry points into one parameterised function all exist to keep
that boundary one deliberate argument away rather than one typo away.

A banner that can be lost on a view rebuild would silently present simulated data
as genuine, which is exactly the outcome the medical-data policy forbids; hence
the re-assertion on every PASS refresh and its own test.

Persisting demo mode would let a scene saved in demo mode reopen showing a
red/green tumour map with no memory of the opt-in, so the flag is deliberately
transient widget state at the cost of manual checkbox wiring.

## Documentation impact

- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: record the simulated
  origin value, the display-only `SLIAFlow.SimulationDetail` attribute, and the
  genuine-wins precedence rule.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: add SLIA-010 to the
  implementation order and state the simulated-display boundary.
- `docs/development/simulated_result_verification.md`: new, carrying the
  developer verification snippet above.

## Completion evidence

Branch: `feature/SLIA-010-simulated-result-origin`, committed as `c3902b2`
"ENH: Display externally simulated UC1 results under a banner". The branch
carried exactly one commit relative to `main`, needed no rebase because it was
already based on `13c9386`, and `main` was fast-forwarded onto it without a
merge commit.

### Files modified

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py` - the
  three constants.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py` and
  `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py` - re-exports.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py` -
  `_matchesResultSource`, `isSimulatedResultSource`, the two-pass
  `findResultSource`, `_simulationDetail`, the `dataOrigin` and
  `simulationDetail` report fields, and the origin stamp and rename in
  `presentResult`. `_resultReport` became a `classmethod` so it can reach
  `_simulationDetail` and `SIMULATION_DETAIL_MAX_CHARS`; every call site
  already used `cls.` or `self.`, so no call changed.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py` - transient demo
  mode, the banner actor pair, `_placeAnnotationActor` extracted from
  `_showWaitingAnnotation`, and the `SIMULATED: ` status prefix.
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui` - `demoModeCheckBox`,
  `simulatedBannerLabel`, and the `Refresh Result` button text.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py` - eight new tests,
  `_createSimulatedResultVolume`, and `_demoModeEnabled` in
  `WIDGET_STATE_FIELDS`.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md` - simulated origin,
  precedence, the display-only detail attribute, on-screen marking, and the
  orthogonality of provenance and validation.
- `docs/development/simulated_result_verification.md` - new.

`docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` needed no change: it
already carries SLIA-010 at position 7 of the implementation order and already
states the simulated-display boundary and the genuine-wins rule.

### Red first

The new tests were run against the pre-change module before the implementation
was accepted, by staging `HEAD` copies of the module beside the new test file
and loading that tree through `--additional-module-paths`.

With the module entirely unchanged, it does not load at all:

```text
File "...\SLIAFlowLib\SLIAFlowTest.py", line 8, in <module>
    from .SLIAFlowParameterNode import (
ImportError: cannot import name 'RESULT_SOURCE_DETAIL_ATTRIBUTE' from
'SLIAFlowLib.SLIAFlowParameterNode'. Did you mean: 'RESULT_SOURCE_DEVICE_ATTRIBUTE'?
Fail to instantiate module "SLIAFlow"
```

With only the new constants added - so the module loads and each test can fail
on its own reason - `Ran 26 tests ... FAILED (failures=2, errors=5, skipped=1)`:

```text
test_simulatedSourceIsNotGenuine                 AttributeError: 'SLIAFlowLogic' object has no
                                                 attribute 'isSimulatedResultSource'
test_simulatedResultStillValidatedAgainstContract AttributeError: ... 'isSimulatedResultSource'
test_simulationDetailNeverAffectsDiscovery       AttributeError: 'SLIAFlowLogic' object has no
                                                 attribute '_simulationDetail'
test_genuinePreferredOverSimulated               TypeError: findResultSource() got an unexpected
                                                 keyword argument 'allowSimulated'
test_simulatedProvenanceReachesResultNode        TypeError: presentSelectedResult() got an
                                                 unexpected keyword argument 'allowSimulated'
test_demoModeDiscoversSimulatedSource            AssertionError: 'WARN' != 'PASS'
test_demoModeIsNotPersisted                      AssertionError: unexpectedly None
                                                 (no demoModeCheckBox in the pre-change .ui)
test_simulatedResultShowsPersistentBanner        skipped, see below
```

A separate earlier run confirmed that adding `_demoModeEnabled` to
`WIDGET_STATE_FIELDS` fails every widget test at `setUp` on the pre-change
widget, which is why the per-test signatures above were obtained with that one
line removed from the staged copy.

### Green

```text
scripts\development\run-python-quality.ps1
  ruff 0.15.21 - All checks passed!

scripts\development\run-slicer-tests.ps1 -Target Source
  SLIAFlow module loaded from: C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py
  Ran 26 tests in 0.398s
  OK (skipped=1)
```

The runner passes `--no-main-window`, so `slicer.app.layoutManager()` is None
and `test_simulatedResultShowsPersistentBanner` skips itself - which would
leave the one safety-critical assertion of this card unproven. It was therefore
run once more against the same working tree with a real main window:

```text
Slicer.exe --testing --no-splash --disable-cli-modules
           --additional-module-paths C:/stratum/extensions/SLIAFlow/SLIAFlow
  Ran 26 tests in 2.141s
  OK
```

No skips. The banner test therefore genuinely executed: both actors present on
the result renderer with the expected strings, both still attached after the
slice node and composite node were modified and the view rebuilt, and both gone
from the renderer once demo mode was switched off.

### Not covered by automated tests

The `## Manual verification` table above was never filled in. Its `Result`
column is empty because the procedure was not run, not because it failed. The
GUI self-test run recorded above exercises the same banner behaviour as manual
steps 2 and 3 through the test suite, but it does not replace a human looking
at the rendered pane. See `## Human approval` for how this was closed.

## Review findings

An independent review of the working tree raised four findings, all of them
fixed before completion. They are recorded with their fixes in
`### Code review findings and fixes` below.

## Human approval

Approved for completion by the project owner on 2026-09-02, who moved this
card to `tasks/completed/` and authorized the commit and the fast-forward of
`main`.

The approval was given with the `## Manual verification` table unfilled. That
is an explicit owner decision, not an omission discovered later, and it is
recorded here so no reader mistakes the empty column for a passed check.

### Automated test evidence

`scripts/development/run-python-quality.ps1` - Ruff 0.15.21 over
`extensions/SLIAFlow/SLIAFlow`: `All checks passed!`

`scripts/development/run-slicer-tests.ps1`: `Ran 28 tests`, `OK (skipped=2)`.
The two skips are `test_simulatedResultShowsPersistentBanner` and
`test_bannerFailureWithholdsSimulatedResult`, both reporting
`This Slicer session has no layout manager`. The test runner is headless, so
there is no slice view to attach a banner to. Both are covered by manual
verification steps 2 and 3, and both run in a GUI Slicer session.

### Code review findings and fixes

An independent review of the working tree raised four findings. All four are
fixed and no code from this task is left as reviewed-but-unchanged.

| # | Finding | Fix |
| --- | --- | --- |
| 1 | Stamping `SLIAFlow.DataOrigin` on the presentation node made it satisfy every check in `_matchesResultSource`, so `findResultSource` could return the module's own output and re-present stale data as an external result | `_matchesResultSource` now rejects any node carrying `SLIAFlow.Owner`. A result source comes from outside SLIAFlow by definition |
| 2 | `_showSimulatedBanner`'s `False` return was discarded, so a result view with no renderer yet displayed and force-rendered the simulated map with no banner | `_updateSimulatedBanner` returns a bool, and `_refreshResultPresentation` withholds the result and reports `BANNER_UNAVAILABLE_STATUS` when the banner is required and cannot be drawn |
| 3 | The banner was updated after `_displayResultVolume` had already flushed the view, and removed the actors without a render, so a genuine result could stay painted under the SIMULATED banner and simulated data got one unbannered frame | The banner is asserted before the volume reaches the view, and `_updateSimulatedBanner` no longer renders. `_displayResultVolume` is the single flush, so the two states are never painted out of agreement |
| 4 | FAIL and WARN status text hard-coded the word "genuine", so the only lines naming a provenance named the wrong one for a simulated source | Added `RESULT_INVALID_SIMULATED_STATUS`, selected by the report's `dataOrigin`, and the logic WARN message now names the provenance actually being waited for (`genuine` or `genuine or simulated`) |

Finding 2's fix is deliberately narrower than "no renderer means fail". When
there is no result view at all, `_displayResultVolume` paints nothing either,
so nothing can be seen unbannered and the result is not withheld. The failure
guarded against is the one that was reported: the view is on screen and about
to receive the volume, and the banner cannot be attached to it.

## Carried forward

Manual verification of the banner in a GUI Slicer session remains outstanding.
The procedure is preserved in `docs/development/simulated_result_verification.md`
and stays runnable against the merged module at any time; `SLIA-014` is the
task that exercises this path end to end once the stand-in producers of
`SLIA-011` to `SLIA-013` exist.

SLIAFlow and UC1 disagree on the class palette: `_getOrCreateClassColorNode`
uses orange for class 3 and dark grey for class 4 where UC1 writes blue and
black. This was found during this task and is out of its scope; it is filed as
`SLIA-015`.
