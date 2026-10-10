# Running the UC1 demonstration

This is the sequence to follow in front of an audience, what each step should
show, and the sentences that keep the demonstration honest.

## The in-Slicer demonstration (SLIA-027)

Since `SLIA-027` the demonstration runs from one application and no console:

1. Once: `.\scripts\development\build-uc1.ps1`, then
   `.\scripts\development\build-sliaflow.ps1`. Both must exit 0.
   `build-uc1.ps1` applies the UC1 patches recorded in `uc1_changes.md`.
2. Double-click `build\SLIAFlow\SlicerWithSLIAFlow.exe` and open SLIAFlow.
3. Press **Start**. LiveView shows the laptop camera. **Recorded capture**
   shows `S-N-002-04`; choose another of IUMA's captures there if wanted
   (`ADR-0006`). `capture_compatibility.md` says which ones run.
4. Press **Capture**. LiveView freezes and the frame is saved under
   `workspace\captures`. Every Capture runs UC1 on the chosen capture's
   calibrated LCTF cube, `input\S-N-002-04\S-N-002-04` by default (the cube
   recorded as `002-04` before 2026-10-08, `ADR-0004`), mapped onto the 93 bands
   UC1's model was trained for (`SLIA-033`). The status names the recorded cube
   and moves through running UC1 and validating; a run took about 4.6 s from
   Capture to result on 2026-09-25.
5. LiveView resumes. **Delineation output** selects `pca.bmp`, `svm.bmp`,
   `knn.bmp`, `kmeans.bmp` or `imageRGB.bmp`, each at the cube's size (1080 x
   1080 for `S-N-002-04`, 1301 wide by 1080 high for most other captures) and
   shown on its own as UC1 wrote it. The result status reads
   `Recorded cube S-N-002-04 - simulated acquisition` and says that UC1 results
   on this cube are not validated. Say it out loud as well: UC1's model was
   trained on another camera, so the map shows what the pipeline does with the
   LCTF cube, not whether it is right. On `S-N-002-04` most of the tissue in
   view comes out as tumour.
6. `svm.bmp` and `knn.bmp` paint each pixel with its class: green normal
   tissue, red tumour, blue hypervascularized, black background. No capture has
   a labelling to compare them with.
7. HS Cube shows the same cube, and both panels name it: HS Cube reads
   `Recorded cube S-N-002-04, calibrated reflectance`, and Tumour Delineation
   reads `Result for recorded cube S-N-002-04`. Scroll HS Cube to move through the 109
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
| `The configured cube ... cannot be used: ...` | The chosen capture's `LCTF_Calibrated_Cube_Single` is missing (the list then shows it `(not found)`), its header and data file disagree, or its bands are not IUMA's LCTF grid (460-1000 nm in 5 nm steps); the reason follows. See `input\README.txt` and `capture_compatibility.md` |
| `Cube <capture> changed on disk since Capture was pressed` | The cube's header or data file was written to or replaced between Capture and the run, or while it was copied for UC1, even with the same size; press Capture again |
| HS Cube: `The hyperspectral cube could not be shown.` | The same cube could not be read for the panel; the reason follows on the panel, and the status says whether UC1 ran |

To check that the patched UC1 still writes what it wrote on `002-04` (now
`S-N-002-04`) when it was recorded, and that each patch does its job, run
`.\.venv\Scripts\python.exe scripts\development\check-uc1.py` after
`build-uc1.ps1`. It prints `PASS` and exits 0. To check whether a capture,
including one just added to `input\`, runs through UC1 and UC2, run
`.\.venv\Scripts\python.exe scripts\development\check-captures.py`
(`capture_compatibility.md`).
