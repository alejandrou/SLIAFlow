# Running the UC1 demonstration

This is the sequence to follow in front of an audience, what each command
should print, and the sentences that keep the demonstration honest. Everything
below was run end to end on 2026-09-04 on the toolchain recorded in
`uc1_local_build.md`, and the output quoted here is that run's, not an example.

## What the demonstration shows, and what it does not

It shows that the vendored UC1 CUDA pipeline compiles unmodified on this
machine, runs on the local GPU, and that the class map it produces reaches
SLIAFlow over OpenIGTLink under the labelling the contract requires.

It does not show detection of anything. The scene is a synthetic optical
phantom: its spectra come from a haemoglobin absorption and scattering model,
its regions are ellipses and sine tracks, and the region named `tumour-like` is
one where the blood volume fraction was set high and the saturation low. If a
viewer asks whether the coloured area is a tumour, the answer is no, and
`synthetic_tissue_phantom.md` is the document that says why at length.

The pipeline is real and only the input is invented, which is why every result
still travels marked `simulated`.

## Once, before the day

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\simulators\requirements.txt
.\scripts\development\build-uc1.ps1
```

The build stages the vendored sources elsewhere and re-proves by hash that
nothing under `workspace/components/` was touched. If it reports a toolchain
different from the one in `uc1_local_build.md`, stop and read that document
before demonstrating: the runtimes and expected warnings recorded there were
measured against a specific GPU, driver and nvcc.

## The demonstration itself

**Terminal 1 - write a scene and serve the live view.** The defaults are the
demonstration defaults: the `demo` preset at 160 x 120, 93 bands, the tissue
phantom.

```powershell
.\scripts\development\run-acquisition-simulator.ps1
```

It prints the folder it wrote, which the next command needs:

```
Acquisition stand-in: preset 'demo' (160x120), 93 bands, scene mode 'tissue', frame source 'synthetic', pyigtl 0.3.4.
  Phantom regions: cortex 37.5%, tumour-like 6.9%, vessel 7.6%, drape 48.0%
  Dataset written: C:\stratum\workspace\simulators\datasets\sim-20260904-090033
  Band covariance rank: 12 (condition number over the retained subspace: 4.099e+07)
```

Add `-DatasetOnly` when the live pane is not part of the story and only the
class map is.

**Terminal 2 - run the genuine pipeline on that folder.**

```powershell
.\scripts\development\run-uc1-real.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-20260904-090033
```

It classifies once, then serves `UC1_MV_CLASS` on 127.0.0.1:18945 and re-sends
on an interval until Ctrl-C. Two switches are worth knowing: `-ClassifyOnly`
runs the pipeline and reports the recovered map without opening a server, which
is the quickest way to prove the GPU path works before an audience arrives, and
`-Cycles 3` stops after a fixed number of sends.

The classification step prints the vendored binary's own stdout, prefixed
`[uc1]`, and then what the runner recovered from its output files:

```
Origin:     simulated - real UC1 pipeline, synthetic tissue phantom
  [uc1] Sample: 160
  [uc1] Lines: 120
  [uc1] Debug: Uploading images from BSQ format to BIP format using CUDA
  [uc1] KMeansIterations: 3,
  [uc1] KMeansError: 0.000374
  [uc1] Time simulation ---> 289.322 ms
Recovered majorityVotingMap: shape (1, 120, 160), dtype uint8, classes {2: 7502 (39.1%), 4: 11698 (60.9%)}
Maps produced by this run: majorityVotingMap
```

**Slicer.** Open the SLIAFlow module, add an `OpenIGTLinkIF` connector of type
Client to 127.0.0.1 port 18945, mark it Active, and turn demo mode on in
SLIAFlow. The map arrives as `UC1_MV_CLASS` and is displayed under the red
banner, with the producer's own description on the line below it:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, synthetic tissue phantom
```

Demo mode is the only thing that lets a simulated result be displayed at all,
and a banner that cannot be drawn withholds the result rather than showing it
unmarked.

## Checking the wire without Slicer

Worth doing before a demonstration, and the honest way to answer "how do you
know what it is sending":

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 8
```

```
Map role:         majorityVotingMap
Device name:      UC1_MV_CLASS
Image shape:      (1, 120, 160)  (k, j, i[, components])
Scalar type:      uint8
Metadata:
  SLIAFlow.DataOrigin = simulated
  SLIAFlow.DeviceName = UC1_MV_CLASS
  SLIAFlow.ResultMap = majorityVotingMap
  SLIAFlow.SimulationDetail = real UC1 pipeline, synthetic tissue phantom

-- Session summary over 8.0 s --
  UC1_MV_CLASS: 3 message(s)
  Distinct UC1_* device names: UC1_MV_CLASS
```

## The four things worth saying out loud

**One map, not five.** UC1 computes the other four contract maps and discards
them before writing anything, so a genuine session sends `UC1_MV_CLASS` alone
and leaves the rest absent rather than substituting zeros. Never run `uc1` and
`uc1-real` in one session: five maps from two different producers would imply
UC1 made all five.

**The provenance string names the scene.** A phantom dataset produces `real UC1
pipeline, synthetic tissue phantom`; a camera- or frame-driven one produces
`real UC1 pipeline, synthetic input`. The runner decides from the phantom record
in the dataset folder, so no flag can make it claim a scene the data does not
support.

**The map is coherent, and it is coarse.** On this scene UC1 separates the
tissue-like field from the drape and the vessels, and nothing finer. Measured
against the phantom's own construction map, which is not ground truth for any
classifier:

| Phantom region | Pixels | Class 2 | Class 4 |
| --- | --- | --- | --- |
| cortex | 7200 | 85.9% | 14.1% |
| tumour-like | 1319 | 100% | 0% |
| vessel | 1457 | 0% | 100% |
| drape | 9224 | 0% | 100% |

Cortex and tumour-like both land in class 2: the pipeline does not distinguish
them. Volunteering that is a stronger demonstration than being asked.

**Re-running moves a few boundary pixels.** Two consecutive runs on one dataset
differ by single pixels - one pixel of 19200 between the two runs quoted above -
because the GPU K-means reduction is not bit-deterministic. SLIA-013 requires at
most 0.1% of pixels to change and every changed pixel to lie on a class
boundary. A run that moved pixels away from boundaries, or moved appreciably
more of them, would be a real regression.

## When something goes wrong

Failure is loud by design, and there is no fallback to the arithmetic stand-in
on any path. The messages are specific, so read them rather than retrying:

| What is printed | What it means |
| --- | --- |
| The staged UC1 build was not found | Run `build-uc1.ps1`; the runner will not build on demand |
| A dataset of N bands cannot be classified | Only 93-band datasets match the staged SVM model. Regenerate the dataset at the default band count |
| A model file has the wrong size | The staged `svm_model/` does not match the pipeline. Rebuild rather than patching it |
| The output is older than the run | UC1 exited without writing. Its stdout is above the message |
| An RGB triple outside the UC1 palette | The output BMP is not a class image the runner can invert. Do not add a nearest-colour fallback |
| Another UC1 run holds the lock | UC1 uses fixed shared output paths, so only one run at a time is possible |

A uniform map is not an error, and is not silently accepted either: the runner
warns on stderr. It usually means the scene stopped having the spectral shape
the SVM model was trained on. The fix is the scene, never the classifier -
`parameters.txt`, the SVM model and the vendored source are not tuned to make an
invented scene look better, because that would make every future result
meaningless.
