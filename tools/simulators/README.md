# STRATUM acquisition stand-in and genuine UC1 runner

**Nothing these processes produce is a clinical result, and no output carries
diagnostic meaning.**

Every cube is a recorded case of the public, anonymized *HSI Human Brain
Database* published by ULPGC: recorded brain-surface imagery, read where it lies
and never written, and described wherever it appears as a recorded case. See
`.ai/policies/medical-data-policy.md`. Nothing here generates a scene, a cube or
a map; the generated tissue phantom and the arithmetic UC1 stand-in were retired
in `SLIA-025`.

The acquisition event is simulated - there is no hyperspectral camera on this
machine - so data leaving these processes is always marked `simulated` on the
wire.

## Why they live here

SLIAFlow is the visualization end of a three-part system: an acquisition
application produces a hyperspectral cube and a LiveView stream, the UC1 CUDA
pipeline turns the cube into brain-tumour maps, and SLIAFlow displays them. Only
the first box is unavailable.

These processes deliberately live **outside** `extensions/`, standing where the
real components stand. The seam between the stand-in and the real acquisition
application is the network boundary the architecture already has, so the
eventual migration is stopping the stand-in and starting the real application on
the same port. Nothing inside `extensions/` changes.

## Setup

The processes reuse the repository-root `.venv` (Python 3.10.11). There is
deliberately no second virtual environment.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\simulators\requirements.txt
```

`crcmod` 1.7 publishes no Windows wheel, so pip fetches the sdist and compiles
it. A working C toolchain is therefore an environment prerequisite. It is free
on any machine carrying the Visual Studio C++ workload the SLIAFlow build
already requires, and a real failure mode on a bare CI runner.

`crcmod` is not optional: `pyigtl` imports it unconditionally at module scope to
build its CRC64 function, so it loads before any message can be constructed.

## Running a recorded case

The acquisition stand-in imitates what the acquisition rig *does* without
inventing what it *sees*. It streams LiveView from the laptop camera, waits for a
capture trigger, holds a capture delay, and then publishes the cube of one
recorded case. The whole loop, with the genuine UC1 pipeline and Slicer, runs from
one console:

```powershell
.\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

A session without `-Case` is refused.

The stand-in and a trigger on their own:

```powershell
.\scripts\development\run-acquisition-simulator.ps1 -Case 004-02

# Or through the module:
$env:PYTHONPATH = "$PWD\tools\simulators"
.\.venv\Scripts\python.exe -m stratum_sim acquisition --case 004-02

# In a second shell:
.\.venv\Scripts\python.exe -m stratum_sim capture
```

The cases live in `input/bin/bin/`, which is gitignored; `--recorded-root` points
elsewhere. **Nothing is written.** The case folder is opened for reading only and
`input/` is byte-identical after a session.

| Preset | LiveView samples x lines |
| --- | --- |
| `demo` (default) | 160 x 120 |
| `medium` | 320 x 240 |
| `full` | 640 x 480 |

The preset sizes the LiveView frame only; the cube is published at the case's
own size.

### Which folders are read

A folder is read as a recorded case only when its `gtMap.hdr` carries the
`HSI Human Brain Database` marker. The marker is not in `raw.hdr`, and anywhere
other than `gtMap.hdr` it identifies nothing. `gtMap` itself is never opened. Any
other folder is refused, by the stand-in and by the UC1 runner alike, and there
is no switch to override that.

Recorded headers close the wavelength block with `}` on its last value line and
put `lines` and `samples` after it. The reader accepts that layout and a `}` on a
line of its own, and a header it cannot parse raises `DatasetReadError`.

### Ports

| Port | Device names | Direction |
| ---: | --- | --- |
| 18944 | `LiveView` | from the stand-in |
| 18947 | `HSCube` | from the stand-in, once per completed capture |
| 18950 | `CaptureTrigger` | to the stand-in |
| 18950 | `CaptureReply`, `CaptureStatus` | from the stand-in |

