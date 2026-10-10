---
id: SLIA-040
title: Every IUMA capture, chosen by the operator, of any dimensions, with a compatibility check
status: active
branch: feature/SLIA-040-every-capture-any-dimensions
priority: high
depends_on: SLIA-039
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004, ADR-0006]
---

# SLIA-040 - Every IUMA capture, chosen by the operator, of any dimensions, with a compatibility check

## Goal

The operator chooses any of IUMA's captures in `input/` and Capture runs on it,
whatever its width and height. One command checks whether any capture, including
one added later, runs through UC1 and UC2, and a compatibility document lists
every capture with its result, the reason for any failure, and possible fixes.

## Context

*Created on 2026-10-08* from the project owner's decisions recorded in
`ADR-0006`. *Specified on 2026-10-08* when the owner said "do the SLIA-040
card", which is the begin-task authorization for this card.

- IUMA delivered 16 LCTF captures on 2026-10-08, `input/S-N-PPP-CC/S-N-PPP-CC/`,
  patients 002, 003, 005, 006 and 007. All have 109 bands at 460-1000 nm (the
  grid of `ADR-0004` decision 4), checked header by header on 2026-10-08.
  14 are 1080 lines x 1301 samples; `S-N-002-04` and `S-N-003-01` are
  1080 x 1080. No 1301-sample cube has run through UC1, UC2 or the panels yet.
- `S-N-002-04` is byte for byte the former `002-04` (compared on 2026-10-08).
  The owner removed `input/002-04`, which these still point at:
  `SLIAFlowLogic.CALIBRATED_CUBE_RELATIVE_PATH`, `check-uc1.py`, `check-uc2.py`,
  `measure-uc1.py`, the stand-in's default `--cube`, and names and texts in
  `SLIAFlowTest.py` and the UI. Until this task is done, Capture on the default
  cube and the build checks fail.
- What reads lines and samples, inspected on 2026-10-08:
  `loadCalibratedCube` and `readCalibratedCube` (header), `acceptCube` and
  `allocateReceivedCube` (`vtkImageData` of samples x lines x bands),
  `describeUc1Input` and `_headerText` (mapped cube), `decodeUc1Bmp` (padded
  rows, size checked against the case), `readBvMapPng` (size checked against
  the cube), `acceptOutputs`, `acceptVascularMap`, `acceptColourPreview`,
  `pixelSpectrum`. None assumes a square cube or a size. The test fixtures
  already use a 4 x 3 cube, so a transposed axis would fail today's tests, but
  4 samples need no BMP row padding, while 1301 samples do (1301 x 3 bytes
  leaves 1 byte of padding per row).
- `CalibratedCube.name` is the header's folder name, so for
  `input/S-N-002-04/S-N-002-04/` it is `S-N-002-04`: the capture ID. UC1's run
  folder (`build/uc1/UC1/input/<name>`), UC2's PNG name (`<name>-BVMap.png`) and
  every provenance text follow from it.
- `cubeSource` ("Cube on disk" or "Last cube from the app", `SLIA-036`) already
  chooses between disk and app. The capture list belongs to "Cube on disk".
- `check-uc1.py` and `check-uc2.py` compare with a recorded run of one cube, so
  their hashes cannot judge a new cube. Their independent oracles can: the
  predicted `CalibratedImage_BIP.bmp`, NumPy's first principal component for
  `pca.bmp`, and the NumPy replica of UC2. These depend only on the cube.
  Neither recorded hash depends on the folder name.
- The medical-data policy permits every file in `input/` (2026-10-08). This
  branch also carries the policy, `ADR-0004`/`ADR-0005` status lines and
  `ADR-0006` written before activation, and the untracked `SLIA-041` card, which
  is not part of this task.

### Owner decisions

1. *2026-10-08.* The capture list always starts on `S-N-002-04`; the choice is
   not remembered between sessions. Within a session it may be changed.
2. *2026-10-08.* Every capture is offered, including those that do not run;
   those are listed in a document with the reason and possible fixes.

## Requirements

### 1. Off `002-04`

- Every path, default and text that names `input/002-04` uses `S-N-002-04` in
  its nested folder. The recorded hashes of `check-uc1.py` and `check-uc2.py`
  stay as they are and must still pass (same cube).
- The saved K-means run `build/uc1/baseline-002-04` keeps its name: it is a
  recorded run, and its hashes are what is checked.

### 2. Captures are found, not configured

- A capture is a folder in `input/` that holds `LCTF_Calibrated_Cube_Single.hdr`
  directly, or in one nested folder of the same name. Its ID is the folder
  name. A file, a folder without that header, or a nested folder of another
  name is not a capture. Captures are listed in ID order.
- One function finds them: `SLIAFlowCaptures.findCaptures`, a module with no
  Slicer import, so that `check-captures.py` imports it from the module folder
  rather than copying the rule. Input validation
  (`ADR-0004` decision 6) is unchanged and stays in `loadCalibratedCube`.
- `input/` is never written.

### 3. The operator chooses the capture

- A "Recorded capture" row under "Cube source" in the Operator section lists
  every capture found, with a Refresh button beside it. The list is read again
  when the module is entered and when Refresh is pressed.
- The chosen capture is what the next Capture reads, what HS Cube shows, and
  what UC1 and UC2 run on. It is held by the logic (`captureId`, default
  `S-N-002-04`), not in settings and not in the parameter node, so neither a
  new Slicer session nor a saved scene loaded into one brings back an earlier
  choice (owner decision 1; review finding 4).
- The list always shows the capture the logic holds, however it was set
  (review finding 5).
- The row is disabled while a capture runs and while Cube source is "Last cube
  from the app".
- A chosen capture that is no longer found stays in the list as
  "`<ID>` (not found)"; Capture on it is refused with the existing reason
  ("... is missing"), and nothing is frozen or started.
- A capture that cannot run is offered like any other; Capture on it ends with
  the module's own reason, as today.
- The provenance texts name the chosen capture where they named `002-04`
  (`ADR-0006` decision 4). They already take `CalibratedCube.name`.
- `SLIAFlowLogic.calibratedCubeHeader` stays as the override tests use; without
  an override it is the chosen capture's header.

### 4. Any dimensions

