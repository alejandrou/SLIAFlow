---
id: SLIA-013
title: Real UC1 build, runner, and MV class sender
status: backlog
branch:
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
  in SLIA-011 instead.

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

## Files allowed

- `scripts/development/build-uc1.ps1`
- `tools/simulators/**`
- `build/uc1/**` (generated and ignored)
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/development/uc1_local_build.md`
- `tasks/{backlog,active,review,completed}/SLIA-013-real-uc1-build-and-runner.md`

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
- Re-running on the same dataset produces byte-identical `.txt` outputs.
- The runner refuses an unmarked dataset folder without `--force-unmarked`.
- A non-zero exit code, a missing output file, or a stale output each fail loudly
  and never silently fall back to the stand-in.
- SLIAFlow receives `UC1_MV_CLASS` carrying all four wire metadata keys with
  `SLIAFlow.SimulationDetail = "real UC1 pipeline, synthetic input"`, and no other
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
| Re-running is deterministic | Manual step 6 | manual |
| The unmarked-dataset refusal holds | `test_uc1_runner.test_unmarkedDatasetIsRefused` | automated; manual step 7 |
| Failure is loud and never falls back silently | `test_uc1_runner.test_nonZeroExitFailsLoudly` | automated |
| `UC1_MV_CLASS` arrives with all four metadata keys and is the only device sent | Manual step 9 | manual |
| VRAM and wall-clock are within the card's limits | Manual step 8 | manual |

Tests to add or change, and how each one will be shown to fail first:

- All five automated tests fail with `ModuleNotFoundError` for
  `stratum_sim.uc1_runner` before that module exists; record the output. They run
  against recorded `.txt` fixtures captured from a real run, so they need no GPU.
- `test_staleOutputIsRejectedNotAccepted` writes the three `.txt` files with a
  modification time before the pre-run timestamp and asserts the runner fails. It
  is additionally shown red against a runner that checks only existence, which is
  the behaviour this card replaces.
- `test_nonZeroExitFailsLoudly` is additionally shown red against a runner that
  falls back to the stand-in, which is the exact failure mode this card forbids.
- `test_unmappedTripleIsReportedNotGuessed` is shown red against a
  nearest-colour inverse, proving the strict table is enforced.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `nvcc --version` and `nvidia-smi`, and paste both into the completion evidence | CUDA 12.9.86, driver 591.74, compute capability 12.0. Any deviation means the machine changed and every step below must be re-verified rather than assumed | |
| 2 | Run `scripts/development/build-uc1.ps1` | `stratum.opt.exe` is produced; only the `#550-D` and `C4068` warnings appear; the post-build SHA-256 assertion passes and `main.cu` still hashes `63d0e9ee...c788c0`. Compare hashes explicitly - `build/` is gitignored, so `git status` proves nothing | |
| 3 | Generate a `demo` (160x120x93) dataset and run the UC1 runner against it | Exit code 0; `output/<dataset>/imageRGB.bmp` exists and the three `output/rgb/*.txt` files are non-empty | |
| 4 | Inspect the recovered class map | Shape `(1, 120, 160)`, dtype uint8, every value in `{1,2,3,4}`, and zero unmapped RGB triples reported | |
| 5 | Open `output/<dataset>/imageRGB.bmp` | Coherent regions, not salt-and-pepper and not a single uniform class. A uniform image means the synthetic spectra are degenerate - tune the NIR envelope in SLIA-011, never the classifier | |
| 6 | Re-run the runner on the same dataset | The three `.txt` files are byte-identical to the previous run | |
| 7 | Point the runner at a folder whose header lacks the simulated marker | It refuses and names the missing marker; it proceeds only with an explicit `--force-unmarked` | |
| 8 | Record wall-clock time and peak VRAM for the `demo` run, then repeat once at `full` (640x480) | Both complete; the 8 GB card is confirmed not to be the limit at `full`. A dataset at `full` is 3 x 54.49 MiB, well inside the roughly 7 GB free with the desktop running | |
| 9 | Connect the small pyigtl client to `127.0.0.1:18945` for a full runner session and print every received device name and metadata dictionary | Only `UC1_MV_CLASS` is ever sent, and its metadata carries all four keys with `SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic input`. Any second `UC1_*` device name in the session violates the one-box rule | |

## Risks

The remaining unknowns are purely numerical: whether synthetic spectra drive the
real classifier to a non-degenerate result, and what that costs in VRAM and
wall-clock. Everything environmental is closed by the trial build.

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

## Completion evidence

Reserved for implementation evidence. Must include the captured `nvcc --version`
and `nvidia-smi` output, the build warning list, the SHA-256 comparison, the
measured wall-clock and peak VRAM at both `demo` and `full`, and the determinism
check.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
