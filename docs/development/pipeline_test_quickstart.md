# Testing the pipeline: a quick start

One console, one command, and a numbered list of what to do and why. This is the
short version of `end_to_end_verification.md`, which is the full procedure with
its evidence tables. Read this to run a session; read that one to record one.

Nothing here is a clinical result. The default session's scene is an optical
phantom the simulator builds, and its maps are produced from invented data. See
`synthetic_tissue_phantom.md` for what the phantom is and, more importantly, what
it is not. A `-Case` session is different: it shows a recorded case of the public
HSI Human Brain Database and the laptop camera, and nothing made up. See
*A recorded case*, below.

## What you are actually testing

Three boxes that have each been verified alone, now run at once:

- an **acquisition stand-in** on port 18944, serving a `LiveView` video stream
  where a hyperspectral camera would be;
- a **map producer** on port 18945, serving a class map - either the genuine UC1
  CUDA pipeline or an arithmetic stand-in;
- **SLIAFlow** inside 3D Slicer, which connects out to both as a client and
  displays what it receives.

The property under test is not "does a picture appear". It is that **SLIAFlow
believes the wire, not its configuration**: swap the producer on 18945 and the
displayed provenance changes, without SLIAFlow being reconfigured or restarted.
That is what the steps below are built around.

## Before the first run

You need, once:

- `.venv` created and `tools/simulators/requirements.txt` installed.
- The UC1 build under `build\uc1\UC1` (`uc1_local_build.md`). Only the genuine
  map producer needs it; the arithmetic stand-in does not.
- Either `build\SLIAFlow\SlicerWithSLIAFlow.exe` (`build-sliaflow.ps1`), or a
  `slicerExecutable` entry in `config\local.json` if you want `-SlicerFrom
  Source`.

Nothing else is set up per session. The launcher writes its own dataset into a
timestamped folder under `workspace\simulators\sessions\` each time.

## The one command

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\development\run-end-to-end-session.ps1
```

`pwsh` runs it too; the `-ExecutionPolicy Bypass` form is what to use from an
editor or any shell that refuses unsigned scripts. Run it from the repository
root. No other terminal is needed - the launcher starts both producers and
Slicer, tails both producer logs into this console, and reports how many clients
each port has.

That default is the one to use: genuine UC1 pipeline, tissue phantom, `demo`
size, Slicer from the build.

### The switches worth knowing

| Switch | What it does |
| --- | --- |
| `-MapProducer standin` | Use the arithmetic stand-in on 18945 instead of the genuine pipeline. Starts in a second; needs no UC1 build. Good for checking the wiring. |
| `-Preset medium\|full` | Bigger frames. `full` is 640x480 and takes noticeably longer to write and classify. |
| `-NoSlicer` | Bring the producers up and start Slicer yourself, or not at all. |
| `-RunSeconds 30` | End the session by itself after 30 seconds. With `-NoSlicer`, this is the way to check the rig comes up and tears down cleanly without sitting through a session. |
| `-SlicerFrom Source` | Run the configured Slicer with `extensions\SLIAFlow\SLIAFlow` on the module path. Use this while editing the module. |
| `-DatasetFolder <path>` | Reuse an existing dataset instead of writing a new one. |
| `-StopStrays` | Kill whatever already holds 18944 or 18945 - and 18947 and 18950 with `-Case` - rather than refusing to start. |
| `-Case 004-02` | Run a recorded case of the HSI Human Brain Database instead of the phantom. See *A recorded case*, below. |
| `-DatasetRoot <path>` | With `-Case`: where the cases live, when that is not `input\bin\bin`. |
| `-InstantCapture` | With `-Case`: complete each capture at once instead of after 5 to 8 seconds. |

## Step by step

### Step 1 - Watch the rig come up

Nothing to do. Read the console. Each stage waits for the previous one to open
its port, so the order below is fixed and a stall is visible where it happens.

