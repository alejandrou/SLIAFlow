# Changes to UC1

This is the record of every change SLIAFlow makes to the vendored UC1 pipeline,
and of the one mapping that feeds it IUMA's LCTF cube. `ADR-0004` decision 3
allows UC1 to be changed only this way: each change is a versioned patch in
`scripts/development/uc1-patches/`, applied at staging, and written down here
with what it does, why, the command that was run and what came out. The SVM
model is never retrained or edited.

Results on the LCTF cube are behavioural, not validated (`ADR-0004` decision 5).
The model was trained on another camera's spectral response, so an output on
`002-04` shows that the pipeline runs and what it produces. It says nothing
about accuracy.

## How the patches are applied

`scripts/development/build-uc1.ps1`:

1. copies the vendored `gpu_single_bsq/source` and `svm_model` from
   `workspace/components/` into `build/uc1/UC1/`;
2. applies every `*.patch` in `scripts/development/uc1-patches/` to the staged
   source, in name order, with `git apply`, which refuses a hunk whose context
   does not match. A patch that does not apply, or that `git apply` reports as
   skipped, stops the build with the patch's name;
3. builds both binaries;
4. rebuilds a reference tree (`build/uc1/expected/`) from a fresh copy of the
   vendored source plus the same patches, and asserts that the staged tree
   equals it file by file, SHA-256, with no extra file.

The vendored copy is never written to. The patches are LF files and the
`.gitattributes` beside them keeps them LF, because the UC1 sources are LF and
`core.autocrlf` is on in this repository.

```powershell
.\scripts\development\build-uc1.ps1 -Clean
.\.venv\Scripts\python.exe scripts\development\check-uc1.py
```

`check-uc1.py` is the check that the patches leave the reference behaviour
alone and that each patch does what this document says. It is run after every
change to a patch. It runs six checks, in about 5 s:

| Check | Patch | Oracle |
| --- | --- | --- |
| Reference case `020-01`, uint16 | all | the unpatched build's hashes and saved run (next section) |
| 109-band header | 0001 | refused, `Band guard:`, no output folder |
| Float32 `020-01` | 0002 | `CalibratedImage_BIP.bmp` byte-identical to a prediction made from the cube; `pca`, `svm`, `knn` within 0.1 % of the uint16 run; `pca.bmp` against NumPy's principal component |
| Equal bands | 0003 | `pca.bmp` within one grey level of NumPy's principal component |
| Float32 cube one value short | 0002 | refused, no output folder |
| No `../../svm_model` | 0001 | refused, `Band guard: ... cannot be opened` |

Each patch section below says what its checks showed, including against a
build without that patch.

## The reference case, before any patch

UC1's model is known to behave as its authors intended only on the HSI Human
Brain Database it was trained on. The reference case `020-01`
(`input/reference_hsi_brain_db/020-01`, 330 x 378 x 93, uint16 with references)
is the check that the patches did not change that behaviour.

The unpatched build (vendored UC1 as delivered, built by `build-uc1.ps1` with
the toolchain in `uc1_local_build.md`) was run on `020-01` seven times on
2026-09-24, each run about 0.4 to 0.6 s inside UC1.

| Output | SHA-256, unpatched | Seven runs |
| --- | --- | --- |
| `pca.bmp` | `ee01256ba51b589f51d6a3a8d726685c04f08f25ccbb3bda857187809632e58c` | identical |
| `svm.bmp` | `5f9548afcf87908115cdff408e263a30a24f4423340b99655d2f46c276f62a0f` | identical |
| `knn.bmp` | `5aea0081152655c4ec4151abe59b97f3231818a2e351663a43178b2614a67910` | identical |
| `CalibratedImage_BIP.bmp` | `810909a985f7bc0424e46fc8c225f7e797840c91b2d42812b5e74a7daedb2b89` | identical |
| `kmeans.bmp` | different every run | up to 0.32 % of pixels differ between two runs |
| `imageRGB.bmp` | different every run | up to 0.19 % of pixels differ between two runs |

UC1's K-means, and the majority vote that uses it, is not deterministic on this
GPU: every run found all 24 clusters and 4 classes, with a few border pixels
assigned differently. This is the delivered behaviour, not something a patch
introduced; making it deterministic is out of scope. So the reference check is:

- the four deterministic images byte-identical to the hashes above;
- `kmeans.bmp` and `imageRGB.bmp` differing from a saved unpatched run
  (`build/uc1/reference-unpatched/`, gitignored) in at most 1 % of pixels.

The vendored `main.cu` SHA-256 is
`63D0E9EE5E77B06876DFA7D76965B1F67719D841D7A4012742F85E2540C788C0`;
`build-uc1.ps1` prints it on every build.

## The band mapping

`ADR-0004` decision 4. The staged model is sized for 93 bands at 440-900 nm in
5 nm steps; IUMA's calibrated LCTF cube has 109 bands at 460-1000 nm in 5 nm
steps. The mapping runs in exactly one place,
`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py`, and is described
only here.

| Model bands | Wavelengths | Fed from |
| --- | --- | --- |
| 1-4 | 440, 445, 450, 455 nm | the 460 nm band (LCTF band 1), repeated |
| 5-93 | 460-900 nm | LCTF bands 1-89, one to one, same wavelength |
| - | 905-1000 nm | LCTF bands 90-109, dropped |

A cube whose wavelengths are not exactly that LCTF grid (109 bands, within
0.01 nm) is refused before UC1 starts, with the reason on the panel. Values are
copied as stored: no resampling, smoothing or rescaling.

At every Capture SLIAFlow writes the mapped cube, 93 bands of float32 in band
sequential order, as `raw.dat` with a `raw.hdr` declaring ENVI data type 4, into
`build/uc1/UC1/input/<cube>/`, and gives UC1 that folder. This is also how UC1
finds `LCTF_Calibrated_Cube_Single` without anything being written into
`input/`. On `002-04` the file is 433,900,800 bytes and takes 0.4 to 0.7 s to
write. An independent NumPy mapping written at specification produced a
byte-identical `raw.dat` (SHA-256 `aaf30f8e...910003e`).

Copying the 460 nm band into four more model bands makes five identical bands.
That is what patch 0003 is for.

## Patch 0001 - band guard

`0001-band-guard.patch`, `main.cu`.

**What.** Before any image is read, UC1 compares the header's band count with
the size of `../../svm_model/w_vector.bin` (one float per band and binary
classifier). If they disagree, or the file cannot be opened, it prints a line
starting `Band guard:` and exits with code 1.

**Why.** `main.cu` reads the weights with the header's band count and never
checks how much it read, so a 109-band cube would be classified against
garbage weights without any error. This closes that for any input.

**Command and result.** `check-uc1.py` starts UC1 on a header declaring 109
bands:

```text
Band guard, 109-band header: exit 1, 0.12 s
  Band guard: the cube has 109 bands, but ../../svm_model/w_vector.bin holds 2232 bytes, the weights of 93 bands for 6 binary classifiers. UC1 does not classify this cube.
```

No output folder was created. Against the unpatched build the same check
failed: UC1 went on to read a `raw.dat` that was not there and was still
running when it was killed after 20 s (and after 120 s on the first try).

The other branch, weights that cannot be opened, is checked by running UC1 from
a scratch folder (`build/uc1/UC1/no-model-check/run/source`, with a copy of
`parameters.txt`) whose `../../svm_model` does not exist. The staged model is
never moved:

```text
Missing weights: exit 1, 0.09 s
  Band guard: ../../svm_model/w_vector.bin cannot be opened.
```

## Patch 0002 - calibrated float32 input

`0002-calibrated-float32-input.patch`: `data_loader.hpp`, `data_loader.cpp`,
`functions.h`, `functions.cu`, `functions_cuda.cuh`, `functions_cuda.cu`,
`main.cu`.

**What.**

- `raw.hdr` is read to the end and its `data type` is kept. A header without
  one is read as uint16, as before. Any type other than 12 (uint16) or 4
  (float32) is refused.
- With data type 4, `raw.dat` is read as float32 band sequential reflectance.
  The white and dark references are never opened. A short read or a failed
  allocation exits with code 1 instead of classifying an empty buffer.
- UC1's calibration kernel is replaced, for that input only, by
  `scaleCalibratedAndConvertToBIP_Tiled`: the same tiled transpose to BIP,
  multiplying by 100. UC1's own calibration writes
  `100 * (raw - dark) / (white - dark)`, so every later stage sees values in
  the units it sees on a uint16 cube.
- The uint16 path is the same code as before, now inside an `else`.

