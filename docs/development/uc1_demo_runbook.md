# Running the UC1 demonstration

This is the sequence to follow in front of an audience, what each command
should print, and the sentences that keep the demonstration honest. The output
quoted here was captured on 2026-09-16 on recorded case `004-02`, on the
toolchain recorded in `uc1_local_build.md`; it is that run's output, not an
example.

## The in-Slicer demonstration (SLIA-027)

Since `SLIA-027` the demonstration runs from one application and no console:

1. Once: `.\scripts\development\build-uc1.ps1`, then
   `.\scripts\development\build-sliaflow.ps1`. Both must exit 0.
2. Double-click `build\SLIAFlow\SlicerWithSLIAFlow.exe` and open SLIAFlow.
3. Press **Start**. LiveView shows the laptop camera.
4. Press **Capture**. LiveView freezes and the frame is saved under
   `workspace\captures`. The status names the recorded case and moves through
   running UC1 and validating; a run on `004-02` took about two seconds. Every
   Capture runs on the one configured cube, `input\reference_hsi_brain_db\020-01`
   (`SLIA-031`, `ADR-0004`).
5. LiveView resumes. **Delineation output** selects `pca.bmp`, `svm.bmp`,
   `knn.bmp`, `kmeans.bmp` or `imageRGB.bmp`, each shown on its own as UC1 wrote
   it. The result status reads `Recorded case <case> - simulated acquisition`.
6. The sixth entry, `gtMap`, lays the case's recorded labelling over whichever
   output is chosen, on the Label layer. Choose `svm.bmp` or `knn.bmp` first:
   those two are painted from the same class colours as the ground truth, so
   the overlay can be read directly. Use the slice view's Label opacity slider
   and outline toggle to compare.

   `020-01` was kept as the reference case because it carries tumour pixels
   (3,655 of them); 35 of the 61 database cases carry none.

When a Capture fails, the status says `Failed on recorded case <case>: ...` with
the reason and what to do, LiveView resumes, and the previous result stays on
screen under `PREVIOUS RESULT - not from the current capture`. No replacement
case is started; press Capture again.

| Status says | What it means |
| --- | --- |
| `stratum.opt.intermediate.exe is not in ...` | Run `build-uc1.ps1` |
| `... .uc1-runner.lock exists ...` | Another UC1 run holds the build. If none is running, delete the named file |
| `The SVM model file ... must be ... bytes` | Re-stage with `build-uc1.ps1`; never patch the model |
| `UC1 timed out after 60 s` | The process was killed; check the GPU and the Python console log |
| `... is not a valid UC1 image ...` | An output was missing, older than the run, the wrong size or malformed; the whole run is refused |
| `The configured cube ... cannot be used: ...` | The folder named is missing or not a recorded case UC1 can run on; the reason follows. See `input\README.txt` |

## Before SLIA-028: the standalone console demonstration

**Historical.** The sections below record the console demonstration of
2026-09-16. `SLIA-028` removed everything they run - `run-end-to-end-session.ps1`,
`run-uc1-real.ps1`, `python -m stratum_sim` and `uc1_client.py` - so their
commands no longer work, and demo mode and banners were removed from SLIAFlow
before that (`ADR-0003`). Use the in-Slicer demonstration above. The cases they
name now live under `input\archive_hsi_brain_db_93_bands\bin`, except `020-01`,
which is `input\reference_hsi_brain_db\020-01`.

### What the demonstration shows, and what it does not

It shows that the vendored UC1 CUDA pipeline compiles unmodified on this
machine, runs on the local GPU over a recorded case of the public, anonymized
HSI Human Brain Database, and that the class map it produces reaches SLIAFlow
over OpenIGTLink under the labelling the contract requires.

It does not show a clinical result. The pipeline is real and the case is real
recorded imagery, but this is a prototype, the acquisition event is simulated,
and nothing on screen carries diagnostic meaning. That is why every result still
travels marked `simulated`.

### Once, before the day

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

The case has to be passed as an explicit folder (see above).

### The demonstration itself

The whole loop - laptop camera, capture, cube, UC1, SLIAFlow - runs from one
console:

```powershell
.\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

`pipeline_test_quickstart.md` walks through that session. To show the pipeline
on its own, run it directly on the case:

```powershell
.\scripts\development\run-uc1-real.ps1 -DatasetFolder input\archive_hsi_brain_db_93_bands\bin\004-02
```

It classifies once, then serves `UC1_RGB` and `UC1_MV_CLASS` on 127.0.0.1:18945
and re-sends on an interval until Ctrl-C. Two switches are worth knowing:
`-ClassifyOnly` runs the pipeline and reports the recovered map without opening a
server, which is the quickest way to prove the GPU path works before an audience
arrives, and `-Cycles 3` stops after a fixed number of sends.

The classification step prints the band resolution for the background, the
vendored binary's own stdout prefixed `[uc1]`, and then what the runner
recovered from its output files:

```
Origin:     simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
UC1_RGB bands: 710 nm -> index 54 at 710 nm (miss 0.00 nm); 540 nm -> index 20 at 540 nm (miss 0.00 nm); 480 nm -> index 8 at 480 nm (miss 0.00 nm)
  [uc1] Sample: 345
  [uc1] Lines: 389
  [uc1] Debug: Uploading images from BSQ format to BIP format using CUDA
  [uc1] KMeansIterations: 18,
  [uc1] KMeansError: 0.000988
  [uc1] Time simulation ---> 379.774 ms
