# Task Lifecycle Workflow

Every task uses this lifecycle:

`BACKLOG -> SPECIFICATION -> HUMAN APPROVAL -> ACTIVE -> IMPLEMENTATION -> FAST AUTOMATED TESTS -> MANUAL VERIFICATION -> REVIEW -> INDEPENDENT AI REVIEW -> HUMAN APPROVAL -> COMPLETED`

## Rules

- Use `.ai/templates/task-template.md` for every task.
- Keep exactly one task across `tasks/active/` and `tasks/review/` combined.
- Keep complex work split into smaller tasks instead of inventing alternate task types.
- Do not start a new implementation task until the current task is completed or explicitly returned to backlog.
- Preserve traceability between task cards, ADRs, code, tests, manual verification, review findings, and completion evidence.

## Directory Meaning

- `tasks/backlog/`: approved or proposed work not currently being implemented.
- `tasks/active/`: the single task currently being implemented.
- `tasks/review/`: the single task awaiting independent review or human approval.
- `tasks/completed/`: finished tasks with completion evidence.
- `tasks/superseded/`: preserved historical cards that have been replaced by an
  approved roadmap. These cards are never eligible for activation.
