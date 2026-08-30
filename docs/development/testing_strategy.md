# Testing Strategy

This document defines how SLIAFlow Slicer code is tested and what counts as
evidence. The per-task procedure lives in the task card; the manual procedure
lives in `.ai/workflows/manual-verification-workflow.md`.

## The three levels

Each level proves something the others cannot. None of them replaces another.

| Level | Tool | Runs in | Proves | Cannot prove |
| --- | --- | --- | --- | --- |
| Static analysis | Ruff | Plain Python, seconds | Undefined names, shadowed imports, unused imports, mutable default arguments | Any behaviour |
| Automated tests | `SLIAFlowTest` | Real Slicer, real MRML | That the module still behaves as specified | That anything is legible on screen |
| Manual verification | A person in Slicer | Real Slicer with a window | That the operator can actually see and use it | Nothing, repeatably |

While SLIAFlow is presentation-only, manual verification carries most of the
weight, so every task must define it explicitly.

### Why there is no static type checker

A static type checker was evaluated on this codebase and removed. Slicer's C++
application injects `slicer.app`, `slicer.util`, `slicer.mrmlScene`, the
`vtkMRML*` classes, and the VTK bindings into the module namespace at runtime.
A type checker therefore has two possible outcomes, both useless here:

- It cannot resolve `slicer` and `vtk`. Every expression that touches them
  becomes an unknown type and is not checked, which is nearly the whole module.
  A clean report then means the checker examined almost nothing.
- It is pointed at a real Slicer installation so the imports resolve. It then
  reports the runtime-injected attributes as errors. The measured result was
  52 errors, all false positives.

Do not reintroduce one without new evidence that this has changed. Ruff has no
such problem because it reasons about names and syntax rather than about the
contents of external modules. Ruff also earns its place empirically: it caught
an `F402` shadowed-import defect in module code that a fully passing test suite
had accepted.

## Rules for a solid test

These rules exist because a passing test that cannot fail is worse than no
test. It produces false confidence and hides the regression it was written to
catch.

1. **Every test must be observed failing before it is accepted.** Run a new or
   changed test against the code as it was before the change and record the
   actual failure message in the task card's completion evidence. A test never
   seen red is not evidence and must not be reported as coverage.
2. **Assert the acceptance criterion, not the implementation.** If the
   criterion is that the operator sees a message, assert what reaches the
   renderer, not that a variable was assigned. Reading a value back in the same
   call stack that wrote it proves only that Python assignment works.
3. **Let the event loop run before asserting anything user-visible.** Slicer
   observers, including the DataProbe slice-view annotations, react only once
   the event loop turns. An assertion made before that can pass against a view
   that displays nothing.
4. **Never write an expected value as a literal that duplicates a constant.**
   Import the constant and compare against it, so that renaming the constant
   breaks the test instead of silently orphaning it.
5. **Never copy an expected value out of observed output without knowing why it
   has that value.** If the reason cannot be stated in one sentence, the test
   records current behaviour rather than required behaviour, and it will pass
   through the next real defect.
6. **One behaviour per test.** Tests must be independent and must not depend on
   execution order. `setUp` clears the MRML scene.
7. **Synthetic data only.** See `.ai/policies/medical-data-policy.md`.

## Traceability

Every task card fills in `## Test plan` before implementation, as a table
mapping each acceptance criterion to how it is verified:

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| The result pane shows the waiting message | `SLIAFlowTest.test_layoutContractAndLifecycle` | automated |
| The message is legible over the dark view | Manual step 4 | manual |

Rules:

- No acceptance criterion may be left without a row.
- A criterion verified manually must name a numbered step in the card's
  `## Manual verification` section rather than only saying "manual".
- Writing the test plan before the implementation is what keeps tests derived
  from the specification instead of reverse-engineered from whatever the code
  happened to do.

## Test discovery

`SLIAFlowTest` derives `moduleTestNames` from `unittest.TestLoader`, so Slicer's
`Reload and Test` button and the command-line runner execute exactly the same
set of test methods. Do not hand-maintain a list of test names and do not
override `runTest`: a hand-written list silently omits any test method that is
forgotten, and the two execution paths then disagree about what "all tests
pass" means.

