# End-to-end hardware-free workflow verification

This is the procedure for running the whole three-box workflow on one machine
with no hyperspectral camera: the acquisition stand-in producing a `LiveView`
stream, the genuine UC1 CUDA pipeline producing a class map, and SLIAFlow
receiving both over OpenIGTLink.

It is written to be followed, not read. Every step names the exact control to
use and the exact text to look for, and every measurement has a place to be
written down. A second person holding only this document and the repository
should be able to repeat the whole session and get the same answers.

If you only want to *run* a session rather than record one, read
`pipeline_test_quickstart.md` instead: it is the same launcher and the same
checks, without the evidence tables.

**Nothing in this procedure produces a clinical result.** The scene is a
synthetic optical phantom, the pipeline is real, and a real algorithm run over
an invented scene is still not a diagnosis. Every map displayed during this
session carries a banner, and no screenshot may be taken of a result pane
without that banner visible in it.

## What this session is for

Each component has already been verified alone. What has never been exercised is
all of them at once, and one property in particular: that stopping one map
producer and starting a different one on the same port changes what SLIAFlow
displays and how it labels it, without SLIAFlow being reconfigured, restarted, or
told which producer it is talking to.

That property is why the architecture puts the seam at the network boundary. If
it holds, the arrival of real hardware is a configuration change. If it does not,
it is a project. The producer swap in step 3 is the measurement of that, and it
is the reason both producers use `127.0.0.1:18945`.

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
| Ports 18944 and 18945 free on the loopback interface | No earlier simulator or Slicer session still running | `netstat -ano \| findstr "18944 18945"` |

## Running the whole session from one console

Everything below can be driven from a single shell:

```powershell
cd C:\stratum
.\scripts\development
un-end-to-end-session.ps1
```

Windows PowerShell and PowerShell 7 both run it. From an editor or a shell that
blocks unsigned scripts, invoke it as
`powershell -ExecutionPolicy Bypass -File .\scripts\developmentun-end-to-end-session.ps1`.

That script does the setup this document describes by hand: it refuses to start
if anything already holds 18944 or 18945, writes the dataset, brings up the
acquisition stand-in and then the genuine UC1 runner in the fixed order, waits
for each port to be listening before going on, and starts Slicer. Both
producers' output is tailed into the same console, tagged `[acq]`,
`[uc1-genuine]` or `[uc1-standin]`, and a `[status]` line reports how many
clients each port has whenever that changes and at least every couple of
seconds. The status line is the answer to "is it working": it turns green when
Slicer has connected to both ports.

Four keys drive the session steps that need something to happen outside Slicer:

| Key | What it does | Step |
| --- | --- | --- |
| `s` | Stops the map producer, holds the port unserved for six seconds so the gap is visible in the panel, and starts the other one | 3 |
| `m` | Runs `liveview_client.py` after prompting for the acquisition link to be disconnected, and prompts to reconnect afterwards | 2 |
| `l` | Starts Slicer again after it has been closed, without touching the producers | 6 |
| `q` | Stops both producers and reports whether either port was left held | 5 and 6 |

`n` prints the current `netstat` rows for both ports, `d` prints the dataset and
log paths, and `?` reprints the list.

Useful switches: `-MapProducer standin` starts on the arithmetic stand-in and
needs no CUDA build, `-NoSlicer` brings the producers up without launching
Slicer, `-SlicerFrom Source` runs the configured Slicer against
`extensions\SLIAFlow\SLIAFlow` instead of the compiled launcher, `-StopStrays`
kills whatever already holds the ports instead of refusing to start, and
`-RunSeconds 30` brings the rig up and takes it down again by itself, which is
the quickest way to check the machine is in a state to run a session at all.

