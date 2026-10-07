---
id: SLIA-039
title: Remove what the old inputs left behind
status: active
branch: feature/SLIA-039-remove-old-input-leftovers
priority: medium
depends_on: SLIA-038
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004, ADR-0005]
---

# SLIA-039 - Remove what the old inputs left behind

## Goal

Nothing in the module, its tests, its scripts or its documentation exists only
for the 93-band HSI Human Brain Database cases. What stays is what 002-04 and
the cube received from IUMA's app need.

## Context

*Created on 2026-10-07 during `SLIA-038`.* The owner asked what to do with tests
tied to the old inputs and their ground truth, and decided that nothing useless
is to be left in the project: old-input leftovers are removed, in one task, after
`SLIA-038`.

What was found on 2026-10-07:

- **The ground-truth overlay can no longer appear.** `ADR-0004` decision 8 offers
  `gtMap` only for a cube with a `gtMap` beside it. `002-04` has none, the cube
  received from the app has none, and SLIAFlow does not read `020-01`. The
  overlay still has code in `SLIAFlowCube.py`, `SLIAFlowLogic.py`,
  `SLIAFlowWidget.py`, `SLIAFlowUc1Input.py`, `SLIAFlowParameterNode.py` and the
  tooltip in `SLIAFlow.ui`, and about 14 tests. None of those tests reads
  `input/`: they write placeholder `gtMap` files.
- **`test_moduleHasNoCasePool`** only checks that the case pool retired in
  `SLIA-031` has not come back.
- **Documents still describe removed commands and folders.** `input\bin\bin`,
  `run-uc1-real.ps1` and `python -m stratum_sim uc1-real` / `uc2-real` no longer
  exist, but appear in `pipeline_test_quickstart.md`, `end_to_end_verification.md`,
  `uc1_local_build.md`, `uc2_local_build.md`, `uc1_demo_runbook.md` and
  `WP5_MS5_DEMO_PLAN.md`.
- **The build checks lean on `020-01`.**
  - `check-uc1.py` never runs UC1 on 002-04. It proves the patches leave UC1
    unchanged on `020-01`, and exercises the float32 path and the equal bands of
    the LCTF band mapping on `020-01` rewritten as float32. Only a Capture in
    Slicer runs UC1 on the mapped 002-04 cube.
  - `check-uc2.py` runs UC2 on `002-04` and matches a NumPy replica pixel for
    pixel; its `020-01` check proves the uint16 path is untouched.
- `SLIA-009` requirement 3 said to keep the ground-truth tests. It was changed
  on 2026-10-07 to point here.

### Specification findings (2026-10-07)

- `SLIAFlowCube.py` holds `parseEnviHeader`, which `SLIAFlowCalibratedCube.py`
  and the tests use, and everything else in it is the overlay. It stays as the
  ENVI header module.
- `GROUND_TRUTH_CLASSES` is the only copy of `FOUR_COLORS_MAP` in code, and only
  the overlay reads it. The legend that stays is the one written in the module
  README, the `SLIAFlow.ui` tooltip and the image contract, which tell the
  operator what the colours of `svm.bmp` and `knn.bmp` mean.
  `measure-uc1.py` keeps its own colour names; its comment points at the table.
- `resultOutput` is a persisted `Choice`. Slicer's combo-box connector raises
  `ValueError` in `connectGui` for a stored value that is not a choice
  (`parameterNodeWrapper/guiConnectors.py`, `QComboBoxToStringableConnector.write`).
  A scene saved with `gtMap` selected would then stop the module panel from
  binding. The widget resets an unknown stored value to the default output
  before binding.
- Mapped 002-04 on the current build, five runs on 2026-10-07: `pca.bmp`,
  `svm.bmp`, `knn.bmp` and `CalibratedImage_BIP.bmp` were identical in all five;
  `kmeans.bmp` differed between two runs in at most 0.0068 % of pixels,
  `imageRGB.bmp` in at most 0.0015 %. Each run took about 2 s. The cube's values
  are finite, 0 to 1.5.
- The mapped 002-04 cube has model bands 1-5 equal by construction, so one
  float32 run on it covers both what check 3 (float32 path) and check 4 (equal
  bands, patch 0003) did on `020-01` rewritten as float32.

### Owner decisions (2026-10-07, at specification)

1. **`020-01`: last run, then drop.** The 002-04 runs are recorded, both checks
   are run on `020-01` one final time with the result recorded here, and the
   `020-01` checks are then removed. The owner deletes
   `input/reference_hsi_brain_db/` afterwards. From then on nothing checks the
   patched build against the build as delivered.
