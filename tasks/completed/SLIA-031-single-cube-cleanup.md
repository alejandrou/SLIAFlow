---
id: SLIA-031
title: Clean up to one cube - archive the old cases, adopt 002-04, retire the case pool
status: completed
branch: feature/SLIA-031-single-cube-cleanup
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
  `DR_DC` (1 band each) and a photo `M01.jpg`; 4.2 GB in 13 files.
- `input/bin/bin` (61 cases, 6.7 GB) and `input/bin_full_size_images/bin_12MPx.zip`
  (20 GB, 3 cases at 4096 x 3000) are no longer the working data.
- `SLIAFlowCasePool.py` exists to shuffle 61 cases, skip deferred ones and check
  each against the 93-band model. With one cube it has no job.

UC1 cannot read `002-04` until `SLIA-033`. So after this task, Capture keeps
running UC1 on the **reference case**, read through the same single-cube loader,
and the HS Cube panel keeps showing that case. `SLIA-032` puts `002-04` on screen
and `SLIA-033` makes it the cube UC1 runs on. Nothing the operator can do today
stops working in between.

### Decisions made at specification (2026-09-24)

- The project owner **accepted `ADR-0004` as written**.
- The reference case is **`020-01`**: 67 MB, 3,655 tumour pixels in its
  `gtMap`, so the ground-truth overlay has something to show (`004-02` has
  none). It is moved out of the archive, not copied.
- The `input/` layout below is confirmed. The owner considered archiving every
  case and was shown that Capture would then have nothing UC1 can run on until
  `SLIA-033`; they chose to keep `020-01`.

### Code as found

- `SLIAFlowCasePool.py`: ENVI header parsing, `loadRecordedCase` (three uint16
  BSQ pairs agree, 93 bands, file sizes, database marker in `gtMap.hdr`),
  `readCube`, `readGroundTruth`, `assertCaseUnchanged`, and the pool itself
  (`discoverCases`, `CasePool`, `DEFERRED_CASES`, `NoCompatibleCaseError`).
- `SLIAFlowLogic`: `INPUT_RELATIVE_PATH = input/bin/bin`, `inputRoot`, and a
  lazily built `casePool` that `setRunEnvironment` resets.
- `SLIAFlowWidget._startCapture` calls `casePool.nextCase()` and on
  `NoCompatibleCaseError` shows "No compatible recorded case was found in ...".
- `SLIAFlowUc1Run` imports `UC1_MODEL_BAND_COUNT`, `IncompatibleCaseError` and
  `assertCaseUnchanged` from the pool module; `SLIAFlowParameterNode` imports
  `GROUND_TRUTH_FILE_NAME`.

## Requirements

- **Accept `ADR-0004`**: status `accepted`, dated, with a Status line; add
  `superseded_in_part_by: ADR-0004` to `ADR-0003`'s front matter and a line to
  its Status section. Neither body is rewritten.
- **Update `.ai/policies/medical-data-policy.md` first**, before `002-04` is
  copied into `input/` or named by any code:
  - add `002-04` as an approved dataset: source IUMA (ULPGC), nature (in vivo
    LCTF capture provided by IUMA for this project), permission from the project
    owner and IUMA dated 2026-09-24, local location `input/002-04/`, read-only,
    never in version control, never copied into `docs/`, `workspace/` or
    published material, results on it behavioural only (`ADR-0004` decision 5);
  - record that the HSI Human Brain Database entry now covers the archive and
    the one reference case, at their new locations;
  - remove the reference to the banner and demo-mode interlock, which `ADR-0003`
    removed.
- **Reorganise `input/`** (gitignored, no Git operation involved):

  ```
  input/
    002-04/                              copy of the IUMA capture, all 13 files
    reference_hsi_brain_db/020-01/       the reference case, moved from bin/bin
    archive_hsi_brain_db_93_bands/
      bin/                               the former input/bin/bin, 60 cases
      bin_full_size_images/              the former input/bin_full_size_images
    README.txt                           what each folder is
  ```

  - `002-04` is **copied** from `Documents`; the original is not touched. Sizes
    and SHA-256 of every file are compared after the copy.
  - The archive and the reference case are **moves** inside `input/` (same
    volume, renames), with file counts and sizes recorded before and after.
  - The emptied `input/bin` folder is removed only when it is empty.
  - Nothing is deleted.
