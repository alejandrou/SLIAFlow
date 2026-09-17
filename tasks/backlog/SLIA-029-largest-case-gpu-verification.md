---
id: SLIA-029
title: Verify the largest recorded cases through UC1 on the GPU
status: backlog
branch:
priority: medium
depends_on: SLIA-027
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-029 - Verify the largest recorded cases through UC1 on the GPU

## Goal

Run `058-02` and the other cases larger than the `full` preset through the
finished in-Slicer pipeline, record GPU memory and timing, and decide whether
each case leaves `SLIA-027`'s deferred-case list.

## Context

`SLIA-023` found nine recorded cases larger than the `full` preset. The largest,
`058-02` at 752x721, scales from the recorded UC1 measurement to about 3.5 GiB of
GPU memory against 8151 MiB available. Its manual step 6 was deferred by the
project owner on 2026-09-14 until the pipeline is complete. `SLIA-027` completes
that pipeline and keeps `058-02` on a deferred-case list meanwhile.

## Requirements

- Run each large case through `stratum.opt.intermediate.exe` from
  `SlicerWithSLIAFlow.exe`, recording peak GPU memory (`nvidia-smi`), wall-clock
  time and whether all five outputs validate.
- A memory failure is recorded as a finding, not worked around.
- Remove a case from the deferred list only when it completes and validates.
- Record the figures in `docs/architecture/WP5_MS5_DEMO_PLAN.md`.

## Out of scope

- Changing UC1 source or build flags to make a case fit.
- Tiling, downsampling or otherwise altering a case.

## Files allowed

To be defined at specification.

## Relevant skills and references

- `tasks/completed/SLIA-023-recorded-cube-acquisition-standin.md`, manual step 6
- `tasks/backlog/SLIA-027-integrated-slicer-capture-uc1.md`

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

A GPU out-of-memory failure may leave the driver or the shared output folder in
a bad state; the run must release the lock and clear outputs.

## Documentation impact

`docs/architecture/WP5_MS5_DEMO_PLAN.md`, `docs/development/uc1_local_build.md`.

## Completion evidence

## Review findings

## Human approval
