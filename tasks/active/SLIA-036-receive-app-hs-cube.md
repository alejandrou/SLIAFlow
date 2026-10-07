---
id: SLIA-036
title: Receive the HS cube from IUMA's acquisition app, show it and capture on it
status: active
branch: feature/SLIA-036-receive-app-hs-cube
priority: medium
depends_on: SLIA-030, SLIA-035, SLIA-033, SLIA-021
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-036 - Receive the HS cube from IUMA's acquisition app, show it and capture on it

## Goal

SLIAFlow receives the cube IUMA's acquisition app sends on its HS Cube port,
assembles it band by band, shows it in the HS Cube panel, and lets the operator
press Capture on it as on the cube read from disk. A raw uint16 cube is shown
but not classified. The calibrated float32 cube runs UC1 and UC2.

## Context

*Created on 2026-10-06 from `SLIA-030` phase B*, which was finalised on
2026-09-27 from the measurement but never implemented (`SLIA-030` front note).
LiveView from the app, also part of that phase B, is `SLIA-037`.

Measured on 2026-09-27 (`docs/hardware/acquisition_app_and_hardware.md`
section 4.1, `SLIA-030` completion evidence):

- `HsCube` on 18946 sends header version 1, no metadata, header timestamp 0.
- Every IMAGE declares the whole cube (4096 x 2160 x 109 for the raw cube) and
  carries one band as the sub-volume (samples, lines, 1) at offset
  (0, 0, band - 1). Offset k + 1 matched disk band k + 1, as stored.
- Single component, uint16 little endian today. IUMA will send the calibrated
  float32 cube with the same structure (`SLIA-030` context).
- No message marks the end of a cube. A client that joined late missed band 1.
- The app sent 8.8 bands/s (157 MB/s) on the loopback.

What SLIAFlow does today (`SLIA-035`):

- An OpenIGTLinkIF client connector per port. On 18946, OpenIGTLinkIF assembles
  the slabs into one volume that it never clears, does not say which band
  arrived, and keeps only 3 messages per device, emptied on the main thread.
- `ChannelMonitor` names a band only from the stand-in's
  `SLIAFlow.BandNumber` metadata. With the real app it counts bands but cannot
  name them or the missing ones.
- Nothing received is shown in a panel or used by Capture.
- The stand-in sends each band as a one-slice version 2 image with invented
  metadata, which the real app does not (review finding, 2026-10-06).

### Owner decisions

From `SLIA-030` (2026-09-27), unchanged:

1. A received uint16 cube is assembled and shown, but not classified: SLIAFlow
   does no white/dark calibration (`ADR-0004`). Capture on it says UC1 waits for
   IUMA's calibrated float32 stream.
2. Provenance (`ADR-0004` decision 7): a received cube has
   `SLIAFlow.DataOrigin = received`. The detail names the host and port, the
   reception time, that IUMA's AcquisitionSystemApp serves its HS cube there,
   and that the sender may have captured it live or replayed a stored cube,
   which SLIAFlow cannot tell apart. Data whose messages carry
   `SLIAFlow.DataOrigin = simulated` (the stand-in) stays `simulated`.

Added on 2026-10-06, when this card was split off:

3. **UC1 and UC2 input.** Capture on a received float32 cube writes it once,
   as an ENVI float32 cube under the names UC2 reads, into a gitignored
   `workspace` folder that the next such Capture overwrites. UC1, UC2 and the
   checks they make then run unchanged.
4. **The HS Cube connector stays listed, never started.** OpenIGTLinkIF keeps
   showing all three ports (`SLIA-035`), but Connect does not start the HS Cube
   connector: SLIAFlow's own reader is the port's one client.
5. **LiveView from the app** is a separate card, `SLIA-037`.

## Requirements

### The reader

- New module `SLIAFlowReceivedCube.py`. It does not import `slicer`, so its
  parsing and assembly are tested without the scene.
- `HsCubeReader` is a socket thread that connects to host:port as the port's
  one client and retries every second while the port refuses. It reads every
  message whole, header version 1 or 2, and checks its CRC-64 (the OpenIGTLink
  polynomial, ECMA-182). It never touches MRML. The main thread polls it from
  the Connections timer.
- **Accepted:** a single-component uint16 or float32 IMAGE whose sub-volume is
  one whole band, (samples, lines, 1) at offset (0, 0, k) with k below the
  declared band count. Anything else is refused by name in the HS Cube row and
  leaves the cube being assembled untouched. This covers a bad CRC, another
  message type, more than one component, another scalar type, another
  sub-volume or a pixel count that disagrees with it. It also covers what
  OpenIGTLink does not define (verification, 2026-10-06): a header version
  other than 1 or 2, an image header version other than 1, a byte order code
  other than 1 (big endian) or 2 (little endian), and an image with no pixels.
- **The GIL.** Slicer's main thread keeps Python's GIL while it waits in Qt's
  event loop, so the reader would run only when the main thread runs Python.
  While the reader runs, the main thread sleeps 10 ms (`GIL_YIELD_SEC`)
  whenever its event loop has nothing else to do, which hands the GIL to the
  reader (verification, 2026-10-06).
- **Band identity.** Band = offset k + 1, of `size[2]` bands. A message that
  also carries `SLIAFlow.BandNumber` (the stand-in, version 2) is refused when
  it disagrees with the offset.
- **Cube boundaries.**
  - A cube is complete as soon as it holds every offset from 0 to
    `size[2] - 1`, in any order.
  - A new cube starts with an offset the current cube already holds.
  - On a connection that joined in mid-cube, a band that connection missed,
    arriving once the cube holds its last band and before any other missed
    band, is the next cube starting. It ends the current cube as incomplete
    and starts a new one, so two captures are never put together as one cube
    (found 2026-10-07: before, the next cube's first bands filled the gaps and
    the mixed cube was reported complete). A cube sent in order always ends
    this way. One sent out of order that cannot be told from it (its last
    band before every missed band) is thrown away, never mixed; other orders
    still complete.
  - The note that the previous cube was incomplete stays while the next cube
    is received, not only for its first band.
  - A size or scalar type that changes in mid-cube ends that cube as
    incomplete, saying so, and starts a new cube with the message.
  - A cube that gets no band for 10 s (`CUBE_IDLE_SEC`), or whose sender
    disconnects, is incomplete. Its missing bands are named, for example
    `Missing bands: 1 (connected after the capture started)` when the first
    band received since connecting was not band 1. It is thrown away. Only a
    complete cube is ever shown or used.
