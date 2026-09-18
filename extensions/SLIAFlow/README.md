# SLIAFlow

SLIAFlow is the 3D Slicer visualization component of the STRATUM demonstrator.
It runs the prebuilt, unmodified UC1 pipeline on recorded public HSI cases and
shows the images UC1 writes. It provides no diagnostic interpretation or
clinical decision support.

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
2. Put the HSI Human Brain Database cases under `input\bin\bin`.
3. Open SLIAFlow and press **Start**. The laptop camera stands in for the
   acquisition system's LiveView.
4. Press **Capture**. LiveView freezes, the frame is saved as
   `workspace\captures\output_laptop_camera_<date>-<time>.png`, a compatible
   recorded case is picked from a shuffled pool, and UC1 runs on it in the
   background (timeout 60 s). The status names the case and the stage.
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
nothing shown is a clinical result. Case `058-02` is deferred until `SLIA-029`.
The HS Cube panel shows the recorded cube the capture stands for, opened at
its middle band; the Enhanced Vascularization panel is black and says why.

`tools\simulators` and the session scripts still exist until `SLIA-028`. They
use the same staged build; `.uc1-runner.lock` keeps one run at a time, and a
Capture while the lock is held is refused with the lock path in the message.
