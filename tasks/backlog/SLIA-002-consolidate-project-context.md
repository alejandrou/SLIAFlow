---
id: SLIA-002
title: Consolidate STRATUM project context
status: backlog
branch:
priority: high
depends_on: SLIA-001
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-002 - Consolidate STRATUM project context

## Goal

Copy the approved complementary projects and reference material into the
canonical `C:\stratum` workspace without changing their code or deleting the
original files.

## Context

The Slicer module needs local access to the acquisition application, UC1 GPU
implementation, UC2 blood-vessel work, project presentation, and meeting notes.
These are supporting references; only SLIAFlow is implemented by this roadmap.

## Requirements

- Copy `AcquisitionSystemApp`, `blood_vessels_enhancement`, and
  `UC1_Brain_Tumor-GPU_optimization` to `workspace/components/`.
- Preserve `.git` metadata for the two component repositories that already have it.
- Copy the approved Slicer architecture Markdown files to `docs/architecture/`.
- Copy the presentation PDF and meeting-review Markdown to `workspace/references/`.
- Exclude `STRATUM_INTEGRATION_ARCHITECTURE_REVIEW.md` from the canonical project.
- Verify file counts, byte counts, repository status, and representative hashes.
- Retain every Desktop and Downloads source after verification.

## Out of scope

- Editing or building any copied component.
- Implementing the Slicer module.
- Deleting or moving the original Desktop/Downloads material.
- Importing private medical data.

## Files allowed

- `docs/architecture/STRATUM_SLICER_MODULE_OVERVIEW.md`
- `docs/architecture/STRATUM_SLICER_UC1_TECHNICAL_DRAFT.md`
- `docs/architecture/stratum-slicer-visualization-analysis.md`
- `workspace/components/**`
- `workspace/references/**`
- `tasks/{backlog,active,review,completed}/SLIA-002-consolidate-project-context.md`

## Relevant skills and references

- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- Source checkout at `C:\Users\AlejandroHerrera\Desktop\stratum`
- Meeting material under `C:\Users\AlejandroHerrera\Downloads`

## Implementation plan

1. Inventory the source and destination trees.
2. Copy each component to its named destination without flattening it.
3. Copy the three approved Markdown documents and two meeting references.
4. Compare counts, sizes, hashes, and nested Git status.
5. Record verification and leave the originals untouched.

## Acceptance criteria

- All three components exist under `workspace/components/` and match their sources.
- Existing component repositories remain clean and retain their remotes.
- Approved documentation exists in the intended tracked/ignored destinations.
- The excluded architecture review is absent from `C:\stratum` migration output.
- No source item is deleted.

## Test plan

- Compare recursive file counts and total byte counts per component.
- Compare SHA-256 hashes for all copied Markdown/PDF references.
- Run `git status --short --branch` in copied component repositories.
- Check the outer repository diff contains only the approved tracked documentation and task card.

## Manual verification

Open each copied document and inspect the three component top-level directories.

## Risks

Nested repository metadata or vendor binaries could be lost by an incomplete copy.
Verification therefore occurs before any future deletion request.

## Documentation impact

Adds the approved architecture documents to the canonical tracked documentation.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
