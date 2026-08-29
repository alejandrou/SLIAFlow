# Begin Task Workflow

Use this workflow when the project owner says:

`Start the next task`

That instruction is explicit authorization to:

- inspect the repository and backlog;
- select the next eligible backlog task;
- complete or refine its specification;
- define its exact `Files allowed`;
- create and switch to the corresponding feature branch;
- move the selected task from `tasks/backlog/` to `tasks/active/`;
- update its status and branch metadata;
- implement the task;
- run the applicable automated tests;
- update the task's implementation evidence.

No additional approval is required between task selection, activation,
branch creation, implementation, and automated testing.

This authorization does not include:

- commit;
- push;
- pull;
- opening a pull request;
- merge;
- rebase;
- reset;
- force operations;
- deleting branches;
- moving the task to `tasks/review/`;
- moving the task to `tasks/completed/`.

Those actions require separate explicit authorization.

## 1. Load repository instructions

Before selecting a task, read:

1. `AGENTS.md`
2. `.ai/workflows/task-lifecycle.md`
3. `.ai/policies/git-workflow.md`
4. relevant accepted ADRs
5. relevant repository policies
6. backlog task cards
7. current code and tests related to eligible tasks

Load any skill declared by the selected task.

Do not modify or reinstall external skills.

## 2. Validate repository state

Inspect:

- the current Git branch;
- the working tree;
- `tasks/active/`;
- `tasks/review/`;
- `tasks/backlog/`;
- `tasks/completed/`;
- dependencies declared by backlog tasks.

Continue only when:

- `tasks/active/` is empty;
- `tasks/review/` is empty;
- no existing user changes would be overwritten;
- the repository has a suitable approved base branch;
- at least one backlog task has all dependencies completed.

Stop and report the blocker when:

- a task already exists in active or review;
- local changes may conflict with the selected task;
- the base branch is ambiguous or unsuitable;
- a required dependency is incomplete;
- repository state cannot be determined safely.

Do not clean, reset, revert, stash, overwrite, or discard user changes.

## 3. Select the next eligible task

Inspect all cards under `tasks/backlog/`.

Exclude tasks whose dependencies are incomplete.

Select exactly one task using this order:

1. dependencies are completed;
2. highest declared priority;
3. logical architectural order;
4. lowest task ID when otherwise equivalent.

Do not select a task only because it is easier.

Stop for owner input only when:

- two equally eligible tasks represent materially different product or
  architectural directions;
- selecting one requires a business, clinical, or product decision;
- the dependency information is contradictory.

Record the selected task and the reason for selection in the final report.

## 4. Complete the task specification

Before activation, inspect the current code, tests, documentation, ADRs, and
supported APIs relevant to the selected task.

Complete or refine the task card so it contains:

- a concrete goal;
- current repository context;
- implementation requirements;
- explicit out-of-scope items;
- an exact `Files allowed` list;
- relevant skills and references;
- a concrete implementation plan;
- verifiable acceptance criteria;
- a `## Test plan` table with one row per acceptance criterion;
- a numbered `## Manual verification` table;
- risks;
- documentation impact.

Report the test plan and the manual steps to the project owner before writing
any implementation code. See `.ai/workflows/implementation-workflow.md` and
`docs/development/testing_strategy.md`.

Keep the specification proportional to the task.

Do not expand the task into unrelated refactoring or future work.

The original `Start the next task` instruction counts as human approval for this
specification and activation when the specification follows the existing
backlog goal and does not introduce a material architectural or product change.

Stop for owner input when:

- a new architectural decision is required;
- the backlog goal is materially ambiguous;
- implementation would broaden the task substantially;
- clinical or sensitive-data decisions are required;
- the exact behavior cannot be safely inferred from current repository context.

## 5. Define the branch

Use this branch format:

`feature/<task-id>-<task-slug>`

Examples:

- `feature/BSSL-005-persistent-module-state`
- `feature/BSSL-006-algorithm-provider-boundary`

The branch must be created from the approved current `main`.

Before creating it, confirm:

- the selected dependency commits are present in `main`;
- no task exists in active or review;
- the branch name does not already represent conflicting work.

The `Start the next task` instruction explicitly authorizes branch creation and
switching for the selected task.

Do not commit or push unless separately authorized.

## 6. Activate the task

Move only the selected card:

`tasks/backlog/<task-file>.md`

to:

`tasks/active/<task-file>.md`

Update its front matter:

```yaml
status: active
branch: feature/<task-id>-<task-slug>