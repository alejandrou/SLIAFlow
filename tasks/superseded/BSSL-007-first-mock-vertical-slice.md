---
id: BSSL-007
title: Implement the first mock vertical slice
status: superseded
branch:
priority: high
depends_on: BSSL-006
required_skills: [slicer]
optional_tools: []
related_adrs: []
---

# BSSL-007 - Implement the first mock vertical slice

> Superseded on 2026-08-26. The approved demonstrator uses a real laptop-camera
> feed and keeps the result view black until genuine UC1 output is available.

## Goal

Implement the first complete non-clinical workflow from selected Slicer input, through a mock provider, to validated and clearly labeled output.

## Context

BSSL-006 defines the provider boundary. This task should prove the boundary end to end with a deliberately mock workflow before any real SLIAFlow-related algorithm is considered.

## Requirements

- Support input selection and a clear execution state.
- Invoke the mock provider through the approved boundary.
- Validate the returned result before display or scene mutation.
- Present a user-visible result with explicit mock/non-clinical labeling.
- Handle provider errors, invalid results, and cancellation.
- Add automated tests and document manual Slicer verification.

## Out of scope

- Selecting, implementing, or integrating a real SLIAFlow algorithm.
- Clinical interpretation, validation, reporting, or claims.
- Expanding the workflow beyond the smallest approved vertical slice.

## Files allowed

Likely areas include the module UI/controller, mock provider integration, result validation, tests, and focused documentation. The exact allowlist requires inspection and approval during specification.

## Relevant skills and references

- Slicer skill for module UI, MRML interaction, and Reload / Reload and Test verification.
- Dependency: BSSL-006.
- `.ai/policies/algorithm-boundary-policy.md`
- `.ai/policies/medical-data-policy.md`

## Implementation plan

To be defined during specification after the approved provider contract and smallest user workflow are confirmed.

## Acceptance criteria

- A selected synthetic input can be processed by the mock provider and produce a validated, visible, explicitly labeled result.
- Execution, error, invalid-result, and cancellation states are understandable.
- Automated tests and manual Slicer verification cover the complete path.

## Test plan

To be defined during specification; it must include successful, invalid, failed, cancelled, and no-input cases.

## Manual verification

Run the mock workflow in Slicer with synthetic data, verify labels and state transitions, exercise failure paths, then use Reload and Reload and Test.

## Risks

The first vertical slice may accidentally establish an API or UI commitment larger than intended, or may make mock output look clinically meaningful. Scope and labeling require explicit review.

## Documentation impact

Document the development-only workflow and its mock limitations without presenting it as a clinical capability.

## Completion evidence

Reserved for implementation, automated-test, manual-verification, review, and approval evidence.

## Review findings

Reserved for later independent review.

## Human approval

Required before specification is activated and before implementation begins.
