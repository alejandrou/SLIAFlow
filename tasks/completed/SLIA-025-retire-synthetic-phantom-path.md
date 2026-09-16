---
id: SLIA-025
title: Retire the synthetic phantom path
status: active
branch: feature/SLIA-025-retire-synthetic-phantom-path
priority: medium
depends_on: SLIA-023
required_skills: []
optional_tools: []
related_adrs: [ADR-0001, ADR-0002]
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
talking about anything synthetic around it is false. `SLIA-023` removed the
synthetic LiveView option and every synthetic word from the recorded session;
this card retires the rest.

At activation (2026-09-16) the recorded path depends on the phantom path in five
places, and each has to survive the removal:

- `uc1_runner.py` imports `tissue` (only to name a phantom dataset), `spectra`
  (for `calibrate`, which `UC1_RGB` needs) and `uc1_maps` (for
  `validateMajorityVotingMap` and the refusal error).
- `envi.py` holds both the dataset writer and the reader, the SVM model file
  sizes the runner checks, and the recorded-case identification.
- `contract.DatasetRef` carries `simulated` beside `recorded`.
- `frames.py` holds the webcam source beside the synthetic one.
- `config.py` defaults to scene mode `tissue` and frame source `synthetic`.

Baseline on `main` at `0456672`: `tools/simulators/tests/run_tests.py` ran 173
tests, all passing, none skipped (the staged UC1 build is present, so the GPU
integration test ran). `config/local.json` has no `simulators` block, so no
removed setting is in use locally.

### Owner decisions, 2026-09-16

The questions the backlog card left open were answered at activation:

1. `input/` is left as it is and nothing is added for a machine without it.
   Tests that need a recorded cube read one from `input/`.
2. `run-end-to-end-session.ps1` without `-Case` refuses and names the switch.
3. The arithmetic UC1 stand-in is retired. The class-map contract check the real
   runner uses is kept.
4. The genuine UC1 integration test runs on recorded case `004-02`.
5. `SLIA-019` and `SLIA-020` move to `tasks/superseded/` with a note naming this
   card.
6. The policy text in `AGENTS.md` and `.ai/policies/medical-data-policy.md` is
   changed so synthetic data is no longer listed as allowed test data (explicit
   owner approval).

## Requirements

1. **Acquisition stand-in, recorded only.** `python -m stratum_sim acquisition`
   has one behaviour: read a recorded case, stream the laptop camera on LiveView,
   publish the case's cube on each capture. Scene modes `tissue` and `channel`,
   the `synthetic` frame source, dataset writing, the spectral-rank report and
   the switches that served them (`--scene-mode`, `--frame-source`,
   `--dataset-only`, `--dataset-folder`, `--dataset-root`, `--seed`,
   `--noise-counts`, `--frames`) are removed. `--case` is still required, from
   the command line or `config/local.json`.
2. **Configuration.** The `simulators` settings `bands`, `frameSource`,
   `sceneMode`, `seed`, `noiseCounts`, `textureFeatureCount`, `frameCount` and
   `datasetRoot` are removed, so naming one is an unknown-setting error.
   `config/local.example.json` lists what remains.
3. **Modules retired.** `tissue.py` and `uc1_sim.py` are deleted. `frames.py`
   keeps only the webcam source and `resizeFrame`. `spectra.py` keeps only UC1's
   calibration. `envi.py` keeps only reading, identification and the SVM model
   constants. `uc1_maps.py` keeps only the class-map contract check.
   `python -m stratum_sim uc1` no longer exists.
4. **Real UC1 runner, recorded only.** `uc1-real` refuses any folder that is not
   an identified recorded case, and has no switch to override that
   (`--force-unmarked` is removed). Every detail it sends is
   `real UC1 pipeline, recorded HSI case <case> (simulated acquisition)`.
5. **Scripts.** `run-uc1-simulator.ps1` is deleted.
   `run-end-to-end-session.ps1` refuses to start without `-Case` and loses
   `-MapProducer`, `-DatasetFolder` and the producer swap.
   `run-acquisition-simulator.ps1` takes a mandatory `-Case`.
   `run-uc1-real.ps1` loses `-ForceUnmarked`.
6. **Tests.** Tests of removed code are deleted. Tests that built a phantom or
   simulated dataset as a fixture use the existing recorded-case layout fixture
   (`support.writeRecordedCaseFixture`, counting placeholders) instead. The
   genuine UC1 integration test runs on recorded case `004-02`, read-only.
   `SLIAFlowTest.py` fixture detail strings use recorded wording.
