---
id: SLIA-028
title: Retire the standalone producers and session scripts, keeping only the OpenIGTLink transport
status: active
branch: feature/SLIA-028-retire-standalone-igtl-producers
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
`input/bin/bin` moves to the archive. Measured on 2026-09-24 before any change
(`.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`): 119 tests, one
error, `test_uc1_runner.RealBinaryIntegrationTest.test_stagedBinaryClassifiesARecordedCaseOnTheGpu`,
`C:\stratum\input\bin\bin\004-02 has no raw.hdr.` All 24
`test_igtl_transport` tests pass.

What is still worth keeping:

- `igtl_transport.py`: building IMAGE and STRING messages with pyigtl, port
  checks, the Windows TCP table reader that says who holds a port, and client
  watching. `SLIA-035` needs a sender that behaves like IUMA's app on 18944,
  18945 and 18946, and this is its base.
- `contract.py` only as far as `igtl_transport.py` imports it.
- `uc1_runner.py`'s run checks are already restated in `SLIAFlowUc1Run.py`
  (`SLIA-027`), so the file itself is no longer the reference.

### Dependency closure of what is kept (measured 2026-09-24)

- `igtl_transport.py` imports only `contract`, and uses only
  `contract.RESERVED_PORTS`.
- `test_igtl_transport.py` imports `contract`, `igtl_transport` and
  `tests.support`, and uses `contract.liveViewMetadata`,
  `support.pinnedRequirement` and `support.REPOSITORY_ROOT`.
- `contract.liveViewMetadata` uses `METADATA_DEVICE_NAME_KEY`,
  `METADATA_DATA_ORIGIN_KEY`, `METADATA_SIMULATION_DETAIL_KEY`,
  `DATA_ORIGIN_SIMULATED` and `LIVE_VIEW_DEVICE_NAME`.
- `contract.loadDataset` lazily imports `envi`. Nothing kept calls it.
- `opencv-python-headless` in `requirements.txt` is imported only by
  `frames.py` and `test_frames.py`.

Files outside `tools/simulators` that point at what is removed:

- `scripts/development/build-uc1.ps1` line 381 ends its run by telling the
  reader to run `python -m stratum_sim uc1-real`.
- `extensions/SLIAFlow/README.md` says `tools\simulators` and the session
  scripts "still exist until `SLIA-028`".
