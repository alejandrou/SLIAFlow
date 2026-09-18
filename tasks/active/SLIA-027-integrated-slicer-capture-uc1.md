---
id: SLIA-027
title: Run capture and UC1 end to end inside the built Slicer
status: active
branch: feature/SLIA-027-integrated-slicer-capture-uc1
priority: high
depends_on: SLIA-025, SLIA-026
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0001, ADR-0002, ADR-0003]
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
   panel, together with the recorded case's own `gtMap` labelling as a sixth
   entry that lays over the chosen output.
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

Facts added at specification (2026-09-17):

- **All five kept outputs are written by one function.** `pca.bmp`
  (`savePCAOutputAsBMP`), `imageRGB.bmp` (`writeMatrixRGB`) and, through
  `writeKNNBMP` and `writeKmeansBMP`, `svm.bmp`, `knn.bmp` and `kmeans.bmp` all
  write a 54-byte header followed by bottom-up B,G,R rows padded with
  `(4 - (w * 3) % 4) % 4` zero bytes (`BitmapWriter.cpp` lines 41-96, 147-203,
  629-680).
- **Their `bfSize` header field is wrong whenever padding is non-zero.** Every
  one of those writers stores `filesize = 54 + 3 * w * h`, which omits the
  padding bytes it then writes. `biSizeImage` is 0. A validator that trusted
  `bfSize` would reject every correct 345-wide output. The padded layout is
  checked against the actual file length instead.
- **Two paths inside UC1 are silently truncated.** `data_loader.cpp` builds
  `<folder>/raw.dat`, `<folder>/darkReference.dat` and
  `<folder>/whiteReference.dat` with `snprintf(..., MAX_PATH_LENGTH, ...)` and
  prints nothing when they are truncated; `MAX_PATH_LENGTH` is 128
  (`data_loader.hpp` line 11). The stage writers do print `Path too long`. So
  the pre-run path check covers both the input file paths and the longest output
  path, `output/<case>/CalibratedImage_BIP.bmp`.
- **Recorded cases.** `input/bin/bin` holds 61 case folders. Each has `raw`,
  `darkReference` and `whiteReference` as `.hdr`/`.dat` pairs plus `gtMap` and
  `gtMap.hdr`; `gtMap.hdr` carries the `HSI Human Brain Database` marker that
  `envi.isRecordedDatabaseCase` reads. Every header read declares 93 bands, data
  type 12, BSQ, byte order 0 and header offset 0.
- **Slicer-side process precedent.** Slicer's `DICOMLib/DICOMProcesses.py` and
  the Slicer-Liver extension's `SegmentationJobQueue.py` both drive `qt.QProcess`
  from PythonQt with string-signature connections
  (`finished(int,QProcess::ExitStatus)`,
  `errorOccurred(QProcess::ProcessError)`, `readyReadStandardOutput()`), and
  treat a start failure as arriving through `errorOccurred` without `finished`.

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
- **HS Cube panel (owner decision, 2026-09-17):** keep the six-panel layout. The
  HS Cube panel is black and carries a stated reason, as Stereoscopic and
  Relative StO2 do: UC1 reads the recorded case from disk and the cube is not
  displayed. Remove the band slider and its label.
- **Layers (owner decision, 2026-09-17):** remove the Layers table and the Layer
  opacity slider. The five-output selector is the only result control.

### Capture and snapshot

- On Capture, stop updating the LiveView volume and keep the last displayed
  frame on screen.
- Save it as `workspace/captures/output_laptop_camera_YYYYMMDD-HHMMSS.png`,
  creating the folder if needed and adding a numeric suffix on a same-second
  collision (`..._YYYYMMDD-HHMMSS-2.png`, `-3`, and so on). The folder is
  already Git-ignored.
- The PNG holds exactly the pixels of the frozen frame, top row first, as the
  operator sees them in LiveView.
- Resume LiveView updates when processing ends, on success or failure.
- The snapshot records the simulated acquisition only; it is not a UC1 input.
- A Capture pressed with no frame displayed yet is refused with a status
  message and starts nothing.

### Recorded-case selection

- Discover cases under `input/bin/bin` without writing to that folder.
- A case is compatible when `raw`, `darkReference` and `whiteReference` exist
  with consistent ENVI headers and a band count that matches the SVM model,
  following `assertRecordedCase` and `assertDatasetMatchesModel`. Concretely:
  - the three headers exist and agree on `samples`, `lines` and `bands`;
  - each declares `data type = 12`, `interleave = bsq`, `byte order = 0` and a
    header offset of 0 (absent counts as 0);
  - `bands` is 93, the staged model's band count;
  - each `.dat` file is exactly `samples * lines * bands * 2` bytes;
  - `gtMap.hdr` carries the `HSI Human Brain Database` marker.
- Keep excluded cases in one named deferred-case list, containing only `058-02`
  until `SLIA-029`.
- Shuffle once, use each case once, then reshuffle. The queue lives only for the
  Slicer session.
- An incompatible folder is skipped with a logged reason; it never stops the
  pool. No compatible case at all is a failure with an actionable message.
- Generate a new capture ID for every Capture: an opaque `uuid4().hex`, the
  same form `contract.newCaptureId` makes (ADR-0002).
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
- The path check refuses a run when any of `<folder>/raw.dat`,
  `<folder>/darkReference.dat`, `<folder>/whiteReference.dat` or
  `output/<case>/CalibratedImage_BIP.bmp` is 128 characters or longer, because
  `snprintf` into a 128-byte buffer truncates at 127.
- The lock file is stamped immediately before the process starts, and its
  modification time is the freshness reference for every output, as in
  `uc1_runner.py`.
- Read stdout and stderr asynchronously; log them and show a short message on
  failure.
- **Run timeout: 60 s** (owner decision, 2026-09-17). Nonzero exit, crash,
  failure to start, a `Path too long` line on either stream, or timeout is a
  failure.
- On scene close, module exit or Slicer shutdown: kill and wait for an owned UC1
  process, stop the camera and timers, release the lock, remove temporary nodes.
- A lock left by another holder is never deleted by SLIAFlow; the run is refused
  with the lock path in the message.

### Output validation and display

- Required outputs in `output/<case>/`: `pca.bmp`, `svm.bmp`, `knn.bmp`,
  `kmeans.bmp`, `imageRGB.bmp`. `CalibratedImage_BIP.bmp` is ignored.
- Each file is newer than run start, an uncompressed 24-bit BMP with padded
  rows, and `samples x lines` of the selected case. Concretely: signature `BM`,
  pixel offset 54, `biSize` 40, `biPlanes` 1, `biBitCount` 24, `biCompression`
  0, `biWidth == samples`, `biHeight == lines` (positive, so bottom-up), and a
  file length of exactly `54 + lines * (3 * samples + padding)`. `bfSize` and
  `biSizeImage` are not trusted (see Context).
- Decode to upright RGB `uint8` (flip bottom-up rows, BGR to RGB) and load into a
  module-owned RGB vector volume with LiveView's IJK-to-RAS directions
  `diag(-1, -1, 1)` from SLIA-026.
- Tag each output node with the shared `SLIAFlow.CaptureId`, the case,
  `SLIAFlow.OutputFile`, `SLIAFlow.DataOrigin = simulated` and the simulation
  detail. The case is `SLIAFlow.RecordedCase`; the detail is
  `real UC1 pipeline, recorded HSI case <case> (simulated acquisition)`, the
  form `contract.recordedCaseDetail` produces.
