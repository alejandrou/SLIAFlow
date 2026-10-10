---
id: SLIA-041
title: Send a capture to Slicer from another computer with a portable stand-in for IUMA's app
status: backlog
branch:
priority: medium
depends_on: SLIA-040
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004, ADR-0006]
---

# SLIA-041 - Send a capture to Slicer from another computer with a portable stand-in for IUMA's app

## Goal

A second computer on the same network, with nothing installed, runs a portable
stand-in for IUMA's app and sends a capture. SLIAFlow on this laptop connects to
that computer's address, receives the cube, shows it, and runs Capture on it.
This proves the reception path over a real network, which a loopback test
does not.

## Context

*Created on 2026-10-08* from the project owner's request.

- IUMA's `AcquisitionSystemApp` listens on all interfaces (0.0.0.0) on ports
  18944-18946 (`docs/hardware/acquisition_app_and_hardware.md` section 4).
  Installing it on another computer needs IUMA's installer and the camera and
  filter drivers, which a network test does not need.
- The stand-in `tools/simulators/stratum_sim/iuma_app_standin.py` already sends
  what the app sends: with `--app-header`, header version 1, no metadata,
  timestamp 0, and every band as a whole-cube sub-volume (`SLIA-036`). It sends
  the calibrated float32 cube.
- It serves only `127.0.0.1`: pyigtl's `OpenIGTLinkServer` binds the loopback
  by default (`local_server=True`), and `igtl_transport`'s port probe binds
  `127.0.0.1`. pyigtl's other mode binds the address of
  `gethostbyname(gethostname())`, which on Windows may be a virtual adapter
  rather than the network card.
- On the Slicer side the Connections panel already takes a host
  (`SLIAFlowConnections.configure`). The received cube's provenance names the
  host and port (`SLIA-036`). It has only ever been `127.0.0.1`.
- `SLIAFlowReceivedCube.CUBE_IDLE_SEC` (10 s) abandons a cube that gets no band
  for 10 s. A float32 band of a 1080 x 1301 capture is about 5.6 MB, so a link
  slower than about 5 Mbit/s would time out. A wired or Wi-Fi local network is
  much faster; the pace is measured here.
- Loopback skips the network card, the firewall, a real address in
  Connections, and the network's pace.

## Requirements

### 1. The stand-in can serve the network

- `--listen ADDRESS`: the address the three ports bind to. The default stays
  `127.0.0.1`; `0.0.0.0` serves every interface, as the app does. The port
  probe binds the same address.
- On start it prints the addresses another computer can use (this computer's
  IPv4 addresses) and the three ports, and says it is a stand-in, not IUMA's
  app, as it already does.
- Check at specification: how to bind pyigtl's server to a chosen address
  (subclass, or set the address before `TCPServer.__init__`), measured on
  Windows.

### 2. The stand-in sends chosen captures

- `--capture ID` (repeatable) or `--input-folder PATH` with `--capture`, using
  `SLIA-040`'s rule for finding captures. `--cube` stays. With several
  captures, each new send of the cube (`--cube-interval`) takes the next one,
  so cubes of both sizes can be sent in one session.
- It prints which capture each send carries.

### 3. A portable package

- `scripts/development/package-standin.ps1` builds
  `build/standin-portable/SLIAFlow-IUMA-app-standin.zip`: a folder that runs
  on a Windows computer without Python, an installer, drivers or admin rights.
  It contains the stand-in as an executable and a `Start-StandIn.bat` that
  lists the captures in a folder next to it, asks which to send, and starts
  the stand-in with `--listen 0.0.0.0 --app-header`.
- The package holds no capture data. The owner copies a capture folder next to
  it on the other computer.
- Nothing in it uses IUMA's name, logo or app identity except to say it is a
  stand-in for IUMA's app.
- Check at specification: PyInstaller (one-folder, proposed) or Python's
  embeddable distribution with pinned wheels; size of the package; whether
  Windows SmartScreen or antivirus blocks an unsigned executable.

### 4. Two-computer guide

- `docs/development/two_computer_link.md`: copy the package and a capture to
  the other computer; start it; allow it on a **private** network when Windows
  asks; find its address; enter it in Connections; what each row shows; how to
  stop.
- Troubleshooting: nothing answers (firewall, network profile set to Public,
  Wi-Fi client isolation, wrong adapter address); the cube stops part way
  (pace, `CUBE_IDLE_SEC`).
- The measured pace over the local network, wired or Wi-Fi as tested.

### 5. Slicer side

- No module change is expected. If the network test shows one is needed, such
  as a cube abandoned by `CUBE_IDLE_SEC` on Wi-Fi, it is recorded and brought to
  the owner before the card is changed.

## Out of scope

- Different networks, the internet, VPNs, encryption or authentication.
  OpenIGTLink has none, so the stand-in is only used on a trusted local
  network.
- Installing or imitating IUMA's real app or its installer.
- LiveView from a real camera; the stand-in sends its colour preview as today.
- Signing the executable.

## Files allowed

Proposed; confirmed at specification.

- `tools/simulators/stratum_sim/iuma_app_standin.py`
- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/test_iuma_app_standin.py`
- `tools/simulators/tests/test_igtl_transport.py`
- `tools/simulators/requirements.txt`
- `tools/simulators/README.md`
- `scripts/development/package-standin.ps1` (new)
- `docs/development/two_computer_link.md` (new)
- `docs/development/openigtlink_setup.md`
- `docs/hardware/acquisition_app_and_hardware.md` (measured network pace only)

## Relevant skills and references

- Slicer skill: OpenIGTLinkIF connector as a client of a remote host.
- `SLIA-036` for the protocol and the reception; `SLIA-035` for Connections.

## Implementation plan

To be written at specification.

## Acceptance criteria

To be written at specification. At least:

- the stand-in binds the address given by `--listen`, and the default is
  unchanged;
- the package runs on a computer without Python;
- from a second computer on the same network, a 1080 x 1301 capture and a
  1080 x 1080 capture are received complete, shown in HS Cube, and run through
  Capture, with the second computer's address in the provenance.

## Test plan

To be written at specification. Automated tests cover the bind address and the
capture order; the two-computer link is manual.

## Manual verification

To be written at specification. Two Windows computers on the same network:
start the package on the second, connect from SLIAFlow on this laptop, receive
both sizes, press Capture on each, stop the stand-in, and see Connections report
it gone.

## Risks

- Windows Firewall, a Public network profile or Wi-Fi client isolation can
  block the connection without an error on the sender.
- An unsigned executable may be blocked by SmartScreen or antivirus.
- The data crosses the local network unencrypted.
- The pace over Wi-Fi is unknown until measured.

## Documentation impact

`two_computer_link.md` (new); `openigtlink_setup.md`; `tools/simulators/README.md`.

## Completion evidence

## Review findings

## Human approval
