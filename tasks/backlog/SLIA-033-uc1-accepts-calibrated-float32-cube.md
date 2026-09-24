---
id: SLIA-033
title: Run UC1 on the calibrated float32 LCTF cube through documented patches
status: backlog
branch:
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
  `raw`. Dimensions come from `raw.hdr`.
- Calibrates with `100 * (raw - dark) / (white - dark)`
  (`calibrateAndConvertToBIP_Tiled`), converting to BIP.
- `normalizeImgKernel_optimized` then rescales each pixel to its own minimum and
  maximum over the bands, so a constant scale factor on the input does not
  change what follows. (To be confirmed on a test run, not assumed.)
- PCA to one band, linear SVM (`w_vector` 93 x 6, 4 classes), KNN filter,
  K-means with 24 clusters, majority vote.
- Reads `../../svm_model/w_vector.bin` with the header's band count and never
  checks how much it read. A 109-band header overreads and gives garbage weights
  without any error.
- `MAX_PATH_LENGTH` is 128; a longer path makes it exit 0 without writing.
- `build-uc1.ps1` stages the vendored tree into `build/uc1/UC1` and asserts the
  staged files are byte-identical to `workspace/components`.

What `002-04` is: float32 BSQ, 1080 x 1080 x 109, 460-1000 nm, already
calibrated by IUMA, values in [0, 1.5], no full-size references, no `gtMap`.
The file is named `LCTF_Calibrated_Cube_Single`, not `raw`.

`ADR-0004` decisions 3 to 6 govern this task: patches at staging, a documented
109-to-93 band mapping, behavioural results only, float32 input validation.

## Requirements

- **Patches, not edits.** Add a versioned patch directory (for example
  `scripts/development/uc1-patches/`). `build-uc1.ps1` applies the patches, in
  order, to the staged copy after staging, and its hash check compares against
  original plus patches. The vendored copy stays unchanged.
- **Float32 calibrated input.** When the header says data type 4, UC1 reads the
  cube as calibrated reflectance, skips its own calibration and needs no
  references. The uint16 path stays unchanged for the reference case.
- **Band guard.** UC1 refuses to start, with a nonzero exit and a message, when
  the band count it will classify differs from the model's. This closes the
  silent overread for any input.
- **Band mapping.** 460-900 nm feed model bands 5-93 one to one; model bands
  1-4 (440-455 nm) take the 460 nm band; 905-1000 nm are dropped. Where the
  mapping runs (UC1 patch or SLIAFlow) is decided at specification, with a
  recommendation; it runs in exactly one place and is described in exactly one
  document.
- **Input file name.** How UC1 finds `LCTF_Calibrated_Cube_Single` without
  writing into `input/` is decided at specification (patch accepting the file
  name, or a run folder outside `input/` holding only a header).
- **SLIAFlow.** Capture runs UC1 on the configured cube. Input validation per
  `ADR-0004` decision 6. The `gtMap` entry is shown only when the cube has one;
  otherwise the panel says there is no ground truth for this cube. Status text
  says results on the LCTF cube are not validated (decision 5).
- **Reference check.** The reference case still runs, through the unchanged
  uint16 path, and its outputs are byte-identical to those before the patches.
- **Record.** A short document, for example `docs/development/uc1_changes.md`:
  one section per patch saying what it changes, why, the command run and what
  came out, with timing.

## Out of scope

- Retraining or editing the SVM model.
- Tuning parameters (`SLIA-034`).
- Reading the raw uint16 LCTF cube.

## Files allowed

To be defined at specification. Expected: `scripts/development/build-uc1.ps1`,
the new patch directory, `SLIAFlowUc1Run.py`, the single-cube loader,
`SLIAFlowLogic.py`, `SLIAFlowWidget.py`, `SLIAFlowTest.py`,
`docs/development/uc1_changes.md`, `docs/development/uc1_local_build.md`.

## Relevant skills and references

- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- UC1 `main.cu`, `functions_cuda.cu`, `functions.cu`, `data_loader.cpp`,
  `GUIDE.md`
- `scripts/development/build-uc1.ps1`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`

## Implementation plan

To be defined at specification. Suggested order: band guard patch first (it
protects every later step), then float32 input, then band mapping, then
SLIAFlow, then the reference-case byte-identity check.

## Acceptance criteria

To be defined at specification. At minimum:

- UC1 with a band count different from the model's exits nonzero before
  classifying;
- Capture on `002-04` produces five valid outputs of 1080 x 1080;
- the reference case's outputs are byte-identical before and after the patches;
- the vendored copy is unchanged and the staged copy equals original plus
  patches;
- every patch has its written record.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- The LCTF cube's spectral response differs from the camera the model was
  trained on. Outputs may look implausible. That is a finding to record, not a
  bug to tune away here.
- A patch that no longer applies after a new UC1 delivery must fail the build,
  not be skipped.

## Documentation impact

`docs/development/uc1_changes.md` (new), `docs/development/uc1_local_build.md`,
module README.

## Completion evidence

## Review findings

## Human approval