- Accept new results only when all five validate; otherwise keep the previous
  valid result.

### Recorded ground truth (added 2026-09-18)

- `gtMap` and `gtMap.hdr` are one ENVI pair, not two candidate files: the
  header is 345 bytes of text, the other file is the raw `lines x samples`
  uint16 label array. Both are read; there is one ground truth per case.
- `gtMap.hdr` is checked before the pixels are: `bands = 1`, `data type = 12`,
  `interleave = bil`, `byte order = 0`, `header offset = 0`, and `samples` and
  `lines` equal to the case's. It is `bil`, not the `bsq` the cube headers
  declare, so it cannot reuse `_headerDimensions`. A gtMap that does not
  describe the case is refused, never cropped or stretched to fit.
- One band of `bil` is a plain row-major image, so the bytes are reshaped and
  never rearranged. Row 0 is the top, which is how `readUc1Bmp` hands back a
  decoded output, so the two line up pixel for pixel with no flip.
- The class IDs `gtMap.hdr` legends are the indices of `FOUR_COLORS_MAP` in
  `BitmapWriter.hpp`, which is the table `writeKNNBMP` paints `svm.bmp` and
  `knn.bmp` from. 0 unlabelled, 1 normal (green), 2 tumour (red), 3
  hypervascularized (blue), 4 background (black). So the ground truth and
  those two outputs already carry one legend, and
  `test_groundTruthPaletteMatchesTheClassifierOutputs` pins the two together.
  `kmeans.bmp` is painted from a different table whose cluster numbers are
  arbitrary, and `pca.bmp` is not a classification, so neither is comparable
  this way.
- Load it as one module-owned `vtkMRMLLabelMapVolumeNode`, not a third colour
  image, so Slicer treats it as the Label layer and its own opacity and
  outline controls work on it. Its colour table gives class 0 zero opacity:
  between 0.0% and 16.2% of a recorded case's pixels carry a class, so a
  white class 0 would sheet over the result almost everywhere.
- Tag it with the same `SLIAFlow.CaptureId`, case, `DataOrigin = simulated`
  and simulation detail as the outputs, and read it only after the outputs are
  accepted, so it always belongs to the result it can be laid over. A ground
  truth from any other capture is not shown.
- `gtMap` is a sixth entry in the Delineation output box, after the five
  outputs. It does not replace the background: it lays over whichever output
  was chosen last, which is the comparison it exists for.
- Like the cube, it is for the panel only. A ground truth that cannot be read
  never fails the capture; the result is still shown and choosing `gtMap`
  says the ground truth could not be read.
- `input/` stays a read target only.

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
- "Marked stale" means both: the result status says the result is from the
  previous capture, and a text line at the top of the Tumour Delineation view
  says `PREVIOUS RESULT - not from the current capture`. Both are removed when
  a new result is accepted.
- With no result accepted yet in the session, the Tumour Delineation view is
  black and says it is waiting for a capture.

### ADR-0003

Add `ADR-0003-integrated-capture-and-uc1-in-slicer.md`, superseding ADR-0001
rules 1-3 and ADR-0002 (no cube-derived overlay; standalone results), ADR-0001's
demo-mode opt-in and genuine-over-simulated precedence, SLIA-026's rule that
SLIAFlow does not start producer processes, and OpenIGTLink inside the operator
workflow. It keeps mandatory provenance, one capture ID per run, input and
output validation, no alteration of algorithm pixels beyond lossless BMP decode,
and non-clinical status.

ADR-0003 must be accepted by the project owner before any module code that
contradicts ADR-0001 or ADR-0002 is written, because an active task may not
contradict an accepted ADR (`AGENTS.md`, Source of Truth).

## Out of scope

- Any change under `workspace/components`.
- Displaying `CalibratedImage_BIP.bmp`.
- OpenIGTLink links of any kind (`SLIA-030`).
- Changing or retiring `tools/simulators` and the session scripts (`SLIA-028`).
- Running `058-02` or any deferred case (`SLIA-029`).
- UC2 execution (`SLIA-021`).
- Microscope or other external hardware.
- Editing `config/local.json`.
- Interpreting the five outputs: no palette inversion and no class statistics.
- Any accuracy, sensitivity, agreement or confusion figure computed against
  `gtMap`. `.ai/policies/medical-data-policy.md` withholds approval for exactly
  that, in the interface and in a deliverable alike, and this card does not
  specialize it. Showing `gtMap` as a layer computes nothing and states
  nothing about accuracy; it puts the database's own labels on screen beside a
  result and leaves the reading to the person looking. A number would be this
  repository evaluating an algorithm, which the policy reserves.
- `.ai/policies/medical-data-policy.md` still mentions the demo-mode interlock
  as a protection. It is not in this card's files; see Risks.

## Files allowed

Confirmed at specification, 2026-09-17.

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowBmpReader.py` (new): BMP
  header validation and lossless decode. No `slicer` import.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCasePool.py` (new): ENVI
  header reading, compatibility checks, the deferred-case list and the shuffle
  queue. No `slicer` import.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py` (new):
  repository-root discovery, the staged build layout, pre-run checks, the lock,
  the `qt.QProcess` run with timeout and cleanup, and output collection.
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

Re-confirmed 2026-09-18 for the ground-truth layer: it touches
`SLIAFlowCasePool.py`, `SLIAFlowLogic.py`, `SLIAFlowWidget.py`,
`SLIAFlowParameterNode.py`, `SLIAFlow.ui` and `SLIAFlowTest.py`, all already on
this list. No file was added to it.

The built copy under `build\SLIAFlow` is regenerated by `build-sliaflow.ps1` and
never edited by hand. Staged UC1 binaries under `build\uc1` are produced by
`build-uc1.ps1` and never edited by hand.

## Relevant skills and references

- Slicer skill: `qt.QProcess` from PythonQt, `vtkMRMLVectorVolumeNode`,
  `SetIJKToRASDirections`, scene-close and module cleanup.
- `slicer-source/Modules/Scripted/DICOMLib/DICOMProcesses.py` and
  `slicer-extensions/Slicer-Liver/LiverSegmentation/LiverSegmentationLib/SegmentationJobQueue.py`
  for `qt.QProcess` signal wiring and idempotent completion.
- SlicerOpenIGTLink `vtkMRMLIGTLConnectorNode::PushNode`, for why links were
  dropped.
- `tools/simulators/stratum_sim/uc1_runner.py`, `envi.py`, `bmp.py`,
  `contract.py` (`newCaptureId`, `recordedCaseDetail`).
- `workspace/components/UC1_Brain_Tumor-GPU_optimization/.../gpu_single_bsq/GUIDE.md`
  sections 2.5 and 3.1-B; `BitmapWriter.cpp`; `functions_cuda.cu`;
  `data_loader.cpp`; `data_loader.hpp`.
- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md`.
- `.ai/policies/medical-data-policy.md`, `.ai/policies/algorithm-boundary-policy.md`.

## Implementation plan

1. Write ADR-0003 as proposed and mark ADR-0001/0002 superseded in part once it
   is accepted. **Stop for owner acceptance before step 3.**
2. Extend `build-uc1.ps1` and build both binaries.
3. BMP reader with failing tests first (unpadded, stale, wrong size, not 24-bit,
   compressed, `bfSize` quirk accepted).
4. Case pool with deferred list and shuffle queue, tested on temporary
   placeholder case folders.
5. UC1 process runner on `QProcess` with lock, pre-run checks, timeout and
   cleanup, tested through a fake process, plus one real `QProcess` run of
   Slicer's own Python to prove the signal wiring.