```
[check]    Port 18944 is free (LiveView).
[check]    Port 18945 is free (UC1 maps).
[acq]      Acquisition stand-in: preset 'demo' (160x120), 93 bands, scene mode 'tissue', ...
[acq]        Phantom regions: cortex 37.5%, tumour-like 6.9%, vessel 7.6%, drape 48.0%
[acq]        Band covariance rank: 12 ...
[acq]        LiveView server listening on 127.0.0.1:18944 as device 'LiveView'.
[session]  The acquisition stand-in is listening on 127.0.0.1:18944.
[uc1-genuine] Time simulation ---> 315.835 ms
[uc1-genuine] Recovered majorityVotingMap: shape (1, 120, 160), classes {2: 7505 (39.1%), 4: 11695 (60.9%)}
[session]  The genuine UC1 pipeline is listening on 127.0.0.1:18945.
```

*Why:* the port checks come first because a stray producer from an earlier run
is indistinguishable from a healthy one once Slicer is connected, and that
mistake once cost a whole session. The two producer lines are the ones to read
every time:

- **`scene mode 'tissue'`** and the **`Phantom regions:`** line. That is the
  brain-like phantom. If you see `scene mode 'channel'` and no region line, you
  are running the old scene and UC1 will resolve the whole frame to background.
- **`classes {...}`**. More than one class means the map has something in it. A
  single class is a valid map and a useless picture, and the runner says so:
  `WARNING: UC1 resolved every pixel to class ...`.

At `demo` this whole stage takes about three seconds. See *How long things
actually take*, below, before concluding anything is slow.

### Step 2 - Connect SLIAFlow to both ports

In Slicer, in this order:

1. Open **SLIAFlow** from the STRATUM category.
2. **Live source** to `AcquisitionSystemApp LiveView`, then **Connect** on the
   Acquisition link row. The live pane fills.
3. **Result map** to `majorityVotingMap`, then **Connect** on the UC1 link row.
   The result pane fills.
4. Tick **Demo mode**. The red banner appears over the result pane.

Watch the console rather than guessing:

```
[status]   live 18944: 1 client(s) | map 18945: 1 client(s), genuine UC1 | Slicer: running
```

*Why:* SLIAFlow owns both connectors as an OpenIGTLink **client** - the
producers listen, the module dials out. This step proves the module can find and
hold both links, and the `[status]` line is the independent witness that it did:
it counts real established sockets, not what the panel claims. It updates on
every change and at least every two seconds, so it is also the answer to "is
anything actually happening".

If either port reports **more than one** client, stop and read the red line
underneath it. Only the first client attached to a producer receives anything;
any other reports itself connected and stays empty. That is the most common
reason a session looks broken when nothing is broken.

### Step 3 - Read the banner and the provenance

The result pane should carry:

```
SIMULATED INPUT - REAL UC1 PIPELINE, NOT A CLINICAL RESULT
real UC1 pipeline, synthetic tissue phantom
```

*Why:* the provenance travels with the data, in OpenIGTLink metadata, not in the
module's settings. Confirming the exact wording here is what makes step 4
meaningful - and the header must be version 2, or metadata is silently dropped
and the banner would be showing a default rather than what arrived.

### Step 4 - Swap the map producer. Press `s`.

**Change nothing in Slicer.** No Disconnect, no restart, no change of result
map. The launcher stops the producer on 18945, holds the port empty for six
seconds so you can watch the link row notice, then starts the other one.

What should happen: the banner changes and nothing else does.

```
SIMULATED - NOT A GENUINE UC1 RESULT
arithmetic stand-in, not a classifier
```

Press `s` again to swap back.

*Why:* this is the whole point of the session. A module that displayed
provenance from its own configuration would keep saying "real UC1 pipeline"
after the genuine producer died and an arithmetic stand-in took its port - which
is the exact failure that would let a demo mislabel itself. The six empty
seconds test the other half: that the connector re-establishes itself when a new
producer takes the port, without being told to.

### Step 5 - Measure the live frame rate. Press `m`.

It will ask you to press **Disconnect** on the Acquisition link row first, then
Enter. It runs a bare client, prints the delivered rate, and asks you to press
**Connect** again.