**Why.** IUMA calibrates the cube itself and sends float32 reflectance
(`ADR-0004` context), with no full-size references. Converting it back to
uint16 with made-up references was rejected in `ADR-0004`.

**Command and result.** At specification, patches 0001 and 0002 were applied
to a scratch copy of the vendored source and built with the `build-uc1.ps1`
intermediate command line, with only the expected warnings (`#550-D` at
`functions_cuda.cu` line 63, `C4068` in `matrixlib.cpp`). Three runs on the
reference case gave the four deterministic images byte-identical to the
unpatched hashes; `kmeans.bmp` and `imageRGB.bmp` differed from the five saved
unpatched runs in at most 0.46 % and 0.28 % of pixels, the same K-means
variation as between unpatched runs.

On `002-04` with patches 0001 and 0002 only, the run finished (exit 0, 3.2 s
wall, 2.1 s inside UC1) but `pca.bmp` was black and `knn.bmp` and
`imageRGB.bmp` were a single class. `svm.bmp` and `kmeans.bmp` had structure.
The cube has no NaN or infinity in 460-900 nm. The cause is in patch 0003.

**How the float32 path is checked.** `002-04` has nothing to compare UC1's
output with, so `check-uc1.py` makes a float32 cube whose answer is known.
`020-01` is calibrated in NumPy exactly as UC1's uint16 kernel does it
(`100 * (raw - dark) / (white - dark)` in float32, which the GPU rounds the same
way: the build does not use fast math), divided by 100 into reflectance, and
written as `raw.dat` with data type 4 into `build/uc1/UC1/input/float32-check`.

- `CalibratedImage_BIP.bmp` shows three bands (indices 54, 20 and 8) of what the
  new kernel produced: the cube multiplied by 100 and transposed to band
  interleaved. The check predicts that image from the cube, with the scaling of
  UC1's `saveBIPtoBMP`, and requires it byte for byte.
- It cannot require byte-identity with the uint16 run: for 1,571,543 of the
  11,600,820 calibrated values (13.5 %) no float32 `x` gives `100 * x` equal to
  the value, so dividing by 100 and multiplying again moves those values by one
  unit in the last place. `pca.bmp`, `svm.bmp` and `knn.bmp` are therefore held
  to the uint16 run within 0.1 % of pixels. They came out 0.0064 %, 0 and 0.
- A copy of the cube one value short is refused.

```text
float32-check: exit 0, 0.56 s
  CalibratedImage_BIP.bmp  identical to the prediction
  pca.bmp                  0.0064% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  svm.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  knn.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  pca.bmp                  99.9960% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
short-read-check: exit 1, 0.21 s
  Error: C:\stratum\build\uc1\UC1\input\short-read-check/raw.dat holds 46403276 bytes, the header describes 46403280
```

Against a build with patch 0001 only (`build-uc1.ps1 -Clean -PatchDirectory`
with a copy of that patch alone), UC1 crashed with `0xC0000005` on each float32
cube, and the float32, equal-bands and short-cube checks failed.

## Patch 0003 - equal diagonal in the PCA's Jacobi step

`0003-jacobi-equal-diagonal.patch`, `functions_cuda.cu`. Added with the project
owner's approval on 2026-09-25.

**What.** UC1's PCA finds eigenvectors with its own Jacobi rotations. For each
off-diagonal entry it computes `pca_alpha = a_ij / (a_jj - a_ii)`. When the two
diagonal entries are exactly equal, the patch uses the 45 degree rotation
(`cos = sin = sqrt(0.5)`), which zeroes `a_ij` exactly in that case, instead of
dividing by zero. Every other rotation is unchanged.

**Why.** The band mapping makes model bands 1-5 five copies of the 460 nm band,
so their covariance entries are equal. The division gave infinity, the rotation
became NaN, and the NaN spread through the whole covariance matrix: the PCA
image was black and the KNN filter, which uses it, and the majority vote
collapsed to one class.

**Command and result.** The three patches, built by
`build-uc1.ps1 -Clean` (exit 0, only the expected warnings; release binary
951,808 to 961,024 bytes, intermediate 1,406,464 to 1,426,432 bytes), then
`check-uc1.py`:

```text
Reference case 020-01: exit 0, 1.98 s
  pca.bmp                  identical  ee01256b...
  svm.bmp                  identical  5f9548af...
  knn.bmp                  identical  5aea0081...
  CalibratedImage_BIP.bmp  identical  810909a9...
  kmeans.bmp               0.0585% of pixels differ from the unpatched run (within 1%)
  imageRGB.bmp             0.0345% of pixels differ from the unpatched run (within 1%)
Band guard, 109-band header: exit 1, 0.12 s
PASS
```

Equal diagonal entries do not occur on the reference case, so its PCA is
unchanged. The 1.98 s is the whole process, including CUDA start-up.

**How the equal-diagonal branch is checked.** `check-uc1.py` sets bands 1-4 of
the float32 cube above to band 5, as the band mapping does for an LCTF cube, so
UC1's Jacobi step meets equal diagonal entries. Changing four bands changes
every pixel's min-max normalisation, so the outputs cannot be compared with the
float32 run. What can be compared is the PCA itself: `pca.bmp` shows 255 times
the first principal component of the normalised, band-centred cube, truncated
and clipped to 0-255. NumPy computes that component in double precision with
`eigh`, independently of UC1's Jacobi rotations, and every pixel must be within
one grey level, taking whichever sign of the eigenvector fits (its sign is
arbitrary). The same comparison is made on the float32 run.

```text
equal-bands-check: exit 0, 0.55 s
  pca.bmp                  99.9864% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
```

Against a build with patches 0001 and 0002 only, on 2026-09-25, this was the
one check that failed:

```text
equal-bands-check: exit 0, 0.53 s
  pca.bmp                  77.1878% of pixels equal to NumPy's first component, at most 255 grey level(s) off (OVER 1)
FAIL: pca.bmp of equal-bands-check is up to 255 grey levels from NumPy's first principal component, over 1
```

The 77 % are the pixels NumPy's component also clips to black.

## check-uc1.py on the three patches

`build-uc1.ps1 -Clean` (exit 0), then `check-uc1.py` (exit 0), 2026-09-25:

```text
Reference case 020-01: exit 0, 0.98 s
  pca.bmp                  identical  ee01256b...
  svm.bmp                  identical  5f9548af...
  knn.bmp                  identical  5aea0081...
  CalibratedImage_BIP.bmp  identical  810909a9...
  kmeans.bmp               0.2413% of pixels differ from the unpatched run (within 1%)
  imageRGB.bmp             0.1475% of pixels differ from the unpatched run (within 1%)
Band guard, 109-band header: exit 1, 0.10 s
float32-check: exit 0, 0.56 s
  CalibratedImage_BIP.bmp  identical to the prediction
  pca.bmp                  0.0064% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  svm.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  knn.bmp                  0.0000% of pixels differ from the uint16 run on 020-01 (within 0.1%)
  pca.bmp                  99.9960% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
equal-bands-check: exit 0, 0.55 s
  pca.bmp                  99.9864% of pixels equal to NumPy's first component, at most 1 grey level(s) off (within 1)
short-read-check: exit 1, 0.21 s
Missing weights: exit 1, 0.09 s
PASS
```

(Messages trimmed; the full output is in the task card.) What none of this
checks: that UC1's classes are right on an LCTF cube. That needs a labelled
LCTF cube, which does not exist yet.

## UC1 on 002-04, with the three patches

Run through SLIAFlow's own logic inside Slicer (the Capture path, without the
window) on 2026-09-25:

| Step | Time |
| --- | --- |
| Checks, lock and writing the mapped cube | 0.49 s |
| UC1 process, start to exit | 4.1 s |
| UC1's own `Time simulation` | 2.0 s |
| Capture to five validated outputs | 4.6 s |

All five outputs are 1080 x 1080. `pca.bmp` has 256 grey levels, `kmeans.bmp`
24 clusters, and:

| Output | Background | Tumour | Normal | Hypervascularized |
| --- | --- | --- | --- | --- |
| `svm.bmp` | 62.1 % | 35.4 % | 2.1 % | 0.4 % |
| `knn.bmp` | 63.8 % | 35.5 % | 0.7 % | 0.1 % |
| `imageRGB.bmp` | 64.1 % | 35.9 % | - | - |

Most of the tissue in view is classed as tumour. That is a finding about a
model trained on another camera meeting the LCTF cube, recorded as such and not
tuned away here (`SLIA-034` owns parameters and speed). `002-04` has no ground
truth, so nothing here can say which pixels are right.