2. **The archive goes too.** The owner deletes
   `input/archive_hsi_brain_db_93_bands/`. `input/README.txt` and the
   medical-data policy describe `input/` as holding `002-04/` only.
3. **Two historical guides deleted.** The owner authorized deleting the tracked
   files `end_to_end_verification.md` and `pipeline_test_quickstart.md`.

### Owner decisions (2026-10-07, after reviewing the implementation)

The owner's review found two defects in `check-uc1.py` (requirement 8) and
further leftovers. The owner widened this task to remove them:

4. **The BMP inspector goes.** `scripts/development/inspect-uc1-bmp.py` looks
   for database-style cases (default `017-01`) and finds none in `002-04`; it is
   deleted, with the gitignored report `informe-uc1-bmp/` it generated. The
   module's own BMP padding tests stay: a cube of another width can still meet
   those defects.
5. **Two stale documents go.** `docs/development/simulated_result_verification.md`
   (imports and controls removed since `SLIA-027`) and
   `docs/SLIAFLOW_CLEANUP_AND_NEXT_STEPS.md` (a 2026-08-27 checklist) are
   deleted, with the root README's link to the second.
6. **Old architecture drafts and robustness reviews go.**
   `STRATUM_SLICER_MODULE_OVERVIEW.md`, `STRATUM_SLICER_UC1_TECHNICAL_DRAFT.md`,
   `stratum-slicer-visualization-analysis.md`, `test_case_robustness_audit.md`
   and its three slice reviews are deleted. Anything still true and useful is
   moved first; the completed cards and Git history keep the record. The
   roadmap is rewritten to describe the project as it is, and stops calling the
   WP5 plan the authority.
7. **Old generated data goes, and the old-control guard.** The agent deletes
   `build/uc1/reference-unpatched/`, the `020-01`, `float32-check`,
   `equal-bands-check` and `determinism-002-04` inputs and outputs under
   `build/uc1/UC1/`, and `workspace/slia-039/`; their evidence is in this card
   and the change records. `test_operatorPanelHasNoLinkDemoOrLayerControls`, a
   guard that 16 controls retired by earlier tasks stay absent, is removed, as
   `test_moduleHasNoCasePool` was. Nothing under `input/` is touched.

## Requirements

1. **Ground-truth overlay retired.** The `gtMap` entry, its reading, its label
   map, its colour table, its status wording and its tooltip text are removed
   from the module, with the tests that cover them. Tests that only used a
   `gtMap` fixture as an aside keep their purpose without it.
   `ADR-0005` supersedes `ADR-0004` decision 8 and the 2026-09-18 amendment of
   `ADR-0003` decision 3.
2. **Older scenes still bind.** A parameter node that holds `gtMap` as
   `resultOutput` binds without error and shows the default output.
3. **Guards for retired code removed.** `test_moduleHasNoCasePool`. No new
   guard of that kind is added for the overlay.
4. **`check-uc1.py` runs on 002-04.**
   - It maps 002-04 onto the 93 model bands itself, from the rule in
     `ADR-0004` decision 4, independently of `SLIAFlowUc1Input.py`, and runs UC1
     on it: exit 0, the five outputs plus `CalibratedImage_BIP.bmp` written,
     each 1080 x 1080.
   - `pca.bmp`, `svm.bmp`, `knn.bmp` and `CalibratedImage_BIP.bmp` must have the
     SHA-256 the current build wrote on 2026-10-07. `kmeans.bmp` and
     `imageRGB.bmp` must differ from a saved run of that build in at most three
     times the largest drift measured (0.02 %).
   - `CalibratedImage_BIP.bmp` must be byte for byte the image predicted from the
     mapped cube, and `pca.bmp` within one grey level of NumPy's first principal
     component (patches 0002 and 0003, as before).
   - Band guard, short float32 cube and missing weights stay, on 002-04 data.
   - The `020-01` checks and the unpatched-build constants are removed.
5. **`check-uc2.py` runs on 002-04 only.** The `020-01` check is removed. The
   002-04 PNG must also have the SHA-256 the current build wrote on 2026-10-07,
   besides matching the NumPy replica.
