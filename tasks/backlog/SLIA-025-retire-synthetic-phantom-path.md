---
id: SLIA-025
title: Retire the synthetic phantom path
status: backlog
branch:
priority: medium
depends_on: SLIA-023
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-025 - Retire the synthetic phantom path

## Goal

Remove generated data from what the project runs and presents, so that every
session, label and document describes data that was recorded. The acquisition
event stays simulated - there is still no hyperspectral camera on this machine -
but no cube, scene or map shown to anyone is made up.

## Context

Decided by the project owner on 2026-09-14, after the `SLIA-023` launcher session
on recorded case `004-02`: the work uses data that has already been recorded, so
talking about anything synthetic around it is false. The owner chose to split the
work. `SLIA-023` removed the synthetic LiveView option and every synthetic word
from the recorded session; this card retires the rest.

What remains, counted on 2026-09-14 (234 mentions of "synthetic" in 58 files,
outside `source/`, `apps/`, `knowledge/` and `input/`):

- **Simulator code** in `tools/simulators/stratum_sim/`: `tissue.py` (the
  optical phantom), the scene synthesis in `spectra.py`,
  `frames.SyntheticFrameSource`, the `tissue` and `channel` scene modes and the
  dataset writer in `acquisition_sim.py` and `envi.py`, the arithmetic UC1
  stand-in in `uc1_maps.py` and `uc1_sim.py`, the phantom and synthetic-input
  details and `--force-unmarked` in `uc1_runner.py`, and the package docstring.
- **Scripts**: the default (phantom) session of `run-end-to-end-session.ps1`,
  `run-acquisition-simulator.ps1`, `run-uc1-simulator.ps1` and `run-uc1-real.ps1`.
- **Tests** that build phantom or channel datasets: `test_tissue.py`,
  `test_frames.py`, `test_uc1_sim.py`, parts of `test_uc1_runner.py`,
  `test_config.py`, `test_igtl_transport.py` and `test_acquisition_sim.py`, and
  the detail strings used as fixtures in `SLIAFlowTest.py`.
- **Documentation**: `synthetic_tissue_phantom.md`, `end_to_end_verification.md`,
  `uc1_demo_runbook.md`, `uc1_local_build.md`, `testing_strategy.md`,
  `pipeline_test_quickstart.md`, `camera_setup.md`, the simulators README, the
  UC1 image contract, the WP5 plan, the implementation roadmap and two Slicer
  architecture notes.
- **Backlog cards** built on the phantom: `SLIA-019` and `SLIA-020`. `SLIA-009`
  and `SLIA-021` mention it in passing.
- **Policy text**: `AGENTS.md` and `.ai/policies/medical-data-policy.md` list
  synthetic data as allowed test data.

Completed task cards and dated review records are history and are not rewritten.

## Questions to settle before activation

1. **What runs on a machine without the database?** `input/` is gitignored, so a
   fresh clone has no recorded case. Proposal: unit tests keep tiny
   counting-placeholder fixtures, labelled as test fixtures, and nothing a person
   can run generates a scene, a cube or a map; a session without `input/` stops
   and says where the cases go.
2. **What does the launcher do without `-Case`?** Refuse, or default to `004-02`.
3. **The arithmetic stand-in.** It already refuses recorded cases. Proposal:
   retire it with the phantom rather than teach it recorded data.
4. **The genuine UC1 integration test** runs the real binary on a phantom
   dataset. Proposal: run it on a recorded case when `input/` holds one, and skip
   with a stated reason when it does not.
5. **`SLIA-019` and `SLIA-020`.** Proposal: move both to `tasks/superseded/` with
   a note naming this card.
6. **The policy text.** Changing what `AGENTS.md` and the medical-data policy
   allow needs the owner's explicit approval, separate from approving this card.

## Requirements

To be completed when the questions above are answered. Fixed already:

- No session, command or document presents generated data as something to look
  at, and no text describes recorded data as synthetic.
- The wire origin stays `simulated`, because the acquisition is still simulated.
- The read-only guarantee over `input/` is unchanged.
- Nothing under `source/`, `apps/`, `knowledge/` or `input/` is modified.

## Out of scope

- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- Rewriting completed task cards or dated review records.
- The GPU run over the largest recorded cases, which the owner deferred until
  the pipeline is complete.

## Files allowed

To be fixed at activation from the inventory above. Expected to include
`tools/simulators/**`, the four scripts named above, the documents named above,
`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py` if its fixture strings
change, `tasks/backlog/SLIA-019-haemoglobin-absorption-valley.md`,
`tasks/backlog/SLIA-020-craniotomy-shaped-phantom-scene.md`, `tasks/superseded/`
and this card.

## Relevant skills and references

- `tasks/active/SLIA-023-recorded-cube-acquisition-standin.md` (or its later
  lifecycle folder), for the recorded path this card builds on
- `.ai/policies/medical-data-policy.md`
- `docs/development/testing_strategy.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`

## Implementation plan

To be written at activation.

## Acceptance criteria

To be written at activation.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
|  |  |  |

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Risks

Removing the phantom removes the only input that exists on every clone. Unless
question 1 is answered first, tests that need a cube will either stop running or
quietly skip, and a skipped test looks like a passing one.

The phantom path carries safeguards the recorded path reuses - the dataset
writer's overwrite interlock, the marker check, the refusal wording. Deleting a
module can delete a guard the recorded path still depends on, so each removal is
checked against the recorded tests, not only against the tests being removed.

## Documentation impact

Every document in the inventory above.

## Completion evidence

Reserved.

## Review findings

Reserved for review.

## Human approval

Proposed on 2026-09-14 under the project owner's instruction to retire the
synthetic information. Required before activation and before completion.
