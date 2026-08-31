---
id: SLIA-006
title: Present genuine UC1 result volumes
status: active
branch: feature/SLIA-006-genuine-result-presentation
priority: high
depends_on: SLIA-005
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-006 - Present genuine UC1 result volumes

## Goal

Validate and display genuine UC1 result volumes already present in the MRML
scene, without adding networking or generating result data.

## Context

This task establishes the result-display boundary before OpenIGTLink is added.
The operator/demo workflow must never expose generated test fixtures.
The current `main` implementation is a monolithic scripted-module entry point;
the package files documented by the repository are not present on `main`. The
existing camera and two-pane behavior must therefore be moved behind the
package entry point while this result boundary is added.

## Requirements

- Support `tmdMap`, majority-voting class, majority-voting probability, SVM probability, and KNN probability selections.
- Default to `tmdMap` and expose class selection only for four-component SVM/KNN maps.
- Use stable map keys in the parameter node and map them to the exact producer
  device names `UC1_TMD`, `UC1_MV_CLASS`, `UC1_MV_PROB`, `UC1_SVM_PROB`, and
  `UC1_KNN_PROB`.
- Discover UI-selectable sources only when an MRML volume carries the exact
  `SLIAFlow.ResultMap` role and `SLIAFlow.DataOrigin=external-genuine`
  attributes. Do not add a generic volume picker or a mock/result-fixture
  option to the normal module UI.
- Require positive image dimensions and finite values.
- Require `float32` values in `[0,1]` for probability maps.
- Require one-component `uint8` values in `{1,2,3,4}` for the class map.
- Require four components for SVM/KNN maps and display the selected class component through a module-owned transient scalar volume.
- Apply continuous colour presentation to probability maps and a discrete four-class presentation to the class map.
- Store source and display node IDs in the parameter node; display and colour
  resources must be module-owned and not saved with the scene.
- Reject invalid data before assigning it to the result view.
- Leave the view black and display a clear waiting/invalid status when no valid genuine result is selected.

## Out of scope

- Deriving or normalizing any UC1 map in Slicer.
- OpenIGTLink connectors.
- Overlaying result data on the camera view.
- Persisting or reporting diagnostic conclusions.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-006-genuine-result-presentation.md`

## Relevant skills and references

- Slicer MRML volume, display-node, NumPy, and colour-node APIs.
- `docs/slicer/scripted_module_structure.md`
- `.ai/policies/algorithm-boundary-policy.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `C:\Users\AlejandroHerrera\.codex\skills\slicer-skill\slicer-source\Base\Python\slicer\util.py`

## Implementation plan

1. Move the existing camera/layout implementation behind the documented
   `SLIAFlowLib` package and keep the entry point limited to metadata/exports.
2. Define map descriptors, producer attributes, and strict validation in the
   logic layer without mutating the scene during validation.
3. Add the result-role selector, source/status display, refresh action, and
   conditional SVM/KNN class control to the widget.
4. Create/reuse module-owned transient scalar display and colour resources,
   copy only validated data, and assign the display node only to the result
   slice view.
5. Add focused in-memory synthetic fixtures that are called directly by tests
   and are never listed by the normal module UI.
6. Document the producer/consumer contract and the exact validation boundary.

## Acceptance criteria

- Each of the five supported valid map types can be displayed in the right pane,
  with probability maps using continuous colour presentation and the class map
  using a discrete four-class presentation.
- Invalid maps are rejected before display and cannot be reported as success;
  validation accepts only positive dimensions, the required scalar type and
  component count, finite values, and the required value range/classes.
- SVM/KNN class selection changes only the selected genuine probability
  component and persists the source/display node IDs by MRML reference.
- No test or simulated result is selectable through the normal user interface;
  only contract-marked external-genuine source nodes are discovered.
- Missing data restores the black result view and a clear waiting/invalid
  status without changing the live pane.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Each supported valid map type displays with the required colour presentation | `SLIAFlowTest.test_resultPresentationForSupportedMapTypes` | automated; manual steps 5-6 |
| Invalid maps are rejected before display and cannot be reported as success | `SLIAFlowTest.test_resultValidationRejectsMalformedMaps` and `SLIAFlowTest.test_invalidResultLeavesResultViewEmpty` | automated; manual step 7 |
| SVM/KNN class selection extracts only the selected component and stores source/display IDs | `SLIAFlowTest.test_vectorProbabilityClassSelection` and `SLIAFlowTest.test_parameterNodeStoresResultReferencesByID` | automated; manual step 6 |
| The normal UI discovers no unmarked test/simulated result | `SLIAFlowTest.test_resultSourceDiscoveryRequiresGenuineMarker` | automated; manual step 4 |
| Missing data restores a black waiting/invalid result state without changing the live pane | `SLIAFlowTest.test_missingResultRestoresWaitingState` | automated; manual steps 3 and 7 |