6. **Documents describe only what exists.**
   - `end_to_end_verification.md` and `pipeline_test_quickstart.md` are deleted;
     their commands were removed in `SLIA-028`. The roadmap's link points at the `SLIA-014`
     card instead.
   - The historical runner sections of `uc1_demo_runbook.md`,
     `uc1_local_build.md` and `uc2_local_build.md` are removed.
   - `uc1_changes.md`, `uc2_changes.md`, `uc1_local_build.md`, the module README,
     the image contract and the runbook describe the 002-04 checks and no
     overlay. The `020-01` measurements stay in the change records as dated
     history, with this task's final run.
   - `WP5_MS5_DEMO_PLAN.md` stays: accepted ADRs link to it and it is marked
     historical. Only its data row changes. The `SLIAFlowCasePool.py` note in
     `acquisition_app_and_hardware.md` is updated.
   - Historical records in `tasks/completed/` and the bodies of accepted ADRs
     stay as written. `ADR-0003` and `ADR-0004` gain a `superseded_in_part_by`
     front-matter entry and a Status line, as `ADR-0004` did for `ADR-0003`.
7. **`input/` described as it will be.** `input/README.txt` and
   `.ai/policies/medical-data-policy.md` drop the reference case and the
   archive. The agent deletes nothing under `input/`.
8. **The saved K-means run cannot replace the reference, or delete anything.**
   `check-uc1.py --save-baseline` deletes nothing and writes only into a
   folder that does not exist yet or is empty. `--baseline` is refused when it
   holds the repository, lies in the UC1 build tree, or lies in the repository
   outside `build/`. A saved run is compared with only when its two files have
   the SHA-256 recorded in the script.
9. **The further leftovers of owner decisions 4-7 are removed.** The roadmap
   describes the six panels, Capture, the checks and the app connection as they
   are since `SLIA-036`, names the accepted ADRs as the authority, and keeps the
   task order as history. No current document links to a deleted one.

## Out of scope

- Any change to UC1's or UC2's algorithms or parameters.
- Judging whether UC1 or UC2 results on 002-04 are meaningful. Noted on
  2026-10-07: UC2's blue channel is at 255 on 69.9 % of the 002-04 map, against
  under 1 % for red and green. Whether UC2's fixed parameters (`high_in 0.15`)
  suit the LCTF camera is a question for IUMA.
- `SLIA-009`'s simulator cleanup, including the `uc1-real` comment in
  `tools/simulators/tests/test_igtl_transport.py`.
- `uc1_performance.md`: its ground-truth wording is about 002-04 having no
  labels, not about the overlay.
- The obsolete transport helpers (`prepareFrameForWire`, `_SharedPortServer`,
  `allowSharedPort`) and their tests: they are `SLIA-009`'s.
- `WP5_MS5_DEMO_PLAN.md` beyond its data row: accepted ADRs link to it.
- `source/`, `apps/`, `knowledge/`, `workspace/components/`.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCube.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/README.md`
- `scripts/development/check-uc1.py`
- `scripts/development/check-uc2.py`
- `scripts/development/measure-uc1.py` (one comment)
- `docs/architecture/decisions/ADR-0005-retire-the-old-inputs.md` (new)
- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`
  and `ADR-0004-iuma-lctf-cube-and-acquisition-app.md` (front matter and Status
  only)
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md` (data row only)
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` (rewritten, owner
  decision 6)
- `docs/development/uc1_changes.md`, `uc2_changes.md`, `uc1_demo_runbook.md`,
  `uc1_local_build.md`, `uc2_local_build.md`
- `docs/development/end_to_end_verification.md` and
  `pipeline_test_quickstart.md` (deleted)
- `docs/hardware/acquisition_app_and_hardware.md` (one note)
- `input/README.txt` (gitignored)
- `.ai/policies/medical-data-policy.md`
- `README.md` (the link to the deleted checklist; owner decision 5)
- Deleted, owner decisions 4-6: `scripts/development/inspect-uc1-bmp.py`,
  `docs/development/simulated_result_verification.md`,
  `docs/SLIAFLOW_CLEANUP_AND_NEXT_STEPS.md`,
  `docs/architecture/STRATUM_SLICER_MODULE_OVERVIEW.md`,
  `docs/architecture/STRATUM_SLICER_UC1_TECHNICAL_DRAFT.md`,
  `docs/architecture/stratum-slicer-visualization-analysis.md`,
  `docs/development/test_case_robustness_audit.md`,
  `docs/development/test_case_robustness_slice1_review.md`,
  `docs/development/test_case_robustness_slice2_review.md`,
  `docs/development/test_case_robustness_slice3_4_review.md`
- Deleted, gitignored, owner decisions 4 and 7: `informe-uc1-bmp/`,
  `build/uc1/reference-unpatched/`, `build/uc1/UC1/input/` and
  `build/uc1/UC1/gpu_single_bsq/source/output/` folders `020-01`,
  `float32-check`, `equal-bands-check`, `determinism-002-04`, and
  `workspace/slia-039/`
- this card

## Relevant skills and references

