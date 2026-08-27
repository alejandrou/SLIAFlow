---
id: SLIA-001
title: Establish the SLIAFlow project foundation
status: completed
branch: feature/SLIA-001-project-foundation
priority: critical
depends_on:
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# SLIA-001 - Establish the SLIAFlow project foundation

## Goal

Make `C:\stratum` the unambiguous home of the STRATUM Slicer demonstrator and
replace the generic test-prototype backlog with an ordered, implementation-ready
roadmap.

## Context

The project owner approved a nine-card roadmap for a simple Slicer visualization
module. The first usable milestone is a two-pane Slicer interface with a laptop
camera on the left and a black UC1 result pane on the right. No simulated
diagnostic output is permitted. The existing base Slicer build is costly and must
remain untouched.

The repository currently contains a generic volume-inspection prototype and an
untracked nested clone at `C:\stratum\SLIAFlow`. The nested clone is clean, has no
unique commits or untracked files, and duplicates repositories and build outputs
already available from the canonical root.

## Requirements

- Record the approved architecture and ordered task roadmap in tracked documentation.
- Create cards `SLIA-002` through `SLIA-009` in dependency order.
- Preserve BSSL-005 through BSSL-008 under `tasks/superseded/`; do not treat them as eligible work.
- Keep completed BSSL-001 through BSSL-004 as historical completion evidence.
- Remove the generic tracked extension prototype from the active source tree. Git history remains the recovery path.
- Remove only the verified duplicate `C:\stratum\SLIAFlow` directory from the
  canonical root. If recursive deletion is unavailable, move it to the ignored
  `workspace/legacy` quarantine and report the remaining disk cleanup explicitly.
- Leave `apps/`, `source/`, `build/`, and `config/local.json` unchanged.
- Do not copy or delete Desktop project material; that belongs to SLIA-002.
- Record the project owner's branch, single-amended-commit, commit-message, and
  rebase-integration conventions in the repository Git workflow policy.

## Out of scope

- Creating the replacement scripted module.
- Building Slicer or the extension.
- Implementing the two-pane interface, camera, result display, or OpenIGTLink.
- Modifying AcquisitionSystemApp, UC1, or UC2.
- Deleting source material from the Desktop checkout or Downloads folder.
- Performing a commit, amend, rebase, merge, push, or other Git mutation while
  documenting the Git workflow.

## Files allowed

- `README.md`
- `.ai/policies/git-workflow.md`
- `.ai/workflows/task-lifecycle.md`
- `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md`
- `docs/SLIAFLOW_CLEANUP_AND_NEXT_STEPS.md`
- `tasks/{active,review,completed}/SLIA-001-project-foundation.md`
- `tasks/active/BSSL-005-persistent-module-state.md`
- `tasks/backlog/BSSL-006-algorithm-provider-boundary.md`
- `tasks/backlog/BSSL-007-first-mock-vertical-slice.md`
- `tasks/backlog/BSSL-008-result-persistence-reporting.md`
- `tasks/backlog/SLIA-002-consolidate-project-context.md`
- `tasks/backlog/SLIA-003-clean-module-scaffold.md`
- `tasks/backlog/SLIA-004-two-pane-interface.md`
- `tasks/backlog/SLIA-005-laptop-camera.md`
- `tasks/backlog/SLIA-006-genuine-result-presentation.md`
- `tasks/backlog/SLIA-007-openigtlink-dependency.md`
- `tasks/backlog/SLIA-008-network-reception.md`
- `tasks/backlog/SLIA-009-demo-hardening.md`
- `tasks/superseded/**`
- `extensions/SLIAFlow/**`
- `SLIAFlow/**` (verified nested duplicate only)
- `workspace/legacy/SLIAFlow-extension-prototype/**` (ignored quarantine)
- `workspace/legacy/SLIAFlow-nested-duplicate/**` (ignored quarantine)

## Relevant skills and references

- Installed Slicer skill for extension structure and build boundaries.
- Approved SLIAFlow Slicer Implementation Roadmap from the project owner.
- `AGENTS.md`
- `.ai/workflows/task-lifecycle.md`
- `.ai/policies/git-workflow.md`
- `.ai/policies/medical-data-policy.md`
- `.ai/policies/algorithm-boundary-policy.md`

## Implementation plan

1. Create `feature/SLIA-001-project-foundation` from the current local `main`.
2. Move obsolete active/backlog BSSL cards to the superseded area without deleting their text.
3. Add the approved roadmap and the next eight task cards.
4. Remove the generic test extension from the active source tree.
5. Remove the exact nested duplicate after confirming its resolved path, clean
   state, and commit containment; use ignored recoverable quarantine if direct
   recursive deletion is unavailable.
6. Verify repository scope and protected directories.
7. Document the owner-approved Git workflow without performing Git mutations.

## Acceptance criteria

- The current branch is `feature/SLIA-001-project-foundation` and is based on local `main`.
- Exactly one task is active: SLIA-001.
- SLIA-002 through SLIA-009 exist in the backlog with ordered dependencies.
- BSSL-005 through BSSL-008 remain readable under `tasks/superseded/`.
- The generic extension prototype and nested duplicate are absent.
- `apps/`, `source/`, the base Slicer executable, and generated extension build are unchanged.
- The roadmap clearly prohibits simulated diagnostic results and changes to UC1/UC2.
- The Git policy defines the one-branch, one-amended-commit workflow, Slicer-style
  final prefixes, concise natural-language explanation, and rebase-based integration.

## Test plan

