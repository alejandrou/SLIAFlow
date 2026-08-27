---
id: BSSL-008
title: Persist and summarize mock workflow results
status: superseded
branch:
priority: medium
depends_on: BSSL-007
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# BSSL-008 - Persist and summarize mock workflow results

> Superseded on 2026-08-26. Mock diagnostic result persistence and reporting are
> not part of the approved SLIAFlow Slicer demonstrator.

## Goal

Persist approved mock workflow results in the Slicer scene and provide a concise development-oriented result summary or report.

## Context

BSSL-007 establishes a complete mock workflow, but its result ownership, scene persistence, provenance, and reporting boundary remain undefined. These concerns should be addressed together only after the workflow is stable.

## Requirements

- Define result ownership in MRML.
- Define scene save/load behavior and stale-result handling.
- Preserve metadata and provenance, including mock/demo status.
- Define a concise development-oriented summary or report/export boundary.
- Add automated tests and manual verification for persistence and stale results.

## Out of scope

- Clinical reporting, clinical interpretation, or clinical claims.
- Persistence of unvalidated results.
- A general reporting framework or integration with external clinical systems.

## Files allowed

Likely areas include result/MRML state support, the mock workflow UI, tests, and focused documentation. Exact files and any architectural implications require approval during specification.

## Relevant skills and references

- Slicer skill for MRML ownership, scene save/load, and verification.
- Dependency: BSSL-007.
- `.ai/policies/algorithm-boundary-policy.md`
- `.ai/policies/medical-data-policy.md`

## Implementation plan

To be defined during specification after result ownership, provenance fields, stale-result rules, and report boundary are approved.

## Acceptance criteria

- Approved mock results persist and reload predictably with required provenance.
- Stale, missing, or invalid results are identified and are not presented as current success.
- The summary/report is concise, development-oriented, and explicitly non-clinical.
- Automated tests and manual Slicer verification cover save/load and stale-result behavior.

## Test plan

To be defined during specification; it must include valid persistence, scene reload, stale input/result, invalid result, and missing-result cases.

## Manual verification

Run the approved mock workflow in Slicer, save and reload a scene, inspect provenance and stale-result handling, verify the summary/report, and use Reload and Reload and Test.

## Risks

Persistence can make stale or malformed output appear authoritative. Ownership, validation, provenance, and display rules must be agreed before implementation.

## Documentation impact

Document only the approved development result format, provenance, and report/export boundary. Do not describe it as clinical reporting.

## Completion evidence

Reserved for implementation, automated-test, manual-verification, review, and approval evidence.

## Review findings

Reserved for later independent review.

## Human approval

Required before specification is activated and before implementation begins.