- Slicer skill: `Base/Python/slicer/parameterNodeWrapper/guiConnectors.py`
  (`QComboBoxToStringableConnector`) and `serializers.py` (validation on write
  only).
- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `tasks/completed/SLIA-025-retire-synthetic-phantom-path.md` and
  `tasks/completed/SLIA-031-single-cube-cleanup.md`, earlier retirements
- `docs/development/uc1_changes.md`, `docs/development/uc2_changes.md`

## Implementation plan

1. Record the final `020-01` runs of both checks (done, see Completion evidence).
2. Change the tests first: rewrite the result-selector test to the five outputs,
   add the stored-`gtMap` test, and observe both fail on the current code.
3. Remove the overlay from `SLIAFlowCube.py`, `SLIAFlowUc1Input.py`,
   `SLIAFlowParameterNode.py`, `SLIAFlowLogic.py`, `SLIAFlowWidget.py` and the
   tooltip; add the reset of an unknown stored `resultOutput` in
   `setParameterNode`.
4. Delete the overlay tests and `test_moduleHasNoCasePool`; strip the
   `groundTruth` fixture options and the `gtMap` parts of the tests that kept
   another purpose (zoom kept across outputs, not-validated status texts,
   translated refusals, mapped input written outside `input/`).
5. Rewrite `check-uc1.py` and `check-uc2.py`; record the 002-04 hashes and save
   the K-means baseline with `check-uc1.py --save-baseline`.
6. Write `ADR-0005` and the documents.
7. Run static analysis, the full headless and headful Slicer runs, and both
   checks.

## Acceptance criteria

1. The Delineation output box lists exactly the five UC1 outputs.
2. A parameter node holding `gtMap` as `resultOutput` binds without error and
   selects `imageRGB.bmp`.
3. No module code, UI text or test refers to `gtMap`, the ground truth or the
   case pool, except the reset of an older scene's `gtMap` selection and its
   test (criterion 2); and `SLIAFlowCube.py` holds only the ENVI header parser.
4. After a Capture the Tumour Delineation panel shows the selected output alone,
   with no label layer, as before.
5. `check-uc1.py` runs UC1 on mapped 002-04 and passes: the four hashes, the
   K-means bound, the predicted `CalibratedImage_BIP.bmp`, the PCA comparison,
   the band guard, the short cube and the missing weights. It names no `020-01`.
6. `check-uc1.py` fails when a recorded 002-04 hash or the saved baseline does
   not match.
7. `check-uc2.py` passes on 002-04 with the recorded PNG hash and names no
   `020-01`, and fails when that hash does not match.
8. No document outside `tasks/completed/`, accepted ADR bodies and dated
   history names `input\bin\bin`, `run-uc1-real.ps1`, `stratum_sim uc1-real` /
   `uc2-real`, `reference_hsi_brain_db` or `archive_hsi_brain_db_93_bands` as
   something that exists, and none describes the overlay as a feature.
9. `ADR-0005` records the retirement, and `ADR-0003` and `ADR-0004` point to it.
10. Static analysis and the full Slicer runs pass.
11. `check-uc1.py` refuses a `--baseline` that holds the repository, lies in the
    UC1 build tree or lies in the repository outside `build/`; refuses to save
    into a folder that holds files; and refuses a saved run whose hashes are
    not the recorded ones. It contains no `rmtree` of a path it is given.
12. The files and folders of owner decisions 4-7 no longer exist, nothing under
    `input/` was touched, and no file outside `tasks/completed/` and
    `tasks/superseded/` links to a deleted document or script.
13. The roadmap describes the panels, Capture and the app connection as the
    module README does, and does not call `WP5_MS5_DEMO_PLAN.md` the authority.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | `SLIAFlowTest.test_resultSelectorListsTheFiveOutputFiles` (changed) | automated |
| 2 | `SLIAFlowTest.test_storedGroundTruthSelectionFallsBackToTheDefaultOutput` (new) | automated |
| 3 | `rg` over `extensions/` recorded in Completion evidence | automated (search) |
| 4 | `SLIAFlowTest.test_selectedOutputIsShownAloneWithStaleLineOnTheView`, unchanged, which asserts no label layer on Tumour Delineation; and manual step 3 | automated + manual |
| 5 | `check-uc1.py` run, output recorded | automated (script) |
| 6 | `check-uc1.py` with one hash altered and with the baseline folder pointed elsewhere, output recorded, then restored | automated (script) |
| 7 | `check-uc2.py` run, and with the hash altered, output recorded | automated (script) |
| 8 | `rg` over `docs/`, `README*`, `extensions/`, `scripts/`, `.ai/` recorded in Completion evidence | automated (search) |
| 9 | Reading `ADR-0005` and the two front matters | manual (review) |
| 10 | `run-python-quality.ps1`, `run-slicer-tests.ps1`, `run-slicer-tests.ps1 -Headful` | automated |
| 11 | `check-uc1.py` with each refused `--baseline`, a full saved run, and a tampered copy, output recorded | automated (script) |
| 12 | `git status`, `Test-Path` on each path, and `git grep` for each deleted name, recorded | automated (search) |
| 13 | Reading the roadmap against the module README | manual (review) |