- **Memory.** Each cube is assembled in place in a buffer allocated once at its
  first band. In Slicer that buffer is the `vtkImageData` the volume node will
  use, so a completed cube is handed over without a copy. Outside a capture,
  the peak is the cube on screen plus the one being assembled (3.9 GB for two
  raw cubes, 1.0 GB for two 1080 x 1080 x 109 float32 cubes). During a capture
  on a received float32 cube, a held cube adds a third (1.5 GB for three
  float32 cubes). A capture on a raw cube ends at once, so a raw cube is held
  only during a float32 capture (4.4 GB peak). Owner decision of 2026-10-06,
  after review: keep holding rather than replace or skip a cube. An incomplete
  cube's buffer is freed when it is thrown away.

### Connections

- The HS Cube row is fed by the reader. The LiveView and Stereo rows keep
  their `SLIA-035` connectors.
- The row shows the states of `SLIA-035`: received bands over the band count
  the messages declare (the Expected bands setting until the first band), the
  rate, the last message with its band number, `Cube complete`,
  `Cube incomplete` with the missing bands, and `Error` with the refusal. Data
  marked simulated shows ` (stand-in)`.
- When the sender leaves with a cube half received, the row waits for the app
  again and still names the missing bands.
- The HS Cube connector stays listed and stopped. Connect stops it if it was
  started in OpenIGTLinkIF. If it is started while SLIAFlow is connected,
  SLIAFlow stops it after one second, and the row says why. The delay avoids
  OpenIGTLinkIO's `Stop()` race (Review findings).

### HS Cube panel and Capture