7. **Documentation and cards.** `synthetic_tissue_phantom.md` is deleted. The
   documents listed under Files allowed describe only the recorded path.
   `SLIA-019` and `SLIA-020` move to `tasks/superseded/`; `SLIA-009` and
   `SLIA-021` lose their passing phantom references.
8. **Policy text.** `AGENTS.md` and `.ai/policies/medical-data-policy.md` no
   longer list synthetic data as allowed.
9. **Local generated output.** The ignored phantom datasets under
   `workspace/simulators/datasets/`, the header-only
   `workspace/simulators/foreign-dataset/` left by testing the retired writer's
   overwrite guard, and the session folders under `workspace/simulators/sessions/`
   that hold a written `dataset/` are deleted. Recorded sessions, which hold no
   dataset, stay.

Fixed from the backlog card:

- No session, command or document presents generated data as something to look
  at, and no text describes recorded data as synthetic.
- The wire origin stays `simulated`, because the acquisition is still simulated.
- The read-only guarantee over `input/` is unchanged.
- Nothing under `source/`, `apps/`, `knowledge/` or `input/` is modified.

## Out of scope

- Any change to UC1, UC2 or `AcquisitionSystemApp` in any copy.
- Any change to SLIAFlow module behaviour; only test fixture strings change.
- Rewriting completed task cards or dated review records
  (`docs/development/test_case_robustness_*.md`).
- Any behaviour change in `bmp.py`, which writes a palette image of a class map
  and generates no data. Only a comment naming the retired stand-in changes.
- The GPU run over the largest recorded cases, which the owner deferred until
  the pipeline is complete.

## Files allowed

Code:

- `tools/simulators/stratum_sim/__init__.py`
- `tools/simulators/stratum_sim/__main__.py`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/bmp.py` (comments only)
- `tools/simulators/stratum_sim/capture_client.py` (one message naming the retired
  scene mode; added during implementation)
- `tools/simulators/stratum_sim/config.py`
- `tools/simulators/stratum_sim/contract.py`
- `tools/simulators/stratum_sim/envi.py`
- `tools/simulators/stratum_sim/frames.py`
- `tools/simulators/stratum_sim/spectra.py`
- `tools/simulators/stratum_sim/tissue.py` (delete)
- `tools/simulators/stratum_sim/uc1_maps.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/stratum_sim/uc1_sim.py` (delete)
- `tools/simulators/tests/*.py` (including `uc1_client.py`, whose default mode
  waited for the retired stand-in's five device names)
- `tools/simulators/README.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py` (fixture strings only)

Scripts and configuration:

- `scripts/development/run-end-to-end-session.ps1`
- `scripts/development/run-acquisition-simulator.ps1`
- `scripts/development/run-uc1-real.ps1`
- `scripts/development/run-uc1-simulator.ps1` (delete)
- `config/local.example.json`

Documentation:

- `docs/development/synthetic_tissue_phantom.md` (delete)
- `docs/development/end_to_end_verification.md`
- `docs/development/uc1_demo_runbook.md`
- `docs/development/uc1_local_build.md`
- `docs/development/testing_strategy.md`
- `docs/development/pipeline_test_quickstart.md`
- `docs/development/camera_setup.md`
- `docs/architecture/SLIAFLOW_UC1_IMAGE_CONTRACT.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/architecture/stratum-slicer-visualization-analysis.md`
- `docs/slicer/slicer_module_architecture.md`

Tasks and policy:

- `tasks/active/SLIA-025-retire-synthetic-phantom-path.md`
- `tasks/backlog/SLIA-019-haemoglobin-absorption-valley.md` (move to `tasks/superseded/`)
- `tasks/backlog/SLIA-020-craniotomy-shaped-phantom-scene.md` (move to `tasks/superseded/`)
- `tasks/backlog/SLIA-009-demo-hardening.md`
- `tasks/backlog/SLIA-021-uc2-independent-map-producer.md`
- `AGENTS.md` (line 189, owner-approved)
- `.ai/policies/medical-data-policy.md` (owner-approved)

Ignored local output (requirement 9): `workspace/simulators/datasets/*` and the
dataset-holding folders under `workspace/simulators/sessions/`.

## Relevant skills and references

- `tasks/completed/SLIA-023-recorded-cube-acquisition-standin.md`
- `tasks/completed/SLIA-024-uc1-result-over-cube-derived-rgb.md`
- `.ai/policies/medical-data-policy.md`
- `docs/development/testing_strategy.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`

No Slicer API work: the only extension change is test fixture text, so the Slicer
skill is not required.

## Implementation plan

1. Trim the package bottom-up: `spectra`, `frames`, `envi`, `contract`,
   `uc1_maps`, `config`; delete `tissue` and `uc1_sim`; then `acquisition_sim`,
   `uc1_runner`, `__main__`, `__init__`.
2. Rework the tests: delete tests of removed code, move dataset fixtures to
   `support.writeRecordedCaseFixture`, point the GPU test at `004-02`, and add
   the refusal tests in the acceptance criteria.
3. Update the four scripts and `config/local.example.json`.
4. Update `SLIAFlowTest.py` fixture strings.
5. Delete and update documentation; supersede `SLIA-019` and `SLIA-020`; edit
   `SLIA-009`, `SLIA-021` and the policy text.
6. Run Ruff, the simulator suite, the Slicer tests, the PowerShell parser over
   the scripts, and a repository-wide search for `synthetic` and `phantom`.
7. Delete the ignored phantom datasets and dataset-holding session folders.

## Acceptance criteria

1. `stratum_sim` contains no scene, cube or map generator: `tissue.py` and
   `uc1_sim.py` are gone, and `frames`, `spectra`, `envi` and `uc1_maps` expose
   none of `SyntheticFrameSource`, `reflectanceCube`, `writeDataset`,
   `deriveMaps`.
2. `python -m stratum_sim uc1` exits 1 as an unknown simulator.
3. The acquisition stand-in refuses the removed settings and switches, and still
   refuses to start without a case.
4. The recorded capture path behaves exactly as before: every existing
   `CaptureControllerTest`, `RecordedCaptureTest`, `RecordedCaptureWireTest` and
   `AcquisitionPortTest` case passes unchanged in intent.
5. `uc1-real` refuses a folder that is not an identified recorded case, has no
   `--force-unmarked`, and names a recorded case in every detail it sends.
6. The genuine UC1 binary classifies recorded case `004-02` on the GPU and the
   case folder is unchanged afterwards.
7. The runner's existing guards - freshness, palette inverse, model size and
   band count, lock, path length, `UC1_RGB` band resolution, capture ID - pass
   against recorded-case fixtures.
8. `run-end-to-end-session.ps1` without `-Case` exits 1 with a message naming
   `-Case`; with `-Case 004-02` the recorded session runs as before.
9. The four scripts parse, and none offers a synthetic, phantom or stand-in
   option.
10. Outside history (completed cards, superseded cards, dated review records,
    this card), no file under the editable directories mentions a synthetic
    scene or phantom except where a sentence says it was retired.
11. `SLIAFlowTest` passes in Slicer with the recorded fixture strings.
12. `AGENTS.md` and the medical-data policy no longer list synthetic data as
    allowed.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | `test_contract.RetiredGeneratorsTest.test_noGeneratorRemainsInThePackage` | automated |
| 2 | `test_contract.RetiredGeneratorsTest.test_theArithmeticStandInIsNotASimulator` | automated |
| 3 | `test_config.ConfigurationTest.test_retiredSettingsAreUnknown`, `test_acquisition_sim.RetiredSwitchesTest` | automated |
| 4 | Existing recorded tests in `test_acquisition_sim.py` | automated |
| 5 | `test_uc1_runner.RecordedCaseRunnerTest` (refusal, detail, no switch) | automated |
| 6 | `test_uc1_runner.RealBinaryIntegrationTest` on `004-02` | automated (GPU) |
| 7 | Existing `test_uc1_runner.py` guard tests on recorded fixtures | automated |
| 8 | Manual steps 1 and 2 | manual |
| 9 | PowerShell parser over the four scripts; manual step 1 | automated + manual |
| 10 | Repository search recorded in Completion evidence | automated |
| 11 | `scripts/development/run-slicer-tests.ps1` | automated (Slicer) |
| 12 | Review of the diff | manual |

Tests to add or change, and how each one will be shown to fail first:

- `RetiredGeneratorsTest` is written before the modules are trimmed and fails
  on `main` because `tissue` imports and `uc1` is a simulator.
- `test_retiredSettingsAreUnknown` fails on `main`, where `sceneMode` is a
  known setting.
- The `uc1-real` refusal test fails on `main`, where `--force-unmarked` parses.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `.\scripts\development\run-end-to-end-session.ps1 -NoSlicer` with no `-Case`. | Exit 1 with a red message saying a session needs `-Case`, for example `-Case 004-02`. No producer starts. |  |
| 2 | Run `.\scripts\development\run-end-to-end-session.ps1 -Case 004-02`. In SLIAFlow connect both links, press `c`. | The UC1 map appears over the case's RGB after the capture; the banner detail reads `real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`. No key offers a producer swap. |  |
| 3 | Run `.\.venv\Scripts\python.exe -m stratum_sim uc1` with `tools\simulators` on `PYTHONPATH`. | `Unknown simulator 'uc1'`, exit 1. |  |
| 4 | Run `.\scripts\development\run-uc1-real.ps1 -DatasetFolder <any folder that is not a recorded case> -ClassifyOnly`. | Refused before the GPU runs, naming the recorded-case marker. |  |
| 5 | In Slicer, SLIAFlow module, **Reload and Test**. | All tests pass. |  |

## Risks

Deleting a module can delete a guard the recorded path still depends on. Each
guard the runner and stand-in use is listed in acceptance criteria 4 and 7 and
checked against recorded-case fixtures, not only against the tests being removed.

The GPU integration test now reads a 72 MB recorded case, so it is slower than
the phantom it replaces.

Requirement 9 deletes ignored local files that no Git operation can restore.
Only folders holding a dataset the retired writer produced are removed.

## Documentation impact

Every document under Files allowed. `synthetic_tissue_phantom.md` is deleted.

## Completion evidence

Implementation and automated testing completed on 2026-09-16 on
`feature/SLIA-025-retire-synthetic-phantom-path`. Nothing is committed. Manual
verification, review and approval are outstanding.

### Automated checks

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Baseline before any change (`main` at `0456672`) | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | `Ran 173 tests`, `OK`, none skipped | 0 |
| New tests fail on the old package | `RetiredGeneratorsTest`, `test_retiredSettingsAreUnknown`, `RetiredSwitchesTest` run against `git archive main tools/simulators/stratum_sim` | `FAILED (failures=31)` | 1 |
| New runner refusal test fails on the old package | `RecordedCaseRunnerTest.test_unidentifiedFolderIsRefusedWithNoOverride` on the same copy | `AttributeError: ... no attribute 'Uc1UnrecordedInputError'` | 1 |
| Simulator suite | `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py` | `Ran 119 tests`, `OK`, none skipped; `RealBinaryIntegrationTest` classified `004-02` on the GPU | 0 |
| Ruff | `.\scripts\development\run-python-quality.ps1` | both targets `All checks passed!` | 0 |
| SLIAFlow, headless | `.\scripts\development\run-slicer-tests.ps1 -Target Source` | `Ran 74 tests`, `OK (skipped=7)`, the headful-only tests | 0 |
| SLIAFlow, headful | `.\scripts\development\run-slicer-tests.ps1 -Target Source -Headful` | `Ran 74 tests`, `OK (skipped=1)`, the headless-only test | 0 |
| PowerShell parser | `[System.Management.Automation.Language.Parser]::ParseFile` over the three remaining scripts | 0 parse errors each | - |
| Launcher refusal | `run-end-to-end-session.ps1 -NoSlicer` | `ERROR: A session runs one recorded case of the HSI Human Brain Database. Pass -Case, for example -Case 004-02.` | 1 |
| Acquisition script refusal | `run-acquisition-simulator.ps1` | `ERROR: The acquisition stand-in publishes one recorded case. Pass -Case, for example -Case 004-02.` | 1 |
| Retired launcher parameter | `run-end-to-end-session.ps1 -MapProducer standin -Case 004-02` | `A parameter cannot be found that matches parameter name 'MapProducer'.` | 1 |
| Retired simulator | `python -m stratum_sim uc1` | `Unknown simulator 'uc1'. Choose one of: acquisition, uc1-real, capture.` | 1 |
| Runner refusal | `run-uc1-real.ps1 -DatasetFolder <recorded layout without the gtMap marker> -ClassifyOnly` | `Refusing to run UC1 on ...: it does not identify as a case of the HSI Human Brain Database ...`, printed before any origin line | 1 |
| Runner on the wire | `uc1-real input/bin/bin/004-02 --port 19945` with `uc1_client.py --port 19945` | `UC1_RGB` and `UC1_MV_CLASS` only, both `real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)`; the process was stopped afterwards | - |
| Repository search | `git grep -i -E "synthetic|phantom"` over the editable directories, excluding completed and superseded cards, dated review records and this card | 12 lines: 8 in tests asserting absence or feeding retired switches, 3 sentences saying the phantom was retired, 1 in the medical-data policy forbidding a recorded cube be called synthetic | - |

Found and fixed during implementation: `uc1-real` printed its `Origin:` line,
which names the folder as a recorded case, before refusing a folder that is not
one. The refusal now comes first (`assertRecordedCase`), with a test.

### Agent confidence pass, 2026-09-16

A second read-through found four gaps. Three were fixed in this card:

- **The launchers called a folder recorded before checking it.** `run-uc1-real.ps1`
  printed "The cube is a recorded case", and `run-end-to-end-session.ps1`
  announced "recorded case <Case>", once the folder merely existed. Both now
  check `gtMap.hdr` for the database marker first, which is the same test
  `envi.isRecordedDatabaseCase` makes, and refuse otherwise. The session also
  creates its session folder only after that check passes, so a refused session
  leaves nothing behind.
- **The policy allowed only in-memory fixtures.** The recorded-case fixtures are
  written to a temporary folder and carry the database marker.
  `.ai/policies/medical-data-policy.md` now says when that is allowed, and
  `AGENTS.md` points to it.
- **A Slicer test still named the retired stand-in.** The `SLIAFlowTest.py`
  fallback-banner fixture detail is now `unnamed test producer`. It still
  exercises the fallback wording.

| Check | Result | Exit |
| --- | --- | --- |
| Both scripts, PowerShell parser | 0 parse errors | - |
| `run-uc1-real.ps1 -DatasetFolder <unmarked layout> -ClassifyOnly` | `ERROR: Refusing ...: its gtMap.hdr does not identify it as a case of the HSI Human Brain Database.`, nothing calls it recorded before that | 1 |
| `run-end-to-end-session.ps1 -Case 004-02 -DatasetRoot <unmarked root> -NoSlicer` | same refusal; the count of session folders is unchanged at 23 | 1 |
| `run-uc1-real.ps1 -DatasetFolder input\bin\bin\004-02 -ClassifyOnly` | classified on the GPU, `Origin: simulated - real UC1 pipeline, recorded HSI case 004-02 (simulated acquisition)` | 0 |
| Simulator suite | `Ran 119 tests`, `OK` | 0 |
| Ruff | `Python quality checks passed.` | 0 |
| SLIAFlow headless / headful | `Ran 74 tests`, `OK (skipped=7)` / `OK (skipped=1)` | 0 / 0 |

The fourth gap is still open: the whole path from camera to capture, GPU and
Slicer has not been run by a person. That is manual steps 2 and 5.

### Local output removed (requirement 9)

696 MB under `workspace/simulators/datasets/` (21 marked `sim-*` datasets,
`verify-channel-demo`, and `unmarked-check-20260903-151840`, a byte copy of
`sim-20260903-151840` with its marker removed), `workspace/simulators/foreign-dataset/`,
and 11 session folders holding a marked `dataset/`. 23 session folders remain;
`session-20260913-234349` is a recorded-case session whose log names the retired
`synthetic` LiveView source, kept as a log.

### Manual verification

Not performed by the project owner yet. Steps 1, 3 and 4 were exercised by the
agent from the command line (rows above); steps 2 and 5 need Slicer and a person.

### Follow-ups, not in this card

- `SLIAFlowParameterNode.py` still describes the fallback banner in terms of the
  retired arithmetic stand-in, and shows `SIMULATED INPUT - REAL UC1 PIPELINE,
  NOT A CLINICAL RESULT` over a recorded case, whose input is recorded and whose
  acquisition is simulated. UC2 already says `SIMULATED ACQUISITION - NOT A
  CLINICAL RESULT`. Changing it is SLIAFlow module behaviour and needs its own card.
- `docs/architecture/decisions/ADR-0002-...md` and
  `docs/development/simulated_result_verification.md` name the arithmetic stand-in
  as a producer. Neither calls data synthetic; the ADR is accepted and changing it
  needs a superseding ADR.
- `build/uc1/UC1/gpu_single_bsq/source/output/` still holds UC1 output folders from
  phantom datasets (`sim-*`, `unmarked*`, `verify-channel-demo`, `dataset`). They
  are local build output and were left alone.

## Review findings

Reserved for review.

## Human approval

Proposed on 2026-09-14 under the project owner's instruction to retire the
synthetic information. Activated on 2026-09-16 under the owner's `start the new
task` instruction, with the six open questions answered by the owner the same
day, including explicit approval of the policy-text change. Review and
completion approval remain outstanding.
