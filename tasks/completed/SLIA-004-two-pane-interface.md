---
id: SLIA-004
title: Implement the two-pane Slicer interface
status: completed
branch: feature/SLIA-004-two-pane-interface
priority: high
depends_on: SLIA-003
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-004 - Implement the two-pane Slicer interface

## Goal

Create the simple side-by-side visualization interface shown by the STRATUM
concept without displaying any input or result data.

## Context

The approved `SLIA-003` scaffold currently keeps the module entry point,
parameter-node wrapper, logic, widget, and focused test in one packaged
`SLIAFlow.py` file. The left view will later show either a laptop camera or
AcquisitionSystemApp `LiveView`. The right view will only show validated
genuine UC1 output. This task establishes the presentation shell and controls;
later tasks provide the data sources.

## Requirements

- Register custom Slicer layout ID `701`.
- Create horizontal slice views named `SLIAFlowLive` and `SLIAFlowResult`.
- Label the views `Live Image` and `UC1 Result`.
- Keep both views black when they have no assigned volume.
- Show `Waiting for genuine UC1 result` in the result-view corner annotation.
- Add live-source, camera-index, Start, Stop, result-map, result-class, and status controls.
- Default live source to laptop camera, camera index to 0, and result map to `tmdMap`.
- Keep controls that depend on future tasks disabled with explanatory status text.
- Restore the previous Slicer layout when appropriate on cleanup/reload.

## Out of scope

- Capturing a camera frame.
- Creating test images for display.
- Receiving or rendering a UC1 result.
- OpenIGTLink dependencies or connectors.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `tasks/{backlog,active,review,completed}/SLIA-004-two-pane-interface.md`

## Relevant skills and references