6. Capture flow: freeze, PNG save, stage status, resume.
7. Panel: remove selector, links, class control, demo mode, overlay, layers and
   band browser; add the five-output selector, the HS Cube reason and stale
   marking. Delete the tests of removed behaviour (listed under Test plan).
8. Update contract and setup docs; rebuild with `build-sliaflow.ps1`; verify in
   `SlicerWithSLIAFlow.exe`.

## Acceptance criteria

1. The panel has no Live source selector, Connect links, link rows, Result class
   control, Demo mode, Layers table, Layer opacity or band slider, and the
   result selector lists exactly `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`,
   `imageRGB.bmp` and `gtMap`, in that order.
2. The HS Cube and Enhanced Vascularization panels are black with a stated
   reason, and the prototype notice is still shown.
3. Capture is enabled only while the camera runs and no capture is in progress,
   and a press while busy starts nothing.
4. Capture freezes LiveView and saves a uniquely named PNG holding the frozen
   frame upright; LiveView resumes on success and on failure.
5. Case selection excludes deferred cases, does not repeat before exhaustion,
   reshuffles, and rejects incompatible folders without writing to `input/`.
6. UC1 runs through `QProcess` without a shell, with the correct program,
   argument and working directory, honouring the lock, pre-run checks, 60 s
   timeout and cleanup.
7. Each of the five outputs is refused when missing, stale, malformed or the
   wrong size; results are accepted only when all five validate.
8. Displayed outputs are upright, unmirrored, pixel-identical to the decoded BMP
   and carry the shared capture ID and required provenance.
9. While a capture processes, and after a failed one, the previous result is
   marked stale; a new accepted result clears the mark.
9a. `gtMap` is refused unless its header describes this case as one `bil` band
    of uint16; it is read top row first; it arrives as a label map whose
    colour table is `FOUR_COLORS_MAP` with class 0 transparent; it carries the
    result's capture ID and is not shown when it belongs to another capture;
    selecting it keeps the chosen output on the background layer; and a ground
    truth that cannot be read never fails the capture. No accuracy, agreement
    or confusion figure is computed or shown anywhere.
10. `build-uc1.ps1` produces both binaries and the SHA-256 source assertion
    passes.
11. A full run from `SlicerWithSLIAFlow.exe` shows no console window and needs no
    external command.
12. ADR-0003 is accepted by the project owner.

## Test plan

Expected values come from these authorities, never from observed output:

- The five output names: `functions_cuda.cu` and `main.cu` `snprintf` formats.
- BMP layout and padding: `BitmapWriter.cpp` `writeBMP`. The test fixtures are
  built by a small writer inside the test that transcribes `writeBMP`, including
  its `bfSize = 54 + 3 * w * h` field, and by a variant that omits padding as
  `saveBIPtoBMP` does.
- Compatibility rules: `envi.py`, `uc1_runner.py` and the vendored headers.
- 128-character limit: `data_loader.hpp` `MAX_PATH_LENGTH`.
- Directions `diag(-1, -1, 1)`: SLIA-026.
- 60 s timeout, deferred list `058-02`, filenames: this card.
- The gtMap class legend and its colours: the `Class ID (n)` lines every
  recorded `gtMap.hdr` carries, and `FOUR_COLORS_MAP` in `BitmapWriter.hpp`,
  which `writeKNNBMP` paints `svm.bmp` and `knn.bmp` from. The two are
  transcribed into one table in `SLIAFlowCasePool` and pinned by
  `test_groundTruthPaletteMatchesTheClassifierOutputs`.

Fixtures are placeholder arrays and placeholder case folders written to a
temporary directory the test deletes, labelled as test fixtures, as
`.ai/policies/medical-data-policy.md` allows. No test reads `input/bin/bin`.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | `SLIAFlowTest.test_operatorPanelHasNoLinkDemoOrLayerControls` (new); `test_resultSelectorListsTheFiveOutputFilesAndTheGroundTruth` (changed 2026-09-18: expects `gtMap` as the sixth entry); manual steps 2, 12 | automated + manual |
| 2 | `SLIAFlowTest.test_reservedPanelIsBlackWithStatedReason` (changed: adds HS Cube and UC2); `test_moduleMetadataAndUi` (kept, asserts the notice); manual step 2 | automated + manual |
| 3 | `SLIAFlowTest.test_captureEnabledOnlyWhileCameraRunsAndIdle` (new); `test_capturePressWhileBusyStartsNothing` (new); manual step 4 | automated + manual |
| 4 | `SLIAFlowTest.test_captureFreezesLiveViewAndSavesUprightSnapshot` (new); `test_snapshotNameIsUniqueWithinOneSecond` (new); `test_liveViewResumesAfterSuccessAndFailure` (new); `test_captureWithoutAFrameIsRefused` (new); manual steps 4, 5, 6, 9 | automated + manual |
| 5 | `SLIAFlowTest.test_casePoolExcludesDeferredCases` (new); `test_casePoolUsesEachCaseOnceThenReshuffles` (new); `test_casePoolRejectsIncompatibleFolders` (new); `test_casePoolDoesNotWriteToInput` (new); manual step 8 | automated + manual |
| 6 | `SLIAFlowTest.test_repositoryRootIsFoundFromModuleLocation` (new); `test_uc1RunUsesProgramArgumentAndWorkingDirectory` (new); `test_uc1PreRunChecksRefuseBeforeStarting` (new); `test_uc1RunRefusesWhileLockIsHeld` (new); `test_uc1RunFailsOnExitCodeCrashOrPathTooLong` (new); `test_uc1RunTimesOutAndKillsProcess` (new); `test_realQProcessReportsOutputAndExitCode` (new); `test_cleanupKillsOwnedRunAndReleasesLock` (new); manual steps 4, 10, 11 | automated + manual |
| 7 | `SLIAFlowTest.test_bmpReaderAcceptsPaddedWriterOutput` (new); `test_bmpReaderRejectsUnpaddedRows` (new); `test_bmpReaderRejectsWrongFormat` (new: bit depth, compression, signature, offset); `test_bmpReaderRejectsWrongDimensions` (new); `test_outputsRefusedWhenMissingOrStale` (new); `test_resultsAcceptedOnlyWhenAllFiveValidate` (new) | automated |
| 8 | `SLIAFlowTest.test_outputVolumeIsUprightUnmirroredAndPixelIdentical` (new); `test_outputNodesCarrySharedCaptureIdAndProvenance` (new); `test_selectedOutputIsShownAloneWithStaleLineOnTheView` (new, headful, added during implementation); manual step 7 | automated + manual |
| 9 | `SLIAFlowTest.test_previousResultIsMarkedStaleWhileProcessingAndAfterFailure` (new); `test_selectedOutputIsShownAloneWithStaleLineOnTheView` (new, headful); manual steps 4, 9 | automated + manual |
| 9a | `SLIAFlowTest.test_groundTruthPaletteMatchesTheClassifierOutputs` (new); `test_groundTruthIsReadTopRowFirst` (new); `test_groundTruthIsRefusedRatherThanReshaped` (new, 10 subtests); `test_groundTruthReadingDoesNotWriteToInput` (new); `test_groundTruthIsASelectableViewAlongsideTheOutputs` (new); `test_groundTruthArrivesAsALabelLayerOverTheResult` (new); `test_groundTruthOverlaysTheOutputChosenLastRatherThanReplacingIt` (new); `test_groundTruthFromAnotherCaptureIsNotLaidOver` (new); `test_unreadableGroundTruthDoesNotFailTheCapture` (new); manual steps 12, 13, 14, 15 | automated + manual |
| 10 | Manual step 1 | manual |
| 11 | Manual steps 3, 4, 6 | manual |
| 12 | Human approval section, recorded by the project owner | manual |

