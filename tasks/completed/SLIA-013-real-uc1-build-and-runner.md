---
id: SLIA-013
title: Real UC1 build, runner, and MV class sender
status: active
branch: feature/SLIA-013-real-uc1-build-and-runner
priority: high
depends_on: SLIA-012
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-013 - Real UC1 build, runner, and MV class sender

## Goal

Put the genuine UC1 CUDA pipeline in the loop: build the vendored
`gpu_single_bsq` sources unmodified for this GPU, run them on a simulated cube,
recover the real classification map from the pipeline's own output files, and
send it to SLIAFlow as `UC1_MV_CLASS`.

## Context

This is the point of the whole simulator effort. Only the scene stays fake; the
calibration, PCA, SVM, KNN, K-means and majority voting are all real code doing
real work on the local GPU. When a camera arrives, the cube generator is deleted
and a folder path changes - the middle and right boxes are already the production
ones.

The toolchain is proven by execution, not inferred. The full GUIDE section 3.1-B
release command line, with `compute_90` swapped for `compute_120`, compiled all
13 translation units clean into a 951 KB `stratum.opt.exe`, which then loaded and
failed correctly against a nonexistent dataset. So `build-uc1.ps1` is
transcription, not discovery.

| Component | Verified value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5050 Laptop, 8151 MiB, compute capability 12.0 |
| Driver | 591.74 |
| CUDA Toolkit | 12.9.86, `nvcc` on PATH |
| Host compiler | MSVC 14.44.35207 (VS 2022 Community 17.14.36908.2), x64 |
| Dev environment | `VC\Auxiliary\Build\vcvars64.bat` puts both `cl.exe` and `nvcc.exe` on PATH |

Three contingencies the earlier planning carried are closed and must not be
reintroduced. `sm_120` compiles and executes natively, so no PTX-JIT fallback is
needed. nvcc 12.9 accepts `_MSC_VER` 1944, so `-allow-unsupported-compiler` must
**not** be added - it would suppress a real diagnostic on a future toolchain.
`-lcublas` links, `cublasCreate` succeeds on the device, and
`cuda_profiler_api.h` resolves.

What the trial build does not prove: the pipeline has never been run on real
input, because no dataset existed. Numerical behaviour on a synthetic cube, VRAM
headroom and wall-clock runtime are this task's only remaining risks.

Binary behaviour verified from source:

- `main.cu` line 17 consumes only `argv[1]`, the dataset folder. There is no
  stage selector; the pipeline always runs end to end.
- The binary is CWD-bound: `fopen("parameters.txt")` at line 28 and
  `fopen("../../svm_model/*.bin")` at lines 107-136 both resolve relative to the
  working directory, so CWD must be `gpu_single_bsq/source/` with `svm_model/`
  exactly two levels up. Forward slashes are fine on Windows.
- Outputs are written **into the source tree**: `output/<dataset>/imageRGB.bmp`
  and `output/rgb/{red,green,blue}.txt` at lines 159-164. Neither directory is
  created by the binary.
- `output/rgb/*.txt` are written unconditionally in every build variant, not only
  under `INTERMEDIATE_OUTPUT`. They are tab-separated ints, one row per line, with
  `R = map[pix*3+2]`, `G = map[pix*3+1]`, `B = map[pix*3+0]`.
- `parse_arguments` derives `dataset_name` from the folder basename, so a
  `sim-YYYYMMDD-HHMMSS` folder keeps simulated runs self-labelling on disk.
- The Makefile's arch is a variable (`SM=90`, `COMPUTE=$(SM)`), so `sm_120` is
  reachable with zero edits to vendored source. On Windows the explicit nvcc line
  must be used instead of `make`, because `FLAGS` carries the POSIX-only `-ldl`.
- `/build/` is already gitignored, so the staging directory needs no
  `.gitignore` change.

## Requirements

- Add `scripts/development/build-uc1.ps1` and `uc1_runner.py` to
  `tools/simulators/stratum_sim/`. Add no new Python dependency.
- Stage a regenerable copy under the already-ignored `build/uc1/`, preserving the
  two-level layout the hardcoded `../../svm_model` requires:

      build/uc1/UC1/
        svm_model/                  # copied verbatim, 5 .bin files
        gpu_single_bsq/source/      # copied verbatim, plus parameters.txt
          output/rgb/               # pre-created; the binary will not create it
          output/<dataset>/         # pre-created per run; likewise
          stratum.opt.exe

- Build with the explicit GUIDE section 3.1-B nvcc command line, not `make`,
  substituting `-gencode arch=compute_120,code=sm_120` and additionally emitting
  `-gencode arch=compute_120,code=compute_120` so the binary survives a future
  GPU change. Do not add `-allow-unsupported-compiler`.
- The build script must call `vcvars64.bat`, change directory to the staged
  source directory, then invoke nvcc.
- Expect the `#550-D` (`num_th_last_block` set but never used, `functions_cuda.cu`
  line 63) and `C4068` (unknown pragma `unroll`, `matrixlib.cpp` lines 205, 221,
  293) warnings. Treat their **absence** as the surprise. Do not silence them and
  do not "fix" them in vendored source.
- Script a post-build SHA-256 assertion that every staged source file is
  byte-identical to its `workspace/components/` original, so the "no changes to
  UC1" compliance property is re-tested on every build rather than trusted once.
- The runner must, in order: take an exclusive lock on the staged build
  directory, so two runners cannot interleave writes into one fixed output path;
  verify the dataset carries the `STRATUM SIMULATED CUBE` marker (the same
  interlock and the same `--force-unmarked` escape as SLIA-012); delete any
  existing `output/rgb/{red,green,blue}.txt` and the contents of the target
  `output/<dataset_name>/`; re-create both directories; record a pre-run
  timestamp; then run `subprocess.run([exe, dataset_folder],
  cwd=<staged source dir>)` with exactly one argument.
- Treat the output paths as fixed and shared, because they are: UC1 writes
  `output/rgb/*.txt` under the same three names on every run for every dataset.
  An existence check therefore cannot distinguish this run's output from a
  previous run's, and a crashed run that leaves last week's files behind would
  pass one. After the process exits, verify that all three files exist **and**
  that each modification time is at or after the pre-run timestamp. A file that
  fails the freshness check is a failure, never a result.
