---
id: SLIA-033
title: Run UC1 on the calibrated float32 LCTF cube through documented patches
status: completed
branch: feature/SLIA-033-uc1-accepts-calibrated-float32-cube
priority: high
depends_on: SLIA-032
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-033 - Run UC1 on the calibrated float32 LCTF cube through documented patches

## Goal

Capture runs UC1 on `002-04`, IUMA's calibrated float32 cube, and the five
outputs appear in the Tumour Delineation panel as they do today for the
reference case. UC1 changes are versioned patches applied at staging, each
documented with its result, and the SVM model is not retrained.

## Context

What UC1 does today (`gpu_single_bsq/source`, checked 2026-09-24):

- Takes a folder argument and reads `raw.dat`, `whiteReference.dat` and
  `darkReference.dat`, all uint16 BSQ, the references as full cubes the size of
  `raw`. Dimensions come from `raw.hdr`; `data type` is never read.
- Calibrates with `100 * (raw - dark) / (white - dark)`
  (`calibrateAndConvertToBIP_Tiled`), converting to BIP.
- `normalizeImgKernel_optimized` then rescales each pixel to its own minimum and
  maximum over the bands.
- PCA to one band (its own Jacobi eigen-solver), linear SVM (`w_vector` 93 x 6,
  4 classes), KNN filter, K-means with 24 clusters, majority vote.
- Reads `../../svm_model/w_vector.bin` with the header's band count and never
  checks how much it read. A 109-band header overreads and gives garbage weights
  without any error.
- `MAX_PATH_LENGTH` is 128; a longer path makes it exit 0 without writing.
- `build-uc1.ps1` stages the vendored tree into `build/uc1/UC1` and asserts the
  staged files are byte-identical to `workspace/components`.

What `002-04` is: float32 BSQ, 1080 x 1080 x 109, 460-1000 nm, already
calibrated by IUMA, values in [0, 1.5], no NaN or infinity in 460-900 nm, no
full-size references, no `gtMap`. The file is named
`LCTF_Calibrated_Cube_Single`, not `raw`.

`ADR-0004` decisions 3 to 6 govern this task: patches at staging, a documented
109-to-93 band mapping, behavioural results only, float32 input validation.

### Measured at specification (2026-09-24/25, scratch copies only)

A scratch copy of the vendored source, patched and built with the
`build-uc1.ps1` command line, was run outside the repository.

1. **The unpatched UC1 is not deterministic.** Seven runs of the current staged
   `stratum.opt.intermediate.exe` on `020-01` gave byte-identical `pca.bmp`,
   `svm.bmp`, `knn.bmp` and `CalibratedImage_BIP.bmp`, but a different
   `kmeans.bmp` and `imageRGB.bmp` every time: up to 0.32 % and 0.19 % of
   pixels differ between two unpatched runs, with all 24 clusters and 4
   classes present each time. The acceptance criterion "byte-identical before
   and after the patches" is therefore stated for the four deterministic
   images, with a bound for the two K-means images.
2. **The ADR-0004 mapping makes UC1's PCA divide by zero.** Model bands 1-5
   (440-460 nm) all carry the 460 nm band, so the covariance matrix has equal
   diagonal entries for them and the Jacobi step
   `pca_alpha = a_ij / (a_jj - a_ii)` divides by zero. On `002-04` `pca.bmp`
   came out black and `knn.bmp` and `imageRGB.bmp` a single class. Using the
   exact 45 degree rotation when the two diagonal entries are equal fixes it;
   `020-01` stayed byte-identical. The project owner chose to add this as patch
   0003 (2026-09-25).
3. **Feasibility.** With the three patches the 1080 x 1080 x 93 run took 2.7 s
   wall time (2.1 s reported by UC1) on the RTX 5050, within the 60 s run
   timeout; writing the mapped 93-band cube took 0.4 to 0.7 s. The band guard
   refused a 109-band header with exit code 1 before creating any output.

### Decisions taken at specification

- **The band mapping runs in SLIAFlow**, in one new module
  (`SLIAFlowUc1Input.py`), and is described in one document
  (`docs/development/uc1_changes.md`). Reasons: the mapping can then be
  asserted band by band in `SLIAFlowTest` as `ADR-0004`'s Validation section
  requires; UC1's patches stay limited to reading a calibrated cube; and the
  same step solves the file name. UC1 never sees 109 bands.
- **Input file name.** At every Capture SLIAFlow writes the mapped cube as
  `raw.dat` plus `raw.hdr` (ENVI float32, 93 bands) into the gitignored run
  folder `build/uc1/UC1/input/<cube>/`, and passes that folder to UC1. Nothing
  is written into `input/`.
- **Units.** UC1's own calibration yields percent (`100 * ...`). The float32
  path multiplies IUMA's reflectance by 100 in the same transpose kernel, so
  every later stage sees the units it sees on a uint16 cube.