- No module change is expected (Context). A test runs a full Capture on a cube
  of 5 samples x 3 lines: 5 samples gives padded BMP rows, as 1301 does, and
  lines and samples differ, so a transposed axis fails.

### 5. Compatibility check for any capture

- `scripts/development/check-captures.py` checks every capture found, or the
  ones named with `--capture ID` (repeatable). Per capture it reports each step
  as PASS or FAIL with the reason:
  1. **Cube**: the module's own `loadCalibratedCube` accepts the cube and its
     `modelBandSources` maps the wavelengths (the LCTF grid), so the check
     refuses what SLIAFlow refuses, with its reason (review finding 1).
  2. **UC1**: the mapped cube is written under `build/uc1/UC1/input/`, UC1
     exits 0 within the module's 60 s timeout and writes six images of the
     cube's samples x lines.
  3. **UC1 oracles**: `CalibratedImage_BIP.bmp` equals the prediction, and
     `pca.bmp` is within one grey level of NumPy's first principal component.
  4. **UC2**: the module's own `Uc2Build.assertRunnable` passes (file names,
     the three fixed bands at 480, 540 and 710 nm, path lengths), UC2 exits 0
     within its 30 s timeout and writes its PNG of the cube's size, equal to
     the NumPy replica.
  5. The run times of UC1 and UC2.
- A capture that cannot be read, or that makes a step raise, fails that step
  of that row with the reason; the other captures are still checked and the
  report is still written (review finding 2). `--input DIR` checks another
  folder laid out as `input/`.
- The oracles move from `check-uc1.py` and `check-uc2.py` into
  `scripts/development/uc_oracles.py`, which all three scripts import.
- It writes only under `build/` (one reused mapped folder, `check-capture`, so
  16 captures do not leave 16 mapped cubes), holds the UC1 and UC2 runner locks
  as the other checks do, prints a Markdown table at the end and writes it to
  `build/captures/compatibility.md`. It exits nonzero if any capture fails.
- "PASS" means the pipelines ran and agree with independent recomputation. It
  says nothing about accuracy (`ADR-0004` decision 5), and the script says so.

### 6. Compatibility document

- `docs/development/capture_compatibility.md`: how to run the check, what PASS
  means and does not mean, and one row per capture (ID, lines x samples, cube,
  UC1, UC1 oracles, UC2, times, date checked). For each failure: the reason
  and possible fixes.
- Filled from a real run on all 16 captures in this task.
- IDs and numbers only: no image, screenshot or pixel data.

### 7. Documents that describe the current input

- Update where documents describe today's input as `input/002-04` (module
  README, roadmap, UC1 and UC2 change records and build notes, runbook, image
  contract, demo plan, simulators README). Records of past runs keep naming
  `002-04` as written, with the cube's current folder named once.

## Out of scope

- Changing the 109-to-93 band mapping, or accepting another band grid.
- Retraining UC1, or any accuracy or comparison between captures.
- A random or shuffled choice of capture.
- Serving the stand-in to another computer (`SLIA-041`); here the stand-in only
  stops pointing at `002-04`.
- The raw cubes and photographs in each capture.
- Naming the cube volume after the capture: it keeps the data file's name, as
  the panel captions and provenance already name the capture.

## Files allowed

Module:

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCaptures.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCalibratedCube.py` (docstring;
  after the review of 2026-10-08, owner-approved: the re-read under the
  described name and the path-length refusal)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py` (added after
  the review of 2026-10-08, owner-approved: the re-read and the ASCII refusal)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowConnections.py` (comment)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc2Run.py` (comment; after
  the review of 2026-10-08, owner-approved: the re-read, and the map's name
  after the folder UC2 is given)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py` (added after the
  second scripted run of 2026-10-08, owner-approved "any fail do it under this
  task": UC1's path check as a function Capture calls before freezing)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt` (the new module file)
- `extensions/SLIAFlow/README.md`

Scripts and tools:

- `scripts/development/check-captures.py` (new)
- `scripts/development/uc_oracles.py` (new)
- `scripts/development/check-uc1.py`
- `scripts/development/check-uc2.py`
- `scripts/development/measure-uc1.py`
- `tools/simulators/stratum_sim/iuma_app_standin.py` (default cube only)
- `tools/simulators/README.md`

Documents:

- `docs/development/capture_compatibility.md` (new)
- `docs/development/uc1_changes.md`, `uc2_changes.md`, `uc1_performance.md`,
  `uc1_demo_runbook.md`, `uc1_local_build.md`, `uc2_local_build.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`,
  `SLIAFLOW_UC1_IMAGE_CONTRACT.md`, `WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`,
  `ADR-0005-retire-the-old-inputs.md`,
  `ADR-0006-several-captures-any-dimensions.md` (written before activation;
  `ADR-0006` gains the decided open details)
- `.ai/policies/medical-data-policy.md` (written before activation)
- this card

Outside Git: `input/README.txt` (written before activation).

## Relevant skills and references

- Slicer skill: `QComboBox` items with user data in PythonQt, the parameter
  node wrapper (`slicer.parameterNodeWrapper`, a `str` with `Default`).
- `ADR-0004` decisions 4 to 7, `ADR-0006`.
- `scripts/development/check-uc1.py`, `check-uc2.py` for the oracles.
- `docs/development/testing_strategy.md`.

## Implementation plan

1. Tests first (below), each seen failing on the current code.
2. `SLIAFlowCaptures.py`: `Capture(id, headerPath)`, `findCaptures(inputRoot)`,
   `captureHeader(inputRoot, captureId)` (the direct header if present, else
   the nested one; changed during implementation from nested first, so that
   the folder named in `input/` wins when both exist), `DEFAULT_CAPTURE_ID = "S-N-002-04"`, the header name. Add to
   `CMakeLists.txt`.
3. Logic: `INPUT_RELATIVE_PATH`, `captureId` (default `DEFAULT_CAPTURE_ID`,
   reset by `setRunEnvironment`), `captures()`, `calibratedCubeHeader` from the
   chosen capture unless overridden. Remove `CALIBRATED_CUBE_RELATIVE_PATH`.
4. Parameter node: unchanged (the choice is not kept in the scene; review
   finding 4).
