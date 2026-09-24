# OpenIGTLink transport

`tools/simulators` used to hold the STRATUM acquisition stand-in, the UC1 runner
service and their clients. `SLIA-028` retired them: UC1 runs inside Slicer since
`SLIA-027` (`ADR-0003`), and IUMA's acquisition app is the producer SLIAFlow
receives from (`ADR-0004`). They remain in Git history.

What is left is the OpenIGTLink transport those processes shared, kept as the
base for `SLIA-035`'s stand-in that imitates IUMA's app on its ports. Nothing
here is a producer today, and nothing here is run by the product.

## What remains

| File | What it is |
| --- | --- |
| `stratum_sim/igtl_transport.py` | Building IMAGE messages with pyigtl at header version 2, so their metadata reaches the wire, and plain STRING messages; refusing a port another process already listens on, and naming that process from the Windows TCP table; watching the clients attached to a server |
| `stratum_sim/contract.py` | What the transport and its tests share: the provenance keys of a `LiveView` message and the reserved ports |
| `tests/test_igtl_transport.py` | The transport's tests |
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
reservation predates `ADR-0004`; `SLIA-035` decides which ports its stand-in
uses.

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
