# STRATUM stand-in simulators

**Everything these processes produce is synthetic and non-clinical.** It is not
patient data, it is not derived from patient data, and no output of these
simulators carries diagnostic meaning. The scene is invented. A genuine
algorithm run over an invented brain is still not a genuine clinical result, so
data leaving these processes is always marked `simulated` on the wire.

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

### Watching the stream

With the simulator running, in a second shell:

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py
```

It prints the device name, image shape, scalar type, header version, the
provenance metadata, and the achieved frame rate.

The rate this client reports is the one to trust. The simulator's own figure
counts frames handed to `send_message(wait=False)`, which returns as soon as the
message is queued on the writer thread, so it is an upper bound on delivered
throughput rather than a measurement of it.

### The webcam conflict

`frameSource` defaults to `synthetic`, which needs no hardware. The `webcam`
source opens camera index 0 - and so does `SLIAFlowLogic.startCamera`. On
Windows the second open fails, so the SLIAFlow live pane and this source cannot
run at the same time. Close one before starting the other.

## Running the UC1 arithmetic stand-in

The UC1 stand-in reads a dataset written by the acquisition simulator and sends
all five contract maps on `127.0.0.1:18945`. It is a fixed arithmetic rule with
hand-chosen constants, not a classifier; its output is synthetic and
non-clinical.

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
message must report header version 2 and all four provenance keys. An empty
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
| `bands` | `93` | Bands in the generated cube. Minimum 8, see below. |
| `frameSource` | `"synthetic"` | `synthetic` or `webcam`. |
| `webcamIndex` | `0` | Camera index for the `webcam` source. |
| `liveViewPort` | `18944` | Port the LiveView server socket listens on. |
| `liveViewDeviceName` | `"LiveView"` | OpenIGTLink device name for the stream. |
| `targetFrameRate` | `10.0` | Frames per second the sender aims for. |
| `rotate180` | `true` | Match the real application, which rotates 180 degrees. |
| `seed` | `20260902` | Seed for the scene and the reference cubes. |
| `noiseCounts` | `0` | Per-frame sensor noise. 0 keeps the calibration round trip exact. |
| `textureFeatureCount` | `6` | Independent narrow features added to the spectral basis. Minimum 5, see below. |
| `frameCount` | `0` | Stop after this many frames. 0 streams until Ctrl-C. |
| `datasetRoot` | `null` | Dataset folder. `null` means `workspace/simulators/datasets`. |

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
