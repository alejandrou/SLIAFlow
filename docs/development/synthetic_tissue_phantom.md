# The synthetic tissue phantom

The acquisition stand-in's default scene is a synthetic optical phantom whose
spectra are built from a haemoglobin absorption and scattering model. This
records why it exists, what it is made of, what the genuine UC1 pipeline says
about it, and - at least as importantly - what none of that means.

## Read this part first

The phantom is **not patient data, is not derived from patient data, and does
not contain a tumour.** Its regions are ellipses and sine tracks drawn on a
grid. A region called `tumour-like` is a region where the blood volume fraction
was set to 0.06 and the oxygen saturation to 0.60. That is all it is.

When the genuine UC1 pipeline runs on this phantom it produces a coloured map
with a red area where the tumour-like region is. **That is not a detection.**
It is a classifier trained on real brain reflectance responding to a spectrum
that was constructed to have the shape of brain reflectance. A demonstration
built on this can honestly show that the pipeline runs, that it is wired to
SLIAFlow, and that it produces a spatially structured result. It cannot show
that the pipeline finds tumours, and it must never be presented as showing
that.

The measured section below states plainly where UC1 disagrees with how the
phantom was built. Those disagreements are the evidence that this is a plumbing
demonstration and not a detector.

## Why the previous scene did not work

The channel-driven scene in `spectra.py` builds each pixel's spectrum by mixing
three camera colour-response Gaussians, a near-infrared envelope, and narrow
texture features. It is spectrally rich - band covariance rank 9, calibrated
values from 1.5 to 90 - and it is what SLIA-011 and SLIA-012 were validated
against.

The genuine UC1 pipeline resolved every pixel of it to class 4, background.

The collapse was localised with UC1's own `INTERMEDIATE_OUTPUT` build, which
writes one bitmap per stage: `svm.bmp` was already 97.2 % background while
`kmeans.bmp` was healthy with 24 clusters at 5-7 % each. So it is the SVM
stage, and `normalizeImgKernel_optimized` says why. It min-max normalizes every
pixel across its bands before the classifier, so **only the shape of a spectrum
ever reaches the SVM, never its magnitude.** The shipped `w_vector.bin` is a
linear model trained on real in-vivo brain reflectance. A shape made of three
colour-filter Gaussians is not a shape that model has ever been asked about.

Tuning the near-infrared envelope, which the task card originally prescribed,
would not have addressed that. The cube was never degenerate.

## What the phantom is made of

`tools/simulators/stratum_sim/tissue.py`, in the units tissue is measured in.

### Chromophores

Absorption is the sum of oxyhaemoglobin, deoxyhaemoglobin and water. Each
haemoglobin curve is an analytic sum of Gaussians at the standard band
positions:

| Chromophore | Bands used |
| --- | --- |
| HbO2 | Soret 415 nm, alpha 542 nm, beta 576 nm, broad NIR rise near 900 nm |
| Hb | Soret 430 nm, visible peak 556 nm, red shoulder 650 nm, NIR peak 758 nm |
| Water | 975 nm, with a weak 840 nm shoulder |

They cross near 800 nm, which is the isosbestic point, and a test asserts that
crossing rather than trusting it.

**These amplitudes and widths are approximations at published peak positions,
not a transcribed extinction table.** They reproduce the features that give
tissue spectra their shape. They must not be used for quantitative oximetry,
and nothing in this repository does.

Absorption from blood is `2.303 * eps(lambda) * f * 2.33 mM`, where `f` is the
blood volume fraction and 2.33 mM is the haemoglobin molarity of whole blood at
150 g/L.

### Scattering and reflectance

Reduced scattering is the usual power law, `a * (lambda / 500 nm)^-b`.

Reflectance is the diffusion approximation for a semi-infinite turbid medium,
a function of the transport albedo `a' = mu_s' / (mu_s' + mu_a)`:

```text
R = a' / (1 + 2k(1 - a') + (1 + 2k/3) * sqrt(3(1 - a')))
```

with `k = 1.44` for a tissue-air boundary at refractive index 1.4. It is a
coarse model - no layering, no boundary geometry, no source-detector separation
- and it is used for one property: it turns chromophore absorption into a
reflectance shape the right way round.

### Regions

