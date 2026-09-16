---
id: SLIA-021
title: Run UC2 blood-vessel enhancement inside Slicer on the LCTF cube
status: active
branch: feature/SLIA-021-uc2-independent-map-producer
priority: low
depends_on: SLIA-033
required_skills: [slicer]
optional_tools: []
related_adrs: [ADR-0003, ADR-0004]
---

# SLIA-021 - Run UC2 blood-vessel enhancement inside Slicer on the LCTF cube

## Goal

Every Capture runs the vendored UC2 blood-vessel enhancement on `002-04`, IUMA's
calibrated float32 LCTF cube, as a background process beside UC1, and shows its
map in the Enhanced Vascularization panel, which is black and reserved today.
UC2 changes are versioned patches applied at staging, each documented with its
result, as UC1's are. The enhancement code itself is not changed.

## Context

*Scheduled by the project owner on 2026-10-05.* The card was parked at low
priority since 2026-09-24. The owner ran UC2 on `002-04` in a standalone copy of
the component and made three changes there so it reads the calibrated cube.
They asked for those changes to be brought into this project so the map can be
shown in Slicer, without touching the enhancement algorithm. If UC2's authors
later adopt equivalent changes, the vendored copy is updated to their commit and
these patches are deleted (`docs/development/uc2_changes.md`, *Retiring the
patches*).

The owner's three changes, as reported (2026-10-05):

1. `params.c`: if the dataset folder has `LCTF_Calibrated_Cube_Single.hdr`, use
   it and its `.dat` instead of `raw.hdr` and `raw.dat`.
2. `functions.h`, `functions.c`: `read_selected_bands_BSQ_float`, reading only
   the three needed bands of a float32 BSQ cube, in the order blue, green, red.
3. `main.c`: `case 4` (float32) in the data-type switch, reading bands 4, 16
   and 50 (480, 540, 710 nm on the 460-1000 nm grid), no calibration, the same
   fixed parameters as `case 12`, and the same PNG writer.

The owner reported that the result was 1080 x 1080 and pixel-identical to their
own Python replica, and that `BV_enhancement.c`, `png_writer.c` and
`hdr_reader.c` were not changed. They also replaced `getline` with `fgets` in
their copy for the UCRT64 GCC; that is not needed here, because
`build-uc2.ps1` builds with the MSYS2 POSIX-layer GCC, which has `getline`.

What the repository had on this branch before this work (WIP commit
`1d73f1c`, 2026-09-16): `scripts/development/build-uc2.ps1`, which staged and
built UC2 unchanged and asserted the staged sources byte-identical to the
vendored ones, and `docs/development/uc2_local_build.md`, which recorded that
build and the Python runner `SLIA-028` has since retired.

Findings kept from the original card (checked 2026-09-11 and 2026-09-24):

- The component (`workspace/components/blood_vessels_enhancement`, partner
  commit `1b5e9ae`) takes one argument, the dataset folder, and writes
  `<folder name>-BVMap.png` into its working directory.
- `high_in = 0.15`, `high_out = 0.8`, `gamma = 1`, `bValue = 3` and the band
  indices are local variables in `main()`; they cannot be set from outside.
- It writes only the PNG, normalised per channel within each image, so two
  captures cannot be compared by colour.
- The enhancer channel is calibrated plane 0, the blue band, while the comment
  says red. Reported to the authors, not changed.
- `main.c` reads any data type other than 12 through a `default:` branch that
  reads uint16, calibrates against references and never writes the map. The
  unpatched build on `002-04` exits 1 with `Failed to open file`, because the
  folder has no `raw.hdr`.

ADR fit. `ADR-0004` decision 3 sets the patch-at-staging mechanism for UC1. This
card applies the same mechanism to UC2, as the card's Requirements already
planned on 2026-09-24, on the owner's instruction of 2026-10-05. The run inside
Slicer, as a background process with no network hop, follows `ADR-0003`
decision 1 as UC1's does. Provenance follows `ADR-0004` decision 7; the result
is behavioural only, as decision 5 says for UC1.

## Requirements

1. The owner's three changes are two versioned patches in
   `scripts/development/uc2-patches/`, transcribed unchanged (comments
   included), applied by `build-uc2.ps1` at staging with `git apply`. The
   vendored copy stays untouched and is checked to be at `1b5e9ae` with no
   tracked change.
