# Building and running the genuine UC1 pipeline locally

This describes how the vendored UC1 CUDA pipeline is compiled and run on this
machine, and what was actually measured when it was. Nothing in
`workspace/components/` is modified: the sources are staged, built and executed
somewhere else, and every build re-proves that property by hash.

The scene the pipeline runs on is synthetic. The pipeline is not. Calibration,
PCA, SVM, KNN, K-means and majority voting are the vendored code doing real work
on the local GPU, so a result is a genuine algorithm output over an invented
input, and it is marked `simulated` on the wire for exactly that reason.

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

The runner is a `Classifier` implementation like the arithmetic stand-in, so it
plugs into the same seam. It uses `dataset.folder` and never loads a calibrated
cube: the binary opens `raw.dat`, `whiteReference.dat`, `darkReference.dat` and
`raw.hdr` itself and calibrates on the GPU.

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"

# Run the pipeline and report the recovered map, without opening a server.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real `
    workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS --classify-only

# Run once, then serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real `
    workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS
```

The pipeline runs once, before the server opens. A GPU run per cycle would turn
a display refresh into a second of compute, and the dataset does not change
between cycles.

Inspect the session from a second shell:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 6
```

That mode records everything that arrives and names every distinct device, which
is the check that matters here: this producer sends one map, so the question is
not whether five arrived but whether anything other than `UC1_MV_CLASS` did.

### What the runner guarantees

- **The marker interlock.** A dataset whose `raw.hdr` lacks
  `STRATUM SIMULATED CUBE` is refused, and `--force-unmarked` is the only
  escape. This is the same interlock SLIA-012 uses and it is not optional: it is
  what physically prevents the pipeline from being pointed at a patient cube in
  this prototype.
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
  `Path too long` on stderr each stop the run. There is no fallback to the
  arithmetic stand-in on any path: an operator who believed the real pipeline
  ran when it did not would be the worst outcome this runner could have.
- **A model the dataset actually fits.** The staged `svm_model/` is sized for 93
  bands, and `main.cu` reads the header's band count out of `w_vector.bin`
  without checking how much it read - so a 40-band dataset would classify
  against a truncated model, and a 120-band one against uninitialised memory,
  both exiting 0 with a map that looks like a result. The runner checks the
  header's band count and all five model file sizes before starting the
  process. The `svm_model/` inside a dataset folder is not a substitute: UC1
  resolves `../../svm_model/*.bin` against its working directory, never against
  the dataset.
- **A strict palette inverse.** The RGB triples are mapped back to classes
  through SLIA-012's shared table read backwards. A triple that is not in the
  table is reported with its count and first coordinates, never resolved to the
  nearest known colour.

### The scene is named on the wire

`SLIAFlow.SimulationDetail` reads `real UC1 pipeline, synthetic tissue phantom`
for a phantom dataset and `real UC1 pipeline, synthetic input` for anything
else. The runner decides by looking for the phantom record in the dataset
folder rather than by taking a flag, so the detail cannot disagree with the data
that was actually read.

### One map, not five

The binary computes `tmdMap`, `majorityVotingProbabilityMap`, `svmProbability`
and `knnProbability` on the device and then discards them; the write that would
have surfaced them is inside a comment block at `main.cu` lines 164-174. So a
real-UC1 session populates `majorityVotingMap` and leaves the other four
absent. They are never substituted with zeros, and the real runner and the
arithmetic stand-in are never run in the same session - five maps from two
different boxes would imply UC1 produced all five.

## Measured behaviour

Measured on the toolchain above, `nvidia-smi` sampled throughout each run
against a 1190 MiB idle desktop baseline on the 8151 MiB card.

| Preset | Cube | Scene | UC1 internal time | Peak VRAM | Over baseline |
| --- | --- | --- | --- | --- | --- |
| `demo` | 160 x 120 x 93 | channel | 262.7 ms | 1325 MiB | 135 MiB |
| `full` | 640 x 480 x 93 | channel | 622.3 ms | 1973 MiB | 783 MiB |
| `demo` | 160 x 120 x 93 | phantom | 299.3 ms | 1325 MiB | 143 MiB |
| `full` | 640 x 480 x 93 | phantom | 446.8 ms | 1973 MiB | 791 MiB |

The 8 GB card is nowhere near the limit at `full`, and the scene does not move
the memory figures: they are set by the cube size. It does move the time,
because it moves the K-means iteration count. On the channel scene K-means took
11 iterations at `demo` and hit the 20-iteration cap from `parameters.txt` at
`full` with an error of 0.001554 against a 1e-3 threshold, so that `full` result
is the capped iterate rather than a converged one. On the phantom it converges
in 3 iterations at `demo` and 2 at `full`, well inside the cap - the phantom's
regions are spectrally further apart than the channel scene's texture.

Re-running on the same dataset is not byte-identical on a varied map: six
consecutive `demo` runs on one phantom dataset changed 6 pixels of 19200
(0.036 %), all of them on a class boundary. The reported K-means error varies in
the sixth decimal place between runs. Both are ordinary floating-point
non-determinism in the GPU K-means reduction, which moves a borderline pixel
between clusters; majority voting then hands it the other cluster's class.

The byte-identical result recorded earlier was measured on a uniformly
single-class map, which is byte-identical far more easily than a varied one, so
it was never evidence of determinism.

Treat this as bounded drift rather than as a defect to chase. SLIA-013 asks for
at most 0.1% of pixels to change between runs on one dataset, every changed
pixel on a class boundary, which is what the measurement shows; byte-identical
output is not a requirement, because making the K-means reduction bit-stable
would mean editing vendored UC1 source. A run that moved pixels away from class
boundaries, or moved appreciably more of them, would be a real regression.

## What the scene has to look like

**A scene whose spectra are mixtures of camera colour curves is resolved to
class 4, background, in every pixel.** That was measured on the channel-driven
scene at both presets, and it is why the acquisition stand-in's default scene
is now the tissue phantom.

The reason is in `normalizeImgKernel_optimized`: UC1 min-max normalizes each
pixel across its bands before the SVM, so only spectral *shape* reaches the
classifier, never magnitude - and `w_vector.bin` is a linear model trained on
real in-vivo brain reflectance. The channel scene was never spectrally
degenerate; its shape was simply nothing the model had been asked about.

The phantom builds that shape from haemoglobin absorption and a scattering
power law instead, and UC1 then produces a two-class, spatially coherent map.
**It is a plumbing demonstration and not a detector**: UC1 does not separate the
phantom's cortex from its tumour-like region, and at `demo` it calls the
vessels background. `docs/development/synthetic_tissue_phantom.md` records the
full comparison, the parameters, and what may and may not be claimed from it.

The classifier itself is never tuned, under any option. Changing
`parameters.txt`, the SVM model, or vendored source to make an invented scene
produce a colourful map would make every future result meaningless. The runner
still reports a uniform map loudly - `uniformClassWarning` on stderr - so a
scene that stops working says so.