| Region | Blood volume | Saturation | Water | mu_s'(500) | Power |
| --- | --- | --- | --- | --- | --- |
| cortex | 0.030 | 0.75 | 0.75 | 22 cm^-1 | 1.3 |
| tumour-like | 0.060 | 0.60 | 0.80 | 16 cm^-1 | 1.0 |
| vessel | 0.250 | 0.85 | 0.85 | 15 cm^-1 | 1.0 |

The drape is **not** run through the tissue model. A matte green surgical drape
is a dyed fabric: a broad reflectance band near 530 nm over a low floor, with
the gentle near-infrared rise woven synthetics have. Running the turbid-medium
model at a near-zero blood volume would have given the surround a spectrum
shaped like exsanguinated brain, which is not what lies around a craniotomy.

Within each region the blood volume, saturation and scattering amplitude are
modulated by smooth low-frequency fields. Without that every pixel of a region
would carry an identical spectrum, the band covariance would be one direction
per region, and K-means would have four points to cluster. Measured band
covariance rank of the written dataset: **12**, against a floor of 8.

### Geometry

An elliptical craniotomy field on drape, with a tumour-like blob and three
sinusoidal vessel tracks inside the field. In fractions of the frame, so that
the scene is the same at every preset:

| Shape | Centre (x, y) | Radii (x, y) |
| --- | --- | --- |
| craniotomy field | 0.50, 0.50 | 0.40, 0.42 |
| tumour-like blob | 0.36, 0.58 | 0.15, 0.17 |

The three vessel tracks are sine curves of the form
`y = offset + amplitude * sin(6x + phase) + slope * x`, each drawn a listed
half-width either side of its curve and clipped to the field; their individual
parameters are `VESSEL_TRACKS` in `tissue.py`. Both ellipses and the track
count are restated in `tests/test_tissue.py`, which rebuilds them from this
table and fails if the code and this document drift apart.

Drawing order matters. The tracks are painted last, so they cut the cortex and
tumour-like labels into several areas each, and the number of areas per label
is a rasterisation artifact of the frame size - the vessel label alone falls
into 15 areas at 24 x 32, 2 at 48 x 64 and 3 at 96 x 128. Those counts are
therefore not pinned by any test. What is asserted is what the geometry
actually promises and what holds at every size:

- the craniotomy field is one connected area, and so is the drape around it;
- every label owns an area covering at least 1 % of the frame;
- the vessel label never falls into more areas than there are tracks;
- the interior regions never touch the frame edge.

Rasterising five curved boundaries onto a small grid does leave a few one- and
two-pixel slivers where a track clips the field or the tumour edge: 10 pixels
of 3072 at 48 x 64, and under 0.02 % of the frame at every larger preset. They
are held to a budget rather than pinned, together with the rule that separates
them from noise - a sliver appears only where two drawn boundaries cross, so it
always borders both of the labels that made it, while a stray pixel dropped
into a region's interior borders only one and is rejected.

### The frame and the cube are the same array

In `tissue` scene mode the cube is built first and the LiveView frame is
rendered from it, by projecting the cube through the same channel response
curves `spectra.py` already defines. So the live pane and the dataset cannot
drift apart. The `channel` mode goes the other way, frame to cube, and remains
the only mode that can carry motion or a webcam - the phantom is a still scene.

## The line that was not crossed

**The optical parameters were never fitted to the classifier.** The absorption
model comes from the chromophores and the region parameters from published
physiological ranges. The shipped SVM weights were used only afterwards, to
characterise what the model does with the result.

That distinction is the whole ethical content of this work. Optimising an input
against a trained model's weights produces an adversarial example: it would
light up the display beautifully and would mean less than nothing. A phantom
built from physics can be judged by a reader who knows tissue optics, and can
be wrong in ways that show.

A `numpy` replica of UC1's SVM - the linear stage, the sigmoid calibration and
the pairwise probability coupling, transcribed from `kernelSVM` in
`functions_cuda.cu` - was used for that characterisation. It reproduces the
real binary's SVM stage on the old channel scene to 97.17 % against the 97.2 %
measured from `svm.bmp`. Over 8960 combinations spanning the physiological
ranges of blood volume, saturation, water, scattering amplitude, scattering
power and specular glare, that model assigns **only classes 2 and 4**. Class 1
appears only at implausible parameters (saturation 0.30 with water 0.1) and
class 3 never appears at all. Those combinations were not adopted.