*Why:* pyigtl serves one client at a time, so a measurement taken while SLIAFlow
holds the link would measure nothing. The producer prints its own *enqueue* rate
too, but that counts frames queued for sending and is an upper bound; the
receiver-side number is the one to trust. Expect the two to be close - about
9.2 fps enqueued against 9.1 fps delivered at `demo`.

### Step 6 - Shut down in both directions

Close Slicer while the producers run. Then press `q` to stop the producers.

*Why:* both directions have to be clean, and neither is obvious. Closing Slicer
first produces a pyigtl traceback and `Error while sending data` from a producer
- that is the expected path, because the transport only notices a gone client on
a failing send, not on EOF. `q` and Ctrl-C both tear down and then report
whether either port was left held:

```
[check]    Nothing is listening on 18944 or 18945. No socket was left held.
```

A held socket is what makes the *next* session refuse to start, so it is checked
at the end of this one rather than discovered at the start of that one.

## The keys, while the session runs

| Key | What it does |
| --- | --- |
| `s` | Swap the map producer on 18945 (step 4). Refused with `-Case`. |
| `c` | With `-Case`: trigger a capture. |
| `m` | Measure the delivered LiveView frame rate (step 5). |
| `l` | Start Slicer again after closing it. |
| `n` | Show what is listening on 18944 and 18945. With `-Case`, also 18947, 18950 and the reserved 18948 and 18949. |
| `d` | Print the dataset folder and both log paths. |
| `q` | Stop both producers and end the session. |

The launcher never stops Slicer - close that yourself.

## A recorded case

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

