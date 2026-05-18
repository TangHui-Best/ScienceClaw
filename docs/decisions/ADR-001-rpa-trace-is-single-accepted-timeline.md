---
doc_kind: adr
id: ADR-001
title: RPA Trace Is The Single Accepted Timeline
status: accepted
feature_ids: [F001]
date: 2026-05-13
---

# ADR-001 RPA Trace Is The Single Accepted Timeline

## Context

RPA recording currently has multiple competing fact sources: `session.steps`, `session.recorded_actions`, `session.traces`, `recording_diagnostics`, generated `legacy_steps`, and step-index based APIs. This was useful while migrating from the old step/generator path, but it now conflicts with the accepted trace-first architecture.

The product is still in development-stage migration. Old sessions, old skill metadata, and old MCP preview payloads do not justify maintaining a permanent dual-source contract.

## Decision

`RPAAcceptedTrace` is the only accepted RPA timeline model. New RPA recording, configure, generate, test, save, and MCP/export paths must consume `session.traces`, `trace_diagnostics`, and `runtime_results`, not `session.steps`, `recorded_actions`, `recording_diagnostics`, or `legacy_steps`.

Step-like objects may exist only as private browser-event DTOs, test fixtures, or reference code during migration. They must not appear in new public API contracts, accepted timeline semantics, saved skill metadata, or main-path compiler/export inputs.

## Rejected Options

- Keep dual-source compatibility indefinitely. Rejected because it preserves the exact ambiguity this migration is meant to remove.
- Add Harness observability on top of the mixed state first. Rejected because it would observe and normalize a false architecture instead of fixing the source of truth.
- Remove every legacy class in one edit. Rejected because manual recording, test failure mapping, MCP/export, and compiler parity still need controlled, test-driven migration.

## Consequences

- Old development-stage sessions and old skill metadata may break or require one-time discard.
- Tests that currently assert `recorded_actions`, `legacy_steps`, `/step/{index}`, or `failed_step_index` must be rewritten to assert trace-only behavior.
- Final readiness requires exhaustive Evidence, including negative grep checks and manual smoke.
- Future RPA features must extend trace models or trace diagnostics rather than adding another accepted timeline source.

## Links

- Feature: `docs/features/F001-rpa-trace-source-convergence.md`
- Spec: `docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md`
