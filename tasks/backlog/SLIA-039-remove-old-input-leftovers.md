---
id: SLIA-039
title: Remove what the old inputs left behind
status: backlog
branch:
priority: medium
depends_on: SLIA-038
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-039 - Remove what the old inputs left behind

## Goal

Nothing in the module, its tests, its scripts or its documentation exists only
for the 93-band HSI Human Brain Database cases. What stays is what 002-04 and
the cube received from IUMA's app need.

## Context

*Created on 2026-10-07 during `SLIA-038`.* The owner asked what to do with tests
tied to the old inputs and their ground truth, and decided that nothing useless
is to be left in the project: old-input leftovers are removed, in one task, after
`SLIA-038`.

What was found on 2026-10-07:

- **The ground-truth overlay can no longer appear.** `ADR-0004` decision 8 offers
  `gtMap` only for a cube with a `gtMap` beside it. `002-04` has none, the cube
  received from the app has none, and SLIAFlow does not read `020-01`. The
  overlay still has code in `SLIAFlowCube.py`, `SLIAFlowLogic.py`,
  `SLIAFlowWidget.py`, `SLIAFlowUc1Input.py` and the tooltip in `SLIAFlow.ui`,
  and about 14 tests. None of those tests reads `input/`: they write placeholder
  `gtMap` files. Twelve of them ran in 0.7 s (`-Test groundTruth,...`, exit 0), so
  the cost is the code they keep alive, not run time.
- **`test_moduleHasNoCasePool`** only checks that the case pool retired in
  `SLIA-031` has not come back.
- **Documents still describe removed commands and folders.** `input\bin\bin`,
  `run-uc1-real.ps1` and `python -m stratum_sim uc1-real` / `uc2-real` no longer
  exist, but appear in `pipeline_test_quickstart.md`, `end_to_end_verification.md`,
  `uc1_local_build.md`, `uc2_local_build.md`, `uc1_demo_runbook.md` and
  `WP5_MS5_DEMO_PLAN.md`.
- **The build checks lean on `020-01`.** Both passed on 2026-10-07
  (`check-uc1.py` exit 0 in 4.5 s, `check-uc2.py` exit 0 in 1.7 s).
  - `check-uc1.py` never runs UC1 on 002-04. It proves the patches leave UC1
    unchanged on `020-01`, and exercises the float32 path and the equal bands of
    the LCTF band mapping on `020-01` rewritten as float32. Only a Capture in
    Slicer runs UC1 on the mapped 002-04 cube.
  - `check-uc2.py` runs UC2 on `002-04` and matches a NumPy replica pixel for
    pixel; its `020-01` check proves the uint16 path is untouched.
  - If `020-01` is deleted, both scripts lose their only comparison with the
    unpatched build as delivered.
- `SLIA-009` requirement 3 said to keep the ground-truth tests. It was changed
  on 2026-10-07 to point here.

## Requirements

To be confirmed at specification.

1. **Ground-truth overlay retired.** The `gtMap` entry, its reading, its label
   layer, its colour table and its status wording are removed from the module,
   with the tests that cover them. A new ADR supersedes `ADR-0004` decision 8 and
   the 2026-09-18 amendment of `ADR-0003` decision 3. The UC1 colour legend
   (`FOUR_COLORS_MAP`) stays, because `svm.bmp` and `knn.bmp` use it.
2. **Guards for retired code removed.** `test_moduleHasNoCasePool` and any test
   like it.
3. **Build checks run on 002-04.**
   - `check-uc1.py` runs UC1 on the mapped 002-04 cube: exit 0, five outputs of
     1080 x 1080.
   - Both scripts compare their 002-04 outputs with a recorded run of the
     current build, so a later change to a patch shows up.
   - What happens to the `020-01` checks is the owner's decision at
     specification (see Risks).
4. **Documents describe only what exists.** Stale instructions are removed or
   rewritten; documents with no remaining use are deleted. Historical records
   in `tasks/completed/` and accepted ADRs stay as written.
5. **`input/` described as it will be.** `input/README.txt` and
   `.ai/policies/medical-data-policy.md` drop the folders the owner removes. The
   owner deletes the data; the agent does not delete anything under `input/`.

## Out of scope

- Any change to UC1's or UC2's algorithms or parameters.
- Judging whether UC1 or UC2 results on 002-04 are meaningful. Noted on
  2026-10-07: UC2's blue channel is at 255 on 69.9 % of the 002-04 map, against
  under 1 % for red and green. Whether UC2's fixed parameters (`high_in 0.15`)
  suit the LCTF camera is a question for IUMA.
- `source/`, `apps/`, `knowledge/`, `workspace/components/`.

## Files allowed

To be defined at specification. Expected: `SLIAFlowCube.py`,
`SLIAFlowLogic.py`, `SLIAFlowWidget.py`, `SLIAFlowUc1Input.py`,
`SLIAFlowTest.py`, `SLIAFlow.ui`, `extensions/SLIAFlow/README.md`,
`scripts/development/check-uc1.py`, `scripts/development/check-uc2.py`, a new
ADR, the documents named in Context, `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`,
`docs/development/uc1_changes.md`, `docs/development/uc2_changes.md`,
`input/README.txt` and `.ai/policies/medical-data-policy.md`.

## Relevant skills and references

- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `tasks/completed/SLIA-025-retire-synthetic-phantom-path.md` and
  `tasks/completed/SLIA-031-single-cube-cleanup.md`, earlier retirements
- `docs/development/uc1_changes.md`, `docs/development/uc2_changes.md`

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

- **Deleting `020-01` loses the proof against the delivered UC1 and UC2.** A
  recorded run of the current build on 002-04 catches later changes, but not a
  difference the patches already introduced. Options for the owner: keep
  `020-01` as the one old case; or record the 002-04 runs first, confirm both
  checks pass on `020-01` one last time, and then delete it.
- The overlay's code is spread across the widget and logic; removing it must not
  change what the five UC1 outputs look like on the Tumour Delineation panel.

## Documentation impact

To be defined at specification.

## Completion evidence

## Review findings

## Human approval