- **SLIAFlow stops running the recorded uint16 case.** `ADR-0004` decision 1
  makes `002-04` the one cube the module works with; the reference case is
  checked outside Slicer by `scripts/development/check-uc1.py`. The
  recorded-case loader (`loadRecordedCase`, `assertCaseUnchanged`,
  `cubeFolder`) is removed; ENVI header parsing and ground-truth reading stay,
  with ground truth looked for beside the configured cube.
- **`gtMap` in the output selector.** The parameter-node combo box connector
  selects by index, so the entry is kept in the list but hidden from the popup
  and disabled while the result's cube has no ground truth. A stored `gtMap`
  selection then shows the chosen output alone and the status says the cube has
  no ground truth.

## Requirements

- **Patches, not edits.** `scripts/development/uc1-patches/` holds numbered
  unified diffs, applied in name order by `build-uc1.ps1` to the staged copy
  with `git apply`. A patch that does not apply fails the build. The hash check
  compares the staged tree with a fresh copy of the vendored tree plus the same
  patches. The vendored copy stays unchanged. A `.gitattributes` in the patch
  folder keeps the patches LF (`core.autocrlf` is on).
- **Patch 0001, band guard.** UC1 exits nonzero with a message, before reading
  any image, when the header's band count does not match the size of
  `w_vector.bin`, or when that file cannot be opened.
- **Patch 0002, float32 calibrated input.** When `raw.hdr` declares data type 4,
  UC1 reads `raw.dat` as calibrated float32 BSQ, never opens references, and
  replaces its calibration with a scale by 100 and the BSQ-to-BIP transpose. A
  short read or failed allocation exits nonzero. Data type 12 or absent keeps
  the uint16 path, whose code is unchanged; any other data type is refused.
- **Patch 0003, equal diagonal in the Jacobi step.** When the two diagonal
  entries are exactly equal, rotate by 45 degrees instead of dividing by zero.
  Otherwise unchanged.
- **Band mapping.** 460-900 nm feed model bands 5-93 one to one; model bands
  1-4 (440-455 nm) take the 460 nm band; 905-1000 nm are dropped. A cube whose
  wavelengths are not exactly the LCTF grid 460-1000 nm in 5 nm steps (109
  bands, within 0.01 nm) is refused before UC1 starts.
- **SLIAFlow.** Capture runs UC1 on the configured calibrated cube through the
  mapped run folder. The cube is re-described immediately before the run and
  refused if it changed since Capture: other dimensions, or any write to or
  replacement of its header or data file, including one that keeps the size
  (size, last write time and file ID recorded at Capture). It is checked again
  after it is copied for UC1, and a refused copy is removed. Input validation
  per `ADR-0004` decision 6. The `gtMap` entry is offered only when the cube
  has a `gtMap` beside it; otherwise the panel says there is no ground truth
  for this cube. Every status that describes a result on screen, fresh or
  stale, says results on the LCTF cube are not validated (decision 5). Output
  provenance per decision 7.
- **Reference check.** `scripts/development/check-uc1.py` runs the staged build
  on `020-01` and on a 109-band header. It passes only if `pca.bmp`, `svm.bmp`,
  `knn.bmp` and `CalibratedImage_BIP.bmp` match the SHA-256 recorded from the
  unpatched build, `kmeans.bmp` and `imageRGB.bmp` differ from a saved
  unpatched run in at most 1 % of pixels, and the band guard refuses.