Each run gets its own folder under `workspace\simulators\sessions\`, holding
the dataset and one log file per producer. The producers run with
`PYTHONUNBUFFERED` set, so the console and the log agree line for line even when
a producer is force-stopped - a redirected Python stdout is otherwise
block-buffered, which is how the acquisition stand-in's rate line was lost from
the first recorded session.

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
Terminal 3 (inspection). Slicer is the fourth window.

## Startup and shutdown order

The order matters, and it is fixed for the session:

1. **Terminal 1** - acquisition stand-in. It writes the dataset and then serves
   `LiveView` on `127.0.0.1:18944`. It has to run first because the map producer
   needs the dataset folder it prints.
2. **Terminal 2** - genuine UC1 runner on the dataset folder from step 1. It
   classifies once and then serves `UC1_MV_CLASS` on `127.0.0.1:18945`.
3. **Slicer** - the SLIAFlow launcher. SLIAFlow connects as a client to both
   ports, so both producers must be listening before the Connect buttons are
   pressed. A connector started against a closed port reports `connecting` and
   does not recover by itself on the first attempt; press Disconnect and
   Connect again once the producer is up.

Shutdown is the reverse, and both directions are checked deliberately in steps 5
and 6 because they exercise different code: stopping a producer under a live
connector, and closing a connector under a live producer.

The live pane uses the received `LiveView` stream, not the laptop camera, so the
laptop camera stays off for this session. The acquisition stand-in's `webcam`
frame source is not used either; the default `synthetic` source and the default
`tissue` scene are what the genuine pipeline resolves to anything at all.

## Step 1 - Pre-session automated baseline

Run both suites and record the output. This is the baseline the same two suites
are compared against in step 7, so that a configuration change made during the
session cannot introduce a regression unnoticed.

```powershell
cd C:\stratum
.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py
.\scripts\development\run-slicer-tests.ps1
.\scripts\development\run-slicer-tests.ps1 -Headful
```

The headless Slicer run skips six view tests because it has no layout manager.
The `-Headful` run keeps the main window and skips only one, so it is the run
that actually covers the panes this session is about. Record both.

| Suite | Command | Result | Recorded |
| --- | --- | --- | --- |
| Simulators | `tools\simulators\tests\run_tests.py` | `Ran 110 tests in 1.536s` / `OK`, exit 0 | 2026-09-04 |
| SLIAFlow, headless | `run-slicer-tests.ps1` | `Ran 45 tests in 0.737s` / `OK (skipped=6)`, exit 0 | 2026-09-04 |
| SLIAFlow, headful | `run-slicer-tests.ps1 -Headful` | `Ran 45 tests in 3.680s` / `OK (skipped=1)`, exit 0 | 2026-09-04 |

## Step 2 - The full loop with the genuine pipeline

**Terminal 1.** Write a scene and serve the live view:

```powershell
.\scripts\development\run-acquisition-simulator.ps1
```

Note the dataset folder it prints; the next command needs it.

**Terminal 2.** Run the genuine pipeline on that folder and serve the class map:

```powershell
.\scripts\development\run-uc1-real.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS
```

It prints the vendored binary's own stdout prefixed `[uc1]`, the recovered map's
shape and class histogram, and the `Time simulation` line that is the per-cycle
GPU wall clock.

**Slicer.** Launch `build\SLIAFlow\SlicerWithSLIAFlow.exe`, open SLIAFlow from
the STRATUM category, and then:

1. Set **Live source** to `AcquisitionSystemApp LiveView`.
2. Press **Connect** on the **Acquisition link** row. The state label goes to
   `connecting` and then to `displaying`; the live pane shows the streaming
   frames.
3. Set **Result map** to `majorityVotingMap`. That is the only map a genuine UC1
   run sends; the other four are computed and discarded by the pipeline itself.
4. Press **Connect** on the **UC1 link** row.
5. Tick **Demo mode**.

The result pane shows the class map under a red banner. Its headline is the
real-pipeline wording, and its second line is whatever the producer put on the
wire:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, synthetic tissue phantom
```

The second line is read by the runner from the dataset folder, not from a
switch. A folder carrying a phantom record yields `real UC1 pipeline, synthetic
tissue phantom`; a folder without one yields `real UC1 pipeline, synthetic
input`. Both select the same headline. Record which one this session saw and
which dataset produced it - the point of the line is that it describes the data,
so a mismatch between the folder and the line is a defect.

Measure the frame rate actually delivered rather than the rate the acquisition
stand-in reports queueing. **One client at a time.** `pyigtl.OpenIGTLinkServer`
is a plain `socketserver.TCPServer` whose request handler loops for the whole
life of a connection, so a producer serves exactly one client and a second one
waits unserved in the accept backlog. Running the measuring client while
SLIAFlow is connected therefore measures nothing and times out after ten
seconds.

