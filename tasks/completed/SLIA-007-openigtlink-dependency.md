---
id: SLIA-007
title: Build the SlicerOpenIGTLink dependency
status: active
branch: feature/SLIA-007-openigtlink-dependency
priority: high
depends_on: SLIA-013
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-007 - Build the SlicerOpenIGTLink dependency

## Goal

Make the official SlicerOpenIGTLink extension available to SLIAFlow without
moving or rebuilding the existing base Slicer application.

## Context

OpenIGTLink will carry `LiveView` and UC1 image maps as independent TCP/IP
streams. Networking behavior is deferred to SLIA-008.

This card depends on SLIA-013 for sequencing, not for code. Nothing here needs
the simulators; the dependency records that the stand-in producers are built
first so that SLIA-008 has something real to receive from on the day it is
written, rather than a connector with no counterpart. If the roadmap order
changes, this card can move without any change to its content.

## Requirements

- Clone official SlicerOpenIGTLink into `workspace/dependencies/SlicerOpenIGTLink`.
- Check out commit `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8` in detached state or a clearly named local branch.
- Build it under `build/SlicerOpenIGTLink` against `apps/SR/Slicer-build`.
- Configure SLIAFlow with `EXTENSION_DEPENDS SlicerOpenIGTLink` and the generated package directory.
- Document exact configure/build/discovery commands and local paths.
- Do not edit or rebuild `apps/` or `source/`.

## Out of scope

- Creating connectors or receiving images.
- Modifying SlicerOpenIGTLink source.
- Packaging or publishing either extension.

## Files allowed

- `extensions/SLIAFlow/CMakeLists.txt`
- `README_SLIAFlow_Build.md`
- `docs/development/openigtlink_setup.md`
- `workspace/dependencies/SlicerOpenIGTLink/**`
- `build/SlicerOpenIGTLink/**` (generated and ignored)
- `build/SLIAFlow/**` (generated and ignored)
- `tasks/{backlog,active,review,completed}/SLIA-007-openigtlink-dependency.md`

## Relevant skills and references

- Official Slicer extension build guidance.
- Official SlicerOpenIGTLink repository and pinned commit.
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`

## Implementation plan

1. Clone and pin the dependency in the ignored workspace.
2. Configure and build it against the existing Slicer directory.
3. Point the SLIAFlow extension configure step at the generated dependency package.
4. Rebuild SLIAFlow and verify module discovery for OpenIGTLinkIF.
5. Record reproducible Windows commands.

## Acceptance criteria

- The dependency commit is exactly pinned and its source is unmodified.
- Slicer starts with OpenIGTLinkIF and SLIAFlow discoverable.
- SLIAFlow declares the dependency through extension CMake metadata.
- No base Slicer source or build file changes.
- The existing SLIAFlow test suite still passes against the rebuilt extension,
  matching the baseline recorded before the dependency was added.

## Test plan

This task builds a dependency; it adds no module behaviour, so its coverage is
the existing suite re-run as a regression gate plus the numbered manual steps.

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The dependency commit is exactly pinned and its source is unmodified | Manual step 1 | manual |
| Slicer starts with OpenIGTLinkIF and SLIAFlow discoverable | Manual step 3 | manual |
| SLIAFlow declares the dependency through extension CMake metadata | Manual step 2 | manual |
| No base Slicer source or build file changes | Manual step 4 | manual |
| The existing SLIAFlow suite still passes against the rebuilt extension | `run-slicer-tests.ps1` | automated |

Tests to add or change, and how each one will be shown to fail first:

- No test is added. The dependency is a build artifact, and the properties that
  matter here - the pinned hash, the unmodified source tree, and the absence of
  changes under `apps/` and `source/` - are Git and filesystem facts rather than
  runtime behaviour, so asserting them in a Slicer test would test the test.
- `run-slicer-tests.ps1` is run before and after the rebuild and both outputs are
  recorded, so a regression introduced by the new `EXTENSION_DEPENDS` configure
  step cannot pass unnoticed.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `git -C workspace/dependencies/SlicerOpenIGTLink rev-parse HEAD` and `git -C ... status --short` | HEAD is exactly `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8` and the working tree is clean | Pass. HEAD is the pinned commit in detached state; `status --short --branch` prints only `## HEAD (no branch)` |
