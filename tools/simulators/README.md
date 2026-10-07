# OpenIGTLink transport

`tools/simulators` used to hold the STRATUM acquisition stand-in, the UC1 runner
service and their clients. `SLIA-028` retired them: UC1 runs inside Slicer since
`SLIA-027` (`ADR-0003`), and IUMA's acquisition app is the producer SLIAFlow
receives from (`ADR-0004`). They remain in Git history.

What is left is the OpenIGTLink transport those processes shared and, since
`SLIA-035`, a **stand-in for IUMA's acquisition app** built on it, for testing
SLIAFlow's Connections section without the app. Nothing here is run by the
product.

## What remains

| File | What it is |
| --- | --- |
| `stratum_sim/igtl_transport.py` | Building IMAGE messages with pyigtl at header version 2, so their metadata reaches the wire, and plain STRING messages; refusing a port another process already listens on, and naming that process from the Windows TCP table; watching the clients attached to a server |
| `stratum_sim/contract.py` | What the transport, the stand-in and their tests share: the provenance keys, the app's device names and base port, the stand-in's band keys, and the reserved ports |
| `stratum_sim/iuma_app_standin.py` | The stand-in for IUMA's acquisition app (`SLIA-035`) |
| `stratum_sim/igtl_recorder.py` | A recorder that logs every message an OpenIGTLink server sends, to measure IUMA's app (`SLIA-030`) |
| `tests/test_igtl_recorder.py` | The recorder's tests |
| `tests/test_igtl_transport.py` | The transport's tests |
| `tests/test_iuma_app_standin.py` | The stand-in's tests |
| `tests/support.py`, `tests/run_tests.py` | Test helpers and the runner |
| `requirements.txt` | `numpy`, `pyigtl` and `crcmod`, pinned |
| `ruff.toml` | Lint settings for Python 3.10 |

Nothing here imports `slicer`. It runs under the repository-root `.venv`, not
inside Slicer's interpreter, and its dependencies are never added to the Slicer
module's `Resources/requirements.txt`.

## Setup

