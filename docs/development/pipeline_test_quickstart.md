# Testing the pipeline: a quick start

> **Historical since `SLIA-028`.** This quick start runs
> `run-end-to-end-session.ps1`, which `SLIA-028` removed with the standalone
> acquisition stand-in and UC1 runner it launched, so the commands below no
> longer work. It is kept as the record of that session. The current way to run
> is the in-Slicer demonstration in `uc1_demo_runbook.md`.

One console, one command, and a numbered list of what to do and why. This is the
short version of `end_to_end_verification.md`, which is the full procedure with
its evidence tables. Read this to run a session; read that one to record one.

Nothing here is a clinical result. A session shows a recorded case of the public,
anonymized HSI Human Brain Database and the laptop camera, and nothing made up.
Only the acquisition event is simulated, and every label says exactly that.
Nothing under `input\` is written.

## What you are actually testing

Three boxes that have each been verified alone, now run at once:

- an **acquisition stand-in** on ports 18944, 18947 and 18950, streaming the
  laptop camera as `LiveView` where the hyperspectral rig's camera would be, and
  publishing the case's cube as `HSCube` when a capture is triggered;
- the **genuine UC1 CUDA pipeline** on port 18945, which classifies the case once
  the first capture is ready and serves `UC1_RGB` and `UC1_MV_CLASS`;
- **SLIAFlow** inside 3D Slicer, which connects out to the producers as a client
  and displays what it receives.

The property under test is not "does a picture appear". It is that **SLIAFlow
believes the wire, not its configuration**: the provenance on screen is the
provenance that arrived, and a producer that goes away or comes back is followed
without SLIAFlow being reconfigured or restarted.

## Before the first run

You need, once:

- `.venv` created and `tools/simulators/requirements.txt` installed.
- The UC1 build under `build\uc1\UC1` (`uc1_local_build.md`).
- The recorded cases under `input\bin\bin`.
- Either `build\SLIAFlow\SlicerWithSLIAFlow.exe` (`build-sliaflow.ps1`), or a
  `slicerExecutable` entry in `config\local.json` if you want `-SlicerFrom
  Source`.

Nothing else is set up per session. The launcher writes its logs into a
timestamped folder under `workspace\simulators\sessions\` each time.

## The one command

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

`pwsh` runs it too; the `-ExecutionPolicy Bypass` form is what to use from an
editor or any shell that refuses unsigned scripts. Run it from the repository
root. No other terminal is needed - the launcher starts the producers and
Slicer, tails every producer log into this console, and reports how many clients
each port has.

`-Case` is required. Without it the launcher stops before anything starts:

```
ERROR: A session runs one recorded case of the HSI Human Brain Database. Pass -Case, for example -Case 004-02.
```

### The switches worth knowing

| Switch | What it does |
| --- | --- |
| `-Case 004-02` | The recorded case to run. Required. |
| `-DatasetRoot <path>` | Where the cases live, when that is not `input\bin\bin`. |
| `-InstantCapture` | Complete each capture at once instead of after 5 to 8 seconds. |
| `-Preset medium\|full` | Bigger LiveView frames. The cube is always the case's own size. |
| `-NoSlicer` | Bring the producers up and start Slicer yourself, or not at all. |
| `-RunSeconds 30` | End the session by itself after 30 seconds. With `-NoSlicer`, this is the way to check the rig comes up and tears down cleanly without sitting through a session. |
| `-SlicerFrom Source` | Run the configured Slicer with `extensions\SLIAFlow\SLIAFlow` on the module path. Use this while editing the module. |
| `-StopStrays` | Kill whatever already holds 18944, 18945, 18947 or 18950 rather than refusing to start. |

## Step by step

### Step 1 - Watch the rig come up

Nothing to do. Read the console. Each stage waits for the previous one to open
its ports, so the order is fixed and a stall is visible where it happens.

```
[check]    Port 18944 is free (LiveView).
[check]    Port 18945 is free (UC1 maps).
[check]    Port 18947 is free (HSCube).
[check]    Port 18950 is free (capture control).
[acq]      RECORDED PUBLIC DATA, SIMULATED ACQUISITION, NON-CLINICAL USE. The cube is case 004-02 ...
[acq]      Acquisition stand-in: recorded case '004-02' (345x389, 93 bands, 440-900 nm), LiveView from the laptop camera (index 0) at preset 'demo', ...
[acq]        Case folder, read-only: C:\stratum\input\bin\bin\004-02
[acq]        LiveView server listening on 127.0.0.1:18944 as device 'LiveView'.
[acq]        HSCube server listening on 127.0.0.1:18947 as device 'HSCube'.
```

*Why:* the port checks come first because a stray producer from an earlier run
is indistinguishable from a healthy one once Slicer is connected, and that
mistake once cost a whole session.

**The map producer does not start yet.** It starts on the case when the first
capture reports `READY`: camera, capture, cube, UC1 - the order the demonstration
shows.

### Step 2 - Connect SLIAFlow

In Slicer, in this order:

1. Open **SLIAFlow** from the STRATUM category.
2. **Live source** to `AcquisitionSystemApp LiveView`, then **Connect** on the
   Acquisition link row. The live pane fills with the laptop camera.
3. **Result map** to `majorityVotingMap`, then **Connect** on the UC1 link row.
   Nothing serves it until the first capture, so it waits.
4. Tick **Demo mode**.

Only one process can hold the camera, so leave SLIAFlow's own camera path off.

Watch the console rather than guessing:

```
[status]   live 18944: 1 client(s) | map 18945: 0 client(s), waiting for the first capture | cube 18947: 0 client(s) | Slicer: running
```

*Why:* SLIAFlow owns its connectors as an OpenIGTLink **client** - the producers
listen, the module dials out. The `[status]` line is the independent witness: it
counts real established sockets, not what the panel claims. It updates on every
change and at least every two seconds.

If a port reports **more than one** client, stop and read the red line
underneath it. Only the first client attached to a producer receives anything;
any other reports itself connected and stays empty. That is the most common
reason a session looks broken when nothing is broken.

### Step 3 - Capture. Press `c`.

A capture reads roughly like this, the delay drawn between 5 and 8 seconds:

```
[session]  Capture trigger 1: sending CAPTURE to 127.0.0.1:18950.
[capture-1] CaptureReply: CAPTURING capture=1 case=004-02 delay=6.4
[acq]        Capture 1 complete: READY capture=1 case=004-02 folder=C:\stratum\input\bin\bin\004-02
[session]  The first capture is ready. Starting the genuine UC1 pipeline on C:\stratum\input\bin\bin\004-02.
[uc1-genuine] Origin:     simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
[uc1-genuine] UC1_RGB bands: 710 nm -> index 54 at 710 nm (miss 0.00 nm); 540 nm -> index 20 at 540 nm (miss 0.00 nm); 480 nm -> index 8 at 480 nm (miss 0.00 nm)
[uc1-genuine]   [uc1] Time simulation ---> 564.417 ms
[uc1-genuine] Recovered majorityVotingMap: shape (1, 389, 345), dtype uint8, classes {1: 55948 (41.7%), 2: 7954 (5.9%), 3: 31589 (23.5%), 4: 38714 (28.8%)}
[session]  The genuine UC1 pipeline is listening on 127.0.0.1:18945.
```

Those `classes` are what the 2026-09-16 session on `004-02` recovered. Press `c`
again during the delay and the second trigger client reports
`IGNORED capture 1 already in progress`: one capture at a time, and nothing is
queued.

*Why:* the line to read is **`classes {...}`**. More than one class means the map
has something in it. A single class is a valid map and a useless picture, and the
runner says so: `WARNING: UC1 resolved every pixel to class ...`.

### Step 4 - Read the result and its provenance

The result pane shows the class map over `UC1_RGB`, three bands of the same cube,
and carries the banner and the detail that arrived with it:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
```