| 2 | Read the SLIAFlow `CMakeLists.txt` diff | `EXTENSION_DEPENDS SlicerOpenIGTLink` is declared and the dependency package directory is passed at configure time | Pass. One-line diff sets `EXTENSION_DEPENDS "SlicerOpenIGTLink"`; `-DSlicerOpenIGTLink_DIR` is documented in the README configure block |
| 3 | Start Slicer with no sender running | Both OpenIGTLinkIF and SLIAFlow appear in the module list and the log shows no new startup error | Headless equivalent passed, exit 0: the module manager lists OpenIGTLinkIF, OpenIGTLinkRemote, PlusRemote, UltrasoundRemoteControl and SLIAFlow, both loaded from this build. Project-owner confirmation in the GUI module list is still outstanding |
| 4 | Run `git status --short` at the repository root | No path under `apps/` or `source/` appears; only the files this card allows | Pass. Only the README, the extension CMakeLists, the new setup doc and this card's move appear |
| 5 | Run `scripts/development/run-slicer-tests.ps1` | The suite passes, matching the pre-rebuild baseline | Pass. 33 tests, OK (skipped=5), exit 0, matching the pre-rebuild Source baseline |

## Risks

Nightly Slicer and extension revisions can drift. The pinned dependency and recorded
local Slicer version make the development environment reproducible.

## Documentation impact

Add an independent OpenIGTLink dependency build procedure.

## Completion evidence

### Dependency

Cloned to the ignored `workspace/dependencies/SlicerOpenIGTLink` and left in
detached `HEAD` at `85e5f764f3ad3d4adbaa568db0104b2b8f5998e8`. A branch would
move under a later `git pull`; a detached checkout makes `rev-parse HEAD` the
whole pin. The source tree is unmodified.

Superbuild configured and built Release/x64 against `apps/SR/Slicer-build`,
exit 0, no compiler or linker errors. Loadable modules land in
`build/SlicerOpenIGTLink/inner-build/lib/Slicer-5.13/qt-loadable-modules/Release`
and the OpenIGTLink runtime libraries in `build/SlicerOpenIGTLink/bin/Release`.
`SlicerOpenIGTLink_USE_VP9` was left OFF.

### Wiring

`extensions/SLIAFlow/CMakeLists.txt` now sets
`EXTENSION_DEPENDS "SlicerOpenIGTLink"`. That name alone does nothing until the
configure step also supplies `SlicerOpenIGTLink_DIR`: `SlicerExtensionCPack`
expands `${dep}_DIR` into the launcher's `--additional-module-paths`, so the
package directory (`inner-build`, not the superbuild root) is passed at
configure time and the reconfigure is mandatory rather than cosmetic.

### Discovery verified against the running application

Through `build/SLIAFlow/SlicerWithSLIAFlow.exe`, exit 0 each time:

- the module manager lists `OpenIGTLinkIF`, `OpenIGTLinkRemote`, `PlusRemote`,
  `UltrasoundRemoteControl` and `SLIAFlow`, 152 modules in total;
- `slicer.util.modulePath('OpenIGTLinkIF')` resolves inside
  `build/SlicerOpenIGTLink/inner-build/...` and `SLIAFlow` inside
  `build/SLIAFlow/...`, so neither comes from a previously installed extension;
- `slicer.vtkMRMLIGTLConnectorNode()` constructs and reports its class name,
  which proves the native library loaded rather than only that a module name was
  registered.

### Regression gate

| Run | Before | After |
| --- | --- | --- |
| `run-slicer-tests.ps1` (Source) | 33 tests, OK (skipped=5), exit 0 | 33 tests, OK (skipped=5), exit 0 |
| `run-slicer-tests.ps1 -Target Build` | 28 tests, OK (skipped=2), exit 0 | 33 tests, OK (skipped=5), exit 0 |

The Build target's count rose because the compiled copy it exercises was a stale
snapshot before this rebuild; the rebuild brought it level with the source tree.
No test changed behaviour.

Also run after the rebuild: `ctest --test-dir build/SLIAFlow -C Release`,
2/2 passed, exit 0; `run-python-quality.ps1`, 31 files, all checks passed,
exit 0.

### Repository state

`git status --short` shows only `README_SLIAFlow_Build.md`,
`extensions/SLIAFlow/CMakeLists.txt`, the new
`docs/development/openigtlink_setup.md` and this card's move. Nothing under
`apps/` or `source/`. The dependency source and both build trees sit inside
Git-ignored directories.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