2. `build-uc2.ps1` fails when a patch does not apply, when the compiler's
   warnings differ from the recorded set, or when the staged sources differ
   from a fresh copy of the vendored sources plus the patches.
3. A repeatable check (`check-uc2.py`) shows: on `002-04` the patched build
   writes a 1080 x 1080 PNG pixel-identical to an independent NumPy replica of
   UC2's own steps on the bands at 480, 540 and 710 nm; on the reference case
   `020-01` (uint16 with references) its PNG is byte-identical to the unpatched
   build's; a calibrated cube too short for band 16 is refused.
4. Capture starts UC2 on the configured cube as a background `QProcess` with no
   shell, a 30 s timeout and its own lock, and runs UC1 as before. Each run's
   refusal or failure is reported on its own panel and status line and never
   fails, stops or changes the other.
5. Before UC2 starts, the run is refused, with the reason, when the cube changed
   since Capture, when its files are not `LCTF_Calibrated_Cube_Single.hdr` and
   `.dat`, when its bands 4, 16 or 50 are not 480, 540 or 710 nm within
   0.01 nm, when the binary or `msys-2.0.dll` is not staged, when a path is too
   long for UC2's buffers, or when the lock is held.
6. After UC2 exits, the run fails on a non-zero exit, a crash, a timeout, any
   of UC2's error lines on either stream whatever the exit code, or a missing,
   stale, undecodable or wrongly sized PNG.
7. A valid map is shown alone in Enhanced Vascularization, upright and
   unmirrored, pixels as UC2 wrote them, named `002-04-BVMap.png`, with the
   caption `Enhanced vascularization for recorded cube 002-04`. It is never
   shown in another panel.
8. The map node carries `SLIAFlow.DataOrigin = simulated`, the cube, the capture
   ID, the detail `real UC2 blood-vessel enhancement, recorded IUMA LCTF
   capture 002-04, calibrated by IUMA (simulated acquisition)` and the fixed
   bands and parameters. A Status line states the parameters, that the map is a
   display enhancement whose colours are not comparable between captures, and
   that it is not validated.
9. A new Capture removes the previous map until its own arrives. LiveView
   resumes and Capture is enabled again only when both UC1 and UC2 have
   finished. Cancelling (scene close, module exit, Reload, quit) kills UC2 and
   releases its lock.
10. Without a UC2 build the panel says the enhanced vascularization could not be
    computed, the Status line names `build-uc2.ps1`, and UC1 behaves exactly as
    before.

## Out of scope

- Changing `BV_enhancement.c`, `png_writer.c` or `hdr_reader.c`, or the fixed
  parameters, or correcting the blue-band enhancer.
- Making the parameters settable from SLIAFlow.
- Replacing `getline` (the build already works with the MSYS2 GCC).
- Comparing UC1 and UC2 outputs, or either against a ground truth.
- Deciding the consortium's output form for UC2, or receiving a UC2 map over
  OpenIGTLink (`SLIA-030`).
- Editing `input/README.txt` (gitignored data folder).

## Files allowed

- `scripts/development/uc2-patches/.gitattributes` (new)
- `scripts/development/uc2-patches/0001-calibrated-cube-path.patch` (new)
- `scripts/development/uc2-patches/0002-calibrated-float32-input.patch` (new)
- `scripts/development/build-uc2.ps1`
- `scripts/development/check-uc2.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc2Run.py` (new)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py` (log label of
  the shared `OwnedProcess` only)
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/README.md`
- `docs/development/uc2_changes.md` (new)
- `docs/development/uc2_local_build.md`
- `tasks/active/SLIA-021-uc2-independent-map-producer.md`

## Relevant skills and references

- `workspace/components/blood_vessels_enhancement/main.c`, `params.c`,
  `functions.c`, `BV_enhancement.c`, `png_writer.c`, `hdr_reader.c`
- `scripts/development/build-uc1.ps1` (patch application), `check-uc1.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowUc1Run.py`
- `docs/development/uc1_changes.md`
- `.ai/policies/algorithm-boundary-policy.md`, `.ai/policies/medical-data-policy.md`

## Implementation plan

1. Apply the owner's changes to a scratch copy of the CRLF working-tree
   sources with a script (byte-exact), and take the patches from a scratch Git
   repository: `params.c` as 0001; `functions.h`, `functions.c` and `main.c` as
   0002.
