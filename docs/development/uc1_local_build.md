# Building and running the genuine UC1 pipeline locally

This describes how the vendored UC1 CUDA pipeline is compiled and run on this
machine, and what was actually measured when it was. Nothing in
`workspace/components/` is modified: the sources are staged, patched, built and
executed somewhere else, and every build re-proves by hash that the staged tree
is the vendored one plus the versioned patches and nothing else.

Since `SLIA-033` the pipeline runs on IUMA's calibrated LCTF cube `002-04`, mapped
onto the model's 93 bands, and still runs unchanged on the recorded reference
case `020-01` of the HSI Human Brain Database. The patches, the band mapping and
what each produced are recorded in [`uc1_changes.md`](uc1_changes.md).
Calibration, PCA, SVM, KNN, K-means and majority voting are the vendored code
doing real work on the local GPU. The acquisition event is simulated, so a
result is marked `simulated`, and nothing it produces is a clinical result.

## Toolchain the binary was proven against

Recorded from `build-uc1.ps1`, which captures both before it stages anything, so
a machine change is detected rather than assumed away.

| Component | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5050 Laptop GPU, 8151 MiB, compute capability 12.0 |
| Driver | 591.74 |
| CUDA Toolkit | 12.9.86 (`nvcc` release 12.9, V12.9.86) |
| Host compiler | MSVC from Visual Studio 2022 Community, x64 |
| Dev environment | `VC\Auxiliary\Build\vcvars64.bat` |

Three contingencies earlier planning carried are closed and must not be
reintroduced. `sm_120` compiles and executes natively, so there is no PTX-JIT
fallback. nvcc 12.9 accepts this MSVC, so `-allow-unsupported-compiler` must
**not** be added: it would suppress a real diagnostic on a future toolchain.
`-lcublas` links and `cuda_profiler_api.h` resolves.

## Build

```powershell
.\scripts\development\build-uc1.ps1
.\scripts\development\build-uc1.ps1 -Clean     # discard previous outputs first
```

The script captures the toolchain, stages the sources, applies the patches in
`scripts/development/uc1-patches/` in name order, pre-creates the output
directories, builds two binaries, checks each one's expected warnings, and
asserts the staged tree hashes identically to `workspace/components/` plus the
patches. Then check the result against the reference case and each patch's own
check ([`uc1_changes.md`](uc1_changes.md)):

```powershell
.\.venv\Scripts\python.exe scripts\development\check-uc1.py
```

| Binary | Command line | Used by |
| --- | --- | --- |
| `stratum.opt.exe` | GUIDE section 3.1-B release | Nothing since `SLIA-028`; it was the `tools/simulators` UC1 runner's |
| `stratum.opt.intermediate.exe` | the same, plus `-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT` (GUIDE 3.1-B intermediate) | SLIAFlow, inside Slicer (`SLIA-027`) |

### Staging layout

The layout is load-bearing, not tidiness. `main.cu` opens the SVM model as the
literal relative path `../../svm_model/*.bin`, resolved against the working
directory, so the model must sit exactly two levels above the source directory.

```text
build/uc1/
  UC1/
    svm_model/                copied verbatim, 5 .bin files
    gpu_single_bsq/source/    37 files including parameters.txt, patched
      output/rgb/             pre-created; the binary will not create it
      output/<dataset>/       pre-created per run; likewise
      stratum.opt.exe
      stratum.opt.intermediate.exe
    input/<cube>/             raw.dat and raw.hdr: the mapped cube SLIAFlow
                              writes at every Capture and gives UC1
  expected/                   vendored source plus patches, for the hash check
  reference-unpatched/        a saved run of the unpatched build on 020-01,
                              for check-uc1.py
```

The binary is never built or run in place: `main.cu` writes its output into the
source tree it runs from, so building in `workspace/components/` would deposit
generated files inside the vendored reference copy. `build/` is already
gitignored, so no `.gitignore` change is needed - and, for the same reason,
`git status` proves nothing about the staged copy. The hash assertion is what
proves it.

