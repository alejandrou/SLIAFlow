---
id: SLIA-028
title: Retire or re-home the standalone OpenIGTLink producers and session scripts
status: backlog
branch:
priority: medium
depends_on: SLIA-027
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-028 - Retire or re-home the standalone OpenIGTLink producers and session scripts

## Goal

Decide, and then carry out, what happens to the Python acquisition stand-in, the
UC1 runner service and the session scripts once `SLIA-027` runs the operator
workflow inside Slicer without OpenIGTLink.

## Context

Before `SLIA-027`, the workflow depended on:

- `tools/simulators/stratum_sim` (`acquisition_sim.py`, `uc1_runner.py`,
  `igtl_transport.py`, `capture_client.py` and their tests);
- `scripts/development/run-acquisition-simulator.ps1`,
  `run-end-to-end-session.ps1` and `run-uc1-real.ps1`.

`SLIA-027` leaves them unchanged but no longer uses them. Parts are still
valuable: `uc1_runner.py`'s run checks are the reference for the in-Slicer
runner, and `igtl_transport.py` may be the basis for `SLIA-030` external links.
`SLIA-021` currently plans a UC2 runner in the same package.

## Requirements

- Inventory each producer, script, test and document by whether anything still
  uses it after `SLIA-027`.
- Propose, per item, keep, move or delete, and get the project owner's decision
  before deleting anything.
- Keep `build-uc1.ps1`, which `SLIA-027` depends on.
- Update docs that still describe the session scripts as the way to run the demo.

## Out of scope

- Adding OpenIGTLink links back into Slicer (`SLIA-030`).
- Changing the vendored UC1 or UC2 source.

## Files allowed

To be defined at specification.

## Relevant skills and references

- `tasks/backlog/SLIA-027-integrated-slicer-capture-uc1.md`
- `tasks/backlog/SLIA-021-uc2-independent-map-producer.md`
- `tools/simulators/README.md`

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

Deleting a producer that `SLIA-021` or `SLIA-030` needs would force rework;
decide those cards' direction first.

## Documentation impact

`tools/simulators/README.md`, `docs/development/end_to_end_verification.md`,
`docs/development/pipeline_test_quickstart.md`, `docs/development/uc1_demo_runbook.md`.

## Completion evidence

## Review findings

## Human approval
