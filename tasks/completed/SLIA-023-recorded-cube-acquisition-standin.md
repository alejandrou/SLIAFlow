---
id: SLIA-023
title: Accept recorded HSI cubes and stand in for the acquisition trigger
status: completed
branch: feature/SLIA-023-recorded-cube-acquisition-standin
priority: high
depends_on: SLIA-011, SLIA-014
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-023 - Accept recorded HSI cubes and stand in for the acquisition trigger

## Goal

Let the tooling read the recorded HSI cases in `input/bin/bin/` without weakening
the guard that stops it processing data it has no business processing, and make
the acquisition stand-in behave like theatre equipment: camera on LiveView, wait
for a trigger, hold a capture delay, publish the cube, announce where it is.

## Context

Workstreams A and B of `docs/architecture/WP5_MS5_DEMO_PLAN.md`. They are one
card because neither can be tested without the other: a reader with nothing to
read is untestable, and a stand-in with no readable cube has nothing to publish.

61 recorded cases were audited on 2026-09-11 and every one of them fits the
pipeline contract unchanged: 93 bands, ENVI data type 12, `interleave = bsq`, and
all three `.dat` files exactly `samples * lines * bands * 2` bytes. All 61 share
one wavelength grid, 440 to 900 nm in 5 nm steps. Nine cases are larger than the
`full` preset; the largest, `058-02` at 752x721, scales from the recorded UC1
measurement to roughly 3.5 GiB of GPU memory against 8151 MiB available.

The dataset is the public, anonymized *HSI Human Brain Database* published by
ULPGC. `input/` is gitignored and no case enters version control.
`.ai/policies/medical-data-policy.md` records the approval and its conditions.

Selected on 2026-09-13 by the begin-task workflow. `SLIA-018` and this card are
the two eligible `high` cards; the WP5 plan's execution order puts this card
first, and both `SLIA-017` and `SLIA-018` are written to cover the producers this
card adds, so taking them first would leave them to be reopened.

### What the plan's first draft got wrong, and this card corrects

The draft described Workstream A as one small change: teach `envi.py` to accept
`HSI Human Brain Database` as a second approved marker alongside
`STRATUM SIMULATED CUBE`. Two measurements say it is not one small change.

**The marker is not in `raw.hdr`.** It is in the sibling `gtMap.hdr`, on a single
line. `envi.loadDataset` reads only `raw.hdr`, so matching the string in the file
it already reads would never match anything.

**`parseHeaderText` crashes on a recorded header before any marker check is
reached.** Recorded headers close the wavelength block with `}` appended to the
last value rather than on a line of its own, and they place `lines` and `samples`
*after* the block:

```
wavelength = {440, 445, 450, 455, 460, 465,
...
890, 895,  900}
lines = 389
samples = 345
```

`parseHeaderText` only leaves the wavelength block on a line that *starts* with
`}`, so it stays inside it and tries to parse the next line as a number.
Reproduced again on 2026-09-13, on `main` at `3ff2f38`:

```
>>> envi.loadDataset(Path('../../input/bin/bin/004-02'))
  File "...\stratum_sim\envi.py", line 138, in parseHeaderText
    wavelengths.append(float(token))
ValueError: could not convert string to float: 'lines = 389'
```

That is also the wrong exception type: a folder this module cannot read should
raise `DatasetReadError`, which is what every caller is written to handle.

The defect is on our side only. UC1's own C parser scans for `bands`, `lines` and
`samples` anywhere and stops after three hits, and UC2's `read_hdr_file` handles
keys in any order; both read the recorded headers correctly today.

### Measured on 2026-09-13 while specifying

- **Every one of the 61 `raw.hdr` files has the same layout**: LF line endings,
  keys in the order `bands, data type, interleave, header offset, wavelength
  units, byte order, wavelength, lines, samples`, and no line starting with `}`.
  There is no second recorded layout to accommodate.
- **Every one of the 61 `gtMap.hdr` files carries the marker**, and every one of
  them uses **CR-only** line endings, which is why the file prints as a single
  line. Identification is a substring test, so it does not depend on line
  endings.
- **Every case folder holds the same eight files**: `raw`, `whiteReference` and
  `darkReference` as `.dat` and `.hdr`, plus `gtMap` and `gtMap.hdr`.
- **pyigtl 0.3.4 cannot be driven by successive one-shot clients unless the
  server sends.** `TCPRequestHandler.handle` treats an empty `recv` as "no
  message" rather than as end of stream, so the handler for a client that has
  left keeps looping, `is_connected()` stays `True`, and the next client waits in
  the accept backlog. Probed with a server and three successive clients each
  connecting, sending one STRING and leaving:

  | Server behaviour | Clients whose trigger arrived | Replies received |
  | --- | --- | --- |
  | Receive only | A only | A only |
  | Also sends a STRING every 0.5 s while connected | A, B, C, each within 0.2 s | all three |

  A failed send is the only thing that releases the dead handler. So the control
  channel publishes its state periodically, and that is a load-bearing
  requirement, not decoration.

### Two constraints on the stand-in the draft did not state

**A `recorded` source is a new scene mode, not a flag.** `config.py` rejects
`sceneMode = tissue` with `frameSource = webcam`, and `channel` mode builds the
cube *from* the camera frame. Streaming the webcam on LiveView while the cube
comes from disk is a third combination that no existing setting expresses.

**Only one process can hold the laptop camera.** If this stand-in opens the
webcam for LiveView, SLIAFlow's own `SLIA-005` camera path must not also open it,
or one of the two gets nothing and looks broken.

### Where the capture button lives

