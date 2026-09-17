---
id: SLIA-027
title: Run capture and UC1 end to end inside the built Slicer
status: backlog
branch: feature/SLIA-027-integrated-slicer-capture-uc1
priority: high
depends_on: SLIA-025, SLIA-026
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001, ADR-0002]
---

# SLIA-027 - Run capture and UC1 end to end inside the built Slicer

## Goal

`C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe` runs the whole workflow on its
own, with no PowerShell or CMD windows, no separately started Python services and
no OpenIGTLink links inside Slicer:

1. The operator presses Start and the laptop camera shows in LiveView.
2. The operator presses Capture. LiveView freezes and the displayed frame is
   saved.
3. The app picks a compatible recorded HSI case from a shuffled pool.
4. Slicer starts the prebuilt UC1 intermediate-output GPU executable as a hidden
   background process.
5. Five validated UC1 BMP outputs become selectable in the Tumour Delineation
   panel.
6. LiveView resumes, whether the run succeeded or failed.

## Context

Planned with the project owner on 2026-09-17, after a Slicer-skill review of an
earlier draft. The owner's decisions from that review are binding on this card:

- **No network hop inside Slicer.** The earlier draft had Slicer serve loopback
  OpenIGTLink links to itself. `vtkMRMLIGTLConnectorNode::PushNode`
  (SlicerOpenIGTLink) clears message metadata and sends only `MRMLNodeName` and
  `Status`, so `SLIAFlow.CaptureId`, `SLIAFlow.OutputFile` and
  `SLIAFlow.DataOrigin` could not travel. Slicer was only talking to itself, so
  nodes are tagged directly instead.
- **Connect links and the five link-status rows are removed** (owner option A).
  Links return in a later task when external hardware or UC2 needs them
  (`SLIA-030`).
- **`CalibratedImage_BIP.bmp` is not shown.** `saveBIPtoBMP` in the vendored
  `BitmapWriter.cpp` writes rows without the 4-byte BMP padding, so the file is
  malformed whenever `samples` is not a multiple of 4 (for example `004-02`, 345
  wide, and `012-01`, 497 wide). The other four stage writers and
  `writeMatrixRGB` pad correctly.

Facts checked on 2026-09-17:

- `stratum.opt.intermediate.exe` takes the case folder as its only argument and
  must run from `build/uc1/UC1/gpu_single_bsq/source`, because it opens
  `../../svm_model` relatively. It creates `output/<case>/` itself;
  `output/rgb` is pre-created by `build-uc1.ps1`.
- The GUIDE section 3.1-B intermediate command line adds
  `-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT`. `functions.cu` includes
  `nvtx3/nvToolsExt.h`, which is header-only and present in CUDA 12.9, so no
  extra library is needed.
- All five kept outputs are 24-bit bottom-up BMPs of `samples x lines`.
- Inside Slicer, `slicer.app.applicationDirPath` is
  `apps/SR/Slicer-build/bin/Release`, because `SlicerWithSLIAFlow.exe` starts
  `Slicer.exe`, which starts `SlicerApp-real.exe`. The repository root must
  therefore be found from the module's own file location.
- `tools/simulators/stratum_sim/uc1_runner.py` already holds the hard-won run
  checks this card reuses: the `.uc1-runner.lock` exclusive lock, clearing
  outputs before a run, model integrity, dataset-matches-model, freshness against
  run start, and the 128-character path limit that makes UC1 exit 0 without
  writing.
- SLIA-026 recorded that SLIAFlow does not start producer processes and that
  one-click startup would be a separate task. This is that task.

## Requirements

### Operator panel

- Remove the Live source selector. The source is fixed as
  `AcquisitionSystemApp LiveView`, backed by the laptop camera.
- Remove the Connect links button, the five link-status rows and the
  link-waiting text added in SLIA-026.
- Remove the module's OpenIGTLink connector creation, receiver lookup and
  wire-provenance handling (`OpenIGTLink.*` attributes).
- Keep manual Start/Stop and Capture.
- Keep the UC2 panel with a plain status that no UC2 producer exists yet
  (`SLIA-021`).
- Enable Capture only while the camera runs and no capture is in progress.
  Ignore further presses while processing.

### Capture and snapshot

- On Capture, stop updating the LiveView volume and keep the last displayed
  frame on screen.
- Save it as `workspace/captures/output_laptop_camera_YYYYMMDD-HHMMSS.png`,
  creating the folder if needed and adding a numeric suffix on a same-second
  collision. The folder is already Git-ignored.
- Resume LiveView updates when processing ends, on success or failure.
- The snapshot records the simulated acquisition only; it is not a UC1 input.

### Recorded-case selection

