---
id: SLIA-009
title: Harden and document the SLIAFlow demonstration
status: backlog
branch:
priority: medium
depends_on: SLIA-008
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-009 - Harden and document the SLIAFlow demonstration

## Goal

Provide a simple Windows operator workflow that can demonstrate the Slicer
interface safely with only a laptop camera and can later receive genuine project
outputs without changing the interface.

## Context

Hardware and external algorithms may be unavailable during early demonstrations.
The camera is a genuine live source; the result pane must remain explicitly empty.

## Requirements

- Add a short operator runbook and startup/shutdown checklist.
- Document one-time camera support installation and dependency checks.
- Document camera-only, acquisition-connected, and full-integration modes.
- Make missing camera, missing OpenIGTLink, disconnected sender, malformed result, and clean shutdown messages understandable.
- Ensure stopping the module releases cameras, timers, observers, and module-owned connectors.
- Record Reload and Reload and Test instructions.
- State clearly that the module is a prototype and not clinically validated.
- Include no fabricated result screenshots or simulated diagnostic outputs.

## Out of scope

- Packaging an installer.
- Clinical-trial deployment or validation.
- Algorithm changes, performance claims, or automated clinical reporting.

## Files allowed

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/**`
- `docs/operator/SLIAFLOW_DEMO_RUNBOOK.md`
- `README.md`
- `README_SLIAFlow_Build.md`
- `tasks/{backlog,active,review,completed}/SLIA-009-demo-hardening.md`

## Relevant skills and references

- Slicer scripted-module lifecycle and manual verification guidance.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Audit the full module lifecycle and user-facing failure messages.
2. Add targeted cleanup and state-transition tests where gaps exist.
3. Write the camera-only and connected-mode runbook.
4. Execute automated checks and the complete manual demonstration checklist.

## Acceptance criteria

- A non-technical operator can start and stop the camera-only demonstration from the runbook.
- The result pane remains black and clearly waiting when no genuine UC1 output exists.
- All expected failure modes are understandable and recoverable without restarting Windows.
- Shutdown leaves no locked camera or running module-owned connector.
- Documentation makes no clinical claim.

## Test plan

- Run the full extension CTest suite and Python quality checks.
- Exercise repeated enter/exit, camera start/stop, connection loss, scene close, and Reload.
- Perform the camera-only operator checklist on the Windows laptop.
- When a genuine sender is available, perform the connected checklist separately.

## Manual verification

Follow the runbook from a clean Slicer launch without relying on developer knowledge.

## Risks

A runbook can imply unsupported readiness if limitations are not prominent. Prototype,
data, and genuine-result boundaries remain visible throughout the instructions.

## Documentation impact

Add the final operator-facing demonstration guide and link it from project entry points.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
