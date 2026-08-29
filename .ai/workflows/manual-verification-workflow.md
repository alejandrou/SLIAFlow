# Manual Verification Workflow

Manual verification is required when a task affects Slicer behavior or user-visible workflow.

Machine-specific Slicer paths must come from `config/local.json`, using `config/local.example.json` as the portable template.

Manual verification is the only level that can prove something is actually
visible and usable. While SLIAFlow is presentation-only it carries most of the
verification weight, so its steps must be written down rather than improvised.

## Slicer Verification

For normal Python scripted-module changes:

1. Open the Slicer executable configured by `config/local.json`.
2. Enable Developer Mode if needed.
3. Open the relevant module.
4. Use Reload or Reload and Test.
5. Follow the numbered steps in the task card's `## Manual verification` table.
6. Record the observed result for every step in that table.

## Writing the manual steps

Codex writes the steps; the project owner performs them. A usable step:

- can be followed by someone who has not read the code;
- names the exact control, view, or label to look at;
- states one observable outcome, not an internal state;
- is worded so that a wrong result is recognisable, not only a right one.

Use the table from `.ai/templates/task-template.md`:

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Open SLIAFlow from the STRATUM category | The two-pane layout replaces the current layout | |
| 2 | Read the right-hand pane | The waiting message is visible and legible | |

Rules:

- Every acceptance criterion marked `manual` in the task card's `## Test plan`
  points at a step number in this table.
- Leave the `Result` column empty until a person has actually performed the
  step. It is filled in with what was observed, not with the word "pass".
- Include at least one step that would reveal the failure the change is meant
  to prevent. A checklist that only confirms the happy path proves little.
- Include the last step of every task that changes the layout: leave the module
  and confirm the previous layout is restored.

## Automated coverage first

Do not use a manual step to cover something an automated test can assert.
Manual steps are for what only a person can judge: visibility, legibility,
placement, responsiveness, and whether the workflow makes sense. Rules for the
automated side live in `docs/development/testing_strategy.md`.

## Documentation-Only Verification

For documentation-only changes, manual verification may be limited to checking links, paths, task status, and whether the written procedure is understandable.

MCP evidence may supplement this workflow only when allowed, but it never replaces manual user verification.