Tests to add or change, and how each one will be shown to fail first:

- Add `test_resultPresentationForSupportedMapTypes`; before implementation it
  fails because result presentation and the fifth map choice do not exist.
- Add `test_resultValidationRejectsMalformedMaps`; before implementation it
  fails with `AttributeError` for the missing validation method.
- Add `test_invalidResultLeavesResultViewEmpty`; before implementation it fails
  because the result refresh/clear path does not exist.
- Add `test_vectorProbabilityClassSelection` and
  `test_parameterNodeStoresResultReferencesByID`; before implementation they
  fail because component extraction and the source/display references are not
  implemented.
- Add `test_resultSourceDiscoveryRequiresGenuineMarker`; before implementation
  it fails because there is no contract-filtered source discovery path.
- Add `test_missingResultRestoresWaitingState`; before implementation it fails
  because the widget has no result refresh state transition.
- Run the new tests against the pre-change module before implementing the result
  behavior and record the actual failure output in `## Completion evidence`.
- Run the Python quality script and source-backed Slicer tests after
  implementation; CTest is run only if the compiled extension is refreshed.

## Manual verification

Perform verification in the Slicer executable configured in `config/local.json`,
with Developer Mode enabled and no private or identifiable medical data. Use
only approved synthetic fixtures through the automated test runner. Do not add
a test fixture through the normal result UI.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Note the current layout and open SLIAFlow from the STRATUM category | The two-pane presentation opens with `Live Image` on the left and `UC1 Result` on the right | |
| 2 | Press Reload, then Reload and Test | The module reloads cleanly and every `SLIAFlowTest.test_*` method reports `ok` | |
| 3 | With no externally supplied result node, inspect the right pane | It remains black and shows `Waiting for genuine UC1 result`; the live pane is unchanged | |
| 4 | Inspect the result controls and try the map selector while no contract-marked source exists | The selector exposes exactly the five approved map roles, no generic volume picker exposes fixtures, and the status reports missing data rather than success | |
| 5 | When an approved external-genuine `UC1_TMD` source is available in the scene, select `tmdMap` and refresh | The validated source appears in the right pane with continuous probability colouring; the source label/status identifies it and the live pane is unchanged | |
| 6 | When approved external-genuine class, SVM, and KNN sources are available, select each role and change the class for SVM/KNN | The class map uses four discrete colours; SVM/KNN show only the chosen component and changing class does not alter the source node or live pane | |
| 7 | Present an unmarked, malformed, or missing source through the approved developer verification path | The right pane stays black, the status clearly reports waiting/invalid data, and no invalid node ID is assigned to the result view | |
| 8 | Leave SLIAFlow for Welcome | The layout noted in step 1 is restored and no SLIAFlow result display remains visible | |

## Risks

Incorrect component or range handling could make malformed output look valid.
Validation occurs before scene display state is changed. The explicit producer
marker is a provenance contract, not cryptographic authentication; the external
producer remains responsible for labeling genuine data correctly.

## Documentation impact

Add `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md` with the exact map keys,
device names, MRML producer attributes, array shapes/types, value constraints,
class meanings, source/display ownership, and the non-clinical boundary.

## Completion evidence

Task selected: `SLIA-006` was the next eligible high-priority backlog task
because its dependency `SLIA-005` is complete and no other task was active or
under review.

Branch: `feature/SLIA-006-genuine-result-presentation`, created from `main`.

Files inspected:

- `AGENTS.md`, the task lifecycle and implementation workflows, applicable
  policies, the SLIAFlow roadmap, scripted-module structure guidance, current
  SLIAFlow source/UI/CMake, and the configured Slicer source APIs.