Tests to add or change, and how each one will be shown to fail first:

- `test_resultSelectorListsTheFiveOutputFiles`, renamed from
  `test_resultSelectorListsTheFiveOutputFilesAndTheGroundTruth`: expects the
  five outputs only. Against the current code it fails, listing `gtMap` sixth.
- `test_storedGroundTruthSelectionFallsBackToTheDefaultOutput` (new): writes
  `gtMap` into the parameter node, rebinds the widget, and expects
  `imageRGB.bmp`. Against the current code it fails: `gtMap` is still a choice,
  so the stored value stays. After the choice is removed and before the reset is
  added it errors with `ValueError` from `connectGui`, which is observed too.
- Removed with the overlay: `test_groundTruthPaletteMatchesTheClassifierOutputs`,
  `test_groundTruthIsReadTopRowFirst`,
  `test_groundTruthIsRefusedRatherThanReshaped`,
  `test_groundTruthReadingDoesNotWriteToInput`,
  `test_groundTruthIsASelectableViewAlongsideTheOutputs`,
  `test_groundTruthEntryIsOfferedOnlyForACubeThatHasOne`,
  `test_groundTruthArrivesAsALabelLayerOverTheResult`,
  `test_groundTruthOverlaysTheOutputChosenLastRatherThanReplacingIt`,
  `test_groundTruthReachesTheResultPanelLabelLayer`,
  `test_cubePanelStaysAloneWhenGroundTruthIsSelected`,
  `test_groundTruthFromAnotherCaptureIsNotLaidOver`,
  `test_unreadableGroundTruthDoesNotFailTheCapture`; and the guard
  `test_moduleHasNoCasePool`.
- Trimmed, same purpose: the zoom test drops `gtMap` from the outputs it
  cycles; `test_resultStatusSaysLctfResultsAreNotValidated` drops the three
  ground-truth texts; the translated-refusals test drops `GroundTruthError`;
  `test_uc1InputIsTheMappedCubeWrittenOutsideInput` drops its `gtMap` fixture.
  These lose assertions and gain none, so they have no new failure to show.

## Manual verification

