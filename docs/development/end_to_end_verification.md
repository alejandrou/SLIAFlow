# End-to-end hardware-free workflow verification

This is the procedure for running the whole three-box workflow on one machine
with no hyperspectral camera: the acquisition stand-in streaming the laptop
camera as `LiveView` and publishing a recorded case's cube on capture, the
genuine UC1 CUDA pipeline producing a class map from that case, and SLIAFlow
receiving both over OpenIGTLink.

It is written to be followed, not read. Every step names the exact control to
use and the exact text to look for, and every measurement has a place to be
written down. A second person holding only this document and the repository
should be able to repeat the whole session and get the same answers.

If you only want to *run* a session rather than record one, read
`pipeline_test_quickstart.md` instead: it is the same launcher and the same
checks, without the evidence tables.

**Nothing in this procedure produces a clinical result.** The cube is a recorded
case of the public, anonymized HSI Human Brain Database, only the acquisition is
simulated, and a prototype run of a real algorithm is not a diagnosis. Every map
displayed during this session carries a banner, and no screenshot may be taken of
a result pane without that banner visible in it.

## What this session is for

Each component has already been verified alone. What this session exercises is
all of them at once, and one property in particular: that stopping the map
producer and starting it again on the same port is followed by SLIAFlow - the
link state, the retained map, the banner - without SLIAFlow being reconfigured,
restarted, or told what happened.

That property is why the architecture puts the seam at the network boundary. If
it holds, the arrival of real hardware is a configuration change. If it does not,
it is a project. Step 3 is the measurement of it.

A defect found here is written up and filed as its own backlog task, with its
reproduction steps, before any fix is attempted. Fixing in place loses the
reproduction, which is the most valuable thing the session can produce.

## Prerequisites

| Requirement | How it is satisfied | Reference |
| --- | --- | --- |
| Repository `.venv` with the simulator requirements installed | `py -3 -m venv .venv` then `pip install -r tools\simulators\requirements.txt` | `tools/simulators/README.md` |
| Vendored UC1 CUDA binary built for this GPU | `.\scripts\development\build-uc1.ps1` | `docs/development/uc1_local_build.md` |
| SLIAFlow launcher built with SlicerOpenIGTLink | `.\scripts\development\build-sliaflow.ps1` produces `build\SLIAFlow\SlicerWithSLIAFlow.exe` | `README_SLIAFlow_Build.md` |
| `config/local.json` present with a valid `slicerExecutable` | Copy `config/local.example.json` and edit | `AGENTS.md` |
| The recorded case to run, for example `004-02`, under `input\bin\bin` | Approved public data; read, never written | `.ai/policies/medical-data-policy.md` |
| Ports 18944, 18945, 18947 and 18950 free on the loopback interface | No earlier session still running. Advisory since `SLIA-017`: a producer refuses an occupied or reserved port itself, names the process holding it and exits 1 | `netstat -ano \| findstr "18944 18945 18947 18950"` |

## Running the whole session from one console

Everything below can be driven from a single shell:

