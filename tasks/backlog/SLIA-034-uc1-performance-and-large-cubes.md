---
id: SLIA-034
title: Measure and improve UC1 speed on the LCTF cube, and find its size limit on this GPU
status: backlog
branch:
priority: medium
depends_on: SLIA-033
required_skills: []
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-034 - Measure and improve UC1 speed on the LCTF cube, and find its size limit on this GPU

## Goal

Know how long UC1 takes on `002-04` from Capture to result, where that time
goes, what makes it faster, and how large a cube this laptop's GPU can take.
Every trial is recorded in a simple table: what was changed, the command, the
time, and whether the output changed.

## Context

- GPU: NVIDIA RTX 5050 Laptop, compute capability 12.0, 8151 MiB.
- UC1 has a profiling build (`make profile`, CSV timings per stage) and build
  flags `PCA_PD`, `OPTIMIZE_KMEANS`, `KMEANS_SHARED` and `OPT`.
- `parameters.txt` next to the executable holds, in order: HySime, PCA bands,
  PCA epsilon, classes, min and max probability, SVM iterations, SVM epsilon,
  lambda, KNN neighbours, KNN window, distance metric, K-means k, minimum error,
  maximum iterations. Current values:
  `0 1 0.00001 4 0.0000001 0.9999999 100 0.005 1.0 40 15 0 24 1e-3 20`.
- The owner allows tuning parameters and build flags as long as changes and
  results are documented simply. Model training is out of scope.
- *Absorbs `SLIA-029`.* That card verified the largest HSI Human Brain Database
  cases (`058-02`, about 3.5 GiB estimated) on this GPU. `ADR-0004` archived
  those cases. The question it asked still matters for the real format: IUMA's
  raw LCTF cube is 4096 x 2160 x 109, and a full-resolution calibrated cube in
  float32 would be about 3.6 GiB before UC1 allocates anything.

## Requirements

- **Baseline.** Time the full Capture-to-result path on `002-04` and each UC1
  stage (profiling build), five runs, median and spread. Record peak GPU memory
  with `nvidia-smi`.
- **Trials.** One change at a time, each against the baseline: build flags,
  K-means k and iterations, KNN window and neighbours, and anything the profile
  points at. For each: time, peak memory, and whether the outputs are
  byte-identical to the baseline or how they differ (pixel count per class).
- **Size limit.** Run UC1 on cubes derived from `002-04` at increasing sizes
  (for example 1080, 1620, 2160 square, made by tiling `002-04` in a scratch
  folder outside `input/` and deleted afterwards), recording peak memory and
  time, up to the first failure. Tiled cubes measure memory and time only; their
  outputs are not looked at. A memory failure is a finding, not
  something to work around here.
- **Recommendation.** One paragraph: which settings to adopt, with the measured
  gain and the output change it costs. Adopting them is the owner's decision.
- Results go in one document, for example `docs/development/uc1_performance.md`,
  with a table a non-specialist can read.

## Out of scope

- Retraining the model.
- Rewriting UC1 kernels. A kernel change worth making becomes its own card.
- Tiling or downsampling cubes in the product.

## Files allowed

To be defined at specification. Expected: `docs/development/uc1_performance.md`,
`docs/development/uc1_changes.md`, UC1 parameter files through the patch
mechanism of `SLIA-033`, possibly `build-uc1.ps1` for a profiling build.

## Relevant skills and references

- UC1 `GUIDE.md` (profiling and flags), `parameters.h`, `parameters.txt`
- `SLIA-029` in Git history (commit `ce43135`), the card this one replaces
- `tasks/backlog/SLIA-033-uc1-accepts-calibrated-float32-cube.md`

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- Laptop GPUs throttle. Record power mode and whether the laptop is on mains,
  and discard the first run.
- A faster setting that changes the output is a trade-off for the owner, not a
  win to adopt silently.

## Documentation impact

`docs/development/uc1_performance.md` (new), `docs/development/uc1_changes.md`.

## Completion evidence

## Review findings

## Human approval