The command-line runner reports one test more than `SLIAFlowTest` defines.
Slicer requires `ScriptedLoadableModuleTest` to be imported into the module
namespace, so `unittest` discovers the imported base class as well and runs its
inherited `runTest`, which finds no test names and returns. It is expected and
always passes; only the `SLIAFlowTest.test_*` entries are project coverage.

## Test location

The tests live in the `SLIAFlowTest` class in
`extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`. Slicer requires the test case class
to be named `<ModuleName>Test` and to be importable from the module file, and
the `Reload and Test` button depends on that. Split the tests into a separate
file only once a logic layer exists that is worth testing without the widget.

## Running the tests

### Static analysis

```powershell
.\scripts\development\run-python-quality.ps1
```

The script resolves Ruff from the ignored root `.venv` first and from `PATH`
second, prints the executable it used and its version, and exits nonzero when
Ruff is missing or reports a finding. It never passes silently because the tool
could not be found.

### Automated tests against the working tree

```powershell
.\scripts\development\run-slicer-tests.ps1
```

This is the default, equivalent to `-Target Source`. It launches the Slicer
executable configured in `config/local.json` with `--additional-module-paths`
pointing at `extensions/SLIAFlow/SLIAFlow`, so it exercises the files currently
being edited.

Before running any test, the runner prints the path the `SLIAFlow` module was
actually loaded from and fails if that path is not the one the selected target
requires. This guard exists because `build\SLIAFlow\SlicerWithSLIAFlow.exe`
carries its own built-in copy of the scripted module, and that copy shadows
`--additional-module-paths`. Without the guard, a stale build produced a green
run that said nothing about the working tree.

### Automated tests against the compiled extension

```powershell
.\scripts\development\run-slicer-tests.ps1 -Target Build
```

Uses `build\SLIAFlow\SlicerWithSLIAFlow.exe` and asserts that the module was
loaded from `build\SLIAFlow`. Use this to check a build, not to check an edit.

CTest covers the same compiled copy. Reconfigure the standalone extension build
first, then list and run:

```powershell
ctest --test-dir "C:\stratum\build\SLIAFlow" -C Release -N
ctest --test-dir "C:\stratum\build\SLIAFlow" -C Release -R "^py_SLIAFlow$" --output-on-failure
```

The listing includes `py_nomainwindow_qSlicerSLIAFlowModuleGenericTest`, the
generic Slicer module test, and `py_SLIAFlow`, the `SLIAFlowTest` methods. CTest
is registered against the standalone SLIAFlow extension build under
`build\SLIAFlow`, not against the upstream Slicer SuperBuild under `apps\SR`.

### Interactive development

1. Edit code under `extensions/SLIAFlow/`.
2. Open the Slicer executable configured in `config/local.json`.
3. Enable Developer Mode.
4. Open the SLIAFlow module and use `Reload` or `Reload and Test`.
5. Fix errors and repeat.

Rebuild Slicer only when C++, CMake, generated wrapping, or dependency changes
require it.

### Refreshing the launcher

Run this whenever you want `build\SLIAFlow\SlicerWithSLIAFlow.exe` to show
your edits: before a demonstration, before manual verification, and before
`run-slicer-tests.ps1 -Target Build`.

1. Edit and test against the working tree as above.
2. Run `.\scripts\developmentuild-sliaflow.ps1` from the repository root.
3. Read the `Verify` section; every module file must be listed as `ok`.
4. On `not deployed`, add that file to `MODULE_PYTHON_SCRIPTS` or
   `MODULE_PYTHON_RESOURCES` in the module `CMakeLists.txt` and run it again.
5. Start the launcher, or pass `-Launch` to have the script start it.

Add `-Configure` only after deleting `build\SLIAFlow` or changing the Slicer
build named in `config/local.json`; adding, renaming, or deleting module files
does not need it. The script rebuilds the deployed copy from scratch on every
run and then compares both trees by SHA-256, so a green run is evidence that
the launcher runs the files you just edited.

## What to test first

When the module gains behaviour beyond presentation, prioritise:

1. Logic functions.
2. Data validation.
3. Coordinate conversions.
4. Input and output behaviour.
5. Error handling.

Test GUI wiring only where the task's acceptance criteria are themselves about
the UI, which is currently the case.

## Test data

Use synthetic data, public Slicer sample data, anonymised data, mock results, or
explicitly approved public medical data. Basic tests must never require private
patient data. `.ai/policies/medical-data-policy.md` is authoritative.