- `docs/development/project_structure.md` describes `tools/simulators` as the
  stand-in processes.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` line 218 sends the
  reader to `tools/simulators/README.md` for control-channel wording that the
  rewritten README will not contain.
- Comments in `SLIAFlowCube.py`, `SLIAFlowUc1Run.py` and `SLIAFlowTest.py` cite
  `uc1_runner.py` as the origin of checks they restate. They are attributions,
  not instructions, and the Slicer module is out of scope, so they stay.
- `ADR-0003` is accepted and records that the session scripts no longer serve
  the operator. It stays as written.
- `pyproject.toml` and `run-python-quality.ps1` lint `tools/simulators`, which
  still exists, so they need no change.
- `config/local.example.json` carries a `simulators` block read only by the
  deleted `config.py`. Found during implementation; its removal was added to
  `Files allowed` (the real `config/local.json` is not touched).

## Inventory

Approved as proposed by the project owner on 2026-09-24, before anything was
deleted.

`tools/simulators`:

| File | Decision | Why |
| --- | --- | --- |
| `README.md` | keep, rewrite | Describes only the transport and what `SLIA-035` uses it for |
| `requirements.txt` | keep, edit | Drop `opencv-python-headless`, used only by `frames.py`; keep `numpy`, `pyigtl`, `crcmod` |
| `ruff.toml` | keep | The lint target remains |
| `stratum_sim/__init__.py` | keep, edit | Docstring and `__all__` name only the kept modules |
| `stratum_sim/igtl_transport.py` | keep, unchanged | The transport `SLIA-035` builds on |
| `stratum_sim/contract.py` | keep, trim | Reduce to `RESERVED_PORTS`, `liveViewMetadata` and the constants it uses; the dataset, map, capture and UC1 metadata contract has no user left |
| `stratum_sim/__main__.py` | delete | Its only job is to launch `acquisition`, `uc1-real` and `capture` |
| `stratum_sim/acquisition_sim.py` | delete | The acquisition stand-in; IUMA's app is the producer (`ADR-0004`) |
| `stratum_sim/uc1_runner.py` | delete | UC1 runs inside Slicer (`ADR-0003`, `SLIAFlowUc1Run.py`) |
| `stratum_sim/capture_client.py` | delete | Triggers the deleted stand-in |
| `stratum_sim/config.py` | delete | Configuration of the deleted producers |
| `stratum_sim/envi.py` | delete | Only the producers read ENVI here; the module has its own reader (`SLIAFlowCube.py`) |
| `stratum_sim/frames.py` | delete | Laptop camera source of the stand-in; the module has its own camera |
| `stratum_sim/bmp.py` | delete | UC1 BMP reading for the runner; `inspect-uc1-bmp.py` is self-contained |
| `stratum_sim/spectra.py` | delete | Used only by the runner |
| `stratum_sim/uc1_maps.py` | delete | Used only by the runner |
| `tests/__init__.py` | keep | Package marker for discovery |
| `tests/run_tests.py` | keep, edit | Docstring says what is tested now |
| `tests/support.py` | keep, trim | Reduce to `REPOSITORY_ROOT` and `pinnedRequirement` |
| `tests/test_igtl_transport.py` | keep, unchanged | The transport's tests |
| `tests/test_contract.py` | delete | Tests the dataset, map and capture contract being removed, and guards retired generators that deleting the package parts makes moot; `liveViewMetadata` stays covered by `test_igtl_transport.py` |
| `tests/test_acquisition_sim.py` | delete | Tests a deleted module |
| `tests/test_uc1_runner.py` | delete | Tests a deleted module; already failing on the archived `input\bin\bin` |
| `tests/test_config.py` | delete | Tests a deleted module |
| `tests/test_envi.py` | delete | Tests a deleted module |
| `tests/test_frames.py` | delete | Tests a deleted module |
| `tests/test_bmp.py` | delete | Tests a deleted module |
| `tests/test_spectra.py` | delete | Tests a deleted module |
| `tests/test_uc1_maps.py` | delete | Tests a deleted module |
| `tests/liveview_client.py` | delete | Manual client for the stand-in's LiveView |
| `tests/uc1_client.py` | delete | Manual client for the runner's maps |

`scripts/development`:

| File | Decision | Why |
| --- | --- | --- |
| `run-acquisition-simulator.ps1` | delete | Launches the deleted stand-in |
| `run-end-to-end-session.ps1` | delete | Launches the deleted stand-in and runner |
| `run-uc1-real.ps1` | delete | Launches the deleted runner |
| `build-uc1.ps1` | keep, edit one hint | Its closing hint names `stratum_sim uc1-real`; point at Capture in SLIAFlow instead |
| `build-sliaflow.ps1`, `run-slicer-tests.ps1`, `run-python-quality.ps1`, `inspect-uc1-bmp.py` | keep, unchanged | Used by the product workflow |

## Requirements

- Show the inventory above to the project owner and wait for the decision
  before deleting anything.
- Keep `igtl_transport.py` unchanged, trim `contract.py` and `tests/support.py`
  to what it and its tests use, and delete the rest of the producers, clients
  and their tests as approved.
- Delete the three session scripts. Keep `build-uc1.ps1`, `build-sliaflow.ps1`,
  `run-slicer-tests.ps1`, `run-python-quality.ps1` and `inspect-uc1-bmp.py`.
- Rewrite `tools/simulators/README.md` to describe only what remains, and what
  it is for.
- Update or mark as historical the documents that describe the removed scripts:
  `end_to_end_verification.md`, `pipeline_test_quickstart.md`,
  `uc1_demo_runbook.md`, `uc1_local_build.md`, `SLIAFLOW_UC1_IMAGE_CONTRACT.md`,
  `WP5_MS5_DEMO_PLAN.md`, plus the pointers listed under Context. The four
  `test_case_robustness_*` reviews and the task cards are historical records
  and stay as they are.
  - Whole-session procedures that only work with the removed scripts
    (`end_to_end_verification.md`, `pipeline_test_quickstart.md`,
    `WP5_MS5_DEMO_PLAN.md`) get a historical banner at the top naming
    `SLIA-028` and pointing at the current way to run; their bodies stay as the
    record.
  - Documents that are still current apart from those passages
    (`uc1_demo_runbook.md`, `uc1_local_build.md`,
    `SLIAFLOW_UC1_IMAGE_CONTRACT.md`) have the passages replaced or marked
    historical in place.
- The remaining simulator tests and the Python quality checks pass.

## Out of scope

- Building the app stand-in sender (`SLIA-035`).
- Any change to the Slicer module's code, including the attribution comments
  that name `uc1_runner.py`.
- Any change to `igtl_transport.py`, including its reserved ports 18948 and
  18949, which predate `ADR-0004`; `SLIA-035` decides the ports its stand-in
  uses.
- Any change to UC1 or UC2 source.
- Removing packages from the repository `.venv`.

## Files allowed

Deleted:

- `tools/simulators/stratum_sim/__main__.py`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/bmp.py`
- `tools/simulators/stratum_sim/capture_client.py`
- `tools/simulators/stratum_sim/config.py`
- `tools/simulators/stratum_sim/envi.py`
- `tools/simulators/stratum_sim/frames.py`
- `tools/simulators/stratum_sim/spectra.py`
- `tools/simulators/stratum_sim/uc1_maps.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/tests/liveview_client.py`
- `tools/simulators/tests/uc1_client.py`
- `tools/simulators/tests/test_acquisition_sim.py`
- `tools/simulators/tests/test_bmp.py`
- `tools/simulators/tests/test_config.py`
- `tools/simulators/tests/test_contract.py`
- `tools/simulators/tests/test_envi.py`
- `tools/simulators/tests/test_frames.py`
- `tools/simulators/tests/test_spectra.py`
- `tools/simulators/tests/test_uc1_maps.py`
- `tools/simulators/tests/test_uc1_runner.py`
- `scripts/development/run-acquisition-simulator.ps1`
- `scripts/development/run-end-to-end-session.ps1`
- `scripts/development/run-uc1-real.ps1`