5. UI and widget: the row, the Refresh button, filling the list (with the
   "(not found)" entry), enabling, handing the chosen ID to the logic when
   Capture is pressed. Tooltips without `002-04`.
6. Comments and docstrings naming `002-04` in the module.
7. `uc_oracles.py`, then `check-uc1.py` and `check-uc2.py` on it and on
   `S-N-002-04`; run both on the real build.
8. `check-captures.py`; run on all 16 captures; write the compatibility
   document from the run.
9. `measure-uc1.py`, the stand-in default, the documents.
10. Static analysis, full headless and full headful runs; record evidence.

## Acceptance criteria

1. With nothing chosen, Capture runs on `input/S-N-002-04/S-N-002-04/`, and the
   default is restored when the run environment changes.
2. Every folder in `input/` holding the calibrated header directly or in a
   same-name nested folder is found as a capture, in ID order; nothing else
   is; `input/` is not written.
3. The Recorded capture list shows every capture, starts on `S-N-002-04`, and
   the chosen capture is the one HS Cube shows and UC1 and UC2 run on, named
   in the provenance and status texts.
4. A capture added while Slicer runs appears after Refresh or on entering the
   module; a chosen capture no longer found is shown as not found, and Capture
   on it is refused with the missing file named, before anything is frozen.
5. The Recorded capture row is disabled while a capture runs and while Cube
   source is the app.
6. A Capture on a 5 x 3 cube (padded BMP rows, lines and samples different)
   shows the cube, its preview, the UC1 outputs and the UC2 map at 5 x 3, and
   UC1 is given a 5 x 3 mapped header.
7. `check-uc1.py` and `check-uc2.py` pass on `S-N-002-04` with their recorded
   hashes, on the real builds.
8. `check-captures.py` checks all captures, or only those named, reports every
   step per capture, writes only under `build/`, and exits nonzero when a
   capture fails.
9. `capture_compatibility.md` lists all 16 captures from a real run, with the
   reason and possible fixes for every failure.
10. No module file, script, tool or current-state document points at
    `input/002-04`.
11. In a real Slicer window the operator chooses a 1080 x 1301 capture, presses
    Capture, and sees it undistorted and named in HS Cube, Tumour Delineation
    and Enhanced Vascularization.
12. Static analysis and the full headless and headful Slicer test runs pass.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Default capture | `SLIAFlowTest.test_captureRunsUc1OnTheConfiguredCalibratedCube` (changed: nested `S-N-002-04` default), `test_runEnvironmentChangeRestoresTheDefaultCube` (changed) | automated |
| 2 Captures found | `SLIAFlowTest.test_capturesAreFoundInInput` (new) | automated |
| 3 Choice drives the capture | `SLIAFlowTest.test_chosenCaptureIsTheCubeCaptureUses` (new); `test_operatorControlsHaveStatedReasons` (changed during implementation: lists the two new controls, which must carry a tooltip); `test_captureListShowsTheCaptureCaptureReads` and `test_chosenCaptureIsNotSavedInTheScene` (new, review findings 5 and 4) | automated |
| 4 Refresh and missing choice | `SLIAFlowTest.test_captureListRefreshesAndKeepsAMissingChoice` (new) | automated |
| 5 Row enabled state | `SLIAFlowTest.test_captureRowFollowsCubeSourceAndCapture` (new) | automated |
| 6 Odd-width cube | `SLIAFlowTest.test_captureRunsOnACubeWithPaddedRows` (new) | automated |
| 7 Recorded hashes | `check-uc1.py`, `check-uc2.py` on the real builds | script |
| 8 Compatibility check | `check-captures.py` on all captures, with `--capture S-N-002-04`, with `--capture absent` (exit code), and with `--input` on placeholder captures the module refuses (review findings 1 and 2) | script |
| 9 Compatibility document | Manual step 9 | manual |
| 10 No `input/002-04` | `git grep` for `input/002-04`, `"002-04"` and `input" / "002-04` over module, scripts and tools | script |
| 11 Real capture on 1301 samples | Manual steps 5-6 | manual |
| 12 Quality and full runs | `run-python-quality.ps1`; `run-slicer-tests.ps1`; `run-slicer-tests.ps1 -Headful` | automated |

Tests to add or change, and how each one will be shown to fail first:

- `test_capturesAreFoundInInput`: fails on the current code because
  `SLIAFlowCaptures` does not exist (ImportError through `_helperModule`).
- `test_chosenCaptureIsTheCubeCaptureUses`,
  `test_captureListRefreshesAndKeepsAMissingChoice`,
  `test_captureRowFollowsCubeSourceAndCapture`: fail because the widget has no
  `captureSelector` and the logic no `captureId`.
- `test_captureRunsOnACubeWithPaddedRows`: chooses its 5 x 3 capture through
  `captureId`, so it fails on the current code with no such attribute. Its
  shape assertions are independent of that and are the part that guards the
  dimensions.
- The changed default tests fail because the current default is
  `input/002-04/...`, not `input/S-N-002-04/S-N-002-04/...`.
- Every fixture and expected text naming `002-04` changes to `S-N-002-04`, with
  the fixture cube in the nested layout. These are renames with the same
  assertions.

## Manual verification