```powershell
cd C:\stratum
.\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

Windows PowerShell and PowerShell 7 both run it. From an editor or a shell that
blocks unsigned scripts, invoke it as
`powershell -ExecutionPolicy Bypass -File .\scripts\development\run-end-to-end-session.ps1 -Case 004-02`.
Without `-Case` it refuses to start.

That script does the setup this document describes by hand: it refuses to start
if anything already holds a session port, brings up the acquisition stand-in,
waits for each of its ports to be listening, and starts Slicer. The `c` key sends
a capture trigger, and the genuine UC1 runner starts on the case once the first
capture reports `READY`. Every producer's output is tailed into the same console,
tagged `[acq]`, `[capture-N]` or `[uc1-genuine]`, and a `[status]` line reports
how many clients each port has whenever that changes and at least every couple of
seconds.

| Key | What it does | Step |
| --- | --- | --- |
| `c` | Sends one capture trigger to the stand-in | 2 |
| `m` | Runs `liveview_client.py` after prompting for the acquisition link to be disconnected, and prompts to reconnect afterwards | 2 |
| `l` | Starts Slicer again after it has been closed, without touching the producers | 6 |
| `q` | Stops the producers and reports whether any port was left held | 5 and 6 |

`n` prints the current `netstat` rows for the session ports and the reserved
ports, `d` prints the case folder and log paths, and `?` reprints the list.

Useful switches: `-InstantCapture` completes each capture at once, `-NoSlicer`
brings the producers up without launching Slicer, `-SlicerFrom Source` runs the
configured Slicer against `extensions\SLIAFlow\SLIAFlow` instead of the compiled
launcher, `-StopStrays` kills whatever already holds the ports instead of refusing
to start, and `-RunSeconds 30` brings the rig up and takes it down again by
itself, which is the quickest way to check the machine is in a state to run a
session at all.

Each run gets its own folder under `workspace\simulators\sessions\`, holding one
log file per producer. The producers run with `PYTHONUNBUFFERED` set, so the
console and the log agree line for line even when a producer is force-stopped.

Two things the script deliberately does not do. It never stops Slicer: closing
Slicer is manual step 6, and it has to be done by hand for the step to mean
anything. And it starts Slicer only at startup and on the `l` key, so a Slicer
window that appears or disappears at any other time is not from this session -
`run-slicer-tests.ps1 -Headful` also opens and closes a Slicer for the duration
of the suite, and that is the usual explanation.

## The same session by hand

The rest of this document is written as the manual procedure, both because the
script is doing exactly these steps and because a verification procedure that
can only be followed through one script is not reproducible. Three shells are
used, referred to as Terminal 1 (acquisition), Terminal 2 (map producer) and
Terminal 3 (trigger and inspection). Slicer is the fourth window.

## Startup and shutdown order

The order matters, and it is fixed for the session:

1. **Terminal 1** - acquisition stand-in on the case. It serves `LiveView` on
   `127.0.0.1:18944`, `HSCube` on 18947 and the control channel on 18950, and
   writes nothing.
2. **Slicer** - the SLIAFlow launcher, connected to the Acquisition link.
3. **Terminal 3** - a capture trigger. The stand-in holds the capture delay and
   reports `READY`.
4. **Terminal 2** - genuine UC1 runner on the case folder. It classifies once and
   then serves `UC1_RGB` and `UC1_MV_CLASS` on `127.0.0.1:18945`.

A connector started against a closed port reports `connecting`; press Disconnect
and Connect again once the producer is up if it does not recover by itself.

Shutdown is the reverse, and both directions are checked deliberately in steps 5
and 6 because they exercise different code: stopping a producer under a live
connector, and closing a connector under a live producer.

The live pane shows the received `LiveView` stream, which is the laptop camera
opened by the stand-in. Only one process can hold the camera, so SLIAFlow's own
camera path stays off for this session.

## Step 1 - Pre-session automated baseline

Run the suites and record the output. This is the baseline the same suites are
compared against in step 7, so that a configuration change made during the
session cannot introduce a regression unnoticed.

```powershell
cd C:\stratum
.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py
.\scripts\development\run-slicer-tests.ps1
.\scripts\development\run-slicer-tests.ps1 -Headful
```

The headless Slicer run skips the view tests because it has no layout manager.
The `-Headful` run keeps the main window, so it is the run that actually covers
the panes this session is about. Record all three.

| Suite | Command | Result | Recorded |
| --- | --- | --- | --- |
| Simulators | `tools\simulators\tests\run_tests.py` |  |  |
| SLIAFlow, headless | `run-slicer-tests.ps1` |  |  |
| SLIAFlow, headful | `run-slicer-tests.ps1 -Headful` |  |  |

## Step 2 - The full loop with the genuine pipeline

**Terminal 1.** Start the stand-in on the case:

```powershell
.\scripts\development\run-acquisition-simulator.ps1 -Case 004-02
```

It prints the recorded-data notice, the case's size, band count and wavelength
range, and the three ports it listens on.

**Slicer.** Launch `build\SLIAFlow\SlicerWithSLIAFlow.exe`, open SLIAFlow from
the STRATUM category, and then:

1. Set **Live source** to `AcquisitionSystemApp LiveView`.
2. Press **Connect** on the **Acquisition link** row. The state label goes to
   `connecting` and then to `displaying`; the live pane shows the laptop camera.

**Terminal 3.** Trigger a capture:

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"
.\.venv\Scripts\python.exe -m stratum_sim capture
```