Files created:

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`

Files modified:

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- this task card, moved from `tasks/backlog/` to `tasks/active/`

Implementation summary:

- Moved the existing camera and two-pane layout behavior behind the
  `SLIAFlowLib` package and kept the entry point limited to metadata/exports.
- Added five stable result roles, exact UC1 device mapping, strict image
  validation, exact external-genuine provenance discovery, one-based SVM/KNN
  component selection, and MRML source/display references.
- Added transient module-owned scalar, continuous probability, and discrete
  class presentation resources; invalid or missing results clear the right
  pane without changing the live pane.
- Added the result selector, source/status display, refresh action, and
  conditional class control without adding a generic volume picker or test
  fixture to the normal UI.

Fail-first evidence collected before implementation:

- `.\scripts\development\run-slicer-tests.ps1` exited `1` with
  `Ran 17 tests`, `FAILED (errors=7)`. The seven new test entry points failed
  with `AttributeError` because `supportedResultMaps`,
  `validateResultVolume`, `presentResult`, `extractSelectedResultComponent`,
  `resultReferenceNames`, `findResultSource`, and
  `presentSelectedResult` were not present in the pre-change logic.

Validation after implementation:

- `.\scripts\development\run-python-quality.ps1` — PASS, exit code `0`.
- `.\scripts\development\run-slicer-tests.ps1` — PASS, exit code `0`;
  all 16 `SLIAFlowTest.test_*` tests passed.
- `git diff --check` — PASS; only expected Git line-ending warnings were
  emitted.

Unavailable or skipped checks:

- CTest was not run because the compiled extension was not refreshed; the
  source-backed Slicer runner was used for this Python scripted-module change.
- Manual Slicer verification is pending and must follow the table above with
  Developer Mode enabled and approved synthetic fixtures only.

Status: implementation and fast automated tests are complete; the task is
ready for project-owner manual verification. It is not marked review or
completed.

## Review findings

Branch review performed against the requirements and acceptance criteria above.
Five defects were found and fixed on this branch; all are covered by tests that
were shown to fail against the pre-review code.

1. Probability maps rendered with an empty colour ramp. A
   `vtkMRMLProceduralColorNode` is constructed with an empty
   `vtkColorTransferFunction`, never a null one, so the guard
   `if colorNode.GetColorTransferFunction() is None:` never fired and the
   SLIAFlow ramp was never written. Observed as `0 != 5` transfer-function
   points. Fixed by writing the ramp into the existing function.
2. The contract value range never reached the slice pipeline. A scalar volume
   is displayed through window/level, not through the display node scalar
   range, so `SetScalarRange`/`SetScalarRangeFlag` had no display effect and
   the default automatic window/level stretched each genuine map to its own
   extrema. Fixed with `SetAutoWindowLevel(False)` plus
   `SetWindowLevelMinMax`, pinned to `[0,1]` and `0-4`.
3. A class left over from an SVM/KNN selection rejected valid single-component
   maps. Selecting class 3 for `svmProbability` and then switching to `tmdMap`
   reported `FAIL - The selected UC1 result component could not be extracted`
   for genuine, contract-valid data. The class is now ignored for
   single-component maps.
4. The result display node was saved with the scene, contrary to the
   module-owned transient-resource requirement and to the contract document.
5. `presentResult` reported the volume node ID as `displayNodeID`. The report
   now carries `resultNodeID` and the real display node ID.

Smaller changes: `_configureFutureControls` renamed to
`_configureResultControls` because the controls are no longer future work, and
`_onResultSelectionChanged` no longer dereferences `self.logic` without a
guard.

Tests added: `test_singleComponentMapIgnoresStaleClassSelection` and
`test_classControlOnlyForVectorProbabilityMaps` (the SVM/KNN-only class control
was previously untested). `test_resultPresentationForSupportedMapTypes` now
asserts the transfer function, window/level range, interpolation, and
`SaveWithScene`; `test_parameterNodeStoresResultReferencesByID` asserts the
reported node IDs.

Open point for the project owner: the fail-first evidence above records
`Ran 17 tests` before implementation, but the suite has 16 test methods at that
point (9 pre-existing plus 7 added). The count should be reconciled before this
card moves to review.

Validation after the review fixes:

- `.\scripts\developmentun-python-quality.ps1` - PASS, exit code `0`.
- `.\scripts\developmentun-slicer-tests.ps1` - PASS, exit code `0`;
  `Ran 18 tests`, `OK`.
- Fail-first evidence for the review fixes, collected by reverting each fix in
  place and re-running the suite: `test_resultPresentationForSupportedMapTypes`
  failed with `AssertionError: 1 is not false` (SaveWithScene), then
  `AssertionError: 1 is not false` (AutoWindowLevel), then
  `AssertionError: 0 != 5` (transfer-function points);
  `test_singleComponentMapIgnoresStaleClassSelection` failed with
  `AssertionError: 'FAIL' != 'PASS'`.

Manual Slicer verification in the table above is still pending and is still
required, in particular steps 5 and 6, which are the ones the colour and
window/level defects affected.

## Human approval

Required before review and completion.