*Why:* the provenance travels with the data, in OpenIGTLink metadata, not in the
module's settings. The header must be version 2, or metadata is silently dropped
and the banner would be showing a default rather than what arrived.

### Step 5 - Measure the live frame rate. Press `m`.

It will ask you to press **Disconnect** on the Acquisition link row first, then
Enter. It runs a bare client, prints the delivered rate, and asks you to press
**Connect** again.

*Why:* pyigtl serves one client at a time, so a measurement taken while SLIAFlow
holds the link would measure nothing.

### Step 6 - Shut down in both directions

Close Slicer while the producers run. Then press `q` to stop the producers.

*Why:* both directions have to be clean, and neither is obvious. Closing Slicer
first produces a pyigtl traceback and `Error while sending data` from a producer
- that is the expected path, because the transport only notices a gone client on
a failing send, not on EOF. `q` and Ctrl-C both tear down and then report
whether any port was left held:

```
[check]    Nothing is listening on 18944, 18945, 18947, 18950. No socket was left held.
```

A held socket is what makes the *next* session refuse to start, so it is checked
at the end of this one rather than discovered at the start of that one.

## The keys, while the session runs

| Key | What it does |
| --- | --- |
| `c` | Trigger a capture (step 3). |
| `m` | Measure the delivered LiveView frame rate (step 5). |
| `l` | Start Slicer again after closing it. |
| `n` | Show what is listening on 18944, 18945, 18947, 18950 and the reserved 18948 and 18949. |
| `d` | Print the case folder and the log paths. |
| `q` | Stop the producers and end the session. |