Tests to add or change, and how each one will be shown to fail first:

- Every new test is run against the code on `main` before its implementation
  exists. The three helper-module test groups fail with `ImportError` or
  `AttributeError` because `SLIAFlowBmpReader`, `SLIAFlowCasePool` and
  `SLIAFlowUc1Run` do not exist. The panel tests fail because
  `liveSourceSelector`, `connectLinksButton`, `demoModeCheckBox`, `layerTable`
  and `bandSlider` exist and the selector lists the five abstract roles. The
  capture tests fail because Capture is tied to the control link. The actual
  messages are recorded under Completion evidence.
- `test_bmpReaderAcceptsPaddedWriterOutput` also has to be seen rejecting a
  correct file when the reader is temporarily made to trust `bfSize`, so the
  `bfSize` quirk is proven to be covered, not assumed.
- `test_realQProcessReportsOutputAndExitCode` runs Slicer's own Python
  executable with `-c` to print one stdout line, one stderr line and exit 3. It
  reports a skip, not a pass, if that executable cannot be resolved.
- `test_reservedPanelIsBlackWithStatedReason` is changed, and seen failing, to
  require the HS Cube and Enhanced Vascularization reasons.

Tests deleted with the behaviour they cover, because this card removes that
behaviour (ADR-0003). Each one's removal is listed in Completion evidence:

- OpenIGTLink links and wire provenance:
  `test_prefixedAndBareWireAttributesBothTranslate`,
  `test_unknownProvenanceIsRejectedNotDefaulted`,
  `test_receivedSimulatedNodeObeysDemoModeGate`,
  `test_liveViewNodeBindsToLivePaneOnly`, `test_resultNodeBindsToResultPaneOnly`,
  `test_invalidResultDoesNotReplaceLastValidState`,
  `test_reconnectDoesNotRedisplayRetainedResultBeforeNewData`,
  `test_reconnectDoesNotRedisplayRetainedLiveFrameBeforeNewData`,
  `test_staleWordingSurvivesBrowsingAfterADrop`,
  `test_waitingConnectorLeavesNoStaleHistory`,
  `test_connectorLifecycleIsCleanAcrossTransitions`,
  `test_liveSourceSwitchingReleasesTheSourceItLeaves`,
  `test_provenanceMirrorsTheWireInsteadOfAccumulating`,
  `test_staleResultIsNotReportedAsDisplayingWithoutALink`,
  `test_lostPeerIsNoticedWithoutADisconnectedEvent`,
  `test_nonConnectedConnectorDoesNotReportInvalid`,
  `test_acquisitionLinkReportsDisplayingAndInvalid`,
  `test_throttledResultEventStillGetsATrailingRefresh`,
  `test_connectLinksStartsAndStopsEveryLink`,
  `test_waitingLinkNamesItsProducer`,
  `test_uc1AndUc2WaitingTextExplainsTheirProducers`,
  `test_connectLinksWarnsWhileTheLaptopCameraHoldsIt`,
  `test_connectorEventsSurviveVtkStringDispatch`,
  `test_liveViewPanelSaysWhatItIsWaitingFor` (replaced by the capture tests).
- Control-link capture: `test_captureDisabledWithoutControlLink`,
  `test_capturePressSendsOneTrigger`, `test_captureStateReflectsStandInAnswers`,
  `test_captureTriggerDeclaresItsWireEncoding`.
- Abstract result roles and class selection:
  `test_resultPresentationForSupportedMapTypes`,
  `test_classColorTableMatchesUc1Palette`,
  `test_classMapSlicePipelineEmitsUc1Colors`,
  `test_resultValidationRejectsMalformedMaps`,
  `test_invalidResultLeavesResultViewEmpty`,
  `test_vectorProbabilityClassSelection`,
  `test_parameterNodeStoresResultReferencesByID`,
  `test_singleComponentMapIgnoresStaleClassSelection`,
  `test_classControlOnlyForVectorProbabilityMaps`,
  `test_resultSourceDiscoveryRequiresGenuineMarker`,
  `test_missingResultRestoresWaitingState`,
  `test_presentedResultIsNotRediscoveredAsSource`.
- Demo mode, banners and genuine-over-simulated precedence:
  `test_bannerWordingFollowsTheProducer`,
  `test_realPipelineResultIsBanneredWithoutCallingItUngenuine`,
  `test_simulatedSourceIsNotGenuine`, `test_demoModeDiscoversSimulatedSource`,
  `test_genuinePreferredOverSimulated`,
  `test_simulatedResultStillValidatedAgainstContract`,
  `test_simulationDetailNeverAffectsDiscovery`, `test_demoModeIsNotPersisted`,
  `test_simulatedProvenanceReachesResultNode`,
  `test_simulatedResultShowsPersistentBanner`,
  `test_bannerFailureWithholdsSimulatedResult`.
- Layers, UC2 reception, cube browser and background compositing:
  `test_layersAreIndependentlyControlled`,
  `test_uc2LayerObeysOriginGateAndPrecedence`,
  `test_invalidUc2LayerLeavesPanelBlack`, `test_bandBrowserReportsWavelength`,
  `test_backgroundIsCompositedUnderClassMap`,
  `test_mismatchedBackgroundIsNotComposited`,
  `test_backgroundWithDifferentProvenanceIsNotComposited`,
  `test_backgroundFromAnotherCaptureIsNotComposited`,
  `test_laterMapOnlyRunDoesNotReuseTheEarlierBackground`,
  `test_backgroundMatchingTheMapsCaptureIsChosen`,
  `test_cameraNodeIsNeverAnOverlayBackground`.

Kept, adjusted only where they reference removed controls:
`test_moduleMetadataAndUi`, `test_presentationParametersAndControls`,
`test_cameraFrameConversion`, `test_cameraBackendFallbackAndLifecycle`,
`test_cameraSupportAndFailureStates`, `test_openCvRequirementMatchesExtensionManifest`,
`test_cameraFrameUpdatesOnlyLiveView`, `test_layoutDescriptionContract`,
`test_headlessPresentationFallback`, `test_layoutContractAndLifecycle`,
`test_layoutRestoreIgnoresTransientEmptyLayout`,
`test_parameterNodeStoresVolumeReferencesByID`,
`test_reloadAndTestRunsPastSkippedTests`, `test_reservedPanelIsBlackWithStatedReason`,
`test_liveVolumeIsDisplayedUpright`, `test_operatorControlsHaveStatedReasons`.

## Manual verification

