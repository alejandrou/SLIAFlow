---
id: SLIA-031
title: Clean up to one cube - archive the old cases, adopt 002-04, retire the case pool
status: backlog
branch:
priority: high
depends_on: SLIA-027
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-031 - Clean up to one cube - archive the old cases, adopt 002-04, retire the case pool

## Goal

Leave the repository and `input/` minimal and centred on one hyperspectral cube,
as `ADR-0004` decides:

- `input/` holds IUMA's LCTF capture `002-04`, one HSI Human Brain Database case
  kept as the UC1 reference, and a clearly named archive of everything else;
- the medical-data policy records the permission before any code reads `002-04`;
- the module reads one configured cube instead of drawing from a shuffled pool.

## Context

Agreed with the project owner on 2026-09-24:

- The owner and IUMA permit use of any data placed in `input/`.
- `002-04` (`C:\Users\AlejandroHerrera\Documents\002-04\002-04`) is the data of
  the future product until IUMA sends more or says otherwise. It holds
  `LCTF_Calibrated_Cube_Single` (float32, 1080 x 1080 x 109, 460-1000 nm),
  `raw_data` (uint16, 4096 x 2160 x 109), `WR` (109 bands), `DR`, `DR_WR` and
  `DR_DC` (1 band each) and a photo `M01.jpg`.
- `input/bin/bin` (61 cases, 6.7 GB) and `input/bin_full_size_images/bin_12MPx.zip`
  (20 GB, 3 cases at 4096 x 3000) are no longer the working data.
- `SLIAFlowCasePool.py` exists to shuffle 61 cases, skip deferred ones and check
  each against the 93-band model. With one cube it has no job.

UC1 cannot read `002-04` until `SLIA-033`. So after this task, Capture keeps
running UC1 on the **reference case**, read through the same single-cube loader,
and the HS Cube panel keeps showing that case. `SLIA-032` puts `002-04` on screen
and `SLIA-033` makes it the cube UC1 runs on. Nothing the operator can do today
stops working in between.

## Requirements

- **Accept `ADR-0004`** with the project owner at specification, and apply its
  acceptance note to `ADR-0003`'s front matter and Status section.
- **Update `.ai/policies/medical-data-policy.md` first**, before any code reads
  the new data:
  - add `002-04` as an approved dataset: source IUMA (ULPGC), nature (in vivo
    LCTF capture provided by IUMA for this project), permission from the project
    owner and IUMA dated 2026-09-24, local location under `input/`, read-only,
    never in version control, never copied into `docs/`, `workspace/` or
    published material;
  - record that the HSI Human Brain Database entry now covers the archive and
    the one reference case;
  - remove the reference to the demo-mode interlock, which `ADR-0003` removed.
- **Reorganise `input/`** (gitignored, no Git operation involved). Proposed
  layout, to confirm at specification:

  ```
  input/
    002-04/                              copy of the IUMA capture, all files
    reference_hsi_brain_db/<case>/       one recorded case for UC1 reference runs
    archive_hsi_brain_db_93_bands/
      bin/                               the former input/bin/bin
      bin_full_size_images/              the former zip
  ```

  - `002-04` is **copied** from `Documents`; the original is not touched.
  - The archive is a **move** inside `input/`, not a copy (27 GB).
  - The reference case is chosen at specification: small, known to run and to
    validate under `SLIA-027` (candidate: the case used in `SLIA-027`'s manual
    verification).
  - Write a short `input/README.txt` saying what each folder is. It stays
    untracked like the rest of `input/`.
- **Replace the case pool with a single-cube loader.** Remove
  `SLIAFlowCasePool.py`'s pool, shuffling, deferred list and `discoverCases`.
  Keep what still applies to a single uint16 case (header parsing, file-size
  checks, band-count check against the model, `gtMap` reading) in a module named
  for what it does now (for example `SLIAFlowCube.py`). The cube folder is one
  setting, defaulting to the reference case.
- Update the widget's error text: "no compatible case in the pool" becomes a
  plain statement about the one configured cube.
- Update tests: remove pool and deferred-case tests; keep and adapt the header,
  size, band-count and ground-truth tests.
- Update the documents that name `input/bin/bin` as the working data.

## Out of scope

- Reading float32 or showing `002-04` (`SLIA-032`).
- Running UC1 on `002-04` (`SLIA-033`).
- Retiring `tools/simulators` and the session scripts (`SLIA-028`). They still
  read `input/bin/bin` and will stop finding it; that breakage is expected and
  recorded, not fixed here.
- Deleting any data. The archive is kept.

## Files allowed

Draft, to be made exact at specification:

- `.ai/policies/medical-data-policy.md`
- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md` (front matter and Status only)
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md` (status to accepted)
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCasePool.py` (removed or renamed)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCube.py` (new, name to confirm)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/__init__.py`
- `extensions/SLIAFlow/README.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/development/uc1_demo_runbook.md`
- `tasks/{backlog,active,review,completed}/SLIA-031-single-cube-cleanup.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `docs/hardware/acquisition_app_and_hardware.md`, sections 3.4, 7 and 8
- `tasks/active/SLIA-027-integrated-slicer-capture-uc1.md`
- Slicer skill, for the parameter-node setting

## Implementation plan

1. Accept `ADR-0004`; update the medical-data policy.
2. Reorganise `input/` and record the before and after listing, with sizes.
3. Write the failing tests for the single-cube loader.
4. Replace the pool; adapt the widget and its messages.
5. Update the documents; run the full test suite and Python quality checks.

## Acceptance criteria

- The medical-data policy approves `002-04` with its conditions, dated, before
  any code in the repository refers to it.
- `input/` matches the agreed layout, `002-04` in `Documents` is unchanged, and
  no data file is tracked by Git.
- The module has no case pool, no shuffling and no deferred-case list.
- Capture runs UC1 on the configured reference case exactly as before, with
  the same outputs, provenance and ground-truth overlay.
- A configured cube folder that is missing or inconsistent is refused with a
  message naming the folder and the reason.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The module reads exactly the configured cube folder | `SLIAFlowTest.test_captureUsesTheConfiguredCube` | automated |
| A missing or inconsistent cube folder is refused with its reason | `SLIAFlowTest.test_configuredCubeIsRefusedWithItsReason` | automated |
| No pool, shuffle or deferred list remains | `SLIAFlowTest.test_moduleHasNoCasePool` | automated |
| The policy approves `002-04` before any code names it | Manual step 1 | manual |
| `input/` matches the layout and no data is tracked | Manual step 2 | manual |
| Capture on the reference case works as before | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_captureUsesTheConfiguredCube` points the setting at a temporary folder
  laid out like the reference case and is shown failing against the pool, which
  ignores the setting.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Read the policy diff and `git log` for the task | The `002-04` approval lands in a commit no later than the first code that reads it | |
| 2 | List `input/` and run `git status --ignored input` | The agreed folders and sizes; nothing under `input/` is tracked | |
| 3 | In `SlicerWithSLIAFlow.exe`, Start, Capture, pick `imageRGB` and `gtMap` | UC1 runs on the reference case, five outputs, overlay drawn, status names the case | |

## Risks

- Moving 27 GB can fail halfway on a full disk. Check free space first and move
  folder by folder, verifying counts after each.
- The standalone tools stop finding `input/bin/bin`. That is intended; `SLIA-028`
  retires them.

## Documentation impact

Medical-data policy, `ADR-0003` status, `ADR-0004` status, module README, UC1
demo runbook, WP5 demo plan.

## Completion evidence

## Review findings

## Human approval