Modified:

- `tools/simulators/README.md`
- `tools/simulators/requirements.txt`
- `tools/simulators/stratum_sim/__init__.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/tests/run_tests.py`
- `tools/simulators/tests/support.py`
- `scripts/development/build-uc1.ps1` (closing hint only)
- `docs/development/end_to_end_verification.md`
- `docs/development/pipeline_test_quickstart.md`
- `docs/development/uc1_demo_runbook.md`
- `docs/development/uc1_local_build.md`
- `docs/development/project_structure.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` (the pointer at line 218 only)
- `extensions/SLIAFlow/README.md` (the `SLIA-028` paragraph only; documentation, not module code)
- `config/local.example.json` (the `simulators` block only; added during implementation)
- `tasks/{backlog,active,review,completed}/SLIA-028-retire-standalone-igtl-producers.md`

## Relevant skills and references

- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md`
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `tools/simulators/README.md`
- `tasks/backlog/SLIA-035-connections-panel.md`

No Slicer skill: nothing here touches Slicer APIs.

## Implementation plan

1. Inventory and owner decision (this card).
2. Delete the approved files and trim `contract.py`, `support.py` and
   `__init__.py`; drop `opencv-python-headless` from `requirements.txt`.
3. Run `run_tests.py` to prove nothing kept imports what went, and
   `run-python-quality.ps1`.
4. Rewrite `tools/simulators/README.md`; update `run_tests.py`'s docstring.
5. Add historical banners or in-place replacements to the documents, fix the
   pointers under Context, and the `build-uc1.ps1` hint.
6. Search the repository for the removed names and record what remains and why.
7. Run `run-slicer-tests.ps1` as a regression check on the untouched module.

## Acceptance criteria

1. No producer, client or session script remains, except what the owner chose to
   keep.
2. `igtl_transport.py` and its tests remain unchanged and pass, and the test
   run contains no test of a removed module.
3. Ruff reports no finding on what remains.
4. No current document or script tells a reader to run a removed script or
   module; mentions remain only in historical banners' records, task cards, the
   `test_case_robustness_*` reviews, `ADR-0003`, and attribution comments in the
   module.
5. The Slicer module still passes its automated tests (it was not changed and
   never imported `stratum_sim`).

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. No producer, client or session script remains | `git status --short` and a listing of `tools/simulators` and `scripts/development`, compared with the Inventory | automated |
| 2. The transport and its tests remain unchanged and pass | `git diff --stat main -- tools/simulators/stratum_sim/igtl_transport.py tools/simulators/tests/test_igtl_transport.py` is empty; `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` runs exactly the 24 `test_igtl_transport` tests, all ok, exit 0 | automated |
| 3. Ruff reports no finding | `.\scripts\development\run-python-quality.ps1`, exit 0 | automated |
| 4. No current document points at a removed script | A repository search for the removed names, each hit classified; then Manual step 1 | automated + manual |
| 5. The Slicer module still passes | `.\scripts\development\run-slicer-tests.ps1`, exit 0 | automated |

Tests to add or change, and how each one will be shown to fail first:

- None new, and `test_igtl_transport.py` is not changed. The run after deletion
  is the check that nothing kept depended on a deleted module: if `contract.py`
  or `support.py` were trimmed too far, the 24 tests fail with an
  `AttributeError` or `ImportError` naming the missing symbol. Baseline before
  any change: 119 tests, 24 transport tests ok, one unrelated error recorded
  under Context.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | In VS Code, search the repository (excluding `apps`, `source`, `build`, `workspace`, `knowledge`) for `run-acquisition-simulator`, `run-end-to-end-session`, `run-uc1-real`, `stratum_sim acquisition`, `stratum_sim uc1-real`, `stratum_sim capture` | Every hit is in a task card, a `test_case_robustness_*` review, `ADR-0003`, or below a banner that says the passage is historical since `SLIA-028` | Verified 2026-09-24: `rg` found 89 matches in 19 files; the 18 matches outside task cards were in the five affected documents and all were below their historical sections/banners. No current-use hit was found. |
| 2 | Open `tools/simulators/README.md` | It describes only `igtl_transport.py`, the trimmed `contract.py` and their tests, says `SLIA-035` builds on them, and names no removed file as usable | Verified 2026-09-24: the README describes the retained transport, contract, tests and dependencies, identifies `SLIA-035` as its consumer, and presents no retired file as usable. |
| 3 | Open `docs/development/end_to_end_verification.md`, `pipeline_test_quickstart.md` and `WP5_MS5_DEMO_PLAN.md` | Each starts with a banner saying it is historical since `SLIA-028` and where the current way to run is | Verified 2026-09-24: all three begin with a `Historical since SLIA-028` banner and point to the in-Slicer demonstration in `uc1_demo_runbook.md`. |

## Risks

- `SLIA-021` planned a UC2 runner in this package. Its rewrite runs UC2 inside
  Slicer instead, so nothing is lost.
- `envi.py`, `bmp.py` and `uc1_runner.py` hold measured knowledge (ENVI header
  parsing, UC1 BMP layout, model file sizes). The module and
  `inspect-uc1-bmp.py` already restate what is in use, and the deleted files
  stay in Git history.
- The kept `RESERVED_PORTS` (18948, 18949) reflect the pre-`ADR-0004` port plan.
  They are left for `SLIA-035` to revise, since changing them changes
  transport behaviour.
- The repository `.venv` keeps `opencv-python-headless` installed until it is
  recreated; that is harmless.

## Documentation impact

`tools/simulators/README.md`, the six documents named under Requirements,
`docs/development/project_structure.md`, one pointer in
`SLIAFLOW_IMPLEMENTATION_ROADMAP.md`, one paragraph in
`extensions/SLIAFlow/README.md`.

## Completion evidence

Implementation on 2026-09-24, branch `feature/SLIA-028-retire-standalone-igtl-producers`,
not committed.

Inventory approved by the project owner as proposed, then applied: 10 modules,
11 test and client files and 3 session scripts deleted; `contract.py`,
`tests/support.py`, `__init__.py`, `run_tests.py` and `requirements.txt` trimmed
or edited; `igtl_transport.py` and `test_igtl_transport.py` unchanged.

| Check | Command | Result |
| --- | --- | --- |
| Baseline, before any change | `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | 119 tests, `FAILED (errors=1)`, exit 1; the error is `test_stagedBinaryClassifiesARecordedCaseOnTheGpu`, `input\bin\bin\004-02 has no raw.hdr.`; 24 `test_igtl_transport` tests ok |
| AC 1 | `git status --short` | Every deleted path is in the Inventory's delete rows; nothing else under `tools/simulators` or `scripts/development` deleted |
| AC 2 | `git diff --stat main -- tools/simulators/stratum_sim/igtl_transport.py tools/simulators/tests/test_igtl_transport.py` | empty |
| AC 2 | `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | `Ran 24 tests`, `OK`, exit 0; all 24 are `tests.test_igtl_transport` |
| AC 3 | `.\scripts\development\run-python-quality.ps1` | Ruff 0.15.21: `extensions/SLIAFlow/SLIAFlow` 9 files, `tools/simulators` 7 files, all checks passed, exit 0 |
| AC 4 | Repository search (excluding `apps`, `source`, `build`, `workspace`, `knowledge`, `tasks`) for the removed script and module names | 59 hits in 13 files: under the historical banners or headings in `end_to_end_verification.md`, `pipeline_test_quickstart.md`, `WP5_MS5_DEMO_PLAN.md`, `uc1_demo_runbook.md` (from line 48), `uc1_local_build.md` (from line 157) and `SLIAFLOW_UC1_IMAGE_CONTRACT.md` (bannered sections); the four `test_case_robustness_*` reviews; attribution comments in `SLIAFlowCube.py`, `SLIAFlowUc1Run.py` and `SLIAFlowTest.py` |
| AC 5 | `.\scripts\development\run-slicer-tests.ps1` | Module loaded from `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`; `Ran 75 tests`, `OK (skipped=9)` (headful-only), exit 0 |
| Whitespace | `git diff --check` | exit 0 |

Not run: `run-slicer-tests.ps1 -Headful` and `-Target Build`, because the module
code is unchanged. Manual steps 1-3 were independently verified on 2026-09-24
by repository search and document inspection; all three matched their expected
observations. No interactive Slicer session was needed because these steps are
documentation-only.

No new test was written, so there is no red-first evidence to record. The
transport tests passing unchanged after the trim is the check that nothing kept
depended on a deleted module.

Pre-review feedback from the project owner on 2026-09-24 found present-tense
statements about the deleted runner and stand-ins left in
`SLIAFLOW_UC1_IMAGE_CONTRACT.md` ("today", "currently", "makes", "sends"). The
runner's behaviour in the `SLIA-013` subsection, the `SLIA-012` pointer, the
`CaptureId` and `UC1_RGB` sentences, and "The stand-ins do." were moved to past
tense. `git diff --check` exit 0 afterwards. This is not the independent review.

## Review findings

## Human approval
