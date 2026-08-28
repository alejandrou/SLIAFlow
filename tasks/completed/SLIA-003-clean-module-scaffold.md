---
id: SLIA-003
title: Create a clean SLIAFlow scripted-module scaffold
status: active
branch: feature/SLIA-003-clean-module-scaffold
priority: high
depends_on: SLIA-002
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-003 - Create a clean SLIAFlow scripted-module scaffold

## Goal

Create a fresh, minimal Python scripted Slicer extension named `SLIAFlow` and
prove that it builds and loads with the existing local Slicer build.

## Context

The former generic volume-inspection prototype is deliberately not reused.
The new scaffold is the stable foundation for the two-pane viewer.

## Requirements

- Create standard extension and scripted-module CMake files.
- Create the module entry point, widget, logic, parameter node, Qt Designer UI, and tests.
- Use translated strings for user-visible text and ASCII source text.
- Identify the module as a non-clinical STRATUM visualization prototype.
- Store MRML references by node ID through the module parameter node.
- Regenerate only `build/SLIAFlow`; do not rebuild or modify base Slicer.
- Preserve the launcher path `build/SLIAFlow/SlicerWithSLIAFlow.exe`.

## Out of scope

- Custom image layouts, camera capture, result maps, or OpenIGTLink.
- Acquisition, UC1, or UC2 changes.
- Any diagnostic image generation.

## Files allowed

- `extensions/SLIAFlow/**`
- `README_SLIAFlow_Build.md`
- `scripts/development/run-slicer-tests.ps1`
- `pyproject.toml`
- `pyrightconfig.json`
- `tasks/{backlog,active,review,completed}/SLIA-003-clean-module-scaffold.md`
- `build/SLIAFlow/**` (generated and ignored)

## Relevant skills and references

- Slicer scripted-module template and extension CMake guidance.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- Existing base Slicer at `apps/SR/Slicer-build`.

## Implementation plan

1. Generate a clean scripted extension structure.
2. Add minimal parameter-node, logic, widget, and test separation.
3. Configure the extension against `C:\stratum\apps\SR\Slicer-build`.
4. Build Release and run its focused CTest test.
5. Launch the generated SLIAFlow Slicer executable and verify module discovery.

## Acceptance criteria

- The extension configures and builds without modifying base Slicer.
- `SlicerWithSLIAFlow.exe` exists and opens the correct Slicer build.
- The SLIAFlow module loads with its title, category, help, and prototype warning.
- Automated scaffold tests pass.
- No code or behavior from the former inspection prototype is present.

## Test plan

- Run CMake configure and Release build from the approved roadmap.
- Run `ctest --test-dir build/SLIAFlow -C Release --output-on-failure`.
- Run the Python quality script.
- Import the module in Slicer and run Reload and Reload and Test manually.

## Manual verification

Launch `SlicerWithSLIAFlow.exe`, open SLIAFlow, run Reload, then Reload and Test.

## Risks

Stale extension build configuration can mask source errors. The ignored extension
build is regenerated; the base Slicer build remains unchanged.

## Documentation impact

Replace the old build README with the canonical build and launch procedure.

## Completion evidence

Implementation and automated validation completed on 2026-08-27 on branch
`feature/SLIA-003-clean-module-scaffold`.

- Created a clean extension root and scripted module with Slicer CMake files,
  metadata, a Qt Designer UI, a widget, logic, parameter-node wrapper, and
  focused tests.
- The parameter-node wrapper stores `liveVolume` and `resultVolume` as MRML
  node references. The focused test confirms that duplicate node names remain
  unambiguous because their IDs are persisted.
- Replaced the former build guide with the canonical extension-only configure,
  build, test, launch, Reload, and Reload and Test procedure.
- Updated `run-slicer-tests.ps1` to prefer the generated SLIAFlow launcher and
  run the standard `SLIAFlowTest` class, while retaining the configured base
  Slicer executable as a fallback.
- `cmake --fresh -S C:\stratum\extensions\SLIAFlow -B
  C:\stratum\build\SLIAFlow -G "Visual Studio 17 2022" -A x64
  -DSlicer_DIR:PATH=C:\stratum\apps\SR\Slicer-build
  -DBUILD_TESTING:BOOL=ON` completed with exit code 0. The generated cache uses
  platform `x64` and the approved base Slicer directory.
- `cmake --build C:\stratum\build\SLIAFlow --config Release` completed with
  exit code 0 and compiled/copied the scripted module resources.
- `ctest --test-dir C:\stratum\build\SLIAFlow -C Release
  --output-on-failure` completed with exit code 0: 2 of 2 tests passed
  (`py_nomainwindow_qSlicerSLIAFlowModuleGenericTest` and `py_SLIAFlow`).
- `powershell -NoProfile -ExecutionPolicy Bypass -File
  C:\stratum\scripts\development\run-slicer-tests.ps1` completed with exit
  code 0 through `SlicerWithSLIAFlow.exe`: all 3 discovered unittest entries
  passed, including metadata/UI warning checks and node-ID reference checks.
- A temporary headless launcher probe completed with exit code 0 and confirmed
  module discovery, title `SLIAFlow`, category `STRATUM`, non-clinical help
  text, and the visible not-clinically-validated warning. The temporary ignored
  probe file was removed after validation.
- On 2026-08-28, the module and extension categories and the manual test guide
  were aligned on the dedicated `STRATUM` category. The UI test now uses the
  module-owned widget representation rather than creating and deleting a second
  scripted widget whose unload callback retained a destroyed developer-mode
  `QToolButton`.
- The final Release rebuild, both CTest entries, and all three discovered
  Slicer-hosted unittest entries passed with exit code 0. A focused test-then-
  reload probe also printed `RELOAD_AFTER_TEST_OK` and exited 0 without the
  destroyed-`QToolButton` traceback.
- `git diff --check`, Qt UI XML parsing, ASCII-only source scanning, and the
  former-prototype marker scan completed successfully. The launcher exists at
  `build/SLIAFlow/SlicerWithSLIAFlow.exe`.
- `run-python-quality.ps1` completed its preflight with exit code 1 because
  Ruff and Pyright are not installed on `PATH`. The script did not install or
  update tools. Python compilation in the Slicer build and all Slicer-hosted
  tests passed.
- Manual Reload and Reload and Test remain pending project-owner verification.
  The implementation is ready for manual verification, not review or
  completion.

Observed non-failing environment warnings: Slicer's CMake configuration reports
the upstream CMP0148 compatibility warning and cannot extract Git metadata from
the extension subdirectory; headless Slicer startup reports an unrelated
`CropVolume` dependency warning. None prevented module discovery or test
success.

## Review findings

Reserved for review.

## Human approval

Task specification and activation approved by the project owner on 2026-08-27.
Review and completion still require separate approval.
