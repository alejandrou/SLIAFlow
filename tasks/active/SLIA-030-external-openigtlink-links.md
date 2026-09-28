---
id: SLIA-030
title: Receive IUMA's acquisition app - measure its protocol, then show and classify its cube
status: active
branch: feature/SLIA-030-external-openigtlink-links
priority: medium
depends_on: SLIA-035, SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-030 - Receive IUMA's acquisition app - measure its protocol, then show and classify its cube

## Goal

Connect SLIAFlow to IUMA's real acquisition app, write down exactly what it
sends, and then use it: LiveView from 18944 in the live pane, and the cube from
18946 assembled, shown in the HS Cube panel and, when it is the calibrated
float32 cube, run through UC1 like the cube read from disk.

## Context

*Rewritten on 2026-09-24 against `ADR-0004`; specified on 2026-09-27.* The
original card waited for "a real external producer". IUMA's app is that
producer, and it is installed on this laptop
(`C:\Program Files\IUMA\InstallerAcquisitionApp`). Its UC2 part moved to
`SLIA-021`.

Known from the app's binary and from IUMA
(`docs/hardware/acquisition_app_and_hardware.md` sections 3.5, 4, 7 and 8):

- The app is the OpenIGTLink server: 18944 LiveView, 18945 stereo, 18946 HS
  cube. Slicer is the client. One client per port.
- The cube goes out as one IMAGE message per band. No per-band metadata strings
  were found in the binary, so how a receiver knows band index, wavelength and
  cube completion was unknown. Phase A measured it (section 4.1 of the hardware
  document): the band index is the sub-volume offset, and completion is having
  every offset. The wavelength is not sent.
- **What the app can send today.** Its cube viewer (Load HS Cube) loads only
  ENVI uint16 BSQ, and Send Capture replays the loaded cube on 18946. So without
  cameras the app can send `002-04`'s **raw** cube (`input\002-04\raw_data.hdr`,
  4096 x 2160 x 109 uint16, 1.93 GB, about 17.7 MB per band), not its
  calibrated float32 cube.
- **What it will send.** IUMA (2026-09-23, relayed again by the owner on
  2026-09-27): the app will send the calibrated cube as float32; integration
  takes time because BSC must agree; ports, device names and message structure
  will not change, only the pixel type (uint16 to float32). The protocol can be
  validated now on the uint16 stream.
- OpenIGTLinkIF keeps a circular buffer of 3 per device name and pulls it every
  5 ms (`SLIA-035`), so a band-per-message cube can lose bands in a plain
  connector if bands arrive faster than they are pulled.

`SLIA-035` gave the Connections panel, the stand-in
(`stratum_sim.iuma_app_standin`, calibrated float32 with invented per-band
metadata) and the list of **stand-in assumptions** this card checks.

### Owner decisions, 2026-09-27

1. **Measurement.** A small recorder in `tools/simulators` connects to the three
   ports as the client and logs every message. The owner runs the app, loads
   `002-04`'s raw cube and presses Send Capture while it records. The receiver
   is designed from that log.
2. **Raw uint16 cube.** A received uint16 cube is assembled and shown in the HS
   Cube panel but not classified: SLIAFlow does no white/dark calibration of its
   own (`acquisition_app_and_hardware.md` section 6, `ADR-0004`). Capture on it
   says UC1 waits for IUMA's calibrated float32 stream. UC1 on a received cube is
   built for float32 and tested with the stand-in.
3. **Provenance** (`ADR-0004` decision 7): a cube or frame received from the app
   has `SLIAFlow.DataOrigin = received`. The detail names IUMA's
   AcquisitionSystemApp, host:port and the reception time, and says the app may
   be capturing live or replaying a stored cube (Send Capture), which SLIAFlow
   cannot tell apart. Anything whose messages carry
   `SLIAFlow.DataOrigin = simulated` (the stand-in) keeps `simulated`.

## Requirements

The task has two phases. Phase B's details depend on what phase A measures, and
are finalised in this card, and reported to the owner, before any phase B code
is written.

### Phase A - measure the protocol