2. `build-uc2.ps1`: stage, apply the patches as `build-uc1.ps1` does (from the
   repository root, `core.autocrlf` off, a skipped patch is a failure), build,
   check warnings (the unused `BVMap` moves to `main.c:196`), and compare the
   staged sources with a fresh vendored copy plus the patches.
3. `check-uc2.py`: the three checks of requirement 3, recording the unpatched
   build's `020-01` hash as the oracle.
4. `SLIAFlowUc2Run.py`: `Uc2Build`, `Uc2Run` and the PNG reader, reusing UC1's
   `OwnedProcess`.
5. Logic: `startUc2Run`, `cancelRun` cancelling both, the map node with its
   provenance.
6. Widget: start UC2 before UC1 at Capture; end the capture when both are done;
   bind the map, caption and messages; the new Status line; forget the map on
   new capture, exit, cleanup and scene close.
7. Tests, README and the two UC2 documents.

## Acceptance criteria

1. `build-uc2.ps1 -Clean` exits 0 with both patches applied, exactly the four
   recorded warnings, and the staged sources equal to the vendored copy plus
   the patches; the vendored copy is unchanged.
2. `check-uc2.py` exits 0: `002-04` pixel-identical to the replica, `020-01`
   identical to the unpatched build, the short cube refused.
3. UC2 is started with the cube folder as its only argument, `build/uc2/run` as
   working directory, no shell, and holds its lock for the run; a previous map
   is cleared first and nothing is written into the cube's folder.
4. Each pre-run defect of requirement 5 refuses the run with its reason, starts
   no process and leaves no lock.
5. Each post-run failure of requirement 6 fails the run with its reason, and a
   valid map is returned pixel for pixel.
6. The PNG is read top row first; a PNG of another size or not a PNG is refused.
7. After Capture the map node holds UC2's pixels, upright, named
   `002-04-BVMap.png`, with the provenance and parameters of requirement 8, and
   the Status line says what requirement 8 says.
8. The capture ends only when both runs have finished, in either order.
9. A UC2 failure or a missing UC2 build leaves UC1's result and status as
   before; a UC1 failure leaves UC2's map.
10. Cancelling the capture kills UC2 and releases its lock.
11. The map reaches Enhanced Vascularization only, with its caption and no
    waiting text, and a new Capture takes it down until its own arrives.
12. In Slicer, on the real build and cube, Capture shows the vessel map beside
    UC1's result, the same way up as the PNG UC2 wrote.
13. The existing test suite still passes.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | `build-uc2.ps1 -Clean`; manual step 1 | automated |
| 2 | `check-uc2.py`; manual step 2 | automated |
| 3 | `SLIAFlowTest.test_uc2RunsTheStagedBuildOnTheCubeFolder` | automated |
| 4 | `SLIAFlowTest.test_uc2PreRunChecksRefuseBeforeStarting` | automated |
| 5 | `SLIAFlowTest.test_uc2RunFailsOnExitCodeErrorLineOrMissingMap` | automated |
| 6 | `SLIAFlowTest.test_uc2MapIsReadTopRowFirstAndChecked` | automated |
| 7 | `SLIAFlowTest.test_captureShowsTheVascularMapAlongsideUc1` | automated |
| 8 | `SLIAFlowTest.test_captureShowsTheVascularMapAlongsideUc1` (both orders) | automated |
| 9 | `SLIAFlowTest.test_uc2FailureOrRefusalLeavesUc1Alone` | automated |
| 10 | `SLIAFlowTest.test_cancellingTheCaptureKillsUc2AndReleasesItsLock` | automated |
| 11 | `SLIAFlowTest.test_vascularMapReachesItsPanelAndNowhereElse` (headful) | automated |
| 12 | Manual steps 3 to 8 | manual |
| 13 | `run-slicer-tests.ps1`, headless and `-Headful` | automated |

Tests to add or change, and how each one is shown to fail first:

- The seven `SLIAFlowTest` tests above are new. Before this work
  `SLIAFlowUc2Run` did not exist and the widget had no `vascularStatusLabel`,
  `vascularMapNode` or `_forgetVascularMap`, so each fails at its first use of
  them. A separate fail-first run against the old code was not made.
