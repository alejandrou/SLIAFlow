---
id: SLIA-009
title: Operator runbook and shutdown hardening for the built application
status: backlog
branch:
priority: low
depends_on: SLIA-030
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-009 - Operator runbook and shutdown hardening for the built application

## Goal

A person who has never seen the code can start `SlicerWithSLIAFlow.exe`, run a
capture on the cube read from disk or received from IUMA's app, read what the
panels show, and shut down cleanly, following one short runbook.

## Context

*Rewritten on 2026-09-24.* The original card documented camera-only, simulated
stand-in and demo-mode operation, with banners marking simulated results.
`ADR-0003` removed demo mode, banners and the stand-in producers, and `ADR-0004`
reduces the data to one cube and makes IUMA's app the source. What remains
worth doing is the runbook and the clean-shutdown checks, written for the
application as it will be after `SLIA-030`.

## Requirements

- One operator runbook, `docs/operator/SLIAFLOW_RUNBOOK.md`, covering:
  - starting the built application and the laptop camera;
  - Capture on the cube read from disk;
  - connecting to IUMA's app and reading the Connections panel;
  - Capture on a cube received from the app;
  - what each panel shows, what "not validated" means, and that nothing shown
    is a clinical result;
  - clean shutdown.
- A troubleshooting section: camera busy (another program holds index 0), app
  not running, bands missing, UC1 failed or timed out, GPU out of memory.
- Shutdown leaves no locked camera, no running UC1 process, no build lock and no
  module-owned connector. Add tests where the module's cleanup does not already
  prove this.
- Reload and Reload and Test instructions for developers, in a short appendix.
- No screenshot of a result without its provenance text visible.

## Out of scope

- An installer.
- Clinical deployment or validation.
- Algorithm changes.

## Files allowed

To be defined at specification. Expected: `docs/operator/SLIAFLOW_RUNBOOK.md`
(new), `README.md`, `README_SLIAFlow_Build.md`, `SLIAFlowLogic.py`,
`SLIAFlowWidget.py`, `SLIAFlowTest.py`.

## Relevant skills and references

- `.ai/workflows/manual-verification-workflow.md`
- `docs/development/uc1_demo_runbook.md`, which the new runbook replaces for
  operators
- `docs/hardware/acquisition_app_and_hardware.md`

## Implementation plan

To be defined at specification.

## Acceptance criteria

To be defined at specification. At minimum: a first-time reader completes a
capture and a clean shutdown from the runbook alone, and records what they had
to guess.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

A runbook can suggest a readiness the prototype does not have. The prototype
and non-clinical status stay at the top of it.

## Documentation impact

The new runbook, linked from `README.md`.

## Completion evidence

## Review findings

## Human approval
