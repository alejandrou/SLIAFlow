---
id: SLIA-035
title: Connections panel - see the acquisition app's ports and what each one carries
status: backlog
branch:
priority: medium
depends_on: SLIA-028, SLIA-032
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-035 - Connections panel - see the acquisition app's ports and what each one carries

## Goal

Give SLIAFlow a **Connections** section that shows, for each port of IUMA's
acquisition app, whether it is connected and what is arriving, the way IUMA's
team saw it in Slicer's OpenIGTLinkIF module, but in the product's own terms. It
is the tool used in `SLIA-030` to measure the app's protocol and receive its
cube.

## Context

Requested by the project owner on 2026-09-24: IUMA could see the ports and what
they carried from OpenIGTLinkIF inside Slicer, and the owner wants that in
SLIAFlow too.

OpenIGTLinkIF shows a list of connectors, each with its state, and under each
the devices that arrived: name, message type and the Slicer node they went to.
It ships with our Slicer build (`SLIA-007`). It is a technician's view: it does
not know what a cube is or how many bands are missing.

IUMA's app serves (`docs/hardware/acquisition_app_and_hardware.md` section 4):

| Port | Channel | Content |
| --- | --- | --- |
| 18944 | LiveView | camera frames, IMAGE |
| 18945 | Stereo ("Steroscopic" in the app) | stereo frames, IMAGE |
| 18946 | HS Cube | one IMAGE per band; float32 per IUMA |

OpenIGTLinkIF keeps only the latest message(s) per device name in a small
buffer, so a cube sent as many bands under one name can lose bands. Showing
band progress makes that visible.

`SLIA-026` showed that link rows for producers that never exist read as
"connecting forever" and confuse the operator. `SLIA-027` removed the old link
rows for that reason.

Proposed panel, to refine at specification:

```
Port   Channel    State        Last message                          Received
18944  LiveView   Connected    IMAGE 1280x1024 uint8 - 0.1 s ago     24 fps
18945  Stereo     Waiting      -                                     -
18946  HS Cube    Receiving    IMAGE 1080x1080 float32 - 650 nm      57 / 109 bands
                                                     [Open in OpenIGTLinkIF]
```

## Requirements

- One row per configured port, and only for configured ports. Host and ports
  are settings with the defaults above.
- State in plain words: not connected, waiting for the app, connected,
  receiving, cube complete, error with its reason.
- Per port: last device name, message type, size, data type, time since the
  last message, message rate; for the HS Cube port, bands received out of
  expected, and which bands are missing.
- A button that opens OpenIGTLinkIF for the technical detail.
- Connectors are client connectors created and removed by the module, with no
  connector left behind on module exit, scene close or shutdown.
- Built from the connector node's state and events and the nodes it creates.
  Which events and methods exist is checked in the Slicer skill at
  specification, not assumed.
- **A stand-in for IUMA's app**, on the transport kept by `SLIA-028`: a small
  sender that serves 18944, 18945 and 18946 and sends `002-04` band by band as
  float32 IMAGE messages, with a mode that drops bands, so the panel can be
  tested without the app. It is labelled as a stand-in in its output and in
  every document that mentions it.
- The panel shows what arrives; it does not yet put the received cube into the
  HS Cube panel (`SLIA-030`).

## Out of scope

- Receiving and assembling the cube for display or UC1 (`SLIA-030`).
- Sending anything to the app.
- PLUS (`ADR-0004` decision 9).

## Files allowed

To be defined at specification. Expected: `SLIAFlowLogic.py`,
`SLIAFlowWidget.py`, `SLIAFlow.ui`, `SLIAFlowParameterNode.py`,
`SLIAFlowTest.py`, a new stand-in module and its tests under `tools/simulators`,
`docs/development/openigtlink_setup.md`, module README.

## Relevant skills and references

- Slicer skill: OpenIGTLinkIF, `vtkMRMLIGTLConnectorNode` (state, events,
  incoming nodes), module cleanup.
- `docs/hardware/acquisition_app_and_hardware.md`, sections 4, 7 and 8
- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md` (what went
  wrong with the old link rows)
- `tools/simulators/stratum_sim/igtl_transport.py`

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification. At minimum:

- with the stand-in running, each row shows the right state and message details;
- the HS Cube row counts bands and names the missing ones when the stand-in
  drops bands;
- with nothing running, rows say plainly that the app is not running rather than
  appearing to connect forever;
- no connector survives module exit, scene close or shutdown.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- Three client connectors trying to reach an app that is not running must not
  slow the module or flood the log.
- The stand-in can only imitate what we know of the app. Anything it assumes
  about message layout is listed and checked against the real app in `SLIA-030`.

## Documentation impact

`docs/development/openigtlink_setup.md`, module README, `tools/simulators/README.md`.

## Completion evidence

## Review findings

## Human approval
