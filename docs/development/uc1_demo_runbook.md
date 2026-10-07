# Running the UC1 demonstration

This is the sequence to follow in front of an audience, what each step should
show, and the sentences that keep the demonstration honest.

## The in-Slicer demonstration (SLIA-027)

Since `SLIA-027` the demonstration runs from one application and no console:

1. Once: `.\scripts\development\build-uc1.ps1`, then
   `.\scripts\development\build-sliaflow.ps1`. Both must exit 0.
   `build-uc1.ps1` applies the UC1 patches recorded in `uc1_changes.md`.
2. Double-click `build\SLIAFlow\SlicerWithSLIAFlow.exe` and open SLIAFlow.
3. Press **Start**. LiveView shows the laptop camera.
4. Press **Capture**. LiveView freezes and the frame is saved under
   `workspace\captures`. Every Capture runs UC1 on the one configured cube,
   IUMA's calibrated LCTF cube `002-04` (`input\002-04`, `ADR-0004`), mapped onto
   the 93 bands UC1's model was trained for (`SLIA-033`). The status names
   recorded cube `002-04` and moves through running UC1 and validating; a run
   took about 4.6 s from Capture to result on 2026-09-25.
5. LiveView resumes. **Delineation output** selects `pca.bmp`, `svm.bmp`,
   `knn.bmp`, `kmeans.bmp` or `imageRGB.bmp`, each 1080 x 1080 and shown on its
   own as UC1 wrote it. The result status reads
   `Recorded cube 002-04 - simulated acquisition` and says that UC1 results on
   this cube are not validated. Say it out loud as well: UC1's model was trained
   on another camera, so the map shows what the pipeline does with the LCTF
   cube, not whether it is right. On `002-04` most of the tissue in view comes
   out as tumour.
6. `svm.bmp` and `knn.bmp` paint each pixel with its class: green normal
   tissue, red tumour, blue hypervascularized, black background. `002-04` has
   no labelling to compare them with.
7. HS Cube shows the same cube, and both panels name it: HS Cube reads
   `Recorded cube 002-04, calibrated reflectance`, and Tumour Delineation reads
   `Result for recorded cube 002-04`. Scroll HS Cube to move through the 109
   bands; the caption gives each band's wavelength. **HS Cube shows** switches
   to a colour preview (650, 550 and 470 nm as red, green and blue, labelled
   a band composite, not a photograph). Clicking a pixel plots its stored
   reflectance under **Pixel spectrum**. Say out loud that the plot shows the
   cube's own numbers, not an analysis.

When a Capture fails, the status says `Failed on recorded cube <cube>: ...` with
the reason and what to do, LiveView resumes, and the previous result stays on
screen under `PREVIOUS RESULT - not from the current capture`. Nothing is run on
another cube; press Capture again.

| Status says | What it means |
| --- | --- |
| `stratum.opt.intermediate.exe is not in ...` | Run `build-uc1.ps1` |
| `... .uc1-runner.lock exists ...` | Another UC1 run holds the build. If none is running, delete the named file |
| `The SVM model file ... must be ... bytes` | Re-stage with `build-uc1.ps1`; never patch the model |
| `UC1 timed out after 60 s` | The process was killed; check the GPU and the Python console log |
| `... is not a valid UC1 image ...` | An output was missing, older than the run, the wrong size or malformed; the whole run is refused |
| `The configured cube ... cannot be used: ...` | `input\002-04\LCTF_Calibrated_Cube_Single` is missing, its header and data file disagree, or its bands are not IUMA's LCTF grid (460-1000 nm in 5 nm steps); the reason follows. See `input\README.txt` |
| `Cube 002-04 changed on disk since Capture was pressed` | The cube's header or data file was written to or replaced between Capture and the run, or while it was copied for UC1, even with the same size; press Capture again |
| HS Cube: `The hyperspectral cube could not be shown.` | The same cube could not be read for the panel; the reason follows on the panel, and the status says whether UC1 ran |

To check that the patched UC1 still writes what it wrote on `002-04` when it
was recorded, and that each patch does its job, run
`.\.venv\Scripts\python.exe scripts\development\check-uc1.py` after
`build-uc1.ps1`. It prints `PASS` and exits 0.