- `tools/simulators/stratum_sim/igtl_recorder.py`, run with
  `python -m stratum_sim.igtl_recorder` from `tools\simulators` under the
  repository `.venv`. Nothing in it imports `slicer`.
- It connects as a client to host (default `127.0.0.1`) on the given ports
  (default 18944, 18945, 18946), tries again every second while a port refuses,
  and reads every message whole with its own header parser. It does not use
  `pyigtl.OpenIGTLinkClient`, which keeps only the latest message per device.
  It sends nothing.
- Per message it writes one JSON line: port, arrival time (wall clock and
  monotonic), header version, message type, device name, header timestamp, body
  size, whether the CRC matches; for header version 2 the extended header and
  every metadata key and value; for IMAGE the image header version, component
  count, scalar type, endianness, coordinate system, size, spacing, origin and
  direction from the matrix, the sub-volume, and the pixel minimum, maximum and
  mean over finite values with the count of non-finite ones. Messages other
  than IMAGE are logged with type and size, STRING and STATUS with their text,
  any other type with its first 64 bytes in hex. Every line is strict JSON (a
  non-finite number is written as `null`).
- Reading is separate from describing: per-port readers only read and
  time-stamp, and one thread checks CRCs, computes statistics and matches
  bands, so arrival times, rates and gaps are the sender's. Past 3 GB waiting
  the readers wait, and the summary reports how long, and the longest wait
  before a message was described.
- `--compare-cube <header>` (ENVI uint16 or float32, BSQ) names, for each
  single-component IMAGE whose size matches the cube, the cube band with the
  same pixels, also trying the band flipped top to bottom and left to right, or
  says none matches. This establishes band order and orientation without any
  band metadata.
- It writes **no pixel data**: only the log and a summary. Output goes to
  `--out` (default `workspace\igtl-recordings\<yyyyMMdd-HHmmss>`, gitignored).
- At the end (Ctrl+C or `--duration`) it writes `summary.md` and prints it: per
  port, messages, device names, types, sizes, scalar types, header versions,
  metadata keys, rate, longest gap, messages other than IMAGE with their text;
  for the cube port, compared bands split into captures wherever more than
  `--capture-gap` s (default 5) pass without one, and per capture the bands in
  order, missing, repeated or out of order, time from first to last band, and
  the messages other than IMAGE that followed it, which could mark the end of
  a cube.
- The measurement itself is run by the owner (manual step A2), and its results
  go into `docs/hardware/acquisition_app_and_hardware.md` section 4,
  `docs/development/openigtlink_setup.md`, the stand-in assumptions in
  `tools/simulators/README.md`, and this card.

### Phase B - receive and use

*Finalised on 2026-09-27 from the measurement (`acquisition_app_and_hardware.md`
section 4.1); proposed to the owner, not yet approved.*

What the measurement fixed: `HsCube` is header version 1 with no metadata.
Every IMAGE declares the whole cube (4096 x 2160 x 109) and carries one band as
the sub-volume at offset (0, 0, band - 1). No message marks the end of a cube.
The app sent 8.8 bands/s (157 MB/s), and a client that joined late missed
band 1.

- **Receiver: a module-owned reader for 18946**
  (`SLIAFlowReceivedCube.py`), not an observer on the `SLIA-035` connector.
  Reasons:
  1. The band is known only from the sub-volume offset, and OpenIGTLinkIF
     does not pass it on. It assembles the slabs into one volume that it does
     not clear. An observer would therefore see a volume change, but not which
     band arrived. It could not name a missing band, and could not tell a
     missing band from one that holds the previous cube's pixels.
  2. The connector keeps 3 messages per device and is emptied on the main
     thread. At 113 ms per band, a main-thread pause of about 0.35 s (a UC1
     run, a colour preview) drops bands silently.
  3. The recorder, written in Python, already read the real stream at
     157 MB/s without being held back.

  The reader is a socket thread that connects to host:18946 as the port's one
  client and retries every second like the connector. It reads each message
  whole, header version 1 or 2, and checks the CRC. It copies each band's
  pixels into place in one preallocated numpy array of the declared size,
  keyed by the sub-volume offset. It never touches MRML: the main thread polls
  it with a Qt timer.

  In the Connections panel, the HsCube row is fed by this reader. The LiveView
  and Stereo rows keep their `SLIA-035` connectors.
