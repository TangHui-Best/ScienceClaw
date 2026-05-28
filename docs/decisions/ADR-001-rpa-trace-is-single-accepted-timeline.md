---
id: ADR-001
doc_kind: adr
status: accepted
scope: project
feature_ids: [F001]
feature_refs:
  - docs/features/F001-rpa-trace-source-convergence.md
decision_area: rpa-trace-timeline
created: 2026-05-13
updated: 2026-05-18
---

# ADR-001: RPA Trace Is The Single Accepted Timeline

## Context

RPA recording had multiple competing fact sources: `session.steps`, `session.recorded_actions`, `session.traces`, `recording_diagnostics`, generated `legacy_steps`, and step-index APIs. That mixed state was useful during migration from the old step/generator path, but it conflicts with the accepted trace-first architecture and makes generate/test/save/MCP/export hard to verify.

## Decision

`RPAAcceptedTrace` is the only accepted RPA timeline model. New RPA recording, configure, generate, test, save, and MCP/export paths must consume `session.traces`, `trace_diagnostics`, and `runtime_results`, not `session.steps`, `recorded_actions`, `recording_diagnostics`, or `legacy_steps`.

Step-like objects may exist only as private browser-event DTOs, test fixtures, or reference code during migration. They must not appear in new public API contracts, accepted timeline semantics, saved skill metadata, or main-path compiler/export inputs.

## Alternatives

- Keep dual-source compatibility indefinitely. Rejected because it preserves the ambiguity this migration is meant to remove.
- Add Harness observability on top of the mixed state first. Rejected because it would observe and normalize a false architecture instead of fixing the source of truth.
- Remove every legacy class in one edit. Rejected because manual recording, test failure mapping, MCP/export, and compiler parity still need controlled, test-driven migration.

## Consequences

- Old development-stage sessions and old skill metadata may break or require one-time discard.
- Tests that currently assert `recorded_actions`, `legacy_steps`, `/step/{index}`, or `failed_step_index` must be rewritten to assert trace-only behavior.
- Final readiness requires exhaustive Evidence, including negative grep checks and manual smoke.
- Future RPA features must extend trace models or trace diagnostics instead of adding another accepted timeline source.

## Evidence

- Feature: [F001 RPA Trace Source Convergence](../features/F001-rpa-trace-source-convergence.md)
- Evidence: [EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md)
- Spec: [2026-04-28 RPA Trace-first Full Migration Design](../superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md)
- Plan: [2026-04-28 RPA Trace-first Full Migration](../superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md)