All steps use `SlicerWithSLIAFlow.exe` started by double-clicking it in File
Explorer, never from a terminal, so that any console window would be the app's
own. Before step 2, run `.\scripts\development\build-sliaflow.ps1` and confirm
every module file is `ok` in its Verify section.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `.\scripts\development\build-uc1.ps1` | Exit 0. Both `stratum.opt.exe` and `stratum.opt.intermediate.exe` are reported produced; each binary's warning check lists only its expected warnings; the SHA-256 assertion prints `All staged files are byte-identical` | Re-run 2026-09-17: exit 0. Both binaries were produced; each warning list contained only `#550-D` and `C4068`; the SHA-256 check printed `All staged files are byte-identical to workspace\components.` `build-sliaflow.ps1` also exited 0 and all 11 module files were `ok`. |
| 2 | Double-click `build\SLIAFlow\SlicerWithSLIAFlow.exe`, open SLIAFlow | Six panels. The panel has no Live source, Connect links, link rows, Result class, Demo mode, Layers or band slider. The result selector lists exactly `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, `imageRGB.bmp`. HS Cube, Stereoscopic, Relative StO2 and Enhanced Vascularization are black and each states why. The prototype notice is at the top. Tumour Delineation says it is waiting for a capture. Capture is disabled | Re-run matched: six panels, fixed camera label, all removed controls absent, five exact output names with the initial selection now `imageRGB.bmp`, four reserved panels black with reasons, prototype notice visible, Tumour Delineation waiting, and Capture disabled. |
| 3 | Press Start | Laptop camera is upright in LiveView; Capture becomes enabled; no console window appears in the taskbar | LiveView showed the laptop camera and Capture became enabled. The frame had no readable orientation cue for an independent rotation judgment. **FAIL for the no-console check:** a Windows Terminal/console window titled `C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe` remained visible in the taskbar/behind Slicer. The Slicer build still has `Slicer_BUILD_WIN32_CONSOLE=ON` and `Slicer_BUILD_WIN32_CONSOLE_LAUNCHER=ON` in `apps\SR\Slicer-build\CMakeCache.txt`. |
| 4 | Press Capture, then immediately press Capture again and move your hand in front of the camera | LiveView stops moving; the status names a recorded case and moves through capturing, running UC1 and validating; Capture is disabled; the second press has no effect; no console or terminal window appears at any point | Re-run froze the displayed frame, named case `016-05`, disabled Capture during the run, and completed with `Recorded case 016-05 - simulated acquisition. Showing imageRGB.bmp.` The immediate second invocation did not start another run. The fixture completed too quickly to separately read every transient status; physical hand motion was not reproducible in this unattended session. **FAIL for the no-console check** for the same launcher console described in step 3. |
| 5 | Open `workspace\captures` in File Explorer | One new `output_laptop_camera_<date>-<time>.png`; opened in Photos it shows the frozen frame the right way up | `output_laptop_camera_20260917-205431.png` was created (131,597 bytes), opened in Photos, and matched the frozen LiveView frame; direct image inspection showed the same orientation. |
| 6 | Wait for the run to finish | Status reads `Recorded case <case> - simulated acquisition`; LiveView moves again; Tumour Delineation shows `imageRGB.bmp` | **Passed on re-run:** case `016-05` finished successfully, LiveView resumed, and both the status and Tumour Delineation showed `imageRGB.bmp`. |
| 7 | Select each of the five names in turn, and open the same file from `build\uc1\UC1\gpu_single_bsq\source\output\<case>\` in Photos | Each selection changes the view; each image has the same orientation as Photos shows (not upside down, not mirrored) | **Passed on re-run:** native clicks selected `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, and `imageRGB.bmp`; each changed the displayed view, and the corresponding output images were inspected and matched the displayed orientation. |
| 8 | Press Capture four more times, one run at a time, noting the case each time | Five different cases in total; `058-02` never appears | **Passed on re-run:** the five cases were `016-05`, `043-02`, `036-02`, `040-02`, and `039-01`; all were different and `058-02` did not appear. |
| 9 | Rename `stratum.opt.intermediate.exe` to `stratum.opt.intermediate.exe.off`, press Capture | Status says the run failed, names the case and says the executable is missing and how to build it; LiveView resumes; the previous result stays on screen with `PREVIOUS RESULT - not from the current capture`. Rename it back, press Capture: the new result replaces it and the stale line disappears | **Passed on re-run:** with the executable renamed, the UI reported `Failed on recorded case 042-02` and the missing executable plus `scripts\development\build-uc1.ps1`; LiveView resumed and the previous case `039-01` remained with the `PREVIOUS RESULT` banner. Restoring the executable and pressing Capture produced case `055-02` showing `imageRGB.bmp`, and the stale banner disappeared. The executable was restored. |
| 10 | Press Capture and close Slicer from its window close button while the status still reads running UC1 (repeat if the run finishes first) | Slicer exits without an error dialog. Task Manager shows no `stratum.opt.intermediate.exe`, and `build\uc1\UC1\.uc1-runner.lock` does not exist | **Passed for shutdown/cleanup:** after Start and Capture, the `stratum.opt.intermediate.exe` child was observed while the window close button was used. The transient status text was too fast to capture as `Running UC1`; Slicer showed only its normal discard prompt, and `Exit (discard modifications)` was clicked. No Slicer/UC1 process or root/source `.uc1-runner.lock` remained. |
| 11 | Restart the app, open SLIAFlow, Start, Capture, wait for a result, then File > Close Scene; then switch to the Welcome module | Close Scene clears the panels and stops the camera with no Python console error; leaving the module restores the previous layout | **Passed on re-run:** after case `035-02`, File > Close Scene and `Close scene (discard modifications)` cleared all six views to their waiting/black states, reset Status to `Camera support is ready. Press Start to show the laptop camera.`, reset the result line to `No UC1 result yet. Press Capture.`, enabled Start, and disabled Stop/Capture. No Python-console error was visible. The module selector was opened and `Welcome to Slicer` was clicked; the conventional Welcome layout returned. |

Added 2026-09-18, for the recorded ground-truth layer. Pick a case with
tumour pixels: across the 61 cases, 35 have none at all, and `004-02` is one
of them. `053-01` (5,549 tumour pixels), `056-01` (4,081), `020-01` (3,655)
and `012-02` (3,139) are the richest.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 12 | Capture until a case with tumour pixels comes up, select `svm.bmp`, then select `gtMap` | The selector lists `gtMap` last. Selecting it keeps `svm.bmp` on screen and draws the database's labels over it at half opacity, in the same green/red/blue/black the classifier used. Unlabelled pixels stay clear, so most of the image still shows `svm.bmp` alone. The status line names both | Not yet performed |
| 13 | With `gtMap` selected, open the slice view's layer controls and change the Label opacity, then turn on outline mode | The ground truth responds to the Label layer's own opacity slider and outline toggle, because it is a label map and not a third colour image | Not yet performed |
| 14 | Select `knn.bmp`, then `kmeans.bmp`, with `gtMap` still on | The overlay follows the newly chosen output. `kmeans.bmp` is painted from cluster numbers, so its colours are not expected to agree with the ground truth; only `svm.bmp` and `knn.bmp` share the legend | Not yet performed |
| 15 | Press Capture again and wait for the new result | The ground truth changes with the result. At no point does one case's labelling sit over another case's result | Not yet performed |

## Risks

- **Scope.** The card touches about 8,000 lines of module and test code. The
  owner chose on 2026-09-17 to deliver it as one task; most of the change is
  deletion.
- **Hidden window.** Qt suppresses the child console only when Slicer has none of
  its own; confirm manually (steps 3, 4). Found on 2026-09-17: this Slicer build
  sets `Slicer_BUILD_WIN32_CONSOLE_LAUNCHER=ON` and `Slicer_BUILD_WIN32_CONSOLE=ON`,
  and `SlicerWithSLIAFlow.exe` is a console-subsystem program, so double-clicking
  it opens Slicer's own console window before UC1 ever runs. UC1 shares that
  window and adds none, but criterion 11 as worded cannot pass on this build.
  Owner decision pending (see Completion evidence, pre-review corrections).
- **Removing safeguards.** Demo mode and genuine-over-simulated precedence go
  away. Provenance tags and the prototype notice are what remain, so they must be
  tested, not assumed.