- **Patch checks.** `check-uc1.py` also checks each patch's own paths against
  an oracle computed outside UC1: `020-01` calibrated in NumPy as UC1 does it
  and run as a float32 cube (`CalibratedImage_BIP.bmp` byte-identical to its
  prediction; `pca`, `svm`, `knn` within 0.1 % of the uint16 run); the same
  cube with bands 1-4 equal to band 5 (`pca.bmp` within one grey level of
  NumPy's first principal component); a float32 cube one value short
  (refused); and UC1 run where `../../svm_model` does not exist (refused by
  the band guard).
- **Record.** `docs/development/uc1_changes.md`: one section per patch saying
  what it changes, why, the command run and what came out, with timing; the
  band mapping; the reference-check baseline.

## Out of scope

- Retraining or editing the SVM model.
- Tuning parameters or speed (`SLIA-034`).
- Reading the raw uint16 LCTF cube.
- Making UC1's K-means deterministic.
- Receiving the cube over the network (`SLIA-030`).

## Files allowed

- `scripts/development/build-uc1.ps1`
- `scripts/development/uc1-patches/.gitattributes` (new)
- `scripts/development/uc1-patches/0001-band-guard.patch` (new)
- `scripts/development/uc1-patches/0002-calibrated-float32-input.patch` (new)
- `scripts/development/uc1-patches/0003-jacobi-equal-diagonal.patch` (new)
- `scripts/development/check-uc1.py` (new)
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCube.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCalibratedCube.py` (docstring only)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/README.md`
- `docs/development/uc1_changes.md` (new)
- `docs/development/uc1_local_build.md`
- `docs/development/uc1_demo_runbook.md`
- `tasks/{backlog,active,review,completed}/SLIA-033-uc1-accepts-calibrated-float32-cube.md`
- `input/README.txt` (gitignored; never staged)
- `build/uc1/` (gitignored build output: staged tree, run folder, the saved
  unpatched reference run; never staged)

## Relevant skills and references

- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- UC1 `main.cu`, `functions_cuda.cu`, `functions.cu`, `data_loader.cpp`,
  `GUIDE.md`
- `scripts/development/build-uc1.ps1`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`
- Slicer skill: `parameterNodeWrapper` `QComboBoxToStringableConnector`
  (`source/Base/Python/slicer/parameterNodeWrapper/guiConnectors.py`) selects
  by index, which is why the `gtMap` entry is hidden rather than removed.

## Implementation plan

1. Save the unpatched reference run (already measured) under
   `build/uc1/reference-unpatched/` and record its hashes.
2. Write the three patches from the scratch copy; add patch application and the
   original-plus-patches hash check to `build-uc1.ps1`; build.
3. Write `check-uc1.py`; run it on the patched build.
4. Write the new and changed tests and observe them failing against the current
   module.
5. Add `SLIAFlowUc1Input.py`; adapt the run, cube, logic, widget and parameter
   node modules; remove the recorded-case loader.
6. Run Ruff and the Slicer tests, headless and headful.
7. Write `uc1_changes.md`; update the build document, runbook, module README
   and `input/README.txt`.

## Acceptance criteria

1. The vendored copy is unchanged; the staged tree equals a fresh copy of the
   vendored tree plus the patches in order; the build fails when a patch does
   not apply.
2. UC1 on a cube whose band count differs from the model's, or without its
   SVM weights, exits nonzero with a message before reading any image.
3. The reference case's `pca.bmp`, `svm.bmp`, `knn.bmp` and
   `CalibratedImage_BIP.bmp` are byte-identical before and after the patches,
   and its `kmeans.bmp` and `imageRGB.bmp` differ from an unpatched run in at
   most 1 % of pixels.
4. Each of the 93 model bands is fed from the source band the `ADR-0004`
   mapping names.
5. A calibrated cube whose wavelengths or band count do not fit the mapping, or
   whose header and data disagree, is refused before UC1 starts, with the
   reason on the panel.
6. The input UC1 reads is the mapped cube, written under `build/uc1/UC1/input/`,
   byte-for-byte the mapped source bands, with a 93-band float32 header; nothing
   is written into `input/`.
7. Capture runs UC1 on the configured calibrated cube and shows its five
   outputs, carrying the provenance of `ADR-0004` decision 7.
8. A cube that changed on disk between Capture and the run, or while it was
   copied for UC1, is refused rather than run on, including a same-size rewrite
   in place and a same-size file moved over it with the same write time.
9. The `gtMap` entry is offered only for a cube with a `gtMap` beside it;
   otherwise the panel says the cube has no ground truth.
10. Every status that describes a result on screen says UC1 results on the
    LCTF cube are not validated: a fresh result, one under its ground truth,
    one whose ground truth could not be read, and the previous result while a
    capture runs and after it fails.
11. Capture on the real `002-04` in the built application produces five
    1080 x 1080 outputs with structure in `pca.bmp`, `knn.bmp` and
    `imageRGB.bmp`.
12. Every patch has its written record with command, result and timing.
13. On `020-01` calibrated in NumPy as UC1 does it and given as a float32 cube,
    `CalibratedImage_BIP.bmp` is byte-identical to the image predicted from the
    cube, `pca.bmp`, `svm.bmp` and `knn.bmp` differ from the uint16 run in at
    most 0.1 % of pixels, and a copy one value short is refused.
14. On that cube with bands 1-4 equal to band 5, `pca.bmp` is within one grey
    level of the first principal component NumPy computes, on every pixel.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Vendored unchanged; staged = original + patches; failing patch fails the build | Manual step 1 (build with patches) and step 2 (build with a patch that does not apply) | manual |
| 2. Band guard refuses before reading images | `check-uc1.py` band-guard and missing-weights checks, run in manual step 3 | manual |
| 3. Reference outputs unchanged | `check-uc1.py` reference check, run in manual step 3 | manual |
| 4. Mapping feeds each model band from the named source | `SLIAFlowTest.test_bandMappingFeedsEachModelBandFromTheDocumentedSource` | automated |
| 5. Off-grid or inconsistent cube refused with reason | `SLIAFlowTest.test_bandMappingRefusesACubeOffTheLctfGrid`, `test_configuredCubeIsRefusedWithItsReason`, `test_cubeRefusalReasonsAreTranslated`, `test_calibratedCubeRejectsIncompatibleContents` | automated |
| 6. UC1 reads the mapped cube, written outside `input/` | `SLIAFlowTest.test_uc1InputIsTheMappedCubeWrittenOutsideInput` | automated |
| 7. Capture runs on the configured cube, five outputs, provenance | `SLIAFlowTest.test_captureRunsUc1OnTheConfiguredCalibratedCube`, `test_outputNodesCarrySharedCaptureIdAndProvenance` | automated |
| 8. Cube changed on disk is refused, same size included | `SLIAFlowTest.test_cubeChangedOnDiskIsRefusedRatherThanRunOn` | automated |
| 7 and 8. A cube chosen in one run environment does not carry into the next | `SLIAFlowTest.test_runEnvironmentChangeRestoresTheDefaultCube` | automated |
| 9. `gtMap` only with ground truth; otherwise stated | `SLIAFlowTest.test_groundTruthEntryIsOfferedOnlyForACubeThatHasOne` and the existing ground-truth tests on a cube that has one | automated |
| 10. Every result status says results are not validated | `SLIAFlowTest.test_resultStatusSaysLctfResultsAreNotValidated` | automated |
| 11. Real `002-04` in the built application | Manual step 4 | manual |
| 12. Written record per patch | Manual step 5 | manual |
| 13. Float32 path against a known calibration | `check-uc1.py` float32 and short-cube checks, run in manual step 3 | manual |
| 14. Equal-diagonal PCA against NumPy | `check-uc1.py` equal-bands check, run in manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_bandMappingFeedsEachModelBandFromTheDocumentedSource` (new): for the
  LCTF grid, model band `m` (440 + 5m nm) is fed by the source band at
  `max(460, 440 + 5m)` nm. Expected values are computed from the wavelengths
  stated in `ADR-0004` decision 4, not from the module. Fails first:
  `SLIAFlowUc1Input` does not exist.
- `test_bandMappingRefusesACubeOffTheLctfGrid` (new): 93-band HSI grid,
  460-900 nm only, a shifted grid, and a 109-band grid with one wavelength off
  by 1 nm are each refused. Fails first on the missing module.
- `test_uc1InputIsTheMappedCubeWrittenOutsideInput` (new): after a run starts
  on a fixture cube, `build/uc1/UC1/input/002-04/raw.dat` equals the fixture's
  values at the mapped bands, `raw.hdr` declares 93 bands and data type 4, and
  every file under the fixture's `input/` has its original bytes and time.
  Replaces `test_cubeReadingDoesNotWriteToInput`. Fails first: the run is given
  the recorded case folder and writes nothing.
- `test_captureRunsUc1OnTheConfiguredCalibratedCube` (replaces
  `test_captureUsesTheConfiguredCube`): two Captures both pass the run folder
  of the configured calibrated cube as UC1's argument. Fails first: the
  argument is the recorded case folder.
- `test_configuredCubeIsRefusedWithItsReason`, `test_cubeRefusalReasonsAreTranslated`
  and `test_surfacedFailureMessagesAreTranslated` (changed): refusals now come
  from the calibrated cube (missing header, truncated data, off-grid
  wavelengths). Fail first: Capture still reads the recorded case and starts a
  run.
- `test_cubeChangedOnDiskIsRefusedRatherThanRunOn` (replaces
  `test_caseChangedOnDiskIsRefusedRatherThanRunOn`): the calibrated cube is
  rewritten with other dimensions after it is described. Fails first on the
  missing module. Extended after review: the data file rewritten in place with
  other values of the same size (write time set one second later, so the test
  does not depend on the file system clock); another same-size file moved over
  it with the original write time; a change during the copy (stamps altered
  after the first check), which must leave no file in the run folder; and the
  unchanged cube still runs. Shown failing by disabling the stamp comparison:
  `AssertionError: Uc1RunError not raised`.
- `test_groundTruthEntryIsOfferedOnlyForACubeThatHasOne` (new): without a
  `gtMap` beside the cube, the `gtMap` row is hidden and disabled after a result
  and a stored `gtMap` selection yields "has no ground truth"; with one, the row
  is enabled. Fails first: the entry is always enabled.
- `test_resultStatusSaysLctfResultsAreNotValidated` (new): the done and result
  statuses carry the not-validated sentence. Fails first: no such text.
  Extended after review to the result under its ground truth, unreadable
  ground truth, the previous result while processing and after a failed
  capture, and every result-status template. Shown failing by removing the
  sentence from the stale and unreadable-ground-truth statuses: five subtests
  fail with `'not validated' not found in 'Previous result: recorded cube
  002-04, ...'` and `'... Its ground truth could not be read.'`.
- `test_outputNodesCarrySharedCaptureIdAndProvenance` (changed): the detail is
  `real UC1 pipeline, recorded IUMA LCTF capture 002-04, calibrated by IUMA
  (simulated acquisition)`. Fails first: the detail names a recorded HSI case.
- `test_moduleHasNoCasePool` (extended): the logic has no `cubeFolder` and
  `SLIAFlowCube` defines no `loadRecordedCase`. Fails first on both.
- Removed with the recorded-case loader: `test_cubeFolderRejectsIncompatibleContents`.
- `test_runEnvironmentChangeRestoresTheDefaultCube` (changed): now asserts that
  the calibrated cube header, the one configured cube, returns to its default.
  No other test covered that reset. It passes against the code as it was, so
  it is shown failing by removing the reset from `setRunEnvironment`.
- The UC1-run, capture-session and ground-truth tests change only their fixture:
  the configured cube is the fixture calibrated cube (with a `gtMap` beside it
  where a test needs one), and UC1's outputs land in `output/002-04`.

`build-uc1.ps1` and `check-uc1.py` are scripts around a CUDA binary, outside
`SLIAFlowTest`; they are checked by running them (manual steps 1 to 3), with
the failing cases forced in step 2 and by the band-guard input in step 3. Each
patch check was also run against a build without its patch and failed there
(Completion evidence).

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `.\scripts\development\build-uc1.ps1 -Clean` | Three patches listed as applied in order; both binaries built with only the expected warnings; the hash section says the staged tree equals the vendored tree plus the patches; the vendored `main.cu` SHA-256 printed matches the one recorded in `uc1_changes.md`; exit 0 | Observed 2026-09-25: exit 0; all three patches applied in order, expected `#550-D`/`C4068` warnings only, staged-tree assertion passed, and the vendored hash matched the record. |
| 2 | Copy `scripts\development\uc1-patches` to a temp folder, change one context line in `0002-calibrated-float32-input.patch`, run `.\scripts\development\build-uc1.ps1 -SkipBuild -PatchDirectory <temp folder>` | The script names the patch that does not apply and exits nonzero | Observed 2026-09-25: exit 1; `0002-calibrated-float32-input.patch` was named and rejected because it did not apply. The repository patch files were not changed. |
| 3 | Run `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` | `pca`, `svm`, `knn`, `CalibratedImage_BIP` identical to the unpatched hashes; `kmeans` and `imageRGB` differ in at most 1 % of pixels from the saved unpatched run; band guard exit 1 with its message and no output folder; `float32-check` `CalibratedImage_BIP.bmp` identical to the prediction and `pca`/`svm`/`knn` within 0.1 %; `pca.bmp` within 1 grey level of NumPy's component on `float32-check` and `equal-bands-check`; `short-read-check` exit 1 with the byte counts; missing weights exit 1 with `cannot be opened`; overall PASS, exit 0 | Observed 2026-09-25: overall PASS, exit 0; deterministic reference images were identical, K-means differences were 0.2004%/0.1227%, all float32/equal-band checks passed, and the intentional refusal cases returned the expected messages and nonzero exits. |
| 4 | Run `.\scripts\development\build-sliaflow.ps1 -Launch`; in SLIAFlow press Start, then Capture; step through the five outputs; open the output list | Status names cube `002-04` and says results on the LCTF cube are not validated; five outputs, each 1080 x 1080; `pca.bmp`, `knn.bmp` and `imageRGB.bmp` show structure, not one flat colour; `gtMap` is not in the list; LiveView resumes | Observed 2026-09-25 in headful Slicer: Start produced a live frame and Capture completed; status named `002-04` and said results were not validated; all five outputs were present at 1080 x 1080, each was selectable, only the five outputs were visible (`gtMap` hidden), and LiveView remained active. |
| 5 | Read `docs/development/uc1_changes.md` | One section per patch with what, why, command, result and timing; the band mapping table; the reference baseline hashes | Observed 2026-09-25: all three patch sections, commands/results/timings, mapping table, and reference baseline hashes were present. |
| 6 | In the Slicer used for development, open SLIAFlow and press `Reload and Test` | All `SLIAFlowTest` tests pass | Observed 2026-09-25: the actual Slicer `Reload and Test` action ran 89 tests, `OK (skipped=1)`, exit 0. |

## Risks

- The LCTF cube's spectral response differs from the camera the model was
  trained on. Outputs may look implausible (at specification most of the scene
  was classed as tumour). That is a finding to record, not a bug to tune away
  here.
- A patch that no longer applies after a new UC1 delivery must fail the build,
  not be skipped. `git apply` refuses rather than fuzzes.
- The run-to-run variation of K-means makes the 1 % bound a tolerance, not an
  identity. The deterministic four images carry the identity check.
- Writing the 434 MB mapped cube at every Capture blocks the UI for about half
  a second. Measured and recorded; `SLIA-034` owns speed.
- The change check compares the cube files' size, last write time (100 ns on
  NTFS) and file ID, not their contents. A rewrite in place that keeps the size
  and sets the write time back to the same 100 ns is not detected. Hashing the
  508 MB cube would read it once more at every Capture; not chosen.
