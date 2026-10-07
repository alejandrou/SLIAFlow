---
id: SLIA-037
title: LiveView from IUMA's acquisition app in the live pane
status: backlog
branch:
priority: low
depends_on: SLIA-036
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0004]
---

# SLIA-037 - LiveView from IUMA's acquisition app in the live pane

## Goal

The operator can choose the app's LiveView stream (18944) instead of the laptop
camera as the picture in the live pane, and Capture freezes that picture as it
does the camera's.

## Context

*Created on 2026-10-06 from `SLIA-030` phase B*, which planned it next to
receiving the cube (`SLIA-036`). The owner split it off because the app sends
no LiveView frames without its cameras (`SLIA-030` manual step A3), so it cannot
be checked by hand until the hardware is available.

`SLIA-035` already connects a client connector to 18944 and shows its rate. Its
criterion 10 keeps any received frame out of the laptop camera volume.

## Requirements

To be defined at specification. From `SLIA-030` phase B:

- LiveView from the app appears in the live pane when the operator chooses it,
  as an alternative to the laptop camera.
- It never lands in the laptop camera volume (`SLIA-035` criterion 10).
- Received frames carry `SLIAFlow.DataOrigin = received`, with the detail of
  `SLIA-036` owner decision 2. Stand-in frames stay `simulated`.

## Out of scope

- Stereo display.
- Camera control or any message sent to the app.

## Files allowed

To be defined at specification.

## Relevant skills and references

- `tasks/completed/SLIA-030-external-openigtlink-links.md`
- `tasks/completed/SLIA-035-connections-panel.md`
- `docs/hardware/acquisition_app_and_hardware.md` section 4

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

Needs the app with its cameras.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

- The app's frame size (up to 4096 x 3000) and rate are not measured yet.

## Documentation impact

To be defined at specification.

## Completion evidence

## Review findings

## Human approval
