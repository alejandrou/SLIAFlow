---
id: SLIA-028
title: Retire the standalone producers and session scripts, keeping only the OpenIGTLink transport
status: backlog
branch:
priority: high
depends_on: SLIA-031
required_skills: []
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-028 - Retire the standalone producers and session scripts, keeping only the OpenIGTLink transport

## Goal

Remove the Python acquisition stand-in, the UC1 runner service, the capture
client and the PowerShell session scripts, which nothing in the product uses
since `SLIA-027`. Keep only the OpenIGTLink transport code and its tests, which
`SLIA-035` reuses to imitate IUMA's acquisition app.

## Context

*Rewritten on 2026-09-24 against `ADR-0004`.* The original card asked for a
keep, move or delete decision per item. The owner's direction since then settles
most of it: the work is to be minimal and centred on one cube, and the real
producer is IUMA's app, not a Python service of ours.

What exists today:

- `tools/simulators/stratum_sim`: `acquisition_sim.py`, `uc1_runner.py`,
  `capture_client.py`, `uc1_maps.py`, `spectra.py`, `frames.py`, `bmp.py`,
  `envi.py`, `config.py`, `contract.py`, `igtl_transport.py`, `__main__.py`,
  and their tests under `tools/simulators/tests`.
- `scripts/development/run-acquisition-simulator.ps1`,
  `run-end-to-end-session.ps1`, `run-uc1-real.ps1`.
- Documents that still describe those scripts as the way to run the demo.

After `SLIA-031`, the producers also stop finding their data, because
`input/bin/bin` moves to the archive.

What is still worth keeping:

- `igtl_transport.py`: building IMAGE and STRING messages with pyigtl, port
  checks, the Windows TCP table reader that says who holds a port, and client
  watching. `SLIA-035` needs a sender that behaves like IUMA's app on 18944,
  18945 and 18946, and this is its base.
- `contract.py` only as far as `igtl_transport.py` imports it.
- `uc1_runner.py`'s run checks are already restated in `SLIAFlowUc1Run.py`
  (`SLIA-027`), so the file itself is no longer the reference.

## Requirements

- Inventory every file under `tools/simulators` and the three scripts, and state
  for each: kept, deleted, and why. Show the list to the project owner before
  deleting.
- Keep `igtl_transport.py`, what it imports, and their tests; delete the rest of
  the producers, clients and their tests.
- Delete the three session scripts. Keep `build-uc1.ps1`, `build-sliaflow.ps1`,
  `run-slicer-tests.ps1`, `run-python-quality.ps1` and `inspect-uc1-bmp.py`.
- Rewrite `tools/simulators/README.md` to describe only what remains, and what
  it is for.
- Update or mark as historical the documents that describe the removed scripts:
  `end_to_end_verification.md`, `pipeline_test_quickstart.md`,
  `uc1_demo_runbook.md`, `uc1_local_build.md`, `SLIAFLOW_UC1_IMAGE_CONTRACT.md`,
  `WP5_MS5_DEMO_PLAN.md`. The four `test_case_robustness_*` reviews are
  historical records and stay as they are.
- The remaining simulator tests and the Python quality checks pass.

## Out of scope

- Building the app stand-in sender (`SLIA-035`).
- Any change to the Slicer module.
- Any change to UC1 or UC2 source.

## Files allowed

Draft, to be made exact at specification:

- `tools/simulators/**`
- `scripts/development/run-acquisition-simulator.ps1` (deleted)
- `scripts/development/run-end-to-end-session.ps1` (deleted)
- `scripts/development/run-uc1-real.ps1` (deleted)
- `docs/development/end_to_end_verification.md`
- `docs/development/pipeline_test_quickstart.md`
- `docs/development/uc1_demo_runbook.md`
- `docs/development/uc1_local_build.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `tasks/{backlog,active,review,completed}/SLIA-028-retire-standalone-igtl-producers.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `tools/simulators/README.md`
- `tasks/backlog/SLIA-035-connections-panel.md`

## Implementation plan

1. Inventory and owner decision.
2. Delete, then run the remaining tests to prove nothing kept imports what went.
3. Rewrite the README and the documents.

## Acceptance criteria

- No producer, client or session script remains, except what the owner chose to
  keep.
- `igtl_transport.py` and its tests remain and pass.
- No document tells a reader to run a removed script.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The transport and its tests remain and pass | `tools/simulators/tests/run_tests.py` | automated |
| Python quality checks pass on what remains | `run-python-quality.ps1` | automated |
| No document points at a removed script | Manual step 1 | manual |

Tests to add or change, and how each one will be shown to fail first:

- None new. The existing transport tests are the check that nothing kept
  depended on a deleted module.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Search the repository for the removed script and module names | Only historical records and the task cards mention them | |

## Risks

`SLIA-021` planned a UC2 runner in this package. Its rewrite runs UC2 inside
Slicer instead, so nothing is lost.

## Documentation impact

`tools/simulators/README.md` and the documents listed above.

## Completion evidence

## Review findings

## Human approval
