---
id: BSSL-009
title: Make the SLIAFlow launcher build reproducible
status: review
branch: feature/BSSL-009-build-sliaflow-script
priority: medium
depends_on: BSSL-004
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# BSSL-009 - Make the SLIAFlow launcher build reproducible

## Goal

Give the project one command that makes `build\SLIAFlow\SlicerWithSLIAFlow.exe`
show the current working tree, and that fails loudly when it cannot.

## Context

`build\SLIAFlow\SlicerWithSLIAFlow.exe` carries its own copy of the scripted
module under `lib\Slicer-<version>\qt-scripted-modules`, and that copy shadows
`--additional-module-paths`. `docs/development/testing_strategy.md` already
records this as the reason `run-slicer-tests.ps1` asserts which path the module
was loaded from. Nothing, however, refreshed that copy, so demonstrating the
application meant either trusting a build tree of unknown age or running CMake
by hand with a `Slicer_DIR` that had to be kept in step with
`config/local.json`.

The copy targets CMake generates for a scripted module only add files; they
never delete. A file renamed or removed in `extensions/SLIAFlow` therefore
survives in the build tree indefinitely. This was not hypothetical: the local
build tree still contained the `SLIAFlowLib/` package and
`Resources/Icons/SLIAFlow.png` from the SLIA-003 scaffold, neither of which
exists in the source any more, and its `SLIAFlow.py` did not match the working
tree. Manual verification against that launcher would have been evidence about
code that no longer exists.

## Requirements

- Provide one PowerShell entry point that builds the standalone SLIAFlow
  extension and leaves the launcher showing the working tree.
- Derive `Slicer_DIR` from `slicerExecutable` in `config/local.json` so the
  build and `run-slicer-tests.ps1` cannot disagree about which Slicer is used.
- Configure only when the build tree has no CMake cache, or on explicit request.
- Remove the deployed scripted-module copy before every build so renamed and
  deleted files cannot survive.
- Verify after the build that every module source file is deployed with
  identical content, and that the build tree holds no file without a source
  counterpart.
- Name the file that is missing from `CMakeLists.txt` when a source file was
  never copied.