Run the rebuilt application produced by `scripts/development/build-sliaflow.ps1`
(`build/SLIAFlow/SlicerWithSLIAFlow.exe`), with the UC1 and UC2 builds staged.
Start a fresh Slicer session without loading a saved scene so the default
selection can be checked. Enable Slicer Developer Mode if needed, open SLIAFlow,
and click its **Reload** control once; then follow the table. Expand SLIAFlow's
own **Developer** section if needed; it contains **Install Camera Support** and
**Result source**. Capture saves the current LiveView frame, so point the laptop
camera at a neutral, non-sensitive scene. If camera support is not installed,
click **Install Camera Support**, restart Slicer, launch a fresh session, and
resume at step 1.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | After Reload, select **SLIAFlow** from the **STRATUM** category if it is not already the active module. | SLIAFlow is active and its six-panel layout is visible: **LiveView**, **Stereoscopic**, **HS Cube**, **Relative StO2**, **Enhanced Vascularization**, and **Tumour Delineation**. | Observed: all six named panels were visible after Reload. |
| 2 | In **Operator**, open **Recorded capture** and inspect the full dropdown list without changing the selection. Check **Cube source** as well. | The list contains these 16 IDs in this order: `S-N-002-01`, `S-N-002-02`, `S-N-002-03`, `S-N-002-04`, `S-N-003-01`, `S-N-003-02`, `S-N-003-03`, `S-N-005-01`, `S-N-005-02`, `S-N-005-03`, `S-N-006-01`, `S-N-006-02`, `S-N-006-03`, `S-N-007-01`, `S-N-007-02`, `S-N-007-03`. `S-N-002-04` is selected, **Cube source** is **Cube on disk**, and **Refresh** is beside the list. | Observed: all 16 IDs appeared in the specified order; `S-N-002-04` was selected, source was **Cube on disk**, and **Refresh** was beside the list. |
| 3 | Set **Live source** to **Laptop camera**. Click **Start** and wait for a current camera image in **LiveView**. | The LiveView panel shows the live camera image and **Capture** becomes enabled. If it stays disabled, check the **Status** message; do not continue until a current frame is visible. | Observed: the camera started, LiveView updated, and **Capture** enabled. The camera showed a person and room, so I stopped it without capturing that image. |
| 4 | With `S-N-002-04` still selected and **Cube source** set to **Cube on disk**, click **Capture**. Wait until any transient progress messages stop and **Capture** is enabled again. Expand SLIAFlow's **Developer** section if needed to see **Result source**. | The **Status** line says UC1 results for recorded cube `S-N-002-04` are shown and says they are not validated. The vascular status names recorded cube `S-N-002-04` and UC2. Neither status says **Failed**. **HS Cube** has caption `Recorded cube S-N-002-04, calibrated reflectance`; **Tumour Delineation** says `Result for recorded cube S-N-002-04`; **Enhanced Vascularization** says `Enhanced vascularization for recorded cube S-N-002-04`. The three image panels show the square 1080 x 1080 capture. **Result source** also names recorded cube `S-N-002-04`. | Observed: UC1 and UC2 completed without failure; captions, Status, and **Result source** named `S-N-002-04`, the status said results were not validated, and the cube view was square. I supplied a synthetic black 480 x 640 RGB frame because the real camera view was not neutral. |
| 5 | In **Recorded capture**, select `S-N-005-01` (1080 lines x 1301 samples). Confirm it remains selected, then click **Capture**. Wait for both UC1 and UC2 to finish as in step 4. If LiveView has stopped, click **Start** and wait for a current frame before pressing **Capture**. | **Capture** completes without a failure. The **Status** and **Result source** name recorded cube `S-N-005-01`; the UC2 status also names it. The HS Cube, Tumour Delineation, and Enhanced Vascularization captions all name `S-N-005-01`, rather than `S-N-002-04`. | Observed: UC1 and UC2 completed without failure; Status, **Result source**, and all three captions named `S-N-005-01`, with results identified as not validated. I used a synthetic black 480 x 640 RGB frame. |
| 6 | Look at the image area in **HS Cube**, **Tumour Delineation**, and **Enhanced Vascularization** after step 5. Compare their outlines and fit in each panel. | Each panel shows the same complete, slightly wider-than-tall image (1301 samples by 1080 lines, about 1.20:1). The image is not square, transposed, cropped, or visibly stretched; all three panels have the same width-to-height shape. | Observed: all three panels showed the same complete landscape shape, about 1.20:1, with no visible transpose, crop, or stretch. |
| 7 | In **HS Cube shows**, choose **Colour preview**. Confirm the displayed image shape, then click inside the image (not the surrounding black area). Look under **Pixel spectrum**. | The colour preview is the same slightly wider-than-tall shape. Its caption gives the R, G, and B wavelengths and says `band composite, not a photograph`. **Pixel spectrum** opens with a plotted curve and a label like `Pixel column <number>, row <number> of recorded cube S-N-005-01: stored values, not an analysis.` The clicked pixel is inside the cube and the label names `S-N-005-01`. | Observed: the landscape preview caption listed R 650 nm, G 550 nm, and B 470 nm as a band composite, not a photograph. An inside click showed the stored-values spectrum label for `S-N-005-01`, ending `not an analysis`; an outside click showed the outside-cube message. |
| 8 | Change **Cube source** to **Last cube from the app**. Then change it back to **Cube on disk**. | While **Last cube from the app** is selected, **Recorded capture** and **Refresh** are greyed out and cannot be changed. Back on **Cube on disk**, both controls are enabled and `S-N-005-01` remains selected. | Observed: **Recorded capture** and **Refresh** were disabled for **Last cube from the app**; both re-enabled on **Cube on disk**, with `S-N-005-01` still selected. |
| 9 | Open `docs/development/capture_compatibility.md` in an editor and inspect its result table and failures section. | The result table has 16 captures in ID order and shows lines x samples, Cube, UC1, UC1 oracles, UC2, and run times. It records 16 of 16 passing every step on 2026-10-08, including `S-N-005-01` at 1080 x 1301. The failures section says there were none in that run and explains likely causes and possible fixes for future failures. | Observed: the document listed all 16 captures in ID order with the requested fields, recorded 16/16 passing on 2026-10-08, and said there were no failures in that run. |
| 10 | Return to **Recorded capture**, select `S-N-002-04`, and press **Capture**. Wait for both runs to finish. | The square 1080 x 1080 cube returns. The captions in all three image panels, **Status**, and **Result source** now name `S-N-002-04`; no caption or status still names `S-N-005-01`. | Observed: UC1 and UC2 completed without failure; the square cube and all captions, Status, and **Result source** returned to `S-N-002-04`, results were identified as not validated, and none named `S-N-005-01`. I used a synthetic black 480 x 640 RGB frame. |

Additional failure-path check (2026-10-09): setting the in-memory selection to
`S-N-999-99` displayed `S-N-999-99 (not found)` and Refresh preserved it. With
a current synthetic black frame, Capture reported that the configured cube
header was missing; it did not freeze LiveView or save another snapshot. The
selection was restored to `S-N-002-04`, and a final Capture completed.

Leave **Result** empty until each step has been performed. Record what was
actually observed for that step; do not enter `pass` without the observation.