The button belongs in Slicer, so the Slicer half of the control channel - an
outgoing text node on a third connector - is new SLIAFlow behaviour and belongs
with `SLIA-022`, not here. This card delivers the producer half: the stand-in
listens on 18950, acts on a trigger STRING from any client, and announces the
result. Until `SLIA-022` lands, the trigger is sent by a one-shot client started
from the launcher console, which is enough to demonstrate and test this side on
its own.

### Three device names on the control channel, not one

The roadmap names the channel `Control`. On the wire it carries three device
names: `CaptureTrigger` towards the stand-in, and `CaptureReply` and
`CaptureStatus` back from it.

- **Direction.** A Slicer OpenIGTLink connector updates the node of the same name
  when a message arrives, and an outgoing node that is modified is sent again; a
  single device name used in both directions would echo the stand-in's own
  status back to it as a command. Separate names make that loop unrepresentable
  rather than guarded.
- **Reply versus state.** pyigtl keeps only the latest message per device name
  on the receiving side (`incoming_messages[device_name] = message`). An answer
  to a trigger sent on the same name as the periodic state would be overwritten
  by the next state message before a client polled for it. So the one answer to
  a trigger goes out as `CaptureReply`, and the state as `CaptureStatus`.
- **Correlation.** Each capture carries a number, so a client can tell the
  `READY` that answers its own trigger from a `READY` left over from an earlier
  capture that the heartbeat is still repeating.

## Requirements

### Reading recorded cubes

- `envi.parseHeaderText` parses a wavelength block that is closed by `}` at the
  end of a value line, and continues parsing key/value lines after it. Header key
  order stops mattering.
- A folder that cannot be read as a dataset raises `DatasetReadError`, never a
  bare `ValueError` from a parse attempt.
- A recorded case is identified as an approved dataset by the
  `HSI Human Brain Database` marker in its sibling `gtMap.hdr`, and by nothing
  else. The identification is read from the data; there is no flag to pass and
  no flag to forget.
- `DatasetRef` distinguishes the two approved kinds without adding a third data
  origin. `simulated` keeps meaning "this simulator wrote it"; a new `recorded`
  field means "a database case"; `approvedInput` is true for either. Both travel
  as `simulated` on the wire.
- A folder that identifies as neither is refused exactly as it is today, with the
  same wording and the same `--force-unmarked` override.
- The write-side overwrite interlock is unchanged. A recorded case is never a
  write target, and `_assertTargetIsSafe` keeps refusing any folder whose
  `raw.hdr` lacks the simulator's own marker.

### Provenance wording

- `uc1_runner.py` accepts a recorded case without `--force-unmarked`, and its
  simulation detail names what the cube actually is:
  `real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`.
- The existing phantom and synthetic-input details are unchanged for the datasets
  they describe. No text the runner prints or sends about a recorded case calls
  the cube synthetic, because that claim is false in the direction that
  understates what is on screen. That includes the per-cycle banner and the
  single-class warning, which today say "synthetic cube" and "synthetic scene"
  unconditionally.
- The origin on the wire stays `simulated` for every case. `simulated` means the
  acquisition event was simulated; the detail says what the cube is. No third
  origin and no change to SLIAFlow.
- The acquisition stand-in in `recorded` mode does not print the
  `SIMULATED, NON-CLINICAL DATA ... not patient data` notice, which would be
  false. It prints a notice naming the public database and the case, stating that
  the acquisition is simulated and that nothing derived from it is a clinical
  result.

### The acquisition stand-in

- Scene mode `recorded` selects a case by name (`case`) under a root
  (`recordedRoot`) that defaults to `input/bin/bin`. The case must identify as a
  recorded database case; anything else is refused before a port opens.
- The case folder is opened read-only and **nothing is written**: no file in it
  is created, modified or removed. `input/` is untouched after a session.
- LiveView streams the laptop camera (`frameSource = webcam`) on port 18944, and
  no other source. Changed on 2026-09-14 by the project owner's decision that a
  recorded session shows recorded data and nothing made up: the `synthetic`
  source this card first kept for a machine without a camera is refused in
  `recorded` mode, the command line defaults to `webcam` there, and the launcher
  has no `-FrameSource`. Tests inject a still-frame test double and never open
  the camera.
- The control channel listens on port 18950. It acts on a `CaptureTrigger`
  STRING. Every message it sends starts with one upper-case word, and `folder=`
  is always last so that a path containing spaces is simply the rest of the line.
  - `CaptureReply`, exactly one per trigger:
    - `CAPTURING capture=<n> case=<case> delay=<seconds>` - the trigger started
      capture `n`;
    - `IGNORED capture <n> already in progress` - a capture was running;
    - `REFUSED unknown command <text>` - the text was not `CAPTURE`.
  - `CaptureStatus`, the current state, every 0.5 s while a client is connected,
    for the reason measured above:
    - `IDLE` - no capture has been taken yet;
    - `CAPTURING capture=<n> case=<case> delay=<seconds>`;
    - `READY capture=<n> case=<case> folder=<absolute case folder>` - capture
      `n` is complete.
- On a trigger the stand-in holds a capture delay drawn uniformly between
  `captureDelayMinSec` (default 5) and `captureDelayMaxSec` (default 8), then
  publishes the raw cube on port 18947 as device `HSCube` and reports `READY`.
  LiveView keeps streaming throughout the delay.
- `HSCube` is a single-component `uint16` IMAGE of shape `(bands, lines, samples)`
  in pyigtl's `(k, j, i)` order, unrotated, identity matrix, LPS, header version
  2. So k is the band index, and the cube's (j, i) grid is the UC1 map's grid.
  Its metadata carries `SLIAFlow.DeviceName`, `SLIAFlow.DataOrigin = simulated`,
  `SLIAFlow.SimulationDetail =
  acquisition stand-in, recorded HSI case <case> (simulated acquisition)`,
  `SLIAFlow.WavelengthsNm` (comma-separated, one per band) and
  `SLIAFlow.DatasetFolder`.