Run in the built application after `build-sliaflow.ps1`, or in the developer
Slicer after Reload.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Open SLIAFlow and press Start. | LiveView shows the laptop camera. The module panel opens without an error in the Python console. | SLIAFlow opened and LiveView streamed camera 0; no module error surfaced in the UI, and Capture later completed. |
| 2 | Open the Delineation output box. | It lists `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, `imageRGB.bmp` and nothing else. Its tooltip names the colours of `svm.bmp` and `knn.bmp` and does not mention `gtMap`. | Observed exactly those five choices; the tooltip named the `svm.bmp` and `knn.bmp` colours and omitted `gtMap`. |
| 3 | Press Capture and wait for the result. Choose `svm.bmp`, then `knn.bmp`. | Tumour Delineation shows each output alone. The result status names recorded cube 002-04 and says results are not validated. | Capture completed on recorded cube 002-04. The status says the results are not validated and names the saved camera snapshot; selecting `svm.bmp` and `knn.bmp` updated the result status in turn. Stopping LiveView disabled Capture; restarting it preserved the `knn.bmp` result. The targeted Slicer test also confirmed no label layer. |
| 4 | Run `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` and `check-uc2.py`. | Each prints `PASS` and exits 0, and names `002-04` and no `020-01`. | After Capture, both printed PASS and exited 0; both name 002-04 and neither names 020-01. UC1 refused the 109-band, short-cube and missing-weights cases; UC2 refused its short-cube case. |
| 5 | After deleting `input\reference_hsi_brain_db` and `input\archive_hsi_brain_db_93_bands`, repeat steps 3 and 4. | The same results: nothing needs the deleted folders. | Both folders were already absent; I did not delete them. I repeated Capture and the command checks with them absent, and each produced the same result. |

## Risks

- **Nothing checks the patched build against the delivered one any more**
  (owner decision 1). The recorded 002-04 hashes catch any later change to a
  patch or to the toolchain's output, but not a difference the patches already
  introduced; the final `020-01` run below is the last evidence there was none.
- A changed GPU, driver or nvcc may change the four hashes without any patch
  changing. `check-uc1.py` then fails and says which file differs; the remedy is
  to re-record with `--save-baseline --baseline <new folder>` after reviewing
  the change, and to put the printed hashes in the script, as written in
  `uc1_changes.md`.
- Losing `build/uc1/baseline-002-04/` makes `check-uc1.py` fail until a run is
  re-recorded and its hashes put in the script. That is deliberate: the
  K-means images of `002-04` may not enter version control (medical-data
  policy), so the script pins their hashes instead.
- `ADR-0005` is written as accepted on the strength of the owner's 2026-10-07
  decisions (the card's Goal and the two decisions above). The owner may ask for
  it to stay proposed until review.

## Documentation impact

`ADR-0005` (new); `ADR-0003` and `ADR-0004` front matter and Status; the image
contract, the module README, `uc1_changes.md`, `uc2_changes.md`,
`uc1_local_build.md`, `uc2_local_build.md`, `uc1_demo_runbook.md`, the WP5 plan's
data row, the roadmap link, the hardware note, `input/README.txt` and the
medical-data policy. Two historical session guides deleted.
After the owner's review: the roadmap rewritten, the root README's checklist
link removed, and nine more documents and one script deleted (owner decisions
4-6).

## Completion evidence

### Final run on 020-01 (owner decision 1), 2026-10-07 11:12, main at 3d3518f

`.\.venv\Scripts\python.exe scripts\development\check-uc1.py`, exit 0:

```
Reference case 020-01: exit 0, 1.54 s
  pca.bmp                  identical  ee01256ba51b589f51d6a3a8d726685c04f08f25ccbb3bda857187809632e58c
  svm.bmp                  identical  5f9548afcf87908115cdff408e263a30a24f4423340b99655d2f46c276f62a0f
  knn.bmp                  identical  5aea0081152655c4ec4151abe59b97f3231818a2e351663a43178b2614a67910
  CalibratedImage_BIP.bmp  identical  810909a985f7bc0424e46fc8c225f7e797840c91b2d42812b5e74a7daedb2b89
  kmeans.bmp               0.2750% of pixels differ from the unpatched run (within 1%)
  imageRGB.bmp             0.1635% of pixels differ from the unpatched run (within 1%)
Band guard, 109-band header: exit 1, 0.12 s
float32-check: exit 0, 0.59 s
  CalibratedImage_BIP.bmp  identical to the prediction
  pca.bmp                  0.0064% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  svm.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  knn.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  pca.bmp                  99.9960% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
equal-bands-check: exit 0, 0.55 s
  pca.bmp                  99.9864% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
short-read-check: exit 1, 0.24 s
Missing weights: exit 1, 0.12 s
PASS
```

`.\.venv\Scripts\python.exe scripts\development\check-uc2.py`, exit 0:

```
002-04: exit 0, 0.25 s
  002-04-BVMap.png  1080 x 1080, identical to the NumPy replica (bands 4, 16, 50 = 480, 540, 710 nm)
  R at 255 0.7%, G at 255 0.8%, B at 255 69.9%
020-01: exit 0, 0.08 s
  020-01-BVMap.png  identical to the unpatched build  C1C7B940...
