---
id: BSSL-005
title: Introduce persistent module state and rebrand as SLIAFlow
status: superseded
branch: feature/BSSL-005-persistent-module-state
priority: high
depends_on: BSSL-004
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# BSSL-005 - Introduce persistent module state and rebrand as SLIAFlow

> Superseded on 2026-08-26 by the approved STRATUM SLIAFlow implementation
> roadmap. The card is retained as historical context, but its generic
> volume-inspection workflow is not part of the new demonstrator.

## Scope expansion

On 2026-07-23, the project owner approved expanding this active task to rebrand the
project-owned repository and scripted module to `SLIAFlow`.
The checkout remains at the existing local root. Required 3D Slicer platform APIs, executable
names, CMake integration, and technical documentation terminology remain unchanged.
Legacy parameter nodes and saved scenes from the former module identity are not migrated.

## Goal

Persist the selected input-volume reference in MRML using Slicer's supported typed parameter-node wrapper so the selection survives scene save/load and remains synchronized with the module UI.

## Context

The current `SLIAFlowWidget` reads `inputVolumeNodeComboBox` directly when inspection is requested. `SLIAFlowLogic.getParameterNode()` provides the supported singleton scripted-module node, and the current Slicer source demonstrates typed `parameterNodeWrapper` state plus scene-close observers. BSSL-004 supplies the repeatable Slicer test runner required to validate this behavior. The rebrand must preserve this behavior under the new `SLIAFlow` module identity.

## Requirements

- Add a typed `SLIAFlowParameterNode` wrapper with one optional `inputVolumeNode` MRML reference.
- Store and retrieve that reference through the singleton parameter node returned by `SLIAFlowLogic.getParameterNode()`.
- Synchronize the combo box to MRML on every user selection change and synchronize MRML to the combo box whenever the parameter node changes.
- Initialize the wrapper when the module is set up or entered; release the wrapper before scene close and recreate it after close only when the module is entered.
- Keep the default state empty. Do not automatically select a scene volume.
- Preserve the existing inspection behavior, but make it read the persistent `inputVolumeNode` state.
- Add focused synthetic-MRML tests for default state, setting/clearing the reference, and scene save/load persistence.
- Rebrand the project-owned repository, extension tree, module identifiers, resources, documentation, tooling, and local workspace launch scripts as `SLIAFlow`.
- Preserve required Slicer platform APIs, executable names, CMake integration, technical documentation terminology, and the existing local checkout root.
- Do not migrate parameter nodes or saved scenes created under the former module identity.

## Out of scope

- Algorithm providers, processing behavior, or result generation.
- Clinical data or clinical claims.
- Unrelated UI redesign or persistence of transient presentation details.
- Persisting environment reports, inspection reports, status labels, button state, or collapsible-panel presentation state.
- New dependencies, algorithm providers, clinical data, legacy-scene migration, generated Slicer/source/build trees, vendor content, or changes outside the approved rebrand files and this task card.

## Files allowed

Implementation files approved for this task, including their renamed equivalents:

- `AGENTS.md`
- `README.md`
- `README_SLIAFlow_Build.md`
- `.ai/policies/medical-data-policy.md`
- `docs/development/coding_standards.md`
- `docs/development/project_structure.md`
- `docs/development/testing_strategy.md`
- `docs/knowledge/README.md`
- `docs/slicer/scripted_module_structure.md`
- `docs/slicer/slicer_module_architecture.md`
- `extensions/SLIAFlow/**`
- `pyproject.toml`
- `pyrightconfig.json`
- `scripts/development/run-python-quality.ps1`
- `scripts/development/run-slicer-tests.ps1`
- `tasks/active/BSSL-005-persistent-module-state.md`
- `tasks/backlog/BSSL-006-algorithm-provider-boundary.md`
- `tasks/backlog/BSSL-007-first-mock-vertical-slice.md`
- `tasks/completed/BSSL-001-ai-development-workflow.md`
- `tasks/completed/BSSL-002-consolidate-repository-documentation.md`
- `tasks/completed/BSSL-003-module-identity-python-quality.md`
- `tasks/completed/BSSL-004-automate-slicer-tests.md`
- `workspace/build_scripts/CommonVars_SLIAFlow_ASCII.bat`
- `workspace/build_scripts/SLIAFlow_Release_Build_ASCII.bat`
- `workspace/build_scripts/Start_SLIAFlow_Slicer_Release_ASCII.bat`