- A completed cube is sent once, to the client connected on 18947 at that moment
  or to the next one that connects. `READY` is reported either way: in Mode A the
  algorithms read the announced folder from disk.
- An instant capture (both delay bounds zero) is selectable.
- The stand-in opens exactly three ports: LiveView, HSCube and Control. The
  stereoscopic port 18948 and the StO2 port 18949 are never bound.
- A trigger arriving while a capture is already running is answered `IGNORED` and
  dropped, not queued.
- Configuration refuses `recorded` without a `case`, a `case` outside `recorded`
  mode, a `case` that is not a plain folder name, and delay bounds that are
  negative or inverted.

### The one-shot trigger client

- `python -m stratum_sim capture` connects to the control port, sends one
  `CAPTURE`, prints its reply and each change of state, and exits once the answer
  to its own trigger is final: 0 on `READY` for the capture its trigger started,
  2 on `IGNORED`, 1 on `REFUSED`, on no connection, or on timeout. It then
  disconnects, so the next trigger client can be served.
- With `--no-wait` it exits 0 as soon as its capture has started. pyigtl serves
  one client at a time, so a client waiting for `READY` would hold the control
  port for the whole delay, and a second trigger would be read only after the
  first capture - starting a new capture instead of being answered `IGNORED`.

### The launcher

- `run-end-to-end-session.ps1` gains `-Case`, `-DatasetRoot` (the recorded root)
  and `-InstantCapture`. A recorded session always streams the laptop camera;
  the `-FrameSource` switch first added here was removed on 2026-09-14.
- With `-Case`, the port preflight covers 18944, 18945, 18947 and 18950, and the
  stale-client check covers the same ports. Shutdown reports on all four, and
  separately confirms nothing listens on 18948 or 18949.
- The `c` key starts one trigger client with `--no-wait` and tails its output
  into the console, reporting its exit code as started, ignored or failed.
- With `-Case`, the map producer is not started up front. It starts on the case
  folder when the stand-in first logs a capture as `READY`, which is the camera →
  capture → cube → UC1 order the plan demonstrates.
- With `-Case`, `-MapProducer standin` and the `s` swap are refused with a
  reason: the arithmetic stand-in's marker interlock lives in `uc1_maps.py`,
  which this card does not touch, and it refuses a recorded case.
- Without `-Case`, the session behaves exactly as it does today.

## Out of scope

- Any change to `extensions/`, including the capture button and the Slicer side
  of the control channel. Those are `SLIA-022`.
- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- A third data origin, a provenance ADR, or capture identifiers.
- The pseudo-RGB background and the overlay, which are `SLIA-024`.
- Emulating the band-by-band sweep in real time.
- Fanning one cube out to several network consumers.
- Any metric computed against `gtMap`. The file's header is read for its marker
  and for nothing else; `gtMap` itself is never opened.
- Refusing a reserved port by name when a producer is asked to bind one. That
  guard is `SLIA-017`; this card only guarantees that the stand-in's own port set
  excludes them.
- Letting the arithmetic stand-in accept a recorded case. It would need
  `uc1_maps.py`, and nothing in the WP5 plan runs it over recorded data.
- Warning about a second client on a port. That is `SLIA-018`.

## Files allowed

