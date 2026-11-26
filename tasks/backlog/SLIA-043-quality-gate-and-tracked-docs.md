---
id: SLIA-043
title: Quality gate - docs tracked again, Ruff on every Python file, fast checks before push and in CI, line endings fixed
status: backlog
branch:
priority: high
depends_on:
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-043 - Quality gate - docs tracked again, Ruff on every Python file, fast checks before push and in CI, line endings fixed

## Goal

The documents the project treats as authority are under version control again.
Every Python file in the repository passes Ruff. The checks that need no Slicer
run by themselves before every push and on GitHub. Git stores every text file
with the same line endings. Nothing in the module's behaviour changes.

## Context

*Created on 2026-11-09* at the project owner's request, from the code-quality
audit of 2026-11-08 and its remediation plan, section 4
(`workspace/audits/SLIAFlow_code_quality_audit_2026-11-08.md` and
`workspace/audits/SLIAFlow_remediation_plan_2026-11-08.md`; both gitignored).
It closes findings P-01 to P-05. Facts checked at `8ac3e0a`.

**Order.** This card goes before `SLIA-042`. `SLIA-042` edits four files under
`docs/development/`, which Git ignores today, so its document changes could not
be committed. The fast checks also protect every later remediation card.

**Owner decisions of 2026-11-09:**

- **Decision 1: all of `docs/` is tracked again.** The owner said the untracking
  was an oversight ("se me olvidó"). Tracking the whole folder means a new
  document is tracked by default. An allow-list would silently leave new
  documents out, which is how P-01 happened.
- **Decision 7:** the owner left the choice to the agent ("la mejor manera
  posible que tu consideres. seguro y robusto").
  - Headless stays the default.
  - `SLIA-047` makes skips visible and makes the wrong skips fail.
  - Effective now: any change under `extensions/SLIAFlow/` needs both full runs,
    headless and headful, before the task is reported implemented. This card
    adds that rule to `testing_strategy.md`.

**P-01. `docs/` is untracked.**
- Commit `d1bbb1d` (2026-10-15) added `/docs/` to `.gitignore` and removed 29
  files from the index.
- `AGENTS.md` ranks the accepted ADRs in `docs/architecture/decisions/` second
  in authority.
- `.ai/workflows/implementation-workflow.md` step 4 and the task template send
  the reader to `docs/development/testing_strategy.md`.
- None of these exist in a fresh clone.
- Today `docs/` holds 24 files (305 KB, all Markdown plus one `.gitkeep`).
  - 21 of them are identical to their last tracked version (`598663c`).
  - Three changed after the untracking: `SLIAFLOW_IMPLEMENTATION_ROADMAP.md`,
    `SLIAFLOW_UC1_IMAGE_CONTRACT.md` and `project_structure.md`.
  - Five files were deleted locally, for example `WP5_MS5_DEMO_PLAN.md`.
- `project_structure.md` now says "`docs/` is ignored by Git (`.gitignore`), so
  these files are local and not versioned."
- A scan on 2026-11-09 found no e-mail address, no `C:\Users\` path and no
  credential-like string in `docs/`.

**Dead links.** Among the live documents (everything except the completed and
superseded cards), only one `docs/` path points nowhere:
`ADR-0001-overlay-result-on-cube-derived-rgb.md`, line 53, cites
`docs/architecture/WP5_MS5_DEMO_PLAN.md`. Two backlog cards cite files they will
create themselves: `SLIA-009` and `SLIA-041`.

**P-02. Documents behind the code:**
- `testing_strategy.md`, *Test location*: says the tests are in `SLIAFlow.py`.
  They have been in `SLIAFlowLib/SLIAFlowTest.py` since `13c9386`.
- `extensions/SLIAFlow/README.md`, lines 17-19: "No console, Python service or
  OpenIGTLink link is involved". Its own Connections section, from line 166,
  contradicts this.
- `SLIAFlow.py`, `helpText`:
  - it speaks of "a recorded public HSI case", the retired input;
  - it does not mention UC2 or the cube received from IUMA's app;
  - `SLIAFlowTest.py:163` asserts that it contains "non-clinical".
- `README_SLIAFlow_Build.md`:
  - it describes "a scaffold" with "two volume-reference selectors";
  - it gives raw `cmake` commands with absolute `C:\stratum\...` paths;
  - it never names `build-sliaflow.ps1`, `build-uc1.ps1`, `build-uc2.ps1` or
    the `check-*.py` scripts.
- `extensions/SLIAFlow/CMakeLists.txt:6`: `EXTENSION_HOMEPAGE` is
  `https://github.com/alejandrou/stratum`, but the remote is
  `https://github.com/alejandrou/SLIAFlow.git`.

**P-03. No CI and no hook.**
- There is no `.github/` folder and no hook.
- Ruff and the 64 simulator tests need no Slicer and take under a minute, but
  they run only when someone remembers to run them.
- The simulator tests read nothing from `input/` and listen only on
  `127.0.0.1` and `127.0.0.2`.

**P-04. `scripts/development` is outside Ruff.**
- Both lists that decide what Ruff checks leave it out: the `include` in
  `pyproject.toml` and `$analysisTargets` in `run-python-quality.ps1`.
- Its six Python files already pass the project's rule set (`E4`, `E7`, `E9`,
  `F`, `I`, `B`) with `py310`. Checked on 2026-11-09: `ruff check --isolated`,
  exit 0.
