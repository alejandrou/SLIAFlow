---
id: SLIA-034
title: Measure and improve UC1 speed on the LCTF cube, and find its size limit on this GPU
status: completed
branch: feature/SLIA-034-uc1-performance-and-large-cubes
priority: medium
depends_on: SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-034 - Measure and improve UC1 speed on the LCTF cube, and find its size limit on this GPU

## Goal

Know how long UC1 takes on `002-04` from Capture to result, where that time
goes, what makes it faster, and how large a cube this laptop's GPU can take.
Every trial is recorded in a simple table: what was changed, the command, the
time, and whether the output changed.

## Context

- GPU: NVIDIA RTX 5050 Laptop, compute capability 12.0, 8151 MiB, WDDM driver
  591.74. Host: 15.3 GB RAM. At specification the laptop was on mains with the
  Balanced power plan.
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

### Found at specification (2026-09-25)

- SLIAFlow runs `stratum.opt.intermediate.exe`, built by `build-uc1.ps1` with
  `-DOPTIMIZE_KMEANS=1 -DPCA_PD=1 -lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT`.
  `PROFILE_MODE` already prints one CSV line per stage
  (`Upload Images , 281.895 ,ms`) and `Time simulation ---> ... ms`, so the
  product binary is the profiling build; no separate build is needed for the
  baseline.
- Two probe runs of that binary on the mapped `002-04` run folder
  (`build/uc1/UC1/input/002-04`, 1080 x 1080 x 93 float32) in a copy under
  `build/uc1/trials/`: `Time simulation` 2256 ms and 1736 ms. The largest
  stages were K-means (617-621 ms, stopping at the 20-iteration cap with error
  0.00114, over the 1e-3 target), Upload Images (282-627 ms), PCA (280-332 ms),
  cudaMalloc (88-140 ms). `SLIA-033` measured the whole UC1 process at 4.1 s
  against 2.0 s of `Time simulation`: about 2 s go to CUDA start-up and to
  what runs after the timer, which includes writing `output/rgb/*.txt`
  (7.8 MB of text).
- `KMEANS_SHARED` is tested with `#ifdef`, not `#if`: `-DKMEANS_SHARED=0`
  switches it on. The trial defines it bare.
- On this WDDM driver `nvidia-smi --query-compute-apps` reports `[N/A]` for
  every process's memory. Peak GPU memory can only be measured device-wide
  (`memory.used`), as the rise over the idle level just before the run.
- The UC1 process reads its whole cube into host memory. On large cubes the
  host may run out before the GPU does. At specification 1.8 GB of RAM were
  free, with three Slicer windows open.

## Requirements

- **Baseline.** Time the full Capture-to-result path on `002-04` inside Slicer,
  and each UC1 stage from the product binary's own CSV lines: one discarded
  warm-up run, then five timed runs, median and spread (min-max). Record peak
  GPU memory (device-wide rise over idle, sampled every 50 ms with
  `nvidia-smi`) and the UC1 process's peak host memory. Record the power plan,
  mains or battery, and the other GPU processes present.
- **Trials.** One change at a time, each against the baseline and with the
  same warm-up and five runs. At least:
  - build flags, through variant builds: `KMEANS_SHARED`, `PCA_PD=0`,
    `OPTIMIZE_KMEANS=0`, and the release binary without intermediate output
    (for information only: SLIAFlow needs the intermediate BMPs);
  - parameters, through `parameters.txt` in the trial folder: K-means k 12 and
    16, K-means maximum iterations 10 and 40, KNN window 9, KNN neighbours 20;
  - anything the baseline profile points at that needs no UC1 source change,
    for example CUDA module loading (`CUDA_MODULE_LOADING`).
  For each: time, peak memory, and the outputs against the baseline. `pca`,
  `svm`, `knn` and `CalibratedImage_BIP` are either byte-identical or described
  by the fraction of pixels that differ and the pixel count per class.
  `kmeans` and `imageRGB` vary from run to run without any change (`SLIA-033`),
  so they are described the same way next to the baseline's own run-to-run
  spread.