- `tools/simulators/stratum_sim/envi.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/stratum_sim/config.py`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/capture_client.py` (new)
- `tools/simulators/stratum_sim/__main__.py`
- `tools/simulators/tests/**`
- `tools/simulators/README.md`
- `config/local.example.json`
- `scripts/development/run-end-to-end-session.ps1`
- `docs/development/pipeline_test_quickstart.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `tasks/{backlog,active,review,completed}/SLIA-023-recorded-cube-acquisition-standin.md`

`__main__.py`, `capture_client.py`, `config/local.example.json` and
`SLIAFLOW_UC1_IMAGE_CONTRACT.md` were added while specifying: the trigger client
needs an entry point, the new settings are documented in the example block the
loader's own docstring points to, and the image contract lists every
`SimulationDetail` value a producer sends.

## Relevant skills and references

- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstreams A and B
- `.ai/policies/medical-data-policy.md`, the approved-dataset entry
- `tools/simulators/stratum_sim/envi.py`, `parseHeaderText` and `loadDataset`
- `tools/simulators/stratum_sim/config.py`, the scene-mode validator
- `pyigtl.comm.OpenIGTLinkBase.get_latest_messages` and `TCPRequestHandler.handle`
  in pyigtl 0.3.4, for the control channel's receive side and the dead-handler
  behaviour
- `SLIA-017` and `SLIA-018`, both of which this card multiplies by adding ports
- `SLIA-022`, which writes the Slicer side against the message names above

## Approved dependencies

None. The control channel uses `pyigtl`'s existing STRING message support.

## Implementation plan

1. Write the tests below and record each one failing against `main`.
2. Fix `parseHeaderText` and the exception type, then add the `gtMap.hdr`
   identification and `DatasetRef.recorded`.
3. Change the UC1 runner's gate and wording for a recorded case.
4. Add the `recorded` scene mode and its configuration checks.
5. Add the capture controller, the control channel, the `HSCube` publication and
   the trigger client.
6. Extend the launcher and the documentation.
7. Run the simulator suite, Ruff, and the Slicer suite; record the results.

## Acceptance criteria

1. `envi.loadDataset` reads every one of the 61 recorded cases and returns the
   dimensions and the 93-value wavelength grid its header states.
2. A header that cannot be parsed raises `DatasetReadError`, not a parse
   exception.
3. A recorded case is identified from the marker in `gtMap.hdr`, and the marker
   anywhere else does not identify one.
4. A folder that identifies as neither kind is refused by the UC1 runner with
   today's wording and today's override.
5. A recorded case is refused as a write target.
6. The UC1 runner accepts a recorded case without `--force-unmarked`, and its
   detail names the case, keeps the origin `simulated`, and never says
   `synthetic`.
7. The runner's per-cycle banner never calls a recorded cube synthetic.
8. The recorded stand-in leaves the case folder byte-identical, with no file
   added or removed.
9. A trigger produces, after the configured delay and not before, one `HSCube`
   publication and a `READY` announcement naming the folder.
10. A trigger during a capture is answered `IGNORED` and does not start a second
    capture.
11. The recorded stand-in opens exactly its LiveView, HSCube and Control ports,
    and never 18948 or 18949.
12. Over real sockets, a trigger client receives `READY` naming the folder and an
    HSCube client receives a `(bands, lines, samples)` `uint16` image with the
    recorded detail in its metadata.
13. Successive one-shot trigger clients are each served.
14. Recorded-mode configuration refuses a missing case, a case outside recorded
    mode, a case that is not a plain name, and inverted or negative delays.
15. The recorded stand-in's notice never says the data is synthetic or not
    derived from patient data.
16. `input/` is untouched after a full session.
17. The launcher runs a full session with `-Case 004-02`, captures on `c`, starts
    UC1 on `READY`, and tears down with nothing left listening.
18. The largest case, `058-02`, either completes through UC1 with its GPU figure
    recorded, or its memory failure is recorded as a finding. Deferred on
    2026-09-14 by the project owner until the pipeline is complete.
19. A recorded session takes LiveView from the laptop camera only: configuration
    refuses any other frame source in `recorded` mode, the command line defaults
    to the camera, and the LiveView detail names the laptop camera and never says
    `synthetic`. Added on 2026-09-14.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. All 61 cases load | `test_envi.RecordedCaseTest.test_parsesHeaderWithTrailingBraceAndLateKeys`, then Manual step 1 over the real folder | automated + manual |
| 2. Unparsable header raises `DatasetReadError` | `test_envi.RecordedCaseTest.test_unparsableHeaderRaisesDatasetReadError` | automated |
| 3. Identified from `gtMap.hdr` only | `test_envi.RecordedCaseTest.test_recordedCaseIsIdentifiedFromGtMapMarker` and `test_markerOutsideGtMapDoesNotIdentifyARecordedCase` | automated |
| 4. Neither kind is refused as today | `test_uc1_runner.RecordedCaseRunnerTest.test_unidentifiedFolderIsStillRefused` | automated |
| 5. Never a write target | `test_envi.RecordedCaseTest.test_recordedCaseIsNeverAWriteTarget` | automated |
| 6. Runner accepts and names a recorded case | `test_uc1_runner.RecordedCaseRunnerTest.test_recordedCaseRunsWithoutForceUnmarked` and `test_recordedCaseDetailNamesTheCase` | automated |
| 7. Banner never says synthetic | `test_uc1_runner.RecordedCaseRunnerTest.test_runnerTextNeverCallsARecordedCubeSynthetic` | automated |
| 8. Writes nothing | `test_acquisition_sim.RecordedCaptureTest.test_recordedSourceDoesNotWrite` | automated |
| 9. Cube after the delay, not before | `test_acquisition_sim.CaptureControllerTest.test_triggerPublishesCubeAfterDelay` | automated |
| 10. Trigger during capture ignored | `test_acquisition_sim.CaptureControllerTest.test_triggerDuringCaptureIsIgnored`, `test_unknownCommandIsRefusedByName` for the `REFUSED` answer, and `RecordedCaptureWireTest.test_aTriggerDuringACaptureIsAnsweredIgnoredOverTheWire` for the same over real sockets with the launcher's `--no-wait` client | automated |
| 11. Only its own ports | `test_acquisition_sim.RecordedCaptureTest.test_standInOpensOnlyItsOwnPorts` | automated |
| 12. Over the wire | `test_acquisition_sim.RecordedCaptureWireTest.test_captureOverTheWireDeliversCubeAndReadiness` | automated |
| 13. Successive one-shot clients | `test_acquisition_sim.RecordedCaptureWireTest.test_successiveTriggerClientsAreEachServed` | automated |
| 14. Configuration refusals | `test_config.RecordedModeConfigurationTest.test_recordedModeRequiresAPlainCaseName` and `test_recordedSettingsOutsideRecordedModeAreRejected` and `test_captureDelayBoundsMustBeOrdered` | automated |
| 15. Notice never says synthetic | `test_acquisition_sim.RecordedCaptureTest.test_recordedNoticeNeverCallsTheCubeSynthetic` | automated |
| 16. `input/` untouched | Manual step 2 | manual |
| 17. Launcher session | Manual steps 3, 4 and 5 | manual |
| 18. Largest case | Manual step 6 (deferred by the project owner) | manual |
| 19. Laptop camera only | `test_config.RecordedModeConfigurationTest.test_recordedLiveViewComesOnlyFromTheLaptopCamera`, `test_acquisition_sim.RecordedCaptureTest.test_recordedCommandLineTakesTheLaptopCameraByDefault` and `test_recordedLiveViewIsLabelledAsTheLaptopCamera`, then Manual step 3 | automated + manual |

Test data. The unit tests never read `input/`. They build tiny test case folders
with a helper in `tests/support.py` that reproduces the recorded layout - the
trailing brace, `lines` and `samples` after the block, LF in `raw.hdr`, CR in
`gtMap.hdr`, and the marker text - around counting-placeholder `uint16` arrays,
and they feed LiveView from a still-frame test double rather than the camera. The parser
test embeds the text of `004-02/raw.hdr` verbatim: it holds dimensions and a
wavelength list and no image content, and it is the authority for the layout the
parser must accept.

Tests to add or change, and how each one will be shown to fail first:

- Every `RecordedCaseTest`, `RecordedCaseRunnerTest` and `RecordedCaptureTest`
  fixture uses the recorded header layout, so against `main` each of them fails
  at `loadDataset` with the recorded
  `ValueError: could not convert string to float: 'lines = 389'` (or the tiny
  fixture's equivalent) before its own assertion is reached. That is a real
  failure of the criterion - a recorded case cannot be read at all - and it is
  recorded as such.
- `test_unparsableHeaderRaisesDatasetReadError` uses a simulator-layout header
  with a non-numeric wavelength, so against `main` it fails with a bare
  `ValueError` rather than at the recorded layout.
- `test_recordedCaseIsNeverAWriteTarget` passes on `main`, because the write
  interlock already refuses the folder. It is a regression guard, so it is shown
  failing against a deliberate mutation of `_assertTargetIsSafe` that returns
  early for an approved dataset, and the mutation is reverted.
- `test_recordedSourceDoesNotWrite` hashes every file, its size, its
  modification time and the file list of the case folder before and after. Its
  failure is shown against a deliberate mutation that writes the phantom record
  the existing write path puts beside a dataset.
- `CaptureControllerTest`, `RecordedCaptureWireTest` and the configuration tests
  fail on `main` because the recorded mode does not exist. That shows only that
  they are not vacuous, so each behavioural claim is also shown failing against
  a mutation: a trigger that completes its capture at once, for the delay test;
  no repeated state on the control channel, for the successive-clients test; and
  a trigger client that ignores `--no-wait`, for the over-the-wire `IGNORED`
  test, which was added with that option.
- The existing `test_datasetWithoutAPhantomRecordKeepsTheOriginalDetail`,
  `MarkerInterlockTest` and `test_datasetRefRoundTripsFromWrittenFolder` are not
  modified; they are the evidence that the simulator path is unchanged.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Load every folder under `input/bin/bin` with `envi.loadDataset` | All 61 load; each reports `recorded` true, 93 bands and a 93-value grid from 440 to 900 nm | 2026-09-14, run by Claude at the owner's request: 61 folders, every one `recorded=True bands=93 grid=93 440-900 nm`, 0 not as expected. `058-02` reads 752x721. |
| 2 | Hash `input/bin/bin` and record every file's modification time before and after a full session on `004-02` | Identical; no file in `input/` was created, written, touched or removed | 2026-09-14, run by Claude, twice: SHA-256, size and mtime of all 488 files plus the mtime of every folder, 549 entries before and 549 after each session; `added=[] removed=[] changed=[]` both times. |
| 3 | Run `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer`, press `c`, and watch the console | `capture-1` reports `CAPTURING capture=1` with a delay between 5 and 8 s and finishes with exit code 0; after the delay `[acq]` logs `Capture 1 complete: READY ... folder=...\input\bin\bin\004-02`; the launcher then starts the UC1 runner on that folder, whose `Origin:` line names recorded HSI case 004-02 | 2026-09-14, run by Claude with the laptop camera, keys typed into the session console's input buffer. Second run, after the camera-only change: `LiveView from the laptop camera (index 0)`; `CAPTURING capture=1 case=004-02 delay=5.9`, `capture-1 finished with exit code 0`; `Capture 1 complete: READY capture=1 case=004-02 folder=C:\stratum\input\bin\bin\004-02`; UC1 started after it, `Origin: simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`, `Time simulation ---> 531.844 ms`. The first run, before the change, gave delay 6.3 and the same sequence. No line in the second transcript contains "synthetic". |
| 4 | While a capture is running, press `c` again | `capture-2` reports `IGNORED capture 1 already in progress` and finishes with exit code 2; exactly one `READY` follows | 2026-09-14, run by Claude, 1.5 s after the first `c`, in both runs: `IGNORED capture 1 already in progress`, `capture-2 finished with exit code 2`; one `READY capture=` line in each transcript. |
| 5 | During the session, `netstat -ano \| findstr "18948 18949"`; then press `q` | Nothing listens on 18948 or 18949; at shutdown the launcher reports nothing listening on 18944, 18945, 18947 or 18950 | 2026-09-14, run by Claude, in both runs: `findstr` found nothing during the capture and again with UC1 listening (exit 1); after `q`: `Nothing is listening on the reserved ports 18948 or 18949.` and `Nothing is listening on 18944, 18945, 18947, 18950. No socket was left held.`; `netstat` afterwards showed none of the six ports. |
| 6 | Run a session on `058-02`, the largest case, and press `c` | Either UC1 completes and its GPU memory figure is recorded, or it fails on memory and the failure is recorded as a finding rather than worked around | Not run. Deferred on 2026-09-14 by the project owner: the large cubes are to be tested once the pipeline is finished, to see how it performs then. |
| 7 | Run `run-end-to-end-session.ps1 -Case 004-02 -MapProducer standin` | The launcher refuses before starting anything and says why | 2026-09-14, run by Claude: refused after 0.1 s with `ERROR: -MapProducer standin cannot run on a recorded case: the arithmetic stand-in's marker interlock accepts only datasets this simulator wrote. A recorded session uses the genuine pipeline.`; nothing listening afterwards. |

## Risks

The provenance wording is the one place this card can do real harm. A recorded
human-brain cube displayed under a detail saying `synthetic input` understates
what is on screen, which is the direction of error that the banner and demo-mode
interlock do not protect against - they guard against simulated data being taken
for real, not against real data being dismissed as simulated. The wording change
is therefore a requirement, not a nicety, and it extends to every console line
that currently says "synthetic" unconditionally.

Adding two bound ports to a rig that already has two makes `SLIA-017` and
`SLIA-018` more likely to be met. Neither is fixed here; the launcher preflight is
extended to cover the new ports, and the trigger client is short-lived by design
so that it does not become the stale client `SLIA-018` describes.

The control channel's heartbeat works around a pyigtl property rather than
fixing it. A client that leaves is still only noticed on a failed send, so a
trigger from a new client can wait up to about one heartbeat interval plus one
failed send before it is read. The probe measured 0.2 s.

The read-only guarantee is easy to lose to a convenience. The existing write path
does more than write four files - it also removes a stale phantom record beside
the dataset - so reusing any of it for a recorded case would modify `input/`
while every functional test passed. That is why it is tested by hashing the
folder rather than by inspecting the code.

`HSCube` is a new wire payload that `SLIA-022` will consume. Its shape, component
count and metadata are fixed here and documented in the README and roadmap, so
that card is written against a stated contract rather than against this code.
A 752x721x93 cube is about 100 MB in one message; that is measured in manual
step 6 rather than assumed to be fine.

Nine cases exceed the measured `full` preset. Running the largest is manual step
6 so that the GPU limit is discovered here, in a card that can record it, rather
than in front of an audience.

## Documentation impact

- `tools/simulators/README.md`: the `recorded` mode, the control-channel device
  names and state words, the heartbeat and why, the capture delay, the `HSCube`
  payload, the trigger client, the ports opened, and a corrected opening
  statement that no longer claims every output is synthetic.
- `config/local.example.json`: the new settings at their defaults.
- `docs/development/pipeline_test_quickstart.md`: the `-Case` command, the `c`
  key, and what a good recorded startup looks like.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: the `HSCube` and
  `Control` rows with their device names and payload.
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`: the recorded-case
  `SimulationDetail` value.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark workstreams A and B implemented,
  and record the largest-case GPU measurement once manual step 6 has been run.

## Completion evidence

Implementation and automated evidence, 2026-09-13, on
`feature/SLIA-023-recorded-cube-acquisition-standin` from `main` at `3ff2f38`.
Nothing is committed. Manual steps 1 to 5 and 7 were run on 2026-09-14 (see the
addendum below); step 6 is deferred by the project owner.

### Baseline on the unchanged branch

- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: `Ran 110
  tests`, `OK`, exit 0.
- `envi.loadDataset(Path('../../input/bin/bin/004-02'))`:
  `ValueError: could not convert string to float: 'lines = 389'`.
- The embedded `RECORDED_004_02_RAW_HEADER` was compared with the real file:
  equal, 632 bytes each.

### New tests observed failing before the implementation

`python -m unittest -v tests.test_envi.RecordedCaseTest
tests.test_uc1_runner.RecordedCaseRunnerTest
tests.test_config.RecordedModeConfigurationTest tests.test_acquisition_sim`:
`Ran 13 tests`, `FAILED (failures=1, errors=13)`, exit 1.

| Test | Failure against the unchanged code |
| --- | --- |
| `test_parsesHeaderWithTrailingBraceAndLateKeys` | `ValueError: could not convert string to float: 'lines = 389'` |
| `test_recordedCaseIsIdentifiedFromGtMapMarker` | `ValueError: could not convert string to float: 'lines = 4'` |
| `test_markerOutsideGtMapDoesNotIdentifyARecordedCase` (both subtests) | `ValueError: could not convert string to float: 'lines = 4'` |
| `test_unparsableHeaderRaisesDatasetReadError` | `ValueError: could not convert string to float: 'not-a-wavelength'` and `ValueError: invalid literal for int() with base 10: 'eight'` |
| `RecordedCaseRunnerTest`, all four | `ValueError: could not convert string to float: 'lines = 2'` |
| `test_recordedModeRequiresAPlainCaseName`, `test_captureDelayBoundsMustBeOrdered` | `ConfigurationError: Unknown simulators setting(s): case.` |
| `test_recordedSettingsOutsideRecordedModeAreRejected` | `AssertionError: 'recorded' not found in 'Unknown simulators setting(s): case. ...'` |
| `test_acquisition_sim` module | `ImportError: cannot import name 'capture_client' from 'stratum_sim'` |
| `test_recordedCaseIsNeverAWriteTarget` | passed, as predicted: a regression guard, shown failing by mutation below |

### Regression guards observed failing against deliberate mutations

Each mutation was applied to one production file, the test run, and the file
restored and verified by SHA-256 (`restored: True` for all five).

| Mutation | Test | Result |
| --- | --- | --- |
| `_assertTargetIsSafe` returns early for a recorded case | `test_recordedCaseIsNeverAWriteTarget` | `AssertionError: DatasetWriteError not raised`, exit 1 |
| a completed capture writes the phantom record beside the case | `test_recordedSourceDoesNotWrite` | fingerprint gained `phantom_regions.json`, exit 1 |
| a trigger completes its capture at once | `test_triggerPublishesCubeAfterDelay` | `AssertionError: True is not false`, exit 1 |
| `CONTROL_STATUS_INTERVAL_SEC = 1.0e9` | `test_successiveTriggerClientsAreEachServed` | `Lists differ: [0, 1, 1] != [0, 0, 0]`, exit 1 |
| the trigger client ignores `--no-wait` | `test_aTriggerDuringACaptureIsAnsweredIgnoredOverTheWire` | `Lists differ: [0, 0] != [0, 2]`, exit 1 |

### Required checks after the implementation

- Simulator suite: `Ran 131 tests`, `OK`, exit 0. The 21 new tests are those in
  the test plan plus `test_unknownCommandIsRefusedByName` and the over-the-wire
  `IGNORED` test. `ERROR:root:Error while receiving data: [WinError 10053]` lines
  are pyigtl's server thread noticing a trigger client that has left; they are
  the heartbeat working, not failures. `[uc1] KMeansError: nan` is printed by the
  existing real-binary integration test and appears identically in the baseline
  log.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21, both targets
  `All checks passed!`, exit 0.
- `.\scripts\development\run-slicer-tests.ps1`: module loaded from
  `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`, `Ran 50 tests`,
  `OK (skipped=6)`, exit 0. No file under `extensions/` changed. A first attempt
  from the wrong working directory did not run at all and is not counted.
- `git diff --check`: clean. Every changed path is in `Files allowed`, as of
  2026-09-13; the review on 2026-09-14 found two working-tree changes that are
  not (review findings 5 and 6).
- Launcher parsed with `System.Management.Automation.Language.Parser`: 0 errors.

### Checks run ahead of the manual steps

These are automated rehearsals, not manual verification.

- **Ahead of manual step 1.** All 61 folders under `input\bin\bin` loaded
  read-only through `envi.loadDataset` and `envi.assertDataFilesMatchHeader`:
  every one `recorded`, not `simulated`, 93 bands, and exactly the 440 to 900 nm
  grid. Non-conforming: none.
- **Ahead of manual steps 2 to 5.**
  `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer -RunSeconds 90 -FrameSource synthetic`,
  with the operator's `c` key played by an external script, since the host had
  no keyboard:
  - the stand-in opened 18944, 18947 and 18950; nothing listened on 18948 or
    18949, both after startup and during the capture;
  - the first trigger client got `CAPTURING capture=1 case=004-02 delay=7.3` and
    exited 0; a second one sent straight after got
    `IGNORED capture 1 already in progress` and exited 2;
  - `[acq] Capture 1 complete: READY capture=1 case=004-02 folder=C:\stratum\input\bin\bin\004-02`,
    then the launcher started UC1 on that folder, 7.7 s after the triggers;
  - UC1: `Origin: simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`,
    `Time simulation ---> 357.618 ms`, and
    `Recovered majorityVotingMap: shape (1, 389, 345), dtype uint8, classes {1: 55936 (41.7%), 2: 7954 (5.9%), 3: 31584 (23.5%), 4: 38731 (28.9%)}`;
  - the stand-in reported no client on 18947, as expected before `SLIA-022`;
  - shutdown: `Nothing is listening on 18944, 18945, 18947, 18950. No socket was left held.`;
  - the 004-02 folder fingerprint - SHA-256, size and modification time of all
    eight files - was identical before and after.

  The class percentages are UC1's output over the database's case, recorded as
  observed. They are not compared with `gtMap` and are not a result.

### Not run, and why (as of 2026-09-13)

- **Manual steps 1 to 7** are the project owner's. The rehearsals above do not
  replace them. They used a generated LiveView scene, no Slicer, and no real
  keypresses. Superseded by the 2026-09-14 addendum below.
- **Manual step 6, `058-02` through UC1**, has not been run, so the largest-case
  GPU figure is still open in the WP5 plan.
- **The webcam path in recorded mode** was not exercised: `frames.py` is
  unchanged, and opening the camera could have disturbed a session of the
  project owner's.
- **`run-slicer-tests.ps1 -Headful`** was not run: no Slicer module file changed.

### Addendum, 2026-09-14: owner feedback, camera-only LiveView, manual steps run

The project owner asked for the tests to be run and gave two decisions on the
risks:

- **No synthetic information.** The work uses data that has already been
  recorded, so talking about anything synthetic is false. The owner chose to
  remove it from the recorded session here and to retire the rest of the
  synthetic path in a separate card, `SLIA-025`.
- **The large cubes are tested later**, once the pipeline is finished, to see
  how it performs then. Manual step 6 is deferred, not failed.

Change made under this card: a recorded session takes LiveView from the laptop
camera only (acceptance criterion 19). `config.py` refuses any other frame
source in `recorded` mode; `acquisition_sim.commandLineOverrides` defaults a
recorded run to `webcam`; the recorded LiveView detail is one constant,
`acquisition stand-in, laptop camera`; the launcher's `-FrameSource` switch is
gone. The recorded tests feed LiveView from `StillFrameSource`, a test double in
`test_acquisition_sim.py`, and the fixture helper no longer calls its placeholder
arrays synthetic. The quick start, README, WP5 plan and this card say the same.

**Red before the change.** `python -m unittest -v
tests.test_config.RecordedModeConfigurationTest
tests.test_acquisition_sim.RecordedCaptureTest
tests.test_acquisition_sim.RecordedCaptureWireTest`: `Ran 12 tests`,
`FAILED (failures=1, errors=1)`, exit 1.

| Test | Failure against the unchanged code |
| --- | --- |
| `test_recordedLiveViewComesOnlyFromTheLaptopCamera` | `AssertionError: ConfigurationError not raised` |
| `test_recordedCommandLineTakesTheLaptopCameraByDefault` | `AttributeError: module 'stratum_sim.acquisition_sim' has no attribute 'commandLineOverrides'` |
| `test_recordedLiveViewIsLabelledAsTheLaptopCamera` | passed: a regression guard, shown failing by mutation below |

**Mutation.** `RECORDED_LIVE_VIEW_DETAIL` set to
`acquisition stand-in, synthetic scene`:
`test_recordedLiveViewIsLabelledAsTheLaptopCamera` failed with
`AssertionError: 'acquisition stand-in, synthetic scene' != 'acquisition stand-in, laptop camera'`,
exit 1; the file was restored and verified by SHA-256 (`restored: True`).

**Checks after the change.**

- Simulator suite: `Ran 134 tests`, `OK`, exit 0. A first run failed one test,
  `test_captureDelayBoundsMustBeOrdered`, which still loaded recorded mode
  without `webcam` and was refused by the new rule; it was moved onto the
  `loadRecorded` helper, and now also asserts that the refusal is about the delay.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21, both targets
  `All checks passed!`, exit 0.
- Launcher parsed with `System.Management.Automation.Language.Parser`: 0 errors.
  `-Case 004-02 -NoSlicer -FrameSource synthetic` is refused by PowerShell with
  `A parameter cannot be found that matches parameter name 'FrameSource'.`
- `git diff --check`: clean.

**Manual steps 1 to 5 and 7** were run on 2026-09-14 by Claude at the project
owner's request; the observations are in the `Result` column above. Two launcher
sessions on `004-02` with the laptop camera, one before and one after the
camera-only change, each driven with real `c`, `c` and `q` key events written
into the session console's input buffer rather than by a trigger script. Logs are
in the session's scratch folder, not in the repository. The UC1 class
percentages recorded there are UC1's output over the case, not compared with
`gtMap`, and not a result.

### Not run, and why (as of 2026-09-14)

- **Manual step 6, `058-02`**: deferred by the project owner until the pipeline
  is complete.
- **A session with Slicer attached**: every run used `-NoSlicer`. Nothing in
  SLIAFlow consumes `HSCube` until `SLIA-022`, and no file under `extensions/`
  changed.
- **`run-slicer-tests.ps1`** was not rerun on 2026-09-14: no Slicer module file
  changed since its 50-test run on 2026-09-13.
- **A person at the keyboard.** The key presses were real console key events,
  but no person watched the console. The owner may want to repeat step 3 once
  themselves before review.

### Findings

- pyigtl 0.3.4 only releases a departed client on a failed send, which is why
  the control channel repeats its state. This works around the property; it does
  not fix it, and every other producer still has it.
- `run-end-to-end-session.ps1` launched through `&` in `pwsh` leaves
  `$LASTEXITCODE` empty after a normal end, so the rehearsal log reads `exit=`.
  The background task itself reported exit 0.
- The arithmetic stand-in still refuses a recorded case with a message that only
  mentions the simulator's marker. The launcher refuses that combination first,
  and changing the stand-in is outside this card.

### Checks after the review fixes, 2026-09-14

- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: `Ran 134
  tests`, `OK`, exit 0.
- `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21,
  `tools/simulators` (32 files) and `extensions/SLIAFlow/SLIAFlow` (6 files)
  `All checks passed!`, exit 0.
- Launcher parsed with `System.Management.Automation.Language.Parser`: 0 errors.
- `git diff --check`: clean, exit 0.
- `git ls-files input`: 0 files.
- `run-slicer-tests.ps1` was not rerun: no file under `extensions/` changed.

## Review findings

Review of the uncommitted working tree on
`feature/SLIA-023-recorded-cube-acquisition-standin`, 2026-09-14, by Claude at
the project owner's request. It is not an independent review: the same session
wrote the implementation. The code diff was read in full and no functional
defect was found; every test named in the test plan exists.

1. **Fixed - stale status.** The WP5 plan's Workstream A status still read
   "2026-09-13 ... manual verification pending" after manual step 1 had passed.
2. **Fixed - the WP5 plan disagreed with the implementation.** It gave the
   stand-in's option as `--source recorded` (the option is
   `--scene-mode recorded`), listed 18947 and 18950 as new with 18950 carrying a
   single `Control` device, and omitted the launcher's `-InstantCapture`. The
   Workstream B status paragraph was also re-wrapped.
3. **Fixed - the quick start understated a `-Case` session.** Its `-StopStrays`
   and `n` rows named only 18944 and 18945, and the sample capture omitted the
   trigger client's `Sent CAPTURE` line. The launcher's `-StopStrays` comment
   named the same two ports.
4. **Fixed - minor.** The README's `captureDelayMinSec` and `captureDelayMaxSec`
   rows did not say they apply only to the `recorded` scene.
5. **Out of scope - `.gitignore`.** The working tree adds a `CLAUDE.md` line.
   This task did not make it and it is not in `Files allowed`, so it was left
   untouched and must be kept out of this card's commit.
6. **Out of scope - the `SLIA-025` card.**
   `tasks/backlog/SLIA-025-retire-synthetic-phantom-path.md` was written in this
   session on the project owner's instruction of 2026-09-14, but it is not in
   `Files allowed`. It belongs in its own commit, or in this one only if the
   owner says so.
7. **Kept - a real header in a test.** `test_envi.py` embeds `004-02/raw.hdr`
   verbatim: dimensions, data type, byte order and the wavelength grid, with no
   image data and nothing identifying. It is in the test plan approved at
   activation, and `input/` itself stays untracked.
8. **Accepted risk - `config/local.json`.** `sceneMode = recorded` without
   `frameSource = webcam` in the local configuration is refused; only the
   command line defaults a recorded run to the camera. The README says so.
9. **Open - the largest case.** Manual step 6 is deferred by the project owner,
   so acceptance criterion 18 is not met and the WP5 GPU figure is still open.
   The same run is where the cost of reading a 752x721 cube from disk on each
   capture, and any pause it causes, should be measured.
10. **Open - verification limits.** No person at the keyboard ran step 3, and no
    session had Slicer attached; `SLIA-022` is the first consumer of `HSCube`.

## Human approval

Activated on 2026-09-13 under the project owner's instruction to start the next
task, which `AGENTS.md` counts as approval of this specification.

On 2026-09-14 the project owner asked for the branch to be reviewed, gave
permission to correct the files in `Files allowed`, and instructed that this
card be moved to completed so that it is ready to commit and push, without
committing or pushing. That instruction is recorded as the human approval for
completion. Recorded with it, so that it is not read as more than it was:

- no independent AI review by a separate reviewer was run; the review above is
  the implementing session's own;
- manual step 6 is deferred, so acceptance criterion 18 remains open;
- the manual steps were run by Claude, not by the owner at the keyboard;
- nothing is committed. Staging, the commit, the rebase onto `main`, the merge
  and the push each still need the owner's authorization.