short-cube: exit 1, 0.03 s, no PNG
PASS
```

The patched build therefore still matched the delivered one on `020-01` on the
day its checks were removed.

### Mapped 002-04, five runs of the current build, 2026-10-07

Identical in all five runs (SHA-256):

```
CalibratedImage_BIP.bmp  ea59726ac65cd1ce9516d6c1231e7e63a792a4dad4c526ff500e1f6222deef81
pca.bmp                  b4f62bfb71b450f5ec8c6b2c0ee5ae038e769f59d47e9455482dee487f0432cc
svm.bmp                  c0a5eb4a29a556ffbaac6d06bb318d7e61099fb67755878512347ca06bf07464
knn.bmp                  c9769b093eb99fdc2c969cc27d0ba830c0da96cce1db6079bf4dfa7b7f40cd66
```

Largest difference between two of the five runs: `kmeans.bmp` 0.0068 %,
`imageRGB.bmp` 0.0015 % of pixels. Each run 2.0-2.3 s, exit 0.

### Tests observed failing first (2026-10-07)

Against the module as it was, after only the two test changes,
`run-slicer-tests.ps1 -Test test_resultSelectorListsTheFiveOutputFiles,test_storedGroundTruthSelectionFallsBackToTheDefaultOutput`,
exit 1, `FAILED (failures=2)`:

```
AssertionError: Tuples differ: ('pca.bmp', 'svm.bmp', 'knn.bmp', 'kmeans.bmp', 'imageRGB.bmp', 'gtMap') != ('pca.bmp', 'svm.bmp', 'knn.bmp', 'kmeans.bmp', 'imageRGB.bmp')
AssertionError: 'gtMap' != 'imageRGB.bmp'
```

With the `gtMap` choice removed and the reset in `setParameterNode` taken out,
`-Test test_storedGroundTruthSelectionFallsBackToTheDefaultOutput`, exit 1,
`FAILED (errors=1)`, from `connectGui`:

```
ValueError: Unable to find value gtMap in choices ['pca.bmp', 'svm.bmp', 'knn.bmp', 'kmeans.bmp', 'imageRGB.bmp']
```

Observed twice: once as first written, and again after the test was changed to
unbind the panel before writing the old value (the first form wrote it while
the panel was bound, and the wrapper's observer printed the same `ValueError`
in an otherwise passing run). The reset was then restored.

### Build checks on 002-04

- `check-uc1.py --save-baseline`: exit 0. Saved `build/uc1/baseline-002-04/`;
  the four hashes printed are those recorded above. The check's own mapping
  wrote a `raw.dat` byte-identical to SLIAFlow's (`aaf30f8e579f8aba...`).
- `check-uc1.py`: exit 0, 7.1 s. Four hashes identical; `kmeans.bmp` 0.0072 %
  and `imageRGB.bmp` 0.0013 % from the saved run (within 0.02 %);
  `CalibratedImage_BIP.bmp` identical to the prediction; `pca.bmp` 99.9709 %
  equal to NumPy's first component, at most 1 grey level off; band guard,
  short cube and missing weights refused.
- `check-uc1.py` with `RECORDED_SHA256["svm.bmp"]` set to zeros and
  `--baseline` holding `svm.bmp` as `kmeans.bmp`: exit 1,
  `FAIL: svm.bmp differs from the run recorded on 2026-10-07` and
  `FAIL: kmeans.bmp: 89.9252% of pixels differ, over 0.02%`.
- `check-uc2.py`: exit 0. PNG identical to the NumPy replica and to the
  recorded `605BF532...`; short cube refused.
- `check-uc2.py` with `RECORDED_PNG_SHA256` set to zeros: exit 1,
  `002-04-BVMap.png is 605BF532..., the build wrote 00000000... on 2026-10-07`.
- Neither script names `020-01` (`rg "020-01|REFERENCE"` over both: no match).

### Owner's review of the implementation (2026-10-07)

Two findings on `check-uc1.py`, fixed:

- **`--save-baseline` deleted the `--baseline` folder** with `shutil.rmtree`,
  wherever it pointed. It now deletes nothing: it writes the six images into a
  folder that does not exist yet or is empty, and refuses otherwise. Before any
  run, `--baseline` is refused when it holds the repository, lies in the UC1
  build tree (where the output under test is written), or lies in the
  repository outside `build/`.
- **The saved K-means run was not pinned**, so a lost baseline re-saved from a
  changed build, or `--baseline` pointed at the output under test, became the
  reference. The saved run's two hashes are now recorded in the script
  (`RECORDED_BASELINE_SHA256`), and a saved run with other hashes is refused.

Evidence, 2026-10-07:

| Command | Result | Exit |
| --- | --- | --- |
| `check-uc1.py --save-baseline --baseline .` | `C:\stratum holds the repository` | 1 |
| `check-uc1.py --save-baseline --baseline C:\` | `C:\ holds the repository` | 1 |
| `check-uc1.py --save-baseline --baseline input` | `in the repository but not under build/` | 1 |
| `check-uc1.py --save-baseline --baseline docs\x` | `in the repository but not under build/` | 1 |
| `check-uc1.py --baseline build\uc1\UC1\gpu_single_bsq\source\output\check-002-04` | `is in the UC1 build tree` | 1 |
| `check-uc1.py --save-baseline` (onto the existing saved run) | `already holds files`; still 6 files | 1 |
| `check-uc1.py --baseline <copy with one byte of kmeans.bmp changed>` | `is not the run recorded on 2026-10-07` | 1 |
| `check-uc1.py --save-baseline --baseline <new scratch folder>` | saved, printed both hash tables; folder removed afterwards | 0 |
| `check-uc1.py` | PASS | 0 |
| `run-python-quality.ps1` | passed | 0 |

The further leftovers (owner decisions 4-7), removed the same day:

- `git rm` of the script and the nine documents of decisions 4-6; `rm -rf` of
  `informe-uc1-bmp/`, `build/uc1/reference-unpatched/`, `workspace/slia-039/`,
  and of `020-01`, `float32-check`, `equal-bands-check` and
  `determinism-002-04` under `build/uc1/UC1/input/` and `.../source/output/`.
  Kept: `002-04`, `check-002-04`, `band-guard-check`, `short-read-check`,
  `received-from-app`, `no-model-check`, `output/rgb` (which UC1 writes into)
  and `build/uc1/baseline-002-04/`. `input/` still holds `002-04/`,
  `README.txt`, and the two folders the owner deletes.
- Facts moved before deleting: none were needed. The audit's rule on contract
  constants is already `testing_strategy.md` rule 4. The analysis's Slicer notes
  are either in use (per-view `SetBackgroundVolumeID`, `AddLayoutDescription`)
  or wrong: it says `DeviceModifiedEvent` is never invoked, while
  `SLIAFlowConnections.py` records, from the pinned source, that it is invoked
  once per message.
- `README.md`: the checklist link removed. The roadmap rewritten (requirement 9).
  `uc1_changes.md`: the dated mention of `reference-unpatched/` says it was
  deleted here.
- `test_operatorPanelHasNoLinkDemoOrLayerControls` removed; it is a guard that
  loses assertions only, so it has no failure to show first.
- `git grep` for each deleted name and folder, outside `tasks/`, plus
  `ADR-0005` and `input/README.txt`: no match, except the dated
  `float32-check` and `equal-bands-check` records in `uc1_changes.md`.

| Command | Result | Exit |
| --- | --- | --- |
| `run-python-quality.ps1` | passed | 0 |
| `run-slicer-tests.ps1` | `Ran 139 tests in 30.9s`, `OK (skipped=17)` | 0 |
| `run-slicer-tests.ps1 -Headful` | `Ran 139 tests in 72.3s`, `OK (skipped=1)` | 0 |
| `check-uc1.py` / `check-uc2.py`, after the deletions | PASS / PASS | 0 / 0 |
| `git diff --check` | clean | 0 |

The count is explained under Required checks below.

### Required checks

| Command | Result | Exit |
| --- | --- | --- |
| `.\scripts\development\run-python-quality.ps1` | Ruff: 14 files in `extensions/SLIAFlow/SLIAFlow` OK, 11 in `tools/simulators` OK | 0 |
| `.\scripts\development\run-slicer-tests.ps1` | `Ran 139 tests in 30.9s`, `OK (skipped=17)`, no traceback in the log | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 139 tests in 72.3s`, `OK (skipped=1)` | 0 |
| `.\scripts\development\build-sliaflow.ps1` | every module file `ok` in Verify, "The build tree matches the working tree." | 0 |
| `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | module loaded from `build\SLIAFlow`, `Ran 139 tests in 98.3s`, `OK (skipped=1)` | 0 |

139 = the 152 of `SLIA-038`, less the 13 overlay tests removed, plus
`test_storedGroundTruthSelectionFallsBackToTheDefaultOutput`, less
`test_operatorPanelHasNoLinkDemoOrLayerControls` (owner decision 7). The
first implementation run had 140, before that last removal. The two headless
skips fewer than `SLIA-038`'s 19 are the two removed headful-only overlay
tests.

In the deployed copy under `build\SLIAFlow`, `gtMap` appears only in the
widget's reset comment: not in `SLIAFlowParameterNode.py` or
`SLIAFlowLogic.py`.

### Searches

- Module (`rg -i "gtMap|ground.?truth|GroundTruth|GROUND_TRUTH|CasePool"` over
  `extensions/`): only the reset comment in `SLIAFlowWidget.py` and
  `test_storedGroundTruthSelectionFallsBackToTheDefaultOutput` (criterion 3).
- Repository, outside `tasks/completed/`, `tasks/superseded/`, `workspace/`,
  `build/`, `source/`, `apps/`, `knowledge/`: removed paths and commands remain
  only in accepted ADR bodies, the image contract's historical section, the
  bannered WP5 plan, the dated `020-01` record in `uc1_changes.md`, this card,
  `SLIA-009`'s pointer here, and the two out-of-scope files named above
  (criterion 8).

### Files

- Created: `docs/architecture/decisions/ADR-0005-retire-the-old-inputs.md`.
- Deleted (`git rm`, owner decision 3): `docs/development/end_to_end_verification.md`,
  `docs/development/pipeline_test_quickstart.md`.
- Modified: the module files, scripts and documents listed under Files allowed;
  `input/README.txt` (gitignored).
- Deleted after the owner's review (owner decisions 4-7): see the section
  above.
- Not touched: anything under `input/` other than `README.txt`.

## Review findings

## Human approval
