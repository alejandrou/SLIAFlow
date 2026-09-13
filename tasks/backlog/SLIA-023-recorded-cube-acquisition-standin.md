---
id: SLIA-023
title: Accept recorded HSI cubes and stand in for the acquisition trigger
status: backlog
branch:
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
`}`, so it stays inside it and tries to parse the next line as a number:

```
>>> envi.loadDataset(Path('input/bin/bin/004-02'))
ValueError: could not convert string to float: 'lines = 389'
```

That is also the wrong exception type: a folder this module cannot read should
raise `DatasetReadError`, which is what every caller is written to handle.

The defect is on our side only. UC1's own C parser scans for `bands`, `lines` and
`samples` anywhere and stops after three hits, and UC2's `read_hdr_file` handles
keys in any order; both read the recorded headers correctly today.

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
result. Until `SLIA-022` lands, the trigger is sent from the launcher console,
which is enough to demonstrate and test this side on its own.

## Requirements

### Reading recorded cubes

- `envi.parseHeaderText` parses a wavelength block that is closed by `}` at the
  end of a value line, and continues parsing key/value lines after it. Header key
  order stops mattering.
- A folder that cannot be read as a dataset raises `DatasetReadError`, never a
  bare `ValueError` from a parse attempt.
- A recorded case is identified as an approved dataset by the
  `HSI Human Brain Database` marker in its sibling `gtMap.hdr`. The identification
  is read from the data; there is no flag to pass and no flag to forget.
- `DatasetRef` distinguishes the two approved kinds without adding a third data
  origin: a simulator-written dataset and a recorded database case are both
  approved input, and both travel as `simulated` on the wire.
- A folder that identifies as neither is refused exactly as it is today, with the
  same wording and the same override.
- The write-side overwrite interlock is unchanged. A recorded case is never a
  write target, and `_assertTargetIsSafe` keeps refusing any folder whose
  `raw.hdr` lacks the simulator's own marker.

### Provenance wording

- `uc1_runner.py`'s simulation detail names what the cube actually is. Over a
  recorded case it says so and names the case, for example
  `real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`.
- The existing phantom and synthetic-input details are unchanged for the datasets
  they describe. A recorded case never reports `synthetic input`, because that
  claim is false in the direction that understates what is on screen.
- The origin on the wire stays `simulated` for every case. `simulated` means the
  acquisition event was simulated; the detail says what the cube is. No third
  origin, no change to `contract.py`'s origin values, no change to SLIAFlow.

### The acquisition stand-in

- A `recorded` source selects a case by name under a dataset root that defaults
  to `input/bin/bin`, opens it read-only, and **writes nothing**. `input/` is
  untouched after a session.
- The laptop camera streams on `LiveView`, port 18944, unchanged.
- A control channel on port 18950 accepts a trigger STRING and answers on the
  same channel. Message device names and payload wording are stated in
  `tools/simulators/README.md` so the Slicer side can be written against them.
- On a trigger the stand-in holds a configurable capture delay, default 5 to 8
  seconds, reporting that it is capturing, then publishes the cube on port 18947
  as device `HSCube` and announces over the control channel that the capture is
  ready and which folder holds it.
- An instant capture (zero delay) is selectable, for tests and for a session that
  does not want to wait.
- The stereoscopic channel is not opened. No producer binds 18948.
- A trigger arriving while a capture is already running is answered and ignored,
  not queued.

### The launcher

- `run-end-to-end-session.ps1` gains `-Case` and `-DatasetRoot`, reusing the port
  preflight it already has, extended to the ports this card opens.
- A keypress sends a capture trigger, so the loop is demonstrable before
  `SLIA-022` adds the button.

## Out of scope

- Any change to `extensions/`, including the capture button and the Slicer side
  of the control channel. Those are `SLIA-022`.
- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- A third data origin, a provenance ADR, or capture identifiers.
- The pseudo-RGB background and the overlay, which are `SLIA-024`.
- Emulating the band-by-band sweep in real time.
- Fanning one cube out to several network consumers.
- Any metric computed against `gtMap`. The file is read for its marker and for
  nothing else.

## Files allowed

