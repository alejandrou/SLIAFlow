# SLIAFlow

SLIAFlow is the 3D Slicer visualization component of the STRATUM demonstrator.
It runs the prebuilt, unmodified UC1 pipeline on recorded public HSI cases,
shows the images UC1 writes, and shows IUMA's calibrated LCTF cube band by band.
It provides no diagnostic interpretation or clinical decision support.

SLIAFlow is prototype software. It is not clinically validated and must not be
used with private or identifiable patient data.

See the repository-level `README_SLIAFlow_Build.md` for the supported local
Windows build, test, and launch procedure.

## Capture and UC1 run inside Slicer

Since `SLIA-027` (`docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`)
the built launcher `build\SLIAFlow\SlicerWithSLIAFlow.exe` runs the whole
workflow by itself. No console, Python service or OpenIGTLink link is involved.

1. Build the UC1 binaries once: `scripts\development\build-uc1.ps1`. SLIAFlow
   runs `build\uc1\UC1\gpu_single_bsq\source\stratum.opt.intermediate.exe`.
2. Capture reads one cube folder, `input\reference_hsi_brain_db\020-01`: a
   recorded case of the HSI Human Brain Database kept as the UC1 reference
   (`ADR-0004`). `input\README.txt` describes the rest of `input\`.
3. Open SLIAFlow and press **Start**. The laptop camera stands in for the
   acquisition system's LiveView.
4. Press **Capture**. LiveView freezes, the frame is saved as
   `workspace\captures\output_laptop_camera_<date>-<time>.png`, the configured
   cube is checked, and UC1 runs on it in the background (timeout 60 s). The
   status names the case and the stage. A cube folder that is missing or
   inconsistent is refused with the folder and the reason, and no run starts.
5. When the run ends, LiveView resumes. On success the five UC1 outputs
   `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp` and `imageRGB.bmp` are
   selectable under **Delineation output**, each shown on its own. On failure
   the previous result stays on screen marked
   `PREVIOUS RESULT - not from the current capture`.
6. **Delineation output** has a sixth entry, `gtMap`: the recorded case's own
   labelling from the HSI Human Brain Database. It does not replace the
   picture on screen -- it is drawn over the output chosen last, on Slicer's
   Label layer, so the layer's opacity slider and outline toggle work on it.
   Its colours are `FOUR_COLORS_MAP` from the UC1 source, the same table
   `svm.bmp` and `knn.bmp` are painted with: green normal tissue, red tumour,
   blue hypervascularized, black background. Unlabelled pixels are left
   clear, because most of a recorded case is unlabelled.

   `svm.bmp` and `knn.bmp` are the two outputs the ground truth can be read
   against, because they share that legend. `kmeans.bmp` is painted from
   cluster numbers that carry no fixed meaning, and `pca.bmp` is not a
   classification at all. Nothing computes an accuracy or agreement figure:
   `.ai/policies/medical-data-policy.md` does not approve one, and this
   module only puts the two pictures on top of each other.

Every output is marked `SLIAFlow.DataOrigin = simulated` and names its recorded
case: the pipeline and the cube are real, the acquisition is simulated, and
nothing shown is a clinical result. The Enhanced Vascularization panel is black
and says why.

## The HS Cube panel: IUMA's calibrated cube (SLIA-032)

Every Capture also reads IUMA's calibrated LCTF cube,
`input\002-04\LCTF_Calibrated_Cube_Single.hdr` and its `.dat` (ENVI float32,
BSQ, 1080 x 1080 x 109, 460-1000 nm), and shows it in HS Cube. It is shown
whether or not UC1 can run. Until `SLIA-033` UC1 still runs on the reference
case, so the two panels name their own cube: HS Cube reads
`Recorded cube 002-04, calibrated reflectance`, and Tumour Delineation reads
`Result for recorded case 020-01`.

- **Bands.** The cube opens at its middle band. Scroll the panel to change band.
  The caption gives the band and its wavelength, for example
  `Band 39 of 109 - 650 nm`. The stored float32 values are shown unchanged;
  window and level are display settings only.
- **Colour preview.** Set **HS Cube shows** to **Colour preview** to see the
  bands nearest 650, 550 and 470 nm as red, green and blue. All three use one
  fixed scale: reflectance 0 is black and 1.0 or more is full brightness. The
  caption names the three wavelengths and says it is a band composite, not a
  photograph.
- **Pixel spectrum.** Click a pixel of HS Cube, in either view, and the
  **Pixel spectrum** section plots that pixel's stored values against
  wavelength (nm). The line under the plot names the cube and the pixel. It is
  the cube's own numbers, not an analysis. A left drag also changes the window
  and level, as it does on any slice view, so click without dragging.
- A cube whose header and data file disagree, or which is not float32 BSQ
  little-endian with one nanometre wavelength per band, is not shown. HS Cube
  says `The hyperspectral cube could not be shown.` with the file and the
  reason, and the capture carries on.

The cube, its preview and the spectrum table carry
`SLIAFlow.DataOrigin = simulated`, `SLIAFlow.RecordedCase = 002-04` and the
detail `recorded IUMA LCTF capture 002-04, calibrated by IUMA (simulated
acquisition)` (`ADR-0004` decision 7).

The staged build's `.uc1-runner.lock` keeps one UC1 run at a time, and a
Capture while the lock is held is refused with the lock path in the message.
