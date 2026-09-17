---
id: SLIA-030
title: Reintroduce OpenIGTLink links for external hardware and UC2
status: backlog
branch:
priority: low
depends_on: SLIA-027
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-030 - Reintroduce OpenIGTLink links for external hardware and UC2

## Goal

When a real external producer exists (microscope acquisition system, UC2
service or a remote UC1), add back the OpenIGTLink links it needs, with link
status in the panel.

## Context

`SLIA-027` removed Connect links, the five link-status rows and the module's
connector code, because the in-Slicer workflow had no external producer and
Slicer's `vtkMRMLIGTLConnectorNode::PushNode` does not send custom metadata. The
receive side does preserve metadata as `OpenIGTLink.*` node attributes, so
external producers that send metadata (for example with pyigtl) remain viable.

`SLIA-021` plans a UC2 producer on port 18946 and a vascularization panel fed by
it, which depends on links this card restores.

## Requirements

To be defined when a concrete external producer is chosen. Expected to cover:
which ports and devices are needed, client connectors, link status, provenance
from received metadata, and switching between the in-Slicer source and the
external one.

## Out of scope

- Serving links from Slicer to itself.

## Files allowed

To be defined at specification.

## Relevant skills and references

- `tasks/completed/SLIA-026-links-and-camera-in-the-built-app.md`
- `tasks/backlog/SLIA-027-integrated-slicer-capture-uc1.md`
- `tasks/backlog/SLIA-021-uc2-independent-map-producer.md`
- `docs/development/openigtlink_setup.md`

## Implementation plan

To be defined at specification.

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

Reintroducing links must not bring back the SLIA-026 "connecting forever"
confusion; link rows should appear only for producers that exist.

## Documentation impact

`docs/development/openigtlink_setup.md`, `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`.

## Completion evidence

## Review findings

## Human approval