- **Size limit.** Run the product binary on cubes tiled from the mapped
  `002-04` at increasing sizes: 1080, 1620, 2160 and 2700 square, 4096 x 2160
  (the raw LCTF frame), then 3240 square, stopping at the first failure. Tiled
  cubes are written under `build/uc1/trials/cubes/` (gitignored, outside
  `input/`), without holding a whole cube in memory, and deleted afterwards.
  Record peak GPU and host memory, time and the exit code, and for a failure
  its message. Tiled outputs are not interpreted. UC1 checks almost none of its
  CUDA calls (its `checkCudaError` calls are commented out), so a failed
  allocation can still exit 0 with an image; `svm.bmp`, computed pixel by
  pixel, must therefore equal the baseline's `svm.bmp` tiled the same way
  (within 0.1 % of pixels), or the size counts as failed. *Added during
  implementation, 2026-09-25.* A failure is a finding, not something to work
  around here.
- **Recommendation.** One paragraph: which settings to adopt, with the measured
  gain and the output change it costs. Adopting them is the owner's decision.
  This task changes neither the product binary nor its `parameters.txt`.
- **Record.** `docs/development/uc1_performance.md`, with a table a
  non-specialist can read: what was changed, the command, the time, the
  memory, and whether the output changed.
- **Tools.** The measurements are repeatable by command:
  - `scripts/development/measure-uc1.py` runs a UC1 binary with a
    `parameters.txt` on a run folder in its own trial folder under
    `build/uc1/trials/<trial>/` (binary, `parameters.txt`, `../../svm_model`
    copy, output folders), never in `build/uc1/UC1/`. It times each run,
    parses the stage CSV, samples GPU memory, reads the peak host memory,
    compares the outputs with a named baseline trial, and writes the results
    as JSON under `build/uc1/trials/results/`. It also makes, runs and deletes
    the tiled cubes. It holds `.uc1-runner.lock` while it runs, as
    `check-uc1.py` does.
  - `scripts/development/measure-capture.py` runs inside Slicer
    (`--python-script`) and times SLIAFlow's Capture path without the window:
    input check, mapped cube write and UC1 start, the UC1 process, output
    validation and acceptance, and, as the widget does in parallel, the cube
    read and cube node.
  - `build-uc1.ps1 -Variant <name> -Defines "<defines>"` stages the vendored
    source plus the same patches into `build/uc1/variants/<name>/` and builds
    only the intermediate binary there, with `<defines>` in place of
    `-DOPTIMIZE_KMEANS=1 -DPCA_PD=1`, or the release binary with `-Release`.
    It prints every compiler warning and does not enforce the product's warning
    list. The staged-tree hash check runs on the variant tree. Without
    `-Variant` the script behaves exactly as it does today.

## Out of scope

- Retraining the model.
- Rewriting UC1 kernels, or any UC1 source change. A kernel change worth
  making becomes its own card.
- Adopting a setting: a new patch or parameter change for the product build is
  a follow-up the owner decides on.
- Making UC1's K-means deterministic.
- Tiling or downsampling cubes in the product.
- Changing the SLIAFlow module.

## Files allowed

- `tasks/{backlog,active,review}/SLIA-034-uc1-performance-and-large-cubes.md`
- `docs/development/uc1_performance.md` (new)
- `docs/development/uc1_changes.md` (a pointer to the performance record only)
- `docs/development/uc1_local_build.md` (the `-Variant` build)
- `scripts/development/build-uc1.ps1`
- `scripts/development/measure-uc1.py` (new)
- `scripts/development/measure-capture.py` (new)
- `build/uc1/` (gitignored: `variants/`, `trials/`, tiled cubes deleted
  afterwards; never staged)

## Relevant skills and references

- Slicer skill: running a script in Slicer with `--python-script`,
  `slicer.app.processEvents()` while a `QProcess` runs, `slicer.util.exit`.
- UC1 `GUIDE.md` sections 1.5, 2.4 and 2.5 (flags, profile CSV), `logger.hpp`
  (`TIMER_*` macros), `main.cu`, `functions_kmeans.cu` (`#ifdef KMEANS_SHARED`),
  `parameters.h`, `parameters.txt`