18948 (stereoscopic) and 18949 (StO2) are reserved and never bound. A producer asked
to serve one refuses by name; see
[A port that is already served](#a-port-that-is-already-served).

### The control channel

Send `CAPTURE` as a `STRING` under the device name `CaptureTrigger`. Every
message back starts with one upper-case word, and `folder=` is always last, so a
path containing spaces is simply the rest of the line.

| Device | Text | When |
| --- | --- | --- |
| `CaptureReply` | `CAPTURING capture=<n> case=<case> delay=<seconds>` | once, when a trigger starts capture `n` |
| `CaptureReply` | `IGNORED capture <n> already in progress` | once, for a trigger during a capture, which is dropped rather than queued |
| `CaptureReply` | `REFUSED unknown command <text>` | once, for anything but `CAPTURE` |
| `CaptureStatus` | `IDLE` | before the first capture |
| `CaptureStatus` | `CAPTURING capture=<n> case=<case> delay=<seconds>` | during a capture |
| `CaptureStatus` | `READY capture=<n> case=<case> folder=<case folder>` | after capture `n` |

`CaptureStatus` is sent whenever it changes, and repeated every 0.5 s while a
client is connected. The repeat is load-bearing. pyigtl 0.3.4 treats an empty
`recv` as "no message" rather than as a closed connection, so the server only
lets go of a client that has left when a send to it fails, and until then the
next client waits unserved in the accept backlog. Measured: with no repeat, a
second and third one-shot client were never served; with it, each was served
within 0.2 s.

There are three names rather than one for two reasons. A Slicer connector re-sends
an outgoing node when a message of the same name updates it, so a trigger and its
answer sharing a name would echo. And pyigtl keeps only the latest message per
device name, so a reply sharing a name with the repeated state would be
overwritten before a client read it. The capture number is what lets a client
tell the `READY` that answers its trigger from an earlier one the repeat is still
sending.

The delay is drawn for each capture between `captureDelayMinSec` and
`captureDelayMaxSec`, 5 and 8 s by default; `--instant-capture` sets both to 0.
LiveView keeps streaming throughout.

### The HSCube message

One `IMAGE` at header version 2: a single-component `uint16` array of shape
`(bands, lines, samples)` in pyigtl's `(k, j, i)` order, so the band is k. It holds
the raw counts from `raw.dat` - uncalibrated, unrotated - with the identity matrix
and LPS, so its (j, i) grid is the UC1 map's grid. A 752x721 case is about 100 MB
in one message.

| Metadata key | Value |
| --- | --- |
| `SLIAFlow.DeviceName` | `HSCube` |
| `SLIAFlow.DataOrigin` | `simulated` |
| `SLIAFlow.SimulationDetail` | `acquisition stand-in, recorded HSI case <case> (simulated acquisition)` |
| `SLIAFlow.WavelengthsNm` | one value per band, comma-separated |
| `SLIAFlow.DatasetFolder` | the case folder |

It is sent once per capture: to the client connected on 18947 at that moment, or
to the next one that connects. `READY` is reported either way, because in this
arrangement the algorithms read the announced folder from disk.

### The trigger client

`python -m stratum_sim capture` connects, sends one `CAPTURE`, prints what comes
back, and disconnects. It exits 0 once the capture its trigger started is
`READY`, 2 when the trigger was ignored, and 1 on a refusal, on no connection, or
on a timeout. With `--no-wait` it leaves as soon as the capture has started.
That is how the launcher's `c` key runs it: a client waiting for `READY` would
hold the control port for the whole delay, so a second press would be read only
afterwards, and would start a new capture instead of being answered `IGNORED`.

### LiveView

LiveView is the laptop camera, which is what the demonstration shows, and it is
the only source there is. On a machine without a camera the stand-in stops with
the camera error. LiveView's `SimulationDetail` names its source -
`acquisition stand-in, laptop camera` - and never the case, because the camera is
not looking at it.

The stand-in opens camera index 0, and so does `SLIAFlowLogic.startCamera`. On
Windows the second open fails, so the SLIAFlow live pane and the stand-in cannot
run at the same time. Close one before starting the other.

### Watching the stream

With the stand-in running, in a second shell:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py
```

It prints the device name, image shape, scalar type, header version, the
provenance metadata, and the achieved frame rate.

Only one client at a time. `pyigtl.OpenIGTLinkServer` is a plain
`socketserver.TCPServer`, so the stand-in serves a single connection and any
second client waits unserved until the first one goes away. Run this client with
SLIAFlow's acquisition link disconnected, not alongside it.

A client that closes is let go at once, even on a port that is sending nothing,
such as HSCube between captures, so a client reopened in its place is served
straight away and receives the next cube. pyigtl on its own notices a departure
only when a send fails. The release prints a pyigtl traceback ending
`Error while receiving data: The client closed the connection.` to standard
error; that is the normal path, not a fault.

Every producer says so when it happens (SLIA-018). Each port prints
`127.0.0.1:<port>: serving 1 client.` and `serving 0 clients.` as its served
client comes and goes. A second client that stays attached for 2 s draws one
line:

```text
WARNING: 127.0.0.1:18944 has 2 clients attached, and a producer serves one client at a time. ...
```

Close the other client. When the extra client has gone, the port prints
`only one client is attached again; the warning above no longer applies.` The
warning is confirmed against the Windows TCP table before it is printed, because
the listening socket alone goes on reporting a queued connection after the client
behind it has given up; off Windows the attach and release lines still print but
no warning is confirmed.

## Running the genuine UC1 pipeline

`uc1-real` executes the vendored UC1 CUDA binary, compiled unmodified for this
GPU, on a recorded case and sends the class map it recovers from the binary's
own output files.

Build it once:

```powershell
.\scripts\development\build-uc1.ps1
```

Then run it against a case. The wrapper script is the short way:

```powershell
# Report the recovered map without opening a server.
.\scripts\development\run-uc1-real.ps1 -DatasetFolder input\bin\bin\004-02 -ClassifyOnly

# Serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\scripts\development\run-uc1-real.ps1 -DatasetFolder input\bin\bin\004-02
```

The same thing through the module, when a switch the script does not expose is
needed:

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"

# Report the recovered map without opening a server.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02 --classify-only

# Serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02
```

Inspect the session from a second shell, recording every device name that
arrives rather than waiting for five:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 6
```

**It sends one map, not five.** UC1 computes the other four contract maps and
then discards them, so a session sends `UC1_MV_CLASS` alone and leaves the rest
absent rather than substituting zeros.

**It also sends `UC1_RGB`, the map's background (`SLIA-024`).** Before the GPU
run the runner resolves 710, 540 and 480 nm against the case header's own
wavelength list and prints which band each resolved to and by how much it missed.
It reads only those three bands, calibrates them as UC1 does, and scales each by
fixed reflectance, `round(clip(reflectance, 0, 1) * 255)`, with no per-image
stretch. The result is a `(1, lines, samples, 3)` `uint8` image sent as `UC1_RGB`
immediately before `UC1_MV_CLASS` in every cycle, with the same origin and
simulation detail and no `SLIAFlow.ResultMap` role. Both messages carry one
`SLIAFlow.CaptureId`, a random value made once per run, so SLIAFlow never puts a
map over a `UC1_RGB` left over from another run. The map carries it when
`UC1_RGB` is refused, too. It is a viewing aid made of
three bands, not a colour-accurate photograph and not the microscope's view.

`UC1_RGB` is refused, and `UC1_MV_CLASS` is sent alone, when the header lists no
wavelengths, lists one that is not finite, lists a different number of them than
it has bands, or has no band within 2.5 nm of a target. The refusal is printed to
stderr as a `WARNING`. A band index is never assumed in place of a wavelength.

The pipeline is real and the acquisition is simulated, so the output is still
marked `simulated` on the wire. `SLIAFlow.SimulationDetail` names the case:
`real UC1 pipeline, recorded HSI case <case> (simulated acquisition)`. The runner
reads the case name from the folder rather than from a switch, so it cannot be
told to claim an input the data does not support. A folder that is not an
identified recorded case is refused before the GPU runs and before anything
describes it.

Failure is always loud. A non-zero exit, a missing output, an output left over
from an earlier run, or an RGB triple outside the UC1 palette each stop the run;
there is no fallback on any path.

### 93 bands

The staged `svm_model/` is the one shipped with the vendored pipeline and it is
sized for 93 bands, which is what every recorded case read so far has. `main.cu`
reads the band count out of the dataset header and then reads that many float32
weights per binary classifier from `w_vector.bin` without checking how many it
got: a wider dataset reads past the end of the file into whatever was already in
the buffer, and a narrower one classifies against a truncated model. Either way
the run exits 0 and produces a map that looks exactly like a result.

A model inside the case folder does not rescue this. UC1 opens the model as the
literal relative path `../../svm_model/*.bin`, resolved against its working
directory and not against the dataset argument. So the runner checks the header's
band count and the five model file sizes before it starts the process, and
refuses rather than running.

### Further reading

`docs/development/uc1_local_build.md` has the build command line, the staging
layout, the expected warnings, and the measured runtime and VRAM.
`docs/development/uc1_demo_runbook.md` is the order to run all of this in when
someone is watching, and the output each step should print.
`docs/development/end_to_end_verification.md` is the verification procedure for
running the stand-in, the pipeline and SLIAFlow together.
`.\scripts\development\run-end-to-end-session.ps1` runs that whole session from
one console: it checks the ports are free, starts the stand-in, tails every
producer's output side by side, reports how many clients each port has, starts
Slicer, triggers captures on a keypress, and starts the genuine pipeline once the
first capture is ready. `docs/development/pipeline_test_quickstart.md` is the
short version: the command, what a good startup looks like, the session keys, and
what to do when it fails.

## A port that is already served

Every producer refuses to start on a port another socket is already listening on
(SLIA-017), and exits 1 with one line naming the port and the process holding it:

```text
ERROR: 127.0.0.1:18945 is already being served by PID 12345 (python.exe). A second producer on it would not take it over: both would listen, and a client would reach whichever one accepted. Stop the other producer, or pass a different port. Two producers share a port only when both are started with --allow-shared-port. To stop it: Stop-Process -Id 12345
```

The PID is the interpreter that owns the socket, the one `netstat` shows. A
producer started through the `.venv` launcher runs as a child of the PID
`Start-Process` reports, and stopping the launcher does not free the port, so stop
the PID the message names.

Before this, a second producer neither failed nor took over. pyigtl sets
`SO_REUSEADDR`, which on Windows lets a second server bind a port that is already
listening, so both listened and SLIAFlow reached whichever one accepted.

The bind itself refuses: the transport's server does not set `SO_REUSEADDR`. Each
command also checks its ports before its first slow step - `uc1-real` before the
pipeline runs, `acquisition` before the case is read and the camera opens - so
the refusal comes at once rather than after a GPU run. That early check is only a
convenience: a producer that takes the port between the check and the bind is
still refused, at the bind.

A reserved port is refused by name whatever the switches: 18948 (`Stereoscopic`)
and 18949 (`UC2_STO2`) stay unbound, so a black panel for either is black because
nothing listens.

`--allow-shared-port`, on `acquisition` and `uc1-real`, lets two producers share a
port on purpose. It has to be given to **both**: Windows refuses it over a
producer that was started without it, so an ordinary producer cannot be joined by
accident. That refusal also comes before the slow step, saying that the other
producer was not started with the switch. A producer that does share prints a
`WARNING:` naming the process it joined, and the first one warns that a later
join would be silent. Starting again on the same port straight after a run is not
refused; the `TIME_WAIT` connections a run leaves behind hold nothing.

`acquisition` also refuses, before the camera opens, a port configured for two of
its own channels, such as `hsCubePort` and `controlPort` both 18947. The switch
does not change that: it shares a port between producers, never between one
producer's channels.

A producer restarts its server after a failed send. If something else takes the
port during that one-second gap, the producer stops with an `ERROR:` that says the
restart could not bind, followed by the refusal above, rather than joining.

## Configuration

Settings come from the `simulators` block of `config/local.json`, which is
already ignored by Git. `config/local.example.json` lists every key at its
default. Command-line switches win over the file, which wins over the defaults.
An unrecognised key is an error rather than a silent no-op, because a mistyped
setting that quietly does nothing is worse than one that stops - and a setting
from the retired phantom (`sceneMode`, `frameSource`, `bands` and the rest) is
refused by name for the same reason.

| Key | Default | Meaning |
| --- | --- | --- |
| `preset` | `"demo"` | LiveView frame size: `demo`, `medium` or `full`. |
| `webcamIndex` | `0` | Camera index for LiveView. |
| `liveViewPort` | `18944` | Port the LiveView server socket listens on. |
| `liveViewDeviceName` | `"LiveView"` | OpenIGTLink device name for the stream. |
| `targetFrameRate` | `10.0` | Frames per second the sender aims for. |
| `rotate180` | `true` | Match the real application, which rotates 180 degrees. |
| `case` | `null` | Recorded case folder name, for example `"004-02"`. The stand-in needs one, from here or `--case`. |
| `recordedRoot` | `null` | Where recorded cases live. `null` means `input/bin/bin`. Read, never written. |
| `hsCubePort` | `18947` | Port the `HSCube` server socket listens on. |
| `controlPort` | `18950` | Port the capture control channel listens on. |
| `captureDelayMinSec` | `5.0` | Shortest capture delay. |
| `captureDelayMaxSec` | `8.0` | Longest capture delay; each capture draws a delay between the two. |

## Provenance on the wire

Five string keys travel with a result:

| Key | Meaning |
| --- | --- |
| `SLIAFlow.ResultMap` | which UC1 map this is; absent on LiveView, `HSCube` and `UC1_RGB`, which are not results |
| `SLIAFlow.DeviceName` | the exact producer device name |
| `SLIAFlow.DataOrigin` | `simulated` or `external-genuine` |
| `SLIAFlow.SimulationDetail` | free text naming the producer and, for a cube or a result, the recorded case |
| `SLIAFlow.CaptureId` | one opaque value per classification, on `UC1_MV_CLASS` and `UC1_RGB` |

Every message is sent at OpenIGTLink header version 2. At pyigtl's default of
version 1 the metadata is silently dropped: the send succeeds, the message is
well formed, and the provenance is gone. `igtl_transport.py` sets the version
and the metadata in one place so that no producer can forget either.

Provenance travels with the data, never with the endpoint. A consumer must never
infer `simulated` from a port or a hostname.

Full details of the contract are in
`docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`.

## Tests

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py
```

These use the standard-library `unittest` runner, not the Slicer test runner:
nothing under `stratum_sim` imports `slicer`. Folders the tests build are laid
out like recorded cases and hold counting placeholders. The one test that runs
the real binary, `RealBinaryIntegrationTest`, classifies recorded case `004-02`
from `input/bin/bin` on the GPU and checks the case folder is unchanged; it skips
only where the staged UC1 build is absent.

Lint both the Slicer module and the simulators with:

```powershell
.\scripts\development\run-python-quality.ps1
```
