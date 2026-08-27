# SLIAFlow

This repository is the active Windows 11 SLIAFlow-related 3D Slicer development project and prototype. It is not the upstream 3D Slicer repository and is not production clinical software.

## Repository Layout

- `AGENTS.md`: entry point and routing rules for Codex.
- `.ai/`: current policies, workflows, and templates.
- `tasks/`: current task cards, review state, and completion evidence.
- `docs/development/`: project structure, coding, testing, and local development guidance.
- `docs/slicer/`: reusable 3D Slicer technical notes for this project.
- `docs/knowledge/`: curated, non-sensitive, version-controlled reference notes.
- `extensions/`: SLIAFlow-specific Slicer extension and module development.
- `source/`: local upstream Slicer source reference.
- `apps/`: local Slicer application/build outputs.
- `workspace/`: temporary work, experiments, scripts, and generated local artifacts.
- `knowledge/`: ignored local reference material, downloaded files, and private working notes.
- `config/`: portable local configuration template and ignored machine-specific configuration.

## Development Entry Points

Extension development happens under `extensions/`.

Local Slicer build instructions are in `README_SLIAFlow_Build.md`.

Project structure, coding guidance, and testing guidance are in `docs/development/`.

3D Slicer module architecture and scripted-module notes are in `docs/slicer/`.

See the approved [STRATUM demonstrator implementation roadmap](docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md).

See the [cleanup checklist and immediate development steps](docs/SLIAFLOW_CLEANUP_AND_NEXT_STEPS.md).

Codex must start from `AGENTS.md`. Current work is tracked under `tasks/`.