- Report failure through a nonzero exit code, and never modify `apps\`.
- Offer an optional switch that starts the launcher once verification passes.

## Out of scope

- Changing SLIAFlow module behavior.
- Replacing `run-slicer-tests.ps1`, `run-python-quality.ps1`, or CTest.
- Building the upstream Slicer SuperBuild under `apps\`.
- Packaging or installing the extension outside `build\`.

## Files allowed

- `scripts/development/build-sliaflow.ps1`
- `docs/development/testing_strategy.md`
- `tasks/{backlog,active,review,completed}/BSSL-009-build-sliaflow-script.md`

## Relevant skills and references

- `slicer` skill for `slicerMacroBuildScriptedModule` and the generated
  `Copy*PythonScriptFiles`, `Copy*PythonResourceFiles`, and
  `Compile*PythonFiles` targets.
- `scripts/development/run-slicer-tests.ps1` for the existing configuration
  reading, error reporting, and exit-code conventions.
- `docs/development/testing_strategy.md`
- `build/SLIAFlow/SlicerWithSLIAFlowLauncherSettings.ini` for the module path
  the launcher actually uses.

## Implementation plan

1. Resolve CMake, the repository paths, and `Slicer_DIR` from
   `config/local.json`, reusing the failure messages style of the existing
   runner.
2. Configure the standalone extension build when no cache exists or `-Configure`
   is given.
3. Delete the deployed `qt-scripted-modules` directory and the bytecode stamp,
   then build with the requested configuration.
4. Compare the working tree and the deployed tree by SHA-256 in both directions
   and fail with the offending relative paths.
5. Document the command and the resulting day-to-day process.

## Acceptance criteria

- One command leaves the launcher running the current working tree.
- A source file that `CMakeLists.txt` does not declare fails the run and is
  named.
- A file removed from the source no longer survives in the build tree.
- Missing CMake, missing or malformed configuration, and a failed build all exit
  nonzero with an actionable message.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| One command leaves the launcher running the current working tree | `run-slicer-tests.ps1 -Target Build` after the script, plus manual step 1 | automated + manual |
| A source file that `CMakeLists.txt` does not declare fails the run and is named | Undeclared-file probe, plus manual step 2 | automated + manual |
| A file removed from the source no longer survives in the build tree | Deployed-tree listing before and after the first run, plus manual step 3 | automated + manual |
| Missing CMake, missing or malformed configuration, and a failed build all exit nonzero with an actionable message | Static reading of every `Stop-WithError` path and the `config/local.json` guards | automated |

Tests to add or change, and how each one will be shown to fail first:

- No `SLIAFlowTest` method is added. This task changes no module behavior, so
  its evidence is the state of the build tree and the script exit codes rather
  than a new Slicer test.
- The undeclared-file case is shown to fail first by adding a temporary
  `ProbeUndeclared.py` that `CMakeLists.txt` does not list, running the script,
  and observing the nonzero exit before removing the probe.

## Manual verification

Perform in the Slicer executable configured in `config/local.json`, with
Developer Mode enabled. Use no patient or private medical data.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Edit a visible string in `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`, run `.\scripts\development\build-sliaflow.ps1 -Launch`, and open SLIAFlow | The launcher opens and the edited string is visible in the module panel | |
| 2 | Create an empty `extensions/SLIAFlow/SLIAFlow/Probe.py`, run the script, then delete the file | The run stops with `not deployed: Probe.py` and a nonzero exit code | |
| 3 | Run the script twice in a row without changing anything | Both runs end with `The build tree matches the working tree.` and no orphan is reported | |

## Risks

Pruning the deployed directory before every build makes each run a clean build
of the module. Only generated output under `build\` is deleted, `build\` is
already ignored by `.gitignore`, and nothing under `apps\` or `extensions\` is
touched, so the worst case is a rebuild rather than lost work.

## Documentation impact

`docs/development/testing_strategy.md` gains a short section that states when to
run the script and how it fits between editing, the source-backed tests, and
manual verification in the launcher.

## Completion evidence

- Selected after `SLIA-005` because its manual verification exposed that nothing
  refreshed the launcher, and because the launcher shadowing
  `--additional-module-paths` was already a known hazard recorded for
  `BSSL-004`. `tasks/active/` and `tasks/review/` were empty at activation.
- Branch created and used: `feature/BSSL-009-build-sliaflow-script`, from the
  approved `SLIA-005` tip that `main` is being fast-forwarded to.
- Added `scripts/development/build-sliaflow.ps1` with `-Configuration`,
  `-Configure`, and `-Launch`. It resolves CMake from `PATH` and then from the
  default installer location, derives `Slicer_DIR` from `slicerExecutable` in
  `config/local.json`, and asserts that `SlicerConfig.cmake` sits beside it.
- The deployed `qt-scripted-modules` directory is discovered rather than
  hard-coded by Slicer version, and is deleted together with the
  `python_compile_*_complete` stamp before every build, which makes one run
  equivalent to a clean build of the module. Only generated output under
  `build\` is deleted; nothing under `apps\` or `extensions\` is touched.
- After the build, every module source file except `CMakeLists.txt`, `.pyc`
  files, and `__pycache__` is compared with its deployed copy by SHA-256, and
  the deployed tree is scanned for files with no source counterpart.
- Defect found and fixed by the first run: the build tree still held
  `SLIAFlowLib\SLIAFlowLogic.py`, `SLIAFlowParameterNode.py`,
  `SLIAFlowTest.py`, `SLIAFlowWidget.py`, `__init__.py`, and
  `Resources\Icons\SLIAFlow.png` from the SLIA-003 scaffold, none of which
  exist in the source, and its `SLIAFlow.py` hashed differently from the
  working tree. The launcher was therefore running an old snapshot plus dead
  modules. The prune step removed them and verification then reported an exact
  match.
- `.\scripts\development\build-sliaflow.ps1`: pruned the stale directory, CMake
  re-ran itself because the module `CMakeLists.txt` was newer than the generate
  stamp, and verification reported `ok` for `SLIAFlow.py`,
  `Resources\requirements.txt`, and `Resources\UI\SLIAFlow.ui`; exit code `0`.
- `.\scripts\development\run-slicer-tests.ps1 -Target Build` afterwards
  reported `SLIAFlow module loaded from:
  C:\stratum\build\SLIAFlow\lib\Slicer-5.13\qt-scripted-modules\SLIAFlow.py`;
  all 9 `SLIAFlowTest.test_*` methods passed plus Slicer's base `runTest`,
  10 tests, exit code `0`. This is the evidence that the launcher runs the
  working tree.
- Undeclared-file probe: a temporary `ProbeUndeclared.py` that the module
  `CMakeLists.txt` does not list produced `not deployed: ProbeUndeclared.py
  (add it to MODULE_PYTHON_SCRIPTS or MODULE_PYTHON_RESOURCES ...)` and exit
  code `1`. The probe was removed in a `finally` block and `git status`
  confirmed the worktree was clean afterwards.
- Idempotence: an immediately repeated run reported the same three `ok` lines,
  no orphan, and exit code `0`.
- PowerShell parser check on the script: passed. `git diff --check`: exit code
  `0`.
- Ruff was not run for this task because no Python source changed.
- Documented in `docs/development/testing_strategy.md` under
  `Refreshing the launcher`.
- Manual steps 1-3 remain pending; no manual result has been marked complete.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