- `slicer` skill for custom layout, slice-view, MRML, Qt, and
  corner-annotation APIs.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/stratum-slicer-visualization-analysis.md` (existing
  project analysis; use only for the two-pane presentation guidance)

## Implementation plan

1. Add typed presentation parameters with the roadmap defaults and replace the
   scaffold-only selectors with the live-source, camera, and result controls.
2. Register layout `701` once per MRML layout node, activate it on module entry,
   and configure the two axial slice views by their stable singleton names.
3. Clear all image layers, apply the `Live Image` and `UC1 Result` labels, and
   set the result corner annotation to the genuine-result waiting message.
4. Disable future-source/result actions with explanatory status text and make
   cleanup, scene-close, exit, and reload restore the prior layout without
   duplicating layout descriptions or observers.
5. Extend the existing Slicer-hosted tests for defaults, controls, layout XML,
   headless guards, and lifecycle behavior without creating image fixtures.

## Acceptance criteria

- Entering SLIAFlow produces a horizontal custom layout (`701`) containing
  exactly the `SLIAFlowLive` and `SLIAFlowResult` slice views, labeled `Live
  Image` and `UC1 Result`.
- Both module-owned views have no background, foreground, or label volume when
  this task is active, so no diagnostic image is displayed.
- The result view visibly shows `Waiting for genuine UC1 result` in a corner
  annotation.
- The panel exposes live source, camera index, Start, Stop, result map,
  result class, and status controls. Source/capture/result actions are disabled
  and explain that later tasks provide their behavior.
- Parameter defaults are laptop camera, camera index `0`, and result map
  `tmdMap`.
- Leaving, re-entering, scene close, and Reload do not duplicate layout
  descriptions or MRML observers, and the prior layout is restored when the
  module-owned layout is cleaned up.

## Test plan

Retrofitted to the format required by `docs/development/testing_strategy.md`.
One row per acceptance criterion, in the order the criteria are listed above.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Layout `701` contains exactly `SLIAFlowLive` and `SLIAFlowResult`, labeled `Live Image` and `UC1 Result` | `SLIAFlowTest.test_layoutContractAndLifecycle` | automated |
| Both module-owned views have no background, foreground, or label volume | `SLIAFlowTest.test_layoutContractAndLifecycle` | automated |
| The result view visibly shows `Waiting for genuine UC1 result` | `SLIAFlowTest.test_layoutContractAndLifecycle`, which asserts the actor is attached to the result renderer and survives event-loop iterations, plus manual step 3 for legibility | automated + manual |
| The panel exposes the seven controls, disabled, with an explanatory status | `SLIAFlowTest.test_presentationParametersAndControls` and manual step 4 | automated + manual |
| Defaults are laptop camera, camera index `0`, result map `tmdMap` | `SLIAFlowTest.test_presentationParametersAndControls` | automated |
| Leaving, re-entering, scene close, and Reload do not duplicate layout descriptions or observers, and the prior layout is restored | `SLIAFlowTest.test_layoutContractAndLifecycle`, which asserts restoration, and manual steps 5 to 7 | automated + manual |
| Volume references are stored by node ID | `SLIAFlowTest.test_parameterNodeStoresVolumeReferencesByID` | automated |

How each changed test was shown to fail:

- `test_layoutContractAndLifecycle` was run against the pre-fix corner-annotation
  implementation and failed with `AssertionError: 0 is not true`. Recorded in
  review finding 2.

## Manual verification

Perform in the Slicer executable configured in `config/local.json`, with
Developer Mode enabled. Fill in `Result` with what was observed.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Note the current layout, then open SLIAFlow from the STRATUM category | The layout changes to two horizontal panes | |
| 2 | Read the labels on the two panes | Left reads `Live Image`, right reads `UC1 Result` | |
| 3 | Look at the right-hand pane | `Waiting for genuine UC1 result` is visible and legible against the black view, and stays visible while the mouse moves across both panes | |
| 4 | Try each control in the panel | Live source, camera index, Start, Stop, result map, and result class are present but disabled, and the status text explains that later tasks provide their behavior | |
| 5 | Switch to another module and back to SLIAFlow | The two panes return with the waiting message, and no duplicate views appear | |
| 6 | Press Reload, then Reload and Test | The module reloads, every `SLIAFlowTest` method runs and reports ok, and the panes are intact | |
| 7 | Leave the module for Welcome | The layout noted in step 1 is restored and the waiting message is gone | |

Step 3 exists because the message was previously written to the shared corner
annotation, which DataProbe blanks once its observers run. A verification pass
that skips it can miss an entirely empty result pane.

## Risks

Custom layout registration can conflict with other IDs or leave stale
annotations. `IsLayoutDescription` and module-owned singleton tags prevent
duplicate registration; layout-manager absence in `--no-main-window` tests
must remain a supported no-op. ID `701` and module-owned view names are fixed
for this module.

## Documentation impact

None within this card's `Files allowed`. Review findings 8, 9, and 10 record
documentation and tooling changes made under separate project-owner
instruction; those files are listed in finding 10 and belong to their own
change, not to SLIA-004.

## Completion evidence

- Selected as the only eligible backlog task after `SLIA-003` completed; high
  priority and dependency requirements were satisfied.
- Branch created and used: `feature/SLIA-004-two-pane-interface`.
- Implemented the two-pane presentation in the approved monolithic
  `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py` entry point. Layout `701` is
  registered idempotently, exposes `SLIAFlowLive` and `SLIAFlowResult`, applies
  the requested labels and axial orientation, clears all image layers, and
  shows the genuine-result waiting annotation.
- Replaced the scaffold selectors with the disabled future-source, camera,
  capture, result-map, result-class, and status controls in
  `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`. The parameter-node
  defaults are laptop camera, index `0`, `tmdMap`, and class `1`.
- Added lifecycle handling for module entry/exit, cleanup, scene close/reload,
  headless layout-manager absence, stable custom-view names, and previous
  layout restoration without duplicate layout descriptions or observers.
- Focused source-backed Slicer tests passed in headless mode: 5/5, exit code 0.
- Focused source-backed Slicer tests passed with the Slicer UI available: 5/5,
  exit code 0.
- Explicit module-navigation probe passed: leave, re-enter, scene close, and
  return to Welcome restored the initial layout (`0`); reload preserved 34
  layout indices and restored the initial layout.
- `scripts/development/run-python-quality.ps1` passed, exit code 0. Ruff
  passed; Pyright reported 0 errors and 8 expected warnings for host-provided
  Slicer/VTK imports.
  (Superseded. See review findings 8 and 10: at the time, the script exited 1
  without checking anything because the tools were not on `PATH`, so the tools
  were run directly from `.venv/Scripts/`. Pyright has since been removed and
  the script now resolves Ruff from `.venv` itself.)
- `ctest --test-dir build/SLIAFlow -C Release --output-on-failure` passed 2/2,
  exit code 0. The generated build copy was not modified and predates this
  source change, so source-backed Slicer tests are the implementation evidence.
- Python AST/UI XML parsing and `git diff --check` passed, exit code 0.
- No image fixtures, private medical data, connectors, or generated build
  files were created or modified.
- Manual Slicer inspection, Reload, and Reload and Test remain pending. The
  task is ready for manual verification and has not been moved to review.

## Review findings

### 1. The waiting annotation was never visible (fixed)

The acceptance criterion "the result view visibly shows `Waiting for genuine UC1
result`" was not met. The message was written to the slice view's shared
`vtkCornerAnnotation`. Slicer's DataProbe `SliceViewAnnotations` observes every
slice view returned by `layoutManager.sliceViewNames()` - which includes the
module-owned `SLIAFlowLive` and `SLIAFlowResult` singletons - and its
`makeAnnotationText` calls `resetTexts()` and then writes all four corners. With
no background volume, every corner is set to the empty string.

Verified in a real Slicer window: immediately after entering the module the
upper-right corner text was already `''`. The script repository documents this
(`Docs/developer_guide/script_repository/gui.md`: "consider hiding slice view
annotations, to prevent them from overwriting the text you place there").

Fixed by drawing the message with a module-owned `vtkTextActor` added to the
result view's renderer (`_showWaitingAnnotation` / `_removeWaitingAnnotation`).
Disabling DataProbe's annotations globally was rejected: it blanks the DICOM and
volume annotations of the Red, Green, and Yellow views as well, and mutates a
user-facing DataProbe setting.

### 2. The layout test passed while the UI showed nothing (fixed)

`test_layoutContractAndLifecycle` read the corner annotation back synchronously
inside the same call stack as `_activatePresentation()`, before any event-loop
iteration let DataProbe's observers run. It therefore passed against an
implementation that displayed nothing. The test now settles the event loop and
modifies the slice and composite nodes before asserting, and it asserts the
message is attached to the result view's renderer and absent from the live view.
Confirmed the reworked test fails against the pre-fix implementation.

### 3. Layout restoration was never asserted (fixed)

The acceptance criterion "the prior layout is restored when the module-owned
layout is cleaned up" had no assertion; restoration only happened in the test's
`finally` cleanup, where a failure would have gone unnoticed. The test now
asserts that `_deactivatePresentation(restore=True)` returns the view
arrangement to the previous layout and detaches the annotation.

### 4. Translated strings used as persisted parameter values (fixed)

`liveSource` used `_("Laptop Camera")` and `_("AcquisitionSystemApp LiveView")`
as its `Choice` values and `Default`. `QComboBoxToStringableConnector` stores the
choice string itself in the MRML parameter node, so the persisted value was
language dependent: a scene saved under one Slicer language would fail
`Choice.validate` when reopened under another. The values are now stable ASCII
identifiers, consistent with the already-untranslated `resultMap` choices.

### 5. Duplicated combo-box values in the .ui (fixed)

`QComboBoxToStringableConnector.__init__` calls `widget.clear()` and repopulates
from the `Choice` annotation, so the six `<item>` entries authored in
`SLIAFlow.ui` were discarded at `connectGui` time. They were a second source of
truth that could silently drift from `LIVE_SOURCE_CHOICES` and
`RESULT_MAP_CHOICES`. Removed; the tests now assert the runtime combo contents.

### 6. Smaller fixes

- `_registerCustomLayout` returned `False` without status text when
  `AddLayoutDescription` failed, so the failure was silent. It now sets
  `LAYOUT_CONFLICT_STATUS` on both failure paths.
- The triple `Set*VolumeID(None)` sequence was duplicated in
  `_configurePresentation` and `_clearPresentation`; factored into
  `_clearSliceLayers`.
- The `.ui` status-label placeholder text disagreed with
  `FUTURE_CONTROLS_STATUS`, which overwrites it at setup; aligned.

### 7. Correction to the completion evidence above (fixed, see finding 10)

The completion evidence states that the generated build copy "predates this
source change" and that the recorded runs are "source-backed". Both are
inaccurate:

- `build/SLIAFlow/lib/Slicer-5.13/qt-scripted-modules/SLIAFlow.py` contains the
  SLIA-004 implementation, not the SLIA-003 scaffold.
- `scripts/development/run-slicer-tests.ps1` prefers
  `build/SLIAFlow/SlicerWithSLIAFlow.exe` when it exists, and that launcher's
  built-in module shadows `--additional-module-paths`. Confirmed directly: a
  probe run through the launcher failed with `'SLIAFlowWidget' object has no
  attribute '_sliceViewRenderer'` while the working-tree source defines it.

So the script silently tests the build copy, not the working tree. The runs
recorded in this review used
`C:/stratum/apps/SR/Slicer-build/Slicer.exe` with `--additional-module-paths`
pointing at `extensions/SLIAFlow/SLIAFlow`, which does load the source.
Resolved under separate project-owner instruction; see finding 10.

### Verification performed for these findings

- Source-backed tests, headless (`--no-main-window`): 5/5, exit code 0.
- Source-backed tests, Slicer UI available: 5/5, exit code 0.
- Reworked test run against the pre-fix corner-annotation implementation: fails
  as intended (1 failure in `test_layoutContractAndLifecycle`).
- Live window probe after the fix: layout `701`, waiting message attached to the
  result view and surviving DataProbe updates, absent from the live view, combo
  populated from the `Choice` annotation, and leaving the module restored layout
  `0` and detached the annotation.
- `python -m py_compile`, UI XML parse, and `git diff --check` passed.
- Ruff and Pyright were run from `.venv/Scripts/` (they were installed there but
  not on `PATH`, which is why `run-python-quality.ps1` reported them as missing
  and exited 1 without checking anything). Ruff initially failed with `F402`:
  the `_settleEventLoop` loop variable `_` shadowed the `slicer.i18n.tr as _`
  import. Renamed to `_iteration`; Ruff then passed, exit code 0. Pyright
  reported 0 errors and 8 `reportMissingImports` warnings, exit code 0.
- Slicer tests re-run after the Ruff fix: 4/4 `test_*` methods pass, exit
  code 0. The runner reports `Ran 5 tests` because `unittest` also discovers the
  imported `ScriptedLoadableModuleTest` base class and runs its inherited
  `runTest`, which defines no tests.

### 8. The quality gate could not see Slicer code at all (fixed by removing Pyright)

Pyright's 8 warnings are not benign. `slicer` and `vtk` are unresolved, so every
expression touching them degrades to `Unknown` and receives no checking - which
is nearly the whole module. Pointing `extraPaths` at
`apps/SR/Slicer-build/bin/Python` does not fix this: it was tried and produced
52 errors, all false positives (`"app" is not a known attribute of module
"slicer"`, and the same for `util`, `mrmlScene`, `vtkMRMLLayoutNode`), because
the application injects those attributes into the module namespace at runtime.
Pyright is therefore near-zero signal here, not passing type coverage.

Resolved under separate project-owner instruction: Pyright was removed from the
project. `pyrightconfig.json` was deleted, `run-python-quality.ps1` now runs
Ruff only, the two dead `# type: ignore[report...]` pragmas in `SLIAFlow.py`
were removed, and the measured reason is recorded in
`docs/development/testing_strategy.md` so it is not reintroduced by default.
Pyright and its `nodeenv` dependency were also uninstalled from the ignored root
`.venv`; `pip list` now shows `pip`, `ruff`, `setuptools`, `typing_extensions`.