- A **Cube source** choice, saved in the parameter node: `Cube on disk` (the
  default, today's behaviour) or `Last cube from the app`.
- With `Last cube from the app`:
  - HS Cube shows the last complete received cube as soon as it completes, with
    its bands, colour preview and pixel spectrum, keeping its received type.
    With none yet, the panel says it is waiting for a complete cube from the
    app.
  - The caption says the cube was received from the app.
  - A uint16 cube is captioned as raw, uncalibrated counts. Its preview is
    scaled to its own maximum, and its spectrum is labelled as raw values.
  - A 109-band cube gets the LCTF grid (460-1000 nm in 5 nm steps). The node
    and the caption say the grid is assumed, not received. A cube with any
    other band count has no wavelengths: its caption gives the band number
    only, and it is shown but not classified.
  - The volume's geometry is SLIAFlow's own, as for the cube read from disk.
    The app's spacing 1 and centred origin carry no physical information.
- Capture with `Last cube from the app`:
  - With no complete received cube, Capture is refused before anything is
    frozen or saved, and the status says why.
  - On a float32 109-band cube, the cube is written as in owner decision 3
    (temporary name, then renamed). UC1 and UC2 run on it exactly as on the
    cube read from disk, and HS Cube keeps showing the received node, without
    reading it back.
  - On a uint16 cube, UC1 and UC2 do not run. The status and the Enhanced
    Vascularization panel say they wait for IUMA's calibrated float32 stream.
  - On a float32 cube with another band count, UC1 and UC2 are refused,
    saying the cube has no wavelengths to map.
- While a capture runs, a newly completed cube is held and shown when the
  capture ends. Only the latest one is held.
- With `Cube on disk`, Capture and HS Cube behave as before.

### Provenance

- The received cube node, its preview and spectrum, and the UC1 and UC2 outputs
  of a capture on it carry the origin and detail of owner decision 2. A UC1 or
  UC2 output's detail starts with the producer, as today.
- Stand-in data, whose messages say `SLIAFlow.DataOrigin = simulated`, keeps
  `simulated` with the stand-in's own detail.
- The Tumour Delineation and Enhanced Vascularization texts describe the cube
  their own result came from. A later capture on another cube does not change
  them.

### Lifetime

- Disconnect, scene close, module cleanup (Reload) and application quit stop
  and join the reader. They also remove the received cube node, any cube held
  during a capture, the assembly buffer, and the written run cube. A run cube
  that a capture is still using is removed when that capture ends.
- A newly completed cube replaces the previous received node, which is freed.

### The stand-in and the transport follow the measured protocol

- `igtl_transport.buildImageSlabMessage` packs one band as the sub-volume of a
  declared whole cube, header version 1 or 2, with a given timestamp.
  `ImageStreamServer.sendImageSlab` sends it. pyigtl 2.2.6 always packs a
  sub-volume as the full image, so it is hand-packed.
- The stand-in sends every HsCube band that way. By default it uses header
  version 2 with its metadata, so its data stays marked `simulated`.
  `--app-header` sends header version 1, no metadata and timestamp 0, exactly
  like the app.
- The stand-in's `--cube` also accepts an ENVI uint16 cube (data type 12), so
  that `002-04`'s raw cube can be sent as the app sends it today.
- Its tests check the measured form (whole-cube size, nonzero offsets, v1
  without metadata) with the recorder's parser. Its old one-slice expectation
  is replaced. This answers the 2026-10-06 review's stand-in finding.
- A recorder test checks a message with the app's geometry: whole-cube size,
  a nonzero band offset and timestamp 0. This answers the review's recorder
  finding.

## Out of scope

- LiveView or stereo frames from the app in a panel (`SLIA-037`).
- Sending anything to the app.
- White/dark calibration in SLIAFlow.
- A history of received cubes, or saving one other than the run cube of owner
  decision 3.
- Retiring `allowSharedPort` and `prepareFrameForWire` (`SLIA-009`).
- PLUS (`ADR-0004` decision 9).

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowReceivedCube.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowConnections.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCalibratedCube.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/README.md`
- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/stratum_sim/iuma_app_standin.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_igtl_transport.py`
- `tools/simulators/tests/test_iuma_app_standin.py`
- `tools/simulators/tests/test_igtl_recorder.py`
- `tools/simulators/README.md`
- `docs/development/openigtlink_setup.md`
- `docs/hardware/acquisition_app_and_hardware.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/active/SLIA-036-receive-app-hs-cube.md`

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1 -Configure` and never edited by hand.

## Relevant skills and references

- Slicer skill: `vtkMRMLScalarVolumeNode`, `vtkImageData`, slice composite
  nodes, `qMRMLPlotWidget`.
- OpenIGTLink version 1 and 2 header and IMAGE layout, as parsed by
  `tools/simulators/stratum_sim/igtl_recorder.py`, which read the real app.
- CRC-64/ECMA-182: polynomial 0x42F0E1EBA9EA3693, initial value 0, not
  reflected, no final XOR; check value 0x6C40DF5F0B497347 for `123456789`.
  The OpenIGTLink library's `igtl_crc64` is not exported by the pinned
  `OpenIGTLink.dll`, and Slicer's Python has no CRC-64. The reader therefore
  computes it with numpy. A prototype checked a 17.7 MB band in about 90 ms
  against the app's 113 ms per band, and agreed with pyigtl's `CRC64`.
- `tasks/completed/SLIA-030-external-openigtlink-links.md` (measurement, owner
  decisions), `tasks/completed/SLIA-035-connections-panel.md`.
- `docs/hardware/acquisition_app_and_hardware.md` section 4.1.

## Implementation plan

1. Simulators, tests first: the slab message and the stand-in's measured form.
   Then `buildImageSlabMessage`, `sendImageSlab`, the stand-in's
   `--app-header` and uint16 cubes, and the recorder test.
2. `SLIAFlowTest`, tests first: CRC, message parsing, assembly, boundaries,
   refusals, and the reader against the stand-in.
3. `SLIAFlowReceivedCube.py`: CRC-64, the parser, `CubeAssembler` and
   `HsCubeReader`.
4. `SLIAFlowConnections.py`: the HS Cube channel on the reader; `ChannelMonitor`
   takes its cube progress from the assembler; the connector is listed, never
   started.
5. Logic and widget: the cube source setting, the received cube node, panel
   and captions, Capture on a received cube, the run cube in `workspace`, and
   provenance and lifetime.
6. Documentation; `build-sliaflow.ps1 -Configure`; quality checks, simulator
   tests and Slicer tests, headless and headful.

## Acceptance criteria

1. **Parsing.** The reader checks the OpenIGTLink CRC-64 and reads header
   versions 1 and 2. It accepts only a single-component uint16 or float32 IMAGE
   whose sub-volume is one whole band of the declared cube. It refuses anything
   else by name, including a `SLIAFlow.BandNumber` that disagrees with the
   offset, an undefined byte order or version, and an image with no pixels,
   and leaves the cube being assembled untouched.
2. **Assembly.** A cube is assembled by sub-volume offset in any order of
   arrival. The result equals the bands sent, uint16 or float32, from header
   version 1 without metadata or version 2 with it.
3. **Boundaries.**
   - A cube is complete once it holds every offset.
   - A repeated offset starts a new cube. A size or type change ends the
     current cube as incomplete and starts a new one.
   - After a connection that joined in mid-cube, the next cube's bands never
     complete the cube it joined, and the next cube received from its first
     band completes.
   - Silence of 10 s, or a disconnection, makes a partial cube incomplete. Its
     missing bands are named, including bands missed by a late connection, and
     it is never shown.
4. **Pace.** At the stand-in's pace of at least 8.8 bands/s, no band is lost
   while the main thread is busy for 2 s. A cube of 1 MB bands sent without
   pause arrives whole while the main thread waits in Qt's event loop, as
   Slicer does when idle.
5. **Connections.**
   - The HS Cube row follows the reader: received over declared bands, rate,
     last message with its band, complete, incomplete with missing bands,
     error with the refusal, and the stand-in mark.
   - A sender that leaves mid-cube still has the missing bands named while
     the row waits.
   - LiveView and Stereo are unchanged.
   - The HS Cube connector is listed but never started. One started in
     OpenIGTLinkIF is stopped, and the row says why.
6. **Panel.** With `Last cube from the app`, HS Cube shows the last complete
   received cube with its bands, preview and spectrum.
   - The caption says received; uint16 is captioned raw and uncalibrated.
   - 109 bands get the assumed LCTF grid, captioned as assumed. Another band
     count gets no wavelengths.
   - With no complete cube, the panel says it is waiting.
7. **Capture.**
   - On a received float32 109-band cube, the run cube is written to
     `workspace`, and UC1 and UC2 run and show their results.
   - On uint16, nothing runs, and the status and the vascular panel say why.
   - Without a complete cube, Capture is refused before anything is frozen.
   - On another band count, UC1 and UC2 are refused.
   - With `Cube on disk`, Capture behaves as before.
8. **Provenance.** The received cube and the UC1 and UC2 outputs of a capture on
   it carry `DataOrigin = received` and the detail of owner decision 2. Stand-in
   data stays `simulated`. A shown result keeps the origin of its own cube
   after a later capture.
9. **Lifetime.**
   - Disconnect, scene close, cleanup and quit stop the reader. They remove
     the received node, the held cube, the buffers and the run cube; a run
     cube still in use is removed when its capture ends.
   - A completed cube replaces and frees the previous one.
   - A cube completed during a capture is shown when the capture ends.
10. **Stand-in and transport.**
    - `buildImageSlabMessage` packs the measured form. The recorder's parser
      reads it back, and a real OpenIGTLinkIF connector assembles it into the
      cube.
    - The stand-in sends that form: version 2 with metadata by default, and
      with `--app-header` version 1 without metadata and timestamp 0. It sends
      a uint16 cube as uint16.
11. **Recorder.** A message with the app's geometry is recorded with its
    whole-cube size, nonzero offset and timestamp 0.
12. **Real app.** The app's raw cube is received whole, shown, and refused for
    UC1. A late connection names the missed band.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Parsing | `SLIAFlowTest.test_receivedCubeCrcIsTheOpenIGTLinkCrc64`, `test_receivedCubeMessageIsParsedInBothHeaderVersions`, `test_receivedCubeRefusesBadMessages` | automated |
| 2 Assembly | `SLIAFlowTest.test_receivedCubeAssemblesBandsByOffset`, `test_receivedCubeFromTheStandInInBothHeaderVersions` | automated |
| 3 Boundaries | `SLIAFlowTest.test_receivedCubeStartsANewCube`, `test_receivedCubeNamesMissingBands`, `test_receivedCubeLateConnectionMissesFirstBand`, `test_receivedCubeLateConnectionNeverMixesTwoCubes` | automated |
| 4 Pace | `SLIAFlowTest.test_receivedCubeSurvivesABusyMainThread`, `test_receivedCubeArrivesWhileSlicerWaitsForEvents` | automated |
| 5 Connections | `SLIAFlowTest.test_channelMonitorFollowsTheCubeProgress`, `test_channelMonitorNamesMissingBandsWhenTheAppLeaves`, `test_connectionsRowsFollowTheStandIn`, `test_connectionsCountBandsTheStandInDrops`, `test_connectionsForgetASenderThatLeft`, `test_hsCubeConnectorIsListedButNeverStarted`, `test_connectionsCreateOneClientPerConfiguredPort`, `test_connectionsCloseOnEveryPath`, `test_igtModulesShowTheConnectors` (headful) | automated |
| 6 Panel | `SLIAFlowTest.test_receivedCubeIsShownInTheHsCubePanel` (headful: binding, preview, captions for calibrated, raw and unknown wavelengths), `test_receivedRawCubeKeepsItsCounts`, `test_receivedCubeWavelengthsAreAssumedOnlyFor109Bands`, `test_hsCubePanelWaitsForACubeFromTheApp` (headful) | automated |
| 6 Legibility | Manual steps 1 and 4 | manual |
| 7 Capture | `SLIAFlowTest.test_captureOnAReceivedFloat32CubeRunsUc1AndUc2`, `test_captureOnAReceivedUint16CubeRunsNothing`, `test_captureWithoutAReceivedCubeIsRefused`, `test_captureOnAReceivedCubeOfAnotherBandCountIsRefused`; unchanged disk path: `test_captureRunsUc1OnTheConfiguredCalibratedCube`, `test_captureShowsTheVascularMapAlongsideUc1` | automated |
| 8 Provenance | `SLIAFlowTest.test_receivedCubeProvenance`, `test_standInCubeStaysSimulated`, `test_outputsOfAReceivedCubeCarryItsProvenance`, `test_resultKeepsTheOriginOfItsOwnCube` | automated |
| 9 Lifetime | `SLIAFlowTest.test_receivedCubeIsFreedOnDisconnectAndSceneClose`, `test_receivedCubeReplacesThePreviousOne`, `test_cubeCompletedDuringACaptureWaitsForItsEnd`, `test_runCubeKeptByADisconnectIsRemovedWhenItsCaptureEnds`, `test_readerStopsOnCleanup` | automated |
| 10 Stand-in and transport | `test_igtl_transport.py`: `test_imageSlabMessageParsesInRecorder`; `test_iuma_app_standin.py`: `test_hsCubeSendsWholeCubeSubVolumes`, `test_appHeaderSendsVersion1WithoutMetadata`, `test_uint16CubeIsSentAsUint16`; `SLIAFlowTest.test_imageSlabMessageIsAssembledByOpenIGTLinkIF` | automated |
| 11 Recorder | `test_igtl_recorder.py`: `test_appSlabGeometryIsRecorded` | automated |
| 12 Real app | Manual steps 1-3 | manual |
| 6-8 End to end with the calibrated cube | Manual step 4 | manual |

Tests to add or change, and how each will be shown to fail first:

- Every new `SLIAFlowTest` reader, assembly and parsing test is run before
  `SLIAFlowReceivedCube.py` exists, and fails on its import.
- The CRC test uses the published check value and an independent bitwise
  oracle written in the test. Messages are packed by the test's own code, not
  by the module under test.
- The changed Connections tests are run against the unchanged module with the
  updated stand-in. Their failures are recorded: the HS Cube row cannot name
  the app-form bands, and Connect starts the HS Cube connector.
- The panel, Capture, provenance and lifetime tests fail on the missing
  `cubeSource` parameter and the missing received-cube API.
- The simulator tests are run before `buildImageSlabMessage` and
  `--app-header` exist, and fail with `AttributeError` or exit code 2.
  `test_appSlabGeometryIsRecorded` fails on the missing builder; the recorder
  itself already parses slabs, so its assertions are also run once against a
  recorder with the sub-volume fields swapped, to show they catch it.
- `test_receivedCubeRefusesBadMessages` is also run once against a reader with
  the CRC check disabled.
- The verification fixes: `test_receivedCubeArrivesWhileSlicerWaitsForEvents`
  and the six new cases of `test_receivedCubeRefusesBadMessages` are run
  before the GIL yield and the new refusals exist.

## Manual verification

Commands from the repository root in PowerShell. Nothing else may be connected
to 18946.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Start IUMA's `AcquisitionSystemApp` and **Load HS Cube** `input\002-04\raw_data.hdr`. Start SLIAFlow, set **Cube source** to `Last cube from the app`, press **Connect**, then press **Send Capture** in the app. While it sends, scroll the HS Cube panel | The HS Cube row counts to 109 / 109 and reads `Cube complete`. HS Cube shows the cube, captioned as received from the app, raw and uncalibrated, wavelengths assumed. Colour preview and pixel spectrum work. Note any stutter while it receives | |
| 2 | With the camera running, press **Capture** | UC1 and UC2 do not run. The status and Enhanced Vascularization say they wait for IUMA's calibrated float32 stream. LiveView resumes. With **Cube on disk**, Capture runs as before | |
| 3 | **Disconnect**. In the app press **Send Capture**, and press **Connect** in SLIAFlow while it sends | After Disconnect the received cube is gone from HS Cube. After the late Connect, the row says `Cube incomplete` naming the missed bands as `connected after the capture started`, and no incomplete cube is shown | |
| 4 | Close the app. Start the stand-in with the calibrated cube: `cd tools\simulators; ..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin`. In SLIAFlow, **Connect** with **Cube source** `Last cube from the app`, start the camera, press **Capture** | UC1 and UC2 run on the received cube and show their results. The HS Cube row and the panels say simulated (stand-in) | |

## Risks

- The float32 version may change the structure despite IUMA's statement
  (hardware document section 7, question 9). The reader refuses what it does
  not recognise, by name, rather than guessing.
- The wavelengths are not sent. The 460-1000 nm grid is assumed for 109 bands
  only (question 10), and the node and caption say so.
- The reader's CRC and copy run in Python. numpy releases the GIL inside each
  operation, but the UI may still stutter while a raw cube arrives. Manual
  step 1 records it.
- Peak memory while a raw cube is assembled next to the one shown is 3.9 GB,
  on top of the app's own copy, on a 15.3 GB laptop. A held cube during a
  float32 capture adds a third cube: 4.4 GB if the app switched to raw cubes
  meanwhile. If the app's future float32 stream is full camera size
  (4096 x 2160 x 109, 3.9 GB a cube), three cubes would need 11.6 GB, and the
  hold should be revisited.
- OpenIGTLinkIO's `Stop()` never returns when called just as a connector
  connects (Review findings). SLIAFlow now waits one second before stopping
  an HS Cube connector started in OpenIGTLinkIF, and the tests no longer
  stop a connector at that instant. Disconnect still calls `Stop()` on the
  LiveView and Stereo connectors. Only a Disconnect within milliseconds of
  their connecting could hang, which an operator cannot press in time.
- A long call into Slicer's C++ code (VTK, loading a volume) keeps the GIL
  from the reader, as the yield cannot run meanwhile. pyigtl's server, in the
  stand-in, gives up a send after 10 ms; the app's limit is not known. A
  cube arriving during such a call may then be cut off, and is reported
  incomplete with its missing bands. The reader reconnects after 1 s, in the
  middle of the same cube or of the next; that partial cube is thrown away
  too, so one cut-off can cost up to two cubes but never yields a mixed one. How long a call
  must be is not measured, nor whether showing a full-size cube while the
  next arrives is long enough. Python running on the main thread, as in
  `test_receivedCubeSurvivesABusyMainThread`, hands the GIL over by itself.
- While connected, the main thread sleeps 10 ms each time it is idle. The
  measured cost: a 16 ms UI timer ticked every 14-15 ms (median), never more
  than 28 ms apart, while a full-size cube arrived.
- Reception of the raw 1.93 GB cube at full size is not yet measured: the
  laptop paged with 0.4 GB free (1.3 GB free on re-check). Manual step 1
  measures it with the app.
- A raw cube could be mistaken for calibrated reflectance, and received data
  for a live capture. The captions and provenance say raw, and that the app
  may be replaying.
- The run cube in `workspace` is about 0.5 GB for a 1080 x 1080 x 109 float32
  cube. Only one is kept.

## Documentation impact

- `extensions/SLIAFlow/README.md`: the Connections section receives the cube;
  the cube source; captions; provenance.
- `docs/development/openigtlink_setup.md`: the receiver replaces "received data
  is not yet used".
- `tools/simulators/README.md`: the stand-in's measured form, `--app-header`,
  uint16 cubes.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the `received` origin.
- `docs/hardware/acquisition_app_and_hardware.md`: only if the receiver
  changes a measured fact or an open question.

## Completion evidence

### Implementation (2026-10-06, uncommitted, branch `feature/SLIA-036-receive-app-hs-cube`)

Order of work: the simulator tests were written and seen failing before the
transport and stand-in changes. On the Slicer side the reader, Connections,
logic and widget were written before their tests, and every new and changed
test was then run against the module as committed on `main` (below), so each
was still seen failing on code without the change.

Decisions taken while implementing, within the owner decisions above:

- The CRC-64 is computed with numpy. Rows of the message are run eight bytes
  a step side by side, then joined by the CRC's linearity. It agrees with the
  published check value and with a bit-by-bit oracle. A prototype checked a
  17.7 MB band in about 90 ms.
- A size or type change in mid-cube ends that cube as incomplete and starts a
  new one with the message. The card's two sentences on this ("refused" and
  "a new cube starts") are read as: no pixel of the new message goes into the
  old cube, and the old cube is named as incomplete.
- The texts that said "recorded cube {case} ... simulated acquisition" now take
  a cube phrase and an origin phrase. For the cube on disk they read exactly as
  before; for a received cube they say "the cube received from the app" and
  "received from the app, captured live or replayed".
- The run cube's ENVI description carries no semicolon: `parseEnviHeader`
  reads one as a comment, which left the brace block open and made the header
  unreadable. Found by `test_captureOnAReceivedFloat32CubeRunsUc1AndUc2`.

### Seen failing first

Simulators, before `buildImageSlabMessage`, `sendImageSlab`, `--app-header`
and uint16 cubes existed (`python -m unittest` on the three modules): 19 run,
1 failure, 10 errors.

- `AttributeError: module 'stratum_sim.igtl_transport' has no attribute
  'buildImageSlabMessage'` (all `ImageSlabMessageTest` tests).
- `TypeError: StandIn.__init__() got an unexpected keyword argument
  'appHeader'`.
- `CubeError: cube.hdr declares data type 12, not 4.`
- `error: unrecognized arguments: --app-header`.
- `test_hsCubeSendsWholeCubeSubVolumes`: `Lists differ: [0, 0, 0, 0] !=
  [0, 1, 3, 4]`.
- `test_aBandWhoseWriteFailedIsNotReportedAsSent`: `'_ClientLeavesDuringTheWrite'
  object has no attribute 'sendImage'`.

`test_appSlabGeometryIsRecorded` passed at once: the recorder already parsed
sub-volumes. Run against a recorder whose sub-volume offset and size fields
were swapped, it failed: `Lists differ: [4, 3, 1] != [0, 0, 2]`.
`RecorderStandInTest.test_recordsEveryBandAndFrameOfTheStandIn` then failed
against the new stand-in (`[4, 3, 5] != [4, 3, 1]`) until it was changed to
expect the measured form.

Slicer, the 36 new and changed tests run against the module as committed on
`main`, with the new test file, in a gitignored copy under
`workspace\failfirst` (headful, OpenIGTLinkIF loaded): 33 failed, 3 passed.

- Reader, parsing and assembly tests: `ModuleNotFoundError: No module named
  'SLIAFlowLib.SLIAFlowReceivedCube'`.
- Panel, provenance and replacement tests: `'SLIAFlowWidget' object has no
  attribute '_forgetReceivedCube'`.
- Capture tests: `'SLIAFlowParameterNode' object has no attribute
  'cubeSource'`.
- Freed on disconnect: `'SLIAFlowLogic' object has no attribute
  'receivedCubeNode'`.
- Monitor tests: `'ChannelMonitor' object has no attribute 'setCubeProgress'`.
- `test_connectionsCreateOneClientPerConfiguredPort`: `1 != 0 : Connect started
  the HS Cube connector`.
- `test_hsCubeConnectorIsListedButNeverStarted`: `2 != 0 : The HS Cube connector
  was started`.
- `test_connectionsRowsFollowTheStandIn`: `HsCube - IMAGE 4 x 3, 5 slices
  float32 - band 5, 480 nm`, the connector's view of the app form.
- `test_connectionsForgetASenderThatLeft`: `HsCube - IMAGE 4 x 3, 5 slices
  float32 - 0.0 s ago`.
- `test_connectionsCloseOnEveryPath`, `test_readerStopsOnCleanup`:
  `'SLIAFlowConnections' object has no attribute 'cubeReader'`.
- `test_closingTheSceneClearsTheStatusPanel`: `KeyError: 'case'`.
- Passed, as expected:
  - `test_imageSlabMessageIsAssembledByOpenIGTLinkIF` checks the stand-in's
    form against OpenIGTLinkIF, not the module.
  - `test_connectionsCountBandsTheStandInDrops` changed only from a 1 s to a
    2 s idle time (the flake), and the default stand-in still sends band
    numbers the old code reads.
  - `test_vascularMapReachesItsPanelAndNowhereElse` now spells out the same
    caption text instead of formatting it.

A first attempt at this run hung in `test_connectionsCreateOneClientPerConfiguredPort`.
`test_readerStopsOnCleanup` had left the widget connected after failing on the
old code. Its cleanup now disconnects, and the rerun above completed.

### Checks

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
Rerun after the review fixes of 2026-10-06 (the simulators were not changed by
them; their row is from the first run):

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | `Python quality checks passed.` (both targets) | 0 |
| Simulators | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 64 run, OK | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | 145 run, OK, 19 skipped (headful-only) | 0 |
| Slicer, Source, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | 145 run, OK, 1 skipped (`test_headlessPresentationFallback`, headless-only) | 0 |
| Build | `.\scripts\development\build-sliaflow.ps1 -Configure` | build tree matches the working tree | 0 |
| Slicer, Build, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | loaded from `build\SLIAFlow`; 145 run, OK, 1 skipped | 0 |
| Whitespace | `git diff --check` | nothing reported | 0 |

The three Slicer rows are from the final runs, after the `Stop()` fix below:
29 s headless, 49 s headful, 50 s on the build target. For the runs after
the verification fixes, see Verification findings, resolved.

The first build-target attempt after the review fixes hung. After more than
10 minutes Slicer was idle (no CPU) with its window not responding. The
official runner prints Slicer's output only on exit, so it showed no test.
It was found by running the suite in the official alphabetical order with
each test named as it started and a stack dump after 120 s
(`workspace\failfirst\run_selected.py`, `loop.ps1`). The first such run hung in
`test_connectTakesOverAConnectorStartedInOpenIGTLinkIF`, with the main thread
in `connector.Stop()` inside `SLIAFlowConnections.connect`. That test, from
SLIA-035, starts a connector and presses Connect straight away. The cause is
in OpenIGTLinkIO (`build\SlicerOpenIGTLink\OpenIGTLinkIO\Logic\igtlioConnector.cxx`):

- `Stop()` waits until the connector's socket list is empty.
- The receiver thread removes its socket only after it has entered its loop.
- If the stop flag is already set when that thread starts, it never enters
  the loop, so the socket stays and `Stop()` waits forever.

`test_hsCubeConnectorIsListedButNeverStarted` stopped a just-started
connector the same way. The fix:

- SLIAFlow stops an HS Cube connector started in OpenIGTLinkIF only after it
  has run for `STARTED_CONNECTOR_STOP_DELAY_SEC` (1 s). The test now checks
  that it is not stopped at once.
- The SLIA-035 test now waits for the started connector's first frame before
  pressing Connect, as an operator would.

Before the fix, 2 of 5 full runs hung. After it, five full runs in the
official order passed (`loop-1.log` to `loop-5.log`): each 144 OK, 1 skipped,
in 50-53 s.

Before this task the suite had 119 tests: 32 were added (two of them after
the verification, below) and 4 removed. The
removed ones are old `ChannelMonitor` band-counting tests. Three have rules
that now belong to the assembler and are tested there:
`RefusesAnythingButBandsOnHsCube`, `NamesMissingBands` and `StartsANewCube`.
`CountsBandsItCannotName` no longer applies, because every band is named by
its offset.

### Full-size check (not a unit test)

The reader in Slicer, assembling into `vtkImageData`, against the stand-in
serving `input\002-04` with `--band-interval 0`
(`workspace\failfirst\fullsize.py`):

- Calibrated cube, 1080 x 1080 x 109 float32, header version 2: 109 messages,
  0 refused, the cube equal to `LCTF_Calibrated_Cube_Single.dat` value for
  value, marked simulated. 27.0 bands/s, 126 MB/s from the first band to the
  last.
- Raw cube, 4096 x 2160 x 109 uint16, `--app-header`: not completed. The
  laptop had 0.4 GB of 15.3 GB free at the time. The stand-in's 1.93 GB copy
  and the reader's buffer paged, so the run was stopped. Manual step 1, with
  the app instead of the stand-in, covers this size.

### Not done

- Manual steps 1-4 are for the owner. The verification of 2026-10-06 failed
  steps 1 and 4. They are to be repeated after the fixes in Verification
  findings, resolved.
- The raw cube at full size (above).

## Review findings

An AI review of the branch with its uncommitted changes, given by the owner on
2026-10-06, before manual verification. Each finding was checked against the
code.

1. **High, memory: confirmed, partly.** A capture on a received float32 cube
   can retain the cube shown, a held cube and one being assembled: three, not
   the two the card stated. The review's "three raw cubes, 5.8 GB" cannot
   happen, because a capture on a raw cube ends at once and holds nothing. The
   peaks are 1.5 GB for three float32 cubes, and 4.4 GB if raw cubes arrive
   during a float32 capture. Owner decision: keep holding. The card and README
   now state the real peak, and the risk names the full-size float32 case.
   The raw full-size reception is still unmeasured (manual step 1).
2. **High, wrong provenance caption: confirmed and fixed.** The Delineation
   and Vascularization texts read the origin of the latest capture's cube.
   A stand-in result shown after a failed capture on the app's cube was
   described as received from the app. The result and the map now keep the
   origin of their own cube.
3. **Medium, missing bands hidden after the sender leaves: confirmed and
   fixed.** The row was `Waiting for the app` or `App not running`, and the
   missing bands were dropped. The row now adds `The last cube was incomplete
   and was not used. Missing bands: ...`.
4. **Medium, end-to-end processing of a received cube unverified: agreed.**
   The automated capture tests use placeholder processes, and the full-size
   check covers reception only. Manual step 4 covers it and is pending.
5. **Low, run cube kept by a Disconnect during a capture: confirmed and
   fixed.** It is now removed when that capture ends.

Fail-first, the three new tests run against a copy of the module with the
fixes taken back out (`workspace\failfirst\make_prefix.py`, headful):

- `test_channelMonitorNamesMissingBandsWhenTheAppLeaves`: `'last cube was
  incomplete' not found in ''`.
- `test_resultKeepsTheOriginOfItsOwnCube`: `'stand-in' not found in 'Previous
  result: the cube received from the app, ...'`.
- `test_runCubeKeptByADisconnectIsRemovedWhenItsCaptureEnds`: `The run cube
  outlived its capture`.

With the fixes, all three pass in every run in the Checks table.

### Agent-driven verification and fault probes (2026-10-06)

Requested by the owner. Branch unchanged:
`feature/SLIA-036-receive-app-hs-cube`. Only this card was edited;
implementation and existing local changes were left untouched. No MCP was
used. Temporary harnesses and text-only evidence are under
`%TEMP%\slia036-verification-20261006`; no medical-image screenshots were
created. The manual table remains pending: the repository workflow reserves
its Result column and visual sign-off for a person.

Slicer was launched with `build\SLIAFlow\SlicerWithSLIAFlow.exe`, SLIAFlow
selected and Reload exercised. The six changed reader/logic/widget helper
files were hash-identical between source and build. The configured Slicer
path was read from `config/local.json`, which was not changed.

**Failures and robustness gaps:**

1. **Blocking: normal interactive reception does not complete.** The real
   AcquisitionSystemApp loaded `input\002-04\raw_data.hdr` (4096 x 2160 x
   109 uint16). With SLIAFlow connected before Send Capture, the reader
   repeatedly lost its connection after 1-3 bands, reported missing bands,
   reconnected late, and never displayed a cube. Observed details included
   `Missing bands: 4-109` and
   `Missing bands: 1-2 (connected after the capture started), 6-109`.
   Available RAM fell to approximately 0.45 GiB. The app displayed
   `HSI capture sent successfully`, despite the receiver not completing.
   Manual step 1 therefore failed; raw Capture in step 2 was blocked.
2. **The same failure affects the calibrated stand-in.** Running the card's
   default stand-in with a 600 s cube interval and 900 s duration produced
   repeated `Error while sending data: timed out` and only 3-4 bands sent.
   This also reproduced with the LiveView/Stereo ports pointed at unused
   ports and the laptop camera stopped. Instrumentation in the running
   process measured 1.3-2.6 s parsing a 4.67 MB band versus 0.016-0.203 s
   receiving its body. The same-size CRC took 0.031 s on the main thread;
   a single-band reader test inside a Python polling loop took 0.312 s.
   A diagnostic loop using `processEvents()` and `sleep(0.02)` allowed all
   109 bands to complete. This points to a difference in background Python
   scheduling during the normal Qt event loop; the precise cause remains
   unproven. Manual step 4 is not a normal-workflow pass.
3. **Undefined byte order is silently accepted.** A valid-CRC uint16 IMAGE
   with endianness code 0 was treated as little endian. A test fixture's
   big-endian value 1 became 256, with no refusal.
4. **Empty images can complete.** A valid-CRC IMAGE declaring zero samples,
   two lines and one band was accepted; the socket reader emitted a complete
   empty cube rather than a refusal. This probe did not display fixture data.
5. **Unsupported versions are accepted.** Header version 0 was parsed as v1;
   version 3 with a v2 body was parsed as v2. IMAGE content version 99 was
   also accepted. These malformed inputs were not refused by name.

**Successful checks and limits:**

- `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: 64 tests,
  OK, exit 0 (48.8 s).
- `scripts\development\run-slicer-tests.ps1 -Headful`: 145 tests, OK,
  one expected headless-only skip, exit 0 (71.0 s). This includes CRC and
  malformed-message refusals, reordered/repeated/dropped bands, late joining,
  timeout/disconnection, held cubes, raw/unknown-band Capture refusal,
  connector ownership, scene close and Reload. The green suite does not
  detect the full-size normal-event-loop failure above.
- Real laptop camera started and supplied a frame. Capture with no complete
  received cube refused before freezing; LiveView stayed active.
- After the explicitly diagnostic reception loop completed, real Capture
  wrote the received float32 cube and ran the installed UC1 and UC2 processes
  successfully. Their panels reported completion and simulated stand-in
  provenance; their output nodes carried their producer and origin details.
  The received node was retained, Capture ended, and LiveView resumed.
- Real disk Capture also completed UC1 and UC2. All five UC1 output nodes
  existed. Colour preview bound a 1080 x 1080 RGB node with simulated origin;
  a pixel click produced a 109-row spectrum table with the same origin.
  An outside-pixel click displayed the refusal label.
- Disconnect stopped the reader and removed the received and held cubes.
  Leaving SLIAFlow restored layout 0; returning and Reload left the module
  disconnected, with no received cube and no Capture running.
- A body truncated before its first complete band produced no complete cube;
  a body size of 1,073,741,825 bytes was refused by name, without allocating
  that body. Both readers stopped successfully. The additional probe script
  exited 0; accepted malformed inputs are findings, not successful validation.
- `git diff --check`: exit 0, no whitespace errors.

The exact deliberate late-Connect sequence, raw preview/spectrum and raw
Capture remain unverified against the real full-size cube. UI legibility and
scroll responsiveness require owner observation. The IUMA app and temporary
stand-in were closed after testing; Slicer remains open in SLIAFlow following
Reload. No review/completion transition or Git mutation was performed.
Resolve normal interactive reception and the parser gaps before repeating
the manual checks or advancing the task.

### Verification findings, resolved (2026-10-06)

Each finding above was checked against the code, and all five hold.

**1 and 2, reception stops after a few bands: cause found and fixed.**

- The cause is the GIL. Slicer's main thread keeps Python's GIL while it
  waits in Qt's event loop. Another Python thread runs only while the main
  thread runs Python. This is documented by Slicer's maintainers
  (discourse.slicer.org/t/32299), and their remedy, used in SimpleFilters, is
  a timer that calls `sleep()`.
- The reader gives up the GIL hundreds of times per band, in every `recv`
  and in each numpy call of the CRC. Each time it had to wait for the main
  thread's next Python call, such as the 500 ms Connections refresh.
- Meanwhile the sender's buffer filled. pyigtl's server gives each send
  10 ms (`settimeout(0.01)` in `TCPRequestHandler.handle`), then logs
  `Error while sending data: timed out` and drops the client. The app
  behaved the same way.
- The unit tests did not see it: every one waits in a loop of
  `processEvents()` and `sleep()`, and the `sleep()` releases the GIL. The
  verifier's diagnostic loop worked for the same reason.
- The fix: while the reader runs, `SLIAFlowConnections` sleeps
  `GIL_YIELD_SEC` (10 ms) on the main thread from a zero-interval QTimer,
  that is, whenever the event loop has nothing else to do. It stops with the
  reader.
- New test `test_receivedCubeArrivesWhileSlicerWaitsForEvents`. The
  stand-in sends 20 bands of 512 x 512 float32 without pause, while the test
  waits inside a `qt.QEventLoop`. Before the fix: `No cube while Slicer
  waited for events; rows: [... 'state': 'Connected', ... 'received': '0 / 20
  bands']` after 21.6 s. After the fix: passed in 1.7 s.
- Full size, in Slicer, with `SLIAFlowConnections` against the stand-in
  serving `input\002-04\LCTF_Calibrated_Cube_Single.hdr`, the main thread
  in `qt.QEventLoop` (`workspace\failfirst\fullsize_idle.py`):

  | Band interval | GIL yield | Result | 16 ms UI timer, gap median / max |
  | --- | --- | --- | --- |
  | 0.114 s (the app's 8.8 bands/s) | off | stand-in: `Error while sending data: timed out`, `sent 3 of 109 bands`; row `Cube incomplete (stand-in)`, `Missing bands: 1, 3-109.`; no cube in 60 s | - |
  | 0.114 s | on | 1080 x 1080 x 109 float32, equal to the file, 16.5 s from Connect | 14 / 28 ms |
  | 0 | on | equal to the file, 4.0 s from Connect | 15 / 27 ms |

- The raw 4096 x 2160 x 109 cube was not repeated with the stand-in: 3.0 GB
  were free, and the stand-in's copy plus the reader's are 3.9 GB. Manual
  step 1, with the app, covers it.

**3-5, malformed messages accepted: fixed.** `parseBandMessage` now refuses,
by name:

- a header version other than 1 or 2;
- an image header version other than 1;
- a byte order code other than 1 or 2;
- an image whose samples, lines or bands are 0.

Six cases were added to `test_receivedCubeRefusesBadMessages`: byte order
codes 0 and 3, header versions 0 and 3, image header version 99, and 2 x 0
pixels. Before the fix, each one failed with `RefusedMessage not raised`.
After it, the test passes.

**Checks after these fixes:**

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | `Python quality checks passed.` | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | 146 run, OK, 19 skipped, 31.0 s | 0 |
| Build | `.\scripts\development\build-sliaflow.ps1 -Configure` | build tree matches the working tree | 0 |
| Slicer, Build, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | loaded from `build\SLIAFlow`; 146 run, OK, 1 skipped, 53.7 s | 0 |
| Whitespace | `git diff --check` | nothing reported | 0 |

The simulators were not changed and were not rerun. The verifier's run had
them at 64 tests, OK.

The manual steps must be repeated on the rebuilt `build\SLIAFlow`, with no
diagnostic loop. Step 4's earlier pass relied on one.

### Mixed cube after a mid-cube connection, fixed (2026-10-07)

- Found while describing the GIL risk. A connection that joined in mid-cube
  received bands k+1 to the last; the next cube's bands 1 to k then filled
  the gaps, and the assembler handed over a complete cube made of two
  captures. Reproduced with `CubeAssembler` directly: a 5-band cube cut off
  after band 2, reconnected at band 4, then the next cube's bands 1-3, came
  back complete with band values `[2, 2, 2, 1, 1]`. It applies to a reconnect
  after a cut-off and to pressing Connect while the app sends.
- The fix (`CubeAssembler._startsNextCube`): a band the connection missed,
  arriving once the cube holds its last band and before any other missed
  band, ends the cube as incomplete and starts the next one. The first
  version, without the last-band condition, failed the approved "any order"
  criterion (`test_receivedCubeAssemblesBandsByOffset`, offsets 2, 0, 3, 1),
  and was narrowed.
- The note "The previous cube was incomplete" lasted only for the first band
  of the next cube, so at the app's pace the 500 ms refresh would rarely show
  it. It now stays while the next cube is received.
- New test `test_receivedCubeLateConnectionNeverMixesTwoCubes`. Before the
  fix: `FAIL ... is not None : Bands of two cubes were put together as one`
  (`workspace\failfirst\mix-before.log`). After it, with
  `test_receivedCubeLateConnectionMissesFirstBand`,
  `test_receivedCubeStartsANewCube`, `test_receivedCubeNamesMissingBands` and
  `test_receivedCubeAssemblesBandsByOffset`: 5 OK.

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | `Python quality checks passed.` | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | 147 run, OK, 19 skipped, 37.3 s | 0 |
| Build | `.\scripts\development\build-sliaflow.ps1 -Configure` | build tree matches the working tree | 0 |
| Slicer, Build, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` | loaded from `build\SLIAFlow`; 147 run, OK, 1 skipped, 91.2 s | 0 |
| Whitespace | `git diff --check` | nothing reported | 0 |

### Agent-driven repeat verification (2026-10-07)

Requested by the owner to repeat the earlier checks after the fixes. Used the
installed Slicer skill without MCP, on the same branch
`feature/SLIA-036-receive-app-hs-cube`. All SLIAFlowLib Python files were
hash-identical between source and build. Launched the built Slicer launcher,
selected SLIAFlow and exercised Reload. Only this card was changed; existing
implementation changes were preserved. Text-only evidence and temporary
harnesses are under `%TEMP%\slia036-verification-20261007`.

**All five previous failures are fixed in the repeated probes:**

1. The real IUMA app loaded `input\002-04\raw_data.hdr`. Connecting before
   Send Capture completed 109 / 109 bands, without reconnects or the diagnostic
   polling/sleep loop. The displayed node was 4096 x 2160 x 109 uint16,
   origin `received`. The caption named raw, uncalibrated counts and assumed
   wavelengths. Colour preview and the centre-pixel spectrum worked; the
   spectrum had 109 rows with received provenance. An outside click refused.
2. The calibrated stand-in, launched from the command line with the default
   cube and `--cube-interval 600 --duration 900`, sent all 109 bands in the
   normal Slicer event loop, without the earlier workaround or sender timeout.
   The displayed node was 1080 x 1080 x 109 float32, origin `simulated`.
   Actual Capture ran the installed UC1 and UC2 successfully, ended Capture,
   unfroze LiveView, and retained the received node. All five UC1 output nodes
   existed, carried simulated provenance and named the real UC1 pipeline and
   received stand-in cube. UC2 and the panel captions named the stand-in.
3. Byte-order codes 0 and 3 now refuse by name. The prior valid-CRC corrupting
   fixture is rejected; a valid big-endian fixture decodes value 1 correctly.
4. Zero samples, zero lines and zero bands all refuse. The socket probe with
   zero samples no longer emits a complete empty cube, and stops cleanly.
5. Header versions 0 and 3, including version 3 with a v2 body, and IMAGE
   content version 99 now refuse by name.

**Other workflow and fault checks:**

- The actual laptop camera supplied frames. Raw Capture refused UC1/UC2 with
  the calibrated-float32 requirement; Capture was idle and LiveView unfrozen.
  Switching to Cube on disk and pressing Capture completed real UC1/UC2;
  `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, `imageRGB.bmp` nodes existed.
- Calibrated colour preview and pixel spectrum worked and named simulated
  stand-in provenance; the spectrum table had 109 rows.
- Disconnect removed the received cube. Send-then-Connect timing was not
  deterministic: one attempt missed band 1, another received the whole cube.
  To force joining during transmission, disconnected after band 5 and
  reconnected after 1.5 seconds while the real app continued sending. After
  the 10-second idle timeout the row read `Cube incomplete`, 102 / 109,
  `Missing bands: 1-7 (connected after the capture started).` No partial node
  or HS Cube caption existed. The precise click timing in manual step 3
  still needs owner observation; the forced reconnect verifies its refusal.
- Truncated bodies emitted no complete cube. A declared body of
  1,073,741,825 bytes refused by name without allocating it. Readers stopped.
  Placeholder fixtures were never displayed. Coordinate-system code 0 remains
  accepted, consistent with the approved decision to ignore transmitted
  geometry; it is not one of the previous failures.
- Disconnect, leaving SLIAFlow (layout restored to 0), returning and Reload
  cleaned up the reader and received state. The app and temporary stand-in
  were closed. Slicer remains open in SLIAFlow, disconnected after Reload.

**Remaining observations; this is not an unconditional verification pass:**

- A 16 ms UI timer measured a 16 ms median gap and a 4,844 ms maximum gap
  across raw reception and completion. Reception succeeds, but this pause
  means responsiveness still needs assessment, especially at full size.
  This is a timing measurement, not a human judgment of scrolling/legibility.
- The first Build headful suite run failed
  `test_hsCubeConnectorIsListedButNeverStarted`: its temporary HS Cube server
  did not answer and 0 / 5 bands arrived within the timeout. There were
  147 tests, one failure and one expected skip, 111.7 s, exit 1. The simulator
  suite ran concurrently, and the real app was opened during that run. The
  cause was not established. Repeating without the simulator suite or real
  app passed: 147 tests, one expected skip, 61.4 s, exit 0. Record the initial
  failure as intermittent; a green rerun does not establish its cause.

Commands: `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`
passed 64 tests in 48.8 s, exit 0.
`.\scripts\development\run-slicer-tests.ps1 -Target Build -Headful` was used
for both suite runs above. Both temporary parser/socket probe scripts exited
0. `git diff --check` exited 0. No implementation edits or Git mutations.

The manual Result cells remain empty because the repository workflow reserves
human visual sign-off for the owner. The five original failures no longer
reproduce, but the UI pause, intermittent suite timeout and human visual
verification remain outstanding. The task remains active.

## Human approval