- **Replace the case pool with a single-cube loader.**
  - `SLIAFlowCasePool.py` is removed and `SLIAFlowCube.py` added. It keeps header
    parsing, `loadRecordedCase`, `readCube`, `readGroundTruth`,
    `assertCaseUnchanged` and the ground-truth constants, with docstrings that no
    longer describe a pool. `random`, `DEFERRED_CASES`, `DEFERRED_REASON`,
    `discoverCases`, `CasePool` and `NoCompatibleCaseError` go.
  - `SLIAFlowLogic` gets one setting, `cubeFolder`: by default
    `<repository>/input/reference_hsi_brain_db/020-01`
    (`CUBE_RELATIVE_PATH`), overridable by assigning a folder and reset by
    assigning `None`. `loadConfiguredCube()` reads it each Capture and raises
    `IncompatibleCaseError` naming the folder and the reason. `inputRoot`,
    `INPUT_RELATIVE_PATH` and `casePool` go.
  - The widget's refusal becomes: "The configured cube {folder} cannot be used:
    {reason}", through Slicer's translation.
- **Update tests**: remove the pool and deferred-case tests; keep the header,
  size, band-count and ground-truth tests on the new module; point fixture
  sessions at a configured fixture cube.
- **Update the documents** that name `input/bin/bin` as the working data: module
  README, UC1 demo runbook, WP5 demo plan.

## Out of scope

- Reading float32 or showing `002-04` (`SLIA-032`).
- Running UC1 on `002-04` (`SLIA-033`).
- Retiring `tools/simulators`, `scripts/development/run-uc1-real.ps1` and the
  session scripts (`SLIA-028`). They still default to `input/bin/bin` and will
  stop finding it; that breakage is expected and recorded, not fixed here.
- Historical task cards and their evidence, which keep the paths of their time.
- A user-interface control for the cube folder.
- Deleting any data. The archive is kept.

## Files allowed

- `.ai/policies/medical-data-policy.md`
- `docs/architecture/decisions/ADR-0003-integrated-capture-and-uc1-in-slicer.md` (front matter and Status only)
- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md` (front matter and Status only)
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCasePool.py` (removed)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowCube.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py` (import and one comment; added at specification because it imports the pool module)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/README.md`
- `docs/architecture/WP5_MS5_DEMO_PLAN.md`
- `docs/development/uc1_demo_runbook.md`
- `tasks/{backlog,active,review,completed}/SLIA-031-single-cube-cleanup.md`
- `input/` (gitignored data layout and `input/README.txt`; never staged)

## Relevant skills and references

- `docs/architecture/decisions/ADR-0004-iuma-lctf-cube-and-acquisition-app.md`
- `docs/hardware/acquisition_app_and_hardware.md`, sections 3.4, 7 and 8
- `tasks/completed/SLIA-027-integrated-slicer-capture-uc1.md`
- Slicer skill: not needed beyond the existing patterns; the setting is a plain
  logic attribute, not a parameter-node field, so no saved scene carries a
  machine-specific path.

## Implementation plan

1. Accept `ADR-0004`; update the medical-data policy.
2. Reorganise `input/` and record the before and after listing, with sizes.
3. Write the new and changed tests and observe them failing against the pool.
4. Replace the pool; adapt logic, widget, UC1 run import and CMake list.
5. Update the documents; run Ruff and the full Slicer test suite, headless and
   headful.

## Acceptance criteria

1. The medical-data policy approves `002-04` with its conditions, dated, and the
   approval is written before `002-04` is copied or named by code.
2. `input/` matches the agreed layout, `002-04` in `Documents` is unchanged, the
   copy matches it file by file, and no data file is tracked by Git.
3. Capture reads exactly the configured cube folder, every time, and by default
   that folder is `input/reference_hsi_brain_db/020-01`.