- `check-uc1.py` checks the float32 path, the transpose and the equal-diagonal
  PCA against oracles computed outside UC1, but not that UC1's classes are
  right on an LCTF cube: no labelled LCTF cube exists.

## Documentation impact

`docs/development/uc1_changes.md` (new), `docs/development/uc1_local_build.md`,
`docs/development/uc1_demo_runbook.md`, module README, `input/README.txt`.

## Completion evidence

Implemented on 2026-09-25 on branch
`feature/SLIA-033-uc1-accepts-calibrated-float32-cube`, created from `main` at
`6dda22a`. Validation, manual verification, review, and completion approval
are complete.

### Files

Created: `scripts/development/uc1-patches/.gitattributes`,
`0001-band-guard.patch`, `0002-calibrated-float32-input.patch`,
`0003-jacobi-equal-diagonal.patch`, `scripts/development/check-uc1.py`,
`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py`,
`docs/development/uc1_changes.md`.

Modified: `scripts/development/build-uc1.ps1`, `CMakeLists.txt`,
`SLIAFlowCube.py`, `SLIAFlowCalibratedCube.py` (docstring),
`SLIAFlowLogic.py`, `SLIAFlowParameterNode.py`, `SLIAFlowUc1Run.py`,
`SLIAFlowWidget.py`, `SLIAFlowTest.py`, `extensions/SLIAFlow/README.md`,
`docs/development/uc1_local_build.md`, `docs/development/uc1_demo_runbook.md`,
this card (moved from `tasks/backlog/`). Gitignored: `input/README.txt`,
`build/uc1/` (staged build, `expected/`, `input/002-04/`,
`reference-unpatched/`).