- Inspect `git status`, `git diff --check`, and changed-path scope.
- Confirm only SLIA-001 exists across `tasks/active/` and `tasks/review/`.
- Confirm all new backlog cards and superseded BSSL cards exist.
- Confirm `C:\stratum\SLIAFlow` and tracked `extensions/SLIAFlow` prototype files are absent.
- Confirm the existing Slicer executable and launcher still exist.
- Inspect the Git policy for consistency with `AGENTS.md` and the begin-task
  workflow, then run Markdown whitespace and changed-path checks.

## Manual verification

Documentation-only verification: read the roadmap and task cards in order and
confirm that the first implementation milestone is understandable without reading
the superseded prototype cards.

## Risks

Recursive deletion is limited to the exact verified nested duplicate. If the
environment blocks it, the safe fallback is an exact-path move into ignored
quarantine. The tracked prototype also remains recoverable from Git history.
Desktop source material is retained.

## Documentation impact

Adds the implementation roadmap, a short cleanup/next-steps handoff, updates the
repository entry point to link them, and records the owner-approved Git workflow.

## Completion evidence

Implementation and fast repository checks completed on 2026-08-26. Documentation
verification, independent AI review, and final human approval completed on
2026-08-27. The final local commit and fast-forward merge are authorized for
this integration pass; no push or branch deletion is authorized.

Implementation summary:

- Created `feature/SLIA-001-project-foundation` from local `main` at
  `52465243f9f7e3b83ec0c9bfe5d9e17b6a83b9eb`.
- Added the tracked architecture roadmap and eight dependency-ordered backlog cards.
- Added a plain-language cleanup and next-development checklist for the project
  owner. No files were deleted as part of that checklist.
- Retained BSSL-005 through BSSL-008 under `tasks/superseded/`; completed BSSL
  history remains under `tasks/completed/`.
- Removed the generic extension prototype from `extensions/SLIAFlow`.
- Verified that the nested clone was clean, had no unique commits or untracked
  files, and occupied approximately 12.377 GiB.
- Recursive `Remove-Item` was blocked by the execution environment after safe-path
  validation. The prototype's ignored runtime artifacts and the exact nested clone
  were therefore moved to `workspace/legacy/SLIAFlow-extension-prototype` and
  `workspace/legacy/SLIAFlow-nested-duplicate`. Both canonical source paths are
  absent. The tracked prototype remains recoverable from Git history, while the
  ignored runtime artifacts and nested duplicate remain in quarantine and still
  occupy disk space.
- Expanded `.ai/policies/git-workflow.md` with the owner-approved one-branch,
  one-amended-commit workflow, temporary `WIP:` subject, final Slicer-style
  prefixes, concise natural-language explanation, and rebase/fast-forward
  integration. StaRT-specific paths and instructions from the supplied reference
  were not imported.
- Left Desktop/Downloads inputs, `apps/`, `source/`, `build/`, and
  `config/local.json` unchanged.

Validation results:

- `git diff --check`: passed, exit code 0; only line-ending notices were reported.
- Task template check: 9 SLIA cards checked, passed.
- Dependency chain check from SLIA-002 through SLIA-009: passed.
- Active/review counts: one active task and zero review tasks.
- Eligible BSSL-card check: passed; none remain in active or backlog.
- Protected-path diff check for `apps`, `source`, `build`, and
  `config/local.json`: passed.
- Canonical-path checks: `extensions/SLIAFlow` absent and `C:\stratum\SLIAFlow`
  absent.
- Existing `Slicer.exe` and `SlicerWithSLIAFlow.exe`: both still present.
- Excluded architecture review copy check: passed.

Implementation revalidation on 2026-08-27:

- `git diff --check`: passed, exit code 0; only Windows line-ending notices
  were reported.
- Allowed-path scope and text-whitespace checks: passed, exit code 0.
- All nine SLIA task cards contain the required sections and expected statuses;
  the SLIA-002 through SLIA-009 dependency chain passed.
- Active/review counts remain one and zero, and no BSSL-005 through BSSL-008
  card remains eligible in `tasks/active/` or `tasks/backlog/`.
- The substantive original text of BSSL-005 through BSSL-008 remains present in
  the superseded cards.
- The canonical extension and nested-clone paths remain absent; both quarantine
  paths resolve beneath `C:\stratum\workspace\legacy` and are ignored by Git.
- The nested clone remains clean at
  `986396b84a1d46fd25d7b303b392db9e2ce483e4`, which is contained in local
  `main`. Its measured size is 13,289,168,015 bytes (about 12.377 GiB).
- The prototype quarantine contains 24 ignored runtime-artifact files totaling
  136,260 bytes (about 0.13 MiB); the removed tracked source remains recoverable
  from Git history.
- Protected tracked-path diff, executable-presence, and excluded-review-copy
  checks passed.
- Git-policy concept and foreign-reference checks passed, exit code 0. The
  policy contains the requested single-commit/amend, prefix, validation, and
  rebase/fast-forward rules, contains no StaRT-specific path references, and no
  change was staged or committed.

Final documentation verification and review on 2026-08-27:

- Read the roadmap, cleanup checklist, README links, and SLIA-002 through
  SLIA-009 cards in order. The first implementation milestone, safety
  boundaries, dependency chain, and next steps are understandable without
  relying on the superseded prototype cards.
- Independent AI review compared the changed paths and content with the task
  requirements, out-of-scope rules, protected directories, and applicable
  policies. No findings were identified.
- The task record is now marked completed in `tasks/completed/`; no task remains
  in `tasks/active/` or `tasks/review/`.

## Review findings

No findings. Independent AI review completed on 2026-08-27 against the approved
requirements, acceptance criteria, out-of-scope items, repository policies, and
changed-path scope.

## Human approval

The project owner explicitly authorized the final task commit and fast-forward
merge on 2026-08-27, and directed that the temporary `WIP:` commit be skipped
because the task is already complete. Push and branch deletion remain
unauthorized.