The launcher never stops Slicer - close that yourself.

## How long things actually take

UC1 is not slow, and **it does not run continuously.** It classifies the cube
**once**, before it opens its port, and then re-sends that same map every second
for as long as a client is connected. On `004-02` the CUDA pipeline itself took
`Time simulation ---> 564.417 ms` in the 2026-09-16 session. The map you see is
final the moment it appears - waiting for it to sharpen, update or converge will
not do anything, because there is nothing left to compute.

Two consequences worth knowing:

- **The cycle counter is a heartbeat, not progress.** `REAL UC1 OUTPUT cycle
  507` means the link has been up for about 507 seconds, nothing more. Cycles
  only advance while a client is connected.
- **If a session felt slow, the time went somewhere else.** The capture delay,
  Slicer's own startup and the clicks in step 2 are usually all of it. The
  console and the log times under `workspace\simulators\sessions\` will say
  exactly where.

## Reading the map

Class 1 is green (normal), 2 red (tumour), 3 blue (hypervascularised) and 4 black
(background). **A coloured area is the output of a classifier run on a prototype,
not a detection**, and nothing on screen is a clinical result.

## When something goes wrong

| What you see | What it is |
| --- | --- |
| `A session runs one recorded case ... Pass -Case` | The launcher was started without `-Case`. |
| `ERROR: Port 18944 is already in use` | A producer from an earlier session survived. `-StopStrays` clears it. The refusal is deliberate: a stray producer looks exactly like a healthy one in the Slicer panel. |
| Slicer opens and closes on its own | Almost always `run-slicer-tests.ps1 -Headful`, which opens a full Slicer for the length of the suite and closes it. This launcher starts Slicer only at startup and on `l`, and never closes it, so anything else is a real event worth recording. |
| A pyigtl traceback and `Error while receiving data: The client closed the connection.` (or `Error while sending data`) after you close Slicer | The expected shutdown path (step 6): the producer lets the closed connection go at once, even on a port that is sending nothing, so a Slicer reopened in its place is served straight away and receives the next cube. |
| `Slicer did not start: ...` | Reported in red; the producers stay up. Fix it and press `l`. |
| The map appears once and never changes | Correct. UC1 classifies once - see *How long things actually take*. |
| Both panes stay empty but the panel says connected | Another Slicer from an earlier session is still attached. A producer serves **one client at a time**; a second one completes its handshake, reports itself connected, and receives nothing until the first lets go. The producer says so under its own tag, within a few seconds: `WARNING: 127.0.0.1:<port> has 2 clients attached ...`. Close the other Slicer; the producer then prints `the warning above no longer applies`. The launcher also refuses to start when it sees this, and names the process. |
| `A client from an earlier session is still retrying these ports` | The check above, firing before anything starts. Close the Slicer it names, or re-run with `-StopStrays` to have it killed for you. |
| The UC1 link never connects | Correct until the first capture: the map producer starts when a capture reports `READY`. Press `c`. |
| The map never appears after a capture | Check the **Result map** name is `majorityVotingMap` and that the UC1 link row is connected. The `[status]` line says whether 18945 has a client. |
| `There is no recorded case folder ...` | `-Case` names a folder that is not under `input\bin\bin`, or under `-DatasetRoot` when one is given. |
| `... does not identify as a case of the HSI Human Brain Database` | The folder has no `gtMap.hdr` carrying the database marker. Only approved database cases are read. |
| `capture-N finished with exit code 1` | The trigger client got no answer. Read the `[acq]` lines: the stand-in has to be listening on 18950. |

SLIAFlow has no consumer for `HSCube` yet, so the stand-in may say the cube is
waiting for a client on 18947. That is expected.

Everything from a session lands in one folder -
`workspace\simulators\sessions\session-<timestamp>\` - with every producer log.
Press `d` to print the path.