- `_captureSession` gains `uc2=False`; without it no UC2 build is staged, UC2 is
  refused before a process exists, and every existing capture test sees the
  same processes as before.
- `check-uc2.py` is new. Against the unpatched build its first check fails
  (exit 1, `Failed to open file`, no PNG), recorded in `uc2_changes.md`.

## Manual verification

Procedure: `.ai/workflows/manual-verification-workflow.md`.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | `.\scripts\development\build-uc2.ps1 -Clean` | Exit 0; `applied 0001-...` and `applied 0002-...`; four warnings `present`, none `UNEXPECTED`; `All 13 staged source(s) equal ... plus 2 patch(es)` | Codex run: exit 0; both patches, four expected warnings, 13 staged sources matched. |
| 2 | `.\.venv\Scripts\python.exe scripts\development\check-uc2.py` | `PASS`; `002-04-BVMap.png 1080 x 1080, identical to the NumPy replica` | Codex run: exit 0; 002-04 matched pixel for pixel, 020-01 matched the unpatched build, short cube refused. |
| 3 | Start Slicer with SLIAFlow (Reload, or the built launcher after `build-sliaflow.ps1`), open SLIAFlow | Enhanced Vascularization is black and reads `Waiting for enhanced vascularization.`; the last Status line reads `No enhanced vascularization yet. Press Capture.` | Codex observed both messages and a black panel in the built launcher's headful window. |
| 4 | Press Start, then Capture | Within a few seconds Enhanced Vascularization shows the vessel map with `Enhanced vascularization for recorded cube 002-04` at the bottom; Tumour Delineation shows UC1's result as before; LiveView resumes | Codex observed both panels with a placeholder frame, then repeated Start and Capture with laptop camera 0: a frame arrived, real UC1 and UC2 finished, and LiveView resumed. |
| 5 | Read the last Status line | Names `002-04`, `simulated acquisition`, bands 480, 540, 710 nm and `high_in 0.15, high_out 0.8, gamma 1, bValue 3`, says colours are not comparable between captures and `Not validated` | Codex observed every named phrase in the visible Status line. |
| 6 | Open `build\uc2\run\002-04-BVMap.png` in an image viewer and compare with the panel | Same picture, same way up, not mirrored | Codex visually compared the PNG and a Slicer screenshot; the map volume also matched the PNG's 1080 x 1080 RGB pixels exactly. |
| 7 | Press Capture again and watch Enhanced Vascularization | The map is replaced by the waiting text, then the new map appears | Codex observed the old map removed, waiting text restored, and a new map after the second run. |
| 8 | Rename `build\uc2\source\uc2_bvmap.exe` to `uc2_bvmap.off`, press Capture, then rename it back | UC1's result appears as usual; Enhanced Vascularization reads `The enhanced vascularization could not be computed.`; the Status line says `uc2_bvmap.exe is not in ...` and names `build-uc2.ps1` | Codex observed the refusal, no UC2 lock, and UC1's result; the executable was restored. |
| 9 | Close Scene | Enhanced Vascularization is black with the waiting text; the Status line reads `No enhanced vascularization yet. Press Capture.` | Codex observed the waiting panel and Status line after scene clear; map node gone. |
| 10 | Developer section: Reload and Test | All tests pass | The first headful run hung in an existing Connections test and was stopped. A redirected rerun of Reload and Test passed: 119 tests, one skipped, exit 0. |

## Risks

- A wrapper that silently corrects an algorithm produces results nobody can
  trace. Every change to UC2 is a documented patch, transcribed from the owner's
  copy unchanged, and the blue-band enhancer goes to the authors rather than
  being fixed here.
- The band indices are fixed in patch 0002. A cube on another grid would be
  enhanced on the wrong bands without error; SLIAFlow refuses it before UC2
  starts, but `check-uc2.py` and the refusal are the only guards.
- The map looks like a result. The panel caption names the cube, and the Status
  line, the node detail and the README say it is a display enhancement, not
  comparable between captures, and not validated.
- `check-uc2.py` also reads the reference case `020-01`, so far used only for
  the UC1 check. The owner and IUMA permit any data in `input/` (`ADR-0004`).

## Documentation impact

`docs/development/uc2_changes.md` (new), `docs/development/uc2_local_build.md`,
`extensions/SLIAFlow/README.md`. `input/README.txt` (gitignored, not edited)
still says only HS Cube and UC1 read `002-04`.