- **Shared output folder.** The Python runner writes the same files; the lock is
  the only protection.
- **Stale policy wording.** `.ai/policies/medical-data-policy.md` names "the
  banner and demo-mode interlock" as protections that this card removes. The
  rule it states - a detail must name the recorded case - still holds and is
  tested. The wording needs a follow-up policy edit outside this card.
- **A stale lock blocks every run.** A Slicer killed from Task Manager during a
  run leaves `.uc1-runner.lock`. SLIAFlow refuses rather than deletes it, and the
  message names the file.
- **First-run time.** The 60 s timeout has not yet been measured against the
  intermediate binary's cold start; step 6 records the observed time.

## Documentation impact

- New ADR-0003; status headers of ADR-0001 and ADR-0002.
- `SLIAFLOW_UC1_IMAGE_CONTRACT.md` and `openigtlink_setup.md`: the operator
  workflow no longer uses ports 18944, 18945, 18947, 18950 or their messages.
- `uc1_local_build.md`: the intermediate binary and its warnings.
- `uc1_demo_runbook.md` and `extensions/SLIAFlow/README.md`: the in-Slicer
  workflow.
- `SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: the in-Slicer run replaces the producer
  processes for the operator workflow.

## Implementation decisions

Owner decisions at specification, 2026-09-17:

- HS Cube panel: black with a stated reason; band slider removed.
- Layers table and Layer opacity slider: removed.
- UC1 run timeout: 60 s.
- Delivery: one task, one branch.
- ADR-0003 accepted by the project owner on 2026-09-17, before any module code
  was written. ADR-0001 and ADR-0002 status headers updated accordingly.

## Completion evidence

Recorded 2026-09-17 on branch `feature/SLIA-027-integrated-slicer-capture-uc1`,
created from `main` at `ce43135`. Nothing is staged or committed.

### UC1 build (acceptance criterion 10, automated part of manual step 1)

`.\scripts\development\build-uc1.ps1`, exit 0:

- `stratum.opt.exe` (951,808 bytes) and `stratum.opt.intermediate.exe`
  (1,406,464 bytes) produced.
- Warnings, each binary: `present #550-D`, `present C4068`, nothing unexpected.
  The intermediate command line emits the same two warnings as the release one,
  so both lists are the same.
- SHA-256 assertion: `gpu_single_bsq\source` 37 files and `svm_model` 5 files
  compared; `All staged files are byte-identical to workspace\components.`

### Real-output facts checked before writing the validator

- `stratum.opt.intermediate.exe C:\stratum\input\bin\bin\004-02`, run from
  `gpu_single_bsq\source` in a terminal: exit 0, 2.40 s wall,
  `Time simulation ---> 719.150 ms`, `KMeansIterations: 18`.