So measure it with SLIAFlow's acquisition link down. Press **Disconnect** on the
**Acquisition link** row, then in Terminal 3:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py
```

The measuring client is accepted only once the producer notices SLIAFlow has
gone, which happens on its next failed send - a second or two at the streaming
rate. If it times out instead, note it in the failures table.

It exits after 60 frames. Press **Connect** on the same row again afterwards and
confirm the live pane comes back, which exercises the reconnect path once more.
Record both the client's figure and the rate the stand-in prints, and note that
the two are not measured at the same instant.

| Measurement | Value |
| --- | --- |
| Dataset folder | `workspace\simulators\datasets\sim-20260904-150404` |
| Preset and band count | `demo`, 160 x 120, 93 bands, scene `tissue`, frame source `synthetic` |
| Live frame rate reported by `liveview_client.py` | 60 frames in 6.60 s, 8.94 fps against a 10 fps target |
| Live frame rate claimed by the acquisition stand-in | Not captured. Python block-buffers stdout when it is redirected, and this session's producers were ended by `Stop-Process` rather than Ctrl-C, so the buffered line was lost. See the failures table |
| UC1 `Time simulation` per cycle | 271.857 ms, from a `-ClassifyOnly` re-run on the same dataset |
| Class histogram of the recovered map | `{2: 7502, 4: 11698}` over `(1, 120, 160) uint8` as displayed; `{2: 7504, 4: 11696}` on the `-ClassifyOnly` re-run. The pipeline's k-means is not seeded, so two runs over one cube differ by a few pixels |
| Banner headline observed | `SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT` |
| Banner second line observed | `real UC1 pipeline, synthetic tissue phantom`, matching the phantom record in the dataset folder |
| UC1 link state label while receiving | `displaying` |

Also recorded, because they are the pane-binding claim rather than a
measurement: the live pane's background was the `LiveView` node and the result
pane's background was `None` before the UC1 link was connected; with demo mode
unticked the result pane stayed on `WARN: Waiting for genuine UC1_MV_CLASS
result.` and no banner existed; the result status once demo mode was ticked read
`PASS: SIMULATED: Displaying Majority-voting class from UC1_MV_CLASS.`, with
`dataOrigin = simulated`.

The measuring client was served only after the acquisition link came down, as
the procedure predicts, and the live pane returned to `displaying` on
reconnect.

## Step 3 - The producer swap

This is the step the task exists for. Change nothing in Slicer.

**Terminal 2.** Ctrl-C the genuine runner, then start the arithmetic stand-in on
the same port, against the same dataset:

```powershell
.\scripts\development\run-uc1-simulator.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS `
    -Cycles 0 -SendNotice
```

Do not touch the module panel, do not press Disconnect, do not restart Slicer.
The UC1 link drops when the first producer exits, the panel says so, and the
retained map stays on screen with its banner rather than being blanked. When the
stand-in comes up, the connector reconnects and the pane recovers on its own.

The stand-in sends all five maps, so `majorityVotingMap` continues to be
available under the same selection. The banner changes:

```
SIMULATED - NOT A GENUINE UC1 RESULT
arithmetic stand-in, not a classifier
```

Both the headline and the second line change, because the stand-in is not a
classifier and the softer real-pipeline wording would be a false statement in red
over the view.

| Observation | Value |
| --- | --- |
| Panel state while no producer was listening | Not observed. The session was driven from a script that released Slicer only once the replacement producer was already listening, so the gap was never sampled. The states seen were `receiving` and `displaying`, both from after the swap. This row is unmet evidence, not a pass |
| Whether the retained map stayed on screen with its banner | Yes. The result node stayed referenced and the banner stayed on it across the swap |
| Time from starting the stand-in to the pane updating | Under 0.2 s from the driver being released, for the same reason the gap was not sampled: the producer was already up |
| Banner headline after the swap | `SIMULATED - NOT A GENUINE UC1 RESULT` |
| Banner second line after the swap | `arithmetic stand-in, not a classifier` |
| Anything reconfigured in SLIAFlow to make this work | Nothing. No Disconnect, no restart, no change of result map, no change of endpoint |

The last row is the acceptance criterion. It should read "nothing".

## Step 4 - Genuine node precedence