### UC1 build and patches

- `.\scripts\development\build-uc1.ps1 -Clean`: exit 0. Three patches applied;
  both binaries with only `#550-D` and `C4068`; release 961,024 bytes,
  intermediate 1,426,432 bytes; "All staged files equal workspace\components
  plus the patches"; vendored `main.cu` `63D0E9EE...C788C0`, staged `main.cu`
  `8635F2A7...E02210`.
- Defect found and fixed during implementation: the first version ran
  `git -C <staged folder> apply`, which inside the repository printed
  `Skipped patch 'main.cu'` and exited 0. The build and its hash check passed
  with no patch applied (staged `main.cu` equal to the vendored one, binaries
  unchanged in size). The script now applies from the repository root with
  `--directory` and fails on any `Skipped patch`.
- A patch that does not apply (one context line changed in a copy of 0002,
  `-SkipBuild -PatchDirectory <copy>`): exit 1, `ERROR:
  0002-calibrated-float32-input.patch does not apply to
  C:\stratum\build\uc1\UC1\gpu_single_bsq\source. ...`, with `git apply`'s
  `patch failed: .../data_loader.hpp:10`.
- `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` on the patched
  build, before review: exit 0, `PASS`. `pca`, `svm`, `knn`,
  `CalibratedImage_BIP` identical to the unpatched hashes; `kmeans.bmp`
  0.0585 %, `imageRGB.bmp` 0.0345 % of pixels from the saved unpatched run;
  band guard exit 1 with its message, no output folder. The extended check,
  after review, is below.
