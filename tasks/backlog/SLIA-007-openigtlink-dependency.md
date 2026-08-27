---
id: SLIA-007
title: Build the SlicerOpenIGTLink dependency
status: backlog
branch:
priority: high
depends_on: SLIA-006
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-007 - Build the SlicerOpenIGTLink dependency

## Goal

Make the official SlicerOpenIGTLink extension available to SLIAFlow without
moving or rebuilding the existing base Slicer application.

## Context

OpenIGTLink will carry `LiveView` and genuine UC1 image maps as independent
TCP/IP streams. Networking behavior is deferred to SLIA-008.

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

## Test plan

- Verify dependency Git status and commit hash.
- Run dependency and SLIAFlow configure/build commands.
- Start Slicer without networking and confirm both modules load.
- Inspect outer Git changed-path scope.

## Manual verification

Open Slicer and confirm OpenIGTLinkIF and SLIAFlow are present without new startup errors.

## Risks

Nightly Slicer and extension revisions can drift. The pinned dependency and recorded
local Slicer version make the development environment reproducible.

## Documentation impact

Add an independent OpenIGTLink dependency build procedure.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
