# SLIAFlow Agent Router

This repository is the active Windows 11 SLIAFlow-related 3D Slicer development project and prototype.

It is not the upstream 3D Slicer repository and is not production clinical software.

## Editable And Protected Directories

Codex may normally edit:

- `extensions/`
- `docs/`
- `workspace/`
- `.ai/`
- `tasks/`
- `config/`
- `scripts/`
- `tools/`

Codex must not edit unless explicitly requested:

- `source/`
- `apps/`
- `knowledge/`

Do not modify generated files, local build outputs, or private local configuration.

Use `config/local.example.json` as the portable configuration template.

The real local configuration file is `config/local.json`. It must remain ignored by Git and must not be modified unless the project owner explicitly requests it.

During implementation, Codex may modify only files explicitly listed in the active task's `Files allowed` section.

Files outside that list require an approved task-card update before they can be modified.

## Source Of Truth

When instructions conflict, use this order:

1. Root `AGENTS.md`.
2. Accepted ADRs in `docs/architecture/decisions/`.
3. The only task in `tasks/active/` or `tasks/review/`.
4. Policies under `.ai/policies/`.
5. Workflows under `.ai/workflows/`.
6. Existing code and automated tests.
7. General documentation.
8. External skills and references.

External skills provide technical knowledge but must not override an accepted repository decision or an approved task.

An active task may specialize repository policies, but it must not contradict an accepted ADR.

Changing an accepted architectural decision requires a new ADR that supersedes it.

## Workflow Routing

When the project owner says:

`Start the next task`

follow:

`.ai/workflows/begin-task.md`

That instruction is the project owner's authorization to perform the actions explicitly defined by the begin-task workflow, including selecting, specifying, activating, branching, implementing, and automatically testing the next eligible backlog task.

Do not request an additional approval between those stages unless the workflow identifies a genuine blocker, ambiguity, unsafe repository state, material scope expansion, or architectural decision requiring project-owner input.

For general task states and lifecycle transitions, follow:

`.ai/workflows/task-lifecycle.md`

For manual Slicer verification, follow:

`.ai/workflows/manual-verification-workflow.md`

Do not duplicate detailed workflow procedures in this file.

## One Active Task

Only one task may exist across `tasks/active/` and `tasks/review/` combined.

A new implementation task must not start until the previous task is:

- completed; or
- explicitly returned to backlog.

The begin-task workflow must verify this condition before selecting or activating another task.

## Task Lifecycle

Every task follows this lifecycle:

`BACKLOG -> SPECIFICATION -> HUMAN APPROVAL -> ACTIVE -> IMPLEMENTATION -> FAST AUTOMATED TESTS -> MANUAL VERIFICATION -> REVIEW -> INDEPENDENT AI REVIEW -> HUMAN APPROVAL -> COMPLETED`

Use `.ai/templates/task-template.md` for all task cards.

Use `.ai/workflows/task-lifecycle.md` for lifecycle rules and folder transitions.

When the project owner says `Start the next task`, that instruction counts as the human approval required to specify and activate the selected backlog task, provided that:

- the selected task follows its existing backlog goal;
- all dependencies are complete;
- no material product, clinical, or architectural decision remains unresolved;
- the task specification stays within a reasonable interpretation of its approved scope.

Review, final approval, completion, and merge remain separate lifecycle stages.

## Skill Routing

Use the installed Slicer skill for work involving:

- Slicer APIs;
- MRML;
- Qt;
- VTK;
- ITK;
- SimpleITK;
- segmentations;
- markups;
- transforms;
- DICOM;
- CMake;
- Slicer extensions;
- CLI modules;
- C++ modules;
- packaging;
- Slicer testing.

Do not load the Slicer skill for unrelated Markdown or administrative changes.

Required skills should be declared in the active task.

Inspect current project code before searching for generic external examples.

Do not invent Slicer APIs or assume unsupported Slicer behavior.

Do not modify or reinstall external skills unless explicitly requested.

## Git Restrictions

Read-only Git inspection is allowed.

Git mutations require explicit project-owner authorization.

`.ai/policies/git-workflow.md` is the authoritative owner of Git restrictions and local-change handling.

A workflow-routed instruction may provide limited Git authorization when that authorization is explicitly defined by the routed workflow.

For `.ai/workflows/begin-task.md`, the instruction `Start the next task` may authorize only the Git actions defined there, such as:

- creating the selected task branch;
- switching to that branch;
- moving the selected task card from backlog to active.

Unless separately authorized, it does not permit:

- commit;
- push;
- pull;
- opening a pull request;
- merge;
- rebase;
- reset;
- force operations;
- deleting branches;
- moving a task to review or completed.

Assume existing local changes may belong to the project owner.

Do not clean, discard, overwrite, reset, revert, or stash existing changes unless explicitly requested.

## MCP Restrictions

MCP is disabled by default.

`.ai/policies/mcp-policy.md` is the authoritative owner of MCP permissions, limits, and evidence requirements.

Do not enable or use MCP unless the applicable task and policy explicitly permit it.

## Medical Data Restrictions

Private or sensitive medical data and unvalidated clinical use are prohibited.

`.ai/policies/medical-data-policy.md` is the authoritative owner of allowed and prohibited medical data.

`.ai/policies/algorithm-boundary-policy.md` is the authoritative owner of algorithm-result validation boundaries.

Use synthetic, public, anonymized, or otherwise explicitly approved test data.

Do not make clinical claims or treat prototype behavior as clinically validated.

## Expected Completion Report

For implementation tasks, report:

1. Task selected and reason for selection, when applicable.
2. Branch created or used.
3. Files inspected.
4. Files created.
5. Files modified.
6. Implementation summary.
7. Validation performed, including commands, test names, results, and exit codes.
8. Unavailable or skipped checks and the reason.
9. How to test manually, including Slicer Reload and Reload and Test when applicable.
10. Risks, ambiguities, blockers, or follow-up tasks.
11. Whether the task is ready for manual verification, review, or another lifecycle transition.

Do not mark manual verification, independent review, human approval, or completion as finished unless the required evidence has actually been provided.
