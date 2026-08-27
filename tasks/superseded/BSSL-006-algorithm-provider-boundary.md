---
id: BSSL-006
title: Define algorithm provider boundary
status: superseded
branch:
priority: high
depends_on: BSSL-005
required_skills: []
optional_tools: []
related_adrs: []
---

# BSSL-006 - Define algorithm provider boundary

> Superseded on 2026-08-26 by SLIA-006 and SLIA-008. The previous mock-provider
> direction conflicts with the approved rule that the demonstrator must not show
> simulated diagnostic results.

## Goal

Define a stable, testable boundary between the Slicer module and future SLIAFlow-related processing implementations.

## Context

The current module provides inspection tools only. Future processing must remain replaceable, testable, explicitly non-clinical, and unable to mutate or display unvalidated results.

## Requirements

- Define a provider protocol or interface with an explicit input model and result model.
- Provide a mock provider for boundary tests.
- Validate results before scene mutation, persistence, or successful display.
- Define error and cancellation behavior.
- Preserve explicit mock/demo labeling and the non-clinical boundary.

## Out of scope

- A real SLIAFlow algorithm or any unvalidated clinical algorithm implementation.
- Clinical validation, performance claims, or clinical reporting.
- Choosing implementation details that require a new architectural decision without recording it.

## Files allowed

Likely areas include a new provider contract/support package, tests, documentation, and possibly an ADR. Exact files and any ADR requirement must be approved during specification.

## Relevant skills and references

- Dependency: BSSL-005.
- `.ai/policies/algorithm-boundary-policy.md`
- `.ai/policies/medical-data-policy.md`
- Accepted ADRs and current module code, to be reviewed during specification.

## Implementation plan

To be defined during specification. The specification must determine whether this boundary requires an ADR before implementation.

## Acceptance criteria

- The provider contract makes inputs, outputs, validation, errors, cancellation, and labeling explicit.
- A mock provider demonstrates the contract without clinical processing.
- Invalid results cannot be treated as successful scene or display state.

## Test plan

To be defined during specification; it must cover valid, malformed, incomplete, mislabeled, failed, and cancelled provider outcomes.

## Manual verification

No clinical workflow is permitted. Verify the documented mock boundary in Slicer only after implementation is approved, including visible non-clinical labeling and failure behavior.

## Risks

An underspecified interface could leak Slicer/MRML details into processing or imply unsupported architectural commitments. Validation requirements must remain aligned with the accepted policy and any new ADR.

## Documentation impact

Record the approved contract and architectural ownership, including an ADR if specification determines one is required.

## Completion evidence

Reserved for implementation, automated-test, manual-verification, review, and approval evidence.

## Review findings

Reserved for later independent review.

## Human approval

Required before specification is activated and before implementation begins.
