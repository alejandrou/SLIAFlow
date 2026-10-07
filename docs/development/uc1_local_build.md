# Building and running the genuine UC1 pipeline locally

This describes how the vendored UC1 CUDA pipeline is compiled and run on this
machine, and what was actually measured when it was. Nothing in
`workspace/components/` is modified: the sources are staged, patched, built and
executed somewhere else, and every build re-proves by hash that the staged tree
is the vendored one plus the versioned patches and nothing else.

Since `SLIA-033` the pipeline runs on IUMA's calibrated LCTF cube `002-04`, mapped
onto the model's 93 bands. The patches, the band mapping and what each produced
are recorded in [`uc1_changes.md`](uc1_changes.md).
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
patches. Then check the result against the run recorded on `002-04` and each
patch's own check ([`uc1_changes.md`](uc1_changes.md)):

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
  baseline-002-04/            a saved run on 002-04, for check-uc1.py
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

### Measurement variants

`SLIA-034` builds UC1 with other preprocessor definitions to measure what they
change, without touching the product build:

```powershell
.\scripts\development\build-uc1.ps1 -Clean -Variant kmeans-shared -Defines "-DOPTIMIZE_KMEANS=1 -DPCA_PD=1 -DKMEANS_SHARED"
.\scripts\development\build-uc1.ps1 -Clean -Variant release -Release
```

A variant is staged, patched and hash-checked like the product, in
`build/uc1/variants/<name>/` with its own reference tree, and only one binary is
built there: the intermediate one, or the release one with `-Release`, under
the product's file name. `-Defines` replaces `-DOPTIMIZE_KMEANS=1 -DPCA_PD=1`.
The variant's compiler warnings are printed but not held to the product's
list, because other definitions compile other code. `build/uc1/UC1/` is never
touched, and SLIAFlow never runs a variant; `scripts/development/measure-uc1.py`
does (`docs/development/uc1_performance.md`).

`KMEANS_SHARED` is tested with `#ifdef`: `-DKMEANS_SHARED=0` switches it on too.

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

On `002-04` (1080 x 1080), run from a terminal on 2026-10-07: exit 0, 2.0 to
2.3 s. 1080 is a multiple of four, so all six files are 3,499,254 bytes
(`54 + 1080 * 3 * 1080`) and the padding does not show. On a 345-pixel-wide case
of the HSI Human Brain Database, on 2026-09-17, the five shown files were
403,058 bytes (`54 + 389 * (3 * 345 + 1)`, `bfSize` 402,669) and
`CalibratedImage_BIP.bmp` 402,669 bytes, one byte per row short.

## Measured behaviour

Measured on the toolchain above, `nvidia-smi` sampled throughout each run
against a 1190 MiB idle desktop baseline on the 8151 MiB card, at two cube sizes
under `SLIA-013`:

| Cube | Peak VRAM | Over baseline |
| --- | --- | --- |
| 160 x 120 x 93 | 1325 MiB | about 140 MiB |
| 640 x 480 x 93 | 1973 MiB | about 790 MiB |

The memory figures are set by the cube size. `SLIA-034` measured speed, memory
and the largest cube this laptop takes on `002-04`:
[`uc1_performance.md`](uc1_performance.md).

Re-running on the same cube is not byte-identical for `kmeans.bmp` and
`imageRGB.bmp`. That is ordinary floating-point non-determinism in the GPU
K-means reduction, which moves a borderline pixel between clusters; majority
voting then hands it the other cluster's class. On `002-04`, five runs on
2026-10-07 differed pairwise in at most 0.0068 % of `kmeans.bmp` and 0.0015 % of
`imageRGB.bmp` pixels, while `pca.bmp`, `svm.bmp`, `knn.bmp` and
`CalibratedImage_BIP.bmp` stayed byte-identical. `check-uc1.py` therefore
compares those four byte for byte and bounds the K-means outputs at 0.02 %
([`uc1_changes.md`](uc1_changes.md)).

Treat this as bounded drift rather than as a defect to chase: making the
K-means reduction bit-stable would mean editing vendored UC1 source. A run that
moved appreciably more pixels would be a real regression.

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
already calibrated, and stop the PCA dividing by zero on identical bands. They
left the reference case's classification unchanged when it was last checked,
on 2026-10-07. The retired runner
reported a uniform map loudly - `uniformClassWarning` on stderr - so an input the
model did not recognise said so.