- `scripts/development/build-uc1.ps1`, `scripts/development/check-uc1.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
  (`loadConfiguredUc1Input`, `startUc1Run`, `acceptOutputs`,
  `loadConfiguredCalibratedCube`, `acceptCube`), `SLIAFlowWidget.py`
  (`_startCapture`, `_onUc1Finished`)
- `docs/development/uc1_changes.md`
- `SLIA-029` in Git history (commit `ce43135`), the card this one replaces

## Implementation plan

1. Add `-Variant`, `-Defines` and `-Release` to `build-uc1.ps1`; check that the
   default build is unchanged (`-Clean`, then `check-uc1.py` PASS).
2. Write `measure-uc1.py`; check its comparison on the baseline against itself
   and on a trial known to change `pca.bmp` (`PCA_PD=0` or a tiled cube's
   dimensions refused).
3. Run the baseline (UC1 alone) and the Capture baseline in Slicer with
   `measure-capture.py`.
4. Build the variants and run every trial.
5. Run the size ladder up to the first failure; delete the tiled cubes.
6. Write `uc1_performance.md` with the tables and the recommendation; add the
   pointer to `uc1_changes.md` and the variant build to `uc1_local_build.md`.
7. Run Ruff on the two new scripts, the repository quality script and the
   Slicer tests.

## Acceptance criteria

1. The baseline records, over five runs after a discarded warm-up, the median
   and spread of UC1's wall time, of `Time simulation` and of every stage, with
   peak GPU and host memory, the power plan and mains state.
2. The Capture-to-result path in Slicer is timed over five runs after a
   warm-up, split into input check and write, UC1 process, and output
   acceptance, with the cube read and cube node timed separately.
3. Every trial listed in Requirements has a row with the change, the command,
   median time and spread, peak memory, and the outputs against the baseline
   (identical, or differing fraction and pixels per class, next to the
   baseline's own spread for `kmeans` and `imageRGB`).
4. The size ladder is run up to the first failure or to its end, with peak GPU
   and host memory, time and exit code per size, and the failure's message and
   cause; no tiled cube remains afterwards and nothing was written to `input/`.
5. `uc1_performance.md` holds the tables and a one-paragraph recommendation
   with its gain and output cost, readable without knowing UC1.
6. Without `-Variant`, `build-uc1.ps1` stages and builds as before: the
   staged tree equals the vendored tree plus the three patches, only the
   expected warnings appear, and `check-uc1.py` passes. A variant build never
   writes into `build/uc1/UC1/` and fails when a patch does not apply.
7. The product binary, its `parameters.txt` and the SLIAFlow module are
   unchanged, and the Slicer tests still pass.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Baseline with median, spread, memory, power state | Manual step 2 (owner reruns the baseline) and step 5 (reads the record) | manual |
| 2. Capture-to-result in Slicer | Manual step 3 | manual |
| 3. One row per trial with output comparison | Manual step 5; the comparison is checked by running the baseline against itself and against a changed trial (Completion evidence) | manual |
| 4. Size ladder, failure recorded, tiled cubes deleted | Manual step 4 and step 5 | manual |
| 5. Readable record with recommendation | Manual step 5 | manual |
| 6. Default build unchanged; variant isolated | Manual step 1 | manual |
| 7. Product and module unchanged; tests pass | `run-slicer-tests.ps1` (all `SLIAFlowTest` tests) and manual step 6; `git status` shows no change under `extensions/` | automated and manual |

Tests to add or change, and how each one will be shown to fail first:

- None. This task adds no behaviour to the SLIAFlow module; the existing
  `SLIAFlowTest` suite runs as a regression check. The two scripts and the
  variant build are measurement tools around a CUDA binary, checked by running
  them: the output comparison of `measure-uc1.py` must report the baseline
  identical to itself (four deterministic images) and must report a
  difference on a trial that changes `pca.bmp`, and a variant build given a
  patch folder with a broken patch must fail. Both are recorded in Completion
  evidence.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `.\scripts\development\build-uc1.ps1 -Clean`, then `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` | Three patches applied, only the expected warnings, staged-tree assertion passes, `check-uc1.py` PASS, exit 0 both times | PASS (2026-09-25): build exit 0; all three patches applied; only `#550-D` and `C4068` were present; staged-tree assertion passed. `check-uc1.py` printed `PASS`, exit 0. The build also printed a non-fatal `vswhere.exe` lookup message before using the configured `vcvars64.bat`. |