- The same check on an unpatched build (`-PatchDirectory` an empty folder):
  exit 1, `FAIL: UC1 did not refuse the 109-band header within 20 s; it was
  killed`. The reference half passed, as it must. The patched build was then
  rebuilt with `-Clean` (exit 0).

### Tests observed failing first

`.\scripts\development\run-slicer-tests.ps1` with the new and changed tests
against the module as it was: exit 1, `Ran 88 tests`, `FAILED (failures=27,
errors=33, skipped=15)`. The new tests failed for the reason they target:

- `test_bandMappingFeedsEachModelBandFromTheDocumentedSource`,
  `test_bandMappingRefusesACubeOffTheLctfGrid`,
  `test_uc1InputIsTheMappedCubeWrittenOutsideInput`,
  `test_cubeChangedOnDiskIsRefusedRatherThanRunOn`,
  `test_cubeRefusalReasonsAreTranslated`,
  `test_surfacedFailureMessagesAreTranslated`: `ModuleNotFoundError: No module
  named 'SLIAFlowLib.SLIAFlowUc1Input'`.
- `test_captureRunsUc1OnTheConfiguredCalibratedCube`,
  `test_resultStatusSaysLctfResultsAreNotValidated`,
  `test_outputNodesCarrySharedCaptureIdAndProvenance`: `AssertionError:
  unexpectedly None : Capture did not start a UC1 run` (Capture still read the
  recorded-case folder, absent from the new fixture).
- `test_configuredCubeIsRefusedWithItsReason`: `AssertionError:
  '...\input\absent\LCTF_Calibrated_Cube_Single.hdr' not found in 'Failed: The
  configured cube ...\input\reference_hsi_brain_db\020-01 cannot be used: ...
  is not a folder. ...'` (and likewise for the off-grid and truncated cubes).