Recovered majorityVotingMap: shape (1, 389, 345), dtype uint8, classes {1: 55938 (41.7%), 2: 7954 (5.9%), 3: 31584 (23.5%), 4: 38729 (28.9%)}
```

**Slicer.** In SLIAFlow set **Result map** to `majorityVotingMap`, press
**Connect** on the UC1 link row, and tick **Demo mode**. The map arrives as
`UC1_MV_CLASS` over `UC1_RGB` and is displayed under the red banner, with the
producer's own description on the line below it:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
```

Demo mode is the only thing that lets a simulated result be displayed at all,
and a banner that cannot be drawn withholds the result rather than showing it
unmarked.

### Checking the wire without Slicer

Worth doing before a demonstration, and the honest way to answer "how do you
know what it is sending". With the runner serving and SLIAFlow's UC1 link
disconnected:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 6
```

```
Map role:         (no role)
Device name:      UC1_RGB
Image shape:      (1, 389, 345, 3)  (k, j, i[, components])
Scalar type:      uint8
Header version:   2
Metadata:
  SLIAFlow.CaptureId = <one value per run>
  SLIAFlow.DataOrigin = simulated
  SLIAFlow.DeviceName = UC1_RGB
  SLIAFlow.SimulationDetail = real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)

Map role:         majorityVotingMap
Device name:      UC1_MV_CLASS
Image shape:      (1, 389, 345)  (k, j, i[, components])
Scalar type:      uint8
Header version:   2
Metadata:
  SLIAFlow.CaptureId = <the same value>
  SLIAFlow.DataOrigin = simulated
  SLIAFlow.DeviceName = UC1_MV_CLASS
  SLIAFlow.ResultMap = majorityVotingMap
  SLIAFlow.SimulationDetail = real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)

-- Session summary over 6.0 s --
  UC1_MV_CLASS: 6 message(s)
  UC1_RGB: 6 message(s)
  Distinct UC1_* device names: UC1_MV_CLASS, UC1_RGB
```

### The four things worth saying out loud

**One map, not five.** UC1 computes the other four contract maps and discards
them before writing anything, so a session sends `UC1_MV_CLASS` alone, with its
`UC1_RGB` background, and leaves the rest absent rather than substituting zeros.

**The provenance string names the case.** The runner reads the case name from
the folder it classified, so no flag can make it claim an input the data does not
support, and a folder that is not an identified recorded case is refused before
the GPU runs.

**The background is a viewing aid.** `UC1_RGB` is three bands of the same cube -
710, 540 and 480 nm - at fixed reflectance scaling. It is not a colour-accurate
photograph and not the microscope's view.

**Re-running moves a few pixels.** Two runs on one case differ by a handful of
pixels - the class counts of the two `004-02` runs quoted in this document and in
`pipeline_test_quickstart.md` differ by 10, 0, 5 and 15 pixels, of 134205 -
because the GPU K-means reduction is not bit-deterministic. SLIA-013
requires at most 0.1% of pixels to change and every changed pixel to lie on a
class boundary. A run that moved pixels away from boundaries, or moved
appreciably more of them, would be a real regression.

### When something goes wrong

Failure is loud by design, and there is no fallback on any path. The messages
are specific, so read them rather than retrying:

| What is printed | What it means |
| --- | --- |
| The staged UC1 build was not found | Run `build-uc1.ps1`; the runner will not build on demand |
| Refusing to run UC1 ... does not identify as a case of the HSI Human Brain Database | The folder is not a recorded case. Point it at a case folder under `input\archive_hsi_brain_db_93_bands\bin` |
| A dataset of N bands cannot be classified | Only 93-band cases match the staged SVM model |
| A model file has the wrong size | The staged `svm_model/` does not match the pipeline. Rebuild rather than patching it |
| The output is older than the run | UC1 exited without writing. Its stdout is above the message |
| An RGB triple outside the UC1 palette | The output BMP is not a class image the runner can invert. Do not add a nearest-colour fallback |
| Another UC1 run holds the lock | UC1 uses fixed shared output paths, so only one run at a time is possible |

A uniform map is not an error, and is not silently accepted either: the runner
warns on stderr. `parameters.txt`, the SVM model and the vendored source are
never tuned to change what a case produces, because that would make every
future result meaningless.