- `check-*.py`, `measure-uc1.py` and `uc_oracles.py` run under the `.venv`
  (Python 3.10). `measure-capture.py` runs inside Slicer (3.12). So `py310` is
  the lower bound for the whole folder.
- The repository tracks 32 Python files: 15 in the module, 6 in
  `scripts/development` and 11 in `tools/simulators`.

**P-05. Line endings.**
- There is no root `.gitattributes`.
- `tasks/completed/SLIA-006-genuine-result-presentation.md` is stored with CRLF
  in the index (`i/-text`). Lines 290-291 hold a lone CR where `\r` of
  `.\scripts\development\run-...` used to be, so Git treats the file as binary.
- Every other text file is `i/lf`. The patch folders keep their own `-text`
  rules.

## Requirements

### 1. Measure first: the remediation baseline

Before changing anything, record the baseline in
`workspace/audits/remediation-baseline/` (gitignored), following plan section 3.
Every later remediation card compares against it. Record:

1. the Ruff exit code;
2. the full headless run: totals, every skip by name and reason, and duration;
3. the full headful run, with the same details;
4. the simulator tests: totals, duration, exit code, and the count of
   `ERROR:root` and `Traceback` lines;
5. the `check-uc1.py`, `check-uc2.py` and `check-captures.py` reports;
6. the Annex B metrics JSON;
7. the test-name list.

### 2. `docs/` is tracked again

