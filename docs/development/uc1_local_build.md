# Building and running the genuine UC1 pipeline locally

This describes how the vendored UC1 CUDA pipeline is compiled and run on this
machine, and what was actually measured when it was. Nothing in
`workspace/components/` is modified: the sources are staged, built and executed
somewhere else, and every build re-proves that property by hash.

The pipeline runs on recorded cases of the public, anonymized HSI Human Brain
Database. Calibration, PCA, SVM, KNN, K-means and majority voting are the
vendored code doing real work on the local GPU. The acquisition event is
simulated, so a result is marked `simulated` on the wire, and nothing it produces
is a clinical result.

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

The script captures the toolchain, stages the sources, pre-creates the output
directories, builds, checks the expected warnings, and asserts the staged tree
still hashes identically to `workspace/components/`.

### Staging layout

The layout is load-bearing, not tidiness. `main.cu` opens the SVM model as the
literal relative path `../../svm_model/*.bin`, resolved against the working
directory, so the model must sit exactly two levels above the source directory.

```text
build/uc1/UC1/
  svm_model/                  copied verbatim, 5 .bin files
  gpu_single_bsq/source/      copied verbatim, 37 files including parameters.txt
    output/rgb/               pre-created; the binary will not create it
    output/<dataset>/         pre-created per run; likewise
    stratum.opt.exe
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

Two warnings appear on every build of this source. They are not silenced, and
the vendored source is not edited to remove them. Their **absence** is the
surprise, and the build script reports it as one.

| Warning | Where |
| --- | --- |
| `#550-D` | `functions_cuda.cu` line 63, `num_th_last_block` set but never used |
| `C4068` | `matrixlib.cpp` lines 205, 221, 293, unknown pragma `unroll` |

`vcvars64.bat` also prints `'vswhere.exe' is not recognized` on this machine.
That comes from inside the vcvars batch file, is unrelated to the compilation,
and is harmless; the toolset is still configured and the build succeeds.

### The hash assertion

After every build, each staged file is compared by SHA-256 against its
`workspace/components/` original, in both directions: a changed or missing file
fails, and so does a staged file with no original that is not a known build
product. That last check is what would catch an edit made by addition.

Reference values from the proven build:

| File | SHA-256 |
| --- | --- |
| `gpu_single_bsq/source/main.cu` | `63D0E9EE5E77B06876DFA7D76965B1F67719D841D7A4012742F85E2540C788C0` |

Modifying vendored UC1 source is out of scope for this project. If a build ever
requires a source edit, that is a roadmap-boundary decision for the project
owner, not a silent fix.

## Running

The runner is a `Classifier` implementation. It uses `dataset.folder` and never
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

### What the runner guarantees

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

## A map that shows nothing

UC1 min-max normalizes each pixel across its bands before the SVM
(`normalizeImgKernel_optimized`), so only spectral *shape* reaches the
classifier, never magnitude, and `w_vector.bin` is a linear model trained on
real in-vivo brain reflectance. An input whose spectra have no shape the model
was trained on comes back as a single class.

The classifier itself is never tuned, under any option. Changing
`parameters.txt`, the SVM model, or vendored source to make a case produce a
different map would make every future result meaningless. The runner reports a
uniform map loudly - `uniformClassWarning` on stderr - so an input the model
does not recognise says so.