With the stand-in still sending, add a genuine-marked node for the same map role
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
| Banner state after the genuine node was added | Gone. Both the headline actor and the detail actor were released, with demo mode still ticked |
| Which node the result pane displayed | The genuine node, `UC1_MV_CLASS-genuine`, reported as `sourceNodeName` with `dataOrigin = external-genuine`, in preference to the received simulated `UC1_MV_CLASS` |
| Result status text | `PASS: Displaying Majority-voting class from UC1_MV_CLASS.`, with no `SIMULATED: ` prefix |
| Behaviour after the genuine node was removed | The received simulated node was picked up again on the next refresh and the banner returned with the stand-in wording |

## Step 5 - Stopping the producers under a live connector

Ctrl-C both producers with Slicer still connected.

Both panes keep the last valid image and both state labels go to `disconnected`.
The result status becomes the stale warning and, because the retained image is
simulated, keeps its `SIMULATED: ` prefix and its banner. No invalid or empty
data is presented as a success, and Slicer does not freeze.

**This step failed.** Both link state labels went on reporting `displaying`
after both producers had been killed, through a 120-second settle window, with
`netstat` confirming nothing was listening on either port. Filed as
`SLIA-016`; see the failures table.

| Observation | Value |
| --- | --- |
| Live pane after the acquisition stand-in stopped | Kept the last valid frame, which is correct. State label `displaying`, which is not |
| Result pane after the map producer stopped | Kept the last valid map, which is correct. State label `displaying`, which is not |
| Result status text | `PASS: SIMULATED: Displaying Majority-voting class from UC1_MV_CLASS.` - it should have degraded to the stale `WARN` |
| Banner state on the retained image | Correct: `SIMULATED - NOT A GENUINE UC1 RESULT` over `arithmetic stand-in, not a classifier`, still on the retained image |
| Any freeze, error dialog, or unresponsive panel | None. The main window stayed responsive throughout |

What the step got right is worth separating from what it got wrong. No invalid
or empty data was presented as a success, nothing was blanked, nothing froze,
and the banner stayed with the image it describes. What failed is the state
label and the result status, which both went on claiming a live link. The two
disagreed with each other, which is worse than either being wrong alone: the
disconnection was observed when the connector reported it, and then overwritten
by the next refresh.

## Step 6 - Closing Slicer under live producers

Restart both producers, reconnect both links, confirm both panes are live, then
close Slicer while both producers keep running.

Slicer exits cleanly and the producers stay up, but what they print is not tidy:
pyigtl's request handler catches the failing send, prints a traceback and logs
`Error while sending data`, and only then releases the connection so that a
later client can be accepted. A traceback here is the expected shutdown path,
not a defect; the process staying alive and serving a later connection is what
is being checked.

That release depends on the producer attempting a send after the client has
gone - it is the failing `sendall` that ends the handler. Both producers send on
an interval, so it happens within a cycle or two. If a later Connect from Slicer
never leaves `connecting` while the producer is still running, the handler did
not release the connection: record it in the failures table, restart that
producer to continue, and file it.

Nothing is left holding a socket or a camera:

```powershell
netstat -ano | findstr "18944 18945"
```

The only sockets remaining are the producers' own listening sockets. After
Ctrl-C on both producers, the command prints nothing.

| Observation | Value |
| --- | --- |
| Slicer exit behaviour | Exited with no surviving process. Both producers stayed up |
| Producer behaviour after the client went away (traceback text) | As documented: a pyigtl traceback ending `ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host`, then `ConnectionAbortedError: [WinError 10053] ...`, each followed by `Error while receiving data: ...`. Both processes kept running |
| Whether a later Slicer session reconnected without restarting the producers | Yes. A fresh launcher session connected both links and reached `displaying` on both, with the result showing `arithmetic stand-in, not a classifier`; demo mode was off on entry, as SLIA-010 requires. `cleanup()` left zero `vtkMRMLIGTLConnectorNode` in the scene |
| `netstat` output with producers running | Exactly two listening sockets, `127.0.0.1:18944` and `127.0.0.1:18945`, one process each |
| `netstat` output after both producers stopped | Nothing on either port |
| Whether the laptop camera opens in another application afterwards | Not applicable to this session. The live pane used the received `LiveView` stream throughout and the laptop camera was never started, so there was nothing to leave locked |

## Step 7 - Post-session automated baseline

Re-run the three commands from step 1 and compare against the recorded baseline.

