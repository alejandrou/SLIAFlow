---
id: SLIA-021
title: Run UC2 blood-vessel enhancement inside Slicer on the LCTF cube
status: backlog
branch:
priority: low
depends_on: SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-021 - Run UC2 blood-vessel enhancement inside Slicer on the LCTF cube

## Goal

Run the vendored UC2 blood-vessel enhancement on the configured cube as a
background process from SLIAFlow, the way `SLIA-027` runs UC1, and show its map
in the Enhanced Vascularization panel, which is black and reserved today.

UC2 is not in the owner's current plan (2026-09-24). This card stays parked at
low priority until the owner schedules it.

## Context

*Rewritten on 2026-09-24 against `ADR-0003` and `ADR-0004`.* The original card
(2026-09-11) planned a Python runner in `tools/simulators` streaming a PNG on
port 18946. Both parts no longer fit: `ADR-0003` runs algorithms inside Slicer
without a network hop, `SLIA-028` retires the Python producers, and 18946 is the
HS cube port of IUMA's app. Its findings about the component still hold and are
kept here in short.

Findings kept from the original card (checked 2026-09-11):

- The component (`workspace/components/blood_vessels_enhancement`) builds with
  the MinGW GCC on this machine and ran unchanged on four HSI Human Brain
  Database cases, writing `<case>-BVMap.png`.
- It takes one argument, the dataset folder. `high_in = 0.15`,
  `high_out = 0.8`, `gamma = 1`, `bValue = 3` and the band indices are local
  variables in `main()`; they cannot be set from outside.
- It can only write the PNG, normalised per channel within each image, so two
  captures cannot be compared by colour. The float map would need a code change.
- The PNG lands in the process working directory, so a run needs a freshness
  check against run start, as UC1's does.
- The enhancer channel is taken from calibrated plane 0, which is the blue band,
  while the comment says red. Reported to the authors, not changed.

New findings against `002-04` (checked 2026-09-24, reading `main.c`):

- **Data type.** `main.c` switches on the header's data type: 12 is read as
  uint16, and anything else falls to a default branch that also reads uint16.
  A float32 cube (type 4) would be read as the wrong type without error.
- **References.** UC2 reads raw, white and dark and calibrates itself, like UC1.
  `002-04`'s calibrated cube has no references.
- **Band indices.** The fixed indices 54, 20 and 8 are commented as 710, 540 and
  480 nm on an LCTF grid starting at 440 nm. `002-04` starts at 460 nm, so the
  same indices land on **730, 560 and 500 nm**. On this grid 710, 540 and 480 nm
  are indices 50, 16 and 4.

So UC2 needs the same kind of documented patches as UC1 (`SLIA-033`): float32
calibrated input, and band selection that matches the cube's wavelengths.

## Requirements

To be defined when the owner schedules the card. Expected to cover:

- build UC2 reproducibly, recording command and toolchain;
- UC2 patches through the mechanism of `SLIA-033`, each documented with its
  result;
- a background run from SLIAFlow with timeout, lock and freshness check, reusing
  `SLIAFlowUc1Run.py`'s shape;
- the map in the Enhanced Vascularization panel with provenance distinct from
  UC1's, stating the fixed parameters.

## Out of scope

- Comparing UC1 and UC2 outputs, or either against a ground truth.
- Deciding the consortium's output form for UC2.

## Files allowed

To be defined at specification.

## Relevant skills and references

- `workspace/components/blood_vessels_enhancement/main.c`, `BV_enhancement.c`,
  `png_writer.c`, `CODE_REVIEW.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`
- `tasks/backlog/SLIA-033-uc1-accepts-calibrated-float32-cube.md`
- `.ai/policies/algorithm-boundary-policy.md`

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

A wrapper that silently corrects an algorithm produces results nobody can
trace. Every change to UC2 is a documented patch, and the blue-band enhancer
finding goes to the authors rather than being fixed quietly.

## Documentation impact

`docs/development/uc2_local_build.md` (new), `docs/development/uc1_changes.md`
or a UC2 equivalent, module README.

## Completion evidence

## Review findings

## Human approval