4. A configured cube folder that is missing or inconsistent is refused with a
   message naming the folder and the reason, and no UC1 run starts.
5. The module has no case pool, no shuffling and no deferred-case list.
6. The header, size, band-count and ground-truth checks behave as before.
7. Capture on the reference case in the built application works as before: five
   outputs, provenance and ground-truth overlay.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Policy approves `002-04` first | Manual step 1 | manual |
| 2. `input/` layout, copy intact, nothing tracked | Manual step 2 (with the listing and hashes recorded in Completion evidence) | manual |
| 3. Capture reads exactly the configured cube; default is the reference case | `SLIAFlowTest.test_captureUsesTheConfiguredCube` | automated |
| 4. Missing or inconsistent cube refused with folder and reason | `SLIAFlowTest.test_configuredCubeIsRefusedWithItsReason`, `test_cubeRefusalReasonsAreTranslated`, `test_surfacedFailureMessagesAreTranslated` | automated |
| 3 and 4. A cube folder set in one run environment does not carry into the next | `SLIAFlowTest.test_runEnvironmentChangeRestoresTheDefaultCube` | automated |
| 5. No pool, shuffle or deferred list | `SLIAFlowTest.test_moduleHasNoCasePool` | automated |
| 6. Header, size, band-count and ground-truth checks unchanged | `SLIAFlowTest.test_cubeFolderRejectsIncompatibleContents`, `test_cubeReadingDoesNotWriteToInput`, `test_groundTruthIsReadTopRowFirst`, `test_groundTruthIsRefusedRatherThanReshaped`, `test_groundTruthReadingDoesNotWriteToInput`, `test_caseChangedOnDiskIsRefusedRatherThanRunOn` | automated |
| 7. Capture on the reference case in the built app | Manual step 3 | manual |

Tests to add or change, and how each one will be shown to fail first:

- `test_captureUsesTheConfiguredCube` (new): a fixture repository with the
  configured cube folder and other case folders beside it; two Captures both run
  UC1 on the configured folder, and the default `cubeFolder` is
  `<root>/input/reference_hsi_brain_db/020-01` (authority: owner decision at
  specification). Fails against the pool: `SLIAFlowLogic` has no `cubeFolder`.
- `test_configuredCubeIsRefusedWithItsReason` (new): a missing folder and a
  folder with a truncated `raw.dat`; the status label names the folder and the
  reason, no process is created, and LiveView resumes. Fails against the pool,
  which reports "No compatible recorded case" without naming a reason.
- `test_moduleHasNoCasePool` (new): `SLIAFlowCasePool` cannot be imported, the
  logic has no `casePool`, and `SLIAFlowCube` defines no `CasePool`,
  `discoverCases`, `DEFERRED_CASES` or `NoCompatibleCaseError`. Fails against
  the pool module, which imports.
- `test_cubeFolderRejectsIncompatibleContents` and `test_cubeReadingDoesNotWriteToInput`
  replace `test_casePoolRejectsIncompatibleFolders` and
  `test_casePoolDoesNotWriteToInput` without the `discoverCases` and pool parts.
  Their defects and expectations are unchanged, so they fail first only in the
  sense that `SLIAFlowCube` does not exist yet (recorded).
- `test_casePoolExcludesDeferredCases` and
  `test_casePoolUsesEachCaseOnceThenReshuffles` are removed.
- The ground-truth, UC1-run and capture-session tests change only which module
  they import and where the fixture cube lies.
- `test_resultOfAnotherSizeIsFittedToTheView` gets its wider second cube by
  replacing the configured cube on disk, since there is no pool to refill.