- **Messages the reader accepts.** Anything but a single-component uint16 or
  float32 IMAGE with a whole-cube size and a one-band sub-volume is refused by
  name in the HsCube row, and does not touch the cube being assembled. So is a
  bad CRC, or a size or type that changes in the middle of a cube.
- **Band identity**: band = sub-volume offset k + 1, of `size[2]` bands. When
  a message carries `SLIAFlow.BandNumber` (the stand-in, header version 2),
  it must agree with the offset, or the message is refused. Wavelengths are
  never sent. For 109 bands the node gets the expected grid (460-1000 nm in
  5 nm steps), and says on the node that the grid is assumed, not received.
  Any other band count has no wavelengths, so it is shown but not classified.
- **Cube boundaries.** A cube is **complete** as soon as it holds every offset
  from 0 to `size[2] - 1`. A new cube starts when an offset already held
  arrives again, or when the size or type changes. A cube that gets no band
  for 10 s (`ChannelMonitor.CUBE_IDLE_SEC`), or whose sender disconnects, is
  **incomplete**: its missing bands are named, for example
  `Missing bands: 1 (connected after the capture started)`, and it is thrown
  away. Only a complete cube is ever shown or classified.
- **The cube from the app.** A complete cube is shown in the HS Cube panel
  with its colour preview and pixel spectrum, as for the cube read from disk,
  keeping its received type (uint16 or float32).
  - The array has the same axis order as the cube read from disk: received
    offset k is disk band k + 1, as stored (measured).
  - The geometry is SLIAFlow's own, not the app's centred origin: the app's
    header is spacing 1 with an identity direction, which carries no physical
    information.
- **Memory.** One received cube is kept. The assembly buffer is a second
  array: a new cube is assembled while the last complete one stays shown, so
  the peak is two cubes (3.9 GB uint16, 7.7 GB float32). The last complete
  cube is replaced, and freed, when the next one completes. An incomplete
  cube's buffer is freed when it is thrown away. Both are freed on Disconnect,
  scene close and Reload.