## What UC1 actually says about it

Measured on the toolchain in `uc1_local_build.md`. Rows are how the phantom was
built; columns are what the genuine pipeline reported.

`demo`, 160 x 120:

| Region | n | class 1 | class 2 | class 3 | class 4 |
| --- | --- | --- | --- | --- | --- |
| cortex | 7200 | 0.0 % | 85.9 % | 0.0 % | 14.1 % |
| tumour-like | 1319 | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| vessel | 1457 | 0.0 % | 0.0 % | 0.0 % | 100.0 % |
| drape | 9224 | 0.0 % | 0.0 % | 0.0 % | 100.0 % |

`full`, 640 x 480: the whole craniotomy field - cortex, tumour-like and vessel
alike - goes to class 2, and the drape to class 4.

Read that honestly and it says four things.

1. **The map is no longer uniform.** Two classes, in coherent regions: 96.6 %
   of pixels at `demo` agree with at least three of their four neighbours, and
   99.7 % at `full`. That was the acceptance criterion, and it is met.
2. **UC1 does not separate cortex from the tumour-like region.** It calls both
   class 2. There is no detection here.
3. **UC1 calls the vessels background** at `demo`, and tissue at `full`. The
   region with the most blood in it is the one the classifier is least sure
   about.
4. **The result depends on the frame size.** The same phantom classified at two
   presets gives two different answers, because K-means clusters a different
   number of pixels into the same 24 clusters.

Classes 1 and 3 never appear. Nothing in the phantom is tuned to make them.

## Run-to-run stability

Six consecutive runs on one `demo` dataset: **6 pixels of 19200 (0.036 %)
changed at all, and all 6 lie on a class boundary.** The `output/rgb/*.txt`
files are therefore *not* byte-identical between runs, though the map is stable
everywhere except those boundary pixels.

This supersedes the byte-identical result recorded against the old channel
scene. That earlier evidence was weak for exactly the reason noted at the time:
a uniformly single-class map is byte-identical far more easily than a varied
one. The variation is ordinary floating-point non-determinism in the GPU
K-means reduction, which moves a borderline pixel between clusters; majority
voting then hands it the other cluster's class.

## Using it

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"

# The default. Writes a phantom dataset and exits.
.\.venv\Scripts\python.exe -m stratum_sim acquisition --preset demo --dataset-only

# The old channel scene, which is the only one that can carry motion or a camera.
.\.venv\Scripts\python.exe -m stratum_sim acquisition --scene-mode channel --frame-source webcam
```

`sceneMode` is also a `simulators` setting in `config/local.json`. Asking for
`tissue` with a webcam is refused rather than silently ignored: in tissue mode
the frame is rendered from the cube, so there is nowhere for a camera frame to
enter, and an operator should not be left believing the phantom was built from
what the camera saw.

Each phantom dataset carries two extra files that no consumer reads:

- `phantom_regions.npy` - the `(lines, samples)` uint8 construction map.
- `phantom_regions.json` - the region names, their optical parameters, and the
  non-clinical notice.

They exist so a person can check what the classifier was shown against how the
scene was built. **They are a construction record, not ground truth**, and no
test in this repository grades UC1 against them - a test that pinned the table
above would turn a measurement into a target.

## What the wire says

The acquisition stand-in reports
`SLIAFlow.SimulationDetail = "acquisition stand-in, synthetic tissue phantom"`,
which distinguishes a phantom dataset from a channel-scene one on the LiveView
stream.

The UC1 runner reports `"real UC1 pipeline, synthetic tissue phantom"` for a
phantom dataset and `"real UC1 pipeline, synthetic input"` - the string
SLIA-013's acceptance criteria name - for anything else. It decides by looking
for `phantom_regions.json` in the dataset folder rather than by taking a flag,
so the detail cannot disagree with the data that was read.

Both strings keep `SLIAFlow.DataOrigin = simulated`. The origin describes the
data and never softens because the algorithm is genuine; the detail is what
distinguishes a phantom built to have the shape of tissue from a scene mixed
out of camera colour curves.