- `test_surfacedFailureMessagesAreTranslated` checks the new refusal instead of
  "No compatible recorded case".

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Read the diff of `.ai/policies/medical-data-policy.md` and the Completion evidence order of operations | `002-04` is listed as approved, dated 2026-09-24, with its conditions; the evidence shows the policy edit made before the copy into `input/` | Verified 2026-09-24: the diff adds the dated approval and its conditions; the recorded order places the policy edit before the `input/002-04` copy. |
| 2 | Open `input/` in Explorer and read `input/README.txt`; run `git status --short --ignored input` | `002-04`, `reference_hsi_brain_db\020-01`, `archive_hsi_brain_db_93_bands\bin` (60 cases) and `archive_hsi_brain_db_93_bands\bin_full_size_images`, plus `README.txt`; `Documents\002-04\002-04` still has its 13 files; git lists only `!! input/` | Verified 2026-09-24: the layout and README matched; the archive had 60 cases and 480 case files, the reference had 8 files, the source/copy each had 13 files and 4,419,916,007 bytes, all 13 SHA-256 hashes matched, and Git reported only `!! input/`. |
| 3 | Run `.\scripts\development\build-sliaflow.ps1 -Launch`; in SLIAFlow press Start, then Capture twice, waiting for each result; select `svm.bmp`, then `gtMap` | Each run's status names recorded case `020-01`; five outputs listed; `gtMap` draws labels (red tumour pixels among them) over `svm.bmp` | Verified 2026-09-24: the build/launch completed with exit 0; Start displayed a live camera frame; both Captures completed for `020-01`, exposed `pca.bmp`, `svm.bmp`, `knn.bmp`, `kmeans.bmp`, and `imageRGB.bmp`, and resumed LiveView. Selecting `svm.bmp` then `gtMap` visibly showed the ground-truth overlay, including red labelled regions. |
| 4 | Close the app, rename `input\reference_hsi_brain_db\020-01` to `020-01.off`, relaunch, Start, Capture; then rename it back | The status says the configured cube `...\input\reference_hsi_brain_db\020-01` cannot be used because it is not a folder; LiveView resumes; no UC1 process starts | Verified 2026-09-24: the status named the configured folder and said it was not a folder; capture ended, LiveView resumed, `currentRun` stayed `None`, and no output nodes were created. The folder was restored to `020-01`. |

## Risks

- Moving 27 GB can fail halfway. Both moves are renames on the same volume, and
  counts and sizes are compared before and after; 398 GB are free for the
  4.2 GB copy.
- The standalone tools and `run-uc1-real.ps1` stop finding `input/bin/bin`.
  That is intended; `SLIA-028` retires them.
- Removing `SLIAFlowCasePool.py` deletes a tracked file. It is listed here and
  was included in the owner-authorized WIP commit.

## Documentation impact

Medical-data policy, `ADR-0003` status, `ADR-0004` status, module README, UC1
demo runbook, WP5 demo plan.

## Completion evidence

Implementation, 2026-09-24, on `feature/SLIA-031-single-cube-cleanup`. Saved as
the branch's single evolving WIP commit after the automated checks passed.

### Order of operations (acceptance criterion 1)

1. `ADR-0004` accepted and `ADR-0003` marked superseded in part.
2. Medical-data policy edited: `002-04` approved, HSI Human Brain Database entry
   moved to the new locations, banner and demo-mode interlock wording removed,
   heading "Explicitly Approved Public Medical Data" renamed "Explicitly
   Approved Medical Data" because `002-04` is not public. Finished 10:28.
3. Only then was `002-04` copied into `input/`; no code names it (only
   `input/README.txt` and the documents do).

### `input/` reorganisation (acceptance criterion 2)

| | Before | After |
| --- | --- | --- |
| `input/bin/bin` | 61 cases, 488 files, 7,117,363,741 bytes | gone (empty `input/bin` removed) |
| `reference_hsi_brain_db/020-01` | - | 8 files, 69,856,641 bytes |
| `archive_hsi_brain_db_93_bands/bin` | - | 60 cases, 480 files, 7,047,507,100 bytes |
| `archive_hsi_brain_db_93_bands/bin_full_size_images` | 1 file, 20,643,852,167 bytes (as `input/bin_full_size_images`) | same file, same size |
| `002-04` | - | 13 files, 4,419,916,007 bytes |

