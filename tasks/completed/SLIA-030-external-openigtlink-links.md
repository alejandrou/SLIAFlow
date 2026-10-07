---
id: SLIA-030
title: Measure IUMA's acquisition app protocol with a recorder
status: completed
branch: feature/SLIA-030-external-openigtlink-links
priority: medium
depends_on: SLIA-035, SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-030 - Measure IUMA's acquisition app protocol with a recorder

> **Scope split on 2026-10-06.** This card was planned in two phases. Only
> phase A, the recorder and the measured protocol, was implemented, verified
> and moved to `tasks/completed/` (commit `7873e7e`). Phase B, receiving the
> cube and using it, was never implemented. At the project owner's request it
> moved to `SLIA-036` (the HS Cube reader, the received cube in the HS Cube
> panel and as Capture source, provenance, the stand-in's measured protocol)
> and `SLIA-037` (LiveView from the app in the live pane). This card now holds
> phase A only; phase B's specification, criteria 7-11, test rows and manual
> steps B1-B4 are in those cards.

## Goal

Connect to IUMA's real acquisition app with a recorder outside Slicer and
write down exactly what it sends, so that SLIAFlow's receiver (`SLIA-036`) is
built on measured facts rather than on the stand-in's assumptions.

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

### Phase B - moved

Phase B, finalised on 2026-09-27 from the measurement, was never implemented.
Its specification moved to `SLIA-036` and `SLIA-037` on 2026-10-06.

## Out of scope

- Receiving, assembling, showing or classifying the app's cube in SLIAFlow
  (`SLIA-036`), and LiveView from the app (`SLIA-037`).
- Sending anything back to the app (commands, parameters, Capture HSI).
- White/dark calibration in SLIAFlow.
- PLUS (`ADR-0004` decision 9).
- UC2 (`SLIA-021`).

## Files allowed

Phase A:

- `tools/simulators/stratum_sim/igtl_recorder.py` (new)
- `tools/simulators/tests/test_igtl_recorder.py` (new)
- `tools/simulators/README.md`
- `docs/hardware/acquisition_app_and_hardware.md`
- `docs/development/openigtlink_setup.md`
- `tasks/active/SLIA-030-external-openigtlink-links.md`

Phase B's files are listed in `SLIA-036` and `SLIA-037`.

Also touched on this branch at the owner's request (2026-09-27), outside the
task: `tasks/active/SLIA-034-uc1-performance-and-large-cubes.md` deleted. It
was a stale copy re-added by `012f59d`; the completed card is in
`tasks/completed/`.

The built copy under `build\SLIAFlow` is regenerated by
`scripts\development\build-sliaflow.ps1 -Configure` and never edited by hand.

## Relevant skills and references

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

Phase B (steps 6-8) moved to `SLIA-036`.

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

Phase B's criteria 7-11 moved to `SLIA-036` and `SLIA-037`.

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

Phase B's manual steps B1-B4 moved to `SLIA-036` and `SLIA-037`.

## Risks

- ~~The protocol may not say which band a message is.~~ Measured: it does, by
  sub-volume offset. The wavelength is still not sent, so the 460-1000 nm grid
  is an assumption. It holds only for 109 bands, and IUMA is asked (hardware
  document section 7, question 10).
- The float32 version may change the structure despite IUMA's statement
  (question 9). Carried into `SLIA-036`.
- The app's cube viewer loads the whole 1.93 GB raw cube into RAM, and the
  recorder reads the same cube for comparison: about 4 GB on a 15.3 GB laptop.
  Close Slicer during A1-A3.
- The app needs its hardware to start cleanly; without it the window opens and
  the ports listen (`acquisition_app_and_hardware.md` section 3.1). If Send
  Capture fails without hardware, that is itself a finding to report.

## Documentation impact

- `docs/hardware/acquisition_app_and_hardware.md` section 4 and 7: measured
  protocol, remaining questions.
- `docs/development/openigtlink_setup.md`: the recorder, the measured protocol,
  the receiver.
- `tools/simulators/README.md`: the recorder; stand-in assumptions checked.

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

Moved to `tasks/completed/` by the project owner in commit `7873e7e`, with
phase A done. The split of phase B into `SLIA-036` and `SLIA-037` was asked
for by the project owner on 2026-10-06.