- Fail loudly on a non-zero exit code, a missing output, a stale output, or a
  `Path too long` on stderr. Never fall back to the stand-in silently; the
  operator must always know which box ran.
- Parse `output/rgb/{red,green,blue}.txt` with `np.loadtxt` and assert the three
  shapes match each other and the header dimensions.
- Recover classes using SLIA-012's single shared palette inverse: green to 1, red
  to 2, blue to 3, black to 4. Any triple not in the table is an error, not a
  guess; report the count and the first few offending coordinates.
- Emit `majorityVotingMap` as uint8 `(1, lines, samples)`, run the same NumPy
  contract self-check as SLIA-012, and send it as `UC1_MV_CLASS` through
  SLIA-011's `igtl_transport.py` carrying the same complete four-key wire
  metadata contract: `SLIAFlow.ResultMap = majorityVotingMap`,
  `SLIAFlow.DeviceName = UC1_MV_CLASS`, `SLIAFlow.DataOrigin = simulated`, and
  `SLIAFlow.SimulationDetail = "real UC1 pipeline, synthetic input"`. Header
  version 2 applies here for the same reason it applies in SLIA-012.
  **Narrowed under review finding 4 on 2026-09-04:** that remains the detail for
  any dataset that is not a tissue phantom; a phantom dataset carries
  `"real UC1 pipeline, synthetic tissue phantom"` instead, so a result node can
  say which scene produced it. The other three keys are unchanged and
  `DataOrigin` stays `simulated` in both cases.
- Implement the SLIA-011 `Classifier` protocol as
  `classify(dataset: DatasetRef) -> Uc1Maps`, using `dataset.folder` to invoke
  the executable and never calling `loadCalibratedCube()`. This is precisely why
  that protocol takes a dataset descriptor rather than an array: the real
  producer reads the raw, white-reference, dark-reference and header files
  itself, and cannot be expressed as a function of an already-calibrated cube.
  Populate `majorityVotingMap` and leave the other four fields `None`; the sender
  must treat an absent field as "not produced" and never substitute zeros.
- Send `UC1_MV_CLASS` **only**. Do not mix real and stand-in maps in one session.

## Out of scope

- Any modification to vendored UC1 source under `workspace/components/`. If the
  build turns out to require a source edit, **stop and escalate**: that is a
  roadmap-boundary decision for the project owner, not a silent fix.
- Adding an output path to UC1 so it writes the other four maps. That needs owner
  approval and a separate task.
- Running the real binary for `UC1_MV_CLASS` while the stand-in supplies the
  other four maps in the same session. See the honest gap below.
- Any change inside `extensions/`.
- Tuning the classifier. If the output is degenerate, tune the synthetic spectra
  in SLIA-011 instead. **Tuning the spectra moved into scope on 2026-09-03; see
  the added goal below. Tuning the classifier never did.**

## The honest gap

`tmdMap`, `majorityVotingProbabilityMap`, `svmProbability` and `knnProbability`
cannot come from the real binary: it computes and then discards them. Three
options exist and none is taken here.

1. Run the real binary for `UC1_MV_CLASS` and the stand-in for the other four.
   This requires a loud, non-optional distinction in the interface - two
   different `SimulationDetail` strings on two different nodes - or it silently
   implies UC1 produced all five.
2. Add an output path to UC1. Out of scope; needs owner approval.
3. Leave the four unavailable in real-UC1 mode and show the waiting state.

**The chosen default is option 3: real UC1 alone, one map, `UC1_MV_CLASS` only.**
One box, one story, nothing implied. The image contract document must record that
a real-UC1 producer currently supplies exactly one of the five roles, and that
this is a property of the upstream binary, not of SLIAFlow.

## Added goal: a scene the pipeline can resolve

Added by the project owner on 2026-09-03, after the run below showed the
genuine pipeline resolving every pixel of the existing scene to background. The
owner chose the first of the two remedies recorded under Risks, and chose to
take it inside this task rather than as a separate one.

**Build the acquisition stand-in's spectra from tissue optics, so that the model
trained on real brain reflectance has something with the right shape to
classify - and document what that does and does not mean.**

The reasoning that had to be settled before doing it, since the owner named it
explicitly: this produces a demonstration that looks like a working brain-tumour
detector whose tumour is a shape invented to trigger the model. That is a
labelling problem, not a coding one, so the work is bounded by four rules.

1. **The optical parameters are never fitted to the classifier.** Absorption
   comes from the chromophores, region parameters from published physiological
   ranges. Fitting an input to a trained model's weights produces an adversarial
   example that would light up the display and mean nothing. The shipped model
   may be used to *characterise* the result afterwards, never as an optimisation
   target.
2. **The classifier is still never tuned.** No change to `parameters.txt`, the
   SVM model, or vendored source.
3. **The construction map is not ground truth.** Where UC1 disagrees with how
   the phantom was built, the disagreement is reported. No test grades UC1
   against the phantom's regions, because a test that pinned that table would
   turn a measurement into a target.
4. **The honest reading is written down where it cannot be missed**, in a
   document of its own, in the module docstring, and on the process banner.

### Added acceptance criteria

- The spectra are built from named chromophores and a scattering model, in
  physical units, and the physics is tested - the isosbestic crossing, the red
  absorption of deoxygenated blood, the scattering power law, reflectance
  bounded in the unit interval.
- The scene mode is selectable and the previous channel scene still works. A
  camera requested with the phantom is refused, not silently ignored.
- The written dataset still clears the band covariance rank floor.
- The genuine pipeline's response to the phantom is measured region by region
  and recorded, including every place it disagrees with the construction map.
- `docs/development/synthetic_tissue_phantom.md` states plainly that a coloured
  region is not a detection.

## Files allowed