- 480 + 8 = 488 files and 7,047,507,100 + 69,856,641 = 7,117,363,741 bytes.
- `sha256sum -c` of the copy against the source: 13 of 13 `OK`.
- After all work, the source `Documents\002-04\002-04` still passes the same
  `sha256sum -c`, and its names, sizes and modification times equal those
  recorded before the copy.
- `git ls-files input` lists 0 files; `git status --short --ignored input`
  prints only `!! input/`.
- The new loader, run outside Slicer on the real reference case:
  `RecordedCase(name='020-01', samples=330, lines=378, bands=93)`, ground-truth
  classes `{0: 115105, 1: 1842, 2: 3655, 3: 1513, 4: 2625}`,
  `assertCaseUnchanged` passes. The longest input path UC1 opens,
  `C:\stratum\input\reference_hsi_brain_db\020-01\whiteReference.dat`, is 65
  characters (UC1 limit 127).

### Tests observed failing first

Run 1: the tests against the unchanged module. Every test that uses a fixture
failed with `ModuleNotFoundError: No module named 'SLIAFlowLib.SLIAFlowCube'`,
including `test_cubeFolderRejectsIncompatibleContents` and
`test_cubeReadingDoesNotWriteToInput`.

Run 2: the same tests with `SLIAFlowCube.py` added as an unchanged copy of
`SLIAFlowCasePool.py`, production code untouched (`Ran 73 tests`, `FAILED
(failures=26, errors=10, skipped=9)`; many of those come from `RecordedCase`
objects of the two module copies never comparing equal):

- `test_captureUsesTheConfiguredCube`: `AssertionError: None != WindowsPath('C:/Users/ALEJAN~2/AppData/Lo[72 chars]-01')`
  -- the logic has no default cube folder.
- `test_configuredCubeIsRefusedWithItsReason` (missing and inconsistent):
  `AssertionError: '...\input\reference_hsi_brain_db\absent' not found in 'Failed: No compatible recorded case was found in ...\input\bin\bin. Put the HSI Human Brain Database cases there; ...'`
- `test_moduleHasNoCasePool`: `AssertionError: ModuleNotFoundError not raised`.
- `test_cubeFolderRejectsIncompatibleContents` and
  `test_cubeReadingDoesNotWriteToInput` passed, as they should: they keep the
  pool module's checks unchanged.

The copy was deleted before the implementation.

### Checks after implementation

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| Ruff | `.\scripts\development\run-python-quality.ps1` | `extensions/SLIAFlow/SLIAFlow` 9 files and `tools/simulators` 28 files, all checks passed | 0 |
| Slicer tests, headless | `.\scripts\development\run-slicer-tests.ps1` | module loaded from `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`; `Ran 73 tests`, `OK (skipped=9)` | 0 |
| Slicer tests, headful | `.\scripts\development\run-slicer-tests.ps1 -Headful` | `Ran 73 tests`, `OK (skipped=1)`, the one skip being `test_headlessPresentationFallback` | 0 |
| Launcher refresh | `.\scripts\development\build-sliaflow.ps1` | every module file `ok`, including `SLIAFlowCube.py`; `SLIAFlowCasePool.py` no longer deployed; "The build tree matches the working tree." | 0 |
| Whitespace | `git diff --check` | no output | 0 |

The first green attempt failed 30 tests with `Uc1RunError: The path
...\input\reference_hsi_brain_db\004-02/darkReference.dat is 129 characters`:
the fixture temp folder `sliaflow-test-fixture-*` plus the longer folder name
passed UC1's 127-character limit. The fixture prefix became `slia-fx-`; no
module code changed for it.

### Other changes worth knowing

- `SLIAFlowUc1Run.py` was added to `Files allowed` at specification because it
  imported the pool module.
- `assertCaseUnchanged` now says "changed on disk since Capture was pressed".
  The test asserts only "changed on disk".
- `test_resultOfAnotherSizeIsFittedToTheView` now replaces the configured cube
  on disk with a wider one, since there is no pool to refill.

### Pre-review findings addressed (2026-09-24)

An informal review of the uncommitted change raised five points. This is not
the independent review stage; `Review findings` below stays for that.