| Suite | Result | Matches step 1 |
| --- | --- | --- |
| Simulators | `Ran 110 tests in 1.513s` / `OK`, exit 0 | Yes |
| SLIAFlow, headless | `Ran 45 tests in 0.850s` / `OK (skipped=6)`, exit 0 | Yes |
| SLIAFlow, headful | `Ran 45 tests in 3.823s` / `OK (skipped=1)`, exit 0 | Yes |

The defect found in step 5 is not caught by either suite, which is the reason
this session exists. `SLIA-016` carries the test that would have caught it.

## Failures observed, and their recovery

One row per failure encountered during the session, whether or not it was
expected. A row here that is a defect gets a backlog task, and the task ID goes
in the last column.

| # | What happened | What it looked like in the panel | Recovery | Filed as |
| --- | --- | --- | --- | --- |
| 1 | Both links went on reporting `displaying` after both producers were killed and nothing was listening on either port | State labels `displaying` on both rows, and the result status still `PASS: SIMULATED: ...` instead of the stale `WARN` | None needed within the session; reconnecting a producer restored a true state | `SLIA-016` |
| 2 | Three processes were found listening on `127.0.0.1:18945` at once during setup, and the Slicer connector had reached none of the two that were meant to be there | Indistinguishable from a healthy session in the panel, which is what makes it dangerous: the banner is the only thing that would have shown it | The whole run was discarded, every stray process was stopped, and the session was restarted from a port verified free | `SLIA-017` |
| 3 | The acquisition stand-in's own enqueue-rate line read `0.01 fps (target 10.00 fps)` in the discarded run, while the receiver measured 8.94 fps in the recorded one. The line describes itself as an upper bound on the delivered rate, so it cannot legitimately fall three orders of magnitude below it | Nothing. This is producer-side reporting and never reaches SLIAFlow | Not reproduced. The line was lost from the recorded session because the producers were force-stopped with their stdout block-buffered; a later run under `run-end-to-end-session.ps1`, which sets `PYTHONUNBUFFERED`, printed `9.37 fps (target 10.00 fps)` enqueued while a receiver measured 9.06 fps, which is the relationship the line claims | Not filed. The only evidence is from a run discarded for the port collision above, and evidence from a run that cannot be trusted is not grounds for a card. It is written down here so the next session looks for it |

Rows 2 and 3 were found during setup and in a discarded run rather than in the
recorded session. They are kept because the point of a failures table is what
the session learned, not only what it scored.

## What changes when real hardware arrives

Nothing in `extensions/`. The acquisition application takes over
`127.0.0.1:18944` and the genuine UC1 pipeline keeps `127.0.0.1:18945`, both
already the endpoints SLIAFlow connects to. The one thing that must change is on
the producers' side: a result computed from a real cube sends
`SLIAFlow.DataOrigin = external-genuine` and no simulation detail, at which point
SLIAFlow displays it with no banner and demo mode stops being relevant to it.

That is the whole migration, and step 3 of this procedure is the evidence for it:
SLIAFlow was never told which producer was on the port, and its display followed
the data every time.

## Session record

| | |
| --- | --- |
| Date | 2026-09-04 |
| Branch | `feature/SLIA-014-end-to-end-workflow-verification` |
| Slicer | `build\SLIAFlow\SlicerWithSLIAFlow.exe`, headful |
| Dataset | `workspace\simulators\datasets\sim-20260904-150404` |
| Producers | acquisition stand-in on 18944; genuine UC1 runner then SLIA-012 stand-in on 18945 |
| Outcome | Steps 1, 2, 3, 4, 6 and 7 passed. Step 5 failed and is filed as `SLIA-016`. One row of step 3 is unmet evidence rather than a pass |

The session was driven from a script rather than by hand, with the shell and the
Slicer process handing off to each other through marker files, so that the
producer swap and the two shutdown directions happened at points the record can
name. Everything the tables report is a value read from the running module -
state labels, status text, banner actor contents, pane bindings, node
attributes - not an inference from the code. What a script cannot attest to is
what the operator sees, so a confirmation by eye of the panes and the banner is
still outstanding.

Provenance followed the data at every stage and was never inferred from the
endpoint. Both producers used `127.0.0.1:18945`; the same connector, unchanged,
reported `real UC1 pipeline, synthetic tissue phantom` for one and `arithmetic
stand-in, not a classifier` for the other, and dropped the banner entirely for a
genuine-marked node while demo mode was still ticked.
