# Git Workflow Policy

This policy keeps SLIAFlow history small, readable, and aligned with the task
lifecycle. Each task uses its own branch and one evolving commit.

## Authorization Boundary

Git mutations require explicit project-owner authorization unless a repository
workflow grants a narrower authorization for a specific action.

Do not perform any of the following without that authorization:

- stage changes;
- create, switch, delete, or rename branches;
- commit or amend a commit;
- fetch, pull, push, merge, or rebase;
- open a pull request;
- reset, revert, clean, stash, or force-update anything;
- delete tracked files.

The instruction `Start the next task` grants only the Git authorization stated
in `.ai/workflows/begin-task.md`, including creation and checkout of the selected
task branch. It does not authorize staging, committing, amending, rebasing,
merging, pushing, or opening a pull request.

Read-only inspection such as `git status`, `git diff`, `git log`, `git show`,
and `git merge-base` is allowed.

## Protect Existing Work

Assume existing local changes belong to the project owner. Never clean, discard,
overwrite, reset, revert, or stash them unless the owner explicitly requests the
exact operation.

Before proposing or performing a commit, inspect:

```text
git status --short --branch
git diff --stat
git diff
```

If anything is staged, also inspect:

```text
git diff --cached --stat
git diff --cached
```

Do not assume every changed file belongs to the active task. Compare all changed
paths with the active task's `Files allowed` section. Unrelated changes stay
untouched and uncommitted.

Do not version generated files, caches, local configuration, build outputs,
logs, temporary files, downloaded dependencies, or experimental artifacts.
Follow `AGENTS.md` and `.gitignore` for repository-specific protected and ignored
paths. Runtime copies under `apps/` and `build/` are not source files.

## Branch Workflow

Each implementation task uses the branch named in its approved task card. The
normal branch format is:

```text
feature/<task-id>-<task-slug>
```

Create the branch from the approved local `main` according to the begin-task
workflow. Keep work for only one task and one purpose on that branch. If an
unrelated change is discovered, leave it out and create or update a separate
task rather than adding another commit to the current branch.

## One Evolving Commit

Once task work is committed, the task branch has exactly one commit relative to
`main`.

After explicit commit authorization, create the initial task commit with a
single-sentence `WIP:` subject:

```text
WIP: Establish the SLIAFlow project foundation
```

Keep the in-progress commit message to that one-sentence subject. Add the short
explanatory body only when finalizing the commit for integration.

When more task changes are made, stage only the reviewed task files and amend
the existing task commit. Update its one-sentence subject so it describes the
complete current change:

```text
git commit --amend -m "WIP: Establish the SLIAFlow project foundation"
```

Do not create a second task commit. Every later save of the same task is an
amendment to the latest commit.

Before amending, verify that the branch has exactly one task commit relative to
`main`:

```text
git rev-list --count main..HEAD
```

If it has no task commit, create the initial `WIP:` commit. If it has more than
one, stop and ask the owner how to repair the history; do not rewrite or squash
it without explicit authorization.

Use explicit staging paths after reviewing the change set. Avoid broad staging
commands such as `git add .` and `git add -A`.

Never merge a commit whose subject still begins with `WIP:`.

## Final Commit Message

Before integration, amend the one commit to replace `WIP:` with the prefix that
best describes the completed change:

- `BUG:` fixes incorrect behavior, a crash, a regression, or a wrong result;
- `COMP:` fixes compilation, CMake, dependency, or build warnings and failures;
- `DOC:` changes only documentation or usage guidance;
- `ENH:` adds behavior, capability, or another user-visible improvement;
- `PERF:` primarily improves speed, memory use, or loading time;
- `STYLE:` changes formatting, naming, imports, or comments without logic impact;
- `WIP:` is reserved for the temporary task-branch commit before integration.

The subject must:

- start with one allowed prefix;
- contain one concise sentence in imperative mood;
- capitalize the first word after the prefix;
- describe the meaningful intent rather than only an implementation detail;
- not end with a period;
- remain below 72 characters, ideally near 50.

Examples:

```text
BUG: Restore the result view after scene reload
ENH: Add laptop camera display to the live pane
DOC: Document the SLIAFlow Git workflow
COMP: Fix OpenIGTLink discovery during extension configure
STYLE: Normalize imports in the camera controller
WIP: Add initial two-pane viewer behavior
```

Add a short, natural-language body to the final commit when an explanation is
useful. State what changed and why; briefly describe how it works, validation,
or a known limitation only when relevant. Keep it to a few small paragraphs,
wrap near 80 characters, and leave a blank line between subject and body.

## Validation Before Commit Or Amend

Run the narrowest checks required by the active task before committing or
amending. At minimum:

- inspect the working and staged diffs;
- run `git diff --check`;
- confirm every changed path is allowed by the active task;
- run the task's relevant automated tests;
- record unavailable or manual-only checks;
- verify that no protected, generated, private, or unrelated file is staged.

After the commit or amend, verify that the task branch contains exactly one
commit relative to `main` and that the worktree contains no unexpected changes.

## Rebase And Merge Integration

The default integration path is a direct rebase and fast-forward merge, not a
pull request. Each step still requires the project owner's explicit
authorization.

1. Inspect the task branch and confirm review, validation, and human approval
   are complete.
2. Amend the single commit to use its final `BUG:`, `COMP:`, `DOC:`, `ENH:`,
   `PERF:`, or `STYLE:` subject and concise natural-language body.
3. Rebase the task branch onto the approved current local `main`.
4. Rerun the relevant validation after the rebase.
5. Fast-forward `main` to the rebased task branch without creating a merge
   commit.
6. Push or delete the task branch only when separately authorized.

Do not use `git pull` as a shortcut for this integration sequence. If remote
updates are needed, obtain authorization and inspect them before changing local
branches. Do not force-push a rebased branch unless the owner explicitly
authorizes it; prefer `--force-with-lease` over an unrestricted force push.

Pull requests are not part of the normal local workflow. If the owner explicitly
requests one as an exception, use the final commit subject as its title and add
only a short, natural explanation of what changed, why it was needed, and how it
was validated.

## Git Review Output

When asked to review or prepare Git work, report:

- the changed files and whether each belongs to the active task;
- any unrelated or unsafe changes that must remain untouched;
- the current number of task-branch commits relative to `main`;
- the recommended temporary `WIP:` or final prefixed subject;
- a short natural-language body when useful;
- validation completed and validation still required;
- the exact Git mutations that still need owner authorization.

When the owner asks only for a commit message, return only the recommended
message.