- Remove `/docs/` from `.gitignore`.
- Before anything is staged, repeat the scan. Every file under `docs/` must be:
  - a text file;
  - free of e-mail addresses, `C:\Users\` paths, credential-like strings and
    patient identifiers.

  List the files and their sizes for the owner. Staging follows only when the
  owner authorizes the commit.
- `project_structure.md`: replace the sentence saying `docs/` is not versioned
  with one saying it is.
- `ADR-0001`, line 53: after the path, add "(removed; last version in commit
  `598663c`)". The text changes; the decision does not.
- No live document may cite a `docs/` file that does not exist. The exceptions
  are the completed and superseded cards, which are historical records, and
  the files that `SLIA-009` and `SLIA-041` will create.

### 3. Documents describe the current code

- **`testing_strategy.md`, *Test location*:** the tests live in the
  `SLIAFlowTest` class in `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`,
  which `SLIAFlow.py` imports. Slicer requires the class to be named
  `<ModuleName>Test` and to be importable from the module file.
- **`testing_strategy.md`, *Which runs are needed when* (decision 7):**
  - Before reporting a task implemented: the full headless run **and** the
    full headful run whenever the task changes any file under
    `extensions/SLIAFlow/`.
  - Before every push: `run-fast-checks.ps1`.
  - The 2026-10-07 row, "when the task touches the layout, the panels or
    rendering", is replaced. Record the date of the change and why.
- **`testing_strategy.md`, *Static analysis*:** the three Ruff targets and the
  coverage check (requirement 4). Add a *Fast checks* section (requirement 5).
- **`extensions/SLIAFlow/README.md`, lines 17-19:** "The Capture workflow itself
  needs no console or Python service. The optional Connections section receives
  frames and cubes from IUMA's acquisition app over OpenIGTLink."
- **`SLIAFlow.py`, `helpText` only:**
  - it names UC1 tumour classification and UC2 vessel enhancement;
  - it says the run uses a recorded IUMA LCTF capture or the last cube received
    from IUMA's app, and that the output images are shown as written;
  - it keeps "non-clinical" and "does not interpret diagnostic images".
- **`README_SLIAFlow_Build.md`, rewritten:**
  - prerequisites from `config/local.json` (template
    `config/local.example.json`);
  - `build-sliaflow.ps1` (with `-Configure` the first time);
  - `build-uc1.ps1` and `build-uc2.ps1`, linking `uc1_local_build.md` and
    `uc2_local_build.md`;
  - the `check-*.py` scripts;
  - the test scripts, `run-fast-checks.ps1` and the hook;
  - repository-relative paths only, with no "scaffold" and no "two
    volume-reference selectors";
  - the raw `cmake` calls, if kept, go in an appendix "What
    `build-sliaflow.ps1` does".
- **`CMakeLists.txt:6`:** `EXTENSION_HOMEPAGE "https://github.com/alejandrou/SLIAFlow"`.
  The owner confirms the URL at approval.

### 4. Ruff covers every Python file

- **New `scripts/development/ruff.toml`:** `target-version = "py310"` and the
  same `[lint] select` as `tools/simulators/ruff.toml`.
- **Add the folder to both lists:** `"scripts/development/**/*.py"` to the
  `include` of `pyproject.toml`, and `"scripts/development"` to
  `$analysisTargets` in `run-python-quality.ps1`.
- **Coverage check at the end of `run-python-quality.ps1`.** The two lists must
  not drift apart again.
  - Compare `git ls-files --cached --others --exclude-standard -- "*.py"`
    (tracked files, plus new ones that are not ignored) with the union of
    `ruff check --show-files` over the targets.
  - Exit nonzero, naming every Python file that no target analysed.
- **Install hints:** `coding_standards.md` (the Ruff paragraph, lines 29-32)
  and the hint in `run-python-quality.ps1` (line 57) name the three targets
  and the pinned install (requirement 5).

### 5. Fast checks before push and in CI

- **New `scripts/development/run-fast-checks.ps1`:**
  - Runs, in order:
    1. `run-python-quality.ps1`;
    2. `.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`.
  - Stops at the first failure.
  - Prints each step's result and duration.
  - Exits 0 only when every step passed.
  - If `.venv` is missing, it fails and prints the setup commands.
  - Needs no Slicer.
  - `SLIA-046` and `SLIA-050` add their own steps.
- **New `tools/simulators/requirements-dev.txt`:** `ruff==0.15.21`.
  - Dependency policy: Ruff is not a new tool. This pins the version already
    in the `.venv` so that CI and local runs agree.
  - The owner approves this pin with the card.
- **New `scripts/git-hooks/pre-push`:**
  - A POSIX `sh` script that runs `run-fast-checks.ps1` with `pwsh`, falling
    back to `powershell.exe -ExecutionPolicy Bypass`, and returns its exit code.
  - It is kept with LF line endings (requirement 6).
  - The owner activates it in their clone with
    `git config core.hooksPath scripts/git-hooks`. The agent does not change
    Git configuration.
- **New `.github/workflows/fast-checks.yml`:**
  - Triggers: `push` and `pull_request`.
  - Runner: `windows-latest`, because the scripts are PowerShell and five
    transport tests need the Windows TCP table (`needsWindowsTcpTable`).
  - Steps:
    1. `actions/checkout@v4`;
    2. `actions/setup-python@v5` with Python `3.10`;
    3. `python -m venv .venv`;
    4. install `tools/simulators/requirements.txt` and `requirements-dev.txt`;
    5. `.\scripts\development\run-fast-checks.ps1`.
- **Documentation:** `testing_strategy.md`, `README_SLIAFlow_Build.md` and the
  install line of `tools/simulators/README.md`.

### 6. One line-ending rule

- **New root `.gitattributes`:**

  ```gitattributes
  # Text files are stored with LF; the working tree follows core.autocrlf.
  * text=auto
  # Git's sh runs the hooks: they keep LF in the working tree too.
  scripts/git-hooks/* text eol=lf
  ```

  The `-text` rules in `uc1-patches/` and `uc2-patches/` are more specific and
  stay as they are.
- **`SLIA-006` lines 290-291:** restore the `\r` with a byte-level edit that
  never types a backslash literally (`bytes([92])`, plan section 4, step 5).
  Afterwards the file holds no lone CR. Nothing else in that card changes.
- **At commit time, with authorization:**
  - run `git add --renormalize .`;
  - mark the hook executable in the index:
    `git update-index --chmod=+x scripts/git-hooks/pre-push`.

### 7. Nothing else changes

- The full headless run gives the baseline's totals, names and skips.
- The full headful run does too.
- So does the built module's headful run after a rebuild.

## Out of scope

- Making the test runner list skips and fail on the wrong ones: decision 7,
  points 1-4, in `SLIA-047`.
- The `docs/` path in the `SLIAFlow.ui` tooltip, and comments used as a change
  log (P-06): `SLIA-048`.
- P-07, the duplication in `AGENTS.md`. It is low severity and needs the
  owner's approval to edit `AGENTS.md`. It can be added at approval.
- Script tests and the pure-Python module suite inside the fast checks:
  `SLIA-046` and `SLIA-050`.
- Running the Slicer tests in CI, which needs a Slicer build.
- Dead links inside completed and superseded cards.
- Restoring any document deleted from `docs/`.
- Any change to module behaviour, UC1, UC2 or the simulators' code.
- Owner actions:
  - activating the hook;
  - enabling GitHub Actions;
  - pushing;
  - committing.

## Files allowed

- `.gitignore`
- `.gitattributes` (new)
- `pyproject.toml`
- `.github/workflows/fast-checks.yml` (new)
- `scripts/development/ruff.toml` (new)
- `scripts/development/run-python-quality.ps1`
- `scripts/development/run-fast-checks.ps1` (new)
- `scripts/git-hooks/pre-push` (new)
- `tools/simulators/requirements-dev.txt` (new)
- `tools/simulators/README.md` (install line only)
- `extensions/SLIAFlow/README.md`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py` (`helpText` only)
- `extensions/SLIAFlow/CMakeLists.txt` (`EXTENSION_HOMEPAGE` only)
- `README_SLIAFlow_Build.md`
- `docs/development/testing_strategy.md`
- `docs/development/project_structure.md`
- `docs/development/coding_standards.md` (the Ruff paragraph only)
- `docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md`
  (line 53 only)
- `tasks/completed/SLIA-006-genuine-result-presentation.md` (lines 290-291 and
  line endings only)
- `workspace/audits/remediation-baseline/` (new, gitignored)
- this card

## Relevant skills and references

- No skill: Markdown, PowerShell, Git configuration and one string in each of
  `SLIAFlow.py` and `CMakeLists.txt`.
- The remediation plan, sections 0, 3 and 4, and Annex B (metrics script).
- `.ai/policies/dependency-policy.md` (the Ruff pin).
- `.ai/policies/git-workflow.md` (One Evolving Commit; staging needs
  authorization).
- `docs/development/testing_strategy.md`, *Which runs are needed when*.

## Implementation plan

1. **Baseline.** Record requirement 1. Use only the existing scripts; change
   nothing.
2. **Red evidence**, before any change. Record each output:
   - `git check-ignore -v docs/development/testing_strategy.md` prints the
     `/docs/` rule and exits 0;
   - a temporary `extensions/SLIAFlow/probe_unlinted.py` holding `import os`
     leaves `run-python-quality.ps1` at exit 0;
   - so does a temporary `scripts/development/probe_unlinted.py`;
   - `git ls-files --eol` shows `i/-text` for `SLIA-006`;
   - delete the probes afterwards.
3. **`docs/` (requirement 2).**
   1. `.gitignore`.
   2. The scan.
   3. `project_structure.md`.
   4. `ADR-0001`.
   5. The link check over the live documents.
4. **Ruff (requirement 4).**
   1. `ruff.toml`, `pyproject.toml` and the targets.
   2. The coverage check.
   3. The two install hints.
   4. Repeat the probes from step 2: both now fail. The first is named as
      unanalysed; the second fails on `F401`.
5. **Fast checks (requirement 5).**
   1. The script.
   2. The pin.
   3. The hook.
   4. The workflow.
   5. Their documentation.
   6. Probe again: a lint error makes `run-fast-checks.ps1` stop at step 1,
      exit nonzero and never start the simulator tests.
6. **Documents (requirement 3).**
7. **Line endings (requirement 6).**
   1. `.gitattributes`.
   2. The `SLIA-006` byte fix.
   3. Python check that it holds no lone CR.
8. **Normalize line endings in the working tree** of every touched file to
   CRLF, except `scripts/git-hooks/pre-push`, which stays LF. Check with Python
   on bytes.
9. **Checks:**
   1. `run-fast-checks.ps1`.
   2. The full headless and full headful runs.
   3. `build-sliaflow.ps1`, then `run-slicer-tests.ps1 -Target Build -Headful`.
   4. Compare all of them with the baseline.
10. **Report** the test plan results and the manual steps.
11. **After review, with commit authorization:**
    1. stage;
    2. run `git add --renormalize .`;
    3. run `git update-index --chmod=+x scripts/git-hooks/pre-push`;
    4. check `git ls-files --eol`;
    5. commit.

## Acceptance criteria

1. `workspace/audits/remediation-baseline/` holds the seven baseline items of
   requirement 1. Each records the command, its totals and its exit code.
2. `git check-ignore -v docs/development/testing_strategy.md` prints nothing and
   exits 1. `git ls-files --others --exclude-standard docs` lists every file
   under `docs/`.
3. The scan of `docs/` finds no e-mail address, no `C:\Users\` path, no
   credential-like string and no non-text file. The file list with sizes is in
   the completion evidence.
4. No live document cites a `docs/` file that does not exist, apart from the
   two files the `SLIA-009` and `SLIA-041` cards will create. `ADR-0001`
   line 53 names the commit that last held `WP5_MS5_DEMO_PLAN.md`.
5. The documents named in requirement 3 match the code:
   - *Test location* names `SLIAFlowLib/SLIAFlowTest.py`;
   - the module README no longer says that no OpenIGTLink link is involved;
   - `helpText` names UC1, UC2 and the app's cube, and still contains
     "non-clinical";
   - `README_SLIAFlow_Build.md` uses the scripts and relative paths, and has no
     "scaffold";
   - `EXTENSION_HOMEPAGE` is the remote's repository.
6. *Which runs are needed when* requires both full runs, headless and headful,
   for any change under `extensions/SLIAFlow/`, and `run-fast-checks.ps1`
   before every push.
7. `run-python-quality.ps1` lints three targets and exits 0 on the clean tree.
   - A Python file outside every target makes it exit nonzero and name that
     file.
   - A lint error in `scripts/development` makes it exit nonzero.
8. `run-fast-checks.ps1` exits 0 on the clean tree and prints both steps with
   their durations. When a step fails, it stops there and exits nonzero.
9. With Git's `sh`, `scripts/git-hooks/pre-push` returns the exit code of
   `run-fast-checks.ps1`: 0 on the clean tree, nonzero with a lint error.
10. `.github/workflows/fast-checks.yml` passes on the pushed task branch.
11. `.gitattributes` holds the rules of requirement 6, and `SLIA-006` holds no
    lone CR. After `git add --renormalize .`:
    - `git ls-files --eol` shows `i/lf` for every text file;
    - only the `-text` patch files and empty files show anything else;
    - `SLIA-006`'s diff is shown as text.
12. The full headless run and the full headful run match the baseline: same
    totals, names and skips. After `build-sliaflow.ps1`,
    `run-slicer-tests.ps1 -Target Build -Headful` passes.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1 | Listing of `workspace/audits/remediation-baseline/` and its contents | scripted |
| 2 | `git check-ignore -v ...` (red before: `/docs/` rule, exit 0) and `git ls-files --others --exclude-standard docs` | scripted |
| 3 | Scan with the Grep tool over `docs/`; `Get-ChildItem docs -Recurse` for the sizes | scripted |
| 4 | Link check: every `docs/...md` path in the live files resolved on disk | scripted |
| 5 | Reading each document against the code; `SLIAFlowTest.test_moduleMetadataAndUi` (its existing `helpText` assertion, line 163); manual step 1 | manual |
| 6 | Reading `testing_strategy.md` | manual |
| 7 | Probe files of implementation step 2: red before (exit 0), red after (exit nonzero, file named); clean tree exit 0 | scripted |
| 8 | `run-fast-checks.ps1` on the clean tree and with a lint probe | scripted |
| 9 | `sh scripts/git-hooks/pre-push`, clean and with a lint probe; manual step 3 | scripted |
| 10 | Manual step 4 | manual |
| 11 | Python byte check on `SLIA-006`; `git ls-files --eol` and `git diff --cached --stat` after renormalizing (needs commit authorization) | scripted |
| 12 | `run-slicer-tests.ps1`, `run-slicer-tests.ps1 -Headful`, `build-sliaflow.ps1`, then `run-slicer-tests.ps1 -Target Build -Headful`, compared with the baseline | automated |

Tests to add or change, and how each one will be shown to fail first:

- **No Slicer test is added or changed.** Nothing in the module's behaviour
  changes, so the proof is that both runs match the baseline (criterion 12).
- **The Ruff coverage check and the `scripts/development` target** are shown
  red first by the probe files of implementation step 2. Today, both probes
  leave the script at exit 0.
- **`run-fast-checks.ps1` and the hook** are new. They are shown failing with a
  lint probe: a mutation, then reverted.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run `build\SLIAFlow\SlicerWithSLIAFlow.exe`, open SLIAFlow, expand *Help & Acknowledgement* | The help text names UC1, UC2, a recorded IUMA capture or the app's cube, and says the module is non-clinical |  |
| 2 | In a new PowerShell console, follow `README_SLIAFlow_Build.md` from the build section to the tests, typing each command as written | Every command runs as written from the repository root; none needs a path the README does not give |  |
| 3 | Owner: run `git config core.hooksPath scripts/git-hooks`, then push the task branch when authorized | Before the push leaves, the console shows the fast checks running both steps; the push goes ahead only after they pass |  |
| 4 | Owner: on GitHub, open *Actions* for the pushed branch | The `fast-checks` run is green, and its log shows Ruff on three targets and the simulator tests |  |
| 5 | On GitHub, open `docs/architecture/decisions/` on the pushed branch | The seven ADRs are there |  |

Steps 3-5 need a push. If the owner prefers not to push before review, they
move to after approval and the card records that.

## Risks

- **Publishing `docs/`.** Pushing makes `docs/` visible to whoever can see the
  repository. The 21 unchanged files are already in its history; the three
  changed ones are new content. The scan and the owner's commit authorization
  are the gate.
- **CI on a hosted runner.** The image changes over time, and the simulator
  tests have timing assumptions (audit S-06). A flaky test shows up as a red
  run. Record it with the run link; the fix belongs to `SLIA-045`.
  - Mitigations: Python 3.10 matches the `.venv` minor version, Ruff is pinned,
    and the actions are pinned to major versions.
- **The hook adds about a minute to each push.** `git push --no-verify`
  bypasses it. CI still runs.
- **The hook needs LF line endings.** With CRLF, `sh` reads `exec ...\r` and
  fails. The `.gitattributes` rule and the Python byte check of step 8 guard
  this.
- **Renormalizing rewrites `SLIA-006` in the index** from CRLF to LF, which
  shows as a whole-file diff. Every other file is already `i/lf`.
- **Line endings in the working tree.** Write and Edit leave LF. Step 8
  normalizes to CRLF; `.gitattributes` does not change how this machine checks
  files out.

## Documentation impact

- `README_SLIAFlow_Build.md`
- `extensions/SLIAFlow/README.md`
- `testing_strategy.md`: *Test location*, *Static analysis*, *Which runs are
  needed when*, and the new *Fast checks*
- `project_structure.md`
- `coding_standards.md`
- `tools/simulators/README.md`
- `ADR-0001`, line 53

## Completion evidence

## Review findings

## Human approval