- `scripts/development/build-uc1.ps1`
- `tools/simulators/**`
- `build/uc1/**` (generated and ignored)
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/development/uc1_local_build.md`
- `docs/development/synthetic_tissue_phantom.md`
- `config/local.example.json` (the documented default block only; `config/local.json`
  stays untouched and Git-ignored)
- `tasks/{backlog,active,review,completed}/SLIA-013-real-uc1-build-and-runner.md`
- `scripts/development/run-uc1-real.ps1`
- `docs/development/uc1_demo_runbook.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/{SLIAFlowParameterNode,SLIAFlowWidget,SLIAFlowTest}.py`
  (the simulated banner wording only)

The last three were added on 2026-09-03 with the added goal below. They are the
minimum the goal needs: a document for the phantom, and the one line in the
example configuration that would otherwise stop describing the defaults.

The three after those were added on 2026-09-04, when the work was first run as
a demonstration end to end. Two are the demonstration path itself: the wrapper
script `uc1-real` never had, and the runbook that sequences it. The third is a
deliberate widening into SLIAFlow, and it is the only one: this card created a
second kind of simulated result, and the banner SLIA-010 wrote for the first
one turned out to state something false about it. That is argued below under
the risks.

## Relevant skills and references

- `workspace/components/UC1_Brain_Tumor-GPU_optimization/.../gpu_single_bsq/source/`
  - `main.cu` lines 17, 28, 56-59, 107-136, 159-164, 164-174
  - `functions.cu` lines 255-282 (the `output/rgb/*.txt` writer)
  - `data_loader.cpp` lines 66-79
  - `Makefile` lines 1-2 and 7 (arch as a variable)
- The UC1 build GUIDE, sections 3.1-B and 3.2
- SLIA-012's shared palette table, used forward there and backward here
- `.ai/policies/algorithm-boundary-policy.md`

## Approved dependencies

None. The build uses the already-installed CUDA 12.9.86 and MSVC 14.44.35207
toolchain, and the runner uses only `subprocess` and the NumPy already approved
in SLIA-011.

## Implementation plan

1. Write `build-uc1.ps1`: stage the copy, pre-create `output/rgb/`, run
   `vcvars64.bat`, invoke the transcribed nvcc line, then assert the staged
   sources still hash identically to `workspace/components/`.
2. Capture `nvcc --version` and `nvidia-smi` into the card's evidence section
   before anything else, so a machine change is detected rather than assumed
   away.
3. Write `uc1_runner.py`: marker interlock, output directory pre-creation,
   `subprocess.run` with the load-bearing CWD, and loud failure on every failure
   mode.
4. Implement `.txt` parsing and the palette inverse against SLIA-012's shared
   table, reporting unmapped triples as an error with coordinates.
5. Run the contract self-check and send `UC1_MV_CLASS` with the real-pipeline
   simulation detail.
6. Run the real GPU verification sequence below and record every measurement.

## Acceptance criteria

- `build-uc1.ps1` produces `stratum.opt.exe`, emits only the two expected
  warnings, and its post-build hash assertion confirms every staged source file
  is byte-identical to `workspace/components/`.
- The runner executes the real binary on a `demo` dataset with exit code 0 and
  produces `output/<dataset>/imageRGB.bmp` and three non-empty
  `output/rgb/*.txt`.
- The outputs read back are this run's: prior `output/rgb/*.txt` are deleted
  before the run, all three exist afterwards, and each is at or newer than the
  pre-run timestamp. A stale file fails the run rather than satisfying it.
- The recovered class map is `(1, 120, 160)` uint8 with every value in
  `{1,2,3,4}`.
- An RGB triple absent from the shared palette table is reported as an error with
  its count and first offending coordinates, never resolved to a nearest colour.
- `imageRGB.bmp` shows coherent regions rather than salt-and-pepper noise, and is
  not uniformly a single class.
- Re-running on the same dataset changes at most 0.1% of pixels, and every pixel
  that changes lies on a class boundary. Byte-identical output is deliberately
  not required: the GPU K-means reduction is not bit-deterministic, and making
  it so would mean editing vendored UC1 source. (Replaced the byte-identical
  criterion under review finding 2, owner decision 2026-09-04.)
- The runner refuses an unmarked dataset folder without `--force-unmarked`.
- A non-zero exit code, a missing output file, or a stale output each fail loudly
  and never silently fall back to the stand-in.
- The runner refuses any dataset whose header band count is not the 93 the staged
  SVM model is sized for, and refuses a model file that is not exactly its
  expected size, both before the process starts. (Added under review finding 1.)
- A dataset folder written over by a different scene never keeps the previous
  scene's phantom record. (Added under review finding 3.)
- `build-uc1.ps1` exits non-zero when an expected warning is absent or an
  unexpected one appears. (Added under review finding 6.)
- SLIAFlow receives `UC1_MV_CLASS` carrying all four wire metadata keys with
  `SLIAFlow.SimulationDetail = "real UC1 pipeline, synthetic input"` - or
  `"real UC1 pipeline, synthetic tissue phantom"` for a phantom dataset, per
  review finding 4 - and no other
  UC1 device name is sent in the same session.
- Wall-clock time and peak VRAM are recorded at both the `demo` and `full`
  presets, and both runs complete within the card's stated limits.

## Test plan

Automated tests run through `tools/simulators/tests/run_tests.py`. The build and
GPU steps are manual by nature and are covered by the numbered steps below.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| Build succeeds with only the expected warnings and unchanged source hashes | Manual steps 1 and 2 | manual |
| A real run produces exit 0 and all expected output files | Manual step 3 | manual |
| The outputs read back are this run's, not a previous run's | `test_uc1_runner.test_staleOutputIsRejectedNotAccepted` | automated; manual step 3 |
| The recovered class map has the right shape, type and class set | `test_uc1_runner.test_recoveredClassMapMatchesContract` | automated; manual step 4 |
| An unmapped RGB triple is an error, not a guess | `test_uc1_runner.test_unmappedTripleIsReportedNotGuessed` | automated |
| The output image is coherent, not degenerate | Manual step 5 | manual |
| Re-running drifts only on class boundaries, within 0.1% of pixels | Manual step 6 | manual |
| The unmarked-dataset refusal holds | `test_uc1_runner.test_unmarkedDatasetIsRefused` | automated; manual step 7 |
| Failure is loud and never falls back silently | `test_uc1_runner.test_nonZeroExitFailsLoudly` | automated |
| `UC1_MV_CLASS` arrives with all four metadata keys and is the only device sent | Manual step 9 | manual |
| VRAM and wall-clock are within the card's limits | Manual step 8 | manual |

Tests to add or change, and how each one was shown to fail first:

- Before `stratum_sim/uc1_runner.py` existed, `tools\simulators\tests\run_tests.py`
  ran 41 tests and exited 1 with `ImportError: cannot import name 'uc1_runner'
  from 'stratum_sim'`. The tests run against recorded `.txt` fixtures and an
  injected process, so they need no GPU and no CUDA toolkit.
- `test_staleOutputIsRejectedNotAccepted` back-dates the three `.txt` files by an
  hour and asserts the runner fails, then asserts the same files exist and are
  non-empty, which documents that an existence check would have accepted them.
  Shown red against a runner that checks only existence: `AssertionError:
  Uc1StaleOutputError not raised`.
- `test_nonZeroExitFailsLoudly` shown red against a runner that catches the
  failure and returns the arithmetic stand-in's class map: `AssertionError:
  Uc1ProcessFailedError not raised`.
- `test_unmappedTripleIsReportedNotGuessed` shown red against a nearest-colour
  inverse: `AssertionError: Uc1PaletteError not raised`.

Four tests beyond the card's five cover requirements that had no other coverage:
`test_secondRunnerIsRefusedWhileOneHoldsTheBuild` (the exclusive lock),
`test_pathTooLongOnStderrFails` (the exit-0 truncated-path failure mode),
`test_previousOutputsAreRemovedBeforeTheRun` (deletion happens before the
process, not after it fails), and `test_paletteInverseIsTheSharedTable` (the
inverse is SLIA-012's table object, not a second one).

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `nvcc --version` and `nvidia-smi`, and paste both into the completion evidence | CUDA 12.9.86, driver 591.74, compute capability 12.0. Any deviation means the machine changed and every step below must be re-verified rather than assumed |  Pass, 2026-09-03. `nvcc` reported `release 12.9, V12.9.86`, build `cuda_12.9.r12.9/compiler.36037853_0`; `nvidia-smi` reported `NVIDIA GeForce RTX 5050 Laptop GPU, 591.74, 12.0, 8151 MiB`. No deviation from the card's recorded values. `build-uc1.ps1` captures both before it stages anything, so this step now runs on every build |
| 2 | Run `scripts/development/build-uc1.ps1` | `stratum.opt.exe` is produced; only the `#550-D` and `C4068` warnings appear; the post-build SHA-256 assertion passes and `main.cu` still hashes `63d0e9ee...c788c0`. Compare hashes explicitly - `build/` is gitignored, so `git status` proves nothing |  Pass, 2026-09-03. 13 translation units compiled to `stratum.opt.exe`, 951808 bytes. Exactly the two expected warnings appeared and the script reported both `present`: `#550-D` at `functions_cuda.cu(63)` and `C4068` at `matrixlib.cpp(205)`, `(221)`, `(293)`. The assertion compared 37 source and 5 model files in both directions and found every one byte-identical; `main.cu` hashed `63D0E9EE5E77B06876DFA7D76965B1F67719D841D7A4012742F85E2540C788C0`. Exit 0. One benign extra line comes from inside `vcvars64.bat` itself, `'vswhere.exe' is not recognized`; the toolset is still configured and the build succeeds |
| 3 | Generate a `demo` (160x120x93) dataset and run the UC1 runner against it | Exit code 0; `output/<dataset>/imageRGB.bmp` exists and the three `output/rgb/*.txt` files are non-empty | Pass, re-verified 2026-09-03 on the tissue phantom. Phantom dataset `sim-20260903-201449` (160x120, 93 bands, band covariance rank 12; regions cortex 37.5%, tumour-like 6.9%, vessel 7.6%, drape 48.0%). The runner exited 0 and UC1's log came through: `Sample: 160`, `Lines: 120`, `KMeansIterations: 3`, `KMeansError: 0.000371`, `Time simulation ---> 299.320 ms`. `imageRGB.bmp` and all three `output/rgb/*.txt` were written, non-empty, and fresh. The earlier channel-scene run (`sim-20260903-193312`, rank 9, 11 K-means iterations, 256.677 ms) also passed |
| 4 | Inspect the recovered class map | Shape `(1, 120, 160)`, dtype uint8, every value in `{1,2,3,4}`, and zero unmapped RGB triples reported | Pass, re-verified 2026-09-03 on the tissue phantom. `shape (1, 120, 160), dtype uint8, classes {2: 7505 (39.1%), 4: 11695 (60.9%)}`. Every value is in `{1,2,3,4}` and no unmapped triple was reported. Two classes now, where the channel scene gave `{4: 19200 (100.0%)}` |
| 5 | Open `output/<dataset>/imageRGB.bmp` | Coherent regions, not salt-and-pepper and not a single uniform class. A uniform image means the synthetic spectra are degenerate - tune the NIR envelope in SLIA-011, never the classifier | **Pass, 2026-09-03, on the tissue phantom** - after failing on the channel scene, which is what the added goal was for. Coherent, not salt-and-pepper: 96.6% of pixels at `demo` and 99.7% at `full` agree with at least three of their four neighbours, and the map is two classes, not one. **Read the rest of this cell before showing the image to anyone.** UC1 does not separate the phantom's cortex from its tumour-like region - it calls both class 2 - and at `demo` it calls the vessels, the region with the most blood in it, class 4. At `full` the whole craniotomy field goes to class 2 and only the drape stays class 4, so the same phantom classified at two presets gives two answers. A red area over the tumour-like region is a trained model responding to a spectrum built to have the shape of tissue; it is not a detection. Classes 1 and 3 never appear. The card's original stated cause was wrong and is corrected under Risks: the channel cube was never degenerate, and the NIR envelope was not the problem |
| 6 | Re-run the runner on the same dataset | At most 0.1% of pixels differ from the previous run, and every differing pixel lies on a class boundary. Diff the `.txt` files rather than hashing them: a hash answers a question this step no longer asks | Pass, 2026-09-03, on the tissue phantom, measured against this criterion. Six consecutive `demo` runs on one dataset changed 6 pixels of 19200 (0.036%), inside the 0.1% bound, and all 6 lie on a class boundary - coordinates (24,40), (50,107), (50,108), (59,122), (62,105), (102,93). The map is stable everywhere else. Cause: ordinary floating-point non-determinism in the GPU K-means reduction moves a borderline pixel between clusters, and majority voting then hands it the other cluster's class. This step originally demanded byte-identical `.txt` files and failed as worded; the byte-identical result recorded earlier against the channel scene was never evidence of determinism, because a uniformly single-class map is byte-identical far more easily than a varied one. The owner replaced the criterion with the bound above on 2026-09-04, under review finding 2 |
| 7 | Point the runner at a folder whose header lacks the simulated marker | It refuses and names the missing marker; it proceeds only with an explicit `--force-unmarked` |  Pass, 2026-09-03. Against a copy whose `raw.hdr` marker was replaced, the run refused with `ERROR: Refusing to run UC1 on ...: raw.hdr lacks the STRATUM SIMULATED CUBE marker. Pass --force-unmarked only for an explicitly approved synthetic test dataset.` and exit 1, with no process started. The same folder ran only with `--force-unmarked`, and only behind the `WARNING: --force-unmarked is enabled...` line |
| 8 | Record wall-clock time and peak VRAM for the `demo` run, then repeat once at `full` (640x480) | Both complete; the 8 GB card is confirmed not to be the limit at `full`. A dataset at `full` is 3 x 54.49 MiB, well inside the roughly 7 GB free with the desktop running | Pass, re-verified 2026-09-03 on the tissue phantom. `nvidia-smi` sampled throughout each run against a 1182 MiB idle desktop baseline on the 8151 MiB card. Phantom `demo`: 299.3 ms internal, peak 1325 MiB, 143 MiB over baseline. Phantom `full`: 446.8 ms internal, peak 1973 MiB, 791 MiB over baseline. The card is nowhere near the limit at `full`. The scene does not move the memory figures - the cube size sets those - but it moves the time, because it moves the K-means iteration count: 3 iterations at `demo` and 2 at `full`, well inside the 20-iteration cap the channel scene hit at `full`. Channel-scene figures, measured earlier: `demo` 262.7 ms / 135 MiB over, `full` 622.3 ms / 783 MiB over |
| 9 | Connect the small pyigtl client to `127.0.0.1:18945` for a full runner session and print every received device name and metadata dictionary | Only `UC1_MV_CLASS` is ever sent, and its metadata carries all four keys with `SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic input`. Any second `UC1_*` device name in the session violates the one-box rule | Pass, re-verified 2026-09-03 on the tissue phantom. A sender session recorded with `uc1_client.py --session-seconds 6`: 5 messages, one distinct device name, `UC1_MV_CLASS`, at `(1, 120, 160)` uint8, header version 2, carrying `SLIAFlow.ResultMap = majorityVotingMap`, `SLIAFlow.DeviceName = UC1_MV_CLASS`, `SLIAFlow.DataOrigin = simulated` and `SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic input`. No second `UC1_*` name appeared; client exit 0. Note the gap recorded in the image contract: that detail string is the same for both scenes, so a result node alone does not say which scene produced it |
| 10 | Compare the recovered map against `phantom_regions.npy` region by region, and record every disagreement | The comparison is recorded whatever it says. A table that matched the construction map everywhere would be the surprising result, not the reassuring one |  Pass, 2026-09-03. At `demo`: cortex 85.9% class 2 / 14.1% class 4; tumour-like 100% class 2; vessel 100% class 4; drape 100% class 4. At `full`: the entire craniotomy field class 2, drape class 4. UC1 separates the field from the drape and nothing finer. Recorded in full in `docs/development/synthetic_tissue_phantom.md`, together with the numpy replica of UC1's SVM used to characterise it - which reproduces the real binary's SVM stage on the channel scene to 97.17% against the 97.2% measured from `svm.bmp` |
| 11 | Ask the acquisition stand-in for the tissue scene with `--frame-source webcam` | It refuses and names `channel` as the mode that takes a camera. Accepting the setting and ignoring it would leave an operator believing the phantom was built from what the camera saw |  Pass, 2026-09-03. `ConfigurationError`, covered by `test_tissueSceneRefusesACameraRatherThanIgnoringIt`, and the `channel` mode still accepts a webcam |

## Risks

### Resolved: UC1 classified the whole channel scene as background

Measured, 2026-09-03. Both numerical unknowns this card carried are now answered,
and they answered differently.

Cost is a non-issue: 262.7 ms and 135 MiB at `demo`, 622.3 ms and 783 MiB at
`full`, on an 8151 MiB card. Nothing here constrains the demonstration.

The result is degenerate. UC1 resolves every pixel to class 4, background, at
both presets. The run is genuine and the map is a valid contract map; it simply
shows nothing, which fails the acceptance criterion that the image not be a
single uniform class.

**The remedy this card prescribes does not apply.** The card says a uniform image
means the synthetic spectra are degenerate and the NIR envelope should be tuned
in SLIA-011. The cube is not degenerate: band covariance rank 9, calibrated
values from 1.5 to 90, spectra that vary spatially, and the same generator that
SLIA-011 and SLIA-012 both validated. Tuning the envelope on that diagnosis would
be guessing.

Where it actually collapses was measured with UC1's own `INTERMEDIATE_OUTPUT`
build, which writes one bitmap per stage:

| Stage | Output |
| --- | --- |
| PCA | varied |
| SVM | already 97.2% background |
| KNN | 98.0% background |
| K-means | healthy: 24 distinct clusters, each 5-7% of the image |
| Majority voting | 100% background |

So spatial structure survives to the last stage. The SVM probability stage
assigns background, and majority voting - which gives every pixel its K-means
cluster's dominant KNN class - then erases the surviving 2%.

The cause is visible in the source. `normalizeImgKernel_optimized` min-max
normalizes each pixel's spectrum across bands before the SVM, so only spectral
*shape* reaches the classifier, never magnitude. The shipped `w_vector.bin` is a
linear model trained on real in-vivo brain reflectance. The stand-in's spectra
are built from an RGB-driven channel basis plus texture features, and that shape
is not what the trained model recognises as tissue.

**Two remedies existed. The project owner chose the first on 2026-09-03 and
asked for it inside this task**, which is the added goal above.

1. Tune the SLIA-011 synthetic spectra toward real in-vivo brain reflectance -
   haemoglobin absorption features, the NIR rise - until the trained model
   reports tissue classes. **Taken.** It was named for what it is when it was
   chosen: it produces a demonstration that looks like a working brain-tumour
   detector whose tumour is a shape invented to trigger the model. The four
   rules under the added goal are what keep that from becoming a false claim,
   and the measured disagreements in manual step 10 are the evidence that it is
   a plumbing demonstration and not a detector.
2. Accept a uniform map as the honest current result and defer a varied
   demonstration to real data. Not taken.

The classifier is never tuned under either option. Changing `parameters.txt`,
the SVM model, or vendored source to make an invented scene produce a colourful
map would make every future result meaningless. The runner still reports a
uniform result loudly - `uniformClassWarning` on stderr - so a scene that stops
working says so.

### Closed under review: the wire now distinguishes the two scenes

Both streams name the scene. The map stream reports
`real UC1 pipeline, synthetic tissue phantom` for a phantom dataset and
`real UC1 pipeline, synthetic input` for anything else, read from the dataset
folder rather than from a flag. See review finding 4.

### Decided: bounded boundary drift replaces byte-identical re-runs

Six boundary pixels of 19200 move between runs, so the original byte-identical
criterion could not hold on a varied map. Achieving determinism would require
editing vendored UC1 source, which is out of scope for this card. On 2026-09-04
the project owner replaced the criterion with the measurable bound now recorded
above - at most 0.1% of pixels change and every changed pixel is on a class
boundary - which the measurement meets with a wide margin. Nothing from the
2026-09-04 review is left open.

### Decided: the banner said something false about real-pipeline output

Found on 2026-09-04, running the work as a demonstration for the first time.
SLIA-010 fixed one headline over every simulated result, `SIMULATED - NOT A
GENUINE UC1 RESULT`, and at the time that was exactly right: the only producer
was the arithmetic stand-in, which is not a classifier. This card added a second
producer for which the sentence is untrue. The genuine vendored pipeline running
on an invented scene *is* a genuine UC1 result; only its input is synthetic. The
view showed the two lines together:

```
SIMULATED - NOT A GENUINE UC1 RESULT
real UC1 pipeline, synthetic tissue phantom
```

An audience that reads a red safety banner contradicting the line under it stops
believing the banner, which costs more than the wording ever saved. The headline
is now chosen from the detail the producer puts on the wire: a detail beginning
`real UC1 pipeline` gets `SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL
RESULT`, everything else keeps SLIA-010's wording. Three properties were kept
deliberately. The banner is still unconditional over any simulated origin, and a
banner that cannot be drawn still withholds the result. The stand-in wording is
still the default, so a producer that stops describing itself is never handed
the softer sentence. And nothing about the *decision* to banner reads the
detail: it selects wording only, exactly as the contract already required of
that attribute.

### Carried risks, all addressed

Running the binary in place would write output into the vendored reference copy,
which is why staging under `build/uc1/` is mandatory rather than convenient. The
post-build hash assertion exists so that a future edit to the build script cannot
quietly break the compliance property; it now checks both directions, so a file
added to the staging area with no original is caught as well as a changed one.

Running the binary in place would write output into the vendored reference copy,
which is why staging under `build/uc1/` is mandatory rather than convenient. The
post-build hash assertion exists so that a future edit to the build script cannot
quietly break the compliance property.

A silent fallback to the stand-in on a UC1 failure would be the worst possible
outcome of this task: the operator would believe the real pipeline ran when it
did not. Hence loud failure on every path and a test written specifically against
the fallback behaviour.

Mixing real and stand-in maps in one session would imply UC1 produced all five
contract maps. That is why the default is one map from one box.

## Documentation impact

- `docs/development/uc1_local_build.md`: new. The exact nvcc command line, the
  staging layout, the CWD requirement, the expected warnings, the hash
  assertion, and the recorded toolchain versions the binary was proven against.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: record that a real-UC1
  producer supplies exactly one of the five roles, that this is a property of the
  upstream binary rather than of SLIAFlow, the three options for the other four
  maps with the chosen default, and the real runner's four wire metadata values.
  Extended 2026-09-04 with the two banner headlines and the rule that picks
  between them.
- `docs/development/uc1_demo_runbook.md`: new, 2026-09-04. The order the three
  processes are started in for a demonstration, the output each step prints,
  what may and may not be claimed while it is on screen, and a table of the
  runner's refusals against what each one means.

## Completion evidence

Implemented 2026-09-03 on `feature/SLIA-013-real-uc1-build-and-runner`.

### Selection

Selected as the next eligible task. `tasks/active/` and `tasks/review/` were both
empty and the worktree was clean on `main`. Only two backlog cards had complete
dependencies: this one (SLIA-012 is in `tasks/completed/`, merged as `33c064b`)
and medium-priority SLIA-015. This card is high priority and unblocks SLIA-007,
SLIA-008 and SLIA-014.

### Toolchain, captured before staging

```text
nvcc: Cuda compilation tools, release 12.9, V12.9.86
      Build cuda_12.9.r12.9/compiler.36037853_0
nvidia-smi: NVIDIA GeForce RTX 5050 Laptop GPU, 591.74, 12.0, 8151 MiB
```

No deviation from the values this card was written against.

### Build

`.\scripts\development\build-uc1.ps1 -Clean`, exit 0. 37 source files and 5
model files staged; `output/rgb/` pre-created; 13 translation units compiled to
`stratum.opt.exe`, 951808 bytes.

Warnings, both `present` as expected and neither silenced:

- `functions_cuda.cu(63): warning #550-D: variable "num_th_last_block" was set but never used`
- `matrixlib.cpp(205), (221), (293): warning C4068: unknown pragma 'unroll'`

SHA-256 assertion: 37 source and 5 model files compared in both directions, all
byte-identical to `workspace/components/`; no extra staged file outside the known
build products. `main.cu` hashed
`63D0E9EE5E77B06876DFA7D76965B1F67719D841D7A4012742F85E2540C788C0`, matching the
value in this card.

`-allow-unsupported-compiler` was not added. `sm_120` is emitted natively and a
second `-gencode` emits PTX for a future GPU.

### Runs

| Preset | Cube | UC1 internal | Wall clock | Peak VRAM | Over 1190 MiB baseline |
| --- | --- | --- | --- | --- | --- |
| `demo` | 160 x 120 x 93 | 262.7 ms | 0.376 s | 1325 MiB | 135 MiB |
| `full` | 640 x 480 x 93 | 622.3 ms | 0.759 s | 1973 MiB | 783 MiB |

Determinism: two consecutive `demo` runs produced `output/rgb/*.txt` hashing
`009FCBFA280EF014...` in both. See manual step 6 for why this evidence is weaker
than intended while the map is uniform.

Wire session: 3 cycles, one distinct device name (`UC1_MV_CLASS`), header version
2, all four metadata keys with
`SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic input`.

### Automated validation

- Red-first: 41 tests, exit 1, `ImportError: cannot import name 'uc1_runner'`.
- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: **68 tests**,
  all passed, exit code 0. 53 before the added goal, plus 15 in `test_tissue.py`.
- Seven negative controls, each run against the exact behaviour it forbids and
  each red. Three for the runner: existence-only freshness check, silent
  stand-in fallback, nearest-colour palette inverse. Four for the phantom:
  within-region modulation removed (rank 3, below the floor of 8), the drape
  modelled as bloodless tissue, deoxyhaemoglobin stripped of its red shoulder
  and NIR peak, and the regions scattered into noise instead of drawn as areas.
- **One of those controls found a real defect and it was fixed, not excused.**
  `test_drapeIsNotModelledAsTissue` originally passed even when the drape *was*
  modelled as bloodless tissue: the assertion it made was too weak to
  distinguish them. It now tests the property that actually separates a dyed
  fabric from a turbid medium - the fabric has a strict local maximum in the
  green, which the scattering power law cannot produce at any blood volume -
  and it is red against the forbidden behaviour.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21, 6 SLIAFlow files
  and 29 simulator files, all checks passed, exit code 0.
- `.\scripts\development\run-slicer-tests.ps1`: 28 tests passed, 2 skipped
  because the no-main-window session has no layout manager, exit code 0.
- `git diff --check`: passed, exit code 0.
- `.\scripts\development\build-uc1.ps1` re-run after the added goal: exit 0, both
  expected warnings `present`, 37 source and 5 model files byte-identical in
  both directions, `main.cu` still `63D0E9EE...C788C0`.

### Scope

Every changed path is in this card's `Files allowed`, including the three paths
added with the added goal. No file under
`extensions/`, `apps/`, `source/`, `knowledge/`, or `workspace/components/` was
modified, and no local configuration was touched. The `INTERMEDIATE_OUTPUT`
diagnostic binary built to localise the SVM collapse was removed afterwards; the
staged tree holds only `stratum.opt.exe` and its import library.

### The added goal

Implemented 2026-09-03 after the project owner chose remedy 1 and asked for it
inside this task. `tools/simulators/stratum_sim/tissue.py` builds the scene from
oxy- and deoxyhaemoglobin absorption, a water band, a reduced-scattering power
law, and the diffusion-approximation reflectance of a semi-infinite turbid
medium. The regions are an elliptical craniotomy field on a drape, with a
tumour-like blob and three vessel tracks inside it; the drape is modelled as
dyed fabric, not as bloodless tissue. Within-region parameters are modulated by
smooth fields so each region spans a range rather than repeating one spectrum.
`sceneMode` selects it, `tissue` is the default, and the previous `channel`
scene is unchanged and still the only one that can carry motion or a camera.

In `tissue` mode the cube is built first and the LiveView frame is rendered from
it, so the live pane and the dataset are projections of the same array. A camera
requested with the phantom is refused rather than ignored.

Measured on the written dataset: band covariance rank 12 against a floor of 8.
The genuine pipeline now returns two classes in coherent regions, so manual step
5 passes, and steps 3, 4, 8 and 9 are re-verified on the phantom.

**Where UC1 disagrees with how the phantom was built, recorded rather than
corrected.** It does not separate the cortex from the tumour-like region; it
calls both class 2. At `demo` it calls the vessels - the region with the most
blood in it - class 4. At `full` the entire craniotomy field goes to class 2.
Classes 1 and 3 never appear. A `numpy` replica of UC1's SVM, validated against
the real binary's SVM stage to 97.17% against a measured 97.2%, assigns only
classes 2 and 4 over 8960 combinations spanning the physiological ranges; class
1 appears there only at implausible parameters and class 3 never.

The optical parameters were never fitted to the classifier, no vendored source
or model was touched, and no test grades UC1 against the construction map.
`docs/development/synthetic_tissue_phantom.md` carries the model, the
parameters, the measured comparison, and the statement that a coloured region is
not a detection.

### Not met

Nothing outstanding. The acceptance criterion once worded "Re-running on the
same dataset produces byte-identical `.txt` outputs" was never met on a varied
map - 6 boundary pixels of 19200 (0.036%) move between runs - and it was
written against a scene that turned out to produce a uniform map, which is
byte-identical far more easily. The owner replaced it on 2026-09-04 with the
bounded-drift criterion, which this pipeline meets: the drift measured is a
third of the bound and confined to class boundaries.

Every acceptance criterion and manual step now passes. The scene-provenance gap
recorded here earlier was closed under review finding 4.

## Review findings

Project-owner review, 2026-09-04. Six findings, ranked by the reviewer. Five are
fixed below; the sixth was an acceptance criterion the pipeline cannot satisfy,
and the owner replaced it on 2026-09-04. Nothing is left open.

Reviewer's own validation: 68 simulator tests, Ruff, 28 Slicer tests with the 2
expected no-layout skips, and `git diff --check`, all passing.

### 1. High - a non-93-band dataset could run against the wrong SVM model. Fixed

The staged `svm_model/` is sized for 93 bands. `main.cu` reads the band count
from the dataset header and then reads that many float32 weights per binary
classifier out of `w_vector.bin` without checking how many `fread` returned, so
a wider dataset reads past the end of the file and a narrower one classifies
against a truncated model - both exiting 0 with a map that looks like a result.
The configuration validator documents any band count of 8 or more, so this was
reachable from a supported setting.

`Uc1Build.assertModelIsIntact` now checks all five model files exist at exactly
their expected sizes, and `assertDatasetMatchesModel` refuses any dataset whose
header does not declare 93 bands. Both run before the process starts, so a
refused run leaves nothing behind. The error names the dataset's own
`svm_model/` as *not* a substitute, since UC1 resolves
`../../svm_model/*.bin` against its working directory and never against the
dataset.

The reviewer was also right that the fixture hid the failure mode. The runner
tests used a four-band dataset and empty model files - a configuration the real
binary cannot serve. `makeMarkedDataset` now defaults to 93 bands and
`makeStagedBuild` writes model files at their real sizes, so the other tests
exercise the path they claim to. Four new tests cover the refusals, and one
checks the expected sizes against the vendored model rather than only against a
fixture this repository wrote.

### 2. High - a stated acceptance criterion is known to fail. Decided

Byte-identical re-runs. Six boundary pixels of 19200 (0.036%) move between runs.
The behaviour is not fixable inside this card's scope: the variation is
floating-point non-determinism in the GPU K-means reduction, and removing it
would mean editing vendored UC1 source, which is explicitly out of scope and a
roadmap-boundary decision.

So the reviewer's second branch applies, and the project owner took it on
2026-09-04: the criterion is replaced with a measurable bounded-drift
requirement - at most 0.1% of pixels change between runs on one dataset, and
every changed pixel lies on a class boundary. The bound was not fitted to the
measurement; it is roughly three times the observed 0.036%, so a real
regression in stability would still fail it. The acceptance criteria,
traceability table and manual step 6 all carry the replacement wording, and
manual step 6 passes against it. Determinism itself, if it is ever wanted, is a
separate card that would have to reopen the vendored source.

### 3. Medium - a reused folder could keep a stale phantom record. Fixed

`--dataset-folder` points two runs at one folder and the ENVI writer replaces
only the four files it owns, so a channel dataset written over a phantom
inherited `phantom_regions.npy` and `.json` and appeared to be described by
them - including which regions were tumour-like.

`tissue.removePhantomRecord` now runs inside `_writeCubeAsDataset`, on the path
both scenes share, and the phantom path writes its own record afterwards. So the
invariant holds structurally rather than by remembering to clean up: a record
exists only where the phantom just wrote one. The removal is reported on the
console when it happens. Three tests cover the overwrite, the phantom rewrite,
and the no-op case.

### 4. Medium - result provenance could not identify the input scene. Fixed

`simulationDetailForDataset` reads the dataset folder and stamps
`real UC1 pipeline, synthetic tissue phantom` for a phantom or
`real UC1 pipeline, synthetic input` for anything else. It reads the folder
rather than taking a flag, so the detail cannot disagree with the data that was
actually read, and `DataOrigin` stays `simulated` either way.

This narrows the acceptance criterion rather than replacing it: the original
string remains exactly what a non-phantom dataset produces. The image contract
records both strings and the rule that a consumer must never branch on the
detail.

### 5. Medium-low - the CUDA path was weakly automated. Fixed

`RealBinaryIntegrationTest` runs the staged binary for real: model loading,
CUDA execution, UC1's own path handling and the creation of real output files,
none of which the injected process reaches. It skips rather than fails when
`build/` is absent, since the CUDA toolchain is not a checkout prerequisite, and
it writes its dataset under `build/` because a temporary path overruns UC1's
128-byte path buffer. It takes the same exclusive lock as any other run, so it
cannot run beside a live sender - which is the lock doing its job.

Two tests, 2.1 s for the whole suite. The reviewer's underlying point stands and
is not fully closed: this exercises one dataset at one size on one machine.

### 6. Low - the build script did not enforce its warning contract. Fixed

A missing expected warning printed yellow and exited 0, and an unexpected
warning was never detected at all. Both now fail the build. Unexpected warnings
are found by matching every `warning #NNN-X` and `warning CNNNN` line and
subtracting the expected codes, so a new diagnostic cannot pass by being
unlisted. The message says explicitly that the vendored source is not to be
silenced to clear it.

Verified against four cases: both expected and nothing else passes; an extra
nvcc warning, an extra MSVC warning, and a missing expected warning each fail.

### Validation after the fixes

- `tools\simulators\tests\run_tests.py`: **81 tests**, all passed, exit 0
  (68 before this review, plus 13).
- `run-python-quality.ps1`: Ruff 0.15.21, all checks passed, exit 0.
- `run-slicer-tests.ps1`: 28 passed, 2 skipped, exit 0.
- `build-uc1.ps1`: exit 0, both warnings `present`, hash assertion passed,
  `main.cu` still `63D0E9EE...C788C0`.
- `git diff --check`: exit 0.

### Demonstration path, 2026-09-04

The whole thing run as it would be run in front of someone, on a phantom dataset
written the same morning:

- `run-acquisition-simulator.ps1` with defaults: `demo`, 93 bands, tissue.
  Regions cortex 37.5%, tumour-like 6.9%, vessel 7.6%, drape 48.0%.
- `run-uc1-real.ps1 -ClassifyOnly`: K-means converged in 3 iterations, 249.6 ms,
  map `{2: 7503 (39.1%), 4: 11697 (60.9%)}`. A second run of the same dataset
  gave 7502/11698 - one pixel of 19200, 0.005%, inside the drift criterion.
- `run-uc1-real.ps1 -Cycles 3` with `tests/uc1_client.py --session-seconds 8`:
  three `UC1_MV_CLASS` messages, no other `UC1_*` device name, and
  `SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic tissue phantom` on
  the wire.
- `run-slicer-tests.ps1`: 30 tests, exit 0, 3 skipped for a headless session
  with no layout manager (the two pre-existing banner tests and the new one).
- `run-python-quality.ps1`: Ruff 0.15.21, both targets OK, exit 0.

## Human approval

Required before review and completion.