## Relevant skills and references

- Slicer skill for MRML scene and parameter-node patterns.
- Dependency: BSSL-004.
- Current Slicer source: `Base/Python/slicer/parameterNodeWrapper/` and `Modules/Scripted/VectorToScalarVolume/VectorToScalarVolume.py`.
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`

## Implementation plan

1. Define the typed wrapper in a dedicated state-support file and package it as a module Python script.
2. Add widget ownership, observer lifecycle, and guarded two-way synchronization around the existing volume selector.
3. Route inspection through the persisted reference without persisting transient report UI.
4. Add synthetic-MRML tests for empty, set/clear, and saved/reloaded state.
5. Rename the extension tree and update Slicer/CMake/Python identifiers, resources, tests, and tooling to `SLIAFlow`.
6. Update project-owned documentation and ignored workspace launch scripts, preserving platform-specific Slicer terminology.
7. Configure and build a fresh ignored `build/SLIAFlow` tree, run the renamed tests, and verify the repository rename and remote.

## Acceptance criteria

- The selected input volume is represented by the singleton `SLIAFlow` scripted-module parameter node and is restored after a saved scene is loaded.
- Changing the selector updates the parameter-node reference; changing the parameter-node reference updates the selector without recursion.
- The default and cleared states are `None`, and closing a scene does not leave the widget holding a stale parameter node.
- Environment and inspection output remain transient and existing inspection results remain correct.
- Automated tests cover empty/default, setting, clearing, and save/load persistence with synthetic MRML data.
- The project-owned source tree and documentation use `SLIAFlow`; required Slicer platform references remain available.
- A fresh `build/SLIAFlow` configure/build and the renamed Slicer/CTest tests succeed.
- The GitHub repository is `alejandrou/SLIAFlow` and the local `origin` points to it.

## Test plan

Run `scripts/development/run-slicer-tests.ps1` from the repository root. The existing module test suite must pass, including new synthetic-MRML state tests for default, set, clear, and save/load behavior. Run `scripts/development/run-python-quality.ps1` with the ignored root `.venv` activated. No private or sensitive medical data may be used.

## Manual verification

In Slicer, open `SLIAFlow`, select and clear a synthetic or public sample volume, save and reopen the scene to confirm the selection returns, then close/open a scene to confirm the empty default and no stale UI. Use Reload and Reload and Test; record the owner-provided results later. Manual verification is not complete in this task activation.

## Risks

Incorrect observer cleanup could retain a cleared parameter node or duplicate callbacks after Reload. Persisting report UI would create misleading stale output, so only the input reference is in scope. Save/load behavior depends on normal Slicer scene persistence and still requires owner manual verification.

## Documentation impact

Project README files, development notes, Slicer module notes, task references, and local
build-script names were updated to the `SLIAFlow` identity. Platform-specific Slicer
terminology remains because it is required for development and runtime use.

## Completion evidence

Status: Active. Implementation and fast automated tests are complete; manual verification, review, human approval, and completion remain pending.

Implementation summary:

- Added `SLIAFlowParameterNode`, a supported typed `parameterNodeWrapper` around the singleton `SLIAFlow` scripted-module node. Its only persisted field is the optional `inputVolumeNode` reference.
- Updated the widget to initialize, observe, and release/recreate the wrapper across module entry and MRML scene-close events. Combo-box changes update MRML, and parameter-node modifications update the combo box with a recursion guard.
- Preserved transient environment and volume-metadata reports. Inspection now reads the persisted input reference.
- Added synthetic-MRML coverage for the empty default, selecting a volume, clearing it, and saving/reloading the selected reference. The discovery adapter had one redundant blank line removed to keep the already-used test path Ruff-compliant.
- Renamed the project-owned extension tree, Python package, module classes, resources, CMake identifiers, test registration, documentation links, quality/test paths, and local workspace launch scripts to `SLIAFlow`.
- Preserved the Slicer runtime namespace, executable names, CMake macros, MRML APIs, and technical documentation terminology.
- Kept the existing checkout root and local Slicer configuration valid; the new standalone extension build uses `build/SLIAFlow`.

Files created or renamed:

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Testing/Python/SLIAFlowModuleTest.py`
- `README_SLIAFlow_Build.md`