- **Capture source.** The operator chooses the cube source: the configured cube
  on disk (today's behaviour, the default) or the last complete cube received
  from the app. Capture on a received float32 cube runs UC1 through the existing
  band mapping and checks; on a received uint16 cube it shows the cube and says
  UC1 waits for IUMA's calibrated float32 stream. Memory: one received cube is
  kept, not a history.
- **LiveView from the app** in the live pane, as an alternative to the laptop
  camera, chosen by the operator. It never lands in the laptop camera volume
  (`SLIA-035` criterion 10).
- **Provenance** as in owner decision 3, on the received cube, the frames, and
  the UC1 outputs of a received cube.
- The stand-in follows the measured protocol: every HsCube message declares
  the whole cube and carries one band as the sub-volume at offset
  (0, 0, band - 1).
  - It keeps header version 2 and its metadata, so that its data stays marked
    `simulated`. `--app-header` sends header version 1 without metadata,
    exactly like the app, which tests the reader on the real form.
  - It gains `--raw`, which sends `002-04`'s raw cube as uint16, so that both
    pixel types are tested.
  - pyigtl 2.2.6 always packs the sub-volume as the full image, so the
    transport gains a hand-packed IMAGE with a sub-volume
    (`igtl_transport.buildImageSlabMessage`). It is checked against the
    recorder's parser and against a real OpenIGTLinkIF connector.
- Questions the measurement cannot answer go to IUMA, listed in the hardware
  document section 7.

## Out of scope

- Sending anything back to the app (commands, parameters, Capture HSI).
- White/dark calibration in SLIAFlow.
- Stereo display beyond showing that the port carries data (SLIA-035 already
  does).
- PLUS (`ADR-0004` decision 9).
- UC2 (`SLIA-021`).
- A history of received cubes, or saving a received cube to disk.

## Files allowed

Phase A:

- `tools/simulators/stratum_sim/igtl_recorder.py` (new)
- `tools/simulators/tests/test_igtl_recorder.py` (new)
- `tools/simulators/README.md`
- `docs/hardware/acquisition_app_and_hardware.md`
- `docs/development/openigtlink_setup.md`
- `tasks/active/SLIA-030-external-openigtlink-links.md`

Phase B, in addition:

- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowReceivedCube.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowConnections.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Input.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/README.md`
- `tools/simulators/stratum_sim/iuma_app_standin.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_iuma_app_standin.py`
- `tools/simulators/stratum_sim/igtl_transport.py` (added 2026-09-27 with
  phase B, pending owner approval: sub-volume IMAGE messages)
- `tools/simulators/tests/test_igtl_transport.py` (same)
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`

Also touched on this branch at the owner's request (2026-09-27), outside the
task: `tasks/active/SLIA-034-uc1-performance-and-large-cubes.md` deleted. It
was a stale copy re-added by `012f59d`; the completed card is in
`tasks/completed/`.

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1 -Configure` and never edited by hand.

## Relevant skills and references

- Slicer skill (phase B): `vtkMRMLIGTLConnectorNode`, volume nodes from arrays.
- OpenIGTLink v2/v3 header and IMAGE message layout, as implemented by the
  pinned `pyigtl` 2.2.6 in `.venv` (`pyigtl/messages.py`), used by the tests to
  build reference messages.
- `docs/hardware/acquisition_app_and_hardware.md`
- `docs/development/openigtlink_setup.md`
- `tasks/completed/SLIA-035-connections-panel.md` (connector facts, stand-in
  assumptions)
- `tools/simulators/stratum_sim/iuma_app_standin.py`

## Implementation plan

Phase A:

1. Write `test_igtl_recorder.py` (below) and see it fail: the module does not
   exist.
2. Write `igtl_recorder.py`: header and IMAGE parsing, per-port reader threads
   with retry, JSON-lines log, compare-cube matching, summary.
3. README section; run the quality checks and the simulators tests.
4. Report to the owner and stop for manual steps A1-A3.
5. Write the measured facts into the documents and this card; check each
   stand-in assumption.

Phase B, after the measurement:

6. Finalise the receiver choice, the phase B acceptance criteria and test names
   in this card; report them to the owner.
7. Tests first, then `SLIAFlowReceivedCube.py` (Slicer-free band assembly), the
   connector-side copying, the capture source choice, LiveView source, UC1 on a
   received float32 cube, provenance; stand-in `--raw` and protocol updates.
8. Documentation; `build-sliaflow.ps1 -Configure`; all checks.

## Acceptance criteria

Phase A:

1. The recorder logs, per message, every field listed in the requirements, for
   header versions 1 and 2, and marks a message whose CRC does not match. The
   text of STRING and STATUS messages is logged; NaN and infinite pixels leave
   the statistics finite and the log strict JSON.
2. With the stand-in running, it records every band on 18946 with its device
   name, float32 type, size and metadata, and every frame on 18944 and 18945.
3. With `--compare-cube`, each band is matched to its cube band, also when
   flipped, and a band that matches nothing says so.
4. It keeps trying a port that refuses and records from the moment the server
   appears; it sends nothing to the server.
5. It writes no pixel data; the summary names missing, repeated and out-of-order
   bands per capture, a second send of the cube is a second capture, and the
   message that followed each capture is named.
5a. Arrival times do not include the time spent describing earlier messages.
6. The real app's protocol is recorded (manual) and written into the hardware
   document, the OpenIGTLink setup document and this card, with each stand-in
   assumption marked confirmed, wrong (with the measured fact) or not
   measurable.

Phase B (finalised 2026-09-27, pending owner approval):

7. A complete cube from the app or the stand-in is assembled by sub-volume
   offset, whatever the order in which bands arrive, and shown in the HS Cube
   panel.
   - This holds for uint16 and float32, and for header version 1 without
     metadata and version 2 with it.
   - A cube with missing bands is never shown, and the HsCube row names the
     missing bands. This includes a first band missed by a late connection.
   - Refused messages are named, and leave the cube being assembled
     untouched: a bad CRC, a wrong type or component count, a band number
     that disagrees with the offset, or a size change in mid-cube.
   - At the app's pace, 8.8 bands/s, no band is lost while the main thread is
     blocked for 2 s.
8. Capture on a received float32 cube runs UC1 and shows its result; on a
   received uint16 cube it runs nothing and says why; on the cube read from disk
   it behaves as before.
9. LiveView from the app appears in the live pane when chosen, and never in the
   laptop camera volume.
10. Received nodes and their UC1 outputs carry `DataOrigin = received` and the
    agreed detail; stand-in data keeps `simulated`.
11. Nothing received survives Disconnect, scene close, Reload or quit beyond
    what `SLIA-035` already allows, and a received cube's memory is freed when
    replaced.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 Fields, v1 and v2, CRC | `RecorderParsingTest.test_headerVersion1ImageIsDescribed`, `test_headerVersion2MetadataIsRecorded`, `test_imageGeometryIsRecorded`, `test_badCrcIsMarked`, `test_nonImageMessageIsLoggedByTypeAndSize`, `test_stringMessageTextIsRecorded`, `test_statusMessageIsRecorded`, `test_otherMessageContentIsPreviewed`, `test_nonFiniteFloatsGiveStrictJson`, `test_allNonFiniteBandGivesNoStatistics` | automated |
| 2 Records the stand-in | `RecorderStandInTest.test_recordsEveryBandAndFrameOfTheStandIn` | automated |
| 3 Band matching | `RecorderCompareCubeTest.test_eachBandIsMatchedInOrder`, `test_flippedBandIsMatchedAsFlipped`, `test_unknownBandMatchesNothing`, `test_uint16CubeIsCompared` | automated |
| 4 Retry, sends nothing | `RecorderStandInTest.test_recordsFromAServerThatStartsLater`, `test_sendsNothingToTheServer` | automated |
| 5 No pixel data; summary | `RecorderStandInTest.test_writesNoPixelData`, `test_summaryNamesMissingBands` (stand-in `--drop-bands`), `RecorderRawServerTest.test_summarySplitsCapturesByGap` | automated |
| 5a Sender's timing | `RecorderRawServerTest.test_arrivalTimesDoNotWaitForSlowDescription` | automated |
| 6 Real protocol recorded | Manual steps A1-A3; document review | manual |
| 7 Assembly | `SLIAFlowTest`: `test_receivedCubeAssemblesBandsByOffset`, `test_receivedCubeOutOfOrderBands`, `test_receivedCubeNamesMissingBands`, `test_receivedCubeLateConnectionMissesFirstBand`, `test_receivedCubeRefusesBadMessages` (CRC, type, components, band number, size change), `test_receivedCubeHeaderVersion1And2`, `test_receivedCubeSurvivesBlockedMainThread` (stand-in on free ports, placeholder cube); `test_iuma_app_standin.py`: `test_hsCubeSendsWholeCubeSubVolumes`, `test_appHeaderSendsVersion1WithoutMetadata`, `test_rawSendsUint16`; `test_igtl_transport.py`: `test_imageSlabMessageParsesInRecorder`; `SLIAFlowTest.test_imageSlabMessageAssembledByOpenIGTLinkIF` | automated |
| 7 Real app | Manual step B1 | manual |
| 8 Capture source | `SLIAFlowTest`: `test_captureOnReceivedFloat32CubeRunsUc1`, `test_captureOnReceivedUint16CubeRunsNothing`, `test_captureOnDiskCubeUnchanged`, `test_receivedCubeWithoutWavelengthGridIsNotClassified` | automated |
| 9 LiveView source | `SLIAFlowTest`: `test_liveViewFromAppShownInLivePane`, `test_liveViewFromAppNeverInLaptopCameraVolume` | automated |
| 10 Provenance | `SLIAFlowTest`: `test_receivedCubeProvenance`, `test_standInCubeStaysSimulated`, `test_uc1OutputsOfReceivedCubeCarryProvenance` | automated |
| 11 Lifetime | `SLIAFlowTest`: `test_receivedCubeFreedOnDisconnect`, `test_receivedCubeFreedOnSceneClose`, `test_receivedCubeReplacedByNextComplete`, `test_readerStopsOnCleanup` | automated |
| 7-10 End to end | Manual steps B1-B3 | manual |

Tests to add, and how each is shown to fail first:

- `tools/simulators/tests/test_igtl_recorder.py`: run before
  `igtl_recorder.py` exists; every test must fail on the import. Reference
  messages are built with pyigtl (v1 and v2) so the parser is checked against
  an independent implementation, and the stand-in runs on free local ports with
  a small placeholder cube written by the test (a fixture that stands for no
  imagery), as in `test_iuma_app_standin.py`.
- `test_badCrcIsMarked` and `test_flippedBandIsMatchedAsFlipped` are also run
  once against a recorder with the CRC check or the flip search disabled, to
  show they catch the omission.

## Manual verification

Phase A, run by the owner. Commands from the repository root in PowerShell.
SLIAFlow must **not** be connected to the app during A2: each port serves one
client, and the recorder must be it.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| A1 | Start `AcquisitionSystemApp` (no hardware needed). In a PowerShell: `cd tools\simulators; ..\..\.venv\Scripts\python.exe -m stratum_sim.igtl_recorder --compare-cube ..\..\input\002-04\raw_data.hdr` | The recorder says it is connected to 18944, 18945 and 18946 (after reading the 1.93 GB compare cube, about 4 s). Without hardware, LiveView and Stereo may send nothing | PASS on the clean rerun: compare cube read in 3.9 s; connected to 18944, 18945 and 18946. The first run stalled under memory pressure before the app cube was closed and was stopped. |
| A2 | In the app: **Load HS Cube**, choose `input\002-04\raw_data.hdr`, wait until it is shown, press **Send Capture**. Wait until the app's console says the transmission ended, then 30 s more | The recorder's console counts HsCube messages up to 109 (or states what it got) | PASS after retrying with the recorder connected before **Send Capture**: 109 `HsCube` IMAGE messages, uint16, 4096 x 2160 x 1. The first attempt joined after transmission began and received 108/109, missing the first band. |
| A3 | Press Ctrl+C in the recorder. Send the folder it names (`workspace\igtl-recordings\...`: `messages.jsonl`, `summary.md`) or paste `summary.md`. Note anything the app's console printed | `summary.md` lists per port the device names, sizes, scalar type, header version, metadata keys, rate, and for HsCube the matched band order | PASS: `workspace\igtl-recordings\manual-real-compare-20260927-1524` contains strict-JSON `messages.jsonl` and `summary.md`; it reports bands 1-109 in order, as stored, no missing/repeated/out-of-order bands, no CRC mismatches, no metadata, and no end-of-cube message. LiveView and Stereo connected but emitted no frames without hardware. |

Phase B (after implementation). Nothing else may be connected to 18946.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| B1 | Start the app, load `input\002-04\raw_data.hdr`. Start SLIAFlow, **Connect**, then **Send Capture** in the app | HsCube row counts to 109 and says the cube is complete; the HS Cube panel shows the received cube, labelled raw uint16 and received from the app; colour preview and pixel spectrum work | |
| B2 | Capture with the received cube as source | UC1 does not run; SLIAFlow says UC1 waits for IUMA's calibrated float32 stream. With the disk cube as source, Capture behaves as before | |
| B3 | Disconnect, then Connect again after pressing **Send Capture** | The late connection names the missing first band(s); no incomplete cube is shown; the previous complete cube is gone after Disconnect | |
| B4 | Stand-in with the calibrated float32 cube: `..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin`, Connect, Capture with the received cube as source | UC1 runs and shows its result; the cube and outputs say simulated (stand-in) | |

## Risks

- ~~The protocol may not say which band a message is.~~ Measured: it does, by
  sub-volume offset. The wavelength is still not sent, so the 460-1000 nm grid
  is an assumption. It holds only for 109 bands, and IUMA is asked (hardware
  document section 7, question 10).
- The float32 version may change the structure despite IUMA's statement. The
  reader refuses what it does not recognise, by name, rather than guessing
  (question 9).
- A reader in Python inside Slicer holds the GIL while it copies about 17.7 MB
  (uint16) or 35 MB (float32) per band. The copy is one numpy slice
  assignment; if the UI stutters measurably during B1, that is reported as a
  finding.
- Peak memory while a second cube is assembled is two cubes, 7.7 GB at
  float32, on a 15.3 GB laptop (`SLIA-034` measured the UC1 limits).
- The app's cube viewer loads the whole 1.93 GB raw cube into RAM, and the
  recorder reads the same cube for comparison: about 4 GB on a 15.3 GB laptop.
  Close Slicer during A1-A3.
- The app needs its hardware to start cleanly; without it the window opens and
  the ports listen (`acquisition_app_and_hardware.md` section 3.1). If Send
  Capture fails without hardware, that is itself a finding to report.
- A uint16 raw cube shown in the HS Cube panel could be mistaken for calibrated
  reflectance. Its caption states it is raw and uncalibrated.
- Received data could be mistaken for a live capture. The provenance says the
  app may be replaying.

## Documentation impact

- `docs/hardware/acquisition_app_and_hardware.md` section 4 and 7: measured
  protocol, remaining questions.
- `docs/development/openigtlink_setup.md`: the recorder, the measured protocol,
  the receiver.
- `tools/simulators/README.md`: the recorder; stand-in assumptions checked.
- Phase B: `extensions/SLIAFlow/README.md`,
  `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`.

## Completion evidence

### Phase A implementation (2026-09-27, uncommitted)

Seen failing first, against the tree without `igtl_recorder.py`
(`.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`): 36 run,
errors=1, `ImportError: cannot import name 'igtl_recorder' from 'stratum_sim'`,
which fails every recorder test.

With the recorder in place, run again with its CRC check forced to pass and its
flip search limited to "as stored":

- `test_badCrcIsMarked`: `AssertionError: True is not false`.
- `test_flippedBandIsMatchedAsFlipped`: `AssertionError: None != {'band': 3,
  'orientation': 'flipped top to bottom'}`.

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | both targets `All checks passed!` (after fixing two B905 `zip` findings in the recorder) | 0 |
| Simulators | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 49 run, OK (14 new) | 0 |
| `git diff --check` | | nothing reported | 0 |

The Slicer suites were not run: phase A changes nothing under `extensions/`.

Full-size check, stand-in serving `002-04`'s calibrated cube, recorder
`--compare-cube ..\..\input\002-04\LCTF_Calibrated_Cube_Single.hdr --duration
30`: HsCube 109 of 109 bands matched `1-109`, as stored, 6.3 bands/s, header
version 2, no CRC mismatch; LiveView and Steroscopic 10.0 frames/s. Reading the
raw 1.93 GB `raw_data.hdr` as compare cube takes 3.9 s and gives 109 distinct
bands, so every band of the real measurement can be told apart.

New tests: `RecorderParsingTest` (`test_headerVersion1ImageIsDescribed`,
`test_headerVersion2MetadataIsRecorded`, `test_imageGeometryIsRecorded`,
`test_badCrcIsMarked`, `test_nonImageMessageIsLoggedByTypeAndSize`),
`RecorderCompareCubeTest` (`test_eachBandIsMatchedInOrder`,
`test_flippedBandIsMatchedAsFlipped`, `test_unknownBandMatchesNothing`,
`test_uint16CubeIsCompared`), `RecorderStandInTest`
(`test_recordsEveryBandAndFrameOfTheStandIn`, `test_summaryNamesMissingBands`,
`test_writesNoPixelData`, `test_recordsFromAServerThatStartsLater`,
`test_sendsNothingToTheServer`).

### Phase A rework after a review of the working tree (2026-09-27)

The review raised four points. The first, whether the recorder describes the
real stream, can only be answered by manual steps A1-A3. The other three were
fixed:

- Timing: arrival was stamped by the thread that then described the message,
  so a slow description delayed the next read and the rate and gaps could be
  the recorder's. Readers now only read and time-stamp; one thread describes.
- Several captures: all bands on a port were one sequence, so a second send
  read as repeated and out-of-order bands, and messages other than IMAGE were
  logged without content. Bands are now split into captures by a gap, each
  with its own checks and the messages that followed it; STRING and STATUS
  text and the head of other types are logged.
- NaN: a float band containing NaN wrote `NaN` into `messages.jsonl`.
  Statistics now use finite values and count the others, and every line is
  strict JSON.

Also fixed: four command paths in the evidence above whose backslashes had
become control characters.

Seen failing first, with the tests written before the fix: 7 new tests,
`KeyError: 'text'`, `'status'`, `'contentHead'`, `nan is not None`,
`Tuples differ: (nan, nan) != (-2.0, 1.0)`, `unexpected keyword argument
'captureGapSec'`, and `1.25 not less than 0.3 : Arrival times include the time
spent describing earlier messages`.

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Static analysis | `.\scripts\development\run-python-quality.ps1` | `All checks passed!` | 0 |
| Simulators | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 56 run, OK (21 recorder tests) | 0 |
| `git diff --check` | | nothing reported | 0 |

Full-size check again, stand-in serving `002-04`'s calibrated cube, recorder
`--duration 55`: 1258 messages, every line strict JSON, no CRC mismatch.
HsCube: 2 captures, the first 1-109 as stored in 17.7 s (6.1 bands/s), the
second 1-48 when the run stopped (missing 49-109, as expected). LiveView and
Steroscopic 10.0 frames/s. Longest wait before a message was described 0.03 s,
readers never held back, so the earlier 6.3 bands/s was the stand-in's pace,
not the recorder's.

Waiting for the owner: manual steps A1-A3 with the real app.

### Manual verification evidence (2026-09-27)

- The real IUMA app was launched from `C:\Program Files\IUMA\InstallerAcquisitionApp\AcquisitionSystemApp.exe` with no hardware. It listened on 18944, 18945 and 18946.
- The successful recording is `workspace\igtl-recordings\manual-real-compare-20260927-1524`. It captured 109/109 `HsCube` IMAGE messages, matched raw cube bands 1-109 in order and as stored, observed header version 1, uint16 pixels, 4096 x 2160 x 1 sub-volumes, no metadata, no CRC mismatches, and no explicit end-of-cube message. `messages.jsonl` contains 109 strict-JSON lines and no pixel-data fields.
- A controlled stand-in break test started the recorder before the server and dropped bands 2 and 4. The recorder retried successfully, recorded v2 metadata and bands 1, 3 and 5, and reported missing bands 2 and 4 without writing pixel data.
- Resource/ordering findings: reading the 1.93 GB comparison cube stalled on the first run while other large processes were resident; after freeing the app cube it completed in 3.9 s. A recorder that joined after the app began sending received 108/109 bands; a recorder connected before **Send Capture** received all 109. This confirms the real stream has no replay/end marker and that a late client can miss the beginning of a capture.

### Protocol written down (criterion 6, 2026-09-27)

Checked from `messages.jsonl` before writing it down:

- Every one of the 109 messages declares size 4096 x 2160 x 109 and carries
  the sub-volume 4096 x 2160 x 1 at offset (0, 0, k), k from 0 to 108.
- Offset k + 1 equals the band its pixels matched, 109 of 109.
- The header timestamp is 0 in every message.
- The late client's 108 messages (`manual-real-20260927-1515b`) were offsets
  1-108, so the band it missed is identified by the offset alone.

OpenIGTLinkIF's handling of such messages was read in the pinned
`OpenIGTLinkIO/Converter/igtlioImageConverter.cxx`. It builds a full-size
volume, copies each slab to its offset, and reuses the volume without
clearing it.

Written into:

- `docs/hardware/acquisition_app_and_hardware.md`: new section 4.1, the
  `[meas]` source tag, and questions 9-12 in section 7.
- `docs/development/openigtlink_setup.md`: "Measuring what a server sends".
- `tools/simulators/README.md`: each stand-in assumption marked confirmed,
  wrong or not measurable, and the real-app check.
- This card: context, and phase B finalised.

## Review findings

## Human approval
