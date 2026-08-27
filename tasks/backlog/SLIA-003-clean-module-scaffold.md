---
id: SLIA-003
title: Create a clean SLIAFlow scripted-module scaffold
status: backlog
branch:
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

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