- `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, `imageRGB.bmp`: 403,058 bytes
  each, which is `54 + 389 * (3 * 345 + 1)`. `CalibratedImage_BIP.bmp`: 402,669
  bytes, unpadded.
- `pca.bmp` header: `BM`, `bfSize` 402,669 (not the file length), offset 54,
  `biSize` 40, 345 x 389, 1 plane, 24-bit, compression 0, `biSizeImage` 0.

### Red run: new and changed tests against unchanged production code

`.\scripts\development\run-slicer-tests.ps1` (headless), exit 1: `Ran 107`,
`FAILED (failures=17, errors=34, skipped=7)`. Every failure and error was a new
or changed test; all pre-existing tests passed.

- BMP reader tests (4): `ModuleNotFoundError: No module named 'SLIAFlowLib.SLIAFlowBmpReader'`.
- Case pool tests (4): `ModuleNotFoundError: No module named 'SLIAFlowLib.SLIAFlowCasePool'`.
- Run, repository-root, real-QProcess and output tests (8):
  `ModuleNotFoundError: No module named 'SLIAFlowLib.SLIAFlowUc1Run'`.
- Capture-flow, provenance, stale and cleanup tests (11):
  `AttributeError: 'SLIAFlowLogic' object has no attribute 'setRunEnvironment'`.
- `test_presentationParametersAndControls`:
  `AttributeError: 'SLIAFlowParameterNode' object has no attribute 'resultOutput'`.
- `test_resultSelectorListsTheFiveOutputFiles`:
  `RuntimeError: Widget with name='resultOutputSelector' does not exist.`
- `test_operatorControlsHaveStatedReasons`: `AssertionError: Lists differ:
  ['bandSlider', 'captureButton', 'connectLin...] != ['captureButton', 'resultOutputSelector', ...]`.
- `test_operatorPanelHasNoLinkDemoOrLayerControls`, 16 subtests, for example
  `AssertionError: QComboBox(..., name="liveSourceSelector") is not None`.

`.\scripts\development\run-slicer-tests.ps1 -Headful`, exit 1: `Ran 107`,
`FAILED (failures=19, errors=34, skipped=1)`. The two additional failures are
`test_reservedPanelIsBlackWithStatedReason`:
`AssertionError: 'not displayed' not found in 'waiting for the hs cube on port 18947.\npress capture.'`
and `AssertionError: 'slia-021' not found in 'waiting for the uc2 blood-vessel map on port 18946.'`.

`test_parameterNodeStoresVolumeReferencesByID` was adjusted only to stop using
the removed `resultVolume` reference and passes on both old and new code; it
guards kept behaviour, not new behaviour.

### Test corrections made while going green

- `test_operatorPanelHasNoLinkDemoOrLayerControls` first used
  `slicer.util.findChild(...) is None`, which raises `RuntimeError` for a missing
  name. It now asserts `findChildren(..., name=name) == []`, which still fails on
  the old panel because each control exists there.
- `slicer.app.applicationDirPath` is a method under PythonQt; the two tests that
  used it as a property now call it.
- `test_repositoryRootIsFoundFromModuleLocation` compared an 8.3 short temporary
  path (`ALEJAN~2`) with the resolved long path; both sides are now resolved.

### Mutation checks

- Reader made to trust `bfSize` (temporary edit, then restored from a copy):
  headless run exit 1, `FAILED (errors=3)`, only
  `test_bmpReaderAcceptsPaddedWriterOutput` for widths 5, 6 and 7:
  `BmpFormatError: bfSize 99 != 102`, `108 != 114`, `117 != 126`. Width 4 (no
  padding) passes, as it should.
- `test_selectedOutputIsShownAloneWithStaleLineOnTheView` was added during
  implementation, because no test asserted what reaches the Tumour Delineation
  view. With `_showResult` never binding and the stale line never drawn
  (temporary edit, then restored from a copy): headful run exit 1,
  `FAILED (failures=4)`: `AssertionError: None != 'vtkMRMLVectorVolumeNode6'`
  (and two more selections), and
  `AssertionError: unexpectedly None : No stale line was drawn while the capture processes`.

### Green runs on the final code

| Check | Command | Result |
| --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | exit 0, `Python quality checks passed.` |
| Lint | `.venv\Scripts\ruff check extensions/SLIAFlow` | `All checks passed!` |
| Whitespace | `git diff --check` | clean |
| Source, headless | `.\scripts\development\run-slicer-tests.ps1` | exit 0, `Ran 46`, `OK (skipped=4)`: the layout lifecycle, layout restore, reserved-panel and view-binding tests need a window |
| Source, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | exit 0, `Ran 46`, `OK (skipped=1)`: the headless-only fallback test |
| Launcher rebuild | `.\scripts\development\build-sliaflow.ps1` | exit 0, all 11 module files `ok`, `The build tree matches the working tree.` |
| Build, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | exit 0, module loaded from `build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules`, `Ran 46`, `OK (skipped=1)` |

`Ran 46` is 45 `SLIAFlowTest` methods plus the imported base class, as
`testing_strategy.md` explains. `test_realQProcessReportsOutputAndExitCode` ran
and passed in every run; it was not skipped.

The test file has 62 tests fewer than on `main` and 30 new ones. The deleted
set was compared with the list under Test plan: identical.

### Real run inside Slicer, no window

A developer check, not part of the suite: `Slicer.exe --no-main-window
--additional-module-paths extensions\SLIAFlow\SLIAFlow --python-script <scratch
script>` called `SLIAFlowLogic.startUc1Run` on recorded case `004-02` with the
real `QProcess` and the real binary. Exit 0. `repositoryRoot: C:\stratum`; lock
held during the run and absent after; stages `running`, `validating`; 2.05 s;
`UC1 finished on recorded case 004-02 in 2.0 s.`; all five outputs accepted as
`(1, 389, 345, 3) uint8` with the shared capture ID and detail
`real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`.

Case discovery over `input\bin\bin`, read-only: 60 compatible cases; rejected
only `058-02` (`deferred until SLIA-029 verifies it`); no case path reaches the
128-character limit.

### Pre-review corrections (findings supplied by the project owner, 2026-09-17)

Four findings were supplied before review. They are recorded here, not under
Review findings, because the independent review stage has not started.

| # | Finding | Verdict | Change |
| --- | --- | --- | --- |
| 1 | High: a new result keeps the previous case's framing, because `_showResult` fitted only when the node ID changed and nodes were reused | Confirmed | `_showResult` refits whenever the result's capture ID differs from the one the view was framed for; `acceptOutputs` also creates new nodes per result |
| 2 | High: "no console window" not established; plain `QProcess` sets no `CREATE_NO_WINDOW` | UC1 part refuted; criterion 11 open for a different reason | Qt 5.15.2 `qprocess_win.cpp:556-561` passes `CREATE_NO_WINDOW` when Slicer has no console and otherwise lets the child share Slicer's; PythonQt exposes no creation-flag hook. Guard test added. The launcher itself is a console program (Risks, Hidden window) |
| 3 | Medium: an exception other than `ValueError` while publishing leaves Capture disabled and LiveView frozen, and can half-replace the previous result | Confirmed | `acceptOutputs` writes five new, unowned nodes and swaps them in only when all five are complete, removing them on any error; `_onUc1Finished` and `_onCaptureClicked` end the capture on any exception |
| 4 | Low: surfaced failure messages bypass Slicer translation | Confirmed | Every operator-facing message in `SLIAFlowUc1Run.py` and the logic goes through `slicer.i18n.tr` (import guarded, so the module still loads outside Slicer); the no-compatible-case message is built in the widget, so `SLIAFlowCasePool.py` keeps no `slicer` import. BMP header details stay as written inside a translated sentence |

Tests added: `test_resultOfAnotherSizeIsFittedToTheView` (headful),
`test_publishingErrorEndsCaptureAndKeepsPreviousResult`,
`test_surfacedFailureMessagesAreTranslated` (13 subtests) and
`test_uc1ProcessOpensNoConsoleWindowOfItsOwn`. The real-process lookup was
moved into `_slicerPythonOrSkip`.

Red run, unchanged production code, `.\scripts\development
un-slicer-tests.ps1 -Headful`:
exit 1, `Ran 50`, `FAILED (failures=12, errors=1, skipped=1)`, only in the new tests:

- `test_publishingErrorEndsCaptureAndKeepsPreviousResult`: `RuntimeError: test: the MRML update failed` escaped the capture.
- `test_resultOfAnotherSizeIsFittedToTheView`: `AssertionError: 4.6049999999999995 != 12.0 within 3 places ... The new result kept the previous case's framing`.
- `test_surfacedFailureMessagesAreTranslated`: all 11 helper subtests `Not translated: ...`, and `'[translated] No compatible recorded case' not found in 'Failed: No compatible recorded case was found in ...'`.

`test_uc1ProcessOpensNoConsoleWindowOfItsOwn` passed on unchanged code: the
behaviour belongs to Qt. To show the test can fail, a scratch probe inside
`Slicer.exe --no-main-window` (no console) compared children: started by
`QProcess`, console window `0`, check passes; started with `CREATE_NEW_CONSOLE`
(hidden), console window `10095752`, check fails.

Green runs after the corrections:

| Check | Result |
| --- | --- |
| `run-slicer-tests.ps1 -Headful` | exit 0, `Ran 50`, `OK (skipped=1)` |
| `run-slicer-tests.ps1` (headless) | exit 0, `Ran 50`, `OK (skipped=5)`: the three earlier view tests, the new framing test, layout lifecycle |
| `build-sliaflow.ps1` | exit 0, `The build tree matches the working tree.` |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, `Ran 50`, `OK (skipped=1)` |
| `run-python-quality.ps1`, `ruff check`, `git diff --check` | exit 0, passed, clean |
| Real UC1 run in Slicer, outputs accepted twice | exit 0, case `004-02` in 0.9 s, lock released; after the second accept 5 volumes, named `SLIAFlow UC1 <file>`, first set removed |

### Corrections after manual verification (2026-09-17)

Two of the three manual failures were module defects and are fixed. The third,
the launcher console, is not a module defect and stays an owner decision.

| Step | Observed defect | Cause | Change |
| --- | --- | --- | --- |
| 6 | The first result was shown as `pca.bmp`, not the declared default `imageRGB.bmp` | `connectGui` builds the combo-box connector by clearing and refilling the box (`guiConnectors.py:440-442`), which emits `currentIndexChanged` before `_connectParametersToGui` writes the stored value back (`wrapper.py:209-210`). The widget's own slot took that first index for an operator choice and wrote `pca.bmp` into the parameter node | `setParameterNode` sets `_bindingResultSelector` while `connectGui` runs and `_onResultOutputChanged` ignores the signal during it; the status and the view are refreshed once the binding is complete |
| 11 | After Close Scene the Status panel still read `Done: UC1 results for recorded case ...` | `onSceneStartClose` reset the result line through `_forgetResult` but never touched `statusLabel` | `onSceneStartClose` ends with `_setCameraSupportState(...)`, the same idle line a freshly opened module shows |
| 3, 4 | A console window belongs to `SlicerWithSLIAFlow.exe` | `Slicer_BUILD_WIN32_CONSOLE=ON` and `Slicer_BUILD_WIN32_CONSOLE_LAUNCHER=ON` in this build | None. Owner decision, below |

Tests added, both named after the manual step they come from:
`test_bindingThePanelKeepsTheDeclaredDefaultOutput` and
`test_closingTheSceneClearsTheStatusPanel`.

Red run, unchanged production code, `.\scripts\development\run-slicer-tests.ps1 -Headful`:
exit 1, `Ran 52`, `FAILED (failures=2, skipped=1)`, only the two new tests:

- `AssertionError: 'pca.bmp' != 'imageRGB.bmp' : Binding the panel overwrote the stored output selection`.
- `AssertionError: '004-02' unexpectedly found in 'Done: UC1 results for recorded case 004-02 are shown. Snapshot saved as output.png.' : Close Scene kept the previous result's status`.

Green after the fixes:

| Check | Result |
| --- | --- |
| `run-slicer-tests.ps1 -Headful` | exit 0, `Ran 52`, `OK (skipped=1)` |
| `run-slicer-tests.ps1` (headless) | exit 0, `Ran 52`, `OK (skipped=5)` |
| `build-sliaflow.ps1` | exit 0, all 11 module files `ok`, `The build tree matches the working tree.` |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, `Ran 52`, `OK (skipped=1)` |
| `run-python-quality.ps1`, `ruff check`, `git diff --check` | exit 0, `All checks passed!`, clean |

### Owner-requested changes after manual verification (2026-09-18)

Authorised by the project owner in session, explicitly including anything that
falls outside the approved scope. All four changes are in files this card
already allows.

| Request | Change |
| --- | --- |
| The six panels must name only the input they wait for: no institution, no repository, no task, no port | `RESERVED_PANEL_REASONS`, `LIVE_WAITING_MESSAGE` and `WAITING_RESULT_MESSAGE` are now one `Waiting for ...` line each; `STEREOSCOPIC_PORT` and `STO2_PORT` are gone from the module |
| A displayed volume must be named after the image it holds, not the module | `OUTPUT_VOLUME_NAME_FORMAT` is `{fileName}` and `LIVE_VOLUME_NAME` is `LiveView`; the cube is `raw.dat`. Nothing looks a node up by name, so no lookup changed |
| Show the HS cube the capture stands for | `SLIAFlowCasePool.readCube` reads the chosen case's `raw.dat` as a `(bands, lines, samples)` uint16 array; `SLIAFlowLogic.acceptCube` puts it in one module-owned `vtkMRMLScalarVolumeNode` with the run's own provenance attributes; the widget binds it to HS Cube as soon as the case is chosen and opens it at the middle band, so the slice slider scrolls the spectrum |
| Explain the Developer section | No code change; answered in session. It holds the camera index, the camera-support installer and the result-source line, all three developer aids rather than operator controls, which is why it is collapsed by default |

The cube is the input of the run, not its result, so a cube that cannot be read
never fails the capture: the panel keeps its waiting line and UC1 runs on the
case regardless. Reading the cube is approved by
`.ai/policies/medical-data-policy.md`, which lists the HSI Human Brain Database
as approved for "the cube behind the WP5 demonstrator". Nothing is written to
`input/`, and the capture snapshot still records only the camera frame.

New tests:

- `test_panelTextNamesOnlyWhatThePanelWaitsFor`
- `test_volumeNamesAreTheImageAndNothingElse`
- `test_capturedCubeIsShownBandByBand`
- `test_unreadableCubeDoesNotFailTheCapture`
- `test_cubeReachesTheCubePanelAndNowhereElse`

`test_reservedPanelIsBlackWithStatedReason` was updated to the new wording.

Seen red first. The build tree still held the previous module, so only the test
file was staged into it and `run-slicer-tests.ps1 -Target Build -Headful` ran the
new tests against the unchanged production code: exit 1, `Ran 57`,
`FAILED (failures=13, errors=4, skipped=1)`.

- `AttributeError: 'SLIAFlowLogic' object has no attribute 'acceptCube'`.
- `AttributeError: 'SLIAFlowLogic' object has no attribute 'cubeNode'`.
- `AssertionError: 'waiting for' not found in 'no producer yet: stereoscopic depth from upm.\nport 18948 is reserved for it.' : The panel does not say what it is waiting for`.
- `AssertionError: 'waiting for' not found in 'the hs cube is not displayed.\nuc1 reads the recorded case from disk\nwhen capture is pressed.' : The panel does not say what it is waiting for`.
- `AssertionError: 'SLIAFlow UC1 imageRGB.bmp' != 'imageRGB.bmp'`.

The build tree's own test file was restored afterwards and the build script
re-staged everything.

One defect was found by these tests rather than by inspection: the first
`_showMiddleBand` called `vtkMRMLSliceLogic.GetSliceOffsetRange`, whose
`AttributeError` escaped `_showCube` and ended the capture before UC1 started.
Three existing headful tests failed with `Capture did not start a UC1 run`. The
band is now taken from the volume's own S bounds, and `_showCapturedCube` holds
both the read and the draw inside one guard, so neither can reach the capture.

Green:

| Check | Result |
| --- | --- |
| `run-slicer-tests.ps1 -Headful` | exit 0, `Ran 57`, `OK (skipped=1)` |
| `run-slicer-tests.ps1` (headless) | exit 0, `Ran 57`, `OK (skipped=6)` |
| `build-sliaflow.ps1` | exit 0, all 11 module files `ok`, `The build tree matches the working tree.` |
| `run-slicer-tests.ps1 -Target Build -Headful` | exit 0, `Ran 57`, `OK (skipped=1)` |
| `run-python-quality.ps1`, `ruff check`, `git diff --check` | exit 0, `All checks passed!`, clean |

Not verified by hand. Nobody has yet looked at the new panel wording, the new
volume names or the HS Cube panel in the built app. The owner re-runs manual
verification.

### Owner-requested change after manual verification (2026-09-18, ground truth)

Requested by the project owner in session: a sixth entry in the Delineation
output box showing the recorded case's ground truth, so that a result can be
read against the real labelling. The owner chose the label-map form over a
plain sixth image, and chose to amend this card rather than open a new task.

Three findings shaped the design, all read out of the sources rather than
assumed:

- `gtMap` and `gtMap.hdr` are one ENVI pair. The owner asked which of the two
  to use; the answer is both, and there is only one ground truth per case.
- `FOUR_COLORS_MAP` in `BitmapWriter.hpp` is indexed by the same class IDs
  `gtMap.hdr` legends, so `svm.bmp` and `knn.bmp` already carry the ground
  truth's legend and can be read against it directly. `kmeans.bmp` is painted
  from `COLOR_MAP` with arbitrary cluster numbers and `pca.bmp` is not a
  classification, so neither can be. This is recorded because it is the whole
  reason the overlay is meaningful, and it is pinned by a test.
- The ground truth is sparse. Across the 61 cases in `input/bin/bin`, between
  0.0% and 16.2% of pixels carry a class, and `FOUR_COLORS_MAP` paints the
  unlabelled class white. That is why class 0 is given zero opacity instead:
  a faithful render of the table would sheet white over the result almost
  everywhere. 35 of the 61 cases hold no tumour pixels at all, which is why
  the new manual steps name cases that do.

No accuracy, agreement or confusion figure is computed. The owner was offered
one and did not take it; `.ai/policies/medical-data-policy.md` withholds
approval for exactly that, so it stays out of scope and a separate decision.

### Not done

- Manual verification steps 1-11 were re-exercised in the built app by Codex on
  2026-09-17 and their fresh observations are recorded in the table above. The
  physical hand-motion portion of step 4 could not be reproduced in this
  unattended session. Steps 3-4 still fail the no-console expectation, which is
  not a module defect. The earlier step 6 and 11 module defects passed after the
  corrections.
- Criterion 11 (no console window) can only be observed manually, and on this
  Slicer build the launcher's own console window is expected to appear. The owner
  decides whether to rebuild Slicer with the console options off (`apps/` is
  protected), reword the criterion to "UC1 opens no console window of its own",
  or have SLIAFlow hide Slicer's console.
- The 2026-09-18 owner-requested changes above have not been seen by anyone in
  the built app: the panel wording, the volume names and the HS Cube panel need
  manual verification, together with steps 6 and 11.
- Independent review and human approval have not started. The task stays in
  `tasks/active/`; moving it to review needs separate authorization.

## Review findings

## Human approval