It prints `CAPTURING capture=1 case=004-02 delay=<seconds>` and, after the delay,
`READY capture=1 case=004-02 folder=...`, and exits 0.

**Terminal 2.** Run the genuine pipeline on the case and serve the result:

```powershell
.\scripts\development\run-uc1-real.ps1 -DatasetFolder input\bin\bin\004-02
```

It prints the `UC1_RGB` band resolution, the vendored binary's own stdout
prefixed `[uc1]`, the recovered map's shape and class histogram, and the
`Time simulation` line that is the GPU wall clock.

**Slicer.**

3. Set **Result map** to `majorityVotingMap`. That is the only map a genuine UC1
   run sends; the other four are computed and discarded by the pipeline itself.
4. Press **Connect** on the **UC1 link** row.
5. Tick **Demo mode**.

The result pane shows the class map over `UC1_RGB` under a red banner. Its
headline is the real-pipeline wording, and its second line is whatever the
producer put on the wire:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
```

The second line is read by the runner from the case folder, not from a switch.
Record which case this session ran and the line it produced - the point of the
line is that it describes the data, so a mismatch between the folder and the line
is a defect.

Measure the frame rate actually delivered. **One client at a time.**
`pyigtl.OpenIGTLinkServer` is a plain `socketserver.TCPServer` whose request
handler loops for the whole life of a connection, so a producer serves exactly one
client and a second one waits unserved in the accept backlog. So measure it with
SLIAFlow's acquisition link down. Press **Disconnect** on the **Acquisition link**
row, then in Terminal 3:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py
```

It exits after 60 frames. Press **Connect** on the same row again afterwards and
confirm the live pane comes back, which exercises the reconnect path once more.

| Measurement | Value |
| --- | --- |
| Case and its size | |
| Preset | |
| Live frame rate reported by `liveview_client.py` | |
| Capture delay reported | |
| `UC1_RGB` band resolution printed | |
| UC1 `Time simulation` | |
| Class histogram of the recovered map | |
| Banner headline observed | |
| Banner second line observed | |
| UC1 link state label while receiving | |

## Step 3 - Stopping and restarting the map producer

This is the step the procedure exists for. Change nothing in Slicer.

**Terminal 2.** Ctrl-C the genuine runner. Wait until the UC1 link row reports
the link is down, then start the runner again on the same case:

```powershell
.\scripts\development\run-uc1-real.ps1 -DatasetFolder input\bin\bin\004-02
```

Do not touch the module panel, do not press Disconnect, do not restart Slicer.
The UC1 link drops when the producer exits, the panel says so, and the retained
map stays on screen with its banner rather than being blanked. When the runner
comes up again, the connector reconnects and the pane recovers on its own, under
a new capture ID.

| Observation | Value |
| --- | --- |
| Panel state while no producer was listening | |
| Whether the retained map stayed on screen with its banner | |
| Time from the runner listening to the pane updating | |
| Banner headline and second line after the restart | |
| Anything reconfigured in SLIAFlow to make this work | |

The last row is the acceptance criterion. It should read "nothing".

## Step 4 - Genuine node precedence

With the runner still sending, add a genuine-marked node for the same map role
through the approved developer path in
`docs/development/simulated_result_verification.md`, using
`RESULT_MAP_MV_CLASS` as the role and `RESULT_SOURCE_GENUINE_ORIGIN` as the
origin, then press **Refresh Result**.