## Risks

- A 1301-sample cube is about 20 % larger: UC1's GPU memory and the 60 s run
  timeout were measured on 1080 x 1080 only (`SLIA-034`). The check shows it.
- A square-cube assumption may hide in UC1's or UC2's C code, which only the
  real run on a 1301-sample cube reaches. The check shows it; fixing one is a
  patch, which goes to the owner before the card is changed.
- K-means outputs vary between runs, so the compatibility check checks their
  size only.
- Running all 16 captures through both pipelines takes several minutes.
- Moving the oracles out of `check-uc1.py` and `check-uc2.py` could change what
  they check; both are run on the real builds after the move.

## Documentation impact

`capture_compatibility.md` (new); the documents in requirement 7; `ADR-0006`'s
open details.

## Completion evidence

*Implementation and automated checks, 2026-10-08, on
`feature/SLIA-040-every-capture-any-dimensions`. Nothing committed. Manual
verification not yet done.*

### Implemented

- `SLIAFlowCaptures.py` (new): `findCaptures`, `captureHeader`,
  `DEFAULT_CAPTURE_ID = "S-N-002-04"`; added to `CMakeLists.txt`.
- Logic: `INPUT_RELATIVE_PATH`, `captureId` (reset by `setRunEnvironment`),
  `captures()`, `inputDirectory`; `calibratedCubeHeader` is the chosen
  capture's unless overridden. `CALIBRATED_CUBE_RELATIVE_PATH` removed.
- Parameter node: unchanged. The choice was first kept there and moved to
  the logic after review finding 4.
- UI and widget: "Recorded capture" row with Refresh; the list is read in
  `setParameterNode` (setup, enter, new scene) and on Refresh; a vanished
  choice is listed `<ID> (not found)`; the row is disabled with Cube source
  "Last cube from the app" and during a capture. Choosing in the list sets
  `logic.captureId`; a change made any other way calls the widget back
  (`captureIdChanged`), which reads the list again. Capture refuses any
  capture UC1 cannot run on (missing, bad cube, non-ASCII ID, paths too long)
  before freezing, saving a snapshot or starting UC2, with the logic's own
  reason (`loadConfiguredUc1Input`; first only a missing capture, widened
  after the scripted run of 2026-10-08).
- No dimension-specific change was needed in the module (Context).
- `uc_oracles.py` (new) holds the oracles `check-uc1.py` and `check-uc2.py`
  had, unchanged in substance; both now import it and read `S-N-002-04`.
  `check-captures.py` (new) as specified. `measure-uc1.py` and the stand-in's
  default point at `S-N-002-04`.
- Documents: `capture_compatibility.md` (new) and requirement 7's documents;
  `ADR-0006` records the decided open details.

### Tests seen failing first

Run against the unchanged module code, `run-slicer-tests.ps1 -Test ...`
(7 selected), exit 1, `FAILED (failures=2, errors=5)`:

- `test_capturesAreFoundInInput`: `ModuleNotFoundError: No module named
  'SLIAFlowLib.SLIAFlowCaptures'`.
- `test_chosenCaptureIsTheCubeCaptureUses`: `AttributeError: '' object has no
  attribute 'captureRefreshButton'`.
- `test_captureListRefreshesAndKeepsAMissingChoice`,
  `test_captureRowFollowsCubeSourceAndCapture`: `AttributeError: '' object has
  no attribute 'captureSelector'`.
- `test_captureRunsOnACubeWithPaddedRows`: `AttributeError: 'NoneType' object
  has no attribute 'case'` (the chosen capture was ignored, Capture went to
  the missing default and started no run).
- `test_captureRunsUc1OnTheConfiguredCalibratedCube`: `.../input/002-04/
  LCTF_Calibrated_Cube_Single.hdr != .../input/S-N-002-04/S-N-002-04/
  LCTF_Calibrated_Cube_Single.hdr`.
- `test_runEnvironmentChangeRestoresTheDefaultCube`: `'S-N-007-03' !=
  'S-N-002-04'`.
- `test_operatorControlsHaveStatedReasons` was not in the plan. It failed on
  the new code with its old list (`First differing element 1:
  'captureRefreshButton'`); its new list names controls the old code does not
  have, so it fails there too (by reading, not run).

The renamed fixtures (`S-N-002-04`, nested) keep their assertions.

### Automated checks