| 2 | Run the baseline command given in `uc1_performance.md` | Five timed runs after a warm-up; the median `Time simulation` within the spread recorded in the document, or the difference explained by power state | PASS (2026-09-25): `baseline-repeat --runs 5 --warmups 1`, exit 0; wall median 1.98 s (1.95-2.29), `Time simulation` median 1647 ms (1626-1852), GPU +2641 MiB (2636-2646), host peak 1105 MiB (1104-1105). The first two counted runs were slower while the GPU/cache warmed; the simulation median remains within the recorded range. |
| 3 | Run the Capture measurement command given in `uc1_performance.md` | A Slicer instance starts without a window, prints five Capture timings and exits 0; the medians close to the recorded ones | PASS (2026-09-25): configured Slicer ran five captures after one warm-up and exited 0; Capture-to-result median 2.40 s (2.37-2.51), UC1 2.05 s, mapped-cube prepare 0.29 s. The expected no-main-window toolbar messages were the only startup noise. |
| 4 | After the size ladder, look in `build\uc1\trials\cubes\` and `input\` | No tiled cube remains; `input\` has no new or changed file | PASS (2026-09-25): `build\uc1\trials\cubes\` absent after the ladder and the fresh 2430 x 2430 probe; no input file was written or changed. |
| 5 | Read `docs/development/uc1_performance.md` | Baseline, Capture and trial tables with command, time, memory and output change; the size ladder with the failure and its cause; a one-paragraph recommendation | PASS (2026-09-25): the 407-line record contains the required baseline, Capture, trial, size-limit and recommendation sections, including the silent-allocation failure and its output guard. |
| 6 | In the development Slicer, open SLIAFlow and press `Reload and Test` | All `SLIAFlowTest` tests pass | PASS (2026-09-25): headful source-target Slicer loaded `extensions\SLIAFlow\SLIAFlow`, ran 89 tests (1 expected skip), including reload/presentation tests, and exited 0. Slicer logged one unrelated optional `CropVolume` dependency warning. |

### Deliberate robustness probes

- A missing patch directory was rejected before compilation (exit 1); a missing UC1 binary was rejected (exit 1); and `sizes --repeat 0` was rejected by argument validation (exit 2).
- A fresh 2430 x 2430 cube reproduced the known capacity boundary: UC1 exited 0 but wrote single-colour images and its SVM map differed 100% from the tiled baseline. The measurement tool recorded the first failing size and deleted the cube; its command exit remains 0 because the size failure is a recorded finding, not a runner crash.
- The retained outputs were rechecked across 14 trials (70 counted runs); every expected output was present, the right size and non-single-colour. The release trial intentionally has only `imageRGB.bmp`; comparison output names the other five as absent relative to the intermediate baseline.

## Risks

- Laptop GPUs throttle. Record power mode and whether the laptop is on mains,
  and discard the first run.
- A faster setting that changes the output is a trade-off for the owner, not a
  win to adopt silently.
- Device-wide GPU memory includes whatever other processes allocate during the
  run (three Slicer windows were open at specification). The idle level is
  taken just before each run, and the other GPU processes are listed with the
  results; the figure is an estimate, not a per-process measurement.
- The size ladder needs up to 3.9 GB of disk per tiled cube and as much host
  memory in the UC1 process. With little free RAM the host may page or fail
  first. That is recorded as the limit it is; the other Slicer windows are
  better closed before the ladder.
- Tiled cubes repeat `002-04`, so K-means and KNN see repeated content. Time
  and memory scale with size regardless; outputs are not interpreted.
- K-means run-to-run variation makes small output differences in `kmeans` and
  `imageRGB` indistinguishable from noise; they are reported next to the
  baseline spread, not judged alone.

## Documentation impact

`docs/development/uc1_performance.md` (new), a pointer in
`docs/development/uc1_changes.md`, the variant build in
`docs/development/uc1_local_build.md`.

## Completion evidence

Implemented on 2026-09-25 on branch
`feature/SLIA-034-uc1-performance-and-large-cubes`, created from `main` at
`2fb61e8`. Automated checks and manual verification pass; the independent
review found no blocking findings, and project-owner approval to commit, push
and complete the task was granted on 2026-09-25.

### Files

Created: `docs/development/uc1_performance.md`,
`scripts/development/measure-uc1.py`, `scripts/development/measure-capture.py`.
Modified: `scripts/development/build-uc1.ps1` (`-Variant`, `-Defines`,
`-Release`), `docs/development/uc1_changes.md` (pointer section),
`docs/development/uc1_local_build.md` (measurement variants), this card (moved
from `tasks/backlog/`). Gitignored, never staged: `build/uc1/variants/`
(kmeans-shared, pca-single, kmeans-aos, release, shared-single),
`build/uc1/trials/` (trial folders, the mapped input, `results/*.json`).
Nothing under `extensions/`, `input/` or `workspace/components/` changed.

### Results (full record in `uc1_performance.md`)

- Capture to result in Slicer: 2.57 s median (2.35-2.66), of which UC1
  2.09 s and the mapped-cube write 0.35 s. This is SLIAFlow's logic, from
  the start of the run to the outputs loaded, without the window: the
  LiveView snapshot, showing the result and drawing the views are not in it.
- UC1 alone, `baseline-repeat`: 1.99 s process, 1637 ms `Time simulation`;
  K-means 619 ms, PCA 271 ms, cube read 258 ms; GPU +2641 MiB.
- `KMEANS_SHARED` + `PCA_PD=0` (`shared-single`): 1.46 s (-27 %), GPU
  +2223 MiB; only `pca.bmp` changes (281 of 1,166,400 pixels, 1 grey level).
- Five of the six parameter changes moved `imageRGB` by 1-21 % of pixels;
  KNN window 9 changed 10 pixels of `knn.bmp` and saved 27 ms. Exact pixel
  counts per class for every kept run are in the document.
  `CUDA_MODULE_LOADING=EAGER` is 0.8 s slower.
- Size limit between 2300 x 2300 (runs, `svm.bmp` identical to the tiled
  baseline) and 2430 x 2430 (exit 0, six images written, all single-colour
  from PCA on: a silent failure), the same in each of four runs per size with
  2.1-8.5 GB of RAM free. 2700 x 2700 fails the same way; the ladder stopped
  there. The raw LCTF frame, 4096 x 2160, does not fit.

### Validation

| Check | Command | Result |
| --- | --- | --- |
| Product build unchanged | `.\scripts\development\build-uc1.ps1 -Clean` | exit 0; three patches applied; only `#550-D` and `C4068`; staged tree equals vendored plus patches; intermediate binary SHA-256 `ccda0ed9...` |
| Reference check | `.\.venv\Scripts\python.exe scripts\development\check-uc1.py` | PASS, exit 0 (K-means differences 0.50 % / 0.30 %, within 1 %) |
| Variant with a broken patch fails | `build-uc1.ps1 -Variant broken-check -SkipBuild -PatchDirectory <copy with 0002 context changed>` | exit 1, `0002-calibrated-float32-input.patch does not apply`; hashes of every file under `build/uc1/UC1` identical before and after |
| Variant builds | `build-uc1.ps1 -Clean -Variant <name> ...` x 5 | exit 0 each; only the product's two expected warnings |
| Output comparison, baseline against itself | `measure-uc1.py run baseline` | four deterministic images one hash across five runs; `kmeans` 0.0036-0.0087 %, `imageRGB` 0.0007-0.0014 % between runs |
| Output comparison, changed trial | `measure-uc1.py run pca-single ...` | `pca.bmp` reported different (0.0241 %, max 1 grey level); `svm`, `knn`, `CalibratedImage_BIP` identical |
| Size guard catches a silent failure | `measure-uc1.py sizes` | 2700 x 2700: exit 0, six outputs, `svm vs tiled baseline 100.0000 %`, reported as first failure; 1080-2160 at 0.0000 % |
| Output check on every kept trial run | `measure-uc1.py recheck` | exit 0; 14 trials x 5 runs: every expected image present, 1080 x 1080, not single-colour; per-class counts recorded |
| Boundary repeated, orientation-fixed guard | `measure-uc1.py sizes --repeat 3 2300x2300 2430x2430` | exit 0; 2300: 3/3 run, `svm` 0.0000 %; 2430: 3/3 fail, `svm` 100 % and five images single-colour; tiled cubes deleted |
| Tiled cubes removed | `Test-Path build\uc1\trials\cubes` | `False` |
| `input/` untouched | `find input -newermt "2026-09-25 10:15"` | no file |
| Ruff on the new scripts | `.\.venv\Scripts\ruff.exe check scripts/development/measure-uc1.py scripts/development/measure-capture.py` | All checks passed |
| Repository quality | `.\scripts\development\run-python-quality.ps1` | exit 0 |
| Slicer tests, headless | `.\scripts\development\run-slicer-tests.ps1` | Ran 89, OK (skipped=15, headful-only), exit 0 |
| Slicer tests, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | Ran 89, OK (skipped=1, headless-only), exit 0 |

No new automated test was added (Test plan): no module behaviour changed.

### Deviations from the specification

- The size ladder's correctness guard (`svm.bmp` against the tiled baseline)
  was added during implementation, when it turned out UC1 does not check its
  CUDA calls; recorded in Requirements. Without it the ladder would have
  reported 2700 x 2700 as a success.
- Two sizes were added between 2160 and 2700 (`sizes 2300x2300 2430x2430`) to
  narrow the limit. They were first run once with a scratch script that kept
  the outputs long enough to describe them, then deleted them, and then
  recorded through `measure-uc1.py`.
- A combined variant (`shared-single`) and a repeated baseline were measured
  in addition to the listed trials, for the recommendation and because the
  first baseline ran on a GPU still at idle clock.

### Corrections after the owner's confidence check (2026-09-25)

Six concerns were raised against the first version. What changed:

1. Trials accepted any exit-0 run. `measure-uc1.py run` now checks every
   run's outputs (present, cube size, more than one colour) and fails the
   trial otherwise; `recheck` applied the check to the 70 kept runs, all pass.
2. The Capture figure was presented as click-to-result. The document, the
   card and `measure-capture.py` now say it excludes the snapshot, showing the
   result and drawing the views.
3. Per-class evidence was rounded shares of one run. The script now records
   exact counts per class for every kept run and their range; the document
   has the table. The first-run shares had put `kmeans-iter40` at 35.4 %
   tumour; the median is 35.1 %, corrected.
4. The size guard picked the closer of two row orders, which could pass a
   shifted map. It now compares in the image orientation only. The earlier
   passes at 1620 and 2300 had used that orientation, and 1080 and 2160 are
   whole multiples where both agree, so no verdict changed.
5. The boundary rested on one run per size. It was repeated three times per
   size (above) and the document now gives it as a measured, not guaranteed,
   figure.
6. Two overstated sentences (every parameter change 1-20 %; "other four"
   images of the release binary) were corrected.

## Review findings

The independent review on 2026-09-25 covered the allowed diff, the build and
measurement scripts, the documented results, and the manual-verification
evidence. No blocking findings remain. The measured UC1 allocation boundary is
retained as a documented limitation: above about 5.3 million pixels UC1 can
exit 0 while producing invalid single-colour outputs, so the measurement guard
must be consulted rather than relying on the exit code alone.

## Human approval

The project owner approved completion on 2026-09-25 after the manual
verification table and robustness probes passed. The final commit uses the
`PERF: Measure UC1 speed and large-cube limit` subject; the pushed branch is
ready for PR review.