## Completion evidence

Implementation and automated tests, 2026-10-05, on
`feature/SLIA-021-uc2-independent-map-producer` (branch already existed, WIP
commit `1d73f1c`). Nothing committed.

| Check | Command | Result | Exit |
| --- | --- | --- | --- |
| UC2 build | `.\scripts\development\build-uc2.ps1 -Clean` | vendored `1b5e9ae`, 0 tracked changes; 2 patches applied; warnings `main.c:196`, `hdr_reader.c:50`, `:102`, `:109` present, none unexpected; 13 staged sources equal vendored plus patches; binary 417,718 bytes | 0 |
| UC2 patches | `.\.venv\Scripts\python.exe scripts\development\check-uc2.py` | `002-04` 1080 x 1080 identical to the replica (0.22 s); `020-01` identical to the unpatched build `C1C7B940...`; short cube refused, `Error reading band 16`, no PNG; `PASS` | 0 |
| Unpatched UC2 on `002-04` | built by hand from the vendored sources in `build\uc2-unpatched` | `Failed to open file`, no PNG | 1 |
| Python quality | `.\scripts\development\run-python-quality.ps1` | ruff: all checks passed | 0 |
| Lint, scripts | `.venv\Scripts\ruff.exe check scripts\development\check-uc2.py` | all checks passed | 0 |
| Slicer, Source, headless | `.\scripts\development\run-slicer-tests.ps1` | 119 run in 20.1 s, OK, 17 skipped (the window-only tests, including `test_vascularMapReachesItsPanelAndNowhereElse`) | 0 |
| Slicer, Source, headful | Slicer launched as `run-slicer-tests.ps1 -Headful` does, tests run through a script logging each test to a file | 119 run in 41.8 s, OK, 1 skipped (`test_headlessPresentationFallback`); `test_vascularMapReachesItsPanelAndNowhereElse` ran and passed | 0 |

**An intermittent hang that predates this card.** Two runs through
`run-slicer-tests.ps1` (one headless, one `-Headful`) and one headful rerun
under a watchdog stopped making progress: the test Slicer sat idle with an IUMA
app stand-in (started by a Connections test of `SLIA-035`) still running, and
their processes were stopped. To tell whether this card causes it, the module
as committed at `HEAD` was exported read-only (`git show`) into
`build\slia021-head` and run the way `run-slicer-tests.ps1` runs it (stdout and
stderr redirected), alternating with the working tree, three times each:

| Run | `HEAD` module (111 tests) | Working tree (119 tests) |
| --- | --- | --- |
| 1 | hung, stopped after 120 s | OK, 17 skipped, 19.4 s |
| 2 | OK, 16 skipped, 19.0 s | OK, 17 skipped, 19.3 s |
| 3 | OK, 16 skipped, 18.8 s | OK, 17 skipped, 19.7 s |

Launched with output to a file instead of pipes, the working tree passed four
headless runs in a row (19.4 to 21.6 s) and the headful run above. The hang is
in existing Connections tests, not in code this card touches. It is a candidate
follow-up: a per-test timeout in the runner, and finding the blocking
OpenIGTLink call.

Codex-assisted headful verification, 2026-10-05: the built SLIAFlow launcher loaded
the working-tree build and ran real UC1 and UC2 on 002-04, with a generated
placeholder LiveView frame. Screenshots were visually inspected; the displayed
UC2 map's pixels matched its PNG exactly. The first Reload and Test run hung in
`test_connectTakesOverAConnectorStartedInOpenIGTLinkIF`, the intermittent
Connections hang recorded above; its three newly launched Slicer processes were
stopped without touching the existing sessions. With output redirected to a file,
`run-slicer-tests.ps1 -Headful` passed 119 tests (one skipped, exit 0), and the
Slicer Reload and Test path passed 119 tests (one skipped, exit 0). A separate
headful run used laptop camera 0: Start received a frame and Capture finished
with both UC1 and UC2 results. These are agent observations, not project-owner
approval.

Two clean UC2 builds on 2026-10-05 produced different executable SHA-256
values (`B93EE364...` and `E398B649...`), while the staged source, size,
warnings and checked outputs matched. The executable hash is not used as an
acceptance oracle; `uc2_local_build.md` records this variation.

## Review findings

## Human approval
