# Project Structure

This repository contains the SLIAFlow-related 3D Slicer development prototype. It is not production clinical software.

## Top-Level Areas

- `AGENTS.md`: Codex routing, repository source-of-truth order, and edit-scope rules.
- `.ai/`: authoritative policies, workflows, and templates for repository work.
- `tasks/`: active, review, backlog, and completed task cards.
- `docs/`: developer and technical documentation.
- `config/`: portable local configuration template and ignored local configuration.
- `extensions/`: SLIAFlow-specific Slicer extension and module source.
- `scripts/`: developer automation for building, testing, and running the project.
- `tools/`: standalone developer processes that are not part of the Slicer extension.
- `source/`: local upstream Slicer source reference.
- `apps/`: local Slicer application and build outputs.
- `workspace/`: temporary work, experiments, scripts, and local generated artifacts.
- `knowledge/`: ignored local reference material, downloaded files, and private working notes.

For exact edit permissions, follow `AGENTS.md` and the active task card.

## Development Code

SLIAFlow extension development occurs under:

```text
extensions/SLIAFlow/
```

The current scripted module lives under:

```text
extensions/SLIAFlow/SLIAFlow/
```

Keep final module source in `extensions/`, not in `workspace/`.

## OpenIGTLink Transport

```text
tools/simulators/
```

`tools/simulators/` holds the OpenIGTLink transport kept from the retired
stand-in processes (`SLIA-028`): building messages whose metadata reaches the
wire, refusing a port another process holds, and watching clients. It is the
base for the stand-in that imitates IUMA's acquisition app (`SLIA-035`). It is
not Slicer code: nothing under it imports `slicer`, and it runs under the
repository-root `.venv` rather than inside Slicer's interpreter.

Its dependencies are pinned in `tools/simulators/requirements.txt` and are
never added to `extensions/SLIAFlow/SLIAFlow/Resources/requirements.txt`, which
is the Slicer-runtime file. Its tests run under the standard-library `unittest`
runner, not the Slicer test runner. See `tools/simulators/README.md`.

## Local Slicer Source And Build Outputs

The local Slicer source tree under `source/` is used as a reference for Slicer APIs, MRML, Qt, VTK, ITK, CMake, and extension examples.

The local build tree under `apps/` is generated output. The conventional build location for this workspace is `apps/SR/`, with the executable under `apps/SR/Slicer-build/`.

Machine-specific paths should be configured in `config/local.json`, using `config/local.example.json` as the template.

## Documentation

- `docs/development/`: project structure, coding standards, and testing strategy.
- `docs/slicer/`: reusable Slicer technical notes.
- `docs/architecture/decisions/`: accepted ADRs.
- `docs/knowledge/`: curated, non-sensitive, version-controlled reference notes useful to the project.

## Task And Workflow Files

Current work is tracked under `tasks/`.

Repository policies and workflows live under `.ai/`. Do not duplicate complete policies or workflows in development documentation; link to the authoritative file instead.