- Discover cases under `input/bin/bin` without writing to that folder.
- A case is compatible when `raw`, `darkReference` and `whiteReference` exist
  with consistent ENVI headers and a band count that matches the SVM model,
  following `assertRecordedCase` and `assertDatasetMatchesModel`.
- Keep excluded cases in one named deferred-case list, containing only `058-02`
  until `SLIA-029`.
- Shuffle once, use each case once, then reshuffle. The queue lives only for the
  Slicer session.
- Generate a new capture ID for every Capture.
- Do not load the cube into the scene; UC1 reads the case from disk and nothing
  displays the cube.
- Show the selected case and the stage (capturing, running UC1, validating,
  done, failed) in the existing status area.

### UC1 build

- Extend `scripts/development/build-uc1.ps1` to also build
  `stratum.opt.intermediate.exe` with the GUIDE intermediate flags and the same
  `sm_120` targeting as the release build.
- Give each binary its own expected-warnings list, and add the intermediate
  `.exe`, `.exp` and `.lib` to the known build products so the SHA-256 source
  assertion still passes.

### UC1 execution

- Find `C:\stratum` from the module file location, so the same code works in
  `build\SLIAFlow\lib\...\qt-scripted-modules` and `extensions\SLIAFlow\SLIAFlow`.
  Do not use the application directory or `config/local.json`.
- Run `stratum.opt.intermediate.exe <case folder>` with `qt.QProcess`, working
  directory `build/uc1/UC1/gpu_single_bsq/source`. No shell, script, PowerShell
  or CMD.
- Before a run: the executable and model exist and the model is intact; hold
  `.uc1-runner.lock` for the whole run; clear the case's outputs and ensure
  `output/rgb` exists; check the output path fits 128 characters.
- Read stdout and stderr asynchronously; log them and show a short message on
  failure.
- Apply a run timeout, recorded in this card at specification. Nonzero exit,
  crash or timeout is a failure.
- On scene close, module exit or Slicer shutdown: kill and wait for an owned UC1
  process, stop the camera and timers, release the lock, remove temporary nodes.

### Output validation and display

- Required outputs in `output/<case>/`: `pca.bmp`, `svm.bmp`, `knn.bmp`,
  `kmeans.bmp`, `imageRGB.bmp`. `CalibratedImage_BIP.bmp` is ignored.
- Each file is newer than run start, an uncompressed 24-bit BMP with padded
  rows, and `samples x lines` of the selected case.
- Decode to upright RGB `uint8` (flip bottom-up rows, BGR to RGB) and load into a
  module-owned RGB vector volume with LiveView's IJK-to-RAS directions
  `diag(-1, -1, 1)` from SLIA-026.
- Tag each output node with the shared `SLIAFlow.CaptureId`, the case,
  `SLIAFlow.OutputFile`, `SLIAFlow.DataOrigin = simulated` and the simulation
  detail.
- Accept new results only when all five validate; otherwise keep the previous
  valid result.

### Result interface and provenance

- Replace the abstract delineation roles with the five exact filenames.
- Remove the Result class control.
- Show the selected output standalone; remove the `UC1_RGB` compositing path and
  its opacity control.
- Remove the Demo-mode checkbox, opt-in gate, transient demo state and the
  simulated overlay banners.
- Mark the previous valid result stale while a capture processes.
- On failure: resume LiveView, keep the previous result marked stale, show the
  case and an actionable message, and wait for another Capture without picking a
  replacement case.
- Keep the top-level "Prototype only - not clinically validated" notice.
- Normal result status reads `Recorded case <case> - simulated acquisition`.

### ADR-0003

Add `ADR-0003-integrated-capture-and-uc1-in-slicer.md`, superseding ADR-0001
rules 1-3 and ADR-0002 (no cube-derived overlay; standalone results), ADR-0001's
demo-mode opt-in and genuine-over-simulated precedence, SLIA-026's rule that
SLIAFlow does not start producer processes, and OpenIGTLink inside the operator
workflow. It keeps mandatory provenance, one capture ID per run, input and
output validation, no alteration of algorithm pixels beyond lossless BMP decode,
and non-clinical status.

## Out of scope

- Any change under `workspace/components`.
- Displaying `CalibratedImage_BIP.bmp`.
- OpenIGTLink links of any kind (`SLIA-030`).
- Changing or retiring `tools/simulators` and the session scripts (`SLIA-028`).
- Running `058-02` or any deferred case (`SLIA-029`).
- UC2 execution (`SLIA-021`).
- Microscope or other external hardware.
- Editing `config/local.json`.

## Files allowed

Proposed; confirm at specification.

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- New helper modules under `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/`, named at
  specification (case pool, UC1 process, BMP reader)