1. Manual verification missing: correct, still an owner action (see Not done).
2. Data evidence not independently verified. Re-checked from scratch:
   - SHA-256 of all 13 files in `Documents\002-04\002-04` recomputed and compared
     with `input\002-04`: 13 of 13 equal, 4,419,916,007 bytes on each side.
   - Source modification times are all 2026-09-23 13:12:56Z-13:13:23Z, the day
     before this task; the copies were created 2026-09-24 09:29:20Z-09:29:26Z.
   - Order, from the session transcript's timestamps: the policy edit adding
     `### IUMA LCTF capture 002-04` at 09:28:29.958Z, the copy command at
     09:29:09.303Z. No policy edit follows the copy.
   - Recount: `archive_hsi_brain_db_93_bands` 481 files, 27,691,359,267 bytes
     (480 case files, 7,047,507,100 bytes, plus the 20,643,852,167-byte zip);
     `020-01` 8 files, 69,856,641 bytes; `input\bin` absent; `git ls-files
     input` lists 0 files.
3. Refusal reasons were not translated, only the "The configured cube ...
   cannot be used" sentence around them. Every `IncompatibleCaseError` message
   in `SLIAFlowCube.py` now goes through `_()`, with the same fallback import as
   `SLIAFlowUc1Run.py`; the English text is unchanged. An `OSError`'s own text
   comes from the operating system and is still inserted as is.
4. `setRunEnvironment` kept a cube folder chosen in the previous environment.
   It now restores the new environment's reference case.
5. Nothing committed, the card in `active`: the owner authorized the Git work.
   The branch holds one task commit, amended to its final subject when the card
   moved to `completed`.

Failing first (headless, `Ran 75 tests`, `FAILED (failures=3, skipped=9)`):

- `test_cubeRefusalReasonsAreTranslated` (new): `Lists differ: [112, 116, 122,
  ...] != [] : Refusals raised without _() at these lines`.
- `test_runEnvironmentChangeRestoresTheDefaultCube` (new):
  `WindowsPath('.../slia-fx-aun84swf/input/elsewhere') !=
  WindowsPath('.../slia-fx-57t1vc29/input/reference_hsi_brain_db/020-01')`.
- `test_surfacedFailureMessagesAreTranslated` (subtest `configured cube
  refused`, now also requiring the reason to be translated): `'[translated]
  ...\004-02 is not a folder' not found in 'Failed: [translated] The configured
  cube ...'`.

After the fix:

| Check | Result | Exit |
| --- | --- | --- |
| `run-python-quality.ps1` | all checks passed | 0 |
| `run-slicer-tests.ps1` | `Ran 75 tests`, `OK (skipped=9)` | 0 |
| `run-slicer-tests.ps1 -Headful` | `Ran 75 tests`, `OK (skipped=1)` | 0 |
| `build-sliaflow.ps1` | `ok  SLIAFlowLib\SLIAFlowCube.py`, all files ok | 0 |
| `git diff --check` | no output | 0 |

### Manual verification completed (2026-09-24)

Steps 1-4 were performed and their observed results are recorded in the table above. No SLIA-031-specific issue was found.

### Not done

- `tools/simulators` defaults, `run-uc1-real.ps1` and the session scripts still
  name `input/bin/bin`; they break as expected until `SLIA-028`.

## Review findings

The one review of this task is the one the project owner supplied on
2026-09-24, run on the change before it was committed. It found no
high-severity functional defect and raised five points; each one and what was
done about it is under `Pre-review findings addressed` in Completion evidence.
In short: the two code findings (untranslated refusal reasons, a cube folder
surviving a run-environment change) were fixed test-first; the data-migration
evidence was recomputed and held; manual verification was then performed by
the owner; the Git and lifecycle state is resolved by this completion. No
second review was run after those fixes; the owner moved the task to
completed without one.

## Human approval

Approved and marked completed by the project owner on 2026-09-24, after manual
steps 1-4 passed. The task commit on `feature/SLIA-031-single-cube-cleanup` is
`ENH: Run every capture on one configured cube`; integrating it into `main`
awaits separate authorization.
