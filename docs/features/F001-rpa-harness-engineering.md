---
id: F001
doc_kind: feature
status: active
created: 2026-05-11
updated: 2026-05-11
---

# F001: RPA Harness Engineering

## Goal

Build a real-flow RPA harness that turns production and development failures
into observable, reproducible, attributable, and regression-protected engineering
assets.

The feature protects the trace-first RPA direction by keeping the production
path focused on factual recording while moving heavy evaluation into offline
development, CI, and diagnosis flows.

## Current Status

Active implementation stage. The architecture guideline is written, and Batch 0
has established the first packet, redaction, artifact storage, retention, and
production-path isolation checks.

Current accepted direction:

- production emits facts only on failure or explicit diagnostic capture
- harness evaluation runs offline, in development, or in CI
- the first corpus must come from real RPA usage, not historical golden-eval
  flows that diverge from the current user path
- DOM morphology cases are first-class harness assets because snapshot
  compression quality is central to RPA usefulness

## Links

- Spec: [RPA Harness Engineering](../rpa/rpa-harness-engineering.md)
- Related architecture: [Trace-first Architecture](../rpa/trace-first-architecture.md)
- Related repair policy: [Failure Repair Policy](../rpa/failure-repair-policy.md)
- Related compiler strategy: [TraceSkillCompiler Generalization](../rpa/trace-skill-compiler-generalization.md)
- Design index: [Design Document Status](../DESIGN_STATUS.md)
- Batch 0 plan: [RPA Harness Batch 0 Implementation Plan](../rpa/rpa-harness-batch-0-implementation-plan.md)

## Acceptance Criteria

- `ObservationPacket` and `FailurePacket` schemas exist with redaction and
  retention rules.
- Real RPA failures can be captured as failure packets without unbounded endpoint
  disk growth.
- Failure packets require triage before promotion into harness cases.
- DOM morphology cases cover at least key/value, table, candidate list/card,
  form, and iframe structures.
- Snapshot harness can distinguish missing raw evidence from compact snapshot
  evidence loss.
- Compiler harness guards dataflow, observed-value de-hardcoding, runtime AI
  preservation, and URL base/suffix generalization.
- Repair harness verifies fact completeness and single-repair policy boundaries.
- Scenario harness contains a small set of real SOP smoke flows and does not
  replace layer-specific harness cases.
- Optional observability adapters remain outside harness core until license
  review is complete.

## Vision Gate

Outcome: pass

Original intent:

- Build a real-flow RPA harness to prevent "fix A, break B" regressions.
- Keep production lightweight: emit facts only, evaluate offline.
- Treat DOM morphology and snapshot compression as first-class harness assets.
- Do not reuse historical golden-eval flows as the baseline when they diverge
  from real user flow.

Alignment:

- The current spec defines failure packets, observation packets, DOM morphology
  corpus, snapshot diff, compiler, repair, and scenario harness layers.
- The design keeps trace-first recording intact and keeps heavy evaluation
  outside the production path.

Drift risks:

- Turning harness into a dashboard/platform before local domain cases are
  stable.
- Letting production diagnostics grow into an unbounded corpus.
- Promoting failure packets into cases without triage.
- Reintroducing site-specific rules or contract-first recording.

Required next action:

- Proceed to Batch 0 implementation planning.

## Evidence

- 2026-05-11: Created active design guideline at
  `docs/rpa/rpa-harness-engineering.md`.
- 2026-05-11: Registered the guideline in `docs/DESIGN_STATUS.md`.
- 2026-05-11: Recorded Entry Vision Gate in this Feature page.
- 2026-05-11: Created Batch 0 implementation plan at
  `docs/rpa/rpa-harness-batch-0-implementation-plan.md`.
- 2026-05-11: Confirmed Batch 0 coding should use
  `subagent-driven-development` with per-task implementer and review gates.
- 2026-05-11: Batch 0 implemented packet schemas, redaction, local artifact
  write/read, retention pruning, path containment checks, and production-path
  isolation checks.
- 2026-05-11: Verified with
  `$env:PYTHONPATH="RpaClaw"; pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_harness_packets.py -q --basetemp .pytest-tmp`.

## Next Step

Proceed to Batch 1 only after at least one real RPA failure packet shape is
reviewed for redaction quality and storage cost. Do not auto-promote captured
packets into harness cases.