### The command line

`nvcc` is invoked directly rather than through `make`. The Makefile's `FLAGS`
carries the POSIX-only `-ldl`, which does not link on Windows. The command is
the GUIDE section 3.1-B release line, transcribed, with two changes:

```bat
nvcc main.cu functions.cu functions_kmeans.cu functions_cuda.cu ^
     HySimeFilter\hysime.cu HySimeFilter\hysimefunc.cu HySimeFilter\lib.cu ^
     HySimeFilter\matrixlib.cpp HySimeFilter\matrixop.cpp ^
     HySimeFilter\ompfunc.cpp HySimeFilter\svd.cpp ^
     BitmapWriter.cpp data_loader.cpp ^
     -IHySimeFilter\ -I. ^
     -gencode arch=compute_120,code=sm_120 ^
     -gencode arch=compute_120,code=compute_120 ^
     -std=c++17 ^
     -DOPTIMIZE_KMEANS=1 -DPCA_PD=1 ^
     -lcublas -O3 -o stratum.opt.exe
```

`compute_90` becomes `compute_120` for this GPU, and a second `-gencode` emits
PTX so the binary survives a future GPU change. The Makefile's arch is already a
variable (`SM=90`), so this needs no edit to vendored source.

### Expected warnings

Each binary has its own expected-warnings list in `build-uc1.ps1`. Measured on
2026-09-17, both command lines emit exactly the same two warnings. They are not
silenced, and the vendored source is not edited to remove them. Their
**absence**, or any other warning, is the surprise, and the build script fails
on it.

| Warning | Where |
| --- | --- |
| `#550-D` | `functions_cuda.cu` line 63, `num_th_last_block` set but never used |
| `C4068` | `matrixlib.cpp` lines 205, 221, 293, unknown pragma `unroll` |

`vcvars64.bat` also prints `'vswhere.exe' is not recognized` on this machine.
That comes from inside the vcvars batch file, is unrelated to the compilation,
and is harmless; the toolset is still configured and the build succeeds.

### The hash assertion

After every build, the script rebuilds `build/uc1/expected/` from a fresh copy of
the vendored source with the same patches applied, and compares each staged file
against it by SHA-256, in both directions: a changed or missing file fails, and
so does a staged file with no counterpart that is not a known build product.
That last check is what would catch an edit made by addition. The model is
compared against the vendored `svm_model/` directly; no patch touches it.

The patches are applied with `git apply` run from the repository root with the
staged folder as `--directory`. Run from inside the ignored staged folder,
`git apply` reads the patch paths from the repository root, skips every file,
prints `Skipped patch` and exits 0; the first version of the script passed that
way at `SLIA-033`, with a vendored `main.cu` in the staged tree. The script now
fails on any skipped patch.

Reference value of the vendored source, printed on every build:

| File | SHA-256 |
| --- | --- |
| `gpu_single_bsq/source/main.cu`, vendored | `63D0E9EE5E77B06876DFA7D76965B1F67719D841D7A4012742F85E2540C788C0` |

UC1 is changed only through a patch in `scripts/development/uc1-patches/`,
recorded in `uc1_changes.md` (`ADR-0004` decision 3). An edit anywhere else fails
the hash assertion.

## The intermediate build SLIAFlow runs

`stratum.opt.intermediate.exe` takes a folder holding `raw.hdr` and `raw.dat` as
its only argument and must run from `gpu_single_bsq/source`. For a uint16
`raw.hdr` it also reads `whiteReference.dat` and `darkReference.dat` there; for a
float32 one (data type 4, patch 0002) it reads `raw.dat` alone as calibrated
reflectance. SLIAFlow gives it `build/uc1/UC1/input/<cube>`. Besides `imageRGB.bmp` and the three
`output/rgb/*.txt` channel files it writes per-stage images into
`output/<case>/`:

| File | Writer (`BitmapWriter.cpp`) | Shown by SLIAFlow |
| --- | --- | --- |
| `pca.bmp` | `savePCAOutputAsBMP` -> `writeBMP` | yes |
| `svm.bmp` | `writeKNNBMP` | yes |
| `knn.bmp` | `writeKNNBMP` | yes |
| `kmeans.bmp` | `writeKmeansBMP` | yes |
| `imageRGB.bmp` | `writeMatrixRGB` -> `writeBMP` | yes |
| `CalibratedImage_BIP.bmp` | `saveBIPtoBMP` | no: rows are written without padding |

All five shown images are 24-bit bottom-up BMPs of `samples x lines` with rows
padded to four bytes. Their `bfSize` header field is `54 + 3 * w * h`, which
leaves out the padding, so it is wrong whenever the width is not a multiple of
four; SLIAFlow checks the actual file length instead.

Measured on 2026-09-17 on `004-02` (345 x 389), run from a terminal: exit 0,
2.40 s wall, `Time simulation ---> 719.150 ms`, K-means 18 iterations. The five
shown files were 403,058 bytes (`54 + 389 * (3 * 345 + 1)`, `bfSize` 402,669);
`CalibratedImage_BIP.bmp` was 402,669 bytes, one byte per row short. The same
case run from Slicer through SLIAFlow's `QProcess` took 2.05 s.

## The standalone runner, before SLIA-028

**Historical.** `SLIA-028` removed the Python UC1 runner, `python -m stratum_sim
uc1-real` and `uc1_client.py`, so the commands in this section no longer work.
SLIAFlow runs `stratum.opt.intermediate.exe` itself when Capture is pressed (see
`uc1_demo_runbook.md`), and `SLIAFlowUc1Run.py` restates the checks listed under
*What the runner guaranteed*. The section is kept as the record of what the
runner did and what was measured with it.

The runner was a `Classifier` implementation. It uses `dataset.folder` and never
loads a calibrated cube: the binary opens `raw.dat`, `whiteReference.dat`,
`darkReference.dat` and `raw.hdr` itself and calibrates on the GPU.

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"

# Run the pipeline and report the recovered map, without opening a server.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02 --classify-only

# Run once, then serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02
```

The pipeline runs once, before the server opens. A GPU run per cycle would turn
a display refresh into a second of compute, and the case does not change
between cycles.

Inspect the session from a second shell:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 6
```

That mode records everything that arrives and names every distinct device, which
is the check that matters here: this producer sends one map, so the question is
not whether five arrived but whether anything other than `UC1_MV_CLASS` did.

### What the runner guaranteed

- **Recorded cases only.** A folder whose `gtMap.hdr` does not carry the
  `HSI Human Brain Database` marker is refused before the GPU runs and before
  anything describes it, and there is no switch to override that. It is what
  keeps the pipeline pointed at approved public data in this prototype.
- **An exclusive lock.** `output/rgb/*.txt` are three fixed names shared by every
  dataset, so two runners in one staged build would interleave writes into the
  same three files and each would read the other's output. The lock file
  (`build/uc1/UC1/.uc1-runner.lock`) is removed on exit; delete it by hand if a
  runner was killed.
- **Freshness, not existence.** The outputs are deleted before the run, and each
  one is then checked against a timestamp taken immediately before the process
  starts. A file that predates the run is a failure, never a result. An
  existence check could not tell this run's output from last week's.
- **Loud failure.** A non-zero exit code, a missing output, a stale output, or
  `Path too long` on stderr each stop the run. There is no fallback on any
  path: an operator who believed the real pipeline ran when it did not would be
  the worst outcome this runner could have.
- **A model the dataset actually fits.** The staged `svm_model/` is sized for 93
  bands, and `main.cu` reads the header's band count out of `w_vector.bin`
  without checking how much it read - so a 40-band dataset would classify
  against a truncated model, and a 120-band one against uninitialised memory,
  both exiting 0 with a map that looks like a result. The runner checks the
  header's band count and all five model file sizes before starting the
  process. An `svm_model/` inside a dataset folder is not a substitute: UC1
  resolves `../../svm_model/*.bin` against its working directory, never against
  the dataset.
