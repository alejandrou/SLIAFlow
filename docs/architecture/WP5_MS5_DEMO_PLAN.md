# WP5 / MS5 demonstrator plan

> **Historical since `SLIA-028`.** This plan was carried out with standalone
> producers on separate ports. `ADR-0003` moved capture and UC1 into Slicer,
> `ADR-0004` made IUMA's acquisition app the producer and its LCTF cube the data,
> and `SLIA-028` removed the producers, the capture client and the session
> scripts this plan names. It is kept as the record of the WP5 / MS5 plan; its
> commands no longer work. The current way to run is the in-Slicer
> demonstration in `docs/development/uc1_demo_runbook.md`.

## Purpose

This is the repository-resident plan for the STRATUM WP5 demonstration that
SLIAFlow is EBATINCA's contribution to: *"Integration of the SW and HW
developments onto the STRATUM Neuronavigation Demonstrator"*, milestone **MS5
"Interactive 3D GUI", deliverable D5.2**. Of MS5's nine points, point 1
(microscope RGB) is recorded Done. This plan attacks point **2** (UC1 results
over RGB) and point **3** (UC2 results).

It is a demonstration, not a product. Everything absent is shown as a black
panel with its reason written on it and a port reserved, so that the day a
component arrives it is started on that port and the panel lights up with no
change inside `extensions/`.