- `extensions/SLIAFlow/README.md`
- `scripts/development/build-uc1.ps1`
- `docs/development/uc1_local_build.md`
- `docs/development/openigtlink_setup.md`
- `docs/development/uc1_demo_runbook.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md` (status header only)
- `docs/architecture/decisions/ADR-0002-uc1-background-capture-identity-and-mismatch.md` (status header only)
- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`
- `tasks/{backlog,active,review,completed}/SLIA-027-integrated-slicer-capture-uc1.md`

The built copy under `build\SLIAFlow` is regenerated by `build-sliaflow.ps1` and
never edited by hand.

## Relevant skills and references

- Slicer skill: `qt.QProcess` from PythonQt, `vtkMRMLVectorVolumeNode`,
  `SetIJKToRASDirections`, scene-close and module cleanup.
- SlicerOpenIGTLink `vtkMRMLIGTLConnectorNode::PushNode`, for why links were
  dropped.
- `tools/simulators/stratum_sim/uc1_runner.py`, `envi.py`, `bmp.py`.
- `workspace/components/UC1_Brain_Tumor-GPU_optimization/.../gpu_single_bsq/GUIDE.md`
  sections 2.5 and 3.1-B; `BitmapWriter.cpp`; `functions_cuda.cu`.
- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md`.
- `.ai/policies/medical-data-policy.md`, `.ai/policies/algorithm-boundary-policy.md`.

## Implementation plan

1. Write ADR-0003 and mark ADR-0001/0002 superseded in part.
2. Extend `build-uc1.ps1` and build both binaries.
3. BMP reader with failing tests first (unpadded, stale, wrong size, not 24-bit).
4. Case pool with deferred list and shuffle queue.
5. UC1 process runner on `QProcess` with lock, pre-run checks, timeout and
   cleanup, tested through a fake process.
6. Capture flow: freeze, PNG save, stage status, resume.
7. Panel: remove selector, links, class control, demo mode and overlay; add the
   five-output selector and stale marking.
8. Update contract and setup docs; rebuild with `build-sliaflow.ps1`; verify in
   `SlicerWithSLIAFlow.exe`.

## Acceptance criteria

- The panel has no Live source selector, Connect links, link rows, Result class
  control or Demo mode, and lists the five exact output names.
- Capture freezes LiveView, saves a uniquely named PNG, and LiveView resumes on
  success and on failure; a second press while busy is ignored.
- Case selection excludes deferred cases, does not repeat before exhaustion,
  reshuffles, and rejects incompatible folders without writing to `input/`.
- UC1 runs through `QProcess` without a shell, with the correct program, argument
  and working directory, honouring the lock, timeout and cleanup.
- Each of the five outputs is refused when missing, stale, malformed or the wrong
  size; results are accepted only when all five validate.
- Displayed outputs are upright, unmirrored and carry the shared capture ID and
  required provenance.
- `build-uc1.ps1` produces both binaries and the SHA-256 source assertion passes.
- A full run from `SlicerWithSLIAFlow.exe` shows no console window and needs no
  external command.
- ADR-0003 is accepted by the project owner.

## Test plan

To be completed at specification, one row per acceptance criterion.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  | `SLIAFlowTest.test_...` | automated |
|  | Manual step N | manual |

Tests to add or change, and how each one will be shown to fail first:

-

## Manual verification

To be completed at specification. Expected steps, all from
`SlicerWithSLIAFlow.exe` only: Start; Capture and see the frozen frame and saved
PNG; see the selected case in status; real GPU run with no console window; all
five results selectable and upright; LiveView resumes; repeated captures pick
different cases; failure recovery with the UC1 binary temporarily renamed; clean
shutdown including during a UC1 run.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- **Scope.** The card touches about 8,000 lines of module and test code. If
  specification shows it cannot be delivered and reviewed as one unit, split it
  into build and runner, capture flow, and panel and ADR.
- **Hidden window.** Qt suppresses the child console only when Slicer has none of
  its own; confirm manually.
- **Removing safeguards.** Demo mode and genuine-over-simulated precedence go
  away. Provenance tags and the prototype notice are what remain, so they must be
  tested, not assumed.
- **Shared output folder.** The Python runner writes the same files; the lock is
  the only protection.

## Documentation impact

- New ADR-0003; status headers of ADR-0001 and ADR-0002.
- `SLIAFLOW_UC1_IMAGE_CONTRACT.md` and `openigtlink_setup.md`: the operator
  workflow no longer uses ports 18944, 18945, 18947, 18950 or their messages.
- `uc1_local_build.md`: the intermediate binary and its warnings.
- `uc1_demo_runbook.md` and `extensions/SLIAFlow/README.md`: the in-Slicer
  workflow.

## Completion evidence

## Review findings

## Human approval