- **A strict palette inverse.** The RGB triples are mapped back to classes
  through the shared table in `bmp.py` read backwards. A triple that is not in the
  table is reported with its count and first coordinates, never resolved to the
  nearest known colour.

### The case is named on the wire

`SLIAFlow.SimulationDetail` reads
`real UC1 pipeline, recorded HSI case <case> (simulated acquisition)`. The runner
takes the case name from the folder rather than from a flag, so the detail cannot
disagree with the data that was actually read.

### One map, not five

The binary computes `tmdMap`, `majorityVotingProbabilityMap`, `svmProbability`
and `knnProbability` on the device and then discards them; the write that would
have surfaced them is inside a comment block at `main.cu` lines 164-174. So a
real-UC1 session populates `majorityVotingMap` and leaves the other four
absent. They are never substituted with zeros.

## Measured behaviour

Measured on the toolchain above, `nvidia-smi` sampled throughout each run
against a 1190 MiB idle desktop baseline on the 8151 MiB card, at two cube sizes
under `SLIA-013`:

| Cube | Peak VRAM | Over baseline |
| --- | --- | --- |
| 160 x 120 x 93 | 1325 MiB | about 140 MiB |
| 640 x 480 x 93 | 1973 MiB | about 790 MiB |

The memory figures are set by the cube size. Scaled linearly, the largest
recorded case, 752 x 721, needs about 3.5 GiB, which fits on this card with less
headroom than the demonstration case; that run is deferred until the pipeline is
complete.

On recorded case `004-02`, 345 x 389 x 93, the pipeline reported
`Time simulation ---> 564.417 ms` in the 2026-09-16 session and `379.774 ms` in
a later run the same day, with K-means converging in 18 iterations against the
20-iteration cap in `parameters.txt`. Time moves with the K-means iteration
count, so it varies by case as well as by size.

Re-running on the same case is not byte-identical: the two `004-02` runs above
recovered class counts `{1: 55948, 2: 7954, 3: 31589, 4: 38714}` and
`{1: 55938, 2: 7954, 3: 31584, 4: 38729}`, and the reported K-means error
differs in the sixth decimal place. Both are ordinary floating-point
non-determinism in the GPU K-means reduction, which moves a borderline pixel
between clusters; majority voting then hands it the other cluster's class.

Treat this as bounded drift rather than as a defect to chase. SLIA-013 asks for
at most 0.1% of pixels to change between runs on one dataset, every changed
pixel on a class boundary; byte-identical output is not a requirement, because
making the K-means reduction bit-stable would mean editing vendored UC1 source. A
run that moved pixels away from class boundaries, or moved appreciably more of
them, would be a real regression.

On the reference case `020-01` the unpatched build moved more than that: up to
0.32 % of `kmeans.bmp` and 0.19 % of `imageRGB.bmp` pixels between two runs, while
`pca.bmp`, `svm.bmp` and `knn.bmp` stayed byte-identical over seven runs
(`SLIA-033`). `check-uc1.py` therefore compares those three byte for byte and
bounds the K-means outputs at 1 % ([`uc1_changes.md`](uc1_changes.md)).

## A map that shows nothing

UC1 min-max normalizes each pixel across its bands before the SVM
(`normalizeImgKernel_optimized`), so only spectral *shape* reaches the
classifier, never magnitude, and `w_vector.bin` is a linear model trained on
real in-vivo brain reflectance. An input whose spectra have no shape the model
was trained on comes back as a single class.

The classifier itself is never tuned, under any option. Changing
`parameters.txt`, the SVM model, or vendored source to make a case produce a
different map would make every future result meaningless. The patches of
`SLIA-033` are not that: they refuse a wrong band count, read a cube IUMA has
already calibrated, and stop the PCA dividing by zero on identical bands; the
reference case's classification is unchanged by them. The retired runner
reported a uniform map loudly - `uniformClassWarning` on stderr - so an input the
model did not recognise said so.