- `test_groundTruthEntryIsOfferedOnlyForACubeThatHasOne`: `AssertionError:
  Tuples differ: (True, True) != (False, False)`, gtMap offered before any
  result.
- `test_moduleHasNoCasePool`: `AssertionError: True is not false : SLIAFlowCube
  still has loadRecordedCase`.
- `test_groundTruthIsReadTopRowFirst`, `test_groundTruthIsRefusedRatherThanReshaped`,
  `test_groundTruthReadingDoesNotWriteToInput`: errors on the new
  `readGroundTruth(folder, samples, lines)` / `GroundTruthError` interface.
- `test_runEnvironmentChangeRestoresTheDefaultCube`, with the reset of the
  header override removed from `setRunEnvironment`: `Ran 89`, one failure,
  `AssertionError: WindowsPath('...slia-fx-j4ntsd9y/input/elsewhere/cube.hdr')
  != WindowsPath('...slia-fx-2tsscu89/input/002-04/LCTF_Calibrated_Cube_Single.hdr')`.
  The line was restored and the suite rerun.

### Required checks, final

| Check | Command | Result |
| --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | "Python quality checks passed.", exit 0 |
| Slicer tests, working tree, headless | `.\scripts\development\run-slicer-tests.ps1` | `Ran 89 tests`, `OK (skipped=15)`, exit 0; the 15 are the headful-only tests |
| Slicer tests, working tree, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 89 tests`, `OK (skipped=1)`, exit 0; the skip is `test_headlessPresentationFallback`, which covers only the no-main-window case |
| Extension build | `.\scripts\development\build-sliaflow.ps1` | exit 0, "The build tree matches the working tree." |
| Slicer tests, built extension | `.\scripts\development\run-slicer-tests.ps1 -Target Build` | module loaded from `build\SLIAFlow\...`, `Ran 89 tests`, `OK (skipped=15)`, exit 0 |
| Whitespace | `git diff --check` | exit 0 |
| Manual verification | the six steps above | performed 2026-09-25: steps 1-5 passed; headful Slicer Capture passed; exact `Reload and Test` passed with 89 tests and one expected skip |

The command-line runner's 89 includes the imported `ScriptedLoadableModuleTest`
base class (`testing_strategy.md`); 88 are `SLIAFlowTest` methods.

### Real data through the module (not a substitute for manual step 4)

`Slicer.exe --no-main-window --additional-module-paths
extensions\SLIAFlow\SLIAFlow --python-script <scratch script>` driving
`SLIAFlowLogic.loadConfiguredUc1Input` and `Uc1Run` with a real `QProcess` on
`input\002-04`, 2026-09-25, exit 0:

- described `002-04`: 1080 x 1080, 109 bands -> 93; band sources
  `(0, 0, 0, 0, 0, 1) ... (86, 87, 88)`; no ground truth;
- `run.start` (checks, lock, mapped cube written) 0.49 s; UC1 process 4.1 s;
  `Time simulation ---> 2018.628 ms`; Capture-path start to validated outputs
  4.57 s;
- `raw.dat` 433,900,800 bytes, byte-identical (SHA-256 `aaf30f8e...910003e`) to
  the independent NumPy mapping written at specification; `raw.hdr` declares
  1080 x 1080 x 93, data type 4, bsq, byte order 0;
- five outputs 1080 x 1080: `pca.bmp` 256 grey levels, `svm.bmp` and
  `knn.bmp` 4 classes, `kmeans.bmp` 24 clusters, `imageRGB.bmp` 2 classes
  (tumour 35.9 %, background 64.1 %);
- output provenance `simulated | real UC1 pipeline, recorded IUMA LCTF capture
  002-04, calibrated by IUMA (simulated acquisition)`.

Not run: CTest against the standalone extension build (optional in
`testing_strategy.md`; the Build-target run above covers the same compiled
module).

## Review findings

### Findings supplied by the project owner, 2026-09-25, during implementation

1. **High: a same-size change to the cube was not detected.** Confirmed:
   `assertUc1InputUnchanged` compared only the reloaded description (paths,
   dimensions, wavelengths). Fixed: `describeUc1Input` records the size, last
   write time and file ID of the header and data file (`fileStamps`); a
   difference refuses the run naming the file. `writeUc1Input` checks again
   after the copy and removes the partial copy on any refusal.
   `test_cubeChangedOnDiskIsRefusedRatherThanRunOn` extended (Test plan).
2. **Medium: the not-validated warning was missing from the stale and
   unreadable-ground-truth statuses.** Confirmed. Fixed: `RESULT_STALE_STATUS`
   and `GROUND_TRUTH_MISSING_STATUS` now end with the sentence.
   `test_resultStatusSaysLctfResultsAreNotValidated` extended to every result
   state and template.
3. **Medium-low: the new CUDA paths had no exact oracle.** Confirmed.
   `check-uc1.py` gained four checks: float32 `020-01` against a NumPy
   calibration (exact on `CalibratedImage_BIP.bmp`), equal bands against
   NumPy's principal component, a short float32 cube, and missing weights.
   Each failed against a build without its patch. Byte-identity of the float32
   run with the uint16 run was measured to be impossible (13.5 % of calibrated
   values cannot be reached through `100 * x`), hence the 0.1 % bound on
   `pca`, `svm` and `knn`; they came out 0.0064 %, 0 and 0.
4. **Low: manual verification outstanding.** Unchanged: the six steps are for
   the project owner.

### After the fixes

- `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` against a build
  with patches 0001 and 0002 only (`build-uc1.ps1 -Clean -PatchDirectory
  <copy of those two>`, exit 0): exit 1, one failure, `FAIL: pca.bmp of
  equal-bands-check is up to 255 grey levels from NumPy's first principal
  component, over 1` (77.1878 % equal). Every other check passed.
- The same against a build with patch 0001 only: exit 1, four failures: `UC1
  exited with 3221225477 on float32-check`, the same on `equal-bands-check`,
  `UC1 did not report the short float32 cube`, and `UC1 created ...\output\
  short-read-check on a float32 cube one value short`.
- `build-uc1.ps1 -Clean` with the three patches: exit 0, "All staged files
  equal workspace\components plus the patches", staged `main.cu`
  `8635F2A7...E02210`. Then `check-uc1.py`: exit 0, `PASS`:

  ```text
  Reference case 020-01: exit 0, 0.98 s
    pca.bmp                  identical  ee01256ba51b589f51d6a3a8d726685c04f08f25ccbb3bda857187809632e58c
    svm.bmp                  identical  5f9548afcf87908115cdff408e263a30a24f4423340b99655d2f46c276f62a0f
    knn.bmp                  identical  5aea0081152655c4ec4151abe59b97f3231818a2e351663a43178b2614a67910
    CalibratedImage_BIP.bmp  identical  810909a985f7bc0424e46fc8c225f7e797840c91b2d42812b5e74a7daedb2b89
    kmeans.bmp               0.2413% of pixels differ from the unpatched run (within 1%)
    imageRGB.bmp             0.1475% of pixels differ from the unpatched run (within 1%)
  Band guard, 109-band header: exit 1, 0.10 s
    Band guard: the cube has 109 bands, but ../../svm_model/w_vector.bin holds 2232 bytes, the weights of 93 bands for 6 binary classifiers. UC1 does not classify this cube.
  float32-check: exit 0, 0.56 s
    CalibratedImage_BIP.bmp  identical to the prediction
    pca.bmp                  0.0064% of pixels differ from the uint16 run on 020-01 (within 0.1%)
    svm.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
    knn.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
    pca.bmp                  99.9960% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
  equal-bands-check: exit 0, 0.55 s
    pca.bmp                  99.9864% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
  short-read-check: exit 1, 0.21 s
    Error: C:\stratum\build\uc1\UC1\input\short-read-check/raw.dat holds 46403276 bytes, the header describes 46403280
  Missing weights: exit 1, 0.09 s
    Band guard: ../../svm_model/w_vector.bin cannot be opened.

  PASS
  ```

- Mutation run, `run-slicer-tests.ps1` with the stamp comparison disabled and
  the sentence removed from the two statuses: exit 1, `Ran 89 tests`,
  `FAILED (failures=6, skipped=15)`: `test_cubeChangedOnDiskIsRefusedRatherThanRunOn`
  (`Uc1RunError not raised`) and five subtests of
  `test_resultStatusSaysLctfResultsAreNotValidated`. Both files were restored
  from copies and checked.
- Final checks, all rerun after the fixes: `run-python-quality.ps1` "Python
  quality checks passed.", exit 0; `run-slicer-tests.ps1` `Ran 89 tests`,
  `OK (skipped=15)`, exit 0; `-Headful` `Ran 89 tests`, `OK (skipped=1)`,
  exit 0; `build-sliaflow.ps1` exit 0, "The build tree matches the working
  tree."; `-Target Build` module loaded from `build\SLIAFlow\...`, `Ran 89
  tests`, `OK (skipped=15)`, exit 0; `git diff --check` exit 0.
- Real-data run through the module (the script of the section below), rerun
  after the fixes, exit 0: `run.start` 0.36 s, UC1 process 2.41 s, `Time
  simulation ---> 1898.957 ms`, start to validated outputs 2.81 s; `raw.dat`
  SHA-256 `aaf30f8e...910003e`, unchanged; `pca.bmp` 256 grey levels, `svm.bmp`
  and `knn.bmp` 4 classes, `kmeans.bmp` 24 clusters, `imageRGB.bmp` 2 classes.

## Human approval
