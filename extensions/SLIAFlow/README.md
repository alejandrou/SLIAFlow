# SLIAFlow

SLIAFlow is the 3D Slicer visualization component of the STRATUM demonstrator.
It runs the prebuilt UC1 pipeline and the UC2 blood-vessel enhancement, each with
documented patches, on IUMA's LCTF cube, shows the images they write, and shows
IUMA's calibrated LCTF cube band by band.
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
is a clinical result.

## The Enhanced Vascularization panel: UC2 (SLIA-021)

Every Capture also runs the vendored UC2 blood-vessel enhancement on the same
cube, in the background beside UC1, and shows its map in Enhanced
Vascularization.

1. Build UC2 once: `scripts\development\build-uc2.ps1`. It applies the
   versioned UC2 patches recorded in `docs\development\uc2_changes.md` and
   builds `build\uc2\source\uc2_bvmap.exe` with the MSYS2 GCC
   (`docs\development\uc2_local_build.md`).
2. Capture gives UC2 the cube's folder, `input\002-04`. UC2 reads only the three
   bands at 480, 540 and 710 nm from `LCTF_Calibrated_Cube_Single.dat`, applies
   its own fixed parameters (`high_in 0.15`, `high_out 0.8`, `gamma 1`,
   `bValue 3`) and writes `build\uc2\run\002-04-BVMap.png`. Nothing is written
   into `input\`. A cube with other file names, or whose bands 4, 16 and 50 are
   not 480, 540 and 710 nm, is refused before UC2 starts.
3. The map is shown alone, named `002-04-BVMap.png`, with the caption
   `Enhanced vascularization for recorded cube 002-04`. The last line of the
   Status section says how it was made: the fixed bands and parameters, that it
   is a display enhancement whose colours are rescaled within each image and are
   not comparable between captures, and that it is not validated.
4. UC2 and UC1 are independent. One failing, being refused or not being built
   does not stop the other or change its panel. The panel then says
   `The enhanced vascularization could not be computed.` and the Status line
   gives the reason. LiveView resumes once both have finished.
5. A new Capture takes the previous map down until its own arrives; a map is
   never kept from an earlier capture.

The map node carries `SLIAFlow.DataOrigin = simulated`,
`SLIAFlow.RecordedCase = 002-04`, the detail `real UC2 blood-vessel
enhancement, recorded IUMA LCTF capture 002-04, calibrated by IUMA (simulated
acquisition)` and `SLIAFlow.Uc2Parameters` with the fixed bands and
parameters. `build\uc2\.uc2-runner.lock` keeps one UC2 run at a time.

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
connected and what arrives. It only receives: nothing is sent to the app. The
HS cube it receives is shown in HS Cube and can be captured on (`SLIA-036`,
below); LiveView and Stereo frames are not shown in a panel yet (`SLIA-037`).

- **Settings**: host (default `127.0.0.1`), the LiveView, Stereo and HS Cube
  ports (18944, 18945 and 18946, as the app serves them; 0 leaves a channel
  out) and the expected bands of one cube (109, as `002-04` has). They can be
  changed only while disconnected.
- **The ports are listed in OpenIGTLinkIF from the start.** As soon as SLIAFlow
  opens, it puts one client connector per configured port in the scene, stopped
  and named `SLIAFlow <channel> (<port>)`, so **IGT > OpenIGTLinkIF** (and the
  Connector list of **IGT > OpenIGTLink Remote**) shows them, off, before
  anything is connected. Changing a port lists them again for the new port.
- **Connect** starts the LiveView and Stereo connectors and becomes
  **Disconnect**, which stops them. The HS Cube connector stays listed but is
  never started: the app serves one client per port, and SLIAFlow reads that
  port itself (below). If it is switched on in OpenIGTLinkIF while SLIAFlow is
  connected, SLIAFlow stops it after a second and the line under the table
  says so. The second is needed because the connector's `Stop()` never
  returns if it is called just as the connector connects. Each row
  shows Port, Channel, State, the Last message (device name, message type,
  size, data type, band number, the wavelength when the message says it, and
  how long ago it arrived) and what was Received (frames or bands per second
  over the last 5 s; for HS Cube, the bands of the current cube out of the
  bands the messages declare, or the Expected bands setting before the first
  one). The line under the table says what the table has no room for.
- **States**: `Not connected`; `Waiting for the app`, then `App not running`
  after 3 s, naming the host and port; `Connected` with no message in the last
  2 s; `Receiving`; for HS Cube, `Cube complete` or `Cube incomplete` with the
  missing band numbers once nothing has arrived for 10 s or the sender left;
  `Error` with its reason, for HS Cube a message it refused. A row whose
  messages say `SLIAFlow.DataOrigin = simulated` adds `(stand-in)`.
- **A new connection starts empty.** When the app, or the stand-in, stops and
  a sender connects to the port again, the row forgets the previous
  connection: its state, bands and `(stand-in)` mark do not carry over.
  OpenIGTLinkIF copies a message's metadata onto its node but never removes a
  key a later message leaves out, so when a connection is lost SLIAFlow removes
  the `OpenIGTLink.SLIAFlow.*` band and origin attributes from the nodes it
  received. The last image stays on its node without them.
- **The HS cube is read by SLIAFlow itself** (`SLIA-036`). The app sends one
  IMAGE per band that declares the whole cube and carries the band as a
  sub-volume at offset (0, 0, band - 1), header version 1, no metadata
  (`docs/hardware/acquisition_app_and_hardware.md` section 4.1). OpenIGTLinkIF
  would assemble these into one volume without saying which band arrived, and
  keeps only 3 messages per device, read on Slicer's main thread. So a reader
  thread of SLIAFlow's own is the port's client: it reads every message whole,
  checks its CRC-64, and puts each band at its offset in the cube's own buffer.
  - It takes only single-component uint16 or float32 IMAGE messages that carry
    one whole band. Anything else, a bad CRC, a stand-in band number that
    disagrees with the offset, a version or byte order OpenIGTLink does not
    define, or an image with no pixels, is refused by name and leaves the
    cube alone.
  - A cube is complete once it holds every band, in any order. A band it
    already holds starts the next cube; so does a change of size or type, which
    ends the current one as incomplete. After connecting in mid-cube, a band
    missed by connecting late that arrives after the cube's last band also
    starts the next cube, so bands of two captures are never put together. A
    cube that gets no band for 10 s, or
    whose sender leaves, is incomplete: its missing bands are named, bands
    missed by connecting late say so, and it is thrown away. When the sender
    leaves, the row names them while it waits for the app again. Only complete
    cubes are shown or used.
  - The reader must keep up: a sender gives up a send that takes too long
    (pyigtl, in the stand-in, after 10 ms) and closes the connection. Slicer's
    main thread keeps Python's GIL while it is idle, so while connected it
    sleeps 10 ms each time it has nothing else to do, which lets the reader
    run. A full-size calibrated cube then arrives at the app's pace, and the
    window keeps responding. Python running on the main thread hands the GIL
    over by itself. A long call into Slicer's C++ code does not, and a cube
    arriving meanwhile may be cut off and reported incomplete. SLIAFlow then
    reconnects, possibly in the middle of the next cube, and throws a cube it
    joined in mid-cube away too, so one cut-off can cost up to two cubes.
- **Open in OpenIGTLinkIF** opens Slicer's own view of the connectors and every
  device they received; **IGT > OpenIGTLinkIF** in the Modules menu is the same
  module. Leaving SLIAFlow for any module leaves the connections as they are:
  they stay connected until **Disconnect**.
- **What a connection received does not stay.** Disconnect, closing the scene,
  Reload and quitting Slicer stop the connectors and the HS Cube reader, and
  remove the nodes they created and the received cube. A node that existed
  before Connect is kept. Closing the scene and Reload also replace the
  connectors with new, stopped ones; quitting removes them.
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
`--app-header` sends the cube exactly as the app does, without the stand-in's
metadata, so SLIAFlow cannot tell it from the app. `--cube` also takes a uint16
cube, such as `002-04`'s raw cube. `tools\simulators\README.md` lists what the
stand-in assumes about the real app.

### The cube from the app in HS Cube and Capture (SLIA-036)

**Cube source** chooses the cube HS Cube shows and Capture uses:

- **Cube on disk** (the default): the configured calibrated cube, `002-04`, as
  before.
- **Last cube from the app**: the last complete cube received on the HS Cube
  port. HS Cube shows it as soon as it completes, with its bands, colour
  preview and pixel spectrum, keeping its received type. Until one arrives the
  panel says it is waiting for a complete cube from the app.
  - The caption says the cube was received from the app, or from the
    stand-in. A uint16 cube is captioned as raw counts, uncalibrated; its
    preview is scaled to its own brightest count and its spectrum is labelled
    as raw counts.
  - The app sends no wavelengths. A 109-band cube is given the LCTF grid,
    460-1000 nm in 5 nm steps, and the node and the caption say the grid is
    assumed. A cube with another band count has no wavelengths: its caption
    gives the band number only, and it is shown but not classified.
  - The volume has SLIAFlow's own geometry: the app's spacing 1 and centred
    origin carry no physical information.
- **Capture on the cube from the app.** With no complete cube received,
  Capture is refused before anything is frozen or saved.
  - On a float32 109-band cube, Capture writes the cube once, as an ENVI
    float32 cube under the names UC2 reads, to the gitignored
    `workspace\received-cube\received-from-app` folder, which the next such
    Capture overwrites. UC1 and UC2 then run on it exactly as on the cube on
    disk, and HS Cube keeps showing the received cube.
  - On a uint16 cube, UC1 and UC2 do not run. The status and Enhanced
    Vascularization say they wait for IUMA's calibrated float32 stream: SLIAFlow
    does no calibration of its own.
  - On a cube with another band count, UC1 and UC2 are refused, because it has
    no wavelengths to map.
  - A cube completed while a capture runs is held and shown when the capture
    ends. Only the latest one is held.
- **Provenance.** A received cube, and the UC1 and UC2 outputs of a capture on
  it, carry `SLIAFlow.DataOrigin = received`. The detail names the host and
  port, the reception time, that IUMA's AcquisitionSystemApp serves its HS cube
  there, and that the sender may have captured it live or replayed a stored
  cube, which SLIAFlow cannot tell apart. Stand-in data, whose messages say
  `SLIAFlow.DataOrigin = simulated`, stays `simulated`.
- **Memory.** A cube is assembled straight into the image its volume then uses.
  Outside a capture, the peak is the cube on screen plus the one being
  received: 3.9 GB for two raw 4096 x 2160 x 109 cubes. During a capture on a
  received float32 cube, a held cube can add a third: 1.5 GB for three
  1080 x 1080 x 109 float32 cubes. A capture on a raw cube ends at once, so a
  raw cube is held only while a float32 capture runs, which peaks at 4.4 GB.
  Disconnect, scene close, Reload and quit remove the received cube, any held
  one, and the cube written for a run. A run cube still in use is removed when
  its capture ends.
