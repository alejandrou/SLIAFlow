# STRATUM stand-in simulators

**Nothing these processes produce is a clinical result, and no output carries
diagnostic meaning.** In the `tissue` and `channel` scenes everything is
synthetic: it is not patient data and it is not derived from patient data. A
genuine algorithm run over an invented brain is still not a genuine clinical
result.

The one exception is scene mode `recorded`, which reads a case of the public,
anonymized *HSI Human Brain Database* published by ULPGC. Its cube is recorded
brain-surface imagery. It is read where it lies and never written, and wherever it
is described it is described as a recorded case - never as synthetic. See
[Running a recorded case](#running-a-recorded-case) and
`.ai/policies/medical-data-policy.md`.

In every mode the acquisition event is simulated, so data leaving these
processes is always marked `simulated` on the wire.

## Why they live here

SLIAFlow is the visualization end of a three-part system: an acquisition
application produces a hyperspectral cube and a LiveView stream, the UC1 CUDA
pipeline turns the cube into brain-tumour maps, and SLIAFlow displays them. Only
the first box is unavailable.

These stand-ins deliberately live **outside** `extensions/`, as separate
processes standing where the real components stand. The seam between a stand-in
and a real component is the network boundary the architecture already has, so
the eventual migration is stopping a simulator and starting the real
application on the same port. Nothing inside `extensions/` changes.

## Setup

The simulators reuse the repository-root `.venv` (Python 3.10.11). There is
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

## Running the acquisition stand-in

```powershell
.\scripts\development\run-acquisition-simulator.ps1
.\scripts\development\run-acquisition-simulator.ps1 -Preset medium -Frames 120
.\scripts\development\run-acquisition-simulator.ps1 -DatasetOnly
```

The simulator writes one dataset and then serves LiveView until Ctrl-C, which
shuts the server socket down cleanly and leaves the dataset intact.

Datasets are written to `workspace/simulators/datasets/sim-YYYYMMDD-HHMMSS/`,
each containing `raw.hdr`, `raw.dat`, `whiteReference.dat`,
`darkReference.dat`, and an `svm_model/` sized for the cube's band count.
`workspace/` is already ignored by Git.

| Preset | Samples x lines |
| --- | --- |
| `demo` (default) | 160 x 120 |
| `medium` | 320 x 240 |
| `full` | 640 x 480 |

Every preset keeps `samples` a multiple of 4, so a BMP row written from a frame
needs no padding.

### The two scenes

`sceneMode` chooses how the cube is built, and the two modes run in opposite
directions.

| Mode | Cube from | LiveView frame from | Moves? | Camera? |
| --- | --- | --- | --- | --- |
| `tissue` (default) | a haemoglobin and scattering model | the cube | no | no |
| `channel` | the frame | the frame source | yes | yes |

`tissue` is the default because it is the only one the genuine UC1 pipeline
resolves to anything. The `channel` scene is spectrally rich, but UC1 min-max
normalizes each pixel across its bands before its SVM, so only spectral *shape*
reaches a classifier trained on real brain reflectance - and every pixel of the
channel scene came back class 4, background.

The phantom is a synthetic optical phantom, not patient data and not a tumour.
When UC1 paints a red area over its tumour-like region **that is not a
detection**: it is a trained model responding to a spectrum built to have the
shape of tissue. `docs/development/synthetic_tissue_phantom.md` records the
model, the region parameters, exactly where UC1 disagrees with how the phantom
was built, and what may and may not be claimed from it. Read it before showing
the result to anyone.

Asking for `tissue` with `--frame-source webcam` is refused rather than
ignored: in tissue mode the frame is rendered from the cube, so there is
nowhere for a camera frame to enter. Use `--scene-mode channel` for a camera or
for motion.

Each phantom dataset also carries `phantom_regions.npy` and
`phantom_regions.json`, a record of how the scene was built. No consumer reads
them and no test grades UC1 against them - they are a construction record, not
ground truth.

### Watching the stream

With the simulator running, in a second shell:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py
```

It prints the device name, image shape, scalar type, header version, the
provenance metadata, and the achieved frame rate.

Only one client at a time. `pyigtl.OpenIGTLinkServer` is a plain
`socketserver.TCPServer`, so the simulator serves a single connection and any
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

The rate this client reports is the one to trust. The simulator's own figure
counts frames handed to `send_message(wait=False)`, which returns as soon as the
message is queued on the writer thread, so it is an upper bound on delivered
throughput rather than a measurement of it.

### The webcam conflict

`frameSource` defaults to `synthetic`, which needs no hardware, except in scene
mode `recorded`, which takes only `webcam`. The `webcam` source opens camera
index 0 - and so does `SLIAFlowLogic.startCamera`. On
Windows the second open fails, so the SLIAFlow live pane and this source cannot
run at the same time. Close one before starting the other.

## Running a recorded case

Scene mode `recorded` imitates what the acquisition rig *does* without inventing
what it *sees*. It streams LiveView, waits for a capture trigger, holds a capture
delay, and then publishes the cube of one recorded case of the HSI Human Brain
Database. The whole loop runs from one console:

```powershell
.\scripts\development\run-end-to-end-session.ps1 -Case 004-02
```

The stand-in and a trigger on their own:

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"
.\.venv\Scripts\python.exe -m stratum_sim acquisition --scene-mode recorded --case 004-02

# In a second shell:
.\.venv\Scripts\python.exe -m stratum_sim capture
```

The cases live in `input/bin/bin/`, which is gitignored; `--recorded-root` points
elsewhere. **Nothing is written.** The case folder is opened for reading only and
`input/` is byte-identical after a session, so `--dataset-only` and
`--dataset-folder`, which write a dataset, are refused in this mode.

### Which folders are read

A folder is read as a recorded case only when its `gtMap.hdr` carries the
`HSI Human Brain Database` marker. The marker is not in `raw.hdr`, and anywhere
other than `gtMap.hdr` it identifies nothing. `gtMap` itself is never opened. A
folder that is neither a simulator dataset nor a database case is refused as
before, by the stand-in and by the UC1 runner alike.

Recorded headers are laid out differently from the ones the simulator writes: the
wavelength block is closed by `}` on its last value line, and `lines` and
`samples` come after it. The reader accepts both, and a header it cannot parse
raises `DatasetReadError`.

### Ports

| Port | Device names | Direction |
| ---: | --- | --- |
| 18944 | `LiveView` | from the stand-in, as in the other scenes |
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

### LiveView in recorded mode

LiveView is the laptop camera, which is what the demonstration shows, and it is
the only source the mode accepts: a recorded session shows recorded data and a
real camera, and nothing made up. `--frame-source` defaults to `webcam` in this
mode, and any other value is refused. On a machine without a camera the stand-in
stops with the camera error rather than falling back to a generated scene. The
webcam conflict above applies. LiveView's `SimulationDetail` names its source -
`acquisition stand-in, laptop camera` - and never the case, because the camera is
not looking at it.

## Running the UC1 arithmetic stand-in

The UC1 stand-in reads a dataset written by the acquisition simulator and sends
all five contract maps on `127.0.0.1:18945`. It is a fixed arithmetic rule with
hand-chosen constants, not a classifier; its output is synthetic and
non-clinical.

It sends no `UC1_RGB`, but all five maps carry one `SLIAFlow.CaptureId`, a
random value made once per run. The connector never removes a metadata key a
later message omits, so maps without one would keep an earlier run's ID and
could be put over that run's `UC1_RGB`.

Create a dataset without leaving the acquisition server running:

```powershell
.\scripts\development\run-acquisition-simulator.ps1 -DatasetOnly
```

Then start the UC1 sender, replacing the path with the folder printed by the
acquisition command:

```powershell
.\scripts\development\run-uc1-simulator.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS `
    -Cycles 0 -SendNotice
```

In a second shell, inspect one message for each device name:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py
```

The client prints the `(1, lines, samples[, components])` shape, scalar type,
header version and every metadata key. The five devices are `UC1_TMD`,
`UC1_MV_CLASS`, `UC1_MV_PROB`, `UC1_SVM_PROB` and `UC1_KNN_PROB`. Every map
message must report header version 2 and all five provenance keys, one
`SLIAFlow.CaptureId` value shared by every message of the run. An empty
metadata dictionary means the sender used pyigtl header version 1 and the
provenance was lost.

Stop the sender with Ctrl-C. The default `raw.hdr` marker is required. If an
explicitly approved synthetic test folder has no `STRATUM SIMULATED CUBE`
marker, the only escape is:

```powershell
.\scripts\development\run-uc1-simulator.ps1 `
    -DatasetFolder path\to\approved-synthetic-folder -ForceUnmarked
```

The sender prints a simulated/non-classifier banner for every complete map
cycle. It never turns an unmarked folder into a genuine result, and
`--force-unmarked` must not be used with patient or clinical data.

## Running the genuine UC1 pipeline

The third command runs the real thing. `uc1-real` executes the vendored UC1 CUDA
binary, compiled unmodified for this GPU, on a simulated dataset and sends the
class map it recovers from the binary's own output files.

Build it once:

```powershell
.\scripts\development\build-uc1.ps1
```

Then run it against a dataset. The wrapper script is the short way:

```powershell
# Report the recovered map without opening a server.
.\scripts\development\run-uc1-real.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS -ClassifyOnly

# Serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\scripts\development\run-uc1-real.ps1 `
    -DatasetFolder workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS
```

The same thing through the module, when a switch the script does not expose is
needed:

```powershell
$env:PYTHONPATH = "$PWD\tools\simulators"

# Report the recovered map without opening a server.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real `
    workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS --classify-only

# Serve UC1_MV_CLASS on 127.0.0.1:18945 until Ctrl-C.
.\.venv\Scripts\python.exe -m stratum_sim uc1-real `
    workspace\simulators\datasets\sim-YYYYMMDD-HHMMSS
```

Inspect the session from a second shell, recording every device name that
arrives rather than waiting for five:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\uc1_client.py --session-seconds 6
```

**It sends one map, not five.** UC1 computes the other four contract maps and
then discards them, so a real-UC1 session sends `UC1_MV_CLASS` alone and leaves
the rest absent rather than substituting zeros. Never run `uc1` and `uc1-real`
together: five maps from two different boxes in one session would imply UC1
produced all five.

**It also sends `UC1_RGB`, the map's background (`SLIA-024`).** Before the GPU
run the runner resolves 710, 540 and 480 nm against the dataset header's own
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
it has bands, or has no band within 2.5 nm of a target. The refusal is printed to stderr as a `WARNING`. A
band index is never assumed in place of a wavelength.

The pipeline is real and the acquisition is simulated, so the output is still
marked `simulated` on the wire. `SLIAFlow.SimulationDetail` names what the cube
was: `real UC1 pipeline, recorded HSI case <case> (simulated acquisition)` for a
recorded database case, `real UC1 pipeline, synthetic tissue phantom` when the
dataset folder carries a phantom record, and `real UC1 pipeline, synthetic input`
otherwise. The runner reads that from the folder rather than from a switch, so it
cannot be told to claim an input the data does not support. A recorded case is
approved input and runs with no switch; any other folder without the
`STRATUM SIMULATED CUBE` marker is refused as before, with the same
`--force-unmarked` escape.

Failure is always loud. A non-zero exit, a missing output, an output left over
from an earlier run, or an RGB triple outside the UC1 palette each stop the run;
there is no fallback to the arithmetic stand-in on any path.

`docs/development/uc1_local_build.md` has the build command line, the staging
layout, the expected warnings, the measured runtime and VRAM, and what the scene
has to look like for UC1 to produce anything but background.
`docs/development/uc1_demo_runbook.md` is the order to run all of this in when
someone is watching, and the output each step should print.
`docs/development/end_to_end_verification.md` is the verification procedure for
running both producers and SLIAFlow together, including the producer swap on
port 18945 that shows SLIAFlow following the data rather than the endpoint.
`.\scripts\developmentun-end-to-end-session.ps1` runs that whole session from
one console: it checks both ports are free, starts both producers in order, tails
their output side by side, reports how many clients each port has, starts Slicer,
and swaps the map producer on a keypress. Use it rather than opening a shell per
producer; the procedure document keeps the by-hand commands as well.
`docs/development/pipeline_test_quickstart.md` is the short version: the command,
what a good startup looks like, the session keys, and what to do when it fails.

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
listening, so both listened and SLIAFlow reached whichever one accepted. A
producer swap could look as though it had worked while the data still came from
the old producer.

The bind itself refuses: the transport's server does not set `SO_REUSEADDR`. Each
command also checks its ports before its first slow step - `uc1-real` before the
pipeline runs, `acquisition` before the camera opens - so the refusal comes at
once rather than after a GPU run. That early check is only a convenience: a
producer that takes the port between the check and the bind is still refused, at
the bind.

A reserved port is refused by name whatever the switches: 18948 (`Stereoscopic`)
and 18949 (`UC2_STO2`) stay unbound, so a black panel for either is black because
nothing listens.

`--allow-shared-port`, on `acquisition`, `uc1` and `uc1-real`, lets two producers
share a port on purpose. It has to be given to **both**: Windows refuses it over a
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
default. All of them are optional; command-line switches win over the file,
which wins over the defaults. An unrecognised key is an error rather than a
silent no-op, because a mistyped setting that quietly does nothing is worse
than one that stops.

| Key | Default | Meaning |
| --- | --- | --- |
| `preset` | `"demo"` | Frame size: `demo`, `medium` or `full`. |
| `bands` | `93` | Bands in the generated cube. Minimum 8, see below - but the genuine UC1 runner accepts **only 93**. |
| `frameSource` | `"synthetic"` | `synthetic` or `webcam`. Used by the `channel` scene. Scene mode `recorded` accepts only `webcam`, and its command line defaults to it. |
| `sceneMode` | `"tissue"` | `tissue`, `channel` or `recorded`. See "The two scenes" and "Running a recorded case" above. |
| `webcamIndex` | `0` | Camera index for the `webcam` source. |
| `liveViewPort` | `18944` | Port the LiveView server socket listens on. |
| `liveViewDeviceName` | `"LiveView"` | OpenIGTLink device name for the stream. |
| `targetFrameRate` | `10.0` | Frames per second the sender aims for. |
| `rotate180` | `true` | Match the real application, which rotates 180 degrees. |
| `seed` | `20260902` | Seed for the scene and the reference cubes. |
| `noiseCounts` | `0` | Per-frame sensor noise. 0 keeps the calibration round trip exact. |
| `textureFeatureCount` | `6` | Independent narrow features added to the spectral basis. Minimum 5, see below. Only used by the `channel` scene. |
| `frameCount` | `0` | Stop after this many frames. 0 streams until Ctrl-C. |
| `datasetRoot` | `null` | Dataset folder. `null` means `workspace/simulators/datasets`. |
| `case` | `null` | Recorded case folder name. Required by, and only accepted in, the `recorded` scene. |
| `recordedRoot` | `null` | Where recorded cases live. `null` means `input/bin/bin`. Read, never written. |
| `hsCubePort` | `18947` | Port the `HSCube` server socket listens on, in the `recorded` scene. |
| `controlPort` | `18950` | Port the capture control channel listens on, in the `recorded` scene. |
| `captureDelayMinSec` | `5.0` | Shortest capture delay, in the `recorded` scene. |
| `captureDelayMaxSec` | `8.0` | Longest capture delay, in the `recorded` scene; each capture draws a delay between the two. |

### 93 bands, for the genuine runner

The floor below is 8, but the genuine UC1 runner refuses anything except 93.

The staged `svm_model/` is the one shipped with the vendored pipeline and it is
sized for 93 bands. `main.cu` reads the band count out of the dataset header and
then reads that many float32 weights per binary classifier from `w_vector.bin`
without checking how many it got: a wider dataset reads past the end of the file
into whatever was already in the buffer, and a narrower one classifies against a
truncated model. Either way the run exits 0 and produces a map that looks
exactly like a result.

The `svm_model/` the acquisition stand-in writes *inside* each dataset folder
does not rescue this. UC1 opens the model as the literal relative path
`../../svm_model/*.bin`, resolved against its working directory and not against
the dataset argument, so a dataset's own model is never the one it reads.

So the runner checks the header's band count and the five model file sizes
before it starts the process, and refuses rather than running. A non-93-band
dataset is still valid input for the arithmetic stand-in, which sizes its
arithmetic to whatever it is given.

`bands` and `textureFeatureCount` carry floors because they can otherwise be set
to values that produce a dataset which writes, loads, and is spectrally
degenerate - the one failure this card exists to prevent. A rank can never
exceed the band count, so fewer than 8 bands cannot reach the required rank of
8 however the scene is generated; and the channel basis reaches rank 3 alone, so
fewer than 5 texture features cannot make up the remainder. Both are rejected
when the configuration is loaded, and the rank measured on the written dataset
is checked again afterwards: a run that falls below the floor exits non-zero
rather than printing the rank and reporting success.

## What the dataset has to satisfy

The generated dataset has three consumers - the genuine UC1 binary, the real
acquisition application's simulated-capture mode, and the stand-in classifier -
and their parsers disagree about almost everything. The constraints that
actually bind, each read out of the vendored source rather than inferred:

Note what that does and does not establish. The tests re-implement UC1's and
`HSCubeLoader`'s parsing rules and check the emitted header against them;
neither real application has been run against a generated dataset. Feeding one
to the genuine CUDA binary is SLIA-013, and that is where compatibility stops
being an argument from source and becomes a measurement.

- BSQ index is `band * totalPixels + line * samples + sample`, so a NumPy
  `(bands, lines, samples)` C-order array's `.tobytes()` is already BSQ.
- The white and dark references are **full cubes**, so one dataset is three
  times the cube size.
- UC1's header parser reads exactly three keys with `sscanf` and stops after
  three hits, so `samples`, `lines` and `bands` must sit at column 0 before the
  long wavelength block.
- `MAX_PATH_LENGTH` is 128, and the same buffer reads header lines, so both the
  dataset path plus `/whiteReference.dat` and every header line must stay under
  128 bytes.
- `HSCubeLoader` requires `data type = 12`, `interleave = bsq` and
  `data file = raw.dat`, and strips everything after a `;`. One header serves
  both consumers as long as it never contains a `;`.

The writer refuses to run rather than produce a dataset that violates any of
these. It also refuses to overwrite a folder whose `raw.hdr` does not carry the
`STRATUM SIMULATED CUBE` marker, and a folder that has no `raw.hdr` at all but
is not empty - there is no marker to clear such a folder, and its `raw.dat`
would be replaced regardless. An empty folder is a fresh target.

### The SVM model is not where UC1 looks for it

Each dataset carries an `svm_model/` sized for its own band count. UC1 does not
read it from there: `main.cu` opens the five model files as the literal relative
paths `../../svm_model/*.bin`, resolved against the binary's working directory
and not against the dataset argument at all. Keeping the model beside the
dataset it was sized for is the honest arrangement, and placing it where UC1's
relative path lands is SLIA-013's job, where the binary is actually invoked.

The `w_vector.bin` size check still binds: it is what catches a band count the
model cannot serve, whichever directory the file is eventually read from.

## The calibration relationship

UC1 computes `100 * (raw - dark) / (white - dark)` on the GPU. The simulator
generates the references first and inverts that formula to obtain `raw`, rather
than generating `raw` and hoping, and keeps `white > dark` strictly everywhere
so UC1's `white != 0` guard never fires. `noiseCounts` defaults to 0, which
makes the round trip exact to within uint16 rounding.

Spectral non-degeneracy is achieved through the basis, never through noise. The
three channel Gaussians are driven by the frame's B, G and R planes; the
near-infrared envelope is driven by luminance, which is a fixed linear
combination of those three and so adds a curve but no new direction. The
texture features each carry an independently generated spatial weight, and each
one does add a direction. The measured band-covariance rank is therefore 3 for
the channel basis alone and 9 with the default six texture features.

## Provenance on the wire

Four string keys travel with the data:

| Key | Meaning |
| --- | --- |
| `SLIAFlow.ResultMap` | which UC1 map this is; absent on LiveView, which is not a result |
| `SLIAFlow.DeviceName` | the exact producer device name |
| `SLIAFlow.DataOrigin` | `simulated` or `external-genuine` |
| `SLIAFlow.SimulationDetail` | free text describing how a simulated result was produced |

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
nothing under `stratum_sim` imports `slicer`.

Lint both the Slicer module and the simulators with:

```powershell
.\scripts\development\run-python-quality.ps1
```