The banner disappears immediately and the genuine node is displayed in preference
to the received simulated one, with demo mode still ticked. Demo mode is an
opt-in to display simulated data, never a preference for it.

Clear the scene of the hand-made node before continuing, so nothing later in the
session is read against a node that was created by hand:

```python
slicer.mrmlScene.RemoveNode(node)
```

| Observation | Value |
| --- | --- |
| Banner state after the genuine node was added | |
| Which node the result pane displayed | |
| Result status text | |
| Behaviour after the genuine node was removed | |

## Step 5 - Stopping the producers under a live connector

Ctrl-C both producers with Slicer still connected.

Both panes keep the last valid image and both state labels go to `disconnected`.
The result status becomes the stale warning and, because the retained image is
simulated, keeps its `SIMULATED: ` prefix and its banner. No invalid or empty
data is presented as a success, and Slicer does not freeze. (The 2026-09-04
session found the state labels stuck at `displaying`; that was `SLIA-016`, now
completed, and this step is its regression check.)

| Observation | Value |
| --- | --- |
| Live pane after the acquisition stand-in stopped | |
| Result pane after the map producer stopped | |
| Result status text | |
| Banner state on the retained image | |
| Any freeze, error dialog, or unresponsive panel | |

## Step 6 - Closing Slicer under live producers

Restart both producers, trigger a capture, reconnect both links, confirm both
panes are live, then close Slicer while both producers keep running.

Slicer exits cleanly and the producers stay up, but what they print is not tidy:
pyigtl's request handler catches the failing send, prints a traceback and logs
`Error while sending data`, and only then releases the connection so that a
later client can be accepted. A traceback here is the expected shutdown path,
not a defect; the process staying alive and serving a later connection is what
is being checked.

Nothing is left holding a socket or the camera:

```powershell
netstat -ano | findstr "18944 18945 18947 18950"
```

The only sockets remaining are the producers' own listening sockets. After
Ctrl-C on both producers, the command prints nothing.

| Observation | Value |
| --- | --- |
| Slicer exit behaviour | |
| Producer behaviour after the client went away (traceback text) | |
| Whether a later Slicer session reconnected without restarting the producers | |
| `netstat` output with producers running | |
| `netstat` output after both producers stopped | |
| Whether the laptop camera opens in another application afterwards | |

## Step 7 - Post-session automated baseline

Re-run the three commands from step 1 and compare against the recorded baseline.

| Suite | Result | Matches step 1 |
| --- | --- | --- |
| Simulators | | |
| SLIAFlow, headless | | |
| SLIAFlow, headful | | |

## Failures observed, and their recovery

One row per failure encountered during the session, whether or not it was
expected. A row here that is a defect gets a backlog task, and the task ID goes
in the last column.

| # | What happened | What it looked like in the panel | Recovery | Filed as |
| --- | --- | --- | --- | --- |
| 1 | | | | |

## What changes when real hardware arrives

Nothing in `extensions/`. The acquisition application takes over
`127.0.0.1:18944`, 18947 and 18950, and the genuine UC1 pipeline keeps
`127.0.0.1:18945`, all already the endpoints SLIAFlow connects to. The one thing
that must change is on the producers' side: a result computed from a real
acquisition sends `SLIAFlow.DataOrigin = external-genuine` and no simulation
detail, at which point SLIAFlow displays it with no banner and demo mode stops
being relevant to it.

## Session record

| | |
| --- | --- |
| Date | |
| Branch | |
| Slicer | |
| Case | |
| Producers | acquisition stand-in on 18944, 18947 and 18950; genuine UC1 runner on 18945 |
| Outcome | |

## History

This procedure was first run on 2026-09-04 under `SLIA-014`, over a generated
tissue phantom and with a second, arithmetic map producer swapped onto 18945. Both
were retired in `SLIA-025`, so that record is not repeated here; it is kept in
`tasks/completed/SLIA-014-end-to-end-workflow-verification.md` and in this file's
Git history. The defects it found were filed as `SLIA-016` and `SLIA-017`.