| Check | Command | Result |
| --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | exit 0; Ruff 0.15.21, 15 + 11 files, all checks passed |
| Ruff on the new scripts (not in the script's targets) | `ruff check --select E4,E7,E9,F,I,B` on `check-uc1.py`, `check-uc2.py`, `check-captures.py`, `uc_oracles.py` | all checks passed |
| Simulators | `tools\simulators\tests\run_tests.py` | exit 0, 64 tests OK |
| Selected tests | `run-slicer-tests.ps1 -Test` (the 7 above, `configuredCubeIsRefusedWithItsReason`, `cubeRefusalReasonsAreTranslated`) | exit 0, 9 OK |
| Full headless | `.\scripts\development\run-slicer-tests.ps1` | first run exit 1 (`test_operatorControlsHaveStatedReasons`, above); after its update exit 0, `Ran 158 tests`, `OK (skipped=18)` (headful-only tests) |
| Full headful | `run-slicer-tests.ps1 -Headful` | exit 0, `Ran 158 tests`, `OK (skipped=1)` (`test_headlessPresentationFallback`, headless only) |
| Rebuild | `.\scripts\development\build-sliaflow.ps1` | exit 0; Verify lists `SLIAFlowLib\SLIAFlowCaptures.py ok`; "The build tree matches the working tree." |
| Built application | `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module loaded from `build\SLIAFlow\...`, `Ran 158 tests`, `OK (skipped=1)` |
| UC1 build check (AC 7) | `.venv\Scripts\python.exe scripts\development\check-uc1.py` | exit 0, `PASS`: `pca`, `svm`, `knn`, `CalibratedImage_BIP` identical to the 2026-10-07 hashes; `kmeans` 0.0063 %, `imageRGB` 0.0012 % from the saved run (limit 0.02 %); BIP identical to the prediction; `pca.bmp` 99.9709 % exact, at most 1 level; band guard, short read and missing weights refused |
| UC2 build check (AC 7) | `.venv\Scripts\python.exe scripts\development\check-uc2.py` | exit 0, `PASS`: `S-N-002-04-BVMap.png` identical to the replica and to the recorded SHA-256 `605BF532...`; short cube refused |
| Compatibility, one capture (AC 8) | `check-captures.py --capture S-N-002-04` | exit 0, every step PASS |
| Compatibility, missing capture (AC 8) | `check-captures.py --capture absent` | exit 1, `Cube FAIL: LCTF_Calibrated_Cube_Single.hdr is missing`, other steps not run |
| Compatibility, all (AC 8, 9) | `check-captures.py` | exit 0, 16 of 16 captures pass every step; UC1 1.9-3.5 s, UC2 0.2-0.4 s; table in `capture_compatibility.md` |
| No `input/002-04` (AC 10) | `grep -rn -E 'input[/\\]002-04\|"002-04"\|input" / "002-04'` over `extensions`, `scripts`, `tools` | 4 hits, all comments saying the cube *was* `input/002-04` until 2026-10-08; no path points there |

### Not yet done

- Manual verification, steps 1-7, by the project owner on the rebuilt
  `build\SLIAFlow\SlicerWithSLIAFlow.exe`.
- Review, independent AI review, approval and commit: separate lifecycle
  stages, not authorized by this card's start.

## Review findings

### Review of 2026-10-08 (owner-supplied review of the uncommitted changes)

| # | Finding | Response |
| --- | --- | --- |
| 1 | The checker accepted 110 bands with 109 wavelengths, and wavelengths in micrometres, which Slicer refuses. | Fixed. The Cube step calls the module's `loadCalibratedCube` and `modelBandSources` through a package entry that skips `SLIAFlowLib/__init__.py`; the UC2 step calls `Uc2Build.assertRunnable`. `uc_oracles.cubeProblems`, the copy, is removed. `writeMappedCube` reads `.dat` or `.raw` as the module does. |
| 2 | A wavelength that is not a number stopped the whole check before the report. | Fixed. Each step runs in `runStep`; anything it raises fails that step of that capture, the next captures are checked and the report is written. The UC1 oracles are their own step, so an oracle error no longer overwrites UC1's PASS. |
| 3 | Real non-square captures are not yet seen in Slicer. | Open: manual steps 1-5 and the new step 7 (switching back) cover it; they are the owner's. |
| 4 | A saved scene kept `captureId`, so loading it brought an earlier choice back. | Fixed. `captureId` left the parameter node (which is back to `main`) for the logic. `test_chosenCaptureIsNotSavedInTheScene` saves the scene to a string and finds no trace of the choice. |
| 5 | Setting the choice other than through the list left the list showing another capture. | Fixed. `logic.captureId` is a property that calls `captureIdChanged`; the widget reads the list again when it does not already show that capture. `test_captureListShowsTheCaptureCaptureReads`; `test_captureRunsOnACubeWithPaddedRows` now chooses through `logic.captureId`. |

Tests seen failing first, on the code before these fixes, `run-slicer-tests.ps1
-Test` (5 selected), exit 1, `FAILED (failures=5)`:
`test_captureListShowsTheCaptureCaptureReads` (`'S-N-002-04' != 'S-N-005-01'`,
list not moved), `test_chosenCaptureIsNotSavedInTheScene`,
`test_chosenCaptureIsTheCubeCaptureUses`,
`test_captureListRefreshesAndKeepsAMissingChoice` (the logic did not hold the
list's choice until Capture), `test_captureRunsOnACubeWithPaddedRows` (Capture
read `S-N-002-04`, not the capture set on the logic).

Checker on placeholder captures (`--input` on a scratch folder, outside
`input/`): exit 1; `X-110-bands` "lists 109 wavelengths for 110 bands",
`X-micrometres` "gives wavelengths in Micrometers, not nanometres",
`X-not-a-number` "lists a wavelength that is not a number", each other step
not run; `X-tiny-but-valid` (5 x 7) checked after them, every step PASS.

Checks after the fixes, 2026-10-08:

| Check | Result |
| --- | --- |
| Ruff (`run-python-quality.ps1`, and on `scripts`, `extensions`, `tools`) | exit 0, all checks passed |
| Simulators | exit 0, 64 tests OK |
| `check-uc1.py`, `check-uc2.py` | exit 0, PASS with the recorded hashes |
| `check-captures.py` | exit 0, 16 of 16 captures pass every step; `--capture absent` exit 1, Cube "LCTF_Calibrated_Cube_Single.hdr is missing." |
| Full headless | a first run beside the UC1/UC2 checks failed `test_connectionsCloseOnEveryPath` twice (the stand-in timed out under load); alone it passed, and the full run alone: exit 0, `Ran 160 tests`, `OK (skipped=18)` |
| Full headful | exit 0, `Ran 160 tests`, `OK (skipped=1)` |
| `build-sliaflow.ps1` | exit 0, "The build tree matches the working tree." |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module from `build\SLIAFlow\...`, `Ran 160 tests`, `OK (skipped=1)` |

### Scripted run of the built app, 2026-10-08 (owner-supplied)

A script drove the built `SlicerWithSLIAFlow.exe` with real UC1, UC2 and the
real captures (read only) through manual steps 1-7, which all held, and tried
to break the selector. That run is not the owner's manual verification: the
camera path was not exercised and the Result column stays the owner's. It
found:

| # | Finding | Response |
| --- | --- | --- |
| 1 | A capture folder that links to a folder of another name showed in HS Cube, but UC1 and UC2 stopped with a false "changed on disk". The cube's paths are resolved, so the re-read before each run took the target folder's name. `check-captures.py` passed UC1 there. | Fixed for UC1 only; UC2 was fixed after the second scripted run (below). With owner approval (Files allowed extended). `reloadCalibratedCube` re-reads a cube under the name it was described with; `assertUc1InputUnchanged` and `Uc2Build.assertRunnable` use it. The checker's UC1 step starts with `assertUc1InputUnchanged`. `test_linkedCaptureRunsUnderItsOwnId`. |
| 2 | A capture ID with other than ASCII characters failed with a raw "'ascii' codec can't encode" after the capture started (UC1's header holds the ID). `check-captures.py` passed it. | Fixed with owner approval. `describeUc1Input` refuses the ID with its reason, so Capture refuses it before LiveView freezes. The checker's Cube step calls `describeUc1Input`. `test_captureWithANonAsciiIdIsRefusedWithItsReason`. |
| 3 | A header path of 260 characters or more was left out of Slicer's list without a word (its Python is not long-path aware); the checker listed and ran it. | Fixed. `findCaptures` looks with the extended-length prefix, so the capture is listed; `loadCalibratedCube` refuses the path with its length, in Slicer and in the checker alike. `test_captureOnALongPathIsListedAndRefusedWithItsReason`. |
| 4 | With both a direct and a nested header, the code takes the direct one; the plan said nested first. | The plan is corrected to the code (implementation plan step 2): the folder named in `input/` wins. |

Tests seen failing first, on the code before these fixes, `run-slicer-tests.ps1
-Test` (3 selected), exit 1, `FAILED (failures=2, errors=1)`:
`test_linkedCaptureRunsUnderItsOwnId` ("Cube S-N-008-01 changed on disk since
Capture was pressed"), `test_captureWithANonAsciiIdIsRefusedWithItsReason`
(`CalibratedCubeError not raised`),
`test_captureOnALongPathIsListedAndRefusedWithItsReason` (the header found was
the direct one, 194 characters: the nested one was not seen).

Checker on scratch captures (`--input`, outside `input/`): exit 1;
`S-N-008-01`, a junction to the real `S-N-005-01` folder, every step PASS at
1080 x 1301; `Z-ñandú-002-04` Cube "Its name Z-ñandú-002-04 has characters
other than ASCII…"; `L-xxx…` Cube "The path to LCTF_Calibrated_Cube_Single.hdr
is 306 characters, over the 259 Slicer can open…"; `X-tiny-but-valid` every
step PASS. The junction and the folder were removed afterwards; `input/` was
only read.

Checks after these fixes, 2026-10-08, run one after another:

| Check | Result |
| --- | --- |
| Ruff (`run-python-quality.ps1`, and on `scripts`, `extensions`, `tools`) | exit 0, all checks passed |
| Simulators (`unittest discover -s tools\simulators`) | exit 0, 64 tests OK |
| `check-uc1.py`, `check-uc2.py` | exit 0, PASS with the recorded hashes |
| `check-captures.py` | exit 0, 16 of 16 captures pass every step (the report under `build/` regenerated from this full run) |
| Full headless | exit 0, `Ran 163 tests`, `OK (skipped=18)` |
| Full headful | exit 0, `Ran 163 tests`, `OK (skipped=1)` |
| `build-sliaflow.ps1` | exit 0, "The build tree matches the working tree." |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module from `build\SLIAFlow\...`, `Ran 163 tests`, `OK (skipped=1)` |

### Second scripted run of the built app, 2026-10-08 (owner-supplied)

The rebuilt app, steps 1-7 and more edge cases (path-length boundaries, links
nested, symlinked and to other names, a header in both places, a non-ASCII
parent folder). Steps 1-7 held, 16 of 16 captures passed the checker, and the
earlier long-path and plan fixes held. Again not the owner's manual
verification. The owner asked for every failure to be fixed under this task.

| # | Finding | Response |
| --- | --- | --- |
| 1 | Linked captures: UC1 ran, UC2 failed with "UC2 did not write S-N-008-01-BVMap.png". UC2 names its map after the folder it is given, the link's target, while SLIAFlow looked for the capture's ID. The checker passed UC2, so the first scripted run's "every step PASS" for `S-N-008-01` held for the checker only. | Fixed. `Uc2Build.outputFileName` is the folder UC2 is given plus `-BVMap.png`; `outputPath`, the output path-length check and the map node's file name use it, and so does the checker. `test_linkedCaptureRunsUnderItsOwnId` checks the name against the argument UC2 is started with. |
| 2 | Non-ASCII ID: the reason was right but late. Capture froze LiveView, saved a snapshot and ran UC2 (its map shown under that capture) before UC1 refused. The check before freezing ran only for a missing header. | Fixed. Capture now always calls `loadConfiguredUc1Input` before freezing, so any capture UC1 cannot run on is refused before a snapshot, UC1 or UC2. `test_configuredCubeIsRefusedWithItsReason` gains the non-ASCII and UC1-path cases, runs with a UC2 build, and checks that no snapshot is saved and no UC2 run started. |
| 3 | Every `--input` or `--capture` run replaced `build/captures/compatibility.md` with a partial table. | Fixed. Only a run over every capture in `input/` writes it; a partial run prints the table and says it did not write the report. |
| 4 | An ID of about 89 characters or more: Slicer listed it and UC2 ran, UC1 refused its 127-character path; the checker passed UC1 (its own short mapped folder). | Fixed. UC1's path check is `assertUc1PathsFit`, called by `loadConfiguredUc1Input`, so Capture refuses before freezing, and by the checker's Cube step on the module's own folder for the capture. |
| 5 | Captures refused for bad content (110 bands, header only, truncated, header in both places) saved a snapshot; missing or too-long paths did not. | Fixed by 2: every capture UC1 cannot run on is refused before a snapshot. `test_unreadableCubeIsExplainedOnThePanel` now truncates the cube after that check, as when it changes during Capture, so the HS Cube explanation is still tested. |

Tests seen failing first, on the code before these fixes, `run-slicer-tests.ps1
-Headful -Test` (3 selected), exit 1, `FAILED (failures=5)`:
`test_linkedCaptureRunsUnderItsOwnId` (`'S-N-008-01-BVMap.png' !=
'kept-under-another-name-BVMap.png'`), `test_configuredCubeIsRefusedWithItsReason`
(off the grid: a snapshot was saved; non-ASCII: a process was started; the
next two subtests found that capture still running).

Checker on scratch captures (`--input`, outside `input/`): exit 1, "Not
written to …compatibility.md"; `S-N-008-01` (junction to the real
`S-N-005-01`) every step PASS; a flat 95-character ID Cube "The path
C:\stratum\build\uc1\UC1\input\U-…/raw.dat is 134 characters. UC1 keeps at
most 127…"; the 306-character path and the non-ASCII ID refused as before;
`X-tiny-but-valid` every step PASS. The report's time was unchanged; the
junction and the folder were removed, and `input/` was only read.

Checks after these fixes, 2026-10-08, run one after another:

| Check | Result |
| --- | --- |
| Ruff (`run-python-quality.ps1`, and on `scripts`, `extensions`, `tools`) | exit 0, all checks passed |
| Simulators | exit 0, 64 tests OK |
| `check-uc1.py`, `check-uc2.py` | exit 0, PASS with the recorded hashes |
| `check-captures.py` | exit 0, 16 of 16 captures pass every step; it wrote the report |
| Full headless | exit 0, `Ran 163 tests`, `OK (skipped=18)` |
| Full headful | exit 0, `Ran 163 tests`, `OK (skipped=1)` |
| `build-sliaflow.ps1` | exit 0, "The build tree matches the working tree." |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module from `build\SLIAFlow\...`, `Ran 163 tests`, `OK (skipped=1)` |

### Project audit of 2026-10-09 (owner-supplied)

An audit of the working tree (`workspace/audits/SLIAFlow_project_audit_2026-10-09.md`,
gitignored) and a review of it found two defects in this card's files and stale
statements in the roadmap. The owner asked for all of them to be fixed ("Do
all", 2026-10-09).

| # | Finding | Response |
| --- | --- | --- |
| 1 | `describeUc1Input` reads the cube's files once more, for their stamps, after the cube is loaded. A file removed or locked in between raised a raw `OSError`, which Capture's check before freezing (`loadConfiguredUc1Input` and the widget) did not catch: the reason went to the Python console, not the panel. | Fixed. `fileStamps` refuses a file it cannot read with `CalibratedCubeError`, "<file> could not be read: <reason>", as `loadConfiguredCalibratedCube` does, so Capture refuses before freezing, with the reason. `test_cubeUnreadableOnceLoadedIsRefusedWithItsReason`; `test_configuredCubeIsRefusedWithItsReason` gains the case "unreadable once loaded". |
| 2 | The checker and the module disagreed on a header without `header offset`: the module reads it as 0, `uc_oracles.writeMappedCube` refused it, so `check-captures.py` failed UC1 on a cube SLIAFlow runs. The checker also mapped the cube with its own oracle, so SLIAFlow's writer was outside its end-to-end check. | Fixed. `uc_oracles` reads an absent header offset as 0 (`LAYOUT_DEFAULTS`, `layoutDifference`). The UC1 step maps the cube with SLIAFlow's `writeUc1Input` into the one reused folder, and `uc_oracles.mappedCubeDifference` compares what it wrote with the mapping restated from the cube's header: layout, dimensions, wavelengths and every band, byte for byte. `capture_compatibility.md` describes the step and its failure. |
| 3 | The roadmap listed ADRs only up to `ADR-0005` and called `SLIA-037` upcoming. | Fixed: `ADR-0006`; LiveView and the history name `SLIA-037` as done; Next lists `SLIA-009`, `SLIA-041` and the two proposals below. |

Tests seen failing first, with `fileStamps` as it was before the fix,
`run-slicer-tests.ps1 -Headful -Test` (2 selected), exit 1, `FAILED
(errors=2)`: both raised `FileNotFoundError: [WinError 2] The system cannot
find the file specified` from `fileStamps`, the widget's out of
`_onCaptureClicked`.

Checker on two 5 x 7 placeholder captures that stand for no imagery, in a
scratch folder outside `input/` (`--input`). Before the fix, exit 1:
`X-no-offset` passed the Cube step and failed UC1 with "ValueError:
LCTF_Calibrated_Cube_Single.hdr declares {... 'header offset': ''}, not {...
'header offset': '0'}"; `X-with-offset` passed every step. After it, exit 0,
both pass every step. `mappedCubeDifference` on damaged copies of a mapped
cube: one bit flipped, "model band 93 (900 nm) is not cube band 89 (900 nm)";
one band off by one, "model band 5 (460 nm) is not cube band 1 (460 nm)";
92 bands, "raw.hdr describes (92, 7, 5), not (93, 7, 5)"; header offset 4,
refused; the copy as written, no difference.

Checks after these fixes, 2026-10-09, run one after another:

| Check | Result |
| --- | --- |
| Ruff (`run-python-quality.ps1`, and on `scripts`, `extensions`, `tools`) | exit 0, all checks passed |
| Simulators (`unittest discover -s tools\simulators`) | exit 0, 64 tests OK |
| Selected tests (`-Headful -Test`, the two above and five related) | exit 0, 7 OK |
| `check-captures.py --capture S-N-002-04` | exit 0, every step PASS |
| `check-captures.py --capture absent` | exit 1, Cube "LCTF_Calibrated_Cube_Single.hdr is missing." |
| `check-uc1.py`, `check-uc2.py` | exit 0, PASS with the recorded hashes (`kmeans` 0.0086 %, `imageRGB` 0.0011 % from the saved run) |
| `check-captures.py` | exit 0, 16 of 16 captures pass every step, UC1 2.0-2.8 s, UC2 0.2-0.3 s; it wrote the report, and `capture_compatibility.md` shows this run |
| Full headless | exit 0, `Ran 164 tests`, `OK (skipped=18)` |
| Full headful | exit 0, `Ran 164 tests`, `OK (skipped=1)` |
| `build-sliaflow.ps1` | exit 0, "The build tree matches the working tree." |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module from `build\SLIAFlow\...`, `Ran 164 tests`, `OK (skipped=1)` |

These fixes change no step of the manual verification: finding 1 only affects
a file that disappears between two reads, and the checker is not part of the
application. Step 9's document now shows the run of 2026-10-09 and still
records that of 2026-10-08, 16 of 16.

Outside this card, at the owner's request and not part of its change set:
`tasks/backlog/SLIA-042-uc1-failures-shown-as-failures.md` (a GPU error ends
UC1's run; a cube over the measured size is refused) and
`docs/architecture/decisions/ADR-0007-tumour-class-over-the-cube-colour-preview.md`
(proposed, not accepted).

## Human approval