- `tools/simulators/stratum_sim/envi.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/stratum_sim/config.py`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/tests/**`
- `tools/simulators/README.md`
- `scripts/development/run-end-to-end-session.ps1`
- `docs/development/pipeline_test_quickstart.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `tasks/{backlog,active,review,completed}/SLIA-023-recorded-cube-acquisition-standin.md`

## Relevant skills and references

- `docs/architecture/WP5_MS5_DEMO_PLAN.md`, workstreams A and B
- `.ai/policies/medical-data-policy.md`, the approved-dataset entry
- `tools/simulators/stratum_sim/envi.py`, `parseHeaderText` and `loadDataset`
- `tools/simulators/stratum_sim/config.py`, the scene-mode validator
- `pyigtl.OpenIGTLinkServer.wait_for_message` and `get_latest_messages`, for the
  control channel's receive side
- `SLIA-017` and `SLIA-018`, both of which this card multiplies by adding ports

## Approved dependencies

None. The control channel uses `pyigtl`'s existing STRING message support.

## Implementation plan

1. Write the header-parser test against a verbatim recorded header and show it
   failing with the recorded `ValueError`.
2. Fix `parseHeaderText` and the exception type, then add the `gtMap.hdr`
   identification and its refusal cases.
3. Change the UC1 runner's simulation detail and prove a recorded case cannot
   report `synthetic input`.
4. Add the `recorded` scene mode and its read-only guarantee.
5. Add the control channel, the capture delay and the `HSCube` publication.
6. Extend the launcher, then run a full session on `004-02` and record it.

## Acceptance criteria

- `envi.loadDataset` reads every one of the 61 recorded cases and returns the
  dimensions and the 93-value wavelength grid its header states.
- A folder that is neither a simulator dataset nor a database case is refused,
  with `DatasetReadError` rather than a parse exception.
- A recorded case run through the UC1 runner carries a simulation detail that
  names the case and never says `synthetic input`.
- A session on a recorded case leaves `input/` byte-identical.
- A trigger on 18950 produces, after the configured delay, an `HSCube` message on
  18947 and a readiness announcement naming the folder.
- Nothing binds port 18948.
- The launcher starts a session with `-Case 004-02` and tears it down with
  nothing left listening.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A recorded header parses, keys after the wavelength block included | `test_envi.test_parses_header_with_trailing_brace_and_late_keys` | automated |
| An unreadable folder raises `DatasetReadError` | `test_envi.test_unparsable_header_raises_dataset_read_error` | automated |
| A database case is identified from `gtMap.hdr` | `test_envi.test_recorded_case_is_identified_from_gtmap_marker` | automated |
| A folder identifying as neither is refused | `test_envi.test_unmarked_folder_is_still_refused` | automated |
| A recorded case never reports synthetic input | `test_uc1_runner.test_recorded_case_detail_names_the_case` | automated |
| The recorded source writes nothing | `test_acquisition_sim.test_recorded_source_does_not_write` | automated |
| A trigger produces a cube after the delay | `test_acquisition_sim.test_trigger_publishes_cube_after_delay` | automated |
| A trigger during a capture is ignored, not queued | `test_acquisition_sim.test_trigger_during_capture_is_ignored` | automated |
| Nothing binds the reserved stereoscopic port | `test_acquisition_sim.test_stereoscopic_port_is_not_bound` | automated |
| All 61 cases load | Manual step 1 | manual |
| `input/` is untouched after a session | Manual step 2 | manual |
| The launcher runs a full session on a case | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_parses_header_with_trailing_brace_and_late_keys` is written against a
  verbatim copy of `input/bin/bin/004-02/raw.hdr` and shown failing with
  `ValueError: could not convert string to float: 'lines = 389'`. The failure
  output is recorded in the completion evidence.
- `test_recorded_case_detail_names_the_case` is first written asserting the
  current `synthetic input` wording and shown passing, to prove the assertion is
  not vacuous, then inverted.
- `test_recorded_source_does_not_write` compares a recursive hash of the case
  folder before and after, and is shown failing against a first implementation
  that copies the case into a working folder.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Load every folder under `input/bin/bin` with `envi.loadDataset` | All 61 load; each reports 93 bands and a 93-value grid from 440 to 900 nm | |
| 2 | Hash `input/bin/bin` before and after a full session, and check file modification times | Identical; no file in `input/` was written or touched | |
| 3 | Run `run-end-to-end-session.ps1 -Case 004-02`, press the capture key, and watch the console | The capture delay is reported, the cube is published on 18947, and the readiness announcement names the case folder | |
| 4 | While a capture is running, press the capture key again | The second trigger is answered and ignored; exactly one cube is published | |
| 5 | `netstat -ano | findstr 18948` during a session | Nothing is listening | |
| 6 | Run a session on `058-02`, the largest case | Either it completes and the GPU figure is recorded, or it fails on memory and the failure is recorded as a finding rather than worked around | |

## Risks

The provenance wording is the one place this card can do real harm. A recorded
human-brain cube displayed under a detail saying `synthetic input` understates
what is on screen, which is the direction of error that the banner and demo-mode
interlock do not protect against - they guard against simulated data being taken
for real, not against real data being dismissed as simulated. The wording change
is therefore a requirement, not a nicety, and its test is written to fail first.

Adding four ports to a rig that already has two makes `SLIA-017` and `SLIA-018`
four times more likely to be met. Neither is fixed here; the launcher preflight
must simply be extended to cover the new ports.

The read-only guarantee is easy to lose to a convenience. A first implementation
that copies a case into a working folder so the existing write path can be reused
would satisfy every functional test and quietly break the guarantee, which is why
it is tested by hashing the source folder rather than by inspecting the code.

Nine cases exceed the measured `full` preset. Running the largest is step 6 so
that the GPU limit is discovered here, in a card that can record it, rather than
in front of an audience.

## Documentation impact

- `tools/simulators/README.md`: the `recorded` source, the control-channel
  message names and wording, the capture delay, and the ports opened.
- `docs/development/pipeline_test_quickstart.md`: the `-Case` command and the
  capture keypress.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`: `HSCube` and `Control`
  in the contract table, and the reserved ports.
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`: mark workstreams A and B done, and
  record the largest-case GPU measurement.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Required before activation and before completion.