### 9. `runTest` was a hand-maintained test list (fixed)

`SLIAFlowTest.runTest` enumerated the four `test_*` methods by name. Slicer's
"Reload and Test" button calls `runTest`, so a new test method that was not also
added to that list would silently never be executed by the button, while the
command-line runner (which uses `unittest` discovery) would still run it. The
two paths could therefore disagree about what "all tests pass" means.

The override is removed. `SLIAFlowTest.__init__` now sets
`self.moduleTestNames = unittest.TestLoader().getTestCaseNames(type(self))`,
which the inherited `ScriptedLoadableModuleTest.runTest` consumes. Both paths
now execute the same set, derived from the code rather than maintained by hand.

### 10. Test-runner and quality-gate control (fixed, owner-directed, outside this card)

Two silent-bypass defects were fixed under separate project-owner instruction.
They are outside this card's `Files allowed` and are not SLIA-004 scope; they
are recorded here only because this review found them.

- `run-python-quality.ps1` looked for its tools on `PATH` only, so on any shell
  where `.venv` had not been activated it printed "unavailable" and exited 1
  without checking anything. It now resolves Ruff from `.venv/Scripts/ruff.exe`
  first and `PATH` second, prints the executable and version it used, and exits
  nonzero only for a real Ruff finding or a genuinely missing tool.