This document is the plan. The cards that execute it are named in
[Execution order](#execution-order); nothing here overrides an accepted ADR or an
approved task card.

## The workflow demonstrated

```
Laptop camera  ──>  [ CAPTURE ]  ──>  HSI cube from the inputs folder
 (stands in for                              │
  the acquisition rig)                       ├──> UC1 ──> tumour delineation
                                             └──> UC2 ──> vascularization
                                                      │
                                                OpenIGTLink → 3D Slicer
```

The acquisition event is simulated end to end: the webcam stands in for the rig,
the button stands in for the trigger, and the cube is read from `input/`. The
cube itself is not simulated - see [Provenance](#provenance-the-one-thing-this-plan-changes-about-labelling),
which is the single point on which this plan corrects the shape of the existing
provenance vocabulary rather than reusing it unchanged.

## What already works

| Piece | Where | State |
| --- | --- | --- |
| SLIAFlow extension | `extensions/SLIAFlow` | Two panes, OIGTL connectors, validation |
| Genuine UC1 (CUDA) | `build/uc1/UC1/.../stratum.opt.exe` | Built `sm_120`, run through `uc1_runner.py` |
| Genuine UC2 (C) | `workspace/components/blood_vessels_enhancement` | Built and already run on real cases `007-01`, `008-01`, `008-02`, `010-03` |
| Stand-ins and transport | `tools/simulators/stratum_sim/` | 110 tests, pyigtl 0.3.4 |
| Laptop camera in Slicer | SLIAFlow, `SLIA-005` | Verified |
| Recorded data | `input/reference_hsi_brain_db/020-01/`, `input/archive_hsi_brain_db_93_bands/` | Since `SLIA-031`: one reference case read by SLIAFlow, the other 60 archived; 93 bands, gitignored |
| IUMA LCTF capture | `input/002-04/` | `ADR-0004`'s reference cube, float32, 109 bands; read from `SLIA-032` on |

The case paths quoted below (`input/bin/bin/...`) are those of their date;
`SLIA-031` moved the cases on 2026-09-24 (`input/README.txt`).

### What was measured about the recorded data

All 61 cases were audited against the pipeline contract on 2026-09-11. Every one
of them: 93 bands, ENVI data type 12 (uint16), `interleave = bsq`, and
`raw.dat`, `whiteReference.dat` and `darkReference.dat` each exactly
`samples * lines * bands * 2` bytes. No case is missing a reference and no case
disagrees with its own header.

All 61 share one wavelength grid: **440 to 900 nm in 5 nm steps, 93 bands**. So
UC2's hard-coded band indices 54, 20 and 8 resolve to **710, 540 and 480 nm** -
exactly the wavelengths its own comments claim. The band mismatch that
`SLIA-021` documented was an artefact of the generated 400.482-1000.73 nm grid
the simulator used before `SLIA-025` retired it, not of the algorithm, and
recorded data removes it. This is the single
largest simplification in the plan and it was verified, not assumed.

Two things the audit found that the plan as first written did not account for:

- **Nine of the 61 cases are larger than the `full` preset.** Sizes run from
  253x298 to 752x721. The recorded UC1 measurement of 1973 MiB at 640x480 scales
  linearly to about **3.5 GiB for the largest case**, against 8151 MiB on the
  RTX 5050 in this machine. It fits, with less headroom than the demonstration
  case. `004-02` at 345x389 is comfortably below the measured preset; the
  dataset as a whole is not.
- **UC1's `MAX_PATH_LENGTH` is not at risk here.** `C:\stratum\input\bin\bin\<case>`
  plus `/whiteReference.dat` is 49 bytes against a 128-byte buffer, and the
  longest header line in a recorded case is 44 bytes against the same buffer.

## The target screen

**Status, 2026-09-16:** implemented under `SLIA-022`. Manual runs found four
defects - the LiveView panel black without its reason, the capture trigger
refused for a non-IANA encoding number, connector events that could not be told
apart because VTK delivers them to Python as a string, and a lost link that
announces itself through an event the connector queues and then never pumps. The
first two are fixed and verified by hand; the last two are fixed and covered by
tests, and the link-loss step must pass a manual run before the card leaves
manual verification. The layer list keeps each result in its own panel: `ADR-0001`, accepted
on 2026-09-15, composites a result only over a background from its own
producer, so `UC2_BV` is never drawn over `UC1_RGB`. The UC1 overlay itself is
`SLIA-024`, implemented on 2026-09-16 (see Workstream C). The UC2 panel cannot be exercised by hand until `SLIA-021` delivers
its producer.

Six views, which is the union of the two reference images:

```
┌────────────────┬────────────────┬────────────────┐
│ LiveView       │ Stereoscopic   │ HS Cube        │
│ laptop camera  │ BLACK          │ band browser   │
│                │ "no producer"  │                │
├────────────────┼────────────────┼────────────────┤
│ Relative StO2  │ Enhanced       │ Tumour         │
│ BLACK          │ Vascularization│ Delineation    │
│ "no algorithm" │ UC2            │ UC1            │
└────────────────┴────────────────┴────────────────┘
```

The two black panels are deliberate and carry their reason on screen. When UPM
delivers depth and ULPGC delivers the optical-parameter algorithm, a process is
started on a port that is already reserved and the panel lights up.

### One port per channel

| Port | Channel | Producer | State |
| ---: | --- | --- | --- |
| 18944 | `LiveView` | Acquisition stand-in (laptop camera) | Same as the real application; interchangeable |
| 18945 | `UC1_MV_CLASS` **and** `UC1_RGB` | `uc1_runner.py` (CUDA) | `UC1_MV_CLASS` exists; `UC1_RGB` is new |
| 18946 | `UC2_BV` | `uc2_runner.py` (C) | New |
| 18947 | `HSCube` | Acquisition stand-in | In use (`SLIA-023`) |
| 18948 | `Stereoscopic` | - | **Reserved: black panel** |
| 18949 | `UC2_STO2` | - | **Reserved: black panel** |
| 18950 | `Control`: `CaptureTrigger`, `CaptureReply`, `CaptureStatus` | Acquisition stand-in; Slicer side `SLIA-022` | Producer side in use (`SLIA-023`) |

`UC1_RGB` shares port 18945 with `UC1_MV_CLASS` rather than taking a port of its
own. The reason is in [Workstream C](#workstream-c--make-the-uc1-result-visible).

## Provenance: the one thing this plan changes about labelling

The existing vocabulary has two origins: `simulated` and `external-genuine`. The
first plan draft said to mark everything `simulated`, on the grounds that the
whole acquisition is a simulation and `simulated` is what the system already
knows how to do. The transport half of that is right and is kept: no third
origin, no ADR for provenance, no change to `contract.py`'s origin values, no
change to SLIAFlow's gate. Everything on the wire stays `simulated`, which keeps
the banner, the demo-mode interlock and the genuine-over-simulated precedence
exactly as they are.

What could not be kept was the *detail string*. The strings `uc1_runner.py` sent
before `SLIA-023` described a generated input, which is false over a recorded
human-brain cube, and false in the direction that understates what is on screen
rather than overstating it. So the detail became, for example:

```
real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
```

`simulated` on the wire means **the acquisition event was simulated**. The
detail says what the cube actually is. Those are two separate claims and the
protocol already has a field for each; nothing new is needed to express it.

The dataset is the public, anonymized *HSI Human Brain Database* published by
ULPGC (`https://hsibraindatabase.iuma.ulpgc.es/`). Under
`.ai/policies/medical-data-policy.md` it falls under "explicitly approved public
medical data", and that approval is now recorded in the policy itself rather
than being assumed here. `input/` is gitignored, so no case ever enters version
control.

## Workstream A - let recorded cubes through without touching the contract

**Status, 2026-09-14:** implemented under `SLIA-023` and verified. All 61 cases
load through `envi.loadDataset`, each identified by its `gtMap.hdr` marker, with
no change to the contract's origins.

**Plainly:** the system refused a cube whose header did not carry the marker its
own generated datasets were written with. That guard exists so the tooling can
never process data it has no business processing. Recorded cases did not carry
it, so they had to be let in without the guard being switched off. Since
`SLIA-025` the recorded-case marker is the only one: the generated datasets and
their marker are gone.

**What is not done**, as overengineering: no third `external-recorded` origin, no
provenance ADR, no change to the image contract, no change to SLIAFlow's display
logic.

**What the first draft got wrong.** The draft said this is one small change to
`envi.py` - recognise `HSI Human Brain Database` as a second approved marker.
Two measurements on 2026-09-11 say it is not:

1. **The marker is not in `raw.hdr`.** It is in `gtMap.hdr`, on a single line,
   and `loadDataset` reads only `raw.hdr`. Recognising the string in the header
   it already reads would never match anything.
2. **`parseHeaderText` crashes on a recorded header before any marker check is
   reached.** Recorded headers close the wavelength block with `}` appended to
   the last number (`890, 895,  900}`) instead of on a line of its own, and they
   put `lines` and `samples` *after* the block. The parser only leaves the block
   on a line that *starts* with `}`, so it keeps going and tries
   `float("lines = 389")`:

   ```
   ValueError: could not convert string to float: 'lines = 389'
   ```

   Reproduced directly against `envi.loadDataset(Path('input/bin/bin/004-02'))`.

So Workstream A is a parser fix plus a dataset-identification change, not a
one-line marker addition. The identification has to read something other than
`raw.hdr`, and the sibling `gtMap.hdr` is the honest place: it is the file the
database itself stamps. A folder that identifies as neither a simulator dataset
nor a database case is still refused exactly as it is today.

Note that **UC1's own C parser handles the recorded headers correctly** - it
scans for `bands`, `lines` and `samples` anywhere in the first three hits and
stops - and so does **UC2's**. The defect is on our side only.

## Workstream B - the stand-in behaves like theatre equipment

**Status, 2026-09-14:** implemented under `SLIA-023`, and its launcher session on
`004-02` verified with the laptop camera. The largest-case GPU measurement on
`058-02` is deferred by the project owner until the pipeline is complete, so that
the large cubes are tested against the finished pipeline; it is recorded here once
it has been taken. A recorded session takes LiveView from the laptop camera only:
the owner decided on 2026-09-14 that nothing generated is shown beside recorded
data.

Two things changed while building it. The control channel carries three device
names - `CaptureTrigger`, `CaptureReply` and `CaptureStatus` - rather than one,
and repeats its state every 0.5 s, because pyigtl 0.3.4 does not release a client
that has left until a send to it fails. And the launcher's capture key starts a
client that leaves once the capture has started, so that a second press is
answered `IGNORED` rather than being read after the first capture.
`tools/simulators/README.md` has the wording.

**Plainly:** a process that impersonates the rig. It does not invent data - the
data is real - it imitates *what the machine does*.

`tools/simulators/stratum_sim/acquisition_sim.py`:

- `--case 004-02`, default root `input/bin/bin`. **Writes
  nothing**: the case folder already is the dataset and is opened read-only, so
  `input/` stays untouched.
- The laptop camera goes out on `LiveView`, port 18944, which is the path
  already implemented and verified.
- It waits for a trigger STRING on 18950. On arrival it holds a **configurable
  5-8 s** (or instant) "capturing..." delay and then publishes the cube on
  18947. The band-by-band sweep is not emulated in real time: this is a
  simulation and real-time sweep adds nothing to the demonstration.
- It announces over the control channel that the capture is ready and where.
- The stereoscopic channel is **not opened**. Black panel with its reason.

`scripts/development/run-end-to-end-session.ps1` gains `-Case`, `-DatasetRoot`
and `-InstantCapture`, reusing the port preflight it already has.

**Why the theatre rather than going straight to the point:** the day the real
rig arrives this process is stopped and the real one started on the same port.
That property was already demonstrated by hot-swapping producers in `SLIA-014`.

**Two constraints the first draft did not state:**

- **A recorded source was a new mode, not a flag.** Streaming the webcam on
  LiveView while the cube comes from disk was a combination the generated scenes
  did not have. `SLIA-025` then retired those scenes, so recorded is the
  stand-in's only behaviour.
- **Only one process can hold the laptop camera.** If the stand-in opens the
  webcam for LiveView, SLIAFlow's own `SLIA-005` camera path must not also open
  it. The six-panel LiveView is fed by one of the two, never both.

**Where the CAPTURE button lives.** The button is in Slicer, so the Slicer half
of the control channel - an outgoing text node on a third connector - is new
SLIAFlow behaviour and belongs with the panel card, not with the stand-in card.
Until then the trigger is a keypress in the launcher console, which is enough to
demonstrate and test the producer side on its own.

## Workstream C - make the UC1 result visible

**Status, 2026-09-16:** implemented under `SLIA-024`, automated tests passing,
manual verification pending. The runner resolves 710, 540 and 480 nm against the
header's own wavelengths (tolerance 2.5 nm; on recorded case `004-02` they resolve
exactly to indices 54, 20 and 8), scales each band by fixed reflectance
(`round(clip(reflectance, 0, 1) * 255)`, no per-image stretch) and sends
`UC1_RGB` before `UC1_MV_CLASS` in every cycle, with the map's provenance. A
header that cannot supply the bands stops `UC1_RGB`, never the map. Two changes
from the bullets below, both in `ADR-0002`: a size mismatch shows the
map **alone**, not side by side, because the delineation view is one panel; and
every UC1 map carries one `SLIAFlow.CaptureId` per run, shared by `UC1_RGB`,
because review found that a `UC1_RGB` retained from an earlier run passes every
other check. SLIAFlow also
refuses a background whose provenance differs from the map's.

**Plainly:** close the loop. Camera → capture → cube → UC1 → result on screen.
That is the thing to show.

- UC1 runs on the announced folder and publishes its class map on 18945. That
  works today; only the cube's origin changes.
- Three bands (710/540/480 nm) are taken from the same cube and composed into a
  colour photograph of the surgical field. Because it comes from the same cube
  as the map, the two agree pixel for pixel by construction.
- The delineation panel shows the map over that photograph, with opacity.
- **One safeguard, one line:** if the two images are not the same size, they are
  not overlaid and are shown side by side. No capture identifiers, no extra
  protocol. *(Superseded by `ADR-0002`: the map is shown alone, and one
  capture ID ties the two images together.)*

The background is the cube-derived photograph, **not the laptop camera**: the
camera is pointed somewhere else, and overlaying there would paint the tumour
where it is not. The camera stays in its LiveView panel, which is where it sits
on the real rig.

**Why `UC1_RGB` shares port 18945.** The pseudo-RGB has no port in the first
draft's table, and it needs a transport. Sending it as a second device name on
the UC1 runner's existing connection is the arrangement that makes the
pixel-for-pixel claim structural rather than hopeful: one producer, one cube,
one connection, two device names, same capture by construction. Giving it its own
port would mean two producers, two connections and a size check doing load-bearing
work. It also avoids an eighth port, and avoids the one-client-at-a-time
transport limit multiplying.

**Inherited limitation, untouched:** UC1 computes five maps and saves one; the
other four are discarded because the write is commented out at `main.cu:164-174`.
That is a partner's code. It is requested in writing; the contract already admits
all five, so nothing here changes when they arrive.

## Workstream D - UC2 alongside, and the screen that hosts it

**Plainly:** UC2 already works on recorded cases. It is wrapped the same way UC1
is, on its own port, and the screen grows from two panes to six.

- Role `bloodVesselMap`, device `UC2_BV`, port 18946.
- **The PNG that UC2 writes is transmitted as-is, as an RGB image.** `SLIA-021`
  proposed transmitting the raw float map so Slicer could apply its own colour
  scale, but the binary **can only write the PNG**: getting the float out would
  require modifying UC2, which is out of scope. The deliverable's reference image
  is a colour image in any case.
- Cost recorded rather than hidden: `normalize_rgb_array` rescales each channel
  to its own min and max *within one image*, so two captures of the same tissue
  can come out different colours. Not comparable between captures. It goes on the
  request list.
- `blood_vessels_enhancement` is not touched in either of its two copies. The
  two copies were diffed on 2026-09-11: every source file is byte-identical;
  only `CODE_REVIEW.md`, the four output PNGs, the `input/` folder and `main.out`
  differ.
- The six-panel layout is `SLIA-022`, widened.

**What the first draft got wrong, twice:**

1. **The four parameters cannot be passed from a wrapper.** `high_in`,
   `high_out`, `gamma` and `bValue` are local variables inside `main()`
   (`main.c`, both branches), and the binary takes exactly one argument - the
   folder path. Passing them from outside requires editing `main.c`, which is
   explicitly out of scope. So the runner records the fixed values
   (`0.15 / 0.8 / 1 / 3`) as part of each run's provenance and the configurability
   stays a request to ULPGC. This removes the only item the first draft listed as
   *lengthening* the task.

2. **The saturation question already has an answer, and it is not `high_in`.**
   The first draft said to check the four real BVMaps before assuming `high_in =
   0.15` saturates the frame. Measured on those four PNGs:

   | Case | Blue at 255 | Green at 255 | Red at 255 |
   | --- | ---: | ---: | ---: |
   | 007-01 | 47.1% | 1.4% | 3.1% |
   | 008-01 | 96.3% | 0.0% | 0.1% |
   | 008-02 | 69.7% | 0.2% | 0.5% |
   | 010-03 | 89.2% | 0.0% | 0.1% |

   Real data still saturates heavily, through a mechanism that is not the
   `high_in` stretch `SLIA-019` suspected (that card is superseded by `SLIA-025`). The blue output channel is
   `|I2 * bValue - calibrated[0]|` with `bValue = 3`, and `clip_array` clamps it
   at 1.0 before normalization. It is the `bValue` multiply clipping, not the
   `high_in` stretch. This is an observation about the algorithm on real data -
   recorded, reported, not corrected.

**Also confirmed, and still not ours to fix:** `computeBVmapLCTF` takes its
enhancer channel from calibrated plane 0, which after
`extract_selected_bands_LCTF_BSQ(cube, lines, samples, red=54, green=20, blue=8)`
is the **blue** band at 480 nm, while the adjacent comment says red and third
band. Report it; do not patch it, and do not compensate for it in the wrapper.

**One mechanical constraint for the runner:** `save_BVMap_as_png` is called with
a hard-coded output folder of `"."`, so the PNG lands in the **process working
directory** under the name `<case>-BVMap.png`. The runner therefore controls the
output location only through CWD, and needs the same freshness guard
`uc1_runner.py` already has - a timestamp taken immediately before the process
starts - or a stale PNG from an earlier run passes for this run's result.

## Out of scope

- Any change to UC1, UC2 or `AcquisitionSystemApp`, in any copy.
- The four maps UC1 discards: an interface request.
- A third data origin or a provenance ADR.
- Building or running the real acquisition application, and its proprietary
  TCP/JP2 protocol on port 2000.
- Stereoscopic and StO2: no algorithm. Port and panel reserved.
- MS5 points 4 to 9 (UC3 depth, UC4 brain-shift, Optitrack, registration).
- Fanning one cube out to several network consumers. In Mode A (everything on
  one machine) it is not needed: the algorithms read the announced folder. See
  [the transport note](#transport-note-for-mode-b-not-for-now).
- Metrics against `gtMap` in the interface.
- The four-file delta between the two UC1 copies: deferred.

## Execution order

`AGENTS.md` allows **one active task** across `tasks/active/` and
`tasks/review/`. Each task needs its card and its branch.

| # | Work | Card | What it lights up |
| --- | --- | --- | --- |
| 1 | Close `SLIA-014` | `SLIA-014` | - |
| 2 | Link state outliving the socket | `SLIA-016` | A real defect; with six panels it is visible six times |
| 3 | Accept recorded cubes + capture stand-in | `SLIA-023` | Workstreams A and B together: camera → capture → cube |
| 4 | Six-panel layout and the capture button | `SLIA-022` | The screen |
| 5 | UC1 over the cube-derived RGB | `SLIA-024` | **MS5 point 2** |
| 6 | UC2 as a producer | `SLIA-021` | **MS5 point 3** |

A and B go together because they are one story and neither can be tested alone.
After step 4 there is something to show even with panels still empty.

`SLIA-017` (two producers share a port silently) and `SLIA-018` (the second
client receives nothing) are still open and already mitigated in the launcher.
With seven ports they are worth taking before step 4.

Step 5 depends on the overlay decision recorded in
`docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`,
which reverses the roadmap's recorded "not overlaid because not registered".

## Verification

1. `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` - baseline
   110 / OK, re-measured 2026-09-11.
2. `.\scripts\development\run-slicer-tests.ps1` and `-Headful` - 45 / OK
   (skipped=6) and 45 / OK (skipped=1).
3. `.\scripts\development\run-python-quality.ps1` - Ruff.
4. `.\scripts\development\build-uc1.ps1` - its SHA-256 assertion over
   `workspace/components/` is the proof UC1 was not touched. For UC2,
   `git status` over both copies does the same job.

A full session in one console:

```powershell
.\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

What has to be seen:

- The laptop camera in the LiveView panel.
- Press capture → wait → the cube appears and can be browsed by band.
- The delineation panel with UC1's map over the cube-derived RGB.
- The vascularization panel with UC2's BVMap.
- Stereoscopic and StO2 black, with their reason on screen.
- Clean shutdown in both directions, with no hung sockets and no locked camera.

## Transport note (for Mode B, not for now)

The meeting asks that one cube *"be readable by several algorithms"*.
`pyigtl.OpenIGTLinkServer` inherits a plain `socketserver.TCPServer`, and the
send queue belongs to the server rather than to the connection: it not only
serves one client at a time (`SLIA-018`), **a `ThreadingMixIn` would not fix
it** - each message would still go out over one connection. A real fan-out needs
per-connection queues, written by us.

In Mode A it is not needed, because the algorithms read the folder from disk.
When the processes move to the SNS/HPC, this is the first thing to solve.

## Requests to other partners (not our code)

Reconstructed from the code of `AcquisitionSystemApp`, `UC1` and `UC2`.

1. **ULPGC - AcquisitionSystemApp:** saves the cube and the dark reference but
   **does not capture a white reference**, which UC1 and UC2 both need, and does
   not calibrate the cube. It is masked today because recorded cases do carry
   one. This is a live integration blocker for the clinical prototype.
2. **ULPGC - AcquisitionSystemApp:** its ENVI loader does not open database
   cases as they ship (`raw.dat` with no `data file` key →
   `FileNotFoundException`). The rig and the database cannot read each other.
3. **ULPGC - AcquisitionSystemApp:** confirm whether an OpenIGTLink path exists
   for the multidimensional cube. In the copy received, the cube leaves only over
   the proprietary TCP/JP2 protocol on port 2000; LiveView does go over OIGTL
   18944.
4. **ULPGC / BSC - UC1:** enable the write of the four discarded maps
   (`main.cu:164-174`). MS4 point 2 asks for *"gradient probability at different
   stages of the algorithm"*.
5. **ULPGC - UC2:** expose the float map before `normalize_rgb_array`, so the
   result is comparable between captures and can carry a colour bar.
6. **ULPGC - UC2:** `computeBVmapLCTF` takes its enhancement channel from
   calibrated index 0, which after `extract_selected_bands_LCTF_BSQ` is the blue
   band, while the adjacent comment says red. Report, do not patch.
7. **ULPGC - UC2:** `high_in`, `high_out`, `gamma` and `bValue` are locals inside
   `main()`, and the binary takes only a folder path, so they cannot be set from
   outside at all. The source itself flags this in capitals.
8. **ULPGC - UC2:** real delivery date for the optical-parameter / StO2
   algorithm.
9. **UPM:** format and channel for the stereoscopic image and the depth map.