Files modified:

- `AGENTS.md`, `README.md`, `.ai/policies/medical-data-policy.md`, `docs/`, and task cards
- `extensions/SLIAFlow/CMakeLists.txt` and `extensions/SLIAFlow/SLIAFlow/CMakeLists.txt`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/Testing/Python/CMakeLists.txt`
- `pyproject.toml`, `pyrightconfig.json`, and development PowerShell runners
- `workspace/build_scripts/CommonVars_SLIAFlow_ASCII.bat`, `SLIAFlow_Release_Build_ASCII.bat`, and `Start_SLIAFlow_Slicer_Release_ASCII.bat`
- `tasks/active/BSSL-005-persistent-module-state.md`

Automated validation on 2026-07-16:

- `git diff --check`: passed (exit code 0). Git emitted only existing Windows line-ending conversion notices.
- `./.venv/Scripts/Activate.ps1; ./scripts/development/run-python-quality.ps1`: passed (exit code 0). Ruff reported `All checks passed!`; Pyright reported 0 errors and 15 expected warnings for Slicer/VTK runtime imports unavailable to ordinary system Python.
- `./scripts/development/run-slicer-tests.ps1`: passed (exit code 0). The configured Slicer executable ran all five tests: environment report, volume inspection with and without selection, parameter-node default/set/clear state, and parameter-node scene save/load persistence.
- The test output included an unrelated pre-existing CropVolume dependency-load warning while the isolated project test suite still completed successfully.

No private medical data or new dependencies were used. The GitHub repository rename was performed with the existing authenticated repository credential; no history rewrite, review transition, or completion transition was performed.

Automated validation on 2026-07-23:

- `git diff --check`: passed (exit code 0).
- `./.venv/Scripts/Activate.ps1; ./scripts/development/run-python-quality.ps1`: passed (exit code 0). Ruff reported all checks passed; Pyright reported 0 errors and 15 expected Slicer/VTK runtime-import warnings.
- `cmake -S extensions/SLIAFlow -B build/SLIAFlow -DSlicer_DIR="C:\\stratum\\apps\\SR\\Slicer-build" -DBUILD_TESTING=ON`: passed (exit code 0); only existing CMake developer-policy/repository-info warnings were emitted.
- `cmake --build build/SLIAFlow --config Release`: passed (exit code 0); renamed Python scripts and resources compiled/copied successfully.
- `ctest --test-dir build/SLIAFlow -C Release -N`: passed (exit code 0); both renamed generic and project-specific tests were listed.
- `ctest --test-dir build/SLIAFlow -C Release -R "^py_SLIAFlowModuleTest$" --output-on-failure`: passed (exit code 0); 1/1 test passed.
- `./scripts/development/run-slicer-tests.ps1`: passed (exit code 0); all five `SLIAFlow` tests passed. The output retained the unrelated pre-existing CropVolume dependency warning.
- Project-owned identifier scan found no remaining former project identity references outside ignored local configuration and Git metadata.

## Review findings

Reserved for later independent review.

## Human approval

The project owner's `Start the next task` instruction on 2026-07-16 approved this proportional specification and activation under `.ai/workflows/begin-task.md`. It does not authorize manual-verification completion, review, completion, commit, push, or pull-request actions.