The code reuses the repository-root `.venv` (Python 3.10.11). There is
deliberately no second virtual environment.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\simulators\requirements.txt
```

`crcmod` 1.7 publishes no Windows wheel, so pip fetches the sdist and compiles
it. A working C toolchain is therefore an environment prerequisite. It is free
on any machine carrying the Visual Studio C++ workload the SLIAFlow build
already requires.

`crcmod` is not optional: `pyigtl` imports it unconditionally at module scope to
build its CRC64 function, so it loads before any message can be constructed.

## The stand-in for IUMA's acquisition app

It is **not IUMA's app**. It serves the app's three ports with a recorded cube
so that SLIAFlow's Connections section and its HS cube reader can be tested
without the app (`SLIA-035`, `SLIA-036`). Run it from `tools\simulators`:

```powershell
cd tools\simulators
..\..\.venv\Scripts\python.exe -m stratum_sim.iuma_app_standin
```

| Port | Device name | What the stand-in sends |
| --- | --- | --- |
| P = 18944 | `LiveView` | a colour preview of the cube (bands nearest 650, 550 and 470 nm, reflectance 0-1 as 0-255), RGB uint8, `--frame-rate` per second (default 10) |
| P + 1 | `Steroscopic` | that preview beside the 650 nm band in grey, RGB uint8, at the same rate |
| P + 2 | `HsCube` | while a client is connected, the cube band by band, one single-component IMAGE every `--band-interval` s (default 0.1), again every `--cube-interval` s (default 30). Each IMAGE declares the whole cube and carries its band as the sub-volume at offset (0, 0, band - 1), as the app sends it (`SLIA-036`) |

- `--cube <header>` sends another ENVI BSQ cube, float32 or uint16; the default
  is `input\002-04\LCTF_Calibrated_Cube_Single.hdr`, read into memory whole
  (about 0.5 GB) and never written. A uint16 cube, such as
  `input\002-04\raw_data.hdr` (1.93 GB), is sent as uint16, as the app sends
  its raw cube today; its LiveView preview is scaled to its brightest count.
- `--app-header` sends `HsCube` exactly as the app does: header version 1, no
  metadata, timestamp 0. Its data is then not marked simulated on the wire, so
  SLIAFlow cannot tell it from the app; use it to test the reader on the real
  form, never to stand for a capture.
- `--drop-bands 5,17,80-84` leaves those band numbers (from 1) out of every
  cube, to see SLIAFlow name the missing bands.
- `--base-port P` moves all three ports; `--duration S` stops after S seconds.
- Every line it prints, on either stream, starts with `[stand-in]`, and its
  banner says it is not IUMA's app.
- Every message carries `SLIAFlow.DataOrigin = simulated` and a
  `SLIAFlow.SimulationDetail` naming it a stand-in; `HsCube` messages also carry
  `SLIAFlow.BandNumber` and `SLIAFlow.WavelengthNm`. Without `--app-header` they
  use header version 2, which the app does not, so that the mark reaches the
  wire. pyigtl always packs an image as its own whole sub-volume and refuses to
  unpack any other, so the band is packed by `igtl_transport.ImageSlabMessage`;
  its tests read it back with the recorder's parser, and SLIAFlow's tests check
  that OpenIGTLinkIF assembles it into the cube.
- A band counts as sent only once it was written to the connection in full
  (`ImageStreamServer.writtenMessageCount`), and the next band is queued only
  then. An empty send queue proves nothing: pyigtl takes a message off its queue
  before writing it, so a client that leaves mid-write empties the queue with
  nothing written. Whether the client then read the band, TCP does not tell the
  sender. The queue itself is a `deque(maxlen=100)` that drops the oldest message
  silently when full, and what was queued for a client that left is dropped
  instead of going to the next one. A frame due while the previous one is still
  queued (`pendingMessageCount`) is skipped rather than queued.
- When a client leaves, pyigtl prints a traceback of the closed connection; it
  is expected.

Measured on this laptop with `002-04` and SLIAFlow connected to all three
ports: 109 of 109 bands arrived in about 15 s, LiveView and Stereo at 10
frames/s.

### What it assumes about the real app

Each point was checked against the real app in `SLIA-030` (2026-09-27, Send
Capture of `002-04`'s raw cube, no cameras;
`docs/hardware/acquisition_app_and_hardware.md` section 4.1):

1. `HsCube` sends one IMAGE per band, single component, `(samples, lines, 1)`,
   spacing 1, identity matrix, LPS, bands in ascending wavelength, with no
   end-of-cube message. **Partly wrong.** One IMAGE per band, single
   component, spacing 1, identity, LPS, bands in file order and no end message
   are confirmed. But every message declares the whole cube,
   `(samples, lines, bands)`, and carries its band as the sub-volume
   `(samples, lines, 1)` at offset `(0, 0, band - 1)`, with the origin at the
   centre of the whole cube. The stand-in sends this form since `SLIA-036`.
2. The per-band keys `SLIAFlow.BandNumber` and `SLIAFlow.WavelengthNm` are the
   stand-in's invention; the app's binary shows no per-band metadata.
   **Confirmed**: the app sends no metadata at all. The band number is in the
   sub-volume offset; the wavelength is not sent.
3. Messages use header version 2 so that metadata reaches the wire; the app's
   header version is unknown. **Wrong**: the app sends header version 1. The
   stand-in keeps version 2 by default, for its simulated mark, and sends
   version 1 without metadata and with timestamp 0 under `--app-header`
   (`SLIA-036`).
4. The cube goes out automatically while a client is connected; the real app
   sends it on Capture HSI or Send Capture. **Confirmed** for Send Capture: the
   app sends the cube once, and a client that connects after the first band
   misses it.
5. LiveView and Stereo carry a colour preview of the cube at 1080 x 1080 and
   2160 x 1080; the app sends camera frames (up to 4096 x 3000) at a rate not
   yet measured. **Not measurable** without cameras: both ports accepted the
   client and sent nothing.
6. The stand-in listens on 127.0.0.1; the app listens on 0.0.0.0. Known from
   running the app; not changed by the measurement.
7. One client per port at a time, as in the app's server loop. Known from the
   binary; not exercised by the measurement.
8. Today's app sends raw uint16 bands; the stand-in sends IUMA's calibrated
   float32 cube, the announced format. **Confirmed**: uint16, little endian.

The stand-in's pace is close to the app's: the app sent 109 bands in 12.3 s
(8.8 bands/s) over the loopback.

## The protocol recorder

It records what an OpenIGTLink server actually sends, to measure IUMA's app
before SLIAFlow's receiver is built on it (`SLIA-030`). It connects as the
client to each port, sends nothing, and reads every message whole with its own
parser (`pyigtl.OpenIGTLinkClient` keeps only the latest message per device
name and would hide lost or doubled bands).

```powershell
cd tools\simulators
..\..\.venv\Scripts\python.exe -m stratum_sim.igtl_recorder --compare-cube ..\..\input\002-04\raw_data.hdr
```

- `--ports` (default `18944,18945,18946`), `--host` (default `127.0.0.1`),
  `--duration S`, `--out <folder>` (default
  `workspace\igtl-recordings\<yyyyMMdd-HHmmss>`, gitignored).
- A port that refuses is tried again every second, so the recorder can start
  before the app. Each port serves one client: do not connect SLIAFlow to the
  same ports while recording.
- `messages.jsonl` has one line per message: port, arrival time, header
  version, type, device name, header timestamp, body size, whether the CRC
  matches, the version-2 extended header and metadata, and for IMAGE the image
  header (components, scalar type, endianness, coordinate system, size,
  spacing, origin, direction, sub-volume) and the pixel minimum, maximum and
  mean over the finite values, with the count of NaN and infinite ones for
  float types. The text of STRING and STATUS messages is logged, and the first
  64 bytes, in hex, of any other type. Every line is strict JSON: a value that
  is not a finite number is written as `null`. **No pixel data is written.**
- Each port's reader only reads and time-stamps; a separate thread checks the
  CRC, computes the statistics and matches bands. Arrival times, rates and gaps
  are therefore the sender's even while a band is being matched. If more than
  3 GB is waiting to be described, the readers wait, which slows the sender;
  the summary says for how long (`Reader held back by the describer`), and
  gives the longest wait before a message was described.
- `--compare-cube <header>` (ENVI uint16 or float32, BSQ; about 4 s for the
  1.93 GB raw cube) names, for each single-component image, the cube band with
  the same pixels, as stored, flipped or rotated, or says none matches. That
  gives band order and orientation without any band metadata.
- `summary.md`, also printed on Ctrl+C, lists per port the device names, types,
  header versions, metadata keys, image properties, rate and longest gap, and
  the messages other than IMAGE with their text. Compared bands are split into
  captures wherever more than `--capture-gap` seconds (default 5) pass without
  one, so that sending the cube twice reads as two captures, not as repeated
  bands. Per capture it gives the arrival order, the missing, repeated and
  out-of-order bands, and the messages other than IMAGE that followed it, which
  shows whether the app marks the end of a cube.

Checked against the stand-in with `002-04` at full size: 109 of 109 bands
matched in order, as stored, at 6.1 bands/s; LiveView and Stereo at 10
frames/s; no CRC mismatch. Against IUMA's app, sending `002-04`'s raw cube:
109 of 109 bands matched in order, as stored, at 8.8 bands/s, no CRC mismatch,
the compare cube read in 3.9 s. Close the app's own copy of a cube before
reading another large one as compare cube: with both in memory the first
attempt stalled.

## Metadata reaches the wire only at header version 2

At pyigtl 0.3.4's default of header version 1, metadata is silently dropped: the
send succeeds, the message is well formed, and the metadata is gone.
`buildImageMessage` sets the version and the metadata in one place so that no
sender can forget either. `buildStringMessage` sends no metadata and leaves the
version at pyigtl's default.

SLIAFlow receives a wire key such as `SLIAFlow.DataOrigin` as the MRML
attribute `OpenIGTLink.SLIAFlow.DataOrigin`; `vtkMRMLIGTLConnectorNode` adds the
prefix on the receiving side.

## A port that is already served

`assertPortCanBeServed` and `ImageStreamServer` refuse a port another socket is
already listening on (`SLIA-017`), with one line naming the port and the process
holding it:

```text
ERROR: 127.0.0.1:18945 is already being served by PID 12345 (python.exe). A second producer on it would not take it over: both would listen, and a client would reach whichever one accepted. Stop the other producer, or pass a different port. Two producers share a port only when both are started with --allow-shared-port. To stop it: Stop-Process -Id 12345
```

Without this, a second server neither failed nor took over: pyigtl sets
`SO_REUSEADDR`, which on Windows lets a second server bind a port that is
already listening, so both listened and a client reached whichever one accepted.
The transport's server does not set it, so the bind itself refuses.

`allowSharedPort` lets two servers share a port on purpose, and has to be set on
both: Windows refuses it over a server that did not set it. The early check is a
convenience; a server that takes the port between the check and the bind is
still refused at the bind.

Ports 18948 (`Stereoscopic`) and 18949 (`UC2_STO2`) are refused by name. That
reservation predates `ADR-0004`. The stand-in uses the app's ports, 18944 to
18946, and leaves the reservation alone.

## Tests

```powershell
.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py
```

These use the standard-library `unittest` runner, not the Slicer test runner.
They open real sockets on free local ports and need no data.

Lint both the Slicer module and this package with:

```powershell
.\scripts\development\run-python-quality.ps1
```