The same session over a recorded case of the public, anonymized HSI Human Brain
Database instead of the phantom. The cube is real brain-surface imagery; only the
acquisition is simulated, and every label says exactly that. Nothing under
`input\` is written.

What changes:

- LiveView is the laptop camera, and nothing else: a recorded session shows
  recorded data and a real camera, never a generated scene. Only one process can
  hold the camera, so leave SLIAFlow's own camera path off.
- The stand-in opens three ports - LiveView on 18944, `HSCube` on 18947 and the
  capture control channel on 18950 - and nothing on 18948 or 18949.
- **The map producer does not start until you press `c`.** That is the order the
  demonstration shows: camera, capture, cube, UC1.
- `s` is refused. The arithmetic stand-in accepts only datasets the simulator
  wrote.

A capture reads roughly like this, the delay drawn between 5 and 8 seconds:

```
[session]  Capture trigger 1: sending CAPTURE to 127.0.0.1:18950.
[capture-1] Sent CAPTURE to 127.0.0.1:18950.
[capture-1] CaptureReply: CAPTURING capture=1 case=004-02 delay=6.4
[acq]        Trigger 'CAPTURE': CAPTURING capture=1 case=004-02 delay=6.4
[acq]        Capture 1 complete: READY capture=1 case=004-02 folder=C:\stratum\input\bin\bin\004-02
[session]  The first capture is ready. Starting the genuine UC1 pipeline on C:\stratum\input\bin\bin\004-02.
[uc1-genuine] Origin:     simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)
```

Press `c` again during the delay and the second trigger client reports
`IGNORED capture 1 already in progress`: one capture at a time, and nothing is
queued.

SLIAFlow has no consumer for `HSCube` yet - the band browser is `SLIA-022` - so
the stand-in says the cube is waiting for a client on 18947. That is expected.

## How long things actually take

Measured on the session of 2026-09-04 19:07, `demo` preset, genuine pipeline:

| From launch | What finished |
| --- | --- |
| +0.5 s | The whole ENVI dataset written - `raw.dat`, both references, the model, the phantom record. |
| +1.3 s | The acquisition stand-in listening on 18944. |
| +2.1 s | The UC1 binary run and the class map recovered. 783 ms from process start; `Time simulation ---> 315.835 ms` of that is the CUDA pipeline itself. |
| +3 s | Both ports serving. The rig is ready. |

So **UC1 is not slow, and it does not run continuously.** It classifies the cube
**once**, before it opens its port, and then re-sends that same map every second
for as long as a client is connected. In that session it sent 507 identical
copies. The map you see is final the moment it appears - waiting for it to
sharpen, update or converge will not do anything, because there is nothing left
to compute.

Two consequences worth knowing:

- **The cycle counter is a heartbeat, not progress.** `REAL UC1 OUTPUT cycle
  507` means the link has been up for about 507 seconds, nothing more. Cycles
  only advance while a client is connected, so the number is a good measure of
  how long SLIAFlow has held the link.
- **If a session felt slow, the time went somewhere else.** Slicer's own startup
  and the four clicks in step 2 are usually all of it. The console timestamps
  and the file times under `workspace\simulators\sessions\` will say exactly
  where.

What *is* genuinely slower: `-Preset full` writes a 640x480 dataset and
classifies 16 times as many pixels, and the very first UC1 run after a rebuild
pays a one-off CUDA context cost.

## Reading the map

At `demo` with the genuine pipeline you should get two colours: a red area over
the craniotomy field and black over the drape. Class 2 is red, class 4 is black;
classes 1 and 3 do not appear on this phantom.

**A red area is not a detection.** UC1 calls the cortex and the tumour-like
region the same class, so what you are looking at is the field, not a tumour.
The measured region-by-region table is in `synthetic_tissue_phantom.md`, and it
is a measurement, not a target - the phantom is never tuned to change it.

## When something goes wrong

| What you see | What it is |
| --- | --- |
| `ERROR: Port 18944 is already in use` | A producer from an earlier session survived. `-StopStrays` clears it. The refusal is deliberate: a stray producer looks exactly like a healthy one in the Slicer panel. |
| Slicer opens and closes on its own | Almost always `run-slicer-tests.ps1 -Headful`, which opens a full Slicer for the length of the suite and closes it. This launcher starts Slicer only at startup and on `l`, and never closes it, so anything else is a real event worth recording. |
| A pyigtl traceback and `Error while receiving data: The client closed the connection.` (or `Error while sending data`) after you close Slicer | The expected shutdown path (step 6): the producer lets the closed connection go at once, even on a port that is sending nothing, so a Slicer reopened in its place is served straight away and receives the next cube. |
| `Slicer did not start: ...` | Reported in red; the producers stay up. Fix it and press `l`. |
| The map appears once and never changes | Correct. UC1 classifies once - see *How long things actually take*. |
| Both panes stay empty but the panel says connected | Another Slicer from an earlier session is still attached. A producer serves **one client at a time**; a second one completes its handshake, reports itself connected, and receives nothing until the first lets go. The producer says so under its own tag, within a few seconds: `WARNING: 127.0.0.1:<port> has 2 clients attached ...`. Close the other Slicer; the producer then prints `the warning above no longer applies`. The launcher also refuses to start when it sees this, and names the process. |
| `A client from an earlier session is still retrying these ports` | The check above, firing before anything starts. Close the Slicer it names, or re-run with `-StopStrays` to have it killed for you. |
| The map never appears, live view is fine | Check the **Result map** name is `majorityVotingMap` and that the UC1 link row is connected. The `[status]` line says whether 18945 has a client. |
| Nothing happens for minutes after launch | Check the last `[session]` line for which stage is waiting. If both ports are serving, the rig is ready and the wait is Slicer's. |
| `There is no recorded case folder ...` | `-Case` names a folder that is not under `input\bin\bin`, or under `-DatasetRoot` when one is given. |
| `... does not identify as a case of the HSI Human Brain Database` | The folder has no `gtMap.hdr` carrying the database marker. Only approved database cases are read. |
| `capture-N finished with exit code 1` | The trigger client got no answer. Read the `[acq]` lines: the stand-in has to be running with `-Case` and listening on 18950. |
| With `-Case`, the UC1 link never connects | Correct until the first capture: the map producer starts when a capture reports `READY`. Press `c`. |

Everything from a session lands in one folder -
`workspace\simulators\sessions\session-<timestamp>\` - with the dataset and both
producer logs. Press `d` to print the path.
