# UC1 speed and size limit on this laptop

How long UC1 takes on IUMA's calibrated cube `002-04`, from Capture to result,
where the time goes, what makes it faster, and how large a cube this laptop's
GPU can take (`SLIA-034`, measured on 2026-09-25). Nothing here has been
adopted: the product build and its `parameters.txt` are still the ones
`uc1_changes.md` describes. Which setting to adopt is the project owner's
decision (see [Recommendation](#recommendation)).

## In short

- **SLIAFlow's Capture work takes about 2.6 s** in Slicer on `002-04`
  (1080 x 1080, mapped to 93 bands), from the start of the run to the outputs
  loaded into Slicer. Of that, UC1 runs for 2.1 s and writing the mapped cube
  for UC1 takes 0.35 s. This is not the whole wait after pressing Capture:
  saving the camera snapshot and drawing the result in the window were not
  timed (see [Capture to result](#capture-to-result)).
- **Most of UC1's time goes to three steps:** K-means (0.62 s), reading the
  cube from disk (0.26 s) and PCA (0.27 s).
- **Two build flags make UC1 27 % faster** (2.0 s down to 1.5 s) and use
  418 MiB less GPU memory. The only output that changes is the PCA image, in
  0.02 % of its pixels, by one grey level. The tissue classes do not change.
- **Changing UC1's parameters** makes it at most 18 % faster (K-means stopped
  at 10 iterations). Five of the six parameter changes moved the final
  classification by 1 % to 21 % of pixels; the sixth, a smaller KNN window,
  changed 10 pixels and saved 27 ms. Not recommended.
- **The largest cube this laptop took is between 2300 x 2300 and 2430 x 2430
  pixels** (5.3 to 5.9 million pixels, 93 bands): 2300 ran and 2430 failed in
  each of four runs, with 2 to 8 GB of RAM free. The exact limit depends on
  what else uses the GPU and RAM. A full-frame LCTF cube, 4096 x 2160
  (8.8 million pixels), is far above it and does not fit. Above the limit
  **UC1 does not report a failure**: it exits normally and writes blank or
  single-colour images. Only a check of the output catches it.

## Capture to result

SLIAFlow's Capture work in Slicer, five captures after a warm-up
(`measure-capture.py`, 2026-09-25 10:43). The script makes the module's own
calls, in the order the Capture button makes them, but runs without the
window and without the camera. Three things the operator waits for are
therefore not in these figures:

- saving the LiveView snapshot as a PNG, before the run starts;
- putting the result in the Tumour Delineation view once it is loaded;
- Slicer drawing the views.

The table is the time from the start of the run to the outputs loaded into
Slicer, not a click-to-screen latency.

| Step | What happens | Median s (range) |
| --- | --- | --- |
| Check | the cube's header read and checked against the band mapping | 0.00 (0.00-0.00) |
| Prepare | lock taken, the mapped 93-band cube (434 MB) written for UC1 | 0.35 (0.28-0.44) |
| UC1 | the UC1 process, start to exit | 2.09 (2.02-2.25) |
| Validate | the five outputs checked | 0.03 (0.03-0.03) |
| Accept | the five outputs loaded into Slicer | 0.02 (0.01-0.02) |
| **Capture to result** (without snapshot and display) | all of the above | **2.57 (2.35-2.66)** |
| HS Cube, alongside | the cube read and shown in HS Cube while UC1 runs | 0.95 (0.93-1.00) |

Inside the UC1 process, UC1's own timer (`Time simulation`) was 1.68 s
(1.64-1.81). The other 0.4 s is CUDA starting before UC1's `main`, and UC1
writing `imageRGB.bmp` and three text files after its timer stops.

`SLIA-033` recorded one capture at 4.6 s. These five were taken with the GPU
and the disk cache warm; the first capture after a pause is slower (the
warm-up here took 2.80 s, and see [The machine](#the-machine)).

## Where UC1 spends its time

UC1 run on its own, on the same mapped cube (`baseline-repeat`, five runs after
a warm-up). UC1 prints these times itself; each is taken on the CPU when the
step returns, so a step that only starts GPU work shows little time and the
next step that waits for the GPU shows more.

| Step | Median ms (range) |
| --- | --- |
| Read the cube from disk (`Upload Images`) | 258 (253-263) |
| Allocate GPU memory (`cudaMalloc`) | 82 (76-84) |
| Pre-processing (scale and normalise) | 31 (28-32) |
| PCA | 271 (268-291) |
| SVM | 37 (35-42) |
| KNN filter | 59 (59-61) |
| K-means | 619 (605-625) |
| Majority vote | 11 (10-11) |
| Free GPU memory | 34 (33-46) |
| **UC1's timer (`Time simulation`)** | **1637 (1592-1691)** |
| **Whole process (wall)** | **1986 (1927-2083)** |

K-means stops at its limit of 20 iterations on every run, with an error of
0.00114, just over its 0.001 target. Given 40 iterations it stops by itself
after 22 or 23.

Memory: the GPU's used memory rose by 2641 MiB during a run; the UC1 process
peaked at 1105 MiB of RAM in use (3766 MiB committed).

## Trials

Each row changes one thing against the baseline, except the last, which
combines the two build flags. Times are medians of five runs after a warm-up,
with the range. "Outputs" says what changed against the baseline.

`kmeans` and `imageRGB` are never identical between two runs of the same
program: UC1's K-means puts a few border pixels in a different cluster each
time. The baseline's own run-to-run difference is 0.004-0.010 % of pixels in
`kmeans` and 0.0004-0.002 % in `imageRGB`. A trial within those figures has not
changed them.

| Trial | Change | Process s | UC1 timer ms | Changed step, ms | GPU MiB | Outputs |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline | none | 1.99 (1.93-2.08) | 1637 (1592-1691) | K-means 619, PCA 271 | 2641 | - |
| `kmeans-shared` | build flag `KMEANS_SHARED` | 1.76 (1.70-1.90) | 1414 (1384-1563) | K-means 399 | 2641 | unchanged (within run-to-run difference) |
| `pca-single` | build flag `PCA_PD=0` (PCA in single precision) | 1.68 (1.68-1.72) | 1373 (1357-1379) | PCA 55 | 2223 | `pca` differs in 0.024 % of pixels, by 1 grey level; `svm`, `knn` identical; the rest unchanged |
| `kmeans-aos` | build flag `OPTIMIZE_KMEANS=0` (the delivered baseline K-means) | 2.03 (2.02-2.10) | 1712 (1704-1722) | K-means 723 | 2641 | `kmeans` 0.011-0.021 %, `imageRGB` 0.003-0.005 %: slightly over run-to-run |
| `release` | the release binary, which writes only `imageRGB` | 1.74 (1.71-1.76) | 1416 (1401-1436) | - | 2641 | `imageRGB` unchanged; the other five images are not written |
| `kmeans-k12` | K-means clusters 24 -> 12 | 2.00 (1.96-2.03) | 1662 (1637-1698) | K-means 669 | 2587 | `imageRGB` 14.6 % of pixels (tumour 35.9 % -> 33.2 %) |
| `kmeans-k16` | K-means clusters 24 -> 16 | 1.81 (1.78-1.81) | 1471 (1465-1473) | K-means 483 | 2604 | `imageRGB` 13.6 % (tumour 35.9 % -> 45.2 %) |
| `kmeans-iter10` | K-means iterations 20 -> 10 | 1.63 (1.62-1.65) | 1311 (1284-1327) | K-means 309 | 2641 | `imageRGB` 9.0-9.6 % (tumour 35.9 % -> 39.8 %) |
| `kmeans-iter40` | K-means iterations 20 -> 40 | 2.01 (2.00-2.04) | 1691 (1670-1699) | K-means 696 | 2641 | `imageRGB` 1.0-1.5 % (tumour 35.9 % -> 35.1 %) |
| `knn-window9` | KNN window 15 -> 9 | 1.89 (1.89-1.96) | 1576 (1561-1621) | KNN 32 | 2640 | `knn` differs in 10 pixels (0.0009 %); the rest unchanged |
| `knn-neighbours20` | KNN neighbours 40 -> 20 | 1.93 (1.92-1.96) | 1610 (1603-1639) | KNN 58 | 2553 | `knn` 42.3 %, `imageRGB` 20.6 % (tumour 35.9 % -> 37.8 %) |
| `cuda-eager` | `CUDA_MODULE_LOADING=EAGER` (load all GPU code at start) | 2.78 (2.73-2.88) | 2389 (2344-2460) | PCA 303, SVM 55 | 2863 | unchanged; slower, and 2148 MiB of RAM instead of 1105 |
| **`shared-single`** | **`KMEANS_SHARED` and `PCA_PD=0` together** | **1.46 (1.45-1.50)** | **1140 (1135-1149)** | K-means 400, PCA 54 | **2223** | `pca` 0.024 %, by 1 grey level; `svm`, `knn` identical; the rest unchanged |

"Tumour" is the median share, over the five runs, of pixels `imageRGB` paints
as tumour. On `002-04` the baseline paints 35.9 % tumour and 64.1 %
background; `002-04` has no ground truth, so none of these shares can be
called right or wrong.

### Pixels per class

The class images counted pixel by pixel, in every one of the five kept runs
of each trial, out of 1,166,400 pixels (`measure-uc1.py report`). Every run of
every trial was also checked to have all its images, at 1080 x 1080 and not
a single colour (`measure-uc1.py recheck`).

`svm` had the same counts in every run of every trial: 24,595 normal,
412,827 tumour, 4,848 hypervascularized and 724,130 background. `knn` had
7,730 normal, 414,025 tumour, 648 hypervascularized and 743,997 background in
every trial except two: `knn-window9` (7,731 normal, 647 hypervascularized, the
rest the same; 10 pixels changed place) and `knn-neighbours20` (10,827 normal,
500,757 tumour, 1,316 hypervascularized, 653,500 background).

`imageRGB` has only tumour and background on `002-04`. Median over the five
runs, with the fewest and most:

| Trial | Tumour pixels | Background pixels |
| --- | --- | --- |
| Baseline (`baseline`, the comparison reference) | 418,970 (418,966-418,972) | 747,430 (747,428-747,434) |
| `baseline-repeat` | 418,965 (418,962-418,969) | 747,435 (747,431-747,438) |
| `kmeans-shared` | 418,960 (418,959-418,963) | 747,440 (747,437-747,441) |
| `pca-single` | 418,968 (418,962-418,977) | 747,432 (747,423-747,438) |
| `shared-single` | 418,963 (418,957-418,967) | 747,437 (747,433-747,443) |
| `kmeans-aos` | 418,951 (418,947-418,956) | 747,449 (747,444-747,453) |
| `release` | 418,963 (418,962-418,967) | 747,437 (747,433-747,438) |
| `cuda-eager` | 418,966 (418,965-418,972) | 747,434 (747,428-747,435) |
| `knn-window9` | 418,967 (418,960-418,970) | 747,433 (747,430-747,440) |
| `kmeans-k12` | 386,864 (386,861-386,867) | 779,536 (779,533-779,539) |
| `kmeans-k16` | 527,247 (527,242-527,251) | 639,153 (639,149-639,158) |
| `kmeans-iter10` | 463,874 (463,871-495,570) | 702,526 (670,830-702,529) |
| `kmeans-iter40` | 409,382 (409,375-412,291) | 757,018 (754,109-757,025) |
| `knn-neighbours20` | 440,894 (440,890-440,897) | 725,506 (725,503-725,510) |

The first nine rows are within a few tens of pixels of each other, which is
K-means' own run-to-run variation. `kmeans-iter10` and `kmeans-iter40` each
had one run thousands of pixels away from their other four. In
`kmeans-iter40` that run stopped after 22 iterations instead of 23. In
`kmeans-iter10` every run did its 10 iterations and ended with the same
error, so the outlier's clusters were split differently, not stopped
earlier.

What the trials show:

- **`KMEANS_SHARED`** updates the K-means cluster centres in the GPU's shared
  memory. It saves 220 ms at no measurable cost to the outputs. UC1's guide
  warns of a "slight float precision trade-off"; on `002-04` it stayed inside
  the run-to-run difference. UC1 tests it with `#ifdef`, so
  `-DKMEANS_SHARED=0` would switch it on too.
- **`PCA_PD=0`** computes the PCA in single rather than double precision. This
  laptop's GPU is much slower at double precision, so PCA drops from 271 to
  55 ms. The SVM step's 37 ms disappears with it, most likely because it was
  the set-up of the first single-precision matrix call, which PCA now makes
  first. It also needs 418 MiB less GPU memory. The PCA image moves by one
  grey level in 0.024 % of its pixels; the SVM, KNN and final classification
  do not change.
- **The product build already has the faster K-means layout**
  (`OPTIMIZE_KMEANS=1`); the delivered baseline layout is 100 ms slower.
- **The intermediate images cost about 0.25 s.** The release binary skips
  them, but SLIAFlow shows them, so this only says what they cost.
- **CUDA's default lazy loading is the right one.** Loading everything at
  start is 0.8 s slower.
- **Every parameter change moves the classification**, except the KNN window,
  whose 27 ms are not worth changing a classifier setting for.

## Size limit

UC1 run once on cubes made by tiling the mapped `002-04` to larger sizes
(`measure-uc1.py sizes`, then `sizes 2300x2300 2430x2430` to narrow the gap).
Each tiled cube was written to `build/uc1/trials/cubes/` and deleted after its
run; nothing was written to `input/`.

UC1 checks almost none of its GPU calls: the error checks in its source are
commented out. When it runs out of GPU memory it does not stop. It exits
normally and writes images, so the exit code cannot tell a success from a
failure. The script therefore checks the outputs, in two ways:

- every image must exist, have the cube's size and hold more than one colour;
- the SVM classifies each pixel on its own, so on a tiled cube its map must
  be the baseline's map tiled the same way, top-down (at most 0.1 % of pixels
  may differ).

| Size (pixels) | Cube | UC1 exit | Process s | UC1 timer ms | GPU in use at peak | RAM peak (committed) | SVM map vs tiled baseline | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1080 x 1080 (1.2 M) | 0.40 GiB | 0 | 2.4 | 1840 | 3687 MiB | 1105 MiB (3766) | identical | runs |
| 1620 x 1620 (2.6 M) | 0.91 GiB | 0 | 5.3 | 4432 | 6850 MiB | 2123 MiB (7568) | identical | runs |
| 2160 x 2160 (4.7 M) | 1.62 GiB | 0 | 14.9 | 13290 | 7778 MiB | 3481 MiB (12818) | identical | runs, slowly |
| 2300 x 2300 (5.3 M) | 1.83 GiB | 0 | 16.3 | 13868 | 7876 MiB | 5578 MiB (14335) | identical | runs, slowly |
| 2430 x 2430 (5.9 M) | 2.05 GiB | 0 | 12.2 | 9465 | 7798 MiB | 7473 MiB (15864) | 100 % different | **fails silently** |
| 2700 x 2700 (7.3 M) | 2.53 GiB | 0 | 12.1 | 9302 | 7708 MiB | 7118 MiB (16757) | 100 % different | **fails silently** |

The GPU has 8151 MiB. From 1620 to 2160 the pixels grow 1.8 times but the time
grows 3 times, and GPU memory stops growing just under the GPU's size: the
Windows driver is most likely moving GPU memory to system RAM, which is slow.
From 2430 up the allocations fail. What UC1 then writes, kept once to look at
it and then deleted:

- at 2430 x 2430 the scaled cube image is right, but the PCA image is black,
  the SVM, KNN and K-means images are one colour each, and the class map is
  entirely one class. KNN reported 0.03 ms and K-means 3 ms: they did not run.
- at 2700 x 2700 even the scaled cube image is black.

The rest of the ladder (4096 x 2160, 3240 x 3240) was not run: 2700 x 2700
was the first failure.

The table gives one run per size. To check that the limit does not depend on
the state of one run, 2300 and 2430 were run three more times each
(`sizes --repeat 3 2300x2300 2430x2430`):

| Size | Run | Process s | RAM free before | GPU in use at idle | GPU in use at peak | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 2300 x 2300 | 1 | 19.9 | 2109 MiB | 598 MiB | 7840 MiB | runs (SVM map identical) |
| 2300 x 2300 | 2 | 15.1 | 6204 MiB | 495 MiB | 7794 MiB | runs (SVM map identical) |
| 2300 x 2300 | 3 | 14.4 | 6771 MiB | 448 MiB | 7821 MiB | runs (SVM map identical) |
| 2430 x 2430 | 1 | 10.6 | 6480 MiB | 429 MiB | 7801 MiB | fails silently |
| 2430 x 2430 | 2 | 8.4 | 8279 MiB | 413 MiB | 7803 MiB | fails silently |
| 2430 x 2430 | 3 | 7.3 | 8483 MiB | 390 MiB | 7810 MiB | fails silently |

Each failed run was caught by both checks: the PCA, SVM, KNN, K-means and
class-map images were each a single colour, and the SVM map was 100 %
different. Over the four runs of each size, 2300 ran with between 2.1 and
6.8 GB of RAM free and 2430 failed with up to 8.5 GB free, with 250 to 600 MiB
of GPU memory used by other programs. The limit held under those conditions.
A desktop that uses more GPU memory would lower it. Four runs cannot rule out
that it moves by a few percent on another day, so plan with 5.3 million
pixels as the measured figure, not as a guaranteed one.

The UC1 process also commits six to nine times the cube's size in RAM
(16.4 GiB at 2700 x 2700, against 15.3 GiB installed), so above about 2160 x 2160 this
laptop pages to disk as well.

What this means for the product: **a calibrated LCTF cube at the camera's full
4096 x 2160 resolution cannot be classified on this laptop by UC1 as it is**,
and if one were given to it, SLIAFlow would today show blank or single-colour
images as a result (SLIAFlow checks that the five images exist, were written
by this run and are valid images of the right size, not what they contain). IUMA's current calibrated cube, 1080 x
1080, runs with about 4.4 GiB of GPU memory to spare.

## Recommendation

Adopt **`KMEANS_SHARED`** in the product build: it saves about 0.2 s of the
2.6 s Capture (9 %) and changed no output beyond UC1's own run-to-run
difference. **`PCA_PD=0`** saves another 0.3 s and 418 MiB of GPU memory. Together they
bring UC1 from 1.99 s to 1.46 s (27 %); Capture to result should fall by about
the same 0.5 s, to about 2.1 s (not measured in Slicer, since the product was
not changed). Its cost is the PCA image: 281 of its 1,166,400 pixels (0.024 %) one
grey level different on `002-04`, with the classification unchanged. Because `check-uc1.py`
holds the reference case's `pca.bmp` to its unpatched hash, adopting
`PCA_PD=0` would also mean restating that check for `pca.bmp`, which is why it
is a separate choice. Do not change UC1's parameters for speed: five of the
six measured move 1-21 % of the classification for at most 0.36 s, and the
sixth (KNN window 9) saves only 27 ms. Adopting
either flag is a change to `build-uc1.ps1`'s definitions, recorded in
`uc1_changes.md` and re-checked with `check-uc1.py`, in a task of its own.

Two findings are not settings but are worth their own cards:

- **Above about 5.3 million pixels UC1 fails without saying so.** Before larger
  cubes arrive, SLIAFlow should refuse a cube above a measured size, or UC1
  should check its GPU allocations (a patch), so that a blank result is never
  shown as a result.
- **The cube goes through the disk twice at every Capture:** SLIAFlow writes the
  mapped cube (0.35 s) and UC1 reads it back (0.26 s). Skipping the write when
  the cube has not changed since the last Capture would save the first.

## How it was measured

### The machine

- NVIDIA GeForce RTX 5050 Laptop GPU, 8151 MiB, compute capability 12.0,
  driver 591.74 (WDDM), CUDA toolkit 12.9 (`uc1_local_build.md`).
- 15.3 GB of RAM. Windows 11, Balanced power plan, on mains throughout.
- Other programs using the GPU while measuring: the desktop, VS Code, Edge,
  Teams, Windows Terminal, NVIDIA Overlay and three Slicer windows. At the
  start 1.0 GiB of GPU memory and 0.8-3.0 GB of RAM were free; by the second
  size run other programs had closed and 0.25 GiB of GPU memory was in use.
- The GPU idles at 250 MHz (P8) and needs a few seconds of work to reach full
  clock. The first baseline, run after the GPU had been idle, came out at
  2.06 s (2.01-2.70), its first runs slower; it was repeated after the other
  trials (`baseline-repeat`, 1.99 s), and the tables use the repeat. The
  deterministic images of both baselines are identical.

### UC1 on its own

`scripts/development/measure-uc1.py` runs a UC1 binary in a folder of its own
under `build/uc1/trials/<trial>/`, never in the product build, so a trial can
change `parameters.txt` or run another binary without touching what SLIAFlow
runs. Its input is the cube a Capture gives UC1: `002-04` mapped onto the 93
model bands by SLIAFlow's own mapping (`SLIAFlowUc1Input`), written once to
`build/uc1/trials/input/002-04/`.

Each trial is one warm-up run, not counted, then five runs. For each run the
script records:

- **Process**: the UC1 process from start to exit, as SLIAFlow waits for it.
- **UC1 timer**: `Time simulation`, from the start of UC1's `main` to the end
  of the classification.
- **Steps**: the timings the intermediate build prints (`KMEANS , 616.2 ,ms`).
- **GPU memory**: the rise of the GPU's used memory over its level in the
  second before the run, sampled by `nvidia-smi` about every 60 ms. This
  driver reports no per-process figure, so it is device-wide: anything else
  allocating GPU memory during the run is counted too.
- **RAM**: the UC1 process's peak working set and peak commit.
- **Output check**: every image the binary writes (six for the intermediate
  build, `imageRGB` alone for the release build) exists, is 1080 x 1080 and
  holds more than one colour. A run that fails this fails the trial, even when
  UC1 exits 0.
- **Outputs**: compared with the baseline's, pixel by pixel, and counted per
  class in every kept run. `pca`, `svm`, `knn` and `CalibratedImage_BIP` were
  identical in every run of every trial that did not change them, so a
  difference there is the trial's.

The output check was added after the trials had run. `measure-uc1.py recheck`
applied it, and the per-class counts, to the outputs the trials had kept: all
five counted runs of all fourteen trials pass. The warm-up runs' outputs are
not kept, so they were not rechecked; they are not in any figure.

### Commands

From the repository root, after `.\scripts\development\build-uc1.ps1 -Clean`:

```powershell
$py = ".\.venv\Scripts\python.exe"
$m = "scripts\development\measure-uc1.py"
$v = "build\uc1\variants"

# Baseline and parameter trials, on the product binary
& $py $m run baseline
& $py $m run kmeans-k12 --set kmeans_k=12
& $py $m run kmeans-k16 --set kmeans_k=16
& $py $m run kmeans-iter10 --set kmeans_max_iterations=10
& $py $m run kmeans-iter40 --set kmeans_max_iterations=40
& $py $m run knn-window9 --set knn_window=9
& $py $m run knn-neighbours20 --set knn_neighbours=20
& $py $m run cuda-eager --env CUDA_MODULE_LOADING=EAGER
& $py $m run baseline-repeat

# Build-flag trials, on variants
.\scripts\development\build-uc1.ps1 -Clean -Variant kmeans-shared -Defines "-DOPTIMIZE_KMEANS=1 -DPCA_PD=1 -DKMEANS_SHARED"
.\scripts\development\build-uc1.ps1 -Clean -Variant pca-single -Defines "-DOPTIMIZE_KMEANS=1 -DPCA_PD=0"
.\scripts\development\build-uc1.ps1 -Clean -Variant kmeans-aos -Defines "-DOPTIMIZE_KMEANS=0 -DPCA_PD=1"
.\scripts\development\build-uc1.ps1 -Clean -Variant release -Release
.\scripts\development\build-uc1.ps1 -Clean -Variant shared-single -Defines "-DOPTIMIZE_KMEANS=1 -DPCA_PD=0 -DKMEANS_SHARED"
& $py $m run kmeans-shared --binary $v\kmeans-shared\gpu_single_bsq\source\stratum.opt.intermediate.exe
& $py $m run pca-single --binary $v\pca-single\gpu_single_bsq\source\stratum.opt.intermediate.exe
& $py $m run kmeans-aos --binary $v\kmeans-aos\gpu_single_bsq\source\stratum.opt.intermediate.exe
& $py $m run release --binary $v\release\gpu_single_bsq\source\stratum.opt.exe
& $py $m run shared-single --binary $v\shared-single\gpu_single_bsq\source\stratum.opt.intermediate.exe

# Size limit
& $py $m sizes
& $py $m sizes 2300x2300 2430x2430
& $py $m sizes --repeat 3 2300x2300 2430x2430

# The output check and per-class counts on the outputs the trials kept
& $py $m recheck

# All results as tables
& $py $m report

# Capture in Slicer, with the configured Slicer and the module source
& C:\stratum\apps\SR\Slicer-build\Slicer.exe --no-splash --no-main-window `
    --additional-module-paths extensions\SLIAFlow\SLIAFlow `
    --python-script scripts\development\measure-capture.py --runs 5
```

Every command writes its results as JSON to `build/uc1/trials/results/`
(gitignored). The variants all compiled with exactly the product's two expected
warnings.

### Capture in Slicer

`scripts/development/measure-capture.py` runs inside Slicer, without the
window, and makes the calls SLIAFlow makes when Capture is pressed, in the same
order: check the cube, write the mapped cube and start UC1, read the cube for
HS Cube while UC1 runs, wait for UC1, check its outputs, load them into Slicer.
It leaves out what needs the window or the camera: the snapshot of the
LiveView frame (one PNG written before the run), putting the result in the
Tumour Delineation view, and drawing the views. Those were not measured.
