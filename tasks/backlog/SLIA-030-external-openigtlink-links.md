---
id: SLIA-030
title: Receive IUMA's acquisition app - measure its protocol, then show and classify its cube
status: backlog
branch:
priority: medium
depends_on: SLIA-035, SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-030 - Receive IUMA's acquisition app - measure its protocol, then show and classify its cube

## Goal

Connect SLIAFlow to IUMA's real acquisition app, write down exactly what it
sends, and then use it: LiveView from 18944 in the live pane, and the cube from
18946 assembled, shown in the HS Cube panel and run through UC1 like the cube
read from disk.

## Context

*Rewritten on 2026-09-24 against `ADR-0004`.* The original card waited for "a
real external producer". IUMA's app is that producer, and it is installed on
this laptop (`C:\Program Files\IUMA\InstallerAcquisitionApp`). Its UC2 part
moved to `SLIA-021`.

Known from the app's binary and from IUMA
(`docs/hardware/acquisition_app_and_hardware.md` sections 4, 7 and 8):

- The app is the OpenIGTLink server: 18944 LiveView, 18945 stereo, 18946 HS
  cube. Slicer is the client.
- The cube goes out as one IMAGE message per band. No per-band metadata strings
  were found in the binary, so how a receiver knows band index, wavelength and
  cube completion is unknown.
- Today the app sends the raw cube; IUMA will switch to the calibrated float32
  cube with the same protocol. White and dark references are handled by hand
  in IUMA's BSC program.
- The app can load a stored cube and transmit it, so reception can be tested
  with `002-04` without the cameras.
- OpenIGTLinkIF keeps only the latest message(s) per device name, so a
  band-per-message cube can lose bands in a plain connector.

`SLIA-035` gives the connections panel and a stand-in sender. This card replaces
the stand-in with the real app.

## Requirements

- **Measure first.** With the app transmitting `002-04`, record per port: device
  names, message types, sizes, data types, image spacing and orientation, any
  metadata, message order and timing, and how the end of a cube can be told.
  Write it into the hardware document and the OpenIGTLink setup document.
- **Decide the receiver** from the measurement: OpenIGTLinkIF connector with an
  observer that copies each band, or a module-owned reader for 18946 built on
  the transport kept by `SLIA-028`. The choice and its reason go in the card.
- **LiveView from the app** in the live pane, as an alternative to the laptop
  camera, chosen by the operator.
- **The cube from the app**: assembled only when every band has arrived, with
  the missing bands named otherwise; shown in the HS Cube panel; run through UC1
  on Capture like the cube read from disk. A partial cube is never classified.
- **Provenance** for a received cube: decide the wording with the owner
  (`ADR-0004` decision 7), and state the source app and time of reception.
- Questions the measurement cannot answer go to IUMA, listed in the hardware
  document section 7.

## Out of scope

- Sending anything back to the app (commands, parameters).
- Stereo display beyond showing that the port carries data.
- PLUS.
- UC2.

## Files allowed

To be defined at specification.

## Relevant skills and references

- Slicer skill: OpenIGTLinkIF, `vtkMRMLIGTLConnectorNode`, volume nodes from
  arrays.
- `docs/hardware/acquisition_app_and_hardware.md`
- `docs/development/openigtlink_setup.md`
- `tasks/backlog/SLIA-035-connections-panel.md`
- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md`

## Implementation plan

To be defined at specification, after the measurement.

## Acceptance criteria

To be defined at specification.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- The protocol may not say which band a message is. Then band order depends on
  message order, and one lost message shifts every band after it. The
  measurement must establish this before any receiver is built on it.
- The app needs its hardware to start cleanly; test with and without the camera
  and filter connected.

## Documentation impact

`docs/hardware/acquisition_app_and_hardware.md`,
`docs/development/openigtlink_setup.md`,
`docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`.

## Completion evidence

## Review findings

## Human approval