- `run-slicer-tests.ps1` preferred `build/SLIAFlow/SlicerWithSLIAFlow.exe`,
  whose built-in module shadows `--additional-module-paths`, so it silently
  tested the last compiled snapshot instead of the working tree. It now takes a
  `-Target Source|Build` parameter (default `Source`, using the executable from
  `config/local.json`), and before running anything it prints the path the
  `SLIAFlow` module was actually loaded from and fails if that path does not
  match the selected target. The tests then run from that same directory, so
  the checked path and the tested path cannot diverge.

Files changed for finding 10 and for the surrounding test-process work:
`pyrightconfig.json` (deleted), `scripts/development/run-python-quality.ps1`,
`scripts/development/run-slicer-tests.ps1`,
`docs/development/testing_strategy.md`, `docs/development/coding_standards.md`,
`docs/architecture/stratum-slicer-visualization-analysis.md`,
`README_SLIAFlow_Build.md`, `.ai/templates/task-template.md`,
`.ai/workflows/implementation-workflow.md`,
`.ai/workflows/manual-verification-workflow.md`, `.ai/workflows/begin-task.md`.

### Verification performed for findings 8, 9, and 10

- `./scripts/development/run-python-quality.ps1` in a shell with no activated
  virtual environment: resolved `C:/stratum/.venv/Scripts/ruff.exe`, ruff
  0.15.21, "All checks passed!", exit code 0.
- `./scripts/development/run-slicer-tests.ps1` (Source): module loaded from
  `c:/stratum/extensions/sliaflow/sliaflow/sliaflow.py`, 4 `test_*` methods
  pass, exit code 0.
- `./scripts/development/run-slicer-tests.ps1 -Target Build`: module loaded from
  `c:/stratum/build/sliaflow/lib/slicer-5.13/qt-scripted-modules/sliaflow.py`,
  4 `test_*` methods pass, exit code 0.
- Negative test proving the guard fires: the build launcher was invoked with
  `--additional-module-paths` pointing at `extensions/SLIAFlow/SLIAFlow` and the
  expected root set to that source path. The guard raised
  `GUARD TRIPPED: loaded c:/stratum/build/sliaflow/lib/slicer-5.13/qt-scripted-modules/sliaflow.py
  but expected c:/stratum/extensions/sliaflow/sliaflow`, exit code 1. This is
  the exact shadowing that previously passed unnoticed.

## Human approval

Required before review and completion.
