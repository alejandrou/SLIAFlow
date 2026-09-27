# SLIAFlow

SLIAFlow is the 3D Slicer visualization component of the STRATUM demonstrator.
It runs the prebuilt UC1 pipeline, with documented patches, on IUMA's LCTF cube,
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

1. Build the UC1 binaries once: `scripts\development\build-uc1.ps1`. It applies
   the versioned UC1 patches recorded in `docs\development\uc1_changes.md`.
   SLIAFlow runs `build\uc1\UC1\gpu_single_bsq\source\stratum.opt.intermediate.exe`.
2. Capture reads one cube, IUMA's calibrated LCTF cube
   `input\002-04\LCTF_Calibrated_Cube_Single.hdr` (`ADR-0004`). It is the cube
   HS Cube shows and the cube UC1 runs on. `input\README.txt` describes the rest
   of `input\`.
3. Open SLIAFlow and press **Start**. The laptop camera stands in for the
   acquisition system's LiveView.
4. Press **Capture**. LiveView freezes, the frame is saved as
   `workspace\captures\output_laptop_camera_<date>-<time>.png`, the configured
   cube is checked, and UC1 runs on it in the background (timeout 60 s). UC1's
   model was trained on 93 bands at 440-900 nm, so SLIAFlow first writes the
   cube mapped onto those bands to `build\uc1\UC1\input\002-04\raw.dat`:
   460-900 nm one to one, 440-455 nm from the 460 nm band, 905-1000 nm dropped
   (`SLIAFlowUc1Input.py`; the mapping is described in `uc1_changes.md`).
   Nothing is written into `input\`. The status names the cube and the stage. A
   cube that is missing, inconsistent or not on the LCTF grid is refused with
   its path and the reason, and no run starts.
5. When the run ends, LiveView resumes. On success the five UC1 outputs
   `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp` and `imageRGB.bmp` are
   selectable under **Delineation output**, each shown on its own. The status
   says the results are not validated on this cube (`ADR-0004` decision 5):
   the model was trained on another camera. On failure the previous result
   stays on screen marked `PREVIOUS RESULT - not from the current capture`.
6. **Delineation output** has a sixth entry, `gtMap`, offered only when the
   cube has a `gtMap` pair beside it (`ADR-0004` decision 8). `002-04` has none,
   so the entry is hidden; a `gtMap` selection kept from earlier makes the
   status say the cube has no ground truth. For a cube that has one, it does not
   replace the picture on screen -- it is drawn over the output chosen last, on
   Slicer's Label layer, so the layer's opacity slider and outline toggle work
   on it. Its colours are `FOUR_COLORS_MAP` from the UC1 source, the same table
   `svm.bmp` and `knn.bmp` are painted with: green normal tissue, red tumour,
   blue hypervascularized, black background. Unlabelled pixels are left clear.

   `svm.bmp` and `knn.bmp` are the two outputs a ground truth can be read
   against, because they share that legend. `kmeans.bmp` is painted from
   cluster numbers that carry no fixed meaning, and `pca.bmp` is not a
   classification at all. Nothing computes an accuracy or agreement figure:
   `.ai/policies/medical-data-policy.md` does not approve one, and this
   module only puts the two pictures on top of each other.

Every output is marked `SLIAFlow.DataOrigin = simulated`, names its cube in
`SLIAFlow.RecordedCase`, and carries the detail `real UC1 pipeline, recorded
IUMA LCTF capture 002-04, calibrated by IUMA (simulated acquisition)`: the
pipeline and the cube are real, the acquisition is simulated, and nothing shown
is a clinical result. The Enhanced Vascularization panel is black and says why.

## The HS Cube panel: IUMA's calibrated cube (SLIA-032)

Every Capture also shows the configured cube,
`input\002-04\LCTF_Calibrated_Cube_Single.hdr` and its `.dat` (ENVI float32,
BSQ, 1080 x 1080 x 109, 460-1000 nm), in HS Cube. It is read for the panel
separately from the run. Both panels name it: HS Cube reads
`Recorded cube 002-04, calibrated reflectance`, and Tumour Delineation reads
`Result for recorded cube 002-04`.

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
  little-endian with one nanometre wavelength per band, is neither shown nor
  run. HS Cube says `The hyperspectral cube could not be shown.` with the file
  and the reason, and the status gives the same reason for UC1.

The cube, its preview and the spectrum table carry
`SLIAFlow.DataOrigin = simulated`, `SLIAFlow.RecordedCase = 002-04` and the
detail `recorded IUMA LCTF capture 002-04, calibrated by IUMA (simulated
acquisition)` (`ADR-0004` decision 7).

The staged build's `.uc1-runner.lock` keeps one UC1 run at a time, and a
Capture while the lock is held is refused with the lock path in the message.

## Connections: the acquisition app's ports (SLIA-035)

The **Connections** section connects to IUMA's acquisition app as an
OpenIGTLink client (`ADR-0004` decision 2) and shows, per port, whether it is
connected and what arrives. It only receives: nothing is sent to the app, and
nothing received is shown in the panels or used by Capture yet (`SLIA-030`).

- **Settings**: host (default `127.0.0.1`), the LiveView, Stereo and HS Cube
  ports (18944, 18945 and 18946, as the app serves them; 0 leaves a channel
  out) and the expected bands of one cube (109, as `002-04` has). They can be
  changed only while disconnected.
- **The ports are listed in OpenIGTLinkIF from the start.** As soon as SLIAFlow
  opens, it puts one client connector per configured port in the scene, stopped
  and named `SLIAFlow <channel> (<port>)`, so **IGT > OpenIGTLinkIF** (and the
  Connector list of **IGT > OpenIGTLink Remote**) shows them, off, before
  anything is connected. Changing a port lists them again for the new port.
- **Connect** starts those connectors and becomes **Disconnect**, which stops
  them. Each row shows Port, Channel, State, the Last message (device
  name, message type, size, data type, band and wavelength when the message
  says them, and how long ago it arrived) and what was Received (frames or bands
  per second over the last 5 s; for HS Cube, the bands of the current cube out
  of the expected bands). The line under the table says what the table has no
  room for.
- **States**: `Not connected`; `Waiting for the app`, then `App not running`
  after 3 s, naming the host and port; `Connected` with no message in the last
  2 s; `Receiving`; for HS Cube, `Cube complete` or `Cube incomplete` with the
  missing band numbers once nothing has arrived for 10 s; `Error` with its
  reason. A row whose messages say `SLIAFlow.DataOrigin = simulated` adds
  `(stand-in)`.
- **A new connection starts empty.** When the app, or the stand-in, stops and
  a sender connects to the port again, the row forgets the previous
  connection: its state, bands and `(stand-in)` mark do not carry over.
  OpenIGTLinkIF copies a message's metadata onto its node but never removes a
  key a later message leaves out, so when a connection is lost SLIAFlow removes
  the `OpenIGTLink.SLIAFlow.*` band and origin attributes from the nodes it
  received. The last image stays on its node without them.
- **Bands** are counted as they reach Slicer. OpenIGTLinkIF keeps a buffer of 3
  per device name and reads it every 5 ms, so bands arriving faster than that
  can be lost before SLIAFlow sees them; the count shows it. Missing bands are
  named only when each message says which band it is; otherwise the line says
  they cannot be named. A new cube starts when a band number repeats, after 10 s
  of silence, or, without band numbers, after a full count.
- **Open in OpenIGTLinkIF** opens Slicer's own view of the connectors and every
  device they received; **IGT > OpenIGTLinkIF** in the Modules menu is the same
  module. Leaving SLIAFlow for any module leaves the connections as they are:
  they stay connected until **Disconnect**.
- **What a connection received does not stay.** Disconnect, closing the scene,
  Reload and quitting Slicer stop the connectors and remove the nodes they
  created. A node that existed before Connect is kept. Closing the scene and
  Reload also replace the connectors with new, stopped ones; quitting removes
  them.
- A connector switched on from OpenIGTLinkIF's own Active checkbox while
  SLIAFlow is disconnected is not followed by the rows; **Connect** takes it
  over.
- **Disconnecting can pause Slicer** for up to about 2 s per port while the app
  is not running: OpenIGTLink's `Stop()` waits for the connection attempt in
  progress, and Windows takes about 2 s to refuse one to a closed local port.
  With the app running it takes a fraction of a second.
- When a device's first image arrives, Slicer logs one warning that the image
  geometry is not the identity; it comes from OpenIGTLinkIF, once per received
  device, not once per message.
- The laptop camera volume is named `Laptop camera`, so that no connector can
  take it for the app's `LiveView` device.

Without IUMA's app, use the stand-in in `tools\simulators` (it says it is a
stand-in in everything it prints and sends):

```powershell
cd tools\simulators
..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin
```

`--drop-bands 5,17,80-84` leaves bands out, to see them named as missing.
`tools\simulators\README.md` lists what the stand-in assumes about the real
app.
